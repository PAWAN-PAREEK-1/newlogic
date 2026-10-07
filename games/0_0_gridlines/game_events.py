"""Events specific to the grid-line pays game.

Standard SDK events used unchanged: reveal, winInfo, updateTumbleWin, setWin, setTotalWin,
updateGlobalMult, updateFreeSpin, freeSpinEnd, wincap, finalWin.
updateGlobalMult is sent only when the multiplier changes.

All positions are board positions {"reel": 0-4, "row": 0-4}, row 0 at the top. The game has
no padding rows, so nothing is offset.
"""

from copy import deepcopy

from src.events.event_constants import EventConstants

WILD_DROP = "wildDrop"
COLLAPSE_BOARD = "collapseBoard"
STICKY_WILDS = "stickyWilds"
REFINE_SYMBOL = "refineSymbol"
PRIME_SYMBOLS = "primeSymbols"
UPDATE_LIVES = "updateLives"


def wild_drop_event(gamestate, positions: list) -> None:
    """Wilds dropped onto the revealed board before it is evaluated."""
    event = {
        "index": len(gamestate.book.events),
        "type": WILD_DROP,
        "positions": deepcopy(positions),
    }
    gamestate.book.add_event(event)


def sticky_wilds_event(gamestate, positions: list) -> None:
    """Survival bonus: wilds carried over from the previous spin (sent before the reveal)."""
    event = {
        "index": len(gamestate.book.events),
        "type": STICKY_WILDS,
        "positions": deepcopy(positions),
    }
    gamestate.book.add_event(event)


def collapse_board_event(gamestate) -> None:
    """Winning symbols removed, centre wilds created, remaining symbols dropped.

    explodingSymbols: positions removed from the board that was just evaluated.
    newWilds: wilds created in an exploding position; "landingRow" is the row each one
        ends on after the fall.
    The event does not repeat the whole board. To get the board after the fall: remove the
    exploding symbols, put a wild in every newWilds position, then let the symbols of each
    reel fall to the bottom keeping their order. Nothing new drops in.
    """
    event = {
        "index": len(gamestate.book.events),
        "type": COLLAPSE_BOARD,
        "explodingSymbols": deepcopy(gamestate.exploded_positions),
        "newWilds": [
            {"reel": s["reel"], "row": s["row"], "landingRow": s["landingRow"]} for s in gamestate.spawned_symbols
        ],
    }
    gamestate.book.add_event(event)


def bonus_trigger_event(gamestate) -> None:
    """Scatters trigger a bonus game. Sent in place of the SDK freeSpinTrigger event.

    bonusType: "surge", "refine" or "survival".
    totalFs: free spins awarded (surge, refine). 0 for survival, which is played on lives.
    lives: lives awarded (survival). 0 for the other bonus games.
    """
    is_survival = gamestate.bonus_type == "survival"
    event = {
        "index": len(gamestate.book.events),
        "type": EventConstants.FREESPINTRIGGER.value,
        "bonusType": gamestate.bonus_type,
        "totalFs": 0 if is_survival else int(gamestate.tot_fs),
        "lives": int(gamestate.lives) if is_survival else 0,
        "positions": deepcopy(gamestate.special_syms_on_board["scatter"]),
    }
    gamestate.book.add_event(event)


def prime_symbols_event(gamestate) -> None:
    """Prime spin: the lowest symbols removed for this spin (sent before the reveal).

    removedSymbols never land on this spin; each one lands as `landAs` instead.
    """
    removed = list(gamestate.config.refine_order[: gamestate.refine_level])
    event = {
        "index": len(gamestate.book.events),
        "type": PRIME_SYMBOLS,
        "level": int(gamestate.refine_level),
        "removedSymbols": removed,
        "landAs": gamestate.apply_refine(removed[-1]) if removed else None,
    }
    gamestate.book.add_event(event)


def refine_symbol_event(gamestate, removed: str, into: str) -> None:
    """Refine bonus: a symbol is upgraded for the rest of the bonus.

    From the next spin on, every `removed` symbol lands as `into`.
    """
    event = {
        "index": len(gamestate.book.events),
        "type": REFINE_SYMBOL,
        "level": int(gamestate.refine_level),
        "removed": removed,
        "into": into,
        "removedSymbols": list(gamestate.config.refine_order[: gamestate.refine_level]),
    }
    gamestate.book.add_event(event)


def update_lives_event(gamestate, lost_life: bool = False) -> None:
    """Survival bonus: lives left and the number of the spin about to be played."""
    event = {
        "index": len(gamestate.book.events),
        "type": UPDATE_LIVES,
        "lives": int(gamestate.lives),
        "spin": int(gamestate.fs),
        "lostLife": bool(lost_life),
    }
    gamestate.book.add_event(event)
