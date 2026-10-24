// Package game implements game logic on top of the engine - the Go
// equivalent of games/gridlines/gamestate.py, game_override.py,
// game_executables.py, game_calculations.py and game_events.py.
//
// Grid-line pays on a collapse grid: every straight run of min_run or more
// like symbols in a row or column pays, the run is removed leaving a wild in
// its centre and the rest falls down (no refill). In a paid spin the win
// multiplier climbs a ladder; in a bonus game every row and column has its own
// multiplier instead. Three bonus games, chosen by the number of scatters:
// refine (symbol upgrades), surge (wild drops) and fusion (both).
//
// Every RNG call happens in the order of the Python code. See README.md
// ("Determinism rules") before changing anything here.
package game

import (
	"encoding/json"
	"fmt"
	"sort"
	"sync"

	"github.com/stakeengine/go-engine/engine"
)

const (
	wildKey    = "wild"
	scatterKey = "scatter"
	blankKey   = "blank"
	wildSym    = "W"
)

// scatterBonus is one (scatters -> bonus game) entry of config.bonus_by_scatters.
type scatterBonus struct {
	Scatters int    `json:"scatters"`
	Bonus    string `json:"bonus"`
}

// gridConfig mirrors the game-specific attributes of games/gridlines/game_config.py
// (exported under spec["game"] by export_spec.py).
type gridConfig struct {
	MinRun              int                             `json:"min_run"`
	CentreWild          bool                            `json:"centre_wild"`
	MultStepPerRun      int                             `json:"mult_step_per_run"`
	MultLadder          []int64                         `json:"mult_ladder"`
	BonusByScatters     []scatterBonus                  `json:"bonus_by_scatters"`
	BonusAwards         map[string]int64                `json:"bonus_awards"`
	LineMultStepPerRun  int                             `json:"line_mult_step_per_run"`
	LineMultLadder      []int64                         `json:"line_mult_ladder"`
	BonusLineMultLadder map[string][]int64              `json:"bonus_line_mult_ladder"`
	BonusUpgrades       []string                        `json:"bonus_upgrades"`
	RefineOrder         []string                        `json:"refine_order"`
	RefineInto          map[string]string               `json:"refine_into"`
	BonusWildDrop       map[string][]engine.WeightedInt `json:"bonus_wild_drop"`
	BlankSymbol         string                          `json:"blank_symbol"`

	gridLines []gridLine // every row and column of the board (fixed shape)
}

// gridConditions holds the condition tables of one criteria that the engine
// does not know about. A nil table means the key is absent in Python.
type gridConditions struct {
	BonusReels       map[string][]engine.WeightedStr `json:"bonus_reels"`
	WildDrop         []engine.WeightedInt            `json:"wild_drop"`
	RefineLevel      []engine.WeightedInt            `json:"refine_level"`       // {level: weight}
	RefineLevelFixed int                             `json:"refine_level_fixed"` // plain int level
}

// runWin is one priced run ("wins" entry of win_data).
type runWin struct {
	Symbol         string
	Kind           int
	Win            float64
	Positions      []engine.Pos
	Direction      string
	LineIndex      int
	Multiplier     int64 // GlobalMult * LineMult
	GlobalMult     int64
	LineMult       int64
	WinWithoutMult float64
	Overlay        engine.Pos
}

// spawnedSym is one wild created in an exploding position by a collapse.
type spawnedSym struct {
	Reel, Row, LandingRow int
}

// gridState is the per-worker game state (attributes the Python GameState
// adds on top of the SDK state).
type gridState struct {
	cfg   *gridConfig
	conds map[*engine.Distribution]*gridConditions

	bonusType   string // "" == None
	multStep    int
	refineLevel int

	// Line multipliers (bonus games): ladder step and value of every row and column.
	rowSteps, colSteps []int
	rowMults, colMults []int64

	wins     []runWin
	totalWin float64
	exploded []engine.Pos
	spawned  []spawnedSym
}

var configCache sync.Map // *engine.Spec -> *gridConfig

