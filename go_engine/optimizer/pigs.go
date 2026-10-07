package optimizer

import (
	"fmt"
	"math"
	"math/rand/v2"
)

// Pig is one candidate payout distribution for a fence: a mixture of random
// gaussians over the payout values, scaled by dresses (main.rs: Pig).
type Pig struct {
	Amps, Mus, Stds   []float64
	Params            []float64  // dress triples (lo, hi, scale)
	ApplyParms        [][]uint16 // gaussians each dress triple applies to
	RTP, SumDist      float64    // average win and total weight
	RandomSeeds       []uint32
	RandomWeights     []float64
	RandomApplyParams [][]int // gaussians each random row applies to
}

// pigHeaven is the fence context for pig creation (main.rs: PigHeaven).
type pigHeaven struct {
	wins           []float64 // sorted distinct payouts of the fence
	dresses        []Dress
	numPigs        int // per worker
	maxWin, minWin float64
	avgWin         float64 // target average payout of the fence
}

// ancestorAttemptFactor caps the random-pig search at numPigs * factor attempts
// before giving up on a fence. main.rs uses 100, which fails hard-to-reach but
// reachable targets (expwilds ante basegame at 100k books stopped at 34 of 41
// pigs above the target). A successful search keeps the same pigs either way;
// a larger cap only turns some of those failures into successes.
const ancestorAttemptFactor = 1000

func intIn(r *rand.Rand, lo, hi int) int { return lo + r.IntN(hi-lo+1) } // gen_range(lo..=hi)

func floatIn(r *rand.Rand, lo, hi float64) float64 { // gen_range(lo..=hi) for floats
	if hi <= lo {
		return lo
	}
	return lo + r.Float64()*(hi-lo)
}

func rangeU16(from, to int) []uint16 {
	out := make([]uint16, 0, to-from)
	for i := from; i < to; i++ {
		out = append(out, uint16(i))
	}
	return out
}

func rangeInt(from, to int) []int {
	out := make([]int, 0, to-from)
	for i := from; i < to; i++ {
		out = append(out, i)
	}
	return out
}

func dressScale(r *rand.Rand, d Dress) float64 {
	if d.Random {
		return d.Factor * r.Float64()
	}
	return d.Factor
}

