from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..models import Address
from .discovery import normalize_address, normalize_postal

URA_SOURCE = "ura_private_residential"


def _residential_type(value: Any) -> str:
    value = normalize_address(value)
    return {
        "LANDED": "PRIVATE_LANDED",
        "NON-LANDED": "PRIVATE_NON_LANDED",
        "EC": "EXECUTIVE_CONDOMINIUM",
    }.get(value, "PRIVATE_RESIDENTIAL")


def iter_ura_private_addresses(path: str | Path, limit: int | None = None) -> Iterator[Address]:
    """Yield deduplicated private-residential postal points from the official URA GeoJSON."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("type") != "FeatureCollection":
        raise ValueError("URA private-residential GeoJSON must be a FeatureCollection")
    seen: set[str] = set()
    for feature in payload.get("features", []):
        properties = feature.get("properties", {})
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        if geometry.get("type") != "Point" or len(coordinates) != 2:
            continue
        postal = normalize_postal(properties.get("POSTALCODE"))
        if not postal or postal in seen:
            continue
        seen.add(postal)
        project = normalize_address(properties.get("PROJ_NAME"))
        block = normalize_address(properties.get("BLK_NO"))
        property_type = _residential_type(properties.get("PROP_TYPE"))
        address = " ".join(part for part in (block, project, property_type, postal) if part)
        yield Address(
            postal_code=postal,
            address=address,
            latitude=float(coordinates[1]),
            longitude=float(coordinates[0]),
            residential_type=property_type,
            source=URA_SOURCE,
            source_identifier=str(properties.get("OBJECTID") or postal),
            confidence="VERIFIED",
        )
        if limit is not None and len(seen) >= limit:
            return


def read_ura_postal_codes(path: str | Path) -> set[str]:
    """Return the source's unique postal keys for completeness audits."""
    return {address.postal_code for address in iter_ura_private_addresses(path)}
