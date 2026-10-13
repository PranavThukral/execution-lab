import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, FormEvent } from "react";
import { bps, integer } from "./format";
import { ExecutionCharts } from "./Charts";
import { TimePicker } from "./TimePicker";
import {
  colors,
  exchangeTimestamp,
  money,
  price,
  shortTime,
  strategyLabel,
} from "./presentation";
import type { Dataset, Order, Result } from "./types";

const defaults = {
  dataset: "demo-sim-v1",
  session: "2025-06-09",
  side: "buy" as "buy" | "sell",
  quantity: 50000,
  start: "10:00",
  end: "11:00",
  liquidity: 1,
  stress: 1,
  cap: 0.1,
  spread: 2,
  impact: 10,
  fee: 0.005,
};
type Inputs = typeof defaults;
async function requestJson<T>(
  url: string,
  options?: RequestInit,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(url, { ...options, signal });
  const body = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(
      body?.error?.fields?.length
        ? `${body.error.message}: ${body.error.fields.map((f: { field: string; message: string }) => `${f.field} ${f.message}`).join("; ")}`
        : (body?.error?.message ?? "The request failed. Please try again."),
    );
  return body as T;
}
const toOrder = (i: Inputs): Order => ({
  dataset_id: i.dataset,
  side: i.side,
  quantity: i.quantity,
  start: exchangeTimestamp(i.session, i.start),
  end: exchangeTimestamp(i.session, i.end),
  participation_cap: i.cap,
  cost_model: {
    full_spread_bps: i.spread,
    impact_coefficient_bps: i.impact,
    fee_per_share: i.fee,
  },
  scenario: {
    liquidity_multiplier: i.liquidity,
    price_path_multiplier: i.stress,
  },
});

const examples: {
  id: string;
  title: string;
  detail: string;
  question: string;
  color: string;
  patch: Partial<Inputs>;
}[] = [
  {
    id: "baseline",
    title: "Baseline",
    detail: "50,000 shares · buy",
    question: "What does waiting cost on this price path?",
    color: "#2860df",
    patch: {},
  },
  {
    id: "liquidity",
    title: "Liquidity squeeze",
    detail: "200,000 shares · 20% volume",
    question: "Can the available volume support a larger order?",
    color: "#e86528",
    patch: { quantity: 200000, liquidity: 0.2 },
  },
  {
    id: "timing",
    title: "Side & timing",
    detail: "50,000 shares · sell · 3× moves",
    question: "Does the same timing choice still work for a sell?",
    color: "#008b7e",
    patch: { side: "sell", stress: 3 },
  },
];
function caseFor(i: Inputs) {
  return examples.find((c) =>
    Object.entries({ ...defaults, ...c.patch }).every(
      ([key, value]) => i[key as keyof Inputs] === value,
    ),
  );
}
function dayLabel(day: string, year = false) {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    ...(year ? { year: "numeric" } : {}),
    timeZone: "UTC",
  }).format(new Date(day + "T12:00:00Z"));
}

