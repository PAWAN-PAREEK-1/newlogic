"""Go-engine run file for the grid-line pays game - the fast replacement for run.py.

PIPELINE (what runs where)
--------------------------
1. EXPORT    (Python) game_config.py     -> library/configs/game_spec_go.json
2. SIMULATE  (Go)     go_engine          -> books, lookup tables, force files
3. CONFIGS   (Python) generate_configs   -> index.json, config.json, fe_config, math_config.json
4. OPTIMIZE  (Go)     go_engine optimize -> publish_files/lookUpTable_<mode>_0.csv
5. ANALYZE   (Python) utils/game_analytics   -> PAR sheet / stats summary
6. VERIFY    (Python) utils/rgs_verification -> format checks and stats_summary.json

The Go simulation is a port of games/gridlines/*.py (go_engine/game/gridlines.go) and
writes byte-identical books to the Python engine for the same simulation counts.
After changing game logic in Python, change gridlines.go the same way and re-run
`python go_engine/tools/verify_parity.py`.

HOW TO USE (from the repository root; needs Go >= 1.22 on PATH)
---------------------------------------------------------------
    python games/gridlines/run_go.py                     # full pipeline
    python games/gridlines/run_go.py --sims 100000       # same simulation count for every mode
    python games/gridlines/run_go.py --modes base,surge  # only some modes
    python games/gridlines/run_go.py --skip-sims         # re-optimize the books already in library/
    python games/gridlines/run_go.py --skip-opt          # simulate + configs + checks only
    python games/gridlines/run_go.py --optimizer rust    # SDK optimizer instead of the Go one
"""

import argparse
import hashlib
import json
import os
import pickle
import platform
import shutil
import subprocess
import sys
import time

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from games.gridlines.game_config import GameConfig
from games.gridlines.gamestate import GameState
from games.gridlines.game_optimization import OptimizationSetup
from games.gridlines.export_spec import export_spec
from games.gridlines.run import clear_stale_outputs
from optimization_program.run_script import OptimizationExecution
from optimization_program.optimization_precheck import PrecheckError
from optimization_program.mode_targets import TargetError
from optimization_program.natural_weights import NaturalWeightsError
from utils.game_analytics.run_analysis import create_stat_sheet
from utils.rgs_verification import execute_all_tests
from src.write_data.write_configs import generate_configs
from src.write_data.write_data import get_sha_256

# ----------------------------------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------------------------------

# Simulations per bet mode. More sims = smoother final win distribution.
NUM_SIMS_PER_MODE = {
    "base": int(1e6),
    "wildspin": int(1e6),
    "primespin": int(1e6),
    "refine": int(1e6),
    "surge": int(1e6),
    "mystery": int(1e6),
}

RUN_CONDITIONS = {
    "run_sims": True,
    "run_optimization": True,
    "run_analysis": True,
    "run_format_checks": True,
}

OPTIMIZER = "go"  # "go" (go_engine/optimizer), "rust" (optimization_program) or "natural"
OPTIMIZER_THREADS = os.cpu_count() or 1
GO_WORKERS = 0  # simulation goroutines, 0 = all CPU cores
GO_BATCH_SIZE = 10000  # sims buffered per batch
COMPRESS_BOOKS = True  # .jsonl.zst books

# ----------------------------------------------------------------------------


def build_go_engine() -> str:
    """Compile the Go engine and return the binary path."""
    go_dir = os.path.join(_REPO_ROOT, "go_engine")
    exe = "engine.exe" if platform.system() == "Windows" else "engine"
    out_path = os.path.join(go_dir, "bin", exe)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    if shutil.which("go") is None:
        if os.path.exists(out_path):
            print(f"Go not found on PATH - using the existing binary {out_path}")
            return out_path
        sys.exit(
            "ERROR: the Go compiler ('go') was not found on PATH.\n"
            "The Go engine needs Go >= 1.22 (https://go.dev/dl/). Install it, restart the\n"
            "terminal and run this command again."
        )

    print("Building Go engine...")
    subprocess.run(["go", "build", "-o", out_path, "."], cwd=go_dir, check=True)
    return out_path


def run_go_simulations(config, modes: list, num_sims: dict) -> None:
    """Export the spec and run the Go engine for the requested modes."""
    clear_stale_outputs(config, modes)
    spec_path = export_spec(config)
    binary = build_go_engine()

    cmd = [
        binary,
        "--spec", spec_path,
        "--library", config.library_path,
        "--modes", ",".join(modes),
        "--sims", ",".join(f"{mode}={num_sims[mode]}" for mode in modes),
        "--batch", str(GO_BATCH_SIZE),
        f"--compress={'true' if COMPRESS_BOOKS else 'false'}",
    ]
    if GO_WORKERS > 0:
        cmd += ["--workers", str(GO_WORKERS)]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, cwd=_REPO_ROOT, check=True)
    write_verification_files(config, modes)


