import { useEffect, useState } from "react";
import { C } from "../lib/theme";
import { getHealth } from "../lib/api";
import type { HealthSource, HealthSourceStatus } from "../types/api";

const STATUS_META: Record<HealthSourceStatus, { label: string; color: string }> = {
  ok:      { label: "OK",      color: C.success },
  stale:   { label: "STALE",   color: C.warningSolid },
  failing: { label: "FAILING", color: C.danger },
  never:   { label: "NO RUN",  color: C.textMuted },
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

  useEffect(() => {
    getHealth()
      .then((r) => setSources(r.data.data?.sources ?? {}))
      .catch(() => setError("Could not load /health"));
  }, []);

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
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
