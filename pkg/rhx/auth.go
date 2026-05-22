package rhx

import (
	"bufio"
	"context"
	"fmt"
	"net/url"
	"os"
	"strings"
	"time"

	"golang.org/x/term"
)

const brokerageClientID = "c82SH0WZOsabOXGP2sxqcj34FxkvfnWRZBKlBjFS"

var authPollInterval = 5 * time.Second

type AuthStatus struct {
	Provider      string `json:"provider"`
	Authenticated bool   `json:"authenticated"`
	MFARequired   bool   `json:"mfa_required"`
	State         string `json:"state"`
	Detail        string `json:"detail,omitempty"`
}

type BrokeragePassiveStatus struct {
	SessionFileExists  bool   `json:"session_file_exists"`
	CredentialsPresent bool   `json:"credentials_present"`
	SessionReady       bool   `json:"session_ready"`
	Detail             string `json:"detail"`
}

type AuthManager struct {
	Profile     string
	SessionPath string
	Store       CredentialStore
	Client      *HTTPClient
}

type brokerageAuthOptions struct {
	PromptForCredentials bool
	WaitForChallenge     bool
	AllowPasswordLogin   bool
	Force                bool
}

func newAuthManager(cfg RuntimeConfig) *AuthManager {
	var session *Session
	if loaded, err := loadSession(sessionPath(cfg.Paths.SessionDir, cfg.App.Profile)); err == nil {
		session = &loaded
	}
	return &AuthManager{
		Profile:     cfg.App.Profile,
		SessionPath: sessionPath(cfg.Paths.SessionDir, cfg.App.Profile),
		Store:       CredentialStore{},
		Client:      newHTTPClient(session),
	}
}

func (a *AuthManager) passiveStatus() BrokeragePassiveStatus {
	_, statErr := os.Stat(a.SessionPath)
	sessionExists := statErr == nil
	username, password, _ := a.Store.brokerageCredentials(a.Profile)
	creds := username != "" && password != ""
	detail := "No brokerage session or credentials detected"
	if sessionExists && creds {
		detail = "Session file and credentials are available"
	} else if sessionExists {
		detail = "Session file is available"
	} else if creds {
		detail = "Credentials are available"
	}
	return BrokeragePassiveStatus{
		SessionFileExists:  sessionExists,
		CredentialsPresent: creds,
		SessionReady:       sessionExists || creds,
		Detail:             detail,
	}
}

func (a *AuthManager) brokerageStatus(ctx context.Context) AuthStatus {
	waitForChallenge := canWaitForAuthChallenge()
	_, err := a.ensureBrokerageAuthenticatedWithOptions(ctx, brokerageAuthOptions{
		WaitForChallenge:   waitForChallenge,
		AllowPasswordLogin: waitForChallenge,
	})
	if err == nil {
		return AuthStatus{Provider: "brokerage", Authenticated: true, State: "READY", Detail: "Authenticated"}
	}
	ce := cliError(err)
	return AuthStatus{
		Provider:      "brokerage",
		Authenticated: false,
		MFARequired:   ce.Code == ErrorMFARequired,
		State:         authStateFromError(ce),
		Detail:        ce.Message,
	}
}

func (a *AuthManager) ensureBrokerageAuthenticated(ctx context.Context, interactive bool, force bool) (Session, error) {
	return a.ensureBrokerageAuthenticatedWithOptions(ctx, brokerageAuthOptions{
		PromptForCredentials: interactive,
		WaitForChallenge:     interactive,
		AllowPasswordLogin:   true,
		Force:                force,
	})
}

