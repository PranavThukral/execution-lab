# Methodology

Bars are one-minute intervals `[timestamp, timestamp + 1 minute)` in UTC after parsing. The UI converts timestamps to America/New_York for display. The default dataset is six deterministic project-generated regular sessions, with five earlier sessions available for the forecast profile and June 9, 2025 used for evaluation.

The demo's volume is synthetic and should be read as a fixture, not as market history. Historical imports must retain source, feed, adjustment, retrieval date, currency, and data-quality counts. Missing interior minutes have zero execution capacity; the simulator never interpolates prices or volume.

Immediate attempts the full parent order at the first slot but remains capacity limited. TWAP uses equal cumulative share targets. Forecast-volume VWAP averages normalized volume curves from up to the five latest eligible earlier sessions and freezes those weights before evaluation. If fewer than three eligible sessions exist, it uses a labeled uniform fallback.

The arrival proxy is the first selected bar's open. A run chooses one reference method: reported market VWAP when every observed selected bar supplies it, otherwise HLC3 for every observed bar. Each fill is recorded at bar end. Capacity is `floor(participation cap × volume)`. Modeled fill price adds half the full spread and square-root impact in the trade direction. These costs are configurable illustrations; they are not calibrated estimates.

Positive signed costs are worse execution for both sides. Executed arrival cost includes timing relative to the arrival proxy, modeled spread, and modeled impact. Fees are explicit. Opportunity cost is the unfilled quantity marked from arrival to the terminal close. Implementation shortfall is their sum. Arrival and realized-window VWAP slippage concern filled shares and exclude fees.

The forecast VWAP schedule and realized market VWAP benchmark are deliberately separate. A VWAP schedule can be poor against its realized benchmark; a favorable filled price does not erase the opportunity cost of residual shares.

Minute bars cannot reconstruct quotes, order-book depth, queue position, auction allocation, or intrabar timing. The price-path stress scales log deviations but is not a volatility forecast. The output supports engineering discussion and execution reasoning; it is not trading advice or a backtest of a profitable strategy.

## Capacity and timing

The prior-session capacity estimate averages `sum(floor(cap × floor(prior minute volume × liquidity multiplier)))` across eligible earlier windows. It uses raw volume levels separately from VWAP's averaged volume fractions. The displayed range is the minimum/maximum across those windows, not a confidence interval. An estimate is unavailable when fewer than three prior windows qualify.

Realized capacity sums the minute capacities of the evaluation replay. It is an upper bound under this bar fill model, computed with evaluation volume; it must not be presented as a pre-trade forecast. When capacity is below quantity, every schedule is guaranteed to leave at least the difference unfilled under these assumptions. When capacity exceeds quantity, timing can still prevent scheduled completion.

Prior windows must fit wholly inside the exchange session and have at least 95% observed-minute coverage and positive volume. Missing prior minutes receive zero weight. Exact rational fractions preserve cumulative share rounding; the final target is exactly the parent quantity. Evaluation and later sessions cannot alter the frozen profile. Tests explicitly change evaluation volume to verify this separation.

Charts start cumulative execution at zero and place step increases at minute end. Price paths break at missing observations. Fill markers show modeled fill prices; the inspector gives reference, volume, filled quantity and time. Dashed original prices provide context during price-path stress.

Shortfall attribution uses signed timing and opportunity cost; either can be negative. Spread and impact are modeled adverse costs. The five cost components reconcile to implementation shortfall within floating-point tolerance. No scenario changes the market path in response to the hypothetical order, so market-impact feedback, cross-strategy interactions, auctions, fragmented Canadian venues, and empirical calibration remain outside this MVP.
