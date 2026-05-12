# Testing

This project uses Go unit tests for the native CLI/library and Node tests for the npm launcher.

## Local Checks

```bash
go test ./...

cd npm
npm test
```

Build the native binary locally:

```bash
node npm/scripts/build-native.cjs
./dist/rhx --help
```

## Test Layout

- `pkg/rhx/*_test.go`: parser, safety, auth/session-adjacent, and signing behavior.
- `npm/test/*.test.cjs`: npm launcher target resolution and native-binary execution behavior.

## Notes

- Tests avoid live Robinhood calls.
- No tests place real orders.
- CLI verification should use `--json` when checking machine-contract stability.
