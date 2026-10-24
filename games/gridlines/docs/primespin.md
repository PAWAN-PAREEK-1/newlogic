# Prime Spin

**Mode name:** `primespin`   **Cost:** 20x the bet

A normal spin without the lowest symbols. 2 to 5 of the lowest symbols are taken out. Where they would land, a better symbol lands.

## What the player sees

1. The game shows which symbols are taken out for this spin, for example L5 and L4.
2. 25 symbols land on the board. The removed symbols are not on it.
3. From here it is a normal spin: wins, symbols vanish, fall, multiplier. See [base.md](base.md).

## Example: a spin that wins 0.1x

1. `primeSymbols` - `"removedSymbols": ["L5", "L4"], "landAs": "L3"`. Show that L5 and L4 are out. They land as L3.
2. `reveal` - Show the 25 symbols. There is no L5 and no L4 on the board.
3. `winInfo` - Highlight the win (3 x L3 in the third column). This win is `10` = 0.1x.
4. `updateTumbleWin` - The win counter of the spin shows 0.1x.
5. `collapseBoard` - Remove the winning symbols. Put one wild in the middle. Let the symbols fall.
6. `updateGlobalMult` - The multiplier shows 2x.
7. `setWin` - The spin is over. It won 0.1x.
8. `setTotalWin` - Total of the round: 0.1x.
9. `finalWin` - The round is over. The player gets 0.1x.

## Which symbols are taken out

| `level` | How often | Taken out | They land as |
|---|---|---|---|
| 2 | 60% | L5, L4 | L3 |
| 3 | 28% | L5, L4, L3 | L2 |
| 4 | 10% | L5, L4, L3, L2 | L1 |
| 5 | 2% | L5, L4, L3, L2, L1 | H4 |

## Remember

- `primeSymbols` is always the first event.
- The frontend does not change the board. The board in `reveal` is already correct.
- It counts for this one spin only. If a bonus starts, all symbols are back.
- The spin costs 20x, but `10` still means 0.1x the normal bet.

Symbols and pays: [symbols.md](symbols.md). All events: [events.md](events.md).
