/**
 * Post-processes a freshly captured HAR (roadmap slice 047).
 *
 * Runs as the capture config's `globalTeardown`, which is the only hook that
 * fires after Playwright has flushed the archive to disk — the HAR does not
 * exist yet while the capture test is still running, so this cannot be part
 * of the spec.
 *
 * Why it is needed: capture records against the demo stack on the compose
 * stack's published port, and the visual suite replays against `vite preview`
 * on :4173. Playwright's HAR router matches on the full request URL, origin
 * included, so without this rewrite not one entry would match at replay. The
 * failure that causes is quiet rather than loud — every request aborts, every
 * card renders "Failed to fetch", and the screenshots are perfectly
 * deterministic pictures of a broken app.
 *
 * Rewriting at capture time rather than at replay time keeps the committed
 * fixture honest about what it is for: read the HAR and the origins name the
 * server the suite actually talks to.
 */

import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  CAPTURE_BASE_URL,
  FIXTURE_DIR_NAME,
  HAR_FILE_NAME,
  VISUAL_BASE_URL,
} from "../support/fixtureContract";

interface HarEntry {
  request: { url: string };
}
interface HarFile {
  log: { entries: HarEntry[] };
}

export default function rewriteHar(): void {
  const harPath = path.join(
    path.dirname(fileURLToPath(import.meta.url)),
    "..",
    FIXTURE_DIR_NAME,
    HAR_FILE_NAME,
  );

  const har = JSON.parse(readFileSync(harPath, "utf8")) as HarFile;

  let rewritten = 0;
  for (const entry of har.log.entries) {
    if (entry.request.url.startsWith(CAPTURE_BASE_URL)) {
      entry.request.url = VISUAL_BASE_URL + entry.request.url.slice(CAPTURE_BASE_URL.length);
      rewritten += 1;
    }
  }

  if (rewritten === 0) {
    // Not fatal — a re-run over an already-rewritten archive lands here —
    // but worth saying out loud, because zero rewrites on a FRESH capture
    // would mean the origins no longer match what this module expects and
    // the fixture set is about to silently stop working.
    console.warn(
      `[visual-capture] no entry origins rewritten; expected URLs starting ${CAPTURE_BASE_URL}`,
    );
  } else {
    console.log(
      `[visual-capture] rewrote ${rewritten} HAR entry origins ` +
        `${CAPTURE_BASE_URL} -> ${VISUAL_BASE_URL}`,
    );
  }

  writeFileSync(harPath, `${JSON.stringify(har, null, 2)}\n`, "utf8");
}
