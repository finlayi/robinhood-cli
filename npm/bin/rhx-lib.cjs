const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const NATIVE_TARGETS = {
  "darwin-arm64": {
    packageName: "rhx-darwin-arm64",
    binaryRelPath: "bin/rhx"
  },
  "linux-x64": {
    packageName: "rhx-linux-x64",
    binaryRelPath: "bin/rhx"
  },
  "win32-x64": {
    packageName: "rhx-win32-x64",
    binaryRelPath: "bin/rhx.exe"
  }
};

function targetKey(platform, arch) {
  return `${platform}-${arch}`;
}

function resolveNativeBinary({
  platform = process.platform,
  arch = process.arch,
  requireResolve = require.resolve,
  exists = fs.existsSync,
  baseDir = __dirname
} = {}) {
  const key = targetKey(platform, arch);
  const spec = NATIVE_TARGETS[key];

  if (!spec) {
    return {
      supported: false,
      key,
      packageName: null,
      binaryPath: null
    };
  }

  const localNodeModulesBinary = path.resolve(
    baseDir,
    "..",
    "node_modules",
    spec.packageName,
    spec.binaryRelPath
  );
  if (exists(localNodeModulesBinary)) {
    return {
      supported: true,
      key,
      packageName: spec.packageName,
      binaryPath: localNodeModulesBinary
    };
  }

  try {
    const binaryPath = requireResolve(`${spec.packageName}/${spec.binaryRelPath}`);

    return {
      supported: true,
      key,
      packageName: spec.packageName,
      binaryPath
    };
  } catch (error) {
    if (error && error.code === "MODULE_NOT_FOUND") {
      return {
        supported: true,
        key,
        packageName: spec.packageName,
        binaryPath: null
      };
    }
    throw error;
  }
}

function buildLaunchers(pypiPackage, argv) {
  return [
    { command: "uvx", args: ["--from", pypiPackage, "rhx", ...argv] },
    { command: "pipx", args: ["run", "--spec", pypiPackage, "rhx", ...argv] },
    { command: "python3", args: ["-m", "pipx", "run", "--spec", pypiPackage, "rhx", ...argv] },
    { command: "python", args: ["-m", "pipx", "run", "--spec", pypiPackage, "rhx", ...argv] }
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
  let sawRunnableLauncher = false;
  let lastExitCode = 1;

  for (const launcher of launchers) {
    const result = spawn(launcher.command, launcher.args, { stdio: "inherit", env });

    if (result.error && result.error.code === "ENOENT") {
      continue;
    }
    if (result.error) {
      stderr.write(`rhx launcher failed via ${launcher.command}: ${result.error.message}\n`);
      sawRunnableLauncher = true;
      lastExitCode = 1;
      continue;
    }
    if (typeof result.status === "number") {
      if (result.status === 0) {
        return 0;
      }
      sawRunnableLauncher = true;
      lastExitCode = result.status;
      continue;
    }
    if (result.signal) {
      stderr.write(`rhx launcher terminated by signal ${result.signal}\n`);
      return 1;
    }
    sawRunnableLauncher = true;
    lastExitCode = 1;
  }

  if (sawRunnableLauncher) {
    stderr.write("All available launchers failed.\n");
    stderr.write("Install or repair uv/pipx, then retry `npx rhx --help`.\n");
    return lastExitCode;
  }

  stderr.write("Unable to find a Python tool launcher (uvx/pipx).\n");
  stderr.write("Install uv or pipx, then retry `npx rhx --help`.\n");
  return 1;
}

function runRhx({
  argv,
  env = process.env,
  spawn = spawnSync,
  stderr = process.stderr,
  platform = process.platform,
  arch = process.arch,
  resolveNative = resolveNativeBinary,
  runLaunchers = runWithLaunchers
}) {
  const native = resolveNative({ platform, arch });

  if (native.supported) {
    if (!native.binaryPath) {
      stderr.write(`rhx native runtime package missing: ${native.packageName}\n`);
      stderr.write("Reinstall with optional dependencies enabled, then retry `npx rhx --help`.\n");
      stderr.write("If you need a Python fallback, set RHX_ENABLE_PYTHON_FALLBACK=1.\n");
      if (env.RHX_ENABLE_PYTHON_FALLBACK !== "1") {
        return 1;
      }
    } else {
      const result = spawn(native.binaryPath, argv, { stdio: "inherit", env });
      if (result.error) {
        stderr.write(`rhx native launcher failed: ${result.error.message}\n`);
        return 1;
      }
      if (typeof result.status === "number") {
        return result.status;
      }
      if (result.signal) {
        stderr.write(`rhx native launcher terminated by signal ${result.signal}\n`);
        return 1;
      }
      return 1;
    }
  }

  return runLaunchers({ argv, env, spawn, stderr });
}

module.exports = {
  NATIVE_TARGETS,
  resolveNativeBinary,
  runRhx,
  buildLaunchers,
  runWithLaunchers
};
