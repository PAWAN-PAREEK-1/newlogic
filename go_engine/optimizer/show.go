package optimizer

import (
	"errors"
	"math"
	"math/bits"
	"math/rand/v2"
)

// aliasTable samples index i with probability w[i]/sum(w) in O(1)
// (Vose's alias method; same role as rand_distr::WeightedAliasIndex).
type aliasTable struct {
	prob  []float64
	alias []int32
}

func newAliasTable(w []float64) (*aliasTable, error) {
	n := len(w)
	sum := 0.0
	for _, x := range w {
		if x < 0 || math.IsNaN(x) || math.IsInf(x, 0) {
			return nil, errors.New("invalid weights")
		}
		sum += x
	}
	if n == 0 || sum <= 0 || math.IsInf(sum, 0) {
		return nil, errors.New("invalid weights")
	}
	t := &aliasTable{prob: make([]float64, n), alias: make([]int32, n)}
	scaled := make([]float64, n)
	small := make([]int32, 0, n)
	large := make([]int32, 0, n)
	for i, x := range w {
		scaled[i] = x * float64(n) / sum
		if scaled[i] < 1 {
			small = append(small, int32(i))
		} else {
			large = append(large, int32(i))
		}
	}
	for len(small) > 0 && len(large) > 0 {
		s := small[len(small)-1]
		small = small[:len(small)-1]
		l := large[len(large)-1]
		t.prob[s] = scaled[s]
		t.alias[s] = l
		scaled[l] = scaled[l] + scaled[s] - 1
		if scaled[l] < 1 {
			large = large[:len(large)-1]
			small = append(small, l)
		}
	}
	for _, i := range large {
		t.prob[i] = 1
		t.alias[i] = i
	}
	for _, i := range small { // only reachable through rounding
		t.prob[i] = 1
		t.alias[i] = i
	}
	return t, nil
}

// winSampler draws win values with probability weight/sum(weights) using one
// 64-bit random number and one memory access per draw: the high part of
// u*n picks the alias slot, the low part is the slot's coin flip.
type winSampler struct {
	entries []samplerEntry
	n       uint64
}

type samplerEntry struct {
	threshold     uint64 // P(keep own win) * 2^64
	win, aliasWin float64
}

func newWinSampler(wins, weights []float64) (*winSampler, error) {
	t, err := newAliasTable(weights)
	if err != nil {
		return nil, err
	}
	s := &winSampler{entries: make([]samplerEntry, len(wins)), n: uint64(len(wins))}
	for i := range wins {
		th := uint64(math.MaxUint64)
		if t.prob[i] < 1 {
			th = uint64(t.prob[i] * 18446744073709551616.0)
		}
		s.entries[i] = samplerEntry{threshold: th, win: wins[i], aliasWin: wins[t.alias[i]]}
	}
	return s, nil
}

func (s *winSampler) draw(src *rand.PCG) float64 {
	slot, frac := bits.Mul64(src.Uint64(), s.n)
	e := &s.entries[slot]
	if frac < e.threshold {
		return e.win
	}
	return e.aliasWin
}

// runSimulation scores a full distribution: the weighted share of `trials`
// sessions whose total win over test_spins[i] spins reaches
// pmb_rtp * test_spins[i] * bet (main.rs: run_simulation).
func runSimulation(wins, weights []float64, spins, trials int, bet float64, testSpins []int,
	testWeights []float64, pmbRTP float64, src *rand.PCG, bank []float64) (float64, error) {

	sampler, err := newWinSampler(wins, weights)
	if err != nil {
		return 0, err
	}
	success := make([]float64, len(testSpins))
	for t := 0; t < trials; t++ {
		total := 0.0
		for s := 0; s < spins; s++ {
			total += sampler.draw(src)
			bank[s+1] = total
		}
		for i, n := range testSpins {
			if bank[n]/(float64(n)*bet) >= pmbRTP {
				success[i]++
			}
		}
	}
	score := 0.0
	for i := range success {
		score += success[i] / float64(trials) * testWeights[i]
	}
	return score, nil
}

// showPig is one scored combination: a pig index per regular fence.
type showPig struct {
	pigIndexes []int
	score      float64
}

// scoringContext is everything needed to turn pig choices into a full
// distribution over all payouts of the mode.
type scoringContext struct {
	fences      []*Fence
	regular     []*Fence // non-fixed fences, in fence order
	pens        [][]Pig  // pig pen per regular fence
	sortedWins  []float64
	fixedIndex  []int   // sortedWins index of each fixed fence's payout (-1 if none)
	globalIndex [][]int // per regular fence: sortedWins index of each fence win
}

// combine writes the distribution of a pig choice into weights (and each regular
// fence's pig weights into fenceWeights) - main.rs: the loop shared by
// create_show_pigs and recreate_show_pig.
func (c *scoringContext) combine(choice []int, weights []float64, fenceWeights [][]float64, s *weightScratch) {
	for i := range weights {
		weights[i] = 0
	}
	regular := 0
	for fi, f := range c.fences {
		if f.WinType {
			if c.fixedIndex[fi] >= 0 {
				weights[c.fixedIndex[fi]] += 1 / f.HR
			}
			continue
		}
		fw := fenceWeights[regular]
		pigWeights(f.Wins, &c.pens[regular][choice[regular]], fw, s)
		for n, w := range fw {
			if g := c.globalIndex[regular][n]; g >= 0 {
				weights[g] += w / f.HR
			}
		}
		regular++
	}
}

// createShowPigs is one worker of the show-pig search (main.rs: create_show_pigs):
// random pig choices per fence, scored; keeps every choice that ties or beats
// the worker's best so far.
func (c *scoringContext) createShowPigs(numPigs int, p Params, bet float64, src *rand.PCG) ([]showPig, error) {
	r := rand.New(src)
	s := &weightScratch{}
	weights := make([]float64, len(c.sortedWins))
	fenceWeights := make([][]float64, len(c.regular))
	for k, f := range c.regular {
		fenceWeights[k] = make([]float64, len(f.Wins))
	}
	spins := 0 // sessions run to the longest test length
	for _, n := range p.TestSpins {
		spins = max(spins, n)
	}
	bank := make([]float64, spins+1)
	var out []showPig
	best := 0.0
	for n := 0; n < numPigs; n++ {
		choice := make([]int, len(c.regular))
		for k := range c.regular {
			choice[k] = r.IntN(len(c.pens[k]))
		}
		c.combine(choice, weights, fenceWeights, s)
		score, err := runSimulation(c.sortedWins, weights, spins, p.SimulationTrials, bet,
			p.TestSpins, p.TestSpinsWeights, p.PmbRTP, src, bank)
		if err != nil {
			return nil, err
		}
		if score != 0 && score >= best {
			best = score
			out = append(out, showPig{pigIndexes: choice, score: score})
		}
	}
	return out, nil
}
