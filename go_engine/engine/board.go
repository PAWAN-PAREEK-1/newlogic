package engine

// board.go - mirror of src/calculations/board.py.
//
// EVERY RNG call in this file happens in the exact order of the Python
// implementation - including "wasted" draws (e.g. symbol-creation hooks whose
// result is later overwritten). Do not reorder anything here without also
// changing the Python engine, or the two engines will produce different books.

import "sort"

// CreateSymbol mirrors Board.create_symbol: instantiate the symbol, then run
// any game-registered special functions (these may consume RNG - e.g. the
// expwilds wild-multiplier assignment during free games).
func (s *State) CreateSymbol(name string) *Symbol {
	sym := NewSymbol(s.Spec.SymbolDefFor(name))
	if fns, ok := s.SpecialSymbolFunctions[name]; ok {
		for _, fn := range fns {
			fn(s, sym)
		}
	}
	return sym
}

// RefreshSpecialSyms mirrors refresh_special_syms.
func (s *State) RefreshSpecialSyms() {
	s.SpecialSymsOnBoard = make(map[string][]Pos, len(s.Spec.SpecialSymbols))
	for _, sp := range s.Spec.SpecialSymbols {
		s.SpecialSymsOnBoard[sp.Property] = []Pos{}
	}
}

// scanCellSpecials replicates the per-cell bookkeeping inside the two board
// creation loops: append the cell to each special-symbol list whose names
// contain it, and detect the first reel that arms scatter anticipation.
func (s *State) scanCellSpecials(sym *Symbol, reel, row int, firstScatterReel *int) {
	if !sym.Def.Special {
		return
	}
	for _, sp := range s.Spec.SpecialSymbols {
		for _, name := range sp.Symbols {
			if sym.Name() == name {
				s.SpecialSymsOnBoard[sp.Property] = append(s.SpecialSymsOnBoard[sp.Property], Pos{reel, row})
				// Python: board.check_attribute("scatter") and
				// len(list) >= anticipation_triggers[gametype] and first == -1
				// (anticipation_triggers may not define the current gametype;
				// Python short-circuits before the KeyError when the cell is
				// not a scatter - we mirror that with the ok-check panic.)
				if sym.CheckAttribute("scatter") && *firstScatterReel == -1 {
					trig, ok := s.Spec.AnticipationTriggers[s.Gametype]
					if !ok {
						panic("anticipation_triggers missing for gametype " + s.Gametype)
					}
					if len(s.SpecialSymsOnBoard[sp.Property]) >= trig {
						*firstScatterReel = reel + 1
					}
				}
			}
		}
	}
}

