# rhx

Go-native Robinhood CLI available through `npx`.

This npm package launches a prebuilt native `rhx` binary for the current platform. It does not fall back to Python.

## Quick Start

```bash
npx rhx --help
npx rhx auth login
npx rhx auth verify
```

Brokerage sessions are refreshed from the saved refresh token before `rhx`
falls back to password login. Interactive commands wait for Robinhood approval
challenges; non-interactive commands fail fast instead of repeatedly triggering
MFA prompts.

## Common Examples

```bash
npx rhx --json quote get AAPL
npx rhx --json quote list --symbols AAPL,MSFT,BTC-USD
npx rhx --json options expirations AAPL

TOKEN=$(npx rhx --json live on --yes | jq -r '.data.live_confirm_token')
npx rhx --json orders stock place --symbol AAPL --side buy --type market --qty 1 --live-confirm-token "$TOKEN"
npx rhx --json orders stock sell-all --symbol AAPL --live-confirm-token "$TOKEN"
```

## Platform Support

- `darwin-arm64`
- `linux-x64`
- `win32-x64`

## Links

- Repo and full docs: <https://github.com/finlayi/robinhood-cli>
- Security policy: <https://github.com/finlayi/robinhood-cli/blob/main/SECURITY.md>
