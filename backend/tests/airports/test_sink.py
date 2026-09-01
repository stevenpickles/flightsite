"""The airport import sink: buffer, canonicalize, replace.

The sink is the piece that lets the airport dataset ride the aircraft-metadata
import pipeline. Its contract is
:class:`~flightsite.metadata.sink.ImportSink`, and the two halves of it that
matter are tested here directly:

* **The boundary.** ``canonical`` is where a provider's record is re-normalized
  rather than trusted, so a lower-case or padded ident cannot reach the table.
* **The buffer.** Nothing it holds is visible to anything else until
  ``promote``, and a run that fails leaves neither rows nor a fragment behind.

The whole pipeline over the sink is exercised in ``test_import.py``; this module
is the unit-level view of the same object.
"""

from __future__ import annotations

import pytest

from flightsite.airports import AirportImportSink, AirportRepository
from flightsite.airports.records import AirportRecord
from flightsite.metadata.sink import ImportSink
from tests.airports.conftest import BASE_EPOCH_MS, airport

SOURCE = "airports"


@pytest.fixture
def sink(repository: AirportRepository) -> AirportImportSink:
    return AirportImportSink(repository)


def test_the_sink_satisfies_the_pipeline_protocol(sink: AirportImportSink) -> None:
    """Caught here rather than halfway through an import run."""
    assert isinstance(sink, ImportSink)


# ----------------------------------------------------------- the boundary


def test_canonical_normalizes_rather_than_trusting(sink: AirportImportSink) -> None:
    """A padded, lower-case ident would make one airport two in the index."""
    found = sink.canonical(
        AirportRecord(
            ident=" ksea ", name="  Sea-Tac ", type="large_airport", lat=47.45, lon=-122.3
        )
    )

    assert found is not None
    assert found.ident == "KSEA"
    assert found.name == "Sea-Tac"


def test_canonical_refuses_a_record_it_cannot_store(sink: AirportImportSink) -> None:
    """Counted as rejected by the pipeline, which enforces a ratio on them."""
    broken = AirportRecord(ident="", name="Nameless", type="small_airport", lat=0.0, lon=0.0)

    assert sink.canonical(broken) is None


def test_canonical_refuses_an_object_that_is_not_a_record(sink: AirportImportSink) -> None:
    """A provider that yielded the wrong type fails one row, not the process."""
    assert sink.canonical(object()) is None
    assert sink.canonical(None) is None


# -------------------------------------------------------------- the buffer


async def test_staging_is_invisible_until_promotion(
    sink: AirportImportSink, repository: AirportRepository
) -> None:
    """Nothing before ``promote`` writes a byte the rest of FlightSite can see."""
    await sink.clear_staging(SOURCE)
    await sink.stage_batch(SOURCE, [airport("KAAA", 10.0, 10.0)], updated_ms=BASE_EPOCH_MS)

    assert await sink.count_staged(SOURCE) == 1
    assert await repository.count() == 0


async def test_promotion_writes_what_was_staged(
    sink: AirportImportSink, repository: AirportRepository
) -> None:
    await sink.stage_batch(
        SOURCE,
        [airport("KAAA", 10.0, 10.0), airport("KBBB", 11.0, 11.0)],
        updated_ms=BASE_EPOCH_MS,
    )

    await sink.promote(SOURCE, at_ms=BASE_EPOCH_MS, dataset_version="v1", row_count=2)

    loaded = await repository.load_all()
    assert [record.ident for record in loaded] == ["KAAA", "KBBB"]


async def test_promotion_empties_the_buffer(
    sink: AirportImportSink, repository: AirportRepository
) -> None:
    """So a second run starts from nothing rather than from the first run's rows."""
    await sink.stage_batch(SOURCE, [airport("KAAA", 10.0, 10.0)], updated_ms=BASE_EPOCH_MS)
    await sink.promote(SOURCE, at_ms=BASE_EPOCH_MS, dataset_version="v1", row_count=1)

    assert await sink.count_staged(SOURCE) == 0


async def test_several_batches_accumulate(sink: AirportImportSink) -> None:
    """The pipeline streams a transform in batches; the buffer is the whole run."""
    for index in range(3):
        await sink.stage_batch(
            SOURCE, [airport(f"K{index:03d}", 10.0, 10.0)], updated_ms=BASE_EPOCH_MS
        )

    assert await sink.count_staged(SOURCE) == 3


async def test_a_repeated_ident_within_a_run_collapses(sink: AirportImportSink) -> None:
    """The promotion's ``UNIQUE`` constraint, honoured before it can fail."""
    await sink.stage_batch(
        SOURCE,
        [airport("DUPE", 10.0, 10.0, name="First"), airport("DUPE", 11.0, 11.0, name="Second")],
        updated_ms=BASE_EPOCH_MS,
    )

    assert await sink.count_staged(SOURCE) == 1


async def test_an_empty_batch_stages_nothing(sink: AirportImportSink) -> None:
    assert await sink.stage_batch(SOURCE, [], updated_ms=BASE_EPOCH_MS) == 0
    assert await sink.count_staged(SOURCE) == 0


async def test_clearing_discards_what_a_failed_run_left(sink: AirportImportSink) -> None:
    """A run that died partway cannot contribute a fragment to the next."""
    await sink.stage_batch(SOURCE, [airport("KAAA", 10.0, 10.0)], updated_ms=BASE_EPOCH_MS)

    await sink.clear_staging(SOURCE)

    assert await sink.count_staged(SOURCE) == 0


async def test_clearing_a_source_that_staged_nothing_is_harmless(
    sink: AirportImportSink,
) -> None:
    """Called before every run, including the first one this process makes."""
    await sink.clear_staging(SOURCE)

    assert await sink.count_staged(SOURCE) == 0


async def test_sources_do_not_see_each_other_s_buffers(sink: AirportImportSink) -> None:
    """One sink instance serves every source that shares a destination."""
    await sink.stage_batch(SOURCE, [airport("KAAA", 10.0, 10.0)], updated_ms=BASE_EPOCH_MS)
    await sink.stage_batch(
        "other", [airport("KBBB", 11.0, 11.0), airport("KCCC", 12.0, 12.0)], updated_ms=1
    )

    assert await sink.count_staged(SOURCE) == 1
    assert await sink.count_staged("other") == 2

    await sink.clear_staging("other")
    assert await sink.count_staged(SOURCE) == 1


async def test_promoting_nothing_is_refused(sink: AirportImportSink) -> None:
    """The pipeline's own row floor precedes this; it is belt as well as braces."""
    with pytest.raises(ValueError):
        await sink.promote(SOURCE, at_ms=BASE_EPOCH_MS, dataset_version="v1", row_count=0)
