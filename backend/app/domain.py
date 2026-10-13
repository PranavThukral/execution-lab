from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal
from fractions import Fraction
from functools import lru_cache
from importlib.metadata import version
from typing import Literal
from zoneinfo import ZoneInfo

import exchange_calendars as xc

from .metrics import calculate_metrics

UTC = ZoneInfo("UTC")
ET = ZoneInfo("America/New_York")
XNYS = xc.get_calendar("XNYS")
Side = Literal["buy", "sell"]
ENGINE_VERSION = "0.3.0"


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    market_vwap: float | None = None
    synthetic: bool = True


@lru_cache(maxsize=512)
def session_minutes(session: date) -> tuple[datetime, ...]:
    """Return the XNYS left-closed one-minute regular-session grid in UTC."""
    try:
        if not XNYS.is_session(session.isoformat()):
            return ()
        return tuple(ts.to_pydatetime() for ts in XNYS.session_minutes(session.isoformat()))
    except (ValueError, xc.errors.DateOutOfBounds) as exc:
        raise ValueError("Date is outside the supported exchange calendar") from exc


def session_boundary(session: date, minute: int) -> datetime:
    grid = session_minutes(session)
    if not grid or minute < 0 or minute > len(grid):
        raise ValueError(f"{session.isoformat()} is not a valid XNYS session window")
    return grid[-1] + timedelta(minutes=1) if minute == len(grid) else grid[minute]


def demo_bars() -> list[Bar]:
    """Generate deterministic regular-session bars for five profile and one test session."""
    sessions = [date(2025, 6, d) for d in [2, 3, 4, 5, 6, 9]]
    bars: list[Bar] = []
    for si, session in enumerate(sessions):
        grid = session_minutes(session)
        for minute, ts in enumerate(grid):
            phase = minute / max(len(grid) - 1, 1)
            trend = 100 + si * 0.12 + 2.0 * phase + 0.6 * math.sin(phase * math.pi * 2 + si)
            noise = 0.08 * math.sin(minute * 0.37 + si * 1.9)
            close = trend + noise
            open_price = close - 0.03 * math.cos(minute * 0.11 + si)
            high = max(open_price, close) + 0.035 + 0.02 * (1 + math.sin(minute * 0.07))
            low = min(open_price, close) - 0.035 - 0.02 * (1 + math.cos(minute * 0.05))
            u = phase
            profile = (
                1.5
                + 5.5 * math.exp(-(((u - 0.08) / 0.12) ** 2))
                + 4.5 * math.exp(-(((u - 0.94) / 0.14) ** 2))
                + 1.0 * math.exp(-(((u - 0.5) / 0.3) ** 2))
            )
            volume = int(9000 * profile * (1 + 0.08 * math.sin(minute * 0.17 + si)))
            bars.append(
                Bar(ts, "SIM_DEMO", open_price, high, low, close, volume, (high + low + close) / 3)
            )
    return bars


