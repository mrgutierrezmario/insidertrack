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
  direction: "buy" | "sell" | null;          // the bet on the ticker; null = neutral (exchange, bond, unknown option)
  asset_type: "stock" | "option" | "other" | null;
  owner: "self" | "spouse" | "child" | "joint" | null;  // null = unknown (pre-2026-09 rows)
  amount_range: string | null;
  amount_low: number | null;
  amount_high: number | null;
  trade_date: string | null;       // YYYY-MM-DD
  disclosure_date: string | null;  // YYYY-MM-DD
  source: string;
  filing_id: string | null;
  filing_url: string | null;      // the filing itself (House PDF / Senate EFD view)
  ai_confidence: number | null;   // paper filings only: the model's confidence in this row
  amends: string | null;   // Senate: filing date of the report this amendment replaced
  risk_level: RiskLevel | null;
  politician: {
    id: number;
    name: string;
    chamber: Chamber;
    party: Party | null;
    state: string | null;
  } | null;
}

// ── Corporate insiders ────────────────────────────────────────────────────────
export interface InsiderCluster {
  ticker: string;
  company: string | null;
  buyers: number;
  buys: number;
  dollars: number;
  last_buy: string | null;
}

// ── AI Desk ────────────────────────────────────────────────────────────────
export interface ModelCall {
  id: number;
  call_date: string;
  ticker: string;
  direction: "bullish" | "bearish";
  horizon_days: 30 | 60 | 90;
  confidence: number | null;
  reasoning: string | null;
  provider: string | null;
  price_at_call: number | null;
  price_at_horizon: number | null;
  return_pct: number | null;
  spy_return_pct: number | null;
  excess_pct: number | null;
  outcome: "hit" | "miss" | null;
  resolves_on: string;
}
export interface ModelDeskStats {
  resolved: number;
  pending: number;
  hit_rate: number | null;
  avg_excess: number | null;
  by_horizon: Record<string, { n: number; hit_rate: number; avg_excess: number }>;
  by_direction: Record<string, { n: number; hit_rate: number }>;
}
export interface ModelDeskToday {
  brief: { date: string; summary: string; provider: string | null } | null;
  calls: ModelCall[];
  stats: ModelDeskStats;
}

// ── Track record ──────────────────────────────────────────────────────────────
export interface TrackRecordWindow {
  n: number;
  avg_return: number | null;
  median_return: number | null;
  win_rate: number | null;
  avg_excess: number | null;
  beat_spy_rate: number | null;
}
export interface TrackRecordTrade {
  trade_id: number;
  ticker: string;
  trade_date: string;
  disclosure_date: string;
  entry_date: string;
  entry_price: number;
  amount_range: string | null;
  owner: string | null;
  r30: number | null; r60: number | null; r90: number | null;
  x30: number | null; x60: number | null; x90: number | null;
}
export interface TrackRecord {
  politician_id: number;
  evaluated: number;
  skipped_demo: number;
  windows: Record<"30" | "60" | "90", TrackRecordWindow | undefined>;
  trades: TrackRecordTrade[];
  // Sells, measured the same way; here a NEGATIVE return is the good call.
  sells?: { evaluated: number; windows: Record<"30" | "60" | "90", TrackRecordWindow | undefined>; trades: TrackRecordTrade[] };
}

// ── 13F holder record ─────────────────────────────────────────────────────────
export interface HolderRecordTrade {
  position_id: number;
  ticker: string;
  company: string | null;
  change: "new" | "increased" | "decreased" | "closed";
  quarter: string | null;
  value_usd: number | null;
  public_on: string;
  entry_date: string;
  entry_price: number;
  r30: number | null; r60: number | null; r90: number | null;
  x30: number | null; x60: number | null; x90: number | null;
}
export interface HolderRecordSide {
  evaluated: number;
  windows: Record<"30" | "60" | "90", TrackRecordWindow | undefined>;
  trades: HolderRecordTrade[];
}
export interface HolderRecord {
  holder_id: number;
  buys: HolderRecordSide;
  sells: HolderRecordSide;
  skipped_demo: number;
}
export interface HolderLeaderboardRow {
  id: number;
  name: string;
  computed: boolean;
  n: number | null;
  beat_spy_rate: number | null;
  avg_excess: number | null;
}

export interface LeaderboardRow {
  rank: number | null;
  id: number;
  name: string;
  party: string | null;
  chamber: string | null;
  state: string | null;
  buys_measured: number | null;
  beat_spy_rate: number | null;
  skill_factor: number | null;
  as_of: string | null;
}
export interface Leaderboard {
  min_trades: number;
  as_of: string | null;
  ranked: LeaderboardRow[];
  unranked: LeaderboardRow[];
}

// ── Health (data sources) ─────────────────────────────────────────────────────
export type HealthSourceStatus = "ok" | "stale" | "failing" | "never";

export interface HealthSource {
  label: string;
  status: HealthSourceStatus;
  last_run_at: string | null;
  last_success_at: string | null;
  last_new_rows_at: string | null;
  last_new_rows: number | null;
  last_error: string | null;
  consecutive_failures: number;
}

// ── Signals ───────────────────────────────────────────────────────────────────

export type SignalLabel = "Strong Watch" | "Watch" | "Neutral" | "High Risk" | "Avoid for Now";
export type SignalDirection = "BULLISH" | "NEUTRAL" | "BEARISH";

export interface SubScores {
  smart_money: number;       // 13F whales, max 20
  insider: number;           // Congress, max 30
  corporate?: number | null; // Form 4, max 25 (null on snapshots older than 2026-09)
  momentum: number;
  sentiment?: number | null; // v1 only — dropped in v2
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
  score_version: number | null;   // regime these stats cover; null = all blended
  current_version: number;
  versions: { version: number | null; snapshots: number; since: string | null; until: string | null }[];
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
  data: { status: "ok" | "stale" | "failing"; sources: Record<string, HealthSource> } | null;
}
