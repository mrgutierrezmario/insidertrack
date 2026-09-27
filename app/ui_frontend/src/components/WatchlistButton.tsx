import { C } from "../lib/theme";
import { useState } from "react";
import type { KeyboardEvent } from "react";
import { isAxiosError } from "axios";
import { addToWatchlist, restoreMessage, restoreWatchlist } from "../lib/api";
import { EMAIL_KEY } from "../lib/storage";

type WatchState = "idle" | "added" | "exists" | "error";

interface EmailModalProps {
  ticker: string;
  onConfirm: (email: string) => void;
  onCancel: () => void;
  initialEmail?: string;
  initialError?: string;
}

interface WatchlistButtonProps {
  ticker: string;
  size?: "sm" | "md";
}

function isValidEmail(e: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test((e || "").trim());
}

function EmailModal({ ticker, onConfirm, onCancel, initialEmail = "", initialError = "" }: EmailModalProps) {
  const [value, setValue] = useState(initialEmail);
  const [token, setToken] = useState("");
  const [err, setErr] = useState(initialError);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    const trimmed = value.trim().toLowerCase();
    if (!trimmed) { setErr("Email is required."); return; }
    if (!isValidEmail(trimmed)) { setErr("Enter a valid email address."); return; }
    // Returning on a new device: sign back in with the token before adding.
    if (token.trim()) {
      setBusy(true);
      const result = await restoreWatchlist(trimmed, token);
      setBusy(false);
      if (result !== "ok") { setErr(restoreMessage(result)); return; }
    }
    onConfirm(trimmed);
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") submit();
    if (e.key === "Escape") onCancel();
  };

  return (
    <div
      onClick={onCancel}
      style={{
        position: "fixed", inset: 0, zIndex: 9999,
        background: "rgba(0,0,0,0.65)",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: C.surface,
          border: "1px solid var(--c-surfaceAlt)",
          borderRadius: 12,
          padding: "28px 32px",
          width: 340,
          boxShadow: "0 20px 60px rgba(0,0,0,0.6)",
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
          <div style={{
            width: 32, height: 32, borderRadius: 8,
            background: "rgba(56,189,248,0.12)",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 16,
          }}>
            ★
          </div>
          <div>
            <div style={{ color: C.text, fontWeight: 700, fontSize: 15 }}>
              Add to Watchlist
            </div>
            <div style={{ color: C.textMuted, fontSize: 12 }}>
              Tracking <span style={{ color: C.accent, fontWeight: 600 }}>{ticker}</span>
            </div>
          </div>
        </div>

        <div style={{ borderTop: "1px solid var(--c-surfaceAlt)", margin: "14px 0" }} />

        <p style={{ color: C.textSoft, fontSize: 13, marginBottom: 16, lineHeight: 1.5 }}>
          Enter your email to save your watchlist. No account or password needed.
        </p>

        <label style={{ display: "block", color: C.textSoft, fontSize: 12, marginBottom: 6, fontWeight: 600 }}>
          EMAIL ADDRESS
        </label>
        <input
          autoFocus
          type="email"
          placeholder="you@example.com"
          value={value}
          onChange={(e) => { setValue(e.target.value); setErr(""); }}
          onKeyDown={onKey}
          style={{
            width: "100%",
            boxSizing: "border-box",
            background: C.bg,
            border: `1px solid ${err ? C.danger : C.surfaceAlt}`,
            borderRadius: 7,
            color: C.text,
            padding: "9px 12px",
            fontSize: 14,
            outline: "none",
            marginBottom: 4,
          }}
        />
        <input
          type="text"
          placeholder="Watchlist token (returning? paste it here)"
          aria-label="Watchlist token (optional)"
          autoComplete="off"
          spellCheck={false}
          value={token}
          onChange={(e) => { setToken(e.target.value); setErr(""); }}
          onKeyDown={onKey}
          style={{
            width: "100%",
            boxSizing: "border-box",
            background: C.bg,
            border: `1px solid ${C.surfaceAlt}`,
            borderRadius: 7,
            color: C.text,
            padding: "9px 12px",
            fontSize: 13,
            fontFamily: "monospace",
            outline: "none",
            margin: "6px 0 4px",
          }}
        />
        {err && (
          <div style={{ color: C.danger, fontSize: 12, marginBottom: 8 }}>{err}</div>
        )}
        {!err && <div style={{ height: 12 }} />}

        <div style={{ display: "flex", gap: 10, marginTop: 4 }}>
          <button
            onClick={onCancel}
            style={{
              flex: 1,
              background: "transparent",
              border: "1px solid var(--c-surfaceAlt)",
              borderRadius: 7,
              color: C.textMuted,
              padding: "8px 0",
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={busy}
            style={{
              flex: 2,
              background: C.accentSolid,
              border: "none",
              borderRadius: 7,
              color: "#fff",
              padding: "8px 0",
              fontSize: 13,
              fontWeight: 700,
              cursor: "pointer",
            }}
          >
            {busy ? "Checking…" : "Save & Watch"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function WatchlistButton({ ticker, size = "sm" }: WatchlistButtonProps) {
  const [state, setState] = useState<WatchState>("idle");
  const [showModal, setShowModal] = useState(false);

  const dims = size === "md"
    ? { pad: "4px 10px", font: 12 }
    : { pad: "2px 7px", font: 11 };

  const [modalEmail, setModalEmail] = useState("");
  const [modalError, setModalError] = useState("");

  const tryAdd = async (email: string): Promise<void> => {
    try {
      const r = await addToWatchlist({ email, ticker });
      setState(r.data.status === "already_watching" ? "exists" : "added");
      setTimeout(() => setState("idle"), 2500);
    } catch (err) {
      const status = isAxiosError(err) ? err.response?.status : undefined;
      if (status === 401 || status === 403) {
        // This email already has a saved watchlist, and this browser doesn't
        // have its token: ask for it instead of flashing a bare error.
        setModalEmail(email);
        setModalError(
          "This email already has a saved watchlist. Paste your token to add to it, " +
          "or open My Watchlist to email yourself a new one.",
        );
        setShowModal(true);
        return;
      }
      setState("error");
      setTimeout(() => setState("idle"), 2500);
    }
  };

  const doAdd = async (email: string): Promise<void> => {
    localStorage.setItem(EMAIL_KEY, email);
    setShowModal(false);
    setModalError("");
    await tryAdd(email);
  };

  const handleClick = async (e: React.MouseEvent<HTMLButtonElement>): Promise<void> => {
    e.preventDefault();
    e.stopPropagation();
    if (!ticker) return;

    const email = localStorage.getItem(EMAIL_KEY);
    if (!email) {
      setModalEmail("");
      setModalError("");
      setShowModal(true);
      return;
    }
    await tryAdd(email);
  };

  const meta = {
    idle:   { label: "+ Watch",    color: C.textMuted, border: C.surfaceAlt,             bg: "transparent" },
    added:  { label: "✓ Added",   color: C.success, border: "rgba(74,222,128,0.3)", bg: "rgba(74,222,128,0.1)" },
    exists: { label: "✓ Watching", color: C.accent, border: "rgba(56,189,248,0.3)", bg: "rgba(56,189,248,0.1)" },
    error:  { label: "✕ Error",   color: C.danger, border: "rgba(248,113,113,0.3)", bg: "rgba(248,113,113,0.1)" },
  }[state];

  return (
    <>
      {showModal && (
        <EmailModal
          key={modalError}
          ticker={ticker}
          onConfirm={doAdd}
          onCancel={() => { setShowModal(false); setModalError(""); }}
          initialEmail={modalEmail}
          initialError={modalError}
        />
      )}
      <button
        onClick={handleClick}
        title={`Add ${ticker} to your watchlist`}
        style={{
          background: meta.bg,
          color: meta.color,
          border: `1px solid ${meta.border}`,
          borderRadius: 5,
          padding: dims.pad,
          fontSize: dims.font,
          fontWeight: 600,
          cursor: "pointer",
          whiteSpace: "nowrap",
          lineHeight: 1.2,
        }}
      >
        {meta.label}
      </button>
    </>
  );
}
