from __future__ import annotations

import math
import time as time_module
from collections.abc import Callable
from typing import Any

from .collector import (
    RateLimiter,
    call_with_retries,
    is_success,
    jobs_for_provider,
    observation_from_job,
    save_failure,
)
from .config import as_utc_rfc3339, query_datetimes
from .db import save_observation
from .models import Job
from .providers.google import GoogleRoutesClient, MatrixResult
from .providers.onemap import OneMapClient


def _job(row: Any, provider: str, service_date: str, query_time: str, config: dict[str, Any]) -> Job:
    return Job(
        postal_code=row["postal_code"],
        origin_lat=float(row["latitude"]),
        origin_lng=float(row["longitude"]),
        provider=provider,
        service_date=service_date,
        query_time=query_time,
        time_semantics=config["providers"][provider]["time_semantics"],
    )


def collect_google(
    rows: list[Any],
    config: dict[str, Any],
    connection: Any,
    client: GoogleRoutesClient,
    logger: Callable[[str], None] = print,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, int]:
    spec = config["providers"]["GOOGLE"]
    destination = (float(config["destination"]["latitude"]), float(config["destination"]["longitude"]))
    limiter = RateLimiter(float(spec.get("requests_per_second", 1.0)))
    batch_size = min(99, int(spec.get("batch_size", 90)))
    expected_total = len(rows) * len(config["experiment"]["dates"]) * len(spec["times"])
    stats = {"success": 0, "failed": 0, "skipped": 0, "requests": 0}
    for service_date, query_time, local_dt in query_datetimes(config, "GOOGLE"):
        pending = [
            row for row in rows if not is_success(connection, row["postal_code"], "GOOGLE", service_date, query_time)
        ]
        stats["skipped"] += len(rows) - len(pending)
        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            jobs = [_job(row, "GOOGLE", service_date, query_time, config) for row in batch]
            limiter.wait()
            stats["requests"] += 1
            attempts = 0
            try:
                result, attempts = call_with_retries(
                    lambda: client.compute_route_matrix(
                        [(job.origin_lat, job.origin_lng) for job in jobs],
                        destination,
                        as_utc_rfc3339(local_dt),
                    ),
                    int(spec.get("max_attempts", 5)),
                    sleep=sleep or time_module.sleep,
                )
            except Exception as exc:
                from .collector import ProviderError

                provider_error = exc if isinstance(exc, ProviderError) else ProviderError(str(exc))
                for job in jobs:
                    save_failure(connection, job, config, attempts or int(spec.get("max_attempts", 5)), provider_error)
                    stats["failed"] += 1
                logger(f"GOOGLE {service_date} {query_time}: batch failed: {provider_error}")
                continue
            for index, job in enumerate(jobs):
                matrix: MatrixResult = result.get(index, MatrixResult(None, "FAILED", "MISSING_ELEMENT"))
                if matrix.status == "SUCCESS" and matrix.duration_seconds is not None:
                    save_observation(
                        connection,
                        observation_from_job(job, config, matrix.duration_seconds, "SUCCESS", attempts),
                    )
                    stats["success"] += 1
                else:
                    save_observation(
                        connection,
                        observation_from_job(
                            job,
                            config,
                            None,
                            "FAILED",
                            attempts,
                            matrix.error_code,
                            matrix.error_message,
                        ),
                    )
                    stats["failed"] += 1
            completed = stats["success"] + stats["failed"] + stats["skipped"]
            logger(
                f"GOOGLE {completed:,} / {expected_total:,} observations; "
                f"{stats['success']:,} success, {stats['failed']:,} failed; requests {stats['requests']:,}"
            )
    return stats


def collect_onemap(
    rows: list[Any],
    config: dict[str, Any],
    connection: Any,
    client: OneMapClient,
    logger: Callable[[str], None] = print,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, int]:
    spec = config["providers"]["ONEMAP"]
    destination = (float(config["destination"]["latitude"]), float(config["destination"]["longitude"]))
    limiter = RateLimiter(float(spec.get("requests_per_second", 1.0)))
    jobs = jobs_for_provider(config, "ONEMAP", rows)
    stats = {"success": 0, "failed": 0, "skipped": 0, "requests": 0}
    total = len(jobs)
    try:
        for job in jobs:
            if is_success(connection, job.postal_code, "ONEMAP", job.service_date, job.query_time):
                stats["skipped"] += 1
                continue
            limiter.wait()
            stats["requests"] += 1
            attempts = 0
            try:
                duration, attempts = call_with_retries(
                    lambda: client.route(
                        (job.origin_lat, job.origin_lng),
                        destination,
                        job.service_date,
                        job.query_time,
                        int(spec.get("max_walk_distance", 1000)),
                        int(spec.get("num_itineraries", 1)),
                    ),
                    int(spec.get("max_attempts", 5)),
                    sleep=sleep or time_module.sleep,
                )
                save_observation(
                    connection,
                    observation_from_job(job, config, int(duration), "SUCCESS", attempts),
                )
                stats["success"] += 1
            except Exception as exc:
                from .collector import ProviderError

                provider_error = exc if isinstance(exc, ProviderError) else ProviderError(str(exc))
                save_failure(connection, job, config, attempts or int(spec.get("max_attempts", 5)), provider_error)
                stats["failed"] += 1
            completed = stats["success"] + stats["failed"] + stats["skipped"]
            logger(
                f"ONEMAP {completed:,} / {total:,} observations; "
                f"{stats['success']:,} success, {stats['failed']:,} failed; requests {stats['requests']:,}"
            )
    except KeyboardInterrupt:
        logger("ONEMAP interrupted; successful and terminal observations are already persisted")
    return stats


def estimate_google_requests(origin_count: int, config: dict[str, Any]) -> int:
    batch_size = min(99, int(config["providers"]["GOOGLE"].get("batch_size", 90)))
    return math.ceil(origin_count / batch_size) * 70 if origin_count else 0
