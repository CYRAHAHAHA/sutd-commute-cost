from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Any


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


def aggregate_rows(
    address_rows: list[Any], observation_rows: list[Any], minimum_successful: int, expected_samples: int = 70
) -> dict[str, dict[str, Any]]:
    grouped: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for row in observation_rows:
        grouped[(row["postal_code"], row["provider"])].append(row)
    result: dict[str, dict[str, Any]] = {}
    for address in address_rows:
        postal = address["postal_code"]
        google = summarize_provider(grouped[(postal, "GOOGLE")], expected_samples, minimum_successful)
        onemap = summarize_provider(grouped[(postal, "ONEMAP")], expected_samples, minimum_successful)
        result[postal] = {
            "postal_code": postal,
            "latitude": address["latitude"],
            "longitude": address["longitude"],
            "google": google,
            "onemap": onemap,
            "combined": combined_summary(google, onemap),
        }
    return result
