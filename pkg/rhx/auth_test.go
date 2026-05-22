package rhx

import (
	"context"
	"net/http"
	"net/http/httptest"
	"net/url"
	"path/filepath"
	"testing"
	"time"
)

func TestAuthStateFromError(t *testing.T) {
	cases := []struct {
		name string
		err  *CLIError
		want string
	}{
		{name: "ready", err: nil, want: "READY"},
		{name: "mfa", err: newError(ErrorMFARequired, "challenge required"), want: "MFA_REQUIRED_DO_NOT_RETRY"},
		{name: "session", err: newError(ErrorAuthRequired, "Stored Robinhood session expired"), want: "SESSION_EXPIRED"},
		{name: "credentials", err: newError(ErrorAuthRequired, "Missing Robinhood username/password"), want: "CREDENTIALS_MISSING"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := authStateFromError(tc.err); got != tc.want {
				t.Fatalf("state = %q, want %q", got, tc.want)
			}
		})
	}
}

func TestEnsureUsesRefreshTokenBeforePasswordLogin(t *testing.T) {
	refreshRequests := 0
	passwordRequests := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/positions/":
			if r.Header.Get("Authorization") == "Bearer expired" {
				w.WriteHeader(http.StatusUnauthorized)
				_, _ = w.Write([]byte(`{"detail":"expired"}`))
				return
			}
			if r.Header.Get("Authorization") != "Bearer refreshed" {
				w.WriteHeader(http.StatusUnauthorized)
				_, _ = w.Write([]byte(`{"detail":"wrong token"}`))
				return
			}
			_, _ = w.Write([]byte(`{"results":[]}`))
		case "/oauth2/token/":
			if err := r.ParseForm(); err != nil {
				t.Errorf("ParseForm returned error: %v", err)
				w.WriteHeader(http.StatusBadRequest)
				return
			}
			switch r.Form.Get("grant_type") {
			case "refresh_token":
				refreshRequests++
				if r.Form.Get("refresh_token") != "refresh-old" {
					t.Errorf("refresh_token = %q, want refresh-old", r.Form.Get("refresh_token"))
				}
				_, _ = w.Write([]byte(`{"access_token":"refreshed","token_type":"Bearer","refresh_token":"refresh-new"}`))
			case "password":
				passwordRequests++
				w.WriteHeader(http.StatusInternalServerError)
				_, _ = w.Write([]byte(`{"detail":"password login should not be used"}`))
			default:
				t.Errorf("grant_type = %q", r.Form.Get("grant_type"))
				w.WriteHeader(http.StatusBadRequest)
			}
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	auth := testAuthManager(t, server, &Session{
		TokenType:    "Bearer",
		AccessToken:  "expired",
		RefreshToken: "refresh-old",
		DeviceToken:  "device-id",
		CreatedAt:    time.Now().Add(-25 * time.Hour).UTC(),
	})

	session, err := auth.ensureBrokerageAuthenticatedWithOptions(context.Background(), brokerageAuthOptions{})
	if err != nil {
		t.Fatalf("ensureBrokerageAuthenticatedWithOptions returned error: %v", err)
	}
	if session.AccessToken != "refreshed" {
		t.Fatalf("access token = %q, want refreshed", session.AccessToken)
	}
	if session.RefreshToken != "refresh-new" {
		t.Fatalf("refresh token = %q, want refresh-new", session.RefreshToken)
	}
	saved, err := loadSession(auth.SessionPath)
	if err != nil {
		t.Fatalf("loadSession returned error: %v", err)
	}
	if saved.AccessToken != "refreshed" || saved.RefreshToken != "refresh-new" {
		t.Fatalf("saved session = %#v", saved)
	}
	if refreshRequests != 1 {
		t.Fatalf("refresh requests = %d, want 1", refreshRequests)
	}
	if passwordRequests != 0 {
		t.Fatalf("password requests = %d, want 0", passwordRequests)
	}
}

