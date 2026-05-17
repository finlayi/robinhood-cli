package rhx

import (
	"path/filepath"
	"testing"
)

func TestSafetyLiveUnlockLifecycle(t *testing.T) {
	cfg := &SafetyConfig{LiveMode: true, LiveUnlockTTLSeconds: 60}
	engine, err := newSafetyEngine(filepath.Join(t.TempDir(), "state.json"), cfg)
	if err != nil {
		t.Fatalf("newSafetyEngine returned error: %v", err)
	}
	token, expiresAt, err := engine.issueLiveUnlock(60)
	if err != nil {
		t.Fatalf("issueLiveUnlock returned error: %v", err)
	}
	if token == "" || expiresAt == 0 {
		t.Fatalf("token/expiresAt not populated")
	}
	if err := engine.requireLiveAuthorization(token); err != nil {
		t.Fatalf("requireLiveAuthorization(valid) returned error: %v", err)
	}
	if err := engine.requireLiveAuthorization("wrong"); err == nil {
		t.Fatalf("requireLiveAuthorization(wrong) succeeded")
	}
	if err := engine.clearLiveUnlock(); err != nil {
		t.Fatalf("clearLiveUnlock returned error: %v", err)
	}
	if err := engine.requireLiveAuthorization(token); err == nil {
		t.Fatalf("requireLiveAuthorization after clear succeeded")
	}
}

func TestSafetyEnforceSymbolPolicy(t *testing.T) {
	max := 100.0
	cfg := &SafetyConfig{
		LiveMode:         true,
		MaxOrderNotional: &max,
		AllowSymbols:     []string{"AAPL"},
	}
	engine, err := newSafetyEngine(filepath.Join(t.TempDir(), "state.json"), cfg)
	if err != nil {
		t.Fatalf("newSafetyEngine returned error: %v", err)
	}
	if err := engine.enforce("AAPL", 50); err != nil {
		t.Fatalf("enforce allowed order returned error: %v", err)
	}
	if err := engine.enforce("MSFT", 50); err == nil {
		t.Fatalf("enforce unallowed symbol succeeded")
	}
	if err := engine.enforce("AAPL", 101); err == nil {
		t.Fatalf("enforce oversized notional succeeded")
	}
}

func TestSafetyReserveReloadsStateBeforeDailyLimit(t *testing.T) {
	maxDaily := 100.0
	cfg := &SafetyConfig{
		LiveMode:         true,
		MaxDailyNotional: &maxDaily,
	}
	path := filepath.Join(t.TempDir(), "state.json")
	first, err := newSafetyEngine(path, cfg)
	if err != nil {
		t.Fatalf("newSafetyEngine(first) returned error: %v", err)
	}
	second, err := newSafetyEngine(path, cfg)
	if err != nil {
		t.Fatalf("newSafetyEngine(second) returned error: %v", err)
	}

	reservation, err := first.reserveNotional("AAPL", 60)
	if err != nil {
		t.Fatalf("first reserveNotional returned error: %v", err)
	}
	defer reservation.release()
	if _, err := second.reserveNotional("AAPL", 60); err == nil {
		t.Fatalf("second reserveNotional succeeded with stale daily state")
	}
}
