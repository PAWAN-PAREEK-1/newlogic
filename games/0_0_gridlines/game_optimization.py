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
# All values below come from python -m utils.criteria_stats 0_0_gridlines (100,000 books per
# mode), so inside a criteria the published weights stay close to the simulation.
# --------------------------------------------------------------------------------------------

# Paid spins (base, wildspin, primespin)
# ---------------------------------------
# Bonus games triggered from a paid spin: 1 in `hr` paid spins, average payout `av_win`.
# av_win is the simulated average (rounds that reach the max win are counted in "wincap").
# How often each bonus triggers is the design choice; together with the simulated base game
# they have to add up to the RTP.
SPIN_MODE_BONUSES = {
    "base": {
        "refine": {"hr": 1000.0, "av_win": 171.3},
        "surge": {"hr": 2800.0, "av_win": 213.2},
        "survival": {"hr": 3000.0, "av_win": 219.4},
    },
    "wildspin": {
        "refine": {"hr": 250.0, "av_win": 169.1},
        "surge": {"hr": 600.0, "av_win": 218.0},
        "survival": {"hr": 700.0, "av_win": 212.9},
    },
    "primespin": {
        "refine": {"hr": 80.0, "av_win": 172.7},
        "surge": {"hr": 160.0, "av_win": 220.9},
        "survival": {"hr": 150.0, "av_win": 210.6},
    },
}
# Winning base-game spins without a bonus: 1 in `hr` spins (the simulated hit rate).
BASE_HIT_RATE = 2.72

# Feature spins: the spins that win without a bonus are set band by band, like the bonus
# buys below. A band is a payout range (from, to] in multiples of the COST of the spin.
#   share   - share of ALL spins of the mode that pay inside the band
#   average - average payout inside the band, in multiples of the cost (the simulated value)
# The band (0.5, 1] is the "basegame" criteria: it has its share here and takes the RTP
# that everything else leaves over. Spins not covered by any share pay nothing.
SPIN_BANDS = {
    "wildspin": [
        {"name": "x0.1", "range": (0.0, 0.1), "share": 0.15, "average": 0.0456},
        {"name": "x0.25", "range": (0.1, 0.25), "share": 0.18, "average": 0.1715},
        {"name": "x0.5", "range": (0.25, 0.5), "share": 0.16, "average": 0.3606},
        {"name": "x2", "range": (1.0, 2.0), "share": 0.09, "average": 1.4391},
        {"name": "x5", "range": (2.0, 5.0), "share": 0.03, "average": 3.2051},
        {"name": "x10", "range": (5.0, 10.0), "share": 0.01, "average": 6.8370},
        {"name": "x25", "range": (10.0, 25.0), "share": 0.005, "average": 14.7376},
        {"name": "xtop", "range": (25.0, None), "share": 0.0015, "average": 41.9731},
    ],
    "primespin": [
        {"name": "x0.1", "range": (0.0, 0.1), "share": 0.18, "average": 0.0316},
        {"name": "x0.25", "range": (0.1, 0.25), "share": 0.17, "average": 0.1680},
        {"name": "x0.5", "range": (0.25, 0.5), "share": 0.15, "average": 0.3654},
        {"name": "x2", "range": (1.0, 2.0), "share": 0.14, "average": 1.4306},
        {"name": "x5", "range": (2.0, 5.0), "share": 0.035, "average": 3.0398},
        {"name": "x10", "range": (5.0, 10.0), "share": 0.008, "average": 6.5975},
        {"name": "xtop", "range": (10.0, None), "share": 0.002, "average": 14.48},
    ],
}
SPIN_BASEGAME_SHARE = {"wildspin": 0.19, "primespin": 0.275}

# RTP given to rounds that pay the max win. The max win then lands
# 1 in max_win / (rtp x cost) rounds.
WINCAP_RTP = {
    "base": 0.003,
    "wildspin": 0.003,
    "primespin": 0.003,
    "refine": 0.02,
    "surge": 0.015,
    "survival": 0.02,
}