func TestEnsureNonInteractiveDoesNotStartPasswordLoginWhenRefreshFails(t *testing.T) {
	refreshRequests := 0
	passwordRequests := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/positions/":
			w.WriteHeader(http.StatusUnauthorized)
			_, _ = w.Write([]byte(`{"detail":"expired"}`))
		case "/oauth2/token/":
			if err := r.ParseForm(); err != nil {
				t.Errorf("ParseForm returned error: %v", err)
				w.WriteHeader(http.StatusBadRequest)
				return
			}
			switch r.Form.Get("grant_type") {
			case "refresh_token":
				refreshRequests++
				w.WriteHeader(http.StatusUnauthorized)
				_, _ = w.Write([]byte(`{"detail":"refresh expired"}`))
			case "password":
				passwordRequests++
				_, _ = w.Write([]byte(`{"access_token":"password-token","token_type":"Bearer"}`))
			default:
				t.Errorf("grant_type = %q", r.Form.Get("grant_type"))
				w.WriteHeader(http.StatusBadRequest)
			}
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	t.Setenv("RH_USERNAME", "user")
	t.Setenv("RH_PASSWORD", "pass")

	auth := testAuthManager(t, server, &Session{
		TokenType:    "Bearer",
		AccessToken:  "expired",
		RefreshToken: "refresh-old",
		DeviceToken:  "device-id",
		CreatedAt:    time.Now().Add(-25 * time.Hour).UTC(),
	})

	_, err := auth.ensureBrokerageAuthenticatedWithOptions(context.Background(), brokerageAuthOptions{})
	if err == nil {
		t.Fatalf("ensureBrokerageAuthenticatedWithOptions succeeded")
	}
	if ce := cliError(err); ce.Code != ErrorAuthRequired {
		t.Fatalf("error code = %s, want %s", ce.Code, ErrorAuthRequired)
	}
	if refreshRequests != 1 {
		t.Fatalf("refresh requests = %d, want 1", refreshRequests)
	}
	if passwordRequests != 0 {
		t.Fatalf("password requests = %d, want 0", passwordRequests)
	}
}

