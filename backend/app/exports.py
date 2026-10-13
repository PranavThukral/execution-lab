from __future__ import annotations

import csv
import io
import json


def render_export(result: dict, kind: str, strategy: str) -> tuple[str, str, str]:
    """Reproducible downloads use the same engine, not a second cost calculator."""
    run_id = result["run_id"]
    if kind == "json":
        return json.dumps(result, indent=2), "application/json", f"execution-lab-{run_id}.json"
    if kind == "csv":
        selected = next(item for item in result["strategies"] if item["strategy"] == strategy)
        headers = [
            "strategy",
            "bar_start",
            "filled_at",
            "desired_shares",
            "capacity_shares",
            "shares",
            "cumulative_filled",
            "remaining_shares",
            "reference_price",
            "fill_price",
            "spread_bps",
            "impact_bps",
            "fee",
        ]
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=headers)
        writer.writeheader()
        writer.writerows({key: fill[key] for key in headers} for fill in selected["fills"])
        return buffer.getvalue(), "text/csv", f"execution-lab-{run_id}-{strategy}-fills.csv"
    order, dataset = result["request"], result["dataset"]
    lines = [
        f"# Execution review / {run_id}",
        "",
        f"{dataset['symbol']} / {order['side'].upper()} {order['quantity']:,} shares / "
        f"{dataset['currency']}",
        f"Window: {order['start']} to {order['end']}. All windows use America/New_York.",
        "",
        f"Data: {dataset['data_kind']}; source {dataset['source']}; feed {dataset['feed']}.",
        "",
        "| Schedule | Filled | Residual | Shortfall | Shortfall bps |",
        "|---|---:|---:|---:|---:|",
    ]
    for item in result["strategies"]:
        name = item["strategy"]
        if name == "vwap" and result["profile"]["fallback"]:
            name += " (uniform TWAP fallback)"
        lines.append(
            f"| {name} | {item['filled_shares']:,} | {item['unfilled_shares']:,} | "
            f"{item['implementation_shortfall']:,.2f} | "
            f"{item['implementation_shortfall_bps']:.2f} |"
        )
    lines.extend(
        [
            "",
            f"Diagnostics: {json.dumps(result['diagnostics'])}",
            "",
            "Prior capacity uses earlier sessions; realized capacity uses evaluation volume.",
            "The realized value is NOT a pre-trade forecast or a completion guarantee.",
            "",
            "Positive cost is worse. Filled-only slippage excludes fees and residual shares.",
            "Shortfall = timing + modeled half-spread + modeled impact + fees + opportunity.",
            "Signed timing/opportunity costs can be negative when prices move favorably.",
            "",
            f"Frozen prior profile: {json.dumps(result['profile']['eligible_session_dates'])}; "
            f"fallback {result['profile']['fallback']}.",
            f"Assumptions: cap {order['participation_cap']}; {json.dumps(order['cost_model'])}; "
            f"scenario {json.dumps(order['scenario'])}.",
            "",
            "Fills occur at minute end. Missing bars receive no liquidity or fills.",
            "Minute bars lack queue position, venue routing, real quotes and intrabar liquidity.",
            "Paths stay exogenous. No universal schedule superiority or live execution is claimed.",
            "",
            f"Engine {result['engine_version']}; dataset SHA-256 {dataset['content_sha256']}.",
            "JSON contains the complete reproducible request and all fill/series records.",
        ]
    )
    return "\n".join(lines) + "\n", "text/markdown", f"execution-lab-{run_id}-review.md"
