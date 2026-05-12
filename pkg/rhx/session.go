package rhx

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"time"
)

type Session struct {
	TokenType    string    `json:"token_type"`
	AccessToken  string    `json:"access_token"`
	RefreshToken string    `json:"refresh_token,omitempty"`
	DeviceToken  string    `json:"device_token"`
	CreatedAt    time.Time `json:"created_at"`
}

func sessionPath(sessionDir string, profile string) string {
	return filepath.Join(sessionDir, "robinhood_"+profile+".json")
}

func loadSession(path string) (Session, error) {
	var session Session
	if err := secureFile(path); err != nil {
		return session, err
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return session, err
	}
	if err := json.Unmarshal(data, &session); err != nil {
		return session, err
	}
	return session, nil
}

func saveSession(path string, session Session) error {
	if err := secureDir(filepath.Dir(path)); err != nil {
		return err
	}
	data, err := json.MarshalIndent(session, "", "  ")
	if err != nil {
		return err
	}
	if err := os.WriteFile(path, append(data, '\n'), 0o600); err != nil {
		return err
	}
	return secureFile(path)
}

func deleteSession(path string) {
	_ = os.Remove(path)
}

func randomDeviceToken() string {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return time.Now().UTC().Format("20060102150405.000000000")
	}
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	return hex.EncodeToString(b[0:4]) + "-" +
		hex.EncodeToString(b[4:6]) + "-" +
		hex.EncodeToString(b[6:8]) + "-" +
		hex.EncodeToString(b[8:10]) + "-" +
		hex.EncodeToString(b[10:16])
}
