# rhx

Thin npm launcher for the `rhx` Python CLI.

## Why this exists

`rhx` is implemented in Python. This package exists so agent workflows that prefer npm can run it via `npx`.

## Usage

```bash
npx rhx --help
npx rhx quote get AAPL
```

The launcher tries:

1. `uvx --from rhx rhx ...`
2. `pipx run rhx rhx ...`
3. `python3 -m pipx run rhx rhx ...`
4. `python -m pipx run rhx rhx ...`

Set `RHX_PYPI_PACKAGE` to override the default PyPI package name:

```bash
RHX_PYPI_PACKAGE=robinhood-cli-rhx npx rhx --help
```
