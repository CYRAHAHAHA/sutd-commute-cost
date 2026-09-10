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
    required = ("timezone", "destination", "experiment", "providers", "addresses", "observations_database")
    missing = [key for key in required if key not in config]
    if missing:
        raise ConfigError(f"Missing configuration keys: {', '.join(missing)}")
    try:
        ZoneInfo(config["timezone"])
    except Exception as exc:
        raise ConfigError(f"Unknown timezone: {config['timezone']}") from exc
    dates = config["experiment"].get("dates", [])
    if len(dates) != 10:
        raise ConfigError(f"The experiment must contain exactly 10 dates; found {len(dates)}")
    for value in dates:
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ConfigError(f"Experiment date is not YYYY-MM-DD: {value}") from exc
    for provider in ("GOOGLE", "ONEMAP"):
        spec = config["providers"].get(provider)
        if not spec or len(spec.get("times", [])) != 7:
            raise ConfigError(f"Provider {provider} must define exactly seven query times")
        if spec.get("time_semantics") not in {"ARRIVAL", "DEPARTURE"}:
            raise ConfigError(f"Provider {provider} has invalid time semantics")
        for value in spec["times"]:
            try:
                time.fromisoformat(value)
            except ValueError as exc:
                raise ConfigError(f"Invalid query time for {provider}: {value}") from exc
    threshold = config["experiment"].get("minimum_successful_samples")
    if not isinstance(threshold, int) or not 0 < threshold <= 70:
        raise ConfigError("experiment.minimum_successful_samples must be an integer from 1 to 70")


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


def query_datetimes(config: dict[str, Any], provider: str) -> list[tuple[str, str, datetime]]:
    zone = ZoneInfo(config["timezone"])
    spec = config["providers"][provider]
    result = []
    for service_date in dates(config):
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
