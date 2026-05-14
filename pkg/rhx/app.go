package rhx

import (
	"context"
	"fmt"
	"strconv"
	"strings"
)

type globalOptions struct {
	Output   OutputOptions
	Profile  string
	Provider string
	Config   string
	Verbose  bool
}

type appRuntime struct {
	cfg       RuntimeConfig
	auth      *AuthManager
	brokerage *BrokerageProvider
	crypto    *OfficialCryptoProvider
	safety    *SafetyEngine
	opts      globalOptions
}

func Run(ctx context.Context, args []string) int {
	opts, commandArgs, err := parseGlobalOptions(args)
	if err != nil {
		ce := cliError(err)
		writeStderrError("global options", "", ce, opts.Output)
		return ce.ExitCode
	}
	if len(commandArgs) == 0 || commandArgs[0] == "--help" || commandArgs[0] == "-h" {
		printHelp()
		return 0
	}
	if opts.Profile == "" {
		opts.Profile = "default"
	}
	if opts.Provider == "" {
		opts.Provider = "auto"
	}
	cfg, err := loadRuntimeConfig(opts.Config, opts.Profile)
	if err != nil {
		ce := cliError(err)
		writeStderrError("runtime init", "", ce, opts.Output)
		return ce.ExitCode
	}
	if opts.Provider == "auto" && cfg.App.ProviderDefault != "" {
		opts.Provider = cfg.App.ProviderDefault
	}
	auth := newAuthManager(cfg)
	safety, err := newSafetyEngine(cfg.Paths.StatePath, &cfg.App.Safety)
	if err != nil {
		ce := cliError(err)
		writeStderrError("runtime init", "", ce, opts.Output)
		return ce.ExitCode
	}
	rt := &appRuntime{
		cfg:       cfg,
		auth:      auth,
		brokerage: newBrokerageProvider(auth),
		crypto:    newOfficialCryptoProvider(auth),
		safety:    safety,
		opts:      opts,
	}
	return rt.dispatch(ctx, commandArgs)
}

func (rt *appRuntime) dispatch(ctx context.Context, args []string) int {
	switch args[0] {
	case "auth":
		return rt.dispatchAuth(ctx, args[1:])
	case "live":
		return rt.dispatchLive(args[1:])
	case "account":
		return rt.dispatchAccount(ctx, args[1:])
	case "positions":
		return rt.dispatchPositions(ctx, args[1:])
	case "quote":
		return rt.dispatchQuote(ctx, args[1:])
	case "orders":
		return rt.dispatchOrders(ctx, args[1:])
	case "options":
		return rt.dispatchOptions(ctx, args[1:])
	case "portfolio":
		return rt.dispatchPortfolio(ctx, args[1:])
	case "doctor":
		return rt.run("doctor", "", func() (any, map[string]any, error) {
			return rt.doctor(ctx), nil, nil
		})
	default:
		ce := wrapError(ErrorValidation, "Unknown command: %s", args[0])
		writeStderrError("dispatch", "", ce, rt.opts.Output)
		return ce.ExitCode
	}
}

func (rt *appRuntime) dispatchOptions(ctx context.Context, args []string) int {
	if len(args) == 0 {
		return rt.usageError("options", "Missing options subcommand")
	}
	switch args[0] {
	case "chains":
		flags, err := parseCommandFlags(args[1:], nil)
		if err != nil {
			return rt.commandError("options chains", "brokerage", err)
		}
		if len(flags.Positionals) != 1 {
			return rt.usageError("options chains", "Expected: options chains SYMBOL")
		}
		return rt.run("options chains", "brokerage", func() (any, map[string]any, error) {
			data, err := rt.brokerage.optionChain(ctx, flags.Positionals[0])
			return data, nil, err
		})
	case "expirations":
		flags, err := parseCommandFlags(args[1:], nil)
		if err != nil {
			return rt.commandError("options expirations", "brokerage", err)
		}
		if len(flags.Positionals) != 1 {
			return rt.usageError("options expirations", "Expected: options expirations SYMBOL")
		}
		return rt.run("options expirations", "brokerage", func() (any, map[string]any, error) {
			data, err := rt.brokerage.optionExpirations(ctx, flags.Positionals[0])
			return data, nil, err
		})
	case "strikes":
		flags, err := parseCommandFlags(args[1:], nil)
		if err != nil {
			return rt.commandError("options strikes", "brokerage", err)
		}
		if len(flags.Positionals) != 1 {
			return rt.usageError("options strikes", "Expected: options strikes SYMBOL --expiration-date YYYY-MM-DD")
		}
		expirationDate := flags.Value("expiration-date")
		if expirationDate == "" {
			return rt.usageError("options strikes", "--expiration-date is required")
		}
		optionType := valueOrDefault(strings.ToLower(flags.Value("option-type")), "both")
		return rt.run("options strikes", "brokerage", func() (any, map[string]any, error) {
			data, err := rt.brokerage.optionStrikes(ctx, flags.Positionals[0], expirationDate, optionType)
			return data, nil, err
		})
	case "contracts":
		return rt.dispatchOptionContracts(ctx, args[1:])
	case "quotes":
		return rt.dispatchOptionQuotes(ctx, args[1:])
	default:
		return rt.usageError("options", "Unknown options subcommand: "+args[0])
	}
}

