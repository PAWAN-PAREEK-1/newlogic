"""Pre-flight check for the Rust optimizer: catch impossible fence targets in seconds.

The Rust optimizer only finds out a criteria ("fence") target is unreachable after grinding
through hundreds of thousands of attempts - and it builds the expensive fences first. This check
reads exactly the same inputs (library/configs/math_config.json, the mode's lookup table and
force_record_<mode>.json), resolves fences and assigns books with the same rules, and reports
every fence before the Rust run starts. It never writes or changes any table.

ERRORS (the Rust optimizer cannot succeed - the run is stopped):
  * a fence matches no books;
  * a fixed-payout fence (wincap, 0, ...) whose payout is not in the lookup table;
  * the fixed hit rates use up all probability (nothing left for hr="x" / "0" fences);
  * a fence's target average win is outside the range of its books' payouts.

WARNINGS (the optimizer may need a very large number of attempts, and can fail to converge):
  * almost none (< 1e-4) of the fence's scaling-weighted payouts lie above (or below) the target.
    The optimizer needs random candidates on both sides of the target. Measured on expwilds:
    ante basegame (~1e-6) failed with 100k books but optimized with 1M books - so this means
    "slow / may fail", not "impossible".

Usage:
    python -m optimization_program.optimization_precheck games/expwilds/library base,ante,superante
From Python (run_script.py calls this automatically before every Rust run):
    precheck_mode(library_path, mode)          # raises PrecheckError on errors
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# Below this share of scaling-weighted payouts on one side of a target, warn (see docstring).
HARD_TARGET_SHARE = 1e-4


class PrecheckError(RuntimeError):
    """A fence target the Rust optimizer provably cannot meet."""


@dataclass
class Fence:
    """One optimization criteria, resolved exactly like the Rust parse_fence_info."""

    name: str
    hr: float
    rtp: float
    avg_win: float
    search: list
    opposite: bool
    win_range_start: float
    win_range_end: float
    win_type: bool
    dresses: list = field(default_factory=list)  # [(lo, hi, scale)]
    book_idx: np.ndarray | None = None


def _num(value, default):
    return default if value is None else float(value)


def _scale(scale_factor: str, prob: float) -> float:
    """Dress multiplier as a number: "r" suffix = factor * U(0,1), applied with probability prob."""
    text = str(scale_factor).strip()
    try:
        factor = float(text[:-1]) * 0.5 if text.endswith("r") else float(text)
    except ValueError:
        factor = 1.0
    return prob * factor + (1.0 - prob)


def parse_fences(math_config: dict, mode: str) -> tuple[list[Fence], float, float]:
    """Fences of `mode`, with hr / rtp / avg_win resolved like the Rust run_farm."""
    bet_mode = next(b for b in math_config["bet_modes"] if b["bet_mode"] == mode)
    bet_amount = float(bet_mode["cost"])
    fence_json = next(f for f in math_config["fences"] if f["bet_mode"] == mode)["fences"]
    dress_json = next(d for d in math_config["dresses"] if d["bet_mode"] == mode)["dresses"]

    fences: list[Fence] = []
    total_prob = 0.0
    for fj in fence_json:
        avg_win = _num(fj.get("avg_win"), -1.0)
        hr_str = fj.get("hr") if fj.get("hr") is not None else "-1"
        hr = -1.0 if hr_str == "x" else float(hr_str)
        rtp = _num(fj.get("rtp"), -1.0)
        if hr_str != "x" and hr > 0 and rtp > 0:
            avg_win = hr * rtp
        if hr_str != "x" and hr > 0 and avg_win > 0:
            rtp = avg_win / hr
        if hr_str != "x" and hr < 0 and rtp > 0 and avg_win > 0:
            hr = avg_win / rtp / bet_amount
        if hr > 0:
            total_prob += 1.0 / hr

        ic = fj["identity_condition"]
        start, end = float(ic["win_range_start"]), float(ic["win_range_end"])
        fence = Fence(
            name=fj["name"], hr=hr, rtp=rtp, avg_win=avg_win,
            search=[(s["name"], s["value"]) for s in ic.get("search", [])],
            opposite=bool(ic.get("opposite", False)),
            win_range_start=start, win_range_end=end,
            win_type=start > -1.0 and end == start,
        )
        for dj in dress_json:
            if dj["fence"] == fence.name:
                lo, hi = dj.get("identity_condition_win_range") or [0.0, 0.0]
                prob = 1.0 if dj.get("prob") is None else float(dj["prob"])
                fence.dresses.append((float(lo), float(hi), _scale(dj["scale_factor"], prob)))
        fences.append(fence)

    if any(f.hr == -1.0 for f in fences) and total_prob >= 1.0:
        raise PrecheckError(
            f"[{mode}] the fixed hit rates already add up to probability {total_prob:.6f} >= 1, "
            f"so nothing is left for the hr='x' / '0' fences. Lower some criteria hit rates (raise hr)."
        )
    for fence in fences:
        if fence.hr == -1.0:
            fence.hr = 1.0 / (1.0 - total_prob)
            fence.avg_win = fence.hr * fence.rtp
    return fences, bet_amount, float(bet_mode["rtp"])


def assign_books(fences: list[Fence], ids: np.ndarray, cents: np.ndarray, forces: list, mode: str) -> None:
    """Give every fence its books with the same rules and order as the Rust sort_wins_by_parameter."""
    wins = cents / 100.0
    remaining = np.ones(len(ids), dtype=bool)
    pos_of_id = pd.Series(np.arange(len(ids)), index=ids)

    for fence in fences:
        if fence.win_type:
            hit = wins != fence.win_range_start if fence.opposite else wins == fence.win_range_start
            members = remaining & hit
            if not np.any(np.abs(wins - fence.avg_win) < 1e-9):
                raise PrecheckError(
                    f"[{mode}] fence '{fence.name}': payout {fence.avg_win} is not in the lookup table "
                    f"(the Rust optimizer panics on this). Simulate more books or fix av_win/search_conditions."
                )
        elif not fence.search and fence.win_range_start == -1.0 and not fence.opposite:
            members = remaining.copy()  # catch-all fence
        elif (
            not fence.search
            and not fence.opposite
            and fence.win_range_start > -1.0
            and fence.win_range_end > fence.win_range_start
        ):
            # payout-range fence: remaining books with start < win <= end (main.rs rule)
            members = remaining & (wins > fence.win_range_start) & (wins <= fence.win_range_end)
        else:
            book_ids = []
            for option in forces:
                option_keys = {(s["name"], s["value"]) for s in option["search"]}
                ok = all(key in option_keys for key in fence.search if key[1] != "None")
                if fence.opposite:
                    ok = not ok
                if ok:
                    book_ids.extend(option["bookIds"])
            members = np.zeros(len(ids), dtype=bool)
            if book_ids:
                known = pos_of_id.reindex(np.unique(book_ids)).dropna().to_numpy(dtype=np.int64)
                members[known] = True
            members &= remaining

        fence.book_idx = np.flatnonzero(members)
        remaining &= ~members
        if fence.book_idx.size == 0:
            raise PrecheckError(
                f"[{mode}] fence '{fence.name}' matched 0 books after earlier fences took theirs "
                f"(search={fence.search}, range={fence.win_range_start}..{fence.win_range_end})."
            )


@dataclass
class FenceReport:
    name: str
    hr: float
    target: float  # average payout the optimizer must hit inside this fence
    books: int
    min_payout: float
    max_payout: float
    scaled_mean: float  # average payout of the scaling-weighted distinct payouts
    share_above: float  # scaling-weighted share of payouts above the target
    share_below: float
    status: str  # "ok" | "warning" | "error"
    message: str


def check_fence(fence: Fence, cents: np.ndarray, bet: float) -> FenceReport:
    payouts = cents[fence.book_idx] / 100.0
    if fence.win_type:
        return FenceReport(fence.name, fence.hr, fence.avg_win, len(payouts), payouts.min(), payouts.max(),
                           fence.avg_win, 0.0, 0.0, "ok", "fixed payout")
    x = np.unique(payouts)
    target = fence.avg_win * bet
    # Rust candidates are smooth weights per distinct payout, multiplied by the scaling dresses.
    w = np.ones_like(x)
    for lo, hi, scale in fence.dresses:
        w[(x >= lo) & (x <= hi)] *= scale
    w /= w.sum()
    share_above, share_below = float(w[x > target].sum()), float(w[x < target].sum())
    report = FenceReport(fence.name, fence.hr, target, len(payouts), float(x.min()), float(x.max()),
                         float(w @ x), share_above, share_below, "ok", "")
    if not (x.min() < target < x.max()):
        report.status = "error"
        report.message = (f"target average payout {target:,.4f} is outside this fence's payouts "
                          f"{x.min():,.2f}..{x.max():,.2f} - impossible. Target = hr x rtp x cost "
                          f"= {fence.hr:g} x {fence.rtp:g} x {bet:g} (av_win is in multiples of the bet COST).")
    elif min(share_above, share_below) < HARD_TARGET_SHARE:
        side = "above" if share_above < share_below else "below"
        report.status = "warning"
        report.message = (f"only {min(share_above, share_below):.1e} of the scaling-weighted payouts lie {side} the "
                          f"target {target:,.2f} (scaled average {report.scaled_mean:,.2f}). The optimizer may need a "
                          f"very large number of attempts and can fail to converge (more books help) - if it does, "
                          f"move the target toward the scaled average or relax the scaling around it.")
    return report


def precheck_mode(library_path: str, mode: str, verbose: bool = True) -> list[FenceReport]:
    """Check one bet mode. Returns the per-fence reports; raises PrecheckError on errors."""
    start = time.time()
    with open(os.path.join(library_path, "configs", "math_config.json"), encoding="utf-8") as f:
        math_config = json.load(f)
    fences, bet, _ = parse_fences(math_config, mode)
    table = pd.read_csv(os.path.join(library_path, "lookup_tables", f"lookUpTable_{mode}.csv"),
                        header=None, names=["id", "weight", "win"], dtype=np.int64)
    ids, cents = table["id"].to_numpy(), table["win"].to_numpy()
    with open(os.path.join(library_path, "forces", f"force_record_{mode}.json"), encoding="utf-8") as f:
        forces = json.load(f)
    assign_books(fences, ids, cents, forces, mode)

    reports = [check_fence(fence, cents, bet) for fence in fences]
    if verbose:
        print(f"\nOptimizer pre-check: {mode} (cost {bet:g}, {len(ids):,} books, {time.time() - start:.1f}s)")
        print(f"  {'criteria':<12}{'hr':>12}{'target avg':>14}{'payouts':>22}{'scaled avg':>13}  status")
        for r in reports:
            span = f"{r.min_payout:,.2f}..{r.max_payout:,.2f}"
            print(f"  {r.name:<12}{r.hr:>12.4f}{r.target:>14,.2f}{span:>22}{r.scaled_mean:>13,.2f}  {r.status}")
        for r in reports:
            if r.status != "ok":
                print(f"  {r.status.upper()} {r.name}: {r.message}")
    errors = [r for r in reports if r.status == "error"]
    if errors:
        raise PrecheckError(f"[{mode}] " + " | ".join(f"{r.name}: {r.message}" for r in errors))
    return reports


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check optimizer fence targets before running the Rust optimizer")
    parser.add_argument("library", help="path to games/<game>/library")
    parser.add_argument("modes", help="comma-separated bet modes")
    args = parser.parse_args(argv)
    failed = False
    for mode in [m.strip() for m in args.modes.split(",")]:
        try:
            precheck_mode(args.library, mode)
        except PrecheckError as err:
            print(f"  ERROR -> {err}")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
