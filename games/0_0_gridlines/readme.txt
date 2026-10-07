# Grid Line Pays

A 5x5 collapse game built on a win logic the SDK samples do not have: straight runs of like
symbols in any row or column.

* 5 reels, 5 rows, no paylines
* 9 paying symbols (H1-H4, L1-L5)
* 1 Wild (W), 1 Scatter (S)
* 6 bet modes: base game, 2 feature spins, 3 bonus buys
* RTP 93.30% in every mode, max win 10,000x
* High volatility in every mode: most rounds pay a fraction of what they cost, a few pay
  many times the cost
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

Multiplier ladder
* Every spin starts at 1x.
* Every winning run moves the multiplier one step up this ladder:

      x1 x2 x3 x4 x5 x6 x7 x8 x9 x10 x14 x20 x28 x40 x55 x75 x100 x150 x200 x300 x400 x500 x750 x1000

  The new value applies from the next collapse.
  Example: two runs on the first board pay at 1x, the board after the collapse pays at 3x.
* The first ten steps are +1 each. After that the ladder gets steep, so a long chain is
  worth far more than a short one. This is where the big wins come from.
* The base game and the feature spins go back to 1x on every spin. The bonus games change
  this rule, each in its own way (below).


## Bet modes

    mode       cost   what the player gets
    base       1x     the base game
    wildspin   5x     1 to 5 extra wilds are dropped onto the grid on every spin
    primespin  20x    2 to 5 of the lowest symbols are gone for the spin (see below)
    refine     100x   buys the Refine bonus
    surge      150x   buys the Surge bonus
    survival   200x   buys the Survival bonus

Wild spin: how many wilds drop is random on every spin - 1 (60%), 2 (25%), 3 (10%),
4 (3.5%) or 5 (1.5%).

Prime spin: how many symbols are removed is random on every spin - 2 (60%), 3 (28%),
4 (10%) or 5 (2%). Removed symbols land as the next symbol up: with 2 removed L5 and L4
land as L3, with 5 removed every low symbol lands as H4. Fewer symbol types means more
and longer runs, so the spin climbs the ladder faster.

Three or more scatters on the first drop of a paid spin (base, wildspin, primespin) trigger
one of the three bonus games. Which one is decided by the maths at that moment, never by the
player. 4 or 5 scatters award a longer bonus. Scatters appear in paid spins only, so a bonus
cannot retrigger.

All three bonus games use the same win logic and collapse. They differ in what builds up.

### Refine - the symbols build up
* 5 free spins (7 / 9 with 4 / 5 scatters).
* After every winning spin the lowest symbol still in play is upgraded for the rest of the
  bonus: L5 lands as L4, then L4 as L3 ... up to H2 landing as H1. Eight upgrades are possible.
* Every upgrade also moves the START of the following spins one step up the ladder.
* The multiplier still goes back to that start on every spin.
* A bonus that wins early snowballs; one that starts with dead spins stays small.

### Surge - the ladder never resets
* 4 free spins (6 / 8).
* 1 wild is dropped onto the grid on every spin.
* The multiplier NEVER goes back during the bonus. Every run on every spin is one more
  step, so the later spins are played on the steep part of the ladder.

### Survival - the wilds and the streak build up
* No spin counter. 3 lives (4 / 5).
* The bonus starts with 1 wild on the grid.
* Wilds still on the grid when a spin ends stay in place for the next spin.
* The multiplier is kept for as long as spins keep winning. Because a streak can run for
  many spins, Survival uses a plain ladder: +1 per winning run (x1, x2, x3, ...).
* A spin without a win costs one life and resets the multiplier to 1x.
* The bonus ends when no life is left (hard stop after 60 spins).

Every bonus pays at least 0.1x: rounds that would pay nothing are not part of the game.


## Events

Standard SDK events, unchanged:
    reveal, winInfo, updateTumbleWin, setWin, setTotalWin, updateGlobalMult,
    updateFreeSpin, freeSpinEnd, wincap, finalWin
updateGlobalMult is sent whenever the multiplier changes value.

Game events (game_events.py):
    primeSymbols    {level, removedSymbols, landAs}     prime spin: symbols removed, before the reveal
    wildDrop        {positions}                         wilds dropped after a reveal
    collapseBoard   {explodingSymbols, newWilds}        one collapse step
    freeSpinTrigger {bonusType, totalFs, lives, positions}
    refineSymbol    {level, removed, into, removedSymbols}
    stickyWilds     {positions}                         survival: wilds on the grid before a reveal
    updateLives     {lives, spin, lostLife}             survival: before each spin and when a life is lost

Positions are {"reel": 0-4, "row": 0-4} with row 0 at the top. The game has no padding rows
(include_padding = False), so no event offsets its rows.

