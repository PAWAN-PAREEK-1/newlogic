# Fusion bonus

**Cannot be bought.**   **Free spins:** 15

It starts when 5 scatters land on a normal spin (base, Wild Spin, Prime Spin or Mystery).

Fusion is the Refine bonus and the Surge bonus together.

## What the player sees

1. A board with 5 scatters lands. The bonus starts.
2. The player gets 15 free spins.
3. Every row and every column has its own multiplier (see below).
4. On every free spin, 3 symbols turn into wilds before the wins are counted. (Like Surge.)
5. After every free spin that wins, the lowest symbol is taken out of the game. (Like Refine.)
6. After 15 free spins the bonus is over.

## The events

**Start**

1. `freeSpinTrigger` - The Fusion bonus starts with 15 free spins (`"bonusType": "fusion", "totalFs": 15`). Highlight the 5 scatters.
2. `updateLineMult` - Show the ten multipliers. All are 1x.

**Each free spin** (15 times)

3. `updateFreeSpin` - Show "free spin 1 of 15".
4. `reveal` - Show a new board.
5. `wildDrop` - Turn 3 cells into wilds.
6. `winInfo`, `updateTumbleWin`, `collapseBoard` - Show the win and the fall. This repeats while the board has wins.
7. `setWin` - What this free spin won.
8. `setTotalWin` - Total of the round so far.
9. `refineSymbol` - The lowest symbol is out of the game.

**End**

10. `freeSpinEnd` - The bonus is over. `amount` is what it won.
11. `finalWin` - The round is over.

## The ten multipliers

- Every row has a multiplier and every column has a multiplier. That is ten numbers on the screen. All start at 1x.
- A win in row 2 is paid times the multiplier of row 2. A win in column 4 is paid times the multiplier of column 4.
- Every win makes the multiplier of its own row or column grow. It grows slowly at first and fast later. It can reach 5000x.
- The multipliers stay until the bonus ends.
- When a number changes, the server sends `updateLineMult` with all ten numbers: `rows` (top row first) and `columns` (left column first). Just show them.

## Remember

- Fusion pays big. The smallest Fusion bonus in the game data pays about 800x the bet. Plan big win animations.
- For the wilds see [surge.md](surge.md). For the symbols taken out see [refine.md](refine.md).
- A free spin that wins nothing has no `setWin` and no `refineSymbol`.
- No scatters land in free spins. The bonus cannot start again.

Symbols and pays: [symbols.md](symbols.md). All events: [events.md](events.md).
