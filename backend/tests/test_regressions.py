import csv
import json
import math
import random
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction

import pytest
from fastapi.testclient import TestClient

from app.cli import _write_dataset
from app.domain import ET, cumulative_targets, demo_bars, normalize_bars, run_simulation
from app.main import _load_datasets, _rate, app
from app.metrics import calculate_metrics


@pytest.fixture(autouse=True)
def clear_rate():
    _rate.clear()


def test_profile_cannot_see_evaluation_or_future_volume():
    bars = demo_bars()
    baseline = run_simulation(bars, date(2025, 6, 9), 30, 90, 50000)
    changed = [
        replace(b, volume=1) if b.timestamp.astimezone(ET).date() >= date(2025, 6, 9) else b
        for b in bars
    ]
    replay = run_simulation(changed, date(2025, 6, 9), 30, 90, 50000)
    assert replay["profile"] == baseline["profile"]
    assert [p["target"] for p in replay["strategies"][2]["series"]] == [
        p["target"] for p in baseline["strategies"][2]["series"]
    ]
    assert (
        replay["diagnostics"]["historical_capacity_estimate_shares"]
        == baseline["diagnostics"]["historical_capacity_estimate_shares"]
    )
    assert replay["diagnostics"]["realized_capacity_shares"] == 0


def test_fractional_profile_has_exact_boundary_and_invalid_weights_fail():
    assert cumulative_targets(9, [Fraction(1, 9), Fraction(2, 9), Fraction(6, 9)]) == [1, 3, 9]
    assert cumulative_targets(10, [2.0, 3.0, 5.0]) == [2, 5, 10]
    with pytest.raises(ValueError):
        cumulative_targets(10, [-1, 2])


def test_gap_has_timestamp_zero_capacity_and_no_interpolated_fill():
    bars = demo_bars()
    missing = datetime(2025, 6, 9, 14, 20, tzinfo=timezone.utc)
    bars = [b for b in bars if b.timestamp != missing]
    result = run_simulation(bars, date(2025, 6, 9), 30, 90, 50000)
    point = next(p for p in result["market"] if p["gap"])
    assert point["timestamp"] == missing.isoformat()
    assert point["volume"] == 0 and point["reference_price"] is None
    assert result["diagnostics"]["observed_minutes"] == 59
    assert "MISSING_BARS" in [w["code"] for w in result["warnings"]]
    for strategy in result["strategies"]:
        assert all(fill["bar_start"] != missing.isoformat() for fill in strategy["fills"])


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_generated_scenarios_conserve_cap_backlog_and_cost_attribution(side):
    rng = random.Random(90210)
    for _ in range(12):
        quantity = rng.randint(1, 1000000)
        result = run_simulation(
            demo_bars(),
            date(2025, 6, 9),
            30,
            90,
            quantity,
            side,
            cap=rng.choice([0.01, 0.10, 0.29, 0.50]),
            liquidity_multiplier=rng.choice([0.1, 1, 2]),
        )
        for strategy in result["strategies"]:
            assert strategy["filled_shares"] + strategy["unfilled_shares"] == quantity
            assert sum(f["shares"] for f in strategy["fills"]) == strategy["filled_shares"]
            assert all(0 < f["shares"] <= f["capacity_shares"] for f in strategy["fills"])
            assert all(
                datetime.fromisoformat(f["filled_at"]) - datetime.fromisoformat(f["bar_start"])
                == timedelta(minutes=1)
                for f in strategy["fills"]
            )
            total = sum(
                strategy[k]
                for k in ["timing_cost", "spread_cost", "impact_cost", "fees", "opportunity_cost"]
            )
            assert math.isclose(total, strategy["implementation_shortfall"], abs_tol=1e-7)
            assert strategy["series"][-1]["target"] == quantity


def test_zero_volume_metrics_are_defined_without_fake_prices():
    result = run_simulation(
        [replace(b, volume=0) for b in demo_bars()], date(2025, 6, 9), 30, 90, 50000
    )
    for strategy in result["strategies"]:
        assert strategy["fills"] == []
        assert strategy["average_execution_price"] is None
        assert strategy["vwap_slippage_bps"] is None
        assert strategy["implementation_shortfall"] == strategy["opportunity_cost"]


def test_signed_opportunity_cost_can_be_favorable():
    buy = calculate_metrics([], 100, "buy", 100, 99, None)
    sell = calculate_metrics([], 100, "sell", 100, 101, None)
    assert buy["opportunity_cost"] == sell["opportunity_cost"] == -100


@pytest.mark.parametrize("volume", ["inf", "nan", "-1", "1.5"])
def test_nonfinite_or_fractional_volume_is_a_validation_error(volume):
    with pytest.raises(ValueError):
        normalize_bars(
            [
                dict(
                    timestamp="2025-06-09T10:00:00-04:00",
                    symbol="TEST",
                    open=100,
                    high=101,
                    low=99,
                    close=100,
                    volume=volume,
                )
            ]
        )


