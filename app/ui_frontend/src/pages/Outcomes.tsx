import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getOutcomeStats, getOutcomes, runOutcomeSnapshot, runOutcomeFill } from "../lib/api";
import { exportCSV } from "../lib/csv";
import { C, LABEL_COLORS, OUTCOME_COLORS } from "../lib/theme";
import useDocumentTitle from "../hooks/useDocumentTitle";
import useAdmin from "../hooks/useAdmin";
import WatchlistButton from "../components/WatchlistButton";
import SkeletonCard from "../components/SkeletonCard";
import type { OutcomeDirection, OutcomeRow, OutcomeStats, OutcomeWindow, SignalLabel } from "../types/api";

function exportOutcomesCSV(rows: OutcomeRow[]) {
  exportCSV(
    ["signal_date","ticker","label","score","price_at_signal","politician","d30_outcome","d30_return","d60_outcome","d60_return","d90_outcome","d90_return"],
    rows.map((r) => [
      r.signal_date, r.ticker, r.label, r.composite_score, r.price_at_signal ?? "",
      r.politician_name ?? "",
      r.d30?.outcome ?? "", r.d30?.return ?? "", r.d60?.outcome ?? "", r.d60?.return ?? "",
      r.d90?.outcome ?? "", r.d90?.return ?? "",
    ]),
    "insidertrack-outcomes",
  );
}


function WinRateBar({ up, down, flat, total }: { up: number; down: number; flat: number; total: number }) {
  if (!total) return <span style={{ color: C.divider, fontSize: 12 }}>No data</span>;
  const upPct = Math.round((up / total) * 100);
  const downPct = Math.round((down / total) * 100);
  const flatPct = 100 - upPct - downPct;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{ flex: 1, height: 8, borderRadius: 4, overflow: "hidden", display: "flex", background: C.surfaceAlt }}>
        <div style={{ width: `${upPct}%`, background: C.success }} />
        <div style={{ width: `${flatPct}%`, background: C.dividerStrong }} />
        <div style={{ width: `${downPct}%`, background: C.danger }} />
      </div>
      <span style={{ color: C.success, fontSize: 12, fontWeight: 700, minWidth: 32 }}>{upPct}%</span>
    </div>
  );
}

function StatsCard({ stat }: { stat: import("../types/api").OutcomeStatsRow }) {
  const color = LABEL_COLORS[stat.label] || C.textSoft;
  return (
    <div style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderLeft: `3px solid ${color}`, borderRadius: 10, padding: "16px 18px" }}>
      <div style={{ color, fontWeight: 700, fontSize: 14, marginBottom: 12 }}>{stat.label}</div>
      {[{ label: "30d", d: stat.d30 }, { label: "60d", d: stat.d60 }, { label: "90d", d: stat.d90 }].map(({ label, d }) => (
        <div key={label} style={{ marginBottom: 8 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
            <span style={{ color: C.textMuted, fontSize: 11 }}>{label}</span>
            <span style={{ color: C.textSoft, fontSize: 11 }}>
              {d.total ? `${d.up}↑ ${d.flat}→ ${d.down}↓ (${d.total})` : "—"}
            </span>
          </div>
          <WinRateBar {...d} />
        </div>
      ))}
    </div>
  );
}

