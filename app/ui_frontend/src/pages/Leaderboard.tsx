import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { C } from "../lib/theme";
import useDocumentTitle from "../hooks/useDocumentTitle";
import { getLeaderboard } from "../lib/api";
import { chamberLabel, fmtDate } from "../lib/format";
import type { Leaderboard as LB, LeaderboardRow } from "../types/api";

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${v.toFixed(0)}%`;
}
function tone(rate: number | null | undefined): string {
  if (rate == null) return C.textMuted;
  return rate > 55 ? C.success : rate < 45 ? C.danger : C.textSoft;
}

function Row({ r }: { r: LeaderboardRow }) {
  return (
    <tr style={{ borderTop: "1px solid var(--c-surfaceAlt)" }}>
      <td style={{ padding: "7px 8px", color: C.textMuted, width: 40 }}>{r.rank ?? "—"}</td>
      <td style={{ padding: "7px 8px" }}>
        <Link to={`/politician/${r.id}`} style={{ color: C.accent, fontWeight: 700, textDecoration: "none" }}>{r.name}</Link>
        <span style={{ color: C.textMuted, fontSize: "0.75rem", marginLeft: 8 }}>{[r.party, chamberLabel(r.chamber), r.state].filter(Boolean).join(" · ")}</span>
      </td>
      <td style={{ padding: "7px 8px", textAlign: "right", color: C.textSoft }}>{r.buys_measured ?? "—"}</td>
      <td style={{ padding: "7px 8px", textAlign: "right", color: tone(r.beat_spy_rate), fontWeight: 700 }}>{pct(r.beat_spy_rate)}</td>
      <td style={{ padding: "7px 8px", textAlign: "right", color: C.textSoft }}>{r.skill_factor != null ? `×${r.skill_factor.toFixed(2)}` : "—"}</td>
    </tr>
  );
}

/**
 * Who is actually good. Members ranked by how often their disclosed stock
 * buys beat SPY at 90 days — the same number that weights their trades in
 * the score. Recomputed weekly.
 */
export default function Leaderboard() {
  useDocumentTitle("Leaderboard");
  const [data, setData] = useState<LB | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    getLeaderboard().then((r) => setData(r.data)).catch(() => setError("Could not load the leaderboard."));
  }, []);

  return (
    <div style={{ maxWidth: 900, margin: "0 auto" }}>
      <div className="page-head">
        <div>
          <h1>Leaderboard</h1>
          <p>Members ranked by how often their stock buys beat the S&amp;P 500 at 90 days after disclosure. The same number sets each member's weight in the score.</p>
          {data?.as_of && <p style={{ color: C.textDim, fontSize: 12, margin: "4px 0 0" }}>Measured {fmtDate(data.as_of)} · recomputed weekly · at least {data.min_trades} measured buys to rank</p>}
        </div>
      </div>
      {error && <p style={{ color: C.danger }}>{error}</p>}
      {data && data.ranked.length === 0 && !error && (
        <p style={{ color: C.textMuted }}>No member has {data.min_trades} measured buys yet — the weekly job hasn't run, or the history is too short.</p>
      )}
      {data && data.ranked.length > 0 && (
        <div style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 10, padding: "0.5rem 0.5rem 0.25rem", overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.88rem" }}>
            <thead>
              <tr style={{ color: C.textMuted, textAlign: "left", fontSize: "0.75rem" }}>
                <th style={{ padding: "6px 8px" }}>#</th>
                <th style={{ padding: "6px 8px" }}>Member</th>
                <th style={{ padding: "6px 8px", textAlign: "right" }}>Buys measured</th>
                <th style={{ padding: "6px 8px", textAlign: "right" }} data-tip="Share of their stock buys that beat SPY over the 90 days after disclosure">Beat SPY (90d)</th>
                <th style={{ padding: "6px 8px", textAlign: "right" }} data-tip="Weight applied to this member's trades in the Congress sub-score: ×0.5 (always wrong) to ×1.5 (always right)">Weight</th>
              </tr>
            </thead>
            <tbody>{data.ranked.map((r) => <Row key={r.id} r={r} />)}</tbody>
          </table>
        </div>
      )}
      {data && data.unranked.length > 0 && (
        <details style={{ marginTop: "1rem", color: C.textMuted, fontSize: "0.85rem" }}>
          <summary style={{ cursor: "pointer" }}>{data.unranked.length} members with fewer than {data.min_trades} measured buys (unranked, weight ×1.00)</summary>
          <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 6 }}>
            {data.unranked.map((r) => (
              <Link key={r.id} to={`/politician/${r.id}`} style={{ color: C.accent, textDecoration: "none", background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, padding: "3px 8px", fontSize: "0.8rem" }}>
                {r.name} <span style={{ color: C.textDim }}>({r.buys_measured})</span>
              </Link>
            ))}
          </div>
        </details>
      )}
      <p style={{ color: C.textDim, fontSize: "0.75rem", marginTop: "1.25rem" }}>
        A member's buys are measured from the first close after the public could see the filing. Past performance is not a forecast; this ranks disclosed history, nothing more.
      </p>
    </div>
  );
}
