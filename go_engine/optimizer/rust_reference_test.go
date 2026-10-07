package optimizer

import (
	"compress/gzip"
	"encoding/json"
	"math"
	"math/rand/v2"
	"os"
	"testing"
)

// testdata/rust_reference.json.gz is produced by the ORIGINAL Rust optimizer
// code (optimization_program: `cargo test --release export_go_vectors -- --ignored`):
// random pigs, the random rows Rust generated for them, and the weights the
// original get_weights returned; plus a score from the original run_simulation.

type rustReference struct {
	WeightCases []struct {
		Wins              []float64   `json:"wins"`
		Amps              []float64   `json:"amps"`
		Mus               []float64   `json:"mus"`
		Stds              []float64   `json:"stds"`
		Params            []float64   `json:"params"`
		ApplyParms        [][]uint16  `json:"apply_parms"`
		RandomApplyParams [][]int     `json:"random_apply_params"`
		Rows              [][]float64 `json:"rows"`
		Weights           []float64   `json:"weights"`
	} `json:"weight_cases"`
	ScoreCase struct {
		Wins        []float64 `json:"wins"`
		Weights     []float64 `json:"weights"`
		Trials      int       `json:"trials"`
		TestSpins   []int     `json:"test_spins"`
		TestWeights []float64 `json:"test_weights"`
		PmbRTPs     []float64 `json:"pmb_rtps"`
		Scores      []float64 `json:"scores"`
	} `json:"score_case"`
}

func loadRustReference(t *testing.T) rustReference {
	t.Helper()
	f, err := os.Open("testdata/rust_reference.json.gz")
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	gz, err := gzip.NewReader(f)
	if err != nil {
		t.Fatal(err)
	}
	var ref rustReference
	if err := json.NewDecoder(gz).Decode(&ref); err != nil {
		t.Fatal(err)
	}
	return ref
}

// The Go gaussian-mixture weights must equal the original Rust get_weights.
func TestWeightsMatchOriginalRust(t *testing.T) {
	ref := loadRustReference(t)
	if len(ref.WeightCases) == 0 {
		t.Fatal("no reference cases")
	}
	s := &weightScratch{}
	worst := 0.0
	for c, tc := range ref.WeightCases {
		randRows := make([][]int, len(tc.Amps))
		for k := range tc.Amps {
			for r, group := range tc.RandomApplyParams {
				for _, member := range group {
					if member == k {
						randRows[k] = append(randRows[k], r)
						break
					}
				}
			}
		}
		out := make([]float64, len(tc.Wins))
		mixtureWeights(tc.Wins, tc.Amps, tc.Mus, tc.Stds, tc.Params, tc.ApplyParms, randRows, tc.Rows, out, s)
		for i := range out {
			rel := math.Abs(out[i]-tc.Weights[i]) / math.Max(math.Abs(tc.Weights[i]), 1e-300)
			worst = math.Max(worst, rel)
			if rel > 1e-9 {
				t.Fatalf("case %d win %d (%v): go=%v rust=%v rel_err=%v", c, i, tc.Wins[i], out[i], tc.Weights[i], rel)
			}
		}
	}
	t.Logf("%d pigs, worst relative error vs original Rust: %.2e", len(ref.WeightCases), worst)
}

// The Go session score must match the original Rust run_simulation within
// Monte-Carlo error (both use 200,000 sessions).
func TestScoreMatchesOriginalRust(t *testing.T) {
	sc := loadRustReference(t).ScoreCase
	spins := sc.TestSpins[len(sc.TestSpins)-1]
	for i, pmb := range sc.PmbRTPs {
		got, err := runSimulation(sc.Wins, sc.Weights, spins, sc.Trials, 1, sc.TestSpins, sc.TestWeights,
			pmb, rand.NewPCG(7, uint64(i)), make([]float64, spins+1))
		if err != nil {
			t.Fatal(err)
		}
		if math.Abs(got-sc.Scores[i]) > 0.01 {
			t.Fatalf("pmb %v: score go=%v rust=%v", pmb, got, sc.Scores[i])
		}
		t.Logf("pmb_rtp %4v: score go=%.5f original rust=%.5f", pmb, got, sc.Scores[i])
	}
}

// The packed alias sampler must draw each win with probability weight/sum.
func TestSamplerFrequencies(t *testing.T) {
	wins := []float64{0, 1, 2, 3, 4}
	weights := []float64{0.5, 0.25, 0.125, 0.0625, 0.0625}
	s, err := newWinSampler(wins, weights)
	if err != nil {
		t.Fatal(err)
	}
	src := rand.NewPCG(3, 5)
	counts := make([]float64, len(wins))
	const n = 4_000_000
	for i := 0; i < n; i++ {
		counts[int(s.draw(src))]++
	}
	for i := range wins {
		if math.Abs(counts[i]/n-weights[i]) > 0.002 {
			t.Fatalf("win %v: frequency %v, want %v", wins[i], counts[i]/n, weights[i])
		}
	}
}

// Breeding must hit the target average win exactly.
func TestBreedHitsTarget(t *testing.T) {
	ref := loadRustReference(t)
	wins := ref.WeightCases[len(ref.WeightCases)-1].Wins
	r := rand.New(rand.NewPCG(1, 1))
	h := &pigHeaven{wins: wins, numPigs: 16, maxWin: wins[len(wins)-1], minWin: wins[0],
		avgWin:  wins[len(wins)/3],
		dresses: []Dress{{Lo: wins[0], Hi: wins[len(wins)/3], Factor: 50, Prob: 1}}}
	pigs, err := createAncestors(h, 0, 10, Bias{}, 20, r, func(string, ...any) {})
	if err != nil {
		t.Fatal(err)
	}
	s := &weightScratch{}
	w := make([]float64, len(wins))
	for _, pig := range pigs {
		pigWeights(wins, &pig, w, s)
		sum, mean := 0.0, 0.0
		for i := range w {
			sum += w[i]
			mean += w[i] * wins[i]
		}
		if math.Abs(mean/sum-h.avgWin)/h.avgWin > 1e-9 {
			t.Fatalf("bred pig mean %v, target %v", mean/sum, h.avgWin)
		}
	}
}
