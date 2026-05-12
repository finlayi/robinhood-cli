#!/usr/bin/env node

const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..", "..");
const dist = path.join(root, "dist");
const exe = process.platform === "win32" ? "rhx.exe" : "rhx";
const output = path.join(dist, exe);

fs.mkdirSync(dist, { recursive: true });
fs.rmSync(output, { recursive: true, force: true });

const result = spawnSync(
  "go",
  ["build", "-trimpath", "-ldflags", "-s -w", "-o", output, "./cmd/rhx"],
  {
    cwd: root,
    stdio: "inherit",
    env: process.env
  }
);

if (result.error) {
  process.stderr.write(`go build failed: ${result.error.message}\n`);
  process.exit(1);
}

if ((result.status ?? 1) === 0 && process.platform !== "win32") {
  fs.chmodSync(output, 0o755);
}

process.exit(result.status ?? 1);
