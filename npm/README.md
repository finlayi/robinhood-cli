# rhx

Native npm launcher for the `rhx` CLI.

## Usage

```bash
npx rhx --help
npx rhx quote get AAPL
```

Supported no-prereq platforms:

1. macOS arm64
2. Linux x64
3. Windows x64

The package installs a matching prebuilt native binary via optional dependencies and runs it directly.

If you are on an unsupported platform, `rhx` falls back to Python launchers (`uvx`/`pipx`).

To force Python fallback even on a supported platform:

```bash
RHX_ENABLE_PYTHON_FALLBACK=1 npx rhx --help
```
