from __future__ import annotations

import argparse
import sys

from commute.addresses.discovery import discovered_timestamp, read_source_csv, resolve_with_onemap
from commute.config import ConfigError, credential, load_config, load_environment, resolve_path
from commute.db import init_addresses_db, upsert_address
from commute.providers.onemap import OneMapClient


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Import a residential source CSV and optionally resolve missing coordinates with OneMap."
    )
    result.add_argument(
        "--input",
        default="data/sample_residential_addresses.csv",
        help="CSV with postal_code,address,latitude,longitude,residential_type,source,source_identifier,confidence",
    )
    result.add_argument("--source", default="csv", help="Provenance label for the imported source")
    result.add_argument("--limit", type=int, help="Import at most this many source rows")
    result.add_argument("--resolve-missing", action="store_true", help="Use OneMap search for missing coordinates")
    result.add_argument("--dry-run", action="store_true", help="Validate and report rows without writing SQLite")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        config = load_config()
        source_rows = read_source_csv(args.input, args.source)
        if args.limit is not None:
            source_rows = source_rows[: args.limit]
        client = None
        if args.resolve_missing:
            load_environment()
            access_token = credential("ONEMAP_ACCESS_TOKEN")
            email, password = credential("ONEMAP_EMAIL"), credential("ONEMAP_PASSWORD")
            if not access_token and (not email or not password):
                raise ConfigError(
                    "--resolve-missing requires ONEMAP_ACCESS_TOKEN, or both ONEMAP_EMAIL and ONEMAP_PASSWORD, in .env"
                )
            client = OneMapClient(email, password, access_token=access_token)
        resolved = [resolve_with_onemap(row, client) if client else row for row in source_rows]
        counts: dict[str, int] = {}
        for row in resolved:
            counts[row.confidence] = counts.get(row.confidence, 0) + 1
        print(f"Loaded {len(resolved):,} address candidates: {counts}")
        if args.dry_run:
            return 0
        connection = init_addresses_db(resolve_path(config, config["addresses"]["database"]))
        timestamp = discovered_timestamp()
        for row in resolved:
            upsert_address(connection, row, timestamp)
            connection.commit()
        print(f"Wrote {len(resolved):,} deduplicated rows to {config['addresses']['database']}")
        return 0
    except (ConfigError, FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
