from __future__ import annotations

import csv
import json
import logging
import os
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import islice
from pathlib import Path
from threading import Lock
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from .domain import (
    ET,
    Bar,
    content_hash,
    demo_bars,
    normalize_bars,
    run_simulation,
    session_minutes,
)
from .exports import render_export
from .schemas import (
    BarsResponse,
    DatasetCatalogResponse,
    DatasetDetailResponse,
    RunResponse,
)


class CostModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_spread_bps: float = Field(2.0, ge=0, le=50)
    impact_coefficient_bps: float = Field(10.0, ge=0, le=100)
    fee_per_share: float = Field(0.005, ge=0, le=0.05)


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    liquidity_multiplier: float = Field(1.0, ge=0.1, le=2.0)
    price_path_multiplier: float = Field(1.0, ge=1.0, le=3.0)


class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str = "demo-sim-v1"
    side: Literal["buy", "sell"] = "buy"
    quantity: int = Field(50000, ge=1, le=1_000_000, strict=True)
    start: datetime = datetime.fromisoformat("2025-06-09T10:00:00-04:00")
    end: datetime = datetime.fromisoformat("2025-06-09T11:00:00-04:00")
    participation_cap: float = Field(0.10, ge=0.01, le=0.50)
    cost_model: CostModel = CostModel()
    scenario: Scenario = Scenario()

    @field_validator("start", "end")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return value


@dataclass(frozen=True)
class Dataset:
    dataset_id: str
    bars: list[Bar]
    meta: dict[str, Any]
    quality: dict[str, Any]


def _truthy(value: str | None) -> bool:
    return value and value.lower() in {"1", "true", "yes", "on"}


def _client_identity(request: Request) -> str:
    """Use forwarded client identity only when the deployment explicitly trusts its proxy."""
    direct = request.client.host if request.client else "unknown"
    if _truthy(os.getenv("TRUST_PROXY")):
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",", 1)[0].strip() or direct
    return direct


def _bars_from_csv(path: Path) -> list[Bar]:
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("CSV exceeds the 20 MiB import limit")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(islice(csv.DictReader(handle), 12001))
    bars, _ = normalize_bars(rows)
    return bars


def _load_datasets() -> dict[str, Dataset]:
    demo = demo_bars()
    demo_manifest = json.loads(
        (Path(__file__).resolve().parents[1] / "fixtures" / "demo" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    if demo_manifest.get("content_sha256") != content_hash(demo):
        raise RuntimeError("Bundled fixture does not match its pinned manifest hash")
    datasets = {
        "demo-sim-v1": Dataset(
            "demo-sim-v1",
            demo,
            demo_manifest,
            {
                "observed_minutes": len(demo),
                "coverage": 1.0,
                "missing_minutes": 0,
                "out_of_session_rows_filtered": 0,
            },
        )
    }
    if not _truthy(os.getenv("ENABLE_IMPORTED_DATASETS")):
        return datasets
    data_dir = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parents[1] / "data" / "local"))
    if not data_dir.exists():
        return datasets
    invalid_manifests: list[str] = []
    manifests = sorted(
        path for path in data_dir.glob("*/manifest.json") if not path.parent.name.startswith(".")
    )
    if len(manifests) > 8:
        raise RuntimeError("At most eight imported datasets may be enabled")
    for manifest_path in manifests:
        try:
            if manifest_path.stat().st_size > 64 * 1024:
                raise ValueError("manifest exceeds 64 KiB")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                raise ValueError("manifest must be a JSON object")
            bars_path = manifest_path.parent / "bars.csv"
            bars = _bars_from_csv(bars_path)
            if content_hash(bars) != manifest.get("content_sha256"):
                raise ValueError("content hash does not match manifest")
            dataset_id = str(manifest["dataset_id"])
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", dataset_id):
                raise ValueError("dataset_id must be a lowercase identifier")
            required = {
                "symbol",
                "currency",
                "data_kind",
                "source",
                "feed",
                "calendar",
                "timezone",
                "bar_interval_seconds",
            }
            if not required.issubset(manifest):
                raise ValueError("manifest is missing required provenance fields")
            if manifest.get("schema_version") != 1 or not re.fullmatch(
                r"[0-9a-f]{64}", str(manifest.get("content_sha256", ""))
            ):
                raise ValueError("manifest schema or content hash is invalid")
            if dataset_id in datasets:
                raise ValueError("dataset_id conflicts with an existing dataset")
            if manifest["symbol"] != bars[0].symbol or manifest["calendar"] != "XNYS":
                raise ValueError("manifest symbol/calendar disagrees with normalized bars")
            if manifest["timezone"] != "America/New_York" or manifest["bar_interval_seconds"] != 60:
                raise ValueError("manifest timezone or bar interval is unsupported")
            if (
                not re.fullmatch(r"[A-Z]{3}", str(manifest["currency"]))
                or manifest["data_kind"] != "historical"
            ):
                raise ValueError("invalid currency or imported data kind")
            if not str(manifest["source"]).strip() or not str(manifest["feed"]).strip():
                raise ValueError("source/feed provenance must not be empty")
            with bars_path.open(newline="", encoding="utf-8") as handle:
                _, quality = normalize_bars(list(islice(csv.DictReader(handle), 12001)))
            manifest["quality"] = quality
            datasets[dataset_id] = Dataset(dataset_id, bars, manifest, quality)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            invalid_manifests.append(f"{manifest_path}: {exc}")
    if invalid_manifests:
        raise RuntimeError("Invalid dataset manifest(s): " + "; ".join(invalid_manifests))
    return datasets


