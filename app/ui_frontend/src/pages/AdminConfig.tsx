import { safeHref } from "../lib/safeUrl";
import { C } from "../lib/theme";
import useDocumentTitle from "../hooks/useDocumentTitle";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { isAxiosError } from "axios";
import {
  getSubscribers, addSubscriber, updateSubscriber,
  deleteSubscriber, sendReportNow, getEmailStatus,
  getSettingsKeys, updateSettingKey, clearSettingKey,
  getAccessLog, adminLogin, adminLogout, ADMIN_TOKEN_KEY,
  getFilingInstitutions, addFilingInstitution, deleteFilingInstitution,
} from "../lib/api";
import { ADMIN_SESSION_KEY } from "../lib/storage";
import { notifyAdminChange } from "../hooks/useAdmin";
import AiProviderPanel from "../components/AiProviderPanel";
import DataSourcesPanel from "../components/DataSourcesPanel";
import ConfirmModal from "../components/ConfirmModal";

type Period = "morning" | "midday" | "evening";

interface Subscriber {
  id: number;
  email: string;
  is_active: boolean;
  subscribe_morning: boolean;
  subscribe_midday: boolean;
  subscribe_evening: boolean;
}

interface EmailStatus {
  configured: boolean;
  from?: string;
}

interface ApiKey {
  key: string;
  label: string;
  description: string;
  is_set: boolean;
  source: "db" | "env" | string;
  sensitive: boolean;
  masked_value?: string;
  placeholder?: string;
  link?: string;
  group?: string;
  choices?: string[] | null;
}

interface AccessLogRow {
  id: number;
  ip_address: string;
  email?: string | null;
  user_agent?: string | null;
  agreed_at?: string | null;
}

interface Institution {
  cik: string;
  name: string;
}

interface ConfirmState {
  message: string;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => Promise<void> | void;
}

const PERIODS: Period[] = ["morning", "midday", "evening"];
const periodLabel: Record<Period, string> = { morning: "8am", midday: "12pm", evening: "6pm" };

function StatusBadge({ configured }: { configured: boolean }) {
  return (
    <span style={{
      background: configured ? C.successBg : C.warningBg,
      color: configured ? C.success : C.warningSolid,
      border: `1px solid ${configured ? C.successDeep : C.warningDeep}`,
      padding: "2px 10px", borderRadius: 4, fontSize: "0.75rem", fontWeight: 700,
    }}>
      {configured ? "Configured" : "Not configured"}
    </span>
  );
}

// ── Password gate ─────────────────────────────────────────────────────────────
function PasswordGate({ onSuccess }: { onSuccess: () => void }) {
  const [pw, setPw]     = useState("");
  const [error, setError] = useState("");

  const attempt = async () => {
    try {
      await adminLogin(pw);
      // Cookie is now set httpOnly by the server — store only a UI visibility flag
      sessionStorage.setItem(ADMIN_SESSION_KEY, "1");
      sessionStorage.setItem(ADMIN_TOKEN_KEY, "1");
      notifyAdminChange();
      onSuccess();
    } catch {
      setError("Incorrect password.");
      setPw("");
    }
  };

  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "60vh" }}>
      <div style={{
        background: C.surface, border: "1px solid var(--c-divider)",
        borderRadius: 12, padding: "2rem 2.5rem", maxWidth: 360, width: "100%", textAlign: "center",
      }}>
        <div style={{ fontSize: "1.75rem", marginBottom: "0.5rem" }}>🔐</div>
        <h2 style={{ color: C.textBright, fontSize: "1.1rem", fontWeight: 700, marginBottom: "0.35rem" }}>Admin Access</h2>
        <p style={{ color: C.textMuted, fontSize: "0.82rem", marginBottom: "1.5rem" }}>
          Enter the admin password to continue.
        </p>
        <input
          autoFocus
          type="password"
          value={pw}
          onChange={e => { setPw(e.target.value); setError(""); }}
          onKeyDown={e => { if (e.key === "Enter") attempt(); }}
          placeholder="Password"
          style={{
            width: "100%", background: C.bg, color: C.text,
            border: error ? "1px solid var(--c-dangerSolid)" : "1px solid var(--c-divider)",
            borderRadius: 8, padding: "0.65rem 0.875rem",
            fontSize: "0.9rem", outline: "none", boxSizing: "border-box",
            marginBottom: "0.5rem",
          }}
        />
        {error && <p style={{ color: C.dangerSolid, fontSize: "0.78rem", marginBottom: "0.75rem" }}>{error}</p>}
        <button
          onClick={attempt}
          style={{
            width: "100%", background: C.accentSolid, color: "#fff",
            border: "none", borderRadius: 8, padding: "0.7rem",
            fontSize: "0.92rem", fontWeight: 600, cursor: "pointer", marginTop: "0.25rem",
          }}
        >
          Unlock
        </button>
      </div>
    </div>
  );
}

