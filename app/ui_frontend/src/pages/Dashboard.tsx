import { C, LABEL_COLORS } from "../lib/theme";
import ModelDeskCard from "../components/ModelDeskCard";
import useDocumentTitle from "../hooks/useDocumentTitle";
import useAdmin from "../hooks/useAdmin";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  getLatestAnalysis, syncTrades, getSyncStatus, runAnalysis, getPerformance,
  getInsiderTransactions, getTechnicalSignals, getTrades, getUnseenAlertCount, getAlertEvents, getWatchlistSignals,
} from "../lib/api";
import { EMAIL_KEY } from "../lib/storage";
import LineChart from "../components/LineChart";
import type { TechnicalSignal, Trade, SignalLabel } from "../types/api";

// Legend colors mirror LineChart's series palette (resolved for canvas there).
const PALETTE = [C.accent, C.success, C.warning, C.info, "#f472b6", "#facc15", "#34d399", C.danger, "#60a5fa", "#e879f9"];

type Period = "morning" | "midday" | "evening";
const PERIOD_ORDER: Period[] = ["morning", "midday", "evening"];

interface Analysis {
  analysis_date?: string;
  tickers_bullish?: string[];
  tickers_bearish?: string[];
}

interface PerfPoint { date: string; close: number; _demo?: boolean; }
interface PerfSeries { label: string; data: { date: string; value: number }[]; }
interface InsiderTxn { id: number; ticker: string; insider_name: string; transaction_type: string; }
interface WatchRow {
  id: number; ticker: string; composite_score: number | null; label: SignalLabel | null;
  current_price: number | null; price_7d_change: number | null;
}

const daysAgo = (n: number) => {
  const d = new Date(); d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
};

const fmtDate = (s?: string | null) =>
  s ? new Date(s + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "—";

/** Small metric card used across the top strip. */
function Stat({ label, value, sub, to, tone }: { label: string; value: React.ReactNode; sub?: React.ReactNode; to?: string; tone?: string }) {
  const body = (
    <div style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 10, padding: "0.9rem 1rem", height: "100%" }}>
      <div style={{ color: C.textMuted, fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>{label}</div>
      <div style={{ color: tone ?? C.textBright, fontSize: "1.35rem", fontWeight: 700, lineHeight: 1.15 }}>{value}</div>
      {sub && <div style={{ color: C.textMuted, fontSize: "0.75rem", marginTop: 4 }}>{sub}</div>}
    </div>
  );
  return to ? <Link to={to} style={{ textDecoration: "none", display: "block", height: "100%" }}>{body}</Link> : body;
}

function SectionHead({ title, to, linkLabel = "View all →" }: { title: string; to?: string; linkLabel?: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: "0.6rem" }}>
      <h2 style={{ fontSize: "0.95rem", fontWeight: 600, color: C.textSoft, margin: 0 }}>{title}</h2>
      {to && <Link to={to} style={{ color: C.textMuted, fontSize: 12, textDecoration: "none" }}>{linkLabel}</Link>}
    </div>
  );
}

// The analysis can flag 100+ tickers; the Dashboard shows the first two rows
// and links to the full list rather than becoming a wall of chips.
const CHIP_CAP = 18;

const Chip = ({ t, up }: { t: string; up: boolean }) => (
  <Link to={`/ticker/${t}`} style={{
    background: up ? C.successBg : C.dangerBg, color: up ? C.success : C.danger,
    padding: "3px 9px", borderRadius: 5, fontSize: "0.8rem", fontWeight: 600, textDecoration: "none",
  }}>
    {up ? "↑" : "↓"} {t}
  </Link>
);