func loadConfig(spec *engine.Spec) *gridConfig {
	if cfg, ok := configCache.Load(spec); ok {
		return cfg.(*gridConfig)
	}
	cfg := &gridConfig{}
	if err := json.Unmarshal(spec.Game, cfg); err != nil {
		panic("gridlines: bad game config in spec: " + err.Error())
	}
	cfg.gridLines = getGridLines(spec.NumRows)
	actual, _ := configCache.LoadOrStore(spec, cfg)
	return actual.(*gridConfig)
}

func grid(s *engine.State) *gridState { return s.GameData.(*gridState) }

// Attach wires the grid-line game logic into a State.
func Attach(s *engine.State) {
	g := &gridState{cfg: loadConfig(s.Spec), conds: map[*engine.Distribution]*gridConditions{}}
	for i := range s.Mode.Distributions {
		d := &s.Mode.Distributions[i]
		c := &gridConditions{}
		if err := json.Unmarshal(d.Conditions.Raw, c); err != nil {
			panic("gridlines: bad conditions for criteria " + d.Criteria + ": " + err.Error())
		}
		g.conds[d] = c
	}
	s.GameData = g
	s.SpecialSymbolFunctions = map[string][]func(*engine.State, *engine.Symbol){}
	s.SymbolNameFn = func(s *engine.State, name string) string { return grid(s).applyRefine(name) }
}

func (g *gridState) conditions(s *engine.State) *gridConditions { return g.conds[s.Dist] }

// Describe returns a short console description.
func Describe() string {
	return "gridlines (5x5 grid-line pays, collapse, refine/surge/fusion bonus games)"
}

// --------------------------------------------------------------------------
// gamestate.py
// --------------------------------------------------------------------------

// RunSpin mirrors GameState.run_spin.
func RunSpin(s *engine.State, sim int) {
	g := grid(s)
	s.ResetSeed(sim)
	s.Repeat = true
	for s.Repeat {
		g.resetBook(s)
		g.drawSpinBoard(s)

		g.playCollapseSequence(s)

		setEndTumbleEvent(s)
		s.WinManager.UpdateGametypeWins(s.Gametype)

		if s.CheckFsCondition() && s.CheckFreespinEntry() {
			g.runFreespinFromBase(s)
		}

		s.EvaluateFinalWin()
		g.checkRepeat(s)
	}
}

// runFreespin mirrors GameState.run_freespin: a fixed number of free spins on
// line multipliers, plus what the bonus adds (wild drops, symbol upgrades).
func (g *gridState) runFreespin(s *engine.State) {
	g.resetFsSpin(s)
	upgrades := contains(g.cfg.BonusUpgrades, g.bonusType)
	for s.FS < s.TotFS && !s.WincapTriggered {
		g.updateFreespin(s)
		g.drawBonusBoard(s)

		g.playCollapseSequence(s)

		setEndTumbleEvent(s)
		s.WinManager.UpdateGametypeWins(s.Gametype)

		// Every winning spin upgrades the lowest symbol left.
		if upgrades && s.WinManager.SpinWin > 0 && g.refineLevel < len(g.cfg.RefineOrder) {
			removed := g.cfg.RefineOrder[g.refineLevel]
			g.refineLevel++
			g.refineSymbolEvent(s, removed, g.cfg.RefineInto[removed])
		}
	}
	s.EndFreespin()
}

// --------------------------------------------------------------------------
// game_override.py
// --------------------------------------------------------------------------

// resetBook mirrors GameStateOverride.reset_book.
func (g *gridState) resetBook(s *engine.State) {
	s.ResetBook()
	g.clearWinData()
	g.bonusType = ""
	g.multStep = 0
	g.resetLineMultipliers(s)
	// Prime spin starts with a random number of symbols already upgraded.
	c := g.conditions(s)
	if c.RefineLevel != nil {
		g.refineLevel = int(engine.GetRandomOutcomeInt(s.Rng, c.RefineLevel))
	} else {
		g.refineLevel = c.RefineLevelFixed
	}
}

// resetFsSpin mirrors GameStateOverride.reset_fs_spin.
func (g *gridState) resetFsSpin(s *engine.State) {
	s.ResetFsSpin()
	g.refineLevel = 0
	g.resetMultiplier(s)
	g.resetLineMultipliers(s)
	g.updateLineMultEvent(s)
}

