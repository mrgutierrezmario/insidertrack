import { describe, expect, it } from "vitest";
import { buildDayMarkers, congressEvent, disclosureNote, insiderEvent, type TradeEvent } from "./tradeMarkers";

const DATES = ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06"];

function ev(date: string, side: "buy" | "sell", who = "X"): TradeEvent {
  return { date, side, who, detail: `${who} ${side}` };
}

describe("buildDayMarkers", () => {
  it("snaps a weekend trade to the next trading day", () => {
    const [m] = buildDayMarkers([ev("2026-10-03", "buy")], DATES);
    expect(m.time).toBe("2026-10-05");
  });

  it("drops trades outside the candle range", () => {
    expect(buildDayMarkers([ev("2026-09-30", "buy"), ev("2026-10-07", "sell")], DATES)).toEqual([]);
  });

  it("merges same-day same-side trades and keeps sides apart", () => {
    const out = buildDayMarkers(
      [ev("2026-10-02", "buy", "A"), ev("2026-10-02", "buy", "B"), ev("2026-10-02", "sell", "C")],
      DATES,
    );
    expect(out).toHaveLength(2);
    expect(out[0]).toMatchObject({ time: "2026-10-02", side: "buy", text: "2 buys", details: ["A buy", "B buy"] });
    expect(out[1]).toMatchObject({ side: "sell", text: "C" });
  });

  it("returns markers sorted by time", () => {
    const out = buildDayMarkers([ev("2026-10-06", "buy"), ev("2026-10-01", "sell")], DATES);
    expect(out.map((m) => m.time)).toEqual(["2026-10-01", "2026-10-06"]);
  });

  it("handles an empty chart", () => {
    expect(buildDayMarkers([ev("2026-10-01", "buy")], [])).toEqual([]);
  });
});

describe("event builders", () => {
  it("labels a Congress trade with the member's surname", () => {
    const e = congressEvent({
      trade_date: "2026-07-10", direction: "buy", amount_range: "$1,001 – $15,000",
      politician: { name: "Dan Newhouse" },
    });
    expect(e).toMatchObject({ who: "Newhouse", side: "buy", detail: "Dan Newhouse (Congress) buy · $1,001 – $15,000" });
  });

  it("skips Congress trades with no direction or date", () => {
    expect(congressEvent({ trade_date: "2026-07-10", direction: null, amount_range: null, politician: null })).toBeNull();
    expect(congressEvent({ trade_date: null, direction: "buy", amount_range: null, politician: null })).toBeNull();
  });

  it("uses a short insider title, else 'Insider'", () => {
    const ceo = insiderEvent({ transaction_type: "buy", transaction_date: "2026-10-01", insider_name: "Jane Roe", insider_title: "CEO", value: 2_000_000 });
    expect(ceo).toMatchObject({ who: "CEO", detail: "Jane Roe, CEO buy · $2.0M" });
    const long = insiderEvent({ transaction_type: "sell", transaction_date: "2026-10-01", insider_name: "John Doe", insider_title: "EVP, Global Operations" });
    expect(long?.who).toBe("Insider");
  });

  it("treats a 'See Remarks' title as no title", () => {
    const e = insiderEvent({ transaction_type: "sell", transaction_date: "2026-10-01", insider_name: "Jo Poe", insider_title: "See Remarks" });
    expect(e).toMatchObject({ who: "Insider", detail: "Jo Poe sell" });
  });

  it("skips insider rows that aren't a buy or sell", () => {
    expect(insiderEvent({ transaction_type: "grant", transaction_date: "2026-10-01", insider_name: "A" })).toBeNull();
  });
});

describe("label spacing", () => {
  it("blanks a label that would overprint a nearby same-side label", () => {
    const out = buildDayMarkers(
      [ev("2026-10-01", "buy", "A"), ev("2026-10-02", "buy", "B"), ev("2026-10-02", "sell", "C"), ev("2026-10-06", "buy", "D")],
      DATES,
    );
    expect(out.map((m) => m.text)).toEqual(["A", "", "C", "D"]);
    expect(out[1].details).toEqual(["B buy"]);
  });
});

describe("disclosureNote", () => {
  it("says when a late filing became public", () => {
    expect(disclosureNote("2026-10-02", "2026-10-28")).toBe(" · disclosed Oct 28 (26 days later)");
    expect(disclosureNote("2026-10-27", "2026-10-28")).toBe(" · disclosed Oct 28 (1 day later)");
  });

  it("counts across a month and year boundary", () => {
    expect(disclosureNote("2026-12-20", "2027-01-05")).toBe(" · disclosed Jan 5 (16 days later)");
  });

  it("is empty for same-day, missing or malformed dates", () => {
    expect(disclosureNote("2026-10-13", "2026-10-13")).toBe("");
    expect(disclosureNote("2026-10-13", null)).toBe("");
    expect(disclosureNote("2026-10-13", "10/20/2026")).toBe("");
  });

  it("is appended to Congress tooltip lines", () => {
    const e = congressEvent({
      trade_date: "2026-07-10", disclosure_date: "2026-08-06", direction: "buy",
      amount_range: "$1,001 – $15,000", politician: { name: "Dan Newhouse" },
    });
    expect(e?.detail).toBe("Dan Newhouse (Congress) buy · $1,001 – $15,000 · disclosed Aug 6 (27 days later)");
  });
});
