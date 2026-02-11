#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");

const TARGETS = {
  "darwin-arm64": {
    packageDir: path.resolve(__dirname, "..", "platform", "rhx-darwin-arm64"),
    outputName: "rhx",
    defaultSource: path.resolve(process.cwd(), "dist", "rhx")
  },
  "linux-x64": {
    packageDir: path.resolve(__dirname, "..", "platform", "rhx-linux-x64"),
    outputName: "rhx",
    defaultSource: path.resolve(process.cwd(), "dist", "rhx")
  },
  "win32-x64": {
    packageDir: path.resolve(__dirname, "..", "platform", "rhx-win32-x64"),
    outputName: "rhx.exe",
    defaultSource: path.resolve(process.cwd(), "dist", "rhx")
  }
};

function parseArgs(argv) {
  const parsed = { target: null, source: null };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--target") {
      parsed.target = argv[i + 1] || null;
      i += 1;
      continue;
    }
    if (argv[i] === "--source") {
      parsed.source = argv[i + 1] || null;
      i += 1;
    }
  }
  return parsed;
}

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

function clearDirectory(directoryPath) {
  fs.mkdirSync(directoryPath, { recursive: true });
  for (const entry of fs.readdirSync(directoryPath)) {
    fs.rmSync(path.join(directoryPath, entry), { recursive: true, force: true });
  }
}

function copyDirectoryContents(sourceDir, destinationDir) {
  for (const entry of fs.readdirSync(sourceDir)) {
    fs.cpSync(path.join(sourceDir, entry), path.join(destinationDir, entry), {
      recursive: true,
      force: true,
      verbatimSymlinks: true
    });
  }
}

const { target, source } = parseArgs(process.argv.slice(2));

if (!target) {
  fail("Missing required flag: --target <darwin-arm64|linux-x64|win32-x64>");
}

const spec = TARGETS[target];
if (!spec) {
  fail(`Unsupported target: ${target}`);
}

const sourcePath = source ? path.resolve(source) : spec.defaultSource;
if (!fs.existsSync(sourcePath)) {
  fail(`Built runtime not found: ${sourcePath}`);
}

const binDir = path.join(spec.packageDir, "bin");
const destination = path.join(binDir, spec.outputName);
clearDirectory(binDir);

const sourceStat = fs.statSync(sourcePath);
if (sourceStat.isFile()) {
  fs.copyFileSync(sourcePath, destination);
} else if (sourceStat.isDirectory()) {
  const sourceExecutable = path.join(sourcePath, spec.outputName);
  if (!fs.existsSync(sourceExecutable)) {
    fail(`Built runtime missing executable: ${sourceExecutable}`);
  }
  copyDirectoryContents(sourcePath, binDir);
} else {
  fail(`Unsupported source type: ${sourcePath}`);
}

if (target !== "win32-x64") {
  fs.chmodSync(destination, 0o755);
}

process.stdout.write(`Staged ${sourcePath} -> ${destination}\n`);
