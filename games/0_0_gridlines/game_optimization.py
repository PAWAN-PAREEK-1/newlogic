"""Set conditions/parameters for optimization program program"""

from optimization_program.optimization_config import (
    ConstructScaling,
    ConstructParameters,
    ConstructConditions,
    verify_optimization_input,
)

# --------------------------------------------------------------------------------------------
# Criteria targets
#
# Every bet mode's RTP is split over its criteria. For each criteria:
#   hr      - "1 in hr" rounds belong to the criteria
#   av_win  - average payout of those rounds, in multiples of the BASE bet
# and the criteria's RTP is av_win / (hr * cost).
#
# The average wins and the base-game hit rates below are what the game produces on its own
# (python -m utils.criteria_stats 0_0_gridlines, 100,000 books per mode), so the published
# weights stay close to the simulation. Rounds that reach the max win are counted in "wincap",
# not in the average of the bonus they came from. How often each bonus game triggers is a
# design choice.
# The base-game ("basegame") average win is the one value left free: it is whatever brings
# the mode to its RTP, and should stay within a few percent of the simulated average.
# --------------------------------------------------------------------------------------------

# Bonus games triggered from a paid spin: 1 in `hr` paid spins, average payout `av_win`.
SPIN_MODE_BONUSES = {
    "base": {
        "refine": {"hr": 550.0, "av_win": 130.0},
        "surge": {"hr": 1500.0, "av_win": 141.5},
        "survival": {"hr": 5500.0, "av_win": 279.0},
    },
    "wildspin": {
        "refine": {"hr": 240.0, "av_win": 132.0},
        "surge": {"hr": 650.0, "av_win": 147.0},
        "survival": {"hr": 2400.0, "av_win": 262.0},
    },
    "primespin": {
        "refine": {"hr": 150.0, "av_win": 133.0},
        "surge": {"hr": 420.0, "av_win": 147.0},
        "survival": {"hr": 1500.0, "av_win": 278.0},
    },
}
# Winning paid spins without a bonus: 1 in `hr` paid spins (the simulated hit rate).
SPIN_MODE_HIT_RATE = {"base": 2.72, "wildspin": 1.224, "primespin": 1.02}
# RTP given to rounds that pay the mode's max win. The max win then lands
# 1 in max_win / (rtp x cost) rounds.
WINCAP_RTP = {
    "base": 0.003,
    "wildspin": 0.003,
    "primespin": 0.003,
    "refine": 0.002,
    "surge": 0.004,
    "survival": 0.031,
}

# --------------------------------------------------------------------------------------------
# Risk limits, checked on the published table of every mode (optimization_program/mode_targets.py).
# The game stays inside them on its own; they are here so a later re-tune cannot drift past them.
# --------------------------------------------------------------------------------------------
# Average payout of the top 0.1% of rounds, in base-bet multiples.
RISK_LIMIT_CVAR = {"alpha": 0.001, "max": 18000.0}
# At most 0.8% of rounds (1 in 125) may pay TAIL_WIN x the base bet or more.
TAIL_WIN = 5000.0
TAIL_WIN_ONE_IN = (125.0, 1e15)


def mode_targets(cost: float) -> dict:
    """Risk limits of one bet mode (win ranges are in multiples of the mode cost)."""
    return {
        "win_ranges": [{"range": (TAIL_WIN / cost, 1e9), "one_in": TAIL_WIN_ONE_IN}],
        "cvar": RISK_LIMIT_CVAR,
    }


