package rhx

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

type SafetyConfig struct {
	LiveMode             bool
	LiveUnlockTTLSeconds int
	MaxOrderNotional     *float64
	MaxDailyNotional     *float64
	AllowSymbols         []string
	BlockSymbols         []string
	TradingWindow        string
}

type AppConfig struct {
	Profile         string
	ProviderDefault string
	Safety          SafetyConfig
}

type RuntimePaths struct {
	ConfigPath string
	StatePath  string
	SessionDir string
}

type RuntimeConfig struct {
	App   AppConfig
	Paths RuntimePaths
}

func defaultConfigPath() string {
	return filepath.Join(homeDir(), ".config", "robinhood-cli", "config.toml")
}

func defaultStatePath() string {
	return filepath.Join(homeDir(), ".local", "share", "robinhood-cli", "state.json")
}

func defaultSessionDir() string {
	return filepath.Join(homeDir(), ".config", "robinhood-cli", "sessions")
}

func homeDir() string {
	home, err := os.UserHomeDir()
	if err != nil || home == "" {
		return "."
	}
	return home
}

func defaultConfig(profile string, configPath string) RuntimeConfig {
	if profile == "" {
		profile = "default"
	}
	if configPath == "" {
		configPath = defaultConfigPath()
	}
	return RuntimeConfig{
		App: AppConfig{
			Profile:         profile,
			ProviderDefault: "auto",
			Safety: SafetyConfig{
				LiveUnlockTTLSeconds: 900,
			},
		},
		Paths: RuntimePaths{
			ConfigPath: configPath,
			StatePath:  defaultStatePath(),
			SessionDir: defaultSessionDir(),
		},
	}
}

func loadRuntimeConfig(configPath string, profile string) (RuntimeConfig, error) {
	cfg := defaultConfig(profile, configPath)
	if err := secureConfigParent(cfg.Paths.ConfigPath); err != nil {
		return cfg, err
	}
	if err := secureDir(filepath.Dir(cfg.Paths.StatePath)); err != nil {
		return cfg, err
	}
	if err := secureDir(cfg.Paths.SessionDir); err != nil {
		return cfg, err
	}

	if _, err := os.Stat(cfg.Paths.ConfigPath); os.IsNotExist(err) {
		if err := saveRuntimeConfig(cfg); err != nil {
			return cfg, err
		}
		return cfg, nil
	} else if err != nil {
		return cfg, err
	}

	if err := secureFile(cfg.Paths.ConfigPath); err != nil {
		return cfg, err
	}
	file, err := os.Open(cfg.Paths.ConfigPath)
	if err != nil {
		return cfg, err
	}
	defer file.Close()

	section := ""
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		if strings.HasPrefix(line, "[") && strings.HasSuffix(line, "]") {
			section = strings.TrimSpace(strings.TrimSuffix(strings.TrimPrefix(line, "["), "]"))
			continue
		}
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		key = strings.TrimSpace(key)
		value = strings.TrimSpace(value)
		switch section {
		case "":
			switch key {
			case "profile":
				cfg.App.Profile = parseTomlString(value)
			case "provider_default":
				cfg.App.ProviderDefault = parseTomlString(value)
			}
		case "safety":
			parseSafetyField(&cfg.App.Safety, key, value)
		}
	}
	if err := scanner.Err(); err != nil {
		return cfg, err
	}
	if profile != "" {
		cfg.App.Profile = profile
	}
	if cfg.App.ProviderDefault == "" {
		cfg.App.ProviderDefault = "auto"
	}
	if cfg.App.Safety.LiveUnlockTTLSeconds <= 0 {
		cfg.App.Safety.LiveUnlockTTLSeconds = 900
	}
	return cfg, nil
}

func parseSafetyField(s *SafetyConfig, key string, value string) {
	switch key {
	case "live_mode":
		s.LiveMode = strings.EqualFold(value, "true")
	case "live_unlock_ttl_seconds":
		if n, err := strconv.Atoi(value); err == nil {
			s.LiveUnlockTTLSeconds = n
		}
	case "max_order_notional":
		s.MaxOrderNotional = parseTomlOptionalFloat(value)
	case "max_daily_notional":
		s.MaxDailyNotional = parseTomlOptionalFloat(value)
	case "allow_symbols":
		s.AllowSymbols = parseTomlStringArray(value)
	case "block_symbols":
		s.BlockSymbols = parseTomlStringArray(value)
	case "trading_window":
		s.TradingWindow = parseTomlString(value)
	}
}

