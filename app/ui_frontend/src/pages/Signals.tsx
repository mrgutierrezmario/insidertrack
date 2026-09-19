import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getTechnicalSignals } from "../lib/api";
import { exportCSV } from "../lib/csv";
import { LABEL_COLORS , C} from "../lib/theme";
import useDocumentTitle from "../hooks/useDocumentTitle";
import WatchlistButton from "../components/WatchlistButton";
import SkeletonCard from "../components/SkeletonCard";
import type { SignalDirection, SignalLabel } from "../types/api";

// Signal rows include extra computed fields that aren't all in the api.ts
// TechnicalSignal shape — keep a page-local shape that mirrors what the
// backend returns from /signals/.
interface SignalRow {
  ticker: string;
  label: SignalLabel;
  signal: SignalDirection;
  composite_score: number | null;
  current_price: number | null;
  rsi: number | null;
  reasons: string[];
  sub_scores: {
    smart_money?: number | null;
    insider?: number | null;
    corporate?: number | null;
    momentum?: number | null;
    sentiment?: number | null;
    risk_penalty?: number | null;
  };
}

function exportSignalsCSV(signals: SignalRow[]) {
  exportCSV(
    ["ticker", "label", "signal", "composite_score", "smart_money", "congress", "corporate_insiders", "momentum", "sentiment", "rsi", "current_price"],
    signals.map((s) => {
      const sub = s.sub_scores || {};
      return [s.ticker, s.label, s.signal, s.composite_score ?? "", sub.smart_money ?? "", sub.insider ?? "", sub.corporate ?? "", sub.momentum ?? "", sub.sentiment ?? "", s.rsi ?? "", s.current_price ?? ""];
    }),
    "insidertrack-signals",
  );
}

const SIGNAL_META: Record<SignalDirection, { color: string; bg: string; border: string; icon: string }> = {
  BULLISH: { color: C.success, bg: "rgba(74,222,128,0.08)",  border: "rgba(74,222,128,0.2)",  icon: "▲" },
  BEARISH: { color: C.danger, bg: "rgba(248,113,113,0.08)", border: "rgba(248,113,113,0.2)", icon: "▼" },
  NEUTRAL: { color: C.textSoft, bg: "rgba(148,163,184,0.04)", border: "rgba(148,163,184,0.15)", icon: "◆" },
};

function ScoreBar({ score }: { score: number | null | undefined }) {
  const pct = Math.min(100, Math.max(0, score || 0));
  const color = pct >= 70 ? C.success : pct >= 50 ? C.accent : pct >= 30 ? C.textSoft : pct >= 15 ? C.warning : C.danger;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ flex: 1, height: 6, background: C.surfaceAlt, borderRadius: 3, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 3 }} />
      </div>
      <span style={{ color, fontWeight: 700, fontSize: 14, minWidth: 28 }}>{score ?? "—"}</span>
    </div>
  );
}

const SUB_TIPS: Record<string, string> = {
  "Smart Money": "Institutional 13F holders in this ticker — new or growing positions score higher. Max 20.",
  "Congress": "Congressional buys vs. sells in the last 45 days, weighted by the disclosed dollar bracket. Options count by contract direction; unknown contracts and bonds are neutral. Max 25.",
  "Insiders": "Company officers and directors (SEC Form 4) in the last 90 days: open-market buys vs. sells by dollar value. Buying counts more than selling, and several insiders buying together earns a bonus. Max 20.",
  "Momentum": "Price vs. 20/50-day averages and RSI. Oversold with an uptrend scores best. Max 25.",
  "Sentiment": "Tone of recent news headlines for the ticker. Max 10.",
  "Risk penalty": "Deducted for stale disclosures (old trades or long disclosure lag). Up to −20.",
};

function SubScore({ label, value, max }: { label: string; value: number | null | undefined; max: number }) {
  return (
    <div data-tip={SUB_TIPS[label]} tabIndex={0} style={{ cursor: "help", outline: "none" }}>
      <div style={{ color: C.dividerStrong, fontSize: 10, textTransform: "uppercase", letterSpacing: "0.04em", borderBottom: "1px dotted var(--c-divider)", display: "inline-block" }}>{label}</div>
      <div style={{ color: C.textSoft, fontWeight: 600, fontSize: 12 }}>
        {value ?? "—"}<span style={{ color: C.divider }}>/{max}</span>
      </div>
    </div>
  );
}

