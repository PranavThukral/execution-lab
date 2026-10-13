# Execution Lab

Compare how immediate execution, TWAP and forecast-volume VWAP fill the same stock order under different timing and liquidity conditions.

## Technologies

- **Frontend:** React, TypeScript, Vite, custom SVG charts, Inter and Krub.
- **Backend:** Python, FastAPI, Pydantic, Uvicorn and exchange-calendars.
- **Testing:** pytest, Ruff, Vitest, React Testing Library and ESLint.
- **Deployment:** Vercel Services for the frontend and API; Docker for a local single-service build.

## Technical details

The default dataset contains 2,340 generated one-minute observations across six US trading sessions. Earlier sessions shape the VWAP volume forecast; the chosen session is replayed for all three strategies. A participation limit caps each minute's fills. The cost model includes spread, market impact, fees and the cost of unfilled shares.

Results include completion, average fill price, arrival/VWAP slippage and implementation shortfall, with linked charts, per-minute fills and JSON/CSV/Markdown downloads. Buy and sell costs use a consistent signed convention. Runs are deterministic and exports retain the submitted order.

The backend also supports validated local CSV imports and an optional Alpaca historical-data adapter. The public demo uses generated data. Spread and impact are modeled; minute bars do not contain an order book.

## Run locally

Requires Node.js 24.15+ and Python 3.12+, with npm and uv installed.

Backend, from `backend/`:

```sh
uv sync --frozen --extra dev
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend, from `frontend/`, in another terminal:

```sh
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

Open **http://127.0.0.1:5173** for live editing. `npm run build` generates the frontend served by the backend at port 8000.

## Tests

```sh
# backend/
uv run pytest
uv run ruff check .

# frontend/
npm test
npm run lint
npm run typecheck
npm run build
```

## Deploy

Import this repository into Vercel with its root directory set to the repository root. `vercel.json` builds the Vite frontend and FastAPI backend together and routes `/api/*` to the backend. No API keys are required for the demo. See [deployment details](docs/DEPLOYMENT.md).

[Methodology](docs/METHODOLOGY.md) · [Example results](evidence/CASE_STUDY.md) · [Editing the wording](docs/EDITING_TEXT.md)
