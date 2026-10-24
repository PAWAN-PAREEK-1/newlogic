# Refine bonus

**Mode name:** `refine`   **Cost:** 100x the bet   **Free spins:** 8

It also starts when 3 scatters land on a normal spin.

## What the player sees

1. A board with 3 scatters lands. The bonus starts.
2. The player gets 8 free spins.
3. Every row and every column has its own multiplier (see below).
4. After every free spin that wins, the lowest symbol is taken out of the game. A better symbol lands in its place.
5. After 8 free spins the bonus is over.

## Example: a real round that wins 151.2x

**Start**

1. `reveal` - Show the board. It has 3 scatters.
2. `setTotalWin` - Total so far: 0.
3. `freeSpinTrigger` - The Refine bonus starts with 8 free spins (`"bonusType": "refine", "totalFs": 8`). Highlight the 3 scatters.
4. `updateLineMult` - Show the ten multipliers. All are 1x.

**Free spin 1** (a block like this comes 8 times)

5. `updateFreeSpin` - Show "free spin 1 of 8" (`"amount": 0, "total": 8`).
6. `reveal` - Show a new board.
7. `winInfo` - Highlight the win (3 x L4 in the third column). This win is `10` = 0.1x.
8. `updateTumbleWin` - The win counter of the spin shows 0.1x.
9. `collapseBoard` - Remove the winning symbols. Put one wild in the middle. Let the symbols fall.
10. `setWin` - This free spin won 0.1x.
11. `setTotalWin` - Total of the round so far: 0.1x.
12. `refineSymbol` - L5 is out of the game. From now on it lands as L4 (`"removed": "L5", "into": "L4"`).

**End**

13. `freeSpinEnd` - The bonus is over. It won `15120` = 151.2x.
14. `finalWin` - The round is over. The player gets 151.2x.

## The ten multipliers

- Every row has a multiplier and every column has a multiplier. That is ten numbers on the screen. All start at 1x.
- A win in row 2 is paid times the multiplier of row 2. A win in column 4 is paid times the multiplier of column 4.
- Every win makes the multiplier of its own row or column grow. It grows slowly at first and fast later. It can reach 5000x.
- The multipliers stay until the bonus ends.
- When a number changes, the server sends `updateLineMult` with all ten numbers: `rows` (top row first) and `columns` (left column first). Just show them.

## Symbols taken out

Always in this order, one after every winning free spin:

L5 lands as L4, then L4 as L3, L3 as L2, L2 as L1, L1 as H4, H4 as H3, H3 as H2, H2 as H1.

## Remember

- The first board (step 1) can win like a normal spin before the bonus starts. Then `winInfo`, `collapseBoard` and so on come before `freeSpinTrigger`.
- A free spin that wins nothing has no `setWin` and no `refineSymbol`.
- After `refineSymbol`, the next boards are already correct. The frontend only shows which symbols are out.
- No scatters land in free spins. The bonus cannot start again.
- The buy costs 100x, but `15120` still means 151.2x the normal bet.

Symbols and pays: [symbols.md](symbols.md). All events: [events.md](events.md).
