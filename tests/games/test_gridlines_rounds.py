"""Play rounds of every bet mode of 0_0_gridlines and replay them with the independent checker."""

import importlib

import pytest

GAME = "games.0_0_gridlines"
config_module = importlib.import_module(f"{GAME}.game_config")
gamestate_module = importlib.import_module(f"{GAME}.gamestate")
verify_books = importlib.import_module(f"{GAME}.verify_books")

# (mode, criteria, rounds)
CASES = [
    ("base", "basegame", 150),
    ("base", "0", 50),
    ("base", "refine", 15),
    ("base", "surge", 15),
    ("base", "survival", 15),
    ("base", "wincap", 2),
    ("wildspin", "basegame", 100),
    ("wildspin", "surge", 10),
    ("primespin", "basegame", 100),
    ("primespin", "refine", 10),
    ("refine", "freegame", 30),
    ("refine", "wincap", 2),
    ("surge", "freegame", 30),
    ("surge", "wincap", 2),
    ("survival", "freegame", 30),
    ("survival", "wincap", 2),
]


@pytest.fixture(scope="module")
def game():
    config = config_module.GameConfig()
    return config, gamestate_module.GameState(config)


@pytest.mark.parametrize("mode,criteria,rounds", CASES)
def test_rounds_follow_the_rules(game, mode, criteria, rounds):
    config, gamestate = game
    bet_mode = next(bm for bm in config.bet_modes if bm.get_name() == mode)
    distribution = next(d for d in bet_mode.get_distributions() if d.get_criteria() == criteria)
    conditions = {d.get_criteria(): d._conditions for d in bet_mode.get_distributions()}
    replay = verify_books.BookReplay(config, mode, conditions, bet_mode.get_wincap())

    config.wincap = bet_mode.get_wincap()  # create_books sets the mode's max win the same way
    gamestate.betmode = mode
    gamestate.criteria = criteria
    for sim in range(rounds):
        gamestate.run_spin(sim)
        book = gamestate.book.to_json()
        replay.replay(book)

        payout = book["payoutMultiplier"]
        if distribution.get_win_criteria() is not None:
            assert payout == int(round(distribution.get_win_criteria() * 100))
        else:
            assert 0 < payout <= int(round(bet_mode.get_wincap() * 100))
        triggered = any(event["type"] == "freeSpinTrigger" for event in book["events"])
        assert triggered == distribution._conditions["force_freegame"]


def test_rounds_are_reproducible(game):
    """The same simulation number always produces the same book: nothing is carried between bets."""
    config, gamestate = game
    config.wincap = config.bet_modes[0].get_wincap()
    gamestate.betmode = "base"
    gamestate.criteria = "survival"
    gamestate.run_spin(7)
    first = gamestate.book.to_json()
    gamestate.criteria = "basegame"
    for sim in range(20):
        gamestate.run_spin(sim)
    gamestate.criteria = "survival"
    gamestate.run_spin(7)
    assert gamestate.book.to_json() == first
