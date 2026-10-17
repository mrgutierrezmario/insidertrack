// Chart indicators computed from daily candles.

export interface LinePoint {
  time: string;
  value: number;
}

/**
 * Simple moving average of the close over `n` bars. The first n-1 bars have
 * no value and are left out. `bars` must be sorted oldest first.
 */
export function sma(bars: { date: string; close: number }[], n: number): LinePoint[] {
  if (n < 1) return [];
  const out: LinePoint[] = [];
  let sum = 0;
  for (let i = 0; i < bars.length; i++) {
    sum += bars[i].close;
    if (i >= n) sum -= bars[i - n].close;
    if (i >= n - 1) out.push({ time: bars[i].date, value: Math.round((sum / n) * 100) / 100 });
  }
  return out;
}

/** The YYYY-MM-DD `days` calendar days before `today` (UTC date math). */
export function daysAgo(today: Date, days: number): string {
  const d = new Date(Date.UTC(today.getFullYear(), today.getMonth(), today.getDate()));
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}
