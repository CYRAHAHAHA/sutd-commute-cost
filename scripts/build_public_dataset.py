from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from commute.config import load_config, resolve_path
from scripts.build_summary import build_summary


def build_public_dataset(config: dict) -> tuple[Path, Path]:
    summary = build_summary(config)
    website_data = resolve_path(config, "website/data")
    website_data.mkdir(parents=True, exist_ok=True)
    public_path = website_data / "commute-summary.json"
    public_path.write_text(json.dumps(summary, separators=(",", ":")) + "\n", encoding="utf-8")
    methodology = {
        "dataset_version": config.get("dataset_version"),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "timezone": config["timezone"],
        "collection_dates": config["experiment"]["dates"],
        "destination": config["destination"],
        "minimum_successful_samples": config["experiment"]["minimum_successful_samples"],
        "providers": {
            provider: {
                "time_semantics": spec["time_semantics"],
                "times": spec["times"],
                "expected_samples": len(config["experiment"]["dates"]) * len(spec["times"]),
                "travel_mode": spec.get("travel_mode", spec.get("mode")),
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
    return public_path, methodology_path


def main() -> int:
    config = load_config()
    paths = build_public_dataset(config)
    print("Wrote:")
    for path in paths:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
