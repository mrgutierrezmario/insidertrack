import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { isAxiosError } from "axios";
import {
  getWatchlistSignals,
  getModelDeskCalls,
  addToWatchlist,
  removeFromWatchlist,
  recoverWatchlistToken,
} from "../lib/api";
import { EMAIL_KEY, WATCHLIST_TOKEN_KEY } from "../lib/storage";
import { card, LABEL_COLORS , C} from "../lib/theme";
import useDocumentTitle from "../hooks/useDocumentTitle";
import type { ModelCall, SignalLabel } from "../types/api";
import SkeletonCard from "../components/SkeletonCard";
import { CallRow } from "../components/ModelDeskCard";

// The /watchlist/signals endpoint enriches each row with current signal
// state — backend shape lives in `routers/watchlist.py:watchlist_with_signals`.
interface WatchlistRow {
  id: number;
  ticker: string;
  note: string | null;
  composite_score: number | null;
  label: SignalLabel | null;
  signal: "BULLISH" | "NEUTRAL" | "BEARISH" | null;
  current_price: number | null;
  price_7d_change: number | null;
}

type LoadState = "idle" | "loading" | "needs_token" | "loaded";

function isValidEmail(e: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test((e || "").trim());
}

function ChangeChip({ pct }: { pct: number | null }) {
  if (pct == null) return null;
  const pos = pct >= 0;
  return (
    <span style={{
      background: pos ? "rgba(74,222,128,0.1)" : "rgba(248,113,113,0.1)",
      color: pos ? C.success : C.danger,
      border: `1px solid ${pos ? "rgba(74,222,128,0.3)" : "rgba(248,113,113,0.3)"}`,
      borderRadius: 4, padding: "1px 7px", fontSize: 11, fontWeight: 700,
    }}>
      {pos ? "+" : ""}{pct.toFixed(1)}% 7d
    </span>
  );
}

