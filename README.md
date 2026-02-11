# rhx

Auth-first Robinhood CLI wrapper for agent workflows.

## What it does

- Wraps `robin_stocks` for brokerage/equities/options (including spread helpers).
- Wraps Robinhood's official crypto trading API when crypto API credentials are configured.
- Keeps brokerage auth persistent via session pickle and keychain-backed credentials.
- Uses global live mode + short-lived confirmation token + configurable safety limits before placing orders.
- Emits deterministic JSON envelopes with `--json` for automation, with summary-default payloads.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Or with pipx:

```bash
pipx install .
```

`npx` launcher (wrapper package):

```bash
npx rhx --help
```

On supported platforms (`darwin-arm64`, `linux-x64`, `win32-x64`), `npx rhx` uses a prebuilt native binary with no Python launcher setup required.

## Authentication

### Brokerage (`robin_stocks`)

```bash
rhx auth login
rhx auth status   # passive/local state only (no network check)
rhx auth verify   # active API verification
```

- `auth status` returns passive brokerage status fields:
  - `session_pickle_exists`
  - `credentials_present`
  - `session_ready`
  - `detail`
- `auth verify` returns active auth check fields:
  - `authenticated`
  - `mfa_required`
  - `detail`
- Session file: `~/.config/robinhood-cli/sessions/robinhood_<profile>.pickle`
- Credentials: stored in OS keychain (fallback to `RH_USERNAME`/`RH_PASSWORD` env vars)

### Official crypto API

Set either env vars or keychain values:

- `RH_CRYPTO_API_KEY`
- `RH_CRYPTO_PRIVATE_KEY_B64`

Then verify:

```bash
rhx auth verify
rhx doctor
```

## Live mode

```bash
rhx live status
rhx live on --yes
rhx live off
```

Order placement is blocked while live mode is off.
When live mode is enabled, `rhx live on` returns a short-lived `live_confirm_token`; every order placement command must pass it via `--live-confirm-token`.

Example:

```bash
TOKEN=$(rhx --json live on --yes | jq -r '.data.live_confirm_token')
rhx --json orders stock place --symbol AAPL --side buy --type market --qty 1 --live-confirm-token "$TOKEN"
```

## Examples

```bash
# Machine-readable output
rhx --json quote get AAPL

# Batch quotes (non-strict: per-symbol errors in `error` field)
rhx --json quote list --symbols AAPL,MSFT,BTC-USD

# Batch quotes strict mode (fails command if any quote fails)
rhx --json quote list --symbols AAPL,MSFT --strict

# Compact human-readable output
rhx --human quote get AAPL

# Full/raw payload view (legacy-style payloads)
rhx --json --view full positions list

# Trim response fields for agent context efficiency
rhx --json --fields symbol,quantity positions list

# Limit list payload size
rhx --json --limit 10 orders list

# Option chain discovery
rhx --json options expirations AAPL
rhx --json options strikes AAPL --expiration-date 2026-12-18 --option-type both

# Single option contract quote
rhx --json options quotes get --symbol AAPL --expiration-date 2026-12-18 --strike 200 --option-type call

# Option chain quote scan with filters/sort/query pagination
rhx --json options quotes list \
  --symbol AAPL \
  --expiration-date 2026-12-18 \
  --option-type both \
  --delta-min 0.20 \
  --delta-max 0.60 \
  --min-oi 100 \
  --sort open_interest \
  --descending \
  --query-limit 25 \
  --offset 0

# Option order history filtering + pagination
rhx --json options orders list \
  --symbol AAPL \
  --state filled \
  --strategy call \
  --from-date 2025-01-01 \
  --to-date 2026-02-11 \
  --sort created_at \
  --descending \
  --query-limit 100 \
  --offset 0

# Portfolio concentration/risk analytics
rhx --json portfolio analyze --top 10

# Stock order (brokerage)
TOKEN=$(rhx --json live on --yes | jq -r '.data.live_confirm_token')
rhx orders stock place --symbol AAPL --side buy --type market --qty 1 --live-confirm-token "$TOKEN"

# Crypto order (auto routes to official crypto API when credentials exist)
rhx orders crypto place --symbol BTC-USD --side buy --type limit --amount-in quantity --qty 0.001 --limit-price 40000 --live-confirm-token "$TOKEN"

# Option single-leg order
rhx options orders place single \
  --side buy --type limit --position-effect open --credit-or-debit debit \
  --symbol AAPL --qty 1 --expiration-date 2026-12-18 --strike 200 --option-type call --price 1.25 \
  --live-confirm-token "$TOKEN"

# Option credit spread
rhx options orders place credit-spread \
  --symbol AAPL --qty 1 --price 0.75 --expiration-date 2026-12-18 --option-type call \
  --short-strike 200 --long-strike 205 --live-confirm-token "$TOKEN"
```

## JSON contract

Every command returns:

```json
{
  "ok": true,
  "command": "live status",
  "provider": null,
  "data": {"live_mode": false},
  "error": null,
  "meta": {
    "timestamp": "2026-02-09T00:00:00Z",
    "output_schema": "v3",
    "view": "summary",
    "query_total_count": 50,
    "query_returned_count": 25,
    "query_truncated": true,
    "query_offset": 0
  }
}
```

`query_*` metadata appears on commands that support query-time filtering/pagination.

### v0.3.0 migration note

- `auth status` is now passive and side-effect free.
- `auth verify` is new and performs active API auth checks.
- JSON schema marker moved from `v2` to `v3`.
- `quote list --symbols ... [--strict]` is available for batch quote retrieval.
- New options market-data commands:
  - `options expirations`
  - `options strikes`
  - `options quotes get`
  - `options quotes list` with filter/sort/query pagination
- `options orders list` now supports in-command filtering/sorting/query pagination (`--query-limit`, `--offset`).
- `portfolio analyze` adds first-party concentration/exposure/risk analytics.
- Keyring persistence warnings are suppressed unless `--verbose` is enabled.

On failure, `ok=false` and `error.code` is one of:

- `VALIDATION_ERROR`
- `AUTH_REQUIRED`
- `MFA_REQUIRED`
- `RATE_LIMITED`
- `BROKER_REJECTED`
- `LIVE_MODE_OFF`
- `SAFETY_POLICY_BLOCK`
- `INTERNAL_ERROR`

## Safety config

`~/.config/robinhood-cli/config.toml`:

```toml
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
.venv/bin/python -m pytest
```

With coverage:

```bash
.venv/bin/python -m pytest --cov=src/rhx --cov-report=term-missing
```

Detailed guidance is in `docs/testing.md`.

## Distribution Channels

1. Canonical Python package (PyPI): `pipx install rhx`
2. Python no-install runner: `uvx --from rhx rhx ...`
3. npm native wrapper for agent ecosystems: `npx rhx ...`
4. Homebrew tap (optional): `brew install <tap>/rhx`

Release process is documented in `docs/releasing.md`.

## Security hardening notes

- Config/session directories are enforced as user-owned and mode `0700`; config/session files are enforced as mode `0600`.
- Symlinked config/session paths are rejected.
- Brokerage session pickle is validated before use/unlink.
- Crypto signing keys must decode to 32-byte or 64-byte Ed25519 private key material.

## Disclaimer

This project uses unofficial Robinhood APIs through `robin_stocks` for non-crypto brokerage features. API behavior can change at any time.

## Security

For vulnerability reporting instructions, see `SECURITY.md`.

## License

MIT. See `LICENSE`.
