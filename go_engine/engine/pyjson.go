package engine

// pyjson.go - JSON serialisation that byte-matches CPython's json.dumps().
//
// WHY: the Python engine writes books with json.dumps(dict), which
//   - preserves dict insertion order,
//   - separates items with ", " and keys with ": ",
//   - prints floats with repr() (shortest round-trip form, "25000.0" style).
//
// Go maps randomise key order, so we model every JSON object as an ordered
// list of key/value pairs (Obj). Marshalling through this file produces the
// exact same bytes as the Python engine, which lets us validate the port with
// a plain file diff and keeps downstream consumers (RGS, frontend, tools)
// looking at familiar output.

import (
	"strconv"
	"strings"
)

// KV is one ordered key/value pair inside a JSON object.
type KV struct {
	K string
	V any
}

// Obj is an insertion-ordered JSON object (mirror of a Python dict).
type Obj []KV

// Arr is a JSON array of arbitrary values.
type Arr []any

// MarshalPy renders any supported value using Python json.dumps() formatting
// (default separators: ", " between items, ": " after keys).
func MarshalPy(v any) []byte {
	var sb strings.Builder
	writePy(&sb, v)
	return []byte(sb.String())
}

func writePy(sb *strings.Builder, v any) {
	switch t := v.(type) {
	case Obj:
		sb.WriteByte('{')
		for i, kv := range t {
			if i > 0 {
				sb.WriteString(", ")
			}
			writeString(sb, kv.K)
			sb.WriteString(": ")
			writePy(sb, kv.V)
		}
		sb.WriteByte('}')
	case Arr:
		sb.WriteByte('[')
		for i, item := range t {
			if i > 0 {
				sb.WriteString(", ")
			}
			writePy(sb, item)
		}
		sb.WriteByte(']')
	case []Obj:
		sb.WriteByte('[')
		for i, item := range t {
			if i > 0 {
				sb.WriteString(", ")
			}
			writePy(sb, item)
		}
		sb.WriteByte(']')
	case []int:
		sb.WriteByte('[')
		for i, item := range t {
			if i > 0 {
				sb.WriteString(", ")
			}
			sb.WriteString(strconv.Itoa(item))
		}
		sb.WriteByte(']')
	case []int64:
		sb.WriteByte('[')
		for i, item := range t {
			if i > 0 {
				sb.WriteString(", ")
			}
			sb.WriteString(strconv.FormatInt(item, 10))
		}
		sb.WriteByte(']')
	case string:
		writeString(sb, t)
	case bool:
		if t {
			sb.WriteString("true")
		} else {
			sb.WriteString("false")
		}
	case int:
		sb.WriteString(strconv.Itoa(t))
	case int64:
		sb.WriteString(strconv.FormatInt(t, 10))
	case float64:
		sb.WriteString(PyFloatRepr(t))
	case rawJSON:
		sb.Write(t)
	case nil:
		sb.WriteString("null")
	default:
		panic("pyjson: unsupported type")
	}
}

// writeString escapes like Python json.dumps (ensure_ascii, but all SDK
// strings are plain ASCII identifiers, so standard JSON escaping suffices).
func writeString(sb *strings.Builder, s string) {
	sb.WriteByte('"')
	for i := 0; i < len(s); i++ {
		c := s[i]
		switch c {
		case '"':
			sb.WriteString(`\"`)
		case '\\':
			sb.WriteString(`\\`)
		case '\n':
			sb.WriteString(`\n`)
		case '\r':
			sb.WriteString(`\r`)
		case '\t':
			sb.WriteString(`\t`)
		default:
			if c < 0x20 {
				sb.WriteString(`\u00`)
				const hex = "0123456789abcdef"
				sb.WriteByte(hex[c>>4])
				sb.WriteByte(hex[c&0xf])
			} else {
				sb.WriteByte(c)
			}
		}
	}
	sb.WriteByte('"')
}

// MarshalPyIndent renders with json.dumps(..., indent=4) formatting -
// used for the force-record and event-config files, which the Python SDK
// writes pretty-printed.
func MarshalPyIndent(v any, indent int) []byte {
	var sb strings.Builder
	writePyIndent(&sb, v, indent, 0)
	return []byte(sb.String())
}

func writePyIndent(sb *strings.Builder, v any, indent, level int) {
	pad := strings.Repeat(" ", indent*(level+1))
	padEnd := strings.Repeat(" ", indent*level)
	switch t := v.(type) {
	case Obj:
		if len(t) == 0 {
			sb.WriteString("{}")
			return
		}
		sb.WriteString("{\n")
		for i, kv := range t {
			if i > 0 {
				sb.WriteString(",\n")
			}
			sb.WriteString(pad)
			writeString(sb, kv.K)
			sb.WriteString(": ")
			writePyIndent(sb, kv.V, indent, level+1)
		}
		sb.WriteString("\n" + padEnd + "}")
	case Arr:
		if len(t) == 0 {
			sb.WriteString("[]")
			return
		}
		sb.WriteString("[\n")
		for i, item := range t {
			if i > 0 {
				sb.WriteString(",\n")
			}
			sb.WriteString(pad)
			writePyIndent(sb, item, indent, level+1)
		}
		sb.WriteString("\n" + padEnd + "]")
	case []Obj:
		arr := make(Arr, len(t))
		for i := range t {
			arr[i] = t[i]
		}
		writePyIndent(sb, arr, indent, level)
	case []int:
		sb.WriteByte('[')
		for i, item := range t {
			if i > 0 {
				sb.WriteString(", ")
			}
			sb.WriteString(strconv.Itoa(item))
		}
		sb.WriteByte(']')
	default:
		writePy(sb, v)
	}
}
