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
# All values below come from python -m utils.criteria_stats gridlines (100,000 books per
# mode), so inside a criteria the published weights stay close to the simulation.
# --------------------------------------------------------------------------------------------

# Paid spins (base, wildspin, primespin) and the mystery buy
# -----------------------------------------------------------
# Bonus games triggered from a paid spin: 1 in `hr` paid spins, average payout `av_win`.
# av_win is the simulated average (rounds that reach the max win are counted in "wincap").
# How often each bonus triggers is the design choice; together with the other criteria they
# have to add up to the RTP.
#
# The WIN RATE of a mode is the share of rounds that pay the cost or more. It is kept low
# (about 2% in base and wildspin, just under 3% in primespin), so the few rounds that do win
# have to carry most of the RTP.
#
# Entries of a mode, in the order the optimizer gives them their rounds:
# * a bonus name ("refine", "surge", "fusion"): the rounds of that bonus.
# * "range": a payout range in multiples of the cost instead of a bonus type (an edge of 1.0
#   sits just below the cost, None is just below the max win). Such a criteria takes every
#   round in the range that the criteria above it left over, whatever its bonus.
# * "bonus_range": the rounds of that bonus inside a payout range (Go optimizer only).
# * "search": another force-file key instead of the bonus type.
# * "takes_rest": the last criteria. It has no search condition, so it takes the rounds that
#   are left and the RTP left over; its av_win here is that target average, for reference.
#
# BIG WINS (primespin and mystery): every payout row of the math report from 1,000x up is
# its own criteria ("x5000" = 2,000x to 5,000x, ... "x20000" = 10,000x to 19,950x), so its
# hit rate is set directly. Every one of them comes at most 1 in 1100 rounds. The row from
# 1,000x to 2,000x is called "fusion": almost all of its rounds are Fusion rounds, and every
# simulated criteria needs a criteria of the same name here. "xhuge" is 19,950x up to the
# max win; with "wincap" it has to stay under HUGE_WIN_RTP.
#
# Prime spin: all Fusion rounds pay 1,000x or more, so Fusion has no criteria of its own; it
# is the big-win rows (together 1 in 355 spins, about 67% of the RTP). "x10000" and "x20000"
# have only 36 and 20 books. Refine and Surge are their rounds up to 1,000x.
#
# Mystery buy: no bonus 2%, refine 14%, surge 83.3%, a win of the price or more 0.6%.
# * A no-bonus round is a spin where the scatters do not trigger. It pays a small win of at
#   most 3x the bet, about 1.2x on average ("basegame"); 1 in 1000 buys it pays more than 3x
#   ("bigspin") and 1 in 1000 it pays nothing ("0", which takes the chance left over).
# * Refine and Surge rounds pay just under the price: 0.8x the price up to just under it
#   (their simulated averages). They hold 90% of the RTP.
# * "x500" is every bonus round from the price up to 500x (1 in 500 buys) and "x1000" from
#   500x up to 1,000x (1 in 1100 buys).
# * "lowbonus" takes every bonus round that is left: Refine and Surge below 0.8x the price.
# * Why so few no-bonus rounds: the RTP that is not paid just under the price has to be
#   paid as wins. A no-bonus round pays almost nothing and a Refine or Surge round at most
#   0.9x the price, so at most 0.9 x (1 - no-bonus share) of the bets sits under the price.
#   The big-win rows at 1 in 1100 can pay about 9% of the bets, which leaves 87% for the
#   rounds under the price: no bonus 2%. With 10% no bonus the 10,000x row has to come
#   1 in 280 buys, with 50% about 1 in 90.
SPIN_MODE_BONUSES = {
    "base": {
        "refine": {"hr": 332.9, "av_win": 103.2},
        "surge": {"hr": 1065.3, "av_win": 202.4},
        "fusion": {"hr": 21713.0, "av_win": 2171.3},
    },
    "wildspin": {
        "refine": {"hr": 84.5, "av_win": 105.6},
        "surge": {"hr": 151.0, "av_win": 196.3},
        "fusion": {"hr": 3082.4, "av_win": 2157.7},
    },
    "primespin": {
        "fusion": {"hr": 1100.0, "av_win": 1763.0, "range": (50.0, 100.0)},
        "x5000": {"hr": 1100.0, "av_win": 2800.0, "range": (100.0, 250.0)},
        "x10000": {"hr": 1500.0, "av_win": 6730.0, "range": (250.0, 500.0)},
        "x20000": {"hr": 3000.0, "av_win": 14046.0, "range": (500.0, 997.5)},
        "xhuge": {"hr": 400000.0, "av_win": 22592.0, "range": (997.5, None)},
        "refine": {"hr": 250.0, "av_win": 76.4},
        "surge": {"hr": 80.0, "av_win": 119.2},
    },
    "mystery": {
        "x500": {"hr": 500.0, "av_win": 380.0, "range": (1.0, 1.666667)},
        "x1000": {"hr": 1100.0, "av_win": 690.0, "range": (1.666667, 3.333333)},
        "fusion": {"hr": 1100.0, "av_win": 1763.0, "range": (3.333333, 6.666667)},
        "x5000": {"hr": 1100.0, "av_win": 3000.0, "range": (6.666667, 16.666667)},
        "x10000": {"hr": 1100.0, "av_win": 7000.0, "range": (16.666667, 33.333333)},
        "x20000": {"hr": 1100.0, "av_win": 14000.0, "range": (33.333333, 66.5)},
        "xhuge": {"hr": 30000.0, "av_win": 22712.0, "range": (66.5, None)},
        "refine": {"hr": 7.142857, "av_win": 265.3, "bonus_range": (0.8, 1.0)},
        "surge": {"hr": 1.201419, "av_win": 268.42, "bonus_range": (0.8, 1.0)},
        "lowbonus": {"hr": 1000.0, "av_win": 68.0, "search": {"symbol": "scatter"}},
        "bigspin": {"hr": 1000.0, "av_win": 12.0, "range": (0.01, 0.6)},
        "basegame": {"hr": 55.555556, "av_win": 1.2, "takes_rest": True},
    },
}

