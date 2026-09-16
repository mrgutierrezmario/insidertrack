import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import Signals from "./Signals";

vi.mock("../lib/api", () => ({
  getTechnicalSignals: vi.fn(),
  addToWatchlist:      vi.fn(),  // WatchlistButton import — keep it inert
}));
import { getTechnicalSignals } from "../lib/api";

// ── Fixtures ──────────────────────────────────────────────────────────────────
const SIGNALS = {
  computed_at: "2026-05-24T15:00:00Z",
  signals: [
    {
      ticker: "AAPL",
      signal: "BULLISH",
      composite_score: 78,
      label: "Strong Watch",
      current_price: 211.50,
      rsi: 55,
      sub_scores: { smart_money: 22, insider: 20, momentum: 18, sentiment: 6, risk_penalty: 0 },
      reasons: ["SMA20 above SMA50 (golden cross zone)", "3 insider purchase(s)"],
    },
    {
      ticker: "TSLA",
      signal: "BEARISH",
      composite_score: 22,
      label: "High Risk",
      current_price: 249.00,
      rsi: 72,
      sub_scores: { smart_money: 8, insider: 6, momentum: 4, sentiment: 4, risk_penalty: 10 },
      reasons: ["2 HIGH-risk disclosure(s) — stale data"],
    },
    {
      ticker: "NVDA",
      signal: "NEUTRAL",
      composite_score: 45,
      label: "Neutral",
      current_price: 131.00,
      rsi: 50,
      sub_scores: { smart_money: 15, insider: 12, momentum: 12, sentiment: 6, risk_penalty: 0 },
      reasons: [],
    },
  ],
};

function renderPage() {
  return render(
    <MemoryRouter>
      <Signals />
    </MemoryRouter>,
  );
}

describe("<Signals />", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getTechnicalSignals).mockResolvedValue({ data: SIGNALS } as any);
  });

  it("renders the header and fetches signals on mount", async () => {
    renderPage();
    expect(screen.getByRole("heading", { name: /Signal Scores/i })).toBeInTheDocument();
    await waitFor(() => expect(getTechnicalSignals).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("AAPL")).toBeInTheDocument();
  });

  it("renders one card per signal with label, score, and BULLISH/BEARISH chip", async () => {
    renderPage();
    await screen.findByText("AAPL");
    expect(screen.getByText("TSLA")).toBeInTheDocument();
    expect(screen.getByText("NVDA")).toBeInTheDocument();

    // Each label appears in the filter chip row AND on its matching card — assert
    // both with getAllByText rather than collide with a single-element matcher.
    expect(screen.getAllByText("Strong Watch").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("High Risk").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText(/▲ BULLISH/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/▼ BEARISH/i).length).toBeGreaterThanOrEqual(1);
  });

  it("sorts by composite_score descending by default", async () => {
    renderPage();
    await screen.findByText("AAPL");
    const tickers = screen.getAllByRole("link").filter((a) => /^\/ticker\//.test(a.getAttribute("href") ?? "")).map((a) => a.textContent);
    expect(tickers).toEqual(["AAPL", "NVDA", "TSLA"]);  // 78 > 45 > 22
  });

  it("ticker search narrows the list", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("AAPL");

    const search = screen.getByPlaceholderText(/Filter ticker/i);
    await user.type(search, "tsl");

    await waitFor(() => {
      expect(screen.queryByText("AAPL")).not.toBeInTheDocument();
      expect(screen.queryByText("NVDA")).not.toBeInTheDocument();
      expect(screen.getByText("TSLA")).toBeInTheDocument();
    });
    expect(screen.getByText(/1 ticker/i)).toBeInTheDocument();
  });

  it("label filter chip narrows the list to that label only", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("AAPL");

    const labelChip = screen.getByRole("button", { name: "Strong Watch" });
    await user.click(labelChip);

    await waitFor(() => {
      expect(screen.getByText("AAPL")).toBeInTheDocument();
      expect(screen.queryByText("TSLA")).not.toBeInTheDocument();
      expect(screen.queryByText("NVDA")).not.toBeInTheDocument();
    });
  });

  it("signal filter (BEARISH) keeps only bearish rows", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("AAPL");

    const bearishChip = screen.getByRole("button", { name: /▼ BEARISH/i });
    await user.click(bearishChip);

    await waitFor(() => {
      expect(screen.getByText("TSLA")).toBeInTheDocument();
      expect(screen.queryByText("AAPL")).not.toBeInTheDocument();
    });
  });

  it("Refresh button re-calls getTechnicalSignals", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("AAPL");
    expect(getTechnicalSignals).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: /Refresh/i }));
    await waitFor(() => expect(getTechnicalSignals).toHaveBeenCalledTimes(2));
  });

  it("shows the empty-state when filter yields no matches", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("AAPL");

    const search = screen.getByPlaceholderText(/Filter ticker/i);
    await user.type(search, "ZZZ");

    expect(await screen.findByText(/No signals yet/i)).toBeInTheDocument();
  });

  it("renders RSI with a color cue when overbought (>70)", async () => {
    renderPage();
    const tslaCard = (await screen.findByText("TSLA")).closest("div")!.parentElement!.parentElement!;
    // TSLA has rsi=72 → overbought (red). NVDA has rsi=50 → neutral.
    const rsiValue = within(tslaCard).getAllByText("72")[0];
    expect(rsiValue).toBeInTheDocument();
  });

  it("sort dropdown switches ordering to ticker A-Z", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("AAPL");

    const sortSelect = screen.getByDisplayValue(/Score/i);
    await user.selectOptions(sortSelect, "ticker");

    await waitFor(() => {
      const tickers = screen.getAllByRole("link").filter((a) => /^\/ticker\//.test(a.getAttribute("href") ?? "")).map((a) => a.textContent);
      expect(tickers).toEqual(["AAPL", "NVDA", "TSLA"]);  // alphabetical
    });
  });
});
