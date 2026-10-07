// Package game implements game logic on top of the engine -
// the Go equivalent of games/0_0_lines/gamestate.py, game_executables.py, game_override.py.
package game

import (
	"fmt"

	"github.com/stakeengine/go-engine/engine"
)

// Attach wires the 0_0_lines game logic into a State.
func Attach(s *engine.State) {
	s.SpecialSymbolFunctions = map[string][]func(*engine.State, *engine.Symbol){
		"W": {assignMultProperty},
	}
	s.RunFreespinFn = runFreespin
	s.DrawBoardFn = drawBoardOverride
	s.CheckRepeatFn = checkRepeat
}

// assignMultProperty assigns multiplier value to Wild in freegame.
func assignMultProperty(s *engine.State, sym *engine.Symbol) {
	if s.Gametype == s.Spec.FreegameType {
		multVals := s.GetConditions().MultValues[s.Gametype]
		if len(multVals) > 0 {
			mult := engine.GetRandomOutcomeInt(s.Rng, multVals)
			sym.AssignMultiplier(mult)
		}
	}
}

// checkRepeat rejects the round if conditions are not met.
func checkRepeat(s *engine.State) {
	if !s.Repeat {
		winCriteria := s.Dist.WinCriteria
		if winCriteria != nil && s.FinalWin != *winCriteria {
			s.Repeat = true
			return
		}
		if winCriteria == nil && s.FinalWin == 0 {
			s.Repeat = true
			return
		}
		if s.GetConditions().ForceFreegame && !s.TriggeredFreegame {
			s.Repeat = true
			return
		}
	}
}

// drawBoardOverride handles scatter forcing for non-freegame spins when scatter_triggers is present.
func drawBoardOverride(s *engine.State, emitEvent bool, triggerSymbol string) {
	conds := s.GetConditions()
	if !conds.ForceFreegame && s.Gametype == s.Spec.BasegameType && len(conds.ScatterTriggers) > 0 {
		override := *conds // shallow copy
		override.ForceFreegame = true
		s.CondOverride = &override
		defer func() { s.CondOverride = nil }()
		s.DrawBoardDefault(emitEvent, triggerSymbol)
		return
	}
	s.DrawBoardDefault(emitEvent, triggerSymbol)
}

// RunSpin is the entry point for one simulation round.
func RunSpin(s *engine.State, sim int) {
	s.ResetSeed(sim)
	s.Repeat = true
	for s.Repeat {
		s.ResetBook()
		s.DrawBoard(true, "scatter")

		engine.GetLines(s)
		engine.RecordLinesWins(s)
		s.WinManager.UpdateSpinWin(s.WinData.TotalWin)
		engine.EmitLinewinEvents(s)

		s.WinManager.UpdateGametypeWins(s.Gametype)
		if s.CheckFsCondition() && s.CheckFreespinEntry() {
			s.RunFreespinFromBase()
		}

		s.EvaluateFinalWin()
		s.CheckRepeatFn(s)
		s.RepeatCount++
	}
}

// runFreespin executes free game rounds.
func runFreespin(s *engine.State) {
	s.ResetFsSpin()
	for s.FS < s.TotFS && !s.WincapTriggered {
		s.UpdateFreespin()
		s.DrawBoard(true, "scatter")

		engine.GetLines(s)
		engine.RecordLinesWins(s)
		s.WinManager.UpdateSpinWin(s.WinData.TotalWin)
		engine.EmitLinewinEvents(s)

		if s.CheckFsCondition() {
			s.RetriggerFreespinAmount()
		}

		s.WinManager.UpdateGametypeWins(s.Gametype)
	}

	s.EndFreespin()
}

// Describe returns a short console description.
func Describe() string {
	return fmt.Sprintf("0_0_lines (5x3 lines pay game with free spins, Go engine)")
}
