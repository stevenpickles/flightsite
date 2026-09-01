/**
 * Flow — backup/restore smoke path (roadmap slice 046,
 * `docs/TEST_STRATEGY.md` §4; `docs/BACKUP.md`).
 *
 * Why this spec drives a CLI instead of a browser
 * ----------------------------------------------
 * Because there is no other way to drive it, by design. Roadmap slice 043
 * ships backup and restore as an in-container command and lists *"UI-driven
 * backup"* under `out_of_scope`; the frontend has no create, download, upload
 * or restore control anywhere, and `/api/internal` exposes no backup route.
 * The only mention of backup in the UI is the Danger Zone quoting the very
 * command below. So the backup/restore path a user actually has is
 * `flightsite-backup`, and that is the path this covers — through the same
 * `docker compose` stack every other spec in this suite is talking to, which
 * is what makes it end-to-end rather than a unit test in disguise.
 *
 * It stays in the Playwright suite rather than moving to the backend's pytest
 * suite because what it exercises is the composed, running installation: a
 * backup taken from a live container whose database is being written to by
 * ongoing demo ingestion. `backend/tests/` covers manifest validation,
 * refusal paths and cross-version restore against fixtures; this covers "the
 * thing you would actually type, against the thing you are actually
 * running".
 *
 * Leaving the stack clean
 * -----------------------
 * Restore is destructive: it replaces the database and `config.yaml` in the
 * data directory, and FlightSite has no lock file, so restoring over the live
 * data directory would leave the running backend writing into an unlinked
 * file — and would destroy the completed setup and accumulated history that
 * the rest of this ordered suite depends on. This flow therefore never
 * touches `/opt/flightsite/data`:
 *
 * - the backup is written to a scratch directory with `--out`, so the data
 *   directory's own `backups/` stays empty;
 * - `verify` is documented as read-only;
 * - the refusal path writes nothing by definition;
 * - the one *successful* restore is aimed at a throwaway `--data-dir`, which
 *   exercises the whole destructive path against a directory the live
 *   process does not own.
 *
 * Everything is removed afterwards, and the final assertion is that the stack
 * the next spec would use is still serving.
 */

import { execFileSync } from "node:child_process";

import { expect, test } from "./support/fixtures";

/**
 * The backend container's name.
 *
 * `compose.yaml` pins `container_name: flightsite-backend`, so it is the same
 * whichever compose project `scripts/stack.mjs` brought the stack up under —
 * and there can only ever be one stack running at a time for that same
 * reason. That makes a plain `docker exec` both correct and independent of
 * how the suite was invoked.
 */
const CONTAINER = "flightsite-backend";

/** Scratch paths inside the container, deliberately outside the data dir. */
const BACKUP_DIR = "/tmp/e2e-backup";
const RESTORE_DIR = "/tmp/e2e-restore";

interface CommandResult {
  status: number;
  stdout: string;
  stderr: string;
}

/** Runs a command inside the backend container, capturing output and exit
 * code rather than throwing — the exit code is frequently the assertion. */
function exec(args: string[]): CommandResult {
  try {
    const stdout = execFileSync("docker", ["exec", CONTAINER, ...args], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });
    return { status: 0, stdout, stderr: "" };
  } catch (error) {
    const failure = error as {
      status?: number;
      stdout?: string;
      stderr?: string;
    };
    return {
      status: failure.status ?? 1,
      stdout: failure.stdout ?? "",
      stderr: failure.stderr ?? "",
    };
  }
}

/** `create` prints `wrote <path> (<n> bytes)` as its first line. */
function archivePathFrom(stdout: string): string {
  const match = /^wrote (\S+) \(\d+ bytes\)/m.exec(stdout);
  if (!match?.[1]) {
    throw new Error(`could not find the archive path in:\n${stdout}`);
  }
  return match[1];
}

