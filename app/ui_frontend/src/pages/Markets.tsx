import { C } from "../lib/theme";
import useDocumentTitle from "../hooks/useDocumentTitle";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { getMarketMovers, getTechnicalSignals, getMacroIndicators } from "../lib/api";
import WatchlistButton from "../components/WatchlistButton";
import type { SignalDirection } from "../types/api";

interface Mover {
  ticker: string;
  price: number;
  change_percentage: number | string;
  volume?: number | string;
}

interface MarketSignal {
  ticker: string;
  signal: SignalDirection;
  current_price?: number | null;
  sma20?: number | null;
  sma50?: number | null;
  rsi?: number | null;
  insider_buys?: number;
  insider_sells?: number;
  window_start?: string | null;
  window_end?: string | null;
  last_trade_date?: string | null;
  last_filing_date?: string | null;
  reasons: string[];
}

interface Macro {
  name: string;
  value: number | string;
  change?: number | string | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function pctColor(pct: number | string): string {
  const n = parseFloat(String(pct).replace("%", "").replace("+", ""));
  return n >= 0 ? C.success : C.danger;
}

function fmtVol(v: number | string | undefined): string {
  const n = parseInt(String(v ?? "").replace(/,/g, ""), 10);
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}K`;
  return String(n);
}

const SIGNAL_META: Record<SignalDirection, { color: string; bg: string; border: string; icon: string }> = {
  BULLISH:  { color: C.success, bg: "rgba(74,222,128,0.1)",  border: "rgba(74,222,128,0.25)",  icon: "▲" },
  BEARISH:  { color: C.danger, bg: "rgba(248,113,113,0.1)", border: "rgba(248,113,113,0.25)", icon: "▼" },
  NEUTRAL:  { color: C.textSoft, bg: "rgba(148,163,184,0.06)", border: "rgba(148,163,184,0.15)", icon: "◆" },
};

// ── Sub-components ────────────────────────────────────────────────────────────

function MoverCard({ m, showVol }: { m: Mover; showVol?: boolean }) {
  const color = pctColor(m.change_percentage);
  const isPos = parseFloat(String(m.change_percentage).replace("%", "")) >= 0;
  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "10px 14px",
      background: C.bg,
      borderRadius: 8,
      border: "1px solid var(--c-surfaceAlt)",
    }}>
      <div>
        <Link to={`/ticker/${m.ticker}`} style={{ textDecoration: "none" }}>
          <span style={{ color: C.textBright, fontWeight: 700, fontSize: 14 }}>{m.ticker}</span>
        </Link>
        {showVol && (
          <span style={{ color: C.dividerStrong, fontSize: 11, marginLeft: 8 }}>Vol {fmtVol(m.volume)}</span>
        )}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{ textAlign: "right" }}>
          <div style={{ color: C.textSoft, fontSize: 12 }}>${m.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
          <div style={{ color, fontWeight: 700, fontSize: 13 }}>
            {isPos && "+"}{typeof m.change_percentage === "string" ? m.change_percentage : `${m.change_percentage}%`}
          </div>
        </div>
        <WatchlistButton ticker={m.ticker} />
      </div>
    </div>
  );
}

function MoverPanel({ title, icon, items, showVol = false, loading }: { title: string; icon: string; items: Mover[]; showVol?: boolean; loading: boolean }) {
  return (
    <div style={{
      background: C.surface,
      border: "1px solid var(--c-surfaceAlt)",
      borderRadius: 12,
      padding: "20px",
      flex: 1,
      minWidth: 220,
    }}>
      <h3 style={{ color: C.textBright, margin: "0 0 16px", fontSize: 14, display: "flex", alignItems: "center", gap: 8 }}>
        <span>{icon}</span> {title}
      </h3>
      {loading ? (
        <div style={{ color: C.dividerStrong, fontSize: 13 }}>Loading…</div>
      ) : items.length === 0 ? (
        <div style={{ color: C.dividerStrong, fontSize: 13 }}>No data</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {items.map((m) => <MoverCard key={m.ticker} m={m} showVol={showVol} />)}
        </div>
      )}
    </div>
  );
}

function SignalCard({ s }: { s: MarketSignal }) {
  const meta = SIGNAL_META[s.signal] || SIGNAL_META.NEUTRAL;
  return (
    <div style={{
      background: meta.bg,
      border: `1px solid ${meta.border}`,
      borderRadius: 12,
      padding: "16px 18px",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Link to={`/ticker/${s.ticker}`} style={{ textDecoration: "none" }}>
            <span style={{ color: C.textBright, fontWeight: 700, fontSize: 16 }}>{s.ticker}</span>
          </Link>
          <WatchlistButton ticker={s.ticker} />
        </div>
        <span style={{
          background: meta.color + "22",
          color: meta.color,
          border: `1px solid ${meta.color}55`,
          borderRadius: 6,
          padding: "2px 10px",
          fontSize: 12,
          fontWeight: 700,
          letterSpacing: "0.04em",
        }}>
          {meta.icon} {s.signal}
        </span>
      </div>

      {/* Indicators row */}
      <div style={{ display: "flex", gap: 16, marginBottom: 10, flexWrap: "wrap" }}>
        {s.current_price && (
          <Stat label="Price" value={`$${s.current_price.toLocaleString()}`} />
        )}
        {s.sma20 && <Stat label="SMA20" value={`$${s.sma20}`} />}
        {s.sma50 && <Stat label="SMA50" value={`$${s.sma50}`} />}
        {s.rsi != null && (
          <Stat
            label="RSI"
            value={s.rsi}
            color={s.rsi < 30 ? C.success : s.rsi > 70 ? C.danger : C.textSoft}
          />
        )}
      </div>

      {/* Insider activity */}
      {((s.insider_buys ?? 0) > 0 || (s.insider_sells ?? 0) > 0) && (
        <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
          {(s.insider_buys ?? 0) > 0 && (
            <span style={{ background: "rgba(74,222,128,0.12)", color: C.success, borderRadius: 5, padding: "2px 8px", fontSize: 11 }}>
              {s.insider_buys} insider buy{(s.insider_buys ?? 0) > 1 ? "s" : ""}
            </span>
          )}
          {(s.insider_sells ?? 0) > 0 && (
            <span style={{ background: "rgba(248,113,113,0.12)", color: C.danger, borderRadius: 5, padding: "2px 8px", fontSize: 11 }}>
              {s.insider_sells} insider sell{(s.insider_sells ?? 0) > 1 ? "s" : ""}
            </span>
          )}
        </div>
      )}

      {/* Date range + last activity */}
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 6 }}>
        {s.window_start && s.window_end && (
          <span style={{ color: C.divider, fontSize: 11 }}>
            Window: {new Date(s.window_start).toLocaleDateString("en-US", { month: "short", day: "numeric" })} – {new Date(s.window_end).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
          </span>
        )}
        {s.last_trade_date && (
          <span style={{ color: C.divider, fontSize: 11 }}>
            Last trade: {new Date(s.last_trade_date + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
          </span>
        )}
        {s.last_filing_date && (
          <span style={{ color: C.divider, fontSize: 11 }}>
            Last filing: {new Date(s.last_filing_date + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
          </span>
        )}
      </div>

      {/* Reasons */}
      <ul style={{ margin: 0, padding: "0 0 0 16px", color: C.textMuted, fontSize: 12 }}>
        {s.reasons.map((r, i) => <li key={i}>{r}</li>)}
      </ul>
    </div>
  );
}

function Stat({ label, value, color = C.textSoft }: { label: string; value: ReactNode; color?: string }) {
  return (
    <div>
      <div style={{ color: C.dividerStrong, fontSize: 10, textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</div>
      <div style={{ color, fontWeight: 600, fontSize: 13 }}>{value}</div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

interface MoversData {
  top_gainers?: Mover[];
  top_losers?: Mover[];
  most_actively_traded?: Mover[];
  _demo?: boolean;
}

interface MacroEntry {
  label: string;
  price: number;
  change_pct: number;
  _stale?: boolean;
  as_of?: string;
}

export default function Markets() {
  useDocumentTitle("Market Overview");
  const [movers, setMovers] = useState<MoversData | null>(null);
  const [signals, setSignals] = useState<MarketSignal[]>([]);
  const [macro, setMacro] = useState<Record<string, MacroEntry> | null>(null);
  const [loading, setLoading] = useState(true);
  const [sigFilter, setSigFilter] = useState<"ALL" | SignalDirection>("ALL");

  useEffect(() => {
    Promise.allSettled([getMarketMovers(), getTechnicalSignals(), getMacroIndicators()]).then(([m, s, mac]) => {
      if (m.status === "fulfilled") setMovers(m.value.data as MoversData);
      if (s.status === "fulfilled") {
        const sd = s.value.data as { signals?: MarketSignal[] } | MarketSignal[];
        setSignals(Array.isArray(sd) ? sd : sd?.signals ?? []);
      }
      if (mac.status === "fulfilled") setMacro(mac.value.data as Record<string, MacroEntry>);
      setLoading(false);
    });
  }, []);

  const filteredSignals = sigFilter === "ALL"
    ? signals
    : signals.filter((s) => s.signal === sigFilter);

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto" }}>
      <div className="page-head">
        <h1>Market Overview</h1>
        {movers?._demo && (
          <span style={{ background: "rgba(251,191,36,0.1)", color: C.warningSolid, border: "1px solid rgba(251,191,36,0.25)", borderRadius: 6, padding: "3px 10px", fontSize: 11 }}>
            demo data — no tracked tickers with price history yet
          </span>
        )}
        {movers && !movers._demo && (
          <span style={{ background: "rgba(74,222,128,0.08)", color: C.success, border: "1px solid rgba(74,222,128,0.2)", borderRadius: 6, padding: "3px 10px", fontSize: 11 }}>
            live — based on tracked tickers
          </span>
        )}
      </div>

      {/* ── Macro indicators ────────────────────────────────── */}
      {macro && (
        <div style={{ marginBottom: 32 }}>
          <h2 style={{ color: C.textSoft, fontSize: 13, textTransform: "uppercase", letterSpacing: "0.08em", margin: "0 0 12px" }}>
            Macro Indicators
          </h2>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 10 }}>
            {Object.entries(macro).map(([sym, d]) => {
              const pos = d.change_pct >= 0;
              const isVix = sym === "^VIX";
              const color = isVix ? (d.price > 25 ? C.danger : d.price > 18 ? C.warning : C.success)
                : (pos ? C.success : C.danger);
              return (
                <div key={sym} style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8, padding: "12px 14px" }}>
                  <div style={{ color: C.dividerStrong, fontSize: 11, marginBottom: 4 }}>{d.label}</div>
                  <div style={{ color: C.textBright, fontWeight: 700, fontSize: 16 }}>
                    {sym === "^TNX" ? `${d.price.toFixed(2)}%` : sym === "FED_RATE" ? `${d.price.toFixed(2)}%` : `$${d.price.toLocaleString(undefined, { maximumFractionDigits: 2 })}`}
                  </div>
                  {d.change_pct !== 0 && sym !== "FED_RATE" && (
                    <div style={{ color, fontSize: 12, fontWeight: 600 }}>
                      {pos ? "+" : ""}{d.change_pct.toFixed(2)}%
                    </div>
                  )}
                  {sym === "FED_RATE" && (
                    <div style={{ fontSize: 10, marginTop: 2 }}>
                      {d._stale ? (
                        <span style={{ color: C.warning }}>⚠ stale data</span>
                      ) : (
                        <span style={{ color: C.divider }}>as of {d.as_of}</span>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Daily Movers ────────────────────────────────────── */}
      <h2 style={{ color: C.textSoft, fontSize: 13, textTransform: "uppercase", letterSpacing: "0.08em", margin: "0 0 14px" }}>
        Daily Movers
      </h2>
      <div style={{ display: "flex", gap: 16, marginBottom: 40, flexWrap: "wrap" }}>
        <MoverPanel title="Top Gainers" icon="📈" items={movers?.top_gainers ?? []} loading={loading} />
        <MoverPanel title="Top Losers"  icon="📉" items={movers?.top_losers  ?? []} loading={loading} />
        <MoverPanel title="Most Active" icon="🔥" items={movers?.most_actively_traded ?? []} loading={loading} showVol />
      </div>

      {/* ── Technical Signals ───────────────────────────────── */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
        <h2 style={{ color: C.textSoft, fontSize: 13, textTransform: "uppercase", letterSpacing: "0.08em", margin: 0 }}>
          Market Signals <span style={{ color: C.dividerStrong, fontWeight: 400 }}>— tracked insider tickers</span>
        </h2>
        <div style={{ display: "flex", gap: 6 }}>
          {(["ALL", "BULLISH", "NEUTRAL", "BEARISH"] as const).map((f) => {
            const meta = f === "ALL" ? { bg: undefined, color: undefined, border: undefined } : SIGNAL_META[f];
            return (
              <button
                key={f}
                onClick={() => setSigFilter(f)}
                style={{
                  background: sigFilter === f ? (meta.bg || "rgba(56,189,248,0.1)") : "transparent",
                  color: sigFilter === f ? (meta.color || C.accent) : C.textMuted,
                  border: `1px solid ${sigFilter === f ? (meta.border || "rgba(56,189,248,0.3)") : C.surfaceAlt}`,
                  borderRadius: 6, padding: "4px 12px", fontSize: 12, cursor: "pointer",
                }}
              >
                {f}
              </button>
            );
          })}
        </div>
      </div>

      {loading ? (
        <div style={{ color: C.dividerStrong, padding: "40px 0", textAlign: "center" }}>Loading signals…</div>
      ) : filteredSignals.length === 0 ? (
        <div style={{ color: C.dividerStrong, padding: "40px 0", textAlign: "center" }}>
          No {sigFilter !== "ALL" ? sigFilter.toLowerCase() : ""} signals — sync trades first to track tickers
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 14 }}>
          {filteredSignals.map((s) => <SignalCard key={s.ticker} s={s} />)}
        </div>
      )}
    </div>
  );
}
