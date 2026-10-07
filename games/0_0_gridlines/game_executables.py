"""Grouped game actions for the grid-line pays game."""

from .game_calculations import GameCalculations
from .game_events import (
    bonus_trigger_event,
    collapse_board_event,
    prime_symbols_event,
    sticky_wilds_event,
    wild_drop_event,
)
from src.calculations.gridlines import GridLines
from src.calculations.statistics import get_random_outcome
from src.events.events import (
    reveal_event,
    update_freespin_event,
    update_global_mult_event,
    update_tumble_win_event,
    win_info_event,
)


class GameExecutables(GameCalculations):
    """Board draws, win evaluation and the collapse sequence."""

    # --------------------------------------------------------------------------------------
    # Board draws
    # --------------------------------------------------------------------------------------

    def draw_spin_board(self) -> None:
        """Draw and reveal the board of a paid spin, then apply the mode's wild drop.

        Prime spin: the symbols removed for this spin are announced before the reveal.
        """
        self.draw_board(emit_event=False)
        if self.refine_level > 0:
            prime_symbols_event(self)
        reveal_event(self)
        wild_drop = self.get_current_distribution_conditions().get("wild_drop")
        if wild_drop is not None:
            self.drop_wilds(get_random_outcome(wild_drop))

    def draw_bonus_board(self) -> None:
        """Draw and reveal the board of a bonus spin from the strip of the active bonus game."""
        reel_weights = self.get_current_distribution_conditions()["bonus_reels"][self.bonus_type]
        self.force_board_from_reelstrips(get_random_outcome(reel_weights), {})
        if len(self.sticky_wilds) > 0:
            for pos in self.sticky_wilds:
                self.board[pos["reel"]][pos["row"]] = self.create_symbol("W")
            sticky_wilds_event(self, self.sticky_wilds)
        self.get_special_symbols_on_board()
        reveal_event(self)
        wild_drop = self.config.bonus_wild_drop.get(self.bonus_type)
        if wild_drop is not None:
            self.drop_wilds(get_random_outcome(wild_drop))

    def drop_wilds(self, count: int) -> None:
        """Turn `count` random regular symbols into wilds."""
        positions = self.pick_wild_drop_positions(count)
        for pos in positions:
            self.board[pos["reel"]][pos["row"]] = self.create_symbol("W")
        self.get_special_symbols_on_board()
        if len(positions) > 0:
            wild_drop_event(self, positions)

    # --------------------------------------------------------------------------------------
    # Win evaluation and collapse
    # --------------------------------------------------------------------------------------

    def evaluate_gridlines(self) -> None:
        """Find every run on the board, record the wins and update the wallet."""
        self.win_data = GridLines.get_gridline_wins(
            self.config,
            self.board,
            global_multiplier=self.global_multiplier,
            min_run=self.config.min_run,
        )
        GridLines.record_gridline_wins(self)
        self.win_manager.update_spinwin(self.win_data["totalWin"])
        self.win_manager.tumble_win = self.win_data["totalWin"]

    def emit_collapse_win_events(self) -> None:
        """Transmit win information for the board that was just evaluated."""
        if self.win_data["totalWin"] > 0:
            win_info_event(self, include_padding_index=self.config.include_padding)
            update_tumble_win_event(self)
            self.evaluate_wincap()

    def collapse_game_board(self) -> None:
        """Remove the winning runs, leave a wild in the centre of each and drop the rest."""
        spawn = []
        if self.config.centre_wild:
            spawn = [{**pos, "name": "W"} for pos in GridLines.get_centre_positions(self.win_data)]
        self.collapse_board(spawn)
        collapse_board_event(self)

    def step_multiplier(self) -> None:
        """Move up the multiplier ladder after a collapse: one step for every winning run."""
        self.set_mult_step(self.mult_step + self.config.mult_step_per_run * len(self.win_data["wins"]))

    def set_mult_step(self, step: int) -> None:
        """Set the position on the multiplier ladder, transmitting the multiplier if it changed."""
        ladder = self.config.bonus_mult_ladder.get(self.bonus_type, self.config.mult_ladder)
        self.mult_step = step
        value = ladder[min(step, len(ladder) - 1)]
        if self.global_multiplier != value:
            self.global_multiplier = value
            update_global_mult_event(self)

    def reset_multiplier(self) -> None:
        """Back to the first step of the ladder (1x)."""
        self.set_mult_step(0)

    def play_collapse_sequence(self) -> None:
        """Evaluate, pay and collapse until the board has no more runs."""
        self.evaluate_gridlines()
        self.emit_collapse_win_events()
        while self.win_data["totalWin"] > 0 and not self.wincap_triggered:
            self.collapse_game_board()
            self.step_multiplier()
            self.evaluate_gridlines()
            self.emit_collapse_win_events()

    # --------------------------------------------------------------------------------------
    # Bonus entry and spin counters
    # --------------------------------------------------------------------------------------

    def run_freespin_from_base(self, scatter_key: str = "scatter") -> None:
        """Choose the bonus game, record the trigger and play the bonus."""
        self.bonus_type = get_random_outcome(self.get_current_distribution_conditions()["bonus_weights"])
        self.record(
            {
                "kind": self.count_special_symbols(scatter_key),
                "symbol": scatter_key,
                "gametype": self.gametype,
                "bonus": self.bonus_type,
            }
        )
        self.update_freespin_amount(scatter_key)
        self.run_freespin()

    def update_freespin_amount(self, scatter_key: str = "scatter") -> None:
        """Set the spins (surge, refine) or lives (survival) awarded and transmit the trigger."""
        award = self.config.bonus_awards[self.bonus_type][self.count_special_symbols(scatter_key)]
        if self.bonus_type == "survival":
            self.lives = award
            self.tot_fs = 0
        else:
            self.lives = 0
            self.tot_fs = award
        bonus_trigger_event(self)

    def update_freespin(self) -> None:
        """Called before a new reveal during a bonus played on a fixed number of spins."""
        self.fs += 1
        update_freespin_event(self)
        self.win_manager.reset_spin_win()
        self.win_data = {}
