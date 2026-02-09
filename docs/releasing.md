# Releasing rhx

This project ships through two channels:

1. Python package (canonical): PyPI
2. npm native wrapper (for `npx` workflows): `rhx` + platform packages

## Prerequisites

1. PyPI trusted publishing configured for this repository.
2. npm token in GitHub Actions secret `NPM_TOKEN` or npm trusted publishing configured.
3. `pyproject.toml` version and `npm/package.json` version updated together.
4. Platform package versions in sync with wrapper package:
   - `npm/platform/rhx-darwin-arm64/package.json`
   - `npm/platform/rhx-linux-x64/package.json`
   - `npm/platform/rhx-win32-x64/package.json`
5. Branch protection enabled on `main` (PRs + reviews + required checks).
6. Protected tag pattern `v*` enabled (only maintainers/admins can create release tags).

## Local release checks

```bash
.venv/bin/python -m pytest --cov=src/rhx --cov-report=term-missing
cd npm && npm test
```

To sync platform package versions automatically:

```bash
cd npm && npm run sync:versions
```

## Release flow

1. Bump versions:
   - `pyproject.toml`
   - `npm/package.json`
2. Commit + push to `main`.
3. Create and push tag:

```bash
git tag v0.1.1
git push origin v0.1.1
```

4. GitHub Actions runs:
   - `.github/workflows/release-python.yml`
   - `.github/workflows/release-npm.yml`
     - Builds native binaries (`darwin-arm64`, `linux-x64`, `win32-x64`)
     - Publishes platform packages (`rhx-<target>`)
     - Publishes wrapper package (`rhx`)

Only users with repository write/maintain/admin access can trigger releases.

## Install examples after release

```bash
pipx install rhx
uvx --from rhx rhx --help
npx rhx --help
brew install <your-tap>/rhx
```
