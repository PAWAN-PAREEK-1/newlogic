"""Overrides of universal state.py functions for the grid-line pays game."""

from .game_executables import GameExecutables


class GameStateOverride(GameExecutables):
    """
    This class is is used to override or extend universal state.py functions.
    e.g: A specific game may have custom book properties to reset
    """

    def reset_book(self):
        # Reset global values used across multiple projects
        super().reset_book()
        # Reset parameters relevant to local game only
        self.bonus_type = None
        self.lives = 0
        self.sticky_wilds = []
        # Prime spin starts with symbols already upgraded; every other mode starts at level 0.
        self.refine_level = self.get_current_distribution_conditions().get("refine_level", 0)

    def reset_fs_spin(self):
        super().reset_fs_spin()
        # Every bonus game starts from the same clean state, whichever mode triggered it.
        self.refine_level = 0
        self.sticky_wilds = []
        self.reset_multiplier()

    def assign_special_sym_function(self):
        self.special_symbol_functions = {}

    def create_symbol(self, name: str):
        """Create a symbol, applying the active symbol upgrades."""
        return super().create_symbol(self.apply_refine(name))

    def get_current_distribution_conditions(self) -> dict:
        """Conditions of the active criteria ({} before a bet mode has been set)."""
        if not hasattr(self, "betmode"):
            return {}
        return super().get_current_distribution_conditions()

    def check_repeat(self):
        """A round is kept only if it matches its criteria.

        * fixed-win criteria ("0", "wincap") must pay exactly that amount;
        * every other criteria must pay something;
        * bonus criteria must have triggered a bonus (checked by the SDK).
        """
        super().check_repeat()
        if self.repeat is False:
            win_criteria = self.get_current_betmode_distributions().get_win_criteria()
            if win_criteria is None and self.final_win == 0:
                self.repeat = True
