package engine

// lines.go - mirror of src/calculations/lines.py + src/wins/multiplier_strategy.py.
//
// Evaluates left-to-right payline wins with wild substitution. A line of pure
// wilds can pay either as the wild's own paytable entry or by substituting for
// the first non-wild symbol - whichever pays more (ties go to the substituted
// win, matching Python's `if wild_win > base_win`).

// applySymbolMult mirrors multiplier_strategy.apply_added_symbol_mult:
// sum the multiplier values (>1) sitting on the winning positions; a win is
// multiplied by that sum, or 1 if no multipliers are present.
func applySymbolMult(board [][]*Symbol, winAmount float64, positions []Pos) (float64, int64) {
	var symbolMultiplier int64
	for _, pos := range positions {
		sym := board[pos.Reel][pos.Row]
		if sym.CheckAttribute("multiplier") && sym.GetMultiplier() > 1 {
			symbolMultiplier += sym.GetMultiplier()
		}
	}
	applied := symbolMultiplier
	if applied < 1 {
		applied = 1
	}
	return PyRound2(winAmount * float64(applied)), applied
}

// GetLines mirrors Lines.get_lines (multiplier_method="symbol", the strategy
// this game uses). Results land in s.WinData.
func GetLines(s *State) {
	const wildKey = "wild"
	const wildSym = "W"

	data := WinData{}
	for _, payline := range s.Spec.Paylines {
		line := payline.Rows
		firstSym := s.Board[0][line[0]]
		finishedWildWin := !firstSym.CheckAttribute(wildKey)
		var firstNonWild *Symbol
		if finishedWildWin {
			firstNonWild = firstSym
		}
		potentialFirst := firstSym // potential_line[0] - the line's leading symbol

		wildMatches := 0
		matches := 0
		if finishedWildWin {
			matches = 1
		} else {
			wildMatches = 1
		}
		var baseWin, wildWin float64

		for reel := 1; reel < len(line); reel++ {
			sym := s.Board[reel][line[reel]]
			if finishedWildWin {
				if sym.Name() == firstNonWild.Name() || sym.CheckAttribute(wildKey) {
					matches++
				} else {
					break
				}
			} else {
				if sym.CheckAttribute(wildKey) && firstNonWild == nil {
					wildMatches++
				} else if firstNonWild == nil {
					firstNonWild = sym
					matches++
					finishedWildWin = true
				} else {
					break
				}
			}
		}

		if pay, ok := s.Spec.Pay(wildMatches, wildSym); ok {
			wildWin = pay
		}
		if firstNonWild != nil {
			if pay, ok := s.Spec.Pay(wildMatches+matches, firstNonWild.Name()); ok {
				baseWin = pay
			}
		}

		if baseWin > 0 || wildWin > 0 {
			var win LineWin
			if wildWin > baseWin {
				// The pure-wild prefix pays better than substituting.
				positions := make([]Pos, wildMatches)
				for idx := 0; idx < wildMatches; idx++ {
					positions[idx] = Pos{Reel: idx, Row: line[idx]}
				}
				lineWin, appliedMult := applySymbolMult(s.Board, wildWin, positions)
				win = LineWin{
					Symbol:         potentialFirst.Name(),
					Kind:           wildMatches,
					Win:            lineWin,
					Positions:      positions,
					LineIndex:      payline.ID,
					Multiplier:     appliedMult,
					WinWithoutMult: wildWin,
					GlobalMult:     s.GlobalMultiplier,
					LineMultiplier: PyTruncInt(float64(appliedMult) / float64(s.GlobalMultiplier)),
				}
			} else {
				positions := make([]Pos, matches+wildMatches)
				for idx := 0; idx < matches+wildMatches; idx++ {
					positions[idx] = Pos{Reel: idx, Row: line[idx]}
				}
				lineWin, appliedMult := applySymbolMult(s.Board, baseWin, positions)
				win = LineWin{
					Symbol:         firstNonWild.Name(),
					Kind:           matches + wildMatches,
					Win:            lineWin,
					Positions:      positions,
					LineIndex:      payline.ID,
					Multiplier:     appliedMult,
					WinWithoutMult: baseWin,
					GlobalMult:     s.GlobalMultiplier,
					LineMultiplier: PyTruncInt(float64(appliedMult) / float64(s.GlobalMultiplier)),
				}
			}
			data.TotalWin += win.Win
			data.Wins = append(data.Wins, win)
		}
	}
	s.WinData = data
}

// RecordLinesWins mirrors Lines.record_lines_wins: one force-file description
// per winning line.
func RecordLinesWins(s *State) {
	for _, win := range s.WinData.Wins {
		s.Record([]ForcePair{
			{K: "kind", V: itoa(len(win.Positions))},
			{K: "symbol", V: win.Symbol},
			{K: "mult", V: itoa64(win.Multiplier)},
			{K: "gametype", V: s.Gametype},
		})
	}
}

// EmitLinewinEvents mirrors Lines.emit_linewin_events.
func EmitLinewinEvents(s *State) {
	if s.WinManager.SpinWin > 0 {
		WinInfoEvent(s)
		s.EvaluateWincap()
		SetWinEvent(s)
	}
	SetTotalEvent(s)
}
