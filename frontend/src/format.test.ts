import { describe, expect, it } from "vitest";
import { bps, integer, money } from "./format";

describe("display formatting", () => {
  it("keeps null financial values explicit", () => {
    expect(money(null)).toBe("—");
    expect(bps(null)).toBe("—");
  });
  it("uses stable reviewer-friendly formats", () => {
    expect(money(140.6)).toBe("$140.60");
    expect(bps(12.345)).toBe("12.35 bps");
    expect(integer(50000)).toBe("50,000");
    expect(money(-140.6)).toBe("-$140.60");
  });
});
