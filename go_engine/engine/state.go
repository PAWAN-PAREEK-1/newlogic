package engine

// state.go - mirror of src/state/state.py + src/executables/executables.py +
// src/state/state_conditions.py: the per-round simulation state machine.
//
// One State instance simulates ONE betting round ("book"). The runner creates
// a fresh State per simulation with an RNG seeded `sim + 1`, exactly like the
// Python engine, so every book is a pure function of its simulation number.

import (
	"fmt"
	"sort"

	"github.com/stakeengine/go-engine/pyrand"
)

// Pos is a board coordinate ({"reel": r, "row": w} in Python).
type Pos struct {
	Reel int
	Row  int
}

// ForcePair is one key/value of a force-record description.
type ForcePair struct {
	K, V string
}

// ForceRecord mirrors one state.record(...) call: the description plus the
// book id it was recorded against.
type ForceRecord struct {
	Pairs  []ForcePair
	BookID int
}

// LineWin is one winning line ("wins" entry of win_data).
type LineWin struct {
	Symbol         string
	Kind           int
	Win            float64
	Positions      []Pos
	LineIndex      int64
	Multiplier     int64
	WinWithoutMult float64
	GlobalMult     int64
	LineMultiplier int64
}

// PrizeWin is one prize-symbol win (superspin mode).
type PrizeWin struct {
	Reel  int
	Row   int
	Value int64
}

// WinData mirrors gamestate.win_data.
type WinData struct {
	TotalWin  float64
	Wins      []LineWin
	PrizeWins []PrizeWin
}

// WildInfo tracks an expanding wild (expwilds game).
type WildInfo struct {
	Reel int
	Row  int
	Mult int64
}

// StickyInfo tracks a sticky prize symbol (superspin mode).
type StickyInfo struct {
	Reel  int
	Row   int
	Prize int64
}

// State is the Go equivalent of the Python GameState object graph.
type State struct {
	Spec     *Spec
	Mode     *BetMode
	ModeName string
	Wincap   float64 // mode-level max win (create_books overrides config.wincap per mode)
	Rng      *pyrand.Rand

	WinManager *WinManager

	Sim      int
	Criteria string
	Dist     *Distribution

	Book             *Book
	Board            [][]*Symbol
	TopSymbols       []*Symbol
	BottomSymbols    []*Symbol
	ReelstripID      string
	Reelstrip        [][]string
	ReelPositions    []int
	PaddingPositions []int
	Anticipation     []int

	SpecialSymsOnBoard map[string][]Pos

	GlobalMultiplier  int64
	FinalWin          float64
	TotFS             int64
	FS                int64
	WincapTriggered   bool
	TriggeredFreegame bool
	Gametype          string
	Repeat            bool
	RepeatCount       int

	WinData  WinData
	TempWins []ForceRecord

	// Hooks wired by the game package (mirror of the Python subclassing).
	SpecialSymbolFunctions map[string][]func(*State, *Symbol)
	RunFreespinFn          func(*State)
	DrawBoardFn            func(s *State, emitEvent bool, triggerSymbol string)
	CheckRepeatFn          func(*State)

	// When set, GetConditions returns this instead of the distribution's
	// conditions. Used by the superante draw_board override, which in Python
	// temporarily mutates the shared conditions dict; the Go engine runs
	// many goroutines against a shared Spec, so we swap in a copy instead.
	CondOverride *Conditions

	// --- expwilds game state ---
	ExpandingWilds []WildInfo
	NewExpWilds    []WildInfo
	AvailableReels []int

	// --- superspin game state ---
	StickySymbols         []StickyInfo
	ExistingStickySymbols map[Pos]bool

	// --- gothic_horror Switch state ---
	// SwitchCollected lists the symbol types converted to Wild, in the order
	// they were collected. Cleared at the end of a base-game respin sequence;
	// kept for the whole free game.
	SwitchCollected []string
	// SwitchedCells maps a converted board cell to its original symbol name.
	SwitchedCells map[Pos]string
}

