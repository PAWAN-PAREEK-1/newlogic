# Grid Line Pays - Frontend Guide

How to read a game response and draw it. The game rules and the paytable are at the end.

For a short page per bet mode (what it does, its events in order), see [docs/](docs/README.md).

## 1. One response = one round

Every bet returns one "book": the complete round, from the first board to the final win.
The frontend plays the `events` list in order. Nothing is decided on the frontend.

```json
{
  "id": 2,
  "payoutMultiplier": 50,
  "events": [ ... ],
  "criteria": "basegame",
  "baseGameWins": 0.5,
  "freeGameWins": 0.0
}
```

| Field | Meaning |
|---|---|
| `id` | Number of the round |
| `payoutMultiplier` | Total win of the round, in hundredths of the bet (`50` = 0.5x the bet) |
| `events` | What happened, in the order to show it |
| `criteria` | Internal label of the round. Do not show it |
| `baseGameWins`, `freeGameWins` | Win of the paid spin and of the bonus, in bet multiples (`0.5` = 0.5x) |

## 2. Conventions

- **Amounts in events are hundredths of the bet.** `"amount": 250` means 2.5x the bet. Divide by 100. This is always the base bet, also in a mode that costs more (a Wild Spin costs 5x, `250` is still 2.5x the base bet).
- **`index`** counts the events from 0. Play them in this order.
- **The board is 5 reels by 5 rows.** `board[reel][row]`, reel 0 is the left column, row 0 is the top.
- **Positions in events use `row` 1 to 5.** `row` 1 is the top row. To get the board index, use `row - 1`. `reel` is 0 to 4.
- **Symbols:** `H1`-`H4` (high), `L1`-`L5` (low), `W` (wild, has `"wild": true`), `S` (scatter, has `"scatter": true`). An empty cell after a collapse has no symbol; it is never sent in a `reveal`.

## 3. Events

Standard Stake Engine events (`freeSpinTrigger` has one extra field, `bonusType`):

| `type` | Fields | What to do |
|---|---|---|
| `reveal` | `board`, `paddingPositions`, `gameType`, `anticipation` | Show a new 5x5 board. `gameType` is `basegame` or `freegame`. Ignore `paddingPositions`. `anticipation` is one number per reel: above 0 means slow that reel down (scatters are close to a trigger) |
| `winInfo` | `totalWin`, `wins[]` | Highlight the winning runs of the current board (see below) |
| `updateTumbleWin` | `amount` | Win of this spin so far |
| `setWin` | `amount`, `winLevel` | Final win of this spin. `winLevel` 1-10 picks the size of the win animation |
| `setTotalWin` | `amount` | Win of the whole round so far |
| `updateGlobalMult` | `globalMult` | Paid spin only: the spin multiplier changed. Sent only when the value changes |
| `freeSpinTrigger` | `totalFs`, `positions`, `bonusType` | A bonus starts. `positions` are the scatters, `bonusType` is `refine`, `surge` or `fusion`, `totalFs` is the number of free spins |
| `updateFreeSpin` | `amount`, `total` | A free spin starts. `amount` counts from 0, so show `amount + 1` of `total` |
| `freeSpinEnd` | `amount`, `winLevel` | The bonus is over. `amount` is its total win |
| `wincap` | `amount` | The max win was reached. The round stops here |
| `finalWin` | `amount` | Last event. Equal to `payoutMultiplier` |

Events only this game has:

| `type` | Fields | What to do |
|---|---|---|
| `collapseBoard` | `explodingSymbols`, `newWilds` | Remove the winning symbols and let the rest fall (see section 5) |
| `wildDrop` | `positions` | Turn the symbols at these positions into wilds. Comes right after a `reveal` |
| `updateLineMult` | `rows`, `columns` | Bonus only: the multiplier of each row and each column (5 numbers each) |
| `refineSymbol` | `level`, `removed`, `into`, `removedSymbols` | Bonus with upgrades: from the next spin on, symbol `removed` lands as `into` |
| `primeSymbols` | `level`, `removedSymbols`, `landAs` | Prime Spin only, before the `reveal`: these symbols are removed for this spin and land as `landAs` |

### One win inside `winInfo`

```json
{
  "symbol": "H2",
  "kind": 3,
  "win": 50,
  "positions": [{"reel": 4, "row": 2}, {"reel": 4, "row": 3}, {"reel": 4, "row": 4}],
  "meta": {
    "lineIndex": 4,
    "multiplier": 1,
    "winWithoutMult": 50,
    "globalMult": 1,
    "lineMultiplier": 1,
    "direction": "column",
    "overlay": {"reel": 4, "row": 3}
  }
}
```

