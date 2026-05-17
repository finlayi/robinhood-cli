package rhx

import (
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"
)

func TestQuoteListCryptoErrorDoesNotPanic(t *testing.T) {
	t.Setenv("RH_CRYPTO_API_KEY", "")
	t.Setenv("RH_CRYPTO_PRIVATE_KEY_B64", "")
	cfg := testRuntimeConfig(t)
	auth := newAuthManager(cfg)
	safety, err := newSafetyEngine(cfg.Paths.StatePath, &cfg.App.Safety)
	if err != nil {
		t.Fatalf("newSafetyEngine returned error: %v", err)
	}
	rt := &appRuntime{
		cfg:    cfg,
		auth:   auth,
		crypto: newOfficialCryptoProvider(auth),
		safety: safety,
		opts: globalOptions{
			Output:   defaultOutputOptions(),
			Profile:  cfg.App.Profile,
			Provider: "crypto",
		},
	}

	defer func() {
		if recovered := recover(); recovered != nil {
			t.Fatalf("quote list panicked: %v", recovered)
		}
	}()
	if code := rt.dispatchQuote(context.Background(), []string{"list", "--symbols", "BTC-USD"}); code != 0 {
		t.Fatalf("quote list exit code = %d, want 0 for non-strict row error", code)
	}
	if code := rt.dispatchQuote(context.Background(), []string{"list", "--symbols", "BTC-USD", "--strict"}); code == 0 {
		t.Fatalf("strict quote list succeeded")
	}
}

func TestCryptoMarketQuantitySafetyUsesQuote(t *testing.T) {
	t.Setenv("RH_CRYPTO_API_KEY", "test-key")
	t.Setenv("RH_CRYPTO_PRIVATE_KEY_B64", base64.StdEncoding.EncodeToString(make([]byte, ed25519.SeedSize)))
	postCount := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch {
		case r.Method == http.MethodGet && r.URL.Path == "/api/v1/crypto/marketdata/best_bid_ask/":
			_, _ = w.Write([]byte(`{"results":[{"symbol":"BTC-USD","bid_inclusive_of_sell_spread":"59.00","ask_inclusive_of_buy_spread":"60.00"}]}`))
		case r.Method == http.MethodPost && r.URL.Path == "/api/v1/crypto/trading/orders/":
			postCount++
			_, _ = w.Write([]byte(`{"id":"order-id","state":"queued"}`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	cfg := testRuntimeConfig(t)
	cfg.App.Safety.LiveMode = true
	maxOrder := 100.0
	cfg.App.Safety.MaxOrderNotional = &maxOrder
	auth := newAuthManager(cfg)
	crypto := newOfficialCryptoProvider(auth)
	crypto.base = server.URL
	safety, err := newSafetyEngine(cfg.Paths.StatePath, &cfg.App.Safety)
	if err != nil {
		t.Fatalf("newSafetyEngine returned error: %v", err)
	}
	token, _, err := safety.issueLiveUnlock(60)
	if err != nil {
		t.Fatalf("issueLiveUnlock returned error: %v", err)
	}
	rt := &appRuntime{
		cfg:    cfg,
		auth:   auth,
		crypto: crypto,
		safety: safety,
		opts: globalOptions{
			Output:   defaultOutputOptions(),
			Profile:  cfg.App.Profile,
			Provider: "crypto",
		},
	}

	code := rt.placeCrypto(context.Background(), []string{
		"--symbol", "BTC-USD",
		"--side", "buy",
		"--type", "market",
		"--amount-in", "quantity",
		"--qty", "2",
		"--live-confirm-token", token,
	})
	if code == 0 {
		t.Fatalf("oversized crypto quantity order succeeded")
	}
	if postCount != 0 {
		t.Fatalf("crypto order POST count = %d, want 0", postCount)
	}
}

func TestValidateCryptoIntentRejectsMismatchedAmountFields(t *testing.T) {
	qty := 2.0
	notional := 1.0
	err := validateCryptoIntent(CryptoOrderIntent{
		Symbol:      "BTC-USD",
		Side:        "buy",
		Type:        "market",
		AmountIn:    "quantity",
		Quantity:    &qty,
		NotionalUSD: &notional,
	})
	if err == nil {
		t.Fatalf("validateCryptoIntent allowed quantity order with --notional-usd")
	}
}

func testRuntimeConfig(t *testing.T) RuntimeConfig {
	t.Helper()
	tmp := t.TempDir()
	cfg := defaultConfig("test", filepath.Join(tmp, "config.toml"))
	cfg.Paths.StatePath = filepath.Join(tmp, "state.json")
	cfg.Paths.SessionDir = filepath.Join(tmp, "sessions")
	return cfg
}
