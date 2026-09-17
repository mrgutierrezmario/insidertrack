// Central registry of browser-storage keys.
// Importing constants from here (instead of inlining the strings) means a key
// rename is a one-place change, and `grep` finds every consumer.

export const EMAIL_KEY            = "insidertrack_email"            as const;  // localStorage — watchlist owner email
export const WATCHLIST_TOKEN_KEY  = "insidertrack_watchlist_token"  as const;  // localStorage — bearer token for the watchlist API (one per email; replaced on each recover)
export const ADMIN_TOKEN_KEY      = "insidertrack_admin_token"      as const;  // sessionStorage — non-sensitive admin-visible flag (httpOnly cookie holds the real token)
export const ADMIN_SESSION_KEY    = "insidertrack_admin_v1"         as const;  // sessionStorage — AdminConfig "logged in this tab" flag
export const AI_SETTINGS_KEY      = "insidertrack_ai"               as const;  // localStorage — visitor's own AI provider/key/model (never sent anywhere but this site's /ai/* endpoints)

// Union of all storage keys — useful for guarding helpers that operate on keys.
export type StorageKey =
  | typeof EMAIL_KEY
  | typeof WATCHLIST_TOKEN_KEY
  | typeof ADMIN_TOKEN_KEY
  | typeof ADMIN_SESSION_KEY
  | typeof AI_SETTINGS_KEY;

export type AiProvider = "claude" | "gemini" | "openai";
export interface OwnAiSettings { provider: AiProvider; key: string; model?: string }

export function readOwnAi(): OwnAiSettings | null {
  try {
    const raw = localStorage.getItem(AI_SETTINGS_KEY);
    if (!raw) return null;
    const v = JSON.parse(raw) as Partial<OwnAiSettings>;
    return v && typeof v.key === "string" && v.key && (["claude", "gemini", "openai"] as string[]).includes(v.provider ?? "")
      ? { provider: v.provider as AiProvider, key: v.key, model: v.model || undefined }
      : null;
  } catch { return null; }
}

export function writeOwnAi(v: OwnAiSettings | null): void {
  try {
    if (v) localStorage.setItem(AI_SETTINGS_KEY, JSON.stringify(v));
    else localStorage.removeItem(AI_SETTINGS_KEY);
  } catch { /* private mode: applies for this page load only */ }
}