// Helper to extract `detail` from an Axios error response.
function errDetail(err: unknown, fallback: string): string {
  if (isAxiosError(err)) {
    const d = (err.response?.data as { detail?: string } | undefined)?.detail;
    if (d) return d;
  }
  return fallback;
}

// ── Main admin panel ──────────────────────────────────────────────────────────
function AdminPanel() {
  const navigate = useNavigate();
  const [subscribers, setSubscribers] = useState<Subscriber[]>([]);
  const [emailStatus, setEmailStatus] = useState<EmailStatus | null>(null);
  const [apiKeys, setApiKeys]         = useState<ApiKey[]>([]);
  const [keyValues, setKeyValues]     = useState<Record<string, string>>({});
  const [keySaving, setKeySaving]     = useState<Record<string, boolean>>({});
  const [keyEditing, setKeyEditing]   = useState<Record<string, boolean>>({});
  const [newEmail, setNewEmail]       = useState("");
  const [newSubs, setNewSubs]         = useState<Record<Period, boolean>>({ morning: true, midday: true, evening: true });
  const [adding, setAdding]           = useState(false);
  const [sending, setSending]         = useState<Record<string, boolean>>({});
  const [accessLog, setAccessLog]     = useState<AccessLogRow[]>([]);
  const [logLoading, setLogLoading]   = useState(false);
  const [logLoaded, setLogLoaded]     = useState(false);
  const [institutions, setInstitutions] = useState<Institution[]>([]);
  const [newInst, setNewInst]         = useState<{ name: string; cik: string }>({ name: "", cik: "" });
  const [instAdding, setInstAdding]   = useState(false);
  const [instError, setInstError]     = useState("");
  const [error, setError]             = useState("");
  const [toast, setToast]             = useState("");
  const [confirm, setConfirm]         = useState<ConfirmState | null>(null);

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(""), 3000); };

  const loadKeys = () => getSettingsKeys().then(r => {
    const keys = r.data as ApiKey[];
    setApiKeys(keys);
    const vals: Record<string, string> = {};
    keys.forEach(k => { if (!k.sensitive && k.masked_value) vals[k.key] = k.masked_value; });
    setKeyValues(prev => ({ ...vals, ...prev }));
  });

  const load = () => Promise.all([getSubscribers(), getEmailStatus()]).then(([sRes, eRes]) => {
    setSubscribers(sRes.data as Subscriber[]);
    setEmailStatus(eRes.data as EmailStatus);
  });

  const loadAccessLog = () => {
    setLogLoading(true);
    getAccessLog().then(r => { setAccessLog(r.data as AccessLogRow[]); setLogLoaded(true); }).finally(() => setLogLoading(false));
  };

  const loadInstitutions = () => getFilingInstitutions().then(r => setInstitutions(r.data as Institution[]));

  useEffect(() => { load(); loadKeys(); loadInstitutions(); }, []);

  const handleAdd = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault(); setError(""); setAdding(true);
    try {
      await addSubscriber({ email: newEmail, ...newSubs });
      setNewEmail("");
      setNewSubs({ morning: true, midday: true, evening: true });
      await load(); showToast(`${newEmail} added.`);
    } catch (err) { setError(errDetail(err, "Could not add subscriber.")); }
    finally { setAdding(false); }
  };

  const handleSaveKey = async (key: string) => {
    const value = (keyValues[key] || "").trim();
    setKeySaving(s => ({ ...s, [key]: true }));
    try {
      await updateSettingKey(key, value);
      setKeyEditing(e => ({ ...e, [key]: false }));
      await loadKeys(); await load();
      showToast("Setting saved.");
    } catch (err) { setError(errDetail(err, "Failed to save.")); }
    finally { setKeySaving(s => ({ ...s, [key]: false })); }
  };

  const handleClearKey = (key: string) => {
    setConfirm({
      message: "Clear this API key value?",
      onConfirm: async () => {
        setConfirm(null);
        await clearSettingKey(key);
        setKeyValues(v => ({ ...v, [key]: "" }));
        setKeyEditing(e => ({ ...e, [key]: false }));
        await loadKeys(); await load(); showToast("Setting cleared.");
      },
    });
  };

  const handleSendNow = async (period: Period) => {
    setSending(s => ({ ...s, [period]: true }));
    try {
      const r = await sendReportNow(period);
      const recipients = (r.data as { recipients?: number }).recipients ?? 0;
      showToast(`${period} report sent to ${recipients} recipient(s).`);
    } catch (err) { setError(errDetail(err, `Failed to send ${period} report.`)); }
    finally { setSending(s => ({ ...s, [period]: false })); }
  };

  const handleAddInstitution = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault(); setInstError(""); setInstAdding(true);
    try {
      await addFilingInstitution({ name: newInst.name.trim(), cik: newInst.cik.trim() });
      setNewInst({ name: "", cik: "" });
      await loadInstitutions();
      showToast(`${newInst.name} added.`);
    } catch (err) { setInstError(errDetail(err, "Could not add institution.")); }
    finally { setInstAdding(false); }
  };

  const handleDeleteInstitution = (inst: Institution) => {
    setConfirm({
      message: `Remove "${inst.name}" from filings tracking?`,
      confirmLabel: "Remove",
      danger: true,
      onConfirm: async () => {
        setConfirm(null);
        await deleteFilingInstitution(inst.cik);
        await loadInstitutions();
        showToast(`${inst.name} removed.`);
      },
    });
  };

  return (
    <div style={{ maxWidth: 800, margin: "0 auto" }}>
      {confirm && (
        <ConfirmModal
          message={confirm.message}
          confirmLabel={confirm.confirmLabel || "Confirm"}
          danger={confirm.danger}
          onConfirm={confirm.onConfirm}
          onCancel={() => setConfirm(null)}
        />
      )}
      {toast && (
        <div style={{ position: "fixed", top: 24, right: 24, background: C.successBg, color: C.success, border: "1px solid var(--c-successDeep)", borderRadius: 8, padding: "12px 20px", fontSize: "0.9rem", zIndex: 999 }}>
          {toast}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.25rem" }}>
        <div>
          <h1>🔐 Admin Panel</h1>
          <p style={{ color: C.textMuted, fontSize: "0.85rem" }}>M.G. Network &amp; Technology Solutions</p>
        </div>
        <button
          onClick={() => { adminLogout(); sessionStorage.removeItem(ADMIN_SESSION_KEY); sessionStorage.removeItem(ADMIN_TOKEN_KEY); notifyAdminChange(); navigate("/config"); }}
          style={{ background: C.surfaceAlt, color: C.textMuted, border: "1px solid var(--c-divider)", borderRadius: 6, padding: "0.35rem 0.875rem", cursor: "pointer", fontSize: "0.8rem" }}
        >
          ← Back to Config
        </button>
      </div>

      <div style={{ height: 1, background: C.surfaceAlt, margin: "1.25rem 0 2rem" }} />

      <DataSourcesPanel />

      {/* AI research notes: provider, keys, models */}
      <AiProviderPanel keys={apiKeys} onChanged={async () => { await loadKeys(); }} onError={(m) => setError(m)} />

      {/* Other credentials */}
      <section style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8, padding: "1.25rem", marginBottom: "1.5rem" }}>
        <div style={{ fontWeight: 600, marginBottom: "1rem" }}>Data &amp; Email Credentials</div>
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          {apiKeys.filter(k => !(k.group ?? "general").startsWith("ai")).map(k => {
            const isEditing = keyEditing[k.key];
            return (
              <div key={k.key} style={{ borderBottom: "1px solid var(--c-bgSunken)", paddingBottom: "1rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4 }}>
                  <div>
                    <span style={{ color: C.text, fontWeight: 500, fontSize: "0.9rem" }}>{k.label}</span>
                    {k.is_set && (
                      <span style={{ marginLeft: 8, background: C.successBg, color: C.success, border: "1px solid var(--c-successDeep)", fontSize: "0.68rem", padding: "1px 7px", borderRadius: 4 }}>
                        {k.source === "db" ? "saved" : "from .env"}
                      </span>
                    )}
                  </div>
                  <div style={{ display: "flex", gap: "0.4rem" }}>
                    {!isEditing && (
                      <button onClick={() => setKeyEditing(e => ({ ...e, [k.key]: true }))}
                        style={{ background: C.surfaceAlt, color: C.textSoft, border: "none", borderRadius: 4, padding: "2px 10px", cursor: "pointer", fontSize: "0.75rem" }}>
                        {k.is_set ? "Update" : "Set"}
                      </button>
                    )}
                    {k.is_set && k.source === "db" && !isEditing && (
                      <button onClick={() => handleClearKey(k.key)}
                        style={{ background: "transparent", color: C.textDim, border: "none", borderRadius: 4, padding: "2px 8px", cursor: "pointer", fontSize: "0.75rem" }}>
                        Clear
                      </button>
                    )}
                  </div>
                </div>
                <div style={{ color: C.textMuted, fontSize: "0.78rem", marginBottom: isEditing ? "0.5rem" : 0 }}>
                  {k.description}
                  {k.link && <> · <a href={safeHref(k.link)} target="_blank" rel="noreferrer" style={{ color: C.accent }}>Get one →</a></>}
                </div>
                {k.is_set && !isEditing && k.masked_value && (
                  <div style={{ color: C.textDim, fontSize: "0.78rem", fontFamily: "monospace", marginTop: 3 }}>{k.masked_value}</div>
                )}
                {isEditing && (
                  <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.4rem" }}>
                    <input
                      autoFocus type={k.sensitive ? "password" : "text"}
                      value={keyValues[k.key] || ""}
                      onChange={e => setKeyValues(v => ({ ...v, [k.key]: e.target.value }))}
                      placeholder={k.placeholder}
                      style={{ flex: 1, background: C.bg, color: C.text, border: "1px solid var(--c-divider)", borderRadius: 5, padding: "0.4rem 0.75rem", fontSize: "0.85rem" }}
                      onKeyDown={e => { if (e.key === "Enter") handleSaveKey(k.key); if (e.key === "Escape") setKeyEditing(ed => ({ ...ed, [k.key]: false })); }}
                    />
                    <button onClick={() => handleSaveKey(k.key)} disabled={keySaving[k.key]}
                      style={{ background: C.accentSolid, color: "#fff", border: "none", borderRadius: 5, padding: "0.4rem 1rem", cursor: "pointer", fontSize: "0.82rem", opacity: keySaving[k.key] ? 0.6 : 1 }}>
                      {keySaving[k.key] ? "Saving…" : "Save"}
                    </button>
                    <button onClick={() => setKeyEditing(e => ({ ...e, [k.key]: false }))}
                      style={{ background: C.surfaceAlt, color: C.textMuted, border: "none", borderRadius: 5, padding: "0.4rem 0.75rem", cursor: "pointer", fontSize: "0.82rem" }}>
                      Cancel
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* Gmail status */}
      <section style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8, padding: "1.25rem", marginBottom: "1.5rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <span style={{ fontWeight: 600 }}>Gmail SMTP</span>
          {emailStatus && <StatusBadge configured={emailStatus.configured} />}
        </div>
        {emailStatus?.configured
          ? <div style={{ color: C.textMuted, fontSize: "0.85rem" }}>Sending from <span style={{ color: C.textSoft }}>{emailStatus.from}</span></div>
          : <div style={{ color: C.textMuted, fontSize: "0.82rem" }}>Set Gmail address and App Password above to enable reports.</div>
        }
      </section>

      {/* Send report now */}
      <section style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8, padding: "1.25rem", marginBottom: "1.5rem" }}>
        <div style={{ fontWeight: 600, marginBottom: "1rem" }}>Send Report Now</div>
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          {PERIODS.map(period => (
            <button key={period} onClick={() => handleSendNow(period)} disabled={sending[period]}
              style={{ background: "var(--c-surfaceAlt)", color: C.text, border: "1px solid var(--c-divider)", borderRadius: 6, padding: "0.5rem 1.25rem", cursor: "pointer", opacity: sending[period] ? 0.6 : 1, fontSize: "0.9rem" }}>
              {sending[period] ? "Sending..." : `${period.charAt(0).toUpperCase() + period.slice(1)} (${periodLabel[period]})`}
            </button>
          ))}
        </div>
        <p style={{ color: C.textDim, fontSize: "0.75rem", marginTop: "0.75rem" }}>
          Sends the most recent analysis for that period to all active subscribers.
        </p>
      </section>

      {/* Add subscriber */}
      <section style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8, padding: "1.25rem", marginBottom: "1.5rem" }}>
        <div style={{ fontWeight: 600, marginBottom: "1rem" }}>Add Subscriber</div>
        <form onSubmit={handleAdd} style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          <input type="email" value={newEmail} onChange={e => setNewEmail(e.target.value)}
            placeholder="email@example.com" required
            style={{ background: C.bg, color: C.text, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, padding: "0.5rem 1rem", fontSize: "0.9rem" }} />
          <div style={{ display: "flex", gap: "1.25rem" }}>
            {PERIODS.map(period => (
              <label key={period} style={{ display: "flex", alignItems: "center", gap: "0.4rem", cursor: "pointer", color: C.textSoft, fontSize: "0.85rem" }}>
                <input type="checkbox" checked={newSubs[period]} onChange={e => setNewSubs(s => ({ ...s, [period]: e.target.checked }))} />
                {period.charAt(0).toUpperCase() + period.slice(1)}
              </label>
            ))}
          </div>
          {error && <p style={{ color: C.danger, fontSize: "0.85rem" }}>{error}</p>}
          <button type="submit" disabled={adding}
            style={{ background: C.accentSolid, color: "#fff", border: "none", borderRadius: 6, padding: "0.5rem 1.25rem", cursor: "pointer", width: "fit-content", opacity: adding ? 0.6 : 1, fontSize: "0.9rem" }}>
            {adding ? "Adding..." : "Add"}
          </button>
        </form>
      </section>

      {/* Subscriber list */}
      <section style={{ marginBottom: "1.5rem" }}>
        <div style={{ fontWeight: 600, marginBottom: "1rem", color: C.textSoft }}>
          Subscribers ({subscribers.length})
        </div>
        {subscribers.length === 0
          ? <p style={{ color: C.textDim, fontSize: "0.9rem" }}>No subscribers yet.</p>
          : (
            <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
              {subscribers.map(sub => (
                <div key={sub.id} style={{ background: C.surface, border: `1px solid ${sub.is_active ? C.surfaceAlt : C.bgSunken}`, borderRadius: 8, padding: "0.875rem 1rem", display: "flex", alignItems: "center", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap", opacity: sub.is_active ? 1 : 0.5 }}>
                  <div style={{ minWidth: 200 }}>
                    <div style={{ color: C.text, fontSize: "0.9rem" }}>{sub.email}</div>
                  </div>
                  <div style={{ display: "flex", gap: "0.5rem" }}>
                    {PERIODS.map(period => {
                      const active = sub[`subscribe_${period}`];
                      return (
                        <button key={period} onClick={() => { updateSubscriber(sub.id, { [`subscribe_${period}`]: !active }).then(() => load()); }}
                          style={{ background: active ? "var(--c-accentBg)" : C.surfaceAlt, color: active ? C.accent : C.textDim, border: `1px solid ${active ? C.accentSolid : C.surfaceAlt}`, borderRadius: 4, padding: "2px 10px", cursor: "pointer", fontSize: "0.75rem" }}>
                          {period.charAt(0).toUpperCase() + period.slice(1)}
                        </button>
                      );
                    })}
                  </div>
                  <div style={{ display: "flex", gap: "0.5rem", marginLeft: "auto" }}>
                    <button onClick={() => { updateSubscriber(sub.id, { is_active: !sub.is_active }).then(() => load()); }}
                      style={{ background: "transparent", color: sub.is_active ? C.textMuted : C.success, border: "1px solid var(--c-surfaceAlt)", borderRadius: 4, padding: "3px 10px", cursor: "pointer", fontSize: "0.75rem" }}>
                      {sub.is_active ? "Pause" : "Resume"}
                    </button>
                    <button onClick={() => {
                      setConfirm({
                        message: `Remove subscriber ${sub.email}?`,
                        confirmLabel: "Remove",
                        danger: true,
                        onConfirm: () => { setConfirm(null); deleteSubscriber(sub.id).then(() => { load(); showToast(`${sub.email} removed.`); }); },
                      });
                    }}
                      style={{ background: "transparent", color: C.danger, border: "1px solid var(--c-surfaceAlt)", borderRadius: 4, padding: "3px 10px", cursor: "pointer", fontSize: "0.75rem" }}>
                      Remove
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )
        }
      </section>

      {/* Filings Institutions */}
      <section style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8, padding: "1.25rem", marginBottom: "1.5rem" }}>
        <div style={{ fontWeight: 600, marginBottom: "1rem" }}>13F Filing Institutions ({institutions.length})</div>
        <p style={{ color: C.textDim, fontSize: "0.78rem", marginTop: 0, marginBottom: "1rem" }}>
          Institutions tracked on the Filings page. CIK is the SEC's 10-digit identifier — find it at sec.gov.
        </p>
        <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem", marginBottom: "1rem" }}>
          {institutions.map(inst => (
            <div key={inst.cik} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", background: C.bg, borderRadius: 6, padding: "0.4rem 0.75rem" }}>
              <div>
                <span style={{ color: C.text, fontSize: "0.88rem" }}>{inst.name}</span>
                <span style={{ color: C.textDim, fontSize: "0.75rem", fontFamily: "monospace", marginLeft: 10 }}>{inst.cik}</span>
              </div>
              <button
                onClick={() => handleDeleteInstitution(inst)}
                style={{ background: "transparent", color: C.textDim, border: "none", cursor: "pointer", fontSize: "0.75rem", padding: "2px 6px" }}
              >
                ✕
              </button>
            </div>
          ))}
        </div>
        <form onSubmit={handleAddInstitution} style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "flex-end" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            <label style={{ color: C.textDim, fontSize: "0.7rem" }}>Name</label>
            <input
              value={newInst.name}
              onChange={e => setNewInst(n => ({ ...n, name: e.target.value }))}
              placeholder="e.g. Soros Fund Management"
              required
              style={{ background: C.bg, color: C.text, border: "1px solid var(--c-surfaceAlt)", borderRadius: 5, padding: "0.4rem 0.75rem", fontSize: "0.85rem", width: 220 }}
            />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            <label style={{ color: C.textDim, fontSize: "0.7rem" }}>CIK (10 digits)</label>
            <input
              value={newInst.cik}
              onChange={e => setNewInst(n => ({ ...n, cik: e.target.value.replace(/\D/g, "") }))}
              placeholder="0001234567"
              required
              maxLength={10}
              style={{ background: C.bg, color: C.text, border: "1px solid var(--c-surfaceAlt)", borderRadius: 5, padding: "0.4rem 0.75rem", fontSize: "0.85rem", width: 130, fontFamily: "monospace" }}
            />
          </div>
          <button type="submit" disabled={instAdding}
            style={{ background: C.accentSolid, color: "#fff", border: "none", borderRadius: 5, padding: "0.4rem 1rem", cursor: "pointer", fontSize: "0.85rem", opacity: instAdding ? 0.6 : 1 }}>
            {instAdding ? "Adding…" : "Add"}
          </button>
        </form>
        {instError && <p style={{ color: C.danger, fontSize: "0.82rem", marginTop: "0.5rem" }}>{instError}</p>}
      </section>

      {/* Access Log */}
      <section>
        <div className="page-head">
          <div style={{ fontWeight: 600, color: C.textSoft }}>
            Access Log {logLoaded && <span style={{ color: C.textDim, fontWeight: 400 }}>({accessLog.length})</span>}
          </div>
          <button onClick={loadAccessLog} disabled={logLoading}
            style={{ background: C.surfaceAlt, color: C.textSoft, border: "1px solid var(--c-divider)", borderRadius: 6, padding: "0.3rem 0.875rem", cursor: "pointer", fontSize: "0.8rem", opacity: logLoading ? 0.6 : 1 }}>
            {logLoading ? "Loading…" : logLoaded ? "↺ Refresh" : "Load Log"}
          </button>
        </div>
        {logLoaded && accessLog.length === 0 && <p style={{ color: C.textDim, fontSize: "0.9rem" }}>No access records yet.</p>}
        {accessLog.length > 0 && (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--c-surfaceAlt)" }}>
                  {["#", "IP Address", "Email", "Device / Browser", "Agreed At"].map(h => (
                    <th key={h} style={{ textAlign: "left", color: C.textDim, fontWeight: 600, padding: "0.4rem 0.75rem", whiteSpace: "nowrap" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {accessLog.map((row, i) => (
                  <tr key={row.id} style={{ borderBottom: "1px solid var(--c-bgSunken)", background: i % 2 === 0 ? "transparent" : C.bg }}>
                    <td style={{ padding: "0.5rem 0.75rem", color: C.textDim }}>{row.id}</td>
                    <td style={{ padding: "0.5rem 0.75rem", color: C.textSoft, fontFamily: "monospace" }}>{row.ip_address}</td>
                    <td style={{ padding: "0.5rem 0.75rem", color: C.text }}>{row.email || <span style={{ color: C.textDim }}>—</span>}</td>
                    <td style={{ padding: "0.5rem 0.75rem", color: C.textMuted, maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {row.user_agent ? row.user_agent.replace(/\(.*?\)/g, "").trim().slice(0, 60) : "—"}
                    </td>
                    <td style={{ padding: "0.5rem 0.75rem", color: C.textMuted, whiteSpace: "nowrap" }}>
                      {row.agreed_at ? new Date(row.agreed_at).toLocaleString() : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

// ── Route component ───────────────────────────────────────────────────────────
export default function AdminConfig() {
  useDocumentTitle("Admin");
  const [authed, setAuthed] = useState(() => sessionStorage.getItem(ADMIN_SESSION_KEY) === "1");
  if (!authed) return <PasswordGate onSuccess={() => setAuthed(true)} />;
  return <AdminPanel />;
}
