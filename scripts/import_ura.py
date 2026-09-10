from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from commute.addresses.ura import URA_SOURCE, iter_ura_private_addresses
from commute.config import ConfigError, load_config, resolve_path
from commute.db import init_addresses_db, upsert_address


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Import official URA private-residential postal points.")
    result.add_argument(
        "--geojson",
        default="data/input/URA_NoOfDwellingUnits.geojson",
        help="Downloaded URA No of Dwelling Units GeoJSON",
    )
    result.add_argument("--limit", type=int, help="Import at most this many private-residential postal points")
    result.add_argument("--dry-run", action="store_true", help="Validate and count rows without writing SQLite")
    return result


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        config = load_config()
        rows = iter_ura_private_addresses(args.geojson, args.limit)
        connection = init_addresses_db(resolve_path(config, config["addresses"]["database"]))
        imported = 0
        skipped_hdb_overlap = 0
        skipped_duplicate = 0
        for address in rows:
            existing = connection.execute(
                "SELECT source FROM residential_address WHERE postal_code=?", (address.postal_code,)
            ).fetchone()
            if existing and existing["source"] == "hdb_property_information":
                skipped_hdb_overlap += 1
                continue
            if existing and existing["source"] == URA_SOURCE:
                skipped_duplicate += 1
                continue
            if args.dry_run:
                imported += 1
                continue
            upsert_address(connection, address, _timestamp())
            connection.commit()
            imported += 1
        print(
            f"URA private-residential source: {imported:,} importable; "
            f"{skipped_hdb_overlap:,} HDB overlaps retained as HDB; "
            f"{skipped_duplicate:,} existing URA duplicates"
        )
        return 0
    except (ConfigError, FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
