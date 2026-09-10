from __future__ import annotations

import json
from datetime import datetime, timezone

from commute.aggregation.summary import aggregate_rows
from commute.config import load_config, resolve_path
from commute.db import init_addresses_db, init_observations_db, iter_addresses, iter_observations


def build_summary(config: dict) -> dict:
    address_connection = init_addresses_db(resolve_path(config, config["addresses"]["database"]))
    observation_connection = init_observations_db(resolve_path(config, config["observations_database"]))
    addresses = list(iter_addresses(address_connection, config["addresses"]["include_confidence"]))
    observations = list(iter_observations(observation_connection))
    rows = aggregate_rows(
        addresses,
        observations,
        int(config["experiment"]["minimum_successful_samples"]),
        expected_samples=70,
    )
    return {
        "dataset_version": config.get("dataset_version"),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "minimum_successful_samples": config["experiment"]["minimum_successful_samples"],
        "postcodes": rows,
    }


def main() -> int:
    config = load_config()
    result = build_summary(config)
    path = resolve_path(config, "data/summary.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(result['postcodes']):,} postcode summaries to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
