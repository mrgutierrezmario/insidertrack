import { safeHref } from "../lib/safeUrl";
import { C } from "../lib/theme";
import useDocumentTitle from "../hooks/useDocumentTitle";
import { useEffect, useState } from "react";
import { getNewsFeed } from "../lib/api";

type SentimentLabel = "Bullish" | "Somewhat-Bullish" | "Neutral" | "Somewhat-Bearish" | "Bearish" | "Headline";

const LABEL_STYLE: Record<SentimentLabel, { color: string; bg: string }> = {
  "Headline": { color: C.textMuted, bg: C.surfaceAlt },
  "Bullish":          { color: C.success, bg: C.successBg },
  "Somewhat-Bullish": { color: "var(--c-success)", bg: "var(--c-successBg)" },
  "Neutral":          { color: C.textSoft, bg: C.bgSunken },
  "Somewhat-Bearish": { color: C.warning, bg: "var(--c-warningBg)" },
  "Bearish":          { color: C.danger, bg: C.dangerBg },
};

interface NewsItem {
  url: string;
  title: string;
  summary?: string;
  tickers?: string[];
  source: string;
  published: string;
  overall_label: SentimentLabel;
}

interface NewsFeedData {
  tickers: string[];
  count: number;
  has_key: boolean;
  items: NewsItem[];
}

function SentimentBadge({ label }: { label: SentimentLabel }) {
  const s = LABEL_STYLE[label] || LABEL_STYLE["Neutral"];
  return (
    <span style={{
      background: s.bg, color: s.color,
      fontSize: "0.68rem", fontWeight: 700,
      padding: "2px 7px", borderRadius: 4, whiteSpace: "nowrap",
    }}>
      {label}
    </span>
  );
}

function fmtDate(iso: string): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch { return iso; }
}

export default function News() {
  useDocumentTitle("News");
  const [data, setData] = useState<NewsFeedData | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");

  const load = () => {
    setLoading(true);
    getNewsFeed()
      .then((r) => setData(r.data as NewsFeedData))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const items = (data?.items || []).filter((n) => {
    if (!filter) return true;
    const f = filter.toUpperCase();
    return (n.tickers || []).some((t) => t.includes(f)) ||
      n.title.toUpperCase().includes(f);
  });

  return (
    <div style={{ maxWidth: 900, margin: "0 auto" }}>
      <div className="page-head">
        <div>
          <h1>News & Sentiment</h1>
          <p style={{ color: C.dividerStrong, margin: 0, fontSize: 13 }}>
            {data?.has_key ? "Headlines for the tickers members are trading most this month · sentiment labels from Alpha Vantage when available · cached 4 hrs" : "Headlines for the tickers members are trading most this month · Google News · cached 4 hrs"}
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {data && !data.has_key && (
            <span style={{ color: C.warningSolid, fontSize: 12, border: "1px solid var(--c-warningDeep)", background: C.warningBg, padding: "4px 10px", borderRadius: 6 }}>
              No AV key — add ALPHA_VANTAGE_KEY to .env
            </span>
          )}
          <button onClick={load} disabled={loading}
            style={{ background: "rgba(56,189,248,0.1)", color: C.accent, border: "1px solid rgba(56,189,248,0.3)", borderRadius: 6, padding: "5px 12px", fontSize: 12, cursor: "pointer", opacity: loading ? 0.6 : 1 }}>
            ↻ Refresh
          </button>
        </div>
      </div>

      {/* Filter bar */}
      <div style={{ marginBottom: 16 }}>
        <input
          placeholder="Filter by ticker or keyword…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          style={{
            background: C.surface, color: C.text,
            border: "1px solid var(--c-surfaceAlt)", borderRadius: 6,
            padding: "0.45rem 0.85rem", fontSize: "0.85rem", width: 280,
          }}
        />
        {data && data.tickers.length > 0 && (
          <span style={{ color: C.dividerStrong, fontSize: 12, marginLeft: 12 }}>
            Most traded this month: {data.tickers.join(", ")}
          </span>
        )}
      </div>

      {loading && (
        <p style={{ color: C.textMuted, textAlign: "center", paddingTop: 40 }}>Loading news…</p>
      )}

      {!loading && items.length === 0 && (
        <div style={{ textAlign: "center", color: C.textDim, paddingTop: 60 }}>
          <p>No news found for these tickers.</p>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {items.map((item) => (
          <a
            key={item.url}
            href={safeHref(item.url)}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: "block",
              background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 10,
              padding: "14px 16px", textDecoration: "none",
              transition: "border-color 0.15s",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
              <div style={{ flex: 1 }}>
                <div style={{ color: C.textBright, fontWeight: 600, fontSize: 14, marginBottom: 6, lineHeight: 1.4 }}>
                  {item.title}
                </div>
                {item.summary && (
                  <div style={{ color: C.textMuted, fontSize: 12, lineHeight: 1.5, marginBottom: 6 }}>
                    {item.summary}
                  </div>
                )}
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  {(item.tickers || []).slice(0, 6).map((t) => (
                    <span key={t} style={{ background: "var(--c-accentBg)", color: C.accent, fontSize: 11, padding: "1px 7px", borderRadius: 4, fontWeight: 700 }}>
                      {t}
                    </span>
                  ))}
                  <span style={{ color: C.divider, fontSize: 11 }}>{item.source}</span>
                  <span style={{ color: C.divider, fontSize: 11 }}>{fmtDate(item.published)}</span>
                </div>
              </div>
              <div style={{ flexShrink: 0 }}>
                <SentimentBadge label={item.overall_label} />
              </div>
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}