func TestLoginWaitsForPromptWorkflowWhenEnabled(t *testing.T) {
	oldPollInterval := authPollInterval
	authPollInterval = time.Millisecond
	defer func() { authPollInterval = oldPollInterval }()

	tokenRequests := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/oauth2/token/":
			if err := r.ParseForm(); err != nil {
				t.Errorf("ParseForm returned error: %v", err)
				w.WriteHeader(http.StatusBadRequest)
				return
			}
			if r.Form.Get("grant_type") != "password" {
				t.Errorf("grant_type = %q, want password", r.Form.Get("grant_type"))
				w.WriteHeader(http.StatusBadRequest)
				return
			}
			tokenRequests++
			if tokenRequests == 1 {
				w.WriteHeader(http.StatusForbidden)
				_, _ = w.Write([]byte(`{"verification_workflow":{"id":"workflow-id","workflow_status":"workflow_status_internal_pending"}}`))
				return
			}
			_, _ = w.Write([]byte(`{"access_token":"approved","token_type":"Bearer","refresh_token":"refresh-approved"}`))
		case "/pathfinder/user_machine/":
			_, _ = w.Write([]byte(`{"id":"machine-id"}`))
		case "/pathfinder/inquiries/machine-id/user_view/":
			if r.Method == http.MethodPost {
				_, _ = w.Write([]byte(`{"type_context":{"result":"workflow_status_approved"}}`))
				return
			}
			_, _ = w.Write([]byte(`{"context":{"sheriff_challenge":{"type":"prompt","status":"issued","id":"challenge-id"}}}`))
		case "/push/challenge-id/get_prompts_status/":
			_, _ = w.Write([]byte(`{"challenge_status":"validated"}`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	t.Setenv("RH_USERNAME", "user")
	t.Setenv("RH_PASSWORD", "pass")

	auth := testAuthManager(t, server, nil)
	session, err := auth.ensureBrokerageAuthenticatedWithOptions(context.Background(), brokerageAuthOptions{
		WaitForChallenge:   true,
		AllowPasswordLogin: true,
	})
	if err != nil {
		t.Fatalf("ensureBrokerageAuthenticatedWithOptions returned error: %v", err)
	}
	if session.AccessToken != "approved" {
		t.Fatalf("access token = %q, want approved", session.AccessToken)
	}
	if tokenRequests != 2 {
		t.Fatalf("token requests = %d, want 2", tokenRequests)
	}
}

func TestForceLoginClearsStaleAuthorizationBeforeWorkflow(t *testing.T) {
	oldPollInterval := authPollInterval
	authPollInterval = time.Millisecond
	defer func() { authPollInterval = oldPollInterval }()

	tokenRequests := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/oauth2/token/":
			tokenRequests++
			if tokenRequests == 1 {
				w.WriteHeader(http.StatusForbidden)
				_, _ = w.Write([]byte(`{"verification_workflow":{"id":"workflow-id","workflow_status":"workflow_status_internal_pending"}}`))
				return
			}
			_, _ = w.Write([]byte(`{"access_token":"approved","token_type":"Bearer","refresh_token":"refresh-approved"}`))
		case "/pathfinder/user_machine/":
			if got := r.Header.Get("Authorization"); got != "" {
				t.Errorf("Authorization header on workflow request = %q, want empty", got)
			}
			_, _ = w.Write([]byte(`{"id":"machine-id"}`))
		case "/pathfinder/inquiries/machine-id/user_view/":
			if r.Method == http.MethodPost {
				_, _ = w.Write([]byte(`{"type_context":{"result":"workflow_status_approved"}}`))
				return
			}
			_, _ = w.Write([]byte(`{"context":{"sheriff_challenge":{"type":"prompt","status":"issued","id":"challenge-id"}}}`))
		case "/push/challenge-id/get_prompts_status/":
			if got := r.Header.Get("Authorization"); got != "" {
				t.Errorf("Authorization header on prompt request = %q, want empty", got)
			}
			_, _ = w.Write([]byte(`{"challenge_status":"validated"}`))
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	t.Setenv("RH_USERNAME", "user")
	t.Setenv("RH_PASSWORD", "pass")

	auth := testAuthManager(t, server, &Session{
		TokenType:    "Bearer",
		AccessToken:  "stale",
		RefreshToken: "refresh-old",
		DeviceToken:  "device-id",
		CreatedAt:    time.Now().Add(-25 * time.Hour).UTC(),
	})
	_, err := auth.ensureBrokerageAuthenticatedWithOptions(context.Background(), brokerageAuthOptions{
		WaitForChallenge:   true,
		AllowPasswordLogin: true,
		Force:              true,
	})
	if err != nil {
		t.Fatalf("ensureBrokerageAuthenticatedWithOptions returned error: %v", err)
	}
}

func testAuthManager(t *testing.T, server *httptest.Server, session *Session) *AuthManager {
	t.Helper()
	target, err := url.Parse(server.URL)
	if err != nil {
		t.Fatalf("Parse(server.URL) returned error: %v", err)
	}
	tmp := t.TempDir()
	sessionPath := filepath.Join(tmp, "sessions", "robinhood_test.json")
	if session != nil {
		if err := saveSession(sessionPath, *session); err != nil {
			t.Fatalf("saveSession returned error: %v", err)
		}
	}
	client := newHTTPClient(session)
	client.client = server.Client()
	client.client.Transport = rewriteTransport{target: target, base: http.DefaultTransport}
	return &AuthManager{
		Profile:     "test",
		SessionPath: sessionPath,
		Store:       CredentialStore{},
		Client:      client,
	}
}