// CreateBoardReelstrips mirrors create_board_reelstrips: pick a reelstrip via
// the criteria's reel weights, choose a random stop per reel, and populate
// the board (plus padding symbols when the game uses them).
func (s *State) CreateBoardReelstrips() {
	var topSymbols, bottomSymbols []*Symbol
	s.RefreshSpecialSyms()
	s.ReelstripID = GetRandomOutcomeStr(s.Rng, s.GetConditions().ReelWeights[s.Gametype])
	s.Reelstrip = s.Spec.Reels[s.ReelstripID]
	if s.Reelstrip == nil {
		panic("unknown reelstrip: " + s.ReelstripID)
	}
	anticipation := make([]int, s.Spec.NumReels)
	board := make([][]*Symbol, s.Spec.NumReels)
	for i := range board {
		board[i] = make([]*Symbol, s.Spec.NumRows[i])
	}
	// Python draws all stop positions first (list comprehension, reel order).
	reelPositions := make([]int, s.Spec.NumReels)
	for reel := 0; reel < s.Spec.NumReels; reel++ {
		reelPositions[reel] = s.Rng.RandRange(len(s.Reelstrip[reel]))
	}
	paddingPositions := make([]int, s.Spec.NumReels)
	firstScatterReel := -1
	for reel := 0; reel < s.Spec.NumReels; reel++ {
		reelPos := reelPositions[reel]
		stripLen := len(s.Reelstrip[reel])
		if s.Spec.IncludePadding {
			topSymbols = append(topSymbols, s.CreateSymbol(s.Reelstrip[reel][PyMod(reelPos-1, stripLen)]))
			bottomSymbols = append(bottomSymbols, s.CreateSymbol(s.Reelstrip[reel][PyMod(reelPos+len(board[reel]), stripLen)]))
		}
		for row := 0; row < s.Spec.NumRows[reel]; row++ {
			symID := s.Reelstrip[reel][PyMod(reelPos+row, stripLen)]
			sym := s.CreateSymbol(symID)
			board[reel][row] = sym
			s.scanCellSpecials(sym, reel, row, &firstScatterReel)
		}
		paddingPositions[reel] = PyMod(reelPositions[reel]+len(board[reel])+1, stripLen)
	}

	if firstScatterReel > -1 && firstScatterReel != s.Spec.NumReels {
		count := 1
		for reel := firstScatterReel; reel < s.Spec.NumReels; reel++ {
			anticipation[reel] = count
			count++
		}
	}
	for r := 1; r < s.Spec.NumReels; r++ {
		if anticipation[r-1] > anticipation[r] {
			panic("anticipation ordering violated")
		}
	}

	s.Board = board
	s.GetSpecialSymbolsOnBoard()
	s.ReelPositions = reelPositions
	s.PaddingPositions = paddingPositions
	s.Anticipation = anticipation
	if s.Spec.IncludePadding {
		s.TopSymbols = topSymbols
		s.BottomSymbols = bottomSymbols
	}
}

// ForceBoardFromReelstrips mirrors force_board_from_reelstrips: build a board
// with pinned stop positions for some reels (used to force scatter counts).
// forcedStops must be ordered by reel (Python sorts before calling).
func (s *State) ForceBoardFromReelstrips(reelstripID string, forcedStops []Pos) {
	var topSymbols, bottomSymbols []*Symbol
	s.RefreshSpecialSyms()
	s.ReelstripID = reelstripID
	s.Reelstrip = s.Spec.Reels[reelstripID]
	anticipation := make([]int, s.Spec.NumReels)
	board := make([][]*Symbol, s.Spec.NumReels)
	for i := range board {
		board[i] = make([]*Symbol, s.Spec.NumRows[i])
	}

	// Pinned reels first (in reel order), then random stops for the rest -
	// same RNG order as Python. A pinned stop is shifted up by a random row
	// offset so the target symbol can land on any visible row; the resulting
	// index may be negative, which Python's modulo wraps around.
	reelPositions := make([]int, s.Spec.NumReels)
	assigned := make([]bool, s.Spec.NumReels)
	for _, fs := range forcedStops {
		reelPositions[fs.Reel] = fs.Row - s.Rng.RandInt(0, s.Spec.NumRows[fs.Reel]-1)
		assigned[fs.Reel] = true
	}
	for r := 0; r < s.Spec.NumReels; r++ {
		if !assigned[r] {
			reelPositions[r] = s.Rng.RandRange(len(s.Reelstrip[r]))
		}
	}

	paddingPositions := make([]int, s.Spec.NumReels)
	firstScatterReel := -1
	for reel := 0; reel < s.Spec.NumReels; reel++ {
		reelPos := reelPositions[reel]
		stripLen := len(s.Reelstrip[reel])
		if s.Spec.IncludePadding {
			topSymbols = append(topSymbols, s.CreateSymbol(s.Reelstrip[reel][PyMod(reelPos-1, stripLen)]))
			bottomSymbols = append(bottomSymbols, s.CreateSymbol(s.Reelstrip[reel][PyMod(reelPos+len(board[reel]), stripLen)]))
		}
		for row := 0; row < s.Spec.NumRows[reel]; row++ {
			symID := s.Reelstrip[reel][PyMod(reelPos+row, stripLen)]
			sym := s.CreateSymbol(symID)
			board[reel][row] = sym
			s.scanCellSpecials(sym, reel, row, &firstScatterReel)
		}
		paddingPositions[reel] = PyMod(reelPositions[reel]+len(board[reel])+1, stripLen)
	}

	// Python's forced variant uses `first_scatter_reel <= num_reels` here
	// (slightly different to create_board_reelstrips) - mirrored exactly.
	if firstScatterReel > -1 && firstScatterReel <= s.Spec.NumReels {
		count := 1
		for reel := firstScatterReel; reel < s.Spec.NumReels; reel++ {
			anticipation[reel] = count
			count++
		}
	}

	s.Board = board
	s.ReelPositions = reelPositions
	s.PaddingPositions = paddingPositions
	s.Anticipation = anticipation
	if s.Spec.IncludePadding {
		s.TopSymbols = topSymbols
		s.BottomSymbols = bottomSymbols
	}
}

