"""The producers: observed facts in, exactly the events they justify out.

Every function here is pure — no session, no clock, no I/O — so the roadmap's
first acceptance criterion for this slice, *"fixture scenarios emit exactly the
expected events (no duplicates on restart/replay)"*, is checked as arithmetic.
The database's part of that guarantee is the ``UNIQUE`` ``dedupe_key``; this
module's part is not proposing an event the facts do not support in the first
place.

What a "record" producer will and will not announce
---------------------------------------------------

:func:`record_events` and :func:`longest_sighting_event` announce a rolling
record only when a **previous record existed**. That is not timidity about
duplicates — the dedupe keys already handle those — it is what makes the
announcement true. On a receiver that has never heard anything, the first
aircraft it hears is trivially the furthest ever, the busiest day ever and the
longest sighting ever, and calling those records would be three events about
nothing. So the first observation of each record seeds silently and the second
one onwards is measured against it.

The honest consequence, stated rather than hidden: the opening hours of a brand
new install do produce a short run of genuine record events as the receiver
establishes its baselines — the furthest detection really is being beaten every
few minutes at first. It stops on its own as records get harder to beat, which
is the same reason nobody needs to damp it artificially.

An install that *upgrades* into this slice is the other case, and it is handled
one level up: the service seeds its baselines from ``lifetime_stats`` before
its first pass and starts its sighting scan at the present, so years of
existing history announce nothing at all.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from flightsite.activity.facts import (
    AlertMatchFact,
    HealthEpisode,
    ImportOutcome,
    LongestSighting,
    MilitaryFirst,
    ReceiverRecords,
    SightingObservation,
)
from flightsite.activity.model import (
    MILESTONE_FIRST_MILITARY,
    ActivityBatch,
    ActivityEventType,
    NewActivityEvent,
    NewMilestone,
    RecordKind,
    Severity,
    crossed_threshold,
    dedupe_key,
    first_type_milestone_key,
    unique_aircraft_milestone_key,
)

#: Milliseconds per second, for the durations payloads report in seconds.
_MS_PER_SECOND = 1000


def _airframe(observation: SightingObservation) -> dict[str, Any]:
    """The identity block every aircraft-scoped payload carries.

    Always the same five keys, present and ``null`` when unknown
    (``docs/API.md`` §2.7), so a client renders one shape rather than probing
    for optional members.
    """
    return {
        "icao": observation.icao24,
        "registration": observation.registration,
        "type_code": observation.type_code,
        "model": observation.model,
        "operator": observation.operator,
    }


def first_ever_events(observations: Iterable[SightingObservation]) -> ActivityBatch:
    """``first_ever_aircraft`` events, plus any unique-airframe milestone.

    Two different things ride the same fact and are deliberately kept apart:
    hearing an airframe for the first time is an *event* about that airframe
    (deduped on its address, so it can never be announced twice however often
    the sighting is re-examined), while being the 1,000th airframe is a
    *milestone* about the receiver (SPEC §54), keyed on the threshold.
    """
    events: list[NewActivityEvent] = []
    milestones: list[NewMilestone] = []
    for observation in observations:
        if not observation.first_ever:
            continue
        events.append(
            NewActivityEvent(
                type=ActivityEventType.FIRST_EVER_AIRCRAFT,
                ts_ms=observation.started_ms,
                dedupe_key=dedupe_key(
                    ActivityEventType.FIRST_EVER_AIRCRAFT.value, observation.icao24
                ),
                aircraft_id=observation.aircraft_id,
                sighting_id=observation.sighting_id,
                payload=_airframe(observation),
            )
        )
        rank = observation.rank
        threshold = None if rank is None else crossed_threshold(rank)
        if threshold is None:
            continue
        key = unique_aircraft_milestone_key(threshold)
        milestones.append(
            NewMilestone(
                key=key,
                achieved_ms=observation.started_ms,
                aircraft_id=observation.aircraft_id,
                value_num=float(threshold),
                payload={
                    "kind": "unique_aircraft",
                    "threshold": threshold,
                    **_airframe(observation),
                },
            )
        )
        events.append(
            NewActivityEvent(
                type=ActivityEventType.MILESTONE,
                ts_ms=observation.started_ms,
                dedupe_key=dedupe_key(ActivityEventType.MILESTONE.value, key),
                severity=Severity.INTERESTING,
                aircraft_id=observation.aircraft_id,
                sighting_id=observation.sighting_id,
                payload={
                    "key": key,
                    "kind": "unique_aircraft",
                    "threshold": threshold,
                    **_airframe(observation),
                },
            )
        )
    return ActivityBatch(events=tuple(events), milestones=tuple(milestones))


def new_type_events(observations: Iterable[SightingObservation]) -> ActivityBatch:
    """``new_type`` events and their ``first_type_*`` milestones (SPEC §54).

    A new type is both — §5 lists ``first_type_B52`` among the milestone keys
    and §3.9 gives the event its own word — so it gets a milestone row *and* an
    event typed ``new_type`` rather than ``milestone``: the specific word wins
    wherever §3.9 supplies one.
    """
    events: list[NewActivityEvent] = []
    milestones: list[NewMilestone] = []
    for observation in observations:
        type_code = observation.type_code
        if not observation.first_of_type or type_code is None:
            continue
        key = first_type_milestone_key(type_code)
        milestones.append(
            NewMilestone(
                key=key,
                achieved_ms=observation.started_ms,
                aircraft_id=observation.aircraft_id,
                payload={"kind": "first_type", "type_code": type_code, **_airframe(observation)},
            )
        )
        events.append(
            NewActivityEvent(
                type=ActivityEventType.NEW_TYPE,
                ts_ms=observation.started_ms,
                dedupe_key=dedupe_key(ActivityEventType.NEW_TYPE.value, type_code),
                severity=Severity.INTERESTING,
                aircraft_id=observation.aircraft_id,
                sighting_id=observation.sighting_id,
                payload={"milestone_key": key, **_airframe(observation)},
            )
        )
    return ActivityBatch(events=tuple(events), milestones=tuple(milestones))


def military_milestone(first: MilitaryFirst | None) -> ActivityBatch:
    """The ``first_military`` milestone and the event announcing it.

    ``first`` is the *earliest* military sighting in the database rather than
    the one a pass happened to look at, because classification lands with a
    metadata import: the first military aircraft a receiver ever heard is
    usually one it heard before it could tell.
    """
    if first is None:
        return ActivityBatch()
    payload: dict[str, Any] = {
        "key": MILESTONE_FIRST_MILITARY,
        "kind": "first_military",
        "icao": first.icao24,
        "registration": first.registration,
        "type_code": first.type_code,
        "model": first.model,
    }
    return ActivityBatch(
        events=(
            NewActivityEvent(
                type=ActivityEventType.MILESTONE,
                ts_ms=first.started_ms,
                dedupe_key=dedupe_key(ActivityEventType.MILESTONE.value, MILESTONE_FIRST_MILITARY),
                severity=Severity.INTERESTING,
                aircraft_id=first.aircraft_id,
                sighting_id=first.sighting_id,
                payload=payload,
            ),
        ),
        milestones=(
            NewMilestone(
                key=MILESTONE_FIRST_MILITARY,
                achieved_ms=first.started_ms,
                aircraft_id=first.aircraft_id,
                payload=payload,
            ),
        ),
    )


def best_closed(
    previous: LongestSighting | None, observations: Iterable[SightingObservation]
) -> LongestSighting | None:
    """The longest-sighting record after ``observations``, ``previous`` included.

    The service advances its in-memory record with this, and
    :func:`longest_sighting_event` decides whether that advance is worth
    announcing. Two callers of one comparison rather than two comparisons that
    have to agree.
    """
    best = previous
    for observation in observations:
        duration_ms, ended_ms = observation.duration_ms, observation.ended_ms
        if duration_ms is None or ended_ms is None:
            continue
        if best is not None and duration_ms <= best.duration_ms:
            continue
        best = LongestSighting(
            sighting_id=observation.sighting_id, duration_ms=duration_ms, ended_ms=ended_ms
        )
    return best


def longest_sighting_event(
    previous: LongestSighting | None, observations: Iterable[SightingObservation]
) -> ActivityBatch:
    """A ``receiver_record`` for a sighting that outlasted every previous one.

    Keyed on the sighting that holds the record, which is what makes it
    idempotent: re-examining that sighting recomputes the same key, and a later
    sighting that beats it gets a different one.

    One event per pass at most, even when several long sightings close
    together: only the best of them is the record, and announcing the
    runners-up would be announcing records that were never held.
    """
    if previous is None:
        return ActivityBatch()
    record = best_closed(previous, observations)
    if record is None or record.sighting_id == previous.sighting_id:
        return ActivityBatch()
    return ActivityBatch(
        events=(
            NewActivityEvent(
                type=ActivityEventType.RECEIVER_RECORD,
                ts_ms=record.ended_ms,
                dedupe_key=dedupe_key(
                    ActivityEventType.RECEIVER_RECORD.value,
                    RecordKind.LONGEST_SIGHTING.value,
                    record.sighting_id,
                ),
                severity=Severity.INTERESTING,
                sighting_id=record.sighting_id,
                payload={
                    "record": RecordKind.LONGEST_SIGHTING.value,
                    "duration_s": record.duration_ms / _MS_PER_SECOND,
                    "previous_s": previous.duration_ms / _MS_PER_SECOND,
                },
            ),
        )
    )


def _improvement(previous: float | None, current: float | None) -> float | None:
    """``current`` when it genuinely beats an existing ``previous``, else ``None``.

    Both halves matter. A missing ``previous`` means no record has been
    observed yet and this observation is the baseline, not an achievement; a
    tie does not displace a standing record, so the record keeps naming the
    first time it was reached.
    """
    if previous is None or current is None or current <= previous:
        return None
    return current


def record_events(
    previous: ReceiverRecords, current: ReceiverRecords, *, now_ms: int
) -> ActivityBatch:
    """Announce every ``lifetime_stats`` record that has just been beaten.

    ``previous`` is the last set of values this service saw, held in memory and
    advanced only after a successful write. It is seeded from the database at
    startup, which is why an install upgrading into this slice announces its
    standing records to nobody: they were already there when the baseline was
    taken.

    ``now_ms`` timestamps only the records ``lifetime_stats`` gives no moment
    for. The furthest detection carries its own ``max_range_at_ms`` and uses
    it, because a range record's interesting fact is when the aircraft was out
    there, not when a background pass noticed.
    """
    events: list[NewActivityEvent] = []

    range_nm = _improvement(previous.max_range_nm, current.max_range_nm)
    if range_nm is not None:
        events.append(
            NewActivityEvent(
                type=ActivityEventType.RANGE_RECORD,
                ts_ms=current.max_range_at_ms if current.max_range_at_ms is not None else now_ms,
                dedupe_key=dedupe_key(ActivityEventType.RANGE_RECORD.value, range_nm),
                severity=Severity.INTERESTING,
                payload={
                    "range_nm": range_nm,
                    "previous_nm": previous.max_range_nm,
                    "bearing_deg": current.max_range_bearing_deg,
                    "icao": current.max_range_icao24,
                },
            )
        )

    simultaneous = _improvement(previous.max_simultaneous, current.max_simultaneous)
    if simultaneous is not None:
        events.append(
            NewActivityEvent(
                type=ActivityEventType.RECEIVER_RECORD,
                ts_ms=now_ms,
                dedupe_key=dedupe_key(
                    ActivityEventType.RECEIVER_RECORD.value,
                    RecordKind.MAX_SIMULTANEOUS.value,
                    int(simultaneous),
                ),
                severity=Severity.INTERESTING,
                payload={
                    "record": RecordKind.MAX_SIMULTANEOUS.value,
                    "value": int(simultaneous),
                    "previous": int(previous.max_simultaneous or 0),
                },
            )
        )

    # The busiest day moves as a pair, and either half changing is a new
    # record: a different day taking the crown, or the standing day's own total
    # being recomputed upwards by a rollup repair.
    count = (
        _improvement(previous.busiest_day_count, current.busiest_day_count)
        if previous.busiest_day is not None and current.busiest_day is not None
        else None
    )
    if count is not None:
        events.append(
            NewActivityEvent(
                type=ActivityEventType.RECEIVER_RECORD,
                ts_ms=now_ms,
                dedupe_key=dedupe_key(
                    ActivityEventType.RECEIVER_RECORD.value,
                    RecordKind.BUSIEST_DAY.value,
                    current.busiest_day,
                    int(count),
                ),
                severity=Severity.INTERESTING,
                payload={
                    "record": RecordKind.BUSIEST_DAY.value,
                    "day": current.busiest_day,
                    "value": int(count),
                    "previous_day": previous.busiest_day,
                    "previous": int(previous.busiest_day_count or 0),
                },
            )
        )

    return ActivityBatch(events=tuple(events))


def health_events(episodes: Iterable[HealthEpisode]) -> ActivityBatch:
    """``receiver_offline`` / ``receiver_restored`` for debounced transitions.

    The debounce itself belongs to the service — it needs a clock — and what
    reaches here is already a transition that held. An outage is ``high``
    severity because it is the one thing in the feed the user can act on; the
    restore that ends it is ``info``, since by the time it is read the problem
    is over.
    """
    events: list[NewActivityEvent] = []
    for episode in episodes:
        offline = episode.offline
        payload: dict[str, Any] = {}
        if offline:
            payload["error"] = episode.error
            if episode.previous_duration_ms is not None:
                payload["uptime_s"] = episode.previous_duration_ms / _MS_PER_SECOND
        elif episode.previous_duration_ms is not None:
            payload["outage_s"] = episode.previous_duration_ms / _MS_PER_SECOND
        events.append(
            NewActivityEvent(
                type=(
                    ActivityEventType.RECEIVER_OFFLINE
                    if offline
                    else ActivityEventType.RECEIVER_RESTORED
                ),
                ts_ms=episode.at_ms,
                dedupe_key=dedupe_key(
                    ActivityEventType.RECEIVER_OFFLINE.value
                    if offline
                    else ActivityEventType.RECEIVER_RESTORED.value,
                    episode.at_ms,
                ),
                severity=Severity.HIGH if offline else Severity.INFO,
                payload=payload,
            )
        )
    return ActivityBatch(events=tuple(events))


def import_events(outcomes: Iterable[ImportOutcome]) -> ActivityBatch:
    """One ``metadata_updated`` event per source of a completed run (SPEC §27).

    Per source, not per run: SPEC §27 is explicit that the user needs to see
    *which* sources worked, and a run in which the registry imported and the
    airport dataset timed out is two different pieces of news. A failure is
    ``interesting`` rather than ``info`` so the feed can lift it, and the
    ``error`` carried is the importer's own short reason — these sources are
    unauthenticated public datasets, so it holds no credential to leak.
    """
    events: list[NewActivityEvent] = []
    for outcome in outcomes:
        events.append(
            NewActivityEvent(
                type=ActivityEventType.METADATA_UPDATED,
                ts_ms=outcome.finished_ms,
                dedupe_key=dedupe_key(
                    ActivityEventType.METADATA_UPDATED.value, outcome.source, outcome.finished_ms
                ),
                severity=Severity.INFO if outcome.ok else Severity.INTERESTING,
                payload={
                    "source": outcome.source,
                    "ok": outcome.ok,
                    "rows_imported": outcome.rows_imported,
                    "rows_rejected": outcome.rows_rejected,
                    "dataset_version": outcome.dataset_version,
                    "error": outcome.error,
                },
            )
        )
    return ActivityBatch(events=tuple(events))


def alert_events(matches: Iterable[AlertMatchFact]) -> ActivityBatch:
    """``alert_triggered`` / ``emergency_squawk`` events for recorded matches.

    Two event types rather than one, because SPEC §55 lists them separately and
    SPEC §47 wants an emergency squawk *prominent* rather than one row among
    the alerts: a feed filtered to ``emergency_squawk`` is a question a user
    genuinely asks, and it cannot be asked of a single ``alert_triggered``
    type with a flag in the payload.

    The dedupe key names the **match**, not the moment: ``alert_triggered:
    {rule_id}:{sighting_id}`` and ``emergency_squawk:{builtin_key}:
    {sighting_id}``. That is the same identity ``alert_matches``'s two partial
    unique indexes enforce, so the feed inherits SPEC §48's
    once-per-sighting-per-rule guarantee rather than restating it — and the
    documented exception inherits with it, since a higher-severity rule and a
    second emergency code are different keys and therefore different events.

    The event's ``severity`` is the match's own, not a fixed one. That is what
    lets the feed and the browser notifications of slice 040 apply SPEC §46's
    ladder to the thing that actually happened: a ``critical`` emergency and an
    ``info`` first-ever sighting are both alerts, and flattening them would
    throw away the only field either layer sorts on.
    """
    events: list[NewActivityEvent] = []
    for match in matches:
        emergency = match.emergency
        event_type = (
            ActivityEventType.EMERGENCY_SQUAWK if emergency else ActivityEventType.ALERT_TRIGGERED
        )
        payload: dict[str, Any] = {
            "icao": match.icao24,
            "callsign": match.callsign,
            "registration": match.registration,
            "type_code": match.type_code,
            "model": match.model,
            "operator": match.operator,
            "reason": match.reason,
            "severity": match.severity,
            "distance_nm": match.distance_nm,
            "altitude_ft": match.altitude_ft,
            "military": match.military,
            "government": match.government,
            "law_enforcement": match.law_enforcement,
        }
        if emergency:
            payload["builtin_key"] = match.builtin_key
            payload["squawk"] = match.squawk
        else:
            payload["rule_id"] = match.rule_id
            payload["rule_name"] = match.rule_name
        events.append(
            NewActivityEvent(
                type=event_type,
                ts_ms=match.matched_ms,
                dedupe_key=dedupe_key(
                    event_type.value,
                    match.builtin_key if emergency else match.rule_id,
                    match.sighting_id,
                ),
                severity=Severity(match.severity),
                aircraft_id=match.aircraft_id,
                sighting_id=match.sighting_id,
                payload=payload,
            )
        )
    return ActivityBatch(events=tuple(events))


def merge(batches: Sequence[ActivityBatch]) -> ActivityBatch:
    """Concatenate batches in order, dropping repeated dedupe keys.

    In-batch de-duplication matters because two producers can legitimately
    reach the same conclusion in one pass — a catch-up scan and the lifecycle
    seam both naming the sighting that just closed, say. The database would
    reject the second insert anyway; collapsing it here means the pass reports
    what it actually wrote.
    """
    events: list[NewActivityEvent] = []
    milestones: list[NewMilestone] = []
    seen_events: set[str] = set()
    seen_milestones: set[str] = set()
    for batch in batches:
        for event in batch.events:
            if event.dedupe_key in seen_events:
                continue
            seen_events.add(event.dedupe_key)
            events.append(event)
        for milestone in batch.milestones:
            if milestone.key in seen_milestones:
                continue
            seen_milestones.add(milestone.key)
            milestones.append(milestone)
    return ActivityBatch(events=tuple(events), milestones=tuple(milestones))


__all__ = [
    "alert_events",
    "best_closed",
    "first_ever_events",
    "health_events",
    "import_events",
    "longest_sighting_event",
    "merge",
    "military_milestone",
    "new_type_events",
    "record_events",
]
