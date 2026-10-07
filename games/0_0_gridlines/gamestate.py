"""Handles the state and output for a single simulation round."""

from .game_override import GameStateOverride
from .game_events import refine_symbol_event, update_lives_event


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
        self.reset_fs_spin()
        if self.bonus_type == "refine":
            self.run_refine()
        elif self.bonus_type == "surge":
            self.run_surge()
        elif self.bonus_type == "survival":
            self.run_survival()
        else:
            raise RuntimeError(f"Unknown bonus type: {self.bonus_type}")
        self.end_freespin()

    def run_refine(self):
        """Fixed number of spins. Every winning spin upgrades the lowest symbol left and
        raises the multiplier the following spins start on."""
        while self.fs < self.tot_fs and not self.wincap_triggered:
            self.update_freespin()
            self.set_multiplier(1 + self.refine_level * self.config.refine_mult_per_level)
            self.draw_bonus_board()

            self.play_collapse_sequence()

            self.set_end_tumble_event()
            self.win_manager.update_gametype_wins(self.gametype)

            if self.win_manager.spin_win > 0 and self.refine_level < len(self.config.refine_order):
                removed = self.config.refine_order[self.refine_level]
                self.refine_level += 1
                refine_symbol_event(self, removed, self.config.refine_into[removed])

    def run_surge(self):
        """Fixed number of spins. Wilds drop on every spin and the multiplier never resets."""
        while self.fs < self.tot_fs and not self.wincap_triggered:
            self.update_freespin()
            self.draw_bonus_board()

            self.play_collapse_sequence()

            self.set_end_tumble_event()
            self.win_manager.update_gametype_wins(self.gametype)

    def run_survival(self):
        """No spin counter. A spin without a win costs a life and resets the multiplier.
        Wilds left on the grid stay for the next spin."""
        self.sticky_wilds = self.pick_start_wilds(self.config.survival_start_wilds)
        while self.lives > 0 and self.fs < self.config.survival_max_spins and not self.wincap_triggered:
            self.fs += 1
            self.win_manager.reset_spin_win()
            self.win_data = {}
            update_lives_event(self)
            self.draw_bonus_board()

            self.play_collapse_sequence()

            self.set_end_tumble_event()
            self.win_manager.update_gametype_wins(self.gametype)

            if self.win_manager.spin_win == 0:
                self.lives -= 1
                update_lives_event(self, lost_life=True)
                self.reset_multiplier()
            self.sticky_wilds = self.get_wild_positions()