def spin_mode_conditions(mode: str, cost: float, rtp: float, wincap: float) -> dict:
    """Criteria targets of a paid-spin mode. Order matters: fixed payouts first, catch-all last."""
    conditions = {
        "wincap": ConstructConditions(rtp=WINCAP_RTP[mode], av_win=wincap, search_conditions=wincap).return_dict(),
        "0": ConstructConditions(rtp=0, av_win=0, search_conditions=0).return_dict(),
    }
    used_rtp = WINCAP_RTP[mode]
    for bonus, target in SPIN_MODE_BONUSES[mode].items():
        bonus_rtp = round(target["av_win"] / (target["hr"] * cost), 5)
        conditions[bonus] = ConstructConditions(
            rtp=bonus_rtp, hr=target["hr"], search_conditions={"bonus": bonus}
        ).return_dict()
        used_rtp += bonus_rtp
    conditions["basegame"] = ConstructConditions(
        hr=SPIN_MODE_HIT_RATE[mode], rtp=round(rtp - used_rtp, 5)
    ).return_dict()
    return conditions


def bonus_mode_conditions(mode: str, cost: float, rtp: float, wincap: float) -> dict:
    """Criteria targets of a bonus buy: every round is a bonus, a few of them the max win."""
    wincap_prob = WINCAP_RTP[mode] * cost / wincap
    freegame_rtp = round(rtp - WINCAP_RTP[mode], 5)
    return {
        "wincap": ConstructConditions(rtp=WINCAP_RTP[mode], av_win=wincap, search_conditions=wincap).return_dict(),
        "freegame": ConstructConditions(rtp=freegame_rtp, hr=round(1.0 / (1.0 - wincap_prob), 10)).return_dict(),
    }


class OptimizationSetup:
    """Optimization inputs for every bet mode."""

    def __init__(self, game_config):
        self.game_config = game_config
        wincaps, costs, rtps = {}, {}, {}
        for bm in game_config.bet_modes:
            wincaps[bm.get_name()] = bm.get_wincap()
            costs[bm.get_name()] = bm.get_cost()
            rtps[bm.get_name()] = bm.get_rtp()

        opt_params = {}

        # Paid spins: base game and the two feature spins.
        for mode in ("base", "wildspin", "primespin"):
            cost = costs[mode]
            opt_params[mode] = {
                "conditions": spin_mode_conditions(mode, cost, rtps[mode], wincaps[mode]),
                # "scaling" and "parameters" are only read by the Rust / Go optimizer.
                "scaling": ConstructScaling(
                    [
                        {
                            "criteria": "basegame",
                            "scale_factor": 1.2,
                            "win_range": (cost, 2 * cost),
                            "probability": 1.0,
                        },
                        {
                            "criteria": "basegame",
                            "scale_factor": 1.5,
                            "win_range": (10 * cost, 20 * cost),
                            "probability": 1.0,
                        },
                    ]
                ).return_dict(),
                "parameters": ConstructParameters(
                    num_show=5000,
                    num_per_fence=10000,
                    min_m2m=1.1,
                    max_m2m=8,
                    pmb_rtp=1.0,
                    sim_trials=5000,
                    test_spins=[50, 100, 200],
                    test_weights=[0.3, 0.4, 0.3],
                    score_type="rtp",
                ).return_dict(),
                "targets": mode_targets(cost),
            }

        # Bonus buys.
        for mode in ("refine", "surge", "survival"):
            cost = costs[mode]
            opt_params[mode] = {
                "conditions": bonus_mode_conditions(mode, cost, rtps[mode], wincaps[mode]),
                "scaling": ConstructScaling(
                    [
                        {
                            "criteria": "freegame",
                            "scale_factor": 1.2,
                            "win_range": (cost, 2 * cost),
                            "probability": 1.0,
                        },
                    ]
                ).return_dict(),
                "parameters": ConstructParameters(
                    num_show=5000,
                    num_per_fence=10000,
                    min_m2m=1.1,
                    max_m2m=8,
                    pmb_rtp=1.0,
                    sim_trials=5000,
                    test_spins=[10, 20, 50],
                    test_weights=[0.6, 0.2, 0.2],
                    score_type="rtp",
                ).return_dict(),
                "targets": mode_targets(cost),
            }

        self.game_config.opt_params = opt_params
        verify_optimization_input(self.game_config, self.game_config.opt_params)
