import { C } from "../lib/theme";
import useDocumentTitle from "../hooks/useDocumentTitle";
import { useEffect, useState } from "react";
import { getTrades, getPoliticians } from "../lib/api";
import { exportCSV } from "../lib/csv";
import type { Trade, Politician } from "../types/api";
import TradeCard from "../components/TradeCard";

interface Filters {
  tracked_only: boolean;
  transaction_type: string;
  politician_id: string;
  ticker: string;
  since: string;
  until: string;
  risk_level: string;
  sort_by: string;
}

function exportFeedCSV(trades: Trade[]) {
  exportCSV(
    ["ticker", "transaction_type", "amount_range", "trade_date", "disclosure_date", "politician", "party", "state", "chamber"],
    trades.map((t) => [
      t.ticker,
      t.transaction_type,
      t.amount_range,
      t.trade_date,
      t.disclosure_date,
      t.politician?.name || "",
      t.politician?.party || "",
      t.politician?.state || "",
      t.politician?.chamber || "",
    ]),
    "insidertrack-trades",
  );
}

const inputStyle = {
  background: C.surface, color: C.text,
  border: "1px solid var(--c-surfaceAlt)", borderRadius: 6,
  padding: "0.4rem 0.75rem", fontSize: "0.85rem",
};

export default function Feed() {
  useDocumentTitle("Trade Feed");
  const [trades, setTrades] = useState<Trade[]>([]);
  const [politicians, setPoliticians] = useState<Politician[]>([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState<Filters>({
    tracked_only: false,
    transaction_type: "",
    politician_id: "",
    ticker: "",
    since: "",
    until: "",
    risk_level: "",
    sort_by: "trade_date",
  });
  const [filtersOpen, setFiltersOpen] = useState(window.innerWidth >= 768);

  useEffect(() => {
    getPoliticians().then((r) => setPoliticians(r.data));
  }, []);

  const [limit, setLimit] = useState(100);
  const [hasMore, setHasMore] = useState(false);

  useEffect(() => {
    setLimit(100);
    setHasMore(false);
  }, [filters]);

  useEffect(() => {
    setLoading(true);
    const params: Record<string, unknown> = { limit };
    if (filters.tracked_only) params.tracked_only = true;
    if (filters.transaction_type) params.transaction_type = filters.transaction_type;
    if (filters.politician_id) params.politician_id = filters.politician_id;
    if (filters.ticker) params.ticker = filters.ticker.toUpperCase();
    if (filters.since) params.since = filters.since;
    if (filters.until) params.until = filters.until;
    if (filters.risk_level) params.risk_level = filters.risk_level;
    if (filters.sort_by) params.sort_by = filters.sort_by;
    getTrades(params)
      .then((r) => {
        setTrades(r.data.items);
        setHasMore(r.data.has_more);
      })
      .finally(() => setLoading(false));
  }, [filters, limit]);

  const set = <K extends keyof Filters>(key: K, val: Filters[K]) =>
    setFilters((f) => ({ ...f, [key]: val }));

  const activeFilterCount = [
    filters.tracked_only,
    filters.transaction_type,
    filters.politician_id,
    filters.ticker,
    filters.since,
    filters.until,
    filters.risk_level,
  ].filter(Boolean).length;

  const clearAll = () => setFilters({ tracked_only: false, transaction_type: "", politician_id: "", ticker: "", since: "", until: "", risk_level: "", sort_by: "trade_date" });

  return (
    <div>
      <div className="page-head">
        <h1>Trade Feed</h1>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          {trades.length > 0 && (
            <button
              onClick={() => exportFeedCSV(trades)}
              style={{ background: C.surfaceAlt, color: C.textSoft, border: "1px solid var(--c-divider)", borderRadius: 6, padding: "0.3rem 0.75rem", cursor: "pointer", fontSize: "0.8rem" }}
            >
              ↓ CSV
            </button>
          )}
          {activeFilterCount > 0 && (
            <button
              onClick={clearAll}
              style={{ background: "none", color: C.textMuted, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, padding: "0.3rem 0.75rem", cursor: "pointer", fontSize: "0.8rem" }}
            >
              Clear ({activeFilterCount})
            </button>
          )}
        </div>
      </div>

      {/* Filter bar */}
      <div style={{ marginBottom: "1.5rem", background: C.surface, borderRadius: 8, border: "1px solid var(--c-surfaceAlt)" }}>
        <button
          onClick={() => setFiltersOpen(o => !o)}
          style={{ display: "flex", width: "100%", justifyContent: "space-between", alignItems: "center", padding: "0.65rem 1rem", background: "none", border: "none", cursor: "pointer", color: C.textSoft, fontSize: "0.85rem" }}
        >
          <span style={{ fontWeight: 600 }}>Filters {activeFilterCount > 0 && <span style={{ color: C.accent, fontSize: "0.75rem" }}>({activeFilterCount} active)</span>}</span>
          <span>{filtersOpen ? "▲" : "▼"}</span>
        </button>
      <div style={{ display: filtersOpen ? "flex" : "none", gap: "0.75rem", flexWrap: "wrap", alignItems: "center", padding: "0 1rem 0.75rem", borderTop: "1px solid var(--c-surfaceAlt)" }}>
        {/* Politician */}
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <label style={{ color: C.textDim, fontSize: "0.7rem" }}>Person</label>
          <select
            value={filters.politician_id}
            onChange={(e) => set("politician_id", e.target.value)}
            style={{ ...inputStyle, minWidth: 160 }}
          >
            <option value="">All people</option>
            {politicians.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>

        {/* Ticker */}
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <label style={{ color: C.textDim, fontSize: "0.7rem" }}>Ticker</label>
          <input
            placeholder="e.g. NVDA"
            value={filters.ticker}
            onChange={(e) => set("ticker", e.target.value.toUpperCase())}
            style={{ ...inputStyle, width: 90 }}
          />
        </div>

        {/* Type */}
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <label style={{ color: C.textDim, fontSize: "0.7rem" }}>Type</label>
          <select
            value={filters.transaction_type}
            onChange={(e) => set("transaction_type", e.target.value)}
            style={inputStyle}
          >
            <option value="">All types</option>
            <option value="purchase">Purchases</option>
            <option value="sale">Sales</option>
          </select>
        </div>

        {/* Date from */}
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <label style={{ color: C.textDim, fontSize: "0.7rem" }}>From date</label>
          <input
            type="date"
            value={filters.since}
            onChange={(e) => set("since", e.target.value)}
            style={{ ...inputStyle, colorScheme: "dark" }}
          />
        </div>

        {/* Date to */}
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <label style={{ color: C.textDim, fontSize: "0.7rem" }}>To date</label>
          <input
            type="date"
            value={filters.until}
            onChange={(e) => set("until", e.target.value)}
            style={{ ...inputStyle, colorScheme: "dark" }}
          />
        </div>

        {/* Risk level */}
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <label style={{ color: C.textDim, fontSize: "0.7rem" }}>Risk</label>
          <select
            value={filters.risk_level}
            onChange={(e) => set("risk_level", e.target.value)}
            style={inputStyle}
          >
            <option value="">All risk</option>
            <option value="LOW">Low</option>
            <option value="MEDIUM">Medium</option>
            <option value="HIGH">High</option>
          </select>
        </div>

        {/* Sort */}
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <label style={{ color: C.textDim, fontSize: "0.7rem" }}>Sort</label>
          <select value={filters.sort_by} onChange={(e) => set("sort_by", e.target.value)} style={inputStyle}>
            <option value="trade_date">Trade date ↓</option>
            <option value="disclosure_date">Disclosure date ↓</option>
          </select>
        </div>
        {/* Tracked only */}
        <div style={{ display: "flex", flexDirection: "column", gap: 3, marginLeft: "auto" }}>
          <label style={{ color: C.textDim, fontSize: "0.7rem" }}>&nbsp;</label>
          <label style={{ color: C.textSoft, fontSize: "0.85rem", display: "flex", alignItems: "center", gap: "0.4rem", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={filters.tracked_only}
              onChange={(e) => set("tracked_only", e.target.checked)}
            />
            Tracked only
          </label>
        </div>
      </div>
      </div>

      {/* Results */}
      {loading ? (
        <p style={{ color: C.textMuted }}>Loading trades...</p>
      ) : trades.length === 0 ? (
        <div style={{ textAlign: "center", color: C.textDim, paddingTop: "3rem" }}>
          <p>No trades match these filters.</p>
          {activeFilterCount > 0 && (
            <button onClick={clearAll} style={{ marginTop: "0.75rem", background: "none", color: C.textMuted, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, padding: "0.35rem 1rem", cursor: "pointer", fontSize: "0.85rem" }}>
              Clear filters
            </button>
          )}
        </div>
      ) : (
        <>
          <p style={{ color: C.textDim, fontSize: "0.78rem", marginBottom: "0.75rem" }}>
            {trades.length} trade{trades.length !== 1 ? "s" : ""}
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            {trades.map((t) => <TradeCard key={t.id} trade={t} />)}
          </div>
          {hasMore && (
            <div style={{ textAlign: "center", marginTop: "1.5rem" }}>
              <button
                onClick={() => setLimit((l) => l + 100)}
                disabled={loading}
                style={{ background: C.surfaceAlt, color: C.textSoft, border: "1px solid var(--c-divider)", borderRadius: 6, padding: "0.5rem 1.5rem", cursor: "pointer", fontSize: "0.85rem" }}
              >
                {loading ? "Loading…" : "Load 100 more"}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
