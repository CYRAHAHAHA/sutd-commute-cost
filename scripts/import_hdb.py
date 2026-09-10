from __future__ import annotations

import argparse
import sys
import time

import httpx

from commute.addresses.hdb import (
    HDB_SOURCE,
    address_from_hdb_result,
    read_hdb_postals_by_block,
    read_hdb_residential_csv,
)
from commute.collector import ProviderError, RateLimiter, call_with_retries
from commute.config import ConfigError, credential, load_config, load_environment, resolve_path
from commute.db import (
    get_address_resolution,
    init_addresses_db,
    save_address_resolution,
    upsert_address,
)
from commute.providers.onemap import OneMapClient


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Resolve official HDB residential property records into a resumable postal-code database."
    )
    result.add_argument(
        "--property-csv",
        default="data/input/HDBPropertyInformation.csv",
        help="Downloaded HDB Property Information CSV",
    )
    result.add_argument(
        "--existing-building-geojson",
        default="data/input/HDBExistingBuilding.geojson",
        help="Official HDB Existing Building GeoJSON used for postal fallback checks",
    )
    result.add_argument("--limit", type=int, help="Resolve at most this many residential source records")
    result.add_argument("--retry-failed", action="store_true", help="Retry previously terminally failed source records")
    result.add_argument("--dry-run", action="store_true", help="Report work without calling OneMap or writing rows")
    return result


def _now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _search_with_retry(client: OneMapClient, search_value: str) -> dict | None:
    try:
        return client.search(search_value)
    except httpx.HTTPError as exc:
        raise ProviderError(f"OneMap geocoding transport error: {exc}", retryable=True) from exc


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        config = load_config()
        candidates = read_hdb_residential_csv(args.property_csv, args.limit)
        if not candidates:
            raise ConfigError("No residential HDB candidates were found in the source CSV")
        connection = init_addresses_db(resolve_path(config, config["addresses"]["database"]))
        configured_rps = float(config["providers"]["ONEMAP"].get("requests_per_second", 1.0))
        postal_candidates_by_block = read_hdb_postals_by_block(args.existing_building_geojson)
        cached_success = 0
        retryable_failures = 0
        pending = 0
        for candidate in candidates:
            cached = get_address_resolution(connection, HDB_SOURCE, candidate.source_identifier)
            if cached and cached["status"] == "SUCCESS":
                cached_success += 1
            elif cached and not args.retry_failed:
                retryable_failures += 1
            else:
                pending += 1
        print(
            f"HDB residential candidates: {len(candidates):,}; cached success: {cached_success:,}; "
            f"previous failures skipped: {retryable_failures:,}; OneMap searches needed: {pending:,}"
        )
        print(
            f"Estimated minimum pacing time at {configured_rps:g} request/second: "
            f"{pending / configured_rps if configured_rps > 0 else 0:,.0f} seconds"
        )
        if args.dry_run:
            return 0

        load_environment()
        access_token = credential("ONEMAP_ACCESS_TOKEN")
        email = credential("ONEMAP_EMAIL")
        password = credential("ONEMAP_PASSWORD")
        if not access_token and (not email or not password):
            raise ConfigError("Set ONEMAP_ACCESS_TOKEN, or set both ONEMAP_EMAIL and ONEMAP_PASSWORD, in .env")
        base_url = credential("ONEMAP_BASE_URL") or "https://www.onemap.gov.sg"
        client = OneMapClient(email, password, base_url=base_url, access_token=access_token)
        spec = config["providers"]["ONEMAP"]
        limiter = RateLimiter(float(spec.get("requests_per_second", 1.0)))
        max_attempts = int(spec.get("max_attempts", 5))
        stats = {
            "success": 0,
            "failed": retryable_failures,
            "skipped": cached_success + retryable_failures,
            "requests": 0,
        }
        try:
            for index, candidate in enumerate(candidates, start=1):
                cached = get_address_resolution(connection, HDB_SOURCE, candidate.source_identifier)
                if cached and cached["status"] == "SUCCESS":
                    stats["success"] += 1
                    continue
                if cached and not args.retry_failed:
                    continue
                attempts = 0
                try:
                    address = None
                    query_used = candidate.search_value
                    last_error: ValueError | None = None
                    for search_value in candidate.search_values:

                        def request():
                            limiter.wait()
                            stats["requests"] += 1
                            return _search_with_retry(client, search_value)

                        result, variant_attempts = call_with_retries(request, max_attempts)
                        attempts += variant_attempts
                        if not result:
                            last_error = ValueError(f"OneMap returned no result for {search_value}")
                            continue
                        try:
                            address = address_from_hdb_result(candidate, result)
                            query_used = search_value
                            break
                        except ValueError as exc:
                            last_error = exc
                    if address is None:
                        for postal in postal_candidates_by_block.get(candidate.block_number, ()):

                            def request_postal():
                                limiter.wait()
                                stats["requests"] += 1
                                return _search_with_retry(client, postal)

                            result, variant_attempts = call_with_retries(request_postal, max_attempts)
                            attempts += variant_attempts
                            if not result:
                                continue
                            try:
                                address = address_from_hdb_result(candidate, result)
                                query_used = postal
                                break
                            except ValueError as exc:
                                last_error = exc
                    if address is None:
                        raise last_error or ValueError(f"OneMap could not resolve {candidate.search_value}")
                    save_address_resolution(
                        connection,
                        source=HDB_SOURCE,
                        source_identifier=candidate.source_identifier,
                        search_value=query_used,
                        status="SUCCESS",
                        postal_code=address.postal_code,
                        latitude=address.latitude,
                        longitude=address.longitude,
                        attempt_count=attempts,
                        resolved_at=_now_utc(),
                    )
                    upsert_address(connection, address, _now_utc())
                    connection.commit()
                    stats["success"] += 1
                except Exception as exc:
                    provider_error = exc if isinstance(exc, ProviderError) else ProviderError(str(exc), retryable=False)
                    save_address_resolution(
                        connection,
                        source=HDB_SOURCE,
                        source_identifier=candidate.source_identifier,
                        search_value=candidate.search_value,
                        status="FAILED",
                        postal_code=None,
                        latitude=None,
                        longitude=None,
                        attempt_count=attempts or max_attempts,
                        resolved_at=_now_utc(),
                        error_code=provider_error.error_code or "GEOCODE_FAILED",
                        error_message=str(provider_error)[:1000],
                    )
                    stats["failed"] += 1
                if index == 1 or index % 25 == 0 or index == len(candidates):
                    print(
                        f"HDB geocoding {index:,} / {len(candidates):,}; "
                        f"{stats['success']:,} success, {stats['failed']:,} failed, "
                        f"{stats['requests']:,} OneMap searches"
                    )
        except KeyboardInterrupt:
            print("HDB geocoding interrupted; completed source records are persisted", file=sys.stderr)
            return 130
        print(
            f"HDB import complete: {stats['success']:,} resolved, {stats['failed']:,} failed, "
            f"{stats['requests']:,} OneMap searches"
        )
        return 0 if stats["failed"] == 0 else 1
    except (ConfigError, FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
