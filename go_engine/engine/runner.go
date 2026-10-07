package engine

// runner.go - the Go replacement for src/state/run_sims.py create_books().
//
// DESIGN
// ------
// Because every simulation seeds its own RNG with `sim + 1`, simulations are
// fully independent - "embarrassingly parallel". The runner fans batches of
// simulations out to a worker pool of goroutines and then writes the results
// back IN SIMULATION ORDER, so the output files are identical no matter how
// many workers run (and identical to the Python engine's output, which
// partitions sims across processes in the same global order).
//
// Python (10 processes, ~minutes)          Go (any number of goroutines, ~seconds)
//   create_books()                            RunMode()
//     run_multi_process_sims()                  criteria := AssignCriteria(...)
//       Process x N -> temp files               worker pool -> in-memory batch
//     output_lookup_and_force_files()           ordered writes -> final files
//
// Outputs per mode (same paths as Python):
//   library/publish_files/books_<mode>.jsonl.zst   - compressed books
//   library/books/books_<mode>.jsonl               - only when compression off
//   library/lookup_tables/lookUpTable_<mode>.csv   - id,weight,payout(cents)
//   library/lookup_tables/lookUpTableSegmented_<mode>.csv - base/free split
//   library/publish_files/lookUpTable_<mode>_0.csv - seeded optimized LUT
//   library/forces/force_record_<mode>.json        - recorded event -> book ids
//   library/forces/force.json                      - searchable key options
//   library/configs/event_config_<mode>.json       - one example per event type

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"sync"
	"time"

	"github.com/klauspost/compress/zstd"
)

// SimResult is everything one finished simulation contributes to the output.
type SimResult struct {
	simID         int    // == book id == simulation number
	BookLine      []byte // one line of books_<mode>.jsonl (Python json.dumps bytes)
	PayoutCents   int64
	BaseWins      any // int64-or-float64, Python min()-cap typing (see Book)
	FreeWins      any
	Criteria      string
	Force         []ForceRecord
	EventExamples map[string][]byte // event type -> example payload (minus "index")
	BaseAccum     float64           // capped base-game win (for RTP reporting)
	FreeAccum     float64           // capped free-game win (for RTP reporting)
}

// RunSpinFunc is the game hook executed for each simulation.
type RunSpinFunc func(s *State, sim int)

// AttachFunc wires game logic (special symbol hooks etc.) onto a fresh State.
type AttachFunc func(s *State)

// RunnerConfig controls one engine invocation.
type RunnerConfig struct {
	Spec           *Spec
	LibraryDir     string // games/<game>/library
	NumSims        map[string]int
	Modes          []string
	Workers        int
	BatchSize      int
	Compress       bool
	WriteEventList bool
	// Newline used for TEXT outputs (LUTs, force files, event configs).
	// Python writes these in text mode, so they get "\r\n" on Windows and
	// "\n" elsewhere; books are written in binary mode and always use "\n".
	Newline string
	Attach  AttachFunc
	RunSpin RunSpinFunc
}

// RunAll simulates every requested mode and writes all output files.
func RunAll(cfg RunnerConfig) error {
	if cfg.Workers <= 0 {
		cfg.Workers = runtime.NumCPU()
	}
	if cfg.BatchSize <= 0 {
		cfg.BatchSize = 10_000
	}
	if cfg.Newline == "" {
		cfg.Newline = "\n"
		if runtime.GOOS == "windows" {
			cfg.Newline = "\r\n" // Python text-mode translation on Windows
		}
	}
	for _, dir := range []string{"books", "configs", "forces", "lookup_tables", "publish_files"} {
		if err := os.MkdirAll(filepath.Join(cfg.LibraryDir, dir), 0o755); err != nil {
			return err
		}
	}

	forceOptions := map[string]Obj{}
	start := time.Now()
	fmt.Println("\nCreating books (Go engine)...")
	for _, modeName := range cfg.Modes {
		if err := runMode(cfg, modeName, forceOptions); err != nil {
			return fmt.Errorf("mode %s: %w", modeName, err)
		}
	}
	if err := WriteForceOptions(filepath.Join(cfg.LibraryDir, "forces"), cfg.Modes, forceOptions, cfg.Newline); err != nil {
		return err
	}
	fmt.Printf("\nFinished creating books in %.2f seconds.\n", time.Since(start).Seconds())
	return nil
}

