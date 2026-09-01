#!/usr/bin/env node
/**
 * Regenerates the visual suite's FIXTURES (roadmap slice 047).
 *
 * Not the same thing as regenerating baselines, and needed far less often:
 *
 *   npm run visual:capture   re-records `visual/fixtures/` from a live demo
 *                            stack — do this when the API changes shape, or
 *                            when a view starts needing an endpoint the
 *                            recording does not contain
 *   npm run visual:update    re-takes the screenshots from the existing
 *                            fixtures — do this after an intended UI change
 *
 * A capture almost always implies an update afterwards, since new fixture
 * data changes what the views render.
 *
 * Runs on the host, not in the Playwright container: capture only makes HTTP
 * requests and reads JSON, so it has no font-rendering dependency, and it
 * needs to drive Docker Compose — which is easier from outside a container
 * than inside one.
 */

import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const e2eDir = path.resolve(__dirname, "..");

// Its own compose project name and data directory, so a capture never
// disturbs (or is disturbed by) a flow-suite run happening at the same time.
process.env.FLIGHTSITE_E2E_PROJECT = "visual-capture";

function node(script, args) {
  return spawnSync(process.execPath, [script, ...args], {
    cwd: e2eDir,
    stdio: "inherit",
    env: process.env,
  });
}

const up = node("scripts/stack.mjs", ["up"]);
if (up.status !== 0) {
  console.error("[visual-capture] stack up failed");
  process.exit(up.status ?? 1);
}

let exitCode = 1;
try {
  const cli = path.join(e2eDir, "node_modules", "@playwright", "test", "cli.js");
  const capture = spawnSync(
    process.execPath,
    [cli, "test", "-c", "playwright.capture.config.ts", ...process.argv.slice(2)],
    { cwd: e2eDir, stdio: "inherit", env: process.env },
  );
  exitCode = capture.status ?? 1;
} finally {
  // Down regardless of outcome, exactly as `run-suite.mjs` does — a failed
  // capture must not leave a stack and a temp data directory behind.
  const down = node("scripts/stack.mjs", ["down"]);
  if (down.status !== 0) {
    console.warn("[visual-capture] stack down reported a non-zero exit");
  }
}

if (exitCode === 0) {
  console.log(
    "\n[visual-capture] fixtures rewritten under e2e/visual/fixtures/.\n" +
      "[visual-capture] baselines are now stale — regenerate them with:\n" +
      "[visual-capture]   npm run visual:update\n" +
      "[visual-capture] and review both the fixture diff and the screenshot diff.",
  );
}
process.exit(exitCode);