# Bonus buys (refine, surge, survival)
# ------------------------------------
# The payout distribution of a buy is set band by band. A band is a payout range in multiples
# of the buy's COST: (from, to]. For each band:
#   share   - share of all rounds that pay inside the band
#   average - average payout inside the band, in multiples of the cost. Use the simulated
#             value (python -m utils.criteria_stats 0_0_gridlines --bands 0.1,0.25,0.5,1,2,5,10,25)
# The band (0.5, 1] is not listed: it is the "freegame" criteria, which takes the share and
# the RTP that the listed bands and the max win leave over. After a change, check in the
# optimizer print-out that its target average is still between 0.5 and 1.
#
# The shares are what make the buys volatile: about half of the rounds pay less than a
# quarter of the cost, about 70% pay between 0.1x and 2x, the 2x-10x middle is kept thin, and
# about 1.6% of the rounds pay more than 10x the cost.
BUY_BANDS = {
    "refine": [
        {"name": "x0.1", "range": (0.0, 0.1), "share": 0.22, "average": 0.0274},
        {"name": "x0.25", "range": (0.1, 0.25), "share": 0.25, "average": 0.1667},
        {"name": "x0.5", "range": (0.25, 0.5), "share": 0.19, "average": 0.3639},
        {"name": "x2", "range": (1.0, 2.0), "share": 0.12, "average": 1.4446},
        {"name": "x5", "range": (2.0, 5.0), "share": 0.052, "average": 3.0648},
        {"name": "x10", "range": (5.0, 10.0), "share": 0.026, "average": 6.5701},
        {"name": "xtop", "range": (10.0, None), "share": 0.015, "average": 13.41},
    ],
    "surge": [
        {"name": "x0.1", "range": (0.0, 0.1), "share": 0.24, "average": 0.0350},
        {"name": "x0.25", "range": (0.1, 0.25), "share": 0.26, "average": 0.1596},
        {"name": "x0.5", "range": (0.25, 0.5), "share": 0.20, "average": 0.3565},
        {"name": "x2", "range": (1.0, 2.0), "share": 0.12, "average": 1.4127},
        {"name": "x5", "range": (2.0, 5.0), "share": 0.0325, "average": 3.1835},
        {"name": "x10", "range": (5.0, 10.0), "share": 0.012, "average": 7.1809},
        {"name": "x25", "range": (10.0, 25.0), "share": 0.010, "average": 15.5335},
        {"name": "xtop", "range": (25.0, None), "share": 0.006, "average": 33.2678},
    ],
    "survival": [
        {"name": "x0.1", "range": (0.0, 0.1), "share": 0.24, "average": 0.0267},
        {"name": "x0.25", "range": (0.1, 0.25), "share": 0.26, "average": 0.1665},
        {"name": "x0.5", "range": (0.25, 0.5), "share": 0.20, "average": 0.3589},
        {"name": "x2", "range": (1.0, 2.0), "share": 0.12, "average": 1.4148},
        {"name": "x5", "range": (2.0, 5.0), "share": 0.032, "average": 3.1429},
        {"name": "x10", "range": (5.0, 10.0), "share": 0.012, "average": 6.9584},
        {"name": "x25", "range": (10.0, 25.0), "share": 0.010, "average": 15.2514},
        {"name": "xtop", "range": (25.0, None), "share": 0.006, "average": 33.3109},
    ],
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
    basegame_hr = BASE_HIT_RATE
    if mode in SPIN_BANDS:
        used_rtp += add_bands(conditions, SPIN_BANDS[mode], cost, wincap)[0]
        basegame_hr = round(1.0 / SPIN_BASEGAME_SHARE[mode], 10)
    conditions["basegame"] = ConstructConditions(hr=basegame_hr, rtp=round(rtp - used_rtp, 5)).return_dict()
    return conditions


def add_bands(conditions: dict, bands: list, cost: float, wincap: float) -> tuple:
    """Add one payout-range criteria per band. Returns (RTP used, share of rounds used)."""
    used_rtp, used_share = 0.0, 0.0
    for band in bands:
        low, high = band["range"]
        # The top band ends just below the max win, which has its own criteria.
        high_win = round(high * cost, 2) if high is not None else wincap - 0.05
        band_rtp = round(band["share"] * band["average"], 5)
        conditions[band["name"]] = ConstructConditions(
            rtp=band_rtp,
            hr=round(1.0 / band["share"], 10),
            search_conditions=(round(low * cost, 2), high_win),
        ).return_dict()
        used_rtp += band_rtp
        used_share += band["share"]
    return used_rtp, used_share


def bonus_mode_conditions(mode: str, cost: float, rtp: float, wincap: float) -> dict:
    """Criteria targets of a bonus buy: the max win, the payout bands, then what is left."""
    conditions = {
        "wincap": ConstructConditions(rtp=WINCAP_RTP[mode], av_win=wincap, search_conditions=wincap).return_dict(),
    }
    band_rtp, band_share = add_bands(conditions, BUY_BANDS[mode], cost, wincap)
    used_rtp = WINCAP_RTP[mode] + band_rtp
    used_share = WINCAP_RTP[mode] * cost / wincap + band_share
    # Everything not taken above: the band (0.5, 1] x cost.
    conditions["freegame"] = ConstructConditions(
        rtp=round(rtp - used_rtp, 5), hr=round(1.0 / (1.0 - used_share), 10)
    ).return_dict()
    return conditions


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
                "scaling": ConstructScaling([]).return_dict(),
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
