from __future__ import annotations

import base64
import json
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


def token_expiry(token: str) -> float:
    """Read an optional JWT exp claim without verifying the token signature."""
    try:
        encoded_payload = token.split(".")[1]
        encoded_payload += "=" * (-len(encoded_payload) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded_payload).decode("utf-8"))
        return float(payload.get("exp", 0))
    except (IndexError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return 0


class OneMapClient:
    def __init__(
        self,
        email: str | None = None,
        password: str | None = None,
        base_url: str = "https://www.onemap.gov.sg",
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
        access_token: str | None = None,
    ):
        self.email = email.strip() if email else None
        self.password = password.strip() if password else None
        self._token = access_token.strip() if access_token else None
        if not self._token and not (self.email and self.password):
            raise ValueError(
                "Set ONEMAP_ACCESS_TOKEN, or set both ONEMAP_EMAIL and ONEMAP_PASSWORD, for OneMap collection"
            )
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=60.0)
        self.clock = clock
        self._expiry: float = token_expiry(self._token) if self._token else 0

    @property
    def can_refresh_token(self) -> bool:
        return bool(self.email and self.password)

    def authenticate(self, force: bool = False) -> str:
        if self._token and not force and (not self._expiry or self.clock() < self._expiry - 60):
            return self._token
        if not self.can_refresh_token:
            if self._token:
                return self._token
            raise ProviderError(
                "OneMap access token is unavailable; set ONEMAP_ACCESS_TOKEN or provide email/password",
                error_code="AUTHENTICATION_FAILED",
                retryable=False,
            )
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
                if not self.can_refresh_token:
                    raise ProviderError(
                        "OneMap access token was rejected or expired; provide a new ONEMAP_ACCESS_TOKEN",
                        http_status=401,
                        error_code="AUTHENTICATION_FAILED",
                        retryable=False,
                    )
                token = self.authenticate(force=True)
                refreshed = True
                continue
            break
        if response.status_code >= 400:
            is_route_request = path == "/api/public/routingsvc/route"
            is_transient_route_not_found = is_route_request and response.status_code == 404
            raise ProviderError(
                f"OneMap HTTP {response.status_code}: {response.text[:500]}",
                http_status=response.status_code,
                error_code="ROUTE_NOT_FOUND" if is_route_request and response.status_code == 404 else None,
                # OneMap has returned temporary 404/no-route responses under load for
                # otherwise valid Singapore origins. Let the collector retry these a
                # bounded number of times; non-routing 404s remain permanent errors.
                retryable=True if is_transient_route_not_found else None,
            )
        payload = response.json()
        if isinstance(payload, dict) and payload.get("error"):
            error = str(payload["error"])
            if "expired" in error.lower() and not refreshed:
                if not self.can_refresh_token:
                    raise ProviderError(
                        "OneMap access token expired; provide a new ONEMAP_ACCESS_TOKEN",
                        error_code="AUTHENTICATION_FAILED",
                        retryable=False,
                    )
                token = self.authenticate(force=True)
                response = self.client.get(f"{self.base_url}{path}", headers={"Authorization": token}, params=params)
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
