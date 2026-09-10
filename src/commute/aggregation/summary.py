from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Any


def row_value(row: Any, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


def percentile(values: list[int], fraction: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * fraction
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return float(values[lower])
    return values[lower] + (values[upper] - values[lower]) * (index - lower)


def summarize_provider(rows: list[Any], expected_samples: int, minimum_successful: int) -> dict[str, Any]:
    durations = sorted(
        int(row["duration_seconds"])
        for row in rows
        if row["status"] == "SUCCESS" and row["duration_seconds"] is not None
    )
    successful = len(durations)
    result: dict[str, Any] = {
        "status": "SUCCESS" if successful >= minimum_successful else "INSUFFICIENT_DATA",
        "mean_seconds": round(statistics.mean(durations), 3) if durations else None,
        "median_seconds": float(statistics.median(durations)) if durations else None,
        "min_seconds": min(durations) if durations else None,
        "max_seconds": max(durations) if durations else None,
        "stddev_seconds": round(statistics.pstdev(durations), 3) if len(durations) > 1 else None,
        "p10_seconds": round(percentile(durations, 0.10), 3) if durations else None,
        "p90_seconds": round(percentile(durations, 0.90), 3) if durations else None,
        "successful_samples": successful,
        "expected_samples": expected_samples,
    }
    return result


def combined_summary(google: dict[str, Any], onemap: dict[str, Any]) -> dict[str, Any]:
    usable = google.get("status") == "SUCCESS" and onemap.get("status") == "SUCCESS"
    value = (google["mean_seconds"] + onemap["mean_seconds"]) / 2 if usable else None
    return {"status": "SUCCESS" if usable else "INSUFFICIENT_DATA", "mean_seconds": value}


def validation_metrics(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compare provider means only at overlapping, sufficiently covered origins."""
    overlaps = [
        row for row in rows.values() if row["google"]["status"] == "SUCCESS" and row["onemap"]["status"] == "SUCCESS"
    ]
    differences = [row["google"]["mean_seconds"] - row["onemap"]["mean_seconds"] for row in overlaps]
    if not differences:
        return {
            "overlap_count": 0,
            "mean_difference_seconds": None,
            "median_difference_seconds": None,
            "mae_seconds": None,
            "correlation": None,
        }
    google_values = [row["google"]["mean_seconds"] for row in overlaps]
    onemap_values = [row["onemap"]["mean_seconds"] for row in overlaps]
    correlation = None
    if len(differences) > 1 and len(set(google_values)) > 1 and len(set(onemap_values)) > 1:
        correlation = round(statistics.correlation(google_values, onemap_values), 5)
    return {
        "overlap_count": len(overlaps),
        "mean_difference_seconds": round(statistics.mean(differences), 3),
        "median_difference_seconds": round(statistics.median(differences), 3),
        "mae_seconds": round(statistics.mean(abs(value) for value in differences), 3),
        "correlation": correlation,
    }


def aggregate_rows(
    address_rows: list[Any],
    observation_rows: list[Any],
    minimum_successful: int | dict[str, int],
    expected_samples: int | dict[str, int] = 70,
) -> dict[str, dict[str, Any]]:
    grouped: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for row in observation_rows:
        grouped[(row["postal_code"], row["provider"])].append(row)
    result: dict[str, dict[str, Any]] = {}
    for address in address_rows:
        postal = address["postal_code"]
        google_expected = expected_samples["GOOGLE"] if isinstance(expected_samples, dict) else expected_samples
        onemap_expected = expected_samples["ONEMAP"] if isinstance(expected_samples, dict) else expected_samples
        google_minimum = minimum_successful["GOOGLE"] if isinstance(minimum_successful, dict) else minimum_successful
        onemap_minimum = minimum_successful["ONEMAP"] if isinstance(minimum_successful, dict) else minimum_successful
        exclusion_reason = row_value(address, "google_exclusion_reason")
        if not exclusion_reason and row_value(address, "onemap_exclusion_reason"):
            exclusion_reason = row_value(address, "onemap_exclusion_reason")
        if exclusion_reason:
            google = {
                "status": "EXCLUDED",
                "mean_seconds": None,
                "median_seconds": None,
                "min_seconds": None,
                "max_seconds": None,
                "stddev_seconds": None,
                "p10_seconds": None,
                "p90_seconds": None,
                "successful_samples": 0,
                "expected_samples": google_expected,
            }
        else:
            google = summarize_provider(grouped[(postal, "GOOGLE")], google_expected, google_minimum)
        onemap_exclusion_reason = row_value(address, "onemap_exclusion_reason")
        if onemap_exclusion_reason:
            onemap = {
                "status": "EXCLUDED",
                "mean_seconds": None,
                "median_seconds": None,
                "min_seconds": None,
                "max_seconds": None,
                "stddev_seconds": None,
                "p10_seconds": None,
                "p90_seconds": None,
                "successful_samples": 0,
                "expected_samples": onemap_expected,
            }
        else:
            onemap = summarize_provider(grouped[(postal, "ONEMAP")], onemap_expected, onemap_minimum)
        result[postal] = {
            "postal_code": postal,
            "latitude": address["latitude"],
            "longitude": address["longitude"],
            "distance_to_sutd_km": row_value(address, "distance_to_sutd_km"),
            "google_exclusion_reason": exclusion_reason,
            "google_stratum": row_value(address, "google_stratum"),
            "google_sample_selected": bool(row_value(address, "google_sample_selected", 0)),
            "onemap_group_key": row_value(address, "onemap_group_key"),
            "onemap_group_representative": row_value(address, "onemap_group_representative"),
            "onemap_group_size": row_value(address, "onemap_group_size"),
            "onemap_exclusion_reason": onemap_exclusion_reason,
            "onemap_observation_mode": (
                "REPRESENTATIVE"
                if row_value(address, "onemap_group_representative")
                and row_value(address, "onemap_group_representative") != postal
                else "DIRECT"
            ),
            "google": google,
            "onemap": onemap,
            "combined": combined_summary(google, onemap),
        }
    return result
