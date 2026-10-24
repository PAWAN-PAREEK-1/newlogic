"""Handles the state and output for a single simulation round."""

from .game_override import GameStateOverride
from .game_events import refine_symbol_event


class GameState(GameStateOverride):
    """Handles game logic and events for a single simulation number/game-round."""

    def run_spin(self, sim, simulation_seed=None):
        self.reset_seed(sim)
        self.repeat = True
        while self.repeat:
            self.reset_book()
            self.draw_spin_board()

            # Evaluate wins, collapse the board and repeat until no run is left
            self.play_collapse_sequence()

            self.set_end_tumble_event()
            self.win_manager.update_gametype_wins(self.gametype)

            if self.check_fs_condition() and self.check_freespin_entry():
                self.run_freespin_from_base()

            self.evaluate_finalwin()
            self.check_repeat()

        self.imprint_wins()

    def run_freespin(self):
        """Play the bonus: a fixed number of free spins on line multipliers.

        What a bonus adds on top comes from the config: wilds dropped on every spin
        (bonus_wild_drop, applied in draw_bonus_board) and symbol upgrades (bonus_upgrades).
        """
        self.reset_fs_spin()
        upgrades = self.bonus_type in self.config.bonus_upgrades
        while self.fs < self.tot_fs and not self.wincap_triggered:
            self.update_freespin()
            self.draw_bonus_board()

            self.play_collapse_sequence()

            self.set_end_tumble_event()
            self.win_manager.update_gametype_wins(self.gametype)

            # Every winning spin upgrades the lowest symbol left.
            if upgrades and self.win_manager.spin_win > 0 and self.refine_level < len(self.config.refine_order):
                removed = self.config.refine_order[self.refine_level]
                self.refine_level += 1
                refine_symbol_event(self, removed, self.config.refine_into[removed])
        self.end_freespin()
