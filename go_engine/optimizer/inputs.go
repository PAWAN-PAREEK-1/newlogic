// Package optimizer is a Go port of the Stake Engine Math SDK optimizer
// (optimization_program/src/main.rs, the "pig farm").
//
// It runs the same algorithm on the same inputs and writes the same files:
//
//	inputs:  <library>/configs/math_config.json   fences (criteria), dresses (scaling), bias
//	         <library>/lookup_tables/lookUpTable_<mode>.csv
//	         <library>/forces/force_record_<mode>.json
//	         the mode's `parameters` block from game_optimization.py (as JSON)
//	outputs: <library>/publish_files/lookUpTable_<mode>_0.csv
//	         <library>/optimization_files/<mode>_0_<n>.csv   (n = 1..10, best first)
//
// Every step mirrors a function of main.rs (named in the comments), so the
// results are the same as the Rust optimizer's - "same" in the statistical
// sense, since both are random searches. The hot loops use the faster,
// equivalence-tested formulations from the sped-up Rust code (bucketed
// gaussian mixture, alias sampling); see PERFORMANCE.md.
package optimizer

import (
	"bufio"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

// Params is the mode's `parameters` block (ConstructParameters in
// optimization_program/optimization_config.py).
type Params struct {
	NumShowPigs      int       `json:"num_show_pigs"`
	NumPigsPerFence  int       `json:"num_pigs_per_fence"`
	MinMeanToMedian  float64   `json:"min_mean_to_median"`
	MaxMeanToMedian  float64   `json:"max_mean_to_median"`
	PmbRTP           float64   `json:"pmb_rtp"`
	SimulationTrials int       `json:"simulation_trials"`
	TestSpins        []int     `json:"test_spins"`
	TestSpinsWeights []float64 `json:"test_spins_weights"`
	ScoreType        string    `json:"score_type"`
	MaxTrialDist     int       `json:"max_trial_dist"`
}

// LoadParams reads the parameters JSON written by run_script.py.
func LoadParams(path string) (Params, error) {
	var p Params
	data, err := os.ReadFile(path)
	if err != nil {
		return p, err
	}
	if err := json.Unmarshal(data, &p); err != nil {
		return p, fmt.Errorf("parse %s: %w", path, err)
	}
	if len(p.TestSpins) == 0 || len(p.TestSpins) != len(p.TestSpinsWeights) {
		return p, fmt.Errorf("parameters: test_spins and test_spins_weights must be non-empty and the same length")
	}
	if p.MaxTrialDist < 5 {
		return p, fmt.Errorf("parameters: max_trial_dist must be >= 5 (got %d)", p.MaxTrialDist)
	}
	return p, nil
}

// ---- math_config.json ------------------------------------------------------

type searchKey struct {
	Name  string `json:"name"`
	Value string `json:"value"`
}

type identityCondition struct {
	Search        []searchKey `json:"search"`
	Opposite      bool        `json:"opposite"`
	WinRangeStart float64     `json:"win_range_start"`
	WinRangeEnd   float64     `json:"win_range_end"`
}

type fenceJSON struct {
	Name              string            `json:"name"`
	HR                *string           `json:"hr"`
	RTP               *string           `json:"rtp"`
	AvgWin            *string           `json:"avg_win"`
	IdentityCondition identityCondition `json:"identity_condition"`
	MinMeanToMedian   *string           `json:"min_mean_to_median"`
	MaxMeanToMedian   *string           `json:"max_mean_to_median"`
}

type dressJSON struct {
	Fence       string      `json:"fence"`
	ScaleFactor string      `json:"scale_factor"`
	WinRange    *[2]float64 `json:"identity_condition_win_range"`
	Prob        *float64    `json:"prob"`
}

type biasJSON struct {
	Criteria string     `json:"criteria"`
	Range    [2]float64 `json:"range"`
	Prob     float64    `json:"prob"`
}

type mathConfig struct {
	BetModes []struct {
		BetMode string  `json:"bet_mode"`
		Cost    float64 `json:"cost"`
		RTP     float64 `json:"rtp"`
	} `json:"bet_modes"`
	Fences []struct {
		BetMode string      `json:"bet_mode"`
		Fences  []fenceJSON `json:"fences"`
	} `json:"fences"`
	Dresses []struct {
		BetMode string      `json:"bet_mode"`
		Dresses []dressJSON `json:"dresses"`
	} `json:"dresses"`
	Bias []struct {
		BetMode string     `json:"bet_mode"`
		Bias    []biasJSON `json:"bias"`
	} `json:"bias"`
}

// Dress is one scaling rule: multiply pig weights of wins in [Lo, Hi] by the
// scale factor, applied to a pig with probability Prob (main.rs: Dress).
type Dress struct {
	Lo, Hi float64
	Factor float64
	Random bool // "r" suffix: factor * U(0,1) per pig (ScaleFactor::FactorR)
	Prob   float64
}

// Bias steers a share of the random gaussian centres into a payout range.
type Bias struct {
	Lo, Hi, Prob float64
}

// Fence is one optimization criteria (main.rs: Fence / parse_fence_info).
type Fence struct {
	Name            string
	HR, RTP, AvgWin float64
	Search          []searchKey
	Opposite        bool
	WinRangeStart   float64
	WinRangeEnd     float64
	WinType         bool // fixed-payout fence (wincap, 0, ...)
	MinM2M, MaxM2M  float64
	Dresses         []Dress
	Bias            Bias

	// Books grouped by distinct payout. For regular fences Wins is sorted
	// ascending; WinBooks[i] are the book ids paying Wins[i].
	Wins     []float64
	WinBooks [][]uint32
}

func parseNum(s *string, def float64) (float64, error) {
	if s == nil {
		return def, nil
	}
	return strconv.ParseFloat(strings.TrimSpace(*s), 64)
}

func parseDress(d dressJSON) Dress {
	out := Dress{Factor: 1, Prob: 1}
	if d.WinRange != nil {
		out.Lo, out.Hi = d.WinRange[0], d.WinRange[1]
	}
	if d.Prob != nil {
		out.Prob = *d.Prob
	}
	text := strings.TrimSpace(d.ScaleFactor)
	if strings.HasSuffix(text, "r") {
		if f, err := strconv.ParseFloat(strings.TrimSuffix(text, "r"), 64); err == nil {
			out.Factor, out.Random = f, true
			return out
		}
	}
	if f, err := strconv.ParseFloat(text, 64); err == nil {
		out.Factor = f
	}
	return out
}

// loadFences resolves the mode's fences exactly like run_farm + parse_fence_info.
func loadFences(libraryDir, mode string) (fences []*Fence, cost, modeRTP float64, err error) {
	data, err := os.ReadFile(filepath.Join(libraryDir, "configs", "math_config.json"))
	if err != nil {
		return nil, 0, 0, err
	}
	var mc mathConfig
	if err := json.Unmarshal(data, &mc); err != nil {
		return nil, 0, 0, fmt.Errorf("parse math_config.json: %w", err)
	}
	found := false
	for _, bm := range mc.BetModes {
		if bm.BetMode == mode {
			cost, modeRTP, found = bm.Cost, bm.RTP, true
		}
	}
	if !found {
		return nil, 0, 0, fmt.Errorf("betmode %q not found in math_config.json", mode)
	}
	var fenceList []fenceJSON
	var dressList []dressJSON
	var biasList []biasJSON
	for _, f := range mc.Fences {
		if f.BetMode == mode {
			fenceList = f.Fences
		}
	}
	for _, d := range mc.Dresses {
		if d.BetMode == mode {
			dressList = d.Dresses
		}
	}
	for _, b := range mc.Bias {
		if b.BetMode == mode {
			biasList = b.Bias
		}
	}

	totalProb := 0.0
	for _, fj := range fenceList {
		avgWin, e1 := parseNum(fj.AvgWin, -1)
		rtp, e2 := parseNum(fj.RTP, -1)
		if e1 != nil || e2 != nil {
			return nil, 0, 0, fmt.Errorf("fence %q: bad avg_win/rtp", fj.Name)
		}
		hrStr := "-1"
		if fj.HR != nil {
			hrStr = strings.TrimSpace(*fj.HR)
		}
		hr := -1.0
		if hrStr != "x" {
			if hr, err = strconv.ParseFloat(hrStr, 64); err != nil {
				return nil, 0, 0, fmt.Errorf("fence %q: bad hr %q", fj.Name, hrStr)
			}
		}
		if hrStr != "x" && hr > 0 && rtp > 0 {
			avgWin = hr * rtp
		}
		if hrStr != "x" && hr > 0 && avgWin > 0 {
			rtp = avgWin / hr
		}
		if hrStr != "x" && hr < 0 && rtp > 0 && avgWin > 0 {
			hr = avgWin / rtp / cost
		}
		if hr > 0 {
			totalProb += 1 / hr
		}
		minM2M, _ := parseNum(fj.MinMeanToMedian, 0)
		maxM2M, _ := parseNum(fj.MaxMeanToMedian, 10)
		ic := fj.IdentityCondition
		f := &Fence{
			Name: fj.Name, HR: hr, RTP: rtp, AvgWin: avgWin,
			Search: ic.Search, Opposite: ic.Opposite,
			WinRangeStart: ic.WinRangeStart, WinRangeEnd: ic.WinRangeEnd,
			WinType: ic.WinRangeStart > -1 && ic.WinRangeEnd == ic.WinRangeStart,
			MinM2M:  minM2M, MaxM2M: maxM2M,
		}
		for _, d := range dressList {
			if d.Fence == f.Name {
				f.Dresses = append(f.Dresses, parseDress(d))
			}
		}
		for _, b := range biasList {
			if b.Criteria == f.Name {
				f.Bias = Bias{Lo: b.Range[0], Hi: b.Range[1], Prob: b.Prob}
				break
			}
		}
		fences = append(fences, f)
	}
	for _, f := range fences {
		if f.HR == -1 {
			f.HR = 1 / (1 - totalProb)
			f.AvgWin = f.HR * f.RTP
		}
	}
	return fences, cost, modeRTP, nil
}

// ---- lookup table and force file -------------------------------------------

// Book is one lookup-table row (main.rs: LookUpTableEntry).
type Book struct {
	ID     uint32
	Weight uint64
	Cents  uint64
}

func (b Book) Win() float64 { return float64(b.Cents) / 100 }

func loadLookupTable(libraryDir, mode string) ([]Book, error) {
	path := filepath.Join(libraryDir, "lookup_tables", fmt.Sprintf("lookUpTable_%s.csv", mode))
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	var books []Book
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1<<20), 1<<20)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" {
			continue
		}
		parts := strings.Split(line, ",")
		if len(parts) != 3 {
			return nil, fmt.Errorf("%s: malformed line %q", path, line)
		}
		id, e1 := strconv.ParseUint(strings.TrimSpace(parts[0]), 10, 32)
		w, e2 := strconv.ParseUint(strings.TrimSpace(parts[1]), 10, 64)
		c, e3 := strconv.ParseUint(strings.TrimSpace(parts[2]), 10, 64)
		if e1 != nil || e2 != nil || e3 != nil {
			return nil, fmt.Errorf("%s: malformed line %q", path, line)
		}
		books = append(books, Book{ID: uint32(id), Weight: w, Cents: c})
	}
	return books, sc.Err()
}

