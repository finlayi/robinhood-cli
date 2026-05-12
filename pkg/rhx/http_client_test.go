package rhx

import (
	"context"
	"net/http"
	"net/http/httptest"
	"net/url"
	"testing"
)

func TestPostFormRawKeepsVerificationWorkflowBody(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusForbidden)
		_, _ = w.Write([]byte(`{"verification_workflow":{"id":"workflow-id","workflow_status":"workflow_status_internal_pending"}}`))
	}))
	defer server.Close()

	client := newHTTPClient(nil)
	data, status, err := client.postFormRaw(context.Background(), server.URL, url.Values{"username": []string{"user"}})
	if err != nil {
		t.Fatalf("postFormRaw returned error: %v", err)
	}
	if status != http.StatusForbidden {
		t.Fatalf("status = %d, want 403", status)
	}
	if got := verificationWorkflowID(asMap(data)); got != "workflow-id" {
		t.Fatalf("verificationWorkflowID = %q, want workflow-id", got)
	}
}

func TestPostFormMapsForbiddenWithoutRaw(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusForbidden)
		_, _ = w.Write([]byte(`{"detail":"denied"}`))
	}))
	defer server.Close()

	client := newHTTPClient(nil)
	_, _, err := client.postForm(context.Background(), server.URL, url.Values{"username": []string{"user"}})
	if err == nil {
		t.Fatalf("postForm succeeded")
	}
	ce := cliError(err)
	if ce.Code != ErrorAuthRequired {
		t.Fatalf("error code = %s, want %s", ce.Code, ErrorAuthRequired)
	}
}
