# Releasing rhx

This project ships through npm:

1. Platform packages: `rhx-darwin-arm64`, `rhx-linux-x64`, `rhx-win32-x64`
2. Entrypoint package: `rhx`

The entrypoint package only locates and executes the platform Go binary. It does not run Python.

## Prerequisites

1. npm token in GitHub Actions secret `NPM_TOKEN` or npm trusted publishing configured.
2. `npm/package.json` version is the release version.
3. Platform package versions are in sync with the entrypoint package:
   - `npm/platform/rhx-darwin-arm64/package.json`
   - `npm/platform/rhx-linux-x64/package.json`
   - `npm/platform/rhx-win32-x64/package.json`
4. Branch protection enabled on `main`.
5. Protected tag pattern `v*` enabled.

## Local Release Checks

```bash
go test ./...
cd npm && npm test
node scripts/build-native.cjs
```

To sync platform package versions automatically:

```bash
cd npm && npm run sync:versions
```

## Automated Release

On merge/push to `main`, `Release On Main` runs after CI succeeds:

1. Reads version from `npm/package.json`.
2. Creates/pushes `v<version>` if it does not already exist.
3. Creates a GitHub Release.
4. Dispatches `.github/workflows/release-npm.yml`.

The npm release workflow builds native binaries on each target runner, stages them into platform packages, publishes platform packages, then publishes the entrypoint package.

## Manual Release

1. Bump `npm/package.json`.
2. Run `cd npm && npm run sync:versions`.
3. Commit and push to `main`.
4. Create and push the tag:

```bash
git tag v0.3.3
git push origin v0.3.3
```

5. GitHub Actions runs `.github/workflows/release-npm.yml`.

## Install Example

```bash
npx rhx --help
```
