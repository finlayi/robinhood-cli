package rhx

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"strconv"
	"strings"
	"time"
)

type OfficialCryptoProvider struct {
	auth *AuthManager
	base string
}

type CryptoOrderIntent struct {
	Symbol      string
	Side        string
	Type        string
	AmountIn    string
	Quantity    *float64
	NotionalUSD *float64
	LimitPrice  *float64
	TimeInForce string
}

func newOfficialCryptoProvider(auth *AuthManager) *OfficialCryptoProvider {
	return &OfficialCryptoProvider{auth: auth, base: robinhoodTradingBase}
}

func (p *OfficialCryptoProvider) credentials() (string, string, error) {
	apiKey, privateKey, _ := p.auth.Store.cryptoCredentials(p.auth.Profile)
	if apiKey == "" || privateKey == "" {
		return "", "", newError(ErrorAuthRequired, "Missing RH_CRYPTO_API_KEY or RH_CRYPTO_PRIVATE_KEY_B64")
	}
	return apiKey, privateKey, nil
}

func (p *OfficialCryptoProvider) verify(ctx context.Context) error {
	_, err := p.request(ctx, http.MethodGet, "/api/v1/crypto/trading/accounts/", nil, nil)
	return err
}

func (p *OfficialCryptoProvider) accountSummary(ctx context.Context) (map[string]any, error) {
	data, err := p.request(ctx, http.MethodGet, "/api/v1/crypto/trading/accounts/", nil, nil)
	if err != nil {
		return nil, err
	}
	return asMap(data), nil
}

func (p *OfficialCryptoProvider) positions(ctx context.Context) ([]map[string]any, error) {
	data, err := p.request(ctx, http.MethodGet, "/api/v1/crypto/trading/holdings/", nil, nil)
	if err != nil {
		return nil, err
	}
	rows := resultsRows(data)
	if len(rows) == 0 {
		if m := asMap(data); len(m) > 0 {
			rows = []map[string]any{m}
		}
	}
	return rows, nil
}

func (p *OfficialCryptoProvider) quote(ctx context.Context, symbol string) (map[string]any, error) {
	data, err := p.request(ctx, http.MethodGet, "/api/v1/crypto/marketdata/best_bid_ask/", map[string]string{"symbol": normalizeCryptoSymbol(symbol)}, nil)
	if err != nil {
		return nil, err
	}
	return map[string]any{"symbol": normalizeCryptoSymbol(symbol), "quote": data}, nil
}

func (p *OfficialCryptoProvider) quotes(ctx context.Context, symbols []string) ([]map[string]any, error) {
	rows := []map[string]any{}
	for _, symbol := range symbols {
		row, err := p.quote(ctx, symbol)
		if err != nil {
			return nil, err
		}
		rows = append(rows, row)
	}
	return rows, nil
}

func (p *OfficialCryptoProvider) placeOrder(ctx context.Context, intent CryptoOrderIntent) (map[string]any, float64, error) {
	payload := map[string]any{
		"client_order_id": randomDeviceToken(),
		"side":            intent.Side,
		"symbol":          normalizeCryptoSymbol(intent.Symbol),
		"type":            intent.Type,
		"time_in_force":   intent.TimeInForce,
	}
	estimated := 0.0
	if intent.Type == "market" {
		if intent.AmountIn == "quantity" {
			if intent.Quantity == nil {
				return nil, 0, newError(ErrorValidation, "--qty is required when --amount-in quantity")
			}
			payload["market_order_config"] = map[string]any{"asset_quantity": formatFloat(*intent.Quantity)}
		} else {
			if intent.NotionalUSD == nil {
				return nil, 0, newError(ErrorValidation, "--notional-usd is required when --amount-in price")
			}
			estimated = *intent.NotionalUSD
			payload["market_order_config"] = map[string]any{"quote_amount": formatFloat(*intent.NotionalUSD)}
		}
	} else {
		if intent.LimitPrice == nil {
			return nil, 0, newError(ErrorValidation, "--limit-price is required for limit orders")
		}
		if intent.AmountIn == "quantity" {
			if intent.Quantity == nil {
				return nil, 0, newError(ErrorValidation, "--qty is required when --amount-in quantity")
			}
			estimated = *intent.Quantity * *intent.LimitPrice
			payload["limit_order_config"] = map[string]any{"asset_quantity": formatFloat(*intent.Quantity), "limit_price": formatFloat(*intent.LimitPrice)}
		} else {
			if intent.NotionalUSD == nil {
				return nil, 0, newError(ErrorValidation, "--notional-usd is required when --amount-in price")
			}
			estimated = *intent.NotionalUSD
			payload["limit_order_config"] = map[string]any{"quote_amount": formatFloat(*intent.NotionalUSD), "limit_price": formatFloat(*intent.LimitPrice)}
		}
	}
	data, err := p.request(ctx, http.MethodPost, "/api/v1/crypto/trading/orders/", nil, payload)
	if err != nil {
		return nil, 0, err
	}
	raw := asMap(data)
	return map[string]any{
		"provider":   "crypto",
		"order_id":   firstString(raw, "id", "order_id"),
		"state":      firstString(raw, "state", "status"),
		"symbol":     normalizeCryptoSymbol(intent.Symbol),
		"side":       intent.Side,
		"asset_type": "crypto",
		"raw":        raw,
	}, estimated, nil
}

