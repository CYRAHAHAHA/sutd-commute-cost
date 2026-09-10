from __future__ import annotations

import pytest

from commute.collector import jobs_for_provider
from commute.config import ConfigError, destination, query_datetimes


def test_fixed_experiment_has_ten_weekdays():
    from commute.config import load_config

    config = load_config()
    assert config["experiment"]["dates"] == [
        "2026-09-14",
        "2026-09-15",
        "2026-09-16",
        "2026-09-17",
        "2026-09-18",
        "2026-09-21",
        "2026-09-22",
        "2026-09-23",
        "2026-09-24",
        "2026-09-25",
    ]


def test_each_provider_defines_seven_timestamps():
    from commute.config import load_config

    config = load_config()
    assert [item[1] for item in query_datetimes(config, "GOOGLE")][:7] == [
        "07:30",
        "07:35",
        "07:40",
        "07:45",
        "07:50",
        "07:55",
        "08:00",
    ]
    assert [item[1] for item in query_datetimes(config, "ONEMAP")][:7] == [
        "06:20",
        "06:25",
        "06:30",
        "06:35",
        "06:40",
        "06:45",
        "06:50",
    ]


def test_seven_times_times_ten_dates_make_70_jobs(test_config):
    row = {"postal_code": "200640", "latitude": 1.3, "longitude": 103.85}
    original_dates = test_config["experiment"]["dates"]
    original_google = test_config["providers"]["GOOGLE"]["times"]
    original_one = test_config["providers"]["ONEMAP"]["times"]
    test_config["experiment"]["dates"] = [str(index) for index in range(10)]
    test_config["providers"]["GOOGLE"]["times"] = [str(index) for index in range(7)]
    test_config["providers"]["ONEMAP"]["times"] = [str(index) for index in range(7)]
    assert len(jobs_for_provider(test_config, "GOOGLE", [row])) == 70
    assert len(jobs_for_provider(test_config, "ONEMAP", [row])) == 70
    test_config["experiment"]["dates"] = original_dates
    test_config["providers"]["GOOGLE"]["times"] = original_google
    test_config["providers"]["ONEMAP"]["times"] = original_one


def test_destination_coordinates_are_required_for_collection():
    from commute.config import load_config

    config = load_config()
    with pytest.raises(ConfigError, match="coordinates are not configured"):
        destination(config, require_coordinates=True)


def test_invalid_destination_coordinate_is_rejected(test_config):
    test_config["destination"]["latitude"] = 91
    with pytest.raises(ConfigError, match="latitude"):
        destination(test_config, require_coordinates=True)
