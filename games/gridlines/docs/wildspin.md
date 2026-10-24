# Wild Spin

**Mode name:** `wildspin`   **Cost:** 5x the bet

A normal spin with one extra: 1 to 5 symbols turn into wilds before the wins are counted.

## What the player sees

1. 25 symbols land on the board.
2. 1 to 5 of them turn into wilds.
3. From here it is a normal spin: wins, symbols vanish, fall, multiplier. See [base.md](base.md).

## Example: a spin that wins 0.2x

1. `reveal` - Show the 25 symbols.
2. `wildDrop` - Turn 2 cells into wilds: `{"reel": 2, "row": 1}` and `{"reel": 4, "row": 3}`.
3. `winInfo` - Highlight the win (3 x L1 in row 4). This win is `20` = 0.2x.
4. `updateTumbleWin` - The win counter of the spin shows 0.2x.
5. `collapseBoard` - Remove the winning symbols. Put one wild in the middle. Let the symbols fall.
6. `updateGlobalMult` - The multiplier shows 2x.
7. `setWin` - The spin is over. It won 0.2x.
8. `setTotalWin` - Total of the round: 0.2x.
9. `finalWin` - The round is over. The player gets 0.2x.

## Remember

- `wildDrop` is always the second event, also when the spin wins nothing.
- The board in `reveal` still has the old symbols. The frontend changes those cells to wilds when `wildDrop` arrives.
- How many wilds: mostly 1 (60%), then 2 (25%), 3 (10%), 4 (3.5%), 5 (1.5%).
- A scatter or a wild is never replaced.
- The spin costs 5x, but `20` still means 0.2x the normal bet.
- A bonus can start, the same way as in a base spin.

Symbols and pays: [symbols.md](symbols.md). All events: [events.md](events.md).
