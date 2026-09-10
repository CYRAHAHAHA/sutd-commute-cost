from __future__ import annotations

from collections import defaultdict
from math import cos, radians
from typing import Any


def _distance_squared(left: Any, right: Any) -> float:
    """Cheap local-distance metric; adequate for selecting a development medoid."""
    mean_latitude = radians((float(left["latitude"]) + float(right["latitude"])) / 2)
    north_south = float(left["latitude"]) - float(right["latitude"])
    east_west = (float(left["longitude"]) - float(right["longitude"])) * cos(mean_latitude)
    return north_south * north_south + east_west * east_west


def group_members(rows: list[Any]) -> dict[str, list[Any]]:
    groups: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        key = row["onemap_group_key"]
        if key:
            groups[str(key)].append(row)
    return groups


def representative_for_group(rows: list[Any]) -> Any:
    """Choose the existing postcode nearest the group's geographic medoid."""
    if not rows:
        raise ValueError("Cannot choose a representative from an empty group")
    return min(rows, key=lambda candidate: sum(_distance_squared(candidate, other) for other in rows))


def collapse_grouped_rows(rows: list[Any]) -> list[Any]:
    """Return one route origin per classified group and every ungrouped row."""
    result: list[Any] = []
    grouped = group_members(rows)
    grouped_postcodes = {row["postal_code"] for members in grouped.values() for row in members}
    result.extend(row for row in rows if row["postal_code"] not in grouped_postcodes)
    result.extend(representative_for_group(members) for members in grouped.values())
    return sorted(result, key=lambda row: row["postal_code"])
