import { C } from "../lib/theme";
import { useEffect, useState } from "react";
import { getAiSettings, getAiModels, testAiProvider, updateSettingKey, clearSettingKey } from "../lib/api";
import type { AiSettings, ModelOption } from "../lib/api";
import { safeHref } from "../lib/safeUrl";

/** One row of /settings/keys, as AdminConfig already types it. */
export interface KeyRowData {
  key: string; label: string; description: string; is_set: boolean; source: string;
  sensitive: boolean; masked_value?: string; placeholder?: string; link?: string;
  group?: string; choices?: string[] | null;
}

const PROVIDERS = ["claude", "gemini", "openai"] as const;
type Provider = (typeof PROVIDERS)[number];
const KEY_FOR: Record<Provider, string> = { claude: "anthropic_api_key", gemini: "gemini_api_key", openai: "openai_api_key" };
const MODEL_FOR: Record<Provider, string> = { claude: "claude_model", gemini: "gemini_model", openai: "openai_model" };

const inputStyle = { background: C.bg, color: C.text, border: "1px solid var(--c-divider)", borderRadius: 5, padding: "0.4rem 0.75rem", fontSize: "0.85rem" } as const;
const btn = { border: "none", borderRadius: 5, padding: "0.4rem 0.9rem", cursor: "pointer", fontSize: "0.8rem" } as const;

/**
 * Admin panel section for AI research notes: which provider writes them, one
 * API key + model per provider, a live Gemini model list, and a Test button.
 * Mirrors the lecture app's Settings → AI providers.
 */
