import { C } from "../lib/theme";
import { useEffect, useState } from "react";
import { getAiSettings, getAiModels, getAiUsage, testAiProvider, updateSettingKey, clearSettingKey } from "../lib/api";
import type { AiSettings, AiUsage, ModelOption } from "../lib/api";
import { safeHref } from "../lib/safeUrl";

/** One row of /settings/keys, as AdminConfig already types it. */
export interface KeyRowData {
  key: string; label: string; description: string; is_set: boolean; source: string;
  sensitive: boolean; masked_value?: string; placeholder?: string; link?: string;
  group?: string; choices?: string[] | null;
}

const PROVIDERS = ["ollama", "claude", "gemini", "openai"] as const;
type Provider = (typeof PROVIDERS)[number];
// Ollama has no key: its "credential" is the server URL.
const KEY_FOR: Record<Provider, string> = { ollama: "ollama_base_url", claude: "anthropic_api_key", gemini: "gemini_api_key", openai: "openai_api_key" };
const KNOWN: Record<Provider, ModelOption[]> = {
  ollama: [
    { id: "llama3", label: "Llama 3 (8B)" }, { id: "llama3.2:3b", label: "Llama 3.2 (3B)" }, { id: "gemma3", label: "Gemma 3" }, { id: "mistral", label: "Mistral" }, { id: "qwen2.5", label: "Qwen 2.5" },
  ],
  claude: [
    { id: "claude-opus-5", label: "Claude Opus 5" }, { id: "claude-sonnet-5", label: "Claude Sonnet 5" }, { id: "claude-haiku-4-5", label: "Claude Haiku 4.5" },
    { id: "claude-opus-4-6", label: "Claude Opus 4.6" }, { id: "claude-sonnet-4-6", label: "Claude Sonnet 4.6" },
  ],
  gemini: [
    { id: "gemini-flash-latest", label: "Gemini Flash Latest" }, { id: "gemini-flash-lite-latest", label: "Gemini Flash-Lite Latest" }, { id: "gemini-pro-latest", label: "Gemini Pro Latest" },
  ],
  openai: [
    { id: "gpt-4o-mini", label: "GPT-4o mini" }, { id: "gpt-4o", label: "GPT-4o" }, { id: "gpt-4.1", label: "GPT-4.1" }, { id: "gpt-4.1-mini", label: "GPT-4.1 mini" },
  ],
};
const CUSTOM = "__custom__";
const MODEL_FOR: Record<Provider, string> = { ollama: "ollama_model", claude: "claude_model", gemini: "gemini_model", openai: "openai_model" };
const JOB_LABELS: Record<string, string> = { notes: "Research notes", desk: "Model Desk brief", vision: "Paper filings (vision)", test: "Test button" };
const fmtK = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : String(n));

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
  const [usage, setUsage] = useState<AiUsage | null>(null);
  const byKey = Object.fromEntries(keys.map((k) => [k.key, k])) as Record<string, KeyRowData | undefined>;

  const refresh = () => Promise.all([
    getAiSettings().then((r) => setAi(r.data)).catch(() => {}),
    getAiUsage().then((r) => setUsage(r.data)).catch(() => {}),
  ]);
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
  const batchChosen = (ai?.batch_chosen ?? "ollama") as Provider;
  const usageRows = usage
    ? Object.entries(usage.jobs).flatMap(([job, byProvider]) => Object.entries(byProvider).map(([provider, row]) => ({ job, provider, ...row })))
    : [];

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
        if the chosen one fails (quota, outage), the others configured are tried as a fallback. Notes are cached 6 h.
        Ollama is a free local model server (no key, no quota) — slower, so it suits the scheduled Model Desk brief;
        scanned paper filings still need a cloud provider unless Ollama has a vision model.
      </p>

      {/* Provider choice */}
      <div style={{ color: C.textMuted, fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>Writes the notes</div>
      <div className="segmented" role="group" aria-label="AI provider" style={{ marginBottom: "0.9rem" }}>
        {PROVIDERS.map((p) => (
          <button key={p} type="button" aria-pressed={chosen === p} disabled={busy.ai_provider} onClick={() => save("ai_provider", p)}>
            {ai?.providers[p].label ?? p}{ai && !ai.providers[p].configured ? (p === "ollama" ? " (no server)" : " (no key)") : ""}
          </button>
        ))}
      </div>
      <div style={{ color: C.textMuted, fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>Writes the daily Model Desk brief</div>
      <div className="segmented" role="group" aria-label="Scheduled jobs provider" style={{ marginBottom: "1.25rem" }}>
        {PROVIDERS.map((p) => (
          <button key={p} type="button" aria-pressed={batchChosen === p} disabled={busy.ai_batch_provider} onClick={() => save("ai_batch_provider", p)}>
            {ai?.providers[p].label ?? p}{ai && !ai.providers[p].configured ? (p === "ollama" ? " (no server)" : " (no key)") : ""}
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
                  ? <span style={{ background: C.successBg, color: C.success, fontSize: "0.68rem", padding: "1px 7px", borderRadius: 4 }}>{k.source === "db" ? (p === "ollama" ? "server saved" : "key saved") : (p === "ollama" ? "server from .env" : "key from .env")}</span>
                  : <span style={{ color: C.textDim, fontSize: "0.7rem" }}>{p === "ollama" ? "no server" : "no key"}</span>}
              </div>

              {/* Key (or, for Ollama, the server URL) */}
              <div style={{ color: C.textMuted, fontSize: "0.72rem", marginBottom: 3 }}>
                {p === "ollama" ? "Server URL" : "API key"}{k.link && <> · <a href={safeHref(k.link)} target="_blank" rel="noreferrer" style={{ color: C.accent }}>{p === "ollama" ? "install →" : "get one →"}</a></>}
              </div>
              {keyDraft === undefined ? (
                <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 10 }}>
                  <span style={{ flex: 1, color: C.textDim, fontSize: "0.78rem", fontFamily: "monospace", overflow: "hidden", textOverflow: "ellipsis" }}>{k.masked_value || "—"}</span>
                  <button type="button" style={{ ...btn, background: C.surfaceAlt, color: C.textSoft }} onClick={() => setDraft((d) => ({ ...d, [k.key]: "" }))}>{k.is_set ? "Update" : "Set"}</button>
                  {k.is_set && k.source === "db" && <button type="button" style={{ ...btn, background: "transparent", color: C.textDim }} onClick={() => clear(k.key)}>Clear</button>}
                </div>
              ) : (
                <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
                  <input autoFocus type={p === "ollama" ? "text" : "password"} value={keyDraft} placeholder={k.placeholder} style={{ ...inputStyle, flex: 1, minWidth: 0 }}
                    onChange={(e) => setDraft((d) => ({ ...d, [k.key]: e.target.value }))}
                    onKeyDown={(e) => { if (e.key === "Enter") save(k.key, keyDraft); if (e.key === "Escape") setDraft((d) => { const n = { ...d }; delete n[k.key]; return n; }); }} />
                  <button type="button" style={{ ...btn, background: C.accentSolid, color: "#fff" }} disabled={busy[k.key]} onClick={() => save(k.key, keyDraft)}>Save</button>
                </div>
              )}

              {/* Model */}
              <div style={{ color: C.textMuted, fontSize: "0.72rem", marginBottom: 3 }}>Model</div>
              {(() => {
                const live = models[p] && models[p]!.length > 0;
                const options = live ? models[p]! : KNOWN[p];
                const current = m.masked_value || "";
                const isCustom = modelDraft !== undefined || (!!current && !options.some((g) => g.id === current));
                return (
                  <div style={{ marginBottom: 10 }}>
                    <select value={isCustom ? CUSTOM : current} style={{ ...inputStyle, width: "100%" }}
                      onChange={(e) => { if (e.target.value === CUSTOM) setDraft((d) => ({ ...d, [m.key]: current })); else { setDraft((d) => { const n = { ...d }; delete n[m.key]; return n; }); save(m.key, e.target.value); } }}>
                      {options.map((g) => <option key={g.id} value={g.id}>{g.label === g.id ? g.id : `${g.label} (${g.id})`}</option>)}
                      <option value={CUSTOM}>Custom model ID…</option>
                    </select>
                    {isCustom && (
                      <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
                        <input type="text" value={modelDraft ?? current} placeholder={m.placeholder} style={{ ...inputStyle, flex: 1, minWidth: 0 }}
                          onChange={(e) => setDraft((d) => ({ ...d, [m.key]: e.target.value }))}
                          onKeyDown={(e) => { if (e.key === "Enter" && modelDraft !== undefined) save(m.key, modelDraft); }} />
                        <button type="button" style={{ ...btn, background: C.accentSolid, color: "#fff" }} disabled={modelDraft === undefined || busy[m.key]} onClick={() => modelDraft !== undefined && save(m.key, modelDraft)}>Save</button>
                      </div>
                    )}
                    <div style={{ color: C.textDim, fontSize: "0.7rem", marginTop: 4 }}>{live ? (p === "ollama" ? `${models[p]!.length} models pulled on the server.` : `${models[p]!.length} models available to the saved key.`) : k.is_set ? "Fetching the live list…" : p === "ollama" ? "Common models; save the server URL to see what it has pulled." : "Common models; save a key to see everything it can use."}</div>
                  </div>
                );
              })()}

              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <button type="button" style={{ ...btn, background: C.surfaceAlt, color: C.textSoft }} disabled={!k.is_set} onClick={() => test(p)}>Test</button>
                {testMsg[p] && <span style={{ fontSize: "0.75rem", color: testMsg[p].startsWith("✓") ? C.success : testMsg[p].startsWith("✗") ? C.danger : C.textMuted }}>{testMsg[p]}</span>}
              </div>
            </div>
          );
        })}
      </div>

      {/* Where the tokens go */}
      {usageRows.length > 0 && (
        <div style={{ marginTop: "1.25rem" }}>
          <div style={{ color: C.textMuted, fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>
            Usage since start-up · today is {usage?.day}
          </div>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" }}>
              <thead>
                <tr style={{ color: C.textMuted, textAlign: "left" }}>
                  <th style={{ padding: "4px 8px" }}>Job</th><th style={{ padding: "4px 8px" }}>Provider</th>
                  <th style={{ padding: "4px 8px", textAlign: "right" }}>Calls (today)</th><th style={{ padding: "4px 8px", textAlign: "right" }}>Failed</th>
                  <th style={{ padding: "4px 8px", textAlign: "right" }}>Tokens in (today)</th><th style={{ padding: "4px 8px", textAlign: "right" }}>Tokens out</th>
                  <th style={{ padding: "4px 8px", textAlign: "right" }}>Avg s</th>
                </tr>
              </thead>
              <tbody>
                {usageRows.map((r) => (
                  <tr key={`${r.job}-${r.provider}`} style={{ borderTop: "1px solid var(--c-divider)" }}>
                    <td style={{ padding: "4px 8px" }}>{JOB_LABELS[r.job] ?? r.job}</td>
                    <td style={{ padding: "4px 8px" }}>{r.provider}</td>
                    <td style={{ padding: "4px 8px", textAlign: "right" }}>{r.calls} ({r.calls_today})</td>
                    <td style={{ padding: "4px 8px", textAlign: "right", color: r.failures ? C.danger : C.textDim }}>{r.failures}</td>
                    <td style={{ padding: "4px 8px", textAlign: "right" }}>{fmtK(r.input_tokens)} ({fmtK(r.input_tokens_today)})</td>
                    <td style={{ padding: "4px 8px", textAlign: "right" }}>{fmtK(r.output_tokens)}</td>
                    <td style={{ padding: "4px 8px", textAlign: "right" }}>{r.calls ? (r.ms / r.calls / 1000).toFixed(1) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p style={{ color: C.textDim, fontSize: "0.7rem", margin: "6px 0 0" }}>
            Counters reset when the app restarts; the log line <code>ai_usage</code> has every call. Tokens are as reported by each provider.
          </p>
        </div>
      )}
    </section>
  );
}
