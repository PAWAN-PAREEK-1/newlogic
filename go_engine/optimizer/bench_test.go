package optimizer

import (
	"math/rand/v2"
	"testing"
)

func BenchmarkRunSimulation(b *testing.B) {
	r := rand.NewPCG(1, 2)
	wins := make([]float64, 4000)
	weights := make([]float64, 4000)
	for i := range wins {
		wins[i] = float64(i) / 10
		weights[i] = 1 / (1 + float64(i))
	}
	bank := make([]float64, 201)
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		runSimulation(wins, weights, 200, 5000, 1, []int{50, 100, 200}, []float64{0.3, 0.4, 0.3}, 1, r, bank)
	}
	b.ReportMetric(float64(b.Elapsed().Nanoseconds())/float64(b.N)/1e6, "ns/spin")
}
