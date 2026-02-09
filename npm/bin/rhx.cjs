#!/usr/bin/env node

const { runRhx } = require("./rhx-lib.cjs");

const exitCode = runRhx({ argv: process.argv.slice(2) });
process.exit(exitCode);
