"""Receiver metrics: decoder statistics, FlightSite metrics, and retention.

SPEC §60 asks for two things that arrive from different places and are stored
as one: the decoder's own statistics where it offers them, and the metrics
FlightSite computes from what it can see. SPEC §64 and
[ADR-0009](../../../../docs/adr/0009-receiver-metric-retention.md) then bound
what any of it costs on a Raspberry Pi, with three tiers — a rolling
high-resolution window, permanent hourly and daily summaries, and lifetime
records that no amount of pruning may lose.

Module map:

============================================== =====================================
Module                                         Responsibility
============================================== =====================================
:mod:`~flightsite.receiver_metrics.model`      domain types; absence as a value
:mod:`~flightsite.receiver_metrics.statsjson`  the ``stats.json`` decoder edge
:mod:`~flightsite.receiver_metrics.sampler`    FlightSite-computed metrics
:mod:`~flightsite.receiver_metrics.aggregate`  downsampling arithmetic (pure)
:mod:`~flightsite.receiver_metrics.lifetime`   records pruning may not lose
:mod:`~flightsite.receiver_metrics.repository` the five tables of §6
:mod:`~flightsite.receiver_metrics.service`    the poller and maintenance tasks
============================================== =====================================

Only :mod:`~flightsite.receiver_metrics.statsjson` knows a decoder's
statistics field names (SPEC §11, ADR-0003), and only
:mod:`~flightsite.receiver_metrics.repository` contains SQL.

This slice owns the *data*. The receiver stats API and the pages that draw it
— scorecard, charts, the range-by-bearing polar plot — are slice 034's, and
the signal-strength *distribution* chart is neither's business here: SPEC §62
wants a population of per-sighting reception statistics, and
``docs/DATA_MODEL.md`` §6.2 is explicit that a histogram of sample-averaged
receiver RSSI is not that.
"""

from __future__ import annotations

from flightsite.receiver_metrics.lifetime import LifetimeDelta, LifetimeValue
from flightsite.receiver_metrics.model import (
    BEARING_BUCKETS,
    LIFETIME_KEYS,
    DecoderStats,
    MetricSample,
    MetricSummary,
    RangeRecord,
    bearing_bucket,
)
from flightsite.receiver_metrics.repository import MetricsRepository
from flightsite.receiver_metrics.service import MaintenanceResult, ReceiverMetricsService
from flightsite.receiver_metrics.statsjson import StatsJsonPoller, StatsPoll, stats_url_for

__all__ = [
    "BEARING_BUCKETS",
    "LIFETIME_KEYS",
    "DecoderStats",
    "LifetimeDelta",
    "LifetimeValue",
    "MaintenanceResult",
    "MetricSample",
    "MetricSummary",
    "MetricsRepository",
    "RangeRecord",
    "ReceiverMetricsService",
    "StatsJsonPoller",
    "StatsPoll",
    "bearing_bucket",
    "stats_url_for",
]
