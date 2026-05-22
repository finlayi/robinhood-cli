package rhx

import (
	"context"
	"math/big"
	"strconv"
	"strings"
	"time"
)

var orderPollInterval = 2 * time.Second

type brokerageOrderSource struct {
	assetType           string
	endpoint            string
	requiredForCombined bool
}

func selectedBrokerageOrderSources(assetType string) []brokerageOrderSource {
	sources := []brokerageOrderSource{
		{assetType: "stock", endpoint: robinhoodAPIBase + "/orders/", requiredForCombined: true},
		{assetType: "option", endpoint: robinhoodAPIBase + "/options/orders/"},
		{assetType: "crypto", endpoint: robinhoodCryptoBase + "/orders/"},
	}
	out := []brokerageOrderSource{}
	for _, source := range sources {
		if assetType == "" || assetType == source.assetType {
			out = append(out, source)
		}
	}
	return out
}

func (source brokerageOrderSource) shouldReturnError(requestedAssetType string) bool {
	return requestedAssetType == source.assetType || (requestedAssetType == "" && source.requiredForCombined)
}

func (p *BrokerageProvider) sellAllStockIntent(ctx context.Context, symbol string, timeInForce string) (StockOrderIntent, map[string]any, error) {
	if err := p.ensure(ctx); err != nil {
		return StockOrderIntent{}, nil, err
	}
	instrument, err := p.instrument(ctx, symbol)
	if err != nil {
		return StockOrderIntent{}, nil, err
	}
	instrumentURL, _ := instrument["url"].(string)
	if instrumentURL == "" {
		return StockOrderIntent{}, nil, wrapError(ErrorBrokerRejected, "No instrument URL returned for %s", symbol)
	}
	stockRows, err := p.auth.Client.getAllPages(ctx, robinhoodAPIBase+"/positions/", map[string]string{"nonzero": "true"})
	if err != nil {
		return StockOrderIntent{}, nil, err
	}
	for _, row := range stockRows {
		rowInstrument, _ := row["instrument"].(string)
		rowSymbol, _ := row["symbol"].(string)
		if rowInstrument != instrumentURL && !strings.EqualFold(rowSymbol, symbol) {
			continue
		}
		quantity, quantityFloat, err := sellableStockQuantity(row)
		if err != nil {
			return StockOrderIntent{}, nil, err
		}
		return StockOrderIntent{
			Symbol:      strings.ToUpper(symbol),
			Side:        "sell",
			Type:        "market",
			Quantity:    &quantityFloat,
			QuantityRaw: quantity,
			TimeInForce: timeInForce,
		}, row, nil
	}
	return StockOrderIntent{}, nil, wrapError(ErrorBrokerRejected, "No nonzero stock position found for %s", symbol)
}

func (p *BrokerageProvider) listOrders(ctx context.Context, assetType string, openOnly bool) ([]map[string]any, error) {
	if err := p.ensure(ctx); err != nil {
		return nil, err
	}
	rows := []map[string]any{}
	for _, source := range selectedBrokerageOrderSources(assetType) {
		rawRows, err := p.auth.Client.getAllPages(ctx, source.endpoint, nil)
		if err != nil {
			if source.shouldReturnError(assetType) {
				return nil, err
			}
			continue
		}
		rows = append(rows, normalizeOrderRows(source.assetType, rawRows, openOnly)...)
	}
	return rows, nil
}

func normalizeOrderRows(assetType string, rawRows []map[string]any, openOnly bool) []map[string]any {
	rows := []map[string]any{}
	for _, row := range rawRows {
		if openOnly && !isOpenishOrder(row) {
			continue
		}
		rows = append(rows, normalizeOrder(assetType, row, map[string]any{"provider": "brokerage"}))
	}
	return rows
}

func trimOrderRows(rows []map[string]any, limit int) []map[string]any {
	if limit > 0 && len(rows) > limit {
		return rows[:limit]
	}
	return rows
}

func (p *BrokerageProvider) listOpenOrders(ctx context.Context, assetType string, limit int) ([]map[string]any, error) {
	if err := p.ensure(ctx); err != nil {
		return nil, err
	}
	if limit <= 0 {
		limit = 20
	}
	rows := []map[string]any{}
	for _, source := range selectedBrokerageOrderSources(assetType) {
		if len(rows) >= limit {
			return rows[:limit], nil
		}
		pageRows, err := p.openOrderPage(ctx, source.endpoint, source.assetType, limit-len(rows))
		if err != nil {
			if source.shouldReturnError(assetType) {
				return nil, err
			}
			continue
		}
		rows = append(rows, pageRows...)
	}
	return trimOrderRows(rows, limit), nil
}

