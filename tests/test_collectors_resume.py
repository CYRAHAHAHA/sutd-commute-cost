from __future__ import annotations

from commute.db import init_observations_db
from commute.providers.google import MatrixResult
from commute.runners import collect_google, collect_onemap


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


def test_google_collector_skips_success_on_resume(test_config, tmp_path):
    rows = [{"postal_code": "200640", "latitude": 1.3, "longitude": 103.85}]
    connection = init_observations_db(tmp_path / "obs.sqlite")
    client = FakeGoogle()
    first = collect_google(rows, test_config, connection, client, sleep=lambda _: None)
    assert first["success"] == 3 and client.calls == 3
    second = collect_google(rows, test_config, connection, client, sleep=lambda _: None)
    assert second["skipped"] == 3 and client.calls == 3


def test_onemap_collector_persists_a_success(test_config, tmp_path):
    rows = [{"postal_code": "200640", "latitude": 1.3, "longitude": 103.85}]
    connection = init_observations_db(tmp_path / "obs.sqlite")
    client = FakeOneMap()
    stats = collect_onemap(rows, test_config, connection, client, sleep=lambda _: None)
    assert stats["success"] == 1
    assert connection.execute("select duration_seconds from commute_observation").fetchone()[0] == 720