func runMode(cfg RunnerConfig, modeName string, forceOptions map[string]Obj) error {
	spec := cfg.Spec
	mode := spec.Mode(modeName)
	numSims := cfg.NumSims[modeName]
	if numSims <= 0 {
		return nil
	}
	fmt.Printf("\nCreating books for %s in %s (%d sims, %d workers)\n",
		spec.GameID, modeName, numSims, cfg.Workers)

	// Deterministic criteria assignment - identical to the Python engine.
	criteria := AssignCriteria(mode, numSims)

	// Output sinks.
	bookPath := filepath.Join(cfg.LibraryDir, "publish_files", fmt.Sprintf("books_%s.jsonl.zst", modeName))
	var bookFile *os.File
	var zw *zstd.Encoder
	var plainWriter *bufio.Writer
	var err error
	if cfg.Compress {
		bookFile, err = os.Create(bookPath)
		if err != nil {
			return err
		}
		zw, err = zstd.NewWriter(bookFile)
		if err != nil {
			return err
		}
	} else {
		bookFile, err = os.Create(filepath.Join(cfg.LibraryDir, "books", fmt.Sprintf("books_%s.jsonl", modeName)))
		if err != nil {
			return err
		}
		plainWriter = bufio.NewWriterSize(bookFile, 1<<20)
	}
	lutFile, err := os.Create(filepath.Join(cfg.LibraryDir, "lookup_tables", fmt.Sprintf("lookUpTable_%s.csv", modeName)))
	if err != nil {
		return err
	}
	lutWriter := bufio.NewWriterSize(lutFile, 1<<20)
	segFile, err := os.Create(filepath.Join(cfg.LibraryDir, "lookup_tables", fmt.Sprintf("lookUpTableSegmented_%s.csv", modeName)))
	if err != nil {
		return err
	}
	segWriter := bufio.NewWriterSize(segFile, 1<<20)

	forceAgg := NewForceAggregator()
	eventExamples := Obj{}
	seenEvents := map[string]bool{}
	var totalBase, totalFree float64

	// Batch loop: generate a batch in parallel, then drain it in sim order.
	for batchStart := 0; batchStart < numSims; batchStart += cfg.BatchSize {
		batchEnd := batchStart + cfg.BatchSize
		if batchEnd > numSims {
			batchEnd = numSims
		}
		results := make([]*SimResult, batchEnd-batchStart)

		var wg sync.WaitGroup
		jobs := make(chan int)
		for w := 0; w < cfg.Workers; w++ {
			wg.Add(1)
			go func() {
				defer wg.Done()
				state := NewState(spec, mode)
				cfg.Attach(state)
				for sim := range jobs {
					results[sim-batchStart] = runOneSim(cfg, state, sim, criteria[sim])
				}
			}()
		}
		for sim := batchStart; sim < batchEnd; sim++ {
			jobs <- sim
		}
		close(jobs)
		wg.Wait()

		// Ordered drain -> identical files regardless of worker count.
		for _, res := range results {
			if cfg.Compress {
				if _, err := zw.Write(res.BookLine); err != nil {
					return err
				}
			} else {
				if _, err := plainWriter.Write(res.BookLine); err != nil {
					return err
				}
			}
			fmt.Fprintf(lutWriter, "%d,1,%d%s", resultID(res), res.PayoutCents, cfg.Newline)
			fmt.Fprintf(segWriter, "%d,%s,%s,%s%s",
				resultID(res), res.Criteria,
				PyNumStr(res.BaseWins), PyNumStr(res.FreeWins), cfg.Newline)
			forceAgg.Add(res.Force)
			for evType, example := range res.EventExamples {
				if !seenEvents[evType] {
					seenEvents[evType] = true
					eventExamples = append(eventExamples, KV{K: evType, V: rawJSON(example)})
				}
			}
			totalBase += res.BaseAccum
			totalFree += res.FreeAccum
		}
		fmt.Printf("  batch %d-%d done\n", batchStart, batchEnd-1)
	}

	// Close book stream.
	if cfg.Compress {
		if err := zw.Close(); err != nil {
			return err
		}
	} else {
		if err := plainWriter.Flush(); err != nil {
			return err
		}
	}
	if err := bookFile.Close(); err != nil {
		return err
	}
	if err := lutWriter.Flush(); err != nil {
		return err
	}
	if err := lutFile.Close(); err != nil {
		return err
	}
	if err := segWriter.Flush(); err != nil {
		return err
	}
	if err := segFile.Close(); err != nil {
		return err
	}

	// Seed the "optimized" LUT with the raw one if the optimizer has not run
	// yet (mirrors output_lookup_and_force_files).
	optimizedPath := filepath.Join(cfg.LibraryDir, "publish_files", fmt.Sprintf("lookUpTable_%s_0.csv", modeName))
	if _, err := os.Stat(optimizedPath); os.IsNotExist(err) {
		raw, err := os.ReadFile(filepath.Join(cfg.LibraryDir, "lookup_tables", fmt.Sprintf("lookUpTable_%s.csv", modeName)))
		if err != nil {
			return err
		}
		if err := os.WriteFile(optimizedPath, raw, 0o644); err != nil {
			return err
		}
	}

	if err := forceAgg.WriteForceRecord(
		filepath.Join(cfg.LibraryDir, "forces", fmt.Sprintf("force_record_%s.json", modeName)),
		cfg.Newline); err != nil {
		return err
	}
	forceOptions[modeName] = forceAgg.Options()

	if cfg.WriteEventList {
		if err := writeTextFile(
			filepath.Join(cfg.LibraryDir, "configs", fmt.Sprintf("event_config_%s.json", modeName)),
			MarshalPyIndent(eventExamples, 4), cfg.Newline); err != nil {
			return err
		}
	}

	// RTP report (same accounting as the Python thread printout).
	cost := mode.Cost
	fmt.Printf("Mode %s finished with %.3f RTP. [baseGame: %.3f, freeGame: %.3f]\n",
		modeName,
		(totalBase+totalFree)/(float64(numSims)*cost),
		totalBase/(float64(numSims)*cost),
		totalFree/(float64(numSims)*cost))
	return nil
}

