"""Natural lookup-table weights: the simulated distribution, tilted just enough to hit the targets.

WHAT IT DOES
------------
An alternative to the Rust / Go optimizer that keeps the published probabilities as close as
possible to what the game really does.

The Rust optimizer gives every distinct payout of a criteria a weight drawn from random smooth
curves, so the number of simulated books behind each payout - how often the game actually
produces it - is not used. This tool starts from the simulation itself (every book of a criteria
equally likely) and makes the SMALLEST change that meets the same `conditions` the optimizer is
given in game_optimization.py:

  * every criteria gets its probability (1 / hr);
  * every criteria gets its average win (hr x rtp x cost), so the mode lands on its RTP;
  * fixed-payout criteria (wincap, 0) spread their probability evenly over their books.

"Smallest change" is the minimum relative-entropy projection (the same method mode_targets.py
uses): inside a criteria each payout x is rescaled by exp(a + b * x). If a criteria's target
average equals its simulated average, nothing changes at all.

It reads exactly what the Rust optimizer reads (library/configs/math_config.json, the mode's
lookup table and force_record_<mode>.json) and writes what it writes:

    library/publish_files/lookUpTable_<mode>_0.csv      the published table
    library/optimization_files/<mode>_0_1.csv           the same table as an optimizer candidate,
                                                        so mode_targets.py can be applied on top

Choose targets close to the simulated values (python -m utils.criteria_stats <game>): the
further a target average is from the simulated one, the harder the tail is bent.

Usage:
    python -m optimization_program.natural_weights --game 0_0_gridlines --mode base,surge
From Python (run_script.py calls this for engine="natural"):
    natural_weights(library_path, mode)
"""

from __future__ import annotations

import argparse
import glob
import importlib
import json
import os
import sys

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from optimization_program.mode_targets import TWO_POW_50, kl_projection
from optimization_program.optimization_precheck import PrecheckError, assign_books, parse_fences


class NaturalWeightsError(RuntimeError):
    """A criteria target cannot be met from the simulated books."""


def natural_weights(library_path: str, mode: str, verbose: bool = True) -> dict:
    """Write the natural lookup table of `mode`. Returns a per-criteria report."""
    with open(os.path.join(library_path, "configs", "math_config.json"), encoding="utf-8") as f:
        math_config = json.load(f)
    fences, cost, mode_rtp = parse_fences(math_config, mode)
    table = pd.read_csv(
        os.path.join(library_path, "lookup_tables", f"lookUpTable_{mode}.csv"),
        header=None,
        names=["id", "weight", "cents"],
        dtype=np.int64,
    )
    ids, cents = table["id"].to_numpy(), table["cents"].to_numpy()
    with open(os.path.join(library_path, "forces", f"force_record_{mode}.json"), encoding="utf-8") as f:
        forces = json.load(f)
    try:
        assign_books(fences, ids, cents, forces, mode)
    except PrecheckError as err:
        raise NaturalWeightsError(str(err)) from err

    wins = cents / 100.0
    total_prob = sum(1.0 / fence.hr for fence in fences)
    prob = np.zeros(len(ids))
    report = {"mode": mode, "cost": cost, "criteria": []}

    for fence in fences:
        idx = fence.book_idx
        mass = (1.0 / fence.hr) / total_prob
        x = wins[idx]
        simulated = float(x.mean())
        if fence.win_type:
            prob[idx] = mass / len(idx)
            target = fence.win_range_start
        else:
            target = fence.avg_win * cost
            payouts, inverse, counts = np.unique(x, return_inverse=True, return_counts=True)
            if not payouts.min() < target < payouts.max():
                raise NaturalWeightsError(
                    f"[{mode}] criteria '{fence.name}': target average win {target:,.4f} is outside its books' "
                    f"payouts {payouts.min():,.2f}..{payouts.max():,.2f}. Target = hr x rtp x cost."
                )
            q = counts / counts.sum()
            p, _, ok = kl_projection(q, np.vstack([np.ones_like(payouts), payouts]), np.array([1.0, target]))
            if not ok:
                raise NaturalWeightsError(
                    f"[{mode}] criteria '{fence.name}': could not reach the target average win {target:,.4f} "
                    f"(simulated average {simulated:,.4f}). Move the target closer to the simulated value."
                )
            prob[idx] = mass * (p / counts)[inverse]
        report["criteria"].append(
            {
                "name": fence.name,
                "books": int(len(idx)),
                "one_in": 1.0 / mass,
                "simulated_avg_win": simulated,
                "target_avg_win": float(target),
                "rtp": mass * float(target) / cost,
            }
        )

    weights = np.floor(prob * TWO_POW_50).astype(np.uint64)
    if np.any(weights == 0):
        raise NaturalWeightsError(f"[{mode}] some books would get zero weight - a criteria is too rare for its books.")

    order = np.argsort(ids, kind="stable")
    rows = "".join(
        f"{i},{w},{c}\n" for i, w, c in zip(ids[order].tolist(), weights[order].tolist(), cents[order].tolist())
    )
    with open(os.path.join(library_path, "publish_files", f"lookUpTable_{mode}_0.csv"), "w", encoding="utf-8", newline="") as f:
        f.write(rows)

    # Leave exactly one optimizer candidate behind, so mode_targets.py works on this table.
    opt_dir = os.path.join(library_path, "optimization_files")
    os.makedirs(opt_dir, exist_ok=True)
    for stale in glob.glob(os.path.join(opt_dir, f"{mode}_0_*.csv")):
        os.remove(stale)
    achieved = float((weights / weights.sum()) @ wins) / cost
    with open(os.path.join(opt_dir, f"{mode}_0_1.csv"), "w", encoding="utf-8", newline="") as f:
        f.write(f"Name,Natural\nScore,\nLockedUpRTP,\nRtp,{achieved}\nDistribution\n")
        f.write(rows)

    report["rtp"] = achieved
    if verbose:
        print(f"\nNatural weights: {mode} (cost {cost:g}, {len(ids):,} books) - RTP {achieved:.6f} (target {mode_rtp:g})")
        print(f"  {'criteria':<12}{'books':>9}{'1 in':>16}{'simulated avg':>16}{'target avg':>14}{'rtp':>10}")
        for row in report["criteria"]:
            print(
                f"  {row['name']:<12}{row['books']:>9,}{row['one_in']:>16,.2f}{row['simulated_avg_win']:>16,.3f}"
                f"{row['target_avg_win']:>14,.3f}{row['rtp']:>10.5f}"
            )
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Natural lookup-table weights (minimum change from the simulation)")
    parser.add_argument("--game", required=True)
    parser.add_argument("--mode", required=True, help="comma-separated bet modes")
    parser.add_argument("--library", default=None, help="override games/<game>/library")
    args = parser.parse_args(argv)
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    os.chdir(root)
    config = importlib.import_module(f"games.{args.game}.game_config").GameConfig()
    importlib.import_module(f"games.{args.game}.game_optimization").OptimizationSetup(config)
    library = args.library or os.path.join(root, "games", args.game, "library")
    failed = 0
    for mode in [m.strip() for m in args.mode.split(",")]:
        try:
            natural_weights(library, mode)
        except NaturalWeightsError as err:
            failed += 1
            print(f"ERROR {err}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
