from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import httpx

from ..collector import ProviderError


@dataclass(frozen=True)
class MatrixResult:
    duration_seconds: int | None
    status: str
    error_code: str | None = None
    error_message: str | None = None


def parse_duration(value: str | int | float | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = re.fullmatch(r"\s*(\d+)(?:\.\d+)?s\s*", value)
    return int(match.group(1)) if match else None


def _stream_json(text: str) -> list[dict[str, Any]]:
    try:
        decoded = json.loads(text)
        if isinstance(decoded, list):
            return [item for item in decoded if isinstance(item, dict)]
        return [decoded] if isinstance(decoded, dict) else []
    except json.JSONDecodeError:
        values = []
        for line in text.splitlines():
            line = line.strip()
            if line:
                values.append(json.loads(line))
        return values


class GoogleRoutesClient:
    endpoint_path = "/distanceMatrix/v2:computeRouteMatrix"

    def __init__(
        self, api_key: str, base_url: str = "https://routes.googleapis.com", client: httpx.Client | None = None
    ):
        if not api_key:
            raise ValueError("GOOGLE_MAPS_API_KEY is required for Google collection")
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=60.0)
        self.base_url = base_url.rstrip("/")

    @staticmethod
    def _waypoint(latitude: float, longitude: float) -> dict[str, Any]:
        return {"waypoint": {"location": {"latLng": {"latitude": latitude, "longitude": longitude}}}}

    def compute_route_matrix(
        self,
        origins: Iterable[tuple[float, float]],
        destination: tuple[float, float],
        arrival_time: str,
    ) -> dict[int, MatrixResult]:
        origin_values = list(origins)
        body = {
            "origins": [self._waypoint(lat, lng) for lat, lng in origin_values],
            "destinations": [self._waypoint(*destination)],
            "travelMode": "TRANSIT",
            "arrivalTime": arrival_time,
            "languageCode": "en-US",
            "regionCode": "SG",
        }
        response = self.client.post(
            f"{self.base_url}{self.endpoint_path}",
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": "originIndex,destinationIndex,status,condition,duration",
            },
            json=body,
        )
        if response.status_code >= 400:
            code = None
            try:
                code = response.json().get("error", {}).get("status")
            except (ValueError, AttributeError):
                pass
            raise ProviderError(
                f"Google Routes HTTP {response.status_code}: {response.text[:500]}",
                http_status=response.status_code,
                error_code=code,
            )
        result: dict[int, MatrixResult] = {}
        for element in _stream_json(response.text):
            origin_index = element.get("originIndex")
            if not isinstance(origin_index, int):
                continue
            status = element.get("status") or {}
            code = status.get("code") if isinstance(status, dict) else None
            message = status.get("message") if isinstance(status, dict) else None
            condition = element.get("condition")
            duration = parse_duration(element.get("duration"))
            if code not in (None, 0) or condition == "ROUTE_NOT_FOUND" or duration is None:
                result[origin_index] = MatrixResult(None, "FAILED", str(code or condition or "NO_DURATION"), message)
            else:
                result[origin_index] = MatrixResult(duration, "SUCCESS")
        for index in range(len(origin_values)):
            result.setdefault(index, MatrixResult(None, "FAILED", "MISSING_ELEMENT", "No matrix element returned"))
        return result