# Paid spins: the spins that win without a bonus are set band by band, like the bonus buys
# below. A band is a payout range (from, to] in multiples of the COST of the spin.
#   share   - share of ALL spins of the mode that pay inside the band
#   average - average payout inside the band, in multiples of the cost (the simulated value)
# A band edge of 1.0 sits just below the cost: a payout equal to the cost is a win, not a
# sub-bet win. The last sub-bet band - (0.5, 1) in base, (0.8, 1) in the feature spins - is
# the "basegame" criteria: it has its share in SPIN_BASEGAME_SHARE and takes the RTP that
# everything else leaves over. Spins not covered by any share pay nothing.
#
# In every paid-spin mode about 75% to 79% of the spins pay nothing. In base and wildspin
# almost every hit is a sub-bet win (most of them just under the cost in wildspin), and only
# about 2% of the spins pay the cost or more.
SPIN_BANDS = {
    "base": [
        {"name": "sub0.5", "range": (0.0, 0.5), "share": 0.05, "average": 0.2075},
        {"name": "x2.5", "range": (1.0, 2.5), "share": 0.004, "average": 1.5508},
        {"name": "x5", "range": (2.5, 5.0), "share": 0.003, "average": 3.5354},
        {"name": "x10", "range": (5.0, 10.0), "share": 0.0035, "average": 7.1033},
        {"name": "x25", "range": (10.0, 25.0), "share": 0.0045, "average": 15.6276},
        {"name": "xtop", "range": (25.0, None), "share": 0.002811, "average": 45.712},
    ],
    "wildspin": [
        {"name": "sub0.5", "range": (0.0, 0.5), "share": 0.02, "average": 0.1219},
        {"name": "sub0.8", "range": (0.5, 0.8), "share": 0.02, "average": 0.6443},
        {"name": "x2.5", "range": (1.0, 2.5), "share": 0.0005, "average": 1.6134},
        {"name": "x5", "range": (2.5, 5.0), "share": 0.0005, "average": 3.5646},
        {"name": "x10", "range": (5.0, 10.0), "share": 0.001, "average": 6.837},
        {"name": "x25", "range": (10.0, 25.0), "share": 0.002, "average": 14.7376},
        {"name": "xtop", "range": (25.0, None), "share": 0.002116, "average": 41.9731},
    ],
    # Prime spin: about 79% of the spins pay nothing and about 2.7% pay the cost or more.
    "primespin": [
        {"name": "sub0.5", "range": (0.0, 0.5), "share": 0.05, "average": 0.1174},
        {"name": "sub0.8", "range": (0.5, 0.8), "share": 0.015, "average": 0.6434},
        {"name": "x2.5", "range": (1.0, 2.5), "share": 0.001, "average": 1.597},
        {"name": "x5", "range": (2.5, 5.0), "share": 0.001, "average": 3.4261},
        {"name": "x10", "range": (5.0, 10.0), "share": 0.003, "average": 6.5975},
        {"name": "xtop", "range": (10.0, None), "share": 0.0035, "average": 14.4786},
    ],
}
SPIN_BASEGAME_SHARE = {"base": 0.14, "wildspin": 0.18, "primespin": 0.1164}