// checkRepeat mirrors GameStateOverride.check_repeat (and the SDK check_repeat).
func (g *gridState) checkRepeat(s *engine.State) {
	winCriteria := s.Dist.WinCriteria
	if !s.Repeat {
		if winCriteria != nil && s.FinalWin != *winCriteria {
			s.Repeat = true
		}
		if s.GetConditions().ForceFreegame && !s.TriggeredFreegame {
			s.Repeat = true
		}
	}
	s.RepeatCount++
	if !s.Repeat && winCriteria == nil && s.FinalWin == 0 {
		s.Repeat = true
	}
}

// --------------------------------------------------------------------------
// game_calculations.py
// --------------------------------------------------------------------------

// applyRefine mirrors GameCalculations.apply_refine: the symbol `name` lands
// as at the current refine level (upgrades chain: L5 -> L4 -> L3).
func (g *gridState) applyRefine(name string) string {
	level := g.refineLevel
	if level <= 0 {
		return name
	}
	if level > len(g.cfg.RefineOrder) {
		level = len(g.cfg.RefineOrder)
	}
	removed := g.cfg.RefineOrder[:level]
	for contains(removed, name) {
		name = g.cfg.RefineInto[name]
	}
	return name
}

// pickWildDropPositions mirrors pick_wild_drop_positions: `count` random
// positions holding a regular symbol.
func (g *gridState) pickWildDropPositions(s *engine.State, count int) []engine.Pos {
	var candidates []engine.Pos
	for reel := range s.Board {
		for row, sym := range s.Board[reel] {
			if !(sym.CheckAttribute(wildKey) || sym.CheckAttribute(scatterKey) || sym.CheckAttribute(blankKey)) {
				candidates = append(candidates, engine.Pos{Reel: reel, Row: row})
			}
		}
	}
	return samplePositions(s, candidates, count)
}

// samplePositions mirrors sorted(random.sample(population, min(count, len))).
func samplePositions(s *engine.State, population []engine.Pos, count int) []engine.Pos {
	if count > len(population) {
		count = len(population)
	}
	chosen := make([]engine.Pos, 0, count)
	for _, idx := range s.Rng.Sample(len(population), count) {
		chosen = append(chosen, population[idx])
	}
	sortPositions(chosen)
	return chosen
}

// --------------------------------------------------------------------------
// game_executables.py
// --------------------------------------------------------------------------

// drawBoard mirrors Board.draw_board(emit_event=False, trigger_symbol="scatter").
func drawBoard(s *engine.State) {
	conds := s.GetConditions()
	isBase := s.Gametype == s.Spec.BasegameType
	switch {
	case conds.ForceFreegame && isBase:
		s.ForceSpecialBoard(scatterKey, int(engine.GetRandomOutcomeInt(s.Rng, conds.ScatterTriggers)))
	case !conds.ForceFreegame && isBase:
		if conds.ScatterTriggers != nil {
			s.ForceSpecialBoard(scatterKey, int(engine.GetRandomOutcomeInt(s.Rng, conds.ScatterTriggers)))
		} else {
			s.CreateBoardReelstrips()
			for s.CountSpecialSymbols(scatterKey) >= s.Spec.MinFreespinTrigger(s.Gametype) {
				s.CreateBoardReelstrips()
			}
		}
	default:
		s.CreateBoardReelstrips()
	}
}

// drawSpinBoard mirrors draw_spin_board.
func (g *gridState) drawSpinBoard(s *engine.State) {
	drawBoard(s)
	if g.refineLevel > 0 {
		g.primeSymbolsEvent(s)
	}
	engine.RevealEvent(s)
	if wildDrop := g.conditions(s).WildDrop; wildDrop != nil {
		g.dropWilds(s, int(engine.GetRandomOutcomeInt(s.Rng, wildDrop)))
	}
}

