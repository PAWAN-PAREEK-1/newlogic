package engine

// force.go - aggregation and output of "force" files, mirroring
// state.imprint_wins + write_data.output_lookup_and_force_files.
//
// Force files map recorded game situations (e.g. "4 scatters in basegame")
// to the book ids that contain them. The Rust optimizer uses them to decide
// which books belong to which criteria fence, and the search tools use them
// to find demo rounds.

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
)

// forceKey uniquely identifies one sorted description.
type forceKey string

func makeForceKey(pairs []ForcePair) forceKey {
	s := ""
	for _, p := range pairs {
		s += p.K + "\x00" + p.V + "\x00"
	}
	return forceKey(s)
}

// ForceAggregator accumulates force records across all sims of a mode, in
// first-seen order (Python dict insertion order).
type ForceAggregator struct {
	order   []forceKey
	entries map[forceKey]*forceEntry
}

type forceEntry struct {
	pairs          []ForcePair
	timesTriggered int
	bookIDs        []int
	seenBooks      map[int]bool
}

// NewForceAggregator creates an empty aggregator.
func NewForceAggregator() *ForceAggregator {
	return &ForceAggregator{entries: map[forceKey]*forceEntry{}}
}

// Add merges one simulation's imprinted records (mirrors imprint_wins: a
// (description, bookId) pair increments timesTriggered only once).
func (f *ForceAggregator) Add(records []ForceRecord) {
	for _, rec := range records {
		k := makeForceKey(rec.Pairs)
		e, ok := f.entries[k]
		if !ok {
			e = &forceEntry{pairs: rec.Pairs, seenBooks: map[int]bool{}}
			f.entries[k] = e
			f.order = append(f.order, k)
		}
		if e.seenBooks[rec.BookID] {
			continue
		}
		e.seenBooks[rec.BookID] = true
		e.timesTriggered++
		e.bookIDs = append(e.bookIDs, rec.BookID)
	}
}

// WriteForceRecord writes forces/force_record_<mode>.json in the same shape
// as the Python engine: [{search: [{name, value}...], timesTriggered, bookIds}].
// newline mirrors Python's text-mode line endings (CRLF on Windows).
func (f *ForceAggregator) WriteForceRecord(path, newline string) error {
	out := make(Arr, 0, len(f.order))
	for _, k := range f.order {
		e := f.entries[k]
		search := make(Arr, 0, len(e.pairs))
		for _, p := range e.pairs {
			search = append(search, Obj{{K: "name", V: p.K}, {K: "value", V: p.V}})
		}
		out = append(out, Obj{
			{K: "search", V: search},
			{K: "timesTriggered", V: e.timesTriggered},
			{K: "bookIds", V: e.bookIDs},
		})
	}
	return writeTextFile(path, MarshalPyIndent(out, 4), newline)
}

// writeTextFile mirrors Python's text-mode open(): every "\n" in the payload
// becomes the platform newline.
func writeTextFile(path string, data []byte, newline string) error {
	if newline != "\n" {
		data = bytesReplaceLF(data, newline)
	}
	return os.WriteFile(path, data, 0o644)
}

func bytesReplaceLF(data []byte, newline string) []byte {
	out := make([]byte, 0, len(data)+len(data)/16)
	for _, b := range data {
		if b == '\n' {
			out = append(out, newline...)
		} else {
			out = append(out, b)
		}
	}
	return out
}

// Options returns {key: [values]} for force.json - every distinct value seen
// for each description key, in first-seen order (deterministic, unlike the
// Python set iteration, but semantically identical).
func (f *ForceAggregator) Options() Obj {
	keyOrder := []string{}
	values := map[string][]string{}
	seen := map[string]map[string]bool{}
	for _, k := range f.order {
		for _, p := range f.entries[k].pairs {
			if _, ok := values[p.K]; !ok {
				keyOrder = append(keyOrder, p.K)
				values[p.K] = nil
				seen[p.K] = map[string]bool{}
			}
			if !seen[p.K][p.V] {
				seen[p.K][p.V] = true
				values[p.K] = append(values[p.K], p.V)
			}
		}
	}
	obj := Obj{}
	for _, k := range keyOrder {
		arr := make(Arr, 0, len(values[k]))
		for _, v := range values[k] {
			arr = append(arr, v)
		}
		obj = append(obj, KV{K: k, V: arr})
	}
	return obj
}

// WriteForceOptions merges the per-mode key options into forces/force.json
// (mirror of the incremental per-mode update in output_lookup_and_force_files).
// Modes simulated in this run are written in run order; modes present in an
// existing force.json but not re-run are preserved (sorted, re-emitted raw).
func WriteForceOptions(forcePath string, runOrder []string, options map[string]Obj, newline string) error {
	path := filepath.Join(forcePath, "force.json")

	ran := map[string]bool{}
	out := Obj{}
	for _, mode := range runOrder {
		out = append(out, KV{K: mode, V: options[mode]})
		ran[mode] = true
	}

	// Preserve untouched modes from a previous force.json, if any.
	if raw, err := os.ReadFile(path); err == nil {
		var prev map[string]json.RawMessage
		if err2 := json.Unmarshal(raw, &prev); err2 == nil {
			keys := make([]string, 0, len(prev))
			for k := range prev {
				if !ran[k] {
					keys = append(keys, k)
				}
			}
			sort.Strings(keys)
			for _, k := range keys {
				out = append(out, KV{K: k, V: rawJSON(prev[k])})
			}
		}
	}
	return writeTextFile(path, MarshalPyIndent(out, 4), newline)
}

// rawJSON lets already-encoded JSON pass through the Python-style marshaller.
type rawJSON []byte