def test_extra_csv_columns_have_a_readable_validation_error():
    row = {
        "timestamp": "2025-06-09T10:00:00-04:00",
        "symbol": "TEST",
        "open": 100,
        "high": 101,
        "low": 99,
        "close": 100,
        "volume": 1000,
        None: ["unexpected"],
    }
    with pytest.raises(ValueError, match="unexpected columns"):
        normalize_bars([row])


def test_import_is_immutable_provenance_sensitive_and_registry_rechecks_quality(
    tmp_path, monkeypatch
):
    original = demo_bars()[:390]
    _write_dataset(
        original,
        {"coverage": 999},
        source="test source",
        feed="test",
        currency="USD",
        output_dir=tmp_path,
    )
    with pytest.raises(ValueError, match="immutable"):
        _write_dataset(
            original, {}, source="test source", feed="test", currency="USD", output_dir=tmp_path
        )
    _write_dataset(
        original, {}, source="other source", feed="test", currency="USD", output_dir=tmp_path
    )
    monkeypatch.setenv("ENABLE_IMPORTED_DATASETS", "true")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    registry = _load_datasets()
    assert len(registry) == 3
    imported = [d for key, d in registry.items() if key != "demo-sim-v1"]
    assert all(d.quality["coverage"] == 1 for d in imported)
    manifest_path = next(tmp_path.glob("*/manifest.json"))
    manifest = json.loads(manifest_path.read_text())
    manifest["symbol"] = "WRONG"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError, match="disagrees"):
        _load_datasets()


def test_csv_roundtrip_preserves_content(tmp_path):
    from app.domain import content_hash

    _write_dataset(demo_bars(), {}, source="test", feed="test", currency="USD", output_dir=tmp_path)
    with next(tmp_path.glob("*/bars.csv")).open(newline="") as handle:
        bars, _ = normalize_bars(list(csv.DictReader(handle)))
    assert content_hash(bars) == content_hash(demo_bars())


def test_public_contract_cap_and_capacity_match_submitted_request():
    client = TestClient(app)
    response = client.post("/api/v1/simulations", json={"participation_cap": 0.29})
    assert response.status_code == 200
    result = response.json()
    assert result["request"]["participation_cap"] == 0.29
    assert result["diagnostics"]["realized_capacity_shares"] == sum(
        p["capacity"] for p in result["strategies"][0]["series"]
    )
    assert result["request"]["start"].endswith("-04:00")
    for path in ["/api/v1/unknown", "/api/v1/datasets/unknown"]:
        assert client.get(path).json()["error"]["code"] == "NOT_FOUND"


def test_catalog_detail_and_bars_have_explicit_openapi_contracts():
    client = TestClient(app)
    catalog = client.get("/api/v1/datasets")
    detail = client.get("/api/v1/datasets/demo-sim-v1")
    bars = client.get("/api/v1/datasets/demo-sim-v1/bars", params={"session": "2025-06-09"})
    assert catalog.status_code == detail.status_code == bars.status_code == 200
    assert catalog.json()["datasets"][0]["session_bounds"]["2025-06-09"] == {
        "start": "09:30",
        "end": "16:00",
    }
    assert detail.json()["default_window"]["session"] == "2025-06-09"
    assert catalog.json()["datasets"][0]["calendar"] == "XNYS"
    assert catalog.json()["datasets"][0]["timezone"] == "America/New_York"
    assert detail.json()["calendar"] == "XNYS"
    assert bars.json()["bars"][0]["market_vwap"] is not None
    openapi = client.get("/openapi.json").json()
    for path in [
        "/api/v1/datasets",
        "/api/v1/datasets/{dataset_id}",
        "/api/v1/datasets/{dataset_id}/bars",
    ]:
        schema = openapi["paths"][path]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
        assert schema.get("$ref")


@pytest.mark.parametrize("quantity", [True, 1.5, "100"])
def test_quantity_requires_integer(quantity):
    assert (
        TestClient(app).post("/api/v1/simulations", json={"quantity": quantity}).status_code == 422
    )


def test_body_limit_applies_without_content_length():
    response = TestClient(app).post("/api/v1/simulations", content=iter([b" " * 17000]))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-request-id"]


