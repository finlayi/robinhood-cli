# rhx

Go-native Robinhood CLI for agent workflows.

## What It Does

- Calls Robinhood brokerage endpoints directly for account, positions, quotes, and stock orders.
- Calls Robinhood's official crypto trading API directly when crypto API credentials are configured.
- Keeps `npx rhx` as the primary entrypoint through prebuilt Go binaries.
- Stores brokerage credentials in the OS keyring when available, with `RH_USERNAME`/`RH_PASSWORD` env vars as a non-persistent fallback.
- Stores brokerage sessions as owner-only JSON files under `~/.config/robinhood-cli/sessions`.
- Uses global live mode plus short-lived confirmation tokens before order placement.
- Emits deterministic JSON envelopes with `--json` for automation.

## Install

```bash
npx rhx --help
```

Supported native npm targets:

- `darwin-arm64`
- `linux-x64`
- `win32-x64`

Local development:

```bash
go test ./...
go build -o dist/rhx ./cmd/rhx
./dist/rhx --help
```

Go library usage:

```go
import (
	"context"

	"github.com/finlayi/robinhood-cli/pkg/rhx"
)

client, err := rhx.NewClient("default", "")
positions, err := client.Positions(context.Background())
```

## Authentication

```bash
rhx auth login
rhx auth status   # passive/local state only
rhx auth verify   # active API verification
```

`auth status` reports local brokerage state:

- `session_file_exists`
- `credentials_present`
- `session_ready`
- `detail`

`auth verify` performs a live API check and reports:

- `authenticated`
- `mfa_required`
- `detail`

Session file:

```text
~/.config/robinhood-cli/sessions/robinhood_<profile>.json
```

Credentials:

- macOS: Keychain via `security`
- Linux: Secret Service via `secret-tool`
- fallback: `RH_USERNAME` and `RH_PASSWORD`

Official crypto API credentials:

- `RH_CRYPTO_API_KEY`
- `RH_CRYPTO_PRIVATE_KEY_B64`

## Live Mode

```bash
rhx live status
rhx live on --yes
rhx live off
```

Order placement is blocked while live mode is off. When live mode is enabled, `rhx live on` returns a short-lived `live_confirm_token`; every order placement command must pass it with `--live-confirm-token`.

## Examples

```bash
rhx --json quote get AAPL
rhx --json quote list --symbols AAPL,MSFT,BTC-USD
rhx --json --fields symbol,quantity positions list
rhx --json --limit 10 orders list
rhx --json account summary
rhx --json portfolio analyze --top 10
rhx --json options expirations AAPL
rhx --json options strikes AAPL --expiration-date 2026-12-18 --option-type both
rhx --json options quotes get --symbol AAPL --expiration-date 2026-12-18 --strike 200 --option-type call
```

Stock order:

```bash
TOKEN=$(rhx --json live on --yes | jq -r '.data.live_confirm_token')
rhx --json orders stock place --symbol AAPL --side buy --type market --qty 1 --live-confirm-token "$TOKEN"
```

Fractional stock orders use notional dollars:

```bash
rhx --json orders stock place --symbol AAPL --side buy --type market --notional-usd 50 --live-confirm-token "$TOKEN"
```

Official crypto order:

```bash
rhx --json --provider crypto orders crypto place \
  --symbol BTC-USD \
  --side buy \
  --type limit \
  --amount-in quantity \
  --qty 0.001 \
  --limit-price 40000 \
  --live-confirm-token "$TOKEN"
```

## JSON Contract

Every JSON command returns:

```json
{
  "ok": true,
  "command": "live status",
  "provider": null,
  "data": {"live_mode": false},
  "error": null,
  "meta": {
    "timestamp": "2026-05-12T00:00:00Z",
    "output_schema": "v3",
    "view": "summary"
  }
}
```

On failure, `ok=false` and `error.code` is one of:

- `VALIDATION_ERROR`
- `AUTH_REQUIRED`
- `MFA_REQUIRED`
- `RATE_LIMITED`
- `BROKER_REJECTED`
- `LIVE_MODE_OFF`
- `SAFETY_POLICY_BLOCK`
- `INTERNAL_ERROR`

## Safety Config

`~/.config/robinhood-cli/config.toml`:

```toml
profile = "default"
provider_default = "auto"

[safety]
live_mode = false
live_unlock_ttl_seconds = 900
max_order_notional = 500.0
max_daily_notional = 2500.0
allow_symbols = []
block_symbols = []
trading_window = "09:30-16:00"
```

## Tests

```bash
go test ./...
cd npm && npm test
```

Detailed guidance is in `docs/testing.md`.

## Distribution

The canonical install path is npm:

```bash
npx rhx --help
```

Release process is documented in `docs/releasing.md`.

## Security Note

This project uses Robinhood APIs directly, including unofficial brokerage endpoints. API behavior can change at any time. Use live mode and safety limits deliberately.
