from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from typing import Any

from .config import GoogleSamplingSettings
from .db import update_google_population


def haversine_km(origin: tuple[float, float], destination: tuple[float, float]) -> float:
    """Return great-circle distance in kilometres between two WGS84 lat/lng points."""
    latitude_1, longitude_1 = map(math.radians, origin)
    latitude_2, longitude_2 = map(math.radians, destination)
    delta_latitude = latitude_2 - latitude_1
    delta_longitude = longitude_2 - longitude_1
    value = (
        math.sin(delta_latitude / 2) ** 2
        + math.cos(latitude_1) * math.cos(latitude_2) * math.sin(delta_longitude / 2) ** 2
    )
    return 6371.0088 * 2 * math.asin(math.sqrt(value))


def stratum_for(row: Any, cell_degrees: float) -> str:
    latitude_cell = math.floor(float(row["latitude"]) / cell_degrees)
    longitude_cell = math.floor(float(row["longitude"]) / cell_degrees)
    return f"{latitude_cell}:{longitude_cell}"


def _stable_rank(postal_code: str, seed: int) -> str:
    return hashlib.sha256(f"{seed}:{postal_code}".encode()).hexdigest()


def stratified_sample(rows: list[Any], sample_size: int, seed: int, cell_degrees: float) -> list[Any]:
    """Select a stable proportional sample using geographic grid strata and Hamilton quotas."""
    if sample_size >= len(rows):
        return sorted(rows, key=lambda row: row["postal_code"])
    sample_size = max(0, sample_size)
    grouped: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        grouped[stratum_for(row, cell_degrees)].append(row)
    total = len(rows)
    quotas = {}
    remainders = []
    for key, members in grouped.items():
        raw = sample_size * len(members) / total
        quota = math.floor(raw)
        quotas[key] = quota
        remainders.append((raw - quota, key))
    remaining = sample_size - sum(quotas.values())
    for _, key in sorted(remainders, key=lambda item: (-item[0], item[1]))[:remaining]:
        quotas[key] += 1
    if sample_size >= len(grouped):
        for key in sorted(quotas):
            if quotas[key] != 0:
                continue
            donors = sorted((candidate for candidate, quota in quotas.items() if quota > 1), key=str)
            if not donors:
                break
            quotas[donors[-1]] -= 1
            quotas[key] = 1
    chosen = []
    for key, members in grouped.items():
        ranked = sorted(members, key=lambda row: _stable_rank(row["postal_code"], seed))
        chosen.extend(ranked[: quotas[key]])
    return sorted(chosen, key=lambda row: row["postal_code"])


def prepare_google_population(
    connection: Any,
    rows: list[Any],
    destination: tuple[float, float],
    settings: GoogleSamplingSettings,
    sample_limit: int | None = None,
    persist: bool = True,
) -> tuple[list[Any], dict[str, int]]:
    """Annotate all rows and return the deterministic Google validation sample."""
    annotations: list[dict[str, Any]] = []
    eligible: list[Any] = []
    for row in rows:
        distance = haversine_km((float(row["latitude"]), float(row["longitude"])), destination)
        reason = (
            f"within_{settings.exclusion_radius_km:g}km_of_sutd" if distance <= settings.exclusion_radius_km else None
        )
        stratum = stratum_for(row, settings.stratum_cell_degrees)
        annotations.append({"row": row, "distance": distance, "reason": reason, "stratum": stratum})
        if reason is None:
            eligible.append(row)
    target = min(sample_limit if sample_limit is not None else settings.sample_size, len(eligible))
    selected = stratified_sample(eligible, target, settings.sampling_seed, settings.stratum_cell_degrees)
    selected_postcodes = {row["postal_code"] for row in selected}
    if persist:
        for item in annotations:
            row = item["row"]
            update_google_population(
                connection,
                row["postal_code"],
                item["distance"],
                item["reason"],
                item["stratum"],
                row["postal_code"] in selected_postcodes,
                settings.sampling_seed,
            )
        connection.commit()
    counts = {
        "population": len(rows),
        "excluded": len(rows) - len(eligible),
        "eligible": len(eligible),
        "selected": len(selected),
    }
    return selected, counts
