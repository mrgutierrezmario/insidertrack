import { C } from "../lib/theme";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getLatestAnalysis, syncTrades, getSyncStatus, runAnalysis, getPerformance, getInsiderTransactions, getFedTrades, ADMIN_TOKEN_KEY } from "../lib/api";
import SignalBadge from "../components/SignalBadge";
import LineChart from "../components/LineChart";

const PALETTE = [C.accent,C.success,C.warning,C.info,"#f472b6","#facc15","#34d399",C.danger,"#60a5fa","#e879f9"];

type Period = "morning" | "midday" | "evening";

interface Analysis {
  analysis_date?: string;
  tickers_bullish?: string[];
  tickers_bearish?: string[];
  signals?: SignalItem[];
}

interface SignalItem {
  ticker: string;
  reason: string;
  insiders?: string[];
  current_price?: number | null;
  signal: "BUY" | "SELL" | "HOLD";
}

interface PerfPoint {
  date: string;
  close: number;
  _demo?: boolean;
}

interface PerfSeries {
  label: string;
  data: { date: string; value: number }[];
}

interface InsiderTxn {
  id: number;
  ticker: string;
  insider_name: string;
  transaction_type: string;
}

interface FedTxn {
  id: number;
  ticker: string;
  official_name?: string;
  transaction_type: string;
}

