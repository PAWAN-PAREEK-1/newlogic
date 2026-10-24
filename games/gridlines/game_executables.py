"""Grouped game actions for the grid-line pays game."""

from .game_calculations import GameCalculations
from .game_events import (
    bonus_trigger_event,
    collapse_board_event,
    prime_symbols_event,
    update_line_mult_event,
    wild_drop_event,
)
from src.calculations.gridlines import GridLines
from src.calculations.statistics import get_random_outcome
from src.events.events import (
    reveal_event,
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
            line_multipliers=self.line_mults if self.bonus_type is not None else None,
        )
        GridLines.record_gridline_wins(self)
        self.win_manager.update_spinwin(self.win_data["totalWin"])
        self.win_manager.tumble_win = self.win_data["totalWin"]

    def emit_collapse_win_events(self) -> None:
        """Transmit win information for the board that was just evaluated."""
        if self.win_data["totalWin"] > 0:
            win_info_event(self)
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
        """After a collapse, one step for every winning run: on the spin's ladder in a paid
        spin, on the multiplier of the run's own row or column in a bonus."""
        if self.bonus_type is None:
            self.set_mult_step(self.mult_step + self.config.mult_step_per_run * len(self.win_data["wins"]))
        else:
            self.step_line_multipliers()

    def step_line_multipliers(self) -> None:
        """Move the multiplier of every winning run's line one step up, transmitting any change."""
        ladder = self.config.bonus_line_mult_ladder.get(self.bonus_type, self.config.line_mult_ladder)
        changed = False
        for win in self.win_data["wins"]:
            direction, index = win["meta"]["direction"], win["meta"]["lineIndex"]
            self.line_steps[direction][index] += self.config.line_mult_step_per_run
            value = ladder[min(self.line_steps[direction][index], len(ladder) - 1)]
            if self.line_mults[direction][index] != value:
                self.line_mults[direction][index] = value
                changed = True
        if changed:
            update_line_mult_event(self)

    def reset_line_multipliers(self) -> None:
        """Every row and column back to 1x."""
        lines = {GridLines.ROW: max(self.config.num_rows), GridLines.COLUMN: self.config.num_reels}
        self.line_steps = {direction: [0] * count for direction, count in lines.items()}
        self.line_mults = {direction: [1] * count for direction, count in lines.items()}

    def set_mult_step(self, step: int) -> None:
        """Set the position on the paid-spin ladder, transmitting the multiplier if it changed."""
        ladder = self.config.mult_ladder
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
        """The number of scatters decides the bonus game: record the trigger and play it."""
        self.bonus_type = self.config.bonus_by_scatters[self.count_special_symbols(scatter_key)]
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
        """Set the free spins the bonus awards and transmit the trigger."""
        self.tot_fs = self.config.bonus_awards[self.bonus_type]
        bonus_trigger_event(self)
