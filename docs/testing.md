# Testing and Coverage

This project uses `pytest` for unit and command-level CLI tests.

## Quick Start

```bash
# Activate venv created during setup
source .venv/bin/activate

# Run all tests
.venv/bin/python -m pytest

# Run tests with line coverage
.venv/bin/python -m pytest --cov=src/rhx --cov-report=term-missing
```

npm wrapper tests:

```bash
cd npm
npm test
```

## Current Baseline

As of February 9, 2026:

- Total coverage: 97%
- Test count: 74

Coverage command used:

```bash
.venv/bin/python -m pytest --cov=src/rhx --cov-report=term-missing
```

## Test Layout

- `tests/test_auth_flow.py` and `tests/test_auth_additional.py`
: Auth/session lifecycle, keychain behavior fallback, MFA-required handling.
- `tests/test_auth_security_coverage.py`
: Additional auth hardening coverage (interactive flow, owner checks, forced refresh, logout failure handling, keyring happy-paths).
- `tests/test_live_mode.py`, `tests/test_json_contract.py`, `tests/test_cli_commands_extended.py`
: End-to-end command wiring, JSON envelope contract, live mode guardrails, live confirmation token gating, provider routing.
- `tests/test_robin_stocks_provider.py`
: Unofficial provider mapping for stock/crypto/options operations.
- `tests/test_crypto_provider.py`
: Official crypto provider request/signing behavior, key validation, and error mapping.
- `tests/test_safety_engine.py`
: Symbol policies, live token lifecycle, notional caps, trading window checks, daily notional accounting.
- `tests/test_config_security.py`
: Config/session path hardening and permission enforcement.
- `tests/test_models_validation.py`, `tests/test_output.py`, `tests/test_errors.py`
: Model validation and output/error formatting.

## Notes

- Tests intentionally use fakes/mocks for broker-facing calls.
- No tests place real orders.
- CLI tests default to `--json` to assert machine-contract stability.
