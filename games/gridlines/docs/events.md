# Every event in one line

Numbers are the bet times 100 (`50` = 0.5x the bet).

## In every mode

| Event | What to show |
|---|---|
| `reveal` | A new board of 25 symbols. If a number in `anticipation` is above 0, slow that reel down (a bonus is close) |
| `winInfo` | Highlight the winning symbols. `wins` lists each win: symbol, cells, amount |
| `updateTumbleWin` | Win of this spin so far |
| `collapseBoard` | Remove the winning symbols, add the new wilds, let everything fall |
| `setWin` | The spin is over and it won `amount`. `winLevel` 1 to 10 picks the win animation |
| `setTotalWin` | Win of the whole round so far |
| `finalWin` | Always the last event. The round is over; the player gets `amount` |
| `wincap` | The max win (25,000x the bet) was reached. The round stops |

## In a normal spin

| Event | What to show |
|---|---|
| `updateGlobalMult` | The spin multiplier changed. Show `globalMult` |
| `wildDrop` | Turn the cells in `positions` into wilds (Wild Spin, and the Surge and Fusion bonus) |
| `primeSymbols` | Prime Spin only: these symbols are removed for this spin |

## In a bonus

| Event | What to show |
|---|---|
| `freeSpinTrigger` | A bonus starts. `bonusType` is `refine`, `surge` or `fusion`. `totalFs` is the number of free spins. `positions` are the scatters |
| `updateLineMult` | The ten multipliers: `rows` (top row first) and `columns` (left column first) |
| `updateFreeSpin` | A free spin starts. `amount` counts from 0, so show `amount + 1` of `total` |
| `refineSymbol` | Symbol `removed` is gone. From now on it lands as `into` |
| `freeSpinEnd` | The bonus is over. `amount` is the win of the bonus |

## How to draw `collapseBoard`

1. Remove the cells listed in `explodingSymbols`.
2. Put a wild in each cell listed in `newWilds`.
3. In every column, let the symbols fall to the bottom. Empty cells stay at the top.

No new symbols come in. The server does not send the board after the fall; the frontend builds it with these 3 steps.
