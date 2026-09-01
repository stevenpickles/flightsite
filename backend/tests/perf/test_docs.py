"""``docs/PERFORMANCE.md`` and the budget table must not drift apart.

The document is the canonical statement of what FlightSite must achieve, and
`backend/src/flightsite/perf/budgets.py` is what actually enforces it. Two
copies of the same numbers is exactly the arrangement that goes stale: someone
tightens a gate in the code and the document keeps promising the old figure, or
loosens one in the document and nothing enforces the change.

So the document is treated as a rendering of the table, and these tests check
the rendering. They are deliberately shallow — presence and value, not layout —
because a test that pinned the prose would fail on every edit and be deleted
within a month.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from flightsite.perf.budgets import BUDGETS, TARGET_AIRCRAFT, Budget, GateKind

#: backend/tests/perf/test_docs.py -> repo root.
DOC = Path(__file__).resolve().parents[3] / "docs" / "PERFORMANCE.md"

HARD_HEADING = "### 2.1 Hard gates"
REFERENCE_HEADING = "### 2.2 Reference budgets"
END_HEADING = "### 2.3"


@pytest.fixture(scope="module")
def document() -> str:
    assert DOC.exists(), f"{DOC} is missing; slice 049 publishes it"
    return DOC.read_text(encoding="utf-8")


def section(document: str, start: str, end: str) -> str:
    """The text between two headings."""
    assert start in document, f"{start!r} is missing from {DOC.name}"
    assert end in document, f"{end!r} is missing from {DOC.name}"
    return document.split(start, 1)[1].split(end, 1)[0]


@pytest.mark.parametrize("budget", BUDGETS, ids=lambda budget: budget.metric)
def test_every_budget_appears_in_the_document(budget: Budget, document: str) -> None:
    """A budget the document omits is one nobody reviewing the product can see."""
    assert budget.metric in document, (
        f"{budget.metric} is enforced by the harness but absent from {DOC.name}"
    )


@pytest.mark.parametrize("budget", BUDGETS, ids=lambda budget: budget.metric)
def test_each_budget_is_documented_under_its_own_gate_kind(budget: Budget, document: str) -> None:
    """The hard/reference split is the document's central claim.

    A hard gate listed among the trend-tracked figures — or the reverse — would
    misrepresent what a merge is actually allowed to break.
    """
    hard = section(document, HARD_HEADING, REFERENCE_HEADING)
    reference = section(document, REFERENCE_HEADING, END_HEADING)
    wanted, other = (hard, reference) if budget.gate is GateKind.HARD else (reference, hard)
    assert budget.metric in wanted, (
        f"{budget.metric} is a {budget.gate.value} gate but is not listed in that table"
    )
    assert budget.metric not in other, (
        f"{budget.metric} is a {budget.gate.value} gate but appears in the other table"
    )


@pytest.mark.parametrize("budget", BUDGETS, ids=lambda budget: budget.metric)
def test_each_documented_row_quotes_its_own_budget_value(budget: Budget, document: str) -> None:
    """The number in the table is the number the harness enforces.

    Formatted the way the document writes it — ``100`` rather than ``100.0`` for
    a whole number — and only checked within that budget's own row, so an
    unrelated ``500`` elsewhere cannot satisfy it.
    """
    rows = [line for line in document.splitlines() if f"`{budget.metric}`" in line]
    assert rows, f"no table row for {budget.metric} in {DOC.name}"
    value = budget.value
    rendered = f"{value:g}"
    assert any(rendered in row for row in rows), (
        f"{budget.metric}'s row does not quote its budget of {rendered} {budget.unit}"
    )


def test_the_envelope_the_document_states_is_the_one_the_harness_runs() -> None:
    """SPEC §5's 500 aircraft, in the document and in the code."""
    document = DOC.read_text(encoding="utf-8")
    assert f"{TARGET_AIRCRAFT}" in document
    assert "Raspberry Pi 4" in document


def test_the_document_records_whether_a_pi_baseline_exists(document: str) -> None:
    """The second acceptance criterion of slice 049 is a recorded Pi 4 run.

    Until one exists the document must say so plainly rather than leaving an
    empty table a reader could mistake for a passing result. When a baseline is
    added, this test is what reminds whoever adds it to remove the disclaimer.
    """
    has_disclaimer = "No Raspberry Pi 4 baseline has been recorded yet" in document
    has_result = "not yet run" not in document
    assert has_disclaimer != has_result, (
        "docs/PERFORMANCE.md §5.4 must either carry the 'no baseline yet' "
        "disclaimer or a recorded result, not both and not neither"
    )
