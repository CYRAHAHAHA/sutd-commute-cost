from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from commute.config import (
    ConfigError,
    expected_samples,
    google_sampling_settings,
    load_config,
    load_environment,
    minimum_successful_samples,
    resolve_path,
)
from commute.db import init_addresses_db, init_observations_db, iter_onemap_origins
from commute.runners import jobs_for_provider
from scripts.build_summary import build_summary

STATUS_CODES = {"SUCCESS": "S", "INSUFFICIENT_DATA": "I", "EXCLUDED": "X"}


def _compact_provider(provider: dict) -> list:
    return [
        STATUS_CODES[provider["status"]],
        provider["mean_seconds"],
        provider["median_seconds"],
        provider["min_seconds"],
        provider["max_seconds"],
        provider["successful_samples"],
        provider["expected_samples"],
    ]


def compact_summary(summary: dict) -> dict:
    """Create a compact row-oriented artifact instead of repeating JSON field names 94k times."""
    rows = []
    exclusion_codes = {"landed_home_excluded_from_scheduled_mapping": "L"}
    for postal_code, record in summary["postcodes"].items():
        exclusion_reason = record.get("onemap_exclusion_reason")
        rows.append(
            [
                postal_code,
                round(record["latitude"], 6),
                round(record["longitude"], 6),
                _compact_provider(record["google"]),
                _compact_provider(record["onemap"]),
                [STATUS_CODES[record["combined"]["status"]], record["combined"]["mean_seconds"]],
                record.get("onemap_group_representative"),
                record.get("onemap_group_size"),
                exclusion_codes.get(exclusion_reason),
            ]
        )
    return {
        "dataset_version": summary["dataset_version"],
        "generated_at": summary["generated_at"],
        "minimum_successful_samples": summary["minimum_successful_samples"],
        "format": {
            "postcodes_row": [
                "postal_code",
                "latitude",
                "longitude",
                "google",
                "onemap",
                "combined",
                "onemap_group_representative",
                "onemap_group_size",
                "onemap_exclusion_code",
            ],
            "provider_row": [
                "status_code",
                "mean_seconds",
                "median_seconds",
                "min_seconds",
                "max_seconds",
                "successful_samples",
                "expected_samples",
            ],
            "status_codes": {"S": "SUCCESS", "I": "INSUFFICIENT_DATA", "X": "EXCLUDED"},
            "onemap_exclusion_codes": {"L": "landed_home_excluded_from_scheduled_mapping"},
        },
        "postcodes": rows,
    }


def collection_completeness(config: dict) -> dict[str, dict[str, int]]:
    """Count expected and persisted job keys for the production populations."""
    addresses = init_addresses_db(resolve_path(config, config["addresses"]["database"]))
    observations = init_observations_db(resolve_path(config, config["observations_database"]))
    routed = list(iter_onemap_origins(addresses, config["addresses"]["include_confidence"], None, None))
    populations = {
        "ONEMAP": routed,
        "GOOGLE": [row for row in routed if row["google_sample_selected"]],
    }
    minimum_google_sample = int(
        config.get("google_sampling", {}).get(
            "minimum_production_sample_size",
            config.get("google_sampling", {}).get("sample_size", 0),
        )
    )
    result: dict[str, dict[str, int | bool]] = {}
    for provider, rows in populations.items():
        expected = {
            (job.postal_code, job.service_date, job.query_time)
            for job in jobs_for_provider(config, provider, rows)
        }
        actual = {
            (row[0], row[2], row[3])
            for row in observations.execute(
                "SELECT postal_code, provider, service_date, query_time FROM commute_observation WHERE provider=?",
                (provider,),
            )
        }
        matched = len(expected & actual)
        result[provider] = {
            "population": len(rows),
            "selection_ready": provider != "GOOGLE" or len(rows) >= minimum_google_sample,
            "minimum_population": minimum_google_sample if provider == "GOOGLE" else 0,
            "expected_jobs": len(expected),
            "persisted_jobs": matched,
            "missing_jobs": len(expected - actual),
        }
    return result


