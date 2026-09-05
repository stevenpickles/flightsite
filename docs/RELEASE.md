# FlightSite Release Process

Releases are prepared autonomously by Fable but **the merge into `main` always
requires human approval** (SPEC §113). This document is the release checklist
referenced by SPEC §112.

## Versioning (SPEC §109)

FlightSite uses [Semantic Versioning](https://semver.org/):

- `0.x.y` during development. The first usable integrated release begins around
  **v0.1.0**.
- **v1.0.0** is used only when the complete agreed v1 scope is qualified and stable
  (see [v1.0.0 definition of done](#v100-definition-of-done)).

### Planned release checkpoints

Matching `planning/roadmap.yaml` (`releases`):

| Version | After phase | Theme |
| --- | --- | --- |
| v0.1.0 | 3 | Live radar MVP: ingestion, sightings, live map, demo mode, setup wizard |
| v0.2.0 | 4 | Aircraft identity: offline metadata, classification, enrichment, overlays |
| v0.3.0 | 5 | History & analytics |
| v0.4.0 | 6 | Alerts & notifications |
| v0.5.0 | 7 | Operations: backup/restore, maintenance, diagnostics |
| v1.0.0 | 8 | Qualified stable release per SPEC §114 |

Checkpoints are targets, not obligations — a release ships only when its
qualification checklist passes.

## Release branch workflow (SPEC §110)

```text
dev ──► release/vX.Y.Z ──► PR ──► main   (human approval, merge commit)
              │                    │
              │                    ├─► tag vX.Y.Z, GitHub Release, GHCR publish
              └────────────────────┴─► merged back into dev (merge commit)
```

- The release branch is created from the **qualified `dev` state**.
- **Only** release branches perform release-specific changes: version bump,
  `CHANGELOG.md` update, final release notes, release metadata.
- Feature branches and `dev` never touch `CHANGELOG.md` (SPEC §111).
- Release PRs use `.github/PULL_REQUEST_TEMPLATE/release.md` (open the PR with the
  `?template=release.md` query parameter, or paste the template in). Numbered slice
  PRs use the default template.

## Changelog rule (SPEC §111)

On the release branch, generate the changelog from accumulated Conventional Commits,
merged PR information, and roadmap/slice history — then **curate it into useful
human-facing release notes** (grouped by feature area, user-visible impact first,
upgrade notes and known issues called out).

## Release qualification checklist (SPEC §112)

Every release branch must complete all applicable items:

- [ ] Version selected (SemVer-appropriate for the changes)
- [ ] Version bumped (backend package, frontend package, image tags)
- [ ] `CHANGELOG.md` generated and curated on the release branch
- [ ] Migration validation: fresh DB and upgrade fixtures migrate cleanly
- [ ] Full CI green (backend, frontend, security, Docker workflows)
- [ ] Full E2E suite green
- [ ] Visual regression suite green (or diffs reviewed and accepted)
- [ ] Security scan results reviewed; no unwaived high/critical findings
- [ ] Dependency scan results reviewed; no unwaived high/critical findings
- [ ] Fresh installation from documentation succeeds on a clean host
- [ ] Docker Compose deployment validated (arm64 and amd64 images)
- [ ] Backup test: backup taken during active ingestion, manifest valid
- [ ] Restore test: backup restores and passes integrity checks
- [ ] Adjacent-version upgrade test: previous release's data dir upgrades in place —
      run against a **populated** data directory (a real deployment's backup, or a
      slice-050 synthetic dataset), not a fresh or lightly seeded one, and **before the
      release PR is opened**. Record the wall time of the migration step. An empty
      database exercises none of the per-row work a schema change does, which is how
      v0.6.0 shipped a migration that hung and failed on any real install (issue #178)
- [ ] Demo-mode validation: full stack runs and exercises scenarios
- [ ] Live-decoder validation against readsb/dump1090-fa where appropriate
- [ ] Raspberry Pi 4 qualification where required — run the procedure in
      `docs/PERFORMANCE.md` §5
  - [ ] Baseline recorded under §5, one subsection per machine (§5.3 step 1); a
        later Pi model runs the same procedure and is recorded beside the Pi 4
        rather than in place of it
- [ ] Documentation reviewed for accuracy against the released behavior
- [ ] `docs/LICENSES.md` reviewed — no unresolved blocked rows for shipped features
- [ ] Risk register (`docs/RISKS.md`) reviewed
- [ ] Known issues reviewed and listed in release notes
- [ ] Release notes finalized

Material high/critical security findings **block the release** (SPEC §88).

## Approval and publication (SPEC §113)

1. Fable prepares the release branch and completes qualification autonomously.
2. Fable opens the PR `release/vX.Y.Z → main`.
3. **A human approves the PR.** Fable may not merge to `main` without this.
4. After approval, Fable:
   1. merges the release branch into `main` (merge commit),
   2. tags the release `vX.Y.Z` on the merge commit,
   3. creates the GitHub Release with the curated notes,
   4. publishes GHCR images (`ghcr.io/<owner>/flightsite-backend`,
      `ghcr.io/<owner>/flightsite-frontend`) for `linux/arm64` and `linux/amd64`,
   5. merges the release branch back into `dev` (merge commit).

## v1.0.0 definition of done (SPEC §114)

v1.0.0 may be proposed only when **all** of the following hold:

- [ ] Every v1 roadmap slice is complete
- [ ] All mandatory tests pass
- [ ] All required CI gates pass
- [ ] Raspberry Pi 4 performance qualification passes
- [ ] Multi-year storage qualification passes
- [ ] Fresh install works from documentation alone
- [ ] Backup works
- [ ] Restore works
- [ ] Upgrade path works
- [ ] Demo mode works
- [ ] Live readsb/dump1090-fa ingestion is validated
- [ ] No known critical/high-severity product bugs remain — the query
      `gh issue list --state open --search 'label:severity:critical,severity:high label:bug'`
      returns nothing (label definitions: `docs/DEVELOPMENT.md`, GitHub Issues)
- [ ] Architecture documentation matches reality
- [ ] API documentation matches reality
- [ ] Deployment documentation matches reality
- [ ] Security assumptions are documented
- [ ] Release checklist passes completely

## User upgrade model (SPEC §115)

There is no in-app self-updater. Users upgrade with:

```bash
docker compose pull
docker compose up -d
```

Database migrations run safely during startup. Release notes for releases containing
schema changes must recommend taking a backup first (`docs/BACKUP.md`, slice 043).

## Rollback

If a release must be rolled back on a deployment:

1. Stop the stack: `docker compose down`.
2. Restore the pre-upgrade backup into the data directory (see `docs/BACKUP.md`) —
   required if the newer version migrated the schema, since older FlightSite refuses
   newer-schema databases by design (SPEC §72).
3. Pin the previous image tags in `compose.yaml` (e.g. `:v0.3.0`) and
   `docker compose up -d`.

At the repository level, a bad release is corrected by a fix-forward patch release
(`v X.Y.Z+1`) — `main` is never force-pushed.