// drawBonusBoard mirrors draw_bonus_board.
func (g *gridState) drawBonusBoard(s *engine.State) {
	reelWeights, ok := g.conditions(s).BonusReels[g.bonusType]
	if !ok {
		panic(fmt.Sprintf("criteria %s has no bonus_reels for %q", s.Criteria, g.bonusType))
	}
	s.ForceBoardFromReelstrips(engine.GetRandomOutcomeStr(s.Rng, reelWeights), nil)
	engine.RevealEvent(s)
	if wildDrop, ok := g.cfg.BonusWildDrop[g.bonusType]; ok {
		g.dropWilds(s, int(engine.GetRandomOutcomeInt(s.Rng, wildDrop)))
	}
}

// dropWilds mirrors drop_wilds: turn `count` random regular symbols into wilds.
func (g *gridState) dropWilds(s *engine.State, count int) {
	positions := g.pickWildDropPositions(s, count)
	for _, p := range positions {
		s.Board[p.Reel][p.Row] = s.CreateSymbol(wildSym)
	}
	s.GetSpecialSymbolsOnBoard()
	if len(positions) > 0 {
		wildDropEvent(s, positions)
	}
}

// evaluateGridlines mirrors evaluate_gridlines.
func (g *gridState) evaluateGridlines(s *engine.State) {
	g.evaluateRuns(s, findRuns(s.Board, g.cfg.gridLines, g.cfg.MinRun))
	for _, w := range g.wins {
		s.Record([]engine.ForcePair{
			{K: "kind", V: fmt.Sprint(w.Kind)},
			{K: "symbol", V: w.Symbol},
			{K: "gametype", V: s.Gametype},
		})
	}
	s.WinManager.UpdateSpinWin(g.totalWin)
	s.WinManager.TumbleWin = g.totalWin
}

// emitCollapseWinEvents mirrors emit_collapse_win_events.
func (g *gridState) emitCollapseWinEvents(s *engine.State) {
	if g.totalWin > 0 {
		g.winInfoEvent(s)
		updateTumbleWinEvent(s)
		s.EvaluateWincap()
	}
}

// collapseGameBoard mirrors collapse_game_board.
func (g *gridState) collapseGameBoard(s *engine.State) {
	spawn := map[engine.Pos]string{}
	if g.cfg.CentreWild {
		for _, w := range g.wins {
			spawn[w.Overlay] = wildSym
		}
	}
	g.collapseBoard(s, spawn)
	g.collapseBoardEvent(s)
}

// stepMultiplier mirrors step_multiplier: one step per winning run, on the
// spin's ladder in a paid spin and on the run's own line in a bonus.
func (g *gridState) stepMultiplier(s *engine.State) {
	if g.bonusType == "" {
		g.setMultStep(s, g.multStep+g.cfg.MultStepPerRun*len(g.wins))
	} else {
		g.stepLineMultipliers(s)
	}
}

// stepLineMultipliers mirrors step_line_multipliers.
func (g *gridState) stepLineMultipliers(s *engine.State) {
	ladder, ok := g.cfg.BonusLineMultLadder[g.bonusType]
	if !ok {
		ladder = g.cfg.LineMultLadder
	}
	changed := false
	for _, w := range g.wins {
		steps, mults := g.rowSteps, g.rowMults
		if w.Direction == "column" {
			steps, mults = g.colSteps, g.colMults
		}
		steps[w.LineIndex] += g.cfg.LineMultStepPerRun
		idx := steps[w.LineIndex]
		if idx > len(ladder)-1 {
			idx = len(ladder) - 1
		}
		if mults[w.LineIndex] != ladder[idx] {
			mults[w.LineIndex] = ladder[idx]
			changed = true
		}
	}
	if changed {
		g.updateLineMultEvent(s)
	}
}

// resetLineMultipliers mirrors reset_line_multipliers: every line back to 1x.
func (g *gridState) resetLineMultipliers(s *engine.State) {
	rows := 0
	for _, n := range s.Spec.NumRows {
		if n > rows {
			rows = n
		}
	}
	g.rowSteps, g.colSteps = make([]int, rows), make([]int, s.Spec.NumReels)
	g.rowMults, g.colMults = make([]int64, rows), make([]int64, s.Spec.NumReels)
	for i := range g.rowMults {
		g.rowMults[i] = 1
	}
	for i := range g.colMults {
		g.colMults[i] = 1
	}
}

