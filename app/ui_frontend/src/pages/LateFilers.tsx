import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { C } from "../lib/theme";
import useDocumentTitle from "../hooks/useDocumentTitle";
import { getLateFilers } from "../lib/api";
import { chamberLabel, fmtDate } from "../lib/format";
import { safeHref } from "../lib/safeUrl";
import type { LateFilerRow, LateFilers as LF } from "../types/api";

const WINDOWS = [
  { days: undefined, label: "All time" },
  { days: 365, label: "Last 12 months" },
] as const;

const SORTS = {
  late: { label: "Most late trades", key: (r: LateFilerRow) => r.late_trades },
  pct: { label: "Highest share late", key: (r: LateFilerRow) => r.late_pct },
  worst: { label: "Longest delay", key: (r: LateFilerRow) => r.worst.lag_days },
} as const;
type SortKey = keyof typeof SORTS;

function days(n: number): string {
  return n >= 730 ? `${(n / 365).toFixed(1)} yrs` : `${n.toLocaleString()} days`;
}

function Row({ r }: { r: LateFilerRow }) {
  return (
    <tr style={{ borderTop: "1px solid var(--c-surfaceAlt)" }}>
      <td style={{ padding: "7px 8px" }}>
        <Link to={`/politician/${r.id}`} style={{ color: C.accent, fontWeight: 700, textDecoration: "none" }}>{r.name}</Link>
        <span style={{ color: C.textMuted, fontSize: "0.75rem", marginLeft: 8 }}>{[r.party, chamberLabel(r.chamber), r.state].filter(Boolean).join(" · ")}</span>
      </td>
      <td style={{ padding: "7px 8px", textAlign: "right", color: C.text, fontWeight: 700, whiteSpace: "nowrap" }}>
        {r.late_trades.toLocaleString()}
        <span style={{ color: C.textDim, fontWeight: 400 }}> / {r.trades.toLocaleString()}</span>
      </td>
      <td style={{ padding: "7px 8px", textAlign: "right", color: r.late_pct >= 50 ? C.danger : C.textSoft }}>{r.late_pct.toFixed(0)}%</td>
      <td style={{ padding: "7px 8px", textAlign: "right", color: C.textSoft }}>{r.late_filings}</td>
      <td style={{ padding: "7px 8px", textAlign: "right", color: C.textSoft, whiteSpace: "nowrap" }}>{days(r.median_lag_days)}</td>
      <td style={{ padding: "7px 8px", textAlign: "right", whiteSpace: "nowrap" }}
          data-tip={`Traded ${fmtDate(r.worst.trade_date)}, disclosed ${fmtDate(r.worst.disclosure_date)}`}>
        {r.worst.filing_url
          ? <a href={safeHref(r.worst.filing_url)} target="_blank" rel="noreferrer" style={{ color: C.textSoft }}>{days(r.worst.lag_days)} ↗</a>
          : <span style={{ color: C.textSoft }}>{days(r.worst.lag_days)}</span>}
      </td>
      <td style={{ padding: "7px 8px", textAlign: "right", color: C.textMuted, whiteSpace: "nowrap" }}>{fmtDate(r.latest_late_disclosure)}</td>
    </tr>
  );
}

/**
 * Who discloses late. The STOCK Act gives members 45 days at most from a
 * trade to report it; this ranks members by how many of their trades came
 * in after that.
 */
