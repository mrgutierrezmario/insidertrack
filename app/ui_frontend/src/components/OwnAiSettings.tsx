import { C } from "../lib/theme";
import { useEffect, useState } from "react";
import { getAiSettings, getOwnGeminiModels, testOwnAiKey } from "../lib/api";
import type { AiSettings } from "../lib/api";
import { readOwnAi, writeOwnAi } from "../lib/storage";
import type { AiProvider } from "../lib/storage";

const PROVIDERS: Array<{ id: AiProvider; label: string; placeholder: string; link: string; defaultModel: string }> = [
  { id: "claude", label: "Claude", placeholder: "sk-ant-…", link: "https://console.anthropic.com/settings/keys", defaultModel: "claude-opus-5" },
  { id: "gemini", label: "Gemini", placeholder: "AIza…", link: "https://aistudio.google.com/apikey", defaultModel: "gemini-flash-latest" },
  { id: "openai", label: "OpenAI", placeholder: "sk-…", link: "https://platform.openai.com/api-keys", defaultModel: "gpt-4o-mini" },
];

const inputStyle = { background: C.bg, color: C.text, border: "1px solid var(--c-divider)", borderRadius: 6, padding: "0.5rem 0.75rem", fontSize: "0.88rem" } as const;
const btn = { border: "none", borderRadius: 6, padding: "0.5rem 1rem", cursor: "pointer", fontSize: "0.85rem" } as const;

/**
 * Settings card for a visitor's own AI key. Everything is kept in this
 * browser's localStorage and sent to this site only when a research note is
 * generated; the server uses it for that call and does not store it.
 */
export default function OwnAiSettings({ onToast }: { onToast: (m: string) => void }) {
  const saved = readOwnAi();
  const [provider, setProvider] = useState<AiProvider>(saved?.provider ?? "gemini");
  const [key, setKey] = useState(saved?.key ?? "");
  const [model, setModel] = useState(saved?.model ?? "");
  const [site, setSite] = useState<AiSettings | null>(null);
  const [testMsg, setTestMsg] = useState("");
  const [gemini, setGemini] = useState<Array<{ id: string; label: string }> | null>(null);
  const meta = PROVIDERS.find((p) => p.id === provider)!;
  const isSaved = !!saved;
  const dirty = !saved || saved.provider !== provider || saved.key !== key || (saved.model ?? "") !== model;

  useEffect(() => { getAiSettings().then((r) => setSite(r.data)).catch(() => {}); }, []);
  useEffect(() => {
    // The live Gemini model list needs the saved key on the request headers.
    if (provider === "gemini" && saved?.provider === "gemini" && saved.key === key && gemini === null) {
      getOwnGeminiModels().then((r) => setGemini(r.data)).catch(() => setGemini([]));
    }
  }, [provider, saved, key, gemini]);

  const save = () => {
    const k = key.trim();
    if (!k) { onToast("Paste an API key first."); return; }
    writeOwnAi({ provider, key: k, model: model.trim() || undefined });
    setGemini(null);
    setTestMsg("");
    onToast("Saved in this browser.");
  };
  const clear = () => { writeOwnAi(null); setKey(""); setModel(""); setGemini(null); setTestMsg(""); onToast("Your AI key was removed from this browser."); };
  const test = async () => {
    if (dirty) { onToast("Save first, then test."); return; }
    setTestMsg("Testing…");
    try { const r = await testOwnAiKey(); setTestMsg((r.data.ok ? "✓ " : "✗ ") + r.data.message); }
    catch { setTestMsg("✗ Could not run the test."); }
  };

  return (
    <section style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 10, padding: "1.5rem", marginBottom: "1.5rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <div style={{ fontWeight: 600 }}>AI research notes</div>
        {isSaved
          ? <span style={{ fontSize: "0.75rem", padding: "2px 9px", borderRadius: 4, background: C.successBg, color: C.success }}>Using your {PROVIDERS.find((p) => p.id === saved!.provider)?.label} key</span>
          : site?.configured
            ? <span style={{ fontSize: "0.75rem", padding: "2px 9px", borderRadius: 4, background: C.accentBg, color: C.accent }}>Using the site's {site.providers[site.active!].label}</span>
            : <span style={{ fontSize: "0.75rem", padding: "2px 9px", borderRadius: 4, background: C.warningBg, color: C.warningSolid }}>Not set up</span>}
      </div>
      <p style={{ color: C.textMuted, fontSize: "0.82rem", margin: "0.35rem 0 1rem", lineHeight: 1.55 }}>
        The bull/bear note on each ticker page is written by an AI model. Bring your own key and it runs on your account
        {site?.configured ? " instead of the site's" : ""}. The key is stored only in this browser and sent to this site over HTTPS
        just to generate a note — it is never saved on the server.
      </p>

      <div style={{ color: C.textMuted, fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>Provider</div>
      <div className="segmented" role="group" aria-label="AI provider" style={{ marginBottom: "1rem" }}>
        {PROVIDERS.map((p) => (
          <button key={p.id} type="button" aria-pressed={provider === p.id} onClick={() => { setProvider(p.id); setModel(""); setGemini(null); setTestMsg(""); }}>{p.label}</button>
        ))}
      </div>

      <label style={{ color: C.textMuted, fontSize: "0.72rem", display: "block", marginBottom: 4 }}>
        {meta.label} API key · <a href={meta.link} target="_blank" rel="noreferrer" style={{ color: C.accent }}>get one →</a>
      </label>
      <input type="password" value={key} placeholder={meta.placeholder} autoComplete="off" spellCheck={false}
        onChange={(e) => setKey(e.target.value)} style={{ ...inputStyle, width: "100%", marginBottom: "0.75rem" }} />

      <label style={{ color: C.textMuted, fontSize: "0.72rem", display: "block", marginBottom: 4 }}>Model <span style={{ color: C.textDim }}>(optional — default {meta.defaultModel})</span></label>
      {provider === "gemini" && gemini && gemini.length > 0 ? (
        <select value={model} onChange={(e) => setModel(e.target.value)} style={{ ...inputStyle, width: "100%", marginBottom: "1rem" }}>
          <option value="">Default ({meta.defaultModel})</option>
          {gemini.map((g) => <option key={g.id} value={g.id}>{g.label} ({g.id})</option>)}
        </select>
      ) : (
        <input type="text" value={model} placeholder={meta.defaultModel} onChange={(e) => setModel(e.target.value)} style={{ ...inputStyle, width: "100%", marginBottom: "1rem" }} />
      )}

      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
        <button type="button" onClick={save} disabled={!key.trim() || !dirty} style={{ ...btn, background: C.accentSolid, color: "#fff", opacity: !key.trim() || !dirty ? 0.5 : 1 }}>Save</button>
        <button type="button" onClick={test} disabled={!isSaved} style={{ ...btn, background: C.surfaceAlt, color: C.textSoft, opacity: isSaved ? 1 : 0.5 }}>Test</button>
        {isSaved && <button type="button" onClick={clear} style={{ ...btn, background: "transparent", color: C.textDim }}>Remove</button>}
        {testMsg && <span style={{ fontSize: "0.78rem", color: testMsg.startsWith("✓") ? C.success : testMsg.startsWith("✗") ? C.danger : C.textMuted }}>{testMsg}</span>}
      </div>
    </section>
  );
}
