from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import tempfile
from datetime import date, datetime, timezone
from itertools import islice
from pathlib import Path

from .domain import content_hash, demo_bars, normalize_bars, run_simulation
from .provider import fetch_alpaca_bars


def _write_dataset(bars, quality, *, source, feed, currency, output_dir, data_kind="historical"):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    symbol = bars[0].symbol
    if not source.strip() or not feed.strip() or not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("source/feed and a three-letter uppercase currency are required")
    safe_symbol = re.sub(r"[^a-z0-9]+", "-", symbol.lower()).strip("-") or "dataset"
    identity = {
        "content_sha256": content_hash(bars),
        "source": source,
        "feed": feed,
        "currency": currency,
        "data_kind": data_kind,
    }
    identity_hash = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    dataset_id = f"{safe_symbol[:48]}-{identity_hash[:12]}"
    target = output / dataset_id
    if target.exists():
        raise ValueError("This dataset already exists; immutable imports cannot be overwritten")
    staging = Path(tempfile.mkdtemp(prefix=".import-", dir=output))
    temp_csv = staging / "bars.csv"
    with temp_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "timestamp",
                "symbol",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "market_vwap",
            ],
        )
        writer.writeheader()
        for bar in bars:
            writer.writerow(
                {
                    "timestamp": bar.timestamp.isoformat(),
                    "symbol": bar.symbol,
                    "open": format(bar.open, ".17g"),
                    "high": format(bar.high, ".17g"),
                    "low": format(bar.low, ".17g"),
                    "close": format(bar.close, ".17g"),
                    "volume": bar.volume,
                    "market_vwap": ""
                    if bar.market_vwap is None
                    else format(bar.market_vwap, ".17g"),
                }
            )
    manifest = {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "symbol": symbol,
        "currency": currency,
        "data_kind": data_kind,
        "source": source,
        "feed": feed,
        "calendar": "XNYS",
        "timezone": "America/New_York",
        "bar_interval_seconds": 60,
        "content_sha256": content_hash(bars),
        "quality": quality,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "bar_timestamp_basis": "bar_start",
        "adjustment": "raw" if source == "alpaca" else "unspecified_by_importer",
        "range": {
            "start": bars[0].timestamp.isoformat(),
            "last_bar_start": bars[-1].timestamp.isoformat(),
        },
    }
    temp_manifest = staging / "manifest.json"
    temp_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    staging.rename(target)
    print(json.dumps(manifest))


def main() -> None:
    parser = argparse.ArgumentParser(description="Execution Lab local data tools")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate-demo")
    sub.add_parser("smoke")
    import_csv = sub.add_parser("import-csv")
    import_csv.add_argument("--path", required=True)
    import_csv.add_argument("--source", required=True)
    import_csv.add_argument("--feed", required=True)
    import_csv.add_argument("--currency", default="USD")
    import_csv.add_argument("--output-dir", default="data/local")
    fetch = sub.add_parser("fetch-alpaca")
    fetch.add_argument("--symbol", required=True)
    fetch.add_argument("--start", required=True)
    fetch.add_argument("--end", required=True)
    fetch.add_argument("--feed", default="iex")
    fetch.add_argument("--currency", default="USD")
    fetch.add_argument("--output-dir", default="data/local")
    args = parser.parse_args()
    if args.command == "generate-demo":
        print(
            json.dumps(
                {
                    "bars": len(demo_bars()),
                    "sessions": 6,
                    "content_sha256": content_hash(demo_bars()),
                }
            )
        )
    elif args.command == "import-csv":
        path = Path(args.path)
        if path.stat().st_size > 20 * 1024 * 1024:
            raise SystemExit("CSV exceeds the 20 MiB import limit")
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(islice(csv.DictReader(handle), 12001))
        bars, quality = normalize_bars(rows)
        _write_dataset(
            bars,
            quality,
            source=args.source,
            feed=args.feed,
            currency=args.currency,
            output_dir=args.output_dir,
        )
    elif args.command == "fetch-alpaca":
        import asyncio

        bars, quality = asyncio.run(
            fetch_alpaca_bars(
                args.symbol,
                datetime.fromisoformat(args.start),
                datetime.fromisoformat(args.end),
                args.feed,
            )
        )
        _write_dataset(
            bars,
            quality,
            source="alpaca",
            feed=args.feed,
            currency=args.currency,
            output_dir=args.output_dir,
        )
    elif args.command == "smoke":
        result = run_simulation(demo_bars(), date(2025, 6, 9), 30, 90, 50000)
        print(
            json.dumps(
                {
                    "run_id": result["run_id"],
                    "strategies": [s["strategy"] for s in result["strategies"]],
                }
            )
        )


if __name__ == "__main__":
    main()
