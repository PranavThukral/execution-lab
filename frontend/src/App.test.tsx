// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "./App";
import type { Result } from "./types";

const catalog = {
  datasets: [
    {
      dataset_id: "demo-sim-v1",
      symbol: "SIM_DEMO",
      currency: "USD",
      data_kind: "synthetic",
      source: "fixture",
      feed: "synthetic",
      sessions: ["2025-06-09"],
      session_bounds: { "2025-06-09": { start: "09:30", end: "16:00" } },
    },
  ],
};
const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
const fetcher = vi.fn<typeof fetch>();
beforeEach(() => {
  vi.stubGlobal("fetch", fetcher);
  fetcher.mockReset();
  fetcher.mockResolvedValueOnce(response(catalog));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
async function ready() {
  render(<App />);
  await waitFor(() =>
    expect(
      screen
        .getByRole("button", { name: "Compare strategies →" })
        .hasAttribute("disabled"),
    ).toBe(false),
  );
}
it("ignores an old response when controls change during a pending run", async () => {
  let finish!: (r: Response) => void;
  fetcher.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  await ready();
  fireEvent.click(screen.getByRole("button", { name: "Compare strategies →" }));
  const signal = fetcher.mock.calls[1][1]?.signal;
  fireEvent.change(screen.getByLabelText("Shares"), {
    target: { value: "200000" },
  });
  expect(signal?.aborted).toBe(true);
  await act(async () => finish(response({ run_id: "stale-result" })));
  expect(screen.queryByText(/stale-result/)).toBeNull();
  expect(screen.queryByText(/Comparing all three strategies/)).toBeNull();
});
it("reset cancels a pending run and restores the baseline controls", async () => {
  fetcher.mockImplementationOnce(() => new Promise(() => {}));
  await ready();
  fireEvent.change(screen.getByLabelText("Shares"), {
    target: { value: "200000" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Compare strategies →" }));
  fireEvent.click(screen.getByRole("button", { name: "Reset inputs" }));
  expect(fetcher.mock.calls[1][1]?.signal?.aborted).toBe(true);
  expect((screen.getByLabelText("Shares") as HTMLInputElement).value).toBe(
    "50000",
  );
});
it("guided liquidity case submits its new values rather than old state", async () => {
  fetcher.mockResolvedValueOnce(
    response({ error: { message: "test response" } }, 422),
  );
  await ready();
  fireEvent.click(
    screen.getByRole("button", { name: /02.*Liquidity squeeze/ }),
  );
  const order = JSON.parse(fetcher.mock.calls[1][1]!.body as string);
  expect(order.quantity).toBe(200000);
  expect(order.scenario.liquidity_multiplier).toBe(0.2);
  expect(order.start).toBe("2025-06-09T10:00:00-04:00");
  expect(await screen.findByRole("alert")).toBeTruthy();
});
it("blocks reversed time windows without making a simulation request", async () => {
  await ready();
  fireEvent.input(screen.getByLabelText("End"), {
    target: { value: "09:45" },
  });
  expect(screen.getByText("End must be later than start.")).toBeTruthy();
  expect(
    screen
      .getByRole("button", { name: "Compare strategies →" })
      .hasAttribute("disabled"),
  ).toBe(true);
  expect(fetcher).toHaveBeenCalledTimes(1);
});
it("submits time-field input events through the exclusive session close", async () => {
  fetcher.mockResolvedValueOnce(response({ error: { message: "test" } }, 422));
  await ready();
  fireEvent.input(screen.getByLabelText("Start"), {
    target: { value: "09:30" },
  });
  fireEvent.input(screen.getByLabelText("End"), { target: { value: "16:00" } });
  fireEvent.click(screen.getByRole("button", { name: "Compare strategies →" }));
  const order = JSON.parse(fetcher.mock.calls[1][1]!.body as string);
  expect(order.start).toBe("2025-06-09T09:30:00-04:00");
  expect(order.end).toBe("2025-06-09T16:00:00-04:00");
  await screen.findByRole("alert");
});
it("catalog arrival does not overwrite a window already edited by the user", async () => {
  let finish!: (r: Response) => void;
  fetcher.mockReset().mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  render(<App />);
  fireEvent.input(screen.getByLabelText("Start"), {
    target: { value: "09:30" },
  });
  fireEvent.input(screen.getByLabelText("End"), { target: { value: "16:00" } });
  await act(async () => finish(response(catalog)));
  expect((screen.getByLabelText("Start") as HTMLInputElement).value).toBe(
    "09:30",
  );
  expect((screen.getByLabelText("End") as HTMLInputElement).value).toBe(
    "16:00",
  );
});
it("retains submitted results when controls change and exports reconciled evidence", async () => {
  const result = (await import("./test-fixture.json"))
    .default as unknown as Result;
  fetcher.mockResolvedValueOnce(response(result));
  await ready();
  fireEvent.click(screen.getByRole("button", { name: "Compare strategies →" }));
  await screen.findByRole("heading", { name: /SIM_DEMO · BUY/ });
  fireEvent.change(screen.getByLabelText("Side"), {
    target: { value: "sell" },
  });
  expect(screen.getByText(/Changes pending. Run the comparison/)).toBeTruthy();
  expect(screen.getByRole("heading", { name: /SIM_DEMO · BUY/ })).toBeTruthy();
  const link = screen.getByRole("link", {
    name: "Export fills CSV",
  }) as HTMLAnchorElement;
  const exported = JSON.parse(new URL(link.href).searchParams.get("payload")!);
  expect(exported.side).toBe("buy");
  expect(exported.quantity).toBe(50000);
  expect(new URL(link.href).searchParams.get("kind")).toBe("csv");
});

it("blocks invalid quantities before comparison", async () => {
  await ready();
  fireEvent.change(screen.getByLabelText("Shares"), { target: { value: "0" } });
  expect(
    screen.getByText("Shares must be a whole number between 1 and 1,000,000."),
  ).toBeTruthy();
  expect(
    (
      screen.getByRole("button", {
        name: "Compare strategies →",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(fetcher).toHaveBeenCalledTimes(1);
});
it("recovers a failed catalog without reloading the page", async () => {
  fetcher
    .mockReset()
    .mockResolvedValueOnce(
      response({ error: { message: "Catalog unavailable" } }, 503),
    )
    .mockResolvedValueOnce(response(catalog));
  render(<App />);
  expect(await screen.findByRole("alert")).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: "Retry dataset loading" }),
  );
  await waitFor(() =>
    expect(
      (
        screen.getByRole("button", {
          name: "Compare strategies →",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  expect(screen.queryByRole("alert")).toBeNull();
  expect(fetcher).toHaveBeenCalledTimes(2);
});
it("keeps the previous result and its exports after a failed comparison", async () => {
  const result = (await import("./test-fixture.json"))
    .default as unknown as Result;
  fetcher
    .mockResolvedValueOnce(response(result))
    .mockResolvedValueOnce(
      response({ error: { message: "Server busy" } }, 429),
    );
  await ready();
  fireEvent.click(screen.getByRole("button", { name: "Compare strategies →" }));
  await screen.findByRole("heading", { name: /SIM_DEMO · BUY/ });
  fireEvent.change(screen.getByLabelText("Side"), {
    target: { value: "sell" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Compare strategies →" }));
  await screen.findByRole("alert");
  expect(screen.getByText(/Your previous result is still shown/)).toBeTruthy();
  const link = screen.getByRole("link", {
    name: "Export JSON",
  }) as HTMLAnchorElement;
  expect(JSON.parse(new URL(link.href).searchParams.get("payload")!).side).toBe(
    "buy",
  );
});

it("introduces the single dataset without an unnecessary selector", async () => {
  await ready();
  expect(screen.queryByLabelText("Dataset")).toBeNull();
  expect(screen.getByText("Generated sample dataset")).toBeTruthy();
  expect(
    screen.getByRole("heading", { name: "Important Assumptions" }),
  ).toBeTruthy();
  expect(screen.queryByText(/engine 0.3/)).toBeNull();
});
it("clears the selected example when the user customizes its order", async () => {
  await ready();
  const baseline = screen.getByRole("button", { name: /01.*Baseline/ });
  expect(baseline.getAttribute("aria-pressed")).toBe("true");
  fireEvent.change(screen.getByLabelText("Shares"), {
    target: { value: "60000" },
  });
  expect(baseline.getAttribute("aria-pressed")).toBe("false");
  expect(screen.getByText("Custom order:")).toBeTruthy();
});
it("converts volume percent into the multiplier used by the simulation", async () => {
  fetcher.mockResolvedValueOnce(response({ error: { message: "test" } }, 422));
  await ready();
  fireEvent.change(screen.getByLabelText(/Available volume/), {
    target: { value: "45" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Compare strategies →" }));
  const order = JSON.parse(fetcher.mock.calls[1][1]!.body as string);
  expect(order.scenario.liquidity_multiplier).toBe(0.45);
  await screen.findByRole("alert");
});
it("blocks out-of-range available volume locally", async () => {
  await ready();
  fireEvent.change(screen.getByLabelText(/Available volume/), {
    target: { value: "0" },
  });
  expect(
    screen.getByText("Available volume must be between 10% and 200%."),
  ).toBeTruthy();
  expect(
    (
      screen.getByRole("button", {
        name: "Compare strategies →",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(fetcher).toHaveBeenCalledTimes(1);
});
