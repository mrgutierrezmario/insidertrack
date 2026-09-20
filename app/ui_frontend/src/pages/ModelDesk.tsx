import { useEffect, useState } from "react";
import { C } from "../lib/theme";
import useDocumentTitle from "../hooks/useDocumentTitle";
import useAdmin from "../hooks/useAdmin";
import { fmtDate } from "../lib/format";
import { generateModelDesk, getModelDeskCalls, getModelDeskToday } from "../lib/api";
import { CallRow } from "../components/ModelDeskCard";
import type { ModelCall, ModelDeskStats, ModelDeskToday } from "../types/api";

function Stat({ label, value, tip }: { label: string; value: string; tip?: string }) {
  return (
    <div style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8, padding: "0.75rem 1rem" }} data-tip={tip}>
      <div style={{ color: C.textMuted, fontSize: "0.72rem", fontWeight: 700, letterSpacing: "0.05em", textTransform: "uppercase" }}>{label}</div>
      <div style={{ color: C.text, fontSize: "1.3rem", fontWeight: 700, marginTop: 4 }}>{value}</div>
    </div>
  );
}

/**
 * The model's track record: every call it has made, what happened, and the
 * hit-rate — sitting next to the human leaderboard on purpose.
 */
export default function ModelDesk() {
  useDocumentTitle("Model desk");
  const isAdmin = useAdmin();
  const [today, setToday] = useState<ModelDeskToday | null>(null);
  const [calls, setCalls] = useState<ModelCall[]>([]);
  const [stats, setStats] = useState<ModelDeskStats | null>(null);
  const [msg, setMsg] = useState("");
  const load = () => {
    getModelDeskToday().then((r) => setToday(r.data)).catch(() => {});
    getModelDeskCalls().then((r) => { setCalls(r.data.items); setStats(r.data.stats); }).catch(() => {});
  };
  useEffect(load, []);
  const run = async (force: boolean) => {
    setMsg("Generating — 20–40 s…");
    try { await generateModelDesk(force); setTimeout(() => { load(); setMsg(""); }, 35000); } catch { setMsg("Could not start."); }
  };
  const pct = (v: number | null | undefined) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%`);

  return (
    <div style={{ maxWidth: 1000, margin: "0 auto" }}>
      <div className="page-head">
        <div>
          <h1>Model desk</h1>
          <p>Each morning the site's AI model reads the day's disclosures and makes 3–5 directional calls. They're measured at their horizon against the S&amp;P 500, exactly like members' trades — so this page is a scorecard, not a forecast.</p>
        </div>
        {isAdmin && (
          <div className="page-head__actions">
            <button onClick={() => run(false)} style={{ background: C.accentSolid, color: "#fff", border: "none", borderRadius: 6, padding: "0.45rem 1rem", cursor: "pointer", fontSize: "0.85rem" }}>Generate today</button>
            <button onClick={() => run(true)} style={{ background: C.surfaceAlt, color: C.textSoft, border: "none", borderRadius: 6, padding: "0.45rem 1rem", cursor: "pointer", fontSize: "0.85rem" }}>Regenerate</button>
            {msg && <span style={{ color: C.textMuted, fontSize: "0.8rem" }}>{msg}</span>}
          </div>
        )}
      </div>

      {stats && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "0.75rem", marginBottom: "1.5rem" }}>
          <Stat label="Right vs SPY" value={stats.hit_rate != null ? `${stats.hit_rate}%` : "—"} tip="Share of scored calls where the direction was right relative to SPY over the horizon" />
          <Stat label="Avg excess" value={pct(stats.avg_excess)} tip="Average return minus SPY over the same days, across scored calls" />
          <Stat label="Scored" value={String(stats.resolved)} />
          <Stat label="Pending" value={String(stats.pending)} tip="Calls whose horizon hasn't passed yet" />
          {Object.entries(stats.by_horizon).map(([h, v]) => <Stat key={h} label={`${h}-day calls`} value={`${v.hit_rate}% · n=${v.n}`} />)}
        </div>
      )}

      {today?.brief && (
        <div style={{ marginBottom: "1.5rem" }}>
          <h2 style={{ fontSize: "0.9rem", fontWeight: 600, color: C.textMuted, marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.05em" }}>Today — {fmtDate(today.brief.date)}</h2>
          <div style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 10, overflow: "hidden" }}>
            <p style={{ color: C.textSoft, fontSize: "0.88rem", lineHeight: 1.6, margin: 0, padding: "0.85rem 0.9rem", borderBottom: "1px solid var(--c-surfaceAlt)" }}>{today.brief.summary}</p>
            {today.calls.map((c) => <CallRow key={c.id} c={c} />)}
          </div>
        </div>
      )}
      {!today?.brief && <p style={{ color: C.textMuted }}>No brief yet — the first one is written at 8:30 AM ET after the morning sync{isAdmin ? ", or generate it now" : ""}.</p>}

      {calls.length > 0 && (
        <div>
          <h2 style={{ fontSize: "0.9rem", fontWeight: 600, color: C.textMuted, marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.05em" }}>All calls</h2>
          <div style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 10, overflow: "hidden" }}>
            {calls.map((c) => (
              <div key={c.id} style={{ display: "grid", gridTemplateColumns: "96px 1fr", alignItems: "start" }}>
                <div style={{ color: C.textDim, fontSize: "0.75rem", padding: "0.6rem 0 0 0.9rem" }}>{fmtDate(c.call_date)}</div>
                <CallRow c={c} />
              </div>
            ))}
          </div>
        </div>
      )}
      <p style={{ color: C.textDim, fontSize: "0.75rem", marginTop: "1.25rem" }}>
        A language model has no information this site doesn't already show; what it adds is a reading of the day's data, and what this page adds is the score. Calls are stored as written and never edited. Not financial advice.
      </p>
    </div>
  );
}
