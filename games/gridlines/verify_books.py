"""Replay every published book from its events and check it against the game rules.

This is an independent check of the maths: it does not use the game's own win calculator
(src/calculations/gridlines.py) or collapse code. It rebuilds each round from the events a
frontend receives, re-evaluates every board with its own implementation of the rules in
readme.txt and compares the result with what the book says.

Checked for every book:
    * every winInfo event lists exactly the runs on the board, at the right multiplier and pay;
    * every collapseBoard event removes exactly the winning symbols and leaves a wild in the
      centre of each run;
    * the multiplier of a paid spin and the line multipliers of a bonus follow the rules;
    * the number of scatters decides the bonus game that is played;
    * wild drops, symbol upgrades and free-spin counts follow the rules of each bonus game;
    * a bonus is triggered exactly when three or more scatters are on the board;
    * the wins add up to the book's payoutMultiplier, which is a multiple of 0.1x and no
      larger than the mode's max win;
    * the payout in the book equals the payout in the published lookup table.

Usage (from the repository root, after the books have been generated):
    python -m games.gridlines.verify_books                  # all modes, all books
    python -m games.gridlines.verify_books --modes base     # some modes
    python -m games.gridlines.verify_books --limit 5000     # first N books of each mode
"""

import argparse
import io
import json
import os
import sys

import zstandard as zstd

if __package__ in (None, ""):
    import importlib

    _REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)
    __package__ = "games." + os.path.basename(
        os.path.dirname(os.path.abspath(__file__))
    )
    importlib.import_module(__package__)

from .game_config import GameConfig

WILD, SCATTER, BLANK = "W", "S", "X"
ROW_OFFSET = 1  # events send row = board row + 1 (the SDK convention)


class BookError(AssertionError):
    """A book does not follow the game rules."""


def check(condition: bool, message: str) -> None:
    if not condition:
        raise BookError(message)


def cell(position: dict) -> tuple:
    """(reel, row) on the board of a position sent in an event."""
    return position["reel"], position["row"] - ROW_OFFSET


def line_of(cells: list) -> tuple:
    """("row" | "column", index) of the row or column a run is in."""
    (reel, row), (next_reel, _) = cells[0], cells[1]
    return ("column", reel) if reel == next_reel else ("row", row)


def find_runs(grid: list, min_run: int) -> list:
    """All runs on `grid` (grid[reel][row] = symbol name) as (symbol, [(reel, row), ...]).

    Rows are read top to bottom, then reels left to right.
    """
    reels, rows = len(grid), len(grid[0])
    lines = [[(reel, row) for reel in range(reels)] for row in range(rows)]
    lines += [[(reel, row) for row in range(rows)] for reel in range(reels)]
    runs = []
    for line in lines:
        names = [grid[reel][row] for reel, row in line]
        regular = []
        for name in names:
            if name not in (WILD, SCATTER, BLANK) and name not in regular:
                regular.append(name)
        used = set()
        for symbol in regular:
            start = 0
            while start < len(names):
                if names[start] not in (symbol, WILD):
                    start += 1
                    continue
                end = start
                while end < len(names) and names[end] in (symbol, WILD):
                    end += 1
                if end - start >= min_run and symbol in names[start:end]:
                    runs.append((symbol, line[start:end]))
                    used.update(range(start, end))
                start = end
        start = 0
        while start < len(names):
            if names[start] != WILD:
                start += 1
                continue
            end = start
            while end < len(names) and names[end] == WILD:
                end += 1
            if end - start >= min_run and not used.intersection(range(start, end)):
                runs.append((WILD, line[start:end]))
            start = end
    return runs


def collapse(grid: list, exploding: set, new_wilds: set) -> list:
    """Remove exploding symbols, place the new wilds and let every reel fall."""
    new_grid = []
    for reel, column in enumerate(grid):
        survivors = []
        for row, name in enumerate(column):
            if (reel, row) in new_wilds:
                survivors.append(WILD)
            elif (reel, row) in exploding or name == BLANK:
                continue
            else:
                survivors.append(name)
        new_grid.append([BLANK] * (len(column) - len(survivors)) + survivors)
    return new_grid