func (p *BrokerageProvider) openOrderPage(ctx context.Context, endpoint string, assetType string, limit int) ([]map[string]any, error) {
	if limit <= 0 {
		return []map[string]any{}, nil
	}
	pageSize := limit
	if pageSize < 20 {
		pageSize = 20
	}
	data, err := p.auth.Client.get(ctx, endpoint, map[string]string{"page_size": strconv.Itoa(pageSize)})
	if err != nil {
		return nil, err
	}
	rows := []map[string]any{}
	for _, row := range resultsRows(data) {
		if !isOpenishOrder(row) {
			continue
		}
		rows = append(rows, normalizeOrder(assetType, row, map[string]any{"provider": "brokerage"}))
		if len(rows) >= limit {
			break
		}
	}
	return rows, nil
}

func (p *BrokerageProvider) getOrder(ctx context.Context, orderID string, assetType string) (map[string]any, error) {
	if err := p.ensure(ctx); err != nil {
		return nil, err
	}
	switch assetType {
	case "option":
		data, err := p.auth.Client.get(ctx, robinhoodAPIBase+"/options/orders/"+orderID+"/", nil)
		return normalizeOrder("option", asMap(data), map[string]any{"provider": "brokerage"}), err
	case "crypto":
		data, err := p.auth.Client.get(ctx, robinhoodCryptoBase+"/orders/"+orderID+"/", nil)
		return normalizeOrder("crypto", asMap(data), map[string]any{"provider": "brokerage"}), err
	default:
		raw, err := p.stockOrder(ctx, orderID)
		return normalizeOrder("stock", raw, map[string]any{"provider": "brokerage"}), err
	}
}

func (p *BrokerageProvider) stockOrder(ctx context.Context, orderID string) (map[string]any, error) {
	data, err := p.auth.Client.get(ctx, robinhoodAPIBase+"/orders/"+orderID+"/", nil)
	return asMap(data), err
}

func (p *BrokerageProvider) cancelOrder(ctx context.Context, orderID string, assetType string) (map[string]any, error) {
	if err := p.ensure(ctx); err != nil {
		return nil, err
	}
	endpoint := robinhoodAPIBase + "/orders/" + orderID + "/cancel/"
	resultType := "stock"
	if assetType == "option" {
		endpoint = robinhoodAPIBase + "/options/orders/" + orderID + "/cancel/"
		resultType = "option"
	} else if assetType == "crypto" {
		endpoint = robinhoodCryptoBase + "/orders/" + orderID + "/cancel/"
		resultType = "crypto"
	}
	data, err := p.auth.Client.postJSON(ctx, endpoint, map[string]any{})
	if err != nil {
		return nil, err
	}
	return map[string]any{"asset_type": resultType, "result": data}, nil
}

func (p *BrokerageProvider) estimateStockOrderNotional(ctx context.Context, intent StockOrderIntent) (float64, error) {
	estimated := estimateStockIntent(intent)
	if estimated > 0 {
		return estimated, nil
	}
	if intent.Quantity == nil {
		return 0, nil
	}
	quoteRow, err := p.quote(ctx, intent.Symbol)
	if err != nil {
		return 0, err
	}
	quote := asMap(quoteRow["quote"])
	price := stockOrderPrice(intent, quote)
	if price <= 0 {
		return 0, newError(ErrorBrokerRejected, "Cannot estimate stock order notional without a quote price")
	}
	return *intent.Quantity * price, nil
}

func (p *BrokerageProvider) placeStockOrder(ctx context.Context, intent StockOrderIntent) (map[string]any, float64, error) {
	if err := p.ensure(ctx); err != nil {
		return nil, 0, err
	}
	account, err := p.accountProfile(ctx)
	if err != nil {
		return nil, 0, err
	}
	instrument, err := p.instrument(ctx, intent.Symbol)
	if err != nil {
		return nil, 0, err
	}
	quoteRow, err := p.quote(ctx, intent.Symbol)
	if err != nil {
		return nil, 0, err
	}
	quote := asMap(quoteRow["quote"])
	ask := floatFromAny(quote["ask_price"])
	bid := floatFromAny(quote["bid_price"])
	price := stockOrderPrice(intent, quote)
	quantity := intent.Quantity
	quantityPayload := stockQuantityPayload(intent)
	estimated := 0.0
	if intent.NotionalUSD != nil {
		estimated = *intent.NotionalUSD
		if price <= 0 {
			return nil, 0, newError(ErrorBrokerRejected, "Cannot derive fractional quantity without a quote price")
		}
		qty := roundPrice(*intent.NotionalUSD / price)
		quantity = &qty
		quantityPayload = formatFloat(qty)
	} else if quantity != nil {
		estimated = *quantity * price
	}
	if quantity == nil || *quantity <= 0 {
		return nil, 0, newError(ErrorValidation, "A positive --qty or --notional-usd is required")
	}

	orderType := intent.Type
	trigger := "immediate"
	payloadPrice := price
	stopPrice := any(nil)
	if intent.Type == "stop_limit" {
		orderType = "limit"
		trigger = "stop"
		if intent.StopPrice == nil {
			return nil, 0, newError(ErrorValidation, "--stop-price is required for stop_limit")
		}
		stopPrice = roundPrice(*intent.StopPrice)
	}
	payload := map[string]any{
		"account":            account["url"],
		"instrument":         instrument["url"],
		"symbol":             strings.ToUpper(intent.Symbol),
		"price":              roundPrice(payloadPrice),
		"ask_price":          roundPrice(ask),
		"bid_ask_timestamp":  time.Now().Format("2006-01-02 15:04:05.000000"),
		"bid_price":          roundPrice(bid),
		"quantity":           quantityPayload,
		"ref_id":             randomDeviceToken(),
		"type":               orderType,
		"stop_price":         stopPrice,
		"time_in_force":      intent.TimeInForce,
		"trigger":            trigger,
		"side":               intent.Side,
		"market_hours":       "regular_hours",
		"extended_hours":     intent.ExtendedHours,
		"order_form_version": 4,
	}
	if intent.Type == "market" && intent.Side == "buy" {
		payload["preset_percent_limit"] = "0.05"
		payload["type"] = "limit"
	} else if intent.Type == "market" && intent.Side == "sell" {
		delete(payload, "price")
		delete(payload, "stop_price")
	}
	if intent.Type != "stop_limit" {
		delete(payload, "stop_price")
	}
	data, err := p.auth.Client.postJSON(ctx, robinhoodAPIBase+"/orders/", payload)
	if err != nil {
		return nil, 0, err
	}
	result := asMap(data)
	return normalizeOrder("stock", result, map[string]any{
		"provider": "brokerage",
		"symbol":   intent.Symbol,
		"side":     intent.Side,
		"state":    firstString(result, "state", "status"),
	}), estimated, nil
}

