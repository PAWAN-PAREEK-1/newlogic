package engine

// symbol.go - mirror of src/calculations/symbol.py.
//
// A SymbolDef is the immutable definition (name + special-property flags);
// a Symbol is one instance on the board, which may carry per-instance values
// (multiplier for wilds, prize for prize symbols).

// SymbolDef mirrors SymbolDefinition: name plus which special properties
// (wild / scatter / multiplier / prize / ...) the symbol carries.
type SymbolDef struct {
	Name    string
	Flags   map[string]bool
	Special bool
}

// Symbol mirrors the Python Symbol instance. Python initialises
// multiplier=1 for symbols with the "multiplier" flag and prize=0 for
// symbols with the "prize" flag (assign_default_attribute); game code then
// overwrites these via assign_attribute.
type Symbol struct {
	Def        *SymbolDef
	Multiplier int64
	MultSet    bool // whether the multiplier slot holds a value (Python: not None)
	Prize      int64
	PrizeSet   bool
}

// NewSymbol mirrors Symbol.__init__ + assign_default_attribute.
func NewSymbol(def *SymbolDef) *Symbol {
	s := &Symbol{Def: def}
	if def.Flags["multiplier"] {
		s.Multiplier = 1
		s.MultSet = true
	}
	if def.Flags["prize"] {
		s.Prize = 0
		s.PrizeSet = true
	}
	return s
}

// Name returns the symbol's name.
func (s *Symbol) Name() string { return s.Def.Name }

// CheckAttribute mirrors Symbol.check_attribute(attr):
// true if the instance value is set and truthy, OR the definition carries the
// flag. (Python treats 0/False/None as "not set" and falls through to flags.)
func (s *Symbol) CheckAttribute(attr string) bool {
	switch attr {
	case "multiplier":
		if s.MultSet && s.Multiplier != 0 {
			return true
		}
	case "prize":
		if s.PrizeSet && s.Prize != 0 {
			return true
		}
	}
	return s.Def.Flags[attr]
}

// GetMultiplier mirrors get_attribute("multiplier").
func (s *Symbol) GetMultiplier() int64 { return s.Multiplier }

// AssignMultiplier mirrors assign_attribute({"multiplier": v}).
func (s *Symbol) AssignMultiplier(v int64) {
	s.Multiplier = v
	s.MultSet = true
}

// AssignPrize mirrors assign_attribute({"prize": v}).
func (s *Symbol) AssignPrize(v int64) {
	s.Prize = v
	s.PrizeSet = true
}

// JSONReady mirrors events.json_ready_sym: {"name": ...} plus one entry per
// special property, in the order special properties are declared in the
// config (that order is what makes the output byte-identical to Python).
// A property renders as its numeric value when the instance holds a truthy
// value, otherwise as `true` when the definition carries the flag.
func (s *Symbol) JSONReady(specialProperties []SpecialSymbols) Obj {
	obj := Obj{{K: "name", V: s.Def.Name}}
	for _, sp := range specialProperties {
		attr := sp.Property
		switch attr {
		case "multiplier":
			if s.MultSet && s.Multiplier != 0 {
				obj = append(obj, KV{K: attr, V: s.Multiplier})
				continue
			}
		case "prize":
			if s.PrizeSet && s.Prize != 0 {
				obj = append(obj, KV{K: attr, V: s.Prize})
				continue
			}
		}
		if s.Def.Flags[attr] {
			obj = append(obj, KV{K: attr, V: true})
		}
	}
	return obj
}
