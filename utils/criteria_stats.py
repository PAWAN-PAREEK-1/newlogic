"""Unoptimized statistics of the simulated books, per bet mode and criteria.

Use it after the simulation stage to choose the hit rates and average wins entered in a
game's game_optimization.py: the closer those targets are to what the books contain, the
less the optimizer has to bend the distribution.

It reads, for every mode,
    library/lookup_tables/lookUpTable_<mode>.csv            id, weight, payout (cents)
    library/lookup_tables/lookUpTableSegmented_<mode>.csv   id, criteria, basegame win, freegame win
and prints one line per criteria. Payouts are in multiples of the base bet.

Remember that inside a criteria the books are equally weighted here, and that the share of
books per criteria is the simulation quota, not a probability.

With --bands it also splits every criteria into payout bands, in multiples of the mode
cost. Use those shares and averages for payout-range conditions (search_conditions=(from, to)).

Usage (from the repository root):
    python -m utils.criteria_stats 0_0_gridlines
    python -m utils.criteria_stats 0_0_gridlines --modes base,surge
    python -m utils.criteria_stats 0_0_gridlines --modes surge --bands 0.1,0.25,0.5,1,2,5,10,25
"""

import argparse
import importlib
import os
from collections import defaultdict

import numpy as np


def load_mode(library_path: str, mode: str) -> dict:
    """Return {criteria: payouts array} for one mode."""
    lut_path = os.path.join(library_path, "lookup_tables", f"lookUpTable_{mode}.csv")
    seg_path = os.path.join(library_path, "lookup_tables", f"lookUpTableSegmented_{mode}.csv")
    payouts = {}
    with open(lut_path, "r", encoding="UTF-8") as f:
        for line in f:
            book_id, _, payout = line.strip().split(",")
            payouts[int(book_id)] = int(payout) / 100.0
    by_criteria = defaultdict(list)
    with open(seg_path, "r", encoding="UTF-8") as f:
        for line in f:
            book_id, criteria, _, _ = line.strip().split(",")
            by_criteria[criteria].append(payouts[int(book_id)])
    return {criteria: np.asarray(values) for criteria, values in by_criteria.items()}


def print_mode(mode: str, cost: float, by_criteria: dict) -> None:
    """Print the statistics table of one mode."""
    total = sum(len(v) for v in by_criteria.values())
    print(f"\n{mode} (cost {cost:g}, {total:,} books)")
    header = (
        f"  {'criteria':<10}{'books':>9}{'share':>8}{'avg win':>11}{'avg/cost':>10}{'median':>10}"
        f"{'p90':>10}{'p99':>10}{'max':>10}{'P(>cost)':>10}{'std/cost':>10}"
    )
    print(header)
    for criteria, wins in by_criteria.items():
        print(
            f"  {criteria:<10}{len(wins):>9,}{len(wins) / total:>8.3f}{wins.mean():>11.3f}{wins.mean() / cost:>10.3f}"
            f"{np.median(wins):>10.2f}{np.quantile(wins, 0.9):>10.2f}{np.quantile(wins, 0.99):>10.2f}"
            f"{wins.max():>10.1f}{(wins > cost).mean():>10.3f}{wins.std() / cost:>10.2f}"
        )


def print_bands(cost: float, max_win: float, by_criteria: dict, edges: list) -> None:
    """Print payout bands (from, to] of every criteria that has more than one payout."""
    bounds = [0.0] + edges + [float("inf")]
    for criteria, wins in by_criteria.items():
        if np.unique(wins).size < 2:
            continue
        below_max = wins[wins < max_win]
        print(f"  bands of '{criteria}' in multiples of the cost (rounds at the max win are left out)")
        print(f"    {'from':>8}{'to':>8}{'books':>9}{'share':>9}{'avg x cost':>12}{'avg win':>11}")
        for low, high in zip(bounds[:-1], bounds[1:]):
            band = below_max[(below_max > low * cost) & (below_max <= high * cost)]
            average = band.mean() if band.size else 0.0
            top = "max" if high == float("inf") else f"{high:g}"
            print(
                f"    {low:>8g}{top:>8}{band.size:>9,}{band.size / below_max.size:>9.4f}"
                f"{average / cost:>12.4f}{average:>11.2f}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Unoptimized per-criteria statistics of simulated books")
    parser.add_argument("game", help="game id, the folder name under games/")
    parser.add_argument("--modes", default=None, help="comma-separated bet modes (default: all)")
    parser.add_argument("--bands", default=None, help="comma-separated band edges in multiples of the mode cost")
    args = parser.parse_args()

    config = importlib.import_module(f"games.{args.game}.game_config").GameConfig()
    modes = {bm.get_name(): bm for bm in config.bet_modes}
    if args.modes:
        modes = {m: modes[m] for m in [x.strip() for x in args.modes.split(",")]}
    edges = sorted(float(x) for x in args.bands.split(",")) if args.bands else None
    for mode, bet_mode in modes.items():
        by_criteria = load_mode(config.library_path, mode)
        print_mode(mode, bet_mode.get_cost(), by_criteria)
        if edges:
            print_bands(bet_mode.get_cost(), bet_mode.get_wincap(), by_criteria, edges)


if __name__ == "__main__":
    main()