// setMultStep mirrors set_mult_step (the paid-spin ladder).
func (g *gridState) setMultStep(s *engine.State, step int) {
	ladder := g.cfg.MultLadder
	g.multStep = step
	idx := step
	if idx > len(ladder)-1 {
		idx = len(ladder) - 1
	}
	if value := ladder[idx]; s.GlobalMultiplier != value {
		s.GlobalMultiplier = value
		engine.UpdateGlobalMultEvent(s)
	}
}

// resetMultiplier mirrors reset_multiplier.
func (g *gridState) resetMultiplier(s *engine.State) { g.setMultStep(s, 0) }

// playCollapseSequence mirrors play_collapse_sequence.
func (g *gridState) playCollapseSequence(s *engine.State) {
	g.evaluateGridlines(s)
	g.emitCollapseWinEvents(s)
	for g.totalWin > 0 && !s.WincapTriggered {
		g.collapseGameBoard(s)
		g.stepMultiplier(s)
		g.evaluateGridlines(s)
		g.emitCollapseWinEvents(s)
	}
}

// runFreespinFromBase mirrors run_freespin_from_base.
func (g *gridState) runFreespinFromBase(s *engine.State) {
	count := s.CountSpecialSymbols(scatterKey)
	g.bonusType = ""
	for _, b := range g.cfg.BonusByScatters {
		if b.Scatters == count {
			g.bonusType = b.Bonus
		}
	}
	if g.bonusType == "" {
		panic(fmt.Sprintf("no bonus game for %d scatters", count))
	}
	s.Record([]engine.ForcePair{
		{K: "kind", V: fmt.Sprint(count)},
		{K: "symbol", V: scatterKey},
		{K: "gametype", V: s.Gametype},
		{K: "bonus", V: g.bonusType},
	})
	g.updateFreespinAmount(s)
	g.runFreespin(s)
}

// updateFreespinAmount mirrors update_freespin_amount.
func (g *gridState) updateFreespinAmount(s *engine.State) {
	award, found := g.cfg.BonusAwards[g.bonusType]
	if !found {
		panic("no bonus award for " + g.bonusType)
	}
	s.TotFS = award
	g.bonusTriggerEvent(s)
}

// updateFreespin mirrors Executables.update_freespin (event BEFORE the counter).
func (g *gridState) updateFreespin(s *engine.State) {
	s.UpdateFreespin()
	g.clearWinData()
}

func (g *gridState) clearWinData() {
	g.wins = nil
	g.totalWin = 0
}

// setEndTumbleEvent mirrors Tumble.set_end_tumble_event.
func setEndTumbleEvent(s *engine.State) {
	if s.WinManager.SpinWin > 0 {
		engine.SetWinEvent(s)
	}
	engine.SetTotalEvent(s)
}

// --------------------------------------------------------------------------
// src/calculations/gridlines.py
// --------------------------------------------------------------------------

const (
	kindBlock = iota
	kindWild
	kindPay
)

type gridLine struct {
	direction string
	index     int
	positions []engine.Pos
}

type run struct {
	symbol    string
	kind      int
	positions []engine.Pos
	direction string
	index     int
}

// getGridLines mirrors GridLines.get_grid_lines: rows left to right (split
// where a reel is too short), then columns top to bottom.
func getGridLines(numRows []int) []gridLine {
	var lines []gridLine
	maxRows := 0
	for _, n := range numRows {
		if n > maxRows {
			maxRows = n
		}
	}
	for row := 0; row < maxRows; row++ {
		var segment []engine.Pos
		for reel, n := range numRows {
			if row < n {
				segment = append(segment, engine.Pos{Reel: reel, Row: row})
			} else if len(segment) > 0 {
				lines = append(lines, gridLine{"row", row, segment})
				segment = nil
			}
		}
		if len(segment) > 0 {
			lines = append(lines, gridLine{"row", row, segment})
		}
	}
	for reel, n := range numRows {
		col := make([]engine.Pos, n)
		for row := range col {
			col[row] = engine.Pos{Reel: reel, Row: row}
		}
		lines = append(lines, gridLine{"column", reel, col})
	}
	return lines
}

