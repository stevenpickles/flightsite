<!-- PR title format: "Slice NNN: <title>"  (or "Release vX.Y.Z" for release PRs) -->

## Slice

- **Slice ID:**
- **Roadmap reference:** `planning/roadmap.yaml` → slice `NNN`
- **Linked issue:** Closes #

## Objective

<!-- One sentence: what this slice delivers, per the roadmap objective. -->

## Implementation summary

<!-- What was built and how; notable design decisions; anything a reviewer must know. -->

## Acceptance criteria

<!-- Copy the slice's acceptance_criteria from planning/roadmap.yaml; check each off. -->

- [ ]
- [ ]

## Tests added / run

<!-- Test layers added (unit/domain/persistence/migration/API/component/E2E), key cases, and the commands run. -->

## Performance considerations

<!-- Impact on ingestion, live-state latency, SQLite, memory, Pi 4 envelope. "None" with justification is acceptable. -->

## Security considerations

<!-- Secrets handling, input validation, exposure surface, trusted-LAN assumptions. "None" with justification is acceptable. -->

## Data / migration considerations

<!-- Schema changes, Alembic revisions, upgrade/rollback behavior, data retention impact. "No schema changes" if applicable. -->

## Documentation updates

<!-- Docs touched in this PR (docs/, README, config reference, ADRs). -->

## Known limitations

<!-- Honest list; each limitation must be acceptable within slice scope or tracked as follow-up. -->

## Follow-up work

<!-- Tracked issues/roadmap items created or referenced; no untracked TODOs. -->

---

## Fable self-review attestation (SPEC §104)

The complete diff has been inspected and each item verified:

- [ ] Acceptance criteria satisfied
- [ ] No scope creep
- [ ] Tests are meaningful; failure cases covered
- [ ] APIs/types coherent
- [ ] Migrations safe
- [ ] Logs/error handling appropriate
- [ ] Security and privacy assumptions preserved
- [ ] Performance acceptable
- [ ] Documentation updated
- [ ] No temporary debug code; no untracked TODO/FIXME
- [ ] Branch reconciled with current `dev`
- [ ] All mandatory CI checks passing
