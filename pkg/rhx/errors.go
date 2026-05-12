package rhx

import (
	"errors"
	"fmt"
)

type ErrorCode string

const (
	ErrorValidation     ErrorCode = "VALIDATION_ERROR"
	ErrorAuthRequired   ErrorCode = "AUTH_REQUIRED"
	ErrorMFARequired    ErrorCode = "MFA_REQUIRED"
	ErrorRateLimited    ErrorCode = "RATE_LIMITED"
	ErrorBrokerRejected ErrorCode = "BROKER_REJECTED"
	ErrorLiveModeOff    ErrorCode = "LIVE_MODE_OFF"
	ErrorSafetyPolicy   ErrorCode = "SAFETY_POLICY_BLOCK"
	ErrorInternal       ErrorCode = "INTERNAL_ERROR"
)

type CLIError struct {
	Code      ErrorCode `json:"code"`
	Message   string    `json:"message"`
	Retriable bool      `json:"retriable"`
	ExitCode  int       `json:"-"`
}

func (e *CLIError) Error() string {
	if e == nil {
		return ""
	}
	return e.Message
}

func newError(code ErrorCode, message string) *CLIError {
	exitCode := 1
	if code == ErrorValidation {
		exitCode = 2
	}
	return &CLIError{Code: code, Message: message, ExitCode: exitCode}
}

func wrapError(code ErrorCode, format string, args ...any) *CLIError {
	return newError(code, fmt.Sprintf(format, args...))
}

func cliError(err error) *CLIError {
	if err == nil {
		return nil
	}
	var ce *CLIError
	if errors.As(err, &ce) {
		if ce.ExitCode == 0 {
			ce.ExitCode = 1
			if ce.Code == ErrorValidation {
				ce.ExitCode = 2
			}
		}
		return ce
	}
	return newError(ErrorInternal, err.Error())
}