// GetSpecialSymbolsOnBoard mirrors get_special_symbols_on_board: rebuild the
// special-symbol position lists by scanning the final board.
func (s *State) GetSpecialSymbolsOnBoard() {
	s.RefreshSpecialSyms()
	for reel := range s.Board {
		for row := range s.Board[reel] {
			if s.Board[reel][row].Def.Special {
				for _, sp := range s.Spec.SpecialSymbols {
					if s.Board[reel][row].CheckAttribute(sp.Property) {
						s.SpecialSymsOnBoard[sp.Property] = append(s.SpecialSymsOnBoard[sp.Property], Pos{reel, row})
					}
				}
			}
		}
	}
}

// DrawBoardDefault mirrors Board.draw_board: either force a scatter count
// (criteria wants a free game), or redraw until the board does NOT trigger
// (criteria forbids a free game), or draw plainly (free-game reveals).
func (s *State) DrawBoardDefault(emitEvent bool, triggerSymbol string) {
	conds := s.GetConditions()
	switch {
	case conds.ForceFreegame && s.Gametype == s.Spec.BasegameType:
		numScatters := GetRandomOutcomeInt(s.Rng, conds.ScatterTriggers)
		s.ForceSpecialBoard(triggerSymbol, int(numScatters))
	case !conds.ForceFreegame && s.Gametype == s.Spec.BasegameType:
		s.CreateBoardReelstrips()
		for s.CountSpecialSymbols(triggerSymbol) >= s.Spec.MinFreespinTrigger(s.Gametype) {
			s.CreateBoardReelstrips()
		}
	default:
		s.CreateBoardReelstrips()
	}
	if emitEvent {
		RevealEvent(s)
	}
}

// DrawBoard dispatches through the game-installed hook (superante override).
func (s *State) DrawBoard(emitEvent bool, triggerSymbol string) {
	s.DrawBoardFn(s, emitEvent, triggerSymbol)
}

// ForceSpecialBoard mirrors force_special_board: retry the forced construction
// until the board holds exactly the requested number of target symbols
// (a stacked target symbol on one reel could otherwise overshoot).
func (s *State) ForceSpecialBoard(forceCriteria string, numForceSyms int) {
	isSpecialProp := false
	for _, sp := range s.Spec.SpecialSymbols {
		if sp.Property == forceCriteria {
			isSpecialProp = true
		}
	}
	for {
		s.forceSpecialBoardOnce(forceCriteria, numForceSyms)
		if isSpecialProp && s.CountSpecialSymbols(forceCriteria) == numForceSyms {
			break
		}
		if !isSpecialProp && s.CountSymbolsOnBoard(forceCriteria) == numForceSyms {
			break
		}
	}
}