// NewState builds the per-simulation state (mirror of run_sims setup).
func NewState(spec *Spec, mode *BetMode) *State {
	s := &State{
		Spec:       spec,
		Mode:       mode,
		ModeName:   mode.Name,
		Wincap:     mode.MaxWin,
		WinManager: NewWinManager(spec.BasegameType, spec.FreegameType, mode.MaxWin),
	}
	return s
}

// ResetSeed mirrors reset_seed: seed the RNG with sim + 1.
func (s *State) ResetSeed(sim int) {
	s.Rng = pyrand.New(uint64(sim) + 1)
	s.Sim = sim
	s.RepeatCount = 0
}

// ResetBook mirrors GeneralGameState.reset_book + the expwilds override
// (game_override.py resets expanding wilds and available reels).
func (s *State) ResetBook() {
	s.TempWins = s.TempWins[:0]
	s.Board = make([][]*Symbol, s.Spec.NumReels)
	for r := range s.Board {
		s.Board[r] = make([]*Symbol, s.Spec.NumRows[r])
	}
	s.TopSymbols = nil
	s.BottomSymbols = nil
	s.Book = NewBook(s.Sim, s.Criteria)
	s.WinData = WinData{}
	s.WinManager.ResetEndRoundWins()
	s.GlobalMultiplier = 1
	s.FinalWin = 0
	s.TotFS = 0
	s.FS = 0
	s.WincapTriggered = false
	s.TriggeredFreegame = false
	s.Gametype = s.Spec.BasegameType
	s.Repeat = false
	s.Anticipation = make([]int, s.Spec.NumReels)

	s.SwitchCollected = nil
	s.SwitchedCells = nil

	// game_override.reset_book additions (expwilds):
	s.ExpandingWilds = nil
	s.AvailableReels = make([]int, s.Spec.NumReels)
	for i := range s.AvailableReels {
		s.AvailableReels[i] = i
	}
}

// ResetFsSpin mirrors reset_fs_spin.
func (s *State) ResetFsSpin() {
	s.TriggeredFreegame = true
	s.FS = 0
	s.Gametype = s.Spec.FreegameType
	s.WinManager.ResetSpinWin()
}

// GetConditions mirrors get_current_distribution_conditions, honouring the
// temporary override installed by game-level draw_board wrappers.
func (s *State) GetConditions() *Conditions {
	if s.CondOverride != nil {
		return s.CondOverride
	}
	return &s.Dist.Conditions
}

// Record mirrors state.record(description): stringify all keys/values and
// remember them with the current book id for the force files.
func (s *State) Record(pairs []ForcePair) {
	cp := make([]ForcePair, len(pairs))
	copy(cp, pairs)
	s.TempWins = append(s.TempWins, ForceRecord{Pairs: cp, BookID: s.Book.ID})
}

// ImprintedRecords mirrors the imprint_wins force handling: sort each
// description's pairs by key (Python: tuple(sorted(dict.items()))) and
// de-duplicate identical (description, bookId) pairs within the round.
func (s *State) ImprintedRecords() []ForceRecord {
	type key struct {
		desc string
		book int
	}
	seen := map[key]bool{}
	var out []ForceRecord
	for _, rec := range s.TempWins {
		sorted := make([]ForcePair, len(rec.Pairs))
		copy(sorted, rec.Pairs)
		sort.SliceStable(sorted, func(i, j int) bool { return sorted[i].K < sorted[j].K })
		id := ""
		for _, p := range sorted {
			id += p.K + "\x00" + p.V + "\x00"
		}
		k := key{id, rec.BookID}
		if seen[k] {
			continue
		}
		seen[k] = true
		out = append(out, ForceRecord{Pairs: sorted, BookID: rec.BookID})
	}
	return out
}

