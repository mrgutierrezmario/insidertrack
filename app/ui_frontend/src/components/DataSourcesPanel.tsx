import { useEffect, useState } from "react";
import { C } from "../lib/theme";
import { getBackfillStatus, getHealth, startBackfill, syncInsiders, syncTrades, syncWhales } from "../lib/api";
import type { BackfillStatus } from "../lib/api";
import type { HealthSource, HealthSourceStatus } from "../types/api";

const STATUS_META: Record<HealthSourceStatus, { label: string; color: string }> = {
  ok:      { label: "OK",      color: C.success },
  stale:   { label: "STALE",   color: C.warningSolid },
  failing: { label: "FAILING", color: C.danger },
  never:   { label: "NO RUN",  color: C.textMuted },
};

// Which endpoint kicks each source. Senate and House run together (one
// congressional sync); the label says so.
const RUNNERS: Record<string, { run: () => Promise<unknown>; note: string }> = {
  senate: { run: () => syncTrades(),   note: "runs Senate + House" },
  house:  { run: () => syncTrades(),   note: "runs Senate + House" },
  form4:  { run: () => syncInsiders(), note: "every tracked ticker" },
  whale:  { run: () => syncWhales(),   note: "latest 13F per holder" },
};

function ago(iso: string | null | undefined): string {
  if (!iso) return "—";
  const ms = Date.now() - new Date(iso).getTime();
  const h = Math.floor(ms / 3_600_000);
  if (h < 1) return "just now";
  if (h < 48) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

/**
 * Admin view of scraper freshness. A government site changing a column header
 * makes the fetcher "succeed" with zero rows — this is where that shows up
 * (as STALE) instead of as an empty dashboard three weeks later.
 */
export default function DataSourcesPanel() {
  const [sources, setSources] = useState<Record<string, HealthSource> | null>(null);
  const [error, setError] = useState("");
  const [backfill, setBackfill] = useState<BackfillStatus | null>(null);
  const [since, setSince] = useState(() => `${new Date().getFullYear() - 1}-01-01`);
  const [starting, setStarting] = useState(false);
  const [running, setRunning] = useState<Record<string, "started" | "error" | undefined>>({});

  const refreshSources = () =>
    getHealth().then((r) => setSources(r.data.data?.sources ?? {})).catch(() => {});

  const runSource = async (key: string) => {
    setRunning((r) => ({ ...r, [key]: undefined }));
    try {
      await RUNNERS[key].run();
      setRunning((r) => ({ ...r, [key]: "started" }));
    } catch {
      setRunning((r) => ({ ...r, [key]: "error" }));
    }
  };

  // Once a run is kicked off, refresh the cards every 20 s so the outcome
  // shows up without a reload.
  useEffect(() => {
    if (!Object.values(running).includes("started")) return;
    const id = setInterval(refreshSources, 20000);
    return () => clearInterval(id);
  }, [running]);

  useEffect(() => {
    getHealth()
      .then((r) => setSources(r.data.data?.sources ?? {}))
      .catch(() => setError("Could not load /health"));
    getBackfillStatus().then((r) => setBackfill(r.data)).catch(() => {});
  }, []);

  // Poll while a backfill runs (it's minutes to tens of minutes).
  useEffect(() => {
    if (!backfill?.running) return;
    const id = setInterval(() => {
      getBackfillStatus().then((r) => setBackfill(r.data)).catch(() => {});
    }, 5000);
    return () => clearInterval(id);
  }, [backfill?.running]);

  const runBackfill = async () => {
    setStarting(true);
    try {
      await startBackfill(since);
      const r = await getBackfillStatus();
      setBackfill({ ...r.data, running: true });
    } catch {
      setError("Could not start backfill");
    } finally {
      setStarting(false);
    }
  };

  return (
    <section style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8, padding: "1.25rem", marginBottom: "1.5rem" }}>
      <div style={{ fontWeight: 600, marginBottom: "0.25rem" }}>Data sources</div>
      <div style={{ color: C.textMuted, fontSize: "0.8rem", marginBottom: "1rem" }}>
        Freshness of each scraper. <b>Stale</b> means runs succeed but nothing new has arrived for longer than expected — usually a site change the parser misses silently. A daily email goes to the admin address when anything is stale or failing.
      </div>
      {error && <div style={{ color: C.danger, fontSize: "0.85rem" }}>{error}</div>}
      {sources && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: "0.75rem" }}>
          {Object.entries(sources).map(([key, s]) => {
            const m = STATUS_META[s.status] ?? STATUS_META.never;
            return (
              <div key={key} style={{ border: "1px solid var(--c-bgSunken)", borderRadius: 6, padding: "0.75rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                  <span style={{ color: C.text, fontSize: "0.9rem", fontWeight: 500 }}>{s.label}</span>
                  <span style={{ color: m.color, fontSize: "0.68rem", fontWeight: 700, letterSpacing: "0.04em" }}>{m.label}</span>
                </div>
                <div style={{ color: C.textMuted, fontSize: "0.75rem", lineHeight: 1.6 }}>
                  <div>Last run: {ago(s.last_run_at)}</div>
                  <div>Last new rows: {ago(s.last_new_rows_at)}{s.last_new_rows != null ? ` (${s.last_new_rows} last run)` : ""}</div>
                  {s.last_error && <div style={{ color: C.danger, wordBreak: "break-word" }}>{s.last_error}</div>}
                </div>
                {RUNNERS[key] && (
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8 }}>
                    <button onClick={() => runSource(key)}
                      style={{ background: C.surfaceAlt, color: C.textSoft, border: "none", borderRadius: 4, padding: "3px 10px", cursor: "pointer", fontSize: "0.75rem" }}>
                      ↻ Run now
                    </button>
                    <span style={{ color: running[key] === "error" ? C.danger : running[key] === "started" ? C.success : C.textDim, fontSize: "0.7rem" }}>
                      {running[key] === "started" ? "started in background" : running[key] === "error" ? "could not start" : RUNNERS[key].note}
                    </span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <div style={{ borderTop: "1px solid var(--c-bgSunken)", marginTop: "1rem", paddingTop: "1rem" }}>
        <div style={{ fontWeight: 600, fontSize: "0.9rem", marginBottom: 4 }}>Backfill history</div>
        <div style={{ color: C.textMuted, fontSize: "0.8rem", marginBottom: "0.6rem" }}>
          The daily sync only looks back ~90 days. Import older filings from both chambers so the simulator, outcomes and per-member records have history. One PDF per filing — a full year takes tens of minutes. Safe to re-run.
        </div>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
          <label style={{ color: C.textMuted, fontSize: "0.8rem" }}>Filed since</label>
          <input type="date" value={since} onChange={(e) => setSince(e.target.value)} disabled={!!backfill?.running}
            style={{ background: C.bg, color: C.text, border: "1px solid var(--c-surfaceAlt)", borderRadius: 5, padding: "0.3rem 0.5rem", fontSize: 16 }} />
          <button onClick={runBackfill} disabled={starting || !!backfill?.running || !since}
            style={{ background: C.accentSolid, color: "#fff", border: "none", borderRadius: 5, padding: "0.35rem 0.9rem", cursor: "pointer", fontSize: "0.8rem", opacity: backfill?.running ? 0.6 : 1 }}>
            {backfill?.running ? "Running…" : "Start backfill"}
          </button>
        </div>
        {backfill && (backfill.running || backfill.finished_at) && (
          <div style={{ color: C.textMuted, fontSize: "0.78rem", marginTop: "0.5rem", lineHeight: 1.6 }}>
            {backfill.running ? (
              <>Importing {backfill.phase ?? "…"}: {backfill.done ?? 0}{backfill.total ? ` / ${backfill.total}` : ""} filings ({backfill.since} → {backfill.until})</>
            ) : (
              <>
                Last backfill {backfill.since} → {backfill.until}: {backfill.result?.senate ?? 0} Senate + {backfill.result?.house ?? 0} House trades added
                {backfill.finished_at ? ` · finished ${ago(backfill.finished_at)}` : ""}
                {backfill.error && <div style={{ color: C.danger }}>{backfill.error}</div>}
              </>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
