import { C } from "../lib/theme";
import useDocumentTitle from "../hooks/useDocumentTitle";
import useAdmin from "../hooks/useAdmin";
import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import { isAxiosError } from "axios";
import { getWhales, getWhaleFeed, syncWhales } from "../lib/api";
import { exportCSV } from "../lib/csv";
import WatchlistButton from "../components/WatchlistButton";

type ChangeType = "new" | "increased" | "decreased" | "closed" | "stable";

const CHANGE_STYLE: Record<ChangeType, { color: string; bg: string; label: string }> = {
  new:       { color: C.success,  bg: C.successBg, label: "NEW" },
  increased: { color: "#34d399",  bg: "var(--c-successBg)", label: "↑ ADD" },
  decreased: { color: C.warning,  bg: "var(--c-warningBg)", label: "↓ TRIM" },
  closed:    { color: C.danger,  bg: C.dangerBg, label: "✕ CLOSED" },
  stable:    { color: C.textMuted,  bg: C.bgSunken, label: "— HOLD" },
};

interface FeedRow {
  id: number;
  ticker: string;
  company_name?: string | null;
  shares?: number | null;
  value_fmt?: string | null;
  quarter?: string | null;
  change_type: ChangeType | string;
  holder?: { id: number; name: string } | null;
}

interface Holder {
  id: number;
  name: string;
  position_count: number;
}

interface Filters {
  holder_id: number | "";
  change_type: ChangeType | "";
  ticker: string;
}

interface SyncStats {
  synced?: number;
  skipped?: number;
  unmapped?: number;
  error?: string;
}

function exportWhalesCSV(rows: FeedRow[]) {
  exportCSV(
    ["ticker","company_name","holder","change_type","shares","value","quarter"],
    rows.map((r) => [r.ticker, r.company_name ?? "", r.holder?.name ?? "", r.change_type, r.shares ?? "", r.value_fmt ?? "", r.quarter ?? ""]),
    "insidertrack-whales",
  );
}

function ChangeBadge({ type }: { type: string }) {
  const s = (CHANGE_STYLE as Record<string, { color: string; bg: string; label: string }>)[type] || CHANGE_STYLE.stable;
  return (
    <span style={{
      background: s.bg, color: s.color,
      fontSize: "0.7rem", fontWeight: 700, padding: "2px 8px",
      borderRadius: 4, whiteSpace: "nowrap",
    }}>
      {s.label}
    </span>
  );
}

function fmtShares(n: number | null | undefined): string {
  if (!n) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toLocaleString();
}

const inputStyle: CSSProperties = {
  background: C.surface, color: C.text,
  border: "1px solid var(--c-surfaceAlt)", borderRadius: 6,
  padding: "0.4rem 0.75rem", fontSize: "0.85rem",
};

