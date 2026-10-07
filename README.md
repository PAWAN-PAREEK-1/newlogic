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
| Multiplier | +1 for every winning run, used from the next collapse |
| RTP | 93.30% in every mode |
| Max win | 10,000x (2,500x in the Refine buy) |
| State | stateless - one bet is one complete round. No jackpot, no gamble, no player choice in a round |

## The six bet modes

| Mode | Cost | What is different |
|---|---|---|
| `base` | 1x | The base game. |
| `wildspin` | 5x | 2 or 3 extra wilds are dropped onto the grid on every spin. |
| `primespin` | 20x | The three lowest symbols are removed: L5, L4 and L3 all land as L2. |
| `refine` | 100x | Bonus buy. 6 spins. Every winning spin upgrades the lowest symbol left for the rest of the bonus, and raises the multiplier the next spins start on. Steady pays. |
| `surge` | 150x | Bonus buy. 8 spins with 1-2 wilds dropped on each. The multiplier never resets, and a full line of 5 doubles it. |
| `survival` | 300x | Bonus buy. No spin counter: 3 lives. Wilds stay on the grid between spins and the multiplier is kept while spins keep winning. A dead spin costs a life and resets the multiplier. |

The three bonus games can also be triggered by 3 or more scatters in `base`, `wildspin` and
`primespin`. All three use the same win logic; they differ in what builds up during the
bonus - the symbols (Refine), the multiplier (Surge) or the wilds and the streak (Survival).

## Results

100,000 simulated rounds per mode. Values are read from the published lookup tables.

| Mode | Cost | RTP | Any win | Win above cost | Max win | Volatility |
|---|---|---|---|---|---|---|
| `base` | 1x | 93.30% | 1 in 2.70 | 1 in 12.31 | 1 in 3,333,333 | 17.18 |
| `wildspin` | 5x | 93.30% | 1 in 1.21 | 1 in 5.22 | 1 in 666,667 | 5.58 |
| `primespin` | 20x | 93.30% | 1 in 1.01 | 1 in 2.85 | 1 in 166,667 | 2.15 |
| `refine` | 100x | 93.30% | always | 1 in 2.78 | 1 in 12,500 | 1.05 |
| `surge` | 150x | 93.30% | always | 1 in 3.08 | 1 in 16,667 | 1.09 |
| `survival` | 300x | 93.30% | always | 1 in 5.40 | 1 in 1,075 | 2.60 |

Volatility is the standard deviation of the payout divided by the cost of the mode.

A bonus game triggers 1 in 375 spins in `base`, 1 in 163 in `wildspin` and 1 in 103 in
`primespin`.

Checks on this configuration:

* RGS format checks (`utils/rgs_verification`) passed for all six modes.
* All 600,000 books were replayed from their events by `verify_books.py`; every win,
  collapse, multiplier step and payout matches the rules and the lookup table.
* `pytest tests/`: 42 passed.

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
| `optimization_program/natural_weights.py` | Lookup-table weights that keep the simulated win distribution and move it only as far as needed to reach the RTP and criteria targets. Used by default. |
| `utils/criteria_stats.py` | Prints what the simulation produced for each mode and criteria. |
| `tests/win_calculations/test_gridlinespay.py` | Tests of the win logic. |
| `tests/games/test_gridlines_rounds.py` | Plays rounds of every mode and replays them. |

The sample games of the SDK are not copied; `games/` holds only the new game.

### Notes

* **Optimizer.** `--optimizer rust` runs the SDK's Rust optimizer instead of the natural
  weights. It reaches the same RTP, but it draws its own distribution shape inside each
  criteria, so the hit rates of small and large wins move away from what the mechanics
  produce. That is why the natural weights are the default.
* **Go engine.** `go_engine/` comes from `lines5-3`. Its simulator supports the lines game
  only; this game is simulated with the Python engine. `--optimizer go` (the Go port of the
  Rust optimizer) is wired in but has not been run for this game.