func (rt *appRuntime) dispatchOptionContracts(ctx context.Context, args []string) int {
	if len(args) == 0 || args[0] != "find" {
		return rt.usageError("options contracts", "Expected: options contracts find")
	}
	flags, err := parseCommandFlags(args[1:], nil)
	if err != nil {
		return rt.commandError("options contracts find", "brokerage", err)
	}
	symbol := flags.Value("symbol")
	expirationDate := flags.Value("expiration-date")
	strike := flags.Value("strike")
	optionType := strings.ToLower(flags.Value("option-type"))
	if symbol == "" || expirationDate == "" || strike == "" || optionType == "" {
		return rt.usageError("options contracts find", "--symbol, --expiration-date, --strike, and --option-type are required")
	}
	return rt.run("options contracts find", "brokerage", func() (any, map[string]any, error) {
		data, err := rt.brokerage.optionContract(ctx, symbol, expirationDate, strike, optionType)
		return data, nil, err
	})
}

func (rt *appRuntime) dispatchOptionQuotes(ctx context.Context, args []string) int {
	if len(args) == 0 {
		return rt.usageError("options quotes", "Missing options quotes subcommand")
	}
	switch args[0] {
	case "get":
		flags, err := parseCommandFlags(args[1:], nil)
		if err != nil {
			return rt.commandError("options quotes get", "brokerage", err)
		}
		symbol := flags.Value("symbol")
		expirationDate := flags.Value("expiration-date")
		strike := flags.Value("strike")
		optionType := strings.ToLower(flags.Value("option-type"))
		if symbol == "" || expirationDate == "" || strike == "" || optionType == "" {
			return rt.usageError("options quotes get", "--symbol, --expiration-date, --strike, and --option-type are required")
		}
		return rt.run("options quotes get", "brokerage", func() (any, map[string]any, error) {
			data, err := rt.brokerage.optionQuote(ctx, symbol, expirationDate, strike, optionType)
			return data, nil, err
		})
	case "list":
		flags, err := parseCommandFlags(args[1:], nil)
		if err != nil {
			return rt.commandError("options quotes list", "brokerage", err)
		}
		symbol := flags.Value("symbol")
		expirationDate := flags.Value("expiration-date")
		if symbol == "" || expirationDate == "" {
			return rt.usageError("options quotes list", "--symbol and --expiration-date are required")
		}
		optionType := valueOrDefault(strings.ToLower(flags.Value("option-type")), "both")
		return rt.run("options quotes list", "brokerage", func() (any, map[string]any, error) {
			data, err := rt.brokerage.optionQuotes(ctx, symbol, expirationDate, optionType)
			return data, nil, err
		})
	default:
		return rt.usageError("options quotes", "Unknown options quotes subcommand: "+args[0])
	}
}

