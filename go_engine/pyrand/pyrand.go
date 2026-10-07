// Package pyrand is a bit-exact re-implementation of CPython's `random` module
// (Mersenne Twister MT19937 + the high-level helpers the Math SDK uses).
//
// WHY THIS EXISTS
// ---------------
// The Python Math SDK seeds `random.seed(sim + 1)` for every simulation, which
// makes each simulated round a pure function of its simulation number.  By
// reproducing CPython's generator *exactly* (same seeding algorithm, same
// tempering, same float construction, same rejection sampling), the Go engine
// produces byte-for-byte identical simulation results to the Python engine.
//
// That gives us two things:
//  1. Verifiability - any logic divergence between the Go port and the Python
//     reference shows up as a diff in the output books.
//  2. Regulatory reproducibility - a book can be regenerated from its sim
//     number by either engine.
//
// WHAT IS IMPLEMENTED (only what the SDK actually calls)
//   - Seed(int)                 -> random.seed(n)              (init_by_array)
//   - Random()                  -> random.random()             (genrand_res53)
//   - GetRandBits(k)            -> random.getrandbits(k)       (k <= 64)
//   - RandBelow(n)              -> random._randbelow(n)        (rejection sampling)
//   - RandRange(n)              -> random.randrange(0, n)
//   - RandInt(a, b)             -> random.randint(a, b)
//   - Uniform(a, b)             -> random.uniform(a, b)
//   - ChoiceIndex(n)            -> index used by random.choice(seq)
//   - WeightedChoiceIndex(w)    -> index used by random.choices(pop, weights)[0]
//   - Shuffle(n, swap)          -> random.shuffle(x)
//
// Every function documents the CPython source it mirrors.  Do NOT "optimise"
// the math here - changing call order or float arithmetic breaks parity.
package pyrand

const (
	n         = 624        // MT19937 state size (words)
	m         = 397        // MT19937 shift constant
	matrixA   = 0x9908b0df // MT19937 twist matrix constant
	upperMask = 0x80000000 // most significant w-r bits
	lowerMask = 0x7fffffff // least significant r bits
)

// Rand mirrors one instance of CPython's random.Random.
// It is NOT safe for concurrent use - create one per goroutine/simulation,
// exactly like the SDK creates one seeded stream per simulation number.
type Rand struct {
	mt  [n]uint32
	mti int
}

// New returns a generator seeded like CPython's random.seed(seed) for a
// non-negative integer seed. The SDK always seeds with `sim + 1` (>= 1).
func New(seed uint64) *Rand {
	r := &Rand{}
	r.Seed(seed)
	return r
}

// Seed replicates CPython random_seed(int):
//   - n = abs(n)
//   - split n into little-endian 32-bit words ("key")
//   - init_by_array(key)
//
// (_randommodule.c: random_seed)
func (r *Rand) Seed(seed uint64) {
	var key []uint32
	if seed == 0 {
		key = []uint32{0}
	} else {
		for s := seed; s != 0; s >>= 32 {
			key = append(key, uint32(s&0xffffffff))
		}
	}
	r.initByArray(key)
}

// initGenrand is MT19937's init_genrand (Knuth line 25 initialiser).
func (r *Rand) initGenrand(s uint32) {
	r.mt[0] = s
	for i := 1; i < n; i++ {
		r.mt[i] = 1812433253*(r.mt[i-1]^(r.mt[i-1]>>30)) + uint32(i)
	}
	r.mti = n
}

// initByArray is MT19937's init_by_array - seeds the state from an array of
// 32-bit words. This is what CPython uses for integer seeds.
func (r *Rand) initByArray(key []uint32) {
	r.initGenrand(19650218)
	i, j := 1, 0
	k := n
	if len(key) > k {
		k = len(key)
	}
	for ; k > 0; k-- {
		r.mt[i] = (r.mt[i] ^ ((r.mt[i-1] ^ (r.mt[i-1] >> 30)) * 1664525)) + key[j] + uint32(j)
		i++
		j++
		if i >= n {
			r.mt[0] = r.mt[n-1]
			i = 1
		}
		if j >= len(key) {
			j = 0
		}
	}
	for k = n - 1; k > 0; k-- {
		r.mt[i] = (r.mt[i] ^ ((r.mt[i-1] ^ (r.mt[i-1] >> 30)) * 1566083941)) - uint32(i)
		i++
		if i >= n {
			r.mt[0] = r.mt[n-1]
			i = 1
		}
	}
	r.mt[0] = 0x80000000
}

