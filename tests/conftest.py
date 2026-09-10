from __future__ import annotations

import copy

import pytest

from commute.config import load_config


@pytest.fixture
def test_config():
    config = copy.deepcopy(load_config())
    config["destination"] = {
        "name": "Singapore University of Technology and Design",
        "latitude": 1.3404,
        "longitude": 103.9634,
    }
    config["experiment"]["dates"] = ["2026-09-14"]
    config["providers"]["GOOGLE"]["dates"] = ["2026-09-14"]
    config["providers"]["ONEMAP"]["dates"] = ["2026-09-14"]
    config["providers"]["GOOGLE"]["times"] = ["07:30"]
    config["providers"]["ONEMAP"]["times"] = ["06:20"]
    config["providers"]["GOOGLE"]["requests_per_second"] = 1000
    config["providers"]["ONEMAP"]["requests_per_second"] = 1000
    config["experiment"]["minimum_successful_samples"] = 1
    return config