function SyncButton({ onRefresh }: { onRefresh: () => void }) {
  const [syncing, setSyncing] = useState(false);
  const [result, setResult] = useState<SyncStats | null>(null);

  const doSync = async () => {
    setSyncing(true);
    setResult(null);
    try {
      const r = await syncWhales();
      setResult(r.data as SyncStats);
      onRefresh();
    } catch (e) {
      const detail = isAxiosError(e) ? (e.response?.data as { detail?: string } | undefined)?.detail : null;
      setResult({ error: detail || "Sync failed" });
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
      <button
        onClick={doSync}
        disabled={syncing}
        style={{ background: syncing ? C.surfaceAlt : C.accentSolid, color: "#fff", border: "none", borderRadius: 6, padding: "0.45rem 1.1rem", cursor: syncing ? "not-allowed" : "pointer", fontSize: "0.85rem", opacity: syncing ? 0.7 : 1 }}
      >
        {syncing ? "Syncing EDGAR…" : "↻ Sync 13F Holdings"}
      </button>
      {result && !result.error && (
        <span style={{ color: C.success, fontSize: "0.72rem" }}>
          {result.synced} positions synced · {result.skipped} skipped · {result.unmapped} unmapped
        </span>
      )}
      {result?.error && <span style={{ color: C.danger, fontSize: "0.72rem" }}>{result.error}</span>}
    </div>
  );
}

export default function Whales() {
  const isAdmin = useAdmin();
  useDocumentTitle("Whales");
  const [feed, setFeed] = useState<FeedRow[]>([]);
  const latestQuarter = feed.reduce<string | null>((m, r) => (r.quarter && (!m || r.quarter > m) ? r.quarter : m), null);
  const [holders, setHolders] = useState<Holder[]>([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState<Filters>({ holder_id: "", change_type: "", ticker: "" });
  const [lastSynced, setLastSynced] = useState<Date | null>(null);

  const loadFeed = (f: Filters = filters) => {
    setLoading(true);
    const params: Record<string, string | number> = { limit: 100 };
    if (f.holder_id !== "")   params.holder_id = f.holder_id;
    if (f.change_type)        params.change_type = f.change_type;
    if (f.ticker)             params.ticker = f.ticker.toUpperCase();
    getWhaleFeed(params)
      .then((r) => { setFeed(r.data as FeedRow[]); setLastSynced(new Date()); })
      .catch(() => setFeed([]))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    getWhales().then((r) => setHolders(r.data as Holder[])).catch(() => {});
    loadFeed();
  }, []);

  const set = <K extends keyof Filters>(k: K, v: Filters[K]) => {
    const next = { ...filters, [k]: v };
    setFilters(next);
    loadFeed(next);
  };

  const activeFilers = [filters.holder_id, filters.change_type, filters.ticker].filter(Boolean).length;
  const clearAll = () => {
    const next: Filters = { holder_id: "", change_type: "", ticker: "" };
    setFilters(next);
    loadFeed(next);
  };

  // Top movers: tickers with new or increased positions
  const topMovers = [...new Set(
    feed.filter((p) => ["new", "increased"].includes(p.change_type)).map((p) => p.ticker)
  )].slice(0, 8);

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Whale Tracker</h1>
          <p style={{ color: C.textMuted, fontSize: "0.85rem", marginTop: 4 }}>
            Institutional & billionaire 13F filings — what the big money is moving.
          </p>
          {latestQuarter && (
            <p style={{ color: C.textMuted, fontSize: 12, margin: "4px 0 0" }}>
              Data through <strong style={{ color: C.textSoft }}>{latestQuarter}</strong> — 13F filings are quarterly and due 45 days after quarter end, so holdings are always at least that stale.
            </p>
          )}
          {lastSynced && (
            <p style={{ color: C.divider, fontSize: 11, margin: "2px 0 0" }}>
              Last loaded: {lastSynced.toLocaleTimeString()}
            </p>
          )}
        </div>
        {isAdmin && (
          <SyncButton onRefresh={() => { getWhales().then((r) => setHolders(r.data)).catch(() => {}); loadFeed(); }} />
        )}
      </div>

      {/* Holder cards row */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "0.75rem", marginBottom: "1.5rem" }}>
        {holders.map((h) => (
          <div
            key={h.id}
            style={{
              background: filters.holder_id == h.id ? "var(--c-accentBg)" : C.surface,
              border: `1px solid ${filters.holder_id == h.id ? C.accentSolid : C.surfaceAlt}`,
              borderRadius: 8, overflow: "hidden",
            }}
          >
            <button
              onClick={() => set("holder_id", filters.holder_id == h.id ? "" : h.id)}
              style={{ background: "none", border: "none", padding: "0.875rem", cursor: "pointer", textAlign: "left", width: "100%" }}
            >
              <div style={{ color: C.text, fontWeight: 600, fontSize: "0.85rem", marginBottom: 4 }}>
                {h.name.split(" / ")[0]}
              </div>
              <div style={{ color: C.textMuted, fontSize: "0.75rem", marginBottom: 4 }}>
                {h.name.split(" / ")[1] || ""}
              </div>
              <div style={{ color: C.accent, fontSize: "0.72rem" }}>
                {h.position_count} position{h.position_count !== 1 ? "s" : ""}
              </div>
            </button>
            <Link
              to={`/whale/${h.id}`}
              style={{
                display: "block", borderTop: "1px solid var(--c-surfaceAlt)",
                color: C.textMuted, fontSize: "0.72rem", textDecoration: "none",
                padding: "0.4rem 0.875rem",
              }}
            >
              View profile →
            </Link>
          </div>
        ))}
      </div>

      {/* Conviction buys banner */}
      {topMovers.length > 0 && !filters.holder_id && (
        <div style={{ background: "var(--c-accentBg)", border: "1px solid var(--c-accentBg)", borderRadius: 8, padding: "0.875rem 1rem", marginBottom: "1.25rem", display: "flex", gap: "0.75rem", alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ color: C.textSoft, fontSize: "0.78rem", fontWeight: 600 }}>Whale conviction buys:</span>
          {topMovers.map((t) => (
            <Link key={t} to={`/ticker/${t}`} style={{ color: C.accent, fontWeight: 700, fontSize: "0.85rem", textDecoration: "none", background: "var(--c-accentBg)", padding: "2px 10px", borderRadius: 4 }}>
              {t}
            </Link>
          ))}
        </div>
      )}

      {/* Filter bar */}
      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "flex-end", marginBottom: "1.25rem", padding: "0.75rem 1rem", background: C.surface, borderRadius: 8, border: "1px solid var(--c-surfaceAlt)" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <label style={{ color: C.textDim, fontSize: "0.7rem" }}>Move type</label>
          <select value={filters.change_type} onChange={(e) => set("change_type", e.target.value as ChangeType | "")} style={inputStyle}>
            <option value="">All moves</option>
            <option value="new">New positions</option>
            <option value="increased">Increased</option>
            <option value="decreased">Decreased</option>
            <option value="closed">Closed</option>
            <option value="stable">Stable</option>
          </select>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <label style={{ color: C.textDim, fontSize: "0.7rem" }}>Ticker</label>
          <input
            style={{ ...inputStyle, width: 100, textTransform: "uppercase" }}
            value={filters.ticker}
            onChange={(e) => set("ticker", e.target.value)}
            placeholder="e.g. NVDA"
          />
        </div>
        {activeFilers > 0 && (
          <button onClick={clearAll} style={{ background: "none", color: C.textMuted, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, padding: "0.4rem 0.75rem", cursor: "pointer", fontSize: "0.8rem", alignSelf: "flex-end" }}>
            Clear ({activeFilers})
          </button>
        )}
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "flex-end" }}>
          {feed.length > 0 && (
            <button onClick={() => exportWhalesCSV(feed)}
              style={{ background: C.surfaceAlt, color: C.textSoft, border: "1px solid var(--c-divider)", borderRadius: 6, padding: "6px 12px", fontSize: 13, cursor: "pointer" }}>
              ↓ CSV
            </button>
          )}
          <span style={{ color: C.textDim, fontSize: "0.75rem" }}>
            {feed.length} position{feed.length !== 1 ? "s" : ""}
          </span>
        </div>
      </div>

      {/* Feed */}
      {loading ? (
        <p style={{ color: C.textMuted }}>Loading...</p>
      ) : feed.length === 0 ? (
        <p style={{ color: C.textDim }}>No positions match these filters.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
          {feed.map((p) => (
            <div key={p.id} style={{
              background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8,
              padding: "0.875rem 1rem",
              display: "flex", justifyContent: "space-between", alignItems: "center", gap: "1rem",
              flexWrap: "wrap",
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
                <Link to={`/ticker/${p.ticker}`} style={{ color: C.accent, fontWeight: 700, fontSize: "1rem", textDecoration: "none", minWidth: 56 }}>
                  {p.ticker}
                </Link>
                <ChangeBadge type={p.change_type} />
                <WatchlistButton ticker={p.ticker} />
                <div>
                  <div style={{ color: C.textSoft, fontSize: "0.82rem" }}>{p.company_name}</div>
                  <div style={{ color: C.textDim, fontSize: "0.75rem" }}>{p.holder?.name?.split(" / ")[0]}</div>
                </div>
              </div>
              <div style={{ textAlign: "right", flexShrink: 0 }}>
                <div style={{ color: C.text, fontWeight: 600 }}>{p.value_fmt}</div>
                <div style={{ color: C.textMuted, fontSize: "0.75rem" }}>{fmtShares(p.shares)} shares</div>
                <div style={{ color: C.textDim, fontSize: "0.7rem" }}>{p.quarter}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
