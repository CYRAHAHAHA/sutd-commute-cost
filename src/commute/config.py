from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


class ConfigError(ValueError):
    """Raised when the version-controlled experiment configuration is invalid."""


@dataclass(frozen=True)
class Destination:
    name: str
    latitude: float | None
    longitude: float | None


@dataclass(frozen=True)
class GoogleSamplingSettings:
    exclusion_radius_km: float
    sample_size: int
    monthly_request_budget: int
    sampling_seed: int
    stratum_cell_degrees: float


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else project_root() / "config" / "project.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Configuration is not valid JSON: {config_path}: {exc}") from exc
    validate_config(config)
    config["_path"] = str(config_path)
    return config


def validate_config(config: dict[str, Any]) -> None:
    required = (
        "timezone",
        "destination",
        "experiment",
        "providers",
        "google_sampling",
        "addresses",
        "observations_database",
    )
    missing = [key for key in required if key not in config]
    if missing:
        raise ConfigError(f"Missing configuration keys: {', '.join(missing)}")
    try:
        ZoneInfo(config["timezone"])
    except Exception as exc:
        raise ConfigError(f"Unknown timezone: {config['timezone']}") from exc
    experiment_dates = config["experiment"].get("dates", [])
    if len(experiment_dates) != 10:
        raise ConfigError(f"The experiment must contain exactly 10 dates; found {len(experiment_dates)}")
    for value in experiment_dates:
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ConfigError(f"Experiment date is not YYYY-MM-DD: {value}") from exc
    for provider in ("GOOGLE", "ONEMAP"):
        spec = config["providers"].get(provider)
        if not spec or not spec.get("times"):
            raise ConfigError(f"Provider {provider} must define at least one query time")
        if spec.get("time_semantics") not in {"ARRIVAL", "DEPARTURE"}:
            raise ConfigError(f"Provider {provider} has invalid time semantics")
        provider_dates = spec.get("dates", experiment_dates)
        if not provider_dates or any(value not in experiment_dates for value in provider_dates):
            raise ConfigError(f"Provider {provider} dates must be a non-empty subset of experiment.dates")
        for value in spec["times"]:
            try:
                time.fromisoformat(value)
            except ValueError as exc:
                raise ConfigError(f"Invalid query time for {provider}: {value}") from exc
    thresholds = config["experiment"].get("minimum_successful_samples_by_provider", {})
    for provider in ("GOOGLE", "ONEMAP"):
        expected = len(config["providers"][provider].get("dates", experiment_dates)) * len(
            config["providers"][provider]["times"]
        )
        threshold = thresholds.get(provider, config["experiment"].get("minimum_successful_samples"))
        if not isinstance(threshold, int) or not 0 < threshold <= expected:
            raise ConfigError(f"minimum successful samples for {provider} must be an integer from 1 to {expected}")
    sampling = config["google_sampling"]
    if float(sampling.get("exclusion_radius_km", 0)) < 0:
        raise ConfigError("google_sampling.exclusion_radius_km cannot be negative")
    if int(sampling.get("sample_size", 0)) < 1:
        raise ConfigError("google_sampling.sample_size must be positive")
    if int(sampling.get("monthly_request_budget", 0)) < 1:
        raise ConfigError("google_sampling.monthly_request_budget must be positive")


def destination(config: dict[str, Any], require_coordinates: bool = False) -> Destination:
    raw = config["destination"]
    result = Destination(raw["name"], raw.get("latitude"), raw.get("longitude"))
    if require_coordinates and (result.latitude is None or result.longitude is None):
        raise ConfigError(
            "SUTD destination coordinates are not configured. Edit config/project.json and set "
            "destination.latitude and destination.longitude before collecting routes."
        )
    if result.latitude is not None and not -90 <= float(result.latitude) <= 90:
        raise ConfigError("destination.latitude must be between -90 and 90")
    if result.longitude is not None and not -180 <= float(result.longitude) <= 180:
        raise ConfigError("destination.longitude must be between -180 and 180")
    return result


def dates(config: dict[str, Any]) -> list[str]:
    return list(config["experiment"]["dates"])


def expected_samples(config: dict[str, Any], provider: str) -> int:
    spec = config["providers"][provider]
    return len(spec.get("dates", dates(config))) * len(spec["times"])


def minimum_successful_samples(config: dict[str, Any], provider: str) -> int:
    thresholds = config["experiment"].get("minimum_successful_samples_by_provider", {})
    return int(thresholds.get(provider, config["experiment"]["minimum_successful_samples"]))


def google_sampling_settings(config: dict[str, Any]) -> GoogleSamplingSettings:
    raw = config["google_sampling"]
    return GoogleSamplingSettings(
        exclusion_radius_km=float(os.getenv("SUTD_EXCLUSION_RADIUS_KM", raw["exclusion_radius_km"])),
        sample_size=int(os.getenv("GOOGLE_SAMPLE_SIZE", raw["sample_size"])),
        monthly_request_budget=int(os.getenv("GOOGLE_MONTHLY_REQUEST_BUDGET", raw["monthly_request_budget"])),
        sampling_seed=int(os.getenv("GOOGLE_SAMPLING_SEED", raw["sampling_seed"])),
        stratum_cell_degrees=float(raw.get("stratum_cell_degrees", 0.02)),
    )


def query_datetimes(config: dict[str, Any], provider: str) -> list[tuple[str, str, datetime]]:
    zone = ZoneInfo(config["timezone"])
    spec = config["providers"][provider]
    result = []
    for service_date in spec.get("dates", dates(config)):
        for query_time in spec["times"]:
            local = datetime.fromisoformat(f"{service_date}T{query_time}:00").replace(tzinfo=zone)
            result.append((service_date, query_time, local))
    return result


def as_utc_rfc3339(value: datetime) -> str:
    return value.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")


def load_environment(root: Path | None = None) -> None:
    load_dotenv((root or project_root()) / ".env")


def credential(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value else None


def resolve_path(config: dict[str, Any], configured_path: str) -> Path:
    path = Path(configured_path)
    return path if path.is_absolute() else project_root() / path
