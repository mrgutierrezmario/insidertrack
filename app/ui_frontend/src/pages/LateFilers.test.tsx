import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import LateFilers from "./LateFilers";

vi.mock("../lib/api", () => ({ getLateFilers: vi.fn() }));
import { getLateFilers } from "../lib/api";

const row = (id: number, name: string, late: number, trades: number, worst: number) => ({
  id, name, party: "R", chamber: "house", state: "TX", trades, late_trades: late,
  late_pct: Math.round((late / trades) * 1000) / 10, late_filings: 1, median_lag_days: 60,
  worst: { lag_days: worst, trade_date: "2026-01-02", disclosure_date: "2026-06-01", filing_url: "https://example.test/f.pdf" },
  latest_late_disclosure: "2026-06-01",
});

const DATA = {
  late_after_days: 45, window_days: null, trades: 1000, late_trades: 170, late_pct: 17.0,
  members_with_trades: 50, members_late: 2,
  items: [row(1, "Many Late", 150, 1000, 90), row(2, "Mostly Late", 20, 21, 900)],
};

function names() {
  return screen.getAllByRole("link").map((a) => a.textContent).filter((t) => t?.includes("Late"));
}

describe("<LateFilers />", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.mocked(getLateFilers).mockResolvedValue({ data: DATA } as any);
  });

  it("summarises the window and lists members by late trades", async () => {
    render(<MemoryRouter><LateFilers /></MemoryRouter>);
    expect(await screen.findByText("Many Late")).toBeInTheDocument();
    expect(screen.getByText(/were disclosed late, by/)).toHaveTextContent("170 of 1,000 trades (17.0%) were disclosed late, by 2 of 50 members who filed.");
    expect(names()).toEqual(["Many Late", "Mostly Late"]);
    expect(screen.getByText("2.5 yrs ↗")).toHaveAttribute("href", "https://example.test/f.pdf");
  });

  it("re-sorts by share late and longest delay", async () => {
    render(<MemoryRouter><LateFilers /></MemoryRouter>);
    await screen.findByText("Many Late");
    await userEvent.selectOptions(screen.getByRole("combobox"), "pct");
    expect(names()).toEqual(["Mostly Late", "Many Late"]);
  });

  it("asks for the last 12 months", async () => {
    render(<MemoryRouter><LateFilers /></MemoryRouter>);
    await screen.findByText("Many Late");
    await userEvent.click(screen.getByRole("button", { name: "Last 12 months" }));
    await waitFor(() => expect(getLateFilers).toHaveBeenLastCalledWith(365));
  });
});
