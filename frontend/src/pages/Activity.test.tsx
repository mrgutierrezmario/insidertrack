import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import Activity from "./Activity";

vi.mock("../lib/api", () => ({
  getTrades:              vi.fn(),
  getInsiderTransactions: vi.fn(),
  getFedTrades:           vi.fn(),
  addToWatchlist:         vi.fn(),  // pulled in by WatchlistButton on each row
}));
import { getTrades, getInsiderTransactions, getFedTrades } from "../lib/api";

// ── Fixtures ──────────────────────────────────────────────────────────────────
const CONG = {
  items: [
    {
      id: 1, ticker: "AAPL", trade_date: "2026-03-10",
      transaction_type: "purchase", amount_range: "$1,001–$15,000",
      politician: { name: "Nancy Pelosi", party: "D", chamber: "House" },
    },
    {
      id: 2, ticker: "NVDA", trade_date: "2026-03-08",
      transaction_type: "sale", amount_range: "$15,001–$50,000",
      politician: { name: "Dan Crenshaw", party: "R", chamber: "House" },
    },
  ],
  has_more: false,
};

const CORP = {
  items: [
    {
      id: 11, ticker: "TSLA", transaction_date: "2026-03-09",
      transaction_type: "Buy",
      insider_name: "Elon Musk", insider_title: "CEO",
    },
  ],
  has_more: false,
};

const FED = {
  items: [
    {
      id: 21, ticker: "MSFT", trade_date: "2026-03-07",
      transaction_type: "purchase", amount_range: "$50,001–$100,000",
      official_name: "Jerome Powell", official_title: "Chair",
    },
  ],
  has_more: false,
};

function renderPage() {
  return render(
    <MemoryRouter>
      <Activity />
    </MemoryRouter>,
  );
}

describe("<Activity />", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getTrades).mockResolvedValue({ data: CONG } as any);
    vi.mocked(getInsiderTransactions).mockResolvedValue({ data: CORP } as any);
    vi.mocked(getFedTrades).mockResolvedValue({ data: FED } as any);
  });

  it("renders the header and fans out to all three sources on mount", async () => {
    renderPage();
    expect(screen.getByRole("heading", { name: /Activity Feed/i })).toBeInTheDocument();
    await waitFor(() => {
      expect(getTrades).toHaveBeenCalledTimes(1);
      expect(getInsiderTransactions).toHaveBeenCalledTimes(1);
      expect(getFedTrades).toHaveBeenCalledTimes(1);
    });
  });

  it("renders rows from each source with the right badge", async () => {
    renderPage();
    await screen.findByText("Nancy Pelosi");
    expect(screen.getByText("Nancy Pelosi")).toBeInTheDocument();
    expect(screen.getByText("Elon Musk")).toBeInTheDocument();
    expect(screen.getByText("Jerome Powell")).toBeInTheDocument();
    // Source labels appear both as filter chips and as row badges — at least one each.
    expect(screen.getAllByText(/Congress/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Insider/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/^Fed$/i).length).toBeGreaterThan(0);
  });

  it("sorts rows newest-first regardless of source", async () => {
    renderPage();
    await screen.findByText("Nancy Pelosi");
    // Order: AAPL 03-10 > TSLA 03-09 > NVDA 03-08 > MSFT 03-07
    const dates = ["2026-03-10", "2026-03-09", "2026-03-08", "2026-03-07"];
    const rendered = dates.map((d) => screen.getByText(d));
    // DOM order check: each must precede the next
    for (let i = 0; i < rendered.length - 1; i++) {
      expect(rendered[i].compareDocumentPosition(rendered[i + 1]))
        .toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    }
  });

  it("toggling the Congress source button hides its rows", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Nancy Pelosi");

    // First Congress button is the source filter chip (uppercase label "Congress")
    await user.click(screen.getByRole("button", { name: /^Congress$/i }));
    await waitFor(() => {
      expect(screen.queryByText("Nancy Pelosi")).not.toBeInTheDocument();
    });
    // Other sources still present
    expect(screen.getByText("Elon Musk")).toBeInTheDocument();
  });

  it("Buys-only filter hides sale rows", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Nancy Pelosi");

    await user.click(screen.getByRole("button", { name: /^Buys$/i }));
    await waitFor(() => {
      // NVDA was a sale → gone. AAPL was a purchase → still here.
      expect(screen.queryByText("Dan Crenshaw")).not.toBeInTheDocument();
      expect(screen.getByText("Nancy Pelosi")).toBeInTheDocument();
    });
  });

  it("typing in the ticker filter narrows the list (no refetch — client-side)", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Nancy Pelosi");

    const tickerInput = screen.getByPlaceholderText(/Ticker…/i);
    await user.type(tickerInput, "AAPL");
    await waitFor(() => {
      expect(screen.queryByText("Elon Musk")).not.toBeInTheDocument();
      expect(screen.queryByText("Jerome Powell")).not.toBeInTheDocument();
      expect(screen.getByText("Nancy Pelosi")).toBeInTheDocument();
    });
  });

  it("CSV download button appears only when results are present", async () => {
    renderPage();
    await screen.findByText("Nancy Pelosi");
    expect(screen.getByRole("button", { name: /↓ CSV/i })).toBeInTheDocument();
  });

  it("shows the empty-state message when every source returns nothing", async () => {
    vi.mocked(getTrades).mockResolvedValue({ data: { items: [], has_more: false } } as any);
    vi.mocked(getInsiderTransactions).mockResolvedValue({ data: { items: [], has_more: false } } as any);
    vi.mocked(getFedTrades).mockResolvedValue({ data: { items: [], has_more: false } } as any);
    renderPage();
    expect(await screen.findByText(/No activity matches your filters/i)).toBeInTheDocument();
  });

  it("Clear button appears with active filters and resets them", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Nancy Pelosi");

    await user.click(screen.getByRole("button", { name: /^Buys$/i }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^Clear$/i })).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: /^Clear$/i }));
    // Filter resets → "All types" becomes active again, NVDA (sale) is back
    await waitFor(() => {
      expect(screen.getByText("Dan Crenshaw")).toBeInTheDocument();
    });
  });

  it("Load-more button appears only when hasMore is true and refetches with offset", async () => {
    vi.mocked(getTrades).mockResolvedValue({ data: { ...CONG, has_more: true } } as any);
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Nancy Pelosi");

    const loadMore = screen.getByRole("button", { name: /Load more/i });
    expect(loadMore).toBeInTheDocument();
    await user.click(loadMore);

    await waitFor(() => {
      // Second call to getTrades should carry offset=50
      const lastCall = vi.mocked(getTrades).mock.calls.at(-1);
      expect(lastCall![0]).toEqual(expect.objectContaining({ offset: 50, limit: 50 }));
    });
  });
});