// classifySymbol mirrors GridLines.classify_symbol.
func classifySymbol(sym *engine.Symbol) int {
	if sym.CheckAttribute(wildKey) {
		return kindWild
	}
	if sym.Def.IsPaying && !sym.Def.Special {
		return kindPay
	}
	return kindBlock
}

// findRuns mirrors GridLines.find_runs.
func findRuns(board [][]*engine.Symbol, lines []gridLine, minRun int) []run {
	var runs []run
	for _, line := range lines {
		positions := line.positions
		length := len(positions)
		if length < minRun {
			continue
		}
		syms := make([]*engine.Symbol, length)
		kinds := make([]int, length)
		var orderedNames []string
		for i, p := range positions {
			syms[i] = board[p.Reel][p.Row]
			kinds[i] = classifySymbol(syms[i])
			if kinds[i] == kindPay && !contains(orderedNames, syms[i].Name()) {
				orderedNames = append(orderedNames, syms[i].Name())
			}
		}

		covered := make([]bool, length)
		for _, name := range orderedNames {
			matches := func(i int) bool {
				return kinds[i] == kindWild || (kinds[i] == kindPay && syms[i].Name() == name)
			}
			start := 0
			for start < length {
				if !matches(start) {
					start++
					continue
				}
				end, hasSymbol := start, false
				for end < length && matches(end) {
					if kinds[end] == kindPay {
						hasSymbol = true
					}
					end++
				}
				if hasSymbol && end-start >= minRun {
					runs = append(runs, run{name, end - start, clonePositions(positions[start:end]), line.direction, line.index})
					for i := start; i < end; i++ {
						covered[i] = true
					}
				}
				start = end
			}
		}

		// Runs of wilds only: paid when no regular symbol run already uses them.
		start := 0
		for start < length {
			if kinds[start] != kindWild {
				start++
				continue
			}
			end := start
			for end < length && kinds[end] == kindWild {
				end++
			}
			if end-start >= minRun && !anyTrue(covered[start:end]) {
				runs = append(runs, run{wildSym, end - start, clonePositions(positions[start:end]), line.direction, line.index})
			}
			start = end
		}
	}
	return runs
}

// evaluateRuns mirrors GridLines.evaluate_runs (mark_explode=True); in a
// bonus a run is also multiplied by the multiplier of its row or column.
func (g *gridState) evaluateRuns(s *engine.State, runs []run) {
	g.wins = nil
	total := 0.0
	for _, r := range runs {
		baseWin, ok := s.Spec.Pay(r.kind, r.symbol)
		if !ok {
			continue
		}
		lineMult := int64(1)
		if g.bonusType != "" {
			if r.direction == "column" {
				lineMult = g.colMults[r.index]
			} else {
				lineMult = g.rowMults[r.index]
			}
		}
		multiplier := s.GlobalMultiplier * lineMult
		win := engine.PyRound2(baseWin * float64(multiplier))
		g.wins = append(g.wins, runWin{
			Symbol:         r.symbol,
			Kind:           r.kind,
			Win:            win,
			Positions:      r.positions,
			Direction:      r.direction,
			LineIndex:      r.index,
			Multiplier:     multiplier,
			GlobalMult:     s.GlobalMultiplier,
			LineMult:       lineMult,
			WinWithoutMult: baseWin,
			Overlay:        r.positions[(len(r.positions)-1)/2],
		})
		total += win
		for _, p := range r.positions {
			s.Board[p.Reel][p.Row].Explode = true
		}
	}
	g.totalWin = engine.PyRound2(total)
}

// --------------------------------------------------------------------------
// src/calculations/collapse.py
// --------------------------------------------------------------------------