export function App() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [inputs, setInputs] = useState<Inputs>(defaults);
  const [result, setResult] = useState<Result | null>(null);
  const [selected, setSelected] = useState("twap");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [catalogError, setCatalogError] = useState("");
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogAttempt, setCatalogAttempt] = useState(0);
  const [dirty, setDirty] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const sequence = useRef(0);
  const resultHeading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    resultHeading.current?.focus({ preventScroll: true });
  }, [result]);
  useEffect(() => {
    const lifetime = sequence;
    const abort = new AbortController();
    let timedOut = false;
    const timeout = window.setTimeout(() => {
      timedOut = true;
      abort.abort();
      setCatalogLoading(false);
      setCatalogError("Dataset loading timed out. Check the server and retry.");
    }, 15000);
    requestJson<{ datasets: Dataset[] }>(
      "/api/v1/datasets",
      undefined,
      abort.signal,
    )
      .then((body) => {
        if (abort.signal.aborted) return;
        if (!body.datasets.length)
          throw new Error(
            "No datasets are available. Check the server and retry.",
          );
        setDatasets(body.datasets);
        const item =
          body.datasets.find((d) => d.dataset_id === defaults.dataset) ??
          body.datasets[0];
        if (item) {
          const session = item.sessions.at(-1)!;
          const bounds = item.session_bounds[session];
          setInputs((current) => ({
            ...current,
            dataset: item.dataset_id,
            session,
            start:
              current.dataset === item.dataset_id && current.session === session
                ? current.start
                : bounds.start <= "10:00" && bounds.end >= "11:00"
                  ? "10:00"
                  : bounds.start,
            end:
              current.dataset === item.dataset_id && current.session === session
                ? current.end
                : bounds.start <= "10:00" && bounds.end >= "11:00"
                  ? "11:00"
                  : bounds.end,
          }));
        }
      })
      .catch((err) => {
        if (!abort.signal.aborted) setCatalogError(err.message);
      })
      .finally(() => {
        window.clearTimeout(timeout);
        if (!abort.signal.aborted || timedOut) setCatalogLoading(false);
      });
    return () => {
      abort.abort();
      window.clearTimeout(timeout);
      controller.current?.abort();
      lifetime.current++;
    };
  }, [catalogAttempt]);
  const chosenDataset = datasets.find((d) => d.dataset_id === inputs.dataset);
  const bounds = chosenDataset?.session_bounds[inputs.session];
  const payload = useMemo(() => toOrder(inputs), [inputs]);
  const strategy =
    result?.strategies.find((s) => s.strategy === selected) ??
    result?.strategies[0];
  const cancel = () => {
    sequence.current++;
    controller.current?.abort();
    setLoading(false);
  };
  const change = (patch: Partial<Inputs>) => {
    cancel();
    setInputs((current) => ({ ...current, ...patch }));
    setDirty(true);
    setError("");
  };
  const run = async (order = payload) => {
    controller.current?.abort();
    const current = ++sequence.current;
    const abort = new AbortController();
    controller.current = abort;
    let timedOut = false;
    const timeout = window.setTimeout(() => {
      timedOut = true;
      abort.abort();
    }, 15000);
    setLoading(true);
    setError("");
    try {
      const next = await requestJson<Result>(
        "/api/v1/simulations",
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(order),
        },
        abort.signal,
      );
      if (current !== sequence.current) return;
      setResult(next);
      setDirty(false);
    } catch (err) {
      if (current !== sequence.current) return;
      if (timedOut)
        setError("The comparison timed out after 15 seconds. Please retry.");
      else if (!abort.signal.aborted)
        setError(err instanceof Error ? err.message : "Simulation failed");
    } finally {
      window.clearTimeout(timeout);
      if (current === sequence.current) setLoading(false);
    }
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (canRun) void run();
  };
  const preset = (patch: Partial<Inputs>) => {
    const next = { ...defaults, ...patch };
    change(next);
    void run(toOrder(next));
  };
  const selectSession = (dataset: Dataset, session: string) => {
    const b = dataset.session_bounds[session];
    change({
      dataset: dataset.dataset_id,
      session,
      start: b.start <= "10:00" && b.end >= "11:00" ? "10:00" : b.start,
      end: b.start <= "10:00" && b.end >= "11:00" ? "11:00" : b.end,
    });
  };
  const exportHref = (kind: string) => {
    if (!result) return "#";
    const {
      dataset_id,
      side,
      quantity,
      start,
      end,
      participation_cap,
      cost_model,
      scenario,
    } = result.request;
    const submitted: Order = {
      dataset_id,
      side,
      quantity,
      start,
      end,
      participation_cap,
      cost_model,
      scenario,
    };
    return `/api/v1/exports?${new URLSearchParams({ payload: JSON.stringify(submitted), kind, strategy: selected })}`;
  };
  const label = (name: string) => (result ? strategyLabel(result, name) : name);
  const validation =
    !inputs.start || !inputs.end
      ? "Enter both a start and end time."
      : !Number.isInteger(inputs.quantity) ||
          inputs.quantity < 1 ||
          inputs.quantity > 1000000
        ? "Shares must be a whole number between 1 and 1,000,000."
        : inputs.cap < 0.01 || inputs.cap > 0.5
          ? "Participation cap must be between 0.01 and 0.50."
          : inputs.spread < 0 || inputs.spread > 50
            ? "Full spread must be between 0 and 50 bps."
            : inputs.impact < 0 || inputs.impact > 100
              ? "Impact coefficient must be between 0 and 100 bps."
              : inputs.fee < 0 || inputs.fee > 0.05
                ? "Fee per share must be between 0 and 0.05."
                : !Number.isFinite(inputs.liquidity) ||
                    inputs.liquidity < 0.1 ||
                    inputs.liquidity > 2
                  ? "Available volume must be between 10% and 200%."
                  : inputs.start >= inputs.end
                    ? "End must be later than start."
                    : !bounds ||
                        inputs.start < bounds.start ||
                        inputs.end > bounds.end
                      ? "Choose a window within the observed session bounds."
                      : "";
  const canRun =
    !loading && !catalogLoading && datasets.length > 0 && !validation;
  const complete =
    result?.strategies.filter((s) => s.unfilled_shares === 0) ?? [];
  const lowestComplete = complete.length
    ? complete.reduce((a, b) =>
        a.implementation_shortfall < b.implementation_shortfall ? a : b,
      )
    : null;

  const activeCase = caseFor(inputs);
  const synthetic = !chosenDataset || chosenDataset.data_kind === "synthetic";
  const sessions = chosenDataset?.sessions ?? [
    "2025-06-02",
    "2025-06-03",
    "2025-06-04",
    "2025-06-05",
    "2025-06-06",
    "2025-06-09",
  ];
  const count =
    chosenDataset?.quality?.observed_minutes ?? (chosenDataset ? null : 2340);

  return (
    <>
      <a className="skip-link" href="#execution-order">
        Skip to order controls
      </a>
      <main className="shell" id="main-content">
        <header className="topbar">
          <a
            className="brand"
            href="#main-content"
            aria-label="Execution Lab home"
          >
            <span className="brand-mark" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
            <h1>Execution Lab</h1>
          </a>
          <a className="text-link" href="#important-assumptions">
            How it works <span aria-hidden="true">↗</span>
          </a>
        </header>

        <section className="dataset-overview" aria-labelledby="dataset-title">
          <div className="dataset-story">
            <span className="source-tag">
              {synthetic
                ? "Generated sample dataset"
                : "Historical data · " + chosenDataset?.source}
            </span>
            <h2 id="dataset-title">
              How much does timing matter when you trade a large order?
            </h2>
            <p className="dataset-lede">One order, with three ways to fill.</p>
            <p>
              {synthetic ? (
                <>
                  I created <strong>SIM_DEMO</strong>, a fictional stock with
                  one-minute prices and volume. It covers {sessions.length} US
                  market sessions, from {dayLabel(sessions[0])} to
                  {dayLabel(sessions.at(-1)!, true)}. The selected day tests the
                  trading strategies on different circumstances and prices.
                </>
              ) : (
                <>
                  {chosenDataset?.symbol} comes from {chosenDataset?.source} (
                  {chosenDataset?.feed}), covering {dayLabel(sessions[0])}–
                  {dayLabel(sessions.at(-1)!, true)}. Earlier sessions build the
                  volume forecast; the selected day tests the strategies.
                </>
              )}
            </p>
          </div>
          <div className="dataset-facts">
            <div className="dataset-counts">
              <div>
                <strong>{sessions.length}</strong>
                <span>market sessions</span>
              </div>
              <div>
                <strong>{count == null ? "1 min" : integer(count)}</strong>
                <span>
                  {count == null
                    ? "per observation"
                    : "one-minute observations"}
                </span>
              </div>
            </div>
            <div className="session-strip" aria-label="Dataset sessions">
              {sessions.map((s) => (
                <span
                  key={s}
                  className={
                    s === inputs.session
                      ? "test-session"
                      : s < inputs.session
                        ? "prior-session"
                        : "future-session"
                  }
                >
                  <small>
                    {new Date(s + "T12:00:00Z").toLocaleDateString("en-US", {
                      weekday: "short",
                      timeZone: "UTC",
                    })}
                  </small>
                  <b>{s.slice(-2)}</b>
                </span>
              ))}
            </div>
            <div className="session-key">
              <span>
                <i className="prior-key" /> Earlier days
              </span>
              <span>
                <i className="test-key" /> Test day
              </span>
            </div>
            <p className="data-meta">
              {chosenDataset?.currency ?? "USD"} · {bounds?.start ?? "09:30"}–
              {bounds?.end ?? "16:00"} ET ·{" "}
              {synthetic
                ? "Prices and volume are simulated."
                : chosenDataset?.calendar}
            </p>
          </div>
        </section>

        <section className="cases" aria-label="Example cases">
          <div className="section-heading">
            <h2>Start with an example</h2>
            <span>Choose one to run the comparison.</span>
          </div>
          <div className="case-buttons">
            {examples.map((c, index) => (
              <button
                key={c.id}
                disabled={
                  loading ||
                  !datasets.some((d) => d.dataset_id === defaults.dataset)
                }
                aria-pressed={activeCase?.id === c.id}
                className={activeCase?.id === c.id ? "active-case" : ""}
                style={{ "--case-color": c.color } as CSSProperties}
                onClick={() => preset(c.patch)}
              >
                <span className="case-number">0{index + 1}</span>
                <span className="case-copy">
                  <strong>{c.title}</strong>
                  <span>{c.detail}</span>
                </span>
                <span className="case-check" aria-hidden="true">
                  {activeCase?.id === c.id ? "✓" : "↗"}
                </span>
              </button>
            ))}
          </div>
          <p className="case-question">
            <strong>
              {activeCase ? activeCase.title + ":" : "Custom order:"}
            </strong>{" "}
            {activeCase?.question ??
              "Here, you can compare your own size, timing, and market conditions."}
          </p>
        </section>

        {catalogError && (
          <div className="error" role="alert">
            {catalogError}{" "}
            <button
              type="button"
              onClick={() => {
                setCatalogLoading(true);
                setCatalogError("");
                setCatalogAttempt((attempt) => attempt + 1);
              }}
            >
              Retry dataset loading
            </button>
          </div>
        )}
        <div className="execution-workspace">
          <form
            className="controls"
            id="execution-order"
            onSubmit={submit}
            aria-label="Execution order"
            aria-busy={loading || catalogLoading}
          >
            <div className="form-heading">
              <h2>Your order</h2>
              <span>Times in New York (ET)</span>
            </div>
            <div className="order-fields">
              <div className="order-primary">
                {datasets.length > 1 && (
                  <label htmlFor="dataset">
                    Dataset
                    <select
                      id="dataset"
                      aria-label="Dataset"
                      value={inputs.dataset}
                      onChange={(e) => {
                        const item = datasets.find(
                          (d) => d.dataset_id === e.target.value,
                        )!;
                        selectSession(item, item.sessions.at(-1)!);
                      }}
                    >
                      {datasets.map((d) => (
                        <option key={d.dataset_id} value={d.dataset_id}>
                          {d.symbol}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <label htmlFor="session">
                  Session
                  <select
                    id="session"
                    aria-label="Session"
                    value={inputs.session}
                    onChange={(e) =>
                      chosenDataset &&
                      selectSession(chosenDataset, e.target.value)
                    }
                  >
                    {(chosenDataset?.sessions ?? [defaults.session]).map(
                      (s) => (
                        <option key={s} value={s}>
                          {dayLabel(s, true)}
                        </option>
                      ),
                    )}
                  </select>
                </label>
                <label htmlFor="side">
                  Side
                  <select
                    id="side"
                    aria-label="Side"
                    value={inputs.side}
                    onChange={(e) =>
                      change({ side: e.target.value as "buy" | "sell" })
                    }
                  >
                    <option value="buy">Buy</option>
                    <option value="sell">Sell</option>
                  </select>
                </label>
                <label htmlFor="quantity">
                  Shares
                  <input
                    id="quantity"
                    type="number"
                    min="1"
                    max="1000000"
                    required
                    value={inputs.quantity}
                    onChange={(e) =>
                      change({ quantity: Number(e.target.value) })
                    }
                  />
                </label>
              </div>
              <div className="order-timing">
                <TimePicker
                  id="start"
                  label="Start"
                  min={bounds?.start}
                  max={bounds?.end}
                  value={inputs.start}
                  onChange={(start) => change({ start })}
                />
                <TimePicker
                  id="end"
                  label="End"
                  min={bounds?.start}
                  max={bounds?.end}
                  value={inputs.end}
                  onChange={(end) => change({ end })}
                />
              </div>
            </div>
            <div className="market-controls">
              <label htmlFor="liquidity">
                Available volume
                <div className="suffix-input">
                  <input
                    id="liquidity"
                    aria-label="Available volume"
                    type="number"
                    min="10"
                    max="200"
                    step="1"
                    required
                    value={Math.round(inputs.liquidity * 100)}
                    onChange={(e) =>
                      change({ liquidity: Number(e.target.value) / 100 })
                    }
                  />
                  <span aria-hidden="true">%</span>
                </div>
                <small>100% uses the dataset’s usual volume.</small>
              </label>
              <label htmlFor="stress">
                Price movement
                <select
                  id="stress"
                  aria-label="Price movement"
                  value={inputs.stress}
                  onChange={(e) => change({ stress: Number(e.target.value) })}
                >
                  <option value="1">Original price moves</option>
                  <option value="1.5">1.5× larger moves</option>
                  <option value="2">2× larger moves</option>
                  <option value="3">3× larger moves</option>
                </select>
                <small>
                  Amplifies rises and falls from the starting price.
                </small>
              </label>
              <div className="order-actions">
                <button className="primary" type="submit" disabled={!canRun}>
                  {loading ? "Comparing…" : "Compare strategies →"}
                </button>
                <button
                  className="reset-button"
                  type="button"
                  onClick={() => change(defaults)}
                >
                  Reset inputs
                </button>
              </div>
            </div>
            <details className="advanced">
              <summary>Adjust costs & participation limit</summary>
              <p>
                A 10% limit lets the order use up to 10% of each minute’s market
                volume.
              </p>
              <div className="advanced-grid">
                {(
                  [
                    {
                      key: "cap",
                      title: "Participation cap",
                      min: 0.01,
                      max: 0.5,
                      step: 0.01,
                    },
                    {
                      key: "spread",
                      title: "Full spread (bps)",
                      min: 0,
                      max: 50,
                      step: 0.1,
                    },
                    {
                      key: "impact",
                      title: "Impact coefficient (bps)",
                      min: 0,
                      max: 100,
                      step: 0.1,
                    },
                    {
                      key: "fee",
                      title:
                        "Fee / share (" +
                        (chosenDataset?.currency ?? "USD") +
                        ")",
                      min: 0,
                      max: 0.05,
                      step: 0.0001,
                    },
                  ] as const
                ).map((f) => (
                  <label key={f.key} htmlFor={f.key}>
                    {f.title}
                    <input
                      id={f.key}
                      type="number"
                      required
                      min={f.min}
                      max={f.max}
                      step={f.step}
                      value={inputs[f.key]}
                      onChange={(e) =>
                        change({ [f.key]: Number(e.target.value) })
                      }
                    />
                  </label>
                ))}
              </div>
            </details>
            {validation && !catalogLoading && datasets.length > 0 && (
              <p className="validation" role="alert">
                {validation}
              </p>
            )}
          </form>
          <div className="results-pane" aria-label="Execution results">
            {dirty && result && (
              <p className="dirty" role="status">
                Changes pending. Run the comparison to update the results below.
              </p>
            )}
            {error && (
              <div className="error" role="alert">
                {error}
                {result && (
                  <p>
                    Your previous result is still shown. Retry to update it.
                  </p>
                )}
              </div>
            )}
            {loading && (
              <p className="loading-message" role="status">
                Comparing all three strategies…
              </p>
            )}
            {!result && !error && (
              <div className="empty">
                <h2>Ready when you are.</h2>
                <p>Choose an example above or compare your own order.</p>
              </div>
            )}

            {result && strategy && (
              <>
                <section
                  className="summary"
                  id="execution-results"
                  aria-live="polite"
                  aria-atomic="true"
                >
                  <div>
                    <span className="section-label">The result</span>
                    <h2 ref={resultHeading} tabIndex={-1}>
                      {result.dataset.symbol} ·{" "}
                      {result.request.side.toUpperCase()} ·{" "}
                      {integer(result.request.quantity)} shares
                    </h2>
                    <p>
                      {dayLabel(result.request.session, true)} ·{" "}
                      {shortTime(result.request.start)}–
                      {shortTime(result.request.end)} ET ·{" "}
                      {result.dataset.currency}
                    </p>
                  </div>
                  <div className="result-outcome">
                    <span>{complete.length} of 3 strategies completed</span>
                    <strong>
                      {lowestComplete
                        ? label(lowestComplete.strategy) +
                          " had the lowest total cost."
                        : "Volume limited every strategy."}
                    </strong>
                  </div>
                </section>
                <section className="diagnostics" aria-label="Order capacity">
                  <div>
                    <span>Expected capacity</span>
                    <strong>
                      {result.diagnostics
                        .historical_capacity_estimate_shares === null
                        ? "Unavailable"
                        : integer(
                            result.diagnostics
                              .historical_capacity_estimate_shares,
                          )}{" "}
                      <small>shares</small>
                    </strong>
                    <p>
                      {result.profile.eligible_session_dates.length
                        ? "Based on " +
                          result.profile.eligible_session_dates.length +
                          " earlier sessions."
                        : "No earlier forecast available."}
                    </p>
                  </div>
                  <div>
                    <span>Capacity on the test day</span>
                    <strong>
                      {integer(result.diagnostics.realized_capacity_shares)}{" "}
                      <small>shares</small>
                    </strong>
                    <p>Available within your time window and limit.</p>
                  </div>
                  <div
                    className={
                      result.diagnostics.minimum_unfilled_shares > 0
                        ? "capacity-warning"
                        : "capacity-ok"
                    }
                  >
                    <span>Minimum shares left unfilled</span>
                    <strong>
                      {integer(result.diagnostics.minimum_unfilled_shares)}{" "}
                      <small>shares</small>
                    </strong>
                    <p>
                      {result.diagnostics.minimum_unfilled_shares > 0
                        ? "This order exceeds the available volume."
                        : "Enough total volume; timing still matters."}
                    </p>
                  </div>
                </section>
              </>
            )}
          </div>
        </div>
        <div className="results-details">
          {result && strategy && (
            <>
              {result.warnings.map((w) => (
                <p className="warning" key={w.code}>
                  {w.message}
                </p>
              ))}
              <section className="comparison-panel panel">
                <div className="section-heading">
                  <h2>Compare the strategies</h2>
                  <span>Total cost in {result.dataset.currency}</span>
                </div>
                <p className="section-description">
                  Select a strategy to see its fills. Positive costs will hurt
                  the order while negative costs will help it.
                </p>
                <div className="mobile-comparison">
                  {result.strategies.map((s) => (
                    <button
                      key={s.strategy}
                      className={selected === s.strategy ? "active" : ""}
                      onClick={() => setSelected(s.strategy)}
                      aria-pressed={selected === s.strategy}
                    >
                      <span className="strategy-name">
                        <i style={{ background: colors[s.strategy] }} />
                        {label(s.strategy)}
                      </span>
                      <strong>
                        {money(
                          s.implementation_shortfall,
                          result.dataset.currency,
                        )}
                      </strong>
                      <small>
                        {(s.fill_rate * 100).toFixed(1)}% filled ·{" "}
                        {bps(s.implementation_shortfall_bps)}
                      </small>
                    </button>
                  ))}
                </div>
                <div
                  className="table-wrap"
                  tabIndex={0}
                  role="region"
                  aria-label="Execution comparison metrics"
                >
                  <table>
                    <thead>
                      <tr>
                        <th scope="col">Strategy</th>
                        <th scope="col">Filled</th>
                        <th scope="col">Average price</th>
                        <th
                          scope="col"
                          title="Difference from the starting price in basis points"
                        >
                          vs. starting price
                        </th>
                        <th
                          scope="col"
                          title="Difference from the test window’s volume-weighted average price"
                        >
                          vs. market VWAP
                        </th>
                        <th scope="col">Total cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.strategies.map((s) => (
                        <tr
                          key={s.strategy}
                          className={
                            selected === s.strategy ? "selected-row" : ""
                          }
                          style={
                            {
                              "--strategy-color": colors[s.strategy],
                            } as CSSProperties
                          }
                        >
                          <th scope="row">
                            <button
                              className="strategy-button"
                              aria-pressed={selected === s.strategy}
                              onClick={() => setSelected(s.strategy)}
                            >
                              <span
                                className="dot"
                                style={{ background: colors[s.strategy] }}
                              />
                              {label(s.strategy)}
                            </button>
                          </th>
                          <td>
                            {(s.fill_rate * 100).toFixed(1)}%
                            <small>
                              {integer(s.filled_shares)} /{" "}
                              {integer(result.request.quantity)}
                            </small>
                          </td>
                          <td>{price(s.average_execution_price)}</td>
                          <td>{bps(s.arrival_slippage_bps)}</td>
                          <td>{bps(s.vwap_slippage_bps)}</td>
                          <td>
                            <strong>
                              {money(
                                s.implementation_shortfall,
                                result.dataset.currency,
                              )}
                            </strong>
                            <small>{bps(s.implementation_shortfall_bps)}</small>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="metric-key">
                  The total cost here is the unfavourable variables in
                  implementation, which include price changing, trading costs
                  and unfilled shares. One basis point (bp) = 0.01%.
                </p>
              </section>
              <ExecutionCharts
                key={result.run_id}
                result={result}
                selected={strategy}
              />
              <section className="cost-panel panel">
                <div className="section-heading">
                  <h2>Where {label(strategy.strategy)}’s cost comes from</h2>
                  <span>
                    {integer(strategy.unfilled_shares)} shares unfilled
                  </span>
                </div>
                <div className="detail-grid">
                  {[
                    { title: "Price movement", value: strategy.timing_cost },
                    { title: "Spread", value: strategy.spread_cost },
                    { title: "Market impact", value: strategy.impact_cost },
                    { title: "Fees", value: strategy.fees },
                    {
                      title: "Unfilled shares",
                      value: strategy.opportunity_cost,
                    },
                    {
                      title: "Total cost",
                      value: strategy.implementation_shortfall,
                    },
                  ].map((m) => (
                    <div key={m.title}>
                      <span>{m.title}</span>
                      <strong>{money(m.value, result.dataset.currency)}</strong>
                    </div>
                  ))}
                </div>
                <details className="ledger">
                  <summary>View {strategy.fills.length} fills</summary>
                  <div
                    className="table-wrap ledger-wrap"
                    tabIndex={0}
                    role="region"
                    aria-label="Fill ledger metrics"
                  >
                    <table>
                      <caption>
                        Fill times are recorded at each minute’s end (ET).
                      </caption>
                      <thead>
                        <tr>
                          {[
                            "Time",
                            "Wanted",
                            "Available",
                            "Filled",
                            "Remaining",
                            "Market price",
                            "Fill price",
                          ].map((h) => (
                            <th scope="col" key={h}>
                              {h}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {strategy.fills.map((f) => (
                          <tr key={f.slot}>
                            <td>{shortTime(f.filled_at)}</td>
                            <td>{integer(f.desired_shares)}</td>
                            <td>{integer(f.capacity_shares)}</td>
                            <td>{integer(f.shares)}</td>
                            <td>{integer(f.remaining_shares)}</td>
                            <td>{price(f.reference_price)}</td>
                            <td>{price(f.fill_price)}</td>
                          </tr>
                        ))}
                        {!strategy.fills.length && (
                          <tr>
                            <td colSpan={7}>
                              No shares filled in this window.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </details>
                <div className="export-actions">
                  <span>Download this result</span>
                  <a href={exportHref("note")} download>
                    Execution note ↗
                  </a>
                  <a href={exportHref("json")} download>
                    Export JSON
                  </a>
                  <a href={exportHref("csv")} download>
                    Export fills CSV
                  </a>
                </div>
              </section>
            </>
          )}
        </div>
        <section className="methodology" id="important-assumptions">
          <h2>Important Assumptions</h2>
          <div className="method-grid">
            <div>
              <h3>Three simple approaches</h3>
              <p>
                <strong>Immediate</strong> fills as soon as volume allows.{" "}
                <strong>TWAP</strong> spreads the order evenly over time.{" "}
                <strong>VWAP</strong> follows volume patterns from earlier days.
              </p>
            </div>
            <div>
              <h3>Volume controls the limit</h3>
              <p>
                An order can use up to{" "}
                {(
                  (result?.request.participation_cap ?? inputs.cap) * 100
                ).toFixed(0)}
                % of each minute’s volume. Leftover shares stay unfilled and add
                to the total cost. Important to note that spread, impact and
                fees are estimates.
              </p>
            </div>
            <div>
              <h3>A simplified market</h3>
              <p>
                One-minute bars capture prices and volume, but not the order
                book. The order doesn't change the price significantly, which
                may occur in larger executions.
                {result?.profile.fallback
                  ? " This run uses TWAP for VWAP because there are too few earlier sessions."
                  : ""}
              </p>
            </div>
          </div>
        </section>
        <footer>
          <span>Execution Lab</span>
          <span>A small project exploring trading decisions.</span>
        </footer>
      </main>
    </>
  );
}
