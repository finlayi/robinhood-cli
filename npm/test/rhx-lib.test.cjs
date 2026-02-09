const assert = require("node:assert/strict");
const test = require("node:test");

const {
  NATIVE_TARGETS,
  resolveNativeBinary,
  runRhx,
  buildLaunchers,
  runWithLaunchers
} = require("../bin/rhx-lib.cjs");

test("NATIVE_TARGETS covers supported no-prereq platforms", () => {
  assert.deepEqual(Object.keys(NATIVE_TARGETS).sort(), ["darwin-arm64", "linux-x64", "win32-x64"]);
});

test("resolveNativeBinary returns unsupported for unknown platform", () => {
  const native = resolveNativeBinary({ platform: "freebsd", arch: "x64" });
  assert.equal(native.supported, false);
  assert.equal(native.binaryPath, null);
});

test("resolveNativeBinary resolves installed platform package", () => {
  const native = resolveNativeBinary({
    platform: "linux",
    arch: "x64",
    requireResolve: (id) => {
      assert.equal(id, "rhx-linux-x64/package.json");
      return "/tmp/rhx-linux-x64/package.json";
    },
    exists: (binaryPath) => binaryPath === "/tmp/rhx-linux-x64/bin/rhx"
  });

  assert.equal(native.supported, true);
  assert.equal(native.packageName, "rhx-linux-x64");
  assert.equal(native.binaryPath, "/tmp/rhx-linux-x64/bin/rhx");
});

test("buildLaunchers includes uvx first and passes args", () => {
  const launchers = buildLaunchers("rhx", ["quote", "get", "AAPL"]);
  assert.equal(launchers[0].command, "uvx");
  assert.deepEqual(launchers[0].args, ["--from", "rhx", "rhx", "quote", "get", "AAPL"]);
  assert.deepEqual(launchers[1].args, ["run", "--spec", "rhx", "rhx", "quote", "get", "AAPL"]);
});

test("runWithLaunchers returns command status when launcher exists", () => {
  const calls = [];
  const spawn = (command, args) => {
    calls.push({ command, args });
    return { status: 0 };
  };

  const code = runWithLaunchers({ argv: ["--help"], spawn, env: { ...process.env } });
  assert.equal(code, 0);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].command, "uvx");
});

test("runWithLaunchers falls back when launcher is missing", () => {
  const calls = [];
  const spawn = (command) => {
    calls.push(command);
    if (command === "uvx") {
      return { error: { code: "ENOENT", message: "not found" } };
    }
    return { status: 0 };
  };

  const code = runWithLaunchers({ argv: ["--help"], spawn, env: { ...process.env } });
  assert.equal(code, 0);
  assert.deepEqual(calls.slice(0, 2), ["uvx", "pipx"]);
});

test("runWithLaunchers falls back when launcher exits non-zero", () => {
  const calls = [];
  const spawn = (command) => {
    calls.push(command);
    if (command === "uvx") {
      return { status: 1 };
    }
    return { status: 0 };
  };

  const code = runWithLaunchers({ argv: ["--help"], spawn, env: { ...process.env } });
  assert.equal(code, 0);
  assert.deepEqual(calls.slice(0, 2), ["uvx", "pipx"]);
});

test("runWithLaunchers returns helpful error when no launcher exists", () => {
  let stderr = "";
  const spawn = () => ({ error: { code: "ENOENT", message: "not found" } });
  const code = runWithLaunchers({
    argv: ["--help"],
    spawn,
    env: { ...process.env },
    stderr: { write: (line) => (stderr += line) }
  });

  assert.equal(code, 1);
  assert.match(stderr, /Unable to find a Python tool launcher/);
});

test("runWithLaunchers returns last non-zero status when all launchers fail", () => {
  let stderr = "";
  const spawn = (command) => {
    if (command === "python") {
      return { status: 3 };
    }
    return { status: 1 };
  };

  const code = runWithLaunchers({
    argv: ["--help"],
    spawn,
    env: { ...process.env },
    stderr: { write: (line) => (stderr += line) }
  });

  assert.equal(code, 3);
  assert.match(stderr, /All available launchers failed/);
});

test("runWithLaunchers honors RHX_PYPI_PACKAGE override", () => {
  const calls = [];
  const spawn = (command, args) => {
    calls.push({ command, args });
    return { status: 0 };
  };
  const env = { ...process.env, RHX_PYPI_PACKAGE: "robinhood-cli-rhx" };
  const code = runWithLaunchers({ argv: ["doctor"], spawn, env });

  assert.equal(code, 0);
  assert.deepEqual(calls[0].args.slice(0, 3), ["--from", "robinhood-cli-rhx", "rhx"]);
});

test("runRhx uses native binary when available", () => {
  const calls = [];
  const code = runRhx({
    argv: ["--help"],
    env: { ...process.env },
    resolveNative: () => ({
      supported: true,
      packageName: "rhx-linux-x64",
      binaryPath: "/tmp/rhx-linux-x64/bin/rhx"
    }),
    runLaunchers: () => {
      throw new Error("launcher fallback should not run");
    },
    spawn: (command, args) => {
      calls.push({ command, args });
      return { status: 0 };
    }
  });

  assert.equal(code, 0);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].command, "/tmp/rhx-linux-x64/bin/rhx");
});

test("runRhx errors when supported native package is missing", () => {
  let stderr = "";
  const code = runRhx({
    argv: ["--help"],
    env: { ...process.env },
    resolveNative: () => ({
      supported: true,
      packageName: "rhx-linux-x64",
      binaryPath: null
    }),
    runLaunchers: () => {
      throw new Error("launcher fallback should not run");
    },
    stderr: { write: (line) => (stderr += line) }
  });

  assert.equal(code, 1);
  assert.match(stderr, /native runtime package missing/);
});

test("runRhx can fallback to Python launchers when explicitly enabled", () => {
  const env = { ...process.env, RHX_ENABLE_PYTHON_FALLBACK: "1" };
  let stderr = "";
  let called = false;
  const code = runRhx({
    argv: ["--help"],
    env,
    resolveNative: () => ({
      supported: true,
      packageName: "rhx-linux-x64",
      binaryPath: null
    }),
    runLaunchers: ({ env: launcherEnv }) => {
      called = true;
      assert.equal(launcherEnv.RHX_ENABLE_PYTHON_FALLBACK, "1");
      return 0;
    },
    stderr: { write: (line) => (stderr += line) }
  });

  assert.equal(code, 0);
  assert.equal(called, true);
  assert.match(stderr, /native runtime package missing/);
});

test("runRhx falls back to Python launchers on unsupported platform", () => {
  let called = false;
  const code = runRhx({
    argv: ["--help"],
    env: { ...process.env },
    resolveNative: () => ({
      supported: false,
      packageName: null,
      binaryPath: null
    }),
    runLaunchers: () => {
      called = true;
      return 0;
    }
  });

  assert.equal(code, 0);
  assert.equal(called, true);
});
