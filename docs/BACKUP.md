# FlightSite Backup and Restore

FlightSite ships a single command — `flightsite-backup` — with three
subcommands: `create`, `verify`, and `restore`. This document is the operator
procedure for all three (SPEC §72).

**The one rule to remember:** taking a backup is safe at any time, including
while FlightSite is running. **Restoring is not — stop FlightSite first.**

## Where backups live

All persistent FlightSite state lives under one directory, by default
`/opt/flightsite/data` (`docs/ARCHITECTURE.md` §2.1):

```text
/opt/flightsite/data/
  config.yaml        # canonical non-secret configuration
  secrets.yaml       # optional secrets (AeroDataBox key)
  flightsite.sqlite3 # application database (+ -wal/-shm)
  logs/              # rotating structured logs
  backups/           # ← backups land here by default
```

Archives are named `flightsite-backup-<UTC timestamp>.tar.gz`, for example
`flightsite-backup-20260901T120000Z.tar.gz`. Nothing rotates or deletes them:
FlightSite writes backups and leaves them alone, so disk usage under
`backups/` is yours to manage. Scheduled backups are deliberately out of scope
for v1 — use `cron` on the host if you want them.

`--out DIR` writes the archive somewhere else instead (a USB stick, an NFS
mount, `/tmp` before you `scp` it away).

## Taking a backup

From the host running the Compose stack:

```bash
docker compose exec flightsite-backend flightsite-backup create
```

With the stack stopped, or on a bare install, point the command at the data
directory:

```bash
flightsite-backup create --data-dir /opt/flightsite/data
```

Both forms produce the same archive. Inside the container no arguments are
needed because `FLIGHTSITE_DATA_DIR` is already set.

To write the archive outside the data directory:

```bash
docker compose exec flightsite-backend \
  flightsite-backup create --out /opt/flightsite/data/backups/pre-upgrade
```

### It is safe to back up while FlightSite is running

The database snapshot is taken with SQLite's `VACUUM INTO`, which runs inside a
single read transaction. FlightSite runs the database in WAL mode
([ADR-0001](adr/0001-sqlite-sole-persistence-store.md)), where readers neither
block nor are blocked by the writer, so:

- ingestion and the write-behind persistence worker keep running throughout;
- the snapshot is a consistent point-in-time image — never a half-written
  transaction;
- the snapshot is a complete, compacted single file with no `-wal` sidecar to
  carry along.

`VACUUM INTO` is used rather than SQLite's online backup API because that API
restarts its page copy whenever the source is written during the copy, which
against a continuously writing FlightSite could take arbitrarily long.

A backup of a multi-gigabyte history takes a while and does real disk I/O.
On a Raspberry Pi, expect the map to feel no different but the SD card to be
busy. Take backups when you are not also doing something else heavy.

## What is in an archive

| Member | Always? | What it is |
| --- | --- | --- |
| `manifest.json` | yes | version, schema revision, checksums, dataset versions |
| `flightsite.sqlite3` | yes | the database snapshot: sightings, aircraft, metadata, analytics rollups, alert rules and matches |
| `config.yaml` | if present | your non-secret configuration |
| `secrets.yaml` | **only with `--include-secrets`** | your AeroDataBox API key |

**Not** included, and not needed for a restore: `logs/`, the `-wal`/`-shm`
sidecars (they are folded into the snapshot), earlier archives under
`backups/`, and anything outside the data directory — notably your
`compose.yaml` and `.env`, which you should keep in your own configuration
backup.

### Secrets policy

Secrets are excluded by default (`docs/SECURITY.md` §3). An archive taken with
`--include-secrets` is **as sensitive as `secrets.yaml` itself**: treat it
accordingly, and prefer keeping the key in your password manager and restoring
it by hand over copying secret-bearing archives around.

The manifest always states which way it went:

```json
"includes_secrets": false
```

This is honest rather than aspirational — asking for `--include-secrets` on an
installation that has no `secrets.yaml` records `false`, and the command says so
on stderr.

### The manifest

```json
{
  "format_version": 1,
  "flightsite_version": "0.5.0",
  "schema_revision": "0009",
  "created_utc": "2026-09-01T12:00:00Z",
  "includes_secrets": false,
  "files": {
    "flightsite.sqlite3": { "sha256": "…", "size_bytes": 41582592 },
    "config.yaml": { "sha256": "…", "size_bytes": 1874 }
  },
  "metadata_sources": [
    { "source": "mictronics", "dataset_version": "2026-08-01", "last_success": "2026-08-02T03:14:00Z" }
  ]
}
```

`schema_revision` is the Alembic revision of the snapshot itself, and it is what
makes restores version-aware.

## Checking an archive

`verify` reads an archive and reports on it. It never writes anything, so it is
safe to run against a production data directory at any time:

```bash
docker compose exec flightsite-backend flightsite-backup verify \
  /opt/flightsite/data/backups/flightsite-backup-20260901T120000Z.tar.gz
```

It checks, and reports on, all of:

1. the archive opens as a gzip tar;
2. `manifest.json` is present and in a format this build understands;
3. the members are exactly what the manifest lists, and all are regular files;
4. the schema revision is restorable by this build;
5. every member's SHA-256 and size match the manifest.

It exits `0` when the archive is restorable and `1` when it is not, printing
every problem it found — so it works in a cron job or a pre-upgrade script.

**Verify your backups periodically.** An unverified backup is a hypothesis.

## Restoring

