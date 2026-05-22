package rhx

import "context"

// Client is the importable Go API behind the rhx CLI.
type Client struct {
	cfg       RuntimeConfig
	auth      *AuthManager
	brokerage *BrokerageProvider
	crypto    *OfficialCryptoProvider
	safety    *SafetyEngine
}

// NewClient creates a direct Robinhood API client for a profile.
func NewClient(profile string, configPath string) (*Client, error) {
	cfg, err := loadRuntimeConfig(configPath, profile)
	if err != nil {
		return nil, err
	}
	auth := newAuthManager(cfg)
	safety, err := newSafetyEngine(cfg.Paths.StatePath, &cfg.App.Safety)
	if err != nil {
		return nil, err
	}
	return &Client{
		cfg:       cfg,
		auth:      auth,
		brokerage: newBrokerageProvider(auth),
		crypto:    newOfficialCryptoProvider(auth),
		safety:    safety,
	}, nil
}

func (c *Client) AuthStatus() map[string]any {
	return map[string]any{
		"brokerage": c.auth.passiveStatus(),
		"crypto":    c.cryptoPassiveStatus(),
	}
}

func (c *Client) AuthVerify(ctx context.Context) map[string]any {
	return map[string]any{
		"brokerage": c.auth.brokerageStatus(ctx),
		"crypto":    c.auth.cryptoStatus(ctx),
	}
}

func (c *Client) Login(ctx context.Context, interactive bool, force bool) (AuthStatus, error) {
	_, err := c.auth.ensureBrokerageAuthenticated(ctx, interactive, force)
	if err != nil {
		return AuthStatus{}, err
	}
	return AuthStatus{Provider: "brokerage", Authenticated: true, State: "READY", Detail: "Authenticated"}, nil
}

func (c *Client) Logout(forgetCredentials bool) {
	c.auth.logout(forgetCredentials)
}

func (c *Client) AccountSummary(ctx context.Context) (map[string]any, error) {
	return c.brokerage.accountSummary(ctx)
}

func (c *Client) Positions(ctx context.Context) ([]map[string]any, error) {
	return c.brokerage.positions(ctx)
}

func (c *Client) Quote(ctx context.Context, symbol string) (map[string]any, error) {
	return c.brokerage.quote(ctx, symbol)
}

func (c *Client) Quotes(ctx context.Context, symbols []string) ([]map[string]any, error) {
	return c.brokerage.quotes(ctx, symbols)
}

func (c *Client) News(ctx context.Context, symbol string) ([]map[string]any, error) {
	return c.brokerage.news(ctx, symbol)
}

func (c *Client) OptionExpirations(ctx context.Context, symbol string) (map[string]any, error) {
	return c.brokerage.optionExpirations(ctx, symbol)
}

func (c *Client) OptionStrikes(ctx context.Context, symbol string, expirationDate string, optionType string) (map[string]any, error) {
	return c.brokerage.optionStrikes(ctx, symbol, expirationDate, optionType)
}

func (c *Client) OptionQuote(ctx context.Context, symbol string, expirationDate string, strike string, optionType string) (map[string]any, error) {
	return c.brokerage.optionQuote(ctx, symbol, expirationDate, strike, optionType)
}

func (c *Client) OptionQuotes(ctx context.Context, symbol string, expirationDate string, optionType string) ([]map[string]any, error) {
	return c.brokerage.optionQuotes(ctx, symbol, expirationDate, optionType)
}

func (c *Client) CryptoQuote(ctx context.Context, symbol string) (map[string]any, error) {
	return c.crypto.quote(ctx, symbol)
}

func (c *Client) CryptoPositions(ctx context.Context) ([]map[string]any, error) {
	return c.crypto.positions(ctx)
}

func (c *Client) cryptoPassiveStatus() AuthStatus {
	return cryptoPassiveStatus(c.auth)
}