func (rt *appRuntime) dispatchAuth(ctx context.Context, args []string) int {
	if len(args) == 0 {
		return rt.usageError("auth", "Missing auth subcommand")
	}
	switch args[0] {
	case "login":
		flags, err := parseCommandFlags(args[1:], boolSet("non-interactive", "force"))
		if err != nil {
			return rt.commandError("auth login", "brokerage", err)
		}
		return rt.run("auth login", "brokerage", func() (any, map[string]any, error) {
			status, err := rt.auth.ensureBrokerageAuthenticated(ctx, !flags.Bool("non-interactive"), flags.Bool("force"))
			if err != nil {
				return nil, nil, err
			}
			return map[string]any{
				"brokerage":    AuthStatus{Provider: "brokerage", Authenticated: true, Detail: "Authenticated"},
				"session_file": rt.auth.SessionPath,
				"created_at":   status.CreatedAt.Format(timeRFC3339()),
			}, nil, nil
		})
	case "status":
		return rt.run("auth status", "", func() (any, map[string]any, error) {
			return map[string]any{
				"brokerage": rt.auth.passiveStatus(),
				"crypto":    rt.cryptoPassiveStatus(),
			}, nil, nil
		})
	case "verify":
		return rt.run("auth verify", "", func() (any, map[string]any, error) {
			return map[string]any{
				"brokerage": rt.auth.brokerageStatus(ctx),
				"crypto":    rt.auth.cryptoStatus(ctx),
			}, nil, nil
		})
	case "refresh":
		flags, err := parseCommandFlags(args[1:], boolSet("non-interactive"))
		if err != nil {
			return rt.commandError("auth refresh", "brokerage", err)
		}
		return rt.run("auth refresh", "brokerage", func() (any, map[string]any, error) {
			_, err := rt.auth.ensureBrokerageAuthenticated(ctx, !flags.Bool("non-interactive"), true)
			if err != nil {
				return nil, nil, err
			}
			return map[string]any{"brokerage": AuthStatus{Provider: "brokerage", Authenticated: true, Detail: "Authenticated"}}, nil, nil
		})
	case "logout":
		flags, err := parseCommandFlags(args[1:], boolSet("forget-creds"))
		if err != nil {
			return rt.commandError("auth logout", "", err)
		}
		return rt.run("auth logout", "", func() (any, map[string]any, error) {
			rt.auth.logout(flags.Bool("forget-creds"))
			return map[string]any{"logged_out": true, "forget_creds": flags.Bool("forget-creds"), "session_file": rt.auth.SessionPath}, nil, nil
		})
	default:
		return rt.usageError("auth", "Unknown auth subcommand: "+args[0])
	}
}

func (rt *appRuntime) dispatchLive(args []string) int {
	if len(args) == 0 {
		return rt.usageError("live", "Missing live subcommand")
	}
	switch args[0] {
	case "on":
		flags, err := parseCommandFlags(args[1:], boolSet("yes"))
		if err != nil {
			return rt.commandError("live on", "", err)
		}
		return rt.run("live on", "", func() (any, map[string]any, error) {
			ttl := rt.cfg.App.Safety.LiveUnlockTTLSeconds
			if raw := flags.Value("ttl-seconds"); raw != "" {
				parsed, err := strconv.Atoi(raw)
				if err != nil || parsed <= 0 {
					return nil, nil, newError(ErrorValidation, "--ttl-seconds must be a positive integer")
				}
				ttl = parsed
			}
			rt.cfg.App.Safety.LiveMode = true
			rt.cfg.App.Safety.LiveUnlockTTLSeconds = ttl
			rt.safety.Config = &rt.cfg.App.Safety
			token, expiresAt, err := rt.safety.issueLiveUnlock(ttl)
			if err != nil {
				return nil, nil, err
			}
			if err := saveRuntimeConfig(rt.cfg); err != nil {
				return nil, nil, err
			}
			return map[string]any{"live_mode": true, "live_confirm_token": token, "expires_at": expiresAt, "ttl_seconds": ttl}, nil, nil
		})
	case "off":
		return rt.run("live off", "", func() (any, map[string]any, error) {
			rt.cfg.App.Safety.LiveMode = false
			rt.safety.Config = &rt.cfg.App.Safety
			if err := rt.safety.clearLiveUnlock(); err != nil {
				return nil, nil, err
			}
			if err := saveRuntimeConfig(rt.cfg); err != nil {
				return nil, nil, err
			}
			return map[string]any{"live_mode": false}, nil, nil
		})
	case "status":
		return rt.run("live status", "", func() (any, map[string]any, error) {
			return map[string]any{"live_mode": rt.safety.liveModeEnabled(), "live_unlock": rt.safety.liveUnlockStatus()}, nil, nil
		})
	default:
		return rt.usageError("live", "Unknown live subcommand: "+args[0])
	}
}