export default function Watchlist() {
  useDocumentTitle("Watchlist");
  const [email, setEmail] = useState<string>(localStorage.getItem(EMAIL_KEY) || "");
  const [emailInput, setEmailInput] = useState<string>(localStorage.getItem(EMAIL_KEY) || "");
  const [items, setItems] = useState<WatchlistRow[]>([]);
  const [state, setState] = useState<LoadState>("idle");
  const [newTicker, setNewTicker] = useState("");
  const [err, setErr] = useState("");
  const [calls, setCalls] = useState<ModelCall[]>([]);
  useEffect(() => { getModelDeskCalls().then((r) => setCalls(r.data.items)).catch(() => setCalls([])); }, []);

  // Recovery UI state
  const [pasteToken, setPasteToken] = useState("");
  const [recoveryMsg, setRecoveryMsg] = useState("");

  const load = (e: string): void => {
    if (!e) return;
    setState("loading");
    getWatchlistSignals(e)
      .then((r) => { setItems(r.data as WatchlistRow[]); setState("loaded"); })
      .catch((error) => {
        if (isAxiosError(error) && (error.response?.status === 401 || error.response?.status === 403)) {
          setItems([]);
          setState("needs_token");
        } else {
          setItems([]);
          setState("loaded");
        }
      });
  };

  useEffect(() => { if (email) load(email); }, [email]);

  const saveEmail = () => {
    if (!isValidEmail(emailInput)) { setErr("Enter a valid email address."); return; }
    setErr("");
    const e = emailInput.trim().toLowerCase();
    localStorage.setItem(EMAIL_KEY, e);
    setEmail(e);
  };

  const add = async () => {
    const t = newTicker.trim().toUpperCase();
    if (!t) return;
    try {
      await addToWatchlist({ email, ticker: t });
      setNewTicker("");
      setErr("");
      load(email);
    } catch (error) {
      if (isAxiosError(error) && (error.response?.status === 401 || error.response?.status === 403)) {
        setState("needs_token");
      } else {
        setErr("Could not add ticker.");
      }
    }
  };

  const remove = async (id: number): Promise<void> => {
    try {
      await removeFromWatchlist(id, email);
      load(email);
    } catch (error) {
      if (isAxiosError(error) && (error.response?.status === 401 || error.response?.status === 403)) {
        setState("needs_token");
      }
    }
  };

  const requestRecovery = async () => {
    setRecoveryMsg("");
    try {
      await recoverWatchlistToken(email);
      setRecoveryMsg(`Recovery email sent to ${email}. Paste the token below to regain access.`);
    } catch {
      setRecoveryMsg("Could not request recovery. Try again in a minute.");
    }
  };

  const applyPastedToken = () => {
    const t = pasteToken.trim();
    if (!t) return;
    localStorage.setItem(WATCHLIST_TOKEN_KEY, t);
    setPasteToken("");
    setRecoveryMsg("");
    load(email);
  };

  const switchEmail = () => {
    localStorage.removeItem(EMAIL_KEY);
    localStorage.removeItem(WATCHLIST_TOKEN_KEY);
    setEmail("");
    setEmailInput("");
    setItems([]);
    setState("idle");
  };

  // ── Email gate ────────────────────────────────────────────────────────────────
  if (!email) {
    return (
      <div style={{ maxWidth: 460, margin: "60px auto", textAlign: "center" }}>
        <h1>My Watchlist</h1>
        <p style={{ color: C.textDim, fontSize: 13, marginBottom: 20 }}>
          Enter your email to create or load your watchlist. No password needed.
        </p>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            type="email" placeholder="you@example.com" value={emailInput}
            onChange={(e) => { setEmailInput(e.target.value); setErr(""); }}
            onKeyDown={(e) => { if (e.key === "Enter") saveEmail(); }}
            style={{ flex: 1, background: C.bg, color: C.text, border: "1px solid var(--c-divider)", borderRadius: 7, padding: "10px 12px", fontSize: 14 }}
          />
          <button onClick={saveEmail}
            style={{ background: C.accentSolid, color: "#fff", border: "none", borderRadius: 7, padding: "10px 18px", fontSize: 14, cursor: "pointer", fontWeight: 600 }}>
            Continue
          </button>
        </div>
        {err && <p style={{ color: C.danger, fontSize: 12, marginTop: 8 }}>{err}</p>}
      </div>
    );
  }

  // ── Recovery gate ─────────────────────────────────────────────────────────────
  // Triggered when the API returns 401/403 — either a legacy user without a token,
  // or one whose stored token doesn't match (e.g. rotated from another device).
  if (state === "needs_token") {
    return (
      <div style={{ maxWidth: 520, margin: "60px auto" }}>
        <h1 style={{ color: C.textBright, fontSize: "1.4rem", marginBottom: 8 }}>Watchlist access</h1>
        <p style={{ color: C.textSoft, fontSize: 13, marginBottom: 16, lineHeight: 1.5 }}>
          Your watchlist for <strong style={{ color: C.text }}>{email}</strong> requires a
          security token. We'll email a fresh token to that address — paste it below to
          regain access.
        </p>
        <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
          <button
            onClick={requestRecovery}
            style={{ background: C.accentSolid, color: "#fff", border: "none", borderRadius: 7, padding: "9px 16px", fontSize: 13, cursor: "pointer", fontWeight: 600 }}>
            Email me a new token
          </button>
          <button
            onClick={switchEmail}
            style={{ background: "transparent", color: C.textSoft, border: "1px solid var(--c-divider)", borderRadius: 7, padding: "9px 16px", fontSize: 13, cursor: "pointer" }}>
            Use a different email
          </button>
        </div>
        {recoveryMsg && (
          <p style={{ color: C.textSoft, fontSize: 12, marginBottom: 12 }}>{recoveryMsg}</p>
        )}
        <label style={{ display: "block", color: C.textSoft, fontSize: 12, marginBottom: 6, fontWeight: 600 }}>
          PASTE YOUR TOKEN
        </label>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            type="text"
            placeholder="paste token from email"
            value={pasteToken}
            onChange={(e) => setPasteToken(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") applyPastedToken(); }}
            style={{ flex: 1, background: C.bg, color: C.text, border: "1px solid var(--c-divider)", borderRadius: 7, padding: "10px 12px", fontSize: 13, fontFamily: "monospace" }}
          />
          <button
            onClick={applyPastedToken}
            disabled={!pasteToken.trim()}
            style={{ background: pasteToken.trim() ? C.accentSolid : "var(--c-surfaceAlt)", color: pasteToken.trim() ? "#fff" : C.textDim, border: "none", borderRadius: 7, padding: "10px 18px", fontSize: 13, cursor: pasteToken.trim() ? "pointer" : "not-allowed", fontWeight: 600 }}>
            Continue
          </button>
        </div>
      </div>
    );
  }

  // ── Main view ────────────────────────────────────────────────────────────────
  return (
    <div style={{ maxWidth: 860, margin: "0 auto" }}>
      <div className="page-head">
        <div>
          <h1 style={{ color: C.textBright, margin: "0 0 4px", fontSize: "1.4rem" }}>My Watchlist</h1>
          <p style={{ color: C.textDim, margin: 0, fontSize: 13 }}>{email}</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={() => load(email)}
            style={{ background: "rgba(56,189,248,0.1)", color: C.accent, border: "1px solid rgba(56,189,248,0.3)", borderRadius: 6, padding: "6px 12px", fontSize: 12, cursor: "pointer" }}>
            ↻ Refresh
          </button>
          <button
            onClick={switchEmail}
            style={{ background: C.surface, color: C.textMuted, border: "1px solid var(--c-divider)", borderRadius: 6, padding: "6px 12px", fontSize: 12, cursor: "pointer" }}>
            Switch email
          </button>
        </div>
      </div>

      {/* Add ticker */}
      <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
        <input
          placeholder="Add a ticker (e.g. NVDA)" value={newTicker}
          onChange={(e) => setNewTicker(e.target.value.toUpperCase())}
          onKeyDown={(e) => { if (e.key === "Enter") add(); }}
          style={{ background: C.bg, color: C.text, border: "1px solid var(--c-divider)", borderRadius: 7, padding: "8px 12px", fontSize: 14, width: 220 }}
        />
        <button onClick={add}
          style={{ background: C.accentSolid, color: "#fff", border: "none", borderRadius: 7, padding: "8px 16px", fontSize: 13, cursor: "pointer", fontWeight: 600 }}>
          + Add
        </button>
      </div>
      {err && <p style={{ color: C.danger, fontSize: 12, marginBottom: 12 }}>{err}</p>}

      {state === "loading" ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {[...Array(3)].map((_, i) => <SkeletonCard key={i} lines={2} height={64} />)}
        </div>
      ) : items.length === 0 ? (
        <div style={{ color: C.textDim, textAlign: "center", padding: "50px 0" }}>
          Your watchlist is empty. Add a ticker above to start tracking its signal score.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {items.map((it) => (
            <div key={it.id} style={{ ...card, padding: "14px 16px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
                <Link to={`/ticker/${it.ticker}`} style={{ color: C.accent, fontWeight: 700, fontSize: 16, textDecoration: "none", minWidth: 60 }}>
                  {it.ticker}
                </Link>
                {it.label ? (
                  <span style={{ color: LABEL_COLORS[it.label] || C.textSoft, fontSize: 13, fontWeight: 600 }}>{it.label}</span>
                ) : (
                  <span style={{ color: C.textDim, fontSize: 12 }}>No signal data</span>
                )}
                <ChangeChip pct={it.price_7d_change} />
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 16, flexShrink: 0 }}>
                {it.composite_score != null && (
                  <div style={{ textAlign: "right" }}>
                    <div style={{ color: C.textBright, fontWeight: 700, fontSize: 18 }}>{it.composite_score}</div>
                    <div style={{ color: C.textDim, fontSize: 10 }}>composite</div>
                  </div>
                )}
                {it.current_price != null && (
                  <div style={{ color: C.textSoft, fontSize: 13 }}>${it.current_price.toLocaleString()}</div>
                )}
                <button onClick={() => remove(it.id)}
                  style={{ background: "transparent", color: C.textDim, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, padding: "4px 10px", fontSize: 12, cursor: "pointer" }}>
                  Remove
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {items.length > 0 && (() => {
        const mine = new Set(items.map((it) => it.ticker));
        const hits = calls.filter((c) => mine.has(c.ticker));
        return (
          <div style={{ ...card, padding: "14px 16px", marginTop: 20 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 4 }}>
              <div style={{ color: C.textSoft, fontSize: 12, fontWeight: 600 }}>AI Desk calls on your tickers</div>
              <Link to="/ai-desk" style={{ color: C.accent, fontSize: 12, textDecoration: "none" }}>All calls →</Link>
            </div>
            {hits.length === 0 ? (
              <p style={{ color: C.textDim, fontSize: 12, margin: "4px 0 0" }}>
                The AI Desk hasn't made a call on any of your tickers yet. It picks a handful each morning from the day's filings; add an alert of type "AI Desk call" to be told when one lands.
              </p>
            ) : (
              <>
                <p style={{ color: C.textDim, fontSize: 12, margin: "0 0 8px" }}>
                  {hits.length} call{hits.length === 1 ? "" : "s"} · the AI's own research view, scored against SPY once the horizon passes.
                </p>
                {hits.map((c) => <CallRow key={c.id} c={c} />)}
              </>
            )}
          </div>
        );
      })()}
    </div>
  );
}
