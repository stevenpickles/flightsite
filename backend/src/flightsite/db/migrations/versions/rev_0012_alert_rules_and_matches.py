"""Alert rules and alert matches.

Creates the two tables ``docs/DATA_MODEL.md`` §4.2 and §4.3 give slice 038 —
``alert_rules`` and ``alert_matches`` — per SPEC §43 to §48. Nothing existing
references them, so the downgrade is a plain drop.

``alert_rules`` stores its conditions as one embedded JSON document rather than
as a child table. §4.2 states the reason and this revision simply obeys it: v1
combines a small closed set of conditions with ``AND`` only (SPEC §43), they are
evaluated in memory against live state and never queried relationally, and the
document carries its own ``version`` so a future nested-expression feature
migrates explicitly. The runtime shape is
:class:`flightsite.alerts.model.RuleConditions`; nothing in SQL constrains it
beyond ``NOT NULL``, which is deliberate — a ``CHECK`` cannot validate a JSON
document, and pretending otherwise would put half a schema in two places.

``alert_matches`` carries the two **partial unique indexes** that are the
once-per-sighting-per-rule guarantee of SPEC §48 at the storage layer. They are
two indexes rather than one over ``(rule_id, builtin_key, sighting_id)``
because a row carries exactly one origin and SQLite treats every ``NULL`` in a
unique index as distinct — a combined index would constrain nothing at all.
Together with ``ck_alert_matches_origin`` they say: every match names a rule or
a built-in, and neither can fire twice within one sighting.

``rule_id`` has no ``ON DELETE`` action, exactly as §4.3 declares it, and
ADR-0001 runs with ``PRAGMA foreign_keys = ON`` — so deleting a rule that has
matched is a referential error unless its matches go with it. That is the
behaviour :class:`flightsite.alerts.repository.AlertRepository` implements, in
one transaction, and it discards less than it appears to: the sighting keeps
its ``max_alert_severity`` and its ``alert_matched`` sighting event, and the
activity feed keeps the ``alert_triggered`` row carrying the rule's name, its
severity and the reason text. What a rule deletion removes is the rule-linked
operational log, not the record that the aircraft was interesting.

``ix_amatch_matched`` is the alert-history read path (``docs/API.md`` §3.9's
``GET /api/v1/alerts/matches``), which is newest-first over a growing table and
therefore the one query here whose cost would otherwise scale with history.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: ``docs/API.md`` §2.8's severity ladder on a column named ``severity``,
#: mirroring :data:`flightsite.db.models.ALERT_ROW_SEVERITY_CHECK`. Spelled out
#: again here rather than imported: a migration must keep reading correctly
#: however the model file evolves after this revision is written (the rule every
#: other migration in this directory follows).
_SEVERITY_CHECK = "severity IN ('info', 'interesting', 'high', 'critical')"

#: Mirrors :data:`flightsite.db.models.ALERT_MATCH_ORIGIN_CHECK`.
_ORIGIN_CHECK = "rule_id IS NOT NULL OR builtin_key IS NOT NULL"


def upgrade() -> None:
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("template_key", sa.Text(), nullable=True),
        sa.Column("conditions_json", sa.Text(), nullable=False),
        sa.Column("created_ms", sa.Integer(), nullable=False),
        sa.Column("updated_ms", sa.Integer(), nullable=False),
        sa.CheckConstraint(_SEVERITY_CHECK, name="ck_alert_rules_severity"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "alert_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=True),
        sa.Column("builtin_key", sa.Text(), nullable=True),
        sa.Column("sighting_id", sa.Integer(), nullable=False),
        sa.Column("aircraft_id", sa.Integer(), nullable=False),
        sa.Column("matched_ms", sa.Integer(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("notified", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.CheckConstraint(_SEVERITY_CHECK, name="ck_alert_matches_severity"),
        sa.CheckConstraint(_ORIGIN_CHECK, name="ck_alert_matches_origin"),
        sa.ForeignKeyConstraint(["rule_id"], ["alert_rules.id"]),
        sa.ForeignKeyConstraint(["sighting_id"], ["sightings.id"]),
        sa.ForeignKeyConstraint(["aircraft_id"], ["aircraft.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_amatch_rule_sighting",
        "alert_matches",
        ["rule_id", "sighting_id"],
        unique=True,
        sqlite_where=sa.text("rule_id IS NOT NULL"),
    )
    op.create_index(
        "ux_amatch_builtin_sighting",
        "alert_matches",
        ["builtin_key", "sighting_id"],
        unique=True,
        sqlite_where=sa.text("builtin_key IS NOT NULL"),
    )
    op.create_index("ix_amatch_matched", "alert_matches", ["matched_ms"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_amatch_matched", table_name="alert_matches")
    op.drop_index("ux_amatch_builtin_sighting", table_name="alert_matches")
    op.drop_index("ux_amatch_rule_sighting", table_name="alert_matches")
    op.drop_table("alert_matches")
    op.drop_table("alert_rules")
