package rhx

import (
	"context"
	"strings"
)

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
