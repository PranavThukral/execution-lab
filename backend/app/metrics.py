from __future__ import annotations

import math
from typing import Literal


def calculate_metrics(
    fills: list[dict],
    quantity: int,
    side: Literal["buy", "sell"],
    arrival_price: float,
    terminal_mark: float,
    market_vwap: float | None,
    *,
    spread_bps: float = 0.0,
    impact_coefficient_bps: float = 0.0,
) -> dict:
    """Calculate signed costs from a fill ledger without depending on the simulator."""
    if (
        side not in {"buy", "sell"}
        or any(not math.isfinite(value) or value <= 0 for value in (arrival_price, terminal_mark))
        or (market_vwap is not None and (not math.isfinite(market_vwap) or market_vwap <= 0))
    ):
        raise ValueError("Invalid side or benchmark price")
    for fill in fills:
        shares = fill["shares"]
        if isinstance(shares, bool) or not isinstance(shares, int) or shares <= 0:
            raise ValueError("Fill shares must be positive integers")
        if not math.isfinite(fill["fill_price"]) or fill["fill_price"] <= 0:
            raise ValueError("Fill price must be finite and positive")
        if not math.isfinite(fill.get("fee", 0)) or fill.get("fee", 0) < 0:
            raise ValueError("Fees must be finite and nonnegative")
    sign = 1 if side == "buy" else -1
    filled = sum(int(fill["shares"]) for fill in fills)
    if quantity <= 0 or filled > quantity:
        raise ValueError("fill ledger exceeds the requested quantity")
    unfilled = quantity - filled
    average = (
        sum(fill["shares"] * fill["fill_price"] for fill in fills) / filled if filled else None
    )
    execution_cost = sign * sum(
        fill["shares"] * (fill["fill_price"] - arrival_price) for fill in fills
    )
    fees = sum(fill.get("fee", 0.0) for fill in fills)
    opportunity = sign * unfilled * (terminal_mark - arrival_price)
    shortfall = execution_cost + fees + opportunity
    timing_cost = sign * sum(
        fill["shares"] * (fill.get("reference_price", fill["fill_price"]) - arrival_price)
        for fill in fills
    )
    spread_cost = sum(
        fill["shares"]
        * fill.get("reference_price", fill["fill_price"])
        * (fill.get("spread_bps", spread_bps) / 2)
        / 10000
        for fill in fills
    )
    impact_cost = sum(
        fill["shares"]
        * fill.get("reference_price", fill["fill_price"])
        * fill.get("impact_bps", 0.0)
        / 10000
        for fill in fills
    )
    return {
        "filled_shares": filled,
        "unfilled_shares": unfilled,
        "fill_rate": filled / quantity,
        "average_execution_price": average,
        "arrival_price": arrival_price,
        "terminal_mark": terminal_mark,
        "market_vwap": market_vwap,
        "execution_cost": execution_cost,
        "timing_cost": timing_cost,
        "spread_cost": spread_cost,
        "impact_cost": impact_cost,
        "fees": fees,
        "opportunity_cost": opportunity,
        "implementation_shortfall": shortfall,
        "implementation_shortfall_bps": shortfall / (quantity * arrival_price) * 10000,
        "arrival_slippage_bps": None
        if average is None
        else sign * (average - arrival_price) / arrival_price * 10000,
        "vwap_slippage_bps": None
        if average is None or market_vwap is None
        else sign * (average - market_vwap) / market_vwap * 10000,
    }
