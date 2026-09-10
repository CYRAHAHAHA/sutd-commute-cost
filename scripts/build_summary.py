from __future__ import annotations

import json
from datetime import datetime, timezone

from commute.aggregation.summary import aggregate_rows, validation_metrics
from commute.config import (
    expected_samples,
    load_config,
    load_environment,
    minimum_successful_samples,
    resolve_path,
)
from commute.db import init_addresses_db, init_observations_db, iter_addresses, iter_observations


def build_summary(config: dict) -> dict:
    address_connection = init_addresses_db(resolve_path(config, config["addresses"]["database"]))
    observation_connection = init_observations_db(resolve_path(config, config["observations_database"]))
    addresses = list(iter_addresses(address_connection, config["addresses"]["include_confidence"]))
    configured_keys = {
        (provider, service_date, query_time)
        for provider, spec in config["providers"].items()
        for service_date in spec.get("dates", config["experiment"]["dates"])
        for query_time in spec["times"]
    }
    selected_google_postcodes = {
        address["postal_code"] for address in addresses if address["google_sample_selected"]
    }
    observations = [
        row
        for row in iter_observations(observation_connection)
        if (row["provider"], row["service_date"], row["query_time"]) in configured_keys
        and (row["provider"] != "GOOGLE" or row["postal_code"] in selected_google_postcodes)
    ]
    direct_by_postal: dict[str, list] = {}
    for observation in observations:
        direct_by_postal.setdefault(observation["postal_code"], []).append(observation)
    derived_observations = []
    for address in addresses:
        postal_code = address["postal_code"]
        representative = address["onemap_group_representative"]
        if representative and representative != postal_code and not direct_by_postal.get(postal_code):
            for observation in direct_by_postal.get(representative, []):
                cloned = dict(observation)
                cloned["postal_code"] = postal_code
                derived_observations.append(cloned)
    observations.extend(derived_observations)
    rows = aggregate_rows(
        addresses,
        observations,
        {provider: minimum_successful_samples(config, provider) for provider in ("GOOGLE", "ONEMAP")},
        expected_samples={provider: expected_samples(config, provider) for provider in ("GOOGLE", "ONEMAP")},
    )
    return {
        "dataset_version": config.get("dataset_version"),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "minimum_successful_samples": {
            provider: minimum_successful_samples(config, provider) for provider in ("GOOGLE", "ONEMAP")
        },
        "validation": validation_metrics(rows),
        "postcodes": rows,
    }


def main() -> int:
    config = load_config()
    load_environment()
    result = build_summary(config)
    path = resolve_path(config, "data/summary.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(result['postcodes']):,} postcode summaries to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