func (rt *appRuntime) dispatchAccount(ctx context.Context, args []string) int {
	if len(args) == 1 && args[0] == "summary" {
		if rt.opts.Provider == "crypto" {
			return rt.run("account summary", "crypto", func() (any, map[string]any, error) {
				data, err := rt.crypto.accountSummary(ctx)
				return data, nil, err
			})
		}
		return rt.run("account summary", "brokerage", func() (any, map[string]any, error) {
			data, err := rt.brokerage.accountSummary(ctx)
			return data, nil, err
		})
	}
	return rt.usageError("account", "Expected: account summary")
}

func (rt *appRuntime) dispatchPositions(ctx context.Context, args []string) int {
	if len(args) == 1 && args[0] == "list" {
		if rt.opts.Provider == "crypto" {
			return rt.run("positions list", "crypto", func() (any, map[string]any, error) {
				data, err := rt.crypto.positions(ctx)
				return data, nil, err
			})
		}
		return rt.run("positions list", "brokerage", func() (any, map[string]any, error) {
			data, err := rt.brokerage.positions(ctx)
			return data, nil, err
		})
	}
	return rt.usageError("positions", "Expected: positions list")
}

func (rt *appRuntime) dispatchQuote(ctx context.Context, args []string) int {
	if len(args) == 0 {
		return rt.usageError("quote", "Missing quote subcommand")
	}
	switch args[0] {
	case "get":
		flags, err := parseCommandFlags(args[1:], nil)
		if err != nil {
			return rt.commandError("quote get", "", err)
		}
		if len(flags.Positionals) != 1 {
			return rt.usageError("quote get", "Expected: quote get SYMBOL")
		}
		symbol := flags.Positionals[0]
		provider := rt.quoteProvider(ctx, symbol)
		return rt.run("quote get", provider, func() (any, map[string]any, error) {
			if provider == "crypto" {
				data, err := rt.crypto.quote(ctx, symbol)
				return data, nil, err
			}
			data, err := rt.brokerage.quote(ctx, symbol)
			return data, nil, err
		})
	case "list":
		flags, err := parseCommandFlags(args[1:], boolSet("strict"))
		if err != nil {
			return rt.commandError("quote list", "", err)
		}
		symbols, err := parseSymbols(flags.Value("symbols"))
		if err != nil {
			return rt.commandError("quote list", "", err)
		}
		return rt.run("quote list", rt.opts.Provider, func() (any, map[string]any, error) {
			rows := []map[string]any{}
			for _, symbol := range symbols {
				provider := rt.quoteProvider(ctx, symbol)
				var raw map[string]any
				var err error
				if provider == "crypto" {
					raw, err = rt.crypto.quote(ctx, symbol)
					raw["asset_type"] = "crypto"
				} else {
					raw, err = rt.brokerage.quote(ctx, symbol)
				}
				if err != nil {
					if flags.Bool("strict") {
						return nil, nil, err
					}
					rows = append(rows, map[string]any{"symbol": symbol, "error": err.Error(), "provider": provider})
					continue
				}
				rows = append(rows, flattenQuote(raw, provider))
			}
			return rows, nil, nil
		})
	default:
		return rt.usageError("quote", "Unknown quote subcommand: "+args[0])
	}
}

