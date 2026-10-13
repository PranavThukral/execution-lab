from __future__ import annotations

import asyncio
import math
import os
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from time import monotonic

import httpx

from .domain import normalize_bars


class ProviderError(RuntimeError):
    pass


async def fetch_alpaca_bars(
    symbol: str, start: datetime, end: datetime, feed: str = "iex"
) -> tuple[list, dict]:
    key = os.getenv("ALPACA_API_KEY")
    secret = os.getenv("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise ProviderError("ALPACA_API_KEY and ALPACA_SECRET_KEY are required for provider fetch")
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    params = {
        "symbols": symbol,
        "timeframe": "1Min",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "feed": feed,
        "adjustment": "raw",
        "sort": "asc",
        "limit": 10000,
    }
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ProviderError("provider bounds must be timezone-aware and increasing")
    rows: list[dict] = []
    token = None
    seen_tokens: set[str] = set()
    deadline = monotonic() + 60
    timeout = httpx.Timeout(10.0, connect=5.0)
    async with httpx.AsyncClient(
        base_url="https://data.alpaca.markets", headers=headers, timeout=timeout
    ) as client:
        for _ in range(20):
            if token:
                if token in seen_tokens:
                    raise ProviderError("Alpaca pagination repeated a page token")
                seen_tokens.add(token)
                params["page_token"] = token
            response = None
            for attempt in range(3):
                if monotonic() >= deadline:
                    raise ProviderError("Alpaca fetch exceeded the 60 second deadline")
                try:
                    response = await asyncio.wait_for(
                        client.get("/v2/stocks/bars", params=params),
                        timeout=max(0.001, deadline - monotonic()),
                    )
                except TimeoutError as exc:
                    raise ProviderError("Alpaca fetch exceeded the 60 second deadline") from exc
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt == 2:
                        raise ProviderError(
                            "Alpaca request timed out or failed after retries"
                        ) from exc
                    await asyncio.sleep(min(2**attempt, 4))
                    continue
                if response.status_code not in {429, 500, 502, 503, 504}:
                    break
                if attempt == 2:
                    break
                retry_after = response.headers.get("retry-after", "1")
                try:
                    wait = float(retry_after)
                except ValueError:
                    try:
                        parsed = parsedate_to_datetime(retry_after)
                        wait = max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())
                    except (TypeError, ValueError, OverflowError):
                        wait = 1.0
                wait = max(0.0, wait)
                if not math.isfinite(wait) or wait > max(0.0, deadline - monotonic()):
                    raise ProviderError("Alpaca retry delay exceeds the fetch deadline")
                await asyncio.sleep(wait)
            assert response is not None
            if response.status_code != 200:
                raise ProviderError(f"Alpaca request failed with HTTP {response.status_code}")
            try:
                payload = response.json()
                items = payload.get("bars", {}).get(symbol, [])
                if not isinstance(items, list) or not isinstance(
                    payload.get("next_page_token"), (str, type(None))
                ):
                    raise ValueError("invalid payload")
                for item in items:
                    if not isinstance(item, dict) or not {"t", "o", "h", "l", "c", "v"}.issubset(
                        item
                    ):
                        raise ValueError("incomplete bar")
                    if not isinstance(item["t"], str):
                        raise ValueError("invalid timestamp")
            except (ValueError, TypeError, AttributeError) as exc:
                raise ProviderError("Alpaca returned malformed bar data") from exc
            for item in items:
                if len(rows) >= 12000:
                    raise ProviderError("Alpaca fetch exceeds the 12000-row dataset limit")
                rows.append(
                    {
                        "timestamp": item["t"],
                        "symbol": symbol,
                        "open": item["o"],
                        "high": item["h"],
                        "low": item["l"],
                        "close": item["c"],
                        "volume": item["v"],
                        "market_vwap": item.get("vw"),
                    }
                )
            token = payload.get("next_page_token")
            if not token:
                break
        else:
            raise ProviderError("Alpaca pagination exceeded the safety limit")
    try:
        rows = [
            row
            for row in rows
            if start <= datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")) < end
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise ProviderError("Alpaca returned an invalid bar timestamp") from exc
    if not rows:
        raise ProviderError("Alpaca returned no bars")
    try:
        return normalize_bars(rows)
    except ValueError as exc:
        raise ProviderError("Alpaca returned invalid normalized bars") from exc
