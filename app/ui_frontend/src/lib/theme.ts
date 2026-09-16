// Single source of truth for color tokens and shared inline-style objects.
//
// Usage:
//   import { C, card, input } from "../lib/theme";
//   <div style={{ ...card, padding: 16 }}>...</div>
//   <span style={{ color: C.textMuted }}>...</span>
//
// Naming convention: semantic over literal. "textMuted" not "slate500" — that
// way a future palette change is a one-place edit. Tier ordering: lighter
// surfaces = higher index (bg → surface → surfaceAlt → border → divider).

export const C = {
  // `as const` at the bottom narrows each value to its literal-string type so
  // consumers like `style={{ color: C.text }}` get string, not arbitrary widen.
  // ── Surfaces (dark → light) ───────────────────────────────────────────────
  bg:           "#0d1117",  // app background, input backgrounds
  bgSunken:     "#0f172a",  // deepest panel (sub-card)
  surface:      "#161b27",  // card / panel background
  surfaceAlt:   "#1e2533",  // border on surface, hover state
  divider:      "#334155",  // subtle dividers
  dividerStrong:"#475569",  // emphasised divider

  // ── Text (dim → bright) ───────────────────────────────────────────────────
  textDimmest:  "#334155",  // disabled / placeholder
  textDim:      "#4b5563",  // de-emphasised
  textMuted:    "#64748b",  // subtitles / metadata
  textSoft:     "#94a3b8",  // secondary body
  text:         "#e2e8f0",  // primary body
  textBright:   "#f1f5f9",  // headings
  textFaint:    "#475569",  // captions

  // ── Semantic ──────────────────────────────────────────────────────────────
  accent:       "#38bdf8",  // links / focus
  accentSolid:  "#1d4ed8",  // primary button
  success:      "#4ade80",  // UP / positive
  successDeep:  "#166534",  // success border
  successBg:    "#052e16",  // success badge background
  danger:       "#f87171",  // DOWN / negative
  dangerSolid:  "#ef4444",  // error
  dangerDeep:   "#7f1d1d",  // danger border
  dangerBg:     "#450a0a",  // danger badge background
  warning:      "#fb923c",  // high risk / overdue
  warningSolid: "#fbbf24",  // pause / caution
  warningDeep:  "#78350f",  // warning border
  warningBg:    "#1c1917",  // warning badge background
  info:         "#a78bfa",  // neutral accent (purple)
} as const;

export type ColorToken = keyof typeof C;

// ── Common inline-style objects ─────────────────────────────────────────────
// Spread these to keep the per-page diff small while still going through the
// theme module. Override individual props as needed.

import type { CSSProperties } from "react";

export const card: CSSProperties = {
  background: C.surface,
  border:     `1px solid ${C.surfaceAlt}`,
  borderRadius: 10,
};

export const cardLg: CSSProperties = {
  background: C.surface,
  border:     `1px solid ${C.surfaceAlt}`,
  borderRadius: 12,
};

export const input: CSSProperties = {
  background: C.bg,
  color:      C.text,
  border:     `1px solid ${C.divider}`,
  borderRadius: 7,
  padding:    "0.6rem 0.875rem",
  fontSize:   "0.9rem",
  outline:    "none",
};

export const buttonPrimary: CSSProperties = {
  background: C.accentSolid,
  color:      "#fff",
  border:     "none",
  borderRadius: 7,
  padding:    "0.6rem 1.25rem",
  cursor:     "pointer",
  fontSize:   "0.88rem",
  fontWeight: 600,
};

export const buttonGhost: CSSProperties = {
  background: C.surfaceAlt,
  color:      C.textSoft,
  border:     `1px solid ${C.divider}`,
  borderRadius: 6,
  padding:    "6px 12px",
  fontSize:   13,
  cursor:     "pointer",
};

// ── Status palettes (UP/DOWN/FLAT, signal labels) ───────────────────────────

import type { OutcomeDirection, SignalLabel } from "../types/api";

export const OUTCOME_COLORS: Record<OutcomeDirection, string> = {
  UP:   C.success,
  DOWN: C.danger,
  FLAT: C.textSoft,
};

export const LABEL_COLORS: Record<SignalLabel, string> = {
  "Strong Watch": C.success,
  "Watch":        C.accent,
  "Neutral":      C.textSoft,
  "High Risk":    C.warning,
  "Avoid for Now":C.danger,
};
