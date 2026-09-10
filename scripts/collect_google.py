from __future__ import annotations

import argparse
import sys

from commute.collector import ProviderError
from commute.config import ConfigError, credential, destination, load_config, load_environment, resolve_path
from commute.db import init_addresses_db, init_observations_db, iter_addresses
from commute.providers.google import GoogleRoutesClient
from commute.runners import collect_google, estimate_google_requests


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Collect Google transit observations (server-side only).")
    result.add_argument("--limit", type=int, help="Maximum number of residential origins to process")
    result.add_argument("--postal-code", help="Process exactly one postal code")
    result.add_argument("--all", action="store_true", help="Select all included residential origins")
    result.add_argument("--confirm-large-run", action="store_true", help="Required with --all")
    result.add_argument("--dry-run", action="store_true", help="Print workload and make no API calls")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.all and not args.confirm_large_run:
        print("Refusing full Google collection without --confirm-large-run.", file=sys.stderr)
        return 2
    if not args.all and args.limit is None and not args.postal_code:
        print("Choose --limit, --postal-code, or --all. Full runs also require --confirm-large-run.", file=sys.stderr)
        return 2
    try:
        config = load_config()
        destination(config, require_coordinates=True)
        load_environment()
        api_key = credential("GOOGLE_MAPS_API_KEY")
        if not api_key and not args.dry_run:
            raise ConfigError("GOOGLE_MAPS_API_KEY is not set in .env")
        address_connection = init_addresses_db(resolve_path(config, config["addresses"]["database"]))
        rows = list(
            iter_addresses(address_connection, config["addresses"]["include_confidence"], args.limit, args.postal_code)
        )
        if not rows:
            print("No matching residential addresses found.", file=sys.stderr)
            return 1
        estimated = len(rows) * 70
        print(f"GOOGLE workload: {len(rows):,} residential origins × 70 = {estimated:,} route elements")
        print(f"Estimated matrix requests at configured batch size: {estimate_google_requests(len(rows), config):,}")
        if args.dry_run:
            return 0
        observation_connection = init_observations_db(resolve_path(config, config["observations_database"]))
        client = GoogleRoutesClient(api_key)
        try:
            collect_google(rows, config, observation_connection, client)
        except KeyboardInterrupt:
            print("GOOGLE interrupted; successful and terminal observations are already persisted")
        return 0
    except (ConfigError, ProviderError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