# RTP given to rounds that pay the max win. Together with every other win of 20,000x the
# bet or more it has to stay under 1% of the bets (HUGE_WIN_RTP below), so it is set lower.
# The max win lands 1 in max_win / (rtp x cost) rounds.
WINCAP_RTP = {
    "base": 0.005,
    "wildspin": 0.006,
    "primespin": 0.006,
    "refine": 0.006,
    "surge": 0.006,
    "mystery": 0.006,
}

# Bonus buys (refine, surge)
# --------------------------
# The payout distribution of a buy is set band by band. A band is a payout range in multiples
# of the buy's COST: (from, to]. For each band:
#   share   - share of all rounds that pay inside the band
#   average - average payout inside the band, in multiples of the cost (the simulated value)
# A band edge of 1.0 sits just below the cost. The band (0.8, 1) is not listed: it is the
# "freegame" criteria, which takes the share and the RTP that the listed bands and the max win
# leave over. After a change, check that its target average is still between 0.84 and 0.95.
#
# A buy loses almost every time, but mostly by a little. Refine: about 77% of the rounds pay
# 0.8x to just under the cost, 10% pay 0.5x to 0.8x, 8% pay 0.1x to 0.5x and 4% pay less than
# 0.1x. Only about 1.1% pay the cost or more, and they carry about a fifth of the RTP.
BUY_BANDS = {
    "refine": [
        {"name": "sub0.1", "range": (0.0, 0.1), "share": 0.04, "average": 0.0387},
        {"name": "sub0.5", "range": (0.1, 0.5), "share": 0.08, "average": 0.2761},
        {"name": "sub0.8", "range": (0.5, 0.8), "share": 0.1, "average": 0.653},
        {"name": "x2", "range": (1.0, 2.0), "share": 0.003, "average": 1.4157},
        {"name": "x5", "range": (2.0, 5.0), "share": 0.003, "average": 2.8671},
        {"name": "x10", "range": (5.0, 10.0), "share": 0.002, "average": 7.125},
        {"name": "x25", "range": (10.0, 25.0), "share": 0.0005, "average": 15.1837},
        {"name": "xtop", "range": (25.0, None), "share": 0.002052, "average": 71.0319},
    ],
    # Surge: about 86% of the rounds (80% of the RTP) pay 0.8x to just under the cost, and
    # about 0.7% pay the cost or more. The top band averages more than its simulated 55.3x
    # to keep the volatility; with this much RTP under the cost it still tops out near 3.1.
    "surge": [
        {"name": "sub0.1", "range": (0.0, 0.1), "share": 0.02, "average": 0.0823},
        {"name": "sub0.5", "range": (0.1, 0.5), "share": 0.045, "average": 0.2693},
        {"name": "sub0.8", "range": (0.5, 0.8), "share": 0.068, "average": 0.6275},
        {"name": "x2", "range": (1.0, 2.0), "share": 0.002, "average": 1.3773},
        {"name": "x5", "range": (2.0, 5.0), "share": 0.002, "average": 2.9479},
        {"name": "x10", "range": (5.0, 10.0), "share": 0.0005, "average": 6.8003},
        {"name": "x25", "range": (10.0, 25.0), "share": 0.0005, "average": 15.89},
        {"name": "xtop", "range": (25.0, None), "share": 0.0016, "average": 69.1},
    ],
}

