"""The versioned public response contract, also exposed through OpenAPI."""

from pydantic import BaseModel, ConfigDict


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DatasetMeta(Contract):
    model_config = ConfigDict(extra="allow", allow_inf_nan=False)
    dataset_id: str
    symbol: str
    currency: str
    data_kind: str
    source: str
    feed: str
    calendar: str
    timezone: str
    bar_interval_seconds: int
    content_sha256: str


class SessionBounds(Contract):
    start: str
    end: str


class DatasetCatalogItem(Contract):
    """The catalog shape consumed by the frontend before a run is submitted."""

    model_config = ConfigDict(extra="allow", allow_inf_nan=False)
    dataset_id: str
    symbol: str
    currency: str
    data_kind: str
    source: str
    feed: str
    calendar: str
    timezone: str
    bar_interval_seconds: int
    content_sha256: str
    sessions: list[str]
    session_bounds: dict[str, SessionBounds]
    quality: dict[str, float | int]


class DatasetCatalogResponse(Contract):
    datasets: list[DatasetCatalogItem]


class DefaultWindow(Contract):
    session: str
    start: str
    end: str


class DatasetDetailResponse(DatasetCatalogItem):
    default_window: DefaultWindow


class BarRecord(Contract):
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    market_vwap: float | None


class BarsResponse(Contract):
    session: str
    bars: list[BarRecord]


class Costs(Contract):
    full_spread_bps: float
    impact_coefficient_bps: float
    fee_per_share: float


class ScenarioInputs(Contract):
    liquidity_multiplier: float
    price_path_multiplier: float


class RunRequest(Contract):
    dataset_id: str
    session: str
    start: str
    end: str
    quantity: int
    side: str
    participation_cap: float
    cost_model: Costs
    scenario: ScenarioInputs
    request_id: str | None = None


class Assumptions(Contract):
    reference_method: str
    arrival_proxy: str
    fill_timing: str
    positive_cost_is_worse: bool
    modeled_spread_bps: float
    impact_coefficient_bps: float
    calendar_version: str


class Profile(Contract):
    strategy: str
    eligible_session_dates: list[str]
    fallback: bool
    weights: list[float]


class Point(Contract):
    slot: int
    timestamp: str
    target: int
    filled: int
    desired: int
    capacity: int
    reference_price: float | None
    volume: int
    gap: bool


class MarketPoint(Contract):
    slot: int
    timestamp: str
    reference_price: float | None
    original_reference_price: float | None
    volume: int
    gap: bool


class Fill(Contract):
    strategy: str
    slot: int
    bar_start: str
    filled_at: str
    desired_shares: int
    capacity_shares: int
    shares: int
    cumulative_filled: int
    remaining_shares: int
    reference_price: float
    fill_price: float
    impact_bps: float
    spread_bps: float
    fee: float


class Strategy(Contract):
    strategy: str
    filled_shares: int
    unfilled_shares: int
    fill_rate: float
    average_execution_price: float | None
    arrival_price: float
    terminal_mark: float
    market_vwap: float | None
    execution_cost: float
    timing_cost: float
    spread_cost: float
    impact_cost: float
    fees: float
    opportunity_cost: float
    implementation_shortfall: float
    implementation_shortfall_bps: float
    arrival_slippage_bps: float | None
    vwap_slippage_bps: float | None
    fills: list[Fill]
    series: list[Point]


class Warning(Contract):
    code: str
    message: str


class Diagnostics(Contract):
    realized_capacity_shares: int
    minimum_unfilled_shares: int
    observed_minutes: int
    expected_minutes: int
    historical_capacity_estimate_shares: int | None
    historical_capacity_range: list[int] | None


class RunResponse(Contract):
    schema_version: int
    engine_version: str
    run_id: str
    dataset: DatasetMeta
    request: RunRequest
    assumptions: Assumptions
    profile: Profile
    market: list[MarketPoint]
    strategies: list[Strategy]
    warnings: list[Warning]
    diagnostics: Diagnostics
