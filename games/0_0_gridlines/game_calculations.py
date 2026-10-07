"""Game-specific calculations for the grid-line pays game."""

import random

from src.calculations.collapse import Collapse
from src.executables.executables import Executables


class GameCalculations(Executables, Collapse):
    """Helper calculations: symbol upgrades, wild positions and wild drops."""

    def apply_refine(self, name: str) -> str:
        """Return the symbol that `name` lands as at the current refine level.

        Level n means the first n symbols of config.refine_order have been upgraded. Each one
        lands as the next symbol up, so upgrades chain: at level 2, L5 -> L4 -> L3.
        """
        level = getattr(self, "refine_level", 0)
        if level <= 0:
            return name
        removed = self.config.refine_order[:level]
        while name in removed:
            name = self.config.refine_into[name]
        return name

    def get_wild_positions(self) -> list:
        """Positions of every wild on the board, in reel then row order."""
        positions = []
        for reel, _ in enumerate(self.board):
            for row, symbol in enumerate(self.board[reel]):
                if symbol.check_attribute("wild"):
                    positions.append({"reel": reel, "row": row})
        return positions

    def pick_wild_drop_positions(self, count: int) -> list:
        """Choose `count` random positions that hold a regular symbol."""
        candidates = []
        for reel, _ in enumerate(self.board):
            for row, symbol in enumerate(self.board[reel]):
                if not symbol.check_attribute("wild", "scatter", "blank"):
                    candidates.append({"reel": reel, "row": row})
        count = min(count, len(candidates))
        chosen = random.sample(candidates, count)
        return sorted(chosen, key=lambda pos: (pos["reel"], pos["row"]))

    def pick_start_wilds(self, count: int) -> list:
        """Choose `count` random board positions for the wilds a survival bonus starts with."""
        positions = [
            {"reel": reel, "row": row}
            for reel in range(self.config.num_reels)
            for row in range(self.config.num_rows[reel])
        ]
        chosen = random.sample(positions, min(count, len(positions)))
        return sorted(chosen, key=lambda pos: (pos["reel"], pos["row"]))
