package engine

// pyfmt.go - numeric helpers that replicate CPython semantics bit-for-bit.
//
// The Python engine rounds win amounts with round(x, 2) / round(x, 0) and
// converts to cents with int(...). Python's round() performs *correct decimal
// rounding of the exact binary value with ties-to-even*, which is exactly what
// Go's strconv.FormatFloat does when formatting with a fixed precision - so we
// round by formatting to a decimal string and parsing it back. Slower than
// arithmetic tricks, but provably identical to Python, which is what matters
// for a math engine.

import (
	"math"
	"strconv"
	"strings"
)

// PyRound2 == Python round(x, 2).
func PyRound2(x float64) float64 {
	s := strconv.FormatFloat(x, 'f', 2, 64)
	v, _ := strconv.ParseFloat(s, 64)
	return v
}

// PyRound0Int == Python int(round(x, 0)).
func PyRound0Int(x float64) int64 {
	s := strconv.FormatFloat(x, 'f', 0, 64)
	v, _ := strconv.ParseInt(s, 10, 64)
	return v
}

// PyTruncInt == Python int(x) for finite floats (truncation toward zero).
func PyTruncInt(x float64) int64 {
	return int64(math.Trunc(x))
}

// PyFloatRepr == Python repr(float) / str(float) for the magnitudes the SDK
// produces (|x| < 1e16): the shortest decimal string that round-trips, always
// containing a decimal point ("25000.0", "0.5", "115.2").
func PyFloatRepr(f float64) string {
	s := strconv.FormatFloat(f, 'f', -1, 64)
	if !strings.ContainsAny(s, ".eE") {
		s += ".0"
	}
	return s
}

// PyMod == Python's % operator for ints (result takes the sign of the
// divisor). Reelstrip indices can go negative when forcing stop positions
// (stop - randint), and Python's negative-modulo wraps around; Go's does not.
func PyMod(a, b int) int {
	m := a % b
	if m < 0 {
		m += b
	}
	return m
}

// MinF mirrors Python min() for two floats.
func MinF(a, b float64) float64 {
	if a < b {
		return a
	}
	return b
}

// PyCappedRound2 mirrors `round(min(x, cap), 2)` where `cap` may have been
// declared as a Python int: min() returns the cap OBJECT when x exceeds it,
// and round(int, 2) keeps it an int - so the result is int64 for capped
// values (when capIsInt) and float64 otherwise.
func PyCappedRound2(x, cap float64, capIsInt bool) any {
	if x <= cap {
		return PyRound2(x)
	}
	if capIsInt {
		return int64(cap)
	}
	return PyRound2(cap)
}

// PyNumStr mirrors Python str() for the int-or-float values produced by
// PyCappedRound2 (used by the segmented lookup table writer).
func PyNumStr(v any) string {
	switch t := v.(type) {
	case int64:
		return strconv.FormatInt(t, 10)
	case float64:
		return PyFloatRepr(t)
	default:
		panic("PyNumStr: unsupported type")
	}
}

// NumF returns the numeric value of an int64-or-float64 `any`.
func NumF(v any) float64 {
	switch t := v.(type) {
	case int64:
		return float64(t)
	case float64:
		return t
	default:
		panic("NumF: unsupported type")
	}
}
