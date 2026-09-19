import { safeHref } from "../lib/safeUrl";
import { fmtDate } from "../lib/format";
import { C } from "../lib/theme";
import useDocumentTitle from "../hooks/useDocumentTitle";
import useAdmin from "../hooks/useAdmin";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getFedOfficials, getFedTrades, seedFed } from "../lib/api";
import { exportCSV } from "../lib/csv";
import WatchlistButton from "../components/WatchlistButton";
import SkeletonCard from "../components/SkeletonCard";

type FedRole = "board" | "regional_president";

interface Official {
  id: number;
  name: string;
  title: string;
  role: FedRole;
  party?: string | null;
  is_fomc_voter?: boolean;
  term_expires?: string | null;
  district?: string | null;
  trade_count: number;
  bio?: string | null;
  disclosure_url?: string | null;
}

interface FedTrade {
  id: number;
  trade_date: string;
  official_name: string;
  official_title: string;
  ticker: string;
  asset_name?: string | null;
  transaction_type: "purchase" | "sale" | "other" | string;
  amount_range?: string | null;
  disclosure_date?: string | null;
  source?: string | null;
  source_url?: string | null;
}

const PARTY_COLOR: Record<string, string> = { D: "#3b82f6", R: C.dangerSolid };
const TYPE_COLOR: Record<string, string>  = { purchase: C.success, sale: C.danger, other: C.textSoft };


function exportFedCSV(rows: FedTrade[]) {
  exportCSV(
    ["trade_date","official_name","official_title","ticker","transaction_type","amount_range","disclosure_date","source"],
    rows.map((r) => [r.trade_date, r.official_name, r.official_title, r.ticker, r.transaction_type, r.amount_range ?? "", r.disclosure_date ?? "", r.source ?? ""]),
    "insidertrack-fed-trades",
  );
}
const ROLE_LABEL: Record<string, string> = {
  board: "Board of Governors",
  regional: "Regional Presidents",
  regional_president: "Regional President",
};

function OfficialCard({ official, isSelected, onClick }: { official: Official; isSelected: boolean; onClick: () => void }) {
  const partyColor = (official.party && PARTY_COLOR[official.party]) || C.dividerStrong;
  return (
    <div
      onClick={onClick}
      style={{
        background: isSelected ? "var(--c-accentBg)" : C.surface,
        border: `1px solid ${isSelected ? C.accent : C.surfaceAlt}`,
        borderLeft: `3px solid ${official.is_fomc_voter ? C.accent : C.divider}`,
        borderRadius: 10,
        padding: "14px 16px",
        cursor: "pointer",
        transition: "border-color 0.15s, background 0.15s",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
        <div style={{ color: C.textBright, fontWeight: 700, fontSize: 14, lineHeight: 1.3 }}>{official.name}</div>
        <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
          {official.is_fomc_voter && (
            <span style={{ background: "rgba(56,189,248,0.12)", color: C.accent, fontSize: 10, fontWeight: 700, padding: "2px 6px", borderRadius: 4 }}>
              VOTER
            </span>
          )}
          {official.party && (
            <span style={{ color: partyColor, fontSize: 10, fontWeight: 700, padding: "2px 6px", borderRadius: 4, border: `1px solid ${partyColor}44` }}>
              {official.party}
            </span>
          )}
        </div>
      </div>
      <div style={{ color: C.textMuted, fontSize: 12, marginTop: 4, lineHeight: 1.4 }}>{official.title}</div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8, alignItems: "center" }}>
        <span style={{ color: C.divider, fontSize: 11 }}>
          {official.role === "board" ? `Expires ${official.term_expires}` : official.district + " District"}
        </span>
        <span style={{ color: official.trade_count > 0 ? C.textSoft : C.divider, fontSize: 11, fontWeight: 600 }}>
          {official.trade_count} trade{official.trade_count !== 1 ? "s" : ""}
        </span>
      </div>
    </div>
  );
}

