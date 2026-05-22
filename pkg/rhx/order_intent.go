package rhx

import (
	"context"
	"strings"
	"time"
)

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

func validateStockIntent(intent StockOrderIntent) error {
	if intent.Symbol == "" {
		return newError(ErrorValidation, "--symbol is required")
	}
	if intent.Side != "buy" && intent.Side != "sell" {
		return newError(ErrorValidation, "--side must be buy or sell")
	}
	if intent.Type != "market" && intent.Type != "limit" && intent.Type != "stop_limit" {
		return newError(ErrorValidation, "--type must be market, limit, or stop_limit")
	}
	if intent.Quantity == nil && intent.NotionalUSD == nil {
		return newError(ErrorValidation, "Either --qty or --notional-usd is required")
	}
	if intent.Quantity != nil && isFractionalStockQuantity(intent) && intent.Type != "market" {
		return newError(ErrorValidation, "Fractional stock quantities via --qty are only supported for market orders.")
	}
	if intent.Type == "limit" && intent.LimitPrice == nil {
		return newError(ErrorValidation, "--limit-price is required for limit orders")
	}
	if intent.Type == "stop_limit" && (intent.LimitPrice == nil || intent.StopPrice == nil) {
		return newError(ErrorValidation, "--limit-price and --stop-price are required for stop_limit orders")
	}
	return nil
}

func stockTimeInForceForPlace(flags parsedFlags, intent StockOrderIntent) (string, error) {
	timeInForce, explicit := flags.Values["time-in-force"]
	timeInForce = strings.ToLower(strings.TrimSpace(timeInForce))
	if timeInForce == "" {
		if isFractionalStockQuantity(intent) && intent.Type == "market" {
			return "gfd", nil
		}
		return "gtc", nil
	}
	if explicit && isFractionalStockQuantity(intent) && intent.Type == "market" && timeInForce != "gfd" {
		return "", newError(ErrorValidation, "Fractional stock quantity orders require --time-in-force gfd.")
	}
	return timeInForce, nil
}

func parseOrderWaitTimeout(raw string) (time.Duration, error) {
	if strings.TrimSpace(raw) == "" {
		return 60 * time.Second, nil
	}
	timeout, err := time.ParseDuration(raw)
	if err != nil || timeout <= 0 {
		return 0, newError(ErrorValidation, "--timeout must be a positive duration like 60s")
	}
	return timeout, nil
}

func isFractionalStockQuantity(intent StockOrderIntent) bool {
	if intent.Quantity == nil {
		return false
	}
	return *intent.Quantity != float64(int64(*intent.Quantity))
}

func estimateStockIntent(intent StockOrderIntent) float64 {
	if intent.NotionalUSD != nil {
		return *intent.NotionalUSD
	}
	if intent.Quantity != nil && intent.LimitPrice != nil {
		return *intent.Quantity * *intent.LimitPrice
	}
	if intent.Quantity != nil && intent.StopPrice != nil {
		return *intent.Quantity * *intent.StopPrice
	}
	return 0
}

func estimateCryptoIntent(intent CryptoOrderIntent) float64 {
	if intent.NotionalUSD != nil {
		return *intent.NotionalUSD
	}
	if intent.Quantity != nil && intent.LimitPrice != nil {
		return *intent.Quantity * *intent.LimitPrice
	}
	return 0
}

func validateCryptoIntent(intent CryptoOrderIntent) error {
	if intent.Symbol == "" {
		return newError(ErrorValidation, "--symbol is required")
	}
	if intent.Side != "buy" && intent.Side != "sell" {
		return newError(ErrorValidation, "--side must be buy or sell")
	}
	if intent.Type != "market" && intent.Type != "limit" {
		return newError(ErrorValidation, "--type must be market or limit")
	}
	if intent.AmountIn != "quantity" && intent.AmountIn != "price" {
		return newError(ErrorValidation, "--amount-in must be quantity or price")
	}
	if intent.AmountIn == "quantity" {
		if intent.Quantity == nil || *intent.Quantity <= 0 {
			return newError(ErrorValidation, "A positive --qty is required when --amount-in quantity")
		}
		if intent.NotionalUSD != nil {
			return newError(ErrorValidation, "--notional-usd cannot be combined with --amount-in quantity")
		}
	} else {
		if intent.NotionalUSD == nil || *intent.NotionalUSD <= 0 {
			return newError(ErrorValidation, "A positive --notional-usd is required when --amount-in price")
		}
		if intent.Quantity != nil {
			return newError(ErrorValidation, "--qty cannot be combined with --amount-in price")
		}
	}
	if intent.Type == "market" && intent.LimitPrice != nil {
		return newError(ErrorValidation, "--limit-price cannot be used with market crypto orders")
	}
	if intent.Type == "limit" {
		if intent.LimitPrice == nil || *intent.LimitPrice <= 0 {
			return newError(ErrorValidation, "A positive --limit-price is required for limit crypto orders")
		}
	}
	return nil
}

func (rt *appRuntime) estimateCryptoOrderNotional(ctx context.Context, intent CryptoOrderIntent) (float64, error) {
	estimated := estimateCryptoIntent(intent)
	if estimated > 0 {
		return estimated, nil
	}
	if intent.Type != "market" || intent.AmountIn != "quantity" || intent.Quantity == nil {
		return 0, newError(ErrorValidation, "Cannot estimate crypto order notional")
	}
	quoteRow, err := rt.crypto.quote(ctx, intent.Symbol)
	if err != nil {
		return 0, err
	}
	price := cryptoSafetyPrice(asMap(quoteRow["quote"]))
	if price <= 0 {
		return 0, newError(ErrorBrokerRejected, "Cannot estimate crypto order notional without a quote price")
	}
	return *intent.Quantity * price, nil
}

func cryptoSafetyPrice(quote map[string]any) float64 {
	price := maxCryptoPrice(quote)
	for _, row := range resultsRows(quote) {
		if rowPrice := maxCryptoPrice(row); rowPrice > price {
			price = rowPrice
		}
	}
	return price
}

func maxCryptoPrice(row map[string]any) float64 {
	price := 0.0
	for _, key := range []string{
		"ask_inclusive_of_buy_spread",
		"bid_inclusive_of_sell_spread",
		"ask_price",
		"bid_price",
		"ask",
		"bid",
		"mark_price",
		"mark",
		"last_trade_price",
		"price",
	} {
		if candidate := floatFromAny(row[key]); candidate > price {
			price = candidate
		}
	}
	return price
}
