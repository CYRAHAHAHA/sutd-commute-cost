from __future__ import annotations

from commute.addresses.discovery import address_from_row, normalize_postal


def test_postal_code_normalization():
    assert normalize_postal("123 456") == "123456"
    assert normalize_postal("12345") is None
    assert normalize_postal("Singapore") is None


def test_missing_coordinates_cannot_be_marked_verified():
    address = address_from_row({"postal_code": "123456", "address": "Example", "confidence": "VERIFIED"})
    assert address.confidence == "UNRESOLVED"
