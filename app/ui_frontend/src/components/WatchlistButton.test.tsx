import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import WatchlistButton from "./WatchlistButton";
import { EMAIL_KEY } from "../lib/storage";

// Mock the API module — we don't want real network calls in unit tests.
vi.mock("../lib/api", () => ({
  addToWatchlist: vi.fn(),
}));
import { addToWatchlist } from "../lib/api";

describe("<WatchlistButton />", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the idle '+ Watch' label initially", () => {
    render(<WatchlistButton ticker="AAPL" />);
    expect(screen.getByRole("button", { name: /\+ Watch/i })).toBeInTheDocument();
  });

  it("opens the email modal when no email is stored", async () => {
    const user = userEvent.setup();
    render(<WatchlistButton ticker="NVDA" />);
    await user.click(screen.getByRole("button", { name: /\+ Watch/i }));
    expect(screen.getByText(/Add to Watchlist/i)).toBeInTheDocument();
    expect(screen.getByText("NVDA")).toBeInTheDocument();
  });

  it("calls addToWatchlist directly when email is already in localStorage", async () => {
    localStorage.setItem(EMAIL_KEY, "saved@example.com");
    vi.mocked(addToWatchlist).mockResolvedValueOnce({ data: { id: 1, ticker: "X", status: "added" as const } } as any);

    const user = userEvent.setup();
    render(<WatchlistButton ticker="TSLA" />);
    await user.click(screen.getByRole("button"));

    await waitFor(() => {
      expect(addToWatchlist).toHaveBeenCalledWith({ email: "saved@example.com", ticker: "TSLA" });
    });
    expect(screen.getByRole("button", { name: /✓ Added/i })).toBeInTheDocument();
  });

  it("shows '✓ Watching' when the API reports already_watching", async () => {
    localStorage.setItem(EMAIL_KEY, "saved@example.com");
    vi.mocked(addToWatchlist).mockResolvedValueOnce({ data: { id: 1, ticker: "X", status: "already_watching" as const } } as any);

    const user = userEvent.setup();
    render(<WatchlistButton ticker="GOOG" />);
    await user.click(screen.getByRole("button"));

    expect(await screen.findByRole("button", { name: /✓ Watching/i })).toBeInTheDocument();
  });

  it("shows '✕ Error' when the API call fails", async () => {
    localStorage.setItem(EMAIL_KEY, "saved@example.com");
    vi.mocked(addToWatchlist).mockRejectedValueOnce(new Error("network"));

    const user = userEvent.setup();
    render(<WatchlistButton ticker="META" />);
    await user.click(screen.getByRole("button"));

    expect(await screen.findByRole("button", { name: /✕ Error/i })).toBeInTheDocument();
  });

  it("modal rejects an invalid email and never calls the API", async () => {
    const user = userEvent.setup();
    render(<WatchlistButton ticker="AMD" />);
    await user.click(screen.getByRole("button"));

    const input = screen.getByPlaceholderText(/you@example\.com/i);
    await user.type(input, "not-an-email");
    await user.click(screen.getByRole("button", { name: /Save/i }));

    expect(screen.getByText(/valid email/i)).toBeInTheDocument();
    expect(addToWatchlist).not.toHaveBeenCalled();
  });

  it("modal accepts a valid email, stores it, and triggers the add flow", async () => {
    vi.mocked(addToWatchlist).mockResolvedValueOnce({ data: { id: 1, ticker: "X", status: "added" as const } } as any);
    const user = userEvent.setup();
    render(<WatchlistButton ticker="CRM" />);
    await user.click(screen.getByRole("button"));

    const input = screen.getByPlaceholderText(/you@example\.com/i);
    await user.type(input, "Alice@Example.com");
    await user.click(screen.getByRole("button", { name: /Save/i }));

    await waitFor(() => {
      expect(addToWatchlist).toHaveBeenCalledWith({
        email: "alice@example.com",   // lowercased before submission
        ticker: "CRM",
      });
    });
    expect(localStorage.getItem(EMAIL_KEY)).toBe("alice@example.com");
  });
});
