//go:build darwin

package rhx

import (
	"errors"
	"os/exec"
	"strings"
)

func keyringGet(service string, account string) (string, error) {
	out, err := exec.Command("security", "find-generic-password", "-s", service, "-a", account, "-w").Output()
	if err != nil {
		return "", errKeyringUnavailable
	}
	return strings.TrimSpace(string(out)), nil
}

func keyringSet(service string, account string, value string) error {
	if err := keyringDelete(service, account); err != nil && !errors.Is(err, errKeyringUnavailable) {
		return err
	}
	cmd := exec.Command("security", "add-generic-password", "-U", "-s", service, "-a", account, "-w", value)
	if err := cmd.Run(); err != nil {
		return errKeyringUnavailable
	}
	return nil
}

func keyringDelete(service string, account string) error {
	cmd := exec.Command("security", "delete-generic-password", "-s", service, "-a", account)
	if err := cmd.Run(); err != nil {
		return errKeyringUnavailable
	}
	return nil
}
