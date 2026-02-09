# Releasing rhx

This project ships through two channels:

1. Python package (canonical): PyPI
2. npm wrapper (for `npx` workflows): `rhx`

## Prerequisites

1. PyPI trusted publishing configured for this repository.
2. npm token in GitHub Actions secret `NPM_TOKEN` or npm trusted publishing configured.
3. `pyproject.toml` version and `npm/package.json` version updated together.

## Local release checks

```bash
.venv/bin/python -m pytest --cov=src/rhx --cov-report=term-missing
cd npm && npm test
```

## Release flow

1. Bump versions:
   - `/Users/ianfinlay/src/other/robinhood-cli/pyproject.toml`
   - `/Users/ianfinlay/src/other/robinhood-cli/npm/package.json`
2. Commit + push to `main`.
3. Create and push tag:

```bash
git tag v0.1.1
git push origin v0.1.1
```

4. GitHub Actions runs:
   - `/Users/ianfinlay/src/other/robinhood-cli/.github/workflows/release-python.yml`
   - `/Users/ianfinlay/src/other/robinhood-cli/.github/workflows/release-npm.yml`

## Install examples after release

```bash
pipx install rhx
uvx --from rhx rhx --help
npx rhx --help
brew install <your-tap>/rhx
```
