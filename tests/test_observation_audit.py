from __future__ import annotations

from commute.audit import audit_provider


def audit_config():
    return {
        "destination": {"latitude": 1.34, "longitude": 103.96},
        "experiment": {"dates": ["2026-09-14"]},
        "providers": {
            "GOOGLE": {
                "dates": ["2026-09-14"],
                "times": ["07:30"],
                "time_semantics": "ARRIVAL",
            }
        },
    }


def observation(**overrides):
    row = {
        "postal_code": "200640",
        "service_date": "2026-09-14",
        "query_time": "07:30",
        "status": "SUCCESS",
        "duration_seconds": 1200,
        "attempt_count": 1,
        "time_semantics": "ARRIVAL",
        "destination_lat": 1.34,
        "destination_lng": 103.96,
        "collected_at": "2026-09-10T00:00:00Z",
        "collector_version": "test",
        "error_code": None,
    }
    row.update(overrides)
    return row


def test_observation_audit_accepts_complete_valid_job():
    result = audit_provider(
        audit_config(),
        "GOOGLE",
        [{"postal_code": "200640", "latitude": 1.3, "longitude": 103.85}],
        [observation()],
        minimum_population=1,
    )
    assert result["missing_jobs"] == 0
    assert result["invariant_errors"] == []


def test_observation_audit_reports_missing_and_invalid_rows():
    result = audit_provider(
        audit_config(),
        "GOOGLE",
        [
            {"postal_code": "200640", "latitude": 1.3, "longitude": 103.85},
            {"postal_code": "200641", "latitude": 1.3, "longitude": 103.85},
        ],
        [observation(duration_seconds=None, error_code="NO_DURATION")],
        minimum_population=3,
    )
    assert result["missing_jobs"] == 1
    assert result["selection_ready"] is False
    assert result["invariant_errors"]
