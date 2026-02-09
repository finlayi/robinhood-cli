#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const MAIN_PACKAGE_PATH = path.join(ROOT, "package.json");
const CHECK_ONLY = process.argv.includes("--check");

const PLATFORM_PACKAGES = [
  {
    name: "rhx-darwin-arm64",
    path: path.join(ROOT, "platform", "rhx-darwin-arm64", "package.json")
  },
  {
    name: "rhx-linux-x64",
    path: path.join(ROOT, "platform", "rhx-linux-x64", "package.json")
  },
  {
    name: "rhx-win32-x64",
    path: path.join(ROOT, "platform", "rhx-win32-x64", "package.json")
  }
];

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function writeJson(filePath, content) {
  fs.writeFileSync(filePath, `${JSON.stringify(content, null, 2)}\n`);
}

function main() {
  const mismatches = [];
  const mainPackage = readJson(MAIN_PACKAGE_PATH);
  const version = mainPackage.version;
  let touched = false;

  mainPackage.optionalDependencies = mainPackage.optionalDependencies || {};

  for (const platformPackage of PLATFORM_PACKAGES) {
    const packageJson = readJson(platformPackage.path);

    if (packageJson.name !== platformPackage.name) {
      mismatches.push(`${platformPackage.path}: expected name ${platformPackage.name}, got ${packageJson.name}`);
    }

    if (packageJson.version !== version) {
      if (CHECK_ONLY) {
        mismatches.push(`${platformPackage.path}: expected version ${version}, got ${packageJson.version}`);
      } else {
        packageJson.version = version;
        touched = true;
      }
    }

    if (mainPackage.optionalDependencies[platformPackage.name] !== version) {
      if (CHECK_ONLY) {
        mismatches.push(
          `${MAIN_PACKAGE_PATH}: optionalDependencies.${platformPackage.name} should be ${version}`
        );
      } else {
        mainPackage.optionalDependencies[platformPackage.name] = version;
        touched = true;
      }
    }

    if (!CHECK_ONLY) {
      writeJson(platformPackage.path, packageJson);
    }
  }

  if (CHECK_ONLY) {
    if (mismatches.length > 0) {
      process.stderr.write(`${mismatches.join("\n")}\n`);
      process.exit(1);
    }
    process.stdout.write("Platform package versions are in sync.\n");
    return;
  }

  if (touched) {
    writeJson(MAIN_PACKAGE_PATH, mainPackage);
    process.stdout.write(`Updated platform package versions to ${version}.\n`);
  } else {
    process.stdout.write("Versions already in sync.\n");
  }
}

main();
