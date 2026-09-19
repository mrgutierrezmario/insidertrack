import axios from "axios";
import type { AxiosResponse } from "axios";

import type {
  Health,
  InsiderCluster,
  OutcomeRow,
  OutcomeStats,
  Politician,
  TechnicalSignal,
  TrackRecord,
  Trade,
  WatchlistItem,
  WhaleHolder,
  WhalePosition,
} from "../types/api";

export { ADMIN_TOKEN_KEY } from "./storage";
import { WATCHLIST_TOKEN_KEY, readOwnAi } from "./storage";

// withCredentials ensures the httpOnly admin_token cookie is sent on every request.
const api = axios.create({ baseURL: "", withCredentials: true });

// A visitor's own AI key (Settings → AI research notes) rides along only on
// /ai/* requests, as headers the server uses for that one call and never stores.
api.interceptors.request.use((config) => {
  if ((config.url || "").startsWith("/ai/")) {
    const own = readOwnAi();
    if (own) {
      config.headers = config.headers ?? {};
      config.headers["X-AI-Provider"] = own.provider;
      config.headers["X-AI-Key"] = own.key;
      if (own.model) config.headers["X-AI-Model"] = own.model;
    }
  }
  return config;
});

// `Resp<T>` is a tiny alias so the per-endpoint signatures read at a glance.
type Resp<T> = Promise<AxiosResponse<T>>;

// ── Common request shapes ─────────────────────────────────────────────────────

