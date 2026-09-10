from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .runners import jobs_for_provider


def audit_provider(
    config: Mapping[str, Any],
    provider: str,
    population: Sequence[Mapping[str, Any]],
    observations: Iterable[Mapping[str, Any]],
    minimum_population: int = 0,
) -> dict[str, Any]:
    """Audit persisted observations against the exact production job population."""
    jobs = jobs_for_provider(config, provider, population)
    expected_keys = {(job.postal_code, job.service_date, job.query_time) for job in jobs}
    observation_rows = list(observations)
    actual_key_list = [(row["postal_code"], row["service_date"], row["query_time"]) for row in observation_rows]
    actual_keys = set(actual_key_list)
    duplicate_keys = [key for key, count in Counter(actual_key_list).items() if count > 1]
    destination = config["destination"]
    expected_semantics = config["providers"][provider]["time_semantics"]
    invariant_errors: list[str] = []
    for row in observation_rows:
        label = f"{row['postal_code']} {row['service_date']} {row['query_time']}"
        status = row["status"]
        duration = row["duration_seconds"]
        if status == "SUCCESS" and (duration is None or int(duration) <= 0):
            invariant_errors.append(f"{label}: bad success duration")
        if status == "FAILED" and duration is not None:
            invariant_errors.append(f"{label}: failed row has duration")
        if int(row["attempt_count"]) < 1:
            invariant_errors.append(f"{label}: attempts < 1")
        if row["time_semantics"] != expected_semantics:
            invariant_errors.append(f"{label}: wrong time semantics")
        if not math.isclose(float(row["destination_lat"]), float(destination["latitude"]), abs_tol=1e-9):
            invariant_errors.append(f"{label}: wrong destination latitude")
        if not math.isclose(float(row["destination_lng"]), float(destination["longitude"]), abs_tol=1e-9):
            invariant_errors.append(f"{label}: wrong destination longitude")
        if not row["collected_at"] or not row["collector_version"]:
            invariant_errors.append(f"{label}: missing collection metadata")
        if status == "FAILED" and not row["error_code"]:
            invariant_errors.append(f"{label}: failed row has no error code")

    missing_keys = expected_keys - actual_keys
    unexpected_keys = actual_keys - expected_keys
    return {
        "provider": provider,
        "population": len(population),
        "minimum_population": minimum_population,
        "selection_ready": len(population) >= minimum_population,
        "expected_jobs": len(expected_keys),
        "persisted_jobs": len(expected_keys & actual_keys),
        "missing_jobs": len(missing_keys),
        "unexpected_jobs": len(unexpected_keys),
        "duplicate_keys": len(duplicate_keys),
        "invariant_errors": invariant_errors,
        "missing_examples": sorted(missing_keys)[:10],
        "unexpected_examples": sorted(unexpected_keys)[:10],
    }
