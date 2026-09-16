import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import Outcomes from "./Outcomes";

// ── Mock the API module — pages call axios, we want pure unit tests ───────────
vi.mock("../lib/api", () => ({
  getOutcomeStats:    vi.fn(),
  getOutcomes:        vi.fn(),
  runOutcomeSnapshot: vi.fn(),
  runOutcomeFill:     vi.fn(),
}));
import { getOutcomeStats, getOutcomes, runOutcomeSnapshot, runOutcomeFill } from "../lib/api";

// ── Fixtures ──────────────────────────────────────────────────────────────────
const STATS_FIXTURE = {
  total_snapshots: 4,
  tracking_since:  "2026-05-16",
  latest_snapshot: "2026-05-22",
  labels: [
    { label: "Strong Watch",  d30: { total: 2, up: 1, down: 1, flat: 0, win_rate: 50 },  d60: { total: 0, up: 0, down: 0, flat: 0, win_rate: null }, d90: { total: 0, up: 0, down: 0, flat: 0, win_rate: null } },
    { label: "Watch",         d30: { total: 0, up: 0, down: 0, flat: 0, win_rate: null }, d60: { total: 0, up: 0, down: 0, flat: 0, win_rate: null }, d90: { total: 0, up: 0, down: 0, flat: 0, win_rate: null } },
    { label: "Neutral",       d30: { total: 0, up: 0, down: 0, flat: 0, win_rate: null }, d60: { total: 0, up: 0, down: 0, flat: 0, win_rate: null }, d90: { total: 0, up: 0, down: 0, flat: 0, win_rate: null } },
    { label: "High Risk",     d30: { total: 0, up: 0, down: 0, flat: 0, win_rate: null }, d60: { total: 0, up: 0, down: 0, flat: 0, win_rate: null }, d90: { total: 0, up: 0, down: 0, flat: 0, win_rate: null } },
    { label: "Avoid for Now", d30: { total: 0, up: 0, down: 0, flat: 0, win_rate: null }, d60: { total: 0, up: 0, down: 0, flat: 0, win_rate: null }, d90: { total: 0, up: 0, down: 0, flat: 0, win_rate: null } },
  ],
};

const RESOLVED_ROW = {
  id: 1, ticker: "AAPL", signal_date: "2026-04-01", composite_score: 78,
  label: "Strong Watch", signal: "BULLISH", price_at_signal: 211,
  politician_id: 42, politician_name: "Jane Doe",
  sub_scores: { smart_money: 22, insider: 20, momentum: 18, sentiment: 6, risk_penalty: 0 },
  d30: { price: 220, return: 4.3, outcome: "UP" },
  d60: { price: 200, return: -5.2, outcome: "DOWN" },
  d90: { price: 212, return: 0.5, outcome: "FLAT" },
};

const PENDING_ROW = {
  id: 2, ticker: "NVDA", signal_date: "2026-05-22", composite_score: 65,
  label: "Watch", signal: "BULLISH", price_at_signal: 131,
  politician_id: null, politician_name: null,
  sub_scores: { smart_money: 18, insider: 12, momentum: 22, sentiment: 6, risk_penalty: 0 },
  d30: { price: null, return: null, outcome: null },
  d60: { price: null, return: null, outcome: null },
  d90: { price: null, return: null, outcome: null },
};

// Helper — render with router so <Link> doesn't blow up
function renderPage() {
  return render(
    <MemoryRouter>
      <Outcomes />
    </MemoryRouter>,
  );
}

