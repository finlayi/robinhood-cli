#!/usr/bin/env node

const { runWithLaunchers } = require("./rhx-lib.cjs");

const exitCode = runWithLaunchers({ argv: process.argv.slice(2) });
process.exit(exitCode);
