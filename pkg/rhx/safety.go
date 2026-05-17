package rhx

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

type SafetyState struct {
	DailyNotional map[string]float64 `json:"daily_notional"`
	LiveUnlock    *LiveUnlockState   `json:"live_unlock,omitempty"`
}

type LiveUnlockState struct {
	TokenHash string `json:"token_hash"`
	ExpiresAt int64  `json:"expires_at"`
}

type SafetyEngine struct {
	Config *SafetyConfig
	Path   string
	State  SafetyState
}

type SafetyReservation struct {
	engine   *SafetyEngine
	value    float64
	released bool
}

func newSafetyEngine(path string, config *SafetyConfig) (*SafetyEngine, error) {
	engine := &SafetyEngine{Config: config, Path: path, State: SafetyState{DailyNotional: map[string]float64{}}}
	if err := secureDir(filepath.Dir(path)); err != nil {
		return nil, err
	}
	if err := engine.load(); err != nil {
		return nil, err
	}
	return engine, nil
}

func (s *SafetyEngine) load() error {
	s.State = SafetyState{DailyNotional: map[string]float64{}}
	if s.Path == "" {
		return nil
	}
	if data, err := os.ReadFile(s.Path); err == nil {
		_ = json.Unmarshal(data, &s.State)
	} else if !os.IsNotExist(err) {
		return err
	}
	if s.State.DailyNotional == nil {
		s.State.DailyNotional = map[string]float64{}
	}
	return nil
}

func (s *SafetyEngine) save() error {
	return s.withStateLock(func() error {
		return s.saveUnlocked()
	})
}

func (s *SafetyEngine) saveUnlocked() error {
	if err := secureDir(filepath.Dir(s.Path)); err != nil {
		return err
	}
	data, err := json.MarshalIndent(s.State, "", "  ")
	if err != nil {
		return err
	}
	if err := os.WriteFile(s.Path, append(data, '\n'), 0o600); err != nil {
		return err
	}
	return secureFile(s.Path)
}

