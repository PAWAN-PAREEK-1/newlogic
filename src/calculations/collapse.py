"""Collapse without refill.

Winning symbols are removed, the symbols above them fall straight down, and nothing new
drops in from the reel strips. Every spin therefore ends after a bounded number of steps:
each step removes at least one symbol and the board only ever gets emptier.

This is the counterpart of tumble.py, which refills the board from the reel strip.
Use it as a mixin next to Executables:

    class GameCalculations(Executables, Collapse):
        ...

The board keeps its shape. Empty positions hold the blank symbol named in
`config.special_symbols["blank"]`.
"""

from copy import copy
from typing import Dict, List


class Collapse:
    """General class for collapse (no refill) game actions."""

    def get_blank_name(self) -> str:
        """Name of the symbol used for an empty board position."""
        return self.config.special_symbols["blank"][0]

    def is_blank(self, symbol) -> bool:
        """True if the symbol marks an empty board position."""
        return symbol.check_attribute("blank")

    def count_symbols_left(self) -> int:
        """Number of board positions that still hold a symbol."""
        return sum(1 for reel in self.board for symbol in reel if not self.is_blank(symbol))

    def collapse_board(self, spawn_symbols: List[Dict] = None) -> None:
        """Remove exploding symbols, spawn replacements and let everything fall.

        spawn_symbols: [{"reel", "row", "name"}, ...] - symbols created in an exploding
        position before the fall (e.g. the wild left in the centre of a winning run).
        A spawned symbol replaces whatever was in that position.

        After the call:
            self.board_before_collapse  board as it was evaluated
            self.exploded_positions     positions removed, in reel then row order
            self.spawned_symbols        [{"reel", "row", "name", "landingRow"}, ...]
            self.board                  board after the fall
        """
        spawn_symbols = spawn_symbols or []
        spawn_lookup = {(s["reel"], s["row"]): s["name"] for s in spawn_symbols}
        blank_name = self.get_blank_name()

        self.board_before_collapse = [copy(reel) for reel in self.board]
        self.exploded_positions = []
        self.spawned_symbols = []
        new_board = []

        for reel, _ in enumerate(self.board):
            survivors = []
            spawned_in_reel = []
            for row, symbol in enumerate(self.board[reel]):
                if symbol.explode:
                    self.exploded_positions.append({"reel": reel, "row": row})
                if (reel, row) in spawn_lookup:
                    survivors.append(self.create_symbol(spawn_lookup[(reel, row)]))
                    spawned_in_reel.append((len(survivors) - 1, row))
                elif symbol.explode or self.is_blank(symbol):
                    continue
                else:
                    survivors.append(symbol)

            num_rows = len(self.board[reel])
            empty = num_rows - len(survivors)
            new_board.append([self.create_symbol(blank_name) for _ in range(empty)] + survivors)
            for survivor_index, from_row in spawned_in_reel:
                self.spawned_symbols.append(
                    {
                        "reel": reel,
                        "row": from_row,
                        "name": spawn_lookup[(reel, from_row)],
                        "landingRow": empty + survivor_index,
                    }
                )

        self.board = new_board
        self.get_special_symbols_on_board()
