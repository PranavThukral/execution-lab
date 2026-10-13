export type Dataset = {
  dataset_id: string;
  symbol: string;
  currency: string;
  data_kind: string;
  source: string;
  feed: string;
  calendar?: string;
  timezone?: string;
  bar_interval_seconds?: number;
  sessions: string[];
  content_sha256: string;
  session_bounds: Record<string, { start: string; end: string }>;
  quality?: {
    coverage?: number;
    missing_minutes?: number;
    observed_minutes?: number;
  };
};
export type Order = {
  dataset_id: string;
  side: "buy" | "sell";
  quantity: number;
  start: string;
  end: string;
  participation_cap: number;
  cost_model: {
    full_spread_bps: number;
    impact_coefficient_bps: number;
    fee_per_share: number;
  };
  scenario: { liquidity_multiplier: number; price_path_multiplier: number };
};
export type Point = {
  slot: number;
  timestamp: string;
  target: number;
  filled: number;
  desired: number;
  capacity: number;
  reference_price: number | null;
  volume: number;
  gap: boolean;
};
export type Fill = {
  strategy: string;
  slot: number;
  bar_start: string;
  filled_at: string;
  desired_shares: number;
  capacity_shares: number;
  shares: number;
  cumulative_filled: number;
  remaining_shares: number;
  reference_price: number;
  fill_price: number;
  impact_bps: number;
  spread_bps: number;
  fee: number;
};
export type Strategy = {
  strategy: string;
  filled_shares: number;
  unfilled_shares: number;
  fill_rate: number;
  average_execution_price: number | null;
  arrival_slippage_bps: number | null;
  vwap_slippage_bps: number | null;
  implementation_shortfall: number;
  implementation_shortfall_bps: number;
  execution_cost: number;
  timing_cost: number;
  spread_cost: number;
  impact_cost: number;
  fees: number;
  opportunity_cost: number;
  arrival_price: number;
  terminal_mark: number;
  market_vwap: number | null;
  series: Point[];
  fills: Fill[];
};
export type Result = {
  schema_version: number;
  engine_version: string;
  run_id: string;
  request: Order & { session: string; request_id?: string | null };
  dataset: Omit<Dataset, "sessions" | "session_bounds" | "quality">;
  assumptions: {
    reference_method: string;
    positive_cost_is_worse: boolean;
    modeled_spread_bps: number;
    impact_coefficient_bps: number;
  };
  profile: {
    eligible_session_dates: string[];
    fallback: boolean;
    weights: number[];
  };
  market: {
    slot: number;
    timestamp: string;
    reference_price: number | null;
    original_reference_price: number | null;
    volume: number;
    gap: boolean;
  }[];
  strategies: Strategy[];
  warnings: { code: string; message: string }[];
  diagnostics: {
    realized_capacity_shares: number;
    minimum_unfilled_shares: number;
    observed_minutes: number;
    expected_minutes: number;
    historical_capacity_estimate_shares: number | null;
    historical_capacity_range: number[] | null;
  };
};
