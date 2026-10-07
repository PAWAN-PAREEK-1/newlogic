"""Test grid-line (run) pay calculation and the no-refill collapse."""

import pytest
from tests.win_calculations.game_test_config import GamestateTest, create_blank_board
from src.calculations.board import Board
from src.calculations.collapse import Collapse
from src.calculations.gridlines import GridLines


class GameGridLinesConfig:
    """Testing game functions"""

    def __init__(self):
        self.game_id = "0_test_class"
        self.rtp = 0.9700

        # Game Dimensions
        self.num_reels = 5
        self.num_rows = [5] * self.num_reels
        # Board and Symbol Properties
        self.paytable = {
            (5, "W"): 100,
            (4, "W"): 40,
            (3, "W"): 20,
            (5, "H1"): 50,
            (4, "H1"): 20,
            (3, "H1"): 10,
            (5, "L1"): 5,
            (4, "L1"): 2,
            (3, "L1"): 1,
        }
        self.special_symbols = {"wild": ["W"], "scatter": ["S"], "blank": ["X"]}
        self.bet_modes = []
        self.basegame_type = "basegame"
        self.freegame_type = "freegame"


class GridLinesTestState(GamestateTest, Board, Collapse):
    """Test gamestate with board helpers and the collapse mixin."""

    def assign_special_sym_function(self):
        self.special_symbol_functions = {}


def set_board(gamestate, rows):
    """Fill the board from rows written the way the player sees them (top row first)."""
    for row, line in enumerate(rows):
        for reel, name in enumerate(line.split()):
            gamestate.board[reel][row] = gamestate.create_symbol(name)


def board_rows(gamestate):
    """Board as rows of symbol names, the way the player sees it."""
    num_rows = len(gamestate.board[0])
    return [" ".join(gamestate.board[reel][row].name for reel in range(len(gamestate.board))) for row in range(num_rows)]


@pytest.fixture
def gamestate():
    """Initialise test state with an empty board."""
    test_config = GameGridLinesConfig()
    test_gamestate = GridLinesTestState(test_config)
    test_gamestate.create_symbol_map()
    test_gamestate.assign_special_sym_function()
    test_gamestate.board = create_blank_board(test_config.num_reels, test_config.num_rows)
    set_board(test_gamestate, ["X X X X X"] * 5)
    return test_gamestate


def test_row_run_anywhere(gamestate):
    "A run of three pays in the middle of a row - it does not have to start on reel 1."
    set_board(
        gamestate,
        [
            "X X X X X",
            "X X X X X",
            "L1 H1 H1 H1 L1",
            "X X X X X",
            "X X X X X",
        ],
    )
    windata = GridLines.get_gridline_wins(gamestate.config, gamestate.board)
    assert windata["totalWin"] == gamestate.config.paytable[(3, "H1")]
    assert len(windata["wins"]) == 1
    win = windata["wins"][0]
    assert win["meta"]["direction"] == GridLines.ROW
    assert win["positions"] == [{"reel": 1, "row": 2}, {"reel": 2, "row": 2}, {"reel": 3, "row": 2}]
    assert win["meta"]["overlay"] == {"reel": 2, "row": 2}


def test_column_run(gamestate):
    "A vertical run pays on its length."
    set_board(
        gamestate,
        [
            "X X X X L1",
            "X X X X H1",
            "X X X X H1",
            "X X X X H1",
            "X X X X H1",
        ],
    )
    windata = GridLines.get_gridline_wins(gamestate.config, gamestate.board)
    assert windata["totalWin"] == gamestate.config.paytable[(4, "H1")]
    assert windata["wins"][0]["meta"]["direction"] == GridLines.COLUMN
    assert windata["wins"][0]["meta"]["overlay"] == {"reel": 4, "row": 2}


def test_no_diagonal_and_no_short_runs(gamestate):
    "Diagonals and runs of two never pay."
    set_board(
        gamestate,
        [
            "H1 X X X X",
            "X H1 X X X",
            "X X H1 X X",
            "X X X H1 H1",
            "L1 L1 X X X",
        ],
    )
    windata = GridLines.get_gridline_wins(gamestate.config, gamestate.board)
    assert windata["totalWin"] == 0
    assert windata["wins"] == []


def test_full_board_pays_every_row_and_column(gamestate):
    "A full board of one symbol pays five rows and five columns."
    set_board(gamestate, ["H1 H1 H1 H1 H1"] * 5)
    windata = GridLines.get_gridline_wins(gamestate.config, gamestate.board, global_multiplier=3)
    assert len(windata["wins"]) == 10
    assert windata["totalWin"] == gamestate.config.paytable[(5, "H1")] * 10 * 3
    assert all(win["meta"]["globalMult"] == 3 for win in windata["wins"])