| Field | Meaning |
|---|---|
| `symbol`, `kind` | The symbol that won and the length of the run (3, 4 or 5) |
| `win` | Win of this run, multiplier included |
| `positions` | The cells of the run |
| `meta.direction` | `row` or `column` |
| `meta.lineIndex` | Which row (0-4, top first) or which reel (0-4) the run is in. Use it as the index into `rows` / `columns` of `updateLineMult` |
| `meta.winWithoutMult` | Paytable value of the run |
| `meta.multiplier` | What the run was multiplied by. Always `globalMult x lineMultiplier` |
| `meta.globalMult` | Spin multiplier (paid spin). Always 1 in a bonus |
| `meta.lineMultiplier` | Multiplier of the run's row or column (bonus). Always 1 in a paid spin |
| `meta.overlay` | The centre cell of the run, where the new wild appears |

## 4. Order of events

A paid spin (base, Wild Spin, Prime Spin):

```
primeSymbols                      Prime Spin only
reveal                            the 25 symbols
wildDrop                          Wild Spin only
  winInfo                         \
  updateTumbleWin                  |  repeated while the board
  collapseBoard                    |  still has winning runs
  updateGlobalMult                /
setWin                            only if the spin won
setTotalWin
freeSpinTrigger ...               only if 3 or more scatters landed (bonus, see below)
finalWin
```

A bonus, between `freeSpinTrigger` and `finalWin`:

```
freeSpinTrigger                   bonusType and number of free spins
updateGlobalMult                  only if the spin multiplier was above 1: it goes back to 1
updateLineMult                    all ten line multipliers at 1: show the meters
  updateFreeSpin                  \
  reveal                           |
  wildDrop                         |  Surge and Fusion
    winInfo                        |
    updateTumbleWin                |  one block per free spin
    collapseBoard                  |
    updateLineMult                 |  only when a value changed
  setWin                           |  only if the spin won
  setTotalWin                      |
  refineSymbol                    /   Refine and Fusion, after a winning spin
freeSpinEnd
finalWin
```

After `wincap` no more boards are played. The events that follow it only close the round (`setTotalWin`, `freeSpinEnd`, `finalWin`).

## 5. How to draw a collapse

`collapseBoard` does not send the new board. Build it from the board you are showing:

1. Remove every cell listed in `explodingSymbols`.
2. Put a wild in every `newWilds` cell (`reel`, `row`).
3. In each reel, let the remaining symbols fall to the bottom, keeping their order. Empty cells stay at the top. Nothing new drops in.

`newWilds[].landingRow` is the row each new wild ends on after the fall, so you can animate it directly.

## 6. Example: one base spin that pays 0.5x

```
        reel0  reel1  reel2  reel3  reel4
row 1    H4     H4     L3     L2     L5
row 2    W      L1     H4     L2     W   \
row 3    L4     H1     H3     L5     H2   |  W + H2 + H2 = 3 of H2 in reel 4
row 4    H4     L4     H2     L2     H2  /
row 5    L2     H3     L5     H1     H3
```

```json
{"index": 0, "type": "reveal", "board": [[...5 symbols...], ...5 reels...], "paddingPositions": [16, 40, 151, 10, 77], "gameType": "basegame", "anticipation": [0, 0, 0, 0, 0]}
{"index": 1, "type": "winInfo", "totalWin": 50, "wins": [ ...the win shown in section 3... ]}
{"index": 2, "type": "updateTumbleWin", "amount": 50}
{"index": 3, "type": "collapseBoard", "explodingSymbols": [{"reel": 4, "row": 2}, {"reel": 4, "row": 3}, {"reel": 4, "row": 4}], "newWilds": [{"reel": 4, "row": 3, "landingRow": 4}]}
{"index": 4, "type": "updateGlobalMult", "globalMult": 2}
{"index": 5, "type": "setWin", "amount": 50, "winLevel": 2}
{"index": 6, "type": "setTotalWin", "amount": 50}
{"index": 7, "type": "finalWin", "amount": 50}
```

After the collapse reel 4 is `empty, empty, L5, W, H3`. No run is left, so the spin ends with 0.5x.

## 7. Win levels

`setWin.winLevel` is set from the win of the spin, `freeSpinEnd.winLevel` from the win of the bonus (both in bet multiples).

| Level | `setWin` | `freeSpinEnd` |
|---|---|---|
| 1 | below 0.1x | below 1x |
| 2 | 0.1x to 1x | 1x to 5x |
| 3 | 1x to 2x | 5x to 10x |
| 4 | 2x to 5x | 10x to 20x |
| 5 | 5x to 15x | 20x to 50x |
| 6 | 15x to 30x | 50x to 100x |
| 7 | 30x to 50x | 100x to 500x |
| 8 | 50x to 100x | 500x to 2,000x |
| 9 | 100x to max win | 2,000x to max win |
| 10 | max win | max win |