describe("<Outcomes />", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.clearAllMocks();
    vi.mocked(getOutcomeStats).mockResolvedValue({ data: STATS_FIXTURE } as any);
    vi.mocked(getOutcomes).mockResolvedValue({ data: [RESOLVED_ROW, PENDING_ROW] } as any);
  });

  it("renders the page header and stats summary", async () => {
    renderPage();
    expect(screen.getByRole("heading", { name: /Signal Outcomes/i })).toBeInTheDocument();
    await waitFor(() => expect(getOutcomeStats).toHaveBeenCalled());
    expect(await screen.findByText(/4 snapshots/)).toBeInTheDocument();
  });

  it("renders a row per outcome and shows real UP/DOWN/FLAT outcomes for resolved rows", async () => {
    renderPage();
    expect(await screen.findByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("NVDA")).toBeInTheDocument();

    // Resolved row shows actual outcomes
    const aaplRow = screen.getByText("AAPL").closest("tr")!;
    expect(within(aaplRow).getByText("UP")).toBeInTheDocument();
    expect(within(aaplRow).getByText("DOWN")).toBeInTheDocument();
    expect(within(aaplRow).getByText("FLAT")).toBeInTheDocument();
    expect(within(aaplRow).getByText(/\+4\.3%/)).toBeInTheDocument();
  });

  it("shows projected 'fills YYYY-MM-DD' on pending outcome cells", async () => {
    renderPage();
    await screen.findByText("NVDA");
    const nvdaRow = screen.getByText("NVDA").closest("tr")!;

    // signal_date 2026-05-22 → fills 2026-06-21 (30d), 2026-07-21 (60d), 2026-08-20 (90d)
    expect(within(nvdaRow).getByText("fills 2026-06-21")).toBeInTheDocument();
    expect(within(nvdaRow).getByText("fills 2026-07-21")).toBeInTheDocument();
    expect(within(nvdaRow).getByText("fills 2026-08-20")).toBeInTheDocument();
  });

  it("ticker filter triggers a refetch with the uppercased value", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("AAPL");

    const tickerInput = screen.getByPlaceholderText(/Filter by ticker/i);
    await user.type(tickerInput, "aapl");

    await waitFor(() => {
      const lastCall = vi.mocked(getOutcomes).mock.calls.at(-1);
      expect(lastCall![0]).toEqual(expect.objectContaining({ ticker: "AAPL" }));
    });
  });

  it("resolved filter sends resolved=true to the API", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("AAPL");

    const resolvedSelect = screen.getByDisplayValue(/All rows/i);
    await user.selectOptions(resolvedSelect, "yes");

    await waitFor(() => {
      const lastCall = vi.mocked(getOutcomes).mock.calls.at(-1);
      expect(lastCall![0]).toEqual(expect.objectContaining({ resolved: true }));
    });
  });

  it("renders the empty-state message when the API returns no rows", async () => {
    vi.mocked(getOutcomes).mockResolvedValue({ data: [] } as any);
    renderPage();
    expect(await screen.findByText(/No outcome records yet/i)).toBeInTheDocument();
  });

  it("hides the admin actions for visitors", async () => {
    renderPage();
    await screen.findByText("AAPL");
    expect(screen.queryByRole("button", { name: /Snapshot Today/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Fill Outcomes/i })).not.toBeInTheDocument();
  });

  it("Snapshot Today button calls runOutcomeSnapshot (admin)", async () => {
    sessionStorage.setItem("insidertrack_admin_token", "1");
    vi.mocked(runOutcomeSnapshot).mockResolvedValue({ data: { status: "snapshot started" } } as any);
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("AAPL");

    const snapshotBtn = screen.getByRole("button", { name: /Snapshot Today/i });
    await user.click(snapshotBtn);

    await waitFor(() => expect(runOutcomeSnapshot).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/Snapshot started/i)).toBeInTheDocument();
  });

  it("Fill Outcomes button calls runOutcomeFill (admin)", async () => {
    sessionStorage.setItem("insidertrack_admin_token", "1");
    vi.mocked(runOutcomeFill).mockResolvedValue({ data: { status: "fill started" } } as any);
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("AAPL");

    const fillBtn = screen.getByRole("button", { name: /Fill Outcomes/i });
    await user.click(fillBtn);

    await waitFor(() => expect(runOutcomeFill).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/Fill started/i)).toBeInTheDocument();
  });
});