def normalize_bars(rows: list[dict]) -> tuple[list[Bar], dict]:
    if not rows or len(rows) > 12000:
        raise ValueError("Dataset must contain between 1 and 12000 rows")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("Dataset rows must be named bar records")
    allowed_columns = {
        "timestamp",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "market_vwap",
    }
    unknown_columns = {str(column) for column in set(rows[0]) - allowed_columns}
    if unknown_columns:
        raise ValueError(f"unexpected columns: {', '.join(sorted(unknown_columns))}")
    parsed: list[Bar] = []
    seen: dict[datetime, tuple] = {}
    duplicate_rows_removed = 0
    out_of_session_rows_filtered = 0
    session_cache: dict[date, set[datetime]] = {}
    for row in rows:
        try:
            if set(row) - allowed_columns:
                unknown = ", ".join(sorted(str(column) for column in set(row) - allowed_columns))
                raise ValueError(f"unexpected columns in dataset row: {unknown}")
            ts = datetime.fromisoformat(str(row["timestamp"]).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                raise ValueError("timestamp must include a timezone")
            if ts.second or ts.microsecond:
                raise ValueError("timestamp must be aligned to an exact minute")
            ts = ts.astimezone(UTC).replace(second=0, microsecond=0)
            symbol = str(row["symbol"]).strip()
            if not symbol:
                raise ValueError("symbol must not be empty")
            vals = tuple(float(row[k]) for k in ("open", "high", "low", "close"))
            volume_float = float(row["volume"])
            if (
                not math.isfinite(volume_float)
                or volume_float < 0
                or volume_float != int(volume_float)
            ):
                raise ValueError("volume must be a nonnegative integer")
            if any(not math.isfinite(v) or v <= 0 for v in vals):
                raise ValueError("prices must be finite and positive")
            o, h, low_price, c = vals
            if not (low_price <= min(o, c) <= max(o, c) <= h):
                raise ValueError("OHLC ordering is invalid")
            mv = row.get("market_vwap")
            market_vwap = None if mv in (None, "") else float(mv)
            if market_vwap is not None and (
                not math.isfinite(market_vwap)
                or market_vwap <= 0
                or market_vwap < low_price - 1e-8
                or market_vwap > h + 1e-8
            ):
                raise ValueError("market_vwap must be within the bar range")
            key = (symbol, o, h, low_price, c, int(volume_float), market_vwap)
            if ts in seen:
                if seen[ts] != key:
                    raise ValueError(f"conflicting duplicate at {ts.isoformat()}")
                duplicate_rows_removed += 1
                continue
            seen[ts] = key
            local_date = ts.astimezone(ET).date()
            if local_date not in session_cache:
                session_cache[local_date] = set(session_minutes(local_date))
            valid_minutes = session_cache[local_date]
            if ts not in valid_minutes:
                out_of_session_rows_filtered += 1
                continue
            parsed.append(
                Bar(ts, symbol, o, h, low_price, c, int(volume_float), market_vwap, False)
            )
        except KeyError as exc:
            raise ValueError(f"missing required column: {exc.args[0]}") from exc
        except (TypeError, OverflowError) as exc:
            raise ValueError("Bar fields must contain valid numeric values") from exc
    if not parsed:
        raise ValueError("dataset contains no valid XNYS regular-session bars")
    if len({b.symbol for b in parsed}) != 1:
        raise ValueError("dataset must contain exactly one symbol")
    session_dates = {b.timestamp.astimezone(ET).date() for b in parsed}
    if len(session_dates) > 30:
        raise ValueError("dataset must contain no more than 30 exchange sessions")
    parsed.sort(key=lambda b: b.timestamp)
    observed = {b.timestamp for b in parsed}
    expected: set[datetime] = set()
    for d in {b.timestamp.astimezone(ET).date() for b in parsed}:
        expected.update(session_minutes(d))
    missing = expected - observed
    missing_runs = sum(ts - timedelta(minutes=1) not in missing for ts in sorted(missing))
    return parsed, {
        "duplicate_rows_removed": duplicate_rows_removed,
        "missing_minutes": len(missing),
        "missing_minute_gaps": missing_runs,
        "out_of_session_rows_filtered": out_of_session_rows_filtered,
        "observed_minutes": len(observed),
        "coverage": len(observed) / len(expected) if expected else 0.0,
    }


def content_hash(bars: list[Bar]) -> str:
    payload = "\n".join(
        ",".join(
            [
                b.timestamp.isoformat(),
                b.symbol,
                *(format(v, ".17g") for v in (b.open, b.high, b.low, b.close)),
                str(b.volume),
                "" if b.market_vwap is None else format(b.market_vwap, ".17g"),
            ]
        )
        for b in bars
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def selected_bars(bars: list[Bar], start: datetime, end: datetime) -> list[Bar | None]:
    lookup = {b.timestamp.astimezone(UTC): b for b in bars}
    cursor, finish = start.astimezone(UTC), end.astimezone(UTC)
    out: list[Bar | None] = []
    while cursor < finish:
        out.append(lookup.get(cursor))
        cursor += timedelta(minutes=1)
    if not out or out[0] is None or out[-1] is None:
        raise ValueError("selected window must have observed first and last bars")
    return out


def prior_profile(
    bars: list[Bar], session: date, start_minute: int, n: int
) -> tuple[list[Fraction], list[str], bool]:
    by_session: dict[date, dict[int, Bar]] = {}
    indices: dict[date, dict[datetime, int]] = {}
    for b in bars:
        d = b.timestamp.astimezone(ET).date()
        if d >= session:
            continue
        if d not in indices:
            indices[d] = {ts: i for i, ts in enumerate(session_minutes(d))}
        slot = indices[d].get(b.timestamp.astimezone(UTC))
        if slot is None:
            continue
        by_session.setdefault(d, {})[slot] = b
    eligible: list[tuple[date, list[Bar]]] = []
    for d in sorted((d for d in by_session if d < session), reverse=True):
        chosen = [by_session[d].get(start_minute + i) for i in range(n)]
        if (
            start_minute + n <= len(session_minutes(d))
            and sum(x is not None for x in chosen) >= math.ceil(n * 0.95)
            and sum(x.volume for x in chosen if x) > 0
        ):
            eligible.append((d, [x for x in chosen if x]))
        if len(eligible) == 5:
            break
    if len(eligible) < 3:
        return [Fraction(1, n)] * n, [d.isoformat() for d, _ in eligible], True
    profiles: list[list[Fraction]] = []
    for d, session_bars in eligible:
        lookup = {indices[d][b.timestamp.astimezone(UTC)]: b.volume for b in session_bars}
        values = [lookup.get(start_minute + i, 0) for i in range(n)]
        total = sum(values)
        profiles.append([Fraction(v, total) for v in values])
    weights = [sum(p[i] for p in profiles) / len(profiles) for i in range(n)]
    total = sum(weights)
    return [w / total for w in weights], [d.isoformat() for d, _ in eligible], False


def cumulative_targets(quantity: int, weights: list[float | Fraction]) -> list[int]:
    if not weights:
        return []
    exact = [
        weight if isinstance(weight, Fraction) else Fraction(str(weight)) for weight in weights
    ]
    if quantity < 1 or any(weight < 0 for weight in exact) or sum(exact) <= 0:
        raise ValueError("schedule weights must be nonnegative with a positive total")
    if len(set(exact)) == 1:
        return [quantity * (index + 1) // len(weights) for index in range(len(weights))]
    running = Fraction(0)
    total = sum(exact)
    targets: list[int] = []
    for weight in exact:
        running += weight
        targets.append(quantity * running // total)
    targets[-1] = quantity
    return targets


def _reference_for_bar(bar: Bar, method: str) -> float:
    if method == "market_vwap":
        if bar.market_vwap is None:
            if bar.volume <= 0:
                return (bar.high + bar.low + bar.close) / 3
            raise ValueError("market_vwap reference requires a value on every observed bar")
        return bar.market_vwap
    return (bar.high + bar.low + bar.close) / 3


def simulate_strategy(
    strategy: str,
    bars: list[Bar | None],
    quantity: int,
    side: Side,
    cap: float,
    spread_bps: float,
    impact_coefficient_bps: float,
    fee_per_share: float,
    targets: list[int],
    reference_method: str = "hlc3",
) -> dict:
    sign = 1 if side == "buy" else -1
    filled, fills, points = 0, [], []
    for i, bar in enumerate(bars):
        desired = max(0, targets[i] - filled)
        volume = 0 if bar is None else bar.volume
        capacity = int(
            (Decimal(str(cap)) * Decimal(volume)).to_integral_value(rounding=ROUND_FLOOR)
        )
        q = min(desired, capacity, quantity - filled)
        reference = None if bar is None else _reference_for_bar(bar, reference_method)
        impact = 0.0 if not q or not volume else impact_coefficient_bps * math.sqrt(q / volume)
        fill_price = (
            None
            if not q or reference is None
            else reference * (1 + sign * (spread_bps / 2 + impact) / 10000)
        )
        if q:
            filled += q
            fills.append(
                {
                    "strategy": strategy,
                    "slot": i,
                    "bar_start": bar.timestamp.isoformat(),
                    "filled_at": (bar.timestamp + timedelta(minutes=1)).isoformat(),
                    "desired_shares": desired,
                    "capacity_shares": capacity,
                    "shares": q,
                    "cumulative_filled": filled,
                    "remaining_shares": quantity - filled,
                    "reference_price": reference,
                    "fill_price": fill_price,
                    "impact_bps": impact,
                    "spread_bps": spread_bps,
                    "fee": q * fee_per_share,
                }
            )
        points.append(
            {
                "slot": i,
                "timestamp": None if bar is None else bar.timestamp.isoformat(),
                "target": targets[i],
                "filled": filled,
                "desired": desired,
                "capacity": capacity,
                "reference_price": reference,
                "volume": volume,
                "gap": bar is None,
            }
        )
    first, last = (
        next(b for b in bars if b is not None),
        next(b for b in reversed(bars) if b is not None),
    )
    p0, pterminal = first.open, last.close
    observed = [p for p in points if p["reference_price"] is not None and p["volume"] > 0]
    total_volume = sum(p["volume"] for p in observed)
    market_vwap = (
        sum(p["reference_price"] * p["volume"] for p in observed) / total_volume
        if total_volume
        else None
    )
    metrics = calculate_metrics(
        fills,
        quantity,
        side,
        p0,
        pterminal,
        market_vwap,
        spread_bps=spread_bps,
        impact_coefficient_bps=impact_coefficient_bps,
    )
    return {"strategy": strategy, **metrics, "fills": fills, "series": points}


def run_simulation(
    bars: list[Bar],
    session: date,
    start_minute: int,
    end_minute: int,
    quantity: int,
    side: Side = "buy",
    cap: float = 0.10,
    spread_bps: float = 2.0,
    impact_coefficient_bps: float = 10.0,
    fee_per_share: float = 0.005,
    liquidity_multiplier: float = 1.0,
    price_path_multiplier: float = 1.0,
    dataset_meta: dict | None = None,
) -> dict:
    grid = session_minutes(session)
    parameters = [
        (cap, 0.01, 0.5),
        (spread_bps, 0, 50),
        (impact_coefficient_bps, 0, 100),
        (fee_per_share, 0, 0.05),
        (liquidity_multiplier, 0.1, 2),
        (price_path_multiplier, 1, 3),
    ]
    if side not in {"buy", "sell"} or any(
        not math.isfinite(value) or not lower <= value <= upper
        for value, lower, upper in parameters
    ):
        raise ValueError("invalid execution assumptions")
    if (
        not grid
        or not (1 <= quantity <= 1_000_000)
        or not (0 <= start_minute < end_minute <= len(grid))
    ):
        raise ValueError("invalid quantity or window")
    all_bars = [b for b in bars if b.timestamp.astimezone(ET).date() == session]
    original = selected_bars(
        all_bars, session_boundary(session, start_minute), session_boundary(session, end_minute)
    )
    transformed: list[Bar | None] = []
    base = next(b for b in original if b is not None).open
    for b in original:
        if b is None:
            transformed.append(None)
            continue

        def px(value: float) -> float:
            try:
                transformed_price = base * math.exp(price_path_multiplier * math.log(value / base))
            except (OverflowError, ValueError) as exc:
                raise ValueError("Price-path stress exceeds the numeric range") from exc
            if not math.isfinite(transformed_price) or transformed_price <= 0:
                raise ValueError("Price-path stress exceeds the numeric range")
            return transformed_price

        o, h, low_price, c = [px(x) for x in (b.open, b.high, b.low, b.close)]
        scaled_volume = int(
            (Decimal(b.volume) * Decimal(str(liquidity_multiplier))).to_integral_value(
                rounding=ROUND_FLOOR
            )
        )
        transformed.append(
            Bar(
                b.timestamp,
                b.symbol,
                o,
                h,
                low_price,
                c,
                scaled_volume,
                None if b.market_vwap is None else px(b.market_vwap),
                b.synthetic,
            )
        )
    n = end_minute - start_minute
    reference_method = (
        "market_vwap"
        if all(b is None or b.volume <= 0 or b.market_vwap is not None for b in original)
        else "hlc3"
    )
    profile, profile_dates, fallback = prior_profile(bars, session, start_minute, n)
    schedules = {
        "immediate": [quantity] * n,
        "twap": cumulative_targets(quantity, [1 / n] * n),
        "vwap": cumulative_targets(quantity, profile),
    }
    strategies = [
        simulate_strategy(
            name,
            transformed,
            quantity,
            side,
            cap,
            spread_bps,
            impact_coefficient_bps,
            fee_per_share,
            targets,
            reference_method,
        )
        for name, targets in schedules.items()
    ]
    slot_times = grid[start_minute:end_minute]
    for strategy in strategies:
        for point, timestamp in zip(strategy["series"], slot_times, strict=True):
            point["timestamp"] = timestamp.isoformat()
    meta = {
        "dataset_id": "demo-sim-v1"
        if all(b.synthetic for b in bars)
        else f"local-{content_hash(bars)[:12]}",
        "symbol": bars[0].symbol,
        "currency": "USD",
        "data_kind": "synthetic" if all(b.synthetic for b in bars) else "historical",
        "source": "execution-lab-fixture" if all(b.synthetic for b in bars) else "local-import",
        "feed": "synthetic" if all(b.synthetic for b in bars) else "unknown",
        "calendar": "XNYS",
        "timezone": "America/New_York",
        "bar_interval_seconds": 60,
        "content_sha256": content_hash(bars),
    }
    if dataset_meta:
        meta.update(dataset_meta)
    canonical = {
        "dataset": meta["content_sha256"],
        "session": session.isoformat(),
        "start": start_minute,
        "end": end_minute,
        "quantity": quantity,
        "side": side,
        "cap": cap,
        "spread": spread_bps,
        "impact": impact_coefficient_bps,
        "fee": fee_per_share,
        "liquidity": liquidity_multiplier,
        "price": price_path_multiplier,
        "reference_method": reference_method,
        "engine_version": ENGINE_VERSION,
        "calendar_version": version("exchange-calendars"),
        "provenance": {
            key: meta.get(key)
            for key in (
                "source",
                "feed",
                "currency",
                "data_kind",
                "calendar",
                "timezone",
                "bar_interval_seconds",
            )
        },
    }
    run_id = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()[:16]
    capacity = sum(point["capacity"] for point in strategies[0]["series"])
    historical_totals = []
    for profile_date in profile_dates:
        previous_grid = session_minutes(date.fromisoformat(profile_date))
        lookup = {
            b.timestamp: b.volume
            for b in bars
            if b.timestamp.astimezone(ET).date().isoformat() == profile_date
        }
        historical_totals.append(
            sum(
                int(
                    Decimal(str(cap))
                    * int(Decimal(lookup.get(ts, 0)) * Decimal(str(liquidity_multiplier)))
                )
                for ts in previous_grid[start_minute:end_minute]
            )
        )
    warnings = []
    if fallback:
        warnings.append(
            {
                "code": "VWAP_FALLBACK",
                "message": "Too few prior sessions: VWAP uses the uniform TWAP schedule.",
            }
        )
    gaps = sum(b is None for b in original)
    if gaps:
        warnings.append(
            {
                "code": "MISSING_BARS",
                "message": f"{gaps} missing minute(s): no liquidity or fills are invented.",
            }
        )
    if capacity < quantity:
        warnings.append(
            {
                "code": "CAPACITY_SHORTFALL",
                "message": "The participation cap prevents this replay from completing the order.",
            }
        )
    return {
        "schema_version": 3,
        "engine_version": ENGINE_VERSION,
        "run_id": run_id,
        "dataset": meta,
        "request": {
            "dataset_id": meta["dataset_id"],
            "session": session.isoformat(),
            "start": session_boundary(session, start_minute).isoformat(),
            "end": session_boundary(session, end_minute).isoformat(),
            "quantity": quantity,
            "side": side,
            "participation_cap": cap,
            "cost_model": {
                "full_spread_bps": spread_bps,
                "impact_coefficient_bps": impact_coefficient_bps,
                "fee_per_share": fee_per_share,
            },
            "scenario": {
                "liquidity_multiplier": liquidity_multiplier,
                "price_path_multiplier": price_path_multiplier,
            },
        },
        "diagnostics": {
            "realized_capacity_shares": capacity,
            "minimum_unfilled_shares": max(0, quantity - capacity),
            "observed_minutes": n - gaps,
            "expected_minutes": n,
            "historical_capacity_estimate_shares": None
            if fallback
            else sum(historical_totals) // len(historical_totals),
            "historical_capacity_range": None
            if fallback
            else [min(historical_totals), max(historical_totals)],
        },
        "assumptions": {
            "reference_method": reference_method,
            "arrival_proxy": "first_selected_bar_open",
            "fill_timing": "bar_end",
            "positive_cost_is_worse": True,
            "calendar_version": version("exchange-calendars"),
            "modeled_spread_bps": spread_bps,
            "impact_coefficient_bps": impact_coefficient_bps,
        },
        "profile": {
            "strategy": "forecast_volume_vwap",
            "eligible_session_dates": profile_dates,
            "fallback": fallback,
            "weights": [float(weight) for weight in profile],
        },
        "market": [
            {
                "slot": i,
                "timestamp": p["timestamp"],
                "reference_price": p["reference_price"],
                "volume": p["volume"],
                "gap": p["gap"],
                "original_reference_price": None
                if original[i] is None
                else _reference_for_bar(original[i], reference_method),
            }
            for i, p in enumerate(strategies[0]["series"])
        ],
        "strategies": strategies,
        "warnings": warnings,
    }
