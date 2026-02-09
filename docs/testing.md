# Testing and Coverage

This project uses `pytest` for unit and command-level CLI tests.

## Quick Start

```bash
# Activate venv created during setup
source .venv/bin/activate

# Run all tests
pytest

# Run tests with line coverage
pytest --cov=src/rhx --cov-report=term-missing
```

## Current Baseline

As of February 9, 2026:

- Total coverage: ~93%
- Test count: 40

Coverage command used:

```bash
pytest --cov=src/rhx --cov-report=term-missing
```

## Test Layout

- `tests/test_auth_flow.py` and `tests/test_auth_additional.py`
: Auth/session lifecycle, keychain behavior fallback, MFA-required handling.
- `tests/test_live_mode.py`, `tests/test_json_contract.py`, `tests/test_cli_commands_extended.py`
: End-to-end command wiring, JSON envelope contract, live mode guardrails, provider routing.
- `tests/test_robin_stocks_provider.py`
: Unofficial provider mapping for stock/crypto/options operations.
- `tests/test_crypto_provider.py`
: Official crypto provider request/signing behavior and error mapping.
- `tests/test_safety_engine.py`
: Symbol policies, notional caps, trading window checks, daily notional accounting.
- `tests/test_models_validation.py`, `tests/test_output.py`
: Model validation and output/error formatting.

## Notes

- Tests intentionally use fakes/mocks for broker-facing calls.
- No tests place real orders.
- CLI tests default to `--json` to assert machine-contract stability.