export default function LateFilers() {
  useDocumentTitle("Late Filers");
  const [windowDays, setWindowDays] = useState<number | undefined>(undefined);
  const [sort, setSort] = useState<SortKey>("late");
  const [data, setData] = useState<LF | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setError("");
    getLateFilers(windowDays)
      .then((r) => { if (!cancelled) setData(r.data); })
      .catch(() => { if (!cancelled) setError("Could not load late filers."); });
    return () => { cancelled = true; };
  }, [windowDays]);

  const rows = useMemo(() => {
    if (!data) return [];
    const k = SORTS[sort].key;
    return [...data.items].sort((a, b) => k(b) - k(a) || b.late_trades - a.late_trades);
  }, [data, sort]);

  const pill = (active: boolean) => ({
    background: active ? C.accentSolid : C.surfaceAlt,
    color: active ? "#fff" : C.textSoft,
    border: "none", borderRadius: 6, padding: "0.35rem 0.9rem", cursor: "pointer", fontSize: "0.82rem",
  });

  return (
    <div style={{ maxWidth: 1000, margin: "0 auto" }}>
      <div className="page-head">
        <div>
          <h1>Late Filers</h1>
          <p>Members of Congress ranked by trades they disclosed more than {data?.late_after_days ?? 45} days after making them, the latest the STOCK Act allows.</p>
        </div>
      </div>

      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center", marginBottom: "1rem" }}>
        {WINDOWS.map((w) => (
          <button key={w.label} onClick={() => setWindowDays(w.days)} style={pill(windowDays === w.days)}>{w.label}</button>
        ))}
        <label style={{ marginLeft: "auto", color: C.textMuted, fontSize: "0.8rem", display: "flex", gap: 6, alignItems: "center" }}>
          Sort
          <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}
            style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, color: C.textBright, padding: "4px 8px", fontSize: "0.8rem" }}>
            {Object.entries(SORTS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
        </label>
      </div>

      {error && <p style={{ color: C.danger }}>{error}</p>}

      {data && (
        <p style={{ color: C.textSoft, fontSize: "0.88rem", margin: "0 0 1rem" }}>
          <strong style={{ color: C.text }}>{data.late_trades.toLocaleString()}</strong> of {data.trades.toLocaleString()} trades
          {data.late_pct != null && <> ({data.late_pct.toFixed(1)}%)</>} were disclosed late, by{" "}
          <strong style={{ color: C.text }}>{data.members_late}</strong> of {data.members_with_trades} members who filed
          {data.window_days ? ` in the last ${data.window_days === 365 ? "12 months" : `${data.window_days} days`}` : ""}.
        </p>
      )}

      {data && rows.length === 0 && !error && (
        <p style={{ color: C.textMuted }}>No late disclosures in this window.</p>
      )}

      {rows.length > 0 && (
        <div style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 10, padding: "0.5rem 0.5rem 0.25rem", overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.88rem" }}>
            <thead>
              <tr style={{ color: C.textMuted, textAlign: "left", fontSize: "0.75rem" }}>
                <th style={{ padding: "6px 8px" }}>Member</th>
                <th style={{ padding: "6px 8px", textAlign: "right" }} data-tip="Trades disclosed late, out of all their trades in this window">Late / all trades</th>
                <th style={{ padding: "6px 8px", textAlign: "right" }}>Share late</th>
                <th style={{ padding: "6px 8px", textAlign: "right" }} data-tip="Separate reports that contained at least one late trade">Late reports</th>
                <th style={{ padding: "6px 8px", textAlign: "right" }} data-tip="Median time from trade to disclosure, across their late trades">Typical delay</th>
                <th style={{ padding: "6px 8px", textAlign: "right" }} data-tip="Their longest gap between a trade and its disclosure; links to the filing">Longest</th>
                <th style={{ padding: "6px 8px", textAlign: "right" }}>Latest late report</th>
              </tr>
            </thead>
            <tbody>{rows.map((r) => <Row key={r.id} r={r} />)}</tbody>
          </table>
        </div>
      )}

      <p style={{ color: C.textDim, fontSize: "0.75rem", marginTop: "1.25rem" }}>
        A report is due 30 days after the member learns of a trade and no later than 45 days after it. Filings don't
        always say when the member was notified, so this uses the 45-day outer limit, measured from the trade date to
        the date the report was filed. Amended reports keep the original report's date. Late often means one large
        catch-up report covering many trades.
      </p>
    </div>
  );
}
