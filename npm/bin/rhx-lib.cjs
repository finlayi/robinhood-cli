const { spawnSync } = require("node:child_process");

function buildLaunchers(pypiPackage, argv) {
  return [
    { command: "uvx", args: ["--from", pypiPackage, "rhx", ...argv] },
    { command: "pipx", args: ["run", pypiPackage, "rhx", ...argv] },
    { command: "python3", args: ["-m", "pipx", "run", pypiPackage, "rhx", ...argv] },
    { command: "python", args: ["-m", "pipx", "run", pypiPackage, "rhx", ...argv] }
  ];
}

function runWithLaunchers({
  argv,
  env = process.env,
  spawn = spawnSync,
  stderr = process.stderr
}) {
  const pypiPackage = env.RHX_PYPI_PACKAGE || "rhx";
  const launchers = buildLaunchers(pypiPackage, argv);

  for (const launcher of launchers) {
    const result = spawn(launcher.command, launcher.args, { stdio: "inherit", env });

    if (result.error && result.error.code === "ENOENT") {
      continue;
    }
    if (result.error) {
      stderr.write(`rhx launcher failed via ${launcher.command}: ${result.error.message}\n`);
      return 1;
    }
    if (typeof result.status === "number") {
      return result.status;
    }
    if (result.signal) {
      stderr.write(`rhx launcher terminated by signal ${result.signal}\n`);
      return 1;
    }
    return 1;
  }

  stderr.write("Unable to find a Python tool launcher (uvx/pipx).\n");
  stderr.write("Install uv or pipx, then retry `npx rhx --help`.\n");
  return 1;
}

module.exports = {
  buildLaunchers,
  runWithLaunchers
};
