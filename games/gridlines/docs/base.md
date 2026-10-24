# Base spin

**Mode name:** `base`   **Cost:** 1x the bet

The normal spin.

## What the player sees

1. 25 symbols land on the board.
2. 3, 4 or 5 same symbols next to each other in a row or a column win.
3. The winning symbols vanish. One wild appears in the middle of each win. The symbols above fall down. No new symbols come in.
4. If the fall makes a new win, it pays too. Every win raises the multiplier for the next wins of this spin: 1x, 2x, 3x ...
5. When no win is left, the spin is over.
6. If 3, 4 or 5 scatters are on the board, a bonus starts.

## Example: a spin that wins 0.5x

The server sends these 8 events. Play them from top to bottom.

1. `reveal` - Show the 25 symbols.
2. `winInfo` - Highlight the 3 winning symbols (3 x H2 in the last column). This win is `50` = 0.5x.
3. `updateTumbleWin` - The win counter of the spin shows 0.5x.
4. `collapseBoard` - Remove the 3 winning symbols. Put one wild in the middle. Let the symbols fall.
5. `updateGlobalMult` - The multiplier shows 2x. (It would count for the next win. Here no win follows.)
6. `setWin` - The spin is over. It won 0.5x. Play the win animation.
7. `setTotalWin` - Total of the round: 0.5x.
8. `finalWin` - The round is over. The player gets 0.5x.

If the fall makes another win, events 2 to 5 come again before `setWin`.

A spin that wins nothing has only 3 events: `reveal`, `setTotalWin`, `finalWin`.

## Remember

- The multiplier starts at 1x again on every new spin.
- Multiplier steps: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 14, 20, 28, 40, 55, 75, 100, 150, 200, 300, 400, 500, 750, 1000. Always show the number from the event.
- If `freeSpinTrigger` comes after `setTotalWin`, a bonus starts. `bonusType` says which one: [refine.md](refine.md), [surge.md](surge.md) or [fusion.md](fusion.md).

Symbols and pays: [symbols.md](symbols.md). All events: [events.md](events.md).
