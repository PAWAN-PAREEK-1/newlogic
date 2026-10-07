# newlogic - Grid Line Pays

A Stake Engine maths project with a win logic that is not in the SDK samples: **grid lines**.
A win is a straight run of 3, 4 or 5 like symbols in any row or column of a 5x5 grid.
There are no paylines, no "from the first reel" rule and no clusters.

The game is `games/0_0_gridlines`. Its full rules, events and tuning notes are in
[`games/0_0_gridlines/readme.txt`](games/0_0_gridlines/readme.txt).

| | |
|---|---|
| Grid | 5 reels x 5 rows |
| Win logic | runs of 3+ in rows and columns, wilds join runs |
| After a win | winners are removed, a wild is left in the centre of each run, symbols fall, **nothing refills** |
| Multiplier | a ladder: every winning run is one step up. x1 to x10 in steps of 1, then x14, x20, x28, x40 ... x1000 |
| RTP | 93.30% in every mode |
| Max win | 10,000x |
| Volatility | high in every mode: most rounds pay 0.1x to 2x of what they cost, a few pay many times the cost |
| State | stateless - one bet is one complete round. No jackpot, no gamble, no player choice in a round |

## The six bet modes

| Mode | Cost | What is different |
|---|---|---|
| `base` | 1x | The base game. |
| `wildspin` | 5x | 1 to 5 extra wilds (random) are dropped onto the grid on every spin. |
| `primespin` | 20x | 2 to 5 of the lowest symbols (random) are removed for the spin, so runs are longer and the ladder climbs faster. |
| `refine` | 100x | Bonus buy. 5 spins. Every winning spin upgrades the lowest symbol left for the rest of the bonus, and the next spins start one step higher on the ladder. |
| `surge` | 150x | Bonus buy. 4 spins with a wild dropped on each. The ladder never resets during the bonus. |
| `survival` | 200x | Bonus buy. No spin counter: 3 lives. Wilds stay on the grid between spins and the multiplier is kept while spins keep winning. A dead spin costs a life and resets the multiplier. |

The three bonus games can also be triggered by 3 or more scatters in `base`, `wildspin` and
`primespin`. All three use the same win logic; they differ in what builds up during the
bonus - the symbols (Refine), the ladder (Surge) or the wilds and the streak (Survival).

## Results

100,000 simulated rounds per mode. Values are read from the published lookup tables.
Payout bands are in multiples of the cost of the mode.

| Mode | Cost | RTP | Pays 0 | Below 0.1x | 0.1x - 2x | Above 2x | Above 10x | Median | Volatility |
|---|---|---|---|---|---|---|---|---|---|
| `base` | 1x | 93.30% | 63.1% | - | 31.9% | 5.0% | 1.50% | 0 | 25.8 |
| `wildspin` | 5x | 93.30% | 17.6% | 13.2% | 64.0% | 5.1% | 0.94% | 0.24x | 10.5 |
| `primespin` | 20x | 93.30% | 1.5% | 18.0% | 74.9% | 5.7% | 0.68% | 0.45x | 5.0 |
| `refine` | 100x | 93.30% | - | 21.9% | 68.8% | 9.3% | 1.52% | 0.28x | 2.5 |
| `surge` | 150x | 93.30% | - | 23.9% | 70.0% | 6.1% | 1.62% | 0.25x | 3.3 |
| `survival` | 200x | 93.30% | - | 24.0% | 70.0% | 6.0% | 1.64% | 0.25x | 3.3 |

Volatility is the standard deviation of the payout divided by the cost of the mode. In the
base game 87% of the winning spins pay between 0.1x and 2x.

The max win lands 1 in 3,333,333 spins in `base`, 1 in 666,667 in `wildspin`, 1 in 166,667
in `primespin`, 1 in 5,000 Refine buys, 1 in 4,444 Surge buys and 1 in 2,500 Survival buys.
A bonus game triggers 1 in 592 spins in `base`, 1 in 141 in `wildspin` and 1 in 39 in
`primespin`.

Checks on this configuration:

* RGS format checks (`utils/rgs_verification`) passed for all six modes.
* All 600,000 books were replayed from their events by `verify_books.py`; every win,
  collapse, ladder step and payout matches the rules and the lookup table.
* `pytest tests/`: 46 passed.

## Quick start

Python 3.12 or newer.

```sh
make setup                          # virtual environment + packages
source env/bin/activate

make run GAME=0_0_gridlines         # simulate, configs, weights, PAR sheet, RGS checks
make verify GAME=0_0_gridlines      # replay every book against the rules
make test                           # unit tests
```

`make run` simulates 100,000 rounds per mode (about 30 minutes on 2 cores). For a quick
look use `python -m games.0_0_gridlines.run --sims 5000`.

The files to upload to Stake Engine are written to
`games/0_0_gridlines/library/publish_files/`. `library/` is generated output and is not
committed.

## What is in the repository

The repository is the Stake Engine math-sdk as used in `lines5-3` (same folder structure,
same `src/` engine, same optimizer and tools), plus:

| Path | What it is |
|---|---|
| `src/calculations/gridlines.py` | **New win logic.** Finds and prices runs in rows and columns. |
| `src/calculations/collapse.py` | **New board mechanic.** Removes winners, places centre wilds, drops the rest, no refill. |
| `games/0_0_gridlines/` | The game: config, game state, events, reels, optimizer targets, pipeline. |
| `games/0_0_gridlines/verify_books.py` | Replays every published book from its events with its own copy of the rules, and compares every win and the payout with the lookup table. |
| `optimization_program/natural_weights.py` | Lookup-table weights that keep the simulated win distribution inside every criteria and move it only as far as needed to reach the targets. Used by default. |
| `utils/criteria_stats.py` | Prints what the simulation produced for each mode and criteria, and per payout band. |
| `tests/win_calculations/test_gridlinespay.py` | Tests of the win logic. |
| `tests/games/test_gridlines_rounds.py` | Plays rounds of every mode and replays them. |

The sample games of the SDK are not copied; `games/` holds only the new game.

### Notes

* **Where the volatility is set.** Two places. The multiplier ladder in `game_config.py`
  decides how much a long chain is worth. The payout bands in `game_optimization.py`
  (`BUY_BANDS`, `SPIN_BANDS`) decide what share of rounds pays in each range of the cost.
  `readme.txt` explains how to change both.
* **Optimizer.** `--optimizer rust` runs the SDK's Rust optimizer on the same conditions
  instead of the natural weights. It draws its own distribution shape inside each criteria.
  It has not been re-run since the payout bands were added.
* **Go engine.** `go_engine/` comes from `lines5-3`. Its simulator supports the lines game
  only; this game is simulated with the Python engine. `--optimizer go` (the Go port of the
  Rust optimizer) is wired in but has not been run for this game.