class BookReplay:
    """Replays one book and raises BookError on the first rule it breaks."""

    def __init__(self, config, mode: str, conditions_by_criteria: dict, max_win: float):
        self.config = config
        self.mode = mode
        self.conditions_by_criteria = conditions_by_criteria
        self.max_win_cents = int(round(max_win * 100))
        self.pay = {
            key: int(round(value * 100)) for key, value in config.paytable.items()
        }

    def cents(self, symbol: str, kind: int, mult: int) -> int:
        """Win of one run in cents (a single run is never shown above the max win)."""
        return min(self.pay[(kind, symbol)] * mult, self.max_win_cents)

    def replay(self, book: dict) -> None:
        events = book["events"]
        conditions = self.conditions_by_criteria[book["criteria"]]
        check(
            [e["index"] for e in events] == list(range(len(events))),
            "event indexes are not 0..n-1",
        )
        check(
            events[0]["type"] in ("reveal", "primeSymbols"),
            "book does not start with a reveal",
        )
        check(events[-1]["type"] == "finalWin", "book does not end with finalWin")

        self.pos = 0
        self.events = events
        self.mult = 1
        self.step = 0
        self.ladder = self.config.mult_ladder
        self.line_mults = None  # {"row": [...], "column": [...]} while a bonus is played
        self.total = 0
        self.capped = False

        # ---- paid spin ----------------------------------------------------------------
        prime_level = conditions.get("refine_level", 0)
        if prime_level:
            prime = self.take("primeSymbols")
            allowed = prime_level if isinstance(prime_level, dict) else {prime_level: 1}
            check(prime["level"] in allowed, "prime level is not allowed in this mode")
            prime_level = prime["level"]
            removed = self.config.refine_order[:prime_level]
            check(
                prime["removedSymbols"] == removed,
                "primeSymbols lists the wrong symbols",
            )
            check(
                prime["landAs"] == self.config.refine_into[removed[-1]],
                "primeSymbols landAs is wrong",
            )
        else:
            check(self.peek() != "primeSymbols", "primeSymbols in a mode without it")
        reveal = self.take("reveal")
        check(
            reveal["gameType"] == self.config.basegame_type,
            "first reveal is not a base game reveal",
        )
        grid = self.grid_from(reveal)
        self.check_refined(grid, prime_level)
        if "wild_drop" in conditions:
            drop = self.take("wildDrop")
            check(
                len(drop["positions"]) in conditions["wild_drop"],
                "wild drop count is not allowed in this mode",
            )
            for reel, row in map(cell, drop["positions"]):
                check(
                    grid[reel][row] not in (WILD, SCATTER, BLANK),
                    "wild dropped on a wild or scatter",
                )
                grid[reel][row] = WILD
        else:
            check(self.peek() != "wildDrop", "wild drop in a mode without one")
        grid, spin_win = self.play_spin(grid)
        self.end_of_spin(spin_win)
        base_win = spin_win

        scatters = sum(name == SCATTER for column in grid for name in column)
        triggered = self.peek() == "freeSpinTrigger"
        check(
            triggered == (scatters >= 3),
            "bonus trigger does not match the scatter count",
        )
        free_win = 0
        if triggered:
            free_win = self.play_bonus(scatters, conditions)

        final = self.take("finalWin")
        check(self.pos == len(events), "events after finalWin")
        expected = min(base_win + free_win, self.max_win_cents)
        check(
            final["amount"] == expected,
            f"finalWin {final['amount']} != replayed {expected}",
        )
        check(
            book["payoutMultiplier"] == expected,
            f"payoutMultiplier {book['payoutMultiplier']} != {expected}",
        )
        check(expected % 10 == 0, "payout is not a multiple of 0.1x")
        check(
            self.capped == (base_win + free_win >= self.max_win_cents),
            "wincap event does not match the win",
        )

    # ---- event helpers --------------------------------------------------------------------

    def peek(self) -> str:
        return self.events[self.pos]["type"] if self.pos < len(self.events) else ""

    def take(self, event_type: str) -> dict:
        check(
            self.peek() == event_type,
            f"expected {event_type} at event {self.pos}, found {self.peek()!r}",
        )
        self.pos += 1
        return self.events[self.pos - 1]

    def grid_from(self, reveal: dict) -> list:
        grid = [[symbol["name"] for symbol in column] for column in reveal["board"]]
        check(
            len(grid) == self.config.num_reels, "reveal has the wrong number of reels"
        )
        check(
            all(len(col) == self.config.num_rows[i] for i, col in enumerate(grid)),
            "reveal has the wrong rows",
        )
        check(
            all(name != BLANK for column in grid for name in column),
            "reveal contains an empty position",
        )
        return grid

    def check_refined(self, grid: list, level: int) -> None:
        removed = set(self.config.refine_order[:level])
        check(
            not removed.intersection(n for col in grid for n in col),
            "board shows a symbol that was upgraded",
        )

    def expect_mult(self, value: int) -> None:
        """Consume an updateGlobalMult event if (and only if) the multiplier changes."""
        if value != self.mult:
            event = self.take("updateGlobalMult")
            check(
                event["globalMult"] == value,
                f"multiplier {event['globalMult']} != expected {value}",
            )
            self.mult = value
        else:
            check(
                self.peek() != "updateGlobalMult", "multiplier event without a change"
            )

    def set_step(self, step: int) -> None:
        """Move to a step of the multiplier ladder and expect the matching event."""
        self.step = step
        self.expect_mult(self.ladder[min(step, len(self.ladder) - 1)])

    # ---- line multipliers (bonus games) -----------------------------------------------------

    def line_mult(self, cells: list) -> int:
        """Multiplier of the row or column a run is in (1 in a paid spin)."""
        if self.line_mults is None:
            return 1
        direction, index = line_of(cells)
        return self.line_mults[direction][index]

    def start_lines(self, bonus: str) -> None:
        """A bonus starts with every row and column at 1x."""
        self.line_ladder = self.config.bonus_line_mult_ladder.get(
            bonus, self.config.line_mult_ladder
        )
        lines = {"row": max(self.config.num_rows), "column": self.config.num_reels}
        self.line_steps = {direction: [0] * count for direction, count in lines.items()}
        self.line_mults = {direction: [1] * count for direction, count in lines.items()}
        self.expect_lines()

    def step_lines(self, runs: list) -> None:
        """After a collapse every run moves its own line one step up the ladder."""
        before = {direction: list(values) for direction, values in self.line_mults.items()}
        for _, cells in runs:
            direction, index = line_of(cells)
            self.line_steps[direction][index] += self.config.line_mult_step_per_run
            step = min(self.line_steps[direction][index], len(self.line_ladder) - 1)
            self.line_mults[direction][index] = self.line_ladder[step]
        if self.line_mults != before:
            self.expect_lines()
        else:
            check(
                self.peek() != "updateLineMult",
                "line multiplier event without a change",
            )

    def expect_lines(self) -> None:
        event = self.take("updateLineMult")
        check(
            event["rows"] == self.line_mults["row"]
            and event["columns"] == self.line_mults["column"],
            "line multipliers are wrong",
        )

    # ---- one spin: evaluate, pay, collapse --------------------------------------------------

    def play_spin(self, grid: list) -> tuple:
        """Replay the collapse sequence of one spin. Returns (final grid, spin win in cents)."""
        spin_win = 0
        while True:
            runs = find_runs(grid, self.config.min_run)
            if not runs:
                check(self.peek() != "winInfo", "winInfo on a board without runs")
                break
            info = self.take("winInfo")
            expected = sorted(
                (
                    symbol,
                    len(cells),
                    self.cents(symbol, len(cells), self.mult * self.line_mult(cells)),
                    tuple(cells),
                )
                for symbol, cells in runs
            )
            found = sorted(
                (
                    w["symbol"],
                    w["kind"],
                    w["win"],
                    tuple(cell(p) for p in w["positions"]),
                )
                for w in info["wins"]
            )
            check(
                found == expected,
                f"winInfo at event {info['index']} does not match the board",
            )
            for w in info["wins"]:
                cells = [cell(p) for p in w["positions"]]
                check(
                    (w["meta"]["direction"], w["meta"]["lineIndex"]) == line_of(cells),
                    "win names the wrong row or column",
                )
                check(
                    w["meta"]["globalMult"] == self.mult
                    and w["meta"]["lineMultiplier"] == self.line_mult(cells)
                    and w["meta"]["multiplier"] == self.mult * self.line_mult(cells),
                    "win carries the wrong multiplier",
                )
                check(
                    w["meta"]["winWithoutMult"] == self.pay[(w["kind"], w["symbol"])],
                    "wrong paytable value",
                )
                centre = w["positions"][(len(w["positions"]) - 1) // 2]
                check(
                    w["meta"]["overlay"] == centre,
                    "overlay is not the centre of the run",
                )
            step_win = sum(win for _, _, win, _ in expected)
            check(
                info["totalWin"] == min(step_win, self.max_win_cents),
                "winInfo totalWin is wrong",
            )
            spin_win += step_win
            self.total += step_win
            banner = self.take("updateTumbleWin")
            check(
                banner["amount"] == min(spin_win, self.max_win_cents),
                "updateTumbleWin amount is wrong",
            )
            if self.total >= self.max_win_cents:
                if not self.capped:
                    self.take("wincap")
                    self.capped = True
                break

            exploding = {cell for _, cells in runs for cell in cells}
            centres = {cells[(len(cells) - 1) // 2] for _, cells in runs}
            event = self.take("collapseBoard")
            check(
                {cell(p) for p in event["explodingSymbols"]} == exploding,
                "wrong exploding symbols",
            )
            check(
                {cell(p) for p in event["newWilds"]} == centres,
                "wrong centre wilds",
            )
            grid = collapse(grid, exploding, centres)
            for p in event["newWilds"]:
                check(
                    grid[p["reel"]][p["landingRow"] - ROW_OFFSET] == WILD,
                    "landingRow of a new wild is wrong",
                )

            if self.line_mults is None:
                self.set_step(self.step + self.config.mult_step_per_run * len(runs))
            else:
                self.step_lines(runs)
        return grid, spin_win

    def end_of_spin(self, spin_win: int) -> None:
        if spin_win > 0 and not self.capped:
            check(self.take("setWin")["amount"] == spin_win, "setWin amount is wrong")
        total = self.take("setTotalWin")
        check(
            total["amount"] == min(self.total, self.max_win_cents),
            "setTotalWin amount is wrong",
        )

    # ---- bonus games ----------------------------------------------------------------------

    def play_bonus(self, scatters: int, conditions: dict) -> int:
        trigger = self.take("freeSpinTrigger")
        bonus = trigger["bonusType"]
        check(
            bonus == self.config.bonus_by_scatters[scatters],
            f"{scatters} scatters do not trigger the {bonus} bonus",
        )
        check(
            len(trigger["positions"]) == scatters, "trigger does not list every scatter"
        )
        award = self.config.bonus_awards[bonus]
        start_total = self.total
        self.set_step(0)  # the paid-spin multiplier goes back to 1x and stays there
        self.start_lines(bonus)

        check(trigger["totalFs"] == award, "wrong number of free spins awarded")
        self.play_free_spins(bonus, award)

        free_win = self.total - start_total
        end = self.take("freeSpinEnd")
        check(
            end["amount"] == min(free_win, self.max_win_cents),
            "freeSpinEnd amount is wrong",
        )
        return free_win

    def play_free_spins(self, bonus: str, spins: int) -> None:
        upgrades = bonus in self.config.bonus_upgrades
        level = 0
        for spin in range(spins):
            if self.capped:
                break
            update = self.take("updateFreeSpin")
            check(
                update["amount"] == spin and update["total"] == spins,
                "free spin counter is wrong",
            )
            reveal = self.take("reveal")
            check(
                reveal["gameType"] == self.config.freegame_type,
                "bonus reveal has the wrong game type",
            )
            grid = self.grid_from(reveal)
            check(
                all(name != SCATTER for col in grid for name in col),
                "scatter on a bonus board",
            )
            if upgrades:
                self.check_refined(grid, level)
            drop_weights = self.config.bonus_wild_drop.get(bonus)
            if drop_weights is not None:
                regular = sum(name != WILD for col in grid for name in col)
                if self.peek() == "wildDrop" or regular > 0:
                    drop = self.take("wildDrop")
                    check(
                        len(drop["positions"]) in drop_weights
                        or len(drop["positions"]) == regular,
                        "wild drop count is not allowed in this bonus",
                    )
                    for reel, row in map(cell, drop["positions"]):
                        check(grid[reel][row] != WILD, "wild dropped on a wild")
                        grid[reel][row] = WILD
            grid, spin_win = self.play_spin(grid)
            self.end_of_spin(spin_win)
            if (
                upgrades
                and spin_win > 0
                and level < len(self.config.refine_order)
                and not self.capped
            ):
                removed = self.config.refine_order[level]
                level += 1
                event = self.take("refineSymbol")
                check(
                    event["level"] == level
                    and event["removed"] == removed
                    and event["into"] == self.config.refine_into[removed]
                    and event["removedSymbols"] == self.config.refine_order[:level],
                    "refineSymbol event is wrong",
                )
            elif upgrades and self.peek() == "refineSymbol":
                level += 1
                self.take("refineSymbol")
        check(self.peek() != "updateFreeSpin", "more free spins than awarded")


def read_books(path: str):
    """Yield books from a .jsonl.zst file."""
    with open(path, "rb") as f:
        reader = zstd.ZstdDecompressor().stream_reader(f)
        for line in io.TextIOWrapper(reader, encoding="UTF-8"):
            line = line.strip()
            if line:
                yield json.loads(line)


def read_lookup(path: str) -> dict:
    """Return {book id: payout in cents} from a lookup table."""
    payouts = {}
    with open(path, "r", encoding="UTF-8") as f:
        for line in f:
            book_id, _, payout = line.strip().split(",")
            payouts[int(book_id)] = int(payout)
    return payouts


def verify_mode(config, bet_mode, limit: int = None) -> tuple:
    """Replay the books of one mode. Returns (books checked, list of error strings)."""
    mode = bet_mode.get_name()
    conditions = {d.get_criteria(): d._conditions for d in bet_mode.get_distributions()}
    replay = BookReplay(config, mode, conditions, bet_mode.get_wincap())
    lookup = read_lookup(os.path.join(config.publish_path, f"lookUpTable_{mode}_0.csv"))
    errors, count, seen = [], 0, set()
    for book in read_books(
        os.path.join(config.publish_path, f"books_{mode}.jsonl.zst")
    ):
        if limit is not None and count >= limit:
            break
        count += 1
        try:
            check(book["id"] not in seen, "duplicate book id")
            seen.add(book["id"])
            check(
                lookup.get(book["id"]) == book["payoutMultiplier"],
                "payout differs from the lookup table",
            )
            replay.replay(book)
        except BookError as err:
            if len(errors) < 10:
                errors.append(f"book {book['id']} ({book['criteria']}): {err}")
    if limit is None and count != len(lookup):
        errors.append(f"{count} books but {len(lookup)} lookup table rows")
    return count, errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay published books against the game rules"
    )
    parser.add_argument(
        "--modes", default=None, help="comma-separated bet modes (default: all)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="only check the first N books of each mode",
    )
    args = parser.parse_args()

    config = GameConfig()
    wanted = [m.strip() for m in args.modes.split(",")] if args.modes else None
    failed = False
    for bet_mode in config.bet_modes:
        if wanted is not None and bet_mode.get_name() not in wanted:
            continue
        count, errors = verify_mode(config, bet_mode, args.limit)
        status = "OK" if not errors else "FAILED"
        print(f"{bet_mode.get_name():<10} {count:>9,} books replayed  {status}")
        for line in errors:
            print("    " + line)
        failed = failed or bool(errors)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
