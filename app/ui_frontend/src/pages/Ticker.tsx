import { safeHref } from "../lib/safeUrl";
import { fmtDate } from "../lib/format";
import { C } from "../lib/theme";
import useDocumentTitle from "../hooks/useDocumentTitle";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { isAxiosError } from "axios";
import { getTrades, getInsiderTransactions, getIntraday, getPriceHistory, getTickerInfo, getMarketStatus, getTickerNews, getTickerEarnings } from "../lib/api";
import AiSummaryPanel from "../components/AiSummaryPanel";
import TradeCard from "../components/TradeCard";
import StockChart from "../components/StockChart";
import WatchlistButton from "../components/WatchlistButton";
import type { Trade } from "../types/api";

const INTERVALS = ["1min", "5min", "15min", "30min", "60min"] as const;
type Interval = typeof INTERVALS[number];

interface InsiderTxn {
  id: number;
  transaction_type: string;
  insider_name: string;
  insider_title?: string | null;
  shares?: number | null;
  value?: number | null;
  transaction_date?: string | null;
}

interface Candle {
  time?: string;
  date?: string;
  open: number;
  high: number;
  low: number;
  close: number;
  _demo?: boolean;
}

interface TickerInfo {
  name?: string;
  sector?: string;
  industry?: string;
  market_cap?: number | null;
  "52w_high"?: number | null;
  "52w_low"?: number | null;
}

interface NewsItem {
  url: string;
  title: string;
  source: string;
  tickers?: string[];
  overall_label?: string | null;
  overall_color?: string | null;
}

interface Earnings {
  report_date: string;
  fiscal_date_ending?: string | null;
  estimate?: number | null;
  days_until: number;
}

