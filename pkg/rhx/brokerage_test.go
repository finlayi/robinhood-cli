package rhx

import (
	"context"
	"net/http"
	"net/http/httptest"
	"net/url"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestListOrdersReturnsExplicitAssetErrors(t *testing.T) {
	provider, cleanup := testBrokerageProvider(t)
	defer cleanup()

	if _, err := provider.listOrders(context.Background(), "option", false); err == nil {
		t.Fatalf("explicit option orders list succeeded")
	}
	if _, err := provider.listOrders(context.Background(), "crypto", false); err == nil {
		t.Fatalf("explicit crypto orders list succeeded")
	}
	if _, err := provider.listOrders(context.Background(), "", false); err != nil {
		t.Fatalf("combined orders list returned error: %v", err)
	}
}

func TestListOpenOrdersUsesSingleBoundedStockPage(t *testing.T) {
	orderRequests := 0
	pageSize := ""
	provider, cleanup := testBrokerageProviderWithHandler(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/positions/":
			_, _ = w.Write([]byte(`{"results":[]}`))
		case "/orders/":
			orderRequests++
			pageSize = r.URL.Query().Get("page_size")
			_, _ = w.Write([]byte(`{
				"next":"https://api.robinhood.com/orders/?cursor=next",
				"results":[
					{"id":"filled-id","symbol":"AAPL","side":"buy","state":"filled"},
					{"id":"open-id","symbol":"MSFT","side":"sell","state":"queued","cancel_url":"https://api.robinhood.com/orders/open-id/cancel/"}
				]
			}`))
		default:
			http.NotFound(w, r)
		}
	})
	defer cleanup()

	rows, err := provider.listOpenOrders(context.Background(), "stock", 1)
	if err != nil {
		t.Fatalf("listOpenOrders returned error: %v", err)
	}
	if orderRequests != 1 {
		t.Fatalf("order requests = %d, want 1", orderRequests)
	}
	if pageSize != "20" {
		t.Fatalf("page_size = %q, want 20", pageSize)
	}
	if len(rows) != 1 {
		t.Fatalf("rows = %d, want 1", len(rows))
	}
	if rows[0]["id"] != "open-id" || rows[0]["symbol"] != "MSFT" || rows[0]["state"] != "queued" {
		t.Fatalf("unexpected normalized row: %#v", rows[0])
	}
}

func TestWaitForStockOrderTerminalReturnsNormalizedFill(t *testing.T) {
	oldInterval := orderPollInterval
	orderPollInterval = time.Millisecond
	defer func() { orderPollInterval = oldInterval }()

	orderRequests := 0
	provider, cleanup := testBrokerageProviderWithHandler(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/positions/":
			_, _ = w.Write([]byte(`{"results":[]}`))
		case "/orders/order-id/":
			orderRequests++
			if orderRequests == 1 {
				_, _ = w.Write([]byte(`{"id":"order-id","symbol":"AAPL","side":"buy","state":"queued"}`))
				return
			}
			_, _ = w.Write([]byte(`{
				"id":"order-id",
				"symbol":"AAPL",
				"side":"buy",
				"state":"filled",
				"executed_quantity":"2",
				"average_price":"6.17",
				"fees":"0.00",
				"settlement_date":"2026-05-26"
			}`))
		default:
			http.NotFound(w, r)
		}
	})
	defer cleanup()

	got, err := provider.waitForStockOrderTerminal(context.Background(), "order-id", time.Second)
	if err != nil {
		t.Fatalf("waitForStockOrderTerminal returned error: %v", err)
	}
	if got["state"] != "filled" {
		t.Fatalf("state = %v, want filled", got["state"])
	}
	if got["executed_quantity"] != "2" || got["average_price"] != "6.17" || got["executed_notional"] != "12.34" {
		t.Fatalf("unexpected execution fields: %#v", got)
	}
	if got["settlement_date"] != "2026-05-26" {
		t.Fatalf("settlement_date = %v, want 2026-05-26", got["settlement_date"])
	}
}

func testBrokerageProvider(t *testing.T) (*BrokerageProvider, func()) {
	return testBrokerageProviderWithHandler(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		originalHost := r.Header.Get("X-Original-Host")
		switch {
		case r.URL.Path == "/positions/":
			_, _ = w.Write([]byte(`{"results":[]}`))
		case r.URL.Path == "/options/orders/":
			w.WriteHeader(http.StatusInternalServerError)
			_, _ = w.Write([]byte(`{"detail":"option orders unavailable"}`))
		case r.URL.Path == "/orders/" && strings.Contains(originalHost, "nummus"):
			w.WriteHeader(http.StatusForbidden)
			_, _ = w.Write([]byte(`{"detail":"crypto orders unavailable"}`))
		case r.URL.Path == "/orders/":
			_, _ = w.Write([]byte(`{"results":[]}`))
		default:
			http.NotFound(w, r)
		}
	})
}

func testBrokerageProviderWithHandler(t *testing.T, handler http.HandlerFunc) (*BrokerageProvider, func()) {
	t.Helper()
	server := httptest.NewServer(handler)

	tmp := t.TempDir()
	sessionPath := filepath.Join(tmp, "sessions", "robinhood_test.json")
	if err := saveSession(sessionPath, Session{
		TokenType:   "Bearer",
		AccessToken: "token",
		DeviceToken: "device",
		CreatedAt:   time.Now().UTC(),
	}); err != nil {
		server.Close()
		t.Fatalf("saveSession returned error: %v", err)
	}
	target, err := url.Parse(server.URL)
	if err != nil {
		server.Close()
		t.Fatalf("Parse(server.URL) returned error: %v", err)
	}
	client := newHTTPClient(nil)
	client.client = server.Client()
	client.client.Transport = rewriteTransport{target: target, base: http.DefaultTransport}
	auth := &AuthManager{
		Profile:     "test",
		SessionPath: sessionPath,
		Store:       CredentialStore{},
		Client:      client,
	}
	return newBrokerageProvider(auth), server.Close
}

type rewriteTransport struct {
	target *url.URL
	base   http.RoundTripper
}

func (t rewriteTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	clone := req.Clone(req.Context())
	clone.URL.Scheme = t.target.Scheme
	clone.URL.Host = t.target.Host
	clone.Host = t.target.Host
	clone.Header = clone.Header.Clone()
	clone.Header.Set("X-Original-Host", req.URL.Host)
	return t.base.RoundTrip(clone)
}