// genrandUint32 is MT19937's genrand_uint32 (one tempered 32-bit output).
func (r *Rand) genrandUint32() uint32 {
	var y uint32
	if r.mti >= n { // generate n words at one time
		var kk int
		for kk = 0; kk < n-m; kk++ {
			y = (r.mt[kk] & upperMask) | (r.mt[kk+1] & lowerMask)
			r.mt[kk] = r.mt[kk+m] ^ (y >> 1) ^ ((y & 1) * matrixA)
		}
		for ; kk < n-1; kk++ {
			y = (r.mt[kk] & upperMask) | (r.mt[kk+1] & lowerMask)
			r.mt[kk] = r.mt[kk+(m-n)] ^ (y >> 1) ^ ((y & 1) * matrixA)
		}
		y = (r.mt[n-1] & upperMask) | (r.mt[0] & lowerMask)
		r.mt[n-1] = r.mt[m-1] ^ (y >> 1) ^ ((y & 1) * matrixA)
		r.mti = 0
	}
	y = r.mt[r.mti]
	r.mti++
	// Tempering
	y ^= y >> 11
	y ^= (y << 7) & 0x9d2c5680
	y ^= (y << 15) & 0xefc60000
	y ^= y >> 18
	return y
}

// Random replicates random.random() == genrand_res53:
// a 53-bit float in [0, 1) built from two 32-bit outputs.
func (r *Rand) Random() float64 {
	a := r.genrandUint32() >> 5 // upper 27 bits
	b := r.genrandUint32() >> 6 // upper 26 bits
	return (float64(a)*67108864.0 + float64(b)) * (1.0 / 9007199254740992.0)
}

// GetRandBits replicates random.getrandbits(k) for 0 < k <= 64.
// CPython consumes ceil(k/32) words little-endian, truncating the last word.
// (_randommodule.c: random_getrandbits)
func (r *Rand) GetRandBits(k uint) uint64 {
	if k == 0 || k > 64 {
		panic("pyrand: GetRandBits supports 1..64 bits")
	}
	if k <= 32 {
		return uint64(r.genrandUint32() >> (32 - k))
	}
	lo := uint64(r.genrandUint32())          // first word: low 32 bits
	hi := uint64(r.genrandUint32() >> (64 - k)) // second word truncated
	return lo | hi<<32
}

// RandBelow replicates random._randbelow_with_getrandbits(n):
// draw bit_length(n) bits, reject values >= n. Requires n > 0.
func (r *Rand) RandBelow(nv int) int {
	if nv <= 0 {
		panic("pyrand: RandBelow requires n > 0")
	}
	k := bitLength(uint64(nv))
	v := r.GetRandBits(k)
	for v >= uint64(nv) {
		v = r.GetRandBits(k)
	}
	return int(v)
}

// RandRange replicates random.randrange(0, stop).
func (r *Rand) RandRange(stop int) int {
	return r.RandBelow(stop)
}

// RandInt replicates random.randint(a, b) == randrange(a, b+1).
func (r *Rand) RandInt(a, b int) int {
	return a + r.RandBelow(b-a+1)
}

// Uniform replicates random.uniform(a, b) == a + (b-a)*random().
func (r *Rand) Uniform(a, b float64) float64 {
	return a + (b-a)*r.Random()
}

// ChoiceIndex replicates the index drawn by random.choice(seq):
// seq[_randbelow(len(seq))].
func (r *Rand) ChoiceIndex(length int) int {
	return r.RandBelow(length)
}

// WeightedChoiceIndex replicates the index selected by
// random.choices(population, weights, k=1)[0]:
//
//	cum = accumulate(weights); total = cum[-1] + 0.0
//	bisect_right(cum, random()*total, 0, len-1)
//
// The SDK only ever asks for k=1. Weights may be ints or floats in Python;
// we accumulate float64 in the same order, which is bit-identical for the
// magnitudes used by the SDK.
func (r *Rand) WeightedChoiceIndex(weights []float64) int {
	cum := make([]float64, len(weights))
	var running float64
	for i, w := range weights {
		running += w
		cum[i] = running
	}
	total := running
	x := r.Random() * total
	// bisect_right(cum, x, 0, hi) with hi = len-1 (CPython passes hi=n-1).
	lo, hi := 0, len(weights)-1
	for lo < hi {
		mid := (lo + hi) / 2
		if x < cum[mid] {
			hi = mid
		} else {
			lo = mid + 1
		}
	}
	return lo
}

// Shuffle replicates random.shuffle(x) - modern Fisher-Yates:
//
//	for i in reversed(range(1, len(x))): j = _randbelow(i+1); swap(i, j)
//
// The caller supplies the swap so any slice type can be shuffled.
func (r *Rand) Shuffle(length int, swap func(i, j int)) {
	for i := length - 1; i > 0; i-- {
		j := r.RandBelow(i + 1)
		swap(i, j)
	}
}

// bitLength mirrors int.bit_length() in Python.
func bitLength(v uint64) uint {
	var k uint
	for v > 0 {
		v >>= 1
		k++
	}
	return k
}
