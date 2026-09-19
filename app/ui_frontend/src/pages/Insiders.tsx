import { useEffect, useState } from "react";
import { fmtDate } from "../lib/format";
import { Link } from "react-router-dom";
import { isAxiosError } from "axios";
import { getInsiderTransactions, getInsiderSummary, syncInsiders } from "../lib/api";
import { exportCSV } from "../lib/csv";
import { card , C} from "../lib/theme";
import useDocumentTitle from "../hooks/useDocumentTitle";
import useAdmin from "../hooks/useAdmin";
import SkeletonCard from "../components/SkeletonCard";
import ClusterBuys from "../components/ClusterBuys";

type TxType = "buy" | "sell" | "other";

const TYPE_STYLE: Record<TxType, { color: string; bg: string; label: string }> = {
  buy:   { color: C.success, bg: C.successBg, label: "BUY" },
  sell:  { color: C.danger, bg: C.dangerBg, label: "SELL" },
  other: { color: C.textSoft, bg: C.bgSunken, label: "OTHER" },
};

interface InsiderRow {
  id: number;
  ticker: string;
  insider_name: string;
  insider_title: string | null;
  transaction_type: TxType | string;
  shares: number | null;
  price: number | null;
  value: number | null;
  transaction_date: string;
}

interface TickerSummary {
  ticker: string;
  buys: number;
  sells: number;
}

interface SyncResult {
  stored?: number;
  skipped?: number;
  tickers?: number;
  error?: string;
}

interface InsiderFilter {
  ticker: string;
  transaction_type: string;
}

function fmtVal(v: number | null | undefined): string {
  if (!v) return "—";
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(0)}K`;
  return `$${v}`;
}

function fmtShares(n: number | null | undefined): string {
  if (!n) return "—";
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}K`;
  return n.toLocaleString();
}


function exportInsidersCSV(rows: InsiderRow[]) {
  exportCSV(
    ["ticker", "insider_name", "insider_title", "transaction_type", "shares", "price", "value", "transaction_date"],
    rows.map((r) => [r.ticker, r.insider_name, r.insider_title, r.transaction_type, r.shares ?? "", r.price ?? "", r.value ?? "", r.transaction_date]),
    "insidertrack-insiders",
  );
}

function SyncButton({ onDone }: { onDone: () => void }) {
  const [syncing, setSyncing] = useState(false);
  const [result, setResult] = useState<SyncResult | null>(null);
  const run = async () => {
    setSyncing(true); setResult(null);
    try {
      const r = await syncInsiders();
      setResult(r.data as SyncResult);
      onDone();
    } catch (e) {
      const detail = isAxiosError(e) ? (e.response?.data as { detail?: string } | undefined)?.detail : null;
      setResult({ error: detail || "Sync failed" });
    } finally { setSyncing(false); }
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
      <button onClick={run} disabled={syncing}
        style={{ background: syncing ? C.surfaceAlt : C.accentSolid, color: "#fff", border: "none", borderRadius: 6, padding: "7px 14px", fontSize: 13, cursor: syncing ? "not-allowed" : "pointer" }}>
        {syncing ? "Syncing EDGAR…" : "↻ Sync Form 4 Filings"}
      </button>
      {result && !result.error && (
        <span style={{ color: C.success, fontSize: 11 }}>
          Syncing {result.tickers} tickers in the background — outcome in <Link to="/admin" style={{ color: C.accent }}>Admin → Data sources</Link>
        </span>
      )}
      {result?.error && <span style={{ color: C.danger, fontSize: 11 }}>{result.error}</span>}
    </div>
  );
}

