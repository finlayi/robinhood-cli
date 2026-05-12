package rhx

import (
	"os"
	"strings"
)

func osGetenv(key string) string {
	return os.Getenv(key)
}

func stringsTrim(value string) string {
	return strings.TrimSpace(value)
}
