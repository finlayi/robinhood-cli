//go:build !darwin && !linux

package rhx

func keyringGet(service string, account string) (string, error) {
	return "", errKeyringUnavailable
}

func keyringSet(service string, account string, value string) error {
	return errKeyringUnavailable
}

func keyringDelete(service string, account string) error {
	return errKeyringUnavailable
}
