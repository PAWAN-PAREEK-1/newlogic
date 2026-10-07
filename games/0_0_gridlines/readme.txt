# Grid Line Pays

A 5x5 collapse game built on a win logic the SDK samples do not have: straight runs of like
symbols in any row or column.

* 5 reels, 5 rows, no paylines
* 9 paying symbols (H1-H4, L1-L5)
* 1 Wild (W), 1 Scatter (S)
* 6 bet modes: base game, 2 feature spins, 3 bonus buys
* RTP 93.30% in every mode, max win 10,000x
* Stateless: every bet is one complete round, nothing is carried to the next bet. No
  jackpots, no gamble, no player choice during a round.


## Win logic: grid lines

A win is a run of 3, 4 or 5 like symbols next to each other in ONE row or ONE column.

* The run can sit anywhere on the grid. It does not have to start on the first reel.
* Diagonals never count.
* A symbol can be part of a row run and a column run at the same time; both pay.
* The pay depends on the symbol and the length of the run (see the paytable in
  game_config.py). There is nothing to bet per line: all 5 rows and 5 columns are always live.

Wilds
* A wild continues the run of the symbol on either side of it.
* One wild can complete two runs in the same row or column (H1 H1 W L1 L1 pays H1 and L1).
* A run made only of wilds pays like H1, unless those wilds are already part of a longer
  run of a regular symbol in that row or column.

Scatters and empty positions break a run.

How it differs from the other SDK win types
    lines     fixed paylines, read from reel 1
    ways      like symbols on consecutive reels from reel 1, any row
    scatter   symbol count anywhere, position does not matter
    cluster   any connected group, shape does not matter, pays on group size
    gridlines straight runs in rows and columns, pays on run length

The calculator is src/calculations/gridlines.py. Tests: tests/win_calculations/test_gridlinespay.py.


## Collapse (no refill)

After the wins on the board are paid:

1. every symbol in a winning run is removed;
2. a wild appears in the centre position of each run (the second position of a run of 4);
3. the remaining symbols and the new wilds fall straight down;
4. NOTHING new drops in from the top.

The board is evaluated again and the steps repeat until no run is left. Because nothing is
refilled the board only gets emptier, so a spin always ends (at most 12 collapses).

This is src/calculations/collapse.py, the counterpart of the SDK's tumble.py (which refills).

Multiplier
* Every spin starts at 1x.
* Every winning run adds +1. The new value applies from the next collapse.
  Example: two runs on the first board pay at 1x, the board after the collapse pays at 3x.
* The base game and the feature spins reset to 1x on every spin. The bonus games change this
  rule, each in its own way (below).


## Bet modes

    mode       cost   what the player gets
    base       1x     the base game
    wildspin   5x     2 or 3 extra wilds are dropped onto the grid on every spin
    primespin  20x    the three lowest symbols (L5, L4, L3) are gone: they all land as L2
    refine     100x   buys the Refine bonus
    surge      150x   buys the Surge bonus
    survival   300x   buys the Survival bonus

Three or more scatters on the first drop of a paid spin (base, wildspin, primespin) trigger
one of the three bonus games. Which one is decided by the maths at that moment, never by the
player. 4 or 5 scatters award a longer bonus. Scatters appear in paid spins only, so a bonus
cannot retrigger.

All three bonus games use the same win logic and collapse. They differ in what builds up.

### Refine - the symbols build up (lowest risk)
* 6 free spins (8 / 10 with 4 / 5 scatters).
* After every winning spin the lowest symbol still in play is upgraded for the rest of the
  bonus: L5 lands as L4, then L4 as L3 ... up to H2 landing as H1. Eight upgrades are possible.
* Every upgrade also raises the multiplier the following spins START on by +1.
* The multiplier still resets at the start of each spin (to 1 + upgrades).
* Fewer symbol types means more and longer runs on every drop, so the bonus pays steadily.
  Its ceiling is lower than the other two: max win of the "refine" buy is 2,500x.

### Surge - the multiplier builds up (medium risk)
* 8 free spins (10 / 12).
* 1 or 2 wilds are dropped onto the grid on every spin.
* The multiplier NEVER resets during the bonus.
* A full line (a run of 5) doubles the multiplier, on top of its +1.

### Survival - the wilds and the streak build up (highest risk)
* No spin counter. 3 lives (4 / 5).
* The bonus starts with 2 wilds on the grid.
* Wilds still on the grid when a spin ends stay in place for the next spin.
* The multiplier is kept for as long as spins keep winning.
* A spin without a win costs one life and resets the multiplier to 1x.
* The bonus ends when no life is left (hard stop after 60 spins).

Every bonus pays at least 0.1x: rounds that would pay nothing are not part of the game.


## Events

Standard SDK events, unchanged:
    reveal, winInfo, updateTumbleWin, setWin, setTotalWin, updateGlobalMult,
    updateFreeSpin, freeSpinEnd, wincap, finalWin

Game events (game_events.py):
    wildDrop        {positions}                         wilds dropped after a reveal
    collapseBoard   {explodingSymbols, newWilds}        one collapse step
    freeSpinTrigger {bonusType, totalFs, lives, positions}
    refineSymbol    {level, removed, into, removedSymbols}
    stickyWilds     {positions}                         survival: wilds on the grid before a reveal
    updateLives     {lives, spin, lostLife}             survival: before each spin and when a life is lost

