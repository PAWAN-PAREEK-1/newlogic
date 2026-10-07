package engine

// events.go - mirror of src/events/events.py.
//
// Every function appends one JSON event to the current book. Key order and
// numeric formulas replicate the Python emitters exactly (that is what makes
// Go books byte-identical to Python books). All win amounts in events are
// integer cents: the book scale is x100 of the bet multiplier.

import "strconv"

func itoa(v int) string    { return strconv.Itoa(v) }
func itoa64(v int64) string { return strconv.FormatInt(v, 10) }

// Event type constants (src/events/event_constants.py).
const (
	EventReveal            = "reveal"
	EventWinData           = "winInfo"
	EventFinalWin          = "finalWin"
	EventSetWin            = "setWin"
	EventSetTotalWin       = "setTotalWin"
	EventWincap            = "wincap"
	EventUpdateFS          = "updateFreeSpin"
	EventFreespinTrigger   = "freeSpinTrigger"
	EventFreespinRetrigger = "freeSpinRetrigger"
	EventFreeSpinEnd       = "freeSpinEnd"
	EventUpdateGlobalMult  = "updateGlobalMult"
)

// BoardClient is the exported form of boardClient, for game-level events.
func BoardClient(s *State) Arr { return boardClient(s) }

// boardClient renders the board (plus optional padding rows) exactly like
// events.reveal_event does.
func boardClient(s *State) Arr {
	board := make(Arr, len(s.Board))
	for reel := range s.Board {
		col := make(Arr, 0, len(s.Board[reel])+2)
		for row := range s.Board[reel] {
			col = append(col, s.Board[reel][row].JSONReady(s.Spec.SpecialSymbols))
		}
		board[reel] = col
	}
	if s.Spec.IncludePadding {
		for reel := range board {
			col := board[reel].(Arr)
			withPad := make(Arr, 0, len(col)+2)
			withPad = append(withPad, s.TopSymbols[reel].JSONReady(s.Spec.SpecialSymbols))
			withPad = append(withPad, col...)
			withPad = append(withPad, s.BottomSymbols[reel].JSONReady(s.Spec.SpecialSymbols))
			board[reel] = withPad
		}
	}
	return board
}

// RevealEvent mirrors reveal_event.
func RevealEvent(s *State) {
	event := Obj{
		{K: "index", V: len(s.Book.Events)},
		{K: "type", V: EventReveal},
		{K: "board", V: boardClient(s)},
		{K: "paddingPositions", V: append([]int{}, s.ReelPositions...)},
		{K: "gameType", V: s.Gametype},
		{K: "anticipation", V: append([]int{}, s.Anticipation...)},
	}
	s.Book.AddEvent(event)
}

// FsTriggerEvent mirrors fs_trigger_event (include_padding_index=True: rows
// are shifted +1 in the event payload).
func FsTriggerEvent(s *State, basegameTrigger, freegameTrigger bool) {
	if basegameTrigger == freegameTrigger {
		panic("must set either basegame_trigger or freegame_trigger")
	}
	positions := make(Arr, 0, len(s.SpecialSymsOnBoard["scatter"]))
	for _, p := range s.SpecialSymsOnBoard["scatter"] {
		positions = append(positions, Obj{{K: "reel", V: p.Reel}, {K: "row", V: p.Row + 1}})
	}
	eventType := EventFreespinTrigger
	if freegameTrigger {
		eventType = EventFreespinRetrigger
	}
	if s.TotFS <= 0 {
		panic("total freegame (tot_fs) must be > 0")
	}
	event := Obj{
		{K: "index", V: len(s.Book.Events)},
		{K: "type", V: eventType},
		{K: "totalFs", V: s.TotFS},
		{K: "positions", V: positions},
	}
	s.Book.AddEvent(event)
}

// SetWinEvent mirrors set_win_event: the per-reveal win ticker. Skipped once
// the win cap has been triggered (the wincap event replaces it).
func SetWinEvent(s *State) {
	if s.WincapTriggered {
		return
	}
	amount := MinF(float64(PyRound0Int(s.WinManager.SpinWin*100)), s.Wincap*100)
	event := Obj{
		{K: "index", V: len(s.Book.Events)},
		{K: "type", V: EventSetWin},
		{K: "amount", V: PyTruncInt(amount)},
		{K: "winLevel", V: s.Spec.GetWinLevel(s.WinManager.SpinWin, "standard", s.Wincap)},
	}
	s.Book.AddEvent(event)
}