function _addDays(iso: string | null | undefined, days: number): string | null {
  if (!iso) return null;
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return null;
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

function OutcomeChip({ outcome, signalDate, days }: { outcome: OutcomeDirection | null; signalDate: string; days: number }) {
  if (!outcome) {
    const fillsOn = _addDays(signalDate, days);
    const today = new Date().toISOString().slice(0, 10);
    const overdue = fillsOn && fillsOn < today;
    return (
      <span
        title={fillsOn ? `Outcome will fill on ${fillsOn}` : "Waiting for fill"}
        style={{ color: overdue ? C.warning : C.divider, fontSize: 11 }}
      >
        {fillsOn ? `fills ${fillsOn}` : "pending"}
      </span>
    );
  }
  return (
    <span style={{
      background: `rgba(${outcome === "UP" ? "74,222,128" : outcome === "DOWN" ? "248,113,113" : "148,163,184"},0.1)`,
      color: OUTCOME_COLORS[outcome] || C.textSoft,
      border: `1px solid ${OUTCOME_COLORS[outcome] || C.divider}33`,
      borderRadius: 4, padding: "1px 7px", fontSize: 11, fontWeight: 600,
    }}>
      {outcome}
    </span>
  );
}

function ReturnCell({ ret, outcome }: { ret: number | null; outcome: OutcomeDirection | null }) {
  if (ret == null) return <span style={{ color: C.divider, fontSize: 12 }}>—</span>;
  const color = outcome === "UP" ? C.success : outcome === "DOWN" ? C.danger : C.textSoft;
  return <span style={{ color, fontSize: 12, fontWeight: 600 }}>{ret > 0 ? "+" : ""}{ret.toFixed(1)}%</span>;
}

function SubScoreTooltip({ sub }: { sub: Partial<import("../types/api").SubScores> | null | undefined }) {
  const [show, setShow] = useState(false);
  if (!sub || Object.keys(sub).every((k) => sub[k as keyof typeof sub] == null)) return null;
  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <button
        onMouseEnter={() => setShow(true)}
        onMouseLeave={() => setShow(false)}
        style={{ background: "transparent", border: "none", color: C.divider, cursor: "pointer", fontSize: 12, padding: "0 2px" }}
        title="Sub-scores"
      >
        ⓘ
      </button>
      {show && (
        <div style={{
          position: "absolute", bottom: "120%", left: "50%", transform: "translateX(-50%)",
          background: C.bg, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8,
          padding: "10px 14px", zIndex: 100, whiteSpace: "nowrap", boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
        }}>
          {[
            ["Smart Money", sub.smart_money, 30],
            ["Insider", sub.insider, 25],
            ["Momentum", sub.momentum, 25],
            ["Sentiment", sub.sentiment, 10],
            ["Risk penalty", sub.risk_penalty ? `-${sub.risk_penalty}` : null, 20],
          ].map(([label, val, max]) => val != null && (
            <div key={label} style={{ display: "flex", justifyContent: "space-between", gap: 16, marginBottom: 4, fontSize: 11 }}>
              <span style={{ color: C.textMuted }}>{label}</span>
              <span style={{ color: C.textSoft, fontWeight: 600 }}>{val}<span style={{ color: C.divider }}>/{max}</span></span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

interface OutcomeFilter {
  ticker: string;
  label: SignalLabel | "";
  resolved: "" | "yes" | "no";
}

export default function Outcomes() {
  const isAdmin = useAdmin();
  useDocumentTitle("Outcomes");
  const [stats, setStats] = useState<OutcomeStats | null>(null);
  const [rows, setRows] = useState<OutcomeRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<OutcomeFilter>({ ticker: "", label: "", resolved: "" });
  const [msg, setMsg] = useState("");

  const load = (f: OutcomeFilter = filter) => {
    setLoading(true);
    const params: Record<string, string | number | boolean> = {};
    if (f.ticker) params.ticker = f.ticker.toUpperCase();
    if (f.label) params.label = f.label;
    if (f.resolved === "yes") params.resolved = true;
    if (f.resolved === "no") params.resolved = false;
    Promise.all([getOutcomeStats(), getOutcomes(params)])
      .then(([s, r]) => { setStats(s.data); setRows(r.data); })
      .finally(() => setLoading(false));
  };

  // Reactive filters
  useEffect(() => { load(filter); }, [filter.ticker, filter.label, filter.resolved]);

  const triggerAction = async (fn: () => Promise<unknown>, label: string) => {
    setMsg(`${label}…`);
    try {
      await fn();
      setMsg(`${label} started — refresh in a moment.`);
    } catch {
      setMsg("Error — check backend logs.");
    }
  };

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto" }}>
      <div className="page-head">
        <div>
          <h1>Signal Outcomes</h1>
          <p style={{ color: C.dividerStrong, margin: 0, fontSize: 13 }}>
            Tracks whether signal scores predicted price direction at 30, 60, and 90 days.
          </p>
        </div>
        {isAdmin && <div style={{ display: "flex", gap: 8 }}>
          <button onClick={() => triggerAction(runOutcomeSnapshot, "Snapshot")}
            style={{ background: "rgba(56,189,248,0.1)", color: C.accent, border: "1px solid rgba(56,189,248,0.3)", borderRadius: 6, padding: "6px 14px", fontSize: 12, cursor: "pointer" }}>
            ↻ Snapshot Today
          </button>
          <button onClick={() => triggerAction(runOutcomeFill, "Fill")}
            style={{ background: "rgba(74,222,128,0.08)", color: C.success, border: "1px solid rgba(74,222,128,0.2)", borderRadius: 6, padding: "6px 14px", fontSize: 12, cursor: "pointer" }}>
            ↻ Fill Outcomes
          </button>
        </div>}
      </div>

      {msg && (
        <div style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8, padding: "10px 14px", marginBottom: 16, color: C.textSoft, fontSize: 13 }}>
          {msg}
        </div>
      )}

      {stats && (
        <div style={{ marginBottom: 28 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <span style={{ color: C.textMuted, fontSize: 12 }}>
              {stats.total_snapshots} snapshots
              {stats.tracking_since ? ` · since ${stats.tracking_since}` : ""}
              {stats.latest_snapshot ? ` · latest ${stats.latest_snapshot}` : ""}
            </span>
            <span style={{ color: C.divider, fontSize: 11 }}>UP = ≥+2% · DOWN = ≤−2% · FLAT = within ±2%</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 12 }}>
            {stats.labels.map((s) => <StatsCard key={s.label} stat={s} />)}
          </div>
        </div>
      )}

      {/* Reactive filters */}
      <div style={{ display: "flex", gap: 10, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
        <input
          value={filter.ticker}
          onChange={(e) => setFilter((f) => ({ ...f, ticker: e.target.value.toUpperCase() }))}
          placeholder="Filter by ticker…"
          style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, color: C.textBright, padding: "6px 12px", fontSize: 13, width: 160 }}
        />
        <select value={filter.label}
          onChange={(e) => setFilter((f) => ({ ...f, label: e.target.value as SignalLabel | "" }))}
          style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, color: C.textSoft, padding: "6px 12px", fontSize: 13 }}>
          <option value="">All labels</option>
          {(["Strong Watch", "Watch", "Neutral", "High Risk", "Avoid for Now"] as SignalLabel[]).map((l) => (
            <option key={l} value={l}>{l}</option>
          ))}
        </select>
        <select value={filter.resolved}
          onChange={(e) => setFilter((f) => ({ ...f, resolved: e.target.value as "" | "yes" | "no" }))}
          style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, color: C.textSoft, padding: "6px 12px", fontSize: 13 }}>
          <option value="">All rows</option>
          <option value="yes">Resolved (30d+ done)</option>
          <option value="no">Pending</option>
        </select>
        {(filter.ticker || filter.label || filter.resolved) && (
          <button onClick={() => setFilter({ ticker: "", label: "", resolved: "" })}
            style={{ background: "none", color: C.textMuted, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, padding: "6px 12px", fontSize: 13, cursor: "pointer" }}>
            Clear
          </button>
        )}
        {rows.length > 0 && (
          <button onClick={() => exportOutcomesCSV(rows)}
            style={{ background: C.surfaceAlt, color: C.textSoft, border: "1px solid var(--c-divider)", borderRadius: 6, padding: "6px 12px", fontSize: 13, cursor: "pointer", marginLeft: "auto" }}>
            ↓ CSV
          </button>
        )}
      </div>

      {loading ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {[...Array(5)].map((_, i) => <SkeletonCard key={i} lines={2} height={50} />)}
        </div>
      ) : rows.length === 0 ? (
        <div style={{ color: C.dividerStrong, textAlign: "center", padding: "60px 0" }}>
          No outcome records yet — click "↻ Snapshot Today" to capture today's signals.
        </div>
      ) : (
        <div style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 12, overflowX: "auto", WebkitOverflowScrolling: "touch" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--c-surfaceAlt)" }}>
                {[
                  ["date", "Date"], ["ticker", "Ticker"], ["label", "Label"],
                  ["politician", "Politician"], ["score", "Score"], ["price", "Price"],
                  ["d30", "30d"], ["d30pct", "+%"],
                  ["d60", "60d"], ["d60pct", "+%"],
                  ["d90", "90d"], ["d90pct", "+%"],
                ].map(([k, h]) => (
                  <th key={k} style={{ padding: "10px 12px", color: C.dividerStrong, fontWeight: 600, fontSize: 11, textAlign: "left" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} style={{ borderBottom: "1px solid var(--c-surfaceAlt)" }}>
                  <td style={{ padding: "9px 12px", color: C.textMuted, whiteSpace: "nowrap" }}>
                    {r.signal_date}
                    {r.is_backfilled && (
                      <span
                        title="Backfilled retroactively — sentiment used neutral 50 (Alpha Vantage doesn't expose historical news)"
                        style={{ marginLeft: 6, fontSize: 9, color: C.warning, border: "1px solid var(--c-warningDeep)", borderRadius: 3, padding: "0 4px", verticalAlign: "middle" }}
                      >
                        BF
                      </span>
                    )}
                  </td>
                  <td style={{ padding: "9px 12px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <Link to={`/ticker/${r.ticker}`} style={{ color: C.accent, fontWeight: 700, textDecoration: "none" }}>{r.ticker}</Link>
                      <WatchlistButton ticker={r.ticker} />
                    </div>
                  </td>
                  <td style={{ padding: "9px 12px" }}>
                    <Link to={`/ticker/${r.ticker}`} style={{ color: LABEL_COLORS[r.label] || C.textSoft, fontSize: 12, textDecoration: "none" }} title="View trades driving this signal">
                      {r.label} →
                    </Link>
                  </td>
                  <td style={{ padding: "9px 12px" }}>
                    {r.politician_id ? (
                      <Link to={`/politician/${r.politician_id}`} style={{ color: C.textSoft, fontSize: 12, textDecoration: "none" }}>
                        {r.politician_name}
                      </Link>
                    ) : (
                      <span style={{ color: C.divider, fontSize: 12 }}>—</span>
                    )}
                  </td>
                  <td style={{ padding: "9px 12px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                      <span style={{ color: C.textBright, fontWeight: 700 }}>{r.composite_score}</span>
                      <SubScoreTooltip sub={r.sub_scores} />
                    </div>
                  </td>
                  <td style={{ padding: "9px 12px", color: C.textSoft }}>{r.price_at_signal ? `$${r.price_at_signal.toFixed(2)}` : "—"}</td>
                  <td style={{ padding: "9px 12px" }}><OutcomeChip outcome={r.d30.outcome} signalDate={r.signal_date} days={30} /></td>
                  <td style={{ padding: "9px 12px" }}><ReturnCell ret={r.d30.return} outcome={r.d30.outcome} /></td>
                  <td style={{ padding: "9px 12px" }}><OutcomeChip outcome={r.d60.outcome} signalDate={r.signal_date} days={60} /></td>
                  <td style={{ padding: "9px 12px" }}><ReturnCell ret={r.d60.return} outcome={r.d60.outcome} /></td>
                  <td style={{ padding: "9px 12px" }}><OutcomeChip outcome={r.d90.outcome} signalDate={r.signal_date} days={90} /></td>
                  <td style={{ padding: "9px 12px" }}><ReturnCell ret={r.d90.return} outcome={r.d90.outcome} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div style={{ marginTop: 16, color: C.divider, fontSize: 11, lineHeight: 1.6 }}>
        Snapshots run daily at 7:00 AM ET · Outcomes fill at 7:30 AM ET · ±2% threshold for UP/DOWN classification
      </div>
    </div>
  );
}