def test_production_security_headers_are_present(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    response = TestClient(app).get("/healthz")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    monkeypatch.delenv("APP_ENV")


def test_forwarded_rate_limit_identity_requires_explicit_trust(monkeypatch):
    from starlette.requests import Request

    from app.main import _client_identity

    scope = {
        "type": "http",
        "client": ("testclient", 123),
        "headers": [(b"x-forwarded-for", b"203.0.113.10, 10.0.0.2")],
    }
    request = Request(scope)
    assert _client_identity(request) == "testclient"
    monkeypatch.setenv("TRUST_PROXY", "true")
    assert _client_identity(request) == "203.0.113.10"
    monkeypatch.delenv("TRUST_PROXY")


def test_calendar_out_of_range_is_readable():
    response = TestClient(app).post(
        "/api/v1/simulations",
        json={"start": "1900-01-02T10:00:00-05:00", "end": "1900-01-02T11:00:00-05:00"},
    )
    assert response.status_code == 422


def test_downloads_reproduce_original_run_and_csv_reconciles():
    import io

    client = TestClient(app)
    original = client.post("/api/v1/simulations", json={}).json()
    request = {
        key: value
        for key, value in original["request"].items()
        if key not in {"session", "request_id"}
    }
    params = {"payload": json.dumps(request), "kind": "json"}
    downloaded = client.get("/api/v1/exports", params=params)
    assert downloaded.status_code == 200
    assert "attachment" in downloaded.headers["content-disposition"]
    assert downloaded.json()["run_id"] == original["run_id"]
    assert downloaded.json()["strategies"] == original["strategies"]
    params.update(kind="csv", strategy="twap")
    csv_response = client.get("/api/v1/exports", params=params)
    rows = list(csv.DictReader(io.StringIO(csv_response.text)))
    assert sum(int(row["shares"]) for row in rows) == original["strategies"][1]["filled_shares"]
    assert set(rows[0]) >= {"strategy", "spread_bps", "bar_start", "filled_at"}
    params["kind"] = "note"
    note = client.get("/api/v1/exports", params=params)
    assert original["run_id"] in note.text
    assert "NOT a pre-trade forecast" in note.text


def test_early_close_must_cover_entire_prior_window():
    from app.domain import prior_profile, session_minutes

    template = demo_bars()[0]
    bars = [
        replace(template, timestamp=ts)
        for d in [date(2025, 11, 26), date(2025, 11, 28), date(2025, 12, 1), date(2025, 12, 2)]
        for ts in session_minutes(d)
    ]
    _, dates, fallback = prior_profile(bars, date(2025, 12, 3), 190, 21)
    assert "2025-11-28" not in dates
    assert len(dates) == 3 and not fallback


def test_uniform_fallback_is_explicit_and_matches_twap():
    result = run_simulation(demo_bars(), date(2025, 6, 3), 30, 90, 50000)
    assert result["profile"]["fallback"]
    assert result["strategies"][1]["fills"] == [
        {**f, "strategy": "twap"} for f in result["strategies"][2]["fills"]
    ]
    assert any(w["code"] == "VWAP_FALLBACK" for w in result["warnings"])


def test_provenance_affects_run_identity():
    bars = demo_bars()
    a = run_simulation(bars, date(2025, 6, 9), 30, 90, 50000, dataset_meta={"feed": "a"})
    b = run_simulation(bars, date(2025, 6, 9), 30, 90, 50000, dataset_meta={"feed": "b"})
    assert a["run_id"] != b["run_id"]


def test_unpublished_import_staging_is_not_a_dataset(tmp_path, monkeypatch):
    staging = tmp_path / ".import-interrupted"
    staging.mkdir()
    (staging / "manifest.json").write_text("invalid unfinished manifest")
    monkeypatch.setenv("ENABLE_IMPORTED_DATASETS", "true")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert list(_load_datasets()) == ["demo-sim-v1"]


@pytest.mark.parametrize("field", ["open", "high", "volume"])
def test_null_csv_numeric_fields_are_readable(field):
    row = dict(
        timestamp="2025-06-09T10:00:00-04:00",
        symbol="TEST",
        open=100,
        high=101,
        low=99,
        close=100,
        volume=1000,
    )
    row[field] = None
    with pytest.raises(ValueError, match="numeric"):
        normalize_bars([row])


def test_import_manifest_must_be_an_object(tmp_path, monkeypatch):
    folder = tmp_path / "bad"
    folder.mkdir()
    (folder / "manifest.json").write_text("null")
    monkeypatch.setenv("ENABLE_IMPORTED_DATASETS", "true")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with pytest.raises(RuntimeError, match="JSON object"):
        _load_datasets()


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_unequal_volume_costs_match_independent_oracle(side):
    from app.domain import Bar

    grid = [datetime(2025, 6, 9, 14, minute, tzinfo=timezone.utc) for minute in [0, 1]]
    bars = [
        Bar(grid[0], "TEST", 100, 102, 98, 101, 100, 100, False),
        Bar(grid[1], "TEST", 101, 103, 99, 102, 200, 101, False),
    ]
    result = run_simulation(
        bars,
        date(2025, 6, 9),
        30,
        32,
        60,
        side,
        cap=0.1,
        spread_bps=0,
        impact_coefficient_bps=0,
        fee_per_share=0.01,
    )
    # Only 10 + 20 shares can fill. Side-independent fees are 30 * .01.
    sign = 1 if side == "buy" else -1
    for strategy in result["strategies"]:
        assert strategy["filled_shares"] == 30
        assert strategy["market_vwap"] == pytest.approx((100 * 100 + 101 * 200) / 300)
        assert strategy["average_execution_price"] == pytest.approx((10 * 100 + 20 * 101) / 30)
        assert strategy["execution_cost"] == sign * 20
        assert strategy["opportunity_cost"] == sign * 60
        assert strategy["implementation_shortfall"] == pytest.approx(sign * 80 + 0.3)
