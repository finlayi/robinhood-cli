package rhx

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

const (
	robinhoodAPIBase     = "https://api.robinhood.com"
	robinhoodCryptoBase  = "https://nummus.robinhood.com"
	robinhoodTradingBase = "https://trading.robinhood.com"
)

type HTTPClient struct {
	client *http.Client
	token  string
}

func newHTTPClient(session *Session) *HTTPClient {
	c := &HTTPClient{client: &http.Client{Timeout: 20 * time.Second}}
	if session != nil && session.AccessToken != "" {
		tokenType := session.TokenType
		if tokenType == "" {
			tokenType = "Bearer"
		}
		c.token = tokenType + " " + session.AccessToken
	}
	return c
}

func (c *HTTPClient) setSession(session Session) {
	tokenType := session.TokenType
	if tokenType == "" {
		tokenType = "Bearer"
	}
	c.token = tokenType + " " + session.AccessToken
}

func (c *HTTPClient) get(ctx context.Context, rawURL string, query map[string]string) (any, error) {
	return c.request(ctx, http.MethodGet, rawURL, query, nil, false)
}

func (c *HTTPClient) postForm(ctx context.Context, rawURL string, form url.Values) (any, int, error) {
	data, status, err := c.postFormRaw(ctx, rawURL, form)
	if err != nil {
		return nil, status, err
	}
	if err := apiStatusError(status, data); err != nil {
		return nil, status, err
	}
	return data, status, nil
}

func (c *HTTPClient) postFormRaw(ctx context.Context, rawURL string, form url.Values) (any, int, error) {
	body := strings.NewReader(form.Encode())
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, rawURL, body)
	if err != nil {
		return nil, 0, err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded; charset=utf-8")
	req.Header.Set("Accept", "application/json")
	return c.doRaw(req)
}

func (c *HTTPClient) postJSON(ctx context.Context, rawURL string, payload any) (any, error) {
	data, err := c.request(ctx, http.MethodPost, rawURL, nil, payload, true)
	return data, err
}

func (c *HTTPClient) postJSONRaw(ctx context.Context, rawURL string, payload any) (any, int, error) {
	b, err := json.Marshal(payload)
	if err != nil {
		return nil, 0, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, rawURL, bytes.NewReader(b))
	if err != nil {
		return nil, 0, err
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("Content-Type", "application/json")
	if c.token != "" {
		req.Header.Set("Authorization", c.token)
	}
	return c.doRaw(req)
}

func (c *HTTPClient) getRaw(ctx context.Context, rawURL string, query map[string]string) (any, int, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, rawURL, nil)
	if err != nil {
		return nil, 0, err
	}
	if query != nil {
		q := req.URL.Query()
		for key, value := range query {
			q.Set(key, value)
		}
		req.URL.RawQuery = q.Encode()
	}
	req.Header.Set("Accept", "application/json")
	if c.token != "" {
		req.Header.Set("Authorization", c.token)
	}
	return c.doRaw(req)
}

func (c *HTTPClient) request(ctx context.Context, method string, rawURL string, query map[string]string, payload any, asJSON bool) (any, error) {
	var body io.Reader
	if payload != nil {
		if asJSON {
			b, err := json.Marshal(payload)
			if err != nil {
				return nil, err
			}
			body = bytes.NewReader(b)
		}
	}
	req, err := http.NewRequestWithContext(ctx, method, rawURL, body)
	if err != nil {
		return nil, err
	}
	if query != nil {
		q := req.URL.Query()
		for key, value := range query {
			q.Set(key, value)
		}
		req.URL.RawQuery = q.Encode()
	}
	req.Header.Set("Accept", "application/json")
	if asJSON && payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if c.token != "" {
		req.Header.Set("Authorization", c.token)
	}
	data, _, err := c.do(req)
	return data, err
}

func (c *HTTPClient) do(req *http.Request) (any, int, error) {
	data, status, err := c.doRaw(req)
	if err != nil {
		return nil, status, err
	}
	if err := apiStatusError(status, data); err != nil {
		return nil, status, err
	}
	return data, status, nil
}

func (c *HTTPClient) doRaw(req *http.Request) (any, int, error) {
	resp, err := c.client.Do(req)
	if err != nil {
		return nil, 0, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, resp.StatusCode, err
	}
	if len(bytes.TrimSpace(body)) == 0 {
		return map[string]any{}, resp.StatusCode, nil
	}
	var decoded any
	if err := json.Unmarshal(body, &decoded); err != nil {
		return map[string]any{"text": string(body)}, resp.StatusCode, nil
	}
	return decoded, resp.StatusCode, nil
}

func apiStatusError(status int, data any) error {
	if status == http.StatusTooManyRequests {
		ce := newError(ErrorRateLimited, "Robinhood API rate limit")
		ce.Retriable = true
		return ce
	}
	if status == http.StatusUnauthorized || status == http.StatusForbidden {
		return newError(ErrorAuthRequired, compactData(data, status))
	}
	if status >= 400 {
		return newError(ErrorBrokerRejected, compactData(data, status))
	}
	return nil
}

func compactBody(body []byte, status int) string {
	if len(body) == 0 {
		return fmt.Sprintf("Robinhood API error %d", status)
	}
	var decoded map[string]any
	if err := json.Unmarshal(body, &decoded); err == nil {
		for _, key := range []string{"detail", "error", "message"} {
			if value, ok := decoded[key].(string); ok && value != "" {
				return value
			}
		}
	}
	msg := strings.TrimSpace(string(body))
	if len(msg) > 500 {
		msg = msg[:500]
	}
	return fmt.Sprintf("Robinhood API error %d: %s", status, msg)
}

func compactData(data any, status int) string {
	payload := asMap(data)
	for _, key := range []string{"detail", "error", "message"} {
		if value, ok := payload[key].(string); ok && value != "" {
			return value
		}
	}
	if len(payload) > 0 {
		if b, err := json.Marshal(payload); err == nil {
			return fmt.Sprintf("Robinhood API error %d: %s", status, string(b))
		}
	}
	if text, ok := payload["text"].(string); ok && text != "" {
		return fmt.Sprintf("Robinhood API error %d: %s", status, text)
	}
	return fmt.Sprintf("Robinhood API error %d", status)
}

func asMap(value any) map[string]any {
	if m, ok := value.(map[string]any); ok {
		return m
	}
	return map[string]any{}
}

func asRows(value any) []map[string]any {
	switch typed := value.(type) {
	case []any:
		rows := make([]map[string]any, 0, len(typed))
		for _, item := range typed {
			rows = append(rows, asMap(item))
		}
		return rows
	case []map[string]any:
		return typed
	default:
		return nil
	}
}

func resultsRows(value any) []map[string]any {
	m := asMap(value)
	return asRows(m["results"])
}

func firstResult(value any) map[string]any {
	rows := resultsRows(value)
	if len(rows) == 0 {
		return nil
	}
	return rows[0]
}

func (c *HTTPClient) getAllPages(ctx context.Context, rawURL string, query map[string]string) ([]map[string]any, error) {
	rows := []map[string]any{}
	nextURL := rawURL
	nextQuery := query
	for nextURL != "" {
		data, err := c.get(ctx, nextURL, nextQuery)
		if err != nil {
			return nil, err
		}
		page := asMap(data)
		rows = append(rows, asRows(page["results"])...)
		next, _ := page["next"].(string)
		nextURL = next
		nextQuery = nil
	}
	return rows, nil
}
