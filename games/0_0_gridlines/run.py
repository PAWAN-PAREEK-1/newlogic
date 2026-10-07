"""Main file for generating results for the grid-line pays game.

PIPELINE
--------
1. SIMULATE  create_books      -> books, lookup tables, force files
2. CONFIGS   generate_configs  -> index.json, config.json, fe_config, math_config.json
3. OPTIMIZE  optimization_program -> publish_files/lookUpTable_<mode>_0.csv
             (natural weights by default; the Rust or Go optimizer on request)
4. ANALYZE   utils/game_analytics -> PAR sheet / stats summary
5. VERIFY    utils/rgs_verification -> format checks and stats_summary.json

HOW TO USE (from the repository root)
-------------------------------------
    python -m games.0_0_gridlines.run                    # full pipeline
    python -m games.0_0_gridlines.run --sims 20000       # same simulation count for every mode
    python -m games.0_0_gridlines.run --modes base,surge # only some modes
    python -m games.0_0_gridlines.run --skip-opt         # simulate + configs + checks only
    python -m games.0_0_gridlines.run --optimizer rust   # SDK optimizer instead of natural weights

`make run GAME=0_0_gridlines` runs the same file.
"""

import argparse
import os
import subprocess
import sys
import time

if __package__ in (None, ""):
    # Started as a script (python games/0_0_gridlines/run.py): make the relative imports work.
    import importlib

    _REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)
    __package__ = "games." + os.path.basename(os.path.dirname(os.path.abspath(__file__)))
    importlib.import_module(__package__)

from .gamestate import GameState
from .game_config import GameConfig
from .game_optimization import OptimizationSetup
from optimization_program.run_script import OptimizationExecution
from optimization_program.optimization_precheck import PrecheckError
from optimization_program.mode_targets import TargetError
from optimization_program.natural_weights import NaturalWeightsError
from utils.game_analytics.run_analysis import create_stat_sheet
from utils.rgs_verification import execute_all_tests
from src.state.run_sims import create_books
from src.write_data.write_configs import generate_configs

NUM_SIMS_PER_MODE = {
    "base": int(1e5),
    "wildspin": int(1e5),
    "primespin": int(1e5),
    "refine": int(1e5),
    "surge": int(1e5),
    "survival": int(1e5),
}

RUN_CONDITIONS = {
    "run_sims": True,
    "run_optimization": True,
    "run_analysis": True,
    "run_format_checks": True,
}

NUM_THREADS = os.cpu_count() or 1  # simulation processes
OPTIMIZER_THREADS = os.cpu_count() or 1
# "natural": keep the simulated distribution, tilted to the targets (natural_weights.py)
# "rust":    SDK optimizer (optimization_program)      "go": its Go port (go_engine/optimizer)
OPTIMIZER = "natural"
BATCHING_SIZE = 5000
COMPRESSION = True
PROFILING = False


def clear_stale_outputs(config, modes: list) -> None:
    """Delete last run's optimized tables and verification sidecars of the modes about to be simulated."""
    for mode in modes:
        for path in (
            os.path.join(config.publish_path, f"lookUpTable_{mode}_0.csv"),
            os.path.join(config.library_path, "configs", f"books_{mode}.verification.json"),
        ):
            if os.path.exists(path):
                os.remove(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="0_0_gridlines pipeline")
    parser.add_argument("--sims", type=int, default=None, help="simulation count for ALL modes")
    parser.add_argument("--modes", type=str, default=None, help="comma-separated subset of modes")
    parser.add_argument("--threads", type=int, default=NUM_THREADS, help="simulation processes")
    parser.add_argument("--skip-sims", action="store_true", help="reuse the books already in library/")
    parser.add_argument("--skip-opt", action="store_true", help="skip optimization")
    parser.add_argument("--optimizer", choices=["natural", "rust", "go"], default=OPTIMIZER, help="optimizer engine")
    parser.add_argument("--skip-analysis", action="store_true", help="skip PAR-sheet analysis")
    parser.add_argument("--skip-checks", action="store_true", help="skip RGS format checks")
    args = parser.parse_args()

    num_sim_args = dict(NUM_SIMS_PER_MODE)
    if args.sims is not None:
        num_sim_args = {mode: args.sims for mode in num_sim_args}
    if args.modes:
        chosen = [m.strip() for m in args.modes.split(",")]
        unknown = [m for m in chosen if m not in num_sim_args]
        if unknown:
            sys.exit(f"Unknown mode(s) {unknown}. Bet modes: {list(num_sim_args)}")
        num_sim_args = {mode: num_sim_args[mode] for mode in chosen}
    target_modes = list(num_sim_args.keys())

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
        clear_stale_outputs(config, target_modes)
        create_books(
            gamestate,
            config,
            num_sim_args,
            BATCHING_SIZE,
            args.threads,
            COMPRESSION,
            PROFILING,
        )

    generate_configs(gamestate)

    failed_modes = {}
    if run_conditions["run_optimization"]:
        for mode in target_modes:
            try:
                OptimizationExecution().run_opt_single_mode(config, mode, OPTIMIZER_THREADS, engine=args.optimizer)
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