func (rt *appRuntime) dispatchOrders(ctx context.Context, args []string) int {
	if len(args) == 0 {
		return rt.usageError("orders", "Missing orders subcommand")
	}
	switch args[0] {
	case "list":
		flags, err := parseCommandFlags(args[1:], boolSet("open"))
		if err != nil {
			return rt.commandError("orders list", "", err)
		}
		assetType := strings.ToLower(flags.Value("asset-type"))
		provider := rt.orderProvider(assetType)
		return rt.run("orders list", provider, func() (any, map[string]any, error) {
			if provider == "crypto" {
				rows, err := rt.crypto.listOrders(ctx, flags.Bool("open"))
				return rows, nil, err
			}
			rows, err := rt.brokerage.listOrders(ctx, assetType, flags.Bool("open"))
			return rows, nil, err
		})
	case "get":
		flags, err := parseCommandFlags(args[1:], nil)
		if err != nil {
			return rt.commandError("orders get", "", err)
		}
		if len(flags.Positionals) != 1 {
			return rt.usageError("orders get", "Expected: orders get ORDER_ID")
		}
		assetType := strings.ToLower(flags.Value("asset-type"))
		provider := rt.orderProvider(assetType)
		return rt.run("orders get", provider, func() (any, map[string]any, error) {
			if provider == "crypto" {
				data, err := rt.crypto.getOrder(ctx, flags.Positionals[0])
				return data, nil, err
			}
			data, err := rt.brokerage.getOrder(ctx, flags.Positionals[0], assetType)
			return data, nil, err
		})
	case "cancel":
		flags, err := parseCommandFlags(args[1:], nil)
		if err != nil {
			return rt.commandError("orders cancel", "", err)
		}
		if len(flags.Positionals) != 1 {
			return rt.usageError("orders cancel", "Expected: orders cancel ORDER_ID")
		}
		assetType := strings.ToLower(flags.Value("asset-type"))
		provider := rt.orderProvider(assetType)
		return rt.run("orders cancel", provider, func() (any, map[string]any, error) {
			if provider == "crypto" {
				data, err := rt.crypto.cancelOrder(ctx, flags.Positionals[0])
				return data, nil, err
			}
			data, err := rt.brokerage.cancelOrder(ctx, flags.Positionals[0], assetType)
			return data, nil, err
		})
	case "stock":
		if len(args) >= 2 && args[1] == "place" {
			return rt.placeStock(ctx, args[2:])
		}
		if len(args) >= 2 && args[1] == "sell-all" {
			return rt.sellAllStock(ctx, args[2:])
		}
	case "crypto":
		if len(args) >= 2 && args[1] == "place" {
			return rt.placeCrypto(ctx, args[2:])
		}
	}
	return rt.usageError("orders", "Unknown orders command")
}

func (rt *appRuntime) placeStock(ctx context.Context, args []string) int {
	flags, err := parseCommandFlags(args, boolSet("extended-hours"))
	if err != nil {
		return rt.commandError("orders stock place", "brokerage", err)
	}
	quantityRaw := strings.TrimSpace(flags.Value("qty"))
	intent := StockOrderIntent{
		Symbol:        strings.ToUpper(flags.Value("symbol")),
		Side:          strings.ToLower(flags.Value("side")),
		Type:          valueOrDefault(strings.ToLower(flags.Value("type")), "market"),
		Quantity:      parseFloatPtr(quantityRaw),
		QuantityRaw:   quantityRaw,
		NotionalUSD:   parseFloatPtr(flags.Value("notional-usd")),
		LimitPrice:    parseFloatPtr(flags.Value("limit-price")),
		StopPrice:     parseFloatPtr(flags.Value("stop-price")),
		TimeInForce:   valueOrDefault(strings.ToLower(flags.Value("time-in-force")), "gtc"),
		ExtendedHours: flags.Bool("extended-hours"),
	}
	return rt.run("orders stock place", "brokerage", func() (any, map[string]any, error) {
		if err := validateStockIntent(intent); err != nil {
			return nil, nil, err
		}
		if err := rt.safety.requireLiveAuthorization(flags.Value("live-confirm-token")); err != nil {
			return nil, nil, err
		}
		estimated, err := rt.brokerage.estimateStockOrderNotional(ctx, intent)
		if err != nil {
			return nil, nil, err
		}
		if err := rt.safety.enforce(intent.Symbol, estimated); err != nil {
			return nil, nil, err
		}
		result, estimated, err := rt.brokerage.placeStockOrder(ctx, intent)
		if err != nil {
			return nil, nil, err
		}
		return result, nil, rt.safety.recordNotional(estimated)
	})
}

