"""Export the Python GameConfig to a JSON spec consumed by the Go engine.

Serialises games/gridlines/game_config.py into library/configs/game_spec_go.json,
which go_engine/game/gridlines.go loads. game_config.py stays the single source of
truth: edit it as usual and the next Go run picks the changes up.

Everything order-sensitive is exported as an ARRAY, never a JSON object: Python
iterates dicts in insertion order and the random-number generator consumes weights in
that order, so preserving order is what keeps Go output byte-identical to Python output.
"""

import json
import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _weighted_int_table(dist: dict) -> list:
    """{value: weight, ...} -> [{"v": value, "w": weight}, ...] keeping order."""
    return [{"v": int(value), "w": weight} for value, weight in dist.items()]


def _weighted_str_table(dist: dict) -> list:
    return [{"v": str(value), "w": weight} for value, weight in dist.items()]


def _export_conditions(conditions: dict) -> dict:
    """Serialise one Distribution's conditions dict (absent keys stay absent)."""
    out = {
        "reel_weights": {
            gametype: _weighted_str_table(weights)
            for gametype, weights in conditions["reel_weights"].items()
        },
        "force_wincap": bool(conditions.get("force_wincap", False)),
        "force_freegame": bool(conditions.get("force_freegame", False)),
    }
    if "scatter_triggers" in conditions:
        out["scatter_triggers"] = _weighted_int_table(conditions["scatter_triggers"])
    if "bonus_reels" in conditions:
        out["bonus_reels"] = {
            bonus: _weighted_str_table(weights)
            for bonus, weights in conditions["bonus_reels"].items()
        }
    if conditions.get("wild_drop") is not None:
        out["wild_drop"] = _weighted_int_table(conditions["wild_drop"])
    level = conditions.get("refine_level", 0)
    if isinstance(level, dict):
        out["refine_level"] = _weighted_int_table(level)
    else:
        out["refine_level_fixed"] = int(level)
    return out


def _export_game(config) -> dict:
    """Game-specific attributes read by go_engine/game/gridlines.go."""
    return {
        "min_run": int(config.min_run),
        "centre_wild": bool(config.centre_wild),
        "mult_step_per_run": int(config.mult_step_per_run),
        "mult_ladder": [int(v) for v in config.mult_ladder],
        "bonus_by_scatters": [
            {"scatters": int(count), "bonus": bonus} for count, bonus in config.bonus_by_scatters.items()
        ],
        "bonus_awards": {bonus: int(award) for bonus, award in config.bonus_awards.items()},
        "line_mult_step_per_run": int(config.line_mult_step_per_run),
        "line_mult_ladder": [int(v) for v in config.line_mult_ladder],
        "bonus_line_mult_ladder": {
            bonus: [int(v) for v in ladder] for bonus, ladder in config.bonus_line_mult_ladder.items()
        },
        "bonus_upgrades": list(config.bonus_upgrades),
        "refine_order": list(config.refine_order),
        "refine_into": dict(config.refine_into),
        "bonus_wild_drop": {
            bonus: _weighted_int_table(dist) for bonus, dist in config.bonus_wild_drop.items()
        },
        "blank_symbol": config.special_symbols["blank"][0],
    }


def _win_levels() -> dict:
    """Mirror of Config.get_win_level in src/config/config.py."""
    return {
        "standard": [
            {"level": 1, "min": 0, "max": 0.1},
            {"level": 2, "min": 0.1, "max": 1.0},
            {"level": 3, "min": 1.0, "max": 2.0},
            {"level": 4, "min": 2.0, "max": 5.0},
            {"level": 5, "min": 5.0, "max": 15.0},
            {"level": 6, "min": 15.0, "max": 30.0},
            {"level": 7, "min": 30.0, "max": 50.0},
            {"level": 8, "min": 50.0, "max": 100.0},
            {"level": 9, "min": 100.0, "max": "wincap"},
            {"level": 10, "min": "wincap", "max": "inf"},
        ],
        "endFeature": [
            {"level": 1, "min": 0.0, "max": 1.0},
            {"level": 2, "min": 1.0, "max": 5.0},
            {"level": 3, "min": 5.0, "max": 10.0},
            {"level": 4, "min": 10.0, "max": 20.0},
            {"level": 5, "min": 20.0, "max": 50.0},
            {"level": 6, "min": 50.0, "max": 100.0},
            {"level": 7, "min": 100.0, "max": 500.0},
            {"level": 8, "min": 500.0, "max": 2000.0},
            {"level": 9, "min": 2000.0, "max": "wincap"},
            {"level": 10, "min": "wincap", "max": "inf"},
        ],
    }


def export_spec(config, out_path: str | None = None) -> str:
    """Serialise a GameConfig instance to game_spec_go.json; returns the path."""
    spec = {
        "game_id": config.game_id,
        "rtp": config.rtp,
        "num_reels": config.num_reels,
        "num_rows": list(config.num_rows),
        "include_padding": bool(config.include_padding),
        "basegame_type": config.basegame_type,
        "freegame_type": config.freegame_type,
        "paytable": [
            {"kind": int(kind), "symbol": symbol, "pay": float(pay)}
            for (kind, symbol), pay in config.paytable.items()
        ],
        "paylines": [],
        "special_symbols": [
            {"property": prop, "symbols": list(names)}
            for prop, names in config.special_symbols.items()
        ],
        "freespin_triggers": {
            gametype: [
                {"scatters": int(count), "spins": int(spins)}
                for count, spins in triggers.items()
            ]
            for gametype, triggers in config.freespin_triggers.items()
        },
        "anticipation_triggers": {
            gametype: int(v) for gametype, v in config.anticipation_triggers.items()
        },
        "reels": config.reels,
        "win_levels": _win_levels(),
        "game": _export_game(config),
        "bet_modes": [
            {
                "name": bm.get_name(),
                "cost": float(bm.get_cost()),
                "rtp": float(bm.get_rtp()),
                "max_win": float(bm.get_wincap()),
                "max_win_is_int": type(bm.get_wincap()) is int,
                "auto_close_disabled": bool(bm.get_auto_close_disabled()),
                "is_feature": bool(bm.get_feature()),
                "is_buybonus": bool(bm.get_buybonus()),
                "distributions": [
                    {
                        "criteria": dist.get_criteria(),
                        "quota": dist.get_quota() if dist.get_quota() is not None else 0.0,
                        "fixed_amt": dist.get_fixed_amt(),
                        "win_criteria": dist.get_win_criteria(),
                        "conditions": _export_conditions(dist._conditions),
                    }
                    for dist in bm.get_distributions()
                ],
            }
            for bm in config.bet_modes
        ],
    }

    if out_path is None:
        out_path = os.path.join(config.library_path, "configs", "game_spec_go.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="UTF-8") as f:
        json.dump(spec, f, indent=2)
    print(f"Exported Go engine spec: {out_path}")
    return out_path


if __name__ == "__main__":
    from games.gridlines.game_config import GameConfig

    export_spec(GameConfig())
