"""``docs/PERFORMANCE.md`` §7 and the storage budget table must not drift apart.

The same arrangement ``tests/perf/test_docs.py`` guards for §2, and for the same
reason: two copies of one set of numbers is exactly what goes stale. Someone
tightens a gate in the code and the document keeps promising the old figure, or
loosens one in the document and nothing enforces the change.

So §7 is treated as a rendering of
:data:`~flightsite.perf.storage_qualification.budgets.STORAGE_BUDGETS`, and
these tests check the rendering. They are deliberately shallow — presence,
value and gate kind, not layout — because a test that pinned the prose would
fail on every edit and be deleted within a month.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from flightsite.perf.budgets import Budget, GateKind
from flightsite.perf.storage_qualification.budgets import STORAGE_BUDGETS
from flightsite.perf.storage_qualification.scenarios import SCENARIO_A, SCENARIO_B

#: backend/tests/perf/storage/test_docs.py -> repo root.
DOC = Path(__file__).resolve().parents[4] / "docs" / "PERFORMANCE.md"

SECTION_HEADING = "## 7. Long-term storage qualification"
HARD_HEADING = "#### 7.2.1 Hard gates"
REFERENCE_HEADING = "#### 7.2.2 Reference budgets"
END_HEADING = "### 7.3"


@pytest.fixture(scope="module")
def document() -> str:
    assert DOC.exists(), f"{DOC} is missing"
    return DOC.read_text(encoding="utf-8")


def section(document: str, start: str, end: str) -> str:
    """The text between two headings."""
    assert start in document, f"{start!r} is missing from {DOC.name}"
    assert end in document, f"{end!r} is missing from {DOC.name}"
    return document.split(start, 1)[1].split(end, 1)[0]


def test_the_storage_section_exists(document: str) -> None:
    """Slice 050's results live in this document, per its acceptance criterion."""
    assert SECTION_HEADING in document


@pytest.mark.parametrize("budget", STORAGE_BUDGETS, ids=lambda budget: budget.metric)
def test_every_budget_appears_in_the_document(budget: Budget, document: str) -> None:
    """A budget the document omits is one nobody reviewing the product can see."""
    assert budget.metric in document, (
        f"{budget.metric} is judged by the qualification but absent from {DOC.name}"
    )


@pytest.mark.parametrize("budget", STORAGE_BUDGETS, ids=lambda budget: budget.metric)
def test_each_budget_is_documented_under_its_own_gate_kind(budget: Budget, document: str) -> None:
    """The hard/reference split is the section's central claim.

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


@pytest.mark.parametrize("budget", STORAGE_BUDGETS, ids=lambda budget: budget.metric)
def test_each_documented_row_quotes_its_own_budget_value(budget: Budget, document: str) -> None:
    """The number in the table is the number the qualification enforces.

    Checked only within that budget's own row, so an unrelated ``500``
    elsewhere in the document cannot satisfy it.
    """
    rows = [line for line in document.splitlines() if f"`{budget.metric}`" in line]
    assert rows, f"no table row for {budget.metric} in {DOC.name}"
    rendered = f"{budget.value:g}"
    assert any(rendered in row for row in rows), (
        f"{budget.metric}'s row does not quote its budget of {rendered} {budget.unit}"
    )


def test_the_section_names_the_spec_item_it_answers(document: str) -> None:
    """SPEC §86 is the charter; a reader must be able to find it from here."""
    storage = document.split(SECTION_HEADING, 1)[1]
    assert "SPEC §86" in storage
    assert "slice 050" in storage


def test_the_documented_scenarios_are_the_ones_encoded(document: str) -> None:
    """§7.3's derivation of one budget from two scenarios must quote both."""
    storage = document.split(SECTION_HEADING, 1)[1]
    for scenario in (SCENARIO_A, SCENARIO_B):
        low, high = scenario.predicted_gb_per_year
        assert f"{low:g}" in storage and f"{high:g}" in storage, (
            f"{scenario.name}'s predicted {low:g}-{high:g} GB/year is not in §7.3"
        )
    assert "2 KB per sighting" in storage


def test_the_command_is_documented_with_the_flags_it_accepts(document: str) -> None:
    """§7.5 is what an operator follows on the hardware being qualified."""
    storage = document.split(SECTION_HEADING, 1)[1]
    assert "flightsite-storage-qual" in storage
    for flag in ("--scenario", "--days", "--data-dir", "--json", "--skip-backup"):
        assert flag in storage, f"{flag} is accepted by the CLI but undocumented"


def test_the_load_marker_is_documented(document: str) -> None:
    """The multi-year run is opt-in, and the document has to say how."""
    storage = document.split(SECTION_HEADING, 1)[1]
    assert "-m load" in storage


def test_the_document_records_whether_a_pi_storage_baseline_exists(document: str) -> None:
    """§7.6 must carry either a disclaimer or a result, never both or neither.

    The same guard ``tests/perf/test_docs.py`` puts on §5.4, for the same
    reason: an empty results table is easy to mistake for a passing one. When a
    Pi 4 storage baseline is finally recorded, this test is what reminds
    whoever adds it to delete the disclaimer above it — and, per §7.8, to
    revisit which reference budgets can now be promoted.
    """
    storage = document.split(SECTION_HEADING, 1)[1]
    has_disclaimer = "No Raspberry Pi 4 storage baseline has been recorded yet" in storage
    has_result = "not yet run" not in storage
    assert has_disclaimer != has_result, (
        "docs/PERFORMANCE.md §7.6 must either carry the 'no baseline yet' "
        "disclaimer or a recorded Pi 4 result, not both and not neither"
    )


def test_the_findings_section_records_what_the_run_surfaced(document: str) -> None:
    """A qualification that measured an overrun and said nothing is worthless.

    §7.7 is where a measured figure becomes an actionable sentence. Pinned
    loosely — the presence of the section, the mechanism behind the growth
    overrun, and the fact that findings are handed on rather than acted on —
    because the prose will and should change as they are addressed.
    """
    storage = document.split(SECTION_HEADING, 1)[1]
    assert "### 7.7 Findings for later slices" in storage
    assert "overflow page" in storage
    assert "WITHOUT ROWID" in storage
    assert "roadmap entry" in storage