def test_wild_extends_run(gamestate):
    "Wilds continue the run of the symbol next to them."
    set_board(
        gamestate,
        [
            "H1 W W H1 L1",
            "X X X X X",
            "X X X X X",
            "X X X X X",
            "X X X X X",
        ],
    )
    windata = GridLines.get_gridline_wins(gamestate.config, gamestate.board)
    assert len(windata["wins"]) == 1
    assert windata["wins"][0]["symbol"] == "H1"
    assert windata["wins"][0]["kind"] == 4
    assert windata["totalWin"] == gamestate.config.paytable[(4, "H1")]


def test_wild_shared_by_two_symbols(gamestate):
    "One wild can complete a run on each side of it."
    set_board(
        gamestate,
        [
            "H1 H1 W L1 L1",
            "X X X X X",
            "X X X X X",
            "X X X X X",
            "X X X X X",
        ],
    )
    windata = GridLines.get_gridline_wins(gamestate.config, gamestate.board)
    assert sorted(win["symbol"] for win in windata["wins"]) == ["H1", "L1"]
    assert windata["totalWin"] == gamestate.config.paytable[(3, "H1")] + gamestate.config.paytable[(3, "L1")]


def test_wild_only_run(gamestate):
    "A run of wilds alone pays the wild's own paytable entry."
    set_board(
        gamestate,
        [
            "X X X X X",
            "W W W X X",
            "X X X X X",
            "X X X X X",
            "X X X X X",
        ],
    )
    windata = GridLines.get_gridline_wins(gamestate.config, gamestate.board)
    assert windata["wins"][0]["symbol"] == "W"
    assert windata["totalWin"] == gamestate.config.paytable[(3, "W")]


def test_wilds_inside_symbol_run_are_not_paid_twice(gamestate):
    "Wilds used by a regular run do not also pay as a wild run."
    set_board(
        gamestate,
        [
            "W W W H1 L1",
            "X X X X X",
            "X X X X X",
            "X X X X X",
            "X X X X X",
        ],
    )
    windata = GridLines.get_gridline_wins(gamestate.config, gamestate.board)
    assert len(windata["wins"]) == 1
    assert windata["wins"][0]["symbol"] == "H1"
    assert windata["wins"][0]["kind"] == 4


def test_scatter_and_blank_break_runs(gamestate):
    "Scatters and empty positions break a run."
    set_board(
        gamestate,
        [
            "H1 H1 S H1 H1",
            "L1 L1 X L1 L1",
            "X X X X X",
            "X X X X X",
            "X X X X X",
        ],
    )
    windata = GridLines.get_gridline_wins(gamestate.config, gamestate.board)
    assert windata["totalWin"] == 0


def test_cross_pays_both_directions(gamestate):
    "A symbol shared by a row run and a column run counts for both."
    set_board(
        gamestate,
        [
            "X X H1 X X",
            "X X H1 X X",
            "H1 H1 H1 H1 H1",
            "X X X X X",
            "X X X X X",
        ],
    )
    windata = GridLines.get_gridline_wins(gamestate.config, gamestate.board)
    assert windata["totalWin"] == gamestate.config.paytable[(5, "H1")] + gamestate.config.paytable[(3, "H1")]
    assert len(GridLines.get_winning_positions(windata)) == 7
    assert gamestate.board[2][2].explode is True
    assert gamestate.board[0][0].explode is False


def test_collapse_without_refill(gamestate):
    "Winners are removed, a wild is left in the centre and the rest fall. Nothing drops in."
    set_board(
        gamestate,
        [
            "L1 X X X X",
            "H1 X X X X",
            "L1 L1 L1 X X",
            "H1 H1 X X X",
            "H1 X X X X",
        ],
    )
    windata = GridLines.get_gridline_wins(gamestate.config, gamestate.board)
    assert windata["totalWin"] == gamestate.config.paytable[(3, "L1")]
    centres = GridLines.get_centre_positions(windata)
    assert centres == [{"reel": 1, "row": 2}]

    gamestate.collapse_board([{**pos, "name": "W"} for pos in centres])
    assert board_rows(gamestate) == [
        "X X X X X",
        "L1 X X X X",
        "H1 X X X X",
        "H1 W X X X",
        "H1 H1 X X X",
    ]
    assert gamestate.exploded_positions == [{"reel": 0, "row": 2}, {"reel": 1, "row": 2}, {"reel": 2, "row": 2}]
    assert gamestate.spawned_symbols == [{"reel": 1, "row": 2, "name": "W", "landingRow": 3}]
    assert gamestate.count_symbols_left() == 6

    # The three H1 symbols in reel 1 are now stacked after the fall: the next step pays.
    windata = GridLines.get_gridline_wins(gamestate.config, gamestate.board, global_multiplier=2)
    assert windata["totalWin"] == gamestate.config.paytable[(3, "H1")] * 2


def test_collapse_can_empty_the_board(gamestate):
    "With no spawned symbols a single row of winners leaves an empty board."
    set_board(
        gamestate,
        [
            "X X X X X",
            "X X X X X",
            "X X X X X",
            "X X X X X",
            "H1 H1 H1 H1 H1",
        ],
    )
    GridLines.get_gridline_wins(gamestate.config, gamestate.board)
    gamestate.collapse_board()
    assert gamestate.count_symbols_left() == 0