function TradeRow({ trade }: { trade: FedTrade }) {
  const typeColor = TYPE_COLOR[trade.transaction_type] || C.textSoft;
  return (
    <tr style={{ borderBottom: "1px solid var(--c-surfaceAlt)" }}>
      <td style={{ padding: "9px 12px", color: C.textMuted, whiteSpace: "nowrap", fontSize: 12 }}>{fmtDate(trade.trade_date)}</td>
      <td style={{ padding: "9px 12px" }}>
        <div style={{ fontSize: 12, color: C.textSoft, lineHeight: 1.3 }}>
          <div style={{ color: C.textBright, fontWeight: 600 }}>{trade.official_name}</div>
          <div style={{ color: C.dividerStrong, fontSize: 11 }}>{trade.official_title}</div>
        </div>
      </td>
      <td style={{ padding: "9px 12px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <Link to={`/ticker/${trade.ticker}`} style={{ color: C.accent, fontWeight: 700, textDecoration: "none", fontSize: 13 }}>{trade.ticker}</Link>
          <WatchlistButton ticker={trade.ticker} />
        </div>
        {trade.asset_name && <div style={{ color: C.dividerStrong, fontSize: 11, marginTop: 2 }}>{trade.asset_name}</div>}
      </td>
      <td style={{ padding: "9px 12px" }}>
        <span style={{
          background: `rgba(${trade.transaction_type === "purchase" ? "74,222,128" : "248,113,113"},0.1)`,
          color: typeColor,
          border: `1px solid ${typeColor}33`,
          borderRadius: 4, padding: "2px 8px", fontSize: 11, fontWeight: 600, textTransform: "uppercase",
        }}>
          {trade.transaction_type}
        </span>
      </td>
      <td style={{ padding: "9px 12px", color: C.textSoft, fontSize: 12 }}>{trade.amount_range || "—"}</td>
      <td style={{ padding: "9px 12px", color: C.dividerStrong, fontSize: 11 }}>
        {trade.disclosure_date || "—"}
      </td>
      <td style={{ padding: "9px 12px" }}>
        {trade.source_url ? (
          <a href={safeHref(trade.source_url)} target="_blank" rel="noopener noreferrer"
            style={{ color: C.accent, fontSize: 11, textDecoration: "none" }}>OGE ↗</a>
        ) : (
          <span style={{ color: C.divider, fontSize: 11 }}>—</span>
        )}
      </td>
    </tr>
  );
}

export default function Fed() {
  const isAdmin = useAdmin();
  useDocumentTitle("Fed Officials");
  const [officials, setOfficials] = useState<Official[]>([]);
  const [trades, setTrades] = useState<FedTrade[]>([]);
  const [loading, setLoading] = useState(true);
  const [tradesLoading, setTradesLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [filter, setFilter] = useState<{ ticker: string; type: string }>({ ticker: "", type: "" });
  const [msg, setMsg] = useState("");
  const [activeTab, setActiveTab] = useState<"board" | "regional">("board");

  useEffect(() => {
    getFedOfficials()
      .then((r) => setOfficials(r.data as Official[]))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    setTradesLoading(true);
    const params: Record<string, string | number> = {};
    if (selectedId) params.official_id = selectedId;
    if (filter.ticker) params.ticker = filter.ticker.toUpperCase();
    if (filter.type) params.transaction_type = filter.type;
    getFedTrades(params)
      .then((r) => {
        const d = r.data as { items?: FedTrade[] } | FedTrade[] | undefined;
        setTrades(Array.isArray(d) ? d : d?.items ?? []);
      })
      .catch(() => {})
      .finally(() => setTradesLoading(false));
  }, [selectedId, filter.ticker, filter.type]);

  const handleSync = async () => {
    setMsg("Refreshing roster…");
    try {
      await seedFed();
      const r = await getFedOfficials();
      setOfficials(r.data as Official[]);
      setMsg("Roster refreshed.");
    } catch {
      setMsg("Error — check backend logs.");
    }
  };

  const board = officials.filter((o) => o.role === "board");
  const regional = officials.filter((o) => o.role === "regional_president");
  const displayed = activeTab === "board" ? board : regional;
  const selectedOfficial = officials.find((o) => o.id === selectedId);

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto" }}>
      <style>{`
        @media (max-width: 700px) {
          .fed-grid { grid-template-columns: 1fr !important; }
        }
      `}</style>
      {/* Header */}
      <div className="page-head">
        <div>
          <h1>Federal Reserve Officials</h1>
          <p style={{ color: C.dividerStrong, margin: 0, fontSize: 13 }}>
            Who sets rates — the FOMC roster, with links to each official's annual disclosure.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <a
            href="https://www.federalreserve.gov/aboutthefed/disclosures.htm"
            target="_blank" rel="noopener noreferrer"
            style={{ color: C.textMuted, fontSize: 12, textDecoration: "none", border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, padding: "6px 12px" }}
          >
            Fed Disclosures ↗
          </a>
          {isAdmin && (
            <button
              onClick={handleSync}
              data-tip="Re-applies the built-in roster (activates new members, retires departed ones)."
              style={{ background: "rgba(56,189,248,0.1)", color: C.accent, border: "1px solid rgba(56,189,248,0.3)", borderRadius: 6, padding: "6px 14px", fontSize: 12, cursor: "pointer" }}
            >
              ↻ Refresh roster
            </button>
          )}
        </div>
      </div>

      {msg && (
        <div style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8, padding: "10px 14px", marginBottom: 16, color: C.textSoft, fontSize: 13 }}>
          {msg}
        </div>
      )}

      {/* Info banner */}
      <div style={{ background: "rgba(56,189,248,0.05)", border: "1px solid rgba(56,189,248,0.15)", borderRadius: 8, padding: "10px 16px", marginBottom: 20, fontSize: 12, color: C.textMuted, lineHeight: 1.6 }}>
        <span style={{ color: C.accent, fontWeight: 600 }}>What to expect here: </span>
        Since the 2022 investment rules (a response to the 2021 trading scandal), Fed governors and reserve-bank presidents may not
        hold individual stocks, bonds or crypto, must pre-clear trades and give 45-day notice. So this page is a <em>roster</em>, not a trade feed:
        an empty transactions list is the normal, compliant state. Annual disclosures (Form 278) are published as PDFs.
        {" "}<a href="https://www.federalreserve.gov/aboutthefed/disclosures.htm" target="_blank" rel="noopener noreferrer" style={{ color: C.accent }}>Official disclosures ↗</a>
      </div>

      <div className="fed-grid" style={{ display: "grid", gridTemplateColumns: "clamp(220px, 28%, 300px) 1fr", gap: 20, alignItems: "start" }}>
        {/* Left: officials list */}
        <div>
          {/* Tabs */}
          <div style={{ display: "flex", gap: 4, marginBottom: 12 }}>
            {([{ key: "board", label: `Board (${board.length})` }, { key: "regional", label: `Regional (${regional.length})` }] as const).map(({ key, label }) => (
              <button key={key} onClick={() => { setActiveTab(key); setSelectedId(null); }}
                style={{
                  flex: 1, padding: "7px 0", fontSize: 12, fontWeight: activeTab === key ? 600 : 400,
                  background: activeTab === key ? "rgba(56,189,248,0.1)" : "transparent",
                  color: activeTab === key ? C.accent : C.textMuted,
                  border: `1px solid ${activeTab === key ? "rgba(56,189,248,0.3)" : C.surfaceAlt}`,
                  borderRadius: 6, cursor: "pointer",
                }}>
                {label}
              </button>
            ))}
          </div>

          {/* "All" option */}
          <div
            onClick={() => setSelectedId(null)}
            style={{
              padding: "10px 14px", marginBottom: 8, borderRadius: 8, cursor: "pointer",
              background: !selectedId ? "rgba(56,189,248,0.08)" : "transparent",
              border: `1px solid ${!selectedId ? "rgba(56,189,248,0.3)" : C.surfaceAlt}`,
              color: !selectedId ? C.accent : C.textMuted,
              fontSize: 13, fontWeight: !selectedId ? 600 : 400,
            }}
          >
            All {ROLE_LABEL[activeTab] || "Officials"} — {displayed.length} members
          </div>

          {loading ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {[...Array(5)].map((_, i) => <SkeletonCard key={i} lines={3} height={90} />)}
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {displayed.map((o) => (
                <OfficialCard
                  key={o.id}
                  official={o}
                  isSelected={selectedId === o.id}
                  onClick={() => setSelectedId(selectedId === o.id ? null : o.id)}
                />
              ))}
            </div>
          )}
        </div>

        {/* Right: trades feed */}
        <div>
          {/* Selected official bio */}
          {selectedOfficial && selectedOfficial.bio && (
            <div style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 10, padding: "16px 18px", marginBottom: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
                <div>
                  <div style={{ color: C.textBright, fontWeight: 700, fontSize: 15 }}>{selectedOfficial.name}</div>
                  <div style={{ color: C.textMuted, fontSize: 12 }}>{selectedOfficial.title}</div>
                </div>
                {selectedOfficial.disclosure_url && (
                  <a href={safeHref(selectedOfficial.disclosure_url)} target="_blank" rel="noopener noreferrer"
                    style={{ color: C.accent, fontSize: 12, textDecoration: "none", flexShrink: 0 }}>
                    Disclosures ↗
                  </a>
                )}
              </div>
              <p style={{ color: C.textSoft, fontSize: 13, margin: 0, lineHeight: 1.6 }}>{selectedOfficial.bio}</p>
            </div>
          )}

          {/* Filters */}
          <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap" }}>
            <input
              value={filter.ticker}
              onChange={(e) => setFilter((f) => ({ ...f, ticker: e.target.value.toUpperCase() }))}
              placeholder="Filter ticker…"
              style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, color: C.textBright, padding: "6px 12px", fontSize: 13, width: 140 }}
            />
            <select value={filter.type}
              onChange={(e) => setFilter((f) => ({ ...f, type: e.target.value }))}
              style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, color: C.textSoft, padding: "6px 12px", fontSize: 13 }}>
              <option value="">All types</option>
              <option value="purchase">Purchase</option>
              <option value="sale">Sale</option>
            </select>
            {(filter.ticker || filter.type) && (
              <button onClick={() => setFilter({ ticker: "", type: "" })}
                style={{ background: "none", color: C.textMuted, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, padding: "6px 12px", fontSize: 13, cursor: "pointer" }}>
                Clear
              </button>
            )}
            {trades.length > 0 && (
              <button onClick={() => exportFedCSV(trades)}
                style={{ background: C.surfaceAlt, color: C.textSoft, border: "1px solid var(--c-divider)", borderRadius: 6, padding: "6px 12px", fontSize: 13, cursor: "pointer", marginLeft: "auto" }}>
                ↓ CSV
              </button>
            )}
          </div>

          {tradesLoading ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {[...Array(4)].map((_, i) => <SkeletonCard key={i} lines={2} height={52} />)}
            </div>
          ) : trades.length === 0 ? (
            <div style={{ color: C.dividerStrong, textAlign: "center", padding: "60px 24px", background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 12 }}>
              <div style={{ fontSize: 32, marginBottom: 12 }}>📋</div>
              <div style={{ fontSize: 15, fontWeight: 600, color: C.textMuted, marginBottom: 8 }}>No individual-stock transactions on record</div>
              <div style={{ fontSize: 13, color: C.textMuted, maxWidth: 360, margin: "0 auto", lineHeight: 1.6 }}>
                That is what the rules require. If a disclosed transaction ever appears in a Form 278 or 278-T,
                it can be entered here; until then, use the roster and the official PDF disclosures.
              </div>
            </div>
          ) : (
            <div style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 12, overflowX: "auto", WebkitOverflowScrolling: "touch" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid var(--c-surfaceAlt)" }}>
                    {["Trade Date", "Official", "Ticker", "Type", "Amount", "Disclosed", "Source"].map((h) => (
                      <th key={h} style={{ padding: "10px 12px", color: C.dividerStrong, fontWeight: 600, fontSize: 11, textAlign: "left", whiteSpace: "nowrap" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {trades.map((t) => <TradeRow key={t.id} trade={t} />)}
                </tbody>
              </table>
            </div>
          )}

          <div style={{ marginTop: 12, color: C.divider, fontSize: 11, lineHeight: 1.6 }}>
            Roster maintained by hand · Board of Governors file annual Form 278 with the{" "}
            <a href="https://www.oge.gov/web/oge.nsf/Public%20Financial%20Disclosure" target="_blank" rel="noopener noreferrer" style={{ color: C.dividerStrong }}>Office of Government Ethics ↗</a>{" "}
            · Reserve-bank presidents publish theirs on their bank's site
          </div>
        </div>
      </div>
    </div>
  );
}
