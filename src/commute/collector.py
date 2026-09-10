from __future__ import annotations

import time as time_module
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from .config import as_utc_rfc3339
from .db import get_observation, save_observation
from .models import Job, Observation
from .retry import RetryDecision, backoff_seconds, retry_decision


@dataclass
class ProviderError(Exception):
    message: str
    http_status: int | None = None
    error_code: str | None = None
    retryable: bool | None = None
    attempt_count: int | None = None

    def __str__(self) -> str:
        return self.message

    @property
    def decision(self) -> RetryDecision:
        return (
            retry_decision(self.http_status, self.error_code)
            if self.retryable is None
            else RetryDecision(self.retryable, "provider_override")
        )


class GoogleBudgetExceeded(ProviderError):
    def __init__(self, used: int, requested: int, limit: int):
        super().__init__(
            f"Google budget guard: {used} used + {requested} requested exceeds configured limit {limit}; "
            "use --override-budget only if you explicitly accept additional usage",
            error_code="GOOGLE_BUDGET_EXCEEDED",
            retryable=False,
        )


class GoogleBudget:
    def __init__(self, limit: int, used: int, override: bool = False):
        self.limit = limit
        self.used = used
        self.override = override

    def reserve(self, elements: int) -> None:
        if not self.override and self.used + elements > self.limit:
            raise GoogleBudgetExceeded(self.used, elements, self.limit)
        self.used += elements


class RateLimiter:
    def __init__(self, requests_per_second: float) -> None:
        self.interval = 1.0 / requests_per_second if requests_per_second > 0 else 0
        self._last_request = 0.0
        self._lock = Lock()

    def wait(self) -> None:
        with self._lock:
            elapsed = time_module.monotonic() - self._last_request
            delay = self.interval - elapsed
            if delay > 0:
                time_module.sleep(delay)
            self._last_request = time_module.monotonic()


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def jobs_for_provider(config: dict[str, Any], provider: str, rows: Iterable[Any]) -> list[Job]:
    spec = config["providers"][provider]
    service_dates = spec.get("dates", config["experiment"]["dates"])
    jobs: list[Job] = []
    for row in rows:
        for service_date in service_dates:
            for query_time in spec["times"]:
                jobs.append(
                    Job(
                        postal_code=row["postal_code"],
                        origin_lat=float(row["latitude"]),
                        origin_lng=float(row["longitude"]),
                        provider=provider,
                        service_date=service_date,
                        query_time=query_time,
                        time_semantics=spec["time_semantics"],
                    )
                )
    return jobs


def observation_from_job(
    job: Job,
    config: dict[str, Any],
    duration_seconds: int | None,
    status: str,
    attempt_count: int,
    error_code: str | None = None,
    error_message: str | None = None,
) -> Observation:
    destination = config["destination"]
    return Observation(
        postal_code=job.postal_code,
        provider=job.provider,
        service_date=job.service_date,
        query_time=job.query_time,
        time_semantics=job.time_semantics,
        origin_lat=job.origin_lat,
        origin_lng=job.origin_lng,
        destination_lat=float(destination["latitude"]),
        destination_lng=float(destination["longitude"]),
        duration_seconds=duration_seconds,
        status=status,
        error_code=error_code,
        error_message=error_message,
        attempt_count=attempt_count,
        collected_at=now_utc(),
        collector_version=config.get("dataset_version", "unknown"),
    )


def call_with_retries(
    fn: Callable[[], Any],
    max_attempts: int,
    sleep: Callable[[float], None] = time_module.sleep,
    base_backoff: float = 1.0,
) -> tuple[Any, int]:
    """Call a provider operation and return (result, attempts), raising after terminal exhaustion."""
    attempts = 0
    while attempts < max_attempts:
        attempts += 1
        try:
            return fn(), attempts
        except ProviderError as exc:
            decision = exc.decision
            if not decision.retryable or attempts >= max_attempts:
                exc.attempt_count = attempts
                raise
            sleep(backoff_seconds(attempts, base=base_backoff))
    raise AssertionError("unreachable")


def is_success(connection: Any, postal_code: str, provider: str, service_date: str, query_time: str) -> bool:
    row = get_observation(connection, postal_code, provider, service_date, query_time)
    return bool(row and row["status"] == "SUCCESS")


def local_to_utc_iso(local_datetime: datetime) -> str:
    return as_utc_rfc3339(local_datetime)


def save_failure(connection: Any, job: Job, config: dict[str, Any], attempts: int, exc: ProviderError) -> None:
    save_observation(
        connection,
        observation_from_job(
            job,
            config,
            None,
            "FAILED",
            attempts,
            error_code=exc.error_code or (f"HTTP_{exc.http_status}" if exc.http_status else "TRANSPORT_ERROR"),
            error_message=str(exc)[:1000],
        ),
    )