// createAncestors builds one worker's share of a fence's pig pen
// (main.rs: create_ancestors): random pigs until it has sqrt(numPigs) pigs whose
// average win is above the target and as many below, then breeds pos x neg
// pairs that hit the target exactly and pass the mean/median filter.
func createAncestors(h *pigHeaven, minM2M, maxM2M float64, bias Bias, maxTrialDist int,
	r *rand.Rand, log func(string, ...any)) ([]Pig, error) {

	need := math.Sqrt(float64(h.numPigs))
	var pos, neg []Pig
	var extra []Dress
	goBackDown := false
	stdWeight := 70.0
	addedExtra := false
	printed := false
	maxLoop := h.numPigs * ancestorAttemptFactor
	s := &weightScratch{}
	work := make([]float64, len(h.wins))
	step := 1 / math.Pow(float64(h.numPigs), 0.9)

	for loop := 1; float64(len(pos)) < need || float64(len(neg)) < need; loop++ {
		if loop > maxLoop {
			return nil, fmt.Errorf("create_ancestors failed to converge after %d iterations. pos_pigs=%d/%d, "+
				"neg_pigs=%d/%d. Target avg_win=%.4f, fence RTP may be unreachable from sim distribution",
				maxLoop, len(pos), int(need), len(neg), int(need), h.avgWin)
		}
		if !goBackDown {
			stdWeight = math.Min(stdWeight*(1+step), 400)
		} else {
			stdWeight = math.Min(stdWeight*(1-step), 400)
		}
		if math.Abs(stdWeight-400) < 0.00001 {
			goBackDown = true
		}
		stdWeight = math.Max(stdWeight, 20)
		if math.Abs(stdWeight-20) < 0.00001 {
			goBackDown = false
		}

		variables := intIn(r, 5, maxTrialDist)
		amps := make([]float64, 0, variables)
		mus := make([]float64, 0, variables)
		stds := make([]float64, 0, variables)
		if loop%2 == 0 {
			for i := 0; i < variables; i++ {
				amps = append(amps, float64(intIn(r, 1, 14)))
				v := r.Float64()
				if bias.Prob > 0 && v <= bias.Prob {
					mus = append(mus, floatIn(r, bias.Lo, bias.Hi))
				} else {
					// main.rs: `v % 2.0 == 0.0` is only true for v == 0
					cond := 0.0
					if math.Mod(v, 2) == 0 {
						cond = 1
					}
					mus = append(mus, h.avgWin*((v*0.25+1)*cond+(1-v*0.25)*(1-cond))*
						(float64(intIn(r, 5, 15))/10))
				}
				stds = append(stds, r.Float64()*30*r.Float64()*stdWeight)
			}
		} else {
			for i := 0; i < variables; i++ {
				v := r.Float64()
				v2 := r.Float64()
				if bias.Prob > 0 && v <= bias.Prob {
					mus = append(mus, floatIn(r, bias.Lo, bias.Hi))
				} else {
					mus = append(mus, math.Max(v*h.avgWin+0.01*v2*h.maxWin, h.minWin))
				}
				stds = append(stds, r.Float64()*stdWeight)
				amps = append(amps, r.Float64())
			}
		}

		var params []float64
		var apply [][]uint16
		for _, d := range h.dresses {
			if r.Float64() < d.Prob {
				params = append(params, d.Lo, d.Hi, dressScale(r, d))
				apply = append(apply, rangeU16(0, len(mus)))
			}
		}
		for _, d := range extra {
			params = append(params, d.Lo, d.Hi, dressScale(r, d))
			apply = append(apply, rangeU16(0, len(mus)))
		}

		pig := Pig{Amps: amps, Mus: mus, Stds: stds, Params: params, ApplyParms: apply,
			RandomSeeds:   []uint32{uint32(intIn(r, 0, 1000000000))},
			RandomWeights: []float64{r.Float64()}}
		pig.RTP, pig.SumDist = freshPigRTP(h.wins, &pig, s, work)

		if pig.RTP > h.avgWin && float64(len(pos)) < need {
			pos = append(pos, pig)
		} else if pig.RTP < h.avgWin && float64(len(neg)) < need {
			neg = append(neg, pig)
		}

		if float64(len(pos)) >= need && !addedExtra {
			addedExtra = true
			extra = append(extra,
				Dress{Lo: h.minWin, Hi: h.avgWin / 2, Factor: 150, Prob: 1},
				Dress{Lo: h.avgWin / 2, Hi: h.maxWin, Factor: 0.0001, Prob: 1})
		}
		if float64(len(neg)) >= need && !addedExtra {
			addedExtra = true
			extra = append(extra,
				Dress{Lo: h.avgWin * 2, Hi: h.maxWin, Factor: 50, Prob: 1},
				Dress{Lo: h.minWin, Hi: h.avgWin, Factor: 0.0001, Prob: 1})
		}
		if loop%(100*h.numPigs) == 0 {
			log("  still searching (attempt %d of max %d): above target %d/%d, below target %d/%d",
				loop, maxLoop, len(pos), int(math.Ceil(need)), len(neg), int(math.Ceil(need)))
		}
		if loop > 5*h.numPigs && !printed {
			printed = true
			if len(neg) > len(pos) {
				log("RTP too low...")
			} else {
				log("RTP too high...")
			}
		}
	}

	// Breed: every accepted child is a pos/neg blend that hits the target exactly.
	var out []Pig
	weights := make([]float64, len(h.wins))
	const maxAttempts = 2_000_000 // main.rs has no cap; this only turns a hang into an error
	for count := 0; count < len(pos)*len(neg); count++ {
		for attempt := 1; ; attempt++ {
			if attempt > maxAttempts {
				return nil, fmt.Errorf("no bred distribution satisfied mean/median %v..%v after %d attempts "+
					"(target avg win %.4f)", minM2M, maxM2M, maxAttempts, h.avgWin)
			}
			p := &pos[r.IntN(len(pos))]
			n := &neg[r.IntN(len(neg))]
			child := breedPigs(p, n, h.avgWin)
			pigWeights(h.wins, &child, weights, s)
			cum, median := 0.0, 0.0
			for i, w := range weights {
				cum += w
				if cum >= 0.5 {
					median = h.wins[i]
					break
				}
			}
			ok := !(median > 0 && (h.avgWin/median <= minM2M || h.avgWin/median >= maxM2M))
			if attempt%500 == 0 {
				log("Mean to Median %v %v %v", h.avgWin/median, minM2M, maxM2M)
			}
			if ok {
				out = append(out, child)
				break
			}
		}
	}
	return out, nil
}

// breedPigs blends a pig above the target with one below it so the child's
// average win is exactly the target (main.rs: breed_pigs + combine_distributions).
func breedPigs(pos, neg *Pig, avgWin float64) Pig {
	var params []float64
	var apply [][]uint16
	nPos, nNeg := len(pos.Mus), len(neg.Mus)
	for p := 0; p < len(pos.Params)/3; p++ {
		params = append(params, pos.Params[3*p:3*p+3]...)
		apply = append(apply, rangeU16(0, nPos))
	}
	for p := 0; p < len(neg.Params)/3; p++ {
		params = append(params, neg.Params[3*p:3*p+3]...)
		apply = append(apply, rangeU16(nPos, nPos+nNeg))
	}

	w := (avgWin - neg.RTP) / (pos.RTP - neg.RTP)
	amps := make([]float64, 0, len(pos.Amps)+len(neg.Amps))
	for _, a := range pos.Amps {
		amps = append(amps, a*w/pos.SumDist)
	}
	for _, a := range neg.Amps {
		amps = append(amps, a*(1-w)/neg.SumDist)
	}
	stds := append(append([]float64{}, pos.Stds...), neg.Stds...)
	mus := append(append([]float64{}, pos.Mus...), neg.Mus...)
	return Pig{
		Amps: amps, Mus: mus, Stds: stds, Params: params, ApplyParms: apply,
		RTP: w*pos.RTP + (1-w)*neg.RTP, SumDist: 1,
		RandomSeeds:   []uint32{pos.RandomSeeds[0], neg.RandomSeeds[0]},
		RandomWeights: []float64{pos.RandomWeights[0], neg.RandomWeights[0]},
		RandomApplyParams: [][]int{rangeInt(0, len(pos.Amps)),
			rangeInt(len(pos.Amps), len(pos.Amps)+len(neg.Amps))},
	}
}
