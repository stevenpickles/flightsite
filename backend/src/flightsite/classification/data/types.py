"""What an ICAO type designator implies, where it implies anything at all.

Four tables, and the shape of the *fifth* one that is deliberately missing.

Present: military types, rotorcraft, light general-aviation aeroplanes, and
business jets. Absent: airliners. A B738 is flown by scheduled passenger
carriers, by freight operators, by charter companies and, occasionally, by a
government or a private owner — so the airframe alone does not decide the
mission, and a table saying otherwise would manufacture exactly the false
certainty SPEC §39 forbids. An airliner type with no operator resolves to
``unknown``, which is the honest answer and one the tests pin down.

The same discipline applies inside the tables that do exist:

* **Military types** are ones with no meaningful civil operation. ``C130`` is
  the one deliberate exception — a handful of civil L-100 Hercules exist — and
  it is the reason a type match is never better than ``MEDIUM`` confidence.
* **Rotorcraft** are listed by designator rather than matched by prefix.
  Prefixes are tempting (``EC*``, ``H1*``) and wrong: ``H47`` and ``H60`` share
  a prefix with ``H25B``, which is a HS.125 business jet. An explicit list
  cannot make that mistake.
* **Light aeroplanes** are single-engine piston trainers and tourers. They
  imply ``general_aviation``, not ``training``: a C172 in a flying club and a
  C172 at a flight school are the same aeroplane, and only the operator name
  tells them apart.
* **Business jets** imply ``business_aviation`` when nothing stronger is known.
  Governments and air forces also fly Gulfstreams — which is fine, because an
  operator or military-flag match outranks a type match every time.

Designators are stored upper-case, matching
:func:`~flightsite.metadata.records.normalize_record`'s canonical spelling.
"""

from __future__ import annotations

from typing import Final

#: Types flown essentially only by armed forces. Imply ``military`` (the flag)
#: and the ``military`` mission at ``MEDIUM`` confidence.
MILITARY_TYPE_CODES: Final[frozenset[str]] = frozenset(
    {
        # Strategic and tactical airlift, tankers, special mission.
        "C17",
        "C5M",
        "C130",
        "C30J",
        "C27J",
        "K35R",
        "A400",
        "C160",
        "E3TF",
        "E3CF",
        "E6",
        "R135",
        "P8",
        "P3",
        "E2",
        "C2",
        "V22",
        "U2",
        # Combat aircraft.
        "F15",
        "F16",
        "F18",
        "F22",
        "F35",
        "A10",
        "AV8B",
        "B1",
        "B2",
        "B52",
        "EUFI",
        "RFAL",
        "TOR",
        "T38",
        # Rotary-wing types with no civil counterpart.
        "AH64",
        "H47",
    }
)

#: Military types drawn as a transport silhouette rather than a fast jet.
MILITARY_TRANSPORT_TYPE_CODES: Final[frozenset[str]] = frozenset(
    {
        "C17",
        "C5M",
        "C130",
        "C30J",
        "C27J",
        "K35R",
        "A400",
        "C160",
        "E3TF",
        "E3CF",
        "E6",
        "R135",
        "P8",
        "P3",
        "E2",
        "C2",
        "V22",
    }
)

#: Rotorcraft designators. Imply the ``helicopter`` mission when nothing
#: stronger is known, and the ``helicopter`` icon category unconditionally —
#: a police helicopter is still drawn as a helicopter.
ROTORCRAFT_TYPE_CODES: Final[frozenset[str]] = frozenset(
    {
        # Airbus Helicopters / Eurocopter / Aerospatiale.
        "EC20",
        "EC25",
        "EC30",
        "EC35",
        "EC45",
        "EC55",
        "EC75",
        "H120",
        "H125",
        "H130",
        "H135",
        "H145",
        "H155",
        "H160",
        "H175",
        "AS32",
        "AS3B",
        "AS50",
        "AS55",
        "AS65",
        "GAZL",
        "PUMA",
        # Bell.
        "B06",
        "B06T",
        "B212",
        "B222",
        "B230",
        "B407",
        "B412",
        "B427",
        "B429",
        "B430",
        "B505",
        "B47G",
        # Sikorsky.
        "S61",
        "S64",
        "S70",
        "S76",
        "S92",
        "H60",
        # Leonardo / Agusta.
        "A109",
        "A119",
        "A139",
        "A169",
        "A189",
        "LYNX",
        "NH90",
        # Military rotorcraft. Listed here as well as in the military table:
        # the mission comes from the military entry, the silhouette from this
        # one, and an Apache drawn as a fast jet would be plainly wrong.
        "AH64",
        "H47",
        # Robinson, MD, Enstrom, Kamov, Mil.
        "R22",
        "R44",
        "R66",
        "H500",
        "H600",
        "EXPL",
        "EN28",
        "MI8",
        "MI17",
        "MI24",
        # Schweizer / Guimbal / Kopter.
        "S269",
        "S300",
        "CABR",
    }
)

#: Single-engine piston aeroplanes and light twins: general aviation.
LIGHT_AIRCRAFT_TYPE_CODES: Final[frozenset[str]] = frozenset(
    {
        "C150",
        "C152",
        "C162",
        "C170",
        "C172",
        "C175",
        "C177",
        "C180",
        "C182",
        "C185",
        "C206",
        "C210",
        "C72R",
        "C77R",
        "P28A",
        "P28B",
        "P28R",
        "P28T",
        "PA18",
        "PA24",
        "PA32",
        "PA34",
        "BE23",
        "BE33",
        "BE35",
        "BE36",
        "BE55",
        "BE58",
        "SR20",
        "SR22",
        "DA20",
        "DA40",
        "DA42",
        "DA62",
        "M20P",
        "M20T",
        "AA5",
        "TOBA",
        "DR40",
        "GLAS",
        "RV7",
        "RV8",
    }
)

#: Purpose-built business jets.
BUSINESS_JET_TYPE_CODES: Final[frozenset[str]] = frozenset(
    {
        "GLF4",
        "GLF5",
        "GLF6",
        "GL5T",
        "GL7T",
        "GLEX",
        "G280",
        "GALX",
        "C25A",
        "C25B",
        "C25C",
        "C500",
        "C510",
        "C525",
        "C550",
        "C560",
        "C56X",
        "C650",
        "C680",
        "C68A",
        "C700",
        "C750",
        "CL30",
        "CL35",
        "CL60",
        "CL64",
        "E50P",
        "E55P",
        "E545",
        "E550",
        "F2TH",
        "F900",
        "F9EX",
        "FA7X",
        "FA8X",
        "H25B",
        "H25C",
        "LJ31",
        "LJ35",
        "LJ40",
        "LJ45",
        "LJ60",
        "LJ75",
        "PC24",
        "BE40",
        "HDJT",
    }
)

__all__ = [
    "BUSINESS_JET_TYPE_CODES",
    "LIGHT_AIRCRAFT_TYPE_CODES",
    "MILITARY_TRANSPORT_TYPE_CODES",
    "MILITARY_TYPE_CODES",
    "ROTORCRAFT_TYPE_CODES",
]
