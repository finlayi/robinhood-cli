package rhx

import (
	"math/big"
	"strconv"
	"strings"
)

func isCryptoSymbol(symbol string) bool {
	normalized := strings.ToUpper(symbol)
	return strings.Contains(normalized, "-") || strings.HasSuffix(normalized, "USD")
}

func normalizeCryptoSymbol(symbol string) string {
	normalized := strings.ToUpper(strings.TrimSpace(symbol))
	if strings.Contains(normalized, "-") {
		return normalized
	}
	if strings.HasSuffix(normalized, "USD") && len(normalized) > 3 {
		return strings.TrimSuffix(normalized, "USD") + "-USD"
	}
	return normalized + "-USD"
}

func cryptoBase(symbol string) string {
	return strings.Split(normalizeCryptoSymbol(symbol), "-")[0]
}

func flattenQuote(row map[string]any, provider string) map[string]any {
	quote := asMap(row["quote"])
	return map[string]any{
		"symbol":           row["symbol"],
		"asset_type":       row["asset_type"],
		"provider":         provider,
		"bid_price":        firstAny(quote, "bid_price", "bid"),
		"ask_price":        firstAny(quote, "ask_price", "ask"),
		"mark_price":       firstAny(quote, "mark_price", "mark"),
		"last_trade_price": firstAny(quote, "last_trade_price", "price"),
		"updated_at":       quote["updated_at"],
		"error":            row["error"],
	}
}

func normalizeNewsArticle(symbol string, instrumentID string, raw map[string]any) map[string]any {
	return map[string]any{
		"uuid":                firstString(raw, "uuid", "id"),
		"symbol":              symbol,
		"instrument_id":       instrumentID,
		"title":               firstString(raw, "title"),
		"source":              firstString(raw, "source"),
		"published_at":        firstAny(raw, "date", "published_at"),
		"url":                 firstString(raw, "url", "relay_url"),
		"source_uri":          firstString(raw, "source_uri"),
		"preview_text":        firstString(raw, "preview_text", "summary"),
		"image_url":           firstAny(raw, "image", "preview_image_url"),
		"related_instruments": firstAny(raw, "related_instruments"),
		"raw":                 raw,
	}
}

func firstAny(row map[string]any, keys ...string) any {
	for _, key := range keys {
		if value, ok := row[key]; ok && value != nil {
			return value
		}
	}
	return nil
}

func firstString(row map[string]any, keys ...string) string {
	for _, key := range keys {
		if value, ok := row[key].(string); ok {
			return value
		}
	}
	return ""
}

func normalizeOrder(assetType string, raw map[string]any, defaults map[string]any) map[string]any {
	id := firstString(raw, "id", "order_id")
	if id == "" {
		id = firstString(defaults, "id", "order_id")
	}
	symbol := firstString(raw, "symbol")
	if symbol == "" {
		symbol = firstString(defaults, "symbol")
	}
	side := firstString(raw, "side")
	if side == "" {
		side = firstString(defaults, "side")
	}
	state := firstString(raw, "state", "status")
	if state == "" {
		state = firstString(defaults, "state", "status")
	}
	executedQuantity := firstAny(raw, "executed_quantity", "cumulative_quantity", "filled_quantity", "quantity_executed")
	averagePrice := firstAny(raw, "average_price", "average_fill_price", "avg_price")
	return map[string]any{
		"id":                id,
		"order_id":          id,
		"symbol":            symbol,
		"side":              side,
		"state":             state,
		"executed_quantity": executedQuantity,
		"average_price":     averagePrice,
		"executed_notional": orderExecutedNotional(raw, executedQuantity, averagePrice),
		"fees":              firstAny(raw, "fees", "fee", "total_fees", "regulatory_fees"),
		"settlement_date":   firstAny(raw, "settlement_date", "settlement_date_for_stock_order", "settlement_date_for_execution"),
		"asset_type":        assetType,
		"provider":          firstString(defaults, "provider"),
		"raw":               raw,
	}
}

func orderExecutedNotional(raw map[string]any, executedQuantity any, averagePrice any) any {
	if value := firstAny(raw, "executed_notional", "cumulative_notional", "filled_notional"); value != nil {
		return value
	}
	qty := floatFromAny(executedQuantity)
	price := floatFromAny(averagePrice)
	if qty <= 0 || price <= 0 {
		return nil
	}
	return formatFloat(qty * price)
}

func isOpenishOrder(row map[string]any) bool {
	if value := firstAny(row, "cancel_url"); value != nil {
		if raw, ok := value.(string); !ok || raw != "" {
			return true
		}
	}
	state := firstString(row, "state", "status")
	if state == "" {
		return false
	}
	return !isTerminalOrderState(state)
}

func isTerminalOrderState(state string) bool {
	switch strings.ToLower(strings.TrimSpace(state)) {
	case "filled", "cancelled", "canceled", "rejected", "failed", "expired", "voided":
		return true
	default:
		return false
	}
}

func valueOrUnknown(value string) string {
	if strings.TrimSpace(value) == "" {
		return "unknown"
	}
	return value
}

func decimalRatFromAny(value any) (*big.Rat, string, bool) {
	raw := decimalStringFromAny(value)
	if raw == "" {
		return nil, "", false
	}
	rat, ok := new(big.Rat).SetString(raw)
	if !ok {
		return nil, "", false
	}
	return rat, raw, true
}

func decimalStringFromAny(value any) string {
	switch typed := value.(type) {
	case string:
		return strings.TrimSpace(typed)
	case float64:
		return strconv.FormatFloat(typed, 'f', -1, 64)
	case float32:
		return strconv.FormatFloat(float64(typed), 'f', -1, 32)
	case int:
		return strconv.Itoa(typed)
	case jsonNumber:
		return string(typed)
	default:
		return ""
	}
}

func formatDecimalRat(value *big.Rat, scale int) string {
	out := value.FloatString(scale)
	out = strings.TrimRight(out, "0")
	out = strings.TrimRight(out, ".")
	if out == "" {
		return "0"
	}
	return out
}

func floatFromAny(value any) float64 {
	switch typed := value.(type) {
	case float64:
		return typed
	case float32:
		return float64(typed)
	case int:
		return float64(typed)
	case jsonNumber:
		f, _ := strconv.ParseFloat(string(typed), 64)
		return f
	case string:
		f, _ := strconv.ParseFloat(typed, 64)
		return f
	default:
		return 0
	}
}

type jsonNumber string

func roundPrice(price float64) float64 {
	places := 2.0
	if price <= 0.01 {
		places = 1_000_000
	} else if price < 1 {
		places = 10_000
	} else {
		places = 100
	}
	return float64(int(price*places+0.5)) / places
}

func formatFloat(value float64) string {
	return strconv.FormatFloat(value, 'f', -1, 64)
}
