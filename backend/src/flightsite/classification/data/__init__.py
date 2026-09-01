"""Curated classification data, kept apart from the logic that reads it.

Everything in this package is *data a person maintains*: operator groups, the
names and callsign prefixes that map onto them, and the type designators whose
meaning is unambiguous. None of it contains behaviour, which is the point —
adding an airline or a helicopter type is a reviewable diff in a table, not a
change to the engine.

Python literals rather than JSON or YAML. The alternative was tempting (a data
file feels like it wants to be data-format), but a literal buys three things a
parsed file cannot: the enums are the real enums, so a typo in a mission
category is a ``mypy`` error rather than a runtime surprise; there is no load,
parse or validate step and therefore no failure mode at start-up; and the
tuples are interned once at import and shared, which matters because the
directory is built once per process. The file is still versioned, still
diffable, and still contains nothing but data.
"""

from __future__ import annotations

__all__: list[str] = []
