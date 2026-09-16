// Shared domain types — mirror the JSON shapes the backend returns.
//
// These are the *runtime* contract; not bound to the Pydantic models on
// purpose so the backend and frontend can evolve independently. When a
// response shape changes, update the corresponding type here and the
// compiler tells you every consumer that needs to change.

// ── Politician / Trade ────────────────────────────────────────────────────────

export type Chamber = "house" | "senate";
export type Party = "D" | "R" | "I" | string;
export type RiskLevel = "LOW" | "MEDIUM" | "HIGH";

export interface Politician {
  id: number;
  name: string;
  chamber: Chamber;
  party: Party | null;
  state: string | null;
  description?: string;
  why_tracked?: string;
  is_tracked: boolean;
  trade_count?: number;
}

export interface Trade {
  id: number;
  ticker: string | null;
  asset_name: string | null;
  transaction_type: string;
  amount_range: string | null;
  trade_date: string | null;       // YYYY-MM-DD
  disclosure_date: string | null;  // YYYY-MM-DD
  source: string;
  risk_level: RiskLevel | null;
  politician: {
    id: number;
    name: string;
    chamber: Chamber;
    party: Party | null;
    state: string | null;
  } | null;
}

// ── Signals ───────────────────────────────────────────────────────────────────

export type SignalLabel = "Strong Watch" | "Watch" | "Neutral" | "High Risk" | "Avoid for Now";
export type SignalDirection = "BULLISH" | "NEUTRAL" | "BEARISH";

export interface SubScores {
  smart_money: number;
  insider: number;
  momentum: number;
  sentiment: number;
  fundamentals?: number;
  risk_penalty: number;
}

export interface TechnicalSignal {
  ticker: string;
  signal: SignalDirection;
  score: number;
  composite_score: number;
  label: SignalLabel;
  current_price: number | null;
  is_demo: boolean;
  sma20: number | null;
  sma50: number | null;
  rsi: number | null;
  reasons: string[];
  insider_buys: number;
  insider_sells: number;
  window_start: string;
  window_end: string;
  last_trade_date: string | null;
  last_filing_date: string | null;
  sub_scores: SubScores;
}

// ── Outcomes ──────────────────────────────────────────────────────────────────

export type OutcomeDirection = "UP" | "DOWN" | "FLAT";

export interface OutcomeWindow {
  price: number | null;
  return: number | null;
  outcome: OutcomeDirection | null;
}

export interface OutcomeRow {
  id: number;
  ticker: string;
  signal_date: string;
  composite_score: number;
  label: SignalLabel;
  signal: SignalDirection;
  price_at_signal: number | null;
  politician_id: number | null;
  politician_name: string | null;
  sub_scores: Partial<SubScores>;
  d30: OutcomeWindow;
  d60: OutcomeWindow;
  d90: OutcomeWindow;
  is_backfilled: boolean;
  created_at: string | null;
}

export interface OutcomeStatsRow {
  label: SignalLabel;
  d30: { total: number; up: number; down: number; flat: number; win_rate: number | null };
  d60: { total: number; up: number; down: number; flat: number; win_rate: number | null };
  d90: { total: number; up: number; down: number; flat: number; win_rate: number | null };
}

export interface OutcomeStats {
  labels: OutcomeStatsRow[];
  total_snapshots: number;
  tracking_since: string | null;
  latest_snapshot: string | null;
}

// ── Whales ────────────────────────────────────────────────────────────────────

export type WhaleChangeType = "new" | "increased" | "decreased" | "closed" | "stable";

export interface WhaleHolder {
  id: number;
  name: string;
  cik: string;
  holder_type: string;
  is_tracked: boolean;
  position_count: number;
}

export interface WhalePosition {
  id: number;
  ticker: string;
  company_name: string;
  shares: number;
  value_usd: number;
  value_fmt: string;
  filing_date: string;
  quarter: string;
  change_type: WhaleChangeType;
  holder: { id: number; name: string } | null;
}

// ── Watchlist ─────────────────────────────────────────────────────────────────

export interface WatchlistItem {
  id: number;
  ticker: string;
  note: string | null;
  created_at: string | null;
}

// ── Health ────────────────────────────────────────────────────────────────────

export interface Health {
  status: "ok" | "degraded";
  db: boolean;
  scheduler: boolean;
  snapshot_gaps_14d: number | null;
}