func saveRuntimeConfig(cfg RuntimeConfig) error {
	if err := secureConfigParent(cfg.Paths.ConfigPath); err != nil {
		return err
	}
	var b strings.Builder
	fmt.Fprintf(&b, "profile = %q\n", cfg.App.Profile)
	fmt.Fprintf(&b, "provider_default = %q\n\n", cfg.App.ProviderDefault)
	fmt.Fprintf(&b, "[safety]\n")
	fmt.Fprintf(&b, "live_mode = %t\n", cfg.App.Safety.LiveMode)
	fmt.Fprintf(&b, "live_unlock_ttl_seconds = %d\n", cfg.App.Safety.LiveUnlockTTLSeconds)
	if cfg.App.Safety.MaxOrderNotional != nil {
		fmt.Fprintf(&b, "max_order_notional = %s\n", strconv.FormatFloat(*cfg.App.Safety.MaxOrderNotional, 'f', -1, 64))
	}
	if cfg.App.Safety.MaxDailyNotional != nil {
		fmt.Fprintf(&b, "max_daily_notional = %s\n", strconv.FormatFloat(*cfg.App.Safety.MaxDailyNotional, 'f', -1, 64))
	}
	fmt.Fprintf(&b, "allow_symbols = %s\n", formatTomlStringArray(cfg.App.Safety.AllowSymbols))
	fmt.Fprintf(&b, "block_symbols = %s\n", formatTomlStringArray(cfg.App.Safety.BlockSymbols))
	if cfg.App.Safety.TradingWindow != "" {
		fmt.Fprintf(&b, "trading_window = %q\n", cfg.App.Safety.TradingWindow)
	}
	if err := os.WriteFile(cfg.Paths.ConfigPath, []byte(b.String()), 0o600); err != nil {
		return err
	}
	return secureFile(cfg.Paths.ConfigPath)
}

func parseTomlString(value string) string {
	value = strings.TrimSpace(value)
	if len(value) >= 2 && value[0] == '"' && value[len(value)-1] == '"' {
		if unquoted, err := strconv.Unquote(value); err == nil {
			return unquoted
		}
	}
	return value
}

func parseTomlOptionalFloat(value string) *float64 {
	value = strings.TrimSpace(value)
	if value == "" {
		return nil
	}
	f, err := strconv.ParseFloat(value, 64)
	if err != nil {
		return nil
	}
	return &f
}

func parseTomlStringArray(value string) []string {
	value = strings.TrimSpace(value)
	if value == "" || value == "[]" {
		return nil
	}
	value = strings.TrimPrefix(strings.TrimSuffix(value, "]"), "[")
	parts := strings.Split(value, ",")
	out := []string{}
	for _, part := range parts {
		item := strings.TrimSpace(part)
		if item == "" {
			continue
		}
		out = append(out, strings.ToUpper(parseTomlString(item)))
	}
	return out
}

func formatTomlStringArray(values []string) string {
	if len(values) == 0 {
		return "[]"
	}
	quoted := make([]string, 0, len(values))
	for _, value := range values {
		quoted = append(quoted, strconv.Quote(strings.ToUpper(value)))
	}
	return "[" + strings.Join(quoted, ", ") + "]"
}

func secureConfigParent(configPath string) error {
	parent := filepath.Dir(configPath)
	if filepath.Clean(configPath) == filepath.Clean(defaultConfigPath()) {
		return secureDir(parent)
	}
	return ensureConfigParent(parent)
}

func ensureConfigParent(path string) error {
	if path == "" || path == "." {
		return nil
	}
	info, err := os.Lstat(path)
	if os.IsNotExist(err) {
		return os.MkdirAll(path, 0o700)
	}
	if err != nil {
		return err
	}
	if info.Mode()&os.ModeSymlink != 0 {
		return wrapError(ErrorAuthRequired, "Refusing symlinked directory: %s", path)
	}
	if !info.IsDir() {
		return wrapError(ErrorAuthRequired, "Path is not a directory: %s", path)
	}
	return nil
}

func secureDir(path string) error {
	if path == "" || path == "." {
		return nil
	}
	info, err := os.Lstat(path)
	if os.IsNotExist(err) {
		return os.MkdirAll(path, 0o700)
	}
	if err != nil {
		return err
	}
	if info.Mode()&os.ModeSymlink != 0 {
		return wrapError(ErrorAuthRequired, "Refusing symlinked directory: %s", path)
	}
	if !info.IsDir() {
		return wrapError(ErrorAuthRequired, "Path is not a directory: %s", path)
	}
	return os.Chmod(path, 0o700)
}

func secureFile(path string) error {
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if info.Mode()&os.ModeSymlink != 0 {
		return wrapError(ErrorAuthRequired, "Refusing symlinked file: %s", path)
	}
	return os.Chmod(path, 0o600)
}
