import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { C } from "../lib/theme";
import { getWhaleTrackRecord } from "../lib/api";
import { fmtDate } from "../lib/format";
import { WindowCards, pct, tone } from "./TrackRecord";
import type { HolderRecord as HR, HolderRecordTrade } from "../types/api";

const WINDOWS = ["30", "60", "90"] as const;
const CHANGE_LABEL: Record<HolderRecordTrade["change"], string> = { new: "NEW", increased: "↑ ADD", decreased: "↓ TRIM", closed: "✕ CLOSED" };

function Head({ children }: { children: string }) {
  return (
    <h2 style={{ fontSize: "0.9rem", fontWeight: 600, color: C.textMuted, marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.05em" }}>
      {children}
    </h2>
  );
}

function Rows({ trades }: { trades: HolderRecordTrade[] }) {
  const [showAll, setShowAll] = useState(false);
  const rows = showAll ? trades : trades.slice(0, 10);
  return (
    <>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" }}>
          <thead>
            <tr style={{ color: C.textMuted, textAlign: "left" }}>
              <th style={{ padding: "4px 8px" }}>Ticker</th>
              <th style={{ padding: "4px 8px" }}>Move</th>
              <th style={{ padding: "4px 8px" }}>Filed</th>
              <th style={{ padding: "4px 8px" }}>Entry</th>
              {WINDOWS.map((w) => <th key={w} style={{ padding: "4px 8px", textAlign: "right" }}>{w}d</th>)}
              {WINDOWS.map((w) => <th key={"x" + w} style={{ padding: "4px 8px", textAlign: "right" }}>vs SPY {w}d</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.position_id} style={{ borderTop: "1px solid var(--c-surfaceAlt)" }}>
                <td style={{ padding: "5px 8px" }}><Link to={`/ticker/${t.ticker}`} style={{ color: C.accent, fontWeight: 700, textDecoration: "none" }}>{t.ticker}</Link></td>
                <td style={{ padding: "5px 8px", color: C.textSoft, fontSize: "0.72rem", fontWeight: 700 }}>{CHANGE_LABEL[t.change] ?? t.change}</td>
                <td style={{ padding: "5px 8px", color: C.textSoft, whiteSpace: "nowrap" }}>{fmtDate(t.public_on)}</td>
                <td style={{ padding: "5px 8px", color: C.textSoft }}>${t.entry_price.toFixed(2)}</td>
                {WINDOWS.map((w) => <td key={w} style={{ padding: "5px 8px", textAlign: "right", color: tone(t[`r${w}`]), fontWeight: 600 }}>{pct(t[`r${w}`])}</td>)}
                {WINDOWS.map((w) => <td key={"x" + w} style={{ padding: "5px 8px", textAlign: "right", color: tone(t[`x${w}`]) }}>{pct(t[`x${w}`])}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {trades.length > 10 && (
        <button onClick={() => setShowAll((v) => !v)}
          style={{ marginTop: 8, background: "none", border: "none", color: C.accent, cursor: "pointer", fontSize: "0.8rem", padding: 0 }}>
          {showAll ? "Show fewer" : `Show all ${trades.length}`}
        </button>
      )}
    </>
  );
}

/**
 * How a fund's 13F moves performed after the filing became public. A 13F
 * is filed up to 45 days after quarter end, so the clock starts at the
 * filing date — the first day anyone could have copied the trade.
 */
export default function HolderRecord({ holderId }: { holderId: number }) {
  const [data, setData] = useState<HR | null>(null);
  const [state, setState] = useState<"loading" | "ok" | "error">("loading");

  useEffect(() => {
    setState("loading");
    getWhaleTrackRecord(holderId)
      .then((r) => { setData(r.data); setState("ok"); })
      .catch(() => setState("error"));
  }, [holderId]);

  if (state === "loading") return <div style={{ marginBottom: "1.5rem" }}><Head>Track record — new & increased positions</Head><p style={{ color: C.textMuted, fontSize: "0.85rem" }}>Computing from price history…</p></div>;
  if (state === "error" || !data) return <div style={{ marginBottom: "1.5rem" }}><Head>Track record — new & increased positions</Head><p style={{ color: C.textMuted, fontSize: "0.85rem" }}>Track record unavailable right now.</p></div>;
  if (data.buys.evaluated === 0 && data.sells.evaluated === 0) {
    return (
      <div style={{ marginBottom: "1.5rem" }}>
        <Head>Track record — new & increased positions</Head>
        <p style={{ color: C.textMuted, fontSize: "0.85rem" }}>
          No position changes old enough to measure yet (a filing needs 30 days on the record). The first quarter a fund is tracked only establishes its holdings.
        </p>
      </div>
    );
  }

  return (
    <div style={{ marginBottom: "1.5rem" }}>
      {data.buys.evaluated > 0 && (
        <>
          <Head>Track record — new & increased positions</Head>
          <p style={{ color: C.textMuted, fontSize: "0.8rem", margin: "0 0 10px" }}>
            {data.buys.evaluated} position{data.buys.evaluated === 1 ? "" : "s"} measured from the first close after the 13F was filed — the earliest anyone could have followed it. "vs SPY" is the return minus SPY over the same days.
          </p>
          <WindowCards windows={data.buys.windows} />
          <Rows trades={data.buys.trades} />
        </>
      )}
      {data.sells.evaluated > 0 && (
        <div style={{ marginTop: data.buys.evaluated > 0 ? "1.25rem" : 0 }}>
          <Head>Track record — trimmed & closed positions</Head>
          <p style={{ color: C.textMuted, fontSize: "0.8rem", margin: "0 0 10px" }}>
            {data.sells.evaluated} position{data.sells.evaluated === 1 ? "" : "s"} measured the same way. A trim was a good call if the stock then <em>fell</em> (or lagged SPY) — so here down is green.
          </p>
          <WindowCards windows={data.sells.windows} invert />
          <Rows trades={data.sells.trades} />
        </div>
      )}
    </div>
  );
}
