import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import Whales from "./Whales";
import { ADMIN_TOKEN_KEY } from "../lib/storage";

vi.mock("../lib/api", () => ({
  getWhales:      vi.fn(),
  getWhaleFeed:   vi.fn(),
  getWhaleLeaderboard: vi.fn().mockResolvedValue({ data: { items: [] } }),
  syncWhales:     vi.fn(),
  addToWatchlist: vi.fn(),  // WatchlistButton import
  // Re-export so `import { ADMIN_TOKEN_KEY }` from "../lib/api" still resolves
  // even though we mock the module.
  ADMIN_TOKEN_KEY: "insidertrack_admin_token",
}));
import { getWhales, getWhaleFeed, syncWhales } from "../lib/api";

// ── Fixtures ──────────────────────────────────────────────────────────────────
const HOLDERS = [
  { id: 1, name: "Berkshire Hathaway / Warren Buffett", cik: "0001067983", holder_type: "fund", is_tracked: true, position_count: 47 },
  { id: 2, name: "Renaissance Technologies / Jim Simons", cik: "0001037389", holder_type: "fund", is_tracked: true, position_count: 312 },
];

const FEED = [
  { id: 101, ticker: "AAPL", company_name: "Apple Inc.", shares: 905_560_000, value_usd: 191e9, value_fmt: "$191.0B", filing_date: "2026-02-14", quarter: "Q4 2025", change_type: "stable", holder: { id: 1, name: "Berkshire Hathaway / Warren Buffett" } },
  { id: 102, ticker: "NVDA", company_name: "NVIDIA Corp.", shares: 5_300_000, value_usd: 695e6, value_fmt: "$695.0M", filing_date: "2026-02-14", quarter: "Q4 2025", change_type: "new", holder: { id: 2, name: "Renaissance Technologies / Jim Simons" } },
  { id: 103, ticker: "TSLA", company_name: "Tesla Inc.", shares: 2_100_000, value_usd: 520e6, value_fmt: "$520.0M", filing_date: "2026-02-14", quarter: "Q4 2025", change_type: "increased", holder: { id: 2, name: "Renaissance Technologies / Jim Simons" } },
  { id: 104, ticker: "MSFT", company_name: "Microsoft Corp.", shares: 800_000, value_usd: 359e6, value_fmt: "$359.0M", filing_date: "2026-02-14", quarter: "Q4 2025", change_type: "closed", holder: { id: 1, name: "Berkshire Hathaway / Warren Buffett" } },
];

function renderPage() {
  return render(
    <MemoryRouter>
      <Whales />
    </MemoryRouter>,
  );
}

