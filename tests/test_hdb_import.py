from __future__ import annotations

import csv

from commute.addresses.hdb import (
    HDB_SOURCE,
    HDBResidentialCandidate,
    address_from_hdb_result,
    canonical_road,
    read_hdb_postals_by_block,
    read_hdb_residential_csv,
)
from commute.addresses.ura import URA_SOURCE, iter_ura_private_addresses
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
    assert rows[0].search_values == ("1 BEACH RD SINGAPORE", "1 BEACH ROAD SINGAPORE", "1 BEACH ROAD")
    saint = HDBResidentialCandidate("1", "ST. GEORGE'S RD", "1|ST. GEORGE'S RD")
    assert saint.search_values == (
        "1 ST. GEORGE'S RD SINGAPORE",
        "1 SAINT GEORGE'S ROAD SINGAPORE",
        "1 SAINT GEORGE'S ROAD",
    )


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
    assert canonical_road("C'WEALTH CRES") == "COMMONWEALTH CRESCENT"
    assert canonical_road("UPP BOON KENG RD") == "UPPER BOON KENG ROAD"
    assert canonical_road("TENGAH GDN AVE") == "TENGAH GARDEN AVENUE"
    assert canonical_road("ST. GEORGE'S RD") == "SAINT GEORGES ROAD"
    assert canonical_road("TG PAGAR PLAZA") == "TANJONG PAGAR PLAZA"
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


def test_hdb_geojson_postal_candidates_are_grouped(tmp_path):
    path = tmp_path / "buildings.geojson"
    path.write_text(
        '{"type":"FeatureCollection","features":['
        '{"type":"Feature","properties":{"BLK_NO":"11","POSTAL_COD":"271011"}},'
        '{"type":"Feature","properties":{"BLK_NO":"11","POSTAL_COD":"380011"}}'
        ']}',
        encoding="utf-8",
    )
    assert read_hdb_postals_by_block(path) == {"11": ("271011", "380011")}


def test_ura_private_geojson_yields_verified_postal_points(tmp_path):
    path = tmp_path / "ura.geojson"
    path.write_text(
        '{"type":"FeatureCollection","features":['
        '{"type":"Feature","geometry":{"type":"Point","coordinates":[103.9,1.3]},'
        '"properties":{"OBJECTID":1,"POSTALCODE":"123456","BLK_NO":"1",'
        '"PROJ_NAME":"Example Court","PROP_TYPE":"Non-Landed"}}]}'
        ,
        encoding="utf-8",
    )
    rows = list(iter_ura_private_addresses(path))
    assert len(rows) == 1
    assert rows[0].source == URA_SOURCE
    assert rows[0].confidence == "VERIFIED"
    assert rows[0].residential_type == "PRIVATE_NON_LANDED"
    assert rows[0].latitude == 1.3