export default function Insiders() {
  const isAdmin = useAdmin();
  useDocumentTitle("Corporate Insiders");
  const [rows, setRows] = useState<InsiderRow[]>([]);
  const [summary, setSummary] = useState<TickerSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<InsiderFilter>({ ticker: "", transaction_type: "" });
  const [autoSynced, setAutoSynced] = useState(false);
  const [lastSynced, setLastSynced] = useState<Date | null>(null);

  const load = (f: InsiderFilter = filter) => {
    setLoading(true);
    const params: Record<string, string> = {};
    if (f.ticker) params.ticker = f.ticker.toUpperCase();
    if (f.transaction_type) params.transaction_type = f.transaction_type;
    Promise.all([getInsiderTransactions(params), getInsiderSummary()])
      .then(([t, s]) => {
        const tdata = t.data as { items?: InsiderRow[] } | InsiderRow[] | undefined;
        const items = Array.isArray(tdata) ? tdata : (tdata?.items ?? []);
        setRows(items);
        setSummary(s.data as TickerSummary[]);
        setLastSynced(new Date());
      })
      .finally(() => setLoading(false));
  };

  // Auto-filter on change
  useEffect(() => { load(filter); }, [filter.ticker, filter.transaction_type]);

  // Auto-sync on first load if DB is empty and user has admin access
  useEffect(() => {
    if (!loading && rows.length === 0 && !autoSynced && isAdmin) {
      setAutoSynced(true);
      syncInsiders()
        .then(() => load())
        .catch(() => {});
    }
  }, [loading, rows.length]);

  return (
    <div style={{ maxWidth: 1000, margin: "0 auto" }}>
      <div className="page-head">
        <div>
          <h1>Corporate Insiders</h1>
          <p style={{ color: C.textDim, margin: 0, fontSize: 13 }}>
            SEC Form 4 filings — officers, directors, and 10%+ owners trading their own company's stock.
          </p>
          {lastSynced && (
            <p style={{ color: C.textDim, fontSize: 11, margin: "2px 0 0" }}>
              Last loaded: {lastSynced.toLocaleTimeString()}
            </p>
          )}
        </div>
        {isAdmin && <SyncButton onDone={() => load()} />}
      </div>

      <ClusterBuys />

      {/* Summary chips */}
      {summary.length > 0 && (
        <div style={{ ...card, padding: "12px 16px", marginBottom: 16, display: "flex", gap: 8, flexWrap: "wrap" }}>
          {summary.slice(0, 14).map((s) => (
            <Link key={s.ticker} to={`/ticker/${s.ticker}`}
              style={{ textDecoration: "none", background: C.bg, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, padding: "4px 10px", display: "flex", gap: 6, alignItems: "center" }}>
              <span style={{ color: C.accent, fontWeight: 700, fontSize: 12 }}>{s.ticker}</span>
              <span style={{ color: C.success, fontSize: 11 }}>{s.buys}B</span>
              <span style={{ color: C.danger, fontSize: 11 }}>{s.sells}S</span>
            </Link>
          ))}
        </div>
      )}

      {/* Filters — reactive on change */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
        {rows.length > 0 && (
          <button onClick={() => exportInsidersCSV(rows)}
            style={{ background: C.surfaceAlt, color: C.textSoft, border: "1px solid var(--c-divider)", borderRadius: 6, padding: "6px 12px", fontSize: 13, cursor: "pointer", marginLeft: "auto" }}>
            ↓ CSV
          </button>
        )}
        <input placeholder="Filter ticker…" value={filter.ticker}
          onChange={(e) => setFilter((f) => ({ ...f, ticker: e.target.value.toUpperCase() }))}
          style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, color: C.textBright, padding: "6px 12px", fontSize: 13, width: 130 }} />
        <select value={filter.transaction_type}
          onChange={(e) => setFilter((f) => ({ ...f, transaction_type: e.target.value }))}
          style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, color: C.textSoft, padding: "6px 12px", fontSize: 13 }}>
          <option value="">All transactions</option>
          <option value="buy">Buys only</option>
          <option value="sell">Sells only</option>
          <option value="other">Other (grants/exercises)</option>
        </select>
        {(filter.ticker || filter.transaction_type) && (
          <button onClick={() => setFilter({ ticker: "", transaction_type: "" })}
            style={{ background: "none", color: C.textMuted, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, padding: "6px 12px", fontSize: 13, cursor: "pointer" }}>
            Clear
          </button>
        )}
      </div>

      {loading ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {[...Array(5)].map((_, i) => <SkeletonCard key={i} lines={2} height={50} />)}
        </div>
      ) : rows.length === 0 ? (
        <div style={{ color: C.textDim, textAlign: "center", padding: "60px 0" }}>
          {isAdmin
            ? "No Form 4 data yet — pulling from SEC EDGAR automatically…"
            : "No Form 4 data yet — use the Sync button (admin access required)."}
        </div>
      ) : (
        <div style={{ ...card, overflowX: "auto", WebkitOverflowScrolling: "touch" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--c-surfaceAlt)" }}>
                {["Ticker", "Insider", "Role", "Type", "Shares", "Price", "Value", "Date"].map((h) => (
                  <th key={h} style={{ padding: "10px 12px", color: C.textDim, fontWeight: 600, fontSize: 11, textAlign: "left" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const ts = (TYPE_STYLE as Record<string, typeof TYPE_STYLE.other>)[r.transaction_type] || TYPE_STYLE.other;
                return (
                  <tr key={r.id} style={{ borderBottom: "1px solid var(--c-surfaceAlt)" }}>
                    <td style={{ padding: "9px 12px" }}>
                      <Link to={`/ticker/${r.ticker}`} style={{ color: C.accent, fontWeight: 700, textDecoration: "none" }}>{r.ticker}</Link>
                    </td>
                    <td style={{ padding: "9px 12px", color: C.text }}>{r.insider_name}</td>
                    <td style={{ padding: "9px 12px", color: C.textMuted, fontSize: 12 }}>{r.insider_title}</td>
                    <td style={{ padding: "9px 12px" }}>
                      <span style={{ background: ts.bg, color: ts.color, fontSize: 11, fontWeight: 700, padding: "2px 7px", borderRadius: 4 }}>
                        {ts.label}
                      </span>
                    </td>
                    <td style={{ padding: "9px 12px", color: C.textSoft }}>{fmtShares(r.shares)}</td>
                    <td style={{ padding: "9px 12px", color: C.textSoft }}>{r.price ? `$${r.price.toFixed(2)}` : "—"}</td>
                    <td style={{ padding: "9px 12px", color: C.text, fontWeight: 600 }}>{fmtVal(r.value)}</td>
                    <td style={{ padding: "9px 12px", color: C.textMuted, whiteSpace: "nowrap" }}>{fmtDate(r.transaction_date)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div style={{ marginTop: 14, color: C.textDim, fontSize: 11, lineHeight: 1.6 }}>
        Form 4 must be filed within 2 business days of an insider transaction · Codes: P = open-market purchase, S = sale.
      </div>
    </div>
  );
}