export default function Dashboard() {
  const isAdmin = useAdmin();
  useDocumentTitle("Dashboard");
  const [analyses, setAnalyses] = useState<Partial<Record<Period, Analysis>>>({});
  const [signals, setSignals] = useState<TechnicalSignal[]>([]);
  const [recentTrades, setRecentTrades] = useState<Trade[]>([]);
  const [weekCount, setWeekCount] = useState<number | null>(null);
  const [recentInsiders, setRecentInsiders] = useState<InsiderTxn[]>([]);
  const [unseen, setUnseen] = useState<number>(0);
  const [firedWeek, setFiredWeek] = useState<number | null>(null);
  const [watch, setWatch] = useState<WatchRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [running, setRunning] = useState<Partial<Record<Period, boolean>>>({});
  const [loadError, setLoadError] = useState("");
  const [perfSeries, setPerfSeries] = useState<PerfSeries[]>([]);
  const [perfLoading, setPerfLoading] = useState(true);
  const [perfDemo, setPerfDemo] = useState(false);
  const [lastSynced, setLastSynced] = useState<Date | null>(null);

  const load = () =>
    getLatestAnalysis()
      .then((r) => setAnalyses(r.data as Partial<Record<Period, Analysis>>))
      .catch((e: Error) => setLoadError(e?.message || "Failed to load analysis"))
      .finally(() => setLoading(false));

  const loadPerf = () => {
    setPerfLoading(true);
    getPerformance()
      .then((r) => {
        let isDemo = false;
        const data = r.data as Record<string, PerfPoint[]>;
        const series = Object.entries(data).map(([label, points]) => {
          if (points[0]?._demo) isDemo = true;
          return { label, data: points.map((p) => ({ date: p.date, value: p.close })) };
        });
        setPerfSeries(series);
        setPerfDemo(isDemo);
      })
      .catch(() => setPerfSeries([]))
      .finally(() => setPerfLoading(false));
  };

  useEffect(() => {
    load();
    loadPerf();
    getTechnicalSignals().then((r) => setSignals(r.data.signals ?? [])).catch(() => {});
    getTrades({ sort_by: "disclosure_date", limit: 6 }).then((r) => setRecentTrades(r.data.items ?? [])).catch(() => {});
    // "Disclosed" = filed with Congress in the last 7 days (disclosure lags the trade by weeks).
    getTrades({ sort_by: "disclosure_date", limit: 500 }).then((r) => {
      const cutoff = daysAgo(7);
      setWeekCount((r.data.items ?? []).filter((t) => (t.disclosure_date ?? "") >= cutoff).length);
    }).catch(() => {});
    getInsiderTransactions({ limit: 5 }).then((r) => {
      const d = r.data as { items?: InsiderTxn[] } | InsiderTxn[] | undefined;
      setRecentInsiders(Array.isArray(d) ? d : d?.items ?? []);
    }).catch(() => {});
    getUnseenAlertCount().then((r) => setUnseen(r.data?.unseen ?? 0)).catch(() => {});
    getAlertEvents({ limit: 500 }).then((r) => {
      const cutoff = new Date(); cutoff.setDate(cutoff.getDate() - 7);
      setFiredWeek(r.data.filter((e) => !!e.triggered_at && new Date(e.triggered_at) >= cutoff).length);
    }).catch(() => {});
    let email = "";
    try { email = localStorage.getItem(EMAIL_KEY) || ""; } catch { /* ignore */ }
    if (email) getWatchlistSignals(email).then((r) => setWatch(r.data as WatchRow[])).catch(() => setWatch(null));
  }, []);

  const handleSync = async () => {
    setSyncing(true);
    try {
      await syncTrades();
      // The sync runs in the background; poll until it finishes (cap ~5 min).
      for (let i = 0; i < 100; i++) {
        await new Promise((r) => setTimeout(r, 3000));
        const { data } = await getSyncStatus();
        if (!data.running) break;
      }
      await runAnalysis("morning");
      await load();
      await loadPerf();
      setLastSynced(new Date());
    } finally {
      setSyncing(false);
    }
  };

  const handleRunPeriod = async (period: Period) => {
    setRunning((r) => ({ ...r, [period]: true }));
    try {
      await runAnalysis(period);
      await load();
    } finally {
      setRunning((r) => ({ ...r, [period]: false }));
    }
  };

  // The most recent analysis: latest date, then latest period within that day.
  const latest = useMemo(() => {
    let best: { period: Period; a: Analysis } | null = null;
    for (const p of PERIOD_ORDER) {
      const a = analyses[p];
      if (!a?.analysis_date) continue;
      if (!best || a.analysis_date >= best.a.analysis_date!) best = { period: p, a };
    }
    return best;
  }, [analyses]);

  const topSignals = useMemo(
    () => [...signals].sort((a, b) => (b.composite_score ?? 0) - (a.composite_score ?? 0)).slice(0, 5),
    [signals],
  );
  const top = topSignals[0];

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Dashboard</h1>
          <p>Public disclosures, scored. {latest ? <>Last analysis {fmtDate(latest.a.analysis_date)} ({latest.period}).</> : null}</p>
        </div>
        {isAdmin && (
          <div className="page-head__actions">
            {PERIOD_ORDER.map((p) => (
              <button
                key={p}
                onClick={() => handleRunPeriod(p)}
                disabled={running[p] || syncing}
                style={{
                  background: C.surfaceAlt, color: C.textSoft, border: "1px solid var(--c-divider)",
                  padding: "0.4rem 0.9rem", borderRadius: 6, cursor: "pointer",
                  fontSize: "0.8rem", opacity: running[p] ? 0.6 : 1,
                }}
              >
                {running[p] ? "Running…" : `▶ ${p.charAt(0).toUpperCase() + p.slice(1)}`}
              </button>
            ))}
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 2 }}>
              <button
                onClick={handleSync}
                disabled={syncing}
                style={{
                  background: C.accentSolid, color: "#fff", border: "none",
                  padding: "0.4rem 1.1rem", borderRadius: 6, cursor: "pointer",
                  fontSize: "0.8rem", opacity: syncing ? 0.6 : 1,
                }}
              >
                {syncing ? "Syncing…" : "⟳ Sync"}
              </button>
              {lastSynced && (
                <span style={{ color: C.textDim, fontSize: "0.68rem" }}>synced {lastSynced.toLocaleTimeString()}</span>
              )}
            </div>
          </div>
        )}
      </div>

      {loadError && <p style={{ color: C.danger, marginBottom: "1rem" }}>Error: {loadError}</p>}

      {/* ── Today strip ─────────────────────────────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: "0.75rem", marginBottom: "1.5rem" }}>
        <Stat label="Disclosed this week" value={weekCount ?? "…"} sub="congressional trades, last 7 days" to="/feed" />
        <Stat
          label="Top signal"
          value={top ? top.ticker : "…"}
          sub={top ? <><span style={{ color: LABEL_COLORS[top.label] }}>{top.label}</span> · score {top.composite_score}</> : undefined}
          to={top ? `/ticker/${top.ticker}` : "/signals"}
        />
        <Stat
          label="Latest read"
          value={latest ? <><span style={{ color: C.success }}>{latest.a.tickers_bullish?.length ?? 0}</span><span style={{ fontSize: "0.8rem", color: C.textMuted }}> bullish</span> · <span style={{ color: C.danger }}>{latest.a.tickers_bearish?.length ?? 0}</span><span style={{ fontSize: "0.8rem", color: C.textMuted }}> bearish</span></> : "…"}
          sub={latest ? `${latest.period} · ${fmtDate(latest.a.analysis_date)}` : "no analysis yet"}
          to="/signals"
        />
        {isAdmin
          ? <Stat label="Unseen alerts" value={unseen} sub={unseen > 0 ? "rules have fired" : "all caught up"} to="/alerts" tone={unseen > 0 ? C.warningSolid : undefined} />
          : <Stat label="Alerts fired" value={firedWeek ?? "…"} sub="last 7 days" to="/alerts" tone={(firedWeek ?? 0) > 0 ? C.warningSolid : undefined} />}
      </div>

      {loading ? (
        <p style={{ color: C.textMuted }}>Loading…</p>
      ) : (
        <>
          {/* ── Latest read + watchlist ───────────────────────────────── */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "1.25rem", marginBottom: "1.75rem" }}>
            <div>
              <SectionHead title={latest ? `Latest read — ${latest.period}, ${fmtDate(latest.a.analysis_date)}` : "Latest read"} to="/signals" linkLabel="All scores →" />
              <div style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 10, padding: "1rem" }}>
                {latest ? (
                  <>
                    <div style={{ color: C.textMuted, fontSize: "0.72rem", textTransform: "uppercase", marginBottom: 6 }}>Bullish</div>
                    <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", marginBottom: 12 }}>
                      {(latest.a.tickers_bullish ?? []).length === 0 && <span style={{ color: C.textDim, fontSize: "0.82rem" }}>none</span>}
                      {(latest.a.tickers_bullish ?? []).slice(0, CHIP_CAP).map((t) => <Chip key={t} t={t} up />)}
                      {(latest.a.tickers_bullish ?? []).length > CHIP_CAP && <Link to="/signals" style={{ color: C.textMuted, fontSize: "0.8rem", alignSelf: "center", textDecoration: "none" }}>+{(latest.a.tickers_bullish ?? []).length - CHIP_CAP} more →</Link>}
                    </div>
                    <div style={{ color: C.textMuted, fontSize: "0.72rem", textTransform: "uppercase", marginBottom: 6 }}>Bearish</div>
                    <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
                      {(latest.a.tickers_bearish ?? []).length === 0 && <span style={{ color: C.textDim, fontSize: "0.82rem" }}>none</span>}
                      {(latest.a.tickers_bearish ?? []).slice(0, CHIP_CAP).map((t) => <Chip key={t} t={t} up={false} />)}
                      {(latest.a.tickers_bearish ?? []).length > CHIP_CAP && <Link to="/signals" style={{ color: C.textMuted, fontSize: "0.8rem", alignSelf: "center", textDecoration: "none" }}>+{(latest.a.tickers_bearish ?? []).length - CHIP_CAP} more →</Link>}
                    </div>
                    <div style={{ color: C.textDim, fontSize: "0.72rem", marginTop: 12 }}>
                      Runs at 8 AM, noon and 6 PM ET.{" "}
                      {PERIOD_ORDER.filter((p) => analyses[p]?.analysis_date && p !== latest.period)
                        .map((p) => `${p} ${fmtDate(analyses[p]!.analysis_date)}`).join(" · ")}
                    </div>
                  </>
                ) : (
                  <div style={{ color: C.textDim, fontSize: "0.85rem" }}>
                    No analysis yet.{isAdmin ? " Click ⟳ Sync to pull trades and run one." : " The first run happens at 8 AM ET."}
                  </div>
                )}
              </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
              <SectionHead title="Your watchlist" to="/watchlist" linkLabel={watch ? "Manage →" : "Set up →"} />
              {/* Fills the column to match the card on the left; longer lists scroll inside. */}
              <div style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 10, padding: watch && watch.length ? "0.25rem 0" : "1rem",
                            flex: "1 1 0px", minHeight: 0, overflowY: "auto" }}>
                {watch && watch.length > 0 ? (
                  watch.map((w) => (
                    <Link key={w.id} to={`/ticker/${w.ticker}`} style={{ display: "flex", alignItems: "center", gap: "0.75rem", padding: "0.55rem 1rem", textDecoration: "none", borderBottom: "1px solid var(--c-surfaceAlt)", flexShrink: 0 }}>
                      <span style={{ color: C.accent, fontWeight: 700, width: 60 }}>{w.ticker}</span>
                      <span style={{ color: C.textSoft, fontSize: "0.85rem", fontVariantNumeric: "tabular-nums", width: 80 }}>{w.current_price != null ? `$${w.current_price.toLocaleString()}` : "—"}</span>
                      <span style={{ color: (w.price_7d_change ?? 0) >= 0 ? C.success : C.danger, fontSize: "0.8rem", width: 60 }}>
                        {w.price_7d_change != null ? `${w.price_7d_change >= 0 ? "+" : ""}${w.price_7d_change.toFixed(1)}% 7d` : ""}
                      </span>
                      <span style={{ marginLeft: "auto", color: w.label ? LABEL_COLORS[w.label] : C.textDim, fontSize: "0.78rem", fontWeight: 600 }}>
                        {w.label ?? "—"}{w.composite_score != null ? ` · ${w.composite_score}` : ""}
                      </span>
                    </Link>
                  ))
                ) : (
                  <div style={{ color: C.textMuted, fontSize: "0.85rem", lineHeight: 1.6 }}>
                    {watch ? "Your watchlist is empty — add tickers from any page with “+ Watch”." : "Save tickers you care about and they show up here with their current score."}
                  </div>
                )}
              </div>
            </div>
          </div>

          <ModelDeskCard />

          {/* ── Top signals + latest disclosures ──────────────────────── */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "1.25rem", marginBottom: "1.75rem" }}>
            <div>
              <SectionHead title="Top signals right now" to="/signals" />
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {topSignals.length === 0 && <div style={{ color: C.textDim, fontSize: "0.85rem" }}>No scores computed yet.</div>}
                {topSignals.map((s) => (
                  <Link key={s.ticker} to={`/ticker/${s.ticker}`} style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8, padding: "0.6rem 0.9rem", textDecoration: "none", display: "grid", gridTemplateColumns: "64px 1fr auto", gap: "0.5rem 0.75rem", alignItems: "center" }}>
                    <span style={{ color: C.accent, fontWeight: 700 }}>{s.ticker}</span>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ height: 5, background: C.surfaceAlt, borderRadius: 3, overflow: "hidden", marginBottom: 4 }}>
                        <div style={{ width: `${Math.max(0, Math.min(100, s.composite_score))}%`, height: "100%", background: LABEL_COLORS[s.label] }} />
                      </div>
                      <div style={{ color: C.textMuted, fontSize: "0.74rem", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{s.reasons?.[0] ?? ""}</div>
                    </div>
                    <span style={{ color: LABEL_COLORS[s.label], fontWeight: 700, fontSize: "0.85rem", fontVariantNumeric: "tabular-nums" }}>{s.composite_score}</span>
                  </Link>
                ))}
              </div>
            </div>

            <div>
              <SectionHead title="Latest disclosures" to="/feed" />
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {recentTrades.length === 0 && <div style={{ color: C.textDim, fontSize: "0.85rem" }}>No trades loaded yet.</div>}
                {recentTrades.map((t) => {
                  const buy = t.direction === "buy";
                  return (
                    <div key={t.id} style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8, padding: "0.6rem 0.9rem", display: "flex", flexWrap: "wrap", gap: "0.25rem 0.75rem", alignItems: "center" }}>
                      <Link to={`/ticker/${t.ticker}`} style={{ color: C.accent, fontWeight: 700, textDecoration: "none", width: 64 }}>{t.ticker}</Link>
                      <span style={{ color: buy ? C.success : t.direction === "sell" ? C.danger : C.textSoft, fontSize: "0.78rem", fontWeight: 600, width: 84 }}>{t.transaction_type}</span>
                      <span style={{ color: C.textSoft, fontSize: "0.82rem", flex: "1 1 120px", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {t.politician ? <Link to={`/politician/${t.politician.id}`} style={{ color: "inherit", textDecoration: "none" }}>{t.politician.name}</Link> : "—"}
                      </span>
                      <span style={{ color: C.textMuted, fontSize: "0.75rem", marginLeft: "auto", whiteSpace: "nowrap" }}>{t.amount_range ?? ""} · disclosed {fmtDate(t.disclosure_date)}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* ── Recent corporate insiders ──────────────────────────────── */}
          {recentInsiders.length > 0 && (
            <div style={{ marginBottom: "1.75rem" }}>
              <SectionHead title="Recent corporate insiders" to="/insiders" />
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 6 }}>
                {recentInsiders.map((t) => (
                  <Link key={t.id} to={`/ticker/${t.ticker}`} style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8, padding: "10px 14px", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, textDecoration: "none" }}>
                    <div style={{ minWidth: 0 }}>
                      <span style={{ color: C.accent, fontWeight: 700, fontSize: 13 }}>{t.ticker}</span>
                      <span style={{ color: C.textMuted, fontSize: 12, marginLeft: 8, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.insider_name}</span>
                    </div>
                    <span style={{ color: t.transaction_type === "buy" ? C.success : t.transaction_type === "sell" ? C.danger : C.textMuted, fontSize: 11, fontWeight: 700, textTransform: "uppercase", flexShrink: 0 }}>
                      {t.transaction_type}
                    </span>
                  </Link>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {/* ── 30-day performance ────────────────────────────────────────── */}
      <div style={{ marginBottom: "1rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.6rem", gap: 8, flexWrap: "wrap" }}>
          <h2 style={{ fontSize: "0.95rem", fontWeight: 600, color: C.textSoft, margin: 0 }}>30-day performance of signaled tickers</h2>
          {perfDemo && (
            <span style={{ background: C.warningBg, color: C.warningSolid, border: "1px solid var(--c-warningDeep)", fontSize: "0.68rem", padding: "1px 8px", borderRadius: 4 }}>
              demo data
            </span>
          )}
        </div>
        <div style={{ background: C.bg, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8, minHeight: 240 }}>
          {perfLoading ? (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 240, color: C.textMuted }}>Loading chart…</div>
          ) : perfSeries.length > 0 ? (
            <LineChart series={perfSeries} height={240} normalized title="Portfolio Performance" />
          ) : (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 240, color: C.textDim, fontSize: "0.85rem" }}>
              No performance data yet
            </div>
          )}
        </div>
        {perfSeries.length > 0 && (
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.5rem" }}>
            {perfSeries.map((s, i) => (
              <Link key={s.label} to={`/ticker/${s.label}`} style={{ display: "flex", alignItems: "center", gap: 5, fontSize: "0.75rem", color: C.textSoft, textDecoration: "none" }}>
                <span style={{ width: 16, height: 3, background: PALETTE[i % PALETTE.length], display: "inline-block", borderRadius: 2, flexShrink: 0 }} />
                {s.label}
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
