"""Game-specific configuration file, inherits from src/config/config.py"""

import os
from src.config.config import Config
from src.config.distributions import Distribution
from src.config.betmode import BetMode


def line_ladder(rate: float, turn: int, steep_rate: float, top: int) -> list:
    """Values of a line multiplier, one per step.

    The multiplier grows by `rate` per step for the first `turn` steps and by `steep_rate` per
    step after that, until it reaches `top`. Values are whole numbers.
    """
    ladder, step = [], 0
    while not ladder or ladder[-1] < top:
        value = rate**step if step <= turn else rate**turn * steep_rate ** (step - turn)
        ladder.append(min(top, max(1, round(value))))
        step += 1
    return ladder


class GameConfig(Config):
    """Grid-line pays on a 5x5 collapse grid: two feature spins, three bonus games, a mystery buy."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        super().__init__()
        self.game_id = "gridlines"
        self.provider_number = 0
        self.working_name = "Grid Line Pays"
        self.game_name = "grid_line_pays"
        self.wincap = 25000.0
        self.win_type = "gridlines"
        self.rtp = 0.9601
        self.construct_paths()

        # Game Dimensions
        self.num_reels = 5
        self.num_rows = [5] * self.num_reels

        # Win logic: straight runs of 3, 4 or 5 like symbols in any row or column.
        self.min_run = 3
        self.paytable = {
            (5, "W"): 6,
            (4, "W"): 2,
            (3, "W"): 0.8,
            (5, "H1"): 6,
            (4, "H1"): 2,
            (3, "H1"): 0.8,
            (5, "H2"): 4,
            (4, "H2"): 1.5,
            (3, "H2"): 0.5,
            (5, "H3"): 3,
            (4, "H3"): 1,
            (3, "H3"): 0.4,
            (5, "H4"): 2,
            (4, "H4"): 0.8,
            (3, "H4"): 0.3,
            (5, "L1"): 1,
            (4, "L1"): 0.4,
            (3, "L1"): 0.2,
            (5, "L2"): 0.8,
            (4, "L2"): 0.3,
            (3, "L2"): 0.1,
            (5, "L3"): 0.8,
            (4, "L3"): 0.3,
            (3, "L3"): 0.1,
            (5, "L4"): 0.6,
            (4, "L4"): 0.2,
            (3, "L4"): 0.1,
            (5, "L5"): 0.6,
            (4, "L5"): 0.2,
            (3, "L5"): 0.1,
        }

        # The grid has no spinning reels, so no padding symbols above or below the board.
        self.include_padding = False
        # "blank" marks an empty board position after a collapse.
        self.special_symbols = {"wild": ["W"], "scatter": ["S"], "blank": ["X"]}

        # Collapse rules (see readme.txt)
        self.centre_wild = True  # every winning run leaves a wild in its centre
        # Paid spins (base game, wild spin, prime spin): the win multiplier climbs a ladder. Every
        # winning run moves it one step up, the new value applies from the next collapse and it
        # goes back to 1x on the next spin. The first ten steps add +1, after that the ladder
        # gets steep, so long chains are what pay big.
        self.mult_step_per_run = 1
        self.mult_ladder = [
            1,
            2,
            3,
            4,
            5,
            6,
            7,
            8,
            9,
            10,
            14,
            20,
            28,
            40,
            55,
            75,
            100,
            150,
            200,
            300,
            400,
            500,
            750,
            1000,
        ]

        # Bonus games. The number of scatters on the first drop decides which one is played and
        # how many free spins it has.
        self.bonus_by_scatters = {3: "refine", 4: "surge", 5: "fusion"}
        self.bonus_awards = {"refine": 8, "surge": 12, "fusion": 15}

        # Line multipliers: what every bonus game has and a paid spin does not. Each of the 5
        # rows and 5 columns has its own multiplier, and a run pays at the multiplier of the row
        # or column it is in. Every winning run moves the multiplier of its line one step up its
        # ladder; the new value applies from the next collapse and is kept until the bonus ends.
        # The paid-spin ladder above is not used in a bonus.
        #
        # A ladder has two parts. A bonus has many runs (about 50 in Refine, 80 in Surge and 170
        # in Fusion), so the first part is slow: it covers the steps a normal bonus reaches. The
        # second part is steep and is only reached when one line keeps winning; that is where
        # the big wins and the max win come from. The longer the bonus, the later the turn.
        self.line_mult_step_per_run = 1
        self.line_mult_top = 5000
        self.bonus_line_mult_ladder = {
            # +7% per step for 19 steps (x1 .. x4), then +70% per step
            "refine": line_ladder(1.07, 19, 1.7, self.line_mult_top),
            # +16% per step for 38 steps (x1 .. x282), then +50% per step
            "surge": line_ladder(1.16, 38, 1.5, self.line_mult_top),
            # +8.5% per step for 42 steps (x1 .. x31), then +60% per step
            "fusion": line_ladder(1.085, 42, 1.6, self.line_mult_top),
        }
        # Ladder of a bonus that has none of its own.
        self.line_mult_ladder = self.bonus_line_mult_ladder["refine"]

        # What each bonus adds to the line multipliers:
        #   refine   symbol upgrades
        #   surge    wilds dropped on every spin
        #   fusion   both
        # Symbol upgrades: after every winning spin the lowest symbol left is upgraded into the
        # next one for the rest of the bonus.
        self.bonus_upgrades = ["refine", "fusion"]
        self.refine_order = ["L5", "L4", "L3", "L2", "L1", "H4", "H3", "H2"]
        self.refine_into = {
            "L5": "L4",
            "L4": "L3",
            "L3": "L2",
            "L2": "L1",
            "L1": "H4",
            "H4": "H3",
            "H3": "H2",
            "H2": "H1",
        }
        # Wild drop: this many wilds are dropped onto the grid on every spin of the bonus.
        self.bonus_wild_drop = {"surge": {3: 1}, "fusion": {3: 1}}

        # Only the keys (scatter counts) are read by the SDK; awards come from bonus_awards.
        self.freespin_triggers = {
            self.basegame_type: {3: 8, 4: 10, 5: 12},
            self.freegame_type: {3: 8, 4: 10, 5: 12},
        }
        self.anticipation_triggers = {
            self.basegame_type: min(self.freespin_triggers[self.basegame_type].keys())
            - 1,
            self.freegame_type: min(self.freespin_triggers[self.freegame_type].keys())
            - 1,
        }

        # Reels (built by build_reels.py)
        reels = {
            "BR0": "BR0.csv",
            "FRS": "FRS.csv",
            "FRR": "FRR.csv",
            "WCAP": "WCAP.csv",
        }
        self.reels = {}
        for r, f in reels.items():
            self.reels[r] = self.read_reels_csv(os.path.join(self.reels_path, f))

        self.padding_reels[self.basegame_type] = self.reels["BR0"]
        self.padding_reels[self.freegame_type] = self.reels["FRS"]

        # ------------------------------------------------------------------------------
        # Simulation conditions
        # ------------------------------------------------------------------------------
        base_reels = {self.basegame_type: {"BR0": 1}, self.freegame_type: {"FRS": 1}}
        bonus_reels = {
            "refine": {"FRR": 1},
            "surge": {"FRS": 1},
            "fusion": {"FRS": 1},
        }
        wincap_reels = {bonus: {"WCAP": 1} for bonus in bonus_reels}

        def spin_condition(**extra) -> dict:
            """A paid spin that does not trigger a bonus."""
            return {
                "reel_weights": base_reels,
                "force_wincap": False,
                "force_freegame": False,
                **extra,
            }

        def bonus_condition(scatter_triggers: dict, **extra) -> dict:
            """A paid spin forced to land scatters; their number decides the bonus played."""
            return {
                "reel_weights": base_reels,
                "bonus_reels": bonus_reels,
                "scatter_triggers": scatter_triggers,
                "force_wincap": False,
                "force_freegame": True,
                **extra,
            }

        def wincap_condition(scatter_triggers: dict, **extra) -> dict:
            """A bonus played on the max-win strip until the win cap is reached."""
            return {
                "reel_weights": base_reels,
                "bonus_reels": wincap_reels,
                "scatter_triggers": scatter_triggers,
                "force_wincap": True,
                "force_freegame": True,
                **extra,
            }

        # Scatters that trigger each bonus, and the scatter counts of a max-win round of a paid
        # spin (any of the three bonuses).
        scatters_for = {
            bonus: {count: 1} for count, bonus in self.bonus_by_scatters.items()
        }
        wincap_triggers = {count: 1 for count in self.bonus_by_scatters}

        # Wild spin: 1 to 5 wilds are dropped onto the grid before it is evaluated.
        wild_drop = {"wild_drop": {1: 60, 2: 25, 3: 10, 4: 3.5, 5: 1.5}}
        # Prime spin: 2 to 5 of the lowest symbols are already upgraded.
        prime = {"refine_level": {2: 60, 3: 28, 4: 10, 5: 2}}

        def feature_spin_mode(
            name: str, cost: float, quotas: dict, extra: dict, is_buy: bool = False
        ) -> BetMode:
            """Bet mode for a paid spin: the base game, the feature spins and the mystery buy.

            Every criteria is one kind of round: no bonus ("0" pays nothing, "basegame" wins),
            one of the three bonus games, or the max win. The quotas are how many books of each
            kind are simulated; how often each kind is PLAYED is set in game_optimization.py.
            """
            return BetMode(
                name=name,
                cost=cost,
                rtp=self.rtp,
                max_win=self.wincap,
                auto_close_disabled=False,
                is_feature=not is_buy,
                is_buybonus=is_buy,
                distributions=[
                    Distribution(
                        criteria="wincap",
                        quota=quotas["wincap"],
                        win_criteria=self.wincap,
                        conditions=wincap_condition(wincap_triggers, **extra),
                    ),
                    Distribution(
                        criteria="refine",
                        quota=quotas["refine"],
                        conditions=bonus_condition(
                            scatters_for["refine"], **extra
                        ),
                    ),
                    Distribution(
                        criteria="surge",
                        quota=quotas["surge"],
                        conditions=bonus_condition(
                            scatters_for["surge"], **extra
                        ),
                    ),
                    Distribution(
                        criteria="fusion",
                        quota=quotas["fusion"],
                        conditions=bonus_condition(
                            scatters_for["fusion"], **extra
                        ),
                    ),
                    Distribution(
                        criteria="0",
                        quota=quotas["0"],
                        win_criteria=0.0,
                        conditions=spin_condition(**extra),
                    ),
                    Distribution(
                        criteria="basegame",
                        quota=quotas["basegame"],
                        conditions=spin_condition(**extra),
                    ),
                ],
            )

        def bonus_buy_mode(name: str, cost: float, max_win: float) -> BetMode:
            """Bet mode that buys one bonus game directly (with the scatters that trigger it)."""
            return BetMode(
                name=name,
                cost=cost,
                rtp=self.rtp,
                max_win=max_win,
                auto_close_disabled=False,
                is_feature=False,
                is_buybonus=True,
                distributions=[
                    Distribution(
                        criteria="wincap",
                        quota=0.001,
                        win_criteria=max_win,
                        conditions=wincap_condition(scatters_for[name]),
                    ),
                    Distribution(
                        criteria="freegame",
                        quota=0.999,
                        conditions=bonus_condition(scatters_for[name]),
                    ),
                ],
            )

        # Contains all game-logic simulation conditions
        self.bet_modes = [
            feature_spin_mode(
                "base",
                1.0,
                {
                    "wincap": 0.001,
                    "refine": 0.04,
                    "surge": 0.04,
                    "fusion": 0.05,
                    "0": 0.30,
                    "basegame": 0.569,
                },
                {},
            ),
            feature_spin_mode(
                "wildspin",
                5.0,
                {
                    "wincap": 0.001,
                    "refine": 0.04,
                    "surge": 0.04,
                    "fusion": 0.05,
                    "0": 0.12,
                    "basegame": 0.749,
                },
                wild_drop,
            ),
            feature_spin_mode(
                "primespin",
                20.0,
                {
                    "wincap": 0.001,
                    "refine": 0.04,
                    "surge": 0.04,
                    "fusion": 0.05,
                    "0": 0.02,
                    "basegame": 0.849,
                },
                prime,
            ),
            bonus_buy_mode("refine", 100.0, self.wincap),
            bonus_buy_mode("surge", 200.0, self.wincap),
            # Mystery buy: a spin that lands no bonus, Refine, Surge or Fusion. Half of the
            # rounds have no bonus; the chances are set in game_optimization.py.
            feature_spin_mode(
                "mystery",
                300.0,
                {
                    "wincap": 0.001,
                    "refine": 0.25,
                    "surge": 0.25,
                    "fusion": 0.299,
                    "0": 0.05,
                    "basegame": 0.15,
                },
                {},
                is_buy=True,
            ),
        ]
