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

func TestValidateStockIntentAllowsFractionalMarketQuantity(t *testing.T) {
	qty := 0.123456
	err := validateStockIntent(StockOrderIntent{
		Symbol:      "AAPL",
		Side:        "sell",
		Type:        "market",
		Quantity:    &qty,
		QuantityRaw: "0.123456",
	})
	if err != nil {
		t.Fatalf("validateStockIntent returned error: %v", err)
	}
}

func TestValidateStockIntentRejectsFractionalLimitQuantity(t *testing.T) {
	qty := 0.123456
	limit := 200.0
	err := validateStockIntent(StockOrderIntent{
		Symbol:      "AAPL",
		Side:        "sell",
		Type:        "limit",
		Quantity:    &qty,
		QuantityRaw: "0.123456",
		LimitPrice:  &limit,
	})
	if err == nil {
		t.Fatal("validateStockIntent allowed fractional limit quantity")
	}
}

func TestStockTimeInForceForPlaceDefaultsFractionalQuantityToGFD(t *testing.T) {
	qty := 0.123456
	got, err := stockTimeInForceForPlace(parsedFlags{Values: map[string]string{}}, StockOrderIntent{
		Symbol:      "AAPL",
		Side:        "sell",
		Type:        "market",
		Quantity:    &qty,
		QuantityRaw: "0.123456",
	})
	if err != nil {
		t.Fatalf("stockTimeInForceForPlace returned error: %v", err)
	}
	if got != "gfd" {
		t.Fatalf("time in force = %q, want gfd", got)
	}
}

func TestStockTimeInForceForPlaceRejectsNonGFDForFractionalQuantity(t *testing.T) {
	qty := 0.123456
	_, err := stockTimeInForceForPlace(parsedFlags{Values: map[string]string{"time-in-force": "gtc"}}, StockOrderIntent{
		Symbol:      "AAPL",
		Side:        "sell",
		Type:        "market",
		Quantity:    &qty,
		QuantityRaw: "0.123456",
	})
	if err == nil {
		t.Fatalf("stockTimeInForceForPlace allowed fractional quantity with gtc")
	}
}

func TestSellableStockQuantityPreservesExactQuantity(t *testing.T) {
	got, gotFloat, err := sellableStockQuantity(map[string]any{
		"quantity": "0.123456",
	})
	if err != nil {
		t.Fatalf("sellableStockQuantity returned error: %v", err)
	}
	if got != "0.123456" {
		t.Fatalf("quantity = %q, want 0.123456", got)
	}
	if gotFloat != 0.123456 {
		t.Fatalf("quantity float = %v, want 0.123456", gotFloat)
	}
}

func TestSellableStockQuantitySubtractsHeldShares(t *testing.T) {
	got, _, err := sellableStockQuantity(map[string]any{
		"quantity":                       "1.000000",
		"shares_held_for_sells":          "0.250000",
		"shares_held_for_stock_grants":   "0.100000",
		"shares_held_for_options_events": "0.000000",
	})
	if err != nil {
		t.Fatalf("sellableStockQuantity returned error: %v", err)
	}
	if got != "0.65" {
		t.Fatalf("quantity = %q, want 0.65", got)
	}
}
