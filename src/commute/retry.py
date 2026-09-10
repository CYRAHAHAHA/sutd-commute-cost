from __future__ import annotations

from dataclasses import dataclass

RETRYABLE_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}
PERMANENT_HTTP_STATUSES = {400, 401, 403, 404, 405, 409, 422}
PERMANENT_ERROR_CODES = {
    "INVALID_ARGUMENT",
    "PERMISSION_DENIED",
    "UNAUTHENTICATED",
    "NOT_FOUND",
    "ROUTE_NOT_FOUND",
    "INVALID_REQUEST",
}


@dataclass(frozen=True)
class RetryDecision:
    retryable: bool
    reason: str


def retry_decision(http_status: int | None = None, error_code: str | None = None) -> RetryDecision:
    if http_status == 429:
        return RetryDecision(True, "rate_limited")
    if http_status in RETRYABLE_HTTP_STATUSES:
        return RetryDecision(True, f"transient_http_{http_status}")
    if http_status in PERMANENT_HTTP_STATUSES:
        return RetryDecision(False, f"permanent_http_{http_status}")
    if error_code in PERMANENT_ERROR_CODES:
        return RetryDecision(False, f"permanent_error_{error_code}")
    if http_status is None and error_code is None:
        return RetryDecision(True, "unknown_transport_error")
    return RetryDecision(False, "unknown_error")


def backoff_seconds(attempt: int, base: float = 1.0, maximum: float = 60.0) -> float:
    """Deterministic exponential backoff; attempt is one-based."""
    return min(maximum, base * (2 ** max(0, attempt - 1)))
