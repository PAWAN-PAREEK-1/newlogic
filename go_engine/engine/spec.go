package engine

// spec.go - loads the game specification exported from the Python config.
//
// SINGLE SOURCE OF TRUTH: the Python file games/<game>/game_config.py remains
// the master definition of the game (paytable, reels, bet modes, criteria
// distributions). `games/<game>/export_spec.py` serialises that config to
// library/configs/game_spec_go.json and this file loads it. That means your
// friend keeps editing ONE Python file to tune the game; the Go engine picks
// the changes up automatically on the next run - no Go knowledge required.
//
// Ordering matters everywhere in this file: Python iterates dicts in insertion
// order and the RNG consumes weights in that order, so every weighted table is
// exported as an ARRAY of {v, w} pairs, never as a JSON object.

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
)

// WeightedInt is one (value, weight) entry of an integer-valued distribution,
// e.g. multiplier values {2: 200, 3: 80, ...} in game_config.py.
type WeightedInt struct {
	V int64   `json:"v"`
	W float64 `json:"w"`
}

// WeightedStr is one (value, weight) entry of a string-valued distribution,
// e.g. reelstrip weights {"BR0": 1}.
type WeightedStr struct {
	V string  `json:"v"`
	W float64 `json:"w"`
}

// GetRandomOutcomeInt replicates src/calculations/statistics.py
// get_random_outcome(): roll = uniform(0, sum(weights)); walk the table in
// insertion order until the cumulative weight reaches the roll.
func GetRandomOutcomeInt(rng Rng, table []WeightedInt) int64 {
	var total float64
	for _, e := range table {
		total += e.W
	}
	roll := rng.Uniform(0, total)
	cumulative := 0.0
	for _, e := range table {
		cumulative += e.W
		if cumulative >= roll {
			return e.V
		}
	}
	panic("empty distribution table")
}

// GetRandomOutcomeStr is the string-valued twin of GetRandomOutcomeInt.
func GetRandomOutcomeStr(rng Rng, table []WeightedStr) string {
	var total float64
	for _, e := range table {
		total += e.W
	}
	roll := rng.Uniform(0, total)
	cumulative := 0.0
	for _, e := range table {
		cumulative += e.W
		if cumulative >= roll {
			return e.V
		}
	}
	panic("empty distribution table")
}

// Rng is the subset of pyrand.Rand the engine consumes (interface kept small
// so tests can substitute a scripted sequence if ever needed).
type Rng interface {
	Random() float64
	Uniform(a, b float64) float64
	RandRange(stop int) int
	RandInt(a, b int) int
	ChoiceIndex(length int) int
	WeightedChoiceIndex(weights []float64) int
	Shuffle(length int, swap func(i, j int))
}

// PaytableEntry mirrors one ((kind, symbol): pay) row of config.paytable.
type PaytableEntry struct {
	Kind   int     `json:"kind"`
	Symbol string  `json:"symbol"`
	Pay    float64 `json:"pay"`
}

// Payline mirrors one payline: id + the row selected on each reel.
type Payline struct {
	ID   int64 `json:"id"`
	Rows []int `json:"rows"`
}

// SpecialSymbols mirrors one (property -> symbol names) entry of
// config.special_symbols, order preserved (it drives event attribute order).
type SpecialSymbols struct {
	Property string   `json:"property"`
	Symbols  []string `json:"symbols"`
}

// FreespinTrigger maps a scatter count to awarded free spins.
type FreespinTrigger struct {
	Scatters int   `json:"scatters"`
	Spins    int64 `json:"spins"`
}

// WinLevel is one row of the win-level tables in src/config/config.py.
// Min/Max are numbers, or the strings "wincap" / "inf" resolved per mode.
type WinLevel struct {
	Level int64           `json:"level"`
	Min   json.RawMessage `json:"min"`
	Max   json.RawMessage `json:"max"`
}