func (rt *appRuntime) sellAllStock(ctx context.Context, args []string) int {
	flags, err := parseCommandFlags(args, nil)
	if err != nil {
		return rt.commandError("orders stock sell-all", "brokerage", err)
	}
	symbol := strings.ToUpper(flags.Value("symbol"))
	timeInForce := valueOrDefault(strings.ToLower(flags.Value("time-in-force")), "gfd")
	return rt.run("orders stock sell-all", "brokerage", func() (any, map[string]any, error) {
		if symbol == "" {
			return nil, nil, newError(ErrorValidation, "--symbol is required")
		}
		if err := rt.safety.requireLiveAuthorization(flags.Value("live-confirm-token")); err != nil {
			return nil, nil, err
		}
		intent, position, err := rt.brokerage.sellAllStockIntent(ctx, symbol, timeInForce)
		if err != nil {
			return nil, nil, err
		}
		estimated, err := rt.brokerage.estimateStockOrderNotional(ctx, intent)
		if err != nil {
			return nil, nil, err
		}
		if err := rt.safety.enforce(intent.Symbol, estimated); err != nil {
			return nil, nil, err
		}
		result, estimated, err := rt.brokerage.placeStockOrder(ctx, intent)
		if err != nil {
			return nil, nil, err
		}
		result["quantity"] = intent.QuantityRaw
		result["source_position"] = position
		return result, nil, rt.safety.recordNotional(estimated)
	})
}

func (rt *appRuntime) placeCrypto(ctx context.Context, args []string) int {
	flags, err := parseCommandFlags(args, nil)
	if err != nil {
		return rt.commandError("orders crypto place", "crypto", err)
	}
	intent := CryptoOrderIntent{
		Symbol:      strings.ToUpper(flags.Value("symbol")),
		Side:        strings.ToLower(flags.Value("side")),
		Type:        valueOrDefault(strings.ToLower(flags.Value("type")), "market"),
		AmountIn:    valueOrDefault(strings.ToLower(flags.Value("amount-in")), "quantity"),
		Quantity:    parseFloatPtr(flags.Value("qty")),
		NotionalUSD: parseFloatPtr(flags.Value("notional-usd")),
		LimitPrice:  parseFloatPtr(flags.Value("limit-price")),
		TimeInForce: valueOrDefault(strings.ToLower(flags.Value("time-in-force")), "gtc"),
	}
	provider := rt.orderProvider("crypto")
	return rt.run("orders crypto place", provider, func() (any, map[string]any, error) {
		if err := rt.safety.requireLiveAuthorization(flags.Value("live-confirm-token")); err != nil {
			return nil, nil, err
		}
		if provider != "crypto" {
			return nil, nil, newError(ErrorValidation, "crypto order placement requires official crypto API credentials or --provider crypto")
		}
		if err := rt.safety.enforce(intent.Symbol, estimateCryptoIntent(intent)); err != nil {
			return nil, nil, err
		}
		result, estimated, err := rt.crypto.placeOrder(ctx, intent)
		if err != nil {
			return nil, nil, err
		}
		return result, nil, rt.safety.recordNotional(estimated)
	})
}

func (rt *appRuntime) dispatchPortfolio(ctx context.Context, args []string) int {
	if len(args) == 0 || args[0] != "analyze" {
		return rt.usageError("portfolio", "Expected: portfolio analyze")
	}
	flags, err := parseCommandFlags(args[1:], boolSet("include-holdings", "no-include-holdings"))
	if err != nil {
		return rt.commandError("portfolio analyze", "brokerage", err)
	}
	top := 10
	if raw := flags.Value("top"); raw != "" {
		parsed, err := strconv.Atoi(raw)
		if err != nil || parsed < 1 {
			return rt.commandError("portfolio analyze", "brokerage", newError(ErrorValidation, "--top must be >= 1"))
		}
		top = parsed
	}
	return rt.run("portfolio analyze", "brokerage", func() (any, map[string]any, error) {
		return rt.portfolioAnalysis(ctx, top)
	})
}

func (rt *appRuntime) portfolioAnalysis(ctx context.Context, top int) (map[string]any, map[string]any, error) {
	summary, err := rt.brokerage.accountSummary(ctx)
	if err != nil {
		return nil, nil, err
	}
	positions, err := rt.brokerage.positions(ctx)
	if err != nil {
		return nil, nil, err
	}
	account := asMap(summary["account_profile"])
	portfolio := asMap(summary["portfolio_profile"])
	return map[string]any{
		"account": map[string]any{
			"equity":              portfolio["equity"],
			"market_value":        portfolio["market_value"],
			"cash":                account["cash"],
			"buying_power":        account["buying_power"],
			"withdrawable_amount": firstAny(portfolio, "withdrawable_amount"),
		},
		"allocation":   limitRows(positions, top),
		"generated_at": nowRFC3339(),
	}, nil, nil
}

