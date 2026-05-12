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

function runRhx({
  argv,
  env = process.env,
  spawn = spawnSync,
  stderr = process.stderr,
  platform = process.platform,
  arch = process.arch,
  resolveNative = resolveNativeBinary
}) {
  const native = resolveNative({ platform, arch });

  if (!native.supported) {
    stderr.write(`rhx native runtime is not available for ${native.key}.\n`);
    return 1;
  }

  if (!native.binaryPath) {
    stderr.write(`rhx native runtime package missing: ${native.packageName}\n`);
    stderr.write("Reinstall with optional dependencies enabled, then retry `npx rhx --help`.\n");
    return 1;
  }

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

module.exports = {
  NATIVE_TARGETS,
  resolveNativeBinary,
  runRhx
};
