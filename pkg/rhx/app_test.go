package rhx

import "testing"

func TestParseGlobalOptionsRemovesKnownFlags(t *testing.T) {
	opts, remaining, err := parseGlobalOptions([]string{
		"--json",
		"--profile", "work",
		"--provider=brokerage",
		"quote", "get", "AAPL",
		"--limit", "5",
	})
	if err != nil {
		t.Fatalf("parseGlobalOptions returned error: %v", err)
	}
	if !opts.Output.JSON {
		t.Fatalf("expected json output")
	}
	if opts.Profile != "work" {
		t.Fatalf("profile = %q, want work", opts.Profile)
	}
	if opts.Provider != "brokerage" {
		t.Fatalf("provider = %q, want brokerage", opts.Provider)
	}
	if opts.Output.Limit != 5 {
		t.Fatalf("limit = %d, want 5", opts.Output.Limit)
	}
	want := []string{"quote", "get", "AAPL"}
	if len(remaining) != len(want) {
		t.Fatalf("remaining = %#v, want %#v", remaining, want)
	}
	for i := range want {
		if remaining[i] != want[i] {
			t.Fatalf("remaining = %#v, want %#v", remaining, want)
		}
	}
}

func TestParseCommandFlags(t *testing.T) {
	flags, err := parseCommandFlags([]string{
		"--symbol", "AAPL",
		"--side=buy",
		"--extended-hours",
		"ignored-positional",
	}, boolSet("extended-hours"))
	if err != nil {
		t.Fatalf("parseCommandFlags returned error: %v", err)
	}
	if flags.Value("symbol") != "AAPL" {
		t.Fatalf("symbol = %q, want AAPL", flags.Value("symbol"))
	}
	if flags.Value("side") != "buy" {
		t.Fatalf("side = %q, want buy", flags.Value("side"))
	}
	if !flags.Bool("extended-hours") {
		t.Fatalf("extended-hours flag not set")
	}
	if len(flags.Positionals) != 1 || flags.Positionals[0] != "ignored-positional" {
		t.Fatalf("positionals = %#v", flags.Positionals)
	}
}

func TestEstimateStockIntent(t *testing.T) {
	qty := 3.0
	limit := 12.50
	got := estimateStockIntent(StockOrderIntent{Quantity: &qty, LimitPrice: &limit})
	if got != 37.5 {
		t.Fatalf("estimate = %v, want 37.5", got)
	}
	notional := 25.0
	got = estimateStockIntent(StockOrderIntent{Quantity: &qty, LimitPrice: &limit, NotionalUSD: &notional})
	if got != 25 {
		t.Fatalf("estimate = %v, want 25", got)
	}
}
