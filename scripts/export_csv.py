from __future__ import annotations

import argparse
import csv
from pathlib import Path

from commute.config import load_config, resolve_path
from commute.db import export_addresses_csv, init_addresses_db, init_observations_db, iter_observations


def write_observations(connection, provider: str, path: Path) -> None:
    rows = list(iter_observations(connection, provider=provider))
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "postal_code",
        "provider",
        "service_date",
        "query_time",
        "time_semantics",
        "origin_lat",
        "origin_lng",
        "destination_lat",
        "destination_lng",
        "duration_seconds",
        "status",
        "error_code",
        "error_message",
        "attempt_count",
        "collected_at",
        "collector_version",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows([[row[column] for column in columns] for row in rows])


def main() -> int:
    parser = argparse.ArgumentParser(description="Export local address and observation SQLite tables to CSV.")
    parser.add_argument("--output-dir", default="exports")
    args = parser.parse_args()
    config = load_config()
    output_dir = resolve_path(config, args.output_dir)
    addresses = init_addresses_db(resolve_path(config, config["addresses"]["database"]))
    observations = init_observations_db(resolve_path(config, config["observations_database"]))
    export_addresses_csv(addresses, output_dir / "residential_addresses.csv")
    write_observations(observations, "GOOGLE", output_dir / "google_observations.csv")
    write_observations(observations, "ONEMAP", output_dir / "onemap_observations.csv")
    print(f"Exported CSV files to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
