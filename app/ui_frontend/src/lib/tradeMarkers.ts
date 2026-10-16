// Turns Congress trades and Form 4 insider transactions into one marker per
// (trading day, side) for the daily candle chart.

export type Side = "buy" | "sell";

export interface TradeEvent {
  date: string;   // YYYY-MM-DD the trade happened
  side: Side;
  who: string;    // short label for the marker: a surname or an insider title
  detail: string; // longer line for the tooltip
}

export interface DayMarker {
  time: string;   // the candle date the marker sits on
  side: Side;
  text: string;
  details: string[];
}

/**
 * Snap each event to the first candle on or after its date (a Saturday trade
 * lands on Monday), drop events outside the candle range, and merge events
 * that share a day and side. `candleDates` must be sorted ascending.
 *
 * Labels within `minGap` candles of the previous labelled marker on the same
 * side are blanked so they don't overprint; the arrow and tooltip remain.
 */
export function buildDayMarkers(events: TradeEvent[], candleDates: string[], minGap = 3): DayMarker[] {
  if (!candleDates.length) return [];
  const first = candleDates[0];
  const last = candleDates[candleDates.length - 1];
  const groups = new Map<string, { time: string; side: Side; events: TradeEvent[] }>();

  for (const ev of events) {
    if (ev.date < first || ev.date > last) continue;
    const time = candleDates.find((d) => d >= ev.date);
    if (!time) continue;
    const key = `${time}|${ev.side}`;
    const g = groups.get(key) ?? { time, side: ev.side, events: [] };
    g.events.push(ev);
    groups.set(key, g);
  }

  const markers = [...groups.values()]
    .map((g) => ({
      time: g.time,
      side: g.side,
      text: g.events.length === 1 ? g.events[0].who : `${g.events.length} ${g.side}s`,
      details: g.events.map((e) => e.detail),
    }))
    .sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : a.side.localeCompare(b.side)));

  const lastLabelled: Partial<Record<Side, number>> = {};
  for (const m of markers) {
    const idx = candleDates.indexOf(m.time);
    const prev = lastLabelled[m.side];
    if (prev !== undefined && idx - prev < minGap) m.text = "";
    else lastLabelled[m.side] = idx;
  }
  return markers;
}

function surname(name: string): string {
  const parts = name.trim().split(/\s+/);
  return parts[parts.length - 1] ?? name;
}

function money(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toLocaleString()}`;
}

export function congressEvent(t: {
  trade_date: string | null;
  direction: Side | null;
  amount_range: string | null;
  politician: { name: string } | null;
}): TradeEvent | null {
  if (!t.trade_date || !t.direction) return null;
  const name = t.politician?.name ?? "Member of Congress";
  return {
    date: t.trade_date,
    side: t.direction,
    who: surname(name),
    detail: `${name} (Congress) ${t.direction}${t.amount_range ? ` · ${t.amount_range}` : ""}`,
  };
}

export function insiderEvent(t: {
  transaction_type: string;
  transaction_date?: string | null;
  insider_name: string;
  insider_title?: string | null;
  value?: number | null;
}): TradeEvent | null {
  if (!t.transaction_date) return null;
  if (t.transaction_type !== "buy" && t.transaction_type !== "sell") return null;
  const title = t.insider_title?.trim();
  return {
    date: t.transaction_date,
    side: t.transaction_type,
    who: title && title.length <= 12 ? title : "Insider",
    detail: `${t.insider_name}${title ? `, ${title}` : ""} ${t.transaction_type}${t.value ? ` · ${money(t.value)}` : ""}`,
  };
}
