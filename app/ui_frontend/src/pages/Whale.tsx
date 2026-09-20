import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useParams, Link } from "react-router-dom";
import { getWhaleDetail } from "../lib/api";
import { card , C} from "../lib/theme";
import useDocumentTitle from "../hooks/useDocumentTitle";
import HolderRecord from "../components/HolderRecord";

type ChangeType = "new" | "increased" | "decreased" | "closed" | "stable";

const CHANGE_STYLE: Record<ChangeType, { color: string; label: string }> = {
  new:       { color: C.success, label: "NEW" },
  increased: { color: "#34d399", label: "↑ ADD" },
  decreased: { color: C.warning, label: "↓ TRIM" },
  closed:    { color: C.danger, label: "✕ CLOSED" },
  stable:    { color: C.textMuted, label: "— HOLD" },
};

const CHANGE_TYPES: ChangeType[] = ["new", "increased", "decreased", "closed", "stable"];

function styleFor(t: string | undefined): { color: string; label: string } | undefined {
  return (CHANGE_STYLE as Record<string, { color: string; label: string }>)[t ?? ""];
}

interface Holding {
  ticker: string;
  company_name: string;
  value_fmt: string;
  weight_pct: number;
  change_type: ChangeType | string;
}

interface WhaleDetail {
  holder: { name: string; holder_type: string; cik: string };
  summary: { position_count: number; total_value_fmt: string; latest_quarter: string | null; change_breakdown?: Partial<Record<ChangeType, number>> };
  conviction_buys: Holding[];
  top_holdings: Holding[];
  all_holdings: Holding[];
}

interface StatProps {
  label: string;
  value: ReactNode;
  color?: string;
}

