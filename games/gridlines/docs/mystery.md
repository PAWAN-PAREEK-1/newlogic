# Mystery buy

**Mode name:** `mystery`   **Cost:** 300x the bet

The player buys one spin. The result is a surprise: a bonus, or no bonus.

## What the player sees

1. One board lands, like a normal spin.
2. The number of scatters on it decides the result:

| Scatters on the board | Result |
|---|---|
| 0, 1 or 2 | No bonus. The player gets only the small win of this spin |
| 3 | Refine bonus, 8 free spins: [refine.md](refine.md) |
| 4 | Surge bonus, 12 free spins: [surge.md](surge.md) |
| 5 | Fusion bonus, 15 free spins: [fusion.md](fusion.md) |

## How the frontend knows the result

There is no special Mystery event. The events are the same as in a base spin ([base.md](base.md)).

- If `freeSpinTrigger` arrives, a bonus starts. `bonusType` says which one.
- If `finalWin` arrives without a `freeSpinTrigger`, there was no bonus.

## Example: no bonus, the spin wins 1.2x

1. `reveal` - Show the 25 symbols.
2. `winInfo`, `updateTumbleWin`, `collapseBoard`, `updateGlobalMult` - Show the win and the fall, like a base spin.
3. `setWin` - The spin won `120` = 1.2x.
4. `setTotalWin` - Total of the round: 1.2x.
5. `finalWin` - The round is over. The player gets 1.2x.

## How often each result comes

| Result | How often |
|---|---|
| No bonus | 2% |
| Refine | about 14% |
| Surge | about 83.6% |
| Fusion | about 0.3% |

These numbers come from the math and can change. Use them only for the help screen.

## Remember

- A no-bonus spin pays little (usually 3x the bet or less) and sometimes nothing. This is normal, not an error.
- The buy costs 300x, but `120` still means 1.2x the normal bet.

Symbols and pays: [symbols.md](symbols.md). All events: [events.md](events.md).
