#!/usr/bin/env node
/**
 * Boots or tears down the FlightSite Docker Compose stack for E2E runs.
 *
 * Design (see docs/DEVELOPMENT.md "Running E2E locally" and
 * .github/workflows/e2e.yml): the stack lifecycle lives in a plain Node
 * script rather than a Playwright globalSetup, because each browser project
 * needs its OWN fresh stack — the first-run flow (roadmap slice 020's flow
 * "a") only means anything against a data directory that has never seen a
 * completed setup. Playwright's globalSetup runs exactly once per test run,
 * shared across every `--project`, which would let only the first browser to
 * execute see `first_run: true`. Driving the lifecycle per browser instead
 * (see scripts/run-suite.mjs and the CI workflow) is the simpler, reliable
 * choice: one compose cycle per browser, each with its own data directory,
 * each running the ordered spec sequence (first-run -> decoder -> live map
 * -> selection/detail) inside that one cycle.
 *
 * `up` creates a fresh host data directory, brings the stack up in demo mode
 * and waits for both containers to report healthy (compose's own `--wait`,
 * exactly like `.github/workflows/docker.yml`'s smoke test). `down` tears the
 * stack back down and removes the data directory. The compose project name
 * is derived from the caller (env FLIGHTSITE_E2E_PROJECT, e.g. a browser
 * name) so parallel CI jobs on separate runners never collide, and so a
 * developer can run `up`/`down` for one browser without disturbing another.
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, existsSync, mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..", "..");

const label = process.env.FLIGHTSITE_E2E_PROJECT ?? "default";
const composeProjectName = `flightsite-e2e-${label}`;
// Where this run's data-dir path (and compose project name) are recorded so
// `down` can find them again without the caller having to pass them back in.
const stateDir = path.join(tmpdir(), "flightsite-e2e-state");
const stateFile = path.join(stateDir, `${composeProjectName}.json`);

function run(cmd, args, options = {}) {
  console.log(`+ ${cmd} ${args.join(" ")}`);
  execFileSync(cmd, args, { stdio: "inherit", cwd: repoRoot, ...options });
}

function up() {
  const hostDataDir = mkdtempSync(path.join(tmpdir(), "flightsite-e2e-data-"));
  console.log(`[stack] data dir: ${hostDataDir}`);
  console.log(`[stack] compose project: ${composeProjectName}`);

  // Linux CI runners: the backend container runs as uid 1000, so a
  // freshly-created temp dir must be handed to that uid or the backend
  // cannot write config/database and never reports healthy (mirrors
  // .github/workflows/docker.yml's compose smoke test). Docker Desktop's
  // bind-mount translation on macOS/Windows does not need this and `sudo`
  // is not generally available there, so it is skipped outside Linux.
  if (process.platform === "linux") {
    try {
      run("sudo", ["chown", "1000:1000", hostDataDir]);
    } catch (err) {
      console.warn(`[stack] chown of data dir failed (continuing): ${err.message}`);
    }
  }

  mkdirSync(stateDir, { recursive: true });
  writeFileSync(stateFile, JSON.stringify({ hostDataDir, composeProjectName }, null, 2));

  const env = {
    ...process.env,
    FLIGHTSITE_DEMO: "1",
    FLIGHTSITE_HOST_DATA_DIR: hostDataDir,
  };

  try {
    run(
      "docker",
      [
        "compose",
        "-p",
        composeProjectName,
        "up",
        "-d",
        "--wait",
        "--wait-timeout",
        "180",
      ],
      { env },
    );
  } catch (err) {
    console.error("[stack] compose up --wait failed; dumping logs");
    try {
      run("docker", ["compose", "-p", composeProjectName, "logs"], { env });
    } catch {
      // best-effort diagnostics only
    }
    throw err;
  }

  console.log("[stack] up and healthy");
}

function down() {
  if (!existsSync(stateFile)) {
    console.warn(`[stack] no recorded state for project ${composeProjectName}; nothing to tear down`);
    return;
  }
  const { hostDataDir } = JSON.parse(readFileSync(stateFile, "utf8"));

  const env = {
    ...process.env,
    FLIGHTSITE_DEMO: "1",
    FLIGHTSITE_HOST_DATA_DIR: hostDataDir,
  };

  try {
    run("docker", ["compose", "-p", composeProjectName, "down", "-v"], { env });
  } finally {
    try {
      if (process.platform === "linux") {
        run("sudo", ["rm", "-rf", hostDataDir]);
      } else {
        rmSync(hostDataDir, { recursive: true, force: true });
      }
    } catch (err) {
      console.warn(`[stack] cleanup of ${hostDataDir} failed: ${err.message}`);
    }
    rmSync(stateFile, { force: true });
  }
  console.log("[stack] down");
}

const command = process.argv[2];
if (command === "up") {
  up();
} else if (command === "down") {
  down();
} else {
  console.error("usage: stack.mjs <up|down>");
  process.exit(1);
}
