import json
import toml
import shutil
import subprocess
import os
from src.config.paths import PATH_TO_GAMES, SETUP_PATH, OPTIMIZATION_PATH, PROJECT_PATH


class OptimizationExecution:
    """Handles execution of Rust optimization algorithm from python."""

    @staticmethod
    def load_math_config(filename: str) -> dict:
        """Load optimization parameter config file."""
        with open(filename, "r", encoding="UTF-8") as f:
            data = json.load(f)
        return data

    @staticmethod
    def run_opt_single_mode(game_config, mode, threads=None, precheck=True, engine="rust", targets=True):
        """Optimize one bet mode: write the setup file and run the optimizer.

        threads: worker threads for the optimizer; None/0 = all CPU cores.
        precheck: first check the fence targets in seconds (optimization_precheck.py) and stop
                  with a clear message if one is impossible, instead of letting it grind.
        engine: "rust" = optimization_program (SDK default); "go" = the Go port of the same
                algorithm in go_engine/optimizer (same inputs and output files, faster);
                "natural" = no random search: the simulated distribution, tilted just enough
                to meet the same conditions (optimization_program/natural_weights.py).
        targets: if the mode has a "targets" block (ConstructTargets) in game_optimization.py,
                 adjust the optimizer output to meet it (optimization_program/mode_targets.py).
        """
        if not threads:
            threads = os.cpu_count() or 1
        os.chdir(PROJECT_PATH)
        library_path = os.path.join(PATH_TO_GAMES, game_config.game_id, "library")
        if precheck:
            from optimization_program.optimization_precheck import precheck_mode

            precheck_mode(library_path, mode)
        if engine == "go":
            OptimizationExecution.run_go_optimizer(library_path, mode, game_config.opt_params[mode]["parameters"], threads)
        elif engine == "rust":
            OptimizationExecution.run_rust_optimizer(game_config, mode, threads)
        elif engine == "natural":
            from optimization_program.natural_weights import natural_weights

            natural_weights(library_path, mode)
        else:
            raise ValueError(f"unknown optimizer engine {engine!r} (use 'rust', 'go' or 'natural')")

        mode_targets = game_config.opt_params[mode].get("targets")
        if targets and mode_targets:
            from optimization_program.mode_targets import apply_mode_targets

            apply_mode_targets(library_path, mode, mode_targets, game_config.opt_params[mode]["parameters"])

    @staticmethod
    def run_rust_optimizer(game_config, mode, threads):
        """Write src/setup.toml for one mode and run the Rust optimizer."""
        filename = os.path.join(PATH_TO_GAMES, game_config.game_id, "library", "configs", "math_config.json")
        opt_config = OptimizationExecution.load_math_config(filename)

        opt_config = game_config.opt_params
        params = None
        for idx, obj in opt_config.items():
            if idx == mode:
                params = obj["parameters"]
        params["game_name"] = game_config.game_id
        params["path_to_games"] = "../games/"
        params["run_1000_batch"] = False
        params["bet_type"] = mode
        params["threads_for_fence_construction"] = threads
        params["threads_for_show_construction"] = threads

        assert params is not None, "Could not load optimization parameters."

        with open(SETUP_PATH, "w", encoding="UTF-8") as f:
            toml.dump(params, f)
        print(f"Running optimization for mode: {mode} ({threads} threads)")
        OptimizationExecution.run_rust_script()

    @staticmethod
    def run_all_modes(game_config, modes_to_run, rust_threads=None, precheck=True, engine="rust"):
        """Loop through all game modes to run"""
        for mode in modes_to_run:
            OptimizationExecution.run_opt_single_mode(game_config, mode, rust_threads, precheck, engine)

    @staticmethod
    def run_go_optimizer(library_path, mode, parameters, threads, seed=0):
        """Run `go_engine optimize` (built with the Go toolchain, cached) for one mode."""
        go_dir = os.path.join(PROJECT_PATH, "go_engine")
        exe = os.path.join(go_dir, "bin", "engine.exe" if os.name == "nt" else "engine")
        if shutil.which("go"):
            subprocess.run(["go", "build", "-o", exe, "."], cwd=go_dir, check=True)
        elif not os.path.exists(exe):
            raise RuntimeError("Go optimizer needs Go >= 1.22 on PATH (https://go.dev/dl/) or a built go_engine/bin binary")
        params_path = os.path.join(library_path, "configs", f"optimizer_params_{mode}.json")
        with open(params_path, "w", encoding="UTF-8") as f:
            json.dump(parameters, f, indent=2)
        print(f"Running Go optimization for mode: {mode} ({threads} threads)")
        try:
            subprocess.run(
                [exe, "optimize", "--library", library_path, "--mode", mode, "--params", params_path,
                 "--threads", str(threads), "--seed", str(seed)],
                check=True,
            )
        except subprocess.CalledProcessError:
            print("Error in Go optimizer (see output above).")
            raise

    @staticmethod
    def run_rust_script():
        """Run compiled binary, streaming its progress to the terminal as it runs."""
        cargo_bin_path = os.path.join(os.path.expanduser("~"), ".cargo", "bin")
        updated_path = cargo_bin_path + os.pathsep + os.environ.get("PATH", "")
        try:
            subprocess.run(
                ["cargo", "run", "--release"],
                cwd=OPTIMIZATION_PATH,
                check=True,
                env={**os.environ, "PATH": updated_path},
            )
        except subprocess.CalledProcessError:
            print("Error in optimization program (see output above).")
            raise
