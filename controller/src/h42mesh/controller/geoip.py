"""Operator (ISP) of a public address, from the MaxMind GeoLite2 ASN database.

This product includes GeoLite2 data created by MaxMind, available from
https://www.maxmind.com. The database is not distributed with the project:
its path is given by H42_MESH_GEOLITE2_ASN_FILE; without it, ``isp`` stays empty.
"""

import logging
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import maxminddb

logger = logging.getLogger(__name__)


class AsnReader(Protocol):
    def get(self, ip_address: str) -> object: ...


@lru_cache(maxsize=2)
def open_reader(path: Path, mtime_ns: int) -> AsnReader | None:
    """Opened once per version of the file (geoipupdate replaces it twice a week).

    None (logged) if the file cannot be read.
    """
    try:
        reader: AsnReader = maxminddb.open_database(str(path))
    except (OSError, ValueError, maxminddb.InvalidDatabaseError) as exc:
        logger.warning("GeoLite2 ASN database %s unusable: %s", path, exc)
        return None
    return reader


def isp_for(address: str, path: Path | None) -> str | None:
    """Organisation of the AS announcing ``address``, or None if unknown."""
    if path is None:
        return None
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:  # not downloaded yet: tried again at the next call
        return None
    reader = open_reader(path, mtime_ns)
    if reader is None:
        return None
    try:
        record = reader.get(address)
    except ValueError:
        return None
    if not isinstance(record, dict):
        return None
    organisation = record.get("autonomous_system_organization")
    return str(organisation)[:128] if organisation else None
