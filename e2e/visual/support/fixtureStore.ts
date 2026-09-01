/**
 * Loads the committed fixture set from disk (roadmap slice 047).
 *
 * Split out from both `fixtureContract.ts` and `replay.ts` on purpose.
 * `fixtureContract.ts` is imported by the capture spec, which runs when the
 * fixtures do not exist yet, so it must never touch the filesystem. `replay.ts`
 * needs the loaded values, and so does `stabilize.ts` (for the frozen clock) —
 * having both import this module instead of each other keeps them acyclic.
 */

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  FIXTURE_DIR_NAME,
  HAR_FILE_NAME,
  LIVE_SNAPSHOT_FILE_NAME,
  MANIFEST_FILE_NAME,
  type FixtureManifest,
} from "./fixtureContract";

const here = path.dirname(fileURLToPath(import.meta.url));

/** Absolute path of the committed fixture directory. */
export const FIXTURE_DIR = path.resolve(here, "..", FIXTURE_DIR_NAME);

/** Absolute path of the HTTP archive the REST replay reads. */
export const HAR_PATH = path.join(FIXTURE_DIR, HAR_FILE_NAME);

function readFixture(fileName: string): string {
  const filePath = path.join(FIXTURE_DIR, fileName);
  if (!existsSync(filePath)) {
    throw new Error(
      [
        `Visual fixture missing: ${filePath}`,
        "",
        "The visual suite replays a committed recording of a demo stack; without it",
        "there is nothing to screenshot. Regenerate the whole set with:",
        "",
        "  cd e2e && npm run visual:capture",
        "",
        "That brings up a seeded demo stack, records every response the five target",
        "views need, and tears the stack down again. See docs/DEVELOPMENT.md,",
        '"Visual regression suite".',
      ].join("\n"),
    );
  }
  return readFileSync(filePath, "utf8");
}

/** One frozen `snapshot` frame (`docs/API.md` §4.2), replayed to the client
 * in place of the live socket. Typed loosely on purpose: this file's job is
 * to hand the recording back byte-for-byte, not to re-validate a payload the
 * app's own parser already validates. */
export interface LiveSnapshotFrame {
  type: string;
  seq: number;
  ts: string;
  data: { aircraft: unknown[]; receiver: unknown };
}

export const FIXTURE_MANIFEST: FixtureManifest = JSON.parse(
  readFixture(MANIFEST_FILE_NAME),
) as FixtureManifest;

export const LIVE_SNAPSHOT: LiveSnapshotFrame = JSON.parse(
  readFixture(LIVE_SNAPSHOT_FILE_NAME),
) as LiveSnapshotFrame;
