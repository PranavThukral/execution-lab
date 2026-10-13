import { bps, integer } from "./format";
import type { Result } from "./types";

export const colors: Record<string, string> = {
  immediate: "#e86528",
  twap: "#2860df",
  vwap: "#008b7e",
};
export function money(value: number | null, currency = "USD") {
  if (value === null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}
export function price(value: number | null) {
  return value === null ? "—" : value.toFixed(4);
}
export function shortTime(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(value));
}
export function exchangeTimestamp(session: string, time: string) {
  const raw =
    new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      timeZoneName: "shortOffset",
    })
      .formatToParts(new Date(`${session}T12:00:00Z`))
      .find((part) => part.type === "timeZoneName")
      ?.value.replace("GMT", "") || "-05";
  const sign = raw.startsWith("-") ? "-" : "+";
  const [hours, minutes = "00"] = raw.replace(/[+-]/, "").split(":");
  return `${session}T${time}:00${sign}${hours.padStart(2, "0")}:${minutes}`;
}
export function strategyLabel(result: Result, name: string) {
  return name === "vwap"
    ? result.profile.fallback
      ? "VWAP · TWAP fallback"
      : "Forecast VWAP"
    : name === "immediate"
      ? "Immediate"
      : "TWAP";
}
export function executionNote(result: Result) {
  const q = result.request.quantity;
  const rows = result.strategies
    .map(
      (s) =>
        `| ${strategyLabel(result, s.strategy)} | ${integer(s.filled_shares)} / ${integer(q)} | ${money(s.implementation_shortfall, result.dataset.currency)} | ${bps(s.implementation_shortfall_bps)} |`,
    )
    .join("\n");
  return `# Execution review · ${result.run_id}\n\n${result.dataset.symbol} · ${result.request.side.toUpperCase()} ${integer(q)} shares · ${result.request.session} · ${shortTime(result.request.start)}–${shortTime(result.request.end)} America/New_York.\n\nData: ${result.dataset.data_kind}; source ${result.dataset.source}; feed ${result.dataset.feed}; currency ${result.dataset.currency}.\n\n| Schedule | Filled | Total shortfall | Shortfall bps |\n|---|---:|---:|---:|\n${rows}\n\nPrior-session capacity estimate: ${result.diagnostics.historical_capacity_estimate_shares === null ? "unavailable (uniform fallback)" : integer(result.diagnostics.historical_capacity_estimate_shares)} shares. Realized replay capacity: ${integer(result.diagnostics.realized_capacity_shares)} shares; minimum unfilled ${integer(result.diagnostics.minimum_unfilled_shares)}. The latter uses evaluation-session volume and is NOT a pre-trade forecast.\n\nPositive cost is worse for both sides. Shortfall = signed timing + modeled half-spread + modeled impact + fees + signed opportunity cost on unfilled shares. Negative opportunity cost is possible when price moves favorably. Filled-only slippage excludes fees and residual shares.\n\nVWAP profile: ${result.profile.fallback ? "uniform fallback" : result.profile.eligible_session_dates.join(", ")}. Frozen before evaluation; at least 95% coverage required per prior window. Missing evaluation minutes do not receive fills.\n\nAssumptions: ${JSON.stringify(result.request.cost_model)}; cap ${result.request.participation_cap}; scenario ${JSON.stringify(result.request.scenario)}. Fills occur at minute end. Minute bars cannot establish queue position, venue routing, real bid/ask or executable intrabar liquidity. No claim of live execution quality or general schedule superiority.\n\nEngine ${result.engine_version}; dataset SHA-256 ${result.dataset.content_sha256}. The JSON export contains the full reproducible request, schedules, diagnostics and ledger.\n`;
}