// Conditions mirrors a Distribution's `conditions` dict from game_config.py.
// Optional tables are nil when the criteria does not define them.
type Conditions struct {
	ReelWeights     map[string][]WeightedStr `json:"reel_weights"`
	MultValues      map[string][]WeightedInt `json:"mult_values"`
	LandingWilds    []WeightedInt            `json:"landing_wilds"`
	ScatterTriggers []WeightedInt            `json:"scatter_triggers"`
	PrizeValues     []WeightedInt            `json:"prize_values"`
	ForceWincap     bool                     `json:"force_wincap"`
	ForceFreegame   bool                     `json:"force_freegame"`

	// Switch mechanic (gothic_horror). Switch maps a gametype to its Switch
	// rules; a gametype without an entry never rolls a Switch.
	Switch map[string]*SwitchConfig `json:"switch"`
	// InitialFS overrides the free spins awarded by a base-game trigger (0 = use
	// freespin_triggers).
	InitialFS int64 `json:"initial_fs"`
	// FirstFsSwitch forces a Switch on the first free spin: "" (none), "any"
	// (Normal or Platinum by the configured weights) or "platinum".
	FirstFsSwitch string `json:"first_fs_switch"`
	// SuperspinResult marks a SUPERSPIN entry criteria: "dead", "normal",
	// "super" or "hidden" ("" = not a SUPERSPIN round).
	SuperspinResult string `json:"superspin_result"`
}

// SwitchConfig is one gametype's Switch rules.
type SwitchConfig struct {
	Chance  float64          `json:"chance"`  // chance per eligible spin that a Switch occurs
	Types   []WeightedStr    `json:"types"`   // {"normal": w, "platinum": w}
	Respins map[string]int64 `json:"respins"` // spins awarded per switch type
}

// Distribution mirrors src/config/distributions.py Distribution.
type Distribution struct {
	Criteria    string     `json:"criteria"`
	Quota       float64    `json:"quota"`     // fraction of simulations allocated to this criteria
	FixedAmt    *int       `json:"fixed_amt"` // alternative to quota (rarely used)
	WinCriteria *float64   `json:"win_criteria"`
	Conditions  Conditions `json:"conditions"`
}

// BetMode mirrors src/config/betmode.py BetMode.
type BetMode struct {
	Name              string         `json:"name"`
	Cost              float64        `json:"cost"`
	RTP               float64        `json:"rtp"`
	MaxWin            float64        `json:"max_win"`
	MaxWinIsInt       bool           `json:"max_win_is_int"` // Python declared the cap as an int (formatting quirk, see book.go)
	AutoCloseDisabled bool           `json:"auto_close_disabled"`
	IsFeature         bool           `json:"is_feature"`
	IsBuyBonus        bool           `json:"is_buybonus"`
	Distributions     []Distribution `json:"distributions"`
}

// Spec is the full exported game definition.
type Spec struct {
	GameID               string                       `json:"game_id"`
	RTP                  float64                      `json:"rtp"`
	NumReels             int                          `json:"num_reels"`
	NumRows              []int                        `json:"num_rows"`
	IncludePadding       bool                         `json:"include_padding"`
	BasegameType         string                       `json:"basegame_type"`
	FreegameType         string                       `json:"freegame_type"`
	Paytable             []PaytableEntry              `json:"paytable"`
	Paylines             []Payline                    `json:"paylines"`
	SpecialSymbols       []SpecialSymbols             `json:"special_symbols"`
	FreespinTriggers     map[string][]FreespinTrigger `json:"freespin_triggers"`
	AnticipationTriggers map[string]int               `json:"anticipation_triggers"`
	Reels                map[string][][]string        `json:"reels"` // reels[id][reel][stop]
	WinLevels            map[string][]WinLevel        `json:"win_levels"`
	BetModes             []BetMode                    `json:"bet_modes"`
	// SwitchSymbols are the regular symbol types a Switch can convert to Wild,
	// in config order (selection draws index into the uncollected subset).
	SwitchSymbols []string `json:"switch_symbols"`
	// SwitchWild is the symbol a converted type becomes.
	SwitchWild string `json:"switch_wild"`

	// Derived lookups (built by Load, not part of the JSON).
	paytableLookup map[payKey]float64
	symbolDefs     map[string]*SymbolDef
}

type payKey struct {
	kind int
	sym  string
}