func (a *AuthManager) ensureBrokerageAuthenticatedWithOptions(ctx context.Context, opts brokerageAuthOptions) (Session, error) {
	if opts.Force {
		deleteSession(a.SessionPath)
		a.Client.clearSession()
	}
	if !opts.Force {
		if session, err := loadSession(a.SessionPath); err == nil && session.AccessToken != "" {
			a.Client.setSession(session)
			err := a.verifyToken(ctx)
			if err == nil {
				return session, nil
			}
			if cliError(err).Code != ErrorAuthRequired {
				return Session{}, err
			}
			if session.RefreshToken != "" {
				a.Client.clearSession()
				refreshed, refreshErr := a.refreshSession(ctx, session, opts.WaitForChallenge)
				if refreshErr == nil {
					if err := saveSession(a.SessionPath, refreshed); err != nil {
						return Session{}, err
					}
					a.Client.setSession(refreshed)
					return refreshed, nil
				}
				if cliError(refreshErr).Code != ErrorAuthRequired {
					return Session{}, refreshErr
				}
			}
			if !opts.AllowPasswordLogin {
				return Session{}, newError(ErrorAuthRequired, "Stored Robinhood session expired and could not be refreshed. Run `rhx auth login`.")
			}
		} else if !opts.AllowPasswordLogin {
			return Session{}, newError(ErrorAuthRequired, "No active Robinhood session. Run `rhx auth login`.")
		}
	}

	username, password, _ := a.Store.brokerageCredentials(a.Profile)
	if opts.PromptForCredentials {
		var err error
		username, password, err = promptForMissingCredentials(username, password)
		if err != nil {
			return Session{}, err
		}
	}
	if username == "" || password == "" {
		return Session{}, newError(ErrorAuthRequired, "Missing Robinhood username/password")
	}
	a.Client.clearSession()
	session, err := a.login(ctx, username, password, opts.WaitForChallenge)
	if err != nil {
		return Session{}, err
	}
	if err := saveSession(a.SessionPath, session); err != nil {
		return Session{}, err
	}
	if err := a.Store.saveBrokerageCredentials(a.Profile, username, password); err != nil && opts.PromptForCredentials {
		fmt.Fprintf(os.Stderr, "warning: could not save credentials to secure keyring: %v\n", err)
	}
	a.Client.setSession(session)
	return session, nil
}

func (a *AuthManager) verifyToken(ctx context.Context) error {
	_, err := a.Client.get(ctx, robinhoodAPIBase+"/positions/", map[string]string{"nonzero": "true"})
	return err
}

func (a *AuthManager) refreshSession(ctx context.Context, session Session, waitForChallenge bool) (Session, error) {
	form := url.Values{}
	form.Set("client_id", brokerageClientID)
	form.Set("expires_in", "86400")
	form.Set("grant_type", "refresh_token")
	form.Set("refresh_token", session.RefreshToken)
	form.Set("scope", "internal")
	if session.DeviceToken != "" {
		form.Set("device_token", session.DeviceToken)
	}
	data, status, err := a.Client.postFormRaw(ctx, robinhoodAPIBase+"/oauth2/token/", form)
	if err != nil {
		return Session{}, err
	}
	payload := asMap(data)
	if workflowID := verificationWorkflowID(payload); workflowID != "" {
		if !waitForChallenge {
			return Session{}, newError(ErrorMFARequired, challengeDetail(payload))
		}
		fmt.Fprintln(os.Stderr, "Verification required. Complete the Robinhood challenge to refresh this session.")
		if err := a.validateVerificationWorkflow(ctx, session.DeviceToken, workflowID); err != nil {
			return Session{}, err
		}
		data, status, err = a.Client.postFormRaw(ctx, robinhoodAPIBase+"/oauth2/token/", form)
		if err != nil {
			return Session{}, err
		}
		payload = asMap(data)
	}
	return sessionFromTokenPayload(payload, status, session.DeviceToken, session.RefreshToken)
}

