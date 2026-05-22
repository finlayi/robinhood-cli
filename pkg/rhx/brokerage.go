package rhx

import (
	"context"
	"net/url"
	"strings"
)

type BrokerageProvider struct {
	auth *AuthManager
}

func newBrokerageProvider(auth *AuthManager) *BrokerageProvider {
	return &BrokerageProvider{auth: auth}
}

func (p *BrokerageProvider) ensure(ctx context.Context) error {
	waitForChallenge := canWaitForAuthChallenge()
	_, err := p.auth.ensureBrokerageAuthenticatedWithOptions(ctx, brokerageAuthOptions{
		WaitForChallenge:   waitForChallenge,
		AllowPasswordLogin: waitForChallenge,
	})
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

func (p *BrokerageProvider) news(ctx context.Context, symbol string) ([]map[string]any, error) {
	normalizedSymbol := strings.ToUpper(symbol)
	instrument, err := p.instrument(ctx, normalizedSymbol)
	if err != nil {
		return nil, err
	}
	instrumentID, _ := instrument["id"].(string)
	if instrumentID == "" {
		return nil, wrapError(ErrorBrokerRejected, "No instrument id returned for %s", normalizedSymbol)
	}
	data, err := p.auth.Client.get(ctx, robinhoodDoraBase+"/feed/midlands/instrument/"+url.PathEscape(instrumentID)+"/", nil)
	if err != nil {
		return nil, err
	}
	rows := asRows(data)
	out := make([]map[string]any, 0, len(rows))
	for _, row := range rows {
		out = append(out, normalizeNewsArticle(normalizedSymbol, instrumentID, row))
	}
	return out, nil
}
