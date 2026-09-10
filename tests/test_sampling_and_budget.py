from __future__ import annotations

from commute.collector import GoogleBudget, GoogleBudgetExceeded
from commute.config import google_sampling_settings
from commute.db import google_usage_events, init_addresses_db, init_observations_db, record_google_usage, upsert_address
from commute.models import Address
from commute.sampling import haversine_km, prepare_google_population, stratified_sample


def test_haversine_and_reproducible_stratified_sample(test_config):
    rows = [
        {"postal_code": "000001", "latitude": 1.3404, "longitude": 103.9634},
        {"postal_code": "100001", "latitude": 1.30, "longitude": 103.80},
        {"postal_code": "100002", "latitude": 1.31, "longitude": 103.81},
        {"postal_code": "200001", "latitude": 1.40, "longitude": 103.90},
    ]
    assert haversine_km((1.3404, 103.9634), (1.3404, 103.9634)) == 0
    first = stratified_sample(rows[1:], 2, 123, 0.02)
    second = stratified_sample(rows[1:], 2, 123, 0.02)
    assert [row["postal_code"] for row in first] == [row["postal_code"] for row in second]
    all_strata = stratified_sample(rows[1:], 3, 123, 0.02)
    assert {row["postal_code"] for row in all_strata} == {"100001", "100002", "200001"}


def test_google_population_persists_radius_exclusion_and_sample(test_config, tmp_path):
    connection = init_addresses_db(tmp_path / "addresses.sqlite")
    addresses = [
        Address("000001", "Near SUTD", 1.3404, 103.9634, "HDB", "test", "1", "VERIFIED"),
        Address("200001", "Far home", 1.40, 103.90, "HDB", "test", "2", "VERIFIED"),
    ]
    for address in addresses:
        upsert_address(connection, address, "2026-09-10T00:00:00Z")
    connection.commit()
    settings = google_sampling_settings(test_config)
    selected, counts = prepare_google_population(
        connection,
        list(connection.execute("select * from residential_address order by postal_code")),
        (1.3404, 103.9634),
        settings,
        sample_limit=1,
    )
    assert counts == {"population": 2, "excluded": 1, "eligible": 1, "selected": 1}
    assert [row["postal_code"] for row in selected] == ["200001"]
    near = connection.execute(
        "select google_exclusion_reason, google_sample_selected from residential_address where postal_code='000001'"
    ).fetchone()
    assert near[0] == "within_3.5km_of_sutd"
    assert near[1] == 0


def test_google_budget_guard_blocks_over_budget_and_allows_override():
    budget = GoogleBudget(9000, 8999)
    try:
        budget.reserve(2)
    except GoogleBudgetExceeded:
        pass
    else:
        raise AssertionError("expected budget guard")
    override = GoogleBudget(9000, 8999, override=True)
    override.reserve(2)
    assert override.used == 9001


def test_google_usage_ledger_counts_retries_across_restarts(tmp_path):
    connection = init_observations_db(tmp_path / "observations.sqlite")
    record_google_usage(connection, 90)
    record_google_usage(connection, 90)
    assert google_usage_events(connection) == 180
    connection.close()
    reopened = init_observations_db(tmp_path / "observations.sqlite")
    assert google_usage_events(reopened) == 180
