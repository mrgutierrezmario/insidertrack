import { describe, expect, it } from "vitest";
import { daysAgo, sma } from "./indicators";

const bars = [10, 11, 12, 13, 14].map((close, i) => ({ date: `2026-10-0${i + 1}`, close }));

describe("sma", () => {
  it("averages the last n closes and skips the warm-up bars", () => {
    expect(sma(bars, 3)).toEqual([
      { time: "2026-10-03", value: 11 },
      { time: "2026-10-04", value: 12 },
      { time: "2026-10-05", value: 13 },
    ]);
  });

  it("returns nothing when there are fewer bars than the window", () => {
    expect(sma(bars, 6)).toEqual([]);
    expect(sma([], 50)).toEqual([]);
  });

  it("rounds to cents", () => {
    expect(sma([{ date: "a", close: 1 }, { date: "b", close: 2 }, { date: "c", close: 2 }], 3)[0].value).toBe(1.67);
  });
});

describe("daysAgo", () => {
  it("crosses month and year boundaries", () => {
    expect(daysAgo(new Date(2026, 0, 10), 15)).toBe("2025-12-26");
    expect(daysAgo(new Date(2026, 9, 16), 90)).toBe("2026-07-18");
  });
});