// collapseBoard mirrors Collapse.collapse_board: remove exploding symbols,
// spawn replacements, let everything fall; empty cells hold the blank symbol.
func (g *gridState) collapseBoard(s *engine.State, spawn map[engine.Pos]string) {
	g.exploded = nil
	g.spawned = nil
	newBoard := make([][]*engine.Symbol, len(s.Board))
	for reel := range s.Board {
		var survivors []*engine.Symbol
		var spawnedIdx, spawnedRow []int
		for row, sym := range s.Board[reel] {
			if sym.Explode {
				g.exploded = append(g.exploded, engine.Pos{Reel: reel, Row: row})
			}
			if name, ok := spawn[engine.Pos{Reel: reel, Row: row}]; ok {
				survivors = append(survivors, s.CreateSymbol(name))
				spawnedIdx = append(spawnedIdx, len(survivors)-1)
				spawnedRow = append(spawnedRow, row)
			} else if !sym.Explode && !sym.CheckAttribute(blankKey) {
				survivors = append(survivors, sym)
			}
		}
		empty := len(s.Board[reel]) - len(survivors)
		col := make([]*engine.Symbol, 0, len(s.Board[reel]))
		for i := 0; i < empty; i++ {
			col = append(col, s.CreateSymbol(g.cfg.BlankSymbol))
		}
		newBoard[reel] = append(col, survivors...)
		for i := range spawnedIdx {
			g.spawned = append(g.spawned, spawnedSym{Reel: reel, Row: spawnedRow[i], LandingRow: empty + spawnedIdx[i]})
		}
	}
	s.Board = newBoard
	s.GetSpecialSymbolsOnBoard()
}

// --------------------------------------------------------------------------
// Events (game_events.py + the SDK events this game calls directly)
// --------------------------------------------------------------------------

// rowOffset mirrors ROW_OFFSET in game_events.py and the SDK events' default
// include_padding_index: event row = board row + 1.
const rowOffset = 1

// posObj renders a board position the way events send it.
func posObj(p engine.Pos) engine.Obj {
	return engine.Obj{{K: "reel", V: p.Reel}, {K: "row", V: p.Row + rowOffset}}
}

func posArr(positions []engine.Pos) engine.Arr {
	arr := make(engine.Arr, 0, len(positions))
	for _, p := range positions {
		arr = append(arr, posObj(p))
	}
	return arr
}

func strArr(values []string) engine.Arr {
	arr := make(engine.Arr, 0, len(values))
	for _, v := range values {
		arr = append(arr, v)
	}
	return arr
}

// wildDropEvent mirrors wild_drop_event.
func wildDropEvent(s *engine.State, positions []engine.Pos) {
	s.Book.AddEvent(engine.Obj{
		{K: "index", V: len(s.Book.Events)},
		{K: "type", V: "wildDrop"},
		{K: "positions", V: posArr(positions)},
	})
}

// collapseBoardEvent mirrors collapse_board_event.
func (g *gridState) collapseBoardEvent(s *engine.State) {
	newWilds := make(engine.Arr, 0, len(g.spawned))
	for _, sp := range g.spawned {
		newWilds = append(newWilds, engine.Obj{
			{K: "reel", V: sp.Reel},
			{K: "row", V: sp.Row + rowOffset},
			{K: "landingRow", V: sp.LandingRow + rowOffset},
		})
	}
	s.Book.AddEvent(engine.Obj{
		{K: "index", V: len(s.Book.Events)},
		{K: "type", V: "collapseBoard"},
		{K: "explodingSymbols", V: posArr(g.exploded)},
		{K: "newWilds", V: newWilds},
	})
}

// bonusTriggerEvent mirrors bonus_trigger_event (sent as freeSpinTrigger).
func (g *gridState) bonusTriggerEvent(s *engine.State) {
	s.Book.AddEvent(engine.Obj{
		{K: "index", V: len(s.Book.Events)},
		{K: "type", V: engine.EventFreespinTrigger},
		{K: "totalFs", V: s.TotFS},
		{K: "positions", V: posArr(s.SpecialSymsOnBoard[scatterKey])},
		{K: "bonusType", V: g.bonusType},
	})
}