// Load reads and indexes a game spec JSON file.
func Load(path string) (*Spec, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read spec: %w", err)
	}
	var s Spec
	if err := json.Unmarshal(raw, &s); err != nil {
		return nil, fmt.Errorf("parse spec: %w", err)
	}

	// Index the paytable for O(1) (kind, symbol) lookups during line evaluation.
	s.paytableLookup = make(map[payKey]float64, len(s.Paytable))
	for _, e := range s.Paytable {
		s.paytableLookup[payKey{e.Kind, e.Symbol}] = e.Pay
	}

	// Build symbol definitions the same way state.create_symbol_map does:
	// every symbol named in the paytable or in special_symbols exists.
	s.symbolDefs = make(map[string]*SymbolDef)
	addSym := func(name string) {
		if _, ok := s.symbolDefs[name]; ok {
			return
		}
		def := &SymbolDef{Name: name, Flags: map[string]bool{}}
		for _, sp := range s.SpecialSymbols {
			for _, n := range sp.Symbols {
				if n == name {
					def.Flags[sp.Property] = true
				}
			}
		}
		def.Special = len(def.Flags) > 0
		s.symbolDefs[name] = def
	}
	for _, e := range s.Paytable {
		addSym(e.Symbol)
	}
	for _, sp := range s.SpecialSymbols {
		for _, n := range sp.Symbols {
			addSym(n)
		}
	}
	return &s, nil
}

// Pay returns the paytable value for (kind, symbol) and whether it exists.
func (s *Spec) Pay(kind int, symbol string) (float64, bool) {
	v, ok := s.paytableLookup[payKey{kind, symbol}]
	return v, ok
}

// SymbolDefFor returns the immutable definition for a symbol name.
func (s *Spec) SymbolDefFor(name string) *SymbolDef {
	def, ok := s.symbolDefs[name]
	if !ok {
		panic(fmt.Sprintf("symbol '%s' is not registered", name))
	}
	return def
}

// MinFreespinTrigger returns min(config.freespin_triggers[gametype].keys()).
func (s *Spec) MinFreespinTrigger(gametype string) int {
	trigs, ok := s.FreespinTriggers[gametype]
	if !ok || len(trigs) == 0 {
		panic("no freespin triggers for gametype " + gametype)
	}
	minV := trigs[0].Scatters
	for _, t := range trigs {
		if t.Scatters < minV {
			minV = t.Scatters
		}
	}
	return minV
}

// FreespinAmount returns config.freespin_triggers[gametype][count]
// (panics like Python's KeyError if the count is not defined).
func (s *Spec) FreespinAmount(gametype string, count int) int64 {
	for _, t := range s.FreespinTriggers[gametype] {
		if t.Scatters == count {
			return t.Spins
		}
	}
	panic(fmt.Sprintf("no freespin trigger for %d scatters in %s", count, gametype))
}

// Mode returns the bet mode by name.
func (s *Spec) Mode(name string) *BetMode {
	for i := range s.BetModes {
		if s.BetModes[i].Name == name {
			return &s.BetModes[i]
		}
	}
	panic("unknown bet mode: " + name)
}

// DistributionFor returns the mode's distribution matching a criteria name.
func (m *BetMode) DistributionFor(criteria string) *Distribution {
	for i := range m.Distributions {
		if m.Distributions[i].Criteria == criteria {
			return &m.Distributions[i]
		}
	}
	panic("could not locate criteria distribution: " + criteria)
}

// winLevelBound resolves a WinLevel bound to a float, honouring the
// "wincap" and "inf" sentinels (wincap is the MODE-level max win).
func winLevelBound(raw json.RawMessage, wincap float64) float64 {
	var s string
	if err := json.Unmarshal(raw, &s); err == nil {
		switch s {
		case "wincap":
			return wincap
		case "inf":
			return inf()
		default:
			panic("bad win level bound: " + s)
		}
	}
	var f float64
	if err := json.Unmarshal(raw, &f); err != nil {
		panic("bad win level bound")
	}
	return f
}

func inf() float64 {
	return math.Inf(1)
}

// GetWinLevel replicates Config.get_win_level: find the level whose
// [min, max) range contains the win amount.
func (s *Spec) GetWinLevel(winAmount float64, key string, wincap float64) int64 {
	levels, ok := s.WinLevels[key]
	if !ok {
		panic("unknown win level key: " + key)
	}
	for _, lv := range levels {
		lo := winLevelBound(lv.Min, wincap)
		hi := winLevelBound(lv.Max, wincap)
		if winAmount >= lo && winAmount < hi {
			return lv.Level
		}
	}
	panic(fmt.Sprintf("winLevel not found: %v", winAmount))
}