---

# Game rules

## The grid and the win

- 5 reels, 5 rows. There are no paylines.
- A win is a run of 3, 4 or 5 matching symbols side by side in one row or one column.
- A run can be anywhere. It does not have to start on the first reel.
- Diagonals never win.
- A symbol can be in a row run and a column run at the same time. Both pay.
- Scatters and empty cells break a run.

## Wild (W)

- A wild continues the run of the symbol next to it, on either side.
- One wild can complete two runs in the same line: `H1 H1 W L1 L1` pays H1 and L1.
- A run made only of wilds pays like H1, unless those wilds are already part of a longer run of another symbol in that line.

## Collapse

After the wins on a board are paid:

1. every symbol in a winning run is removed;
2. a wild appears in the centre of each run (the second cell of a run of 4);
3. the remaining symbols and the new wilds fall straight down;
4. nothing new drops in.

The board is checked again, and this repeats until no run is left.

## Multiplier in a paid spin

- Every spin starts at 1x.
- Every winning run moves the multiplier one step up. The new value counts from the next collapse.
- Steps: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 14, 20, 28, 40, 55, 75, 100, 150, 200, 300, 400, 500, 750, 1000.
- The multiplier goes back to 1x on the next spin.

## Bet modes

| Mode | Name in the request | Cost | What the player gets |
|---|---|---|---|
| Base | `base` | 1x | The normal spin |
| Wild Spin | `wildspin` | 5x | 1 to 5 extra wilds are dropped on the board on every spin |
| Prime Spin | `primespin` | 20x | 2 to 5 of the lowest symbols are removed for the spin; they land as the next better symbol |
| Refine | `refine` | 100x | Buys the Refine bonus |
| Surge | `surge` | 200x | Buys the Surge bonus |
| Mystery | `mystery` | 300x | A spin with a random result: no bonus (2%, a small spin win), Refine (about 14%), Surge (about 83.6%) or Fusion (about 0.3%) |

RTP is 96.01% in every mode. The max win is 25,000x the bet in every mode.

## Bonus games

3, 4 or 5 scatters on a paid spin start a bonus. The number of scatters decides which one. A bonus has no scatters, so it cannot retrigger.

| Scatters | Bonus | Free spins | Its own feature |
|---|---|---|---|
| 3 | Refine | 8 | Symbol upgrades |
| 4 | Surge | 12 | 3 wilds dropped on every spin |
| 5 | Fusion | 15 | Symbol upgrades and 3 wilds dropped on every spin |

Fusion cannot be bought directly. It comes from 5 scatters or from the Mystery buy.

**Line multipliers (every bonus).**

- Each of the 5 rows and each of the 5 columns has its own multiplier. All ten start at 1x.
- A run pays its paytable value times the multiplier of the row or column it is in.
- Every winning run moves the multiplier of its own row or column one step up. The new value counts from the next collapse.
- Line multipliers are never reset during the bonus.
- The multiplier grows slowly at first and fast once the same line has won many times. The highest value is 5000x.
- The spin multiplier of the paid spins is not used in a bonus.

**Symbol upgrades (Refine and Fusion).** After every winning free spin the lowest symbol still in play is upgraded for the rest of the bonus: L5 lands as L4, then L4 as L3, L3 as L2, L2 as L1, L1 as H4, H4 as H3, H3 as H2 and H2 as H1.

**Wild drop (Surge and Fusion).** On every free spin 3 symbols on the board are turned into wilds before the wins are counted.

**Surge never ends close to zero.** With 3 wilds on each of its 12 free spins, almost every spin wins something, so the small wins always add up. In the current books the lowest Surge bonus pays 5.7x the bet. This is not a fixed rule: it is the lowest result in the simulated rounds, and the number can change when the books are generated again. Fusion has the same wild drop and pays far more (its lowest round in the current books is about 800x). Refine has no wild drop, so a Refine bonus can end as low as 0.1x.

## Paytable

Pays are in multiples of the bet, for a run of 3, 4 or 5.

| Symbol | 3 | 4 | 5 |
|---|---|---|---|
| W (wild) | 0.8 | 2 | 6 |
| H1 | 0.8 | 2 | 6 |
| H2 | 0.5 | 1.5 | 4 |
| H3 | 0.4 | 1 | 3 |
| H4 | 0.3 | 0.8 | 2 |
| L1 | 0.2 | 0.4 | 1 |
| L2 | 0.1 | 0.3 | 0.8 |
| L3 | 0.1 | 0.3 | 0.8 |
| L4 | 0.1 | 0.2 | 0.6 |
| L5 | 0.1 | 0.2 | 0.6 |

The scatter (S) does not pay. It only triggers the bonus games.
