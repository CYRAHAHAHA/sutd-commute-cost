from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models import Address

CONFIDENCES = {"VERIFIED", "LIKELY", "UNRESOLVED", "EXCLUDED"}


def normalize_postal(value: Any) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits if len(digits) == 6 else None


def normalize_address(value: Any) -> str:
    return " ".join(str(value or "").upper().split())


def address_from_row(row: dict[str, Any], fallback_source: str = "csv") -> Address:
    postal = normalize_postal(row.get("postal_code") or row.get("POSTAL") or row.get("postal"))
    if not postal:
        raise ValueError(f"Address row has no six-digit postal_code: {row}")
    address = normalize_address(row.get("address") or row.get("ADDRESS") or row.get("searchval") or postal)
    lat_value = row.get("latitude") or row.get("LATITUDE")
    lng_value = row.get("longitude") or row.get("LONGITUDE") or row.get("LONGTITUDE")
    latitude = float(lat_value) if lat_value not in (None, "") else 0.0
    longitude = float(lng_value) if lng_value not in (None, "") else 0.0
    has_coordinates = bool(lat_value not in (None, "") and lng_value not in (None, ""))
    confidence = str(row.get("confidence") or ("VERIFIED" if has_coordinates else "UNRESOLVED")).upper()
    if confidence not in CONFIDENCES:
        raise ValueError(f"Invalid confidence {confidence!r}; choose one of {sorted(CONFIDENCES)}")
    if not has_coordinates and confidence in {"VERIFIED", "LIKELY"}:
        confidence = "UNRESOLVED"
    return Address(
        postal_code=postal,
        address=address,
        latitude=latitude,
        longitude=longitude,
        residential_type=str(row.get("residential_type") or row.get("type") or "UNKNOWN").upper(),
        source=str(row.get("source") or fallback_source),
        source_identifier=str(row.get("source_identifier") or row.get("id") or postal),
        confidence=confidence,
    )


def read_source_csv(path: str | Path, source: str = "csv") -> list[Address]:
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        return [address_from_row(row, source) for row in csv.DictReader(handle)]


def resolve_with_onemap(address: Address, client: Any) -> Address:
    """Resolve a postal code/address and retain explicit provenance."""
    if address.latitude and address.longitude:
        return address
    result = client.search(address.postal_code)
    if not result:
        return Address(**{**address.__dict__, "confidence": "UNRESOLVED"})
    lat = result.get("LATITUDE")
    lng = result.get("LONGITUDE") or result.get("LONGTITUDE")
    if lat in (None, "") or lng in (None, ""):
        return Address(**{**address.__dict__, "confidence": "UNRESOLVED"})
    resolved_postal = normalize_postal(result.get("POSTAL")) or address.postal_code
    resolved_address = normalize_address(result.get("ADDRESS") or address.address)
    return Address(
        postal_code=resolved_postal,
        address=resolved_address,
        latitude=float(lat),
        longitude=float(lng),
        residential_type=address.residential_type,
        source=address.source,
        source_identifier=address.source_identifier,
        confidence=address.confidence if address.confidence != "UNRESOLVED" else "LIKELY",
    )


def discovered_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
