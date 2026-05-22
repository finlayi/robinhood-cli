package rhx

import "time"

func timeNowUTC() string {
	return time.Now().UTC().Format(time.RFC3339)
}

func nowRFC3339() string {
	return timeNowUTC()
}

func timeRFC3339() string {
	return "2006-01-02T15:04:05Z07:00"
}
