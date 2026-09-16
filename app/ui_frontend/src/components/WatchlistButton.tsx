import { C } from "../lib/theme";
import { useState } from "react";
import type { KeyboardEvent } from "react";
import { addToWatchlist } from "../lib/api";
import { EMAIL_KEY } from "../lib/storage";

type WatchState = "idle" | "added" | "exists" | "error";

interface EmailModalProps {
  ticker: string;
  onConfirm: (email: string) => void;
  onCancel: () => void;
}

interface WatchlistButtonProps {
  ticker: string;
  size?: "sm" | "md";
}

function isValidEmail(e: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test((e || "").trim());
}

function EmailModal({ ticker, onConfirm, onCancel }: EmailModalProps) {
  const [value, setValue] = useState("");
  const [err, setErr] = useState("");

  const submit = () => {
    const trimmed = value.trim().toLowerCase();
    if (!trimmed) { setErr("Email is required."); return; }
    if (!isValidEmail(trimmed)) { setErr("Enter a valid email address."); return; }
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
            Save &amp; Watch
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

  const doAdd = async (email: string): Promise<void> => {
    localStorage.setItem(EMAIL_KEY, email);
    setShowModal(false);
    try {
      const r = await addToWatchlist({ email, ticker });
      setState(r.data.status === "already_watching" ? "exists" : "added");
      setTimeout(() => setState("idle"), 2500);
    } catch {
      setState("error");
      setTimeout(() => setState("idle"), 2500);
    }
  };

  const handleClick = async (e: React.MouseEvent<HTMLButtonElement>): Promise<void> => {
    e.preventDefault();
    e.stopPropagation();
    if (!ticker) return;

    const email = localStorage.getItem(EMAIL_KEY);
    if (!email) {
      setShowModal(true);
      return;
    }

    try {
      const r = await addToWatchlist({ email, ticker });
      setState(r.data.status === "already_watching" ? "exists" : "added");
      setTimeout(() => setState("idle"), 2500);
    } catch {
      setState("error");
      setTimeout(() => setState("idle"), 2500);
    }
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
          ticker={ticker}
          onConfirm={doAdd}
          onCancel={() => setShowModal(false)}
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
