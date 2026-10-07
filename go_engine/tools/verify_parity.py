"""Byte-level parity check: Python engine vs Go engine.

Copies games/expwilds to a TEMPORARY game (games/expwilds_paritytmp), runs
BOTH engines there on the same small simulation counts, and byte-diffs every
output file. The real game's library/ is never touched, so this is safe to
run at any time - including right after a production run.

Byte-equality proves the Go port is faithful; run this after ANY change to
game logic in either engine.

Usage (from the repository root, venv active):

    python go_engine/tools/verify_parity.py            # default counts
    python go_engine/tools/verify_parity.py --sims 500 # quicker
"""

import argparse
import io
import os
import platform
import shutil
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)
os.chdir(REPO)

SRC_GAME = "expwilds"
TMP_GAME = "expwilds_paritytmp"

DEFAULT_SIMS = {
    "base": 2000,
    "ante": 1000,
    "bonus": 300,
    "superbonus": 200,
    # "hyperbonus": 200,
    "superante": 500,
}


def make_tmp_game() -> None:
    """Clone the game package under a temporary id (isolated library dir)."""
    src = os.path.join(REPO, "games", SRC_GAME)
    dst = os.path.join(REPO, "games", TMP_GAME)
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("library", "__pycache__"))
    cfg = os.path.join(dst, "game_config.py")
    with open(cfg, encoding="utf-8") as f:
        text = f.read()
    text = text.replace(
        f'self.game_id = "{SRC_GAME}"', f'self.game_id = "{TMP_GAME}"'
    )
    with open(cfg, "w", encoding="utf-8") as f:
        f.write(text)


def cleanup_tmp_game() -> None:
    shutil.rmtree(os.path.join(REPO, "games", TMP_GAME), ignore_errors=True)


def run_python_engine(num_sims: dict, snapshot_dir: str) -> str:
    """Run the reference engine; returns the tmp game's library path."""
    import importlib

    config_mod = importlib.import_module(f"games.{TMP_GAME}.game_config")
    state_mod = importlib.import_module(f"games.{TMP_GAME}.gamestate")
    from src.state.run_sims import create_books

    config = config_mod.GameConfig()
    gamestate = state_mod.GameState(config)
    create_books(gamestate, config, dict(num_sims), 50000, 1, True, False)

    lib = config.library_path
    os.makedirs(snapshot_dir, exist_ok=True)
    for sub, names in {
        "publish_files": [f"books_{m}.jsonl.zst" for m in num_sims],
        "lookup_tables": [f"lookUpTable_{m}.csv" for m in num_sims]
        + [f"lookUpTableSegmented_{m}.csv" for m in num_sims],
        "forces": [f"force_record_{m}.json" for m in num_sims],
    }.items():
        for name in names:
            shutil.copy(os.path.join(lib, sub, name), os.path.join(snapshot_dir, name))
    return lib


def run_go_engine(num_sims: dict, lib: str) -> None:
    import importlib

    config_mod = importlib.import_module(f"games.{TMP_GAME}.game_config")
    export_mod = importlib.import_module(f"games.{TMP_GAME}.export_spec")
    config = config_mod.GameConfig()
    spec_path = export_mod.export_spec(config)

    go_dir = os.path.join(REPO, "go_engine")
    exe = os.path.join(
        go_dir, "bin", "engine.exe" if platform.system() == "Windows" else "engine"
    )
    subprocess.run(["go", "build", "-o", exe, "."], cwd=go_dir, check=True)
    subprocess.run(
        [
            exe,
            "--spec", spec_path,
            "--library", lib,
            "--modes", ",".join(num_sims),
            "--sims", ",".join(f"{m}={n}" for m, n in num_sims.items()),
        ],
        check=True,
    )


def compare(num_sims: dict, snapshot_dir: str, lib: str) -> int:
    import zstandard as zstd

    failures = 0

    def read_zst_lines(path):
        with open(path, "rb") as f:
            reader = zstd.ZstdDecompressor().stream_reader(f)
            return io.TextIOWrapper(reader, encoding="UTF-8").read().splitlines()

    def check(name, ok, detail=""):
        nonlocal failures
        print(("PASS  " if ok else "FAIL  ") + name + (f"  {detail}" if detail else ""))
        if not ok:
            failures += 1

    for mode in num_sims:
        py_lines = read_zst_lines(os.path.join(snapshot_dir, f"books_{mode}.jsonl.zst"))
        go_lines = read_zst_lines(os.path.join(lib, "publish_files", f"books_{mode}.jsonl.zst"))
        if py_lines == go_lines:
            check(f"books_{mode} ({len(py_lines)} books)", True, "byte-identical")
        else:
            bad = next(
                (i for i, (a, b) in enumerate(zip(py_lines, go_lines)) if a != b),
                min(len(py_lines), len(go_lines)),
            )
            check(f"books_{mode}", False, f"first mismatch at book {bad}")

        for prefix in ("lookUpTable", "lookUpTableSegmented"):
            with open(os.path.join(snapshot_dir, f"{prefix}_{mode}.csv"), "rb") as f:
                a = f.read()
            with open(os.path.join(lib, "lookup_tables", f"{prefix}_{mode}.csv"), "rb") as f:
                b = f.read()
            check(f"{prefix}_{mode}.csv", a == b, "byte-identical" if a == b else "")

        with open(os.path.join(snapshot_dir, f"force_record_{mode}.json"), "rb") as f:
            a = f.read()
        with open(os.path.join(lib, "forces", f"force_record_{mode}.json"), "rb") as f:
            b = f.read()
        check(f"force_record_{mode}.json", a == b, "byte-identical" if a == b else "")

    print(
        "\nALL PASS - the Go engine matches the Python engine byte-for-byte."
        if failures == 0
        else f"\n{failures} FAILURES - engines have diverged!"
    )
    return failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sims", type=int, default=None,
                        help="override sim count for every mode (keep small!)")
    args = parser.parse_args()

    num_sims = dict(DEFAULT_SIMS)
    if args.sims:
        num_sims = {m: args.sims for m in num_sims}

    snapshot_dir = os.path.join(REPO, "games", TMP_GAME, "py_snapshot")
    try:
        print(f"[1/4] Cloning {SRC_GAME} -> games/{TMP_GAME} (isolated library)...")
        make_tmp_game()
        print(f"[2/4] Python engine ({sum(num_sims.values())} sims, single thread)...")
        lib = run_python_engine(num_sims, snapshot_dir)
        print("[3/4] Go engine (same counts)...")
        run_go_engine(num_sims, lib)
        print("[4/4] Comparing outputs...\n")
        failures = compare(num_sims, snapshot_dir, lib)
    finally:
        cleanup_tmp_game()
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
