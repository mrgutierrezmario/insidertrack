import { C } from "../lib/theme";
import { useState, useEffect, useRef, useCallback } from "react";
import type { KeyboardEvent, MouseEvent, ReactNode } from "react";
import { useNavigate } from "react-router-dom";

interface PoliticianHit {
  id: number;
  name: string;
  party?: string | null;
  state?: string | null;
  is_tracked?: boolean;
}

interface FedHit {
  id: number;
  name: string;
  title?: string | null;
}

interface SearchResults {
  politicians: PoliticianHit[];
  fed_officials?: FedHit[];
  tickers: string[];
}

type Item =
  | ({ type: "politician" } & PoliticianHit)
  | ({ type: "fed" } & FedHit)
  | { type: "ticker"; ticker: string };

const PARTY_COLOR: Record<string, string> = { D: "#3b82f6", R: C.dangerSolid, I: C.info };

function useIsMobile(): boolean {
  const [mobile, setMobile] = useState<boolean>(() =>
    typeof window !== "undefined" && window.innerWidth <= 900
  );
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 900px)");
    const handler = (e: MediaQueryListEvent) => setMobile(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);
  return mobile;
}

function useSearch() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResults | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const navigate = useNavigate();

  const search = useCallback((q: string) => {
    if (!q.trim()) { setResults(null); return; }
    fetch(`/search/?q=${encodeURIComponent(q)}`)
      .then((r) => r.json())
      .then((data: SearchResults) => setResults(data))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => search(query), 220);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, search]);

  const go = (item: Item, onDone?: () => void) => {
    if (item.type === "politician") navigate(`/politician/${item.id}`);
    else if (item.type === "fed") navigate(`/fed`);
    else navigate(`/ticker/${item.ticker}`);
    setQuery("");
    setResults(null);
    onDone?.();
  };

  const allItems: Item[] = results
    ? [
        ...results.politicians.map((p): Item => ({ type: "politician", ...p })),
        ...(results.fed_officials || []).map((f): Item => ({ type: "fed", ...f })),
        ...results.tickers.map((t): Item => ({ type: "ticker", ticker: t })),
      ]
    : [];

  const hasResults = !!results && (
    results.politicians.length > 0 ||
    (results.fed_officials || []).length > 0 ||
    results.tickers.length > 0
  );

  return { query, setQuery, results, allItems, hasResults, go };
}

