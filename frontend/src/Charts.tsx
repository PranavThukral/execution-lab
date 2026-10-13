import { useEffect, useRef, useState } from "react";
import type { PointerEvent } from "react";
import { integer } from "./format";
import { colors, price, shortTime, strategyLabel } from "./presentation";
import type { Point, Result, Strategy } from "./types";

function useChartWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(560);
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) =>
      setWidth(Math.max(160, Math.round(entry.contentRect.width))),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}
export function stepPath(
  points: Point[],
  field: "target" | "filled",
  x: (slot: number) => number,
  y: (value: number) => number,
) {
  return (
    "M " +
    x(0) +
    " " +
    y(0) +
    " " +
    points.map((p) => "H " + x(p.slot + 1) + " V " + y(p[field])).join(" ")
  );
}
export function segmentedPath(
  points: { slot: number; reference_price: number | null }[],
  x: (slot: number) => number,
  y: (value: number) => number,
) {
  let connected = false;
  return points
    .map((p) => {
      if (p.reference_price === null) {
        connected = false;
        return "";
      }
      const segment =
        (connected ? "L" : "M") +
        " " +
        x(p.slot + 1) +
        " " +
        y(p.reference_price);
      connected = true;
      return segment;
    })
    .join(" ");
}
export function shareTicks(quantity: number) {
  return [
    ...new Set(
      Array.from({ length: 5 }, (_, i) => Math.round((quantity * i) / 4)),
    ),
  ];
}
export function priceScale(values: number[]) {
  const low = Math.min(...values),
    high = Math.max(...values);
  const padding = Math.max(
    (high - low) * 0.08,
    Math.abs(low) * 0.0001,
    0.00001,
  );
  const rough = (high - low + padding * 2) / 4;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step =
    ([1, 2, 2.5, 5, 10].find((v) => v * power >= rough) ?? 10) * power;
  const min = Math.floor((low - padding) / step) * step;
  const max = Math.ceil((high + padding) / step) * step;
  const ticks = Array.from(
    { length: Math.round((max - min) / step) + 1 },
    (_, i) => min + i * step,
  );
  const decimals = Math.max(2, Math.min(10, -Math.floor(Math.log10(step))));
  return { min, max, ticks, decimals };
}
function clockAt(result: Result, slot: number) {
  return shortTime(
    new Date(
      new Date(result.request.start).getTime() + slot * 60000,
    ).toISOString(),
  );
}
function tickSlots(n: number, width: number) {
  const parts = width < 440 ? 2 : 4;
  return [
    ...new Set(
      Array.from({ length: parts + 1 }, (_, i) => Math.round((n * i) / parts)),
    ),
  ];
}
function inspectAt(
  event: PointerEvent<SVGSVGElement>,
  width: number,
  left: number,
  right: number,
  n: number,
  onInspect: (index: number) => void,
) {
  const rect = event.currentTarget.getBoundingClientRect();
  const local = ((event.clientX - rect.left) * width) / rect.width;
  onInspect(
    Math.max(
      0,
      Math.min(n - 1, Math.round(((local - left) / (right - left)) * n) - 1),
    ),
  );
}
type Shared = {
  result: Result;
  active: number;
  onInspect: (index: number) => void;
};
export function CumulativeChart({ result, active, onInspect }: Shared) {
  const { ref, width } = useChartWidth();
  const q = result.request.quantity,
    n = result.market.length;
  const left = q >= 100000 ? 94 : width < 400 ? 65 : 78,
    right = width - 16;
  const x = (slot: number) => left + (slot / n) * (right - left);
  const y = (value: number) => 270 - (value / q) * 225;
  return (
    <div className="chart-frame" ref={ref}>
      <svg
        viewBox={"0 0 " + width + " 320"}
        role="img"
        aria-label="Shares filled and planned, from zero to the full order"
        onPointerMove={(e) => inspectAt(e, width, left, right, n, onInspect)}
      >
        <text className="axis-title" x="0" y="18">
          Shares
        </text>
        {shareTicks(q).map((value) => (
          <g key={value}>
            <line
              className="grid-line"
              x1={left}
              x2={right}
              y1={y(value)}
              y2={y(value)}
            />
            <text x={left - 12} textAnchor="end" y={y(value) + 4}>
              {integer(value)}
            </text>
          </g>
        ))}
        {tickSlots(n, width).map((slot) => (
          <g key={slot}>
            <line
              className="time-grid"
              x1={x(slot)}
              x2={x(slot)}
              y1="42"
              y2="270"
            />
            <text
              x={x(slot)}
              textAnchor={slot === 0 ? "start" : slot === n ? "end" : "middle"}
              y="299"
            >
              {clockAt(result, slot)}
            </text>
          </g>
        ))}
        {result.strategies.map((s) => (
          <g key={s.strategy}>
            <path
              d={stepPath(s.series, "target", x, y)}
              fill="none"
              stroke={colors[s.strategy]}
              strokeDasharray="5 5"
              strokeWidth="1.3"
              opacity="0.5"
            />
            <path
              d={stepPath(s.series, "filled", x, y)}
              fill="none"
              stroke={colors[s.strategy]}
              strokeWidth="2.6"
              strokeLinejoin="round"
            />
          </g>
        ))}
        <line
          className="chart-crosshair"
          x1={x(active + 1)}
          x2={x(active + 1)}
          y1="42"
          y2="270"
        />
        {result.strategies.map((s) => (
          <circle
            key={s.strategy}
            cx={x(active + 1)}
            cy={y(s.series[active].filled)}
            r="4"
            fill={colors[s.strategy]}
            stroke="white"
            strokeWidth="1.5"
          />
        ))}
        <text className="axis-time" x={right} textAnchor="end" y="318">
          Time (ET)
        </text>
      </svg>
      <div className="chart-readout cumulative-readout" aria-live="polite">
        {result.strategies.map((s) => (
          <div key={s.strategy}>
            <span>
              <i style={{ background: colors[s.strategy] }} />
              {strategyLabel(result, s.strategy)}
            </span>
            <strong>
              {integer(s.series[active].filled)} <small>shares</small>
            </strong>
          </div>
        ))}
      </div>
    </div>
  );
}
export function PriceChart({
  result,
  selected,
  active,
  onInspect,
}: Shared & { selected: Strategy }) {
  const { ref, width } = useChartWidth();
  const points = result.market,
    n = points.length,
    point = points[active];
  const fill = selected.fills.find((f) => f.slot === active);
  const scale = priceScale([
    ...points.flatMap((p) =>
      [p.reference_price, p.original_reference_price].filter(
        (v): v is number => v !== null,
      ),
    ),
    ...selected.fills.map((f) => f.fill_price),
  ]);
  const observedMaxVolume = Math.max(...points.map((p) => p.volume), 0);
  const volumeStep =
    10 ** Math.floor(Math.log10(Math.max(observedMaxVolume, 1)));
  const maxVolume = Math.max(
    1,
    Math.ceil(observedMaxVolume / volumeStep) * volumeStep,
  );
  const volumeTicks =
    observedMaxVolume === 0
      ? [0]
      : [...new Set([0, Math.round(maxVolume / 2), maxVolume])];
  const left = width < 400 ? 76 : 88,
    right = width - 16,
    plotWidth = right - left;
  const x = (slot: number) => left + (slot / n) * plotWidth;
  const y = (value: number) =>
    42 + (1 - (value - scale.min) / (scale.max - scale.min)) * 147;
  const stressed = result.request.scenario.price_path_multiplier !== 1;
  return (
    <div className="chart-frame" ref={ref}>
      <svg
        viewBox={"0 0 " + width + " 320"}
        role="img"
        aria-label="Stock price, minute volume and selected strategy fill prices"
        onPointerMove={(e) => inspectAt(e, width, left, right, n, onInspect)}
      >
        <text className="axis-title" x="0" y="18">
          Price ({result.dataset.currency})
        </text>
        {scale.ticks.map((value) => (
          <g key={value}>
            <line
              className="grid-line"
              x1={left}
              x2={right}
              y1={y(value)}
              y2={y(value)}
            />
            <text x={left - 12} textAnchor="end" y={y(value) + 4}>
              {value.toFixed(scale.decimals)}
            </text>
          </g>
        ))}
        <text className="axis-title" x="0" y="219">
          Volume (shares)
        </text>
        {volumeTicks.map((value) => (
          <g key={value}>
            <text
              x={left - 12}
              textAnchor="end"
              y={273 - (value / maxVolume) * 42 + 4}
            >
              {integer(value)}
            </text>
            <line
              className="volume-grid"
              x1={left}
              x2={right}
              y1={273 - (value / maxVolume) * 42}
              y2={273 - (value / maxVolume) * 42}
            />
          </g>
        ))}
        {points.map((p) =>
          p.gap ? (
            <rect
              key={p.slot}
              x={x(p.slot)}
              y="42"
              width={plotWidth / n}
              height="231"
              className="gap-band"
            >
              <title>{"Missing minute: " + shortTime(p.timestamp)}</title>
            </rect>
          ) : (
            <rect
              key={p.slot}
              className="volume-bar"
              x={x(p.slot)}
              y={273 - (p.volume / maxVolume) * 42}
              width={Math.max(0.25, plotWidth / n - 0.8)}
              height={(p.volume / maxVolume) * 42}
            />
          ),
        )}
        {tickSlots(n, width).map((slot) => (
          <g key={slot}>
            <line
              className="time-grid"
              x1={x(slot)}
              x2={x(slot)}
              y1="42"
              y2="189"
            />
            <text
              x={x(slot)}
              textAnchor={slot === 0 ? "start" : slot === n ? "end" : "middle"}
              y="299"
            >
              {clockAt(result, slot)}
            </text>
          </g>
        ))}
        {stressed && (
          <path
            d={segmentedPath(
              points.map((p) => ({
                ...p,
                reference_price: p.original_reference_price,
              })),
              x,
              y,
            )}
            fill="none"
            stroke="#949ba9"
            strokeDasharray="4 4"
            strokeWidth="1.5"
          />
        )}
        <path
          d={segmentedPath(points, x, y)}
          fill="none"
          stroke="#20324d"
          strokeWidth="2.3"
        />
        {points.length === 1 && point.reference_price !== null && (
          <circle
            cx={x(1)}
            cy={y(point.reference_price)}
            r="4"
            fill="#20324d"
          />
        )}
        {selected.fills.map((f) => (
          <circle
            key={f.slot}
            cx={x(f.slot + 1)}
            cy={y(f.fill_price)}
            r={n > 100 ? 1.7 : 2.6}
            fill={colors[selected.strategy]}
          >
            <title>
              {shortTime(f.filled_at) +
                " · " +
                integer(f.shares) +
                " shares · " +
                price(f.fill_price)}
            </title>
          </circle>
        ))}
        <line
          className="chart-crosshair"
          x1={x(active + 1)}
          x2={x(active + 1)}
          y1="42"
          y2="273"
        />
        {point.reference_price !== null && (
          <circle
            cx={x(active + 1)}
            cy={y(point.reference_price)}
            r="4"
            fill="#20324d"
            stroke="white"
            strokeWidth="1.5"
          />
        )}
        <text className="axis-time" x={right} textAnchor="end" y="318">
          Time (ET)
        </text>
      </svg>
      <div className="chart-readout" aria-live="polite">
        <div>
          <span>Market price</span>
          <strong>
            {point.reference_price === null
              ? "Missing"
              : point.reference_price.toFixed(4)}
          </strong>
        </div>
        <div>
          <span>Volume</span>
          <strong>
            {integer(point.volume)} <small>shares</small>
          </strong>
        </div>
        <div>
          <span>{strategyLabel(result, selected.strategy)} fill</span>
          <strong>
            {integer(fill?.shares ?? 0)} <small>shares</small>
          </strong>
        </div>
      </div>
    </div>
  );
}
export function ExecutionCharts({
  result,
  selected,
}: {
  result: Result;
  selected: Strategy;
}) {
  const [active, setActive] = useState(0);
  const index = Math.min(active, result.market.length - 1);
  return (
    <section className="chart-section" aria-label="Execution charts">
      <div className="chart-pair">
        <div className="chart-panel panel">
          <div className="chart-heading">
            <h2>Shares filled over time</h2>
            <p>Solid = filled · dashed = planned</p>
          </div>
          <CumulativeChart
            result={result}
            active={index}
            onInspect={setActive}
          />
        </div>
        <div className="chart-panel panel">
          <div className="chart-heading">
            <h2>Price, volume & fills</h2>
            <p>
              {strategyLabel(result, selected.strategy)} fills
              {result.request.scenario.price_path_multiplier !== 1
                ? " · dashed: original"
                : ""}
              {result.market.some((p) => p.gap) ? " · red: missing" : ""}
            </p>
          </div>
          <PriceChart
            result={result}
            selected={selected}
            active={index}
            onInspect={setActive}
          />
        </div>
      </div>
      <div className="chart-toolbar">
        <p>Hover a chart to inspect a minute.</p>
        <div className="minute-controls">
          <button
            type="button"
            aria-label="Previous minute"
            disabled={index === 0}
            onClick={() => setActive(index - 1)}
          >
            ←
          </button>
          <label htmlFor="inspect-minute">
            Minute{" "}
            <input
              id="inspect-minute"
              type="number"
              aria-label="Inspect minute"
              min="1"
              max={result.market.length}
              value={index + 1}
              onChange={(e) =>
                setActive(
                  Math.max(
                    0,
                    Math.min(
                      result.market.length - 1,
                      Math.round(Number(e.target.value)) - 1,
                    ),
                  ),
                )
              }
            />{" "}
            / {result.market.length}
          </label>
          <button
            type="button"
            aria-label="Next minute"
            disabled={index === result.market.length - 1}
            onClick={() => setActive(index + 1)}
          >
            →
          </button>
          <output htmlFor="inspect-minute">
            {clockAt(result, index)}–{clockAt(result, index + 1)} ET
          </output>
        </div>
      </div>
    </section>
  );
}
