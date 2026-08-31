# Release vX.Y.Z

<!-- Release PRs only (release/vX.Y.Z → main). Numbered slice PRs use the default
     template. Open this template with ?template=release.md or paste it in. -->

## Release

- **Version:** vX.Y.Z
- **Theme:**
- **Release branch:** `release/vX.Y.Z`
- **Roadmap checkpoint:** (see `planning/roadmap.yaml` `releases` / `docs/ROADMAP.md`)
- **Included slices since last release:**

## Release qualification checklist (SPEC §112 — `docs/RELEASE.md`)

- [ ] Version selected (SemVer-appropriate for the changes)
- [ ] Version bumped (backend package, frontend package, image tags)
- [ ] `CHANGELOG.md` generated and curated **on the release branch only** (SPEC §111)
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
- [ ] Adjacent-version upgrade test: previous release's data dir upgrades in place
- [ ] Demo-mode validation: full stack runs and exercises scenarios
- [ ] Live-decoder validation against readsb/dump1090-fa where appropriate
- [ ] Raspberry Pi 4 qualification where required (`docs/PERFORMANCE.md`)
- [ ] Documentation reviewed for accuracy against the released behavior
- [ ] `docs/LICENSES.md` reviewed — no unresolved blocked rows for shipped features
- [ ] Risk register (`docs/RISKS.md`) reviewed
- [ ] Known issues reviewed and listed in release notes
- [ ] Release notes finalized

## Human approval

> **This PR requires explicit human approval before merge (SPEC §113).** Fable may
> prepare and qualify the release autonomously but may not merge to `main` without a
> human's approval on this PR.

- [ ] Human approval received

## Post-merge steps (performed by Fable after approval)

- [ ] Merge release branch into `main` (merge commit)
- [ ] Tag `vX.Y.Z` on the merge commit
- [ ] Create the GitHub Release with curated notes
- [ ] Publish GHCR images (`flightsite-backend`, `flightsite-frontend`) for
      `linux/arm64` and `linux/amd64`
- [ ] Merge the release branch back into `dev` (merge commit)
