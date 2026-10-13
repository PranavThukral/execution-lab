import asyncio
from datetime import datetime

import pytest

from app import provider

START = datetime.fromisoformat("2025-06-09T14:30:00+00:00")
END = datetime.fromisoformat("2025-06-09T14:32:00+00:00")


def bar(timestamp: str):
    return {"t": timestamp, "o": 100, "h": 101, "l": 99, "c": 100.5, "v": 1000, "vw": 100.2}


class FakeResponse:
    def __init__(self, status_code: int, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload


class FakeClient:
    responses = []
    calls = 0

    def __init__(self, *args, **kwargs):
        self.responses = type(self).responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, *args, **kwargs):
        response = self.responses[type(self).calls]
        type(self).calls += 1
        return response


def test_provider_trims_inclusive_bounds_and_retries_5xx(monkeypatch):
    FakeClient.calls = 0
    FakeClient.responses = [
        FakeResponse(503),
        FakeResponse(
            200,
            {
                "bars": {
                    "AAPL": [
                        bar("2025-06-09T14:29:00Z"),
                        bar("2025-06-09T14:30:00Z"),
                        bar("2025-06-09T14:31:00Z"),
                        bar("2025-06-09T14:32:00Z"),
                    ]
                }
            },
        ),
    ]
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    monkeypatch.setattr(provider.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(provider.asyncio, "sleep", lambda _: _completed())
    bars, quality = asyncio.run(provider.fetch_alpaca_bars("AAPL", START, END))
    assert [item.timestamp.isoformat() for item in bars] == [
        "2025-06-09T14:30:00+00:00",
        "2025-06-09T14:31:00+00:00",
    ]
    assert quality["observed_minutes"] == 2
    assert FakeClient.calls == 2


def test_provider_repeated_token_fails_without_unbounded_requests(monkeypatch):
    FakeClient.calls = 0
    FakeClient.responses = [
        FakeResponse(
            200, {"bars": {"AAPL": [bar("2025-06-09T14:30:00Z")]}, "next_page_token": "same"}
        ),
        FakeResponse(
            200, {"bars": {"AAPL": [bar("2025-06-09T14:31:00Z")]}, "next_page_token": "same"}
        ),
    ]
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    monkeypatch.setattr(provider.httpx, "AsyncClient", FakeClient)
    with pytest.raises(provider.ProviderError, match="repeated"):
        asyncio.run(provider.fetch_alpaca_bars("AAPL", START, END))
    assert FakeClient.calls == 2


def test_provider_does_not_retry_auth_failures(monkeypatch):
    FakeClient.calls = 0
    FakeClient.responses = [FakeResponse(401)]
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    monkeypatch.setattr(provider.httpx, "AsyncClient", FakeClient)
    with pytest.raises(provider.ProviderError, match="HTTP 401"):
        asyncio.run(provider.fetch_alpaca_bars("AAPL", START, END))
    assert FakeClient.calls == 1


async def _completed():
    return None


@pytest.mark.parametrize(
    "payload", [{"bars": []}, {"bars": {"AAPL": [{}]}}, {"bars": {"AAPL": "bad"}}]
)
def test_malformed_payload_has_a_safe_error(monkeypatch, payload):
    FakeClient.calls = 0
    FakeClient.responses = [FakeResponse(200, payload)]
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    monkeypatch.setattr(provider.httpx, "AsyncClient", FakeClient)
    with pytest.raises(provider.ProviderError, match="malformed"):
        asyncio.run(provider.fetch_alpaca_bars("AAPL", START, END))


def test_invalid_normalized_bar_has_a_safe_error(monkeypatch):
    FakeClient.calls = 0
    FakeClient.responses = [
        FakeResponse(
            200,
            {
                "bars": {
                    "AAPL": [
                        {
                            "t": "2025-06-09T14:30:00Z",
                            "o": 100,
                            "h": 99,
                            "l": 98,
                            "c": 98.5,
                            "v": 1000,
                        }
                    ]
                }
            },
        )
    ]
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    monkeypatch.setattr(provider.httpx, "AsyncClient", FakeClient)
    with pytest.raises(provider.ProviderError, match="invalid normalized"):
        asyncio.run(provider.fetch_alpaca_bars("AAPL", START, END))


def test_provider_limits_accumulated_rows(monkeypatch):
    FakeClient.calls = 0
    FakeClient.responses = [
        FakeResponse(200, {"bars": {"AAPL": [bar("2025-06-09T14:30:00Z")] * 12001}})
    ]
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    monkeypatch.setattr(provider.httpx, "AsyncClient", FakeClient)
    with pytest.raises(provider.ProviderError, match="12000-row"):
        asyncio.run(provider.fetch_alpaca_bars("AAPL", START, END))


@pytest.mark.parametrize("timestamp", [None, 123, "broken", "2025-06-09T14:30:00"])
def test_provider_invalid_timestamp_is_a_safe_error(monkeypatch, timestamp):
    FakeClient.calls = 0
    FakeClient.responses = [FakeResponse(200, {"bars": {"AAPL": [bar(timestamp)]}})]
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    monkeypatch.setattr(provider.httpx, "AsyncClient", FakeClient)
    with pytest.raises(provider.ProviderError):
        asyncio.run(provider.fetch_alpaca_bars("AAPL", START, END))


def test_provider_respects_http_date_retry_and_rejects_long_wait(monkeypatch):
    from datetime import timedelta, timezone
    from email.utils import format_datetime

    waits = []

    async def capture_wait(seconds):
        waits.append(seconds)

    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    monkeypatch.setattr(provider.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(provider.asyncio, "sleep", capture_wait)
    FakeClient.calls = 0
    retry_at = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=3), usegmt=True)
    FakeClient.responses = [
        FakeResponse(429, headers={"retry-after": retry_at}),
        FakeResponse(200, {"bars": {"AAPL": [bar("2025-06-09T14:30:00Z")]}}),
    ]
    asyncio.run(provider.fetch_alpaca_bars("AAPL", START, END))
    assert 1 < waits[0] <= 3
    FakeClient.calls = 0
    FakeClient.responses = [FakeResponse(429, headers={"retry-after": "120"})]
    with pytest.raises(provider.ProviderError, match="deadline"):
        asyncio.run(provider.fetch_alpaca_bars("AAPL", START, END))
    assert FakeClient.calls == 1
