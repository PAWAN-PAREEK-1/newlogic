// Command go-engine simulates Stake Engine game rounds ("books") from a game
// spec exported by the Python Math SDK, writing the same output files as the
// Python engine but 1-2 orders of magnitude faster (native code + goroutines
// + one process for all modes).
//
// Typical invocation (from the repository root; run_go.py does this for you):
//
//	go run ./go_engine --spec games/expwilds/library/configs/game_spec_go.json \
//	    --library games/expwilds/library \
//	    --modes base,ante,superante,bonus,superbonus,superspin \
//	    --sims 100000
//
// The Go engine replicates CPython's RNG, so its books are byte-identical to
// the Python engine's for the same simulation counts. Optimization (Rust) and
// analysis (Python) then run unchanged on these files.
package main

import (
	"flag"
	"fmt"
	"os"
	"strconv"
	"strings"

	"github.com/stakeengine/go-engine/engine"
	"github.com/stakeengine/go-engine/game"
	"github.com/stakeengine/go-engine/optimizer"
)

func main() {
	if len(os.Args) > 1 && os.Args[1] == "optimize" {
		runOptimize(os.Args[2:])
		return
	}

	specPath := flag.String("spec", "", "path to game_spec_go.json (exported by export_spec.py)")
	libraryDir := flag.String("library", "", "path to games/<game>/library output directory")
	modesArg := flag.String("modes", "", "comma-separated bet modes to simulate (default: all in spec)")
	simsArg := flag.String("sims", "10000", "simulations per mode: a number, or per-mode pairs 'base=100000,bonus=50000'")
	workers := flag.Int("workers", 0, "worker goroutines (default: number of CPUs)")
	batch := flag.Int("batch", 10000, "simulations buffered per batch (memory/throughput trade-off)")
	compress := flag.Bool("compress", true, "write zstd-compressed books (books_<mode>.jsonl.zst)")
	writeEvents := flag.Bool("write-event-list", true, "write event_config_<mode>.json examples")
	flag.Parse()

	if *specPath == "" || *libraryDir == "" {
		fmt.Fprintln(os.Stderr, "error: --spec and --library are required")
		flag.Usage()
		os.Exit(2)
	}

	spec, err := engine.Load(*specPath)
	if err != nil {
		fatal(err)
	}

	// Default to every mode defined in the spec, in spec order.
	var modes []string
	if *modesArg == "" {
		for _, m := range spec.BetModes {
			modes = append(modes, m.Name)
		}
	} else {
		for _, m := range strings.Split(*modesArg, ",") {
			modes = append(modes, strings.TrimSpace(m))
		}
	}

	numSims, err := parseSims(*simsArg, modes)
	if err != nil {
		fatal(err)
	}

	fmt.Printf("Go engine - game: %s | %s\n", spec.GameID, game.Describe())
	err = engine.RunAll(engine.RunnerConfig{
		Spec:           spec,
		LibraryDir:     *libraryDir,
		NumSims:        numSims,
		Modes:          modes,
		Workers:        *workers,
		BatchSize:      *batch,
		Compress:       *compress,
		WriteEventList: *writeEvents,
		Attach:         game.Attach,
		RunSpin:        game.RunSpin,
	})
	if err != nil {
		fatal(err)
	}
}

// parseSims accepts "100000" (applies to every mode) or "base=1000,bonus=500".
func parseSims(arg string, modes []string) (map[string]int, error) {
	out := map[string]int{}
	if !strings.Contains(arg, "=") {
		n, err := strconv.Atoi(strings.TrimSpace(arg))
		if err != nil {
			return nil, fmt.Errorf("invalid --sims value %q", arg)
		}
		for _, m := range modes {
			out[m] = n
		}
		return out, nil
	}
	for _, pair := range strings.Split(arg, ",") {
		kv := strings.SplitN(strings.TrimSpace(pair), "=", 2)
		if len(kv) != 2 {
			return nil, fmt.Errorf("invalid --sims entry %q", pair)
		}
		n, err := strconv.Atoi(kv[1])
		if err != nil {
			return nil, fmt.Errorf("invalid --sims count in %q", pair)
		}
		out[kv[0]] = n
	}
	for _, m := range modes {
		if _, ok := out[m]; !ok {
			return nil, fmt.Errorf("--sims does not define a count for mode %q", m)
		}
	}
	return out, nil
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "error:", err)
	os.Exit(1)
}

func runOptimize(args []string) {
	fs := flag.NewFlagSet("optimize", flag.ExitOnError)
	libraryDir := fs.String("library", "", "path to games/<game>/library")
	mode := fs.String("mode", "", "bet mode to optimize")
	paramsPath := fs.String("params", "", "JSON file with the mode's `parameters` block (game_optimization.py)")
	threads := fs.Int("threads", 0, "worker goroutines (default: number of CPUs)")
	seed := fs.Uint64("seed", 0, "random seed; same seed + threads = same result")
	fs.Parse(args)
	if *libraryDir == "" || *mode == "" || *paramsPath == "" {
		fmt.Fprintln(os.Stderr, "error: --library, --mode and --params are required")
		fs.Usage()
		os.Exit(2)
	}
	params, err := optimizer.LoadParams(*paramsPath)
	if err != nil {
		fatal(err)
	}
	err = optimizer.Run(optimizer.Config{LibraryDir: *libraryDir, Mode: *mode, Params: params,
		Threads: *threads, Seed: *seed})
	if err != nil {
		fatal(err)
	}
}
