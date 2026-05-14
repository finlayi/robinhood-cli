package rhx

import (
	"context"
	"fmt"
	"math/big"
	"net/url"
	"strconv"
	"strings"
	"time"
)

type BrokerageProvider struct {
	auth *AuthManager
}

func newBrokerageProvider(auth *AuthManager) *BrokerageProvider {
	return &BrokerageProvider{auth: auth}
}

func (p *BrokerageProvider) ensure(ctx context.Context) error {
	_, err := p.auth.ensureBrokerageAuthenticated(ctx, false, false)
	return err
}

func (p *BrokerageProvider) accountSummary(ctx context.Context) (map[string]any, error) {
	if err := p.ensure(ctx); err != nil {
		return nil, err
	}
	account, err := p.accountProfile(ctx)
	if err != nil {
		return nil, err
	}
	portfolio, err := p.portfolioProfile(ctx)
	if err != nil {
		return nil, err
	}
	user, err := p.auth.Client.get(ctx, robinhoodAPIBase+"/user/", nil)
	if err != nil {
		return nil, err
	}
	return map[string]any{
		"account_profile":   account,
		"portfolio_profile": portfolio,
		"user_profile":      asMap(user),
	}, nil
}

func (p *BrokerageProvider) accountProfile(ctx context.Context) (map[string]any, error) {
	data, err := p.auth.Client.get(ctx, robinhoodAPIBase+"/accounts/", map[string]string{"default_to_all_accounts": "true"})
	if err != nil {
		return nil, err
	}
	row := firstResult(data)
	if row == nil {
		return nil, newError(ErrorAuthRequired, "No Robinhood account profile returned")
	}
	return row, nil
}

func (p *BrokerageProvider) portfolioProfile(ctx context.Context) (map[string]any, error) {
	data, err := p.auth.Client.get(ctx, robinhoodAPIBase+"/portfolios/", nil)
	if err != nil {
		return nil, err
	}
	row := firstResult(data)
	if row == nil {
		return nil, newError(ErrorBrokerRejected, "No Robinhood portfolio profile returned")
	}
	return row, nil
}

