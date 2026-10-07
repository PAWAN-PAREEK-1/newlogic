package optimizer

import "testing"

// Payout-range fences take remaining books with start < win <= end, in fence order
// (main.rs sort_wins_by_parameter), after fixed-payout fences took theirs.
func TestAssignBooksPayoutRange(t *testing.T) {
	books := []Book{{ID: 0, Cents: 0}, {ID: 1, Cents: 5000}, {ID: 2, Cents: 10000},
		{ID: 3, Cents: 15000}, {ID: 4, Cents: 2500000}, {ID: 5, Cents: 20000}}
	wincap := &Fence{Name: "wincap", WinType: true, AvgWin: 25000, WinRangeStart: 25000, WinRangeEnd: 25000}
	zero := &Fence{Name: "0", WinType: true, AvgWin: 0, WinRangeStart: 0, WinRangeEnd: 0}
	low := &Fence{Name: "low", WinRangeStart: 0, WinRangeEnd: 100}
	high := &Fence{Name: "high", WinRangeStart: 100, WinRangeEnd: 25000}
	fences := []*Fence{wincap, zero, low, high}
	if err := assignBooks(fences, books, nil); err != nil {
		t.Fatal(err)
	}
	count := func(f *Fence) int {
		n := 0
		for _, ids := range f.WinBooks {
			n += len(ids)
		}
		return n
	}
	if count(wincap) != 1 || count(zero) != 1 || count(low) != 2 || count(high) != 2 {
		t.Fatalf("got wincap=%d zero=%d low=%d high=%d", count(wincap), count(zero), count(low), count(high))
	}
}
