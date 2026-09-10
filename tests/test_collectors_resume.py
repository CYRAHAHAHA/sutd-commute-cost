from __future__ import annotations

import httpx
import pytest

from commute.collector import ProviderError
from commute.db import get_observation, google_usage_events, init_observations_db
from commute.providers.google import MatrixResult
from commute.runners import collect_google, collect_onemap


class FlakyGoogleClient:
    def __init__(self):
        self.calls = 0

    def compute_route_matrix(self, origins, destination, arrival_time):
        self.calls += 1
        if self.calls == 1:
            raise httpx.ConnectError("temporary connection failure")
        return {0: MatrixResult(900, "SUCCESS")}


def test_google_transport_error_retries_and_persists_success(test_config, tmp_path):
    connection = init_observations_db(tmp_path / "observations.sqlite")
    client = FlakyGoogleClient()
    sleeps = []
    stats = collect_google(
        [{"postal_code": "200640", "latitude": 1.3, "longitude": 103.85}],
        test_config,
        connection,
        client,
        logger=lambda _: None,
        sleep=sleeps.append,
    )
    row = get_observation(connection, "200640", "GOOGLE", "2026-09-14", "07:30")
    assert client.calls == 2
    assert stats["success"] == 1
    assert row["attempt_count"] == 2
    assert google_usage_events(connection) == 2
    assert sleeps == [1.0]


class FakeGoogle:
    def __init__(self):
        self.calls = 0

    def compute_route_matrix(self, origins, destination, arrival_time):
        self.calls += 1
        return {index: MatrixResult(600 + index, "SUCCESS") for index in range(len(list(origins)))}


class FakeOneMap:
    def __init__(self):
        self.calls = 0

    def route(self, *args, **kwargs):
        self.calls += 1
        return 720


class FlakyOneMap:
    def __init__(self):
        self.calls = 0

    def route(self, *args, **kwargs):
        self.calls += 1
        if self.calls < 3:
            raise TimeoutError("temporary network timeout")
        return 720


class ExpiredOneMap:
    def route(self, *args, **kwargs):
        raise ProviderError("token expired", http_status=401, error_code="AUTHENTICATION_FAILED")


def test_google_collector_skips_success_on_resume(test_config, tmp_path):
    rows = [{"postal_code": "200640", "latitude": 1.3, "longitude": 103.85}]
    connection = init_observations_db(tmp_path / "obs.sqlite")
    client = FakeGoogle()
    first = collect_google(rows, test_config, connection, client, sleep=lambda _: None)
    assert first["success"] == 1 and client.calls == 1
    second = collect_google(rows, test_config, connection, client, sleep=lambda _: None)
    assert second["skipped"] == 1 and client.calls == 1


def test_onemap_collector_persists_a_success(test_config, tmp_path):
    rows = [{"postal_code": "200640", "latitude": 1.3, "longitude": 103.85}]
    connection = init_observations_db(tmp_path / "obs.sqlite")
    client = FakeOneMap()
    stats = collect_onemap(rows, test_config, connection, client, sleep=lambda _: None)
    assert stats["success"] == 1
    assert connection.execute("select duration_seconds from commute_observation").fetchone()[0] == 720


def test_onemap_collector_retries_transport_errors(test_config, tmp_path):
    rows = [{"postal_code": "200640", "latitude": 1.3, "longitude": 103.85}]
    connection = init_observations_db(tmp_path / "obs.sqlite")
    client = FlakyOneMap()
    stats = collect_onemap(rows, test_config, connection, client, sleep=lambda _: None)
    assert stats["success"] == 1 and client.calls == 3
    assert connection.execute("select attempt_count from commute_observation").fetchone()[0] == 3


def test_onemap_authentication_failure_stops_without_mass_failure_rows(test_config, tmp_path):
    rows = [{"postal_code": "200640", "latitude": 1.3, "longitude": 103.85}]
    connection = init_observations_db(tmp_path / "obs.sqlite")
    with pytest.raises(ProviderError, match="token expired"):
        collect_onemap(rows, test_config, connection, ExpiredOneMap(), sleep=lambda _: None)
    assert connection.execute("select count(*) from commute_observation").fetchone()[0] == 0
