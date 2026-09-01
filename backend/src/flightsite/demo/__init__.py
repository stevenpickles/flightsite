"""Deterministic demo/mock decoder traffic (SPEC §76, ``docs/ARCHITECTURE.md`` §3.5).

Module map:

=================================== ==========================================
Module                              Responsibility
=================================== ==========================================
:mod:`~flightsite.demo.motion`      closed-form position/altitude integration
:mod:`~flightsite.demo.roster`      the seeded, deterministic aircraft roster
:mod:`~flightsite.demo.scenario`    tick index -> decoder batch (pure)
:mod:`~flightsite.demo.adapter`     :class:`DemoAdapter`, the ``DecoderAdapter``
:mod:`~flightsite.demo.env`         the ``FLIGHTSITE_DEMO`` activation flag
=================================== ==========================================

:class:`DemoAdapter` implements :class:`~flightsite.ingest.protocol.DecoderAdapter`
(ADR-0003): it is a drop-in replacement for
:class:`~flightsite.ingest.readsb.ReadsbJsonAdapter` that needs no decoder, no
network and no configuration, generating a rotating population of commercial,
military, government, police, non-positioned Mode S, MLAT, rare, first-ever
and ground traffic — including an emergency-squawk event — deterministically
from a seed.
"""

from __future__ import annotations

from flightsite.demo.adapter import (
    DEFAULT_CENTER,
    DEFAULT_POPULATION,
    DEFAULT_SEED,
    TICK_INTERVAL_S,
    DemoAdapter,
)
from flightsite.demo.env import DEMO_ENV_VAR, demo_enabled
from flightsite.demo.roster import PERIOD_S, AircraftProfile, Category, EmergencyEvent, build_roster
from flightsite.demo.scenario import SCENARIO_EPOCH, batch_at, update_at

__all__ = [
    "DEFAULT_CENTER",
    "DEFAULT_POPULATION",
    "DEFAULT_SEED",
    "DEMO_ENV_VAR",
    "PERIOD_S",
    "SCENARIO_EPOCH",
    "TICK_INTERVAL_S",
    "AircraftProfile",
    "Category",
    "DemoAdapter",
    "EmergencyEvent",
    "batch_at",
    "build_roster",
    "demo_enabled",
    "update_at",
]
