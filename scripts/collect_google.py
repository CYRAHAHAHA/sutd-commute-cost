from __future__ import annotations

import argparse
import sys

from commute.collector import GoogleBudgetExceeded, ProviderError
from commute.config import (
    ConfigError,
    credential,
    destination,
    expected_samples,
    google_sampling_settings,
    load_config,
    load_environment,
    resolve_path,
)
from commute.db import google_usage_events, init_addresses_db, init_observations_db, iter_addresses
from commute.providers.google import GoogleRoutesClient
from commute.runners import collect_google, estimate_google_requests, pending_google_events
from commute.sampling import prepare_google_population


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Collect Google transit observations (server-side only).")
    result.add_argument("--limit", type=int, help="Maximum number of residential origins to process")
    result.add_argument("--postal-code", help="Process exactly one postal code")
    result.add_argument("--all", action="store_true", help="Select all included residential origins")
    result.add_argument("--confirm-large-run", action="store_true", help="Required with --all")
    result.add_argument(
        "--override-budget",
        action="store_true",
        help="Explicitly allow Google usage above GOOGLE_MONTHLY_REQUEST_BUDGET",
    )
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
        destination_value = destination(config, require_coordinates=True)
        load_environment()
        settings = google_sampling_settings(config)
        api_key = credential("GOOGLE_MAPS_API_KEY")
        if not api_key and not args.dry_run:
            raise ConfigError("GOOGLE_MAPS_API_KEY is not set in .env")
        address_connection = init_addresses_db(resolve_path(config, config["addresses"]["database"]))
        rows = list(
            iter_addresses(address_connection, config["addresses"]["include_confidence"], None, args.postal_code)
        )
        if not rows:
            print("No matching residential addresses found.", file=sys.stderr)
            return 1
        sample_limit = 1 if args.postal_code else args.limit or settings.sample_size
        selected, population_counts = prepare_google_population(
            address_connection,
            rows,
            (float(destination_value.latitude), float(destination_value.longitude)),
            settings,
            sample_limit=sample_limit,
            persist=not args.dry_run,
        )
        expected = expected_samples(config, "GOOGLE")
        estimated = len(selected) * expected
        print(
            f"GOOGLE population: {population_counts['population']:,}; "
            f"excluded within {settings.exclusion_radius_km:g} km: {population_counts['excluded']:,}; "
            f"eligible: {population_counts['eligible']:,}; selected: {population_counts['selected']:,}"
        )
        print(f"GOOGLE workload: {len(selected):,} sampled origins × {expected} = {estimated:,} route elements")
        print(
            f"Estimated matrix HTTP requests at configured batch size: "
            f"{estimate_google_requests(len(selected), config):,}"
        )
        observation_connection = init_observations_db(resolve_path(config, config["observations_database"]))
        current_usage = google_usage_events(observation_connection)
        pending = pending_google_events(selected, config, observation_connection)
        print(
            f"Google budget: {current_usage:,} attempted elements used + {pending:,} pending "
            f"of {settings.monthly_request_budget:,}"
        )
        if not args.override_budget and current_usage + pending > settings.monthly_request_budget:
            raise GoogleBudgetExceeded(current_usage, pending, settings.monthly_request_budget)
        if args.dry_run:
            return 0
        if not selected:
            print("No eligible Google origins remain after the configured exclusion.")
            return 0
        client = GoogleRoutesClient(api_key)
        try:
            collect_google(
                selected,
                config,
                observation_connection,
                client,
                budget_override=args.override_budget,
            )
        except KeyboardInterrupt:
            print("GOOGLE interrupted; successful and terminal observations are already persisted")
        return 0
    except (ConfigError, ProviderError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
