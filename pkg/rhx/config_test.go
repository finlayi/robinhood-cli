package rhx

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadRuntimeConfigDoesNotChmodCustomParent(t *testing.T) {
	tmp := t.TempDir()
	t.Setenv("HOME", filepath.Join(tmp, "home"))
	parent := filepath.Join(tmp, "shared")
	if err := os.Mkdir(parent, 0o755); err != nil {
		t.Fatalf("Mkdir returned error: %v", err)
	}
	if err := os.Chmod(parent, 0o755); err != nil {
		t.Fatalf("Chmod returned error: %v", err)
	}

	configPath := filepath.Join(parent, "config.toml")
	if _, err := loadRuntimeConfig(configPath, "test"); err != nil {
		t.Fatalf("loadRuntimeConfig returned error: %v", err)
	}

	parentInfo, err := os.Stat(parent)
	if err != nil {
		t.Fatalf("Stat(parent) returned error: %v", err)
	}
	if got := parentInfo.Mode().Perm(); got != 0o755 {
		t.Fatalf("custom parent mode = %o, want 755", got)
	}
	configInfo, err := os.Stat(configPath)
	if err != nil {
		t.Fatalf("Stat(config) returned error: %v", err)
	}
	if got := configInfo.Mode().Perm(); got != 0o600 {
		t.Fatalf("config mode = %o, want 600", got)
	}
}
