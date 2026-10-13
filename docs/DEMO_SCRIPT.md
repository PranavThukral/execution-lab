# 45-second Execution Lab walkthrough

About 125 spoken words. Aim for roughly 165 words per minute; rehearse once with the scrolling so the demo fits 45 seconds.

## Prepare before recording

Open the live demo and click **01 / Baseline**. Leave **TWAP** selected so the second graph shows TWAP fills. Run the comparison before speaking, then return to the top. This is a simulated stock order, not an order-book demo.

The inputs are **SIM_DEMO**, **9 June 2025**, **Buy**, **50,000 shares**, **10:00–11:00 ET**, **100% available volume**, **original price moves**, and a **10% participation cap**. Keep the default costs: **2 bps full spread**, **10 bps impact coefficient**, and **$0.005 fee per share**.

## Speak and show

**0–8 seconds — introduction:**

“I built Execution Lab to show how timing and liquidity change a large order’s cost, using Python, FastAPI, React and TypeScript.”

**8–16 seconds — point to the order inputs:**

“Here I’m buying 50,000 shares from ten to eleven Eastern, at normal volume with a ten-percent participation limit.”

**16–24 seconds — scroll to Shares filled over time:**

“The first graph shows shares filled: Immediate moves first, TWAP spreads evenly, and forecast VWAP follows earlier volume patterns. All reach 50,000.”

**24–32 seconds — point to Price, volume & fills and the comparison table:**

“The second overlays prices, volume and fills. This rising price path makes waiting more expensive: roughly $700 immediate, $16,900 TWAP, and $13,900 VWAP.”

**32–35 seconds — scroll to the cost breakdown:**

“Below, the breakdown separates price movement, spread, impact and fees.”

**35–45 seconds — finish at Important Assumptions:**

“The data is synthetic; costs are modeled, and minute bars don’t capture an order book. The result is a reproducible way to explain execution trade-offs, down to each fill.”

## Engineering follow-up, if asked

- VWAP uses only earlier eligible sessions, with its volume weights frozen before the test day.
- Baseline implementation shortfall is **$697.68 Immediate**, **$16,873.47 TWAP**, and **$13,885.00 forecast VWAP**. All three fill the full order; unfilled-share cost is zero here. These are total costs, not just spread or fees.
- The cumulative chart uses solid lines for fills and dashed lines for plans. Fills occur at minute end. In the second chart, the dark line is the reference price, bars show minute volume, and colored dots are the selected strategy’s modeled fill prices.
- The cap limits each minute’s fills. Changing to **Liquidity squeeze** leaves at least **142,075 shares unfilled** out of **200,000**, illustrating why completion matters alongside cost.
- These results describe this generated price path. They do not establish a universally best execution strategy.
- The frontend charts are custom SVG. The backend validates inputs, produces deterministic runs, and exports the order and fill ledger for reconciliation.
