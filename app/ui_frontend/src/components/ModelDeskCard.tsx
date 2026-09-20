import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { C } from "../lib/theme";
import { fmtDate } from "../lib/format";
import { getModelDeskToday } from "../lib/api";
import type { ModelCall, ModelDeskToday } from "../types/api";

export function CallRow({ c, compact = false }: { c: ModelCall; compact?: boolean }) {
  const up = c.direction === "bullish";
  const color = up ? C.success : C.danger;
  return (
    <div style={{ padding: compact ? "0.5rem 0.9rem" : "0.65rem 0.9rem", borderBottom: "1px solid var(--c-surfaceAlt)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <Link to={`/ticker/${c.ticker}`} style={{ color: C.accent, fontWeight: 700, textDecoration: "none", width: 64 }}>{c.ticker}</Link>
        <span style={{ color, fontWeight: 700, fontSize: "0.78rem", letterSpacing: "0.04em" }}>{up ? "▲ BULLISH" : "▼ BEARISH"}</span>
        <span style={{ color: C.textMuted, fontSize: "0.78rem" }}>{c.horizon_days}d</span>
        {c.confidence != null && <span style={{ color: C.textDim, fontSize: "0.75rem" }}>conf {Math.round(c.confidence * 100)}%</span>}
        <span style={{ marginLeft: "auto", fontSize: "0.78rem", fontWeight: 700, color: c.outcome === "hit" ? C.success : c.outcome === "miss" ? C.danger : C.textDim }}
          data-tip={c.outcome ? `Return ${c.return_pct}% vs SPY ${c.spy_return_pct}% → ${c.excess_pct! > 0 ? "+" : ""}${c.excess_pct}%` : `Scored on ${fmtDate(c.resolves_on)}`}>
          {c.outcome ? `${c.outcome.toUpperCase()} · ${c.excess_pct! > 0 ? "+" : ""}${c.excess_pct}% vs SPY` : `scores ${fmtDate(c.resolves_on)}`}
        </span>
      </div>
      {!compact && c.reasoning && <div style={{ color: C.textMuted, fontSize: "0.8rem", marginTop: 4, lineHeight: 1.5 }}>{c.reasoning}</div>}
    </div>
  );
}

/**
 * Dashboard card: the model's calls for today and its running score. The
 * calls are measured like everything else on the site; the score is the point.
 */
export default function ModelDeskCard() {
  const [data, setData] = useState<ModelDeskToday | null>(null);
  useEffect(() => { getModelDeskToday().then((r) => setData(r.data)).catch(() => setData(null)); }, []);
  if (!data || !data.brief) return null;
  const s = data.stats;
  return (
    <div style={{ marginBottom: "1.75rem" }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
        <h2 style={{ fontSize: "1rem", fontWeight: 600, margin: 0 }}>Model desk — {fmtDate(data.brief.date)}</h2>
        <Link to="/model-desk" style={{ color: C.textMuted, fontSize: "0.8rem", textDecoration: "none" }}>
          {s.resolved > 0 ? `${s.hit_rate}% right vs SPY over ${s.resolved} scored calls · track record →` : "Track record →"}
        </Link>
      </div>
      <div style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 10, overflow: "hidden" }}>
        <p style={{ color: C.textSoft, fontSize: "0.88rem", lineHeight: 1.6, margin: 0, padding: "0.85rem 0.9rem", borderBottom: "1px solid var(--c-surfaceAlt)" }}>{data.brief.summary}</p>
        {data.calls.map((c) => <CallRow key={c.id} c={c} />)}
        <p style={{ color: C.textDim, fontSize: "0.72rem", margin: 0, padding: "0.5rem 0.9rem" }}>
          Written by {data.brief.provider ?? "the site's AI model"} from today's disclosures. Every call is scored at its horizon against the S&amp;P 500 — that scorecard, not the calls, is the point. Not advice.
        </p>
      </div>
    </div>
  );
}