Positions are {"reel": 0-4, "row": 0-4} with row 0 at the top. The game has no padding rows
(include_padding = False), so no event offsets its rows.

Order of events in one spin:

    reveal                              the 25 symbols
    wildDrop                            (wildspin, surge)
    winInfo, updateTumbleWin            runs on the current board      } repeated while
    collapseBoard, updateGlobalMult     remove, centre wilds, fall     } the board has runs
    setWin                              (only if the spin won)
    setTotalWin

collapseBoard does not repeat the whole board. To draw the board after a collapse: remove
explodingSymbols, put a wild on every newWilds position, then let each reel's symbols fall
to the bottom in order. winInfo "meta" gives direction ("row" / "column"), lineIndex, the
multiplier applied (globalMult) and the centre of the run (overlay).

verify_books.py replays books from exactly these events, and is a working example of how
to read them.


## Files

    game_config.py        rules, paytable, bet modes and simulation conditions
    gamestate.py          one round: paid spin, then the bonus game it triggers
    game_executables.py   board draws, win evaluation, collapse sequence, bonus entry
    game_calculations.py  symbol upgrades and wild positions
    game_events.py        game events
    game_override.py      resets, symbol creation, round acceptance rules
    game_optimization.py  criteria targets (hit rates, average wins) and risk limits
    run.py                the whole pipeline
    build_reels.py        builds reels/*.csv from symbol counts
    verify_books.py       independent replay of every published book
    reels/                BR0 (paid spins), FRR / FRS / FRV (refine / surge / survival),
                          WCAP (max-win rounds only)


## Running

From the repository root, after `make setup`:

    python -m games.0_0_gridlines.run                 # simulate, configs, weights, analysis, checks
    python -m games.0_0_gridlines.run --sims 20000    # quicker run
    python -m games.0_0_gridlines.verify_books        # replay every book against the rules
    python -m utils.criteria_stats 0_0_gridlines      # what the simulation produced, per criteria

Upload the contents of library/publish_files to Stake Engine.

Lookup-table weights. run.py uses `--optimizer natural` by default
(optimization_program/natural_weights.py): the published probabilities are the simulated
distribution, tilted only as far as needed to give every criteria its probability and
average win from game_optimization.py. Wins then come as often as the mechanics produce
them. `--optimizer rust` or `--optimizer go` runs the SDK optimizer instead; it hits the
same RTP and criteria targets but draws its own shape inside each criteria, so tune
"scaling" and "parameters" in game_optimization.py if you use it.

The risk limits in game_optimization.py ("targets") are checked after either optimizer by
optimization_program/mode_targets.py.


## Tuning

* Symbol counts on the strips: edit STRIPS in build_reels.py, run it, simulate again.
* Rules: the "Collapse rules" and "Bonus games" blocks in game_config.py
  (spins and lives, wild drops, upgrade ladder, starting wilds).
* After any change: simulate, run `python -m utils.criteria_stats 0_0_gridlines`, and move
  the hit rates and average wins in game_optimization.py to the new simulated values. The
  base game average win is computed, so each mode always adds up to its RTP.
* A different RTP: change self.rtp in game_config.py. Nothing else needs editing.


## Results of the committed configuration

100,000 simulated rounds per mode, natural weights. Values are read from the published
lookup tables (library/publish_files/lookUpTable_<mode>_0.csv).

    mode       cost   RTP      any win    win > cost   max win            volatility
    base       1x     93.30%   1 in 2.70  1 in 12.31   1 in 3,333,333     17.18
    wildspin   5x     93.30%   1 in 1.21  1 in 5.22    1 in 666,667       5.58
    primespin  20x    93.30%   1 in 1.01  1 in 2.85    1 in 166,667       2.15
    refine     100x   93.30%   always     1 in 2.78    1 in 12,500        1.05
    surge      150x   93.30%   always     1 in 3.08    1 in 16,667        1.09
    survival   300x   93.30%   always     1 in 5.40    1 in 1,075         2.60

Volatility is the standard deviation of the payout divided by the cost of the mode. The max
win is 10,000x the base bet (2,500x in the refine buy).

Bonus games from paid spins (1 in N spins) and their average payout in base bets:

    mode       refine   surge     survival   any bonus
    base       550      1,500     5,500      375
    wildspin   240      650       2,400      163
    primespin  150      420       1,500      103
    avg pay    130x     141-147x  262-279x

The averages exclude rounds that reach the max win. The buys always give the 3-scatter
bonus and average 93x (Refine), 140x (Surge) and 280x (Survival) with max-win rounds
included. Refine pays more from a paid spin because 4 and 5 scatters award longer bonuses.

Where the RTP of the base mode comes from: spins without a bonus 54.9%, Refine 23.6%,
Surge 9.4%, Survival 5.1%, max-win rounds 0.3%.

Checks run on this configuration:
* utils/rgs_verification (format checks): passed for all six modes.
* verify_books.py: all 600,000 books replayed from their events; every win, collapse,
  multiplier step, wild drop, upgrade, life and payout matches the rules and the lookup table.
* pytest tests/: 42 passed.
* Risk limits in game_optimization.py: met by every mode with no change to the weights.

Book sizes (100,000 rounds, compressed): base 39 MB, wildspin 47 MB, primespin 58 MB,
refine 143 MB, surge 192 MB, survival 249 MB. Fewer simulations give smaller files.
