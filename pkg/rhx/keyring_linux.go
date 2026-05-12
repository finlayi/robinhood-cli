//go:build linux

package rhx

import (
	"os/exec"
	"strings"
)

func keyringGet(service string, account string) (string, error) {
	if _, err := exec.LookPath("secret-tool"); err != nil {
		return "", errKeyringUnavailable
	}
	out, err := exec.Command("secret-tool", "lookup", "service", service, "account", account).Output()
	if err != nil {
		return "", errKeyringUnavailable
	}
	return strings.TrimSpace(string(out)), nil
}

func keyringSet(service string, account string, value string) error {
	if _, err := exec.LookPath("secret-tool"); err != nil {
		return errKeyringUnavailable
	}
	cmd := exec.Command("secret-tool", "store", "--label", service+" "+account, "service", service, "account", account)
	cmd.Stdin = strings.NewReader(value)
	if err := cmd.Run(); err != nil {
		return errKeyringUnavailable
	}
	return nil
}

func keyringDelete(service string, account string) error {
	if _, err := exec.LookPath("secret-tool"); err != nil {
		return errKeyringUnavailable
	}
	if err := exec.Command("secret-tool", "clear", "service", service, "account", account).Run(); err != nil {
		return errKeyringUnavailable
	}
	return nil
}
