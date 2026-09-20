import { C } from "../lib/theme";
import { chamberLabel, fmtDate } from "../lib/format";
import useDocumentTitle from "../hooks/useDocumentTitle";
import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { getTrades, getInsiderTransactions, getFedTrades } from "../lib/api";
import { exportCSV } from "../lib/csv";
import WatchlistButton from "../components/WatchlistButton";
import SkeletonCard from "../components/SkeletonCard";

const PAGE_SIZE = 50;

type Source = "congressional" | "corporate" | "fed";

const SOURCE_META: Record<Source, { label: string; color: string; bg: string }> = {
  congressional: { label: "Congress",  color: C.info, bg: "rgba(167,139,250,0.1)" },
  corporate:     { label: "Insider",   color: C.accent, bg: "rgba(56,189,248,0.1)"  },
  fed:           { label: "Fed",       color: C.warningSolid, bg: "rgba(251,191,36,0.1)"  },
};

interface ActivityItem {
  id: number;
  ticker: string;
  trade_date: string;
  transaction_type?: string | null;
  amount_range?: string | null;
  _direction: "buy" | "sell" | null;   // the bet on the ticker; null = neutral
  _source: Source;
  _who: string;
  _role?: string | null;
}

function SourceBadge({ source }: { source: Source }) {
  const m = SOURCE_META[source] || SOURCE_META.congressional;
  return (
    <span style={{ background: m.bg, color: m.color, border: `1px solid ${m.color}33`, borderRadius: 4, padding: "1px 7px", fontSize: 10, fontWeight: 700 }}>
      {m.label}
    </span>
  );
}

/** Form 4 / Fed rows have no stored direction — read it off the verb. */
function directionFromVerb(type: string | undefined | null): "buy" | "sell" | null {
  const t = (type || "").toLowerCase();
  if (t === "buy" || t.includes("purchase")) return "buy";
  if (t === "sell" || t.includes("sale")) return "sell";
  return null;
}

function ActivityRow({ item }: { item: ActivityItem }) {
  const typeColor = item._direction === "buy" ? C.success : item._direction === "sell" ? C.danger : C.textSoft;

  return (
    <div style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 9, padding: "11px 14px", display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
      <div style={{ flexShrink: 0, width: 80 }}>
        <div style={{ color: C.textDim, fontSize: 11 }}>{fmtDate(item.trade_date)}</div>
        <SourceBadge source={item._source} />
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 80 }}>
        <Link to={`/ticker/${item.ticker}`} style={{ color: C.accent, fontWeight: 700, textDecoration: "none", fontSize: 14 }}>{item.ticker}</Link>
        <WatchlistButton ticker={item.ticker} />
      </div>

      <div style={{ flex: 1, minWidth: 120 }}>
        <div style={{ color: C.textSoft, fontSize: 12, fontWeight: 500 }}>{item._who}</div>
        {item._role && <div style={{ color: C.textDim, fontSize: 11 }}>{item._role}</div>}
      </div>

      <div style={{ flexShrink: 0 }}>
        <span style={{ color: typeColor, fontWeight: 700, fontSize: 12, textTransform: "uppercase" }}>
          {item._direction === "buy" ? "BUY" : item._direction === "sell" ? "SELL" : (item.transaction_type || "—")}
        </span>
        {item.amount_range && (
          <div style={{ color: C.textDim, fontSize: 11 }}>{item.amount_range}</div>
        )}
      </div>
    </div>
  );
}

type Payload = { items?: Record<string, unknown>[]; has_more?: boolean } | Record<string, unknown>[] | undefined;
type FetchResult = PromiseSettledResult<{ data: Payload }>;

function asList(data: Payload): Record<string, unknown>[] {
  if (Array.isArray(data)) return data;
  return data?.items ?? [];
}

function asHasMore(data: Payload): boolean {
  if (!data || Array.isArray(data)) return Array.isArray(data) ? data.length === PAGE_SIZE : false;
  if (typeof data.has_more === "boolean") return data.has_more;
  return (data.items ?? []).length === PAGE_SIZE;
}