func (a *AuthManager) login(ctx context.Context, username string, password string, waitForChallenge bool) (Session, error) {
	deviceToken := randomDeviceToken()
	if old, err := loadSession(a.SessionPath); err == nil && old.DeviceToken != "" {
		deviceToken = old.DeviceToken
	}
	form := url.Values{}
	form.Set("client_id", brokerageClientID)
	form.Set("expires_in", "86400")
	form.Set("grant_type", "password")
	form.Set("password", password)
	form.Set("scope", "internal")
	form.Set("username", username)
	form.Set("device_token", deviceToken)
	form.Set("try_passkeys", "false")
	form.Set("token_request_path", "/login")
	form.Set("create_read_only_secondary_token", "true")
	if mfa := envOrNone("RH_MFA_CODE"); mfa != "" {
		form.Set("mfa_code", mfa)
	}
	data, status, err := a.Client.postFormRaw(ctx, robinhoodAPIBase+"/oauth2/token/", form)
	if err != nil {
		return Session{}, err
	}
	payload := asMap(data)
	if workflowID := verificationWorkflowID(payload); workflowID != "" {
		if !waitForChallenge {
			return Session{}, newError(ErrorMFARequired, challengeDetail(payload))
		}
		fmt.Fprintln(os.Stderr, "Verification required. Complete the Robinhood challenge to approve this device.")
		if err := a.validateVerificationWorkflow(ctx, deviceToken, workflowID); err != nil {
			return Session{}, err
		}
		data, status, err = a.Client.postFormRaw(ctx, robinhoodAPIBase+"/oauth2/token/", form)
		if err != nil {
			return Session{}, err
		}
		payload = asMap(data)
	}
	return sessionFromTokenPayload(payload, status, deviceToken, "")
}

func sessionFromTokenPayload(payload map[string]any, status int, deviceToken string, fallbackRefreshToken string) (Session, error) {
	if hasMFAChallenge(payload) {
		return Session{}, newError(ErrorMFARequired, challengeDetail(payload))
	}
	if status >= 400 {
		return Session{}, newError(ErrorAuthRequired, challengeDetail(payload))
	}
	accessToken, _ := payload["access_token"].(string)
	if accessToken == "" {
		return Session{}, newError(ErrorAuthRequired, "Brokerage authentication failed")
	}
	tokenType, _ := payload["token_type"].(string)
	if tokenType == "" {
		tokenType = "Bearer"
	}
	refreshToken, _ := payload["refresh_token"].(string)
	if refreshToken == "" {
		refreshToken = fallbackRefreshToken
	}
	return Session{
		TokenType:    tokenType,
		AccessToken:  accessToken,
		RefreshToken: refreshToken,
		DeviceToken:  deviceToken,
		CreatedAt:    time.Now().UTC(),
	}, nil
}

func (a *AuthManager) validateVerificationWorkflow(ctx context.Context, deviceToken string, workflowID string) error {
	machinePayload := map[string]any{
		"device_id": deviceToken,
		"flow":      "suv",
		"input": map[string]any{
			"workflow_id": workflowID,
		},
	}
	data, status, err := a.Client.postJSONRaw(ctx, robinhoodAPIBase+"/pathfinder/user_machine/", machinePayload)
	if err != nil {
		return err
	}
	if status >= 400 {
		return newError(ErrorMFARequired, compactData(data, status))
	}
	machineID, _ := asMap(data)["id"].(string)
	if machineID == "" {
		return newError(ErrorMFARequired, "No verification machine id returned")
	}

	inquiryURL := robinhoodAPIBase + "/pathfinder/inquiries/" + machineID + "/user_view/"
	deadline := time.Now().Add(2 * time.Minute)
	if err := a.waitForSheriffChallenge(ctx, inquiryURL, deadline); err != nil {
		return err
	}
	return a.waitForWorkflowApproval(ctx, inquiryURL, deadline)
}

