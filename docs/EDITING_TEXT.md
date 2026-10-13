# Editing the wording

There is no separate browser copy editor. The displayed wording lives in the React source files below. Edit the words between tags or inside quoted strings, leaving the surrounding code in place.

## Where each section lives

Paths are relative to the `execution-lab` folder containing this guide's `docs` folder.

| What you want to change | File | Search for |
| --- | --- | --- |
| Opening question and introduction | `frontend/src/App.tsx` | `dataset-title`, `dataset-lede` |
| Dataset description | `frontend/src/App.tsx` | `I generated`, `Earlier days` |
| Example names, details and questions | `frontend/src/App.tsx` | `const examples` |
| Order labels and help text | `frontend/src/App.tsx` | `Your order`, `Available volume` |
| Three headline numbers' labels and explanations | `frontend/src/App.tsx` | `Expected capacity`, `Capacity on the test day`, `Minimum shares left unfilled` |
| Strategy comparison labels and explanations | `frontend/src/App.tsx` | `Compare the strategies`, `Total cost is implementation shortfall` |
| Chart titles, captions, units and readouts | `frontend/src/Charts.tsx` | `Shares filled over time`, `Price, volume & fills` |
| Cost breakdown and download labels | `frontend/src/App.tsx` | `cost comes from`, `Download this result` |
| Important Assumptions and footer | `frontend/src/App.tsx` | `Important Assumptions`, `A small project` |
| Strategy display names | `frontend/src/presentation.ts` | `strategyLabel` |
| Time-picker labels and prompts | `frontend/src/TimePicker.tsx` | `Scroll or swipe`, `Done` |
| Validation and loading messages | `frontend/src/App.tsx` | `const validation`, `Comparing all three` |
| Generated API warnings and downloaded execution note | `backend/app/` | Search the exact current phrase |

Numbers and dates come from the simulation or dataset. Expressions inside braces, such as `{integer(...)}`, produce those values; keep them intact when changing the surrounding wording.

For example, you can change:

```tsx
<h2>Price, volume & fills</h2>
```

to your preferred heading:

```tsx
<h2>What happened in the market</h2>
```

## Preview as you edit

Keep the backend running on port 8000. In a terminal opened inside `frontend/`, run:

```powershell
npm run dev -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173/`. Saving the source updates this development preview automatically.

The existing `http://127.0.0.1:8000/` page serves the built frontend. To update it after editing, run this inside `frontend/`, then refresh that page:

```powershell
npm run build
```

Node.js and npm must be on the terminal's PATH, as described in the README. No dependency installation is needed for wording edits in this existing checkout.