function normalize(results: [FetchResult, FetchResult, FetchResult]): { items: ActivityItem[]; hasMore: boolean } {
  const [cong, corp, fed] = results;
  const all: ActivityItem[] = [];

  if (cong.status === "fulfilled") {
    for (const t of asList(cong.value.data) as Record<string, unknown>[]) {
      const pol = t.politician as { name?: string; party?: string; chamber?: string } | null | undefined;
      all.push({
        ...(t as object),
        id: t.id as number,
        ticker: t.ticker as string,
        trade_date: t.trade_date as string,
        transaction_type: t.transaction_type as string | undefined,
        amount_range: t.amount_range as string | undefined,
        _direction: (t.direction as "buy" | "sell" | null | undefined) ?? null,
        _source: "congressional",
        _who: pol?.name || "Unknown",
        _role: [pol?.party, chamberLabel(pol?.chamber)].filter(Boolean).join(" · "),
      });
    }
  }

  if (corp.status === "fulfilled") {
    for (const t of asList(corp.value.data) as Record<string, unknown>[]) {
      all.push({
        ...(t as object),
        id: t.id as number,
        ticker: t.ticker as string,
        trade_date: t.transaction_date as string,
        transaction_type: t.transaction_type as string | undefined,
        amount_range: t.amount_range as string | undefined,
        _direction: directionFromVerb(t.transaction_type as string | undefined),
        _source: "corporate",
        _who: t.insider_name as string,
        _role: t.insider_title as string | undefined,
      });
    }
  }

  if (fed.status === "fulfilled") {
    for (const t of asList(fed.value.data) as Record<string, unknown>[]) {
      all.push({
        ...(t as object),
        id: t.id as number,
        ticker: t.ticker as string,
        trade_date: t.trade_date as string,
        transaction_type: t.transaction_type as string | undefined,
        amount_range: t.amount_range as string | undefined,
        _direction: directionFromVerb(t.transaction_type as string | undefined),
        _source: "fed",
        _who: t.official_name as string,
        _role: t.official_title as string | undefined,
      });
    }
  }

  const hasMore = (
    (cong.status === "fulfilled" && asHasMore(cong.value.data)) ||
    (corp.status === "fulfilled" && asHasMore(corp.value.data)) ||
    (fed.status  === "fulfilled" && asHasMore(fed.value.data))
  );

  return { items: all, hasMore };
}


function exportActivityCSV(items: ActivityItem[]) {
  exportCSV(
    ["date", "source", "ticker", "who", "role", "type", "amount_range"],
    items.map((it) => [it.trade_date, it._source, it.ticker, it._who, it._role ?? "", it.transaction_type ?? "", it.amount_range ?? ""]),
    "insidertrack-activity",
  );
}

