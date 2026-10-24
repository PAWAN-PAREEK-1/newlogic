# Surge bonus

**Mode name:** `surge`   **Cost:** 200x the bet   **Free spins:** 12

It also starts when 4 scatters land on a normal spin.

## What the player sees

1. A board with 4 scatters lands. The bonus starts.
2. The player gets 12 free spins.
3. Every row and every column has its own multiplier (see below).
4. On every free spin, 3 symbols turn into wilds before the wins are counted.
5. After 12 free spins the bonus is over.

## Example: a real round that wins 89.9x

**Start**

1. `reveal` - Show the board. It has 4 scatters.
2. `setTotalWin` - Total so far: 0.
3. `freeSpinTrigger` - The Surge bonus starts with 12 free spins (`"bonusType": "surge", "totalFs": 12`). Highlight the 4 scatters.
4. `updateLineMult` - Show the ten multipliers. All are 1x.

**Free spin 1** (a block like this comes 12 times)

5. `updateFreeSpin` - Show "free spin 1 of 12" (`"amount": 0, "total": 12`).
6. `reveal` - Show a new board.
7. `wildDrop` - Turn 3 cells into wilds.
8. `winInfo` - Highlight the win (3 x H3 in row 3). This win is `40` = 0.4x.
9. `updateTumbleWin` - The win counter of the spin shows 0.4x.
10. `collapseBoard` - Remove the winning symbols. Put one wild in the middle. Let the symbols fall.
11. `setWin` - This free spin won 0.4x.
12. `setTotalWin` - Total of the round so far: 0.4x.

**End**

13. `freeSpinEnd` - The bonus is over. It won `8990` = 89.9x.
14. `finalWin` - The round is over. The player gets 89.9x.

## The ten multipliers

- Every row has a multiplier and every column has a multiplier. That is ten numbers on the screen. All start at 1x.
- A win in row 2 is paid times the multiplier of row 2. A win in column 4 is paid times the multiplier of column 4.
- Every win makes the multiplier of its own row or column grow. It grows slowly at first and fast later. It can reach 5000x.
- The multipliers stay until the bonus ends.
- When a number changes, the server sends `updateLineMult` with all ten numbers: `rows` (top row first) and `columns` (left column first). Just show them.

## Remember

- `wildDrop` comes after every `reveal` of a free spin, always with 3 cells.
- The board in `reveal` still has the old symbols. The frontend changes those 3 cells to wilds.
- The first board (step 1) can win like a normal spin before the bonus starts.
- A free spin that wins nothing has no `setWin`.
- No scatters land in free spins. The bonus cannot start again.
- The buy costs 200x, but `8990` still means 89.9x the normal bet.

Symbols and pays: [symbols.md](symbols.md). All events: [events.md](events.md).
