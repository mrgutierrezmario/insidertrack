import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import Fed from "./Fed";
import { ADMIN_TOKEN_KEY } from "../lib/storage";

vi.mock("../lib/api", () => ({
  getFedOfficials: vi.fn(),
  getFedTrades:    vi.fn(),
  seedFed:         vi.fn(),
  addToWatchlist:  vi.fn(),  // pulled in by WatchlistButton on each row
  // Fed.tsx imports ADMIN_TOKEN_KEY from "../lib/api" (re-exported)
  ADMIN_TOKEN_KEY: "insidertrack_admin_token",
}));
import { getFedOfficials, getFedTrades, seedFed } from "../lib/api";

// ── Fixtures ──────────────────────────────────────────────────────────────────
const OFFICIALS = [
  {
    id: 1, name: "Jerome Powell", title: "Chair",
    role: "board", party: "R", is_fomc_voter: true,
    term_expires: "2028", trade_count: 4,
  },
  {
    id: 2, name: "Lael Brainard", title: "Vice Chair",
    role: "board", party: "D", is_fomc_voter: true,
    term_expires: "2027", trade_count: 0,
  },
  {
    id: 3, name: "John Williams", title: "President, NY Fed",
    role: "regional_president", party: null, is_fomc_voter: true,
    district: "Second", trade_count: 2,
  },
];

// Distinct names from OFFICIALS so a query like "Jerome Powell" unambiguously
// targets the official card, not a trade row.
const TRADES = [
  { id: 11, ticker: "MSFT", trade_date: "2026-03-10", transaction_type: "purchase",
    amount_range: "$15,001–$50,000", official_name: "Trader A",
    official_title: "Some Title", disclosure_date: "2026-03-15" },
  { id: 12, ticker: "AAPL", trade_date: "2026-03-05", transaction_type: "sale",
    amount_range: "$1,001–$15,000", official_name: "Trader B",
    official_title: "Some Title", disclosure_date: "2026-03-12" },
];

function renderPage() {
  return render(
    <MemoryRouter>
      <Fed />
    </MemoryRouter>,
  );
}

describe("<Fed />", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    vi.mocked(getFedOfficials).mockResolvedValue({ data: OFFICIALS } as any);
    vi.mocked(getFedTrades).mockResolvedValue({ data: { items: TRADES, has_more: false } } as any);
  });

  it("renders header and fetches officials + trades on mount", async () => {
    renderPage();
    expect(screen.getByRole("heading", { name: /Federal Reserve Officials/i })).toBeInTheDocument();
    await waitFor(() => {
      expect(getFedOfficials).toHaveBeenCalledTimes(1);
      expect(getFedTrades).toHaveBeenCalledTimes(1);
    });
  });

  it("shows board members in the default 'board' tab", async () => {
    renderPage();
    await screen.findByText("Jerome Powell");
    expect(screen.getByText("Jerome Powell")).toBeInTheDocument();
    expect(screen.getByText("Lael Brainard")).toBeInTheDocument();
    // Regional presidents are hidden on the default board tab
    expect(screen.queryByText("John Williams")).not.toBeInTheDocument();
  });

  it("switches to the regional tab and shows regional presidents", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Jerome Powell");

    await user.click(screen.getByRole("button", { name: /Regional \(1\)/i }));

    await waitFor(() => {
      expect(screen.getByText("John Williams")).toBeInTheDocument();
      expect(screen.queryByText("Jerome Powell")).not.toBeInTheDocument();
    });
  });

  it("clicking an official refetches trades with official_id", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Jerome Powell");

    await user.click(screen.getByText("Jerome Powell"));

    await waitFor(() => {
      const lastCall = vi.mocked(getFedTrades).mock.calls.at(-1);
      expect(lastCall![0]).toEqual(expect.objectContaining({ official_id: 1 }));
    });
  });

  it("typing in the ticker filter refetches with uppercased ticker", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Jerome Powell");

    const tickerInput = screen.getByPlaceholderText(/Filter ticker…/i);
    await user.type(tickerInput, "msft");

    await waitFor(() => {
      const lastCall = vi.mocked(getFedTrades).mock.calls.at(-1);
      expect(lastCall![0]).toEqual(expect.objectContaining({ ticker: "MSFT" }));
    });
  });

  it("selecting a transaction type refetches with transaction_type", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Jerome Powell");

    const typeSelect = screen.getByDisplayValue(/All types/i);
    await user.selectOptions(typeSelect, "purchase");

    await waitFor(() => {
      const lastCall = vi.mocked(getFedTrades).mock.calls.at(-1);
      expect(lastCall![0]).toEqual(expect.objectContaining({ transaction_type: "purchase" }));
    });
  });

  it("Clear button resets ticker and type filters", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Jerome Powell");

    const tickerInput = screen.getByPlaceholderText(/Filter ticker…/i);
    await user.type(tickerInput, "MSFT");
    await waitFor(() => expect(screen.getByRole("button", { name: /^Clear$/i })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /^Clear$/i }));

    await waitFor(() => {
      const lastCall = vi.mocked(getFedTrades).mock.calls.at(-1);
      expect(lastCall![0]).not.toHaveProperty("ticker");
    });
  });

  it("CSV button appears only when trades are present", async () => {
    renderPage();
    await screen.findByText("Jerome Powell");
    expect(screen.getByRole("button", { name: /↓ CSV/i })).toBeInTheDocument();
  });

  it("does NOT show the roster refresh button when user is not admin", async () => {
    renderPage();
    await screen.findByText("Jerome Powell");
    expect(screen.queryByRole("button", { name: /Refresh roster/i })).not.toBeInTheDocument();
  });

  it("SHOWS the roster refresh button when admin and re-seeds on click", async () => {
    sessionStorage.setItem(ADMIN_TOKEN_KEY, "1");
    vi.mocked(seedFed).mockResolvedValue({ data: { seeded: 12 } } as any);

    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Jerome Powell");

    const btn = screen.getByRole("button", { name: /Refresh roster/i });
    await user.click(btn);

    await waitFor(() => expect(seedFed).toHaveBeenCalledTimes(1));
    // There is no machine-readable Fed trade source, so nothing else is called.
    expect(await screen.findByText(/Roster refreshed/i)).toBeInTheDocument();
  });

  it("shows the compliant empty state when no trades come back", async () => {
    vi.mocked(getFedTrades).mockResolvedValue({ data: { items: [], has_more: false } } as any);
    renderPage();
    expect(await screen.findByText(/No individual-stock transactions on record/i)).toBeInTheDocument();
  });
});
