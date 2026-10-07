"""Replay every published book from its events and check it against the game rules.

This is an independent check of the maths: it does not use the game's own win calculator
(src/calculations/gridlines.py) or collapse code. It rebuilds each round from the events a
frontend receives, re-evaluates every board with its own implementation of the rules in
readme.txt and compares the result with what the book says.

Checked for every book:
    * every winInfo event lists exactly the runs on the board, at the right multiplier and pay;
    * every collapseBoard event removes exactly the winning symbols and leaves a wild in the
      centre of each run;
    * the multiplier follows the rules of the base game and of each bonus game;
    * wild drops, sticky wilds, symbol upgrades, free-spin counts and lives follow the rules;
    * a bonus is triggered exactly when three or more scatters are on the board;
    * the wins add up to the book's payoutMultiplier, which is a multiple of 0.1x and no
      larger than the mode's max win;
    * the payout in the book equals the payout in the published lookup table.

Usage (from the repository root, after the books have been generated):
    python -m games.0_0_gridlines.verify_books                  # all modes, all books
    python -m games.0_0_gridlines.verify_books --modes base     # some modes
    python -m games.0_0_gridlines.verify_books --limit 5000     # first N books of each mode
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
    __package__ = "games." + os.path.basename(os.path.dirname(os.path.abspath(__file__)))
    importlib.import_module(__package__)

from .game_config import GameConfig

WILD, SCATTER, BLANK = "W", "S", "X"


class BookError(AssertionError):
    """A book does not follow the game rules."""


def check(condition: bool, message: str) -> None:
    if not condition:
        raise BookError(message)


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
        self.pay = {key: int(round(value * 100)) for key, value in config.paytable.items()}

    def cents(self, symbol: str, kind: int, mult: int) -> int:
        """Win of one run in cents (a single run is never shown above the max win)."""
        return min(self.pay[(kind, symbol)] * mult, self.max_win_cents)

    def replay(self, book: dict) -> None:
        events = book["events"]
        conditions = self.conditions_by_criteria[book["criteria"]]
        check([e["index"] for e in events] == list(range(len(events))), "event indexes are not 0..n-1")
        check(events[0]["type"] in ("reveal", "primeSymbols"), "book does not start with a reveal")
        check(events[-1]["type"] == "finalWin", "book does not end with finalWin")

        self.pos = 0
        self.events = events
        self.mult = 1
        self.step = 0
        self.ladder = self.config.mult_ladder
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
            check(prime["removedSymbols"] == removed, "primeSymbols lists the wrong symbols")
            check(prime["landAs"] == self.config.refine_into[removed[-1]], "primeSymbols landAs is wrong")
        else:
            check(self.peek() != "primeSymbols", "primeSymbols in a mode without it")
        reveal = self.take("reveal")
        check(reveal["gameType"] == self.config.basegame_type, "first reveal is not a base game reveal")
        grid = self.grid_from(reveal)
        self.check_refined(grid, prime_level)
        if "wild_drop" in conditions:
            drop = self.take("wildDrop")
            check(len(drop["positions"]) in conditions["wild_drop"], "wild drop count is not allowed in this mode")
            for p in drop["positions"]:
                check(grid[p["reel"]][p["row"]] not in (WILD, SCATTER, BLANK), "wild dropped on a wild or scatter")
                grid[p["reel"]][p["row"]] = WILD
        else:
            check(self.peek() != "wildDrop", "wild drop in a mode without one")
        grid, spin_win = self.play_spin(grid)
        self.end_of_spin(spin_win)
        base_win = spin_win

        scatters = sum(name == SCATTER for column in grid for name in column)
        triggered = self.peek() == "freeSpinTrigger"
        check(triggered == (scatters >= 3), "bonus trigger does not match the scatter count")
        free_win = 0
        if triggered:
            free_win = self.play_bonus(scatters, conditions)

        final = self.take("finalWin")
        check(self.pos == len(events), "events after finalWin")
        expected = min(base_win + free_win, self.max_win_cents)
        check(final["amount"] == expected, f"finalWin {final['amount']} != replayed {expected}")
        check(book["payoutMultiplier"] == expected, f"payoutMultiplier {book['payoutMultiplier']} != {expected}")
        check(expected % 10 == 0, "payout is not a multiple of 0.1x")
        check(self.capped == (base_win + free_win >= self.max_win_cents), "wincap event does not match the win")

    # ---- event helpers --------------------------------------------------------------------

    def peek(self) -> str:
        return self.events[self.pos]["type"] if self.pos < len(self.events) else ""

    def take(self, event_type: str) -> dict:
        check(self.peek() == event_type, f"expected {event_type} at event {self.pos}, found {self.peek()!r}")
        self.pos += 1
        return self.events[self.pos - 1]

    def grid_from(self, reveal: dict) -> list:
        grid = [[symbol["name"] for symbol in column] for column in reveal["board"]]
        check(len(grid) == self.config.num_reels, "reveal has the wrong number of reels")
        check(all(len(col) == self.config.num_rows[i] for i, col in enumerate(grid)), "reveal has the wrong rows")
        check(all(name != BLANK for column in grid for name in column), "reveal contains an empty position")
        return grid

    def check_refined(self, grid: list, level: int) -> None:
        removed = set(self.config.refine_order[:level])
        check(not removed.intersection(n for col in grid for n in col), "board shows a symbol that was upgraded")

    def expect_mult(self, value: int) -> None:
        """Consume an updateGlobalMult event if (and only if) the multiplier changes."""
        if value != self.mult:
            event = self.take("updateGlobalMult")
            check(event["globalMult"] == value, f"multiplier {event['globalMult']} != expected {value}")
            self.mult = value
        else:
            check(self.peek() != "updateGlobalMult", "multiplier event without a change")

    def set_step(self, step: int) -> None:
        """Move to a step of the multiplier ladder and expect the matching event."""
        self.step = step
        self.expect_mult(self.ladder[min(step, len(self.ladder) - 1)])

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
                (symbol, len(cells), self.cents(symbol, len(cells), self.mult), tuple(cells)) for symbol, cells in runs
            )
            found = sorted(
                (w["symbol"], w["kind"], w["win"], tuple((p["reel"], p["row"]) for p in w["positions"]))
                for w in info["wins"]
            )
            check(found == expected, f"winInfo at event {info['index']} does not match the board")
            for w in info["wins"]:
                check(w["meta"]["globalMult"] == self.mult, "win carries the wrong multiplier")
                check(w["meta"]["winWithoutMult"] == self.pay[(w["kind"], w["symbol"])], "wrong paytable value")
                centre = w["positions"][(len(w["positions"]) - 1) // 2]
                check(w["meta"]["overlay"] == centre, "overlay is not the centre of the run")
            step_win = sum(win for _, _, win, _ in expected)
            check(info["totalWin"] == min(step_win, self.max_win_cents), "winInfo totalWin is wrong")
            spin_win += step_win
            self.total += step_win
            banner = self.take("updateTumbleWin")
            check(banner["amount"] == min(spin_win, self.max_win_cents), "updateTumbleWin amount is wrong")
            if self.total >= self.max_win_cents:
                if not self.capped:
                    self.take("wincap")
                    self.capped = True
                break

            exploding = {cell for _, cells in runs for cell in cells}
            centres = {cells[(len(cells) - 1) // 2] for _, cells in runs}
            event = self.take("collapseBoard")
            check({(p["reel"], p["row"]) for p in event["explodingSymbols"]} == exploding, "wrong exploding symbols")
            check({(p["reel"], p["row"]) for p in event["newWilds"]} == centres, "wrong centre wilds")
            grid = collapse(grid, exploding, centres)
            for p in event["newWilds"]:
                check(grid[p["reel"]][p["landingRow"]] == WILD, "landingRow of a new wild is wrong")

            self.set_step(self.step + self.config.mult_step_per_run * len(runs))
        return grid, spin_win

    def end_of_spin(self, spin_win: int) -> None:
        if spin_win > 0 and not self.capped:
            check(self.take("setWin")["amount"] == spin_win, "setWin amount is wrong")
        total = self.take("setTotalWin")
        check(total["amount"] == min(self.total, self.max_win_cents), "setTotalWin amount is wrong")

    # ---- bonus games ----------------------------------------------------------------------

    def play_bonus(self, scatters: int, conditions: dict) -> int:
        trigger = self.take("freeSpinTrigger")
        bonus = trigger["bonusType"]
        check(bonus in conditions["bonus_weights"], f"bonus type {bonus} is not possible for this criteria")
        check(len(trigger["positions"]) == scatters, "trigger does not list every scatter")
        award = self.config.bonus_awards[bonus][scatters]
        start_total = self.total
        self.ladder = self.config.bonus_mult_ladder.get(bonus, self.config.mult_ladder)
        self.set_step(0)  # every bonus starts at 1x

        if bonus == "survival":
            check(trigger["lives"] == award and trigger["totalFs"] == 0, "wrong number of lives awarded")
            self.play_survival(award)
        else:
            check(trigger["totalFs"] == award and trigger["lives"] == 0, "wrong number of free spins awarded")
            self.play_fixed_spins(bonus, award)

        free_win = self.total - start_total
        end = self.take("freeSpinEnd")
        check(end["amount"] == min(free_win, self.max_win_cents), "freeSpinEnd amount is wrong")
        return free_win

    def play_fixed_spins(self, bonus: str, spins: int) -> None:
        level = 0
        for spin in range(1, spins + 1):
            if self.capped:
                break
            update = self.take("updateFreeSpin")
            check(update["amount"] == spin and update["total"] == spins, "free spin counter is wrong")
            if bonus == "refine":
                self.set_step(level * self.config.refine_steps_per_level)
            reveal = self.take("reveal")
            check(reveal["gameType"] == self.config.freegame_type, "bonus reveal has the wrong game type")
            grid = self.grid_from(reveal)
            check(all(name != SCATTER for col in grid for name in col), "scatter on a bonus board")
            if bonus == "refine":
                self.check_refined(grid, level)
            drop_weights = self.config.bonus_wild_drop.get(bonus)
            if drop_weights is not None:
                regular = sum(name != WILD for col in grid for name in col)
                if self.peek() == "wildDrop" or regular > 0:
                    drop = self.take("wildDrop")
                    check(
                        len(drop["positions"]) in drop_weights or len(drop["positions"]) == regular,
                        "wild drop count is not allowed in this bonus",
                    )
                    for p in drop["positions"]:
                        check(grid[p["reel"]][p["row"]] != WILD, "wild dropped on a wild")
                        grid[p["reel"]][p["row"]] = WILD
            grid, spin_win = self.play_spin(grid)
            self.end_of_spin(spin_win)
            if bonus == "refine" and spin_win > 0 and level < len(self.config.refine_order) and not self.capped:
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
            elif bonus == "refine" and self.peek() == "refineSymbol":
                level += 1
                self.take("refineSymbol")
        check(self.peek() != "updateFreeSpin", "more free spins than awarded")

    def play_survival(self, lives: int) -> None:
        sticky = None
        spin = 0
        while lives > 0 and spin < self.config.survival_max_spins and not self.capped:
            spin += 1
            update = self.take("updateLives")
            check(update["lives"] == lives and update["spin"] == spin and not update["lostLife"], "lives event is wrong")
            if sticky is None:
                carried = self.take("stickyWilds") if self.config.survival_start_wilds > 0 else {"positions": []}
                check(len(carried["positions"]) == self.config.survival_start_wilds, "wrong number of starting wilds")
                sticky = {(p["reel"], p["row"]) for p in carried["positions"]}
            elif sticky:
                carried = self.take("stickyWilds")
                check({(p["reel"], p["row"]) for p in carried["positions"]} == sticky, "sticky wilds were not carried")
            else:
                check(self.peek() != "stickyWilds", "sticky wilds event without wilds")
            reveal = self.take("reveal")
            grid = self.grid_from(reveal)
            check(all(grid[reel][row] == WILD for reel, row in sticky), "a sticky wild is missing from the board")
            check(all(name != SCATTER for col in grid for name in col), "scatter on a bonus board")
            grid, spin_win = self.play_spin(grid)
            self.end_of_spin(spin_win)
            if spin_win == 0:
                lives -= 1
                lost = self.take("updateLives")
                check(lost["lives"] == lives and lost["lostLife"], "life was not taken after a losing spin")
                self.set_step(0)
            sticky = {(reel, row) for reel, col in enumerate(grid) for row, name in enumerate(col) if name == WILD}
        check(self.peek() != "updateLives", "survival bonus continues after it should have ended")


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
    for book in read_books(os.path.join(config.publish_path, f"books_{mode}.jsonl.zst")):
        if limit is not None and count >= limit:
            break
        count += 1
        try:
            check(book["id"] not in seen, "duplicate book id")
            seen.add(book["id"])
            check(lookup.get(book["id"]) == book["payoutMultiplier"], "payout differs from the lookup table")
            replay.replay(book)
        except BookError as err:
            if len(errors) < 10:
                errors.append(f"book {book['id']} ({book['criteria']}): {err}")
    if limit is None and count != len(lookup):
        errors.append(f"{count} books but {len(lookup)} lookup table rows")
    return count, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay published books against the game rules")
    parser.add_argument("--modes", default=None, help="comma-separated bet modes (default: all)")
    parser.add_argument("--limit", type=int, default=None, help="only check the first N books of each mode")
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
