"""Build the reel strip CSV files in reels/ from the symbol counts below.

The strips are generated, not hand-written, so the maths can be re-tuned by changing a
count and running this file again:

    python games/0_0_gridlines/build_reels.py

Every strip is built with a fixed seed, so the same counts always give the same file.
Each CSV has one line per stop and one column per reel, the format read by
Config.read_reels_csv.

Rules applied to every reel:
    * scatters are at least MIN_SCATTER_GAP stops apart (also across the wrap), so a
      5-row window can never show two scatters on one reel - the SDK relies on this when
      it forces a board with an exact number of scatters;
    * wilds are at least `wild_gap` stops apart;
    * no symbol is stacked more than `max_stack` high.
"""

import os
import random

NUM_REELS = 5
NUM_ROWS = 5
MIN_SCATTER_GAP = NUM_ROWS + 1

# counts are stops per reel; the same counts are used on all five reels unless a list
# (one dict per reel) is given.
STRIPS = {
    # Base game, wild spin and prime spin.
    "BR0": {
        "seed": 101,
        "counts": {
            "H1": 8, "H2": 10, "H3": 12, "H4": 14,
            "L1": 19, "L2": 21, "L3": 21, "L4": 23, "L5": 23,
            "W": 2, "S": 2,
        },
        "wild_gap": 6,
        "max_stack": 3,
    },
    # Surge bonus: more wilds, so collapse chains are longer and the multiplier climbs.
    "FRS": {
        "seed": 202,
        "counts": {
            "H1": 8, "H2": 10, "H3": 12, "H4": 14,
            "L1": 19, "L2": 21, "L3": 21, "L4": 23, "L5": 23,
            "W": 6,
        },
        "wild_gap": 4,
        "max_stack": 3,
    },
    # Refine bonus: base-like strip, the symbol upgrades do the work.
    "FRR": {
        "seed": 303,
        "counts": {
            "H1": 8, "H2": 10, "H3": 12, "H4": 14,
            "L1": 19, "L2": 21, "L3": 21, "L4": 23, "L5": 23,
            "W": 4,
        },
        "wild_gap": 6,
        "max_stack": 3,
    },
    # Survival bonus: wilds carry over between spins, so few are needed on the strip.
    # The wild is on the first three reels only; the last two get one more L5 instead.
    "FRV": {
        "seed": 404,
        "counts": [
            {
                "H1": 8, "H2": 10, "H3": 12, "H4": 14,
                "L1": 19, "L2": 21, "L3": 21, "L4": 23, "L5": 23 if reel < 3 else 24,
                "W": 1 if reel < 3 else 0,
            }
            for reel in range(NUM_REELS)
        ],
        "wild_gap": 6,
        "max_stack": 3,
    },
    # Max-win strip: only used by the "wincap" criteria to produce the capped rounds.
    "WCAP": {
        "seed": 505,
        "counts": {"H1": 30, "H2": 6, "H3": 4, "H4": 4, "W": 16},
        "wild_gap": 1,
        "max_stack": 5,
    },
}


def cyclic_gap_ok(reel: list, symbol: str, min_gap: int) -> bool:
    """True if every pair of `symbol` stops is at least `min_gap` apart around the reel."""
    stops = [i for i, name in enumerate(reel) if name == symbol]
    if len(stops) < 2:
        return True
    for a, b in zip(stops, stops[1:] + [stops[0] + len(reel)]):
        if b - a < min_gap:
            return False
    return True


def stack_ok(reel: list, max_stack: int) -> bool:
    """True if no symbol repeats more than `max_stack` times in a row around the reel."""
    doubled = reel + reel[:max_stack]
    run = 1
    for prev, name in zip(doubled, doubled[1:]):
        run = run + 1 if name == prev else 1
        if run > max_stack:
            return False
    return True


def build_reel(counts: dict, rng: random.Random, wild_gap: int, max_stack: int) -> list:
    """Shuffle one reel until it meets the spacing rules."""
    reel = [name for name, count in counts.items() for _ in range(count)]
    for _ in range(200000):
        rng.shuffle(reel)
        if (
            cyclic_gap_ok(reel, "S", MIN_SCATTER_GAP)
            and cyclic_gap_ok(reel, "W", wild_gap)
            and stack_ok(reel, max_stack)
        ):
            return list(reel)
    raise RuntimeError("Could not build a reel that meets the spacing rules - relax the counts.")


def build_strip(spec: dict) -> list:
    """Build all reels of one strip."""
    rng = random.Random(spec["seed"])
    reels = []
    for reel_index in range(NUM_REELS):
        counts = spec["counts"]
        if isinstance(counts, list):
            counts = counts[reel_index]
        reels.append(build_reel(counts, rng, spec["wild_gap"], spec["max_stack"]))
    lengths = {len(reel) for reel in reels}
    assert len(lengths) == 1, "All reels of a strip must have the same number of stops."
    return reels


def write_strip(name: str, reels: list, folder: str) -> str:
    """Write one strip as <name>.csv: one line per stop, one column per reel."""
    path = os.path.join(folder, f"{name}.csv")
    with open(path, "w", encoding="UTF-8", newline="\n") as f:
        for stop in range(len(reels[0])):
            f.write(",".join(reel[stop] for reel in reels) + "\n")
    return path


def main() -> None:
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reels")
    os.makedirs(folder, exist_ok=True)
    for name, spec in STRIPS.items():
        reels = build_strip(spec)
        path = write_strip(name, reels, folder)
        print(f"{name}: {len(reels[0])} stops per reel -> {path}")


if __name__ == "__main__":
    main()
