#!/usr/bin/env node
/**
 * Full local/CI lifecycle for one browser project: fresh stack up, run the
 * ordered E2E spec sequence against it, stack down — regardless of test
 * outcome. See scripts/stack.mjs for why the stack is per-browser rather
 * than shared across the whole Playwright run.
 *
 * Usage: node scripts/run-suite.mjs <chromium|firefox|webkit> [extra playwright args...]
 */

import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const e2eDir = path.resolve(__dirname, "..");

const project = process.argv[2];
const extraArgs = process.argv.slice(3);

if (!project) {
  console.error("usage: run-suite.mjs <chromium|firefox|webkit> [extra playwright args...]");
  process.exit(1);
}

process.env.FLIGHTSITE_E2E_PROJECT = project;

function node(script, args) {
  return spawnSync(process.execPath, [script, ...args], {
    cwd: e2eDir,
    stdio: "inherit",
    env: process.env,
  });
}

function playwright(args) {
  // Invokes the installed @playwright/test CLI's JS entrypoint directly
  // with `process.execPath` rather than shelling out to `npx`/`npx.cmd`:
  // Node's `spawnSync` cannot execute a Windows `.cmd` shim without
  // `shell: true` (EINVAL), and `shell: true` in turn needs careful
  // quoting for the `--project=` argument. Running the CLI's own script
  // through `node` sidesteps both and behaves identically on every OS.
  const cli = path.join(e2eDir, "node_modules", "@playwright", "test", "cli.js");
  return spawnSync(process.execPath, [cli, "test", `--project=${project}`, ...args], {
    cwd: e2eDir,
    stdio: "inherit",
    env: process.env,
  });
}

const up = node("scripts/stack.mjs", ["up"]);
if (up.status !== 0) {
  console.error(`[run-suite] stack up failed for project ${project}`);
  process.exit(up.status ?? 1);
}

let exitCode = 1;
try {
  const test = playwright(extraArgs);
  exitCode = test.status ?? 1;
} finally {
  const down = node("scripts/stack.mjs", ["down"]);
  if (down.status !== 0) {
    console.warn(`[run-suite] stack down reported a non-zero exit for project ${project}`);
  }
}

process.exit(exitCode);
