import { C } from "../lib/theme";
import { useState, useEffect } from "react";
import type { ReactNode } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { recoverWatchlistToken, restoreMessage, restoreWatchlist } from "../lib/api";

const STORAGE_KEY = "insidertrack_terms_v1";

type Status = "checking" | "pending" | "agreed";
type SubResult = "already_registered" | "subscribed" | null;
type PeriodKey = "subscribe_morning" | "subscribe_midday" | "subscribe_evening";

interface DisclaimerProps { children: ReactNode }

function isValidEmail(e: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e.trim());
}

const PERIODS: ReadonlyArray<{ key: PeriodKey; label: string; time: string }> = [
  { key: "subscribe_morning",  label: "Morning",  time: "8am"   },
  { key: "subscribe_midday",   label: "Midday",   time: "12pm"  },
  { key: "subscribe_evening",  label: "Evening",  time: "6pm"   },
];

export default function Disclaimer({ children }: DisclaimerProps) {
  const [status, setStatus] = useState<Status>(() => {
    try { return localStorage.getItem(STORAGE_KEY) === "true" ? "agreed" : "checking"; }
    catch { return "checking"; }
  });

  const [email, setEmail]             = useState("");
  const [emailError, setEmailError]   = useState("");
  const [submitting, setSubmitting]   = useState(false);

  const [wantsEmails, setWantsEmails] = useState(false);
  const [periods, setPeriods]         = useState<Record<PeriodKey, boolean>>({
    subscribe_morning: true,
    subscribe_midday:  true,
    subscribe_evening: true,
  });
  const [subResult, setSubResult]     = useState<SubResult>(null);
  // Returning visitor on a new device: email + token loads their saved watchlist.
  const [token, setToken]             = useState("");
  const [sendingToken, setSendingToken] = useState(false);
  const [tokenSent, setTokenSent]     = useState("");

  // "Email me a token": same flow as My Watchlist. The server answers the same
  // whether or not the email has a watchlist, and rate-limits the requests.
  const emailMeToken = async () => {
    if (!isValidEmail(email)) { setEmailError("Enter your email first, then we can send your token."); return; }
    setEmailError("");
    setSendingToken(true);
    try {
      await recoverWatchlistToken(email.trim().toLowerCase());
      setTokenSent(`If ${email.trim()} has a saved watchlist, a token is on its way. Paste it above, then Continue.`);
    } catch {
      setTokenSent("Couldn't send right now. Try again in a minute.");
    } finally {
      setSendingToken(false);
    }
  };

  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    if (status !== "checking") return;
    fetch("/access/check")
      .then(r => r.json())
      .then(data => {
        if (data.agreed) {
          try { localStorage.setItem(STORAGE_KEY, "true"); } catch {}
          setStatus("agreed");
        } else {
          if (location.pathname !== "/") navigate("/", { replace: true });
          setStatus("pending");
        }
      })
      .catch(() => {
        if (location.pathname !== "/") navigate("/", { replace: true });
        setStatus("pending");
      });
  }, []);

  const handleAgree = async () => {
    if (email.trim() && !isValidEmail(email)) { setEmailError("Enter a valid email address."); return; }
    if (wantsEmails && !email.trim()) { setEmailError("An email address is required to sign up for reports."); return; }
    if (token.trim() && !email.trim()) { setEmailError("Enter the email your watchlist is saved under."); return; }
    setEmailError("");
    setSubmitting(true);

    // Load a saved watchlist first: a wrong token should stop here, with the
    // reason, rather than let the visitor in and fail later.
    if (token.trim()) {
      const result = await restoreWatchlist(email, token);
      if (result !== "ok") { setEmailError(restoreMessage(result)); setSubmitting(false); return; }
    }

    // Record IP + email agreement
    try {
      await fetch("/access/agree", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim() }),
      });
    } catch {}

    // Optionally subscribe to email reports
    if (wantsEmails) {
      try {
        const res = await fetch("/config/subscribers", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: email.trim(), ...periods }),
        });
        if (res.status === 409) {
          setSubResult("already_registered");
          setSubmitting(false);
          return; // keep modal open so they see the message
        }
        if (res.ok) setSubResult("subscribed");
      } catch {}
    }

    try { localStorage.setItem(STORAGE_KEY, "true"); } catch {}
    setStatus("agreed");
  };

  if (status === "agreed") return children;

  if (status === "checking") {
    return (
      <div style={{ background: C.bg, minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <p style={{ color: C.textDim, fontSize: "0.85rem" }}>Loading…</p>
      </div>
    );
  }

  // status === "pending"
  return (
    <div style={{
      background: C.bg,
      minHeight: "100vh",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: "1rem",
    }}>
      <div style={{
        background: C.bg,
        border: "1px solid var(--c-divider)",
        borderRadius: 14,
        padding: "2rem 1.75rem",
        maxWidth: 540,
        width: "100%",
        boxShadow: "0 25px 60px rgba(0,0,0,0.8)",
        textAlign: "center",
        overflowY: "auto",
        maxHeight: "95vh",
      }}>
        {/* Company branding */}
        {/* Two variants: the tagline under the mark is navy in the brand file, which vanishes on dark. */}
        <img className="brand-logo brand-logo--light" src="/logo.svg" alt="M.G. Network and Technology Solutions" />
        <img className="brand-logo brand-logo--dark" src="/logo-dark.svg" alt="" aria-hidden="true" />

        <h2 style={{ color: C.textBright, fontSize: "1.35rem", fontWeight: 700, marginBottom: "0.4rem" }}>
          Welcome to InsiderTrack
        </h2>

        <div style={{ width: 48, height: 2, background: C.accent, margin: "0 auto 1.25rem", borderRadius: 2 }} />

        <p style={{ color: C.textSoft, fontSize: "0.9rem", lineHeight: 1.7, marginBottom: "1rem" }}>
          Congressional, corporate-insider, institutional and Fed disclosures in one place,
          scored so you can see who is moving before the market does.
        </p>

        {/* Informational disclaimer */}
        <div style={{ background: C.surface, border: `1px solid ${C.surfaceAlt}`, borderRadius: 8, padding: "0.875rem 1.25rem", marginBottom: "1.25rem", textAlign: "left" }}>
          <p style={{ color: C.textMuted, fontSize: "0.8rem", lineHeight: 1.65 }}>
            <strong style={{ color: C.textSoft }}>Not financial advice.</strong> Everything here is compiled
            from public filings (STOCK Act, SEC Form 4, 13F) and may be delayed or incomplete. Signals are
            statistical, not recommendations. Past performance does not guarantee future results. By
            continuing you accept this and our use of your IP address to remember that you did.
            {" "}<a href="/guide" target="_blank" rel="noreferrer" style={{ color: C.accent }}>User guide</a> ·{" "}
            <a href="/privacy" target="_blank" rel="noreferrer" style={{ color: C.accent }}>Privacy</a>
          </p>
        </div>

        {/* Email field */}
        <div style={{ marginBottom: "1rem", textAlign: "left" }}>
          <label style={{ color: C.textSoft, fontSize: "0.8rem", fontWeight: 500, display: "block", marginBottom: "0.4rem" }}>
            Email address <span style={{ color: C.textDim, fontWeight: 400 }}>(optional)</span>
          </label>
          <input
            type="email"
            placeholder="you@example.com"
            value={email}
            onChange={e => { setEmail(e.target.value); setEmailError(""); setSubResult(null); }}
            onKeyDown={e => { if (e.key === "Enter" && !wantsEmails) handleAgree(); }}
            style={{
              width: "100%",
              background: C.surface,
              color: C.text,
              border: emailError ? "1px solid var(--c-dangerSolid)" : "1px solid var(--c-divider)",
              borderRadius: 8,
              padding: "0.65rem 0.875rem",
              fontSize: "0.9rem",
              outline: "none",
              boxSizing: "border-box",
              WebkitAppearance: "none",
            }}
          />
          {emailError && (
            <p style={{ color: C.dangerSolid, fontSize: "0.75rem", marginTop: "0.35rem" }}>{emailError}</p>
          )}
          <p style={{ color: C.textDim, fontSize: "0.72rem", marginTop: "0.35rem" }}>
            Only stored if you subscribe (for the reports) or load a saved watchlist.
          </p>

          <div style={{ marginTop: "0.85rem" }}>
            <label style={{ color: C.textSoft, fontSize: "0.8rem", fontWeight: 500, display: "block", marginBottom: "0.4rem" }}>
              Watchlist token <span style={{ color: C.textDim, fontWeight: 400 }}>(optional, returning visitors)</span>
            </label>
            <input
              type="text"
              placeholder="Paste your token to load your saved stocks"
              value={token}
              autoComplete="off"
              spellCheck={false}
              onChange={e => { setToken(e.target.value); setEmailError(""); }}
              onKeyDown={e => { if (e.key === "Enter" && !wantsEmails) handleAgree(); }}
              style={{
                width: "100%",
                background: C.surface,
                color: C.text,
                border: "1px solid var(--c-divider)",
                borderRadius: 8,
                padding: "0.65rem 0.875rem",
                fontSize: "0.85rem",
                fontFamily: "monospace",
                outline: "none",
                boxSizing: "border-box",
              }}
            />
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.75rem", marginTop: "0.4rem", flexWrap: "wrap" }}>
              <span style={{ color: C.textDim, fontSize: "0.72rem" }}>New here? Leave it empty.</span>
              <button
                type="button"
                onClick={emailMeToken}
                disabled={sendingToken}
                style={{ background: "none", border: "none", padding: 0, color: C.accent, fontSize: "0.78rem", fontWeight: 600, cursor: sendingToken ? "wait" : "pointer" }}
              >
                {sendingToken ? "Sending…" : "Don't have it? Email me my token"}
              </button>
            </div>
            {tokenSent && (
              <p style={{ color: C.textSoft, fontSize: "0.75rem", marginTop: "0.45rem", lineHeight: 1.5 }}>
                {tokenSent} A new token replaces the old one, so other devices will need it too.
              </p>
            )}
          </div>
        </div>

        {/* Email subscription opt-in */}
        <div style={{
          background: C.surface,
          border: "1px solid var(--c-surfaceAlt)",
          borderRadius: 8,
          padding: "0.875rem 1.25rem",
          marginBottom: "1.5rem",
          textAlign: "left",
        }}>
          <label style={{ display: "flex", alignItems: "center", gap: "0.6rem", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={wantsEmails}
              onChange={e => { setWantsEmails(e.target.checked); setSubResult(null); }}
              style={{ width: 16, height: 16, accentColor: C.accent, cursor: "pointer" }}
            />
            <span style={{ color: C.text, fontSize: "0.88rem", fontWeight: 500 }}>
              Sign me up for email market reports
            </span>
          </label>

          {wantsEmails && (
            <div style={{ marginTop: "0.875rem", paddingTop: "0.875rem", borderTop: "1px solid var(--c-surfaceAlt)" }}>
              <p style={{ color: C.textMuted, fontSize: "0.75rem", marginBottom: "0.6rem" }}>
                Choose which reports to receive:
              </p>
              <div style={{ display: "flex", gap: "0.625rem", flexWrap: "wrap" }}>
                {PERIODS.map(({ key, label, time }) => {
                  const active = periods[key];
                  return (
                    <button
                      key={key}
                      type="button"
                      onClick={() => setPeriods(p => ({ ...p, [key]: !p[key] }))}
                      style={{
                        background: active ? "var(--c-accentBg)" : C.bg,
                        color: active ? C.accent : C.textDim,
                        border: `1px solid ${active ? C.accentSolid : C.surfaceAlt}`,
                        borderRadius: 6,
                        padding: "0.35rem 0.875rem",
                        cursor: "pointer",
                        fontSize: "0.8rem",
                        fontWeight: active ? 600 : 400,
                        WebkitAppearance: "none",
                      }}
                    >
                      {label} <span style={{ opacity: 0.6 }}>({time})</span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Already registered message */}
          {subResult === "already_registered" && (
            <div style={{
              marginTop: "0.875rem",
              padding: "0.65rem 0.875rem",
              background: "var(--c-warningBg)",
              border: "1px solid var(--c-warningDeep)",
              borderRadius: 6,
            }}>
              <p style={{ color: C.warningSolid, fontSize: "0.8rem", margin: 0 }}>
                ⚠️ <strong>{email}</strong> is already subscribed to reports.
                To change or cancel them, go to{" "}
                <strong style={{ color: C.textBright }}>Settings</strong>.
              </p>
              <button
                onClick={handleAgree}
                style={{
                  marginTop: "0.6rem",
                  background: "none",
                  color: C.accent,
                  border: "none",
                  padding: 0,
                  cursor: "pointer",
                  fontSize: "0.78rem",
                  textDecoration: "underline",
                }}
              >
                Continue Without Subscribing →
              </button>
            </div>
          )}
        </div>

        {/* Buttons */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "0.75rem" }}>
          <button
            onClick={handleAgree}
            disabled={submitting}
            style={{
              background: C.accentSolid, color: "#fff",
              border: "none", borderRadius: 8,
              padding: "0.8rem 2rem", fontSize: "0.95rem",
              fontWeight: 600,
              cursor: submitting ? "not-allowed" : "pointer",
              minWidth: 200, WebkitAppearance: "none",
              opacity: submitting ? 0.7 : 1,
            }}
          >
            {submitting ? "Saving…" : "Continue"}
          </button>
          <button
            type="button"
            onClick={() => { if (window.history.length > 1) window.history.back(); else window.close(); }}
            style={{ background: "none", border: "none", color: C.textDim, fontSize: "0.78rem", cursor: "pointer", padding: 0 }}
          >
            No Thanks, Take Me Back
          </button>
        </div>

        <p style={{ color: C.textDim, fontSize: "0.68rem", marginTop: "1rem" }}>
          © {new Date().getFullYear()} M.G. Network and Technology Solutions. All rights reserved.
        </p>
      </div>
    </div>
  );
}
