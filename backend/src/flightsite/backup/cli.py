"""``flightsite-backup`` — the backup, restore, and verify commands.

Run inside the container, where the data directory is mounted::

    docker compose exec backend flightsite-backup create
    docker compose exec backend flightsite-backup verify \\
        /opt/flightsite/data/backups/flightsite-backup-20260901T120000Z.tar.gz
    docker compose exec backend flightsite-backup restore \\
        /opt/flightsite/data/backups/flightsite-backup-20260901T120000Z.tar.gz --confirm

Exit codes are stable enough to script against:

======= ================================================================
``0``   the command succeeded
``1``   the command refused: damaged archive, incompatible schema, no
        database to back up, failed swap
``2``   the invocation was wrong, including a ``restore`` without
        ``--confirm``
======= ================================================================

The data directory resolves the same way it does for the application
(:func:`flightsite.config.paths.resolve_data_dir`): ``--data-dir``, else
``FLIGHTSITE_DATA_DIR``, else ``/opt/flightsite/data``. That is what makes the
in-container invocation above need no arguments at all.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from flightsite.backup.create import create_backup
from flightsite.backup.errors import BackupError, ConfirmationRequiredError
from flightsite.backup.restore import OPERATIONAL_RULE, restore_backup
from flightsite.backup.verify import verify_archive
from flightsite.config.paths import resolve_data_dir

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2

PROGRAM = "flightsite-backup"


def build_arg_parser() -> argparse.ArgumentParser:
    """The ``flightsite-backup`` argument parser."""
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="Back up, verify, and restore a FlightSite data directory.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    create = subcommands.add_parser(
        "create", help="write a checksum-validated backup archive", description="Take a backup."
    )
    _add_data_dir(create)
    create.add_argument(
        "--include-secrets",
        action="store_true",
        help=(
            "also archive secrets.yaml. Off by default: the archive is then as "
            "sensitive as the secrets file itself"
        ),
    )
    create.add_argument(
        "--out",
        metavar="DIR",
        help="destination directory (default: <data-dir>/backups)",
    )

    restore = subcommands.add_parser(
        "restore",
        help="replace a data directory's contents with an archive",
        description="Restore a backup. Destructive; stop FlightSite first.",
    )
    restore.add_argument("archive", help="path to a flightsite-backup-*.tar.gz")
    _add_data_dir(restore)
    restore.add_argument(
        "--confirm",
        action="store_true",
        help="required: acknowledge that this overwrites the data directory",
    )

    verify = subcommands.add_parser(
        "verify",
        help="check an archive's checksums, manifest, and schema compatibility",
        description="Validate a backup without modifying anything.",
    )
    verify.add_argument("archive", help="path to a flightsite-backup-*.tar.gz")

    return parser


def _add_data_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data-dir",
        metavar="DIR",
        help="FlightSite data directory (default: $FLIGHTSITE_DATA_DIR or /opt/flightsite/data)",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``flightsite-backup`` console script."""
    args = build_arg_parser().parse_args(argv)

    try:
        if args.command == "create":
            return _create(args)
        if args.command == "restore":
            return _restore(args)
        return _verify(args)
    except ConfirmationRequiredError as exc:
        print(f"{PROGRAM}: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except BackupError as exc:
        print(f"{PROGRAM}: {exc}", file=sys.stderr)
        return EXIT_REFUSED


def _create(args: argparse.Namespace) -> int:
    result = create_backup(
        resolve_data_dir(args.data_dir),
        include_secrets=args.include_secrets,
        out_dir=Path(args.out) if args.out else None,
    )
    print(result.render())
    if args.include_secrets and not result.manifest.includes_secrets:
        print(
            "note: --include-secrets was given but no secrets.yaml exists; "
            "the manifest records includes_secrets=false",
            file=sys.stderr,
        )
    return EXIT_OK


def _restore(args: argparse.Namespace) -> int:
    if not args.confirm:
        raise ConfirmationRequiredError(
            "restore replaces the database and configuration in the data directory. "
            f"{OPERATIONAL_RULE} Then re-run with --confirm."
        )
    result = restore_backup(Path(args.archive), resolve_data_dir(args.data_dir), confirm=True)
    print(result.render())
    return EXIT_OK


def _verify(args: argparse.Namespace) -> int:
    report = verify_archive(Path(args.archive))
    print(report.render())
    return EXIT_OK if report.ok else EXIT_REFUSED


__all__ = ["EXIT_OK", "EXIT_REFUSED", "EXIT_USAGE", "PROGRAM", "build_arg_parser", "main"]