func limitRows(rows []map[string]any, n int) []map[string]any {
	if n > 0 && len(rows) > n {
		return rows[:n]
	}
	return rows
}

func (rt *appRuntime) doctor(ctx context.Context) map[string]any {
	return map[string]any{
		"config_path":  rt.cfg.Paths.ConfigPath,
		"state_path":   rt.cfg.Paths.StatePath,
		"session_file": rt.auth.SessionPath,
		"auth": map[string]any{
			"brokerage": rt.auth.passiveStatus(),
			"crypto":    rt.cryptoPassiveStatus(),
		},
		"live_mode": rt.safety.liveModeEnabled(),
	}
}

func (rt *appRuntime) cryptoPassiveStatus() AuthStatus {
	apiKey, privateKey, _ := rt.auth.Store.cryptoCredentials(rt.auth.Profile)
	return AuthStatus{
		Provider:      "crypto",
		Authenticated: apiKey != "" && privateKey != "",
		Detail:        map[bool]string{true: "Credentials configured", false: "Missing RH_CRYPTO_API_KEY or RH_CRYPTO_PRIVATE_KEY_B64"}[apiKey != "" && privateKey != ""],
	}
}

func (rt *appRuntime) quoteProvider(ctx context.Context, symbol string) string {
	if rt.opts.Provider == "crypto" {
		return "crypto"
	}
	if rt.opts.Provider == "brokerage" {
		return "brokerage"
	}
	if isCryptoSymbol(symbol) && rt.cryptoPassiveStatus().Authenticated {
		return "crypto"
	}
	return "brokerage"
}

func (rt *appRuntime) orderProvider(assetType string) string {
	if rt.opts.Provider == "crypto" || assetType == "crypto" && rt.cryptoPassiveStatus().Authenticated {
		return "crypto"
	}
	return "brokerage"
}

func (rt *appRuntime) run(command string, provider string, fn func() (any, map[string]any, error)) int {
	data, meta, err := fn()
	if err != nil {
		return rt.commandError(command, provider, err)
	}
	if meta == nil {
		meta = map[string]any{}
	}
	writeStdoutSuccess(command, provider, data, rt.opts.Output, meta)
	return 0
}

func (rt *appRuntime) commandError(command string, provider string, err error) int {
	ce := cliError(err)
	writeStderrError(command, provider, ce, rt.opts.Output)
	return ce.ExitCode
}

