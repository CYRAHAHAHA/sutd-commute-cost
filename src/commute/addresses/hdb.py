from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..models import Address
from .discovery import normalize_address, normalize_postal

HDB_SOURCE = "hdb_property_information"


@dataclass(frozen=True)
class HDBResidentialCandidate:
    block_number: str
    street: str
    source_identifier: str

    @property
    def search_value(self) -> str:
        return f"{self.block_number} {self.street} SINGAPORE"

    @property
    def search_values(self) -> tuple[str, ...]:
        expanded = f"{self.block_number} {expanded_road(self.street)} SINGAPORE"
        without_country = expanded.removesuffix(" SINGAPORE")
        values = [self.search_value, expanded, without_country]
        return tuple(dict.fromkeys(values))


def _required_columns() -> set[str]:
    return {"blk_no", "street", "residential"}


def read_hdb_residential_csv(path: str | Path, limit: int | None = None) -> list[HDBResidentialCandidate]:
    """Read official HDB property records, retaining only residential buildings.

    The source has no postal code.  OneMap Search resolves each exact block/street
    candidate, and the source identifier makes the process resumable.
    """
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        missing = _required_columns() - fields
        if missing:
            raise ValueError(f"HDB property CSV is missing columns: {', '.join(sorted(missing))}")
        result: list[HDBResidentialCandidate] = []
        seen: set[str] = set()
        for row in reader:
            if str(row.get("residential", "")).strip().upper() != "Y":
                continue
            block_number = normalize_address(row.get("blk_no"))
            street = normalize_address(row.get("street"))
            if not block_number or not street:
                continue
            source_identifier = f"{block_number}|{street}"
            if source_identifier in seen:
                continue
            seen.add(source_identifier)
            result.append(HDBResidentialCandidate(block_number, street, source_identifier))
            if limit is not None and len(result) >= limit:
                break
    return result


_ROAD_WORDS = {
    "AVE": "AVENUE",
    "AV": "AVENUE",
    "CL": "CLOSE",
    "CRES": "CRESCENT",
    "CTRL": "CENTRAL",
    "DR": "DRIVE",
    "JLN": "JALAN",
    "LOR": "LORONG",
    "PK": "PARK",
    "PL": "PLACE",
    "RD": "ROAD",
    "ST": "STREET",
    "TER": "TERRACE",
    "BT": "BUKIT",
    "C'WEALTH": "COMMONWEALTH",
    "CWEALTH": "COMMONWEALTH",
    "KG": "KAMPONG",
    "NTH": "NORTH",
    "STH": "SOUTH",
    "TG": "TANJONG",
    "E": "EAST",
    "W": "WEST",
}


def expanded_road(value: Any) -> str:
    raw_tokens = normalize_address(value).split()
    result = []
    for index, raw_token in enumerate(raw_tokens):
        token = raw_token.replace(".", "")
        if token == "ST" and index + 1 < len(raw_tokens):
            next_token = raw_tokens[index + 1].replace(".", "")
            if next_token in {"GEORGE", "GEORGE'S"}:
                token = "SAINT"
        result.append(_ROAD_WORDS.get(token, token))
    return " ".join(result)


def canonical_road(value: Any) -> str:
    return expanded_road(value).replace("'", "")


def _contains_token_sequence(haystack: str, needle: str) -> bool:
    haystack_tokens = haystack.split()
    needle_tokens = needle.split()
    width = len(needle_tokens)
    return any(haystack_tokens[index : index + width] == needle_tokens for index in range(len(haystack_tokens)))


def _result_matches_candidate(candidate: HDBResidentialCandidate, result: dict[str, Any]) -> bool:
    returned_block = normalize_address(result.get("BLK_NO"))
    if returned_block != candidate.block_number:
        return False
    source_road = canonical_road(candidate.street)
    returned_road = canonical_road(result.get("ROAD_NAME"))
    if returned_road:
        return returned_road == source_road
    return _contains_token_sequence(canonical_road(result.get("ADDRESS")), source_road)


def address_from_hdb_result(candidate: HDBResidentialCandidate, result: dict[str, Any] | None) -> Address:
    if not result:
        raise ValueError(f"OneMap returned no result for {candidate.search_value}")
    if not _result_matches_candidate(candidate, result):
        raise ValueError(
            f"OneMap result did not match block/street for {candidate.search_value}: "
            f"{result.get('ADDRESS') or result.get('SEARCHVAL') or result}"
        )
    postal_code = normalize_postal(result.get("POSTAL"))
    latitude = result.get("LATITUDE")
    longitude = result.get("LONGITUDE") or result.get("LONGTITUDE")
    if not postal_code or latitude in (None, "") or longitude in (None, ""):
        raise ValueError(f"OneMap result lacks a usable postal code/coordinate for {candidate.search_value}")
    return Address(
        postal_code=postal_code,
        address=normalize_address(result.get("ADDRESS") or candidate.search_value),
        latitude=float(latitude),
        longitude=float(longitude),
        residential_type="HDB",
        source=HDB_SOURCE,
        source_identifier=candidate.source_identifier,
        confidence="VERIFIED",
    )
