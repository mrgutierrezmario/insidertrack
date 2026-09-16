/**
 * Sanitize a URL that came from an external feed (news, SEC, OGE) before
 * passing it to an <a href={...}>.
 *
 * React 18 emits a warning but still renders `javascript:` URLs in href —
 * a click executes the script. Tickers/officials/news rows pull from external
 * sources without strict per-field URL validation, so a malicious entry
 * could (in theory) plant a payload.
 *
 * This helper accepts only http(s):// and mailto: URLs. Anything else (including
 * `javascript:`, `data:`, `vbscript:`, `file:`, empty strings, undefined)
 * returns "#" — the link renders but click is a no-op page-anchor jump.
 */
export function safeHref(url: string | null | undefined): string {
  if (!url) return "#";
  const trimmed = url.trim();
  if (!trimmed) return "#";
  // Allow protocol-relative URLs and same-origin paths
  if (trimmed.startsWith("/") || trimmed.startsWith("#")) return trimmed;
  // Strict scheme allowlist
  const lower = trimmed.toLowerCase();
  if (lower.startsWith("http://") || lower.startsWith("https://") || lower.startsWith("mailto:")) {
    return trimmed;
  }
  return "#";
}
