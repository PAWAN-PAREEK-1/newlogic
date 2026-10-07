package engine

// criteria.go - mirror of src/state/run_sims.py get_sim_splits() and
// assign_sim_criteria().
//
// Before a mode is simulated, every simulation number is assigned a criteria
// ("0", "basegame", "freegame", "wincap", ...) according to the quotas in
// game_config.py. Python does this with the module RNG seeded to 0, so the
// assignment is deterministic; we replicate it exactly, which keeps sim->
// criteria mapping (and therefore every book) identical between engines.

import (
	"fmt"

	"github.com/stakeengine/go-engine/pyrand"
)

// AssignCriteria returns criteria[sim] for every simulation of the mode.
func AssignCriteria(mode *BetMode, numSims int) []string {
	rng := pyrand.New(0) // Python: random.seed(0)

	// num_sims_criteria = {criteria: max(int(num_sims * quota), 1)}
	counts := make([]int, len(mode.Distributions))
	weights := make([]float64, len(mode.Distributions))
	total := 0
	for i, d := range mode.Distributions {
		counts[i] = int(float64(numSims) * d.Quota) // Python int() truncates
		if counts[i] < 1 {
			counts[i] = 1
		}
		weights[i] = d.Quota
		total += counts[i]
	}
	reduceSims := total > numSims

	// Randomly nudge counts until they sum to num_sims. Draws that cannot be
	// applied (count already 1 while reducing) still consume RNG - faithful
	// to Python. The iteration cap only guards against impossible configs
	// (e.g. more criteria than simulations), where Python would hang.
	sum := total
	for iter := 0; sum != numSims; iter++ {
		if iter > 100_000_000 {
			panic(fmt.Sprintf("criteria quotas for mode %q cannot be balanced to %d sims", mode.Name, numSims))
		}
		c := rng.WeightedChoiceIndex(weights)
		if reduceSims && counts[c] > 1 {
			counts[c]--
			sum--
		} else if !reduceSims {
			counts[c]++
			sum++
		}
	}

	// sim_allocation = [criteria] * count, concatenated in distribution
	// order, then shuffled with the same RNG stream.
	allocation := make([]string, 0, numSims)
	for i, d := range mode.Distributions {
		for j := 0; j < counts[i]; j++ {
			allocation = append(allocation, d.Criteria)
		}
	}
	rng.Shuffle(len(allocation), func(i, j int) {
		allocation[i], allocation[j] = allocation[j], allocation[i]
	})
	return allocation
}