Order of events in one spin:

    primeSymbols                        (primespin)
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
(optimization_program/natural_weights.py): inside every criteria the published
probabilities are the simulated distribution, tilted only as far as needed to reach the
criteria's average win from game_optimization.py. `--optimizer rust` or `--optimizer go`
runs the SDK optimizer on the same conditions instead; it draws its own shape inside each
criteria, so tune "scaling" and "parameters" in game_optimization.py if you use it.

How the payout distribution is set (game_optimization.py):
* Base game: one criteria per bonus game with its hit rate, plus the spins without a
  bonus. The shape inside each is what the game produces.
* Bonus buys: the payout range is cut into bands, in multiples of the cost of the buy
  (up to 0.1x, 0.25x, 0.5x, 1x, 2x, 5x, 10x, 25x, above). Every band has its share of
  rounds in BUY_BANDS. This is what makes a buy volatile: about half of the rounds pay
  less than a quarter of the cost, about 70% pay between 0.1x and 2x, the 2x-10x middle
  is kept thin, and about 1.6% of the rounds pay more than 10x the cost. Change the
  shares to make a buy calmer or wilder.
* Feature spins (wildspin, primespin): the bonus games have their hit rates like in the
  base game, and the spins without a bonus are cut into the same kind of bands
  (SPIN_BANDS). The bonus games are triggered more often than the reels alone would,
  which is where most of the volatility of these two modes comes from.

The risk limits in game_optimization.py ("targets") are checked after either optimizer by
optimization_program/mode_targets.py.


## Tuning

* Multiplier ladder: mult_ladder in game_config.py. It is the main volatility control of
  the game itself: a steeper ladder moves pay from short chains to long ones.
* Symbol counts on the strips: edit STRIPS in build_reels.py, run it, simulate again.
* Rules: the "Collapse rules" and "Bonus games" blocks in game_config.py (spins and lives,
  wild drops, upgrade ladder, starting wilds), and the wild-drop / prime-level weights
  further down.
* After any change: simulate, then run
      python -m utils.criteria_stats 0_0_gridlines --bands 0.1,0.25,0.5,1,2,5,10,25
  and move the hit rates, average wins and band averages in game_optimization.py to the
  new simulated values. One criteria per mode is computed ("basegame" for paid spins,
  "freegame" for buys), so each mode always adds up to its RTP.
* A different RTP: change self.rtp in game_config.py, then re-check the computed criteria.


## Results of the committed configuration

100,000 simulated rounds per mode, natural weights. Values are read from the published
lookup tables (library/publish_files/lookUpTable_<mode>_0.csv). Payout bands are in
multiples of the COST of the mode.

    mode       cost   RTP      pays 0   below 0.1x  0.1x - 2x  above 2x  above 10x  median   volatility
    base       1x     93.30%   63.1%     -          31.9%      5.0%      1.50%      0        25.8
    wildspin   5x     93.30%   17.6%    13.2%       64.0%      5.1%      0.94%      0.24x    10.5
    primespin  20x    93.30%    1.5%    18.0%       74.9%      5.7%      0.68%      0.45x     5.0
    refine     100x   93.30%    -       21.9%       68.8%      9.3%      1.52%      0.28x     2.5
    surge      150x   93.30%    -       23.9%       70.0%      6.1%      1.62%      0.25x     3.3
    survival   200x   93.30%    -       24.0%       70.0%      6.0%      1.64%      0.25x     3.3

Volatility is the standard deviation of the payout divided by the cost of the mode. In
the base game 87% of the winning spins pay between 0.1x and 2x.

    mode       win above cost   max win (10,000x)
    base       1 in 12.5        1 in 3,333,333
    wildspin   1 in 7.1         1 in 666,667
    primespin  1 in 5.0         1 in 166,667
    refine     1 in 4.7         1 in 5,000
    surge      1 in 5.5         1 in 4,444
    survival   1 in 5.5         1 in 2,500

Bonus games from paid spins (1 in N spins) and their average payout in base bets (rounds
that reach the max win not included):

    mode       refine   surge    survival   any bonus
    base       1,000    2,800    3,000      592
    wildspin   250      600      700        141
    primespin  80       160      150        39
    avg pay    169-173x 213-221x 211-219x

A triggered bonus pays more on average than a bought one because 4 and 5 scatters award
longer bonuses; the buys always give the 3-scatter bonus.

Where the RTP of the base mode comes from: spins without a bonus 60.9%, Refine 17.1%,
Surge 7.6%, Survival 7.3%, max-win rounds 0.3%.

Checks run on this configuration:
* utils/rgs_verification (format checks): passed for all six modes.
* verify_books.py: all 600,000 books replayed from their events; every win, collapse,
  ladder step, wild drop, upgrade, life and payout matches the rules and the lookup table.
* pytest tests/: 46 passed.
* Risk limits in game_optimization.py: met by every mode with no change to the weights.

Book sizes (100,000 rounds, compressed): base 32 MB, wildspin 38 MB, primespin 48 MB,
refine 116 MB, surge 89 MB, survival 214 MB. Fewer simulations give smaller files.
