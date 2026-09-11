from __future__ import annotations

import csv
import sqlite3
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Address, Observation


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
    discovered_at TEXT NOT NULL,
    distance_to_sutd_km REAL,
    google_exclusion_reason TEXT,
    google_stratum TEXT,
    google_sample_selected INTEGER NOT NULL DEFAULT 0,
    google_sample_seed INTEGER,
    onemap_group_key TEXT,
    onemap_group_representative TEXT,
    onemap_group_size INTEGER,
    onemap_group_method TEXT,
    onemap_exclusion_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_residential_confidence ON residential_address(confidence);
CREATE TABLE IF NOT EXISTS address_resolution (
    source TEXT NOT NULL,
    source_identifier TEXT NOT NULL,
    search_value TEXT NOT NULL,
    postal_code TEXT,
    latitude REAL,
    longitude REAL,
    status TEXT NOT NULL CHECK (status IN ('SUCCESS', 'FAILED')),
    error_code TEXT,
    error_message TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    resolved_at TEXT NOT NULL,
    PRIMARY KEY (source, source_identifier)
);
CREATE INDEX IF NOT EXISTS idx_address_resolution_status ON address_resolution(source, status);
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
CREATE TABLE IF NOT EXISTS google_usage_ledger (
    id INTEGER PRIMARY KEY,
    recorded_at TEXT NOT NULL,
    event_count INTEGER NOT NULL CHECK (event_count > 0)
);
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
    existing_columns = {row[1] for row in connection.execute("PRAGMA table_info(residential_address)")}
    migrations = {
        "distance_to_sutd_km": "REAL",
        "google_exclusion_reason": "TEXT",
        "google_stratum": "TEXT",
        "google_sample_selected": "INTEGER NOT NULL DEFAULT 0",
        "google_sample_seed": "INTEGER",
        "onemap_group_key": "TEXT",
        "onemap_group_representative": "TEXT",
        "onemap_group_size": "INTEGER",
        "onemap_group_method": "TEXT",
        "onemap_exclusion_reason": "TEXT",
    }
    for column, definition in migrations.items():
        if column not in existing_columns:
            connection.execute(f"ALTER TABLE residential_address ADD COLUMN {column} {definition}")
    connection.commit()
    return connection


def init_observations_db(path: str | Path) -> sqlite3.Connection:
    connection = connect(path)
    connection.executescript(OBSERVATION_SCHEMA)
    if connection.execute("SELECT COUNT(*) FROM google_usage_ledger").fetchone()[0] == 0:
        legacy_usage = connection.execute(
            "SELECT COALESCE(SUM(attempt_count), 0) FROM commute_observation WHERE provider='GOOGLE'"
        ).fetchone()[0]
        if legacy_usage:
            connection.execute(
                "INSERT INTO google_usage_ledger (recorded_at, event_count) VALUES (?, ?)",
                (now_utc(), int(legacy_usage)),
            )
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


def get_address_resolution(
    connection: sqlite3.Connection, source: str, source_identifier: str
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT * FROM address_resolution
        WHERE source=? AND source_identifier=?
        """,
        (source, source_identifier),
    ).fetchone()


def save_address_resolution(
    connection: sqlite3.Connection,
    *,
    source: str,
    source_identifier: str,
    search_value: str,
    status: str,
    postal_code: str | None,
    latitude: float | None,
    longitude: float | None,
    attempt_count: int,
    resolved_at: str,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    if status not in {"SUCCESS", "FAILED"}:
        raise ValueError(f"Invalid address resolution status: {status}")
    connection.execute(
        """
        INSERT INTO address_resolution
          (source, source_identifier, search_value, postal_code, latitude, longitude,
           status, error_code, error_message, attempt_count, resolved_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, source_identifier) DO UPDATE SET
          search_value=excluded.search_value, postal_code=excluded.postal_code,
          latitude=excluded.latitude, longitude=excluded.longitude,
          status=excluded.status, error_code=excluded.error_code,
          error_message=excluded.error_message, attempt_count=excluded.attempt_count,
          resolved_at=excluded.resolved_at
        """,
        (
            source,
            source_identifier,
            search_value,
            postal_code,
            latitude,
            longitude,
            status,
            error_code,
            error_message,
            attempt_count,
            resolved_at,
        ),
    )
    connection.commit()


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


def iter_onemap_origins(
    connection: sqlite3.Connection,
    include_confidence: Iterable[str] = ("VERIFIED", "LIKELY"),
    limit: int | None = None,
    postal_code: str | None = None,
) -> Iterator[sqlite3.Row]:
    """Yield every eligible non-landed postal origin exactly once.

    Group metadata is retained in the schema for historical datasets, but the
    current production policy is direct-postal routing. Ignoring stale group
    metadata here prevents an old classification from silently reducing a new
    collection's spatial resolution.
    """
    allowed = tuple(include_confidence)
    if not allowed:
        return
    placeholders = ",".join("?" for _ in allowed)
    params: list[Any] = list(allowed)
    if postal_code:
        row = connection.execute(
            f"SELECT * FROM residential_address WHERE postal_code=? AND confidence IN ({placeholders})",
            [postal_code, *params],
        ).fetchone()
        if row is None:
            return
        if row["onemap_exclusion_reason"] or row["residential_type"] == "PRIVATE_LANDED":
            return
        yield row
        return
    query = (
        "SELECT * FROM residential_address "
        f"WHERE confidence IN ({placeholders}) "
        "AND onemap_exclusion_reason IS NULL "
        "AND residential_type <> 'PRIVATE_LANDED' "
        "ORDER BY postal_code"
    )
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    yield from connection.execute(query, params)


def update_google_population(
    connection: sqlite3.Connection,
    postal_code: str,
    distance_to_sutd_km: float,
    exclusion_reason: str | None,
    stratum: str,
    sample_selected: bool,
    sample_seed: int,
) -> None:
    connection.execute(
        """
        UPDATE residential_address
        SET distance_to_sutd_km=?, google_exclusion_reason=?, google_stratum=?,
            google_sample_selected=?, google_sample_seed=?
        WHERE postal_code=?
        """,
        (
            distance_to_sutd_km,
            exclusion_reason,
            stratum,
            int(sample_selected),
            sample_seed,
            postal_code,
        ),
    )


def google_usage_events(connection: sqlite3.Connection) -> int:
    """Count persisted Google matrix elements reserved before each HTTP attempt."""
    value = connection.execute("SELECT COALESCE(SUM(event_count), 0) FROM google_usage_ledger").fetchone()[0]
    return int(value)


def record_google_usage(connection: sqlite3.Connection, event_count: int) -> None:
    if event_count < 1:
        raise ValueError("Google usage event count must be positive")
    connection.execute(
        "INSERT INTO google_usage_ledger (recorded_at, event_count) VALUES (?, ?)",
        (now_utc(), event_count),
    )
    connection.commit()


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
                "distance_to_sutd_km",
                "google_exclusion_reason",
                "google_stratum",
                "google_sample_selected",
                "google_sample_seed",
            ]
        )
        writer.writerows(rows)
