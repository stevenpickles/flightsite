#!/usr/bin/env node
/**
 * Runs the visual regression suite inside the pinned Playwright container
 * (roadmap slice 047) — the supported way to run it, and the ONLY supported
 * way to regenerate baselines.
 *
 * Why a container at all: a screenshot baseline is a function of the font
 * stack and the font rasterizer as much as of the CSS. The same page
 * rendered on Windows, macOS and Linux differs on almost every text pixel,
 * and even two Linux machines differ if their FreeType or fontconfig
 * versions do. `docs/TEST_STRATEGY.md` §5 resolves this by pinning font
 * rendering "by running in the CI container image"; this script is that
 * pin, and `.github/workflows/visual.yml` runs the same image so a local
 * regeneration and a CI comparison are byte-comparable.
 *
 * The image tag is derived from `@playwright/test` in `e2e/package.json`
 * rather than written out here, so bumping Playwright cannot silently leave
 * the container on an older browser build than the one the baselines were
 * taken with.
 *
 * Usage:
 *   node scripts/visual-docker.mjs                     # compare
 *   node scripts/visual-docker.mjs --update-snapshots  # regenerate
 */

import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const e2eDir = path.resolve(__dirname, "..");
const repoRoot = path.resolve(e2eDir, "..");

const pkg = JSON.parse(readFileSync(path.join(e2eDir, "package.json"), "utf8"));
const playwrightVersion = pkg.devDependencies?.["@playwright/test"];
if (!playwrightVersion || !/^\d+\.\d+\.\d+$/.test(playwrightVersion)) {
  console.error(
    `[visual] @playwright/test must be pinned to an exact version in e2e/package.json ` +
      `to derive the container tag (found: ${playwrightVersion ?? "nothing"}).`,
  );
  process.exit(1);
}
const image = `mcr.microsoft.com/playwright:v${playwrightVersion}-noble`;

// Container-local node_modules for both workspaces.
//
// The repository is bind-mounted from the host, and on a Windows or macOS
// host `frontend/node_modules` holds native binaries (esbuild, rollup) built
// for that OS, which the Linux container cannot execute. Named volumes
// mounted over those two paths give the container its own copies —
// invisible to the host checkout, and persistent across runs so the install
// only pays for itself once.
const volumes = [
  "flightsite-visual-frontend-node-modules:/work/frontend/node_modules",
  "flightsite-visual-e2e-node-modules:/work/e2e/node_modules",
];

const args = [
  "run",
  "--rm",
  // Chromium's default 64 MB /dev/shm is not enough for a full-page
  // screenshot of the Receiver page; the Playwright docs' own recommendation.
  "--ipc=host",
  "-v",
  `${repoRoot}:/work`,
  ...volumes.flatMap((volume) => ["-v", volume]),
  "-w",
  "/work/e2e",
  // The handshake `assertPinnedRenderer()` checks. Set here and in the CI
  // workflow, and nowhere else, so running the suite outside a container
  // stops with an actionable message instead of writing incomparable
  // baselines.
  "-e",
  "FLIGHTSITE_VISUAL_CONTAINER=1",
  ...(process.env.CI ? ["-e", "CI"] : []),
  image,
  "node",
  "scripts/visual.mjs",
  ...process.argv.slice(2),
];

console.log(`[visual] docker ${args.join(" ")}`);
const result = spawnSync("docker", args, { stdio: "inherit" });

if (result.error) {
  console.error(
    `[visual] could not run docker: ${result.error.message}\n` +
      "The visual suite needs a working Docker daemon — it is what pins font rendering.",
  );
  process.exit(1);
}
process.exit(result.status ?? 1);