function Stat({ label, value, color }: StatProps) {
  return (
    <div style={{ ...card, padding: "14px 16px", flex: 1, minWidth: 130 }}>
      <div style={{ color: C.textDim, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.04em" }}>{label}</div>
      <div style={{ color: color || C.textBright, fontSize: 20, fontWeight: 700, marginTop: 4 }}>{value}</div>
    </div>
  );
}

export default function Whale() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<WhaleDetail | null>(null);
  useDocumentTitle(data?.holder?.name ?? "Whale");
  const [loading, setLoading] = useState(true);
  const [showAll, setShowAll] = useState(false);
  const [tickerFilter, setTickerFilter] = useState("");
  const [changeFilter, setChangeFilter] = useState<ChangeType | "">("");

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    getWhaleDetail(Number(id))
      .then((r) => setData(r.data as WhaleDetail))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div style={{ color: C.textDim, textAlign: "center", padding: "60px 0" }}>Loading…</div>;
  if (!data) return <div style={{ color: C.danger, textAlign: "center", padding: "60px 0" }}>Whale holder not found.</div>;

  const { holder, summary, conviction_buys, top_holdings, all_holdings } = data;
  const cb = summary.change_breakdown || {};

  const baseHoldings = showAll ? all_holdings : top_holdings;
  const filtered = baseHoldings.filter((h) => {
    if (tickerFilter && !h.ticker.includes(tickerFilter.toUpperCase())) return false;
    if (changeFilter && h.change_type !== changeFilter) return false;
    return true;
  });
  const hasFilter = tickerFilter || changeFilter;

  return (
    <div style={{ maxWidth: 900, margin: "0 auto" }}>
      <Link to="/whales" style={{ color: C.textDim, fontSize: 12, textDecoration: "none" }}>← All whales</Link>

      <div style={{ margin: "10px 0 20px" }}>
        <h1 style={{ color: C.textBright, margin: "0 0 4px", fontSize: "1.5rem" }}>{holder.name}</h1>
        <p style={{ color: C.textDim, margin: 0, fontSize: 13 }}>
          {holder.holder_type} · CIK {holder.cik} · latest filing {summary.latest_quarter || "—"}
        </p>
      </div>

      {/* Summary stats */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 16 }}>
        <Stat label="Positions" value={summary.position_count} />
        <Stat label="Portfolio value" value={summary.total_value_fmt} color={C.accent} />
        <Stat label="New" value={cb.new || 0} color={C.success} />
        <Stat label="Increased" value={cb.increased || 0} color="#34d399" />
        <Stat label="Decreased" value={cb.decreased || 0} color={C.warning} />
      </div>

      {/* Conviction buys */}
      {conviction_buys.length > 0 && (
        <div style={{ ...card, padding: "12px 16px", marginBottom: 16 }}>
          <div style={{ color: C.textSoft, fontSize: 12, fontWeight: 600, marginBottom: 8 }}>
            Conviction buys (new + increased)
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {conviction_buys.map((h) => (
              <Link key={h.ticker} to={`/ticker/${h.ticker}`}
                style={{ textDecoration: "none", background: C.bg, border: "1px solid var(--c-accentBg)", borderRadius: 6, padding: "4px 10px", display: "flex", gap: 6, alignItems: "center" }}>
                <span style={{ color: C.accent, fontWeight: 700, fontSize: 12 }}>{h.ticker}</span>
                <span style={{ color: styleFor(h.change_type)?.color || C.textMuted, fontSize: 10 }}>
                  {styleFor(h.change_type)?.label}
                </span>
              </Link>
            ))}
          </div>
        </div>
      )}

      <HolderRecord holderId={Number(id)} />

      {/* Holdings header + filters */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", margin: "0 0 10px", flexWrap: "wrap", gap: 8 }}>
        <h2 style={{ color: C.textSoft, fontSize: 13, fontWeight: 600, margin: 0 }}>
          Holdings ({hasFilter ? `${filtered.length} of ` : ""}{all_holdings.length})
        </h2>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <input
            placeholder="Ticker…"
            value={tickerFilter}
            onChange={(e) => setTickerFilter(e.target.value.toUpperCase())}
            style={{ background: C.bg, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, color: C.textBright, padding: "4px 10px", fontSize: 12, width: 90 }}
          />
          <select
            value={changeFilter}
            onChange={(e) => setChangeFilter(e.target.value as ChangeType | "")}
            style={{ background: C.bg, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, color: C.textSoft, padding: "4px 8px", fontSize: 12 }}
          >
            <option value="">All moves</option>
            {CHANGE_TYPES.map((t) => (
              <option key={t} value={t}>{styleFor(t)?.label || t}</option>
            ))}
          </select>
          {hasFilter && (
            <button
              onClick={() => { setTickerFilter(""); setChangeFilter(""); }}
              style={{ background: "none", color: C.textMuted, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, padding: "4px 8px", fontSize: 12, cursor: "pointer" }}
            >
              Clear
            </button>
          )}
          {all_holdings.length > top_holdings.length && (
            <button onClick={() => setShowAll((s) => !s)}
              style={{ background: C.surfaceAlt, color: C.textSoft, border: "1px solid var(--c-divider)", borderRadius: 6, padding: "4px 10px", fontSize: 12, cursor: "pointer" }}>
              {showAll ? "Show top 25" : `Show all ${all_holdings.length}`}
            </button>
          )}
        </div>
      </div>

      {all_holdings.length === 0 ? (
        <p style={{ color: C.textDim, fontSize: 13 }}>
          No parsed holdings yet — run "↻ Sync 13F Holdings" on the Whales page.
        </p>
      ) : filtered.length === 0 ? (
        <p style={{ color: C.textDim, fontSize: 13 }}>No positions match your filters.</p>
      ) : (
        <div style={{ ...card, overflowX: "auto", WebkitOverflowScrolling: "touch" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--c-surfaceAlt)" }}>
                {["Ticker", "Company", "Value", "Weight", "Change"].map((h) => (
                  <th key={h} style={{ padding: "10px 12px", color: C.textDim, fontWeight: 600, fontSize: 11, textAlign: "left" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((h) => (
                <tr key={h.ticker} style={{ borderBottom: "1px solid var(--c-surfaceAlt)" }}>
                  <td style={{ padding: "9px 12px" }}>
                    <Link to={`/ticker/${h.ticker}`} style={{ color: C.accent, fontWeight: 700, textDecoration: "none" }}>{h.ticker}</Link>
                  </td>
                  <td style={{ padding: "9px 12px", color: C.textSoft, fontSize: 12 }}>{h.company_name}</td>
                  <td style={{ padding: "9px 12px", color: C.text, fontWeight: 600 }}>{h.value_fmt}</td>
                  <td style={{ padding: "9px 12px", color: C.textMuted }}>{h.weight_pct}%</td>
                  <td style={{ padding: "9px 12px" }}>
                    <span style={{ color: styleFor(h.change_type)?.color || C.textMuted, fontSize: 11, fontWeight: 700 }}>
                      {styleFor(h.change_type)?.label || h.change_type}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
