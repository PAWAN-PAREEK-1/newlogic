"""Evaluates and records wins for grid-line (run) pay games.

A win is a straight run of `min_run` or more like symbols in one row or one column,
anywhere on the grid. Diagonals never count and the run does not have to start on the
first reel.

How this differs from the other calculators in this folder:
    lines.py    - fixed paylines, always read from the first reel
    ways.py     - like symbols on consecutive reels from the first reel, any row
    scatter.py  - symbol count anywhere on the board, position is irrelevant
    cluster.py  - any connected group, shape is irrelevant, pays on group size
    gridlines   - straight horizontal or vertical runs, pays on run length

Wild rules
    * A wild continues the run of any paying symbol on either side of it.
    * One wild can belong to two runs in the same line (`A A W B B` pays A and B) and to a
      row run and a column run at the same time.
    * A run made only of wilds pays the wild's own paytable entry, and only when it is not
      part of a longer run of a regular symbol in that line.

Scatters, blanks and every other non-paying symbol break a run.
"""

from typing import Dict, List

from src.calculations.symbol import Symbol
from src.config.config import Config


class GridLines:
    """Collection of functions to handle grid-line (run) pay games."""

    ROW = "row"
    COLUMN = "column"

    @staticmethod
    def get_grid_lines(board: List[List[Symbol]]) -> List[dict]:
        """Every row and column of the board as an ordered list of positions.

        Rows are read left to right, columns top to bottom. Boards with a different
        number of rows per reel are supported: a row is split wherever a reel is too
        short to contain it.
        """
        grid_lines = []
        max_rows = max(len(reel) for reel in board)
        for row in range(max_rows):
            segment = []
            for reel, _ in enumerate(board):
                if row < len(board[reel]):
                    segment.append({"reel": reel, "row": row})
                elif segment:
                    grid_lines.append({"direction": GridLines.ROW, "index": row, "positions": segment})
                    segment = []
            if segment:
                grid_lines.append({"direction": GridLines.ROW, "index": row, "positions": segment})

        for reel, _ in enumerate(board):
            grid_lines.append(
                {
                    "direction": GridLines.COLUMN,
                    "index": reel,
                    "positions": [{"reel": reel, "row": row} for row in range(len(board[reel]))],
                }
            )
        return grid_lines

    @staticmethod
    def classify_symbol(symbol: Symbol, wild_key: str = "wild") -> str:
        """Return 'wild', 'pay' or 'block' for a symbol."""
        if symbol.check_attribute(wild_key):
            return "wild"
        if symbol.defn.is_paying and not symbol.defn.special:
            return "pay"
        return "block"

    @staticmethod
    def get_centre_position(positions: List[Dict]) -> Dict:
        """Middle position of a run (the earlier of the two middle cells for even lengths)."""
        centre = positions[(len(positions) - 1) // 2]
        return {"reel": centre["reel"], "row": centre["row"]}

    @staticmethod
    def find_runs(
        board: List[List[Symbol]],
        min_run: int = 3,
        wild_key: str = "wild",
        wild_sym: str = "W",
    ) -> List[dict]:
        """Return every run of `min_run` or more like symbols, wilds included.

        Each run is {"symbol", "kind", "positions", "direction", "index"}. Runs are returned
        in a fixed order (rows top to bottom, then columns left to right; inside a line in
        the order the symbols first appear) so results are reproducible.
        """
        runs = []
        for grid_line in GridLines.get_grid_lines(board):
            positions = grid_line["positions"]
            length = len(positions)
            if length < min_run:
                continue
            symbols = [board[p["reel"]][p["row"]] for p in positions]
            kinds = [GridLines.classify_symbol(s, wild_key) for s in symbols]

            ordered_names = []
            for sym, kind in zip(symbols, kinds):
                if kind == "pay" and sym.name not in ordered_names:
                    ordered_names.append(sym.name)

            covered = [False] * length
            for name in ordered_names:
                start = 0
                while start < length:
                    if kinds[start] == "wild" or (kinds[start] == "pay" and symbols[start].name == name):
                        end = start
                        has_symbol = False
                        while end < length and (
                            kinds[end] == "wild" or (kinds[end] == "pay" and symbols[end].name == name)
                        ):
                            if kinds[end] == "pay":
                                has_symbol = True
                            end += 1
                        if has_symbol and end - start >= min_run:
                            runs.append(
                                {
                                    "symbol": name,
                                    "kind": end - start,
                                    "positions": [dict(p) for p in positions[start:end]],
                                    "direction": grid_line["direction"],
                                    "index": grid_line["index"],
                                }
                            )
                            for idx in range(start, end):
                                covered[idx] = True
                        start = end
                    else:
                        start += 1

            # Runs of wilds only: paid when no regular symbol run already uses them.
            start = 0
            while start < length:
                if kinds[start] == "wild":
                    end = start
                    while end < length and kinds[end] == "wild":
                        end += 1
                    if end - start >= min_run and not any(covered[start:end]):
                        runs.append(
                            {
                                "symbol": wild_sym,
                                "kind": end - start,
                                "positions": [dict(p) for p in positions[start:end]],
                                "direction": grid_line["direction"],
                                "index": grid_line["index"],
                            }
                        )
                    start = end
                else:
                    start += 1

        return runs

    @staticmethod
    def evaluate_runs(
        config: Config,
        board: List[List[Symbol]],
        runs: List[dict],
        global_multiplier: int = 1,
        mark_explode: bool = True,
    ) -> dict:
        """Price every run from the paytable and flag winning symbols with `explode`.

        Runs whose (kind, symbol) is not in the paytable are ignored.
        """
        return_data = {"totalWin": 0, "wins": []}
        for run in runs:
            key = (run["kind"], run["symbol"])
            if key not in config.paytable:
                continue
            base_win = config.paytable[key]
            win = round(base_win * global_multiplier, 2)
            centre = GridLines.get_centre_position(run["positions"])
            return_data["wins"].append(
                {
                    "symbol": run["symbol"],
                    "kind": run["kind"],
                    "win": win,
                    "positions": run["positions"],
                    "meta": {
                        "direction": run["direction"],
                        "lineIndex": run["index"],
                        "globalMult": int(global_multiplier),
                        "winWithoutMult": base_win,
                        "overlay": centre,
                    },
                }
            )
            return_data["totalWin"] += win
            if mark_explode:
                for pos in run["positions"]:
                    board[pos["reel"]][pos["row"]].explode = True

        return_data["totalWin"] = round(return_data["totalWin"], 2)
        return return_data

    @staticmethod
    def get_gridline_wins(
        config: Config,
        board: List[List[Symbol]],
        global_multiplier: int = 1,
        min_run: int = 3,
        wild_key: str = "wild",
        wild_sym: str = "W",
        mark_explode: bool = True,
    ) -> dict:
        """Event-ready win information for the current board."""
        runs = GridLines.find_runs(board, min_run=min_run, wild_key=wild_key, wild_sym=wild_sym)
        return GridLines.evaluate_runs(
            config, board, runs, global_multiplier=global_multiplier, mark_explode=mark_explode
        )

    @staticmethod
    def get_winning_positions(win_data: dict) -> List[Dict]:
        """Unique winning positions of a win_data block, in reel then row order."""
        seen = set()
        for win in win_data["wins"]:
            for pos in win["positions"]:
                seen.add((pos["reel"], pos["row"]))
        return [{"reel": reel, "row": row} for reel, row in sorted(seen)]

    @staticmethod
    def get_centre_positions(win_data: dict) -> List[Dict]:
        """Unique centre position of every winning run, in reel then row order."""
        seen = set()
        for win in win_data["wins"]:
            centre = win["meta"]["overlay"]
            seen.add((centre["reel"], centre["row"]))
        return [{"reel": reel, "row": row} for reel, row in sorted(seen)]

    @staticmethod
    def record_gridline_wins(gamestate) -> None:
        """Force-file description keys."""
        for win in gamestate.win_data["wins"]:
            gamestate.record(
                {
                    "kind": win["kind"],
                    "symbol": win["symbol"],
                    "gametype": gamestate.gametype,
                }
            )
