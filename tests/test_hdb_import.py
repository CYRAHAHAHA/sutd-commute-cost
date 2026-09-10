from __future__ import annotations

import csv

from commute.addresses.hdb import (
    HDB_SOURCE,
    HDBResidentialCandidate,
    address_from_hdb_result,
    canonical_road,
    read_hdb_residential_csv,
)
from commute.db import get_address_resolution, init_addresses_db, save_address_resolution


def test_hdb_reader_filters_residential_and_deduplicates(tmp_path):
    path = tmp_path / "hdb.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["blk_no", "street", "residential"])
        writer.writeheader()
        writer.writerow({"blk_no": "1", "street": "BEACH RD", "residential": "Y"})
        writer.writerow({"blk_no": "1", "street": "BEACH RD", "residential": "Y"})
        writer.writerow({"blk_no": "2", "street": "OTHER RD", "residential": "N"})
    rows = read_hdb_residential_csv(path)
    assert len(rows) == 1
    assert rows[0].source_identifier == "1|BEACH RD"
    assert rows[0].search_value == "1 BEACH RD SINGAPORE"
    assert rows[0].search_values == ("1 BEACH RD SINGAPORE", "1 BEACH ROAD SINGAPORE")


def test_hdb_result_requires_matching_block_and_canonical_street():
    candidate = HDBResidentialCandidate("1", "BEACH RD", "1|BEACH RD")
    result = {
        "BLK_NO": "1",
        "ROAD_NAME": "BEACH ROAD",
        "POSTAL": "189673",
        "LATITUDE": "1.29",
        "LONGITUDE": "103.85",
        "ADDRESS": "1 BEACH ROAD SINGAPORE 189673",
    }
    address = address_from_hdb_result(candidate, result)
    assert address.source == HDB_SOURCE
    assert address.confidence == "VERIFIED"
    assert address.postal_code == "189673"
    assert canonical_road("JLN BT MERAH") == "JALAN BUKIT MERAH"


def test_address_resolution_checkpoint_is_idempotent(tmp_path):
    connection = init_addresses_db(tmp_path / "addresses.sqlite")
    values = {
        "source": HDB_SOURCE,
        "source_identifier": "1|BEACH RD",
        "search_value": "1 BEACH RD SINGAPORE",
        "status": "SUCCESS",
        "postal_code": "189673",
        "latitude": 1.29,
        "longitude": 103.85,
        "attempt_count": 1,
        "resolved_at": "2026-09-10T00:00:00Z",
    }
    save_address_resolution(connection, **values)
    save_address_resolution(connection, **{**values, "attempt_count": 2})
    row = get_address_resolution(connection, HDB_SOURCE, "1|BEACH RD")
    assert row["postal_code"] == "189673"
    assert row["attempt_count"] == 2
    assert connection.execute("select count(*) from address_resolution").fetchone()[0] == 1
