package engine

// winmanager.go - mirror of src/wins/win_manager.py.
//
// Tracks wins at three levels:
//   - cumulative across all simulations (for the RTP printout),
//   - per betting round (basegame vs freegame split),
//   - per reveal ("spin win").

// WinManager mirrors the Python WinManager.
type WinManager struct {
	BaseGameMode  string
	FreeGameMode  string
	MaxAllowedWin float64

	// Cumulative across simulations (per worker; merged for reporting).
	TotalCumulativeWins float64
	CumulativeBaseWins  float64
	CumulativeFreeWins  float64

	// Per betting round.
	RunningBetWin float64
	BasegameWins  float64
	FreegameWins  float64

	// Per reveal.
	SpinWin   float64
	TumbleWin float64
}

// NewWinManager mirrors WinManager.__init__.
func NewWinManager(baseMode, freeMode string, modeMaxWin float64) *WinManager {
	return &WinManager{BaseGameMode: baseMode, FreeGameMode: freeMode, MaxAllowedWin: modeMaxWin}
}

// UpdateSpinWin mirrors update_spinwin.
func (w *WinManager) UpdateSpinWin(amount float64) {
	w.SpinWin += amount
	w.RunningBetWin += amount
}

// SetSpinWin mirrors set_spin_win.
func (w *WinManager) SetSpinWin(amount float64) {
	diff := amount - w.SpinWin
	w.SpinWin = amount
	w.RunningBetWin += diff
}

// ResetSpinWin mirrors reset_spin_win.
func (w *WinManager) ResetSpinWin() { w.SpinWin = 0.0 }

// UpdateGametypeWins mirrors update_gametype_wins.
func (w *WinManager) UpdateGametypeWins(gametype string) {
	switch gametype {
	case w.BaseGameMode:
		w.BasegameWins += w.SpinWin
	case w.FreeGameMode:
		w.FreegameWins += w.SpinWin
	default:
		panic("must define a valid gametype: " + gametype)
	}
}

// UpdateEndRoundWins mirrors update_end_round_wins (caps each game type at
// the mode max win before accumulating).
func (w *WinManager) UpdateEndRoundWins() {
	base := MinF(w.MaxAllowedWin, w.BasegameWins)
	free := MinF(w.MaxAllowedWin, w.FreegameWins)
	w.TotalCumulativeWins += base + free
	w.CumulativeBaseWins += base
	w.CumulativeFreeWins += free
}

// ResetEndRoundWins mirrors reset_end_round_wins.
func (w *WinManager) ResetEndRoundWins() {
	w.BasegameWins = 0.0
	w.FreegameWins = 0.0
	w.RunningBetWin = 0.0
	w.SpinWin = 0.0
	w.TumbleWin = 0.0
}
