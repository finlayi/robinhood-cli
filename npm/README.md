# rhx

Auth-first Robinhood CLI available via `npx`.

This npm package is a launcher for the `rhx` CLI. It runs a prebuilt native binary on supported platforms and falls back to Python launchers (`uvx`/`pipx`) when needed.

## Quick Start

```bash
npx rhx --help
npx rhx auth login
npx rhx auth verify
```

## Common Examples

```bash
# Quote lookup
npx rhx --json quote get AAPL

# Batch quotes
npx rhx --json quote list --symbols AAPL,MSFT,BTC-USD

# Enable live mode and place a stock order
TOKEN=$(npx rhx --json live on --yes | jq -r '.data.live_confirm_token')
npx rhx --json orders stock place --symbol AAPL --side buy --type market --qty 1 --live-confirm-token "$TOKEN"

# Option chain discovery
npx rhx --json options expirations AAPL
npx rhx --json options strikes AAPL --expiration-date 2026-12-18 --option-type both
```

## Platform Support

- `darwin-arm64`
- `linux-x64`
- `win32-x64`

Set `RHX_ENABLE_PYTHON_FALLBACK=1` to force Python fallback even on a supported platform.

## Links

- Repo and full docs: <https://github.com/finlayi/robinhood-cli>
- Security policy: <https://github.com/finlayi/robinhood-cli/blob/main/SECURITY.md>
