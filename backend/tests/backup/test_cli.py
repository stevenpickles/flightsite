"""``flightsite-backup``: argument handling, output, and exit codes."""

from __future__ import annotations

from pathlib import Path

import pytest

from flightsite.backup import DATABASE_MEMBER, SECRETS_MEMBER, default_backup_dir
from flightsite.backup.cli import EXIT_OK, EXIT_REFUSED, EXIT_USAGE, build_arg_parser, main
from flightsite.config import ConfigStore
from flightsite.config.paths import DATA_DIR_ENV_VAR
from tests.backup.conftest import (
    file_bytes,
    flip_byte,
    make_backup,
    read_members,
    repack,
    sqlite_scalar,
    write_sightings,
)
from tests.conftest import SECRET_SENTINEL


def only_archive(data_dir: Path) -> Path:
    """The single archive in the data directory's backups folder."""
    archives = sorted(default_backup_dir(data_dir).glob("*.tar.gz"))
    assert len(archives) == 1
    return archives[0]


async def test_create_writes_an_archive_and_reports_it(
    data_dir: Path, populated_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["create"]) == EXIT_OK

    archive = only_archive(data_dir)
    out = capsys.readouterr().out
    assert str(archive) in out
    assert "includes secrets:   no" in out


async def test_create_resolves_the_data_dir_from_the_environment(
    data_dir: Path, populated_db: Path
) -> None:
    """No arguments needed inside the container, where the env var is set."""
    import os

    assert os.environ[DATA_DIR_ENV_VAR] == str(data_dir)

    assert main(["create"]) == EXIT_OK
    assert only_archive(data_dir).exists()


async def test_create_accepts_an_explicit_data_dir_and_out_dir(
    data_dir: Path, populated_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(DATA_DIR_ENV_VAR)
    destination = tmp_path / "external-drive"

    assert main(["create", "--data-dir", str(data_dir), "--out", str(destination)]) == EXIT_OK

    assert len(list(destination.glob("*.tar.gz"))) == 1


async def test_create_include_secrets_puts_them_in_the_archive(
    data_dir: Path, populated_db: Path, config_files: ConfigStore
) -> None:
    assert main(["create", "--include-secrets"]) == EXIT_OK

    members = read_members(only_archive(data_dir))
    assert SECRET_SENTINEL.encode() in members[SECRETS_MEMBER]


async def test_create_warns_when_there_are_no_secrets_to_include(
    data_dir: Path, populated_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["create", "--include-secrets"]) == EXIT_OK

    captured = capsys.readouterr()
    assert "includes_secrets=false" in captured.err
    assert "includes secrets:   no" in captured.out


async def test_create_without_a_database_is_refused(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["create"]) == EXIT_REFUSED
    assert "no FlightSite database" in capsys.readouterr().err


async def test_verify_prints_a_report_and_exits_zero(
    data_dir: Path, populated_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = make_backup(data_dir)

    assert main(["verify", str(archive)]) == EXIT_OK

    out = capsys.readouterr().out
    assert "RESULT: restorable" in out
    assert f"- {DATABASE_MEMBER}: OK" in out


async def test_verify_of_a_corrupted_archive_exits_nonzero(
    data_dir: Path, populated_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = make_backup(data_dir)
    damaged = repack(
        archive,
        tmp_path / "damaged.tar.gz",
        mutate=lambda members: members.__setitem__(
            DATABASE_MEMBER, flip_byte(members[DATABASE_MEMBER], 3000)
        ),
    )

    assert main(["verify", str(damaged)]) == EXIT_REFUSED

    out = capsys.readouterr().out
    assert "RESULT: NOT RESTORABLE" in out
    assert "checksum mismatch" in out


async def test_restore_without_confirm_is_a_usage_error(
    data_dir: Path, populated_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = make_backup(data_dir)
    before = file_bytes(populated_db)

    assert main(["restore", str(archive)]) == EXIT_USAGE

    err = capsys.readouterr().err
    assert "--confirm" in err
    assert "Stop FlightSite before restoring" in err
    assert file_bytes(populated_db) == before


async def test_restore_with_confirm_replaces_the_database(
    data_dir: Path, populated_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = make_backup(data_dir)

    from flightsite.db import Database

    database = Database(populated_db)
    try:
        await write_sightings(database, count=2, start=900)
    finally:
        await database.dispose()
    assert sqlite_scalar(populated_db, "SELECT COUNT(*) FROM sightings") == 7

    assert main(["restore", str(archive), "--confirm"]) == EXIT_OK

    assert sqlite_scalar(populated_db, "SELECT COUNT(*) FROM sightings") == 5
    assert "start FlightSite" in capsys.readouterr().out


async def test_restore_of_a_damaged_archive_exits_refused(
    data_dir: Path, populated_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = make_backup(data_dir)
    damaged = repack(
        archive,
        tmp_path / "damaged.tar.gz",
        mutate=lambda members: members.__setitem__(
            DATABASE_MEMBER, flip_byte(members[DATABASE_MEMBER], 3000)
        ),
    )

    assert main(["restore", str(damaged), "--confirm"]) == EXIT_REFUSED
    assert "checksum mismatch" in capsys.readouterr().err


async def test_restore_of_a_newer_schema_archive_exits_refused(
    data_dir: Path, populated_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = make_backup(data_dir)
    future = repack(
        archive,
        tmp_path / "future.tar.gz",
        mutate_manifest=lambda manifest: manifest.__setitem__("schema_revision", "8888"),
    )

    assert main(["restore", str(future), "--confirm"]) == EXIT_REFUSED
    assert "Upgrade FlightSite" in capsys.readouterr().err


def test_a_missing_subcommand_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main([])

    assert exit_info.value.code == EXIT_USAGE


def test_the_parser_documents_every_subcommand() -> None:
    help_text = build_arg_parser().format_help()

    assert "create" in help_text
    assert "restore" in help_text
    assert "verify" in help_text
