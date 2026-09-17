import { C } from "../lib/theme";
import { useState } from "react";
import { getAiSummary } from "../lib/api";
import { Link } from "react-router-dom";
import { readOwnAi } from "../lib/storage";
import useAdmin from "../hooks/useAdmin";

interface SummaryData {
  available: boolean;
  message?: string;
  why_today?: string | null;
  bull_case?: string | null;
  bear_case?: string | null;
  risk_note?: string | null;
  model?: string;
  generated_at?: string;
  fallback?: string | null;
  fallback_reason?: string | null;
  source?: "own" | "site";
}

const PROVIDER_LABEL: Record<string, string> = { claude: "Claude", gemini: "Gemini", openai: "OpenAI" };
function providerLabel(model?: string): string {
  if (!model) return "";
  const [p, m] = model.split("/");
  return m ? `${PROVIDER_LABEL[p] ?? p} · ${m}` : model;
}

function Section({ label, color, text }: { label: string; color: string; text: string | null | undefined }) {
  if (!text) return null;
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ color, fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 3 }}>
        {label}
      </div>
      <div style={{ color: "var(--c-text)", fontSize: 13, lineHeight: 1.55 }}>{text}</div>
    </div>
  );
}

export default function AiSummaryPanel({ symbol }: { symbol: string }) {
  const [data, setData] = useState<SummaryData | null>(null);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const isAdmin = useAdmin();

  const generate = async (refresh = false) => {
    setLoading(true);
    try {
      const r = await getAiSummary(symbol, refresh);
      setData(r.data as SummaryData);
    } catch {
      setData({ available: false, message: "Could not reach the AI service." });
    } finally {
      setLoading(false);
      setLoaded(true);
    }
  };

  return (
    <div style={{
      background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 10,
      padding: "16px 18px", marginTop: "2rem", marginBottom: "2rem",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <div style={{ color: C.textBright, fontWeight: 600, fontSize: 14 }}>
            ✨ AI Research Note
          </div>
          <div style={{ color: C.dividerStrong, fontSize: 11, marginTop: 2 }}>
            Bull/bear thesis generated from this app's signal, insider, and whale data.
          </div>
        </div>
        {/* Regenerating costs a call: allowed with your own key, or for the admin on the site key. */}
        {loaded && data?.available && (readOwnAi() || isAdmin) ? (
          <button
            onClick={() => generate(true)}
            disabled={loading}
            style={{ background: C.surfaceAlt, color: C.textSoft, border: "1px solid var(--c-divider)", borderRadius: 6, padding: "5px 12px", fontSize: 12, cursor: "pointer" }}
          >
            {loading ? "…" : "↻ Regenerate"}
          </button>
        ) : (
          <button
            onClick={() => generate(false)}
            disabled={loading}
            style={{ background: "rgba(56,189,248,0.1)", color: C.accent, border: "1px solid rgba(56,189,248,0.3)", borderRadius: 6, padding: "5px 14px", fontSize: 12, cursor: "pointer" }}
          >
            {loading ? "Generating…" : "Generate"}
          </button>
        )}
      </div>

      {loaded && data && (
        <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--c-surfaceAlt)" }}>
          {data.available ? (
            <>
              {data.why_today && (
                <div style={{ background: C.bg, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8, padding: "10px 12px", marginBottom: 14, color: C.text, fontSize: 13, fontStyle: "italic" }}>
                  {data.why_today}
                </div>
              )}
              <Section label="Bull Case" color={C.success} text={data.bull_case} />
              <Section label="Bear Case" color={C.danger} text={data.bear_case} />
              <Section label="Key Risk" color={C.warning} text={data.risk_note} />
              <div style={{ color: C.divider, fontSize: 10, marginTop: 8 }}>
                {providerLabel(data.model)}{data.source === "own" ? " (your key)" : ""} · {data.generated_at} · Not financial advice — informational only.
                {data.fallback && <> · {PROVIDER_LABEL[data.fallback] ?? data.fallback} was {data.fallback_reason ?? "unavailable"}, so another provider answered.</>}
              </div>
            </>
          ) : (
            <div style={{ color: C.warningSolid, fontSize: 12 }}>
              {data.message || "AI summaries are not available."}{" "}
              <Link to="/config" style={{ color: C.accent }}>Open Settings →</Link>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
