const assert = require("node:assert/strict");
const test = require("node:test");

const { buildLaunchers, runWithLaunchers } = require("../bin/rhx-lib.cjs");

test("buildLaunchers includes uvx first and passes args", () => {
  const launchers = buildLaunchers("rhx", ["quote", "get", "AAPL"]);
  assert.equal(launchers[0].command, "uvx");
  assert.deepEqual(launchers[0].args, ["--from", "rhx", "rhx", "quote", "get", "AAPL"]);
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