func (p *BrokerageProvider) waitForStockOrderTerminal(ctx context.Context, orderID string, timeout time.Duration) (map[string]any, error) {
	if orderID == "" {
		return nil, newError(ErrorBrokerRejected, "Broker did not return an order id to reconcile")
	}
	if err := p.ensure(ctx); err != nil {
		return nil, err
	}
	deadline := time.Now().UTC().Add(timeout)
	for {
		raw, err := p.stockOrder(ctx, orderID)
		if err != nil {
			return nil, err
		}
		order := normalizeOrder("stock", raw, map[string]any{"provider": "brokerage"})
		state := firstString(order, "state")
		if isTerminalOrderState(state) {
			return order, nil
		}
		remaining := time.Until(deadline)
		if remaining <= 0 {
			return nil, wrapError(ErrorBrokerRejected, "Order %s did not reach a terminal state within %s; last state was %s", orderID, timeout, valueOrUnknown(state))
		}
		sleep := orderPollInterval
		if sleep > remaining {
			sleep = remaining
		}
		timer := time.NewTimer(sleep)
		select {
		case <-ctx.Done():
			timer.Stop()
			return nil, ctx.Err()
		case <-timer.C:
		}
	}
}

func stockOrderPrice(intent StockOrderIntent, quote map[string]any) float64 {
	price := floatFromAny(quote["last_trade_price"])
	if intent.Side == "buy" {
		if ask := floatFromAny(quote["ask_price"]); ask > 0 {
			price = ask
		}
	}
	if intent.Side == "sell" {
		if bid := floatFromAny(quote["bid_price"]); bid > 0 {
			price = bid
		}
	}
	if intent.Type == "limit" && intent.LimitPrice != nil {
		price = *intent.LimitPrice
	}
	if intent.Type == "stop_limit" && intent.LimitPrice != nil {
		price = *intent.LimitPrice
	}
	return price
}

func stockQuantityPayload(intent StockOrderIntent) any {
	if intent.QuantityRaw != "" {
		return intent.QuantityRaw
	}
	if intent.Quantity != nil {
		return formatFloat(*intent.Quantity)
	}
	return nil
}

func sellableStockQuantity(row map[string]any) (string, float64, error) {
	quantity, quantityRaw, ok := decimalRatFromAny(row["quantity"])
	if !ok {
		return "", 0, newError(ErrorBrokerRejected, "Position is missing a quantity")
	}
	sellable := new(big.Rat).Set(quantity)
	for _, field := range []string{
		"shares_held_for_sells",
		"shares_held_for_options_collateral",
		"shares_held_for_options_events",
		"shares_held_for_stock_grants",
	} {
		if held, _, ok := decimalRatFromAny(row[field]); ok {
			sellable.Sub(sellable, held)
		}
	}
	if sellable.Sign() <= 0 {
		return "", 0, newError(ErrorBrokerRejected, "No sellable shares are available for this position")
	}
	out := quantityRaw
	if sellable.Cmp(quantity) != 0 {
		out = formatDecimalRat(sellable, 9)
	}
	value, err := strconv.ParseFloat(out, 64)
	if err != nil || value <= 0 {
		return "", 0, newError(ErrorBrokerRejected, "No sellable shares are available for this position")
	}
	return out, value, nil
}
