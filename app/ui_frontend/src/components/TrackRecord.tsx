import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { C } from "../lib/theme";
import { getTrackRecord } from "../lib/api";
import type { TrackRecord as TR } from "../types/api";

const WINDOWS = ["30", "60", "90"] as const;

function pct(v: number | null | undefined, sign = true): string {
  if (v == null) return "—";
  return `${sign && v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}
function tone(v: number | null | undefined): string {
  if (v == null) return C.textMuted;
  return v > 0 ? C.success : v < 0 ? C.danger : C.textSoft;
}

/**
 * How a member's disclosed stock purchases performed after the public could
 * see them — the question every reader of this page actually has.
 */
export default function TrackRecord({ politicianId }: { politicianId: number }) {
  const [data, setData] = useState<TR | null>(null);
  const [state, setState] = useState<"loading" | "ok" | "error">("loading");
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    setState("loading");
    getTrackRecord(politicianId)
      .then((r) => { setData(r.data); setState("ok"); })
      .catch(() => setState("error"));
  }, [politicianId]);

  const head = (
    <h2 style={{ fontSize: "0.9rem", fontWeight: 600, color: C.textMuted, marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.05em" }}>
      Track record — stock purchases
    </h2>
  );

  if (state === "loading") return <div style={{ marginBottom: "1.5rem" }}>{head}<p style={{ color: C.textMuted, fontSize: "0.85rem" }}>Computing from price history…</p></div>;
  if (state === "error" || !data) return <div style={{ marginBottom: "1.5rem" }}>{head}<p style={{ color: C.textMuted, fontSize: "0.85rem" }}>Track record unavailable right now.</p></div>;
  if (data.evaluated === 0) {
    return (
      <div style={{ marginBottom: "1.5rem" }}>
        {head}
        <p style={{ color: C.textMuted, fontSize: "0.85rem" }}>
          No stock purchases old enough to measure yet (a buy needs 30 days after disclosure).
          {data.skipped_demo > 0 && " Some tickers had no live price history."}
        </p>
      </div>
    );
  }

  const rows = showAll ? data.trades : data.trades.slice(0, 10);
  return (
    <div style={{ marginBottom: "1.5rem" }}>
      {head}
      <p style={{ color: C.textMuted, fontSize: "0.8rem", margin: "0 0 10px" }}>
        {data.evaluated} purchase{data.evaluated === 1 ? "" : "s"} measured from the first close after disclosure. "vs SPY" is the return minus SPY over the same days.
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: "0.75rem", marginBottom: "1rem" }}>
        {WINDOWS.map((w) => {
          const s = data.windows[w];
          if (!s || !s.n) return null;
          return (
            <div key={w} style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8, padding: "0.75rem 1rem" }}>
              <div style={{ color: C.textMuted, fontSize: "0.72rem", fontWeight: 700, letterSpacing: "0.05em", marginBottom: 6 }}>{w} DAYS · {s.n} trade{s.n === 1 ? "" : "s"}</div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: "0.85rem", lineHeight: 1.7 }}>
                <div>
                  <div style={{ color: C.textMuted, fontSize: "0.72rem" }}>Avg return</div>
                  <div style={{ color: tone(s.avg_return), fontWeight: 700, fontSize: "1.1rem" }}>{pct(s.avg_return)}</div>
                  <div style={{ color: C.textMuted, fontSize: "0.72rem" }}>Win rate {s.win_rate != null ? `${s.win_rate.toFixed(0)}%` : "—"}</div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div style={{ color: C.textMuted, fontSize: "0.72rem" }}>vs SPY</div>
                  <div style={{ color: tone(s.avg_excess), fontWeight: 700, fontSize: "1.1rem" }}>{pct(s.avg_excess)}</div>
                  <div style={{ color: C.textMuted, fontSize: "0.72rem" }}>Beat SPY {s.beat_spy_rate != null ? `${s.beat_spy_rate.toFixed(0)}%` : "—"}</div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" }}>
          <thead>
            <tr style={{ color: C.textMuted, textAlign: "left" }}>
              <th style={{ padding: "4px 8px" }}>Ticker</th>
              <th style={{ padding: "4px 8px" }}>Disclosed</th>
              <th style={{ padding: "4px 8px" }}>Entry</th>
              {WINDOWS.map((w) => <th key={w} style={{ padding: "4px 8px", textAlign: "right" }}>{w}d</th>)}
              {WINDOWS.map((w) => <th key={"x" + w} style={{ padding: "4px 8px", textAlign: "right" }}>vs SPY {w}d</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.trade_id} style={{ borderTop: "1px solid var(--c-surfaceAlt)" }}>
                <td style={{ padding: "5px 8px" }}><Link to={`/ticker/${t.ticker}`} style={{ color: C.accent, fontWeight: 700, textDecoration: "none" }}>{t.ticker}</Link></td>
                <td style={{ padding: "5px 8px", color: C.textSoft, whiteSpace: "nowrap" }}>{t.disclosure_date}</td>
                <td style={{ padding: "5px 8px", color: C.textSoft }}>${t.entry_price.toFixed(2)}</td>
                {WINDOWS.map((w) => <td key={w} style={{ padding: "5px 8px", textAlign: "right", color: tone(t[`r${w}`]), fontWeight: 600 }}>{pct(t[`r${w}`])}</td>)}
                {WINDOWS.map((w) => <td key={"x" + w} style={{ padding: "5px 8px", textAlign: "right", color: tone(t[`x${w}`]) }}>{pct(t[`x${w}`])}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.trades.length > 10 && (
        <button onClick={() => setShowAll((v) => !v)}
          style={{ marginTop: 8, background: "none", border: "none", color: C.accent, cursor: "pointer", fontSize: "0.8rem", padding: 0 }}>
          {showAll ? "Show fewer" : `Show all ${data.trades.length}`}
        </button>
      )}
    </div>
  );
}
