from __future__ import annotations

import argparse
import sys
import time

from commute.collector import ProviderError
from commute.config import (
    ConfigError,
    credential,
    destination,
    expected_samples,
    load_config,
    load_environment,
    resolve_path,
)
from commute.db import init_addresses_db, init_observations_db, iter_addresses
from commute.providers.onemap import OneMapClient, token_expiry
from commute.runners import collect_onemap


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Collect OneMap public-transport observations.")
    result.add_argument("--limit", type=int, help="Maximum number of residential origins to process")
    result.add_argument("--postal-code", help="Process exactly one postal code")
    result.add_argument("--all", action="store_true", help="Select all included residential origins")
    result.add_argument("--dry-run", action="store_true", help="Print workload and make no API calls")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not args.all and args.limit is None and not args.postal_code:
        print("Choose --limit, --postal-code, or --all.", file=sys.stderr)
        return 2
    try:
        config = load_config()
        destination(config, require_coordinates=True)
        load_environment()
        access_token = credential("ONEMAP_ACCESS_TOKEN")
        email = credential("ONEMAP_EMAIL")
        password = credential("ONEMAP_PASSWORD")
        if not access_token and (not email or not password) and not args.dry_run:
            raise ConfigError("Set ONEMAP_ACCESS_TOKEN, or set both ONEMAP_EMAIL and ONEMAP_PASSWORD, in .env")
        address_connection = init_addresses_db(resolve_path(config, config["addresses"]["database"]))
        rows = list(
            iter_addresses(address_connection, config["addresses"]["include_confidence"], args.limit, args.postal_code)
        )
        if not rows:
            print("No matching residential addresses found.", file=sys.stderr)
            return 1
        expected = expected_samples(config, "ONEMAP")
        route_calls = len(rows) * expected
        print(f"ONEMAP workload: {len(rows):,} residential origins × {expected} = {route_calls:,} route calls")
        if access_token and not email and not password:
            expiry = token_expiry(access_token)
            requests_per_second = float(config["providers"]["ONEMAP"].get("requests_per_second", 1.0))
            if expiry and requests_per_second > 0:
                remaining_seconds = expiry - time.time()
                estimated_seconds = route_calls / requests_per_second
                print(
                    f"ONEMAP token expiry: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(expiry))}; "
                    f"estimated pacing time: {estimated_seconds:,.0f} seconds"
                )
                if args.all and not args.dry_run and remaining_seconds < estimated_seconds:
                    raise ConfigError(
                        "ONEMAP_ACCESS_TOKEN will expire before this full workload can finish. "
                        "Refresh the token or run a bounded resumable chunk with --limit."
                    )
        if args.dry_run:
            return 0
        observation_connection = init_observations_db(resolve_path(config, config["observations_database"]))
        client = OneMapClient(
            email,
            password,
            base_url=credential("ONEMAP_BASE_URL") or "https://www.onemap.gov.sg",
            access_token=access_token,
        )
        collect_onemap(rows, config, observation_connection, client)
        return 0
    except (ConfigError, ProviderError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
