import { C } from "../lib/theme";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { isAxiosError } from "axios";
import { getMySubscription, updateSubscriber, deleteSubscriber } from "../lib/api";
import ConfirmModal from "../components/ConfirmModal";
import useTheme from "../hooks/useTheme";
import type { ThemePref } from "../hooks/useTheme";
import useDocumentTitle from "../hooks/useDocumentTitle";
import OwnAiSettings from "../components/OwnAiSettings";

type Period = "morning" | "midday" | "evening";
const PERIODS: Period[] = ["morning", "midday", "evening"];
const periodLabel: Record<Period, string> = { morning: "8am", midday: "12pm", evening: "6pm" };

interface Subscription {
  id: number;
  email: string;
  is_active: boolean;
  subscribe_morning: boolean;
  subscribe_midday: boolean;
  subscribe_evening: boolean;
}

interface ConfirmState {
  message: string;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => Promise<void> | void;
}

function isValidEmail(e: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e.trim());
}

export default function Config() {
  const navigate = useNavigate();

  const [email, setEmail]           = useState("");
  const [emailError, setEmailError] = useState("");
  const [mySub, setMySub]           = useState<Subscription | null>(null);
  const [looking, setLooking]       = useState(false);

  const [confirm, setConfirm] = useState<ConfirmState | null>(null);
  const [toast, setToast]     = useState("");
  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(""), 3000); };

  const lookup = async () => {
    if (!email.trim()) { setEmailError("Enter your email address."); return; }
    if (!isValidEmail(email)) { setEmailError("Enter a valid email address."); return; }
    setEmailError(""); setLooking(true);
    try {
      const r = await getMySubscription(email.trim());
      setMySub(r.data as Subscription);
    } catch (err) {
      setMySub(null);
      const is404 = isAxiosError(err) && err.response?.status === 404;
      setEmailError(is404 ? "No subscription found for that email." : "Could not look up subscription.");
    }
    finally { setLooking(false); }
  };

  const togglePeriod = async (period: Period) => {
    if (!mySub) return;
    const key = `subscribe_${period}` as `subscribe_${Period}`;
    await updateSubscriber(mySub.id, { [key]: !mySub[key] }, mySub.email);
    setMySub((s) => (s ? { ...s, [key]: !s[key] } : s));
    showToast("Preference updated.");
  };

  const toggleActive = async () => {
    if (!mySub) return;
    await updateSubscriber(mySub.id, { is_active: !mySub.is_active }, mySub.email);
    setMySub((s) => (s ? { ...s, is_active: !s.is_active } : s));
    showToast(mySub.is_active ? "Subscription paused." : "Subscription resumed.");
  };

  const unsubscribe = () => {
    if (!mySub) return;
    const sub = mySub;
    setConfirm({
      message: `Unsubscribe ${sub.email} from all reports?`,
      confirmLabel: "Unsubscribe",
      danger: true,
      onConfirm: async () => {
        setConfirm(null);
        await deleteSubscriber(sub.id, sub.email);
        setMySub(null); setEmail("");
        showToast("Unsubscribed successfully.");
      },
    });
  };

  const { theme, setTheme } = useTheme();
  useDocumentTitle("Settings");

  return (
    <div style={{ maxWidth: 640 }}>
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
        <div style={{
          position: "fixed", top: 24, right: 24, zIndex: 999,
          background: C.successBg, color: C.success,
          border: "1px solid var(--c-successDeep)", borderRadius: 8,
          padding: "12px 20px", fontSize: "0.9rem",
        }}>
          {toast}
        </div>
      )}

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "2rem" }}>
        <div>
          <h1 style={{ fontSize: "1.5rem", fontWeight: 700, marginBottom: "0.25rem" }}>Settings</h1>
          <p style={{ color: C.textMuted, fontSize: "0.88rem" }}>Appearance, your AI key, and your email-report subscription.</p>
        </div>
        <button
          onClick={() => navigate("/admin")}
          style={{
            background: C.surface, color: C.textMuted,
            border: "1px solid var(--c-divider)", borderRadius: 7,
            padding: "0.45rem 1rem", cursor: "pointer",
            fontSize: "0.8rem", display: "flex", alignItems: "center", gap: "0.4rem",
          }}
        >
          🔐 Admin Panel
        </button>
      </div>

      <section style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 10, padding: "1.5rem", marginBottom: "1.5rem" }}>
        <div style={{ fontWeight: 600, marginBottom: "0.25rem" }}>Appearance</div>
        <p style={{ color: C.textMuted, fontSize: "0.82rem", marginBottom: "1rem" }}>
          Follows your device by default. Saved in this browser.
        </p>
        <div className="segmented" role="group" aria-label="Theme">
          {(["system", "light", "dark"] as ThemePref[]).map((t) => (
            <button key={t} type="button" aria-pressed={theme === t} onClick={() => setTheme(t)}>
              {t === "system" ? "System" : t === "light" ? "Light" : "Dark"}
            </button>
          ))}
        </div>
      </section>

      <OwnAiSettings onToast={(m) => showToast(m)} />

      <section style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 10, padding: "1.5rem", marginBottom: "1.5rem" }}>
        <div style={{ fontWeight: 600, marginBottom: "0.25rem" }}>Manage My Email Subscription</div>
        <p style={{ color: C.textMuted, fontSize: "0.82rem", marginBottom: "1rem" }}>
          Enter the email you used when you agreed to the terms.
        </p>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <input
            type="email"
            value={email}
            onChange={(e) => { setEmail(e.target.value); setEmailError(""); setMySub(null); }}
            onKeyDown={(e) => { if (e.key === "Enter") lookup(); }}
            placeholder="you@example.com"
            style={{
              flex: 1, background: C.bg, color: C.text,
              border: emailError ? "1px solid var(--c-dangerSolid)" : "1px solid var(--c-divider)",
              borderRadius: 7, padding: "0.6rem 0.875rem", fontSize: "0.9rem", outline: "none",
            }}
          />
          <button
            onClick={lookup}
            disabled={looking}
            style={{ background: C.accentSolid, color: "#fff", border: "none", borderRadius: 7, padding: "0.6rem 1.25rem", cursor: "pointer", fontSize: "0.88rem", fontWeight: 600, opacity: looking ? 0.6 : 1 }}
          >
            {looking ? "…" : "Look up"}
          </button>
        </div>
        {emailError && <p style={{ color: C.dangerSolid, fontSize: "0.78rem", marginTop: "0.4rem" }}>{emailError}</p>}

        {mySub && (
          <div style={{ marginTop: "1.25rem", paddingTop: "1.25rem", borderTop: "1px solid var(--c-surfaceAlt)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
              <div>
                <div style={{ color: C.text, fontWeight: 600 }}>{mySub.email}</div>
                <div style={{ color: mySub.is_active ? C.success : C.warningSolid, fontSize: "0.78rem", marginTop: 2 }}>
                  {mySub.is_active ? "● Active" : "● Paused"}
                </div>
              </div>
              <button
                onClick={toggleActive}
                style={{ background: "transparent", color: mySub.is_active ? C.textMuted : C.success, border: "1px solid var(--c-divider)", borderRadius: 6, padding: "0.35rem 0.875rem", cursor: "pointer", fontSize: "0.8rem" }}
              >
                {mySub.is_active ? "Pause" : "Resume"}
              </button>
            </div>
            <p style={{ color: C.textMuted, fontSize: "0.78rem", marginBottom: "0.6rem" }}>Report times:</p>
            <div style={{ display: "flex", gap: "0.625rem", flexWrap: "wrap", marginBottom: "1.25rem" }}>
              {PERIODS.map((period) => {
                const active = mySub[`subscribe_${period}`];
                return (
                  <button
                    key={period}
                    onClick={() => togglePeriod(period)}
                    style={{
                      background: active ? "var(--c-accentBg)" : C.bg,
                      color: active ? C.accent : C.textDim,
                      border: `1px solid ${active ? C.accentSolid : C.surfaceAlt}`,
                      borderRadius: 6, padding: "0.4rem 1rem",
                      cursor: "pointer", fontSize: "0.82rem", fontWeight: active ? 600 : 400,
                    }}
                  >
                    {period.charAt(0).toUpperCase() + period.slice(1)}
                    <span style={{ opacity: 0.55, marginLeft: 4 }}>({periodLabel[period]})</span>
                  </button>
                );
              })}
            </div>
            <button
              onClick={unsubscribe}
              style={{ background: "transparent", color: C.danger, border: "1px solid var(--c-dangerDeep)", borderRadius: 6, padding: "0.4rem 1rem", cursor: "pointer", fontSize: "0.82rem" }}
            >
              Unsubscribe
            </button>
          </div>
        )}
      </section>

      <p style={{ color: C.dividerStrong, fontSize: "0.78rem" }}>
        Looking for API keys, subscriber management, or email diagnostics? Those live in the{" "}
        <button onClick={() => navigate("/admin")} style={{ background: "none", border: "none", color: C.accent, cursor: "pointer", padding: 0, fontSize: "0.78rem" }}>
          Admin Panel
        </button>.
      </p>
      <p style={{ color: C.dividerStrong, fontSize: "0.72rem", marginTop: "2rem" }}>
        InsiderTrack <span data-tip="Application version">v{__APP_VERSION__}</span> · M.G. Network &amp; Technology Solutions ·{" "}
        <a href="https://github.com/mrgutierrezmario/stock-tracker" target="_blank" rel="noreferrer" style={{ color: C.textMuted }}>source</a> ·{" "}
        <a href="https://github.com/mrgutierrezmario/stock-tracker/blob/main/LICENSE" target="_blank" rel="noreferrer" style={{ color: C.textMuted }}>PolyForm Noncommercial 1.0.0</a>
      </p>
    </div>
  );
}