func (a *AuthManager) waitForSheriffChallenge(ctx context.Context, inquiryURL string, deadline time.Time) error {
	for time.Now().Before(deadline) {
		if err := sleepContext(ctx, authPollInterval); err != nil {
			return err
		}
		data, _, err := a.Client.getRaw(ctx, inquiryURL, nil)
		if err != nil {
			continue
		}
		challenge := sheriffChallenge(data)
		if len(challenge) == 0 {
			continue
		}
		challengeType, _ := challenge["type"].(string)
		challengeStatus, _ := challenge["status"].(string)
		challengeID, _ := challenge["id"].(string)
		if challengeStatus == "validated" {
			return nil
		}
		switch challengeType {
		case "prompt":
			if challengeID == "" {
				return newError(ErrorMFARequired, "Robinhood app prompt challenge missing id")
			}
			fmt.Fprintln(os.Stderr, "Check the Robinhood app and approve the device login prompt.")
			return a.waitForPromptChallenge(ctx, challengeID, deadline)
		case "sms", "email":
			if challengeStatus != "issued" {
				continue
			}
			if challengeID == "" {
				return newError(ErrorMFARequired, "Robinhood verification challenge missing id")
			}
			if !canPromptForVerificationCode() {
				return newError(ErrorMFARequired, "Robinhood verification code required. Run `rhx auth login` in an interactive terminal.")
			}
			code, err := promptVerificationCode(challengeType)
			if err != nil {
				return err
			}
			form := url.Values{}
			form.Set("response", code)
			data, status, err := a.Client.postFormRaw(ctx, robinhoodAPIBase+"/challenge/"+challengeID+"/respond/", form)
			if err != nil {
				return err
			}
			if status >= 400 {
				return newError(ErrorMFARequired, compactData(data, status))
			}
			if asMap(data)["status"] == "validated" {
				return nil
			}
		}
	}
	return newError(ErrorMFARequired, "Robinhood verification challenge timed out")
}

func (a *AuthManager) waitForPromptChallenge(ctx context.Context, challengeID string, deadline time.Time) error {
	promptURL := robinhoodAPIBase + "/push/" + challengeID + "/get_prompts_status/"
	for time.Now().Before(deadline) {
		if err := sleepContext(ctx, authPollInterval); err != nil {
			return err
		}
		data, _, err := a.Client.getRaw(ctx, promptURL, nil)
		if err != nil {
			continue
		}
		status, _ := asMap(data)["challenge_status"].(string)
		if status == "validated" {
			return nil
		}
	}
	return newError(ErrorMFARequired, "Robinhood app approval timed out")
}

func (a *AuthManager) waitForWorkflowApproval(ctx context.Context, inquiryURL string, deadline time.Time) error {
	for time.Now().Before(deadline) {
		data, status, err := a.Client.postJSONRaw(ctx, inquiryURL, map[string]any{
			"sequence": 0,
			"user_input": map[string]any{
				"status": "continue",
			},
		})
		if err == nil && status < 500 {
			if workflowApproved(data) {
				fmt.Fprintln(os.Stderr, "Robinhood verification approved.")
				return nil
			}
		}
		if err := sleepContext(ctx, authPollInterval); err != nil {
			return err
		}
	}
	return newError(ErrorMFARequired, "Robinhood verification workflow timed out")
}

func canWaitForAuthChallenge() bool {
	return term.IsTerminal(int(os.Stdin.Fd())) || term.IsTerminal(int(os.Stderr.Fd()))
}

func canPromptForVerificationCode() bool {
	return term.IsTerminal(int(os.Stdin.Fd()))
}

func hasMFAChallenge(payload map[string]any) bool {
	for _, key := range []string{"verification_workflow", "mfa_required", "challenge"} {
		if _, ok := payload[key]; ok {
			return true
		}
	}
	return false
}

func verificationWorkflowID(payload map[string]any) string {
	workflow := asMap(payload["verification_workflow"])
	id, _ := workflow["id"].(string)
	return id
}

func sheriffChallenge(data any) map[string]any {
	contextPayload := asMap(asMap(data)["context"])
	return asMap(contextPayload["sheriff_challenge"])
}

