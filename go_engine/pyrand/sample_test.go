package pyrand

// Parity test for Sample against CPython 3.12:
//
//	random.seed(seed); random.sample(range(n), k); repr(random.random())
//
// The trailing random() proves the stream position after the sample matches.
// Cases cover both CPython branches: pool selection (n <= setsize) and
// set-based rejection sampling (n > setsize, e.g. a 25-cell board with k <= 5).

import (
	"reflect"
	"strconv"
	"testing"
)

func TestSampleMatchesCPython(t *testing.T) {
	cases := []struct {
		seed  uint64
		n, k  int
		want  []int
		after string
	}{
		{1, 25, 1, []int{4}, "0.5692038748222122"},
		{2, 25, 5, []int{1, 2, 11, 5, 23}, "0.8089620446393668"},
		{3, 20, 3, []int{7, 18, 17}, "0.13042279608514273"},
		{4, 21, 5, []int{7, 9, 3, 12, 15}, "0.15497227080241027"},
		{7, 22, 2, []int{10, 4}, "0.3948234964231735"},
		{9, 100, 10, []int{59, 78, 47, 34, 17, 23, 86, 0, 43, 64}, "0.46372153534217153"},
		{11, 10, 0, []int{}, "0.4523795535098186"},
		{12, 10, 10, []int{7, 4, 5, 1, 3, 0, 2, 6, 9, 8}, "0.6905926530386846"},
		{13, 30, 6, []int{8, 9, 21, 27, 25, 5}, "0.6520097272884742"},
	}
	for _, c := range cases {
		r := New(c.seed)
		got := r.Sample(c.n, c.k)
		if !reflect.DeepEqual(got, c.want) {
			t.Errorf("seed %d sample(%d, %d) = %v, want %v", c.seed, c.n, c.k, got, c.want)
		}
		want, _ := strconv.ParseFloat(c.after, 64)
		if after := r.Random(); after != want {
			t.Errorf("seed %d: random() after sample = %v, want %s", c.seed, after, c.after)
		}
	}
}
