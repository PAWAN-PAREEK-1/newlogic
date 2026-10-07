package optimizer

import (
	"bufio"
	"fmt"
	"math"
	"math/rand/v2"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"sync"
	"time"
)

// Config selects what to optimize.
type Config struct {
	LibraryDir string
	Mode       string
	Params     Params
	Threads    int    // 0 = all CPUs
	Seed       uint64 // runs with the same seed and thread count are reproducible
}

const twoPow50 = float64(1 << 50)

// Same reporting buckets as main.rs get_win_ranges.
var winRanges = [][2]float64{
	{0, 0.1}, {0.1, 1}, {1, 2}, {2, 3}, {3, 5}, {5, 10}, {10, 20}, {20, 50}, {50, 100},
	{100, 200}, {200, 500}, {500, 1000}, {1000, 2000}, {2000, 3000}, {3000, 5001},
}

// workerSource gives every worker its own reproducible stream.
func workerSource(seed uint64, stream uint64) *rand.PCG {
	return rand.NewPCG(seed^0x6A09E667F3BCC909, stream*0x9E3779B97F4A7C15+1)
}

// fmtFloat formats like Rust's `{}` for f64 (shortest round-trip, no exponent).
func fmtFloat(v float64) string { return strconv.FormatFloat(v, 'f', -1, 64) }

// toU64 mirrors Rust's saturating `f64 as u64`.
func toU64(v float64) uint64 {
	if !(v > 0) {
		return 0
	}
	if v >= 18446744073709551615.0 {
		return math.MaxUint64
	}
	return uint64(v)
}

// Run optimizes one bet mode and writes the lookup table and optimization files
// (main.rs: run_farm).
func Run(cfg Config) error {
	start := time.Now()
	threads := cfg.Threads
	if threads <= 0 {
		threads = runtime.NumCPU()
	}
	p := cfg.Params
	fmt.Printf("Running Go optimizer - mode: %s (%d threads, seed %d)\n", cfg.Mode, threads, cfg.Seed)

	fences, cost, _, err := loadFences(cfg.LibraryDir, cfg.Mode)
	if err != nil {
		return err
	}
	books, err := loadLookupTable(cfg.LibraryDir, cfg.Mode)
	if err != nil {
		return err
	}
	forces, err := loadForces(cfg.LibraryDir, cfg.Mode)
	if err != nil {
		return err
	}
	if err := assignBooks(fences, books, forces); err != nil {
		return err
	}
	fmt.Printf("[timing] load inputs: %.1fs (%d books)\n", time.Since(start).Seconds(), len(books))

	// Pig pens per regular fence, built in parallel (one worker = one Rust thread).
	ctx := &scoringContext{fences: fences}
	var mu sync.Mutex
	logf := func(format string, a ...any) {
		mu.Lock()
		fmt.Printf(format+"\n", a...)
		mu.Unlock()
	}
	for fi, f := range fences {
		if f.WinType {
			continue
		}
		t := time.Now()
		heaven := &pigHeaven{wins: f.Wins, dresses: f.Dresses, numPigs: p.NumPigsPerFence / threads,
			maxWin: f.Wins[len(f.Wins)-1], minWin: f.Wins[0], avgWin: f.AvgWin * cost}
		if heaven.numPigs < 1 {
			return fmt.Errorf("num_pigs_per_fence (%d) must be >= threads (%d)", p.NumPigsPerFence, threads)
		}
		pens := make([][]Pig, threads)
		errs := make([]error, threads)
		var wg sync.WaitGroup
		for w := 0; w < threads; w++ {
			wg.Add(1)
			go func(w int) {
				defer wg.Done()
				pens[w], errs[w] = createAncestors(heaven, f.MinM2M, f.MaxM2M, f.Bias, p.MaxTrialDist,
					rand.New(workerSource(cfg.Seed, uint64(fi*1000+w))), logf)
			}(w)
		}
		wg.Wait()
		var pen []Pig
		for w := range pens {
			if errs[w] != nil {
				return fmt.Errorf("fence %s: %w", f.Name, errs[w])
			}
			pen = append(pen, pens[w]...)
		}
		ctx.regular = append(ctx.regular, f)
		ctx.pens = append(ctx.pens, pen)
		fmt.Printf("[timing] fence %s: %.1fs (%d distinct wins, %d distributions)\n",
			f.Name, time.Since(t).Seconds(), len(f.Wins), len(pen))
	}

	// All payouts of the mode (main.rs: sorted_wins) and index maps.
	seen := map[uint64]bool{}
	var sortedWins []float64
	for _, f := range fences {
		if f.WinType {
			seen[math.Float64bits(f.AvgWin)] = true
			sortedWins = append(sortedWins, f.AvgWin)
			continue
		}
		for _, w := range f.Wins {
			if !seen[math.Float64bits(w)] {
				seen[math.Float64bits(w)] = true
				sortedWins = append(sortedWins, w)
			}
		}
	}
	sort.Float64s(sortedWins)
	indexOf := make(map[uint64]int, len(sortedWins))
	for i, w := range sortedWins {
		indexOf[math.Float64bits(w)] = i
	}
	ctx.sortedWins = sortedWins
	for _, f := range fences {
		idx := -1
		if f.WinType {
			if i, ok := indexOf[math.Float64bits(f.AvgWin)]; ok {
				idx = i
			}
		}
		ctx.fixedIndex = append(ctx.fixedIndex, idx)
	}
	for _, f := range ctx.regular {
		g := make([]int, len(f.Wins))
		for n, w := range f.Wins {
			g[n] = -1
			if i, ok := indexOf[math.Float64bits(w)]; ok {
				g[n] = i
			}
		}
		ctx.globalIndex = append(ctx.globalIndex, g)
	}

	// Show pigs (main.rs: create_show_pigs on every thread, then sort by score).
	t := time.Now()
	results := make([][]showPig, threads)
	errs := make([]error, threads)
	var wg sync.WaitGroup
	for w := 0; w < threads; w++ {
		wg.Add(1)
		go func(w int) {
			defer wg.Done()
			results[w], errs[w] = ctx.createShowPigs(p.NumShowPigs/threads, p, cost,
				workerSource(cfg.Seed, uint64(1_000_000+w)))
		}(w)
	}
	wg.Wait()
	var show []showPig
	for w := range results {
		if errs[w] != nil {
			return errs[w]
		}
		show = append(show, results[w]...)
	}
	sort.SliceStable(show, func(a, b int) bool { return show[a].score > show[b].score })
	fmt.Printf("[timing] show distributions: %.1fs\n", time.Since(t).Seconds())
	if len(show) == 0 {
		return fmt.Errorf("no distribution scored above 0 - check test_spins / pmb_rtp")
	}

	t = time.Now()
	if err := writeOutputs(cfg, ctx, books, show); err != nil {
		return err
	}
	fmt.Printf("[timing] write outputs: %.1fs\n", time.Since(t).Seconds())
	fmt.Printf("time taken %.1fs\n", time.Since(start).Seconds())
	return nil
}