def write_verification_files(config, modes: list) -> None:
    """Write configs/books_<mode>.verification.json like the Python engine does.

    The RGS checks use it to skip re-reading the books. The payouts come from the raw
    lookup table, which the Go engine writes from the same values as the books.
    """
    for mode in modes:
        lut_path = os.path.join(config.library_path, "lookup_tables", f"lookUpTable_{mode}.csv")
        with open(lut_path, "r", encoding="UTF-8") as f:
            payouts = [int(line.rsplit(",", 1)[1]) for line in f if line.strip()]
        book_file = os.path.join(config.publish_path, f"books_{mode}.jsonl.zst")
        verification = {
            "payout_hash": hashlib.md5(pickle.dumps(payouts)).hexdigest(),
            "file_hash": get_sha_256(book_file),
            "num_entries": len(payouts),
        }
        path = os.path.join(config.library_path, "configs", f"books_{mode}.verification.json")
        with open(path, "w", encoding="UTF-8") as f:
            json.dump(verification, f, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="gridlines Go engine pipeline")
    parser.add_argument("--sims", type=int, default=None, help="simulation count for ALL modes")
    parser.add_argument("--modes", type=str, default=None, help="comma-separated subset of modes")
    parser.add_argument("--skip-sims", action="store_true", help="reuse the books already in library/")
    parser.add_argument("--skip-opt", action="store_true", help="skip optimization")
    parser.add_argument(
        "--optimizer", choices=["go", "rust", "natural"], default=OPTIMIZER, help="optimizer engine"
    )
    parser.add_argument("--skip-analysis", action="store_true", help="skip PAR-sheet analysis")
    parser.add_argument("--skip-checks", action="store_true", help="skip RGS format checks")
    args = parser.parse_args()

    num_sims = dict(NUM_SIMS_PER_MODE)
    if args.sims is not None:
        num_sims = {mode: args.sims for mode in num_sims}
    if args.modes:
        chosen = [m.strip() for m in args.modes.split(",")]
        unknown = [m for m in chosen if m not in num_sims]
        if unknown:
            sys.exit(f"Unknown mode(s) {unknown}. Bet modes: {list(num_sims)}")
        num_sims = {mode: num_sims[mode] for mode in chosen}
    target_modes = list(num_sims.keys())

    run_conditions = dict(RUN_CONDITIONS)
    if args.skip_sims:
        run_conditions["run_sims"] = False
    if args.skip_opt:
        run_conditions["run_optimization"] = False
    if args.skip_analysis:
        run_conditions["run_analysis"] = False
    if args.skip_checks:
        run_conditions["run_format_checks"] = False

    start = time.time()
    config = GameConfig()
    gamestate = GameState(config)
    if run_conditions["run_optimization"] or run_conditions["run_analysis"]:
        OptimizationSetup(config)

    if run_conditions["run_sims"]:
        run_go_simulations(config, target_modes, num_sims)

    # Books and lookup tables exist now - build the RGS/frontend/optimizer config files.
    generate_configs(gamestate)

    failed_modes = {}
    if run_conditions["run_optimization"]:
        for mode in target_modes:
            try:
                OptimizationExecution().run_opt_single_mode(
                    config, mode, OPTIMIZER_THREADS, engine=args.optimizer
                )
            except (PrecheckError, TargetError, NaturalWeightsError, subprocess.CalledProcessError) as err:
                failed_modes[mode] = str(err).splitlines()[0]
                print(f"\nOptimization of '{mode}' FAILED - continuing with the other modes.\n")
        generate_configs(gamestate)

    if run_conditions["run_analysis"]:
        custom_keys = [{"symbol": "scatter"}]
        create_stat_sheet(gamestate, custom_keys=custom_keys)

    if run_conditions["run_format_checks"]:
        # Only modes with books can be checked (all of them after a full run).
        missing = [
            bm.get_name()
            for bm in config.bet_modes
            if not os.path.exists(os.path.join(config.publish_path, f"books_{bm.get_name()}.jsonl.zst"))
        ]
        execute_all_tests(config, excluded_modes=missing)

    if failed_modes:
        print("\nOptimization FAILED for these modes (their lookUpTable_<mode>_0.csv is NOT optimized):")
        for mode, reason in failed_modes.items():
            print(f"  - {mode}: {reason}")
        sys.exit(1)

    print(f"\nPipeline finished in {time.time() - start:.1f}s")


if __name__ == "__main__":
    main()
