import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import TradeCard from "./TradeCard";
import type { Trade } from "../types/api";

vi.mock("../lib/api", () => ({ deleteTrade: vi.fn(), rereadFiling: vi.fn(), addToWatchlist: vi.fn(), getWatchlist: vi.fn(() => Promise.resolve({ data: [] })) }));

const base: Trade = {
  id: 1, ticker: "UBER", asset_name: "Uber", transaction_type: "purchase", direction: "buy", asset_type: "stock",
  owner: "self", amount_range: "$1,001 - $15,000", amount_low: 1001, amount_high: 15000,
  trade_date: "2026-03-01", disclosure_date: "2026-03-20", source: "house", filing_id: null, filing_url: null,
  ai_confidence: null, amends: null, risk_level: "LOW",
  politician: { id: 9, name: "Rep Test", chamber: "house", party: "D", state: "CA" },
};

function renderCard(t: Trade) {
  return render(<MemoryRouter><TradeCard trade={t} /></MemoryRouter>);
}

describe("<TradeCard /> late badge", () => {
  it("is absent for an on-time filing (45 days is on time)", () => {
    renderCard({ ...base, disclosure_date: "2026-04-15" });   // 45 days
    expect(screen.queryByText(/DAYS LATER/)).toBeNull();
  });

  it("shows how late a filing was and links to Late Filers", () => {
    renderCard({ ...base, disclosure_date: "2026-06-22" });   // 113 days
    const badge = screen.getByText("FILED 113 DAYS LATER");
    expect(badge.closest("a")).toHaveAttribute("href", "/late-filers");
  });

  it("is absent when a date is missing", () => {
    renderCard({ ...base, disclosure_date: null });
    expect(screen.queryByText(/DAYS LATER/)).toBeNull();
  });
});
