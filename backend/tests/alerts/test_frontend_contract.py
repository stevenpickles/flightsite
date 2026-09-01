"""The wizard's template ids against the catalogue they have to name.

Issue #111 was a contract with no checker on either side. The setup wizard's
catalogue lives in TypeScript, the shipped catalogue lives in Python, the wire
between them is ``alerts.enabled_templates`` — a bare ``string[]`` with no
union type, no generated client and no runtime validation — and the backend
answers an id it does not recognize by skipping it. So the wizard said
``law_enforcement``, the catalogue said ``police``, and ticking "Police / law
enforcement aircraft" produced no rule, no error and no log line. It took an
E2E suite to notice.

Both halves of that are fixed — the wizard sends ``police``, and an
unrecognized key is now warned about
(:meth:`flightsite.alerts.service.AlertService._warn_about_key_spellings`) — but
neither stops the *next* drift. This module does. It is the only place in the
repository where both catalogues are visible at once, which is why a Python
test reads a TypeScript file: the frontend's own tests derive their
expectations from ``ALERT_TEMPLATES`` itself, so they pass no matter what the
ids say.

Reading the source rather than a fixture is the point. A checked-in copy of the
backend catalogue would be a third thing to keep in step, and the two that
already exist are one too many.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from flightsite.alerts.templates import TEMPLATE_KEY_ALIASES, TEMPLATES_BY_KEY

#: ``backend/tests/alerts/`` -> the repository root.
REPO_ROOT = Path(__file__).resolve().parents[3]

#: The wizard's catalogue, also imported by the Settings page's alerts section
#: — the two write paths for ``alerts.enabled_templates`` share this one list.
CONSTANTS = REPO_ROOT / "frontend" / "src" / "features" / "setup" / "constants.ts"

_ARRAY = re.compile(r"ALERT_TEMPLATES[^=]*=\s*\[(?P<body>.*?)\]\s*as const;", re.DOTALL)
_ID = re.compile(r"""\bid:\s*["'](?P<id>[^"']+)["']""")
_DEFAULTS = re.compile(r"""DEFAULT_ENABLED_TEMPLATE_IDS[^=]*=\s*\[(?P<body>[^\]]*)\]""", re.DOTALL)
_STRING = re.compile(r"""["'](?P<value>[^"']+)["']""")


def _section(pattern: re.Pattern[str], source: str, what: str) -> str:
    match = pattern.search(source)
    if match is None:  # pragma: no cover - only on a rename this test must fail for
        pytest.fail(
            f"could not find {what} in {CONSTANTS}. If it moved or was renamed, "
            f"update this test — it is the only check that the wizard's template "
            f"ids are keys this backend has."
        )
    return match.group("body")


@pytest.fixture(scope="module")
def source() -> str:
    if not CONSTANTS.is_file():  # pragma: no cover - frontend-less checkout
        pytest.skip(f"frontend sources are not present at {CONSTANTS}")
    return CONSTANTS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def wizard_ids(source: str) -> tuple[str, ...]:
    return tuple(_ID.findall(_section(_ARRAY, source, "ALERT_TEMPLATES")))


def test_the_wizard_offers_exactly_the_shipped_catalogue(wizard_ids: tuple[str, ...]) -> None:
    """Set equality, not containment, and both directions matter.

    An id the backend does not have selects nothing (issue #111). A key the
    wizard does not offer is a shipped template no user can reach — which is
    what ``locally_rare_type`` was: the wizard collapsed SPEC §45's rarity
    entry back into one option labelled "aircraft or type" that sent only
    ``locally_rare``, promising a rule it never created.
    """
    assert set(wizard_ids) == set(TEMPLATES_BY_KEY)


def test_the_wizard_offers_each_template_once(wizard_ids: tuple[str, ...]) -> None:
    """Two boxes for one template would be two ways to ask for one rule."""
    assert len(wizard_ids) == len(set(wizard_ids))


def test_the_wizard_sends_no_deprecated_spelling(wizard_ids: tuple[str, ...]) -> None:
    """The aliases exist for configurations already written to disk, not as a
    second name a current client may use — see
    :data:`flightsite.alerts.templates.TEMPLATE_KEY_ALIASES`. A wizard still
    sending one would keep writing the spelling it is meant to correct."""
    assert not set(wizard_ids) & set(TEMPLATE_KEY_ALIASES)


def test_every_default_ticked_template_is_a_real_key(source: str) -> None:
    """The defaults are what a user who clicks straight through gets, so a typo
    here is the same silent nothing in the most common path of all."""
    defaults = _STRING.findall(_section(_DEFAULTS, source, "DEFAULT_ENABLED_TEMPLATE_IDS"))

    assert defaults, "the wizard should tick some templates by default"
    assert set(defaults) <= set(TEMPLATES_BY_KEY)
