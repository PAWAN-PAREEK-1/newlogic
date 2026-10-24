"""Events specific to the grid-line pays game.

Standard SDK events used unchanged: reveal, winInfo, updateTumbleWin, setWin, setTotalWin,
updateGlobalMult, updateFreeSpin, freeSpinEnd, wincap, finalWin.
updateGlobalMult is sent only when the paid-spin multiplier changes; a bonus sends
updateLineMult for its row and column multipliers instead.

Positions are sent the way the SDK events send them (win_info_event and fs_trigger_event
with their default include_padding_index), so every game reads them the same way:
{"reel": 0-4, "row": 1-5}, where row = board row + 1 and row 1 is the top of the grid.
"""

from src.events.event_constants import EventConstants

WILD_DROP = "wildDrop"
COLLAPSE_BOARD = "collapseBoard"
REFINE_SYMBOL = "refineSymbol"
PRIME_SYMBOLS = "primeSymbols"
UPDATE_LINE_MULT = "updateLineMult"

ROW_OFFSET = 1  # event row = board row + ROW_OFFSET


def client_positions(positions: list) -> list:
    """Board positions as they are sent in events."""
    return [{"reel": p["reel"], "row": p["row"] + ROW_OFFSET} for p in positions]


def wild_drop_event(gamestate, positions: list) -> None:
    """Wilds dropped onto the revealed board before it is evaluated."""
    event = {
        "index": len(gamestate.book.events),
        "type": WILD_DROP,
        "positions": client_positions(positions),
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
        "explodingSymbols": client_positions(gamestate.exploded_positions),
        "newWilds": [
            {"reel": s["reel"], "row": s["row"] + ROW_OFFSET, "landingRow": s["landingRow"] + ROW_OFFSET}
            for s in gamestate.spawned_symbols
        ],
    }
    gamestate.book.add_event(event)


def bonus_trigger_event(gamestate) -> None:
    """Scatters trigger a bonus game. The SDK freeSpinTrigger event plus bonusType.

    bonusType: the bonus game the number of scatters triggered ("refine", "surge" or "fusion").
    """
    event = {
        "index": len(gamestate.book.events),
        "type": EventConstants.FREESPINTRIGGER.value,
        "totalFs": int(gamestate.tot_fs),
        "positions": client_positions(gamestate.special_syms_on_board["scatter"]),
        "bonusType": gamestate.bonus_type,
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
    """Bonus with symbol upgrades: a symbol is upgraded for the rest of the bonus.

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


def update_line_mult_event(gamestate) -> None:
    """Bonus games: the multiplier of every row and column.

    Sent when a bonus starts (every line at 1) and after a collapse that changed a value.
    rows[i] is the multiplier of board row i (top first) and columns[i] of reel i: the same
    index as "lineIndex" in winInfo meta for direction "row" / "column".
    """
    event = {
        "index": len(gamestate.book.events),
        "type": UPDATE_LINE_MULT,
        "rows": list(gamestate.line_mults["row"]),
        "columns": list(gamestate.line_mults["column"]),
    }
    gamestate.book.add_event(event)