export default function Dashboard() {
  const [analyses, setAnalyses] = useState<Partial<Record<Period, Analysis>>>({});
  const [recentInsiders, setRecentInsiders] = useState<InsiderTxn[]>([]);
  const [recentFed, setRecentFed] = useState<FedTxn[]>([]);
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
    getInsiderTransactions({ limit: 5 }).then((r) => {
      const d = r.data as { items?: InsiderTxn[] } | InsiderTxn[] | undefined;
      setRecentInsiders(Array.isArray(d) ? d : d?.items ?? []);
    }).catch(() => {});
    getFedTrades({ limit: 5 }).then((r) => {
      const d = r.data as { items?: FedTxn[] } | FedTxn[] | undefined;
      setRecentFed(Array.isArray(d) ? d : d?.items ?? []);
    }).catch(() => {});
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

  const latestAnalysis: Analysis | undefined = analyses.evening || analyses.midday || analyses.morning;

  return (
    <div>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem", flexWrap: "wrap", gap: "0.75rem" }}>
        <h1 style={{ fontSize: "1.5rem", fontWeight: 700 }}>Dashboard</h1>
        {sessionStorage.getItem(ADMIN_TOKEN_KEY) && (
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {(["morning", "midday", "evening"] as Period[]).map((p) => (
              <button
                key={p}
                onClick={() => handleRunPeriod(p)}
                disabled={running[p] || syncing}
                style={{
                  background: C.surfaceAlt, color: C.textSoft, border: "1px solid #334155",
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
                <span style={{ color: C.divider, fontSize: "0.68rem" }}>
                  synced {lastSynced.toLocaleTimeString()}
                </span>
              )}
            </div>
          </div>
        )}
      </div>

      {loadError && <p style={{ color: C.danger, marginBottom: "1rem" }}>Error: {loadError}</p>}
      {latestAnalysis?.analysis_date && !syncing && (
        <p style={{ color: C.divider, fontSize: "0.72rem", marginBottom: "0.75rem" }}>
          Last analysis: {latestAnalysis.analysis_date}
        </p>
      )}

      {/* 30-day performance chart */}
      <div style={{ marginBottom: "2rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
          <h2 style={{ fontSize: "1rem", fontWeight: 600, color: C.textSoft }}>30-Day Performance</h2>
          {perfDemo && (
            <span style={{ background: C.warningBg, color: C.warningSolid, border: "1px solid #78350f", fontSize: "0.68rem", padding: "1px 8px", borderRadius: 4 }}>
              demo data
            </span>
          )}
        </div>
        <div style={{ background: C.bg, border: "1px solid #1e2533", borderRadius: 8, minHeight: 260 }}>
          {perfLoading ? (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 260, color: C.textMuted }}>Loading chart…</div>
          ) : perfSeries.length > 0 ? (
            <LineChart series={perfSeries} height={260} normalized title="Portfolio Performance" />
          ) : (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 260, color: C.textDim, fontSize: "0.85rem" }}>
              No performance data — sync trades first
            </div>
          )}
        </div>
        {perfSeries.length > 0 && (
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "0.5rem" }}>
            {perfSeries.map((s, i) => (
              <Link
                key={s.label}
                to={`/ticker/${s.label}`}
                style={{ display: "flex", alignItems: "center", gap: 5, fontSize: "0.75rem", color: C.textSoft, textDecoration: "none" }}
              >
                <span style={{ width: 16, height: 3, background: PALETTE[i % PALETTE.length], display: "inline-block", borderRadius: 2, flexShrink: 0 }} />
                {s.label}
              </Link>
            ))}
          </div>
        )}
      </div>

      {loading ? (
        <p style={{ color: C.textMuted }}>Loading…</p>
      ) : (
        <>
          {/* Period summary cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: "1rem", marginBottom: "2rem" }}>
            {(["morning", "midday", "evening"] as Period[]).map((period) => {
              const a = analyses[period];
              return (
                <div key={period} style={{ background: C.surface, border: "1px solid #1e2533", borderRadius: 8, padding: "1rem" }}>
                  <div style={{ color: C.textMuted, fontSize: "0.75rem", textTransform: "uppercase", marginBottom: 8, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span>{period}</span>
                    {running[period] && <span style={{ color: C.accent, fontSize: "0.7rem" }}>running…</span>}
                  </div>
                  {a ? (
                    <>
                      <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", marginBottom: 6 }}>
                        {(a.tickers_bullish || []).map((t) => (
                          <Link key={t} to={`/ticker/${t}`} style={{ background: C.successBg, color: C.success, padding: "2px 8px", borderRadius: 4, fontSize: "0.78rem", textDecoration: "none" }}>↑ {t}</Link>
                        ))}
                        {(a.tickers_bearish || []).map((t) => (
                          <Link key={t} to={`/ticker/${t}`} style={{ background: C.dangerBg, color: C.danger, padding: "2px 8px", borderRadius: 4, fontSize: "0.78rem", textDecoration: "none" }}>↓ {t}</Link>
                        ))}
                      </div>
                      <div style={{ color: C.textDim, fontSize: "0.72rem" }}>{a.analysis_date}</div>
                    </>
                  ) : (
                    <div style={{ color: "#374151", fontSize: "0.82rem" }}>No analysis yet</div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Active signals */}
          {(latestAnalysis?.signals?.length ?? 0) > 0 && (
            <div>
              <h2 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "1rem", color: C.textSoft }}>Active Signals</h2>
              <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
                {(latestAnalysis?.signals ?? []).map((s) => (
                  <div
                    key={s.ticker}
                    style={{ background: C.surface, border: "1px solid #1e2533", borderRadius: 8, padding: "0.875rem 1rem", display: "flex", justifyContent: "space-between", alignItems: "center" }}
                  >
                    <div style={{ flex: 1 }}>
                      <Link to={`/ticker/${s.ticker}`} style={{ color: C.accent, fontWeight: 700, marginRight: "0.75rem", textDecoration: "none", fontSize: "1.05rem" }}>
                        {s.ticker}
                      </Link>
                      <span style={{ color: C.textMuted, fontSize: "0.82rem" }}>{s.reason}</span>
                      {(s.insiders?.length ?? 0) > 0 && (
                        <div style={{ color: C.textDim, fontSize: "0.72rem", marginTop: 3 }}>
                          {(s.insiders ?? []).join(", ")}
                        </div>
                      )}
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: "1rem", flexShrink: 0 }}>
                      {s.current_price != null && (
                        <span style={{ color: C.textSoft, fontSize: "0.9rem", fontFamily: "monospace" }}>
                          ${s.current_price.toLocaleString()}
                        </span>
                      )}
                      <SignalBadge signal={s.signal} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {!latestAnalysis && (
            <div style={{ textAlign: "center", color: C.textDim, paddingTop: "3rem" }}>
              <p>No analysis data yet. Click "⟳ Sync" to pull trades and run analysis.</p>
            </div>
          )}

          {/* Recent corporate insider + Fed activity */}
          {(recentInsiders.length > 0 || recentFed.length > 0) && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: "1.5rem", marginTop: "2rem" }}>
              {recentInsiders.length > 0 && (
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
                    <h2 style={{ fontSize: "1rem", fontWeight: 600, color: C.textSoft, margin: 0 }}>Recent Corporate Insiders</h2>
                    <Link to="/insiders" style={{ color: C.dividerStrong, fontSize: 12, textDecoration: "none" }}>View all →</Link>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {recentInsiders.map((t) => (
                      <div key={t.id} style={{ background: C.surface, border: "1px solid #1e2533", borderRadius: 8, padding: "10px 14px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <div>
                          <span style={{ color: C.accent, fontWeight: 700, fontSize: 13 }}>{t.ticker}</span>
                          <span style={{ color: C.dividerStrong, fontSize: 12, marginLeft: 8 }}>{t.insider_name}</span>
                        </div>
                        <span style={{ color: t.transaction_type === "buy" ? C.success : C.danger, fontSize: 11, fontWeight: 700, textTransform: "uppercase" }}>
                          {t.transaction_type}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {recentFed.length > 0 && (
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
                    <h2 style={{ fontSize: "1rem", fontWeight: 600, color: C.textSoft, margin: 0 }}>Recent Fed Disclosures</h2>
                    <Link to="/fed" style={{ color: C.dividerStrong, fontSize: 12, textDecoration: "none" }}>View all →</Link>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {recentFed.map((t) => (
                      <div key={t.id} style={{ background: C.surface, border: "1px solid #1e2533", borderRadius: 8, padding: "10px 14px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <div>
                          <span style={{ color: C.accent, fontWeight: 700, fontSize: 13 }}>{t.ticker}</span>
                          <span style={{ color: C.dividerStrong, fontSize: 12, marginLeft: 8 }}>{t.official_name?.split(" ").slice(-1)[0]}</span>
                        </div>
                        <span style={{ color: t.transaction_type === "purchase" ? C.success : C.danger, fontSize: 11, fontWeight: 700, textTransform: "uppercase" }}>
                          {t.transaction_type}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