Restore is destructive: it replaces the database and configuration in the data
directory. It therefore requires `--confirm`, and there is a documented order
of operations.

```bash
# 1. Stop FlightSite.
docker compose down

# 2. Restore. --confirm is required; without it the command refuses.
docker compose run --rm flightsite-backend flightsite-backup restore \
  /opt/flightsite/data/backups/flightsite-backup-20260901T120000Z.tar.gz --confirm

# 3. Start FlightSite. It migrates the schema if needed and runs its
#    startup integrity check.
docker compose up -d
```

Then confirm the instance came back healthy:

```bash
curl -fsS http://localhost:8080/api/v1/ready
```

Without Compose:

```bash
flightsite-backup restore /path/to/archive.tar.gz \
  --data-dir /opt/flightsite/data --confirm
```

### Stop FlightSite before restoring

FlightSite has no lock file and does not try to detect whether it is running —
any cheap check would be both spoofable and prone to false refusals across
container restarts, and a wrong refusal during a recovery is worse than no
check. **The rule is operational: stop the stack first.**

The restore is nonetheless built to survive the mistake rather than corrupt
your data. Each file is replaced whole, by rename, so a still-running
FlightSite keeps writing to the old file (now unlinked) rather than into the
middle of the restored one. You lose whatever it wrote after the restore, which
is what you asked for anyway — but the restored files are intact. Restart the
stack and you are in the state the archive describes.

### What restore does, in order

1. Refuses immediately unless `--confirm` was given.
2. Reads and validates the manifest, and checks schema compatibility — both
   cheap, so an incompatible archive is refused before any bytes are written.
3. Extracts each member into a staging directory *inside* the data directory,
   verifying SHA-256 as it goes. Nothing outside staging has been touched yet.
4. Swaps: each live file is moved aside to `<name>.pre-restore.<timestamp>`,
   then the staged file is renamed into place. Stale `flightsite.sqlite3-wal`
   and `-shm` sidecars are moved aside too — they describe the *replaced*
   database and must not survive.
5. Deletes the `.pre-restore.*` copies, but only after the whole swap
   succeeded. If any step fails, every move is undone and the data directory is
   left exactly as it was found.

A member the archive does not carry is left alone rather than deleted. In
particular, restoring a backup taken **without** `--include-secrets` does not
remove an existing `secrets.yaml`: your API key survives the restore. The
command says which way it went in its summary.

### Version compatibility (SPEC §72)

| Backup schema revision | Result |
| --- | --- |
| same as this build's head | restored; no migration needed |
| an ancestor of this build's head (older) | restored, then **migrated to head at the next startup** |
| anything else (newer, or unknown) | **refused** |

Older backups restoring into a newer FlightSite is the ordinary path, and it is
the same migration path an in-place data directory takes — restore does not
migrate anything itself; the normal startup sequence does.

A **newer**-schema backup is refused on an older FlightSite because this build
has no migration that could bring the schema back down, and running old code
against a newer schema is how data gets silently mangled. If you hit this,
upgrade FlightSite to at least the version that wrote the archive and retry.
This refusal is what makes the rollback procedure in `docs/RELEASE.md` safe.

### If restore refuses

| Message | Meaning | What to do |
| --- | --- | --- |
| `checksum mismatch` / `size mismatch` | the archive is corrupt or was modified | use another backup; check the media it was stored on |
| `not a readable FlightSite backup archive` | not a gzip tar, or badly truncated | check you named the right file, and that the copy completed |
| `manifest is missing…` / `format_version … is not supported` | not a FlightSite archive, or from a much newer build | restore with the version that wrote it |
| `not part of this build's migration history` | newer-schema backup | upgrade FlightSite, then retry |
| `Re-run with --confirm` | you did not confirm | stop FlightSite, then add `--confirm` |

Nothing in the data directory has been changed in any of these cases.

## Moving an installation to another host (SPEC §116)

A FlightSite installation is the data directory plus the deployment
configuration. To move it:

1. On the old host: `docker compose down`, then
   `flightsite-backup create --include-secrets` (or take the backup without
   secrets and carry the API key separately, which is safer).
2. Copy the archive and your `compose.yaml` / `.env` to the new host.
3. On the new host, create the data directory as described in `compose.yaml`,
   then `flightsite-backup verify` the archive, then restore it into that
   directory with `--confirm`.
4. `docker compose up -d`. If the new host runs a newer FlightSite, it migrates
   the restored database to head on that first start.

Archives are architecture-independent: a backup taken on an `amd64` machine
restores on a Raspberry Pi (`arm64`) and vice versa. SQLite database files are
portable across both.

Copying the whole data directory while the stack is stopped works too, and is
the fastest option on the same filesystem — but the archive is the form that
carries a manifest, checksums, and a schema revision, so it is the one to use
when anything about the two hosts differs.

## Before upgrading

Release notes for versions containing schema changes recommend taking a backup
first (`docs/RELEASE.md`). The habit worth keeping:

```bash
docker compose exec flightsite-backend flightsite-backup create
docker compose exec flightsite-backend flightsite-backup verify \
  /opt/flightsite/data/backups/flightsite-backup-<timestamp>.tar.gz
docker compose pull && docker compose up -d
```

If the upgrade goes badly, `docs/RELEASE.md` §Rollback restores that archive and
pins the previous image tags.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | success |
| `1` | refused: damaged archive, incompatible schema, no database to back up, failed swap |
| `2` | wrong invocation — including `restore` without `--confirm` |
