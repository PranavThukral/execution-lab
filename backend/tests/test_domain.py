from datetime import date, datetime, timezone

from app.domain import (
    ET,
    Bar,
    cumulative_targets,
    demo_bars,
    run_simulation,
    session_minutes,
    simulate_strategy,
)
from app.metrics import calculate_metrics


def test_schedule_conserves_quantity():
    assert cumulative_targets(7, [0.2, 0.3, 0.5]) == [1, 3, 7]


def test_default_run_is_deterministic_and_has_three_strategies():
    bars = demo_bars()
    first = run_simulation(bars, date(2025, 6, 9), 30, 90, 50000)
    second = run_simulation(bars, date(2025, 6, 9), 30, 90, 50000)
    assert first["run_id"] == second["run_id"]
    assert [x["strategy"] for x in first["strategies"]] == ["immediate", "twap", "vwap"]
    for strategy in first["strategies"]:
        assert strategy["filled_shares"] + strategy["unfilled_shares"] == 50000
        assert (
            strategy["implementation_shortfall"]
            == strategy["execution_cost"] + strategy["fees"] + strategy["opportunity_cost"]
        )


def test_sell_cost_sign_is_positive_when_price_rises():
    bars = demo_bars()
    buy = run_simulation(bars, date(2025, 6, 9), 30, 90, 50000, "buy")["strategies"][0]
    sell = run_simulation(bars, date(2025, 6, 9), 30, 90, 50000, "sell")["strategies"][0]
    assert buy["implementation_shortfall"] >= 0
    assert sell["implementation_shortfall"] >= 0


def test_hand_calculated_partial_fill_metrics():
    result = calculate_metrics(
        [{"shares": 60, "fill_price": 101.0, "fee": 0.6}],
        100,
        "buy",
        100.0,
        102.0,
        None,
    )
    assert result["filled_shares"] == 60
    assert result["unfilled_shares"] == 40
    assert result["execution_cost"] == 60
    assert result["opportunity_cost"] == 80
    assert result["fees"] == 0.6
    assert result["implementation_shortfall"] == 140.6
    assert result["implementation_shortfall_bps"] == 140.6


def test_calendar_handles_holidays_early_closes_and_full_session():
    assert len(session_minutes(date(2025, 7, 4))) == 0
    assert len(session_minutes(date(2025, 11, 28))) == 210
    result = run_simulation(demo_bars(), date(2025, 6, 9), 0, 390, 50000)
    assert len(result["market"]) == 390


def test_exact_integer_targets_and_decimal_capacity():
    assert cumulative_targets(600, [1 / 60] * 60) == [10 * i for i in range(1, 61)]
    bar = Bar(
        datetime(2025, 6, 9, 13, 30, tzinfo=timezone.utc),
        "TEST",
        100,
        101,
        99,
        100,
        100,
        100,
        False,
    )
    strategy = simulate_strategy("immediate", [bar], 100, "buy", 0.29, 0, 0, 0, [100])
    assert strategy["filled_shares"] == 29


def test_all_or_none_reference_method():
    bars = demo_bars()
    selected = (
        next(
            index
            for index, bar in enumerate(bars)
            if bar.timestamp.astimezone(ET).date() == date(2025, 6, 9)
        )
        + 30
    )
    bar = bars[selected]
    bars[selected] = Bar(
        bar.timestamp, bar.symbol, bar.open, bar.high, bar.low, bar.close, bar.volume, None, False
    )
    result = run_simulation(bars, date(2025, 6, 9), 30, 90, 50000)
    assert result["assumptions"]["reference_method"] == "hlc3"
