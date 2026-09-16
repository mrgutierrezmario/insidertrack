// Central registry of browser-storage keys.
// Importing constants from here (instead of inlining the strings) means a key
// rename is a one-place change, and `grep` finds every consumer.

export const EMAIL_KEY            = "insidertrack_email"            as const;  // localStorage — watchlist owner email
export const WATCHLIST_TOKEN_KEY  = "insidertrack_watchlist_token"  as const;  // localStorage — bearer token for the watchlist API (one per email; replaced on each recover)
export const ADMIN_TOKEN_KEY      = "insidertrack_admin_token"      as const;  // sessionStorage — non-sensitive admin-visible flag (httpOnly cookie holds the real token)
export const ADMIN_SESSION_KEY    = "insidertrack_admin_v1"         as const;  // sessionStorage — AdminConfig "logged in this tab" flag

// Union of all storage keys — useful for guarding helpers that operate on keys.
export type StorageKey =
  | typeof EMAIL_KEY
  | typeof WATCHLIST_TOKEN_KEY
  | typeof ADMIN_TOKEN_KEY
  | typeof ADMIN_SESSION_KEY;