// resultID returns the book id (== the simulation number).
func resultID(res *SimResult) int { return res.simID }

// runOneSim executes a single simulation on a reusable per-worker State.
func runOneSim(cfg RunnerConfig, state *State, sim int, criteria string) *SimResult {
	state.Criteria = criteria
	state.Dist = state.Mode.DistributionFor(criteria)

	cfg.RunSpin(state, sim)

	// imprint_wins equivalents:
	state.WinManager.UpdateEndRoundWins()
	bookJSON := state.Book.ToJSON()
	line := append(MarshalPy(bookJSON), '\n')

	// Event examples (write_library_events: payload minus the "index" key).
	examples := map[string][]byte{}
	for _, ev := range state.Book.Events {
		evType := ""
		for _, kv := range ev {
			if kv.K == "type" {
				evType = kv.V.(string)
				break
			}
		}
		if _, ok := examples[evType]; ok {
			continue
		}
		trimmed := make(Obj, 0, len(ev)-1)
		for _, kv := range ev {
			if kv.K != "index" {
				trimmed = append(trimmed, kv)
			}
		}
		examples[evType] = MarshalPyIndent(trimmed, 4)
	}

	return &SimResult{
		simID:         sim,
		BookLine:      line,
		PayoutCents:   PyRound0Int(state.Book.PayoutMultiplier * 100),
		BaseWins:      state.Book.BasegameWins,
		FreeWins:      state.Book.FreegameWins,
		Criteria:      state.Criteria,
		Force:         state.ImprintedRecords(),
		EventExamples: examples,
		BaseAccum:     MinF(state.WinManager.MaxAllowedWin, state.WinManager.BasegameWins),
		FreeAccum:     MinF(state.WinManager.MaxAllowedWin, state.WinManager.FreegameWins),
	}
}
