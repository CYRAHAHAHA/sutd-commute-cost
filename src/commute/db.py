from __future__ import annotations

import csv
import sqlite3
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from .models import Address, Observation

ADDRESS_SCHEMA = """
CREATE TABLE IF NOT EXISTS residential_address (
    postal_code TEXT PRIMARY KEY,
    address TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    residential_type TEXT NOT NULL,
    source TEXT NOT NULL,
    source_identifier TEXT NOT NULL,
    confidence TEXT NOT NULL CHECK (confidence IN ('VERIFIED', 'LIKELY', 'UNRESOLVED', 'EXCLUDED')),
    discovered_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_residential_confidence ON residential_address(confidence);
"""

OBSERVATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS commute_observation (
    id INTEGER PRIMARY KEY,
    postal_code TEXT NOT NULL,
    provider TEXT NOT NULL,
    service_date TEXT NOT NULL,
    query_time TEXT NOT NULL,
    time_semantics TEXT NOT NULL,
    origin_lat REAL NOT NULL,
    origin_lng REAL NOT NULL,
    destination_lat REAL NOT NULL,
    destination_lng REAL NOT NULL,
    duration_seconds INTEGER,
    status TEXT NOT NULL CHECK (status IN ('SUCCESS', 'FAILED')),
    error_code TEXT,
    error_message TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    collected_at TEXT,
    collector_version TEXT NOT NULL,
    UNIQUE (postal_code, provider, service_date, query_time)
);
CREATE INDEX IF NOT EXISTS idx_observation_lookup
  ON commute_observation(postal_code, provider, service_date, query_time);
CREATE INDEX IF NOT EXISTS idx_observation_status ON commute_observation(provider, status);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_addresses_db(path: str | Path) -> sqlite3.Connection:
    connection = connect(path)
    connection.executescript(ADDRESS_SCHEMA)
    connection.commit()
    return connection


def init_observations_db(path: str | Path) -> sqlite3.Connection:
    connection = connect(path)
    connection.executescript(OBSERVATION_SCHEMA)
    connection.commit()
    return connection


def upsert_address(connection: sqlite3.Connection, address: Address, discovered_at: str) -> None:
    connection.execute(
        """
        INSERT INTO residential_address
          (postal_code, address, latitude, longitude, residential_type, source,
           source_identifier, confidence, discovered_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(postal_code) DO UPDATE SET
          address=excluded.address, latitude=excluded.latitude, longitude=excluded.longitude,
          residential_type=excluded.residential_type, source=excluded.source,
          source_identifier=excluded.source_identifier, confidence=excluded.confidence,
          discovered_at=excluded.discovered_at
        """,
        (
            address.postal_code,
            address.address,
            address.latitude,
            address.longitude,
            address.residential_type,
            address.source,
            address.source_identifier,
            address.confidence,
            discovered_at,
        ),
    )


def iter_addresses(
    connection: sqlite3.Connection,
    include_confidence: Iterable[str] = ("VERIFIED", "LIKELY"),
    limit: int | None = None,
    postal_code: str | None = None,
) -> Iterator[sqlite3.Row]:
    allowed = tuple(include_confidence)
    if not allowed:
        return
    placeholders = ",".join("?" for _ in allowed)
    query = f"SELECT * FROM residential_address WHERE confidence IN ({placeholders})"
    params: list[Any] = list(allowed)
    if postal_code:
        query += " AND postal_code = ?"
        params.append(postal_code)
    query += " ORDER BY postal_code"
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    yield from connection.execute(query, params)


def count_addresses(connection: sqlite3.Connection, include_confidence: Iterable[str]) -> int:
    allowed = tuple(include_confidence)
    if not allowed:
        return 0
    placeholders = ",".join("?" for _ in allowed)
    return int(
        connection.execute(
            f"SELECT COUNT(*) FROM residential_address WHERE confidence IN ({placeholders})", allowed
        ).fetchone()[0]
    )


def get_observation(
    connection: sqlite3.Connection, postal_code: str, provider: str, service_date: str, query_time: str
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT * FROM commute_observation
        WHERE postal_code=? AND provider=? AND service_date=? AND query_time=?
        """,
        (postal_code, provider, service_date, query_time),
    ).fetchone()


def save_observation(connection: sqlite3.Connection, observation: Observation) -> bool:
    """Persist an observation, never overwriting a prior SUCCESS with a failure."""
    existing = get_observation(
        connection,
        observation.postal_code,
        observation.provider,
        observation.service_date,
        observation.query_time,
    )
    if existing and existing["status"] == "SUCCESS" and observation.status != "SUCCESS":
        return False
    connection.execute(
        """
        INSERT INTO commute_observation
          (postal_code, provider, service_date, query_time, time_semantics,
           origin_lat, origin_lng, destination_lat, destination_lng, duration_seconds,
           status, error_code, error_message, attempt_count, collected_at, collector_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(postal_code, provider, service_date, query_time) DO UPDATE SET
          time_semantics=excluded.time_semantics, origin_lat=excluded.origin_lat,
          origin_lng=excluded.origin_lng, destination_lat=excluded.destination_lat,
          destination_lng=excluded.destination_lng, duration_seconds=excluded.duration_seconds,
          status=excluded.status, error_code=excluded.error_code,
          error_message=excluded.error_message, attempt_count=excluded.attempt_count,
          collected_at=excluded.collected_at, collector_version=excluded.collector_version
        """,
        (
            observation.postal_code,
            observation.provider,
            observation.service_date,
            observation.query_time,
            observation.time_semantics,
            observation.origin_lat,
            observation.origin_lng,
            observation.destination_lat,
            observation.destination_lng,
            observation.duration_seconds,
            observation.status,
            observation.error_code,
            observation.error_message,
            observation.attempt_count,
            observation.collected_at,
            observation.collector_version,
        ),
    )
    connection.commit()
    return True


def iter_observations(
    connection: sqlite3.Connection, provider: str | None = None, postal_code: str | None = None
) -> Iterator[sqlite3.Row]:
    query = "SELECT * FROM commute_observation WHERE 1=1"
    params: list[str] = []
    if provider:
        query += " AND provider=?"
        params.append(provider)
    if postal_code:
        query += " AND postal_code=?"
        params.append(postal_code)
    query += " ORDER BY postal_code, provider, service_date, query_time"
    yield from connection.execute(query, params)


def export_addresses_csv(connection: sqlite3.Connection, path: str | Path) -> None:
    rows = list(connection.execute("SELECT * FROM residential_address ORDER BY postal_code"))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            rows[0].keys()
            if rows
            else [
                "postal_code",
                "address",
                "latitude",
                "longitude",
                "residential_type",
                "source",
                "source_identifier",
                "confidence",
                "discovered_at",
            ]
        )
        writer.writerows(rows)