func (p *BrokerageProvider) positions(ctx context.Context) ([]map[string]any, error) {
	if err := p.ensure(ctx); err != nil {
		return nil, err
	}
	rows := []map[string]any{}
	stockRows, err := p.auth.Client.getAllPages(ctx, robinhoodAPIBase+"/positions/", map[string]string{"nonzero": "true"})
	if err != nil {
		return nil, err
	}
	for _, row := range stockRows {
		row["asset_type"] = "stock"
		rows = append(rows, row)
	}
	cryptoRows, err := p.auth.Client.getAllPages(ctx, robinhoodCryptoBase+"/holdings/", nil)
	if err == nil {
		for _, row := range cryptoRows {
			row["asset_type"] = "crypto"
			rows = append(rows, row)
		}
	}
	optionRows, err := p.auth.Client.getAllPages(ctx, robinhoodAPIBase+"/options/positions/", nil)
	if err == nil {
		for _, row := range optionRows {
			row["asset_type"] = "option"
			rows = append(rows, row)
		}
	}
	return rows, nil
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

func (p *BrokerageProvider) quote(ctx context.Context, symbol string) (map[string]any, error) {
	rows, err := p.quotes(ctx, []string{symbol})
	if err != nil {
		return nil, err
	}
	if len(rows) == 0 {
		return nil, wrapError(ErrorBrokerRejected, "No quote returned for %s", symbol)
	}
	return rows[0], nil
}

func (p *BrokerageProvider) quotes(ctx context.Context, symbols []string) ([]map[string]any, error) {
	if err := p.ensure(ctx); err != nil {
		return nil, err
	}
	stockSymbols := []string{}
	cryptoSymbols := []string{}
	for _, symbol := range symbols {
		if isCryptoSymbol(symbol) {
			cryptoSymbols = append(cryptoSymbols, normalizeCryptoSymbol(symbol))
		} else {
			stockSymbols = append(stockSymbols, strings.ToUpper(symbol))
		}
	}
	bySymbol := map[string]map[string]any{}
	if len(stockSymbols) > 0 {
		data, err := p.auth.Client.get(ctx, robinhoodAPIBase+"/quotes/", map[string]string{"symbols": strings.Join(stockSymbols, ",")})
		if err != nil {
			return nil, err
		}
		for _, row := range resultsRows(data) {
			symbol, _ := row["symbol"].(string)
			if symbol == "" {
				continue
			}
			bySymbol[strings.ToUpper(symbol)] = map[string]any{
				"asset_type": "stock",
				"symbol":     strings.ToUpper(symbol),
				"quote":      row,
			}
		}
	}
	for _, symbol := range cryptoSymbols {
		quote, err := p.cryptoQuote(ctx, symbol)
		if err != nil {
			return nil, err
		}
		bySymbol[strings.ToUpper(symbol)] = map[string]any{
			"asset_type": "crypto",
			"symbol":     symbol,
			"quote":      quote,
		}
	}
	out := []map[string]any{}
	for _, symbol := range symbols {
		key := strings.ToUpper(symbol)
		if isCryptoSymbol(key) {
			key = strings.ToUpper(normalizeCryptoSymbol(key))
		}
		if row, ok := bySymbol[key]; ok {
			out = append(out, row)
		}
	}
	return out, nil
}

func (p *BrokerageProvider) cryptoQuote(ctx context.Context, symbol string) (map[string]any, error) {
	pair, err := p.cryptoPair(ctx, symbol)
	if err != nil {
		return nil, err
	}
	id, _ := pair["id"].(string)
	if id == "" {
		return nil, wrapError(ErrorBrokerRejected, "No crypto pair id returned for %s", symbol)
	}
	data, err := p.auth.Client.get(ctx, robinhoodAPIBase+"/marketdata/forex/quotes/"+id+"/", nil)
	if err != nil {
		return nil, err
	}
	return asMap(data), nil
}

func (p *BrokerageProvider) cryptoPair(ctx context.Context, symbol string) (map[string]any, error) {
	base := cryptoBase(symbol)
	data, err := p.auth.Client.get(ctx, robinhoodCryptoBase+"/currency_pairs/", nil)
	if err != nil {
		return nil, err
	}
	for _, row := range resultsRows(data) {
		if asset, ok := row["asset_currency"].(map[string]any); ok {
			if code, _ := asset["code"].(string); strings.EqualFold(code, base) {
				return row, nil
			}
		}
		if s, _ := row["symbol"].(string); strings.EqualFold(s, normalizeCryptoSymbol(symbol)) {
			return row, nil
		}
	}
	return nil, wrapError(ErrorBrokerRejected, "No crypto pair returned for %s", symbol)
}

func (p *BrokerageProvider) listOrders(ctx context.Context, assetType string, openOnly bool) ([]map[string]any, error) {
	if err := p.ensure(ctx); err != nil {
		return nil, err
	}
	rows := []map[string]any{}
	if assetType == "" || assetType == "stock" {
		stockRows, err := p.auth.Client.getAllPages(ctx, robinhoodAPIBase+"/orders/", nil)
		if err != nil {
			return nil, err
		}
		for _, row := range stockRows {
			if openOnly && row["cancel_url"] == nil {
				continue
			}
			row["asset_type"] = "stock"
			rows = append(rows, row)
		}
	}
	if assetType == "" || assetType == "option" {
		optionRows, err := p.auth.Client.getAllPages(ctx, robinhoodAPIBase+"/options/orders/", nil)
		if err == nil {
			for _, row := range optionRows {
				if openOnly && row["cancel_url"] == nil {
					continue
				}
				row["asset_type"] = "option"
				rows = append(rows, row)
			}
		}
	}
	if assetType == "" || assetType == "crypto" {
		cryptoRows, err := p.auth.Client.getAllPages(ctx, robinhoodCryptoBase+"/orders/", nil)
		if err == nil {
			for _, row := range cryptoRows {
				if openOnly && row["cancel_url"] == nil {
					continue
				}
				row["asset_type"] = "crypto"
				rows = append(rows, row)
			}
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
		return map[string]any{"asset_type": "option", "order": asMap(data)}, err
	case "crypto":
		data, err := p.auth.Client.get(ctx, robinhoodCryptoBase+"/orders/"+orderID+"/", nil)
		return map[string]any{"asset_type": "crypto", "order": asMap(data)}, err
	default:
		data, err := p.auth.Client.get(ctx, robinhoodAPIBase+"/orders/"+orderID+"/", nil)
		return map[string]any{"asset_type": "stock", "order": asMap(data)}, err
	}
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
	return map[string]any{
		"provider":   "brokerage",
		"order_id":   firstString(result, "id", "order_id"),
		"state":      firstString(result, "state", "status"),
		"symbol":     intent.Symbol,
		"side":       intent.Side,
		"asset_type": "stock",
		"raw":        result,
	}, estimated, nil
}

func (p *BrokerageProvider) instrument(ctx context.Context, symbol string) (map[string]any, error) {
	data, err := p.auth.Client.get(ctx, robinhoodAPIBase+"/instruments/", map[string]string{"symbol": strings.ToUpper(symbol)})
	if err != nil {
		return nil, err
	}
	row := firstResult(data)
	if row == nil {
		return nil, wrapError(ErrorBrokerRejected, "No instrument returned for %s", symbol)
	}
	return row, nil
}

func (p *BrokerageProvider) optionChain(ctx context.Context, symbol string) (map[string]any, error) {
	if err := p.ensure(ctx); err != nil {
		return nil, err
	}
	instrument, err := p.instrument(ctx, symbol)
	if err != nil {
		return nil, err
	}
	chainID, _ := instrument["tradable_chain_id"].(string)
	if chainID == "" {
		return nil, wrapError(ErrorBrokerRejected, "No option chain id returned for %s", symbol)
	}
	data, err := p.auth.Client.get(ctx, robinhoodAPIBase+"/options/chains/"+chainID+"/", nil)
	if err != nil {
		return nil, err
	}
	return asMap(data), nil
}

func (p *BrokerageProvider) optionExpirations(ctx context.Context, symbol string) (map[string]any, error) {
	chain, err := p.optionChain(ctx, symbol)
	if err != nil {
		return nil, err
	}
	return map[string]any{"symbol": strings.ToUpper(symbol), "expiration_dates": chain["expiration_dates"]}, nil
}

func (p *BrokerageProvider) optionInstruments(ctx context.Context, symbol string, expirationDate string, optionType string, strike string) ([]map[string]any, error) {
	chain, err := p.optionChain(ctx, symbol)
	if err != nil {
		return nil, err
	}
	chainID, _ := chain["id"].(string)
	query := map[string]string{
		"chain_id": chainID,
		"state":    "active",
	}
	if expirationDate != "" {
		query["expiration_dates"] = expirationDate
	}
	if optionType != "" && optionType != "both" {
		query["type"] = optionType
	}
	if strike != "" {
		query["strike_price"] = strike
	}
	return p.auth.Client.getAllPages(ctx, robinhoodAPIBase+"/options/instruments/", query)
}

func (p *BrokerageProvider) optionStrikes(ctx context.Context, symbol string, expirationDate string, optionType string) (map[string]any, error) {
	rows, err := p.optionInstruments(ctx, symbol, expirationDate, optionType, "")
	if err != nil {
		return nil, err
	}
	seen := map[string]bool{}
	strikes := []string{}
	for _, row := range rows {
		strike, _ := row["strike_price"].(string)
		if strike == "" || seen[strike] {
			continue
		}
		seen[strike] = true
		strikes = append(strikes, strike)
	}
	return map[string]any{
		"symbol":          strings.ToUpper(symbol),
		"expiration_date": expirationDate,
		"option_type":     optionType,
		"strikes":         strikes,
	}, nil
}

func (p *BrokerageProvider) optionContract(ctx context.Context, symbol string, expirationDate string, strike string, optionType string) (map[string]any, error) {
	rows, err := p.optionInstruments(ctx, symbol, expirationDate, optionType, strike)
	if err != nil {
		return nil, err
	}
	if len(rows) == 0 {
		return nil, newError(ErrorBrokerRejected, "No option contract returned")
	}
	return rows[0], nil
}

func (p *BrokerageProvider) optionQuote(ctx context.Context, symbol string, expirationDate string, strike string, optionType string) (map[string]any, error) {
	contract, err := p.optionContract(ctx, symbol, expirationDate, strike, optionType)
	if err != nil {
		return nil, err
	}
	quote, err := p.optionMarketData(ctx, []map[string]any{contract})
	if err != nil {
		return nil, err
	}
	if len(quote) == 0 {
		return nil, newError(ErrorBrokerRejected, "No option quote returned")
	}
	return mergeOptionQuote(contract, quote[0]), nil
}

func (p *BrokerageProvider) optionQuotes(ctx context.Context, symbol string, expirationDate string, optionType string) ([]map[string]any, error) {
	contracts, err := p.optionInstruments(ctx, symbol, expirationDate, optionType, "")
	if err != nil {
		return nil, err
	}
	quotes, err := p.optionMarketData(ctx, contracts)
	if err != nil {
		return nil, err
	}
	quotesByInstrument := map[string]map[string]any{}
	for _, quote := range quotes {
		if instrument, _ := quote["instrument"].(string); instrument != "" {
			quotesByInstrument[instrument] = quote
		}
	}
	out := []map[string]any{}
	for _, contract := range contracts {
		instrumentURL, _ := contract["url"].(string)
		if quote, ok := quotesByInstrument[instrumentURL]; ok {
			out = append(out, mergeOptionQuote(contract, quote))
		}
	}
	return out, nil
}

func (p *BrokerageProvider) optionMarketData(ctx context.Context, contracts []map[string]any) ([]map[string]any, error) {
	urls := []string{}
	for _, contract := range contracts {
		instrumentURL, _ := contract["url"].(string)
		if instrumentURL != "" {
			urls = append(urls, instrumentURL)
		}
	}
	if len(urls) == 0 {
		return nil, nil
	}
	data, err := p.auth.Client.get(ctx, robinhoodAPIBase+"/marketdata/options/", map[string]string{"instruments": strings.Join(urls, ",")})
	if err != nil {
		return nil, err
	}
	return resultsRows(data), nil
}

func mergeOptionQuote(contract map[string]any, quote map[string]any) map[string]any {
	return map[string]any{
		"contract_id":        contract["id"],
		"symbol":             contract["chain_symbol"],
		"expiration_date":    contract["expiration_date"],
		"strike_price":       contract["strike_price"],
		"option_type":        contract["type"],
		"bid_price":          quote["bid_price"],
		"ask_price":          quote["ask_price"],
		"mark_price":         quote["mark_price"],
		"last_trade_price":   quote["last_trade_price"],
		"implied_volatility": quote["implied_volatility"],
		"delta":              quote["delta"],
		"gamma":              quote["gamma"],
		"theta":              quote["theta"],
		"vega":               quote["vega"],
		"rho":                quote["rho"],
		"open_interest":      quote["open_interest"],
		"volume":             quote["volume"],
		"updated_at":         quote["updated_at"],
		"tradability":        contract["tradability"],
		"state":              contract["state"],
	}
}

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

func queryEscape(value string) string {
	return url.QueryEscape(value)
}

func formatFloat(value float64) string {
	return strconv.FormatFloat(value, 'f', -1, 64)
}

var _ = fmt.Sprintf

type StockOrderIntent struct {
	Symbol        string
	Side          string
	Type          string
	Quantity      *float64
	QuantityRaw   string
	NotionalUSD   *float64
	LimitPrice    *float64
	StopPrice     *float64
	TimeInForce   string
	ExtendedHours bool
}
