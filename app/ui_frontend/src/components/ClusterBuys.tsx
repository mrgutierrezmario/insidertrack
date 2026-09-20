import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { C, card } from "../lib/theme";
import { getInsiderClusters } from "../lib/api";
import { fmtDate } from "../lib/format";
import type { InsiderCluster } from "../types/api";
import WatchlistButton from "./WatchlistButton";

function dollars(n: number): string {
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n}`;
}

/**
 * Market-wide cluster buys: tickers where two or more insiders bought on the
 * open market recently. Comes from the daily EDGAR feed, so it covers stocks
 * no member of Congress touched — the part of Form 4 the score can't see.
 */
export default function ClusterBuys() {
  const [data, setData] = useState<{ days: number; items: InsiderCluster[] } | null>(null);
  useEffect(() => {
    getInsiderClusters().then((r) => setData(r.data)).catch(() => setData({ days: 30, items: [] }));
  }, []);
  if (!data || data.items.length === 0) return null;
  return (
    <div style={{ ...card, padding: "12px 16px", marginBottom: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
        <div style={{ fontWeight: 600, fontSize: "0.9rem" }}>Cluster buys — last {data.days} days, market-wide</div>
        <div style={{ color: C.textMuted, fontSize: 11 }}
          data-tip="Two or more different insiders buying their own company's stock on the open market in the same window. Several people with inside knowledge putting in their own money is the strongest Form 4 pattern. Includes companies no member of Congress traded.">
          2+ insiders buying · by dollars
        </div>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" }}>
          <thead>
            <tr style={{ color: C.textMuted, textAlign: "left" }}>
              <th style={{ padding: "4px 8px" }}>Ticker</th>
              <th style={{ padding: "4px 8px" }}>Company</th>
              <th style={{ padding: "4px 8px", textAlign: "right" }}>Insiders</th>
              <th style={{ padding: "4px 8px", textAlign: "right" }}>Buys</th>
              <th style={{ padding: "4px 8px", textAlign: "right" }}>Bought</th>
              <th style={{ padding: "4px 8px" }}>Last buy</th>
            </tr>
          </thead>
          <tbody>
            {data.items.slice(0, 15).map((c) => (
              <tr key={c.ticker} style={{ borderTop: "1px solid var(--c-surfaceAlt)" }}>
                <td style={{ padding: "5px 8px", whiteSpace: "nowrap" }}>
                  <Link to={`/ticker/${c.ticker}`} style={{ color: C.accent, fontWeight: 700, textDecoration: "none" }}>{c.ticker}</Link>
                  {" "}<WatchlistButton ticker={c.ticker} />
                </td>
                <td style={{ padding: "5px 8px", color: C.textSoft, maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.company}</td>
                <td style={{ padding: "5px 8px", textAlign: "right", color: C.success, fontWeight: 700 }}>{c.buyers}</td>
                <td style={{ padding: "5px 8px", textAlign: "right", color: C.textSoft }}>{c.buys}</td>
                <td style={{ padding: "5px 8px", textAlign: "right", color: C.text, fontWeight: 600 }}>{dollars(c.dollars)}</td>
                <td style={{ padding: "5px 8px", color: C.textMuted, whiteSpace: "nowrap" }}>{fmtDate(c.last_buy)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