func workflowApproved(data any) bool {
	payload := asMap(data)
	typeContext := asMap(payload["type_context"])
	if result, _ := typeContext["result"].(string); result == "workflow_status_approved" {
		return true
	}
	workflow := asMap(payload["verification_workflow"])
	status, _ := workflow["workflow_status"].(string)
	return status == "workflow_status_approved"
}

func challengeDetail(payload map[string]any) string {
	for _, key := range []string{"detail", "message", "error"} {
		if value, ok := payload[key].(string); ok && value != "" {
			return value
		}
	}
	if hasMFAChallenge(payload) {
		return "MFA challenge required"
	}
	return "Brokerage authentication failed"
}

func promptVerificationCode(challengeType string) (string, error) {
	reader := bufio.NewReader(os.Stdin)
	fmt.Fprintf(os.Stderr, "Enter the %s verification code sent by Robinhood: ", challengeType)
	line, err := reader.ReadString('\n')
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(line), nil
}

func sleepContext(ctx context.Context, duration time.Duration) error {
	timer := time.NewTimer(duration)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}

func promptForMissingCredentials(username string, password string) (string, string, error) {
	reader := bufio.NewReader(os.Stdin)
	if username == "" {
		fmt.Fprint(os.Stderr, "Robinhood username: ")
		line, err := reader.ReadString('\n')
		if err != nil {
			return "", "", err
		}
		username = strings.TrimSpace(line)
	}
	if password == "" {
		fmt.Fprint(os.Stderr, "Robinhood password: ")
		if term.IsTerminal(int(os.Stdin.Fd())) {
			raw, err := term.ReadPassword(int(os.Stdin.Fd()))
			fmt.Fprintln(os.Stderr)
			if err != nil {
				return "", "", err
			}
			password = strings.TrimSpace(string(raw))
		} else {
			line, err := reader.ReadString('\n')
			if err != nil {
				return "", "", err
			}
			password = strings.TrimSpace(line)
		}
	}
	return username, password, nil
}

func (a *AuthManager) logout(forgetCreds bool) {
	deleteSession(a.SessionPath)
	if forgetCreds {
		a.Store.deleteBrokerageCredentials(a.Profile)
		a.Store.deleteCryptoCredentials(a.Profile)
	}
}

func (a *AuthManager) cryptoStatus(ctx context.Context) AuthStatus {
	apiKey, privateKey, _ := a.Store.cryptoCredentials(a.Profile)
	if apiKey == "" || privateKey == "" {
		return AuthStatus{Provider: "crypto", Authenticated: false, State: "CREDENTIALS_MISSING", Detail: "Missing RH_CRYPTO_API_KEY or RH_CRYPTO_PRIVATE_KEY_B64"}
	}
	provider := newOfficialCryptoProvider(a)
	if err := provider.verify(ctx); err != nil {
		ce := cliError(err)
		return AuthStatus{Provider: "crypto", Authenticated: false, State: authStateFromError(ce), Detail: ce.Message}
	}
	return AuthStatus{Provider: "crypto", Authenticated: true, State: "READY", Detail: "Authenticated"}
}

func authStateFromError(err *CLIError) string {
	if err == nil {
		return "READY"
	}
	switch err.Code {
	case ErrorMFARequired:
		return "MFA_REQUIRED_DO_NOT_RETRY"
	case ErrorAuthRequired:
		msg := strings.ToLower(err.Message)
		if strings.Contains(msg, "missing") && (strings.Contains(msg, "username") || strings.Contains(msg, "credential") || strings.Contains(msg, "api key") || strings.Contains(msg, "api_key")) {
			return "CREDENTIALS_MISSING"
		}
		return "SESSION_EXPIRED"
	case ErrorRateLimited:
		return "RATE_LIMITED"
	default:
		return string(err.Code)
	}
}
