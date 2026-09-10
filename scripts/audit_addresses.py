from __future__ import annotations

import argparse
import sys

from commute.addresses.hdb import HDB_SOURCE, read_hdb_residential_csv
from commute.addresses.ura import URA_SOURCE, iter_ura_private_addresses
from commute.config import ConfigError, load_config, resolve_path
from commute.db import init_addresses_db


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Audit the deduplicated residential address database.")
    result.add_argument("--property-csv", default="data/input/HDBPropertyInformation.csv")
    result.add_argument("--ura-geojson", default="data/input/URA_NoOfDwellingUnits.geojson")
    result.add_argument(
        "--require-complete",
        action="store_true",
        help="Return failure unless all HDB and URA source points are imported and no failures remain",
    )
    result.add_argument(
        "--reject-fixtures",
        action="store_true",
        help="Return failure if sample_fixture rows remain in the production address database",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        config = load_config()
        connection = init_addresses_db(resolve_path(config, config["addresses"]["database"]))
        source_counts = dict(
            connection.execute("SELECT source, COUNT(*) FROM residential_address GROUP BY source").fetchall()
        )
        resolution_counts = dict(
            connection.execute(
                "SELECT status, COUNT(*) FROM address_resolution WHERE source=? GROUP BY status", (HDB_SOURCE,)
            ).fetchall()
        )
        hdb_expected = len(read_hdb_residential_csv(args.property_csv))
        ura_expected = sum(1 for _ in iter_ura_private_addresses(args.ura_geojson))
        hdb_success = int(resolution_counts.get("SUCCESS", 0))
        hdb_failed = int(resolution_counts.get("FAILED", 0))
        invalid_coordinates = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM residential_address
                WHERE latitude IS NULL OR longitude IS NULL
                   OR latitude NOT BETWEEN -90 AND 90
                   OR longitude NOT BETWEEN -180 AND 180
                """
            ).fetchone()[0]
        )
        duplicate_postals = int(
            connection.execute(
                "SELECT COUNT(*) - COUNT(DISTINCT postal_code) FROM residential_address"
            ).fetchone()[0]
        )
        fixture_rows = int(source_counts.get("sample_fixture", 0))
        print(f"address rows: {sum(source_counts.values()):,}; sources: {source_counts}")
        print(
            f"HDB source: {hdb_success:,}/{hdb_expected:,} resolved; "
            f"{hdb_failed:,} failed; database rows: {source_counts.get(HDB_SOURCE, 0):,}"
        )
        print(
            f"URA source: {source_counts.get(URA_SOURCE, 0):,}/{ura_expected:,} imported; "
            f"fixture rows: {fixture_rows:,}; invalid coordinates: {invalid_coordinates:,}; "
            f"duplicate postals: {duplicate_postals:,}"
        )
        errors: list[str] = []
        if args.require_complete:
            if hdb_success != hdb_expected or hdb_failed:
                errors.append("HDB source is incomplete or has failed resolutions")
            if source_counts.get(URA_SOURCE, 0) != ura_expected:
                errors.append("URA source is incomplete")
        if args.reject_fixtures and fixture_rows:
            errors.append("sample_fixture rows remain")
        if invalid_coordinates or duplicate_postals:
            errors.append("database contains invalid coordinates or duplicate postal keys")
        if errors:
            print("AUDIT FAILED: " + "; ".join(errors), file=sys.stderr)
            return 1
        print("AUDIT PASSED")
        return 0
    except (ConfigError, FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
