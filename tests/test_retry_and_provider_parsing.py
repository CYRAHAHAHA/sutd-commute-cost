from __future__ import annotations

import json

import httpx

from commute.collector import ProviderError, call_with_retries
from commute.providers.google import GoogleRoutesClient, parse_duration
from commute.providers.onemap import OneMapClient, parse_total_time, token_expiry
from commute.retry import retry_decision


def test_retry_classification_treats_429_separately():
    assert retry_decision(429).retryable
    assert retry_decision(429).reason == "rate_limited"
    assert not retry_decision(400).retryable
    assert retry_decision(503).retryable


def test_retry_backoff_retries_transient_then_succeeds():
    calls = 0
    sleeps: list[float] = []

    def operation():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ProviderError("busy", http_status=503)
        return "ok"

    assert call_with_retries(operation, 3, sleep=sleeps.append) == ("ok", 3)
    assert sleeps == [1.0, 2.0]


def test_permanent_error_is_not_retried():
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        raise ProviderError("bad request", http_status=400)

    try:
        call_with_retries(operation, 5, sleep=lambda _: None)
    except ProviderError:
        pass
    assert calls == 1


def test_provider_duration_parsers():
    assert parse_duration("123.9s") == 123
    assert parse_duration("bad") is None
    assert parse_total_time({"route_summary": {"total_time": 987}}) == 987
    assert parse_total_time({"plan": [{"duration": 321}]}) == 321


def test_google_matrix_client_uses_arrival_time_and_parses_elements():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["mask"] = request.headers["X-Goog-FieldMask"]
        return httpx.Response(
            200,
            text='[{"originIndex":0,"destinationIndex":0,"condition":"ROUTE_EXISTS","duration":"600s","status":{}}]',
        )

    client = GoogleRoutesClient("secret", client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = client.compute_route_matrix([(1.3, 103.8)], (1.34, 103.96), "2026-09-14T23:30:00Z")
    assert result[0].duration_seconds == 600
    assert seen["body"]["arrivalTime"] == "2026-09-14T23:30:00Z"
    assert "duration" in seen["mask"]


def test_onemap_client_authenticates_and_routes():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("getToken"):
            return httpx.Response(200, json={"access_token": "token", "expiry_timestamp": "9999999999"})
        return httpx.Response(200, json={"route_summary": {"total_time": 777}})

    client = OneMapClient("email", "password", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.route((1.3, 103.8), (1.34, 103.96), "2026-09-14", "06:20") == 777
    assert calls == ["/api/auth/post/getToken", "/api/public/routingsvc/route"]


def test_onemap_access_token_can_be_used_without_email_or_password():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["authorization"] = request.headers["Authorization"]
        return httpx.Response(200, json={"route_summary": {"total_time": 888}})

    client = OneMapClient(
        access_token="existing-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.route((1.3, 103.8), (1.34, 103.96), "2026-09-14", "06:20") == 888
    assert seen == {"path": "/api/public/routingsvc/route", "authorization": "existing-token"}
    assert token_expiry("not-a-jwt") == 0