// ── Mobile full-screen overlay ────────────────────────────────────────────────
function MobileSearch() {
  const [open, setOpen] = useState(false);
  const { query, setQuery, hasResults, results, go } = useSearch();
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 60);
  }, [open]);

  // Cmd+K / Ctrl+K to open overlay on mobile too
  useEffect(() => {
    const handler = (e: globalThis.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen(true);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  // Close on back navigation
  useEffect(() => {
    if (!open) return;
    const handler = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open]);

  const close = () => { setOpen(false); setQuery(""); };

  return (
    <>
      <input
        readOnly
        onClick={() => setOpen(true)}
        placeholder="Search…"
        style={{
          background: C.surface, border: "1px solid var(--c-surfaceAlt)",
          color: C.textSoft, borderRadius: 6,
          padding: "5px 10px", fontSize: "0.82rem",
          width: 110, cursor: "pointer", outline: "none",
        }}
      />

      {open && (
        <div style={{
          position: "fixed", inset: 0, zIndex: 500,
          background: C.bg,
          display: "flex", flexDirection: "column",
        }}>
          {/* Search bar row */}
          <div style={{
            display: "flex", alignItems: "center", gap: 10,
            padding: "12px 16px",
            borderBottom: "1px solid var(--c-surfaceAlt)",
            flexShrink: 0,
          }}>
            <button
              onClick={close}
              style={{ background: "none", border: "none", color: C.textSoft, fontSize: 22, cursor: "pointer", padding: "0 4px", lineHeight: 1 }}
            >
              ←
            </button>
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search ticker or person…"
              style={{
                flex: 1,
                background: C.surface,
                color: C.text,
                border: "1px solid var(--c-surfaceAlt)",
                borderRadius: 8,
                padding: "10px 14px",
                fontSize: 16,
                outline: "none",
              }}
            />
            {query && (
              <button
                onClick={() => setQuery("")}
                style={{ background: "none", border: "none", color: C.textMuted, fontSize: 18, cursor: "pointer", padding: "0 4px" }}
              >
                ✕
              </button>
            )}
          </div>

          {/* Results */}
          <div style={{ flex: 1, overflowY: "auto" }}>
            {!query.trim() && (
              <div style={{ color: C.textDim, fontSize: 14, textAlign: "center", padding: "48px 24px" }}>
                Type a ticker symbol or politician name
              </div>
            )}
            {query.trim() && !hasResults && results && (
              <div style={{ color: C.textDim, fontSize: 14, textAlign: "center", padding: "48px 24px" }}>
                No results for "{query}"
              </div>
            )}
            {hasResults && results && (
              <>
                {results.politicians.length > 0 && (
                  <Section label="Politicians">
                    {results.politicians.map((p) => (
                      <MobileItem key={p.id} onClick={() => go({ type: "politician", ...p }, close)}>
                        <span style={{ color: C.text, fontWeight: 500, fontSize: 15 }}>{p.name}</span>
                        <span style={{ display: "flex", gap: 8, alignItems: "center", marginLeft: "auto" }}>
                          {p.party && <span style={{ color: PARTY_COLOR[p.party] || C.textMuted, fontSize: 12, fontWeight: 600 }}>{p.party}</span>}
                          <span style={{ color: C.textDim, fontSize: 12 }}>{p.state}</span>
                          {p.is_tracked && <span style={{ color: "#7c3aed", fontSize: 11 }}>●</span>}
                        </span>
                      </MobileItem>
                    ))}
                  </Section>
                )}
                {(results.fed_officials ?? []).length > 0 && (
                  <Section label="Fed Officials">
                    {(results.fed_officials ?? []).map((f) => (
                      <MobileItem key={f.id} onClick={() => { go({ type: "fed", ...f }, close); }}>
                        <span style={{ color: C.text, fontWeight: 500, fontSize: 15 }}>{f.name}</span>
                        <span style={{ color: C.textDim, fontSize: 11, marginLeft: "auto" }}>{f.title?.split(",")[0]}</span>
                      </MobileItem>
                    ))}
                  </Section>
                )}
                {results.tickers.length > 0 && (
                  <Section label="Tickers">
                    {results.tickers.map((t) => (
                      <MobileItem key={t} onClick={() => go({ type: "ticker", ticker: t }, close)}>
                        <span style={{ color: C.accent, fontWeight: 700, fontFamily: "monospace", fontSize: 16 }}>{t}</span>
                        <span style={{ color: C.textDim, fontSize: 12, marginLeft: "auto" }}>→ Ticker page</span>
                      </MobileItem>
                    ))}
                  </Section>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div style={{ padding: "10px 16px 6px", color: C.textDim, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em", borderTop: "1px solid var(--c-surfaceAlt)" }}>
        {label}
      </div>
      {children}
    </div>
  );
}

function MobileItem({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <div
      onClick={onClick}
      style={{
        padding: "14px 16px", cursor: "pointer",
        display: "flex", alignItems: "center", gap: 10,
        borderBottom: "1px solid var(--c-surfaceAlt)",
        fontSize: 14,
        WebkitTapHighlightColor: "transparent",
      }}
      onTouchStart={(e) => e.currentTarget.style.background = "var(--c-accentBg)"}
      onTouchEnd={(e) => e.currentTarget.style.background = "transparent"}
    >
      {children}
    </div>
  );
}

// ── Desktop inline search ─────────────────────────────────────────────────────
function DesktopSearch() {
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(-1);
  const { query, setQuery, allItems, hasResults, results, go } = useSearch();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const dropdownRef = useRef<HTMLDivElement | null>(null);

  // Cmd+K / Ctrl+K global shortcut
  useEffect(() => {
    const handler = (e: globalThis.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  useEffect(() => {
    if (query) setOpen(true); else setOpen(false);
    setCursor(-1);
  }, [query]);

  useEffect(() => {
    const handler = (e: globalThis.MouseEvent) => {
      const target = e.target as Node;
      if (dropdownRef.current && !dropdownRef.current.contains(target) &&
          inputRef.current && !inputRef.current.contains(target)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (!open || !allItems.length) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setCursor((c) => Math.min(c + 1, allItems.length - 1)); }
    if (e.key === "ArrowUp")   { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)); }
    if (e.key === "Enter" && cursor >= 0) { e.preventDefault(); go(allItems[cursor]); }
    if (e.key === "Escape") { setOpen(false); setCursor(-1); }
  };

  return (
    <div style={{ position: "relative" }}>
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => query && setOpen(true)}
          onKeyDown={handleKey}
          placeholder="Search…"
          style={{
            background: C.surface, color: C.text,
            border: "1px solid var(--c-surfaceAlt)", borderRadius: 6,
            padding: "0.4rem 2.5rem 0.4rem 0.9rem", fontSize: "0.82rem",
            width: 200, outline: "none",
          }}
        />
        {!query && (
          <span style={{
            position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)",
            color: C.divider, fontSize: "0.68rem", pointerEvents: "none",
            fontFamily: "monospace",
          }}>⌘K</span>
        )}

      {open && (
        <div
          ref={dropdownRef}
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            right: 0,           // anchor right so it doesn't fly off-screen
            minWidth: 280,
            background: C.surface,
            border: "1px solid var(--c-surfaceAlt)",
            borderRadius: 8,
            boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
            zIndex: 1000,
            overflow: "hidden",
          }}
        >
          {!hasResults || !results ? (
            <div style={{ padding: "0.75rem 1rem", color: C.textDim, fontSize: "0.82rem" }}>
              No results for "{query}"
            </div>
          ) : (
            <>
              {results.politicians.length > 0 && (
                <DesktopSection label="Politicians">
                  {results.politicians.map((p, i) => (
                    <DesktopItem key={p.id} active={cursor === i}
                      onClick={() => go({ type: "politician", ...p })}
                      onMouseEnter={() => setCursor(i)}>
                      <span style={{ color: C.text, fontWeight: 500 }}>{p.name}</span>
                      <span style={{ marginLeft: "auto", display: "flex", gap: "0.4rem", alignItems: "center" }}>
                        {p.party && <span style={{ color: PARTY_COLOR[p.party] || C.textMuted, fontSize: "0.72rem", fontWeight: 600 }}>{p.party}</span>}
                        <span style={{ color: C.textDim, fontSize: "0.72rem" }}>{p.state}</span>
                        {p.is_tracked && <span style={{ color: "#7c3aed", fontSize: "0.7rem" }}>●</span>}
                      </span>
                    </DesktopItem>
                  ))}
                </DesktopSection>
              )}
              {(results.fed_officials ?? []).length > 0 && (
                <DesktopSection label="Fed Officials">
                  {(results.fed_officials ?? []).map((f, i) => {
                    const idx = results.politicians.length + i;
                    return (
                      <DesktopItem key={f.id} active={cursor === idx}
                        onClick={() => go({ type: "fed", ...f })}
                        onMouseEnter={() => setCursor(idx)}>
                        <span style={{ color: C.text, fontWeight: 500 }}>{f.name}</span>
                        <span style={{ color: C.textDim, fontSize: "0.72rem", marginLeft: "auto" }}>{f.title?.split(",")[0]}</span>
                      </DesktopItem>
                    );
                  })}
                </DesktopSection>
              )}
              {results.tickers.length > 0 && (
                <DesktopSection label="Tickers">
                  {results.tickers.map((t, i) => {
                    const idx = results.politicians.length + (results.fed_officials ?? []).length + i;
                    return (
                      <DesktopItem key={t} active={cursor === idx}
                        onClick={() => go({ type: "ticker", ticker: t })}
                        onMouseEnter={() => setCursor(idx)}>
                        <span style={{ color: C.accent, fontWeight: 700, fontFamily: "monospace" }}>{t}</span>
                        <span style={{ color: C.textDim, fontSize: "0.72rem", marginLeft: "auto" }}>→ Ticker page</span>
                      </DesktopItem>
                    );
                  })}
                </DesktopSection>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function DesktopSection({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div style={{ padding: "0.4rem 1rem 0.25rem", color: C.textDim, fontSize: "0.68rem", textTransform: "uppercase", letterSpacing: "0.06em", borderTop: "1px solid var(--c-surfaceAlt)" }}>
        {label}
      </div>
      {children}
    </div>
  );
}

function DesktopItem({ active, onClick, onMouseEnter, children }: { active: boolean; onClick: (e: MouseEvent<HTMLDivElement>) => void; onMouseEnter: () => void; children: ReactNode }) {
  return (
    <div onClick={onClick} onMouseEnter={onMouseEnter}
      style={{
        padding: "0.55rem 1rem", cursor: "pointer",
        display: "flex", alignItems: "center", gap: "0.5rem",
        background: active ? "var(--c-accentBg)" : "transparent",
        fontSize: "0.85rem", transition: "background 0.1s",
      }}>
      {children}
    </div>
  );
}

// ── Entry point ───────────────────────────────────────────────────────────────
export default function SearchBar() {
  const isMobile = useIsMobile();
  return isMobile ? <MobileSearch /> : <DesktopSearch />;
}