export default function Signals() {
  useDocumentTitle("Signal Scores");
  const [signals, setSignals] = useState<SignalRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [labelFilter, setLabelFilter] = useState<string>("ALL");
  const [signalFilter, setSignalFilter] = useState<string>("ALL");
  const [sortBy, setSortBy] = useState("score");
  const [tickerSearch, setTickerSearch] = useState("");

  const [computedAt, setComputedAt] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const fetchSignals = (isRefresh = false) => {
    if (isRefresh) setRefreshing(true); else setLoading(true);
    getTechnicalSignals()
      .then((r) => {
        const d = r.data as { signals?: SignalRow[]; computed_at?: string } | SignalRow[] | undefined;
        if (d && !Array.isArray(d) && d.signals) {
          setSignals(d.signals);
          setComputedAt(d.computed_at || null);
        } else if (Array.isArray(d)) {
          setSignals(d);
        }
      })
      .finally(() => { setLoading(false); setRefreshing(false); });
  };

  useEffect(() => { fetchSignals(); }, []);

  const labels = ["ALL", "Strong Watch", "Watch", "Neutral", "High Risk", "Avoid for Now"];
  const signalOpts = ["ALL", "BULLISH", "NEUTRAL", "BEARISH"];

  let filtered = signals
    .filter((s) => labelFilter === "ALL" || s.label === labelFilter)
    .filter((s) => signalFilter === "ALL" || s.signal === signalFilter)
    .filter((s) => !tickerSearch || s.ticker.includes(tickerSearch.toUpperCase()));

  if (sortBy === "score") filtered = [...filtered].sort((a, b) => (b.composite_score ?? 0) - (a.composite_score ?? 0));
  else if (sortBy === "ticker") filtered = [...filtered].sort((a, b) => a.ticker.localeCompare(b.ticker));
  else if (sortBy === "rsi") filtered = [...filtered].sort((a, b) => (b.rsi ?? 0) - (a.rsi ?? 0));

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto" }}>
      {/* Header */}
      <div className="page-head">
        <div>
          <h1>Signal Scores</h1>
          <p style={{ color: C.dividerStrong, margin: 0, fontSize: 13 }}>
            Composite scores for all tracked insider tickers — sorted by conviction strength.
            {computedAt && (
              <span style={{ color: C.divider, marginLeft: 10, fontSize: 11 }}>
                · computed {new Date(computedAt).toLocaleString()}
              </span>
            )}
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {filtered.length > 0 && (
            <button
              onClick={() => exportSignalsCSV(filtered)}
              style={{ background: C.surfaceAlt, color: C.textSoft, border: "1px solid var(--c-divider)", borderRadius: 6, padding: "5px 12px", fontSize: 12, cursor: "pointer" }}
            >
              ↓ CSV
            </button>
          )}
          <button
            onClick={() => fetchSignals(true)}
            disabled={refreshing}
            style={{ background: "rgba(56,189,248,0.1)", color: C.accent, border: "1px solid rgba(56,189,248,0.3)", borderRadius: 6, padding: "5px 12px", fontSize: 12, cursor: "pointer", opacity: refreshing ? 0.6 : 1 }}
          >
            {refreshing ? "Computing…" : "↻ Refresh"}
          </button>
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, color: C.textSoft, padding: "6px 10px", fontSize: 13 }}
          >
            <option value="score">Sort: Score ↓</option>
            <option value="ticker">Sort: Ticker A-Z</option>
            <option value="rsi">Sort: RSI ↓</option>
          </select>
        </div>
      </div>

      {/* Ticker search */}
      <div style={{ marginBottom: 12 }}>
        <input
          placeholder="Filter ticker…"
          value={tickerSearch}
          onChange={(e) => setTickerSearch(e.target.value.toUpperCase())}
          style={{
            background: C.surface, color: C.text,
            border: "1px solid var(--c-surfaceAlt)", borderRadius: 6,
            padding: "0.4rem 0.85rem", fontSize: "0.85rem", width: 180,
          }}
        />
      </div>

      {/* Label filter */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
        {labels.map((l) => (
          <button key={l} onClick={() => setLabelFilter(l)}
            style={{
              background: labelFilter === l ? "rgba(56,189,248,0.12)" : "transparent",
              color: labelFilter === l ? C.accent : C.textMuted,
              border: `1px solid ${labelFilter === l ? "rgba(56,189,248,0.3)" : C.surfaceAlt}`,
              borderRadius: 6, padding: "4px 12px", fontSize: 12, cursor: "pointer",
            }}>
            {l}
          </button>
        ))}
        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          {signalOpts.map((o) => {
            const meta = (SIGNAL_META as Record<string, { color: string; bg: string; border: string; icon: string }>)[o] || {};
            return (
              <button key={o} onClick={() => setSignalFilter(o)}
                style={{
                  background: signalFilter === o ? (meta.bg || "rgba(56,189,248,0.12)") : "transparent",
                  color: signalFilter === o ? (meta.color || C.accent) : C.textMuted,
                  border: `1px solid ${signalFilter === o ? (meta.border || "rgba(56,189,248,0.3)") : C.surfaceAlt}`,
                  borderRadius: 6, padding: "4px 12px", fontSize: 12, cursor: "pointer",
                }}>
                {o !== "ALL" && ((SIGNAL_META as Record<string, { color: string; bg: string; border: string; icon: string }>)[o]?.icon + " ")}{o}
              </button>
            );
          })}
        </div>
      </div>

      {/* Count */}
      {!loading && (
        <p style={{ color: C.divider, fontSize: 12, marginBottom: 14 }}>
          {filtered.length} ticker{filtered.length !== 1 ? "s" : ""}
        </p>
      )}

      {/* Cards */}
      {loading ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {[...Array(6)].map((_, i) => <SkeletonCard key={i} lines={3} height={110} />)}
        </div>
      ) : filtered.length === 0 ? (
        <div style={{ textAlign: "center", color: C.dividerStrong, padding: "60px 0" }}>
          No signals yet — sync trades from the Dashboard first.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {filtered.map((s) => {
            const sig = SIGNAL_META[s.signal] || SIGNAL_META.NEUTRAL;
            const labelColor = LABEL_COLORS[s.label] || C.textSoft;
            const sub = s.sub_scores || {};
            return (
              <div key={s.ticker} style={{
                background: C.surface,
                border: "1px solid var(--c-surfaceAlt)",
                borderLeft: `3px solid ${labelColor}`,
                borderRadius: 10,
                padding: "14px 18px",
              }}>
                {/* Top row */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                    <Link to={`/ticker/${s.ticker}`} style={{ color: C.textBright, fontWeight: 700, fontSize: 16, textDecoration: "none" }}>
                      {s.ticker}
                    </Link>
                    <WatchlistButton ticker={s.ticker} />
                    <span style={{ color: labelColor, fontSize: 12, fontWeight: 600 }}>{s.label}</span>
                    <span style={{
                      background: sig.bg, color: sig.color, border: `1px solid ${sig.border}`,
                      borderRadius: 5, padding: "2px 8px", fontSize: 11, fontWeight: 700,
                    }}>
                      {sig.icon} {s.signal}
                    </span>
                  </div>
                  {s.current_price != null && (
                    <span style={{ color: C.textSoft, fontFamily: "monospace", fontSize: 13 }}>
                      ${s.current_price.toLocaleString()}
                    </span>
                  )}
                </div>

                {/* Score bar */}
                <div style={{ marginBottom: 12 }}>
                  <ScoreBar score={s.composite_score} />
                </div>

                {/* Sub-scores */}
                <div style={{ display: "flex", gap: 20, flexWrap: "wrap", marginBottom: 10 }}>
                  <SubScore label="Smart Money" value={sub.smart_money} max={20} />
                  <SubScore label="Congress" value={sub.insider} max={25} />
                  <SubScore label="Insiders" value={sub.corporate} max={20} />
                  <SubScore label="Momentum" value={sub.momentum} max={25} />
                  <SubScore label="Sentiment" value={sub.sentiment} max={10} />
                  {(sub.risk_penalty ?? 0) > 0 && (
                    <SubScore label="Risk penalty" value={-(sub.risk_penalty ?? 0)} max={20} />
                  )}
                  {s.rsi != null && (
                    <div>
                      <div style={{ color: C.dividerStrong, fontSize: 10, textTransform: "uppercase", letterSpacing: "0.04em" }}>RSI</div>
                      <div style={{ color: s.rsi < 30 ? C.success : s.rsi > 70 ? C.danger : C.textSoft, fontWeight: 600, fontSize: 12 }}>
                        {s.rsi}
                      </div>
                    </div>
                  )}
                </div>

                {/* Reasons */}
                {s.reasons?.length > 0 && (
                  <ul style={{ margin: 0, padding: "0 0 0 16px", color: C.textMuted, fontSize: 12 }}>
                    {s.reasons.map((r, i) => <li key={i}>{r}</li>)}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