def build_public_dataset(config: dict, allow_incomplete: bool = False) -> tuple[Path, Path]:
    completeness = collection_completeness(config)
    website_data = resolve_path(config, "website/data")
    ready_path = website_data / "deployment-ready.json"
    incomplete = {
        provider: values
        for provider, values in completeness.items()
        if values["missing_jobs"] or not values["selection_ready"]
    }
    if incomplete and ready_path.exists():
        ready_path.unlink()
    if incomplete and not allow_incomplete:
        details = "; ".join(
            (
                f"{provider}: Google sample selection has "
                f"{values['population']:,}/{values['minimum_population']:,} origins"
                if not values["selection_ready"] and provider == "GOOGLE"
                else f"{provider}: {values['persisted_jobs']:,}/{values['expected_jobs']:,} jobs"
            )
            for provider, values in incomplete.items()
        )
        raise ConfigError(
            "Refusing production dataset build because collection is incomplete (" + details + "). "
            "Finish the configured provider runs, or use --allow-incomplete only for local preview."
        )
    for provider, values in completeness.items():
        print(
            f"{provider} dataset coverage: {values['persisted_jobs']:,}/{values['expected_jobs']:,} jobs "
            f"({values['missing_jobs']:,} missing)"
        )
    summary = build_summary(config)
    sampling = google_sampling_settings(config)
    collection_dates = sorted(
        {
            service_date
            for spec in config["providers"].values()
            for service_date in spec.get("dates", config["experiment"]["dates"])
        }
    )
    website_data.mkdir(parents=True, exist_ok=True)
    public_path = website_data / "commute-summary.json"
    public_path.write_text(json.dumps(compact_summary(summary), separators=(",", ":")) + "\n", encoding="utf-8")
    methodology = {
        "dataset_version": config.get("dataset_version"),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "timezone": config["timezone"],
        "collection_dates": collection_dates,
        "destination": config["destination"],
        "minimum_successful_samples": {
            provider: minimum_successful_samples(config, provider) for provider in ("GOOGLE", "ONEMAP")
        },
        "google_sampling": {
            "exclusion_radius_km": sampling.exclusion_radius_km,
            "sample_size": sampling.sample_size,
            "monthly_request_budget": sampling.monthly_request_budget,
            "sampling_seed": sampling.sampling_seed,
            "stratum_cell_degrees": sampling.stratum_cell_degrees,
        },
        "providers": {
            provider: {
                "time_semantics": spec["time_semantics"],
                "times": spec["times"],
                "dates": spec.get("dates", config["experiment"]["dates"]),
                "expected_samples": expected_samples(config, provider),
                "travel_mode": spec.get("travel_mode", spec.get("mode")),
                "origin_grouping": spec.get("origin_grouping"),
            }
            for provider, spec in config["providers"].items()
        },
        "calculation": {
            "provider_mean": "arithmetic mean of successful duration_seconds",
            "combined_mean": "(google_mean_seconds + onemap_mean_seconds) / 2",
            "round_trip_week": "one_way_mean_minutes × 2 × 5",
        },
        "raw_observations": {
            "browser_view": False,
            "reason": "The site ships compact summaries; raw rows remain in local SQLite and CSV export scripts.",
        },
    }
    methodology_path = website_data / "methodology.json"
    methodology_path.write_text(json.dumps(methodology, indent=2) + "\n", encoding="utf-8")
    if not incomplete:
        ready_path.write_text(
            json.dumps(
                {
                    "dataset_version": config.get("dataset_version"),
                    "verified_at": methodology["generated_at"],
                    "status": "COMPLETE",
                    "coverage": completeness,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return public_path, methodology_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the static postcode dataset.")
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Write a local preview even when configured collection jobs are missing; never use for deployment",
    )
    args = parser.parse_args()
    try:
        config = load_config()
        load_environment()
        paths = build_public_dataset(config, allow_incomplete=args.allow_incomplete)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("Wrote:")
    for path in paths:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