function fmtValue(n: number | null | undefined): string | null {
  if (!n) return null;
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toLocaleString()}`;
}

function InsiderRow({ txn }: { txn: InsiderTxn }) {
  const isBuy = txn.transaction_type === "buy";
  return (
    <div style={{
      background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8,
      padding: "0.75rem 1rem", display: "flex", justifyContent: "space-between",
      alignItems: "center", gap: "1rem", flexWrap: "wrap",
    }}>
      <div style={{ flex: 1, minWidth: 160 }}>
        <div style={{ color: C.text, fontWeight: 600, fontSize: "0.88rem" }}>{txn.insider_name}</div>
        {txn.insider_title && (
          <div style={{ color: C.textMuted, fontSize: "0.75rem", marginTop: 2 }}>{txn.insider_title}</div>
        )}
      </div>
      <div style={{ display: "flex", gap: "1.25rem", alignItems: "center", flexShrink: 0 }}>
        {txn.shares && (
          <div style={{ textAlign: "right" }}>
            <div style={{ color: C.textSoft, fontSize: "0.82rem" }}>
              {txn.shares >= 1_000 ? `${(txn.shares / 1_000).toFixed(0)}K` : txn.shares.toLocaleString()} shares
            </div>
            {fmtValue(txn.value) && (
              <div style={{ color: C.textMuted, fontSize: "0.75rem" }}>{fmtValue(txn.value)}</div>
            )}
          </div>
        )}
        <div style={{ textAlign: "right", minWidth: 60 }}>
          <div style={{
            color: isBuy ? C.success : C.danger,
            fontWeight: 700, fontSize: "0.8rem", textTransform: "uppercase",
          }}>
            {isBuy ? "BUY" : "SELL"}
          </div>
          {txn.transaction_date && (
            <div style={{ color: C.textDim, fontSize: "0.72rem" }}>{txn.transaction_date}</div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function Ticker() {
  const { symbol = "" } = useParams<{ symbol: string }>();
  useDocumentTitle(symbol.toUpperCase());
  const [trades, setTrades] = useState<Trade[]>([]);
  const [insiderTxns, setInsiderTxns] = useState<InsiderTxn[]>([]);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [isDemo, setIsDemo] = useState(false);
  const [info, setInfo] = useState<TickerInfo | null>(null);
  const [interval, setInterval] = useState<Interval>("1min");
  const [chartMode, setChartMode] = useState<"intraday" | "history">("intraday");
  const [intradayEnabled, setIntradayEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState("");
  const [news, setNews] = useState<NewsItem[]>([]);
  const [earnings, setEarnings] = useState<Earnings | null>(null);

  useEffect(() => {
    getMarketStatus().then((r) => setIntradayEnabled((r.data as { intraday_enabled?: boolean }).intraday_enabled ?? false));
  }, []);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      getTrades({ ticker: symbol, limit: 100 }),
      getTickerInfo(symbol),
      getTickerNews(symbol).catch(() => ({ data: { items: [] } })),
      getTickerEarnings(symbol).catch(() => ({ data: null })),
      getInsiderTransactions({ ticker: symbol, limit: 50 }).catch(() => ({ data: [] })),
    ]).then(([tradesRes, infoRes, newsRes, earningsRes, insidersRes]) => {
      const tradesData = tradesRes.data as { items?: Trade[] } | Trade[] | undefined;
      setTrades(Array.isArray(tradesData) ? tradesData : tradesData?.items ?? []);
      setInfo(infoRes.data as TickerInfo);
      const newsData = newsRes.data as { items?: NewsItem[] } | undefined;
      setNews((newsData?.items || []).filter((n) => (n.tickers || []).includes(symbol)).slice(0, 5));
      const ed = earningsRes.data as Earnings | null;
      setEarnings(ed && ed.report_date ? ed : null);
      const insData = insidersRes.data as { items?: InsiderTxn[] } | undefined;
      setInsiderTxns(insData?.items ?? []);
    }).finally(() => setLoading(false));
  }, [symbol]);

  useEffect(() => {
    setChartLoading(true);
    setChartError("");
    const fetch = chartMode === "intraday"
      ? getIntraday(symbol, interval)
      : getPriceHistory(symbol, 90);
    fetch
      .then((r) => {
        const c = ((r.data as { candles?: Candle[] }).candles) || [];
        setCandles(c);
        setIsDemo(c.length > 0 && c[0]._demo === true);
      })
      .catch((err: unknown) => {
        const detail = isAxiosError(err) ? (err.response?.data as { detail?: string } | undefined)?.detail : null;
        setChartError(detail || "Could not load chart data");
      })
      .finally(() => setChartLoading(false));
  }, [symbol, chartMode, interval]);

  const formatMarketCap = (n: number | null | undefined): string => {
    if (!n) return "—";
    if (n >= 1e12) return `$${(n / 1e12).toFixed(1)}T`;
    if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
    if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
    return `$${n}`;
  };

  return (
    <div>
      {/* Header */}
      <div style={{ marginBottom: "1.5rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: 4, flexWrap: "wrap" }}>
          <h1 style={{ fontSize: "1.75rem", fontWeight: 700, margin: 0 }}>{symbol}</h1>
          {info?.name && <span style={{ color: C.textMuted, fontSize: "1rem" }}>{info.name}</span>}
          <WatchlistButton ticker={symbol} size="md" />
        </div>
        {info && (
          <div style={{ display: "flex", gap: "2rem", color: C.textSoft, fontSize: "0.8rem", flexWrap: "wrap" }}>
            {info.sector && <span>{info.sector}</span>}
            {info.industry && <span>{info.industry}</span>}
            {info.market_cap && <span>Market cap: {formatMarketCap(info.market_cap)}</span>}
            {info["52w_high"] && <span>52w high: ${info["52w_high"]}</span>}
            {info["52w_low"] && <span>52w low: ${info["52w_low"]}</span>}
          </div>
        )}
      </div>

      {/* Chart controls */}
      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "0.75rem", alignItems: "center", flexWrap: "wrap" }}>
        <button
          onClick={() => setChartMode("intraday")}
          disabled={!intradayEnabled}
          title={!intradayEnabled ? "Add ALPHA_VANTAGE_KEY to .env to enable" : ""}
          style={{
            background: chartMode === "intraday" ? C.accentSolid : C.surfaceAlt,
            color: chartMode === "intraday" ? "#fff" : intradayEnabled ? C.textSoft : C.textDim,
            border: "none", borderRadius: 6, padding: "0.4rem 1rem",
            cursor: intradayEnabled ? "pointer" : "not-allowed", fontSize: "0.85rem",
          }}
        >
          Intraday {!intradayEnabled && "(no key)"}
        </button>
        <button
          onClick={() => setChartMode("history")}
          style={{
            background: chartMode === "history" ? C.accentSolid : C.surfaceAlt,
            color: chartMode === "history" ? "#fff" : C.textSoft,
            border: "none", borderRadius: 6, padding: "0.4rem 1rem",
            cursor: "pointer", fontSize: "0.85rem",
          }}
        >
          90-day
        </button>
        {chartMode === "intraday" && intradayEnabled && (
          <div style={{ display: "flex", gap: "0.25rem", marginLeft: "0.5rem" }}>
            {INTERVALS.map((iv) => (
              <button key={iv} onClick={() => setInterval(iv)}
                style={{
                  background: interval === iv ? C.divider : "transparent",
                  color: interval === iv ? C.text : C.textMuted,
                  border: "1px solid var(--c-surfaceAlt)", borderRadius: 4,
                  padding: "0.25rem 0.6rem", cursor: "pointer", fontSize: "0.75rem",
                }}>
                {iv}
              </button>
            ))}
          </div>
        )}
        <div style={{ marginLeft: "auto", display: "flex", gap: "0.5rem", alignItems: "center" }}>
          {isDemo && (
            <span style={{ background: C.warningBg, color: C.warningSolid, border: "1px solid var(--c-warningDeep)", fontSize: "0.68rem", padding: "1px 8px", borderRadius: 4 }}>
              demo data
            </span>
          )}
          {intradayEnabled && (
            <span style={{ color: C.textDim, fontSize: "0.7rem" }}>Intraday cached 5 min · 25 req/day limit</span>
          )}
        </div>
      </div>

      {/* Chart */}
      <div style={{ background: C.bg, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8, marginBottom: "2rem", minHeight: 320 }}>
        {chartLoading ? (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 320, color: C.textMuted }}>Loading chart...</div>
        ) : chartError ? (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 320, color: C.danger, fontSize: "0.9rem", padding: "2rem", textAlign: "center" }}>
            {chartError}
          </div>
        ) : candles.length > 0 ? (
          <StockChart data={candles} height={320} title={symbol} />
        ) : (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 320, color: C.textDim }}>No chart data available</div>
        )}
      </div>

      <AiSummaryPanel symbol={symbol} />

      {/* Congressional trades */}
      <h2 style={{ fontSize: "1rem", fontWeight: 600, color: C.textSoft, marginBottom: "1rem" }}>
        Congressional Trades ({trades.length})
      </h2>
      {loading ? (
        <p style={{ color: C.textMuted }}>Loading...</p>
      ) : trades.length === 0 ? (
        <p style={{ color: C.textDim }}>No congressional trades recorded for {symbol}.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          {trades.map((t) => <TradeCard key={t.id} trade={t} />)}
        </div>
      )}

      {/* Corporate Form 4 insider trades */}
      <h2 style={{ fontSize: "1rem", fontWeight: 600, color: C.textSoft, margin: "2rem 0 1rem" }}>
        Corporate Insider Trades ({insiderTxns.length})
      </h2>
      {loading ? (
        <p style={{ color: C.textMuted }}>Loading...</p>
      ) : insiderTxns.length === 0 ? (
        <p style={{ color: C.textDim }}>No Form 4 filings recorded for {symbol}.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
          {insiderTxns.map((t) => <InsiderRow key={t.id} txn={t} />)}
        </div>
      )}

      {earnings && (
        <div style={{ marginTop: "2rem" }}>
          <h2 style={{ fontSize: "1rem", fontWeight: 600, color: C.textSoft, marginBottom: "0.75rem" }}>Next Earnings</h2>
          <div style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8, padding: "0.875rem 1rem", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <div style={{ color: C.text, fontWeight: 600 }}>{fmtDate(earnings.report_date)}</div>
              {earnings.fiscal_date_ending && <div style={{ color: C.textMuted, fontSize: "0.8rem" }}>FY ending {earnings.fiscal_date_ending}</div>}
            </div>
            <div style={{ textAlign: "right" }}>
              {earnings.estimate != null && <div style={{ color: C.textSoft, fontSize: "0.85rem" }}>Est. EPS: {earnings.estimate}</div>}
              <div style={{ color: earnings.days_until <= 7 ? C.warning : C.success, fontWeight: 700, fontSize: "0.9rem" }}>
                {earnings.days_until === 0 ? "Today" : earnings.days_until === 1 ? "Tomorrow" : `in ${earnings.days_until} days`}
              </div>
            </div>
          </div>
        </div>
      )}

      {news.length > 0 && (
        <div style={{ marginTop: "2rem" }}>
          <h2 style={{ fontSize: "1rem", fontWeight: 600, color: C.textSoft, marginBottom: "0.75rem" }}>Recent News</h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {news.map((n) => (
              <a key={n.url} href={safeHref(n.url)} target="_blank" rel="noopener noreferrer"
                style={{ display: "block", background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8, padding: "10px 14px", textDecoration: "none" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
                  <div style={{ color: C.text, fontSize: 13, fontWeight: 500, lineHeight: 1.4 }}>{n.title}</div>
                  {n.overall_label && (
                    <span style={{ color: n.overall_color || C.textSoft, fontSize: 11, fontWeight: 700, whiteSpace: "nowrap", flexShrink: 0 }}>
                      {n.overall_label}
                    </span>
                  )}
                </div>
                <div style={{ color: C.dividerStrong, fontSize: 11, marginTop: 4 }}>{n.source}</div>
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
