"""Reading and writing the backup container (a ``tar.gz``).

The container is deliberately boring: a gzip-compressed tar holding a flat set
of members whose names come from a fixed allowlist
(:data:`~flightsite.backup.manifest.ALLOWED_MEMBERS`). Restore looks members up
**by name** and writes them to paths it computes itself — ``extractall`` is
never called, and any member that is not a plain file with an allowlisted name
is a validation failure rather than something to skip. That makes the classic
tar path-traversal and symlink attacks structurally impossible instead of
merely guarded against.

Everything here streams in fixed-size chunks: on a Pi the database can be
several gigabytes and neither backup nor restore may hold it in memory.
"""

from __future__ import annotations

import hashlib
import os
import tarfile
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from flightsite.backup.errors import ArchiveValidationError

#: Streaming chunk size for hashing and extraction.
CHUNK_BYTES = 1024 * 1024

#: gzip level for the container, chosen against measurement rather than taken
#: from tarfile's default of 9. On a 419 MB slab of a real database
#: (``docs/PERFORMANCE.md`` §7.7) level 6 and level 9 both compress to a ratio
#: of 0.188, but level 6 runs at 41.0 MB/s against level 9's 15.2 MB/s — 2.7x
#: faster for an identical archive size, because SQLite pages of packed integer
#: blobs give deflate nothing more to find above 6. Backup is gzip-dominated
#: (about 330 s of a 406.9 s backup of a 5.03 GB database), so this is worth
#: roughly 200 s per 5 GB and costs nothing measurable in size. Level 1 would
#: save a further ~290 s but widens the ratio to 0.197.
COMPRESS_LEVEL = 6

#: Everything a damaged container can raise on the way out of tarfile/gzip.
#: ``zlib.error`` is not an ``OSError``, so it has to be named explicitly —
#: without it a flipped byte inside the deflate stream would escape as an
#: unhandled exception instead of a "this archive is corrupt" refusal.
CONTAINER_ERRORS = (tarfile.TarError, OSError, EOFError, zlib.error)


@dataclass(frozen=True, slots=True)
class Digest:
    """A file's SHA-256 and byte length."""

    sha256: str
    size_bytes: int


def digest_file(path: Path) -> Digest:
    """Hash a file on disk without reading it all into memory."""
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            hasher.update(chunk)
            size += len(chunk)
    return Digest(hasher.hexdigest(), size)


def _open_tar(path: Path) -> tarfile.TarFile:
    try:
        return tarfile.open(path, "r:gz")
    except CONTAINER_ERRORS as exc:
        raise ArchiveValidationError(
            f"{path} is not a readable FlightSite backup archive (expected gzip tar): {exc}"
        ) from exc


@contextmanager
def open_archive(path: Path) -> Iterator[tarfile.TarFile]:
    """Open a backup archive for reading.

    Raises:
        ArchiveValidationError: if the file is missing, not gzip, or not a tar.
    """
    if not path.exists():
        raise ArchiveValidationError(f"no such archive: {path}")
    with _open_tar(path) as handle:
        yield handle


def member_names(archive: tarfile.TarFile) -> tuple[str, ...]:
    """Names of every entry in the archive, in stored order."""
    try:
        return tuple(info.name for info in archive.getmembers())
    except CONTAINER_ERRORS as exc:
        raise ArchiveValidationError(f"archive index is unreadable: {exc}") from exc


def irregular_members(archive: tarfile.TarFile) -> tuple[str, ...]:
    """Names of entries that are not plain files (links, devices, directories)."""
    try:
        return tuple(info.name for info in archive.getmembers() if not info.isfile())
    except CONTAINER_ERRORS as exc:  # pragma: no cover - getmembers already ran above
        raise ArchiveValidationError(f"archive index is unreadable: {exc}") from exc


def read_member(archive: tarfile.TarFile, name: str) -> bytes:
    """Read a small member (the manifest) fully into memory."""
    stream = _member_stream(archive, name)
    try:
        return stream.read()
    except CONTAINER_ERRORS as exc:
        raise ArchiveValidationError(f"member {name!r} could not be read: {exc}") from exc
    finally:
        stream.close()


def copy_member(archive: tarfile.TarFile, name: str, destination: Path | None) -> Digest:
    """Stream a member out, hashing it, optionally writing it to ``destination``.

    Passing ``destination=None`` verifies without extracting — that is what
    ``flightsite-backup verify`` does, and why it can never modify anything.
    """
    hasher = hashlib.sha256()
    size = 0
    stream = _member_stream(archive, name)
    try:
        if destination is None:
            while chunk := stream.read(CHUNK_BYTES):
                hasher.update(chunk)
                size += len(chunk)
        else:
            with destination.open("wb") as handle:
                while chunk := stream.read(CHUNK_BYTES):
                    hasher.update(chunk)
                    size += len(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
    except CONTAINER_ERRORS as exc:
        raise ArchiveValidationError(f"member {name!r} could not be read: {exc}") from exc
    finally:
        stream.close()
    return Digest(hasher.hexdigest(), size)


def _member_stream(archive: tarfile.TarFile, name: str) -> IO[bytes]:
    try:
        info = archive.getmember(name)
    except KeyError as exc:
        raise ArchiveValidationError(f"archive is missing member {name!r}") from exc
    if not info.isfile():
        raise ArchiveValidationError(f"archive member {name!r} is not a regular file")
    stream = archive.extractfile(info)
    if stream is None:  # pragma: no cover - isfile() already guarantees a stream
        raise ArchiveValidationError(f"archive member {name!r} has no readable content")
    return stream


def write_archive(destination: Path, sources: dict[str, Path], *, mtime: int) -> None:
    """Write ``sources`` (member name -> file on disk) as a gzip tar.

    Ownership and timestamps are normalized so two backups of identical bytes
    differ only by their creation time, and so an archive never carries the
    uid/gid of whoever happened to run the command.

    Compressed at :data:`COMPRESS_LEVEL` rather than tarfile's default; see the
    constant for why.
    """

    def normalize(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid = 0
        info.gid = 0
        info.uname = ""
        info.gname = ""
        info.mtime = mtime
        info.mode = 0o600
        return info

    with tarfile.open(destination, "w:gz", compresslevel=COMPRESS_LEVEL) as archive:
        for name, path in sources.items():
            archive.add(path, arcname=name, filter=normalize)


__all__ = [
    "CHUNK_BYTES",
    "CONTAINER_ERRORS",
    "Digest",
    "copy_member",
    "digest_file",
    "irregular_members",
    "member_names",
    "open_archive",
    "read_member",
    "write_archive",
]