test.describe("backup and restore", () => {
  test.afterAll(() => {
    // Best effort: the scratch directories must not survive the spec, but a
    // cleanup failure should not be reported as a test failure.
    exec(["rm", "-rf", BACKUP_DIR, RESTORE_DIR]);
  });

  test("a live install backs up, verifies, refuses an unconfirmed restore, and restores elsewhere", async ({
    request,
  }) => {
    // ---------------------------------------------------------------
    // create — while the stack is up and ingesting
    // ---------------------------------------------------------------
    // The point of the `--out` scratch directory: the data directory's own
    // `backups/` is left exactly as it was.
    const created = exec([
      "flightsite-backup",
      "create",
      "--out",
      BACKUP_DIR,
    ]);
    expect(
      created.status,
      `create failed:\n${created.stdout}\n${created.stderr}`,
    ).toBe(0);

    // A backup taken during active ingestion is slice 043's headline
    // guarantee; the manifest is what makes the archive self-describing.
    expect(created.stdout).toContain("flightsite version:");
    expect(created.stdout).toContain("schema revision:");
    expect(created.stdout).toContain("flightsite.sqlite3");
    // Secrets are opt-in and were not asked for.
    expect(created.stdout).toContain("includes secrets:   no");

    const archive = archivePathFrom(created.stdout);
    expect(archive).toContain(BACKUP_DIR);

    // ---------------------------------------------------------------
    // verify — read-only, and the gate a restore would apply
    // ---------------------------------------------------------------
    const verified = exec(["flightsite-backup", "verify", archive]);
    expect(
      verified.status,
      `verify failed:\n${verified.stdout}\n${verified.stderr}`,
    ).toBe(0);
    expect(verified.stdout).toContain("RESULT: restorable");
    // Every archived file's checksum was actually checked, not just listed.
    expect(verified.stdout).toContain("checksums:");
    expect(verified.stdout).not.toContain("FAILED");

    // ---------------------------------------------------------------
    // restore without --confirm — refused, and nothing is touched
    // ---------------------------------------------------------------
    // Exit 2 is "the invocation was wrong", which is what an unconfirmed
    // destructive command is. The refusal happens before the archive is
    // read, so this is the safest possible assertion to make against a live
    // data directory.
    const unconfirmed = exec(["flightsite-backup", "restore", archive]);
    expect(
      unconfirmed.status,
      "an unconfirmed restore was not refused",
    ).toBe(2);
    expect(unconfirmed.stderr).toContain("Stop FlightSite before restoring");

    // ---------------------------------------------------------------
    // restore --confirm, into a throwaway data directory
    // ---------------------------------------------------------------
    // The full destructive path, aimed somewhere the running backend does
    // not own — so the round trip is genuinely exercised and the live
    // install is still untouched.
    const restored = exec([
      "flightsite-backup",
      "restore",
      archive,
      "--data-dir",
      RESTORE_DIR,
      "--confirm",
    ]);
    expect(
      restored.status,
      `restore failed:\n${restored.stdout}\n${restored.stderr}`,
    ).toBe(0);
    expect(restored.stdout).toContain(`into:              ${RESTORE_DIR}`);
    expect(restored.stdout).toContain("flightsite.sqlite3");

    // The database really landed, rather than the command merely reporting
    // that it had.
    const listed = exec(["ls", `${RESTORE_DIR}/flightsite.sqlite3`]);
    expect(listed.status, "the restored database is not there").toBe(0);

    // ---------------------------------------------------------------
    // the live install is still the live install
    // ---------------------------------------------------------------
    // Nothing above should have reached the data directory: no archive in
    // its `backups/`, and the backend still serving the setup and history
    // the remaining specs depend on.
    const backupsDir = exec([
      "python",
      "-c",
      "import os; d='/opt/flightsite/data/backups'; print('\\n'.join(sorted(os.listdir(d))) if os.path.isdir(d) else '')",
    ]);
    expect(
      backupsDir.stdout.trim(),
      "the smoke path left an archive in the live data directory",
    ).toBe("");

    const health = await request.get("/api/v1/health");
    expect(health.ok(), "the stack stopped being healthy").toBeTruthy();
  });

  test("a damaged archive is refused rather than restored", async () => {
    // The other half of slice 043's contract: a corrupted archive must fail
    // closed. Truncating a real archive is the cheapest honest corruption —
    // the manifest's checksums no longer describe the bytes present.
    const created = exec([
      "flightsite-backup",
      "create",
      "--out",
      BACKUP_DIR,
    ]);
    expect(created.status).toBe(0);
    const archive = archivePathFrom(created.stdout);
    const damaged = `${archive}.damaged.tar.gz`;

    // Copy, then truncate to a fraction of its size. Done through Python
    // rather than `cp`/`truncate` because the runtime image is
    // `python:3.12-slim` — the interpreter is the one tool guaranteed to be
    // in it.
    const corrupt = exec([
      "python",
      "-c",
      "import shutil,sys; shutil.copyfile(sys.argv[1], sys.argv[2]); open(sys.argv[2], 'r+b').truncate(512)",
      archive,
      damaged,
    ]);
    expect(
      corrupt.status,
      `could not produce a damaged archive: ${corrupt.stderr}`,
    ).toBe(0);

    const verified = exec(["flightsite-backup", "verify", damaged]);
    expect(
      verified.status,
      `a truncated archive verified clean:\n${verified.stdout}`,
    ).toBe(1);

    // And a confirmed restore of it still refuses — verification is not the
    // only thing standing between a damaged archive and a data directory.
    const restored = exec([
      "flightsite-backup",
      "restore",
      damaged,
      "--data-dir",
      RESTORE_DIR,
      "--confirm",
    ]);
    expect(
      restored.status,
      "a truncated archive was restored anyway",
    ).toBe(1);
  });
});
