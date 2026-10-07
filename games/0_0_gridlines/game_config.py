"""Game-specific configuration file, inherits from src/config/config.py"""

import os
from src.config.config import Config
from src.config.distributions import Distribution
from src.config.betmode import BetMode


class GameConfig(Config):
    """Grid-line pays on a 5x5 collapse grid, with three feature spins and three bonus games."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        super().__init__()
        self.game_id = "0_0_gridlines"
        self.provider_number = 0
        self.working_name = "Grid Line Pays"
        self.game_name = "grid_line_pays"
        self.wincap = 10000.0
        self.refine_wincap = 2500.0  # max win of the "refine" bonus buy
        self.win_type = "gridlines"
        self.rtp = 0.9330
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
        self.mult_step_per_run = 1  # multiplier added for every winning run, applied from the next collapse

        # Bonus games. Three or more scatters on the first drop trigger one of them.
        self.bonus_types = ["refine", "surge", "survival"]
        # scatters -> free spins (refine, surge) or lives (survival)
        self.bonus_awards = {
            "refine": {3: 6, 4: 8, 5: 10},
            "surge": {3: 8, 4: 10, 5: 12},
            "survival": {3: 3, 4: 4, 5: 5},
        }
        # Refine: after every winning spin the lowest symbol left is upgraded into the next one,
        # and the multiplier the following spins start on rises by refine_mult_per_level.
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
        self.refine_mult_per_level = 1
        # Surge: wilds dropped on every spin, the multiplier never resets, a full line doubles it.
        self.bonus_wild_drop = {"surge": {1: 3, 2: 2}}
        self.surge_full_line_double = True
        # Survival: the multiplier is kept while spins keep winning. Hard stop on the number of
        # spins so a round can never run forever.
        self.survival_max_spins = 60
        self.survival_start_wilds = 2  # wilds already on the grid for the first spin

        # Only the keys (scatter counts) are read by the SDK; awards come from bonus_awards.
        self.freespin_triggers = {
            self.basegame_type: {3: 8, 4: 10, 5: 12},
            self.freegame_type: {3: 8, 4: 10, 5: 12},
        }
        self.anticipation_triggers = {
            self.basegame_type: min(self.freespin_triggers[self.basegame_type].keys()) - 1,
            self.freegame_type: min(self.freespin_triggers[self.freegame_type].keys()) - 1,
        }

        # Reels (built by build_reels.py)
        reels = {"BR0": "BR0.csv", "FRS": "FRS.csv", "FRR": "FRR.csv", "FRV": "FRV.csv", "WCAP": "WCAP.csv"}
        self.reels = {}
        for r, f in reels.items():
            self.reels[r] = self.read_reels_csv(os.path.join(self.reels_path, f))

        self.padding_reels[self.basegame_type] = self.reels["BR0"]
        self.padding_reels[self.freegame_type] = self.reels["FRS"]

        # ------------------------------------------------------------------------------
        # Simulation conditions
        # ------------------------------------------------------------------------------
        base_reels = {self.basegame_type: {"BR0": 1}, self.freegame_type: {"FRS": 1}}
        bonus_reels = {"refine": {"FRR": 1}, "surge": {"FRS": 1}, "survival": {"FRV": 1}}
        wincap_reels = {
            "refine": {"FRR": 1, "WCAP": 4},
            "surge": {"FRS": 1, "WCAP": 4},
            "survival": {"FRV": 1, "WCAP": 4},
        }

        def spin_condition(**extra) -> dict:
            """A paid spin that does not trigger a bonus."""
            return {"reel_weights": base_reels, "force_wincap": False, "force_freegame": False, **extra}

        def bonus_condition(bonus_weights: dict, scatter_triggers: dict, **extra) -> dict:
            """A paid spin forced to trigger a bonus of one of the weighted types."""
            return {
                "reel_weights": base_reels,
                "bonus_reels": bonus_reels,
                "bonus_weights": bonus_weights,
                "scatter_triggers": scatter_triggers,
                "force_wincap": False,
                "force_freegame": True,
                **extra,
            }

        def wincap_condition(bonus_weights: dict, scatter_triggers: dict, **extra) -> dict:
            """A bonus played on the max-win strip until the win cap is reached."""
            return {
                "reel_weights": base_reels,
                "bonus_reels": wincap_reels,
                "bonus_weights": bonus_weights,
                "scatter_triggers": scatter_triggers,
                "force_wincap": True,
                "force_freegame": True,
                **extra,
            }

        # Scatter counts of a bonus triggered from a paid spin, and of a max-win round.
        natural_triggers = {3: 90, 4: 9, 5: 1}
        wincap_triggers = {4: 1, 5: 2}
        # Refine cannot reach the game's win cap, so max-win rounds of paid spins use the other two.
        wincap_bonuses = {"surge": 1, "survival": 1}

        # Wild spin: 2 or 3 wilds are dropped onto the grid before it is evaluated.
        wild_drop = {"wild_drop": {2: 4, 3: 1}}
        # Prime spin: the three lowest symbols are already upgraded.
        prime = {"refine_level": 3}

        def feature_spin_mode(name: str, cost: float, quotas: dict, extra: dict) -> BetMode:
            """Bet mode for a paid spin (base game and the feature spins)."""
            return BetMode(
                name=name,
                cost=cost,
                rtp=self.rtp,
                max_win=self.wincap,
                auto_close_disabled=False,
                is_feature=True,
                is_buybonus=False,
                distributions=[
                    Distribution(
                        criteria="wincap",
                        quota=quotas["wincap"],
                        win_criteria=self.wincap,
                        conditions=wincap_condition(wincap_bonuses, wincap_triggers, **extra),
                    ),
                    Distribution(
                        criteria="refine",
                        quota=quotas["refine"],
                        conditions=bonus_condition({"refine": 1}, natural_triggers, **extra),
                    ),
                    Distribution(
                        criteria="surge",
                        quota=quotas["surge"],
                        conditions=bonus_condition({"surge": 1}, natural_triggers, **extra),
                    ),
                    Distribution(
                        criteria="survival",
                        quota=quotas["survival"],
                        conditions=bonus_condition({"survival": 1}, natural_triggers, **extra),
                    ),
                    Distribution(criteria="0", quota=quotas["0"], win_criteria=0.0, conditions=spin_condition(**extra)),
                    Distribution(criteria="basegame", quota=quotas["basegame"], conditions=spin_condition(**extra)),
                ],
            )

        def bonus_buy_mode(name: str, cost: float, max_win: float, max_win_triggers: dict) -> BetMode:
            """Bet mode that buys one bonus game directly (always three scatters)."""
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
                        conditions=wincap_condition({name: 1}, max_win_triggers),
                    ),
                    Distribution(
                        criteria="freegame",
                        quota=0.999,
                        conditions=bonus_condition({name: 1}, {3: 1}),
                    ),
                ],
            )

        # Contains all game-logic simulation conditions
        self.bet_modes = [
            feature_spin_mode(
                "base",
                1.0,
                {"wincap": 0.001, "refine": 0.04, "surge": 0.04, "survival": 0.05, "0": 0.30, "basegame": 0.569},
                {},
            ),
            feature_spin_mode(
                "wildspin",
                5.0,
                {"wincap": 0.001, "refine": 0.04, "surge": 0.04, "survival": 0.05, "0": 0.12, "basegame": 0.749},
                wild_drop,
            ),
            feature_spin_mode(
                "primespin",
                20.0,
                {"wincap": 0.001, "refine": 0.04, "surge": 0.04, "survival": 0.05, "0": 0.02, "basegame": 0.849},
                prime,
            ),
            # Refine is the low-risk bonus: its own ceiling is lower than the game's win cap.
            bonus_buy_mode("refine", 100.0, self.refine_wincap, {5: 1}),
            bonus_buy_mode("surge", 150.0, self.wincap, wincap_triggers),
            bonus_buy_mode("survival", 300.0, self.wincap, wincap_triggers),
        ]