describe("<Whales />", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    vi.mocked(getWhales).mockResolvedValue({ data: HOLDERS } as any);
    vi.mocked(getWhaleFeed).mockResolvedValue({ data: FEED } as any);
  });

  it("renders the header and fetches holders + feed on mount", async () => {
    renderPage();
    expect(screen.getByRole("heading", { name: /^Whales$/i })).toBeInTheDocument();
    await waitFor(() => {
      expect(getWhales).toHaveBeenCalledTimes(1);
      expect(getWhaleFeed).toHaveBeenCalledTimes(1);
    });
    // Card sub-label is unique to the holder card row (feed rows don't include it).
    expect(await screen.findByText("Warren Buffett")).toBeInTheDocument();
  });

  it("renders holder cards with position counts and feed rows", async () => {
    renderPage();
    await screen.findByText("Warren Buffett");
    expect(screen.getByText("47 positions")).toBeInTheDocument();
    expect(screen.getByText("312 positions")).toBeInTheDocument();

    expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
    expect(screen.getByText("NVIDIA Corp.")).toBeInTheDocument();
    expect(screen.getByText("Tesla Inc.")).toBeInTheDocument();
  });

  it("renders the correct change badge for each row", async () => {
    renderPage();
    await screen.findByText("Apple Inc.");
    expect(screen.getByText("NEW")).toBeInTheDocument();        // NVDA
    expect(screen.getByText("↑ ADD")).toBeInTheDocument();      // TSLA
    expect(screen.getByText("— HOLD")).toBeInTheDocument();     // AAPL
    expect(screen.getByText("✕ CLOSED")).toBeInTheDocument();   // MSFT
  });

  it("shows the conviction-buys banner for new/increased tickers", async () => {
    renderPage();
    await screen.findByText("Apple Inc.");
    expect(screen.getByText(/Whale conviction buys/i)).toBeInTheDocument();
    // NVDA (new) and TSLA (increased) qualify; AAPL (stable) and MSFT (closed) don't.
    const banner = screen.getByText(/Whale conviction buys/i).parentElement!;
    expect(within(banner).getByText("NVDA")).toBeInTheDocument();
    expect(within(banner).getByText("TSLA")).toBeInTheDocument();
  });

  it("clicking a move-type filter refetches with change_type", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Apple Inc.");

    const moveSelect = screen.getByDisplayValue(/All moves/i);
    await user.selectOptions(moveSelect, "new");

    await waitFor(() => {
      const lastCall = vi.mocked(getWhaleFeed).mock.calls.at(-1);
      expect(lastCall![0]).toEqual(expect.objectContaining({ change_type: "new" }));
    });
  });

  it("typing in the ticker input refetches with uppercased ticker", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Apple Inc.");

    const tickerInput = screen.getByPlaceholderText(/e\.g\. NVDA/i);
    await user.type(tickerInput, "nvda");

    await waitFor(() => {
      const lastCall = vi.mocked(getWhaleFeed).mock.calls.at(-1);
      expect(lastCall![0]).toEqual(expect.objectContaining({ ticker: "NVDA" }));
    });
  });

  it("clicking a holder card sets holder_id filter", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Warren Buffett");

    // "Warren Buffett" sub-label only appears inside the holder card — climb to its button.
    const holderBtn = screen.getByText("Warren Buffett").closest("button")!;
    await user.click(holderBtn);

    await waitFor(() => {
      const lastCall = vi.mocked(getWhaleFeed).mock.calls.at(-1);
      expect(lastCall![0]).toEqual(expect.objectContaining({ holder_id: 1 }));
    });
  });

  it("Clear button resets all filters", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Apple Inc.");

    const tickerInput = screen.getByPlaceholderText(/e\.g\. NVDA/i);
    await user.type(tickerInput, "NVDA");
    await waitFor(() => expect(screen.getByText(/Clear \(1\)/i)).toBeInTheDocument());

    await user.click(screen.getByText(/Clear \(1\)/i));

    await waitFor(() => {
      const lastCall = vi.mocked(getWhaleFeed).mock.calls.at(-1);
      expect(lastCall![0]).not.toHaveProperty("ticker");
      expect(lastCall![0]).not.toHaveProperty("holder_id");
    });
  });

  it("does NOT show the Sync button when user is not admin", async () => {
    renderPage();
    await screen.findByText("Apple Inc.");
    expect(screen.queryByRole("button", { name: /Sync 13F/i })).not.toBeInTheDocument();
  });

  it("SHOWS the Sync button when ADMIN_TOKEN_KEY is set, and clicking triggers syncWhales", async () => {
    sessionStorage.setItem(ADMIN_TOKEN_KEY, "1");
    vi.mocked(syncWhales).mockResolvedValue({ data: { status: "started" } } as any);

    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Apple Inc.");

    const syncBtn = screen.getByRole("button", { name: /Sync 13F/i });
    await user.click(syncBtn);

    await waitFor(() => expect(syncWhales).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/Sync started in the background/i)).toBeInTheDocument();
  });

  it("shows empty-state message when feed comes back empty", async () => {
    vi.mocked(getWhaleFeed).mockResolvedValue({ data: [] } as any);
    renderPage();
    expect(await screen.findByText(/No positions match these filters/i)).toBeInTheDocument();
  });
});
