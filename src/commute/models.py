from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Address:
    postal_code: str
    address: str
    latitude: float
    longitude: float
    residential_type: str
    source: str
    source_identifier: str
    confidence: str


@dataclass(frozen=True)
class Job:
    postal_code: str
    origin_lat: float
    origin_lng: float
    provider: str
    service_date: str
    query_time: str
    time_semantics: str


@dataclass(frozen=True)
class Observation:
    postal_code: str
    provider: str
    service_date: str
    query_time: str
    time_semantics: str
    origin_lat: float
    origin_lng: float
    destination_lat: float
    destination_lng: float
    duration_seconds: int | None
    status: str
    error_code: str | None
    error_message: str | None
    attempt_count: int
    collected_at: str | None
    collector_version: str

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()