// UpdateFinalWin mirrors update_final_win, including its consistency asserts.
// The win-split fields keep Python's int-vs-float distinction for capped
// rounds (see Book) so the JSON output is byte-identical.
func (s *State) UpdateFinalWin() {
	capIsInt := s.Mode.MaxWinIsInt
	final := PyRound2(MinF(s.WinManager.RunningBetWin, s.Wincap))
	basewin := PyCappedRound2(s.WinManager.BasegameWins, s.Wincap, capIsInt)
	freewin := PyCappedRound2(s.WinManager.FreegameWins, s.Wincap, capIsInt)

	s.FinalWin = final
	s.Book.PayoutMultiplier = s.FinalWin
	s.Book.BasegameWins = basewin
	s.Book.FreegameWins = freewin

	if MinF(PyRound2(s.WinManager.BasegameWins+s.WinManager.FreegameWins), s.Wincap) !=
		PyRound2(MinF(s.WinManager.RunningBetWin, s.Wincap)) {
		panic(fmt.Sprintf("base + free game payout mismatch (sim %d)", s.Sim))
	}
	if MinF(PyRound2(NumF(basewin)+NumF(freewin)), s.Wincap) !=
		MinF(PyRound2(s.Book.PayoutMultiplier), PyRound2(s.Wincap)) {
		panic(fmt.Sprintf("book base + free payout mismatch (sim %d)", s.Sim))
	}
}

// --- Executables (src/executables/executables.py) ---

// EvaluateWincap mirrors evaluate_wincap: fires the wincap event once the
// running round win reaches the mode max win.
func (s *State) EvaluateWincap() bool {
	if s.WinManager.RunningBetWin >= s.Wincap && !s.WincapTriggered {
		s.WincapTriggered = true
		WincapEvent(s)
		return true
	}
	return false
}

// CheckFsCondition mirrors check_fs_condition.
func (s *State) CheckFsCondition() bool {
	return s.CountSpecialSymbols("scatter") >= s.Spec.MinFreespinTrigger(s.Gametype) && !s.Repeat
}

// CheckFreespinEntry mirrors check_freespin_entry.
func (s *State) CheckFreespinEntry() bool {
	if s.GetConditions().ForceFreegame &&
		len(s.SpecialSymsOnBoard["scatter"]) >= s.Spec.MinFreespinTrigger(s.Gametype) {
		return true
	}
	s.Repeat = true
	return false
}

// RunFreespinFromBase mirrors run_freespin_from_base: record the trigger for
// the force files, publish the trigger event, then run the feature.
func (s *State) RunFreespinFromBase() {
	s.Record([]ForcePair{
		{K: "kind", V: fmt.Sprintf("%d", s.CountSpecialSymbols("scatter"))},
		{K: "symbol", V: "scatter"},
		{K: "gametype", V: s.Gametype},
	})
	s.UpdateFreespinAmount()
	s.RunFreespinFn(s)
}

// UpdateFreespinAmount mirrors update_freespin_amount. A criteria with
// conditions["initial_fs"] set overrides the base-game award.
func (s *State) UpdateFreespinAmount() {
	baseTrigger := s.Gametype == s.Spec.BasegameType
	if baseTrigger && s.GetConditions().InitialFS > 0 {
		s.TotFS = s.GetConditions().InitialFS
	} else {
		s.TotFS = s.Spec.FreespinAmount(s.Gametype, s.CountSpecialSymbols("scatter"))
	}
	FsTriggerEvent(s, baseTrigger, !baseTrigger)
}

// RetriggerFreespinAmount mirrors update_fs_retrigger_amt: a free-game
// retrigger ADDS spins to the remaining total.
func (s *State) RetriggerFreespinAmount() {
	s.TotFS += s.Spec.FreespinAmount(s.Gametype, s.CountSpecialSymbols("scatter"))
	FsTriggerEvent(s, false, true)
}

// UpdateFreespin mirrors update_freespin: called before each free-spin reveal.
func (s *State) UpdateFreespin() {
	UpdateFreespinEvent(s)
	s.FS++
	s.WinManager.ResetSpinWin()
	s.WinData = WinData{}
}

// EndFreespin mirrors end_freespin.
func (s *State) EndFreespin() {
	FreespinEndEvent(s)
}

// EvaluateFinalWin mirrors evaluate_finalwin.
func (s *State) EvaluateFinalWin() {
	s.UpdateFinalWin()
	FinalWinEvent(s)
}