func (s *SafetyEngine) withStateLock(fn func() error) error {
	if s.Path == "" {
		return fn()
	}
	if err := secureDir(filepath.Dir(s.Path)); err != nil {
		return err
	}
	lockPath := s.Path + ".lock"
	deadline := time.Now().UTC().Add(10 * time.Second)
	for {
		lock, err := os.OpenFile(lockPath, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
		if err == nil {
			_, _ = lock.WriteString(strconv.Itoa(os.Getpid()) + "\n")
			_ = lock.Close()
			defer os.Remove(lockPath)
			return fn()
		}
		if !os.IsExist(err) {
			return err
		}
		now := time.Now().UTC()
		if info, statErr := os.Stat(lockPath); statErr == nil && now.Sub(info.ModTime()) > 30*time.Second {
			_ = os.Remove(lockPath)
			continue
		}
		if now.After(deadline) {
			return newError(ErrorSafetyPolicy, "Timed out waiting for safety state lock")
		}
		time.Sleep(25 * time.Millisecond)
	}
}

func (s *SafetyEngine) liveModeEnabled() bool {
	return s.Config != nil && s.Config.LiveMode
}

func (s *SafetyEngine) issueLiveUnlock(ttlSeconds int) (string, int64, error) {
	if ttlSeconds <= 0 {
		ttlSeconds = 900
	}
	raw := make([]byte, 24)
	if _, err := rand.Read(raw); err != nil {
		return "", 0, err
	}
	token := base64.RawURLEncoding.EncodeToString(raw)
	expiresAt := time.Now().UTC().Add(time.Duration(ttlSeconds) * time.Second).Unix()
	if err := s.withStateLock(func() error {
		if err := s.load(); err != nil {
			return err
		}
		s.State.LiveUnlock = &LiveUnlockState{TokenHash: hashToken(token), ExpiresAt: expiresAt}
		return s.saveUnlocked()
	}); err != nil {
		return "", 0, err
	}
	return token, expiresAt, nil
}

func (s *SafetyEngine) clearLiveUnlock() error {
	return s.withStateLock(func() error {
		if err := s.load(); err != nil {
			return err
		}
		s.State.LiveUnlock = nil
		return s.saveUnlocked()
	})
}

func (s *SafetyEngine) liveUnlockStatus() map[string]any {
	if s.State.LiveUnlock == nil {
		return map[string]any{"active": false, "expires_at": nil}
	}
	active := s.State.LiveUnlock.ExpiresAt > time.Now().UTC().Unix()
	return map[string]any{"active": active, "expires_at": s.State.LiveUnlock.ExpiresAt}
}

func (s *SafetyEngine) requireLiveAuthorization(token string) error {
	if !s.liveModeEnabled() {
		return newError(ErrorLiveModeOff, "Live mode is OFF. Enable with `rhx live on`.")
	}
	if err := s.withStateLock(func() error {
		return s.load()
	}); err != nil {
		return err
	}
	if token == "" {
		return newError(ErrorSafetyPolicy, "Missing live confirmation token. Run `rhx live on` and pass --live-confirm-token.")
	}
	if s.State.LiveUnlock == nil {
		return newError(ErrorSafetyPolicy, "No active live unlock token. Run `rhx live on` again.")
	}
	if s.State.LiveUnlock.ExpiresAt <= time.Now().UTC().Unix() {
		return newError(ErrorSafetyPolicy, "Live confirmation token expired. Run `rhx live on` again.")
	}
	if hashToken(token) != s.State.LiveUnlock.TokenHash {
		return newError(ErrorSafetyPolicy, "Invalid live confirmation token.")
	}
	return nil
}

func hashToken(token string) string {
	sum := sha256.Sum256([]byte(token))
	return hex.EncodeToString(sum[:])
}

func (s *SafetyEngine) enforce(symbol string, estimatedNotional float64) error {
	normalized := strings.ToUpper(symbol)
	allow := symbolSet(s.Config.AllowSymbols)
	block := symbolSet(s.Config.BlockSymbols)
	if len(allow) > 0 && !allow[normalized] {
		return wrapError(ErrorSafetyPolicy, "Symbol %s is not in allow list", normalized)
	}
	if block[normalized] {
		return wrapError(ErrorSafetyPolicy, "Symbol %s is blocked by policy", normalized)
	}
	if err := s.checkTradingWindow(); err != nil {
		return err
	}
	if s.Config.MaxOrderNotional != nil && estimatedNotional > *s.Config.MaxOrderNotional {
		return wrapError(ErrorSafetyPolicy, "Estimated order notional %.2f exceeds max_order_notional %.2f", estimatedNotional, *s.Config.MaxOrderNotional)
	}
	if s.Config.MaxDailyNotional != nil {
		projected := s.todayNotional() + estimatedNotional
		if projected > *s.Config.MaxDailyNotional {
			return wrapError(ErrorSafetyPolicy, "Projected daily notional %.2f exceeds max_daily_notional %.2f", projected, *s.Config.MaxDailyNotional)
		}
	}
	return nil
}

func (s *SafetyEngine) reserveNotional(symbol string, estimatedNotional float64) (*SafetyReservation, error) {
	reservation := &SafetyReservation{engine: s}
	err := s.withStateLock(func() error {
		if err := s.load(); err != nil {
			return err
		}
		if err := s.enforce(symbol, estimatedNotional); err != nil {
			return err
		}
		if estimatedNotional <= 0 {
			return nil
		}
		day := time.Now().UTC().Format("2006-01-02")
		s.State.DailyNotional[day] += estimatedNotional
		reservation.value = estimatedNotional
		return s.saveUnlocked()
	})
	if err != nil {
		return nil, err
	}
	return reservation, nil
}

func (r *SafetyReservation) release() error {
	if r == nil || r.engine == nil || r.value <= 0 || r.released {
		return nil
	}
	r.released = true
	return r.engine.releaseNotional(r.value)
}

func (s *SafetyEngine) releaseNotional(value float64) error {
	if value <= 0 {
		return nil
	}
	return s.withStateLock(func() error {
		if err := s.load(); err != nil {
			return err
		}
		day := time.Now().UTC().Format("2006-01-02")
		remaining := s.State.DailyNotional[day] - value
		if remaining <= 0 {
			delete(s.State.DailyNotional, day)
		} else {
			s.State.DailyNotional[day] = remaining
		}
		return s.saveUnlocked()
	})
}

func (s *SafetyEngine) checkTradingWindow() error {
	window := strings.TrimSpace(s.Config.TradingWindow)
	if window == "" {
		return nil
	}
	startRaw, endRaw, ok := strings.Cut(window, "-")
	if !ok {
		return newError(ErrorValidation, "Invalid trading_window format; expected HH:MM-HH:MM")
	}
	start, err := parseClock(startRaw)
	if err != nil {
		return err
	}
	end, err := parseClock(endRaw)
	if err != nil {
		return err
	}
	now := time.Now()
	current := now.Hour()*60 + now.Minute()
	allowed := false
	if start <= end {
		allowed = current >= start && current <= end
	} else {
		allowed = current >= start || current <= end
	}
	if !allowed {
		return newError(ErrorSafetyPolicy, "Trading is outside configured trading_window")
	}
	return nil
}

func parseClock(raw string) (int, error) {
	raw = strings.TrimSpace(raw)
	parts := strings.Split(raw, ":")
	if len(parts) != 2 {
		return 0, newError(ErrorValidation, "Invalid trading_window format; expected HH:MM-HH:MM")
	}
	hour, err := strconv.Atoi(parts[0])
	if err != nil {
		return 0, newError(ErrorValidation, "Invalid trading_window hour")
	}
	minute, err := strconv.Atoi(parts[1])
	if err != nil {
		return 0, newError(ErrorValidation, "Invalid trading_window minute")
	}
	if hour < 0 || hour > 23 || minute < 0 || minute > 59 {
		return 0, newError(ErrorValidation, "Invalid trading_window clock")
	}
	return hour*60 + minute, nil
}

func symbolSet(values []string) map[string]bool {
	out := map[string]bool{}
	for _, value := range values {
		out[strings.ToUpper(strings.TrimSpace(value))] = true
	}
	return out
}

func (s *SafetyEngine) todayNotional() float64 {
	day := time.Now().UTC().Format("2006-01-02")
	return s.State.DailyNotional[day]
}

func (s *SafetyEngine) recordNotional(value float64) error {
	if value <= 0 {
		return nil
	}
	return s.withStateLock(func() error {
		if err := s.load(); err != nil {
			return err
		}
		day := time.Now().UTC().Format("2006-01-02")
		s.State.DailyNotional[day] += value
		return s.saveUnlocked()
	})
}