func (p *OfficialCryptoProvider) listOrders(ctx context.Context, openOnly bool) ([]map[string]any, error) {
	query := map[string]string(nil)
	if openOnly {
		query = map[string]string{"state": "open"}
	}
	data, err := p.request(ctx, http.MethodGet, "/api/v1/crypto/trading/orders/", query, nil)
	if err != nil {
		return nil, err
	}
	return resultsRows(data), nil
}

func (p *OfficialCryptoProvider) getOrder(ctx context.Context, orderID string) (map[string]any, error) {
	data, err := p.request(ctx, http.MethodGet, "/api/v1/crypto/trading/orders/"+orderID+"/", nil, nil)
	if err != nil {
		return nil, err
	}
	return map[string]any{"asset_type": "crypto", "order": asMap(data)}, nil
}

func (p *OfficialCryptoProvider) cancelOrder(ctx context.Context, orderID string) (map[string]any, error) {
	data, err := p.request(ctx, http.MethodPost, "/api/v1/crypto/trading/orders/"+orderID+"/cancel/", nil, map[string]any{})
	if err != nil {
		return nil, err
	}
	return map[string]any{"asset_type": "crypto", "result": data}, nil
}

func (p *OfficialCryptoProvider) request(ctx context.Context, method string, path string, query map[string]string, payload any) (any, error) {
	apiKey, privateKeyB64, err := p.credentials()
	if err != nil {
		return nil, err
	}
	body := ""
	var reader *bytes.Reader
	if payload != nil {
		b, err := json.Marshal(payload)
		if err != nil {
			return nil, err
		}
		body = string(b)
		reader = bytes.NewReader(b)
	} else {
		reader = bytes.NewReader(nil)
	}
	timestamp := strconvFormatUnix(time.Now().Unix())
	signingPayload := apiKey + timestamp + path + strings.ToUpper(method) + body
	signature, err := signEd25519(privateKeyB64, signingPayload)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, method, p.base+path, reader)
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
	req.Header.Set("x-api-key", apiKey)
	req.Header.Set("x-signature", signature)
	req.Header.Set("x-timestamp", timestamp)
	req.Header.Set("Accept", "application/json")
	if payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	data, _, err := newHTTPClient(nil).do(req)
	return data, err
}

func signEd25519(privateKeyB64 string, message string) (string, error) {
	keyBytes, err := base64.StdEncoding.DecodeString(privateKeyB64)
	if err != nil {
		return "", wrapError(ErrorAuthRequired, "Invalid crypto private key encoding: %v", err)
	}
	var privateKey ed25519.PrivateKey
	switch len(keyBytes) {
	case ed25519.SeedSize:
		privateKey = ed25519.NewKeyFromSeed(keyBytes)
	case ed25519.PrivateKeySize:
		privateKey = ed25519.PrivateKey(keyBytes)
	default:
		return "", newError(ErrorAuthRequired, "Invalid crypto private key length; expected 32 or 64 decoded bytes")
	}
	sig := ed25519.Sign(privateKey, []byte(message))
	return base64.StdEncoding.EncodeToString(sig), nil
}

func strconvFormatUnix(ts int64) string {
	return strconv.FormatInt(ts, 10)
}
