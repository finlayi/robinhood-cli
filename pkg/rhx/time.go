package rhx

import "time"

func timeNowUTC() string {
	return time.Now().UTC().Format(time.RFC3339)
}