export default function Activity() {
  useDocumentTitle("Activity");
  const [items, setItems] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const [sources, setSources] = useState<Record<Source, boolean>>({ congressional: true, corporate: true, fed: true });
  const [typeFilter, setTypeFilter] = useState<"all" | "buy" | "sell">("all");
  const [tickerFilter, setTickerFilter] = useState("");
  const [afterDate, setAfterDate] = useState("");

  const fetch = useCallback((off: number, append = false) => {
    const setter = append ? setLoadingMore : setLoading;
    setter(true);
    const dateParams = afterDate ? { since: afterDate } : {};
    Promise.allSettled([
      getTrades({ limit: PAGE_SIZE, offset: off, ...dateParams }),
      getInsiderTransactions({ limit: PAGE_SIZE, offset: off, ...(afterDate ? { after: afterDate } : {}) }),
      getFedTrades({ limit: PAGE_SIZE, offset: off, ...(afterDate ? { after: afterDate } : {}) }),
    ]).then((results) => {
      const { items: newItems, hasMore: more } = normalize(results as [FetchResult, FetchResult, FetchResult]);

      newItems.sort((a, b) => (b.trade_date || "").localeCompare(a.trade_date || ""));

      setItems((prev) => {
        const merged = append ? [...prev, ...newItems] : newItems;
        merged.sort((a, b) => (b.trade_date || "").localeCompare(a.trade_date || ""));
        return merged;
      });
      setHasMore(more);
    }).finally(() => setter(false));
  }, [afterDate]);

  useEffect(() => {
    setOffset(0);
    setItems([]);
    fetch(0, false);
  }, [fetch]);

  const loadMore = () => {
    const nextOffset = offset + PAGE_SIZE;
    setOffset(nextOffset);
    fetch(nextOffset, true);
  };

  const filtered = items.filter((it) => {
    if (!sources[it._source]) return false;
    if (typeFilter === "buy" && it._direction !== "buy") return false;
    if (typeFilter === "sell" && it._direction !== "sell") return false;
    if (tickerFilter && !it.ticker?.includes(tickerFilter.toUpperCase())) return false;
    return true;
  });

  const totalSources = Object.values(sources).filter(Boolean).length;
  const hasActiveFilter = tickerFilter || typeFilter !== "all" || totalSources < 3 || afterDate;

  const clearAll = () => {
    setTickerFilter("");
    setTypeFilter("all");
    setSources({ congressional: true, corporate: true, fed: true });
    setAfterDate("");
  };

  return (
    <div style={{ maxWidth: 900, margin: "0 auto" }}>
      <div className="page-head">
        <div>
          <h1>Activity</h1>
          <p style={{ color: C.textDim, margin: 0, fontSize: 13 }}>
            Congressional trades · Corporate Form 4 insiders · Federal Reserve disclosures — unified timeline.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {filtered.length > 0 && (
            <button onClick={() => exportActivityCSV(filtered)}
              style={{ background: C.surfaceAlt, color: C.textSoft, border: "1px solid var(--c-divider)", borderRadius: 6, padding: "6px 14px", fontSize: 12, cursor: "pointer" }}>
              ↓ CSV
            </button>
          )}
          <button onClick={() => { setOffset(0); setItems([]); fetch(0, false); }} disabled={loading}
            style={{ background: "rgba(56,189,248,0.1)", color: C.accent, border: "1px solid rgba(56,189,248,0.3)", borderRadius: 6, padding: "6px 14px", fontSize: 12, cursor: "pointer", opacity: loading ? 0.6 : 1 }}>
            ↻ Refresh
          </button>
        </div>
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: 10, marginBottom: 16, flexWrap: "wrap", alignItems: "center", background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8, padding: "10px 14px" }}>
        {(Object.entries(SOURCE_META) as [Source, typeof SOURCE_META[Source]][]).map(([key, m]) => (
          <button key={key}
            onClick={() => setSources((s) => ({ ...s, [key]: !s[key] }))}
            style={{
              background: sources[key] ? m.bg : "transparent",
              color: sources[key] ? m.color : C.divider,
              border: `1px solid ${sources[key] ? m.color + "44" : C.surfaceAlt}`,
              borderRadius: 6, padding: "4px 12px", fontSize: 12, cursor: "pointer", fontWeight: 600,
            }}>
            {m.label}
          </button>
        ))}

        <div style={{ width: 1, height: 24, background: C.surfaceAlt, flexShrink: 0 }} />

        {(["all", "buy", "sell"] as const).map((t) => (
          <button key={t}
            onClick={() => setTypeFilter(t)}
            style={{
              background: typeFilter === t ? "rgba(148,163,184,0.1)" : "transparent",
              color: typeFilter === t ? C.textSoft : C.dividerStrong,
              border: `1px solid ${typeFilter === t ? C.divider : C.surfaceAlt}`,
              borderRadius: 6, padding: "4px 10px", fontSize: 12, cursor: "pointer",
            }}>
            {t === "all" ? "All types" : t === "buy" ? "Buys" : "Sells"}
          </button>
        ))}

        <div style={{ width: 1, height: 24, background: C.surfaceAlt, flexShrink: 0 }} />

        <input
          placeholder="Ticker…"
          value={tickerFilter}
          onChange={(e) => setTickerFilter(e.target.value.toUpperCase())}
          style={{ background: C.bg, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, color: C.textBright, padding: "4px 10px", fontSize: 12, width: 90 }}
        />

        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <label style={{ color: C.textDim, fontSize: 10 }}>After date</label>
          <input
            type="date"
            value={afterDate}
            onChange={(e) => setAfterDate(e.target.value)}
            style={{ background: C.bg, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, color: afterDate ? C.textBright : C.dividerStrong, padding: "3px 8px", fontSize: 12, colorScheme: "dark" }}
          />
        </div>

        {hasActiveFilter && (
          <button onClick={clearAll}
            style={{ background: "none", color: C.textMuted, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, padding: "4px 10px", fontSize: 12, cursor: "pointer", marginLeft: "auto" }}>
            Clear
          </button>
        )}
      </div>

      <p style={{ color: C.textDim, fontSize: 12, marginBottom: 12 }}>
        {filtered.length} of {items.length} loaded
      </p>

      {loading ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {[...Array(6)].map((_, i) => <SkeletonCard key={i} lines={2} height={54} />)}
        </div>
      ) : filtered.length === 0 ? (
        <div style={{ color: C.textDim, textAlign: "center", padding: "60px 0", background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 12 }}>
          No activity matches your filters.
        </div>
      ) : (
        <>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {filtered.map((item, i) => <ActivityRow key={`${item._source}-${item.id}-${i}`} item={item} />)}
          </div>

          {hasMore && (
            <div style={{ textAlign: "center", marginTop: 20 }}>
              <button
                onClick={loadMore}
                disabled={loadingMore}
                style={{
                  background: loadingMore ? C.surfaceAlt : "rgba(56,189,248,0.08)",
                  color: C.accent, border: "1px solid rgba(56,189,248,0.25)",
                  borderRadius: 8, padding: "9px 28px", fontSize: 13,
                  cursor: loadingMore ? "not-allowed" : "pointer",
                  opacity: loadingMore ? 0.6 : 1,
                }}
              >
                {loadingMore ? "Loading…" : `Load more (${PAGE_SIZE} per source)`}
              </button>
            </div>
          )}

          {!hasMore && items.length > PAGE_SIZE && (
            <p style={{ textAlign: "center", color: C.textDim, fontSize: 12, marginTop: 16 }}>
              All {items.length} activities loaded.
            </p>
          )}
        </>
      )}
    </div>
  );
}
