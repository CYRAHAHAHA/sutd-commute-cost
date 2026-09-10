from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx

from ..collector import ProviderError


def parse_total_time(payload: Any) -> int | None:
    """Read OneMap's route_summary.total_time, tolerating minor response-shape variations."""
    if isinstance(payload, dict):
        for key in ("total_time", "totalTime", "duration", "duration_seconds"):
            value = payload.get(key)
            if isinstance(value, (int, float)):
                return int(value)
        for key in ("route_summary", "routeSummary", "plan", "itineraries", "routes"):
            if key in payload:
                found = parse_total_time(payload[key])
                if found is not None:
                    return found
    elif isinstance(payload, list):
        for value in payload:
            found = parse_total_time(value)
            if found is not None:
                return found
    return None


class OneMapClient:
    def __init__(
        self,
        email: str,
        password: str,
        base_url: str = "https://www.onemap.gov.sg",
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
    ):
        if not email or not password:
            raise ValueError("ONEMAP_EMAIL and ONEMAP_PASSWORD are required for OneMap collection")
        self.email = email
        self.password = password
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=60.0)
        self.clock = clock
        self._token: str | None = None
        self._expiry: float = 0

    def authenticate(self, force: bool = False) -> str:
        if self._token and not force and self.clock() < self._expiry - 60:
            return self._token
        response = self.client.post(
            f"{self.base_url}/api/auth/post/getToken",
            json={"email": self.email, "password": self.password},
        )
        if response.status_code >= 400:
            raise ProviderError(
                f"OneMap authentication HTTP {response.status_code}: {response.text[:500]}",
                http_status=response.status_code,
                error_code="AUTHENTICATION_FAILED",
            )
        payload = response.json()
        token = payload.get("access_token")
        expiry = payload.get("expiry_timestamp")
        if not token:
            raise ProviderError(
                "OneMap authentication response did not contain access_token", error_code="AUTHENTICATION_FAILED"
            )
        self._token = str(token)
        self._expiry = float(expiry or (self.clock() + 3 * 24 * 3600))
        return self._token

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        token = self.authenticate()
        refreshed = False
        while True:
            response = self.client.get(f"{self.base_url}{path}", headers={"Authorization": token}, params=params)
            if response.status_code == 401 and not refreshed:
                token = self.authenticate(force=True)
                refreshed = True
                continue
            break
        if response.status_code >= 400:
            raise ProviderError(
                f"OneMap HTTP {response.status_code}: {response.text[:500]}",
                http_status=response.status_code,
                error_code="ROUTE_NOT_FOUND" if response.status_code == 404 else None,
            )
        payload = response.json()
        if isinstance(payload, dict) and payload.get("error"):
            error = str(payload["error"])
            if "expired" in error.lower() and not refreshed:
                token = self.authenticate(force=True)
                response = self.client.get(
                    f"{self.base_url}{path}", headers={"Authorization": token}, params=params
                )
                payload = response.json()
                if not (isinstance(payload, dict) and payload.get("error")):
                    return payload
                error = str(payload["error"])
            raise ProviderError(error, error_code="AUTHENTICATION_FAILED", retryable=False)
        return payload

    def search(self, search_value: str) -> dict[str, Any] | None:
        payload = self._get(
            "/api/common/elastic/search",
            {"searchVal": search_value, "returnGeom": "Y", "getAddrDetails": "Y", "pageNum": 1},
        )
        results = payload.get("results", []) if isinstance(payload, dict) else []
        return results[0] if results else None

    def route(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        service_date: str,
        query_time: str,
        max_walk_distance: int = 1000,
        num_itineraries: int = 1,
    ) -> int:
        date_value = datetime.strptime(service_date, "%Y-%m-%d").strftime("%m-%d-%Y")
        payload = self._get(
            "/api/public/routingsvc/route",
            {
                "start": f"{start[0]},{start[1]}",
                "end": f"{end[0]},{end[1]}",
                "routeType": "pt",
                "mode": "TRANSIT",
                "date": date_value,
                "time": f"{query_time}:00",
                "maxWalkDistance": max_walk_distance,
                "numItineraries": num_itineraries,
            },
        )
        duration = parse_total_time(payload)
        if duration is None:
            raise ProviderError("OneMap response did not contain a route duration", error_code="NO_DURATION")
        return duration