# --------------------------------------------------------------------------------------------
# Volatility and risk limits, applied to the published table of every mode
# (optimization_program/mode_targets.py).
# --------------------------------------------------------------------------------------------
# Average payout of the top 0.1% of rounds, in base-bet multiples. The compliance report
# fails a mode above 20,000, so the limit is set a little under it.
RISK_LIMIT_CVAR = {"alpha": 0.001, "max": 19500.0}
# Wins of HUGE_WIN x the bet or more (the max win included) may pay at most this share of
# the bets in any mode.
HUGE_WIN = 20000.0
HUGE_WIN_RTP = (0.0, 0.0095)
# At most 0.8% of rounds (1 in 125) may pay TAIL_WIN x the base bet or more.
TAIL_WIN = 12500.0
TAIL_WIN_ONE_IN = (125.0, 1e15)


# Volatility of every mode: standard deviation of the payout divided by the cost, as a
# (from, to) range. After the optimizer, mode_targets.py moves the published table into the
# range with the smallest possible change; hit rates and criteria averages stay as set above.
MODE_VOLATILITY = {
    "base": (18.0, 23.0),
    "wildspin": (15.0, 16.0),
    "primespin": (16.0, 20.0),
    "refine": (4.0, 6.0),
    "surge": (3.0, 3.9),  # its 125x-the-cost max win and the CVaR limit allow about 3.1
    "mystery": (1.5, 4.0),
}


# A payout range that starts or ends "at the cost" is cut this far below it.
BELOW_COST = 0.05


def mode_targets(mode: str, cost: float) -> dict:
    """Volatility and risk limits of one bet mode (win ranges are in multiples of the mode cost)."""
    return {
        "volatility": MODE_VOLATILITY[mode],
        "win_ranges": [{"range": (TAIL_WIN / cost, 1e9), "one_in": TAIL_WIN_ONE_IN}],
        "rtp_ranges": [{"range": (HUGE_WIN / cost, 1e9), "rtp": HUGE_WIN_RTP}],
        "cvar": RISK_LIMIT_CVAR,
    }


