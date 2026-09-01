"""``flightsite-backup verify``: checksums, manifest, schema report, no side effects."""

from __future__ import annotations

import tarfile
from pathlib import Path

from flightsite.backup import (
    CONFIG_MEMBER,
    DATABASE_MEMBER,
    SchemaRelation,
    create_backup,
    verify_archive,
)
from flightsite.config import ConfigStore
from flightsite.db import migrate
from tests.backup.conftest import (
    FIXED_NOW,
    BytesReader,
    fixed_clock,
    flip_byte,
    read_members,
    repack,
    tree_mtimes,
    write_members,
)


async def test_a_fresh_backup_verifies_clean(
    data_dir: Path, populated_db: Path, config_files: ConfigStore
) -> None:
    archive = create_backup(data_dir, now=fixed_clock()).path

    report = verify_archive(archive)

    assert report.ok
    assert report.problems == ()
    assert {check.name for check in report.checks} == {DATABASE_MEMBER, CONFIG_MEMBER}
    assert all(check.ok for check in report.checks)
    assert report.compatibility is not None
    assert report.compatibility.relation is SchemaRelation.SAME


async def test_verify_reports_versions_checksums_and_compatibility(
    data_dir: Path, populated_db: Path
) -> None:
    archive = create_backup(data_dir, now=fixed_clock()).path

    rendered = verify_archive(archive).render()

    assert str(archive) in rendered
    assert "created (UTC):      2026-09-01T12:00:00Z" in rendered
    assert f"schema revision:    {migrate.head_revision()}" in rendered
    assert "includes secrets:   no" in rendered
    assert "- opensky: version=2026-08-01" in rendered
    assert f"- {DATABASE_MEMBER}: OK" in rendered
    assert "RESULT: restorable" in rendered


async def test_verify_notes_when_no_metadata_sources_are_recorded(
    data_dir: Path, populated_db: Path, tmp_path: Path
) -> None:
    archive = create_backup(data_dir, now=fixed_clock()).path
    stripped = repack(
        archive,
        tmp_path / "stripped.tar.gz",
        mutate_manifest=lambda manifest: manifest.__setitem__("metadata_sources", []),
    )

    assert "metadata sources:   (none recorded)" in verify_archive(stripped).render()


async def test_verify_does_not_modify_anything(data_dir: Path, populated_db: Path) -> None:
    archive = create_backup(data_dir, now=fixed_clock()).path
    before = tree_mtimes(data_dir)

    verify_archive(archive)

    assert tree_mtimes(data_dir) == before


async def test_a_flipped_byte_fails_the_checksum(
    data_dir: Path, populated_db: Path, tmp_path: Path
) -> None:
    archive = create_backup(data_dir, now=fixed_clock()).path

    def corrupt(members: dict[str, bytes]) -> None:
        members[DATABASE_MEMBER] = flip_byte(members[DATABASE_MEMBER], 5000)

    damaged = repack(archive, tmp_path / "damaged.tar.gz", mutate=corrupt)
    report = verify_archive(damaged)

    assert not report.ok
    assert any("checksum mismatch" in problem for problem in report.problems)
    assert "RESULT: NOT RESTORABLE" in report.render()
    assert f"- {DATABASE_MEMBER}: FAILED" in report.render()


async def test_a_truncated_member_fails_on_size(
    data_dir: Path, populated_db: Path, tmp_path: Path
) -> None:
    archive = create_backup(data_dir, now=fixed_clock()).path

    def truncate(members: dict[str, bytes]) -> None:
        members[DATABASE_MEMBER] = members[DATABASE_MEMBER][:-64]

    damaged = repack(archive, tmp_path / "short.tar.gz", mutate=truncate)
    report = verify_archive(damaged)

    assert any("size mismatch" in problem for problem in report.problems)


async def test_a_missing_member_is_reported(
    data_dir: Path, populated_db: Path, tmp_path: Path
) -> None:
    archive = create_backup(data_dir, now=fixed_clock()).path

    def drop(members: dict[str, bytes]) -> None:
        del members[DATABASE_MEMBER]

    damaged = repack(archive, tmp_path / "missing.tar.gz", mutate=drop)
    report = verify_archive(damaged)

    assert any("does not contain" in problem for problem in report.problems)
    # The missing member is reported once, not also as a checksum failure.
    assert report.checks == ()


async def test_an_unlisted_extra_member_is_reported(
    data_dir: Path, populated_db: Path, tmp_path: Path
) -> None:
    archive = create_backup(data_dir, now=fixed_clock()).path

    def smuggle(members: dict[str, bytes]) -> None:
        members["../evil.sh"] = b"rm -rf /\n"

    damaged = repack(archive, tmp_path / "extra.tar.gz", mutate=smuggle)
    report = verify_archive(damaged)

    assert any("the manifest does not list" in problem for problem in report.problems)
    assert any("may contain" in problem for problem in report.problems)


async def test_a_non_regular_member_is_reported(
    data_dir: Path, populated_db: Path, tmp_path: Path
) -> None:
    archive = create_backup(data_dir, now=fixed_clock()).path
    members = read_members(archive)

    hostile = tmp_path / "symlink.tar.gz"
    with tarfile.open(hostile, "w:gz") as handle:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mtime = int(FIXED_NOW.timestamp())
            handle.addfile(info, BytesReader(payload))
        link = tarfile.TarInfo(CONFIG_MEMBER + ".link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        handle.addfile(link)

    report = verify_archive(hostile)

    assert any("is not a regular file" in problem for problem in report.problems)


async def test_a_manifest_free_archive_is_refused(tmp_path: Path) -> None:
    archive = write_members(tmp_path / "no-manifest.tar.gz", {DATABASE_MEMBER: b"nope"})

    report = verify_archive(archive)

    assert not report.ok
    assert any("missing member 'manifest.json'" in problem for problem in report.problems)
    assert report.manifest is None


async def test_a_file_that_is_not_an_archive_is_refused(tmp_path: Path) -> None:
    plain = tmp_path / "notes.txt"
    plain.write_text("this is not a backup", encoding="utf-8")

    report = verify_archive(plain)

    assert any("not a readable FlightSite backup archive" in p for p in report.problems)
    assert "RESULT: NOT RESTORABLE" in report.render()


async def test_a_missing_archive_is_refused(tmp_path: Path) -> None:
    report = verify_archive(tmp_path / "absent.tar.gz")

    assert any("no such archive" in problem for problem in report.problems)


async def test_a_corrupt_gzip_stream_is_refused(
    data_dir: Path, populated_db: Path, tmp_path: Path
) -> None:
    archive = create_backup(data_dir, now=fixed_clock()).path
    mangled = tmp_path / "mangled.tar.gz"
    payload = bytearray(archive.read_bytes())
    payload[len(payload) // 2] ^= 0xFF
    mangled.write_bytes(bytes(payload))

    report = verify_archive(mangled)

    assert not report.ok