// writeOutputs writes the top 10 distributions (main.rs: print_information).
func writeOutputs(cfg Config, ctx *scoringContext, books []Book, show []showPig) error {
	num := 10
	if len(show) < num {
		fmt.Printf("warning: only %d distributions were kept; writing %d files\n", len(show), len(show))
		num = len(show)
	}
	order := make([]int, len(books))
	for i := range order {
		order[i] = i
	}
	sort.Slice(order, func(a, b int) bool { return books[order[a]].ID < books[order[b]].ID })
	optDir := filepath.Join(cfg.LibraryDir, "optimization_files")
	if err := os.MkdirAll(optDir, 0o755); err != nil {
		return err
	}

	errs := make([]error, num)
	var wg sync.WaitGroup
	for n := 0; n < num; n++ {
		wg.Add(1)
		go func(n int) {
			defer wg.Done()
			errs[n] = writeOne(cfg, ctx, books, order, show[n], n)
		}(n)
	}
	wg.Wait()
	for _, err := range errs {
		if err != nil {
			return err
		}
	}
	return nil
}

func writeOne(cfg Config, ctx *scoringContext, books []Book, order []int, sp showPig, n int) error {
	s := &weightScratch{}
	weights := make([]float64, len(ctx.sortedWins))
	fenceWeights := make([][]float64, len(ctx.regular))
	for k, f := range ctx.regular {
		fenceWeights[k] = make([]float64, len(f.Wins))
	}
	ctx.combine(sp.pigIndexes, weights, fenceWeights, s)

	// Per-book weights: P(payout | fence) / hr / books with that payout * 2^50.
	bookWeight := make(map[uint32]uint64, len(books))
	for _, b := range books {
		bookWeight[b.ID] = b.Weight // books outside every fence keep their weight
	}
	regular := 0
	for _, f := range ctx.fences {
		for k, ids := range f.WinBooks {
			var w uint64
			if f.WinType {
				w = toU64(1 / f.HR / float64(len(ids)) * twoPow50)
			} else {
				w = toU64(fenceWeights[regular][k] / f.HR / float64(len(ids)) * twoPow50)
			}
			for _, id := range ids {
				bookWeight[id] = w
			}
		}
		if !f.WinType {
			regular++
		}
	}
	rtp, sumDist := 0.0, 0.0
	for _, i := range order {
		b := books[i]
		rtp += float64(bookWeight[b.ID]) * b.Win()
		sumDist += float64(bookWeight[b.ID])
	}
	rtp /= sumDist

	if n == 0 {
		path := filepath.Join(cfg.LibraryDir, "publish_files", fmt.Sprintf("lookUpTable_%s_0.csv", cfg.Mode))
		if err := writeFile(path, func(w *bufio.Writer) {
			for _, i := range order {
				b := books[i]
				fmt.Fprintf(w, "%d,%d,%d\n", b.ID, bookWeight[b.ID], uint64(math.Round(b.Win()*100)))
			}
		}); err != nil {
			return err
		}
	}
	path := filepath.Join(cfg.LibraryDir, "optimization_files", fmt.Sprintf("%s_0_%d.csv", cfg.Mode, n+1))
	return writeFile(path, func(w *bufio.Writer) {
		fmt.Fprintf(w, "Name,Pig%d\nScore,%s\nLockedUpRTP,\nRtp,%s\nWin Ranges\n", n+1, fmtFloat(sp.score), fmtFloat(rtp))
		for _, rg := range winRanges {
			tot := 0.0
			for i, win := range ctx.sortedWins {
				if win >= rg[0] && win < rg[1] {
					tot += weights[i]
				}
			}
			if tot == 0 {
				fmt.Fprintf(w, "%s,%s,1 in never\n", fmtFloat(rg[0]), fmtFloat(rg[1]))
			} else {
				fmt.Fprintf(w, "%s,%s,1 in %.3f\n", fmtFloat(rg[0]), fmtFloat(rg[1]), 1/tot)
			}
		}
		fmt.Fprintf(w, "Distribution\n")
		for _, i := range order {
			b := books[i]
			fmt.Fprintf(w, "%d,%d,%.2f\n", b.ID, bookWeight[b.ID], b.Win())
		}
	})
}

func writeFile(path string, body func(*bufio.Writer)) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	w := bufio.NewWriterSize(f, 1<<20)
	body(w)
	if err := w.Flush(); err != nil {
		f.Close()
		return err
	}
	return f.Close()
}
