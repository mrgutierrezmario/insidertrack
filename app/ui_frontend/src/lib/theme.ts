// Single source of truth for color tokens and shared inline-style objects.
//
// Every value is a CSS custom property defined in src/index.css, so inline
// styles follow the light/dark theme automatically. Canvas-based charts need
// real color strings — use resolveColor() for those.
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
  bg:           "var(--c-bg)",  // app background, input backgrounds
  bgSunken:     "var(--c-bgSunken)",  // deepest panel (sub-card)
  surface:      "var(--c-surface)",  // card / panel background
  surfaceAlt:   "var(--c-surfaceAlt)",  // border on surface, hover state
  divider:      "var(--c-divider)",  // subtle dividers
  dividerStrong:"var(--c-dividerStrong)",  // emphasised divider

  // ── Text (dim → bright) ───────────────────────────────────────────────────
  textDimmest:  "var(--c-textDimmest)",  // disabled / placeholder
  textDim:      "var(--c-textDim)",  // de-emphasised
  textMuted:    "var(--c-textMuted)",  // subtitles / metadata
  textSoft:     "var(--c-textSoft)",  // secondary body
  text:         "var(--c-text)",  // primary body
  textBright:   "var(--c-textBright)",  // headings
  textFaint:    "var(--c-textFaint)",  // captions

  // ── Semantic ──────────────────────────────────────────────────────────────
  accent:       "var(--c-accent)",  // links / focus
  accentSolid:  "var(--c-accentSolid)",  // primary button
  accentBg:     "var(--c-accentBg)",     // selected / tinted accent background
  success:      "var(--c-success)",  // UP / positive
  successDeep:  "var(--c-successDeep)",  // success border
  successBg:    "var(--c-successBg)",  // success badge background
  danger:       "var(--c-danger)",  // DOWN / negative
  dangerSolid:  "var(--c-dangerSolid)",  // error
  dangerDeep:   "var(--c-dangerDeep)",  // danger border
  dangerBg:     "var(--c-dangerBg)",  // danger badge background
  warning:      "var(--c-warning)",  // high risk / overdue
  warningSolid: "var(--c-warningSolid)",  // pause / caution
  warningDeep:  "var(--c-warningDeep)",  // warning border
  warningBg:    "var(--c-warningBg)",  // warning badge background
  info:         "var(--c-info)",  // neutral accent (purple)
} as const;

export type ColorToken = keyof typeof C;

/** Resolve any "var(--c-x)" string to its computed value; other strings pass through. */
export function resolveCss(value: string): string {
  const m = /^var\(--c-([a-zA-Z]+)\)$/.exec(value);
  return m ? resolveColor(m[1] as ColorToken) : value;
}

/** Snapshot of every token as a real color string — for canvas charts, which cannot read CSS variables. */
export function resolvedPalette(): Record<ColorToken, string> {
  const out = {} as Record<ColorToken, string>;
  (Object.keys(C) as ColorToken[]).forEach((k) => { out[k] = resolveColor(k); });
  return out;
}

/** Resolve a token to its current computed value (for canvas charts). */
export function resolveColor(token: ColorToken): string {
  if (typeof window === "undefined") return "#000";
  return getComputedStyle(document.documentElement).getPropertyValue(`--c-${token}`).trim() || "#000";
}

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