DATASETS = _load_datasets()
app = FastAPI(title="Execution Lab API", version="0.3.0")
logger = logging.getLogger("execution_lab")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
_rate_lock = Lock()
_rate: defaultdict[str, deque[float]] = defaultdict(deque)
_compute_lock = Lock()


def _error(
    code: str, message: str, status: int, request: Request, fields: list[dict] | None = None
):
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "fields": fields or [],
                "request_id": getattr(request.state, "request_id", "unknown"),
            }
        },
    )


def _secure_response_headers(response: Response, request_id: str | None = None) -> Response:
    if request_id:
        response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["X-Frame-Options"] = "DENY"
    if os.getenv("APP_ENV") == "production":
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        )
    return response


@app.middleware("http")
async def request_controls(request: Request, call_next):
    request.state.request_id = os.urandom(8).hex()
    started = time.monotonic()
    if len(request.url.query) > 4096:
        return _secure_response_headers(
            _error("REQUEST_TOO_LARGE", "Query exceeds 4 KiB", 414, request),
            request.state.request_id,
        )
    if request.url.path.startswith("/api/"):
        chunks = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 16 * 1024:
                return _secure_response_headers(
                    _error("REQUEST_TOO_LARGE", "Request body exceeds 16 KiB", 413, request),
                    request.state.request_id,
                )
            chunks.append(chunk)
        request._body = b"".join(chunks)
    if request.url.path.startswith("/api/"):
        client = _client_identity(request)
        now = time.monotonic()
        with _rate_lock:
            for stale in [key for key, queue in _rate.items() if not queue or now - queue[-1] > 60]:
                del _rate[stale]
            if client not in _rate and len(_rate) >= 4096:
                return _secure_response_headers(
                    _error("RATE_LIMITED", "Server is busy; retry shortly", 429, request),
                    request.state.request_id,
                )
            entries = _rate[client]
            while entries and now - entries[0] > 60:
                entries.popleft()
            if len(entries) >= 60:
                return _secure_response_headers(
                    _error("RATE_LIMITED", "Too many requests; retry shortly", 429, request),
                    request.state.request_id,
                )
            entries.append(now)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response = _secure_response_headers(response)
    logger.info(
        "request path=%s status=%s elapsed_ms=%.2f request_id=%s",
        request.url.path,
        response.status_code,
        (time.monotonic() - started) * 1000,
        request.state.request_id,
    )
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    fields = [
        {"field": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
        for error in exc.errors()
    ]
    return _error("INVALID_REQUEST", "Request validation failed", 422, request, fields)


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return _error("INVALID_REQUEST", str(exc), 422, request)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    return _error(
        "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR",
        str(exc.detail),
        exc.status_code,
        request,
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception):
    logger.error("unexpected_error request_id=%s", request.state.request_id, exc_info=exc)
    return _error("INTERNAL_ERROR", "The server could not complete the request", 500, request)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    static_index = Path(__file__).resolve().parents[2] / "frontend" / "dist" / "index.html"
    if "demo-sim-v1" not in DATASETS or not DATASETS["demo-sim-v1"].bars:
        raise HTTPException(503, "Bundled demo dataset is unavailable")
    if (
        os.getenv("APP_ENV") == "production"
        and not _truthy(os.getenv("FRONTEND_EXTERNAL"))
        and not static_index.exists()
    ):
        raise HTTPException(503, "Frontend build is unavailable")
    return {
        "status": "ready",
        "datasets": len(DATASETS),
        "bars": len(DATASETS["demo-sim-v1"].bars),
        "frontend": static_index.exists(),
    }


def _dataset_summary(item: Dataset) -> dict[str, Any]:
    sessions = sorted({b.timestamp.astimezone(ET).date().isoformat() for b in item.bars})
    bounds = {}
    for value in sessions:
        observed = [
            b.timestamp.astimezone(ET)
            for b in item.bars
            if b.timestamp.astimezone(ET).date().isoformat() == value
        ]
        bounds[value] = {
            "start": observed[0].strftime("%H:%M"),
            "end": (observed[-1] + timedelta(minutes=1)).strftime("%H:%M"),
        }
    return item.meta | {
        "dataset_id": item.dataset_id,
        "sessions": sessions,
        "quality": item.quality,
        "session_bounds": bounds,
    }


@app.get("/api/v1/datasets", response_model=DatasetCatalogResponse)
def datasets():
    return {"datasets": [_dataset_summary(item) for item in DATASETS.values()]}


@app.get("/api/v1/datasets/{dataset_id}", response_model=DatasetDetailResponse)
def dataset(dataset_id: str):
    item = DATASETS.get(dataset_id)
    if not item:
        raise HTTPException(404, "Unknown dataset")
    sessions = sorted({b.timestamp.astimezone(ET).date().isoformat() for b in item.bars})
    summary = _dataset_summary(item)
    return summary | {
        "default_window": {"session": sessions[-1], **summary["session_bounds"][sessions[-1]]}
    }


@app.get("/api/v1/datasets/{dataset_id}/bars", response_model=BarsResponse)
def bars(dataset_id: str, session: date):
    item = DATASETS.get(dataset_id)
    if not item:
        raise HTTPException(404, "Unknown dataset")
    selected = [b for b in item.bars if b.timestamp.astimezone(ET).date() == session]
    if not selected:
        raise HTTPException(404, "Session is unavailable in this dataset")
    return {
        "session": session.isoformat(),
        "bars": [
            {
                "timestamp": b.timestamp.isoformat(),
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
                "market_vwap": b.market_vwap,
            }
            for b in selected
        ],
    }


@app.post("/api/v1/simulations", response_model=RunResponse)
def simulations(payload: SimulationRequest, request: Request):
    item = DATASETS.get(payload.dataset_id)
    if not item:
        raise HTTPException(404, "Unknown dataset")
    local_start, local_end = payload.start.astimezone(ET), payload.end.astimezone(ET)
    if (
        local_start.date() != local_end.date()
        or local_start.second
        or local_end.second
        or local_start.microsecond
        or local_end.microsecond
    ):
        raise ValueError("Start and end must be minute-aligned within one session")
    grid = session_minutes(local_start.date())
    if not grid:
        raise ValueError("Selected date is not an XNYS regular session")
    start_minute = next(
        (
            i
            for i, ts in enumerate(grid)
            if ts.astimezone(ET).time().strftime("%H:%M") == local_start.strftime("%H:%M")
        ),
        -1,
    )
    end_minute = (
        len(grid)
        if local_end.strftime("%H:%M")
        == (grid[-1] + timedelta(minutes=1)).astimezone(ET).strftime("%H:%M")
        else next(
            (
                i
                for i, ts in enumerate(grid)
                if ts.astimezone(ET).time().strftime("%H:%M") == local_end.strftime("%H:%M")
            ),
            -1,
        )
    )
    if start_minute < 0 or end_minute < 0 or start_minute >= end_minute:
        raise ValueError("Start and end must fall within one available exchange session")
    if not _compute_lock.acquire(blocking=False):
        raise HTTPException(429, "A simulation is already running; retry shortly")
    try:
        result = run_simulation(
            item.bars,
            local_start.date(),
            start_minute,
            end_minute,
            payload.quantity,
            payload.side,
            payload.participation_cap,
            payload.cost_model.full_spread_bps,
            payload.cost_model.impact_coefficient_bps,
            payload.cost_model.fee_per_share,
            payload.scenario.liquidity_multiplier,
            payload.scenario.price_path_multiplier,
            item.meta,
        )
    finally:
        _compute_lock.release()
    result["request"]["start"] = local_start.isoformat()
    result["request"]["end"] = local_end.isoformat()
    result["request"]["request_id"] = request.state.request_id
    logger.info("simulation run_id=%s request_id=%s", result["run_id"], request.state.request_id)
    return result


@app.get("/api/v1/exports")
def export_run(
    request: Request,
    payload: str = Query(max_length=4000),
    kind: Literal["json", "csv", "note"] = "json",
    strategy: Literal["immediate", "twap", "vwap"] = "twap",
):
    try:
        order = SimulationRequest.model_validate_json(payload)
    except ValidationError as exc:
        raise ValueError("Export request is invalid") from exc
    result = simulations(order, request)
    body, media_type, filename = render_export(result, kind, strategy)
    return Response(
        body,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/")
def root():
    static_index = Path(__file__).resolve().parents[2] / "frontend" / "dist" / "index.html"
    if static_index.exists():
        return FileResponse(static_index)
    return {"service": "execution-lab", "docs": "/docs", "demo": "/api/v1/datasets"}


static_dir = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
