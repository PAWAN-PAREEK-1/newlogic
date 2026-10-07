package optimizer

import (
	"math"
	"math/rand/v2"
	"sort"
)

// lnBase: the SDK's bell curves use base 2.71 (not e): 2.71^x == exp(x * ln 2.71).
var lnBase = math.Log(2.71)

// fillRandomWeights fills rows[r][i] = 1 + U{-100..100}/100 * randomWeights[r],
// one deterministic stream per pig seed (main.rs: the random_weights_to_apply
// loop). The same seed always gives the same row, so a pig reproduces exactly.
func fillRandomWeights(numWins int, seeds []uint32, randomWeights []float64, rows [][]float64) [][]float64 {
	for r := range seeds {
		if len(rows) <= r {
			rows = append(rows, make([]float64, numWins))
		}
		if len(rows[r]) < numWins {
			rows[r] = make([]float64, numWins)
		}
		rng := rand.New(rand.NewPCG(uint64(seeds[r]), 0x9E3779B97F4A7C15))
		row := rows[r]
		for i := 0; i < numWins; i++ {
			row[i] = 1 + float64(rng.IntN(201)-100)/100*randomWeights[r]
		}
	}
	return rows
}

type normBucket struct {
	params   []int
	randRows []int
	ampSum   float64
	bump     []float64
}

// weightScratch holds reusable buffers so the hot loop does not allocate.
type weightScratch struct {
	buckets  []normBucket
	bumps    [][]float64
	rows     [][]float64
	randRows [][]int
}

func (s *weightScratch) bumpBuffer(k, n int) []float64 {
	for len(s.bumps) <= k {
		s.bumps = append(s.bumps, nil)
	}
	if cap(s.bumps[k]) < n {
		s.bumps[k] = make([]float64, n)
	}
	b := s.bumps[k][:n]
	for i := range b {
		b[i] = 0
	}
	return b
}

func containsU16(sorted []uint16, v uint16) bool {
	i := sort.Search(len(sorted), func(i int) bool { return sorted[i] >= v })
	return i < len(sorted) && sorted[i] == v
}

func sameInts(a, b []int) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

// mixtureWeights writes the weight of every win under a pig's gaussian mixture:
//
//	w(win) = sum_k amp_k * (1 + 20000/sqrt(std_k*6.28) * 2.71^(-0.5*((win-mu_k)/std_k)^2))
//	              * prod(scale_p   for params p applied to k with lo_p <= win <= hi_p)
//	              * prod(rows[r][i] for random rows r applied to k)
//
// (main.rs: get_weights / mixture_weights). Gaussians with identical
// multipliers are bucketed and each bump is only evaluated where it can still
// change the float result, exactly like the equivalence-tested Rust version.
func mixtureWeights(wins, amps, mus, stds, params []float64, applyParms [][]uint16,
	randRowsOfNorm [][]int, rows [][]float64, out []float64, s *weightScratch) {

	numWins := len(wins)
	numParams := len(params) / 3
	s.buckets = s.buckets[:0]
	bucketOf := make([]int, len(amps))
	for k := range amps {
		var normParams []int
		for p := 0; p < numParams && p < len(applyParms); p++ {
			if containsU16(applyParms[p], uint16(k)) {
				normParams = append(normParams, p)
			}
		}
		rr := randRowsOfNorm[k]
		b := -1
		for i := range s.buckets {
			if sameInts(s.buckets[i].params, normParams) && sameInts(s.buckets[i].randRows, rr) {
				b = i
				break
			}
		}
		if b < 0 {
			b = len(s.buckets)
			s.buckets = append(s.buckets, normBucket{params: normParams, randRows: rr,
				bump: s.bumpBuffer(b, numWins)})
		}
		s.buckets[b].ampSum += amps[k]
		bucketOf[k] = b
	}

	sorted := true
	for i := 1; i < numWins; i++ {
		if wins[i-1] > wins[i] {
			sorted = false
			break
		}
	}
	for k := range amps {
		mu, std := mus[k], stds[k]
		coef := 20000 * (1 / math.Sqrt(std*(2*3.14)))
		ampCoef := amps[k] * coef
		lo, hi := 0, numWins
		threshold := math.Log(coef) + 42
		halfWidth := math.Sqrt(2*threshold/lnBase) * std
		if sorted && !math.IsNaN(halfWidth) && !math.IsInf(halfWidth, 0) {
			if threshold <= 0 {
				lo, hi = 0, 0
			} else {
				lo = sort.SearchFloat64s(wins, mu-halfWidth)                                  // first w >= mu-hw
				hi = sort.Search(numWins, func(i int) bool { return wins[i] > mu+halfWidth }) // first w > mu+hw
			}
		}
		bump := s.buckets[bucketOf[k]].bump
		for i := lo; i < hi; i++ {
			z := (wins[i] - mu) / std
			bump[i] += ampCoef * math.Exp(-0.5*z*z*lnBase)
		}
	}

	for i := 0; i < numWins; i++ {
		win := wins[i]
		total := 0.0
		for bi := range s.buckets {
			b := &s.buckets[bi]
			w := b.ampSum + b.bump[i]
			for _, p := range b.params {
				if win >= params[3*p] && win <= params[3*p+1] {
					w *= params[3*p+2]
				}
			}
			for _, r := range b.randRows {
				w *= rows[r][i]
			}
			total += w
		}
		out[i] = total
	}
}

// pigWeights: weights of a bred pig (main.rs: get_weights).
func pigWeights(wins []float64, pig *Pig, out []float64, s *weightScratch) {
	s.rows = fillRandomWeights(len(wins), pig.RandomSeeds, pig.RandomWeights, s.rows)
	for len(s.randRows) < len(pig.Amps) {
		s.randRows = append(s.randRows, nil)
	}
	randRows := s.randRows[:len(pig.Amps)]
	for k := range pig.Amps {
		randRows[k] = randRows[k][:0]
		for r, group := range pig.RandomApplyParams {
			for _, member := range group {
				if member == k {
					randRows[k] = append(randRows[k], r)
					break
				}
			}
		}
	}
	mixtureWeights(wins, pig.Amps, pig.Mus, pig.Stds, pig.Params, pig.ApplyParms, randRows, s.rows, out, s)
}

// freshPigRTP: average win and total weight of a fresh pig, whose random row 0
// applies to every gaussian (main.rs: get_weights_no_weight_array).
func freshPigRTP(wins []float64, pig *Pig, s *weightScratch, out []float64) (rtp, sumDist float64) {
	s.rows = fillRandomWeights(len(wins), pig.RandomSeeds, pig.RandomWeights, s.rows)
	for len(s.randRows) < len(pig.Amps) {
		s.randRows = append(s.randRows, nil)
	}
	randRows := s.randRows[:len(pig.Amps)]
	for k := range randRows {
		randRows[k] = append(randRows[k][:0], 0)
	}
	mixtureWeights(wins, pig.Amps, pig.Mus, pig.Stds, pig.Params, pig.ApplyParms, randRows, s.rows, out, s)
	totalWin := 0.0
	for i, w := range out {
		sumDist += w
		totalWin += w * wins[i]
	}
	return totalWin / sumDist, sumDist
}
