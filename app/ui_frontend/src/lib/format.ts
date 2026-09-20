/**
 * One place for how dates, chambers and a few labels read across the site,
 * so a table and a card never disagree about the same value.
 */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-09-19" (or an ISO datetime) → "Sep 19, 2026". Falls back to "—". */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  return `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}, ${m[1]}`;
}

/** Same, without the year — for dense tables where every row is this year. */
export function fmtDateShort(iso: string | null | undefined): string {
  if (!iso) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  return `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}`;
}

const CHAMBER: Record<string, string> = { house: "House", senate: "Senate" };

/** "house" → "House". Unknown values pass through. */
export function chamberLabel(c: string | null | undefined): string {
  if (!c) return "";
  return CHAMBER[c.toLowerCase()] ?? c;
}