def spin_mode_conditions(mode: str, cost: float, rtp: float, wincap: float) -> dict:
    """Criteria targets of a paid-spin mode or the mystery buy. Order matters: fixed payouts
    first, catch-all last."""
    conditions = {
        "wincap": ConstructConditions(
            rtp=WINCAP_RTP[mode], av_win=wincap, search_conditions=wincap
        ).return_dict(),
        "0": ConstructConditions(rtp=0, av_win=0, search_conditions=0).return_dict(),
    }
    used_rtp = WINCAP_RTP[mode]
    rest = None
    for bonus, target in SPIN_MODE_BONUSES[mode].items():
        if target.get("takes_rest"):
            rest = bonus  # added last: it is the catch-all
            continue
        bonus_rtp = round(target["av_win"] / (target["hr"] * cost), 5)
        search = target.get("search", {"bonus": bonus})
        if "range" in target:
            search = payout_range(target["range"], cost, wincap)
        conditions[bonus] = ConstructConditions(
            rtp=bonus_rtp, hr=target["hr"], search_conditions=search
        ).return_dict()
        if "bonus_range" in target:
            # A bonus type AND a payout range: only the rounds of that bonus inside the range.
            conditions[bonus]["search_range"] = payout_range(
                target["bonus_range"], cost, wincap
            )
        used_rtp += bonus_rtp
    if rest is not None:
        # Mystery buy: no payout bands. The last criteria takes the rounds and the RTP left over.
        conditions[rest] = ConstructConditions(
            hr=SPIN_MODE_BONUSES[mode][rest]["hr"], rtp=round(rtp - used_rtp, 5)
        ).return_dict()
        return conditions
    used_rtp += add_bands(conditions, SPIN_BANDS[mode], cost, wincap)[0]
    conditions["basegame"] = ConstructConditions(
        hr=round(1.0 / SPIN_BASEGAME_SHARE[mode], 10), rtp=round(rtp - used_rtp, 5)
    ).return_dict()
    return conditions


def payout_range(band: tuple, cost: float, wincap: float) -> tuple:
    """(from, to] in multiples of the cost as a payout range in multiples of the bet."""
    low, high = band
    # A range without an upper edge ends just below the max win, which has its own criteria.
    high_win = round(high * cost, 2) if high is not None else wincap - 0.05
    # An edge of 1.0 sits just below the cost (payouts are multiples of 0.1x the bet).
    low_win = round(low * cost, 2)
    if low == 1.0:
        low_win = round(low_win - BELOW_COST, 2)
    if high == 1.0:
        high_win = round(high_win - BELOW_COST, 2)
    return low_win, high_win


def add_bands(conditions: dict, bands: list, cost: float, wincap: float) -> tuple:
    """Add one payout-range criteria per band. Returns (RTP used, share of rounds used)."""
    used_rtp, used_share = 0.0, 0.0
    for band in bands:
        band_rtp = round(band["share"] * band["average"], 5)
        conditions[band["name"]] = ConstructConditions(
            rtp=band_rtp,
            hr=round(1.0 / band["share"], 10),
            search_conditions=payout_range(band["range"], cost, wincap),
        ).return_dict()
        used_rtp += band_rtp
        used_share += band["share"]
    return used_rtp, used_share


def bonus_mode_conditions(mode: str, cost: float, rtp: float, wincap: float) -> dict:
    """Criteria targets of a bonus buy: the max win, the payout bands, then what is left."""
    conditions = {
        "wincap": ConstructConditions(
            rtp=WINCAP_RTP[mode], av_win=wincap, search_conditions=wincap
        ).return_dict(),
    }
    band_rtp, band_share = add_bands(conditions, BUY_BANDS[mode], cost, wincap)
    used_rtp = WINCAP_RTP[mode] + band_rtp
    used_share = WINCAP_RTP[mode] * cost / wincap + band_share
    # Everything not taken above: the band (0.8, 1) x cost.
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
                "conditions": spin_mode_conditions(
                    mode, cost, rtps[mode], wincaps[mode]
                ),
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
                "targets": mode_targets(mode, cost),
            }

        # Bonus buys, and the mystery buy (a spin that lands no bonus or one of the three).
        for mode in ("refine", "surge", "mystery"):
            cost = costs[mode]
            make_conditions = (
                spin_mode_conditions if mode == "mystery" else bonus_mode_conditions
            )
            opt_params[mode] = {
                "conditions": make_conditions(mode, cost, rtps[mode], wincaps[mode]),
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
                "targets": mode_targets(mode, cost),
            }

        self.game_config.opt_params = opt_params
        verify_optimization_input(self.game_config, self.game_config.opt_params)