// forceSpecialBoardOnce mirrors _force_special_board: choose which reels get
// the target symbol (weighted by how often it appears on each reel of the
// strip), pick a concrete stop for each, then build the board around them.
func (s *State) forceSpecialBoardOnce(forceCriteria string, numForceSyms int) {
	reelstripID := GetRandomOutcomeStr(s.Rng, s.GetConditions().ReelWeights[s.Gametype])
	reelstops := s.GetSymsOnReel(reelstripID, forceCriteria)

	symProb := make([]float64, s.Spec.NumReels)
	for x := 0; x < s.Spec.NumReels; x++ {
		symProb[x] = float64(len(reelstops[x])) / float64(len(s.Spec.Reels[reelstripID][x]))
	}
	forceStops := map[int]int{}
	possibleReels := []int{}
	possibleProbs := []float64{}
	for i := 0; i < s.Spec.NumReels; i++ {
		if symProb[i] > 0 {
			possibleReels = append(possibleReels, i)
			possibleProbs = append(possibleProbs, symProb[i])
		}
	}

	for len(forceStops) != numForceSyms && len(possibleReels) > 0 {
		chosenReel := possibleReels[s.Rng.WeightedChoiceIndex(possibleProbs)]
		chosenStop := reelstops[chosenReel][s.Rng.ChoiceIndex(len(reelstops[chosenReel]))]
		symProb[chosenReel] = 0
		forceStops[chosenReel] = chosenStop
		possibleReels = possibleReels[:0]
		possibleProbs = possibleProbs[:0]
		for i := 0; i < s.Spec.NumReels; i++ {
			if symProb[i] > 0 {
				possibleReels = append(possibleReels, i)
				possibleProbs = append(possibleProbs, symProb[i])
			}
		}
	}

	// Python sorts the forced stops by reel before building the board.
	ordered := make([]Pos, 0, len(forceStops))
	for reel, stop := range forceStops {
		ordered = append(ordered, Pos{Reel: reel, Row: stop})
	}
	sort.Slice(ordered, func(i, j int) bool { return ordered[i].Reel < ordered[j].Reel })
	s.ForceBoardFromReelstrips(reelstripID, ordered)
}

// GetSymsOnReel mirrors get_syms_on_reel: all stop positions of a symbol (or
// special-property group) on each reel of a strip.
func (s *State) GetSymsOnReel(reelID, targetSymbol string) [][]int {
	reel := s.Spec.Reels[reelID]
	positions := make([][]int, s.Spec.NumReels)
	var groupNames []string
	for _, sp := range s.Spec.SpecialSymbols {
		if sp.Property == targetSymbol {
			groupNames = sp.Symbols
		}
	}
	for r := 0; r < s.Spec.NumReels; r++ {
		positions[r] = []int{}
		for stop := 0; stop < len(reel[r]); stop++ {
			if groupNames != nil {
				for _, n := range groupNames {
					if reel[r][stop] == n {
						positions[r] = append(positions[r], stop)
						break
					}
				}
			} else if reel[r][stop] == targetSymbol {
				positions[r] = append(positions[r], stop)
			}
		}
	}
	return positions
}

// CountSpecialSymbols mirrors count_special_symbols.
func (s *State) CountSpecialSymbols(prop string) int {
	return len(s.SpecialSymsOnBoard[prop])
}

// CountSymbolsOnBoard mirrors count_symbols_on_board (case-insensitive name
// match, faithfully ported even though the SDK always passes exact names).
func (s *State) CountSymbolsOnBoard(name string) int {
	count := 0
	for reel := range s.Board {
		for row := range s.Board[reel] {
			if equalFold(s.Board[reel][row].Name(), name) {
				count++
			}
		}
	}
	return count
}

func equalFold(a, b string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := 0; i < len(a); i++ {
		ca, cb := a[i], b[i]
		if 'a' <= ca && ca <= 'z' {
			ca -= 32
		}
		if 'a' <= cb && cb <= 'z' {
			cb -= 32
		}
		if ca != cb {
			return false
		}
	}
	return true
}
