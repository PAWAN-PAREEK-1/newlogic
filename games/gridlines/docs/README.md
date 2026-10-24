# Grid Line Pays - frontend docs

Read in this order: this page, then [symbols.md](symbols.md), then [base.md](base.md). After that, any mode you need.

## 5 rules for every mode

1. **One bet, one answer.** The server answers with a list called `events`. Play the events one by one, from the first to the last. The frontend never decides a result.
2. **Every number is the bet times 100.** `250` means 2.5x the bet. `50` means 0.5x the bet.
3. **"The bet" is always the normal 1x bet.** A Wild Spin costs 5x, but `250` is still 2.5x the normal bet.
4. **The board has 5 columns (reels) and 5 rows.** In `board[reel][row]`, reel 0 is the left column and row 0 is the top row.
5. **Cells inside events are written as `reel` 0 to 4 and `row` 1 to 5.** Row 1 is the top row.

## The modes

| Page | Mode name | Cost | What it is |
|---|---|---|---|
| [base.md](base.md) | `base` | 1x | The normal spin |
| [wildspin.md](wildspin.md) | `wildspin` | 5x | Normal spin + extra wilds |
| [primespin.md](primespin.md) | `primespin` | 20x | Normal spin without the lowest symbols |
| [refine.md](refine.md) | `refine` | 100x | Buys the Refine bonus (8 free spins) |
| [surge.md](surge.md) | `surge` | 200x | Buys the Surge bonus (12 free spins) |
| [mystery.md](mystery.md) | `mystery` | 300x | One spin, the result is a surprise |
| [fusion.md](fusion.md) | - | - | The Fusion bonus (15 free spins). It cannot be bought |

## Other pages

- [symbols.md](symbols.md): every symbol, what it does, what it pays.
- [events.md](events.md): every event in one line.
- [../FRONTEND_GUIDE.md](../FRONTEND_GUIDE.md): the long reference with every field.
