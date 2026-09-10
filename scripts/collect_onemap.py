from __future__ import annotations

import argparse
import copy
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
from commute.db import init_addresses_db, init_observations_db, iter_onemap_origins
from commute.preflight import evenly_spaced_sample
from commute.providers.onemap import OneMapClient, token_expiry
from commute.runners import collect_onemap


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Collect OneMap public-transport observations.")
    result.add_argument("--limit", type=int, help="Maximum number of residential origins to process")
    result.add_argument("--postal-code", help="Process exactly one postal code")
    result.add_argument(
        "--date",
        action="append",
        dest="dates",
        help="Collect only this configured service date; repeat for multiple dates",
    )
    result.add_argument("--all", action="store_true", help="Select all included residential origins")
    result.add_argument("--dry-run", action="store_true", help="Print workload and make no API calls")
    result.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip the distributed quality gate before --all (requires deliberate review)",
    )
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
        if args.dates:
            configured_dates = set(config["providers"]["ONEMAP"].get("dates", config["experiment"]["dates"]))
            invalid_dates = sorted(set(args.dates) - configured_dates)
            if invalid_dates:
                raise ConfigError(
                    "--date must refer to a configured OneMap date; invalid date(s): " + ", ".join(invalid_dates)
                )
            run_config = copy.deepcopy(config)
            run_config["providers"]["ONEMAP"]["dates"] = args.dates
        else:
            run_config = config
        access_token = credential("ONEMAP_ACCESS_TOKEN")
        email = credential("ONEMAP_EMAIL")
        password = credential("ONEMAP_PASSWORD")
        if not access_token and (not email or not password) and not args.dry_run:
            raise ConfigError("Set ONEMAP_ACCESS_TOKEN, or set both ONEMAP_EMAIL and ONEMAP_PASSWORD, in .env")
        address_connection = init_addresses_db(resolve_path(config, config["addresses"]["database"]))
        rows = list(
            iter_onemap_origins(
                address_connection, config["addresses"]["include_confidence"], args.limit, args.postal_code
            )
        )
        if not rows:
            print("No matching residential addresses found.", file=sys.stderr)
            return 1
        expected = expected_samples(run_config, "ONEMAP")
        route_calls = len(rows) * expected
        print(f"ONEMAP workload: {len(rows):,} residential origins × {expected} = {route_calls:,} route calls")
        spec = run_config["providers"]["ONEMAP"]
        if args.dates:
            print("ONEMAP dates: " + ", ".join(args.dates))
        requests_per_second = float(spec.get("requests_per_second", 1.0))
        workers = max(1, int(spec.get("parallel_workers", 1)))
        max_in_flight = max(workers, int(spec.get("max_in_flight", workers * 4)))
        print(
            f"ONEMAP execution: {workers} workers, {max_in_flight} max in-flight, "
            f"one shared limiter at {requests_per_second:g} requests/sec; "
            f"pacing floor {route_calls / requests_per_second / 3600:.2f} hours"
        )
        if access_token and not (email and password):
            expiry = token_expiry(access_token)
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
        if args.all and not args.skip_preflight:
            preflight_size = max(1, int(spec.get("preflight_sample_size", 30)))
            preflight_rows = evenly_spaced_sample(rows, preflight_size)
            print(
                f"ONEMAP preflight: {len(preflight_rows):,} distributed origins × {len(spec['times'])} times; "
                "persisting results before the full run"
            )
            preflight_stats = collect_onemap(preflight_rows, run_config, observation_connection, client)
            attempted = preflight_stats["success"] + preflight_stats["failed"] + preflight_stats["skipped"]
            failure_rate = preflight_stats["failed"] / attempted if attempted else 1.0
            max_failure_rate = float(spec.get("preflight_max_failure_rate", 0.2))
            print(
                f"ONEMAP preflight result: {preflight_stats['success']:,} success, "
                f"{preflight_stats['failed']:,} failed, {preflight_stats['skipped']:,} skipped; "
                f"failure rate {failure_rate:.1%} (limit {max_failure_rate:.1%})"
            )
            if failure_rate > max_failure_rate:
                raise ConfigError(
                    "Refusing full OneMap collection: distributed preflight failure rate "
                    f"{failure_rate:.1%} exceeds configured limit {max_failure_rate:.1%}. "
                    "Wait for the service date to become routable, or use --skip-preflight only after review."
                )
        elif args.all and args.skip_preflight:
            print("ONEMAP preflight skipped by explicit --skip-preflight")
        collect_onemap(rows, run_config, observation_connection, client)
        return 0
    except (ConfigError, ProviderError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
