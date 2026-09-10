from __future__ import annotations

from commute.aggregation.summary import (
    aggregate_rows,
    combined_summary,
    summarize_provider,
    validation_metrics,
)
from commute.db import get_observation, init_observations_db, save_observation
from commute.models import Observation


def make_observation(status="SUCCESS", duration=600, provider="GOOGLE"):
    return Observation(
        postal_code="200640",
        provider=provider,
        service_date="2026-09-14",
        query_time="07:30",
        time_semantics="ARRIVAL" if provider == "GOOGLE" else "DEPARTURE",
        origin_lat=1.3,
        origin_lng=103.85,
        destination_lat=1.34,
        destination_lng=103.96,
        duration_seconds=duration if status == "SUCCESS" else None,
        status=status,
        error_code=None if status == "SUCCESS" else "NO_ROUTE",
        error_message=None,
        attempt_count=1,
        collected_at="2026-09-10T00:00:00Z",
        collector_version="test",
    )


def test_database_uniqueness_and_success_protection(tmp_path):
    connection = init_observations_db(tmp_path / "obs.sqlite")
    assert save_observation(connection, make_observation(duration=600))
    assert not save_observation(connection, make_observation(status="FAILED"))
    row = get_observation(connection, "200640", "GOOGLE", "2026-09-14", "07:30")
    assert row["status"] == "SUCCESS"
    assert connection.execute("select count(*) from commute_observation").fetchone()[0] == 1


def test_summary_uses_successful_samples_only_and_threshold():
    rows = [
        {"status": "SUCCESS", "duration_seconds": 600},
        {"status": "SUCCESS", "duration_seconds": 1200},
        {"status": "FAILED", "duration_seconds": None},
    ]
    summary = summarize_provider(rows, expected_samples=3, minimum_successful=2)
    assert summary["status"] == "SUCCESS"
    assert summary["mean_seconds"] == 900
    assert summary["successful_samples"] == 2
    insufficient = summarize_provider(rows, expected_samples=3, minimum_successful=3)
    assert insufficient["status"] == "INSUFFICIENT_DATA"
    assert insufficient["mean_seconds"] == 900


def test_combined_requires_both_provider_means():
    good = {"status": "SUCCESS", "mean_seconds": 600}
    other = {"status": "SUCCESS", "mean_seconds": 1200}
    assert combined_summary(good, other) == {"status": "SUCCESS", "mean_seconds": 900.0}
    assert combined_summary(good, {"status": "INSUFFICIENT_DATA", "mean_seconds": 500})["mean_seconds"] is None


def test_aggregate_rows_keeps_missing_provider_as_insufficient():
    addresses = [{"postal_code": "200640", "latitude": 1.3, "longitude": 103.8}]
    observations = [{"postal_code": "200640", "provider": "GOOGLE", "status": "FAILED", "duration_seconds": None}]
    result = aggregate_rows(addresses, observations, minimum_successful=1)
    assert result["200640"]["google"]["mean_seconds"] is None
    assert result["200640"]["combined"]["status"] == "INSUFFICIENT_DATA"


def test_validation_metrics_compare_only_overlapping_provider_estimates():
    rows = {
        "200640": {
            "google": {"status": "SUCCESS", "mean_seconds": 900},
            "onemap": {"status": "SUCCESS", "mean_seconds": 780},
        },
        "460123": {
            "google": {"status": "SUCCESS", "mean_seconds": 1200},
            "onemap": {"status": "INSUFFICIENT_DATA", "mean_seconds": None},
        },
    }
    metrics = validation_metrics(rows)
    assert metrics["overlap_count"] == 1
    assert metrics["mean_difference_seconds"] == 120
    assert metrics["mae_seconds"] == 120