// SetTotalEvent mirrors set_total_event: cumulative round win ticker.
func SetTotalEvent(s *State) {
	event := Obj{
		{K: "index", V: len(s.Book.Events)},
		{K: "type", V: EventSetTotalWin},
		{K: "amount", V: PyRound0Int(MinF(s.WinManager.RunningBetWin, s.Wincap) * 100)},
	}
	s.Book.AddEvent(event)
}

// WincapEvent mirrors wincap_event.
func WincapEvent(s *State) {
	event := Obj{
		{K: "index", V: len(s.Book.Events)},
		{K: "type", V: EventWincap},
		{K: "amount", V: PyRound0Int(MinF(s.WinManager.RunningBetWin, s.Wincap) * 100)},
	}
	s.Book.AddEvent(event)
}

// WinInfoEvent mirrors win_info_event (include_padding_index=True): the
// detailed per-line win breakdown for the reveal.
func WinInfoEvent(s *State) {
	wins := make(Arr, 0, len(s.WinData.Wins))
	for _, w := range s.WinData.Wins {
		positions := make(Arr, 0, len(w.Positions))
		for _, p := range w.Positions {
			positions = append(positions, Obj{{K: "reel", V: p.Reel}, {K: "row", V: p.Row + 1}})
		}
		meta := Obj{
			{K: "lineIndex", V: w.LineIndex},
			{K: "multiplier", V: w.Multiplier},
			{K: "winWithoutMult", V: PyTruncInt(MinF(w.WinWithoutMult*100, s.Wincap*100))},
			{K: "globalMult", V: w.GlobalMult},
			{K: "lineMultiplier", V: w.LineMultiplier},
		}
		wins = append(wins, Obj{
			{K: "symbol", V: w.Symbol},
			{K: "kind", V: w.Kind},
			{K: "win", V: PyRound0Int(MinF(w.Win, s.Wincap) * 100)},
			{K: "positions", V: positions},
			{K: "meta", V: meta},
		})
	}
	event := Obj{
		{K: "index", V: len(s.Book.Events)},
		{K: "type", V: EventWinData},
		{K: "totalWin", V: PyRound0Int(MinF(s.WinData.TotalWin, s.Wincap) * 100)},
		{K: "wins", V: wins},
	}
	s.Book.AddEvent(event)
}

// UpdateFreespinEvent mirrors update_freespin_event - emitted BEFORE the
// spin counter increments, so `amount` is the 0-based spin index.
func UpdateFreespinEvent(s *State) {
	event := Obj{
		{K: "index", V: len(s.Book.Events)},
		{K: "type", V: EventUpdateFS},
		{K: "amount", V: s.FS},
		{K: "total", V: s.TotFS},
	}
	s.Book.AddEvent(event)
}

// FreespinEndEvent mirrors freespin_end_event.
func FreespinEndEvent(s *State) {
	event := Obj{
		{K: "index", V: len(s.Book.Events)},
		{K: "type", V: EventFreeSpinEnd},
		{K: "amount", V: PyRound0Int(MinF(s.WinManager.FreegameWins, s.Wincap) * 100)},
		{K: "winLevel", V: s.Spec.GetWinLevel(s.WinManager.FreegameWins, "endFeature", s.Wincap)},
	}
	s.Book.AddEvent(event)
}

// FinalWinEvent mirrors final_win_event.
func FinalWinEvent(s *State) {
	event := Obj{
		{K: "index", V: len(s.Book.Events)},
		{K: "type", V: EventFinalWin},
		{K: "amount", V: PyRound0Int(MinF(s.FinalWin, s.Wincap) * 100)},
	}
	s.Book.AddEvent(event)
}

// UpdateGlobalMultEvent mirrors update_global_mult_event.
func UpdateGlobalMultEvent(s *State) {
	event := Obj{
		{K: "index", V: len(s.Book.Events)},
		{K: "type", V: EventUpdateGlobalMult},
		{K: "globalMult", V: s.GlobalMultiplier},
	}
	s.Book.AddEvent(event)
}