interface PaginatedTrades {
  items: Trade[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
}

interface TechnicalSignalsResponse {
  computed_at: string;
  signals: TechnicalSignal[];
}

// ── Trades ────────────────────────────────────────────────────────────────────

export const getTrades = (params: Record<string, unknown> = {}): Resp<PaginatedTrades> =>
  api.get("/trades/", { params });
export const syncTrades = (): Resp<{ status: string }> => api.post("/trades/sync");

export interface BackfillStatus {
  running: boolean;
  since?: string;
  until?: string;
  reparse?: boolean;
  started_at?: string | null;
  finished_at?: string | null;
  phase?: "senate" | "house" | null;
  done?: number;
  total?: number;
  result?: { senate?: number; house?: number; errors?: Record<string, string> };
  error?: string | null;
}
export const startBackfill = (since: string, until?: string, reparse = false): Resp<{ status: string }> =>
  api.post("/trades/backfill", null, { params: { since, ...(until ? { until } : {}), ...(reparse ? { reparse: true } : {}) } });
export const getBackfillStatus = (): Resp<BackfillStatus> => api.get("/trades/backfill-status");

export interface SyncStatus {
  running: boolean;
  started_at: string | null;
  finished_at: string | null;
  result: { house: number; senate: number } | null;
  error: string | null;
}
export const getSyncStatus = (): Resp<SyncStatus> => api.get("/trades/sync-status");

// ── Politicians ───────────────────────────────────────────────────────────────

export const getPoliticians = (params: Record<string, unknown> = {}): Resp<Politician[]> =>
  api.get("/politicians/", { params });
export const getPolitician = (id: number): Resp<Politician> => api.get(`/politicians/${id}`);
export const getTrackRecord = (id: number): Resp<TrackRecord> => api.get(`/politicians/${id}/track-record`);
export const createPolitician = (body: Partial<Politician>): Resp<Politician> =>
  api.post("/politicians/", body);
export const updatePolitician = (id: number, body: Partial<Politician>): Resp<Politician> =>
  api.patch(`/politicians/${id}`, body);
export const deletePolitician = (id: number): Resp<void> => api.delete(`/politicians/${id}`);
export const getPoliticianTrades = (id: number, limit = 50): Resp<Trade[]> =>
  api.get(`/politicians/${id}/trades`, { params: { limit } });
export const toggleTrack = (id: number, track: boolean): Resp<{ id: number; is_tracked: boolean }> =>
  api.patch(`/politicians/${id}/track`, null, { params: { track } });

// ── Analysis ──────────────────────────────────────────────────────────────────

export const getLatestAnalysis = (): Resp<unknown> => api.get("/analysis/latest");
export const listAnalyses = (params: Record<string, unknown> = {}): Resp<unknown> =>
  api.get("/analysis/", { params });
export const runAnalysis = (period: string): Resp<unknown> => api.post(`/analysis/run/${period}`);

// ── Simulator ─────────────────────────────────────────────────────────────────

export const projectInvestment = (ticker: string, amount: number): Resp<unknown> =>
  api.get("/simulator/project", { params: { ticker, amount } });
export const getSimulatorGrowth = (ticker: string, amount: number): Resp<unknown> =>
  api.get("/simulator/growth", { params: { ticker, amount } });

// ── Market data ───────────────────────────────────────────────────────────────

export const getIntraday = (ticker: string, interval = "1min"): Resp<unknown> =>
  api.get(`/market/intraday/${ticker}`, { params: { interval } });
export const getPriceHistory = (ticker: string, days = 90): Resp<unknown> =>
  api.get(`/market/history/${ticker}`, { params: { days } });
export const getTickerInfo = (ticker: string): Resp<unknown> => api.get(`/market/info/${ticker}`);
export const getMarketStatus = (): Resp<unknown> => api.get("/market/status");
export const getPerformance = (): Resp<Record<string, Array<{ date: string; close: number }>>> =>
  api.get("/market/performance");
export const getMarketMovers = (): Resp<unknown> => api.get("/market/movers");
export const getMacroIndicators = (): Resp<unknown> => api.get("/market/macro");

// ── Signals ───────────────────────────────────────────────────────────────────

export const getTechnicalSignals = (): Resp<TechnicalSignalsResponse> => api.get("/signals/");

// ── Filings ───────────────────────────────────────────────────────────────────

export const getFilingInstitutions = (): Resp<unknown> => api.get("/filings/institutions");
export const addFilingInstitution = (body: unknown): Resp<unknown> =>
  api.post("/filings/institutions", body);
export const deleteFilingInstitution = (cik: string): Resp<void> =>
  api.delete(`/filings/institutions/${cik}`);
export const getRecentFilings = (limit_per = 3): Resp<unknown> =>
  api.get("/filings/recent", { params: { limit_per } });
export const getInstitutionFilings = (cik: string): Resp<unknown> => api.get(`/filings/${cik}`);

// ── Search ────────────────────────────────────────────────────────────────────

export const searchAll = (q: string): Resp<unknown> => api.get("/search/", { params: { q } });

// ── Whales ────────────────────────────────────────────────────────────────────

export const getWhales = (): Resp<WhaleHolder[]> => api.get("/whales/");
export const getWhaleFeed = (params: Record<string, unknown> = {}): Resp<WhalePosition[]> =>
  api.get("/whales/feed", { params });
export const getWhalePositions = (id: number): Resp<unknown> => api.get(`/whales/${id}/positions`);
export const getWhaleDetail = (id: number): Resp<unknown> => api.get(`/whales/${id}/detail`);
export const syncWhales = (): Resp<{ status: string }> =>
  api.post("/whales/sync");

// ── Settings ──────────────────────────────────────────────────────────────────

export const getSettingsKeys = (): Resp<unknown> => api.get("/settings/keys");
export const updateSettingKey = (key: string, value: string): Resp<unknown> =>
  api.patch(`/settings/keys/${key}`, { value });
export const clearSettingKey = (key: string): Resp<void> => api.delete(`/settings/keys/${key}`);

// ── Subscribers / Config ──────────────────────────────────────────────────────

interface Subscriber {
  id: number;
  email: string;
  is_active: boolean;
  subscribe_morning: boolean;
  subscribe_midday: boolean;
  subscribe_evening: boolean;
}

export const getSubscribers = (): Resp<Subscriber[]> => api.get("/config/subscribers");
export const getMySubscription = (email: string): Resp<Subscriber> =>
  api.get("/config/subscribers/lookup", { params: { email } });
export const addSubscriber = (body: Partial<Subscriber>): Resp<Subscriber> =>
  api.post("/config/subscribers", body);
export const updateSubscriber = (id: number, body: Partial<Subscriber>, email = ""): Resp<Subscriber> =>
  api.patch(`/config/subscribers/${id}`, body, { params: { email } });
export const deleteSubscriber = (id: number, email = ""): Resp<void> =>
  api.delete(`/config/subscribers/${id}`, { params: { email } });
export const sendReportNow = (period: string): Resp<unknown> =>
  api.post(`/config/send-report/${period}`);
export const getEmailStatus = (): Resp<unknown> => api.get("/config/email-status");

// ── News ──────────────────────────────────────────────────────────────────────

export const getNewsFeed = (): Resp<unknown> => api.get("/news/feed");
export const getTickerNews = (tickers: string | string[]): Resp<unknown> =>
  api.get("/news/", {
    params: { tickers: Array.isArray(tickers) ? tickers.join(",") : tickers },
  });

// ── Earnings ──────────────────────────────────────────────────────────────────

export const getEarningsCalendar = (params: Record<string, unknown> = {}): Resp<unknown> =>
  api.get("/earnings/", { params });
export const getTickerEarnings = (ticker: string): Resp<unknown> => api.get(`/earnings/${ticker}`);

// ── Access ────────────────────────────────────────────────────────────────────

export const getAccessLog = (): Resp<unknown> => api.get("/access/log");

// ── Outcomes ──────────────────────────────────────────────────────────────────

export const getOutcomeStats = (): Resp<OutcomeStats> => api.get("/outcomes/stats");
export const getOutcomes = (params: Record<string, unknown> = {}): Resp<OutcomeRow[]> =>
  api.get("/outcomes/", { params });
export const runOutcomeSnapshot = (): Resp<{ status: string }> => api.post("/outcomes/snapshot");
export const runOutcomeFill = (): Resp<{ status: string }> => api.post("/outcomes/fill");
export const runOutcomeBackfill = (window_days = 14): Resp<{ status: string; window_days: number }> =>
  api.post("/outcomes/backfill", null, { params: { window_days } });

// ── Alerts ────────────────────────────────────────────────────────────────────

interface AlertRule {
  id: number;
  name: string;
  alert_type: string;
  ticker: string | null;
  threshold: number | null;
  is_active: boolean;
  notify_email?: string | null;
  created_at: string;
}

interface AlertEvent {
  id: number;
  rule_id: number;
  rule_name: string | null;
  alert_type: string | null;
  ticker: string | null;
  message: string;
  seen: boolean;
  triggered_at: string | null;
}

export const getAlertTypes = (): Resp<Array<{ value: string; description: string }>> =>
  api.get("/alerts/types");
export const getAlertRules = (): Resp<AlertRule[]> => api.get("/alerts/rules");
export const createAlertRule = (body: Partial<AlertRule>): Resp<AlertRule> =>
  api.post("/alerts/rules", body);
export const updateAlertRule = (id: number, body: Partial<AlertRule>): Resp<AlertRule> =>
  api.patch(`/alerts/rules/${id}`, body);
export const deleteAlertRule = (id: number): Resp<void> => api.delete(`/alerts/rules/${id}`);
export const getAlertEvents = (params: Record<string, unknown> = {}): Resp<AlertEvent[]> =>
  api.get("/alerts/events", { params });
export const getUnseenAlertCount = (): Resp<{ unseen: number }> =>
  api.get("/alerts/events/unseen-count");
export const markAlertsSeen = (): Resp<{ status: string }> => api.post("/alerts/events/mark-seen");
export const runAlerts = (): Resp<{ status: string }> => api.post("/alerts/run");

// ── AI summaries ──────────────────────────────────────────────────────────────

export interface AiStatus { configured: boolean; provider: string | null; label: string | null; model: string | null; }
export const getAiStatus = (): Resp<AiStatus> => api.get("/ai/status");
export interface AiSettings {
  configured: boolean; active: string | null; chosen: string;
  providers: Record<string, { label: string; configured: boolean; model: string }>;
}
export const getAiSettings = (): Resp<AiSettings> => api.get("/settings/ai");
// Visitor's own key (headers added by the interceptor)
export const testOwnAiKey = (): Resp<{ provider: string; ok: boolean; message: string }> => api.post("/ai/test");
// Explicit headers so the list can load for a key that is typed but not yet saved.
export const getOwnModels = (provider: string, key: string): Resp<ModelOption[]> =>
  api.get("/ai/models", { headers: { "X-AI-Provider": provider, "X-AI-Key": key } });
export interface ModelOption { id: string; label: string }
export const getAiModels = (provider: string): Resp<ModelOption[]> => api.get("/settings/ai/models", { params: { provider } });
export const testAiProvider = (provider: string): Resp<{ provider: string; ok: boolean; message: string }> =>
  api.post("/settings/ai/test", null, { params: { provider } });
export const getAiSummary = (ticker: string, refresh = false): Resp<unknown> =>
  api.get(`/ai/summary/${ticker}`, { params: { refresh } });

// ── Corporate insiders (Form 4) ───────────────────────────────────────────────

export const getInsiderTransactions = (params: Record<string, unknown> = {}): Resp<unknown> =>
  api.get("/insiders/", { params });
export const getInsiderSummary = (): Resp<unknown> => api.get("/insiders/summary");
export const getInsiderClusters = (days = 30, minBuyers = 2): Resp<{ days: number; min_buyers: number; items: InsiderCluster[] }> =>
  api.get("/insiders/clusters", { params: { days, min_buyers: minBuyers } });
export const syncInsiders = (): Resp<unknown> => api.post("/insiders/sync");

// ── Watchlist ─────────────────────────────────────────────────────────────────
// Auth: every call attaches `Authorization: Bearer <token>` from localStorage.
// The token is minted server-side on the first POST /watchlist/ for a new email
// and returned in the response — addToWatchlist() captures and stores it.
// Lost tokens are recovered via recoverWatchlistToken(); the server emails the
// address a freshly minted token (rotating the stored hash).

interface AddWatchlistResponse {
  id: number;
  ticker: string;
  status: "added" | "already_watching";
  token?: string;  // present only on the first add for a given email
}

function watchlistAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem(WATCHLIST_TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export const getWatchlist = (email: string): Resp<WatchlistItem[]> =>
  api.get("/watchlist/", { params: { email }, headers: watchlistAuthHeaders() });

export const getWatchlistSignals = (email: string): Resp<unknown> =>
  api.get("/watchlist/signals", { params: { email }, headers: watchlistAuthHeaders() });

export async function addToWatchlist(
  body: { email: string; ticker: string; note?: string },
): Promise<AxiosResponse<AddWatchlistResponse>> {
  const r = await api.post<AddWatchlistResponse>("/watchlist/", body, {
    headers: watchlistAuthHeaders(),
  });
  if (r.data?.token) {
    localStorage.setItem(WATCHLIST_TOKEN_KEY, r.data.token);
  }
  return r;
}

export const removeFromWatchlist = (id: number, email = ""): Resp<void> =>
  api.delete(`/watchlist/${id}`, { params: { email }, headers: watchlistAuthHeaders() });

export const recoverWatchlistToken = (email: string): Resp<{ status: string }> =>
  api.post("/watchlist/recover", { email });

// ── Federal Reserve officials ─────────────────────────────────────────────────

export const getFedOfficials = (): Resp<unknown> => api.get("/fed/officials");
export const getFedTrades = (params: Record<string, unknown> = {}): Resp<unknown> =>
  api.get("/fed/trades", { params });
export const seedFed = (): Resp<unknown> => api.post("/fed/seed");

// ── Admin ─────────────────────────────────────────────────────────────────────

/** Cookie-based login — sets httpOnly admin_token cookie. */
export const adminLogin = (password: string): Resp<{ ok: boolean }> =>
  api.post("/access/admin/login", { password });
/** Clears the httpOnly admin_token cookie. */
export const adminLogout = (): Resp<{ ok: boolean }> => api.post("/access/admin/logout");
/** Returns { is_admin: bool } by inspecting the httpOnly cookie server-side. */
export const getAdminStatus = (): Resp<{ is_admin: boolean }> => api.get("/access/admin/status");
/** Legacy header-based verify — kept for backward compat. */
export const verifyAdmin = (password: string): Resp<unknown> =>
  api.post("/access/admin/verify", { password });

// ── Health ────────────────────────────────────────────────────────────────────

// /health answers 503 when db/scheduler are down; we still want the body.
export const getHealth = (): Resp<Health> =>
  api.get("/health", { validateStatus: (s) => s === 200 || s === 503 });
