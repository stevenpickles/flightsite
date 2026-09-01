#!/usr/bin/env node
/**
 * Runs the visual regression suite (roadmap slice 047).
 *
 * This script assumes it is ALREADY inside the pinned Playwright container —
 * `scripts/visual-docker.mjs` is what puts it there, and the CI job runs it
 * under the same image via `container:`. Running it directly is supported
 * only on a Linux host that is itself the pinned image; the suite's
 * `globalSetup` refuses anything else, because baselines are a function of
 * the container's font rendering.
 *
 * Unlike the flow suite there is no Docker Compose stack here and no
 * backend: every API response is replayed from `visual/fixtures/api.har` and
 * the live socket is served one frozen snapshot, so all this needs to serve
 * is the built SPA. It builds `frontend/dist` and lets Playwright's
 * `webServer` run `vite preview` over it (see `playwright.visual.config.ts`).
 *
 * Usage: node scripts/visual.mjs [extra playwright args...]
 *   e.g. node scripts/visual.mjs --update-snapshots
 */

import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const e2eDir = path.resolve(__dirname, "..");
const repoRoot = path.resolve(e2eDir, "..");
const frontendDir = path.join(repoRoot, "frontend");

const extraArgs = process.argv.slice(2);

/**
 * The container tag and the Playwright dependency must agree.
 *
 * `scripts/visual-docker.mjs` derives its image tag from
 * `e2e/package.json`, but `.github/workflows/visual.yml` cannot — a
 * `container.image` has to be a literal. So the two can drift, and the
 * symptom of drift is the nastiest kind: both still run, both still produce
 * screenshots, and the screenshots differ because the browser builds differ.
 * Baselines regenerated locally would then never match CI, with nothing in
 * either log saying why.
 *
 * Checking here — the one entry point both paths go through — turns that
 * into a one-line failure naming the file to edit.
 */
function assertWorkflowImageMatches() {
  const pkg = JSON.parse(
    readFileSync(path.join(e2eDir, "package.json"), "utf8"),
  );
  const expected = pkg.devDependencies?.["@playwright/test"];
  const workflowPath = path.join(
    repoRoot,
    ".github",
    "workflows",
    "visual.yml",
  );
  if (!expected || !existsSync(workflowPath)) {
    return;
  }
  const workflow = readFileSync(workflowPath, "utf8");
  const match = workflow.match(
    /image:\s*mcr\.microsoft\.com\/playwright:v(\d+\.\d+\.\d+)-/,
  );
  if (!match) {
    return;
  }
  if (match[1] !== expected) {
    console.error(
      [
        "[visual] Playwright version drift — baselines would not be reproducible.",
        `  e2e/package.json @playwright/test : ${expected}`,
        `  .github/workflows/visual.yml image: ${match[1]}`,
        "",
        "Update the workflow's container image tag to match the dependency",
        "(scripts/visual-docker.mjs derives its tag from package.json automatically),",
        "then regenerate the baselines with `npm run visual:update`.",
      ].join("\n"),
    );
    process.exit(1);
  }
}

assertWorkflowImageMatches();

function run(command, args, cwd) {
  console.log(`[visual] + ${command} ${args.join(" ")}  (in ${cwd})`);
  const result = spawnSync(command, args, {
    cwd,
    stdio: "inherit",
    env: process.env,
    // npm is a shell script on Linux; the container always has a shell.
    shell: process.platform === "win32",
  });
  if (result.status !== 0) {
    console.error(`[visual] ${command} ${args.join(" ")} failed`);
    process.exit(result.status ?? 1);
  }
}

// The `e2e` and `frontend` workspaces are installed separately: the bind
// mount from the host may carry node_modules built for a different OS
// (native esbuild/rollup binaries are platform-specific), so
// `visual-docker.mjs` shadows both directories with container-local
// volumes. On the very first run those volumes are empty and both installs
// happen here; afterwards they are warm and this is a no-op check.
if (!existsSync(path.join(e2eDir, "node_modules", "@playwright", "test"))) {
  run("npm", ["ci"], e2eDir);
}
if (!existsSync(path.join(frontendDir, "node_modules", "vite"))) {
  run("npm", ["ci"], frontendDir);
}

// A fresh build every run, deliberately. The whole point of the suite is to
// photograph the current frontend, and reusing a stale `dist` is the one
// mistake that would make a green run meaningless.
run("npm", ["run", "build"], frontendDir);

const cli = path.join(e2eDir, "node_modules", "@playwright", "test", "cli.js");
const test = spawnSync(
  process.execPath,
  [cli, "test", "-c", "playwright.visual.config.ts", ...extraArgs],
  { cwd: e2eDir, stdio: "inherit", env: process.env },
);

process.exit(test.status ?? 1);