export default function AiProviderPanel({ keys, onChanged, onError }: { keys: KeyRowData[]; onChanged: () => Promise<void> | void; onError: (m: string) => void }) {
  const [ai, setAi] = useState<AiSettings | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [testMsg, setTestMsg] = useState<Record<string, string>>({});
  const [models, setModels] = useState<Partial<Record<Provider, ModelOption[]>>>({});
  const byKey = Object.fromEntries(keys.map((k) => [k.key, k])) as Record<string, KeyRowData | undefined>;

  const refresh = () => getAiSettings().then((r) => setAi(r.data)).catch(() => {});
  useEffect(() => { refresh(); }, [keys]);
  useEffect(() => {
    // Live model list for every provider that has a key saved.
    if (!ai) return;
    PROVIDERS.forEach((p) => {
      if (ai.providers[p].configured && models[p] === undefined) {
        getAiModels(p).then((r) => setModels((m) => ({ ...m, [p]: r.data }))).catch(() => setModels((m) => ({ ...m, [p]: [] })));
      }
    });
  }, [ai, models]);

  const save = async (key: string, value: string) => {
    setBusy((b) => ({ ...b, [key]: true }));
    try {
      await updateSettingKey(key, value.trim());
      setDraft((d) => { const n = { ...d }; delete n[key]; return n; });
      const p = (Object.keys(KEY_FOR) as Provider[]).find((x) => KEY_FOR[x] === key);
      if (p) setModels((m) => { const n = { ...m }; delete n[p]; return n; }); // re-list for the new key
      await onChanged(); await refresh();
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      onError(detail || "Failed to save.");
    } finally { setBusy((b) => ({ ...b, [key]: false })); }
  };
  const clear = async (key: string) => {
    setBusy((b) => ({ ...b, [key]: true }));
    try { await clearSettingKey(key); await onChanged(); await refresh(); }
    finally { setBusy((b) => ({ ...b, [key]: false })); }
  };
  const test = async (p: Provider) => {
    setTestMsg((m) => ({ ...m, [p]: "Testing…" }));
    try { const r = await testAiProvider(p); setTestMsg((m) => ({ ...m, [p]: (r.data.ok ? "✓ " : "✗ ") + r.data.message })); }
    catch { setTestMsg((m) => ({ ...m, [p]: "✗ Could not run the test." })); }
  };

  const chosen = (ai?.chosen ?? "claude") as Provider;

  return (
    <section style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8, padding: "1.25rem", marginBottom: "1.5rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 4 }}>
        <span style={{ fontWeight: 600 }}>AI research notes</span>
        {ai && (
          <span style={{ fontSize: "0.75rem", padding: "2px 9px", borderRadius: 4, background: ai.configured ? C.successBg : C.warningBg, color: ai.configured ? C.success : C.warningSolid }}>
            {ai.configured ? `Active: ${ai.providers[ai.active!].label} · ${ai.providers[ai.active!].model}` : "Not configured"}
          </span>
        )}
      </div>
      <p style={{ color: C.textMuted, fontSize: "0.8rem", margin: "0 0 1rem", lineHeight: 1.5 }}>
        The bull/bear note on each ticker page is written by the provider you pick here. Save a key for any of them;
        if the chosen one fails (quota, outage), the others with a key are tried as a fallback. Notes are cached 6 h.
      </p>

      {/* Provider choice */}
      <div style={{ color: C.textMuted, fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>Writes the notes</div>
      <div className="segmented" role="group" aria-label="AI provider" style={{ marginBottom: "1.25rem" }}>
        {PROVIDERS.map((p) => (
          <button key={p} type="button" aria-pressed={chosen === p} disabled={busy.ai_provider} onClick={() => save("ai_provider", p)}>
            {ai?.providers[p].label ?? p}{ai && !ai.providers[p].configured ? " (no key)" : ""}
          </button>
        ))}
      </div>

      {/* One card per provider */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "0.75rem" }}>
        {PROVIDERS.map((p) => {
          const k = byKey[KEY_FOR[p]]; const m = byKey[MODEL_FOR[p]];
          if (!k || !m) return null;
          const keyDraft = draft[k.key]; const modelDraft = draft[m.key];
          const isChosen = chosen === p;
          return (
            <div key={p} style={{ border: `1px solid ${isChosen ? "var(--c-accent)" : "var(--c-surfaceAlt)"}`, borderRadius: 8, padding: "0.9rem", background: C.bg }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                <span style={{ fontWeight: 600, fontSize: "0.9rem" }}>{ai?.providers[p].label ?? p}</span>
                {k.is_set
                  ? <span style={{ background: C.successBg, color: C.success, fontSize: "0.68rem", padding: "1px 7px", borderRadius: 4 }}>{k.source === "db" ? "key saved" : "key from .env"}</span>
                  : <span style={{ color: C.textDim, fontSize: "0.7rem" }}>no key</span>}
              </div>

              {/* Key */}
              <div style={{ color: C.textMuted, fontSize: "0.72rem", marginBottom: 3 }}>
                API key{k.link && <> · <a href={safeHref(k.link)} target="_blank" rel="noreferrer" style={{ color: C.accent }}>get one →</a></>}
              </div>
              {keyDraft === undefined ? (
                <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 10 }}>
                  <span style={{ flex: 1, color: C.divider, fontSize: "0.78rem", fontFamily: "monospace", overflow: "hidden", textOverflow: "ellipsis" }}>{k.masked_value || "—"}</span>
                  <button type="button" style={{ ...btn, background: C.surfaceAlt, color: C.textSoft }} onClick={() => setDraft((d) => ({ ...d, [k.key]: "" }))}>{k.is_set ? "Update" : "Set"}</button>
                  {k.is_set && k.source === "db" && <button type="button" style={{ ...btn, background: "transparent", color: C.textDim }} onClick={() => clear(k.key)}>Clear</button>}
                </div>
              ) : (
                <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
                  <input autoFocus type="password" value={keyDraft} placeholder={k.placeholder} style={{ ...inputStyle, flex: 1, minWidth: 0 }}
                    onChange={(e) => setDraft((d) => ({ ...d, [k.key]: e.target.value }))}
                    onKeyDown={(e) => { if (e.key === "Enter") save(k.key, keyDraft); if (e.key === "Escape") setDraft((d) => { const n = { ...d }; delete n[k.key]; return n; }); }} />
                  <button type="button" style={{ ...btn, background: C.accentSolid, color: "#fff" }} disabled={busy[k.key]} onClick={() => save(k.key, keyDraft)}>Save</button>
                </div>
              )}

              {/* Model */}
              <div style={{ color: C.textMuted, fontSize: "0.72rem", marginBottom: 3 }}>Model</div>
              {models[p] && models[p]!.length > 0 ? (
                <select value={m.masked_value || ""} style={{ ...inputStyle, width: "100%", marginBottom: 10 }} onChange={(e) => save(m.key, e.target.value)}>
                  {!models[p]!.some((g) => g.id === m.masked_value) && <option value={m.masked_value || ""}>{m.masked_value} (not in the provider's current list)</option>}
                  {models[p]!.map((g) => <option key={g.id} value={g.id}>{g.label === g.id ? g.id : `${g.label} (${g.id})`}</option>)}
                </select>
              ) : (
                <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
                  <input type="text" value={modelDraft ?? m.masked_value ?? ""} placeholder={m.placeholder} style={{ ...inputStyle, flex: 1, minWidth: 0 }}
                    onChange={(e) => setDraft((d) => ({ ...d, [m.key]: e.target.value }))}
                    onBlur={() => { if (modelDraft !== undefined && modelDraft !== m.masked_value) save(m.key, modelDraft); }}
                    onKeyDown={(e) => { if (e.key === "Enter" && modelDraft !== undefined) save(m.key, modelDraft); }} />
                </div>
              )}

              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <button type="button" style={{ ...btn, background: C.surfaceAlt, color: C.textSoft }} disabled={!k.is_set} onClick={() => test(p)}>Test</button>
                {testMsg[p] && <span style={{ fontSize: "0.75rem", color: testMsg[p].startsWith("✓") ? C.success : testMsg[p].startsWith("✗") ? C.danger : C.textMuted }}>{testMsg[p]}</span>}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