// primeSymbolsEvent mirrors prime_symbols_event (only sent when level > 0).
func (g *gridState) primeSymbolsEvent(s *engine.State) {
	level := g.refineLevel
	if level > len(g.cfg.RefineOrder) {
		level = len(g.cfg.RefineOrder)
	}
	removed := g.cfg.RefineOrder[:level]
	var landAs any
	if len(removed) > 0 {
		landAs = g.applyRefine(removed[len(removed)-1])
	}
	s.Book.AddEvent(engine.Obj{
		{K: "index", V: len(s.Book.Events)},
		{K: "type", V: "primeSymbols"},
		{K: "level", V: g.refineLevel},
		{K: "removedSymbols", V: strArr(removed)},
		{K: "landAs", V: landAs},
	})
}

// refineSymbolEvent mirrors refine_symbol_event.
func (g *gridState) refineSymbolEvent(s *engine.State, removed, into string) {
	s.Book.AddEvent(engine.Obj{
		{K: "index", V: len(s.Book.Events)},
		{K: "type", V: "refineSymbol"},
		{K: "level", V: g.refineLevel},
		{K: "removed", V: removed},
		{K: "into", V: into},
		{K: "removedSymbols", V: strArr(g.cfg.RefineOrder[:g.refineLevel])},
	})
}

// updateLineMultEvent mirrors update_line_mult_event.
func (g *gridState) updateLineMultEvent(s *engine.State) {
	s.Book.AddEvent(engine.Obj{
		{K: "index", V: len(s.Book.Events)},
		{K: "type", V: "updateLineMult"},
		{K: "rows", V: append([]int64(nil), g.rowMults...)},
		{K: "columns", V: append([]int64(nil), g.colMults...)},
	})
}

// winInfoEvent mirrors win_info_event (default include_padding_index=True).
func (g *gridState) winInfoEvent(s *engine.State) {
	wins := make(engine.Arr, 0, len(g.wins))
	for _, w := range g.wins {
		wins = append(wins, engine.Obj{
			{K: "symbol", V: w.Symbol},
			{K: "kind", V: w.Kind},
			{K: "win", V: engine.PyRound0Int(engine.MinF(w.Win, s.Wincap) * 100)},
			{K: "positions", V: posArr(w.Positions)},
			{K: "meta", V: engine.Obj{
				{K: "lineIndex", V: w.LineIndex},
				{K: "multiplier", V: w.Multiplier},
				{K: "winWithoutMult", V: engine.PyTruncInt(engine.MinF(w.WinWithoutMult*100, s.Wincap*100))},
				{K: "globalMult", V: w.GlobalMult},
				{K: "lineMultiplier", V: w.LineMult},
				{K: "direction", V: w.Direction},
				{K: "overlay", V: posObj(w.Overlay)},
			}},
		})
	}
	s.Book.AddEvent(engine.Obj{
		{K: "index", V: len(s.Book.Events)},
		{K: "type", V: engine.EventWinData},
		{K: "totalWin", V: engine.PyRound0Int(engine.MinF(g.totalWin, s.Wincap) * 100)},
		{K: "wins", V: wins},
	})
}

// updateTumbleWinEvent mirrors update_tumble_win_event.
func updateTumbleWinEvent(s *engine.State) {
	s.Book.AddEvent(engine.Obj{
		{K: "index", V: len(s.Book.Events)},
		{K: "type", V: "updateTumbleWin"},
		{K: "amount", V: engine.PyRound0Int(engine.MinF(s.WinManager.SpinWin, s.Wincap) * 100)},
	})
}

// --------------------------------------------------------------------------
// helpers
// --------------------------------------------------------------------------

func contains(list []string, v string) bool {
	for _, x := range list {
		if x == v {
			return true
		}
	}
	return false
}

func anyTrue(flags []bool) bool {
	for _, f := range flags {
		if f {
			return true
		}
	}
	return false
}

func clonePositions(positions []engine.Pos) []engine.Pos {
	return append([]engine.Pos(nil), positions...)
}

func sortPositions(positions []engine.Pos) {
	sort.Slice(positions, func(i, j int) bool {
		if positions[i].Reel != positions[j].Reel {
			return positions[i].Reel < positions[j].Reel
		}
		return positions[i].Row < positions[j].Row
	})
}
