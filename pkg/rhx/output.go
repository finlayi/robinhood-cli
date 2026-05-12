package rhx

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"sort"
	"strings"
	"time"
)

const outputSchemaVersion = "v3"

type BrokerError struct {
	Code      ErrorCode      `json:"code"`
	Message   string         `json:"message"`
	Retriable bool           `json:"retriable"`
	Details   map[string]any `json:"details,omitempty"`
}

type Envelope struct {
	OK       bool           `json:"ok"`
	Command  string         `json:"command"`
	Provider *string        `json:"provider"`
	Data     any            `json:"data"`
	Error    *BrokerError   `json:"error"`
	Meta     map[string]any `json:"meta"`
}

type OutputOptions struct {
	JSON   bool
	Human  bool
	View   string
	Fields []string
	Limit  int
}

func emitSuccess(w io.Writer, command string, provider string, data any, opts OutputOptions, meta map[string]any) {
	payload := data
	shapeMeta := map[string]any{}
	if opts.JSON || opts.Human {
		payload, shapeMeta = shapeData(payload, opts)
	}

	combinedMeta := envelopeMeta(opts.View)
	for k, v := range meta {
		combinedMeta[k] = v
	}
	for k, v := range shapeMeta {
		combinedMeta[k] = v
	}

	if opts.JSON {
		env := Envelope{
			OK:       true,
			Command:  command,
			Provider: providerPtr(provider),
			Data:     payload,
			Error:    nil,
			Meta:     combinedMeta,
		}
		writeJSONLine(w, env)
		return
	}

	fmt.Fprintf(w, "OK %s\n", command)
	if payload != nil {
		writeHuman(w, payload)
	}
}

func emitError(w io.Writer, command string, provider string, err *CLIError, opts OutputOptions) {
	if opts.JSON {
		env := Envelope{
			OK:       false,
			Command:  command,
			Provider: providerPtr(provider),
			Data:     nil,
			Error: &BrokerError{
				Code:      err.Code,
				Message:   err.Message,
				Retriable: err.Retriable,
			},
			Meta: envelopeMeta(opts.View),
		}
		writeJSONLine(w, env)
		return
	}
	fmt.Fprintf(w, "%s %s\n", err.Code, err.Message)
}

func envelopeMeta(view string) map[string]any {
	if view == "" {
		view = "summary"
	}
	return map[string]any{
		"timestamp":     time.Now().UTC().Format(time.RFC3339),
		"output_schema": outputSchemaVersion,
		"view":          view,
	}
}

func providerPtr(provider string) *string {
	if provider == "" {
		return nil
	}
	return &provider
}

func writeJSONLine(w io.Writer, v any) {
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(v)
}

func writeHuman(w io.Writer, v any) {
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		fmt.Fprintf(w, "%v\n", v)
		return
	}
	fmt.Fprintf(w, "%s\n", b)
}

func shapeData(data any, opts OutputOptions) (any, map[string]any) {
	meta := map[string]any{}
	if opts.View == "full" {
		return data, meta
	}

	switch rows := data.(type) {
	case []map[string]any:
		total := len(rows)
		if opts.Limit > 0 && opts.Limit < len(rows) {
			rows = rows[:opts.Limit]
			meta["total_count"] = total
			meta["returned_count"] = len(rows)
			meta["truncated"] = true
		}
		if len(opts.Fields) > 0 {
			rows = projectRows(rows, opts.Fields)
		}
		return rows, meta
	case []any:
		total := len(rows)
		if opts.Limit > 0 && opts.Limit < len(rows) {
			rows = rows[:opts.Limit]
			meta["total_count"] = total
			meta["returned_count"] = len(rows)
			meta["truncated"] = true
		}
		if len(opts.Fields) > 0 {
			rows = projectAnyRows(rows, opts.Fields)
		}
		return rows, meta
	case map[string]any:
		if len(opts.Fields) > 0 {
			return projectMap(rows, opts.Fields), meta
		}
	}
	return data, meta
}

func projectRows(rows []map[string]any, fields []string) []map[string]any {
	out := make([]map[string]any, 0, len(rows))
	for _, row := range rows {
		out = append(out, projectMap(row, fields))
	}
	return out
}

func projectAnyRows(rows []any, fields []string) []any {
	out := make([]any, 0, len(rows))
	for _, row := range rows {
		if m, ok := row.(map[string]any); ok {
			out = append(out, projectMap(m, fields))
			continue
		}
		out = append(out, row)
	}
	return out
}

func projectMap(row map[string]any, fields []string) map[string]any {
	out := map[string]any{}
	for _, field := range fields {
		if value, ok := row[field]; ok {
			out[field] = value
		}
	}
	return out
}

func parseFields(raw string) ([]string, error) {
	if raw == "" {
		return nil, nil
	}
	seen := map[string]bool{}
	fields := []string{}
	for _, part := range strings.Split(raw, ",") {
		field := strings.TrimSpace(part)
		if field == "" || seen[field] {
			continue
		}
		seen[field] = true
		fields = append(fields, field)
	}
	if len(fields) == 0 {
		return nil, newError(ErrorValidation, "--fields requires at least one field name")
	}
	return fields, nil
}

func parseSymbols(raw string) ([]string, error) {
	seen := map[string]bool{}
	symbols := []string{}
	for _, part := range strings.Split(raw, ",") {
		symbol := strings.ToUpper(strings.TrimSpace(part))
		if symbol == "" || seen[symbol] {
			continue
		}
		seen[symbol] = true
		symbols = append(symbols, symbol)
	}
	if len(symbols) == 0 {
		return nil, newError(ErrorValidation, "--symbols requires at least one symbol")
	}
	return symbols, nil
}

func sortedKeys(m map[string]any) []string {
	keys := make([]string, 0, len(m))
	for key := range m {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}

func defaultOutputOptions() OutputOptions {
	return OutputOptions{View: "summary"}
}

func writeStdoutSuccess(command string, provider string, data any, opts OutputOptions, meta map[string]any) {
	emitSuccess(os.Stdout, command, provider, data, opts, meta)
}

func writeStderrError(command string, provider string, err *CLIError, opts OutputOptions) {
	writer := os.Stderr
	if opts.JSON {
		writer = os.Stdout
	}
	emitError(writer, command, provider, err, opts)
}
