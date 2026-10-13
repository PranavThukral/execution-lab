import { expect, it } from "vitest";
import { priceScale, segmentedPath, shareTicks, stepPath } from "./Charts";
import { exchangeTimestamp } from "./presentation";
import type { Point } from "./types";

it("breaks price lines across absent bars instead of drawing invented prices", () => {
  expect(
    segmentedPath(
      [
        { slot: 0, reference_price: 100 },
        { slot: 1, reference_price: null },
        { slot: 2, reference_price: 102 },
      ],
      (v) => v,
      (v) => v,
    ),
  ).toBe("M 1 100  M 3 102");
});
it("starts cumulative fills at zero and puts each fill at the minute end", () => {
  expect(
    stepPath(
      [
        { slot: 0, filled: 10 },
        { slot: 1, filled: 20 },
      ] as Point[],
      "filled",
      (v) => v,
      (v) => v,
    ),
  ).toBe("M 0 0 H 1 V 10 H 2 V 20");
});
it("uses the exchange date offset across daylight saving transitions", () => {
  expect(exchangeTimestamp("2025-06-09", "10:00")).toBe(
    "2025-06-09T10:00:00-04:00",
  );
  expect(exchangeTimestamp("2025-01-09", "10:00")).toBe(
    "2025-01-09T10:00:00-05:00",
  );
});

it("labels the full share quantity without rounded-thousands ambiguity", () => {
  expect(shareTicks(50000)).toEqual([0, 12500, 25000, 37500, 50000]);
  expect(shareTicks(1)).toEqual([0, 1]);
  expect(shareTicks(1000000)).toEqual([0, 250000, 500000, 750000, 1000000]);
});
it("keeps a constant price visible and includes costly fills in the scale", () => {
  const flat = priceScale([100, 100]);
  expect(flat.min).toBeLessThan(100);
  expect(flat.max).toBeGreaterThan(100);
  expect(flat.ticks.length).toBeGreaterThan(2);
  const range = priceScale([100, 101, 102.6]);
  expect(range.max).toBeGreaterThan(102.6);
  expect(range.min).toBeLessThan(100);
});