func (rt *appRuntime) usageError(command string, message string) int {
	return rt.commandError(command, "", newError(ErrorValidation, message))
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

func parseFloatPtr(raw string) *float64 {
	if raw == "" {
		return nil
	}
	value, err := strconv.ParseFloat(raw, 64)
	if err != nil {
		return nil
	}
	return &value
}

func valueOrDefault(value string, fallback string) string {
	if value == "" {
		return fallback
	}
	return value
}

func parseGlobalOptions(args []string) (globalOptions, []string, error) {
	opts := globalOptions{Output: defaultOutputOptions(), Provider: "auto", Profile: "default"}
	remaining := []string{}
	for i := 0; i < len(args); i++ {
		arg := args[i]
		switch {
		case arg == "--json":
			opts.Output.JSON = true
		case arg == "--human":
			opts.Output.Human = true
		case arg == "--verbose":
			opts.Verbose = true
		case arg == "--no-color":
		case arg == "--view" || arg == "--fields" || arg == "--limit" || arg == "--profile" || arg == "--provider" || arg == "--config":
			if i+1 >= len(args) {
				return opts, nil, wrapError(ErrorValidation, "%s requires a value", arg)
			}
			i++
			if err := setGlobalValue(&opts, strings.TrimPrefix(arg, "--"), args[i]); err != nil {
				return opts, nil, err
			}
		case strings.HasPrefix(arg, "--view=") || strings.HasPrefix(arg, "--fields=") || strings.HasPrefix(arg, "--limit=") || strings.HasPrefix(arg, "--profile=") || strings.HasPrefix(arg, "--provider=") || strings.HasPrefix(arg, "--config="):
			name, value, _ := strings.Cut(strings.TrimPrefix(arg, "--"), "=")
			if err := setGlobalValue(&opts, name, value); err != nil {
				return opts, nil, err
			}
		default:
			remaining = append(remaining, arg)
		}
	}
	if opts.Output.JSON && opts.Output.Human {
		return opts, nil, newError(ErrorValidation, "--human cannot be used with --json")
	}
	if opts.Output.View != "summary" && opts.Output.View != "full" {
		return opts, nil, newError(ErrorValidation, "Unsupported --view. Use summary or full.")
	}
	if len(opts.Output.Fields) > 0 && opts.Output.View != "summary" {
		return opts, nil, newError(ErrorValidation, "--fields requires --view summary")
	}
	return opts, remaining, nil
}

func setGlobalValue(opts *globalOptions, name string, value string) error {
	switch name {
	case "view":
		opts.Output.View = strings.ToLower(value)
	case "fields":
		fields, err := parseFields(value)
		if err != nil {
			return err
		}
		opts.Output.Fields = fields
	case "limit":
		limit, err := strconv.Atoi(value)
		if err != nil || limit < 1 {
			return newError(ErrorValidation, "--limit must be >= 1")
		}
		opts.Output.Limit = limit
	case "profile":
		opts.Profile = value
	case "provider":
		provider := strings.ToLower(value)
		if provider != "auto" && provider != "brokerage" && provider != "crypto" {
			return newError(ErrorValidation, "--provider must be auto, brokerage, or crypto")
		}
		opts.Provider = provider
	case "config":
		opts.Config = value
	}
	return nil
}

type parsedFlags struct {
	Values      map[string]string
	Bools       map[string]bool
	Positionals []string
}

func (f parsedFlags) Value(name string) string {
	return f.Values[name]
}

func (f parsedFlags) Bool(name string) bool {
	return f.Bools[name]
}

func parseCommandFlags(args []string, bools map[string]bool) (parsedFlags, error) {
	flags := parsedFlags{Values: map[string]string{}, Bools: map[string]bool{}, Positionals: []string{}}
	for i := 0; i < len(args); i++ {
		arg := args[i]
		if !strings.HasPrefix(arg, "--") {
			flags.Positionals = append(flags.Positionals, arg)
			continue
		}
		nameValue := strings.TrimPrefix(arg, "--")
		name, value, hasValue := strings.Cut(nameValue, "=")
		if bools != nil && bools[name] {
			if hasValue {
				flags.Bools[name] = value == "true" || value == "1" || value == "yes"
			} else {
				flags.Bools[name] = true
			}
			continue
		}
		if !hasValue {
			if i+1 >= len(args) {
				return flags, wrapError(ErrorValidation, "--%s requires a value", name)
			}
			i++
			value = args[i]
		}
		flags.Values[name] = value
	}
	return flags, nil
}

func boolSet(names ...string) map[string]bool {
	out := map[string]bool{}
	for _, name := range names {
		out[name] = true
	}
	return out
}

func nowRFC3339() string {
	return timeNowUTC()
}

func timeRFC3339() string {
	return "2006-01-02T15:04:05Z07:00"
}

func printHelp() {
	fmt.Println(`rhx

Go-native Robinhood CLI for agent workflows.

Usage:
  rhx [--json] [--profile NAME] [--provider auto|brokerage|crypto] <command>

Commands:
  auth login|status|verify|refresh|logout
  live on|off|status
  account summary
  positions list
  quote get SYMBOL
  quote list --symbols AAPL,MSFT
  orders list|get|cancel
  orders stock place --symbol AAPL --side buy --qty 1 --live-confirm-token TOKEN
  orders stock sell-all --symbol AAPL --live-confirm-token TOKEN
  orders crypto place --symbol BTC-USD --side buy --qty 0.001 --live-confirm-token TOKEN
  options expirations AAPL
  options strikes AAPL --expiration-date 2026-12-18 --option-type both
  options quotes get --symbol AAPL --expiration-date 2026-12-18 --strike 200 --option-type call
  portfolio analyze
  doctor`)
}
