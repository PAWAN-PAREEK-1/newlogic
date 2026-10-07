package engine

// book.go - mirror of src/state/books.py.
//
// A Book is the full recorded outcome of ONE simulated betting round: the
// ordered list of events the frontend replays, plus the final payout split.
// One book == one line of books_<mode>.jsonl.

// Book mirrors the Python Book class.
//
// BasegameWins/FreegameWins are `any` (int64 or float64) to replicate a
// CPython formatting quirk: update_final_win stores min(win, config.wincap),
// and when the round EXCEEDS the cap Python's min() returns the cap object
// itself - an int if the cap was declared as an int in mode_maxwins - so the
// books print "freeGameWins": 25000 (no decimal) for capped rounds but
// "freeGameWins": 123.5 otherwise. Byte-identical output requires carrying
// that type distinction through to JSON.
type Book struct {
	ID               int
	PayoutMultiplier float64
	Events           []Obj
	Criteria         string
	BasegameWins     any
	FreegameWins     any
}

// NewBook mirrors Book.__init__.
func NewBook(id int, criteria string) *Book {
	return &Book{ID: id, Criteria: criteria, Events: []Obj{}, BasegameWins: 0.0, FreegameWins: 0.0}
}

// AddEvent mirrors Book.add_event (the Python side deep-copies; in Go every
// event Obj is freshly built per call, so no copy is needed).
func (b *Book) AddEvent(event Obj) {
	b.Events = append(b.Events, event)
}

// ToJSON mirrors Book.to_json - note payoutMultiplier is stored as an
// integer number of cents: int(round(payout * 100, 0)).
func (b *Book) ToJSON() Obj {
	return Obj{
		{K: "id", V: b.ID},
		{K: "payoutMultiplier", V: PyRound0Int(b.PayoutMultiplier * 100)},
		{K: "events", V: b.Events},
		{K: "criteria", V: b.Criteria},
		{K: "baseGameWins", V: b.BasegameWins},
		{K: "freeGameWins", V: b.FreegameWins},
	}
}
