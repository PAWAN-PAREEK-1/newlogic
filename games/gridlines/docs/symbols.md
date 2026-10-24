# Symbols and paytable

## How to win

3, 4 or 5 of the same symbol next to each other, in one row or in one column. Not diagonal.

```
H2  L1  L3  L5  H4
L4  H1  H1  H1  L2     <- 3 x H1 in a row: win
L3  L5  H3  L1  L4
L1  L2  L4  H4  L3
H4  L3  L2  L5  H3
```

The win can be anywhere in the row or column. It does not have to start at the left.

## What each symbol pays

In multiples of the bet.

| Symbol | What it is | 3 in a line | 4 in a line | 5 in a line |
|---|---|---|---|---|
| `H1` | Best symbol | 0.8 | 2 | 6 |
| `H2` | High symbol | 0.5 | 1.5 | 4 |
| `H3` | High symbol | 0.4 | 1 | 3 |
| `H4` | High symbol | 0.3 | 0.8 | 2 |
| `L1` | Low symbol | 0.2 | 0.4 | 1 |
| `L2` | Low symbol | 0.1 | 0.3 | 0.8 |
| `L3` | Low symbol | 0.1 | 0.3 | 0.8 |
| `L4` | Low symbol | 0.1 | 0.2 | 0.6 |
| `L5` | Lowest symbol | 0.1 | 0.2 | 0.6 |
| `W` | Wild | 0.8 | 2 | 6 |
| `S` | Scatter | - | - | - |

If a multiplier is active, the win is this value times the multiplier.

## Wild (`W`)

- A wild counts as the symbol beside it. `H1 W H1` is 3 x H1.
- 3, 4 or 5 wilds alone in a line pay like `H1`.
- One wild can help two wins at once: `H1 H1 W L1 L1` pays H1 and L1.

## Scatter (`S`)

- A scatter pays nothing.
- 3 scatters start the Refine bonus, 4 start Surge, 5 start Fusion.
- A scatter never lands during free spins.
- A scatter (or an empty cell) between symbols breaks a line.

## How a symbol looks in the data

- Normal symbol: `{"name": "H1"}`
- Wild: `{"name": "W", "wild": true}`
- Scatter: `{"name": "S", "scatter": true}`
