package rhx

import (
	"strconv"
	"strings"
)

type globalOptions struct {
	Output   OutputOptions
	Profile  string
	Provider string
	Config   string
	Verbose  bool
}

func parseGlobalOptions(args []string) (globalOptions, []string, error) {
	opts := globalOptions{Output: defaultOutputOptions(), Provider: "auto", Profile: "default"}
	remaining := []string{}
	for i := 0; i < len(args); i++ {
		arg := args[i]
		switch {
		case arg == "--json":
			opts.Output.JSON = true
		case arg == "--human":
			opts.Output.Human = true
		case arg == "--verbose":
			opts.Verbose = true
		case arg == "--no-color":
		case arg == "--view" || arg == "--fields" || arg == "--limit" || arg == "--profile" || arg == "--provider" || arg == "--config":
			if i+1 >= len(args) {
				return opts, nil, wrapError(ErrorValidation, "%s requires a value", arg)
			}
			i++
			if err := setGlobalValue(&opts, strings.TrimPrefix(arg, "--"), args[i]); err != nil {
				return opts, nil, err
			}
		case strings.HasPrefix(arg, "--view=") || strings.HasPrefix(arg, "--fields=") || strings.HasPrefix(arg, "--limit=") || strings.HasPrefix(arg, "--profile=") || strings.HasPrefix(arg, "--provider=") || strings.HasPrefix(arg, "--config="):
			name, value, _ := strings.Cut(strings.TrimPrefix(arg, "--"), "=")
			if err := setGlobalValue(&opts, name, value); err != nil {
				return opts, nil, err
			}
		default:
			remaining = append(remaining, arg)
		}
	}
	if opts.Output.JSON && opts.Output.Human {
		return opts, nil, newError(ErrorValidation, "--human cannot be used with --json")
	}
	if opts.Output.View != "summary" && opts.Output.View != "full" {
		return opts, nil, newError(ErrorValidation, "Unsupported --view. Use summary or full.")
	}
	if len(opts.Output.Fields) > 0 && opts.Output.View != "summary" {
		return opts, nil, newError(ErrorValidation, "--fields requires --view summary")
	}
	return opts, remaining, nil
}

func setGlobalValue(opts *globalOptions, name string, value string) error {
	switch name {
	case "view":
		opts.Output.View = strings.ToLower(value)
	case "fields":
		fields, err := parseFields(value)
		if err != nil {
			return err
		}
		opts.Output.Fields = fields
	case "limit":
		limit, err := strconv.Atoi(value)
		if err != nil || limit < 1 {
			return newError(ErrorValidation, "--limit must be >= 1")
		}
		opts.Output.Limit = limit
	case "profile":
		opts.Profile = value
	case "provider":
		provider := strings.ToLower(value)
		if provider != "auto" && provider != "brokerage" && provider != "crypto" {
			return newError(ErrorValidation, "--provider must be auto, brokerage, or crypto")
		}
		opts.Provider = provider
	case "config":
		opts.Config = value
	}
	return nil
}

type parsedFlags struct {
	Values      map[string]string
	Bools       map[string]bool
	Positionals []string
}

func (f parsedFlags) Value(name string) string {
	return f.Values[name]
}

func (f parsedFlags) Bool(name string) bool {
	return f.Bools[name]
}

func parseCommandFlags(args []string, bools map[string]bool) (parsedFlags, error) {
	flags := parsedFlags{Values: map[string]string{}, Bools: map[string]bool{}, Positionals: []string{}}
	for i := 0; i < len(args); i++ {
		arg := args[i]
		if !strings.HasPrefix(arg, "--") {
			flags.Positionals = append(flags.Positionals, arg)
			continue
		}
		nameValue := strings.TrimPrefix(arg, "--")
		name, value, hasValue := strings.Cut(nameValue, "=")
		if bools != nil && bools[name] {
			if hasValue {
				flags.Bools[name] = value == "true" || value == "1" || value == "yes"
			} else {
				flags.Bools[name] = true
			}
			continue
		}
		if !hasValue {
			if i+1 >= len(args) {
				return flags, wrapError(ErrorValidation, "--%s requires a value", name)
			}
			i++
			value = args[i]
		}
		flags.Values[name] = value
	}
	return flags, nil
}

func boolSet(names ...string) map[string]bool {
	out := map[string]bool{}
	for _, name := range names {
		out[name] = true
	}
	return out
}

func parseFloatPtr(raw string) *float64 {
	if raw == "" {
		return nil
	}
	value, err := strconv.ParseFloat(raw, 64)
	if err != nil {
		return nil
	}
	return &value
}

func valueOrDefault(value string, fallback string) string {
	if value == "" {
		return fallback
	}
	return value
}