type forceOption struct {
	Search  []searchKey `json:"search"`
	BookIDs []uint32    `json:"bookIds"`
}

func loadForces(libraryDir, mode string) ([]forceOption, error) {
	f, err := os.Open(filepath.Join(libraryDir, "forces", fmt.Sprintf("force_record_%s.json", mode)))
	if err != nil {
		return nil, err
	}
	defer f.Close()
	var out []forceOption
	if err := json.NewDecoder(bufio.NewReaderSize(f, 1<<20)).Decode(&out); err != nil {
		return nil, fmt.Errorf("parse force file: %w", err)
	}
	return out, nil
}

// assignBooks gives every fence its books, in fence order, with the rules of
// main.rs sort_wins_by_parameter (a book belongs to the first fence that takes it).
func assignBooks(fences []*Fence, books []Book, forces []forceOption) error {
	pos := make(map[uint32]int, len(books))
	for i, b := range books {
		pos[b.ID] = i
	}
	remaining := make([]bool, len(books))
	for i := range remaining {
		remaining[i] = true
	}

	for _, f := range fences {
		var members []int
		switch {
		case f.WinType:
			found := false
			for i, b := range books {
				if math.Abs(b.Win()-f.AvgWin) < 1e-9 {
					found = true
				}
				if !remaining[i] {
					continue
				}
				if (b.Win() == f.WinRangeStart) != f.Opposite {
					members = append(members, i)
				}
			}
			if !found {
				return fmt.Errorf("fence.avg_win %v not found in lookup table", f.AvgWin)
			}
		case len(f.Search) == 0 && f.WinRangeStart == -1 && !f.Opposite:
			for i := range books { // catch-all: every remaining book
				if remaining[i] {
					members = append(members, i)
				}
			}
		case len(f.Search) == 0 && !f.Opposite && f.WinRangeStart > -1 && f.WinRangeEnd > f.WinRangeStart:
			// payout-range fence: remaining books with start < win <= end (main.rs rule)
			for i, b := range books {
				if remaining[i] && b.Win() > f.WinRangeStart && b.Win() <= f.WinRangeEnd {
					members = append(members, i)
				}
			}
		default:
			taken := make([]bool, len(books))
			for _, opt := range forces {
				ok := true
				for _, key := range f.Search {
					if key.Value == "None" {
						continue
					}
					hit := false
					for _, s := range opt.Search {
						if s.Name == key.Name && s.Value == key.Value {
							hit = true
							break
						}
					}
					if !hit {
						ok = false
						break
					}
				}
				if f.Opposite {
					ok = !ok
				}
				if !ok {
					continue
				}
				for _, id := range opt.BookIDs {
					if i, exists := pos[id]; exists && remaining[i] && !taken[i] {
						taken[i] = true
						members = append(members, i)
					}
				}
			}
		}
		if len(members) == 0 {
			return fmt.Errorf("optimizer fence '%s' matched 0 books after prior fences were assigned "+
				"(search=%v, payout range %v..%v, opposite=%v). Fence identity conditions must be "+
				"populated and mutually exclusive", f.Name, f.Search, f.WinRangeStart, f.WinRangeEnd, f.Opposite)
		}
		groupBooks(f, books, members)
		for _, i := range members {
			remaining[i] = false
		}
	}
	return nil
}

// groupBooks fills f.Wins (sorted distinct payouts) and f.WinBooks.
func groupBooks(f *Fence, books []Book, members []int) {
	byCents := map[uint64][]uint32{}
	for _, i := range members {
		byCents[books[i].Cents] = append(byCents[books[i].Cents], books[i].ID)
	}
	cents := make([]uint64, 0, len(byCents))
	for c := range byCents {
		cents = append(cents, c)
	}
	sort.Slice(cents, func(a, b int) bool { return cents[a] < cents[b] })
	f.Wins = make([]float64, len(cents))
	f.WinBooks = make([][]uint32, len(cents))
	for k, c := range cents {
		f.Wins[k] = float64(c) / 100
		f.WinBooks[k] = byCents[c]
	}
}
