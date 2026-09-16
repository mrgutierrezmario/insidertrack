import { C } from "../lib/theme";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getEarningsCalendar } from "../lib/api";
import { EMAIL_KEY } from "../lib/storage";

interface EarningsItem {
  ticker: string;
  company: string;
  report_date: string;
  fiscal_date_ending?: string;
  days_until: number | null;
  estimate?: number | null;
}

interface EarningsData {
  upcoming: EarningsItem[];
  recent: EarningsItem[];
  has_key: boolean;
}

function daysLabel(days: number | null | undefined): string {
  if (days === null || days === undefined) return "";
  if (days === 0) return "Today";
  if (days === 1) return "Tomorrow";
  if (days < 0) return `${Math.abs(days)}d ago`;
  return `in ${days}d`;
}

function daysColor(days: number | null | undefined): string {
  if (days === null || days === undefined) return C.textMuted;
  if (days < 0) return C.dividerStrong;
  if (days <= 3) return C.danger;
  if (days <= 7) return C.warning;
  if (days <= 14) return C.warningSolid;
  return C.success;
}

function fmtDate(d: string | null | undefined): string {
  if (!d) return "—";
  return new Date(d + "T00:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" });
}

export default function Earnings() {
  const [data, setData] = useState<EarningsData | null>(null);
  const [loading, setLoading] = useState(true);
  const watchlistEmail = localStorage.getItem(EMAIL_KEY) || null;

  useEffect(() => {
    getEarningsCalendar(watchlistEmail ? { email: watchlistEmail } : {})
      .then((r) => setData(r.data as EarningsData))
      .finally(() => setLoading(false));
  }, []);

  const upcoming = data?.upcoming || [];
  const recent = data?.recent || [];

  return (
    <div style={{ maxWidth: 800, margin: "0 auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 24 }}>
        <div>
          <h1 style={{ color: C.textBright, margin: "0 0 4px", fontSize: "1.4rem" }}>Earnings Calendar</h1>
          <p style={{ color: C.dividerStrong, margin: 0, fontSize: 13 }}>
            Upcoming earnings for tracked tickers · Alpha Vantage · cached 24 hrs
          </p>
        </div>
        {data && !data.has_key && (
          <span style={{ color: C.warningSolid, fontSize: 12, border: "1px solid #78350f", background: C.warningBg, padding: "4px 10px", borderRadius: 6 }}>
            No AV key — add ALPHA_VANTAGE_KEY to .env
          </span>
        )}
      </div>

      {loading && (
        <p style={{ color: C.textMuted, textAlign: "center", paddingTop: 40 }}>Loading earnings…</p>
      )}

      {!loading && upcoming.length === 0 && !data?.has_key && (
        <div style={{ textAlign: "center", color: C.textDim, paddingTop: 60 }}>
          <p>Configure Alpha Vantage key in Config to enable the earnings calendar.</p>
        </div>
      )}

      {!loading && upcoming.length === 0 && data?.has_key && (
        <div style={{ textAlign: "center", color: C.textDim, paddingTop: 60 }}>
          <p>No upcoming earnings found for tracked tickers in the next 3 months.</p>
        </div>
      )}

      {upcoming.length > 0 && (
        <>
          <h2 style={{ color: C.textSoft, fontSize: "0.9rem", fontWeight: 600, marginBottom: 12, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Upcoming ({upcoming.length})
          </h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 32 }}>
            {upcoming.map((e) => (
              <div key={e.ticker + e.report_date} style={{
                background: C.surface, border: "1px solid #1e2533", borderRadius: 10,
                padding: "14px 18px", display: "flex", justifyContent: "space-between", alignItems: "center",
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                  <Link to={`/ticker/${e.ticker}`} style={{ color: C.accent, fontWeight: 700, fontSize: "1.1rem", textDecoration: "none", minWidth: 56 }}>
                    {e.ticker}
                  </Link>
                  <div>
                    <div style={{ color: C.text, fontSize: 13 }}>{e.company}</div>
                    <div style={{ color: C.dividerStrong, fontSize: 12 }}>
                      Reports: {fmtDate(e.report_date)}
                      {e.fiscal_date_ending && ` · FY ending ${e.fiscal_date_ending}`}
                    </div>
                  </div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div style={{ color: daysColor(e.days_until), fontWeight: 700, fontSize: 14 }}>
                    {daysLabel(e.days_until)}
                  </div>
                  {e.estimate != null && (
                    <div style={{ color: C.textMuted, fontSize: 12 }}>Est. EPS: {e.estimate}</div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {recent.length > 0 && (
        <>
          <h2 style={{ color: C.dividerStrong, fontSize: "0.9rem", fontWeight: 600, marginBottom: 12, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Recent
          </h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {recent.map((e) => (
              <div key={e.ticker + e.report_date} style={{
                background: C.bg, border: "1px solid #1e2533", borderRadius: 10,
                padding: "12px 18px", display: "flex", justifyContent: "space-between", alignItems: "center", opacity: 0.6,
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                  <Link to={`/ticker/${e.ticker}`} style={{ color: C.accent, fontWeight: 700, fontSize: "1rem", textDecoration: "none", minWidth: 56 }}>
                    {e.ticker}
                  </Link>
                  <div style={{ color: C.dividerStrong, fontSize: 13 }}>Reported {fmtDate(e.report_date)}</div>
                </div>
                <div style={{ color: C.textDim, fontSize: 12 }}>{daysLabel(e.days_until)}</div>
              </div>
            ))}
          </div>
        </>
      )}

      <div style={{ marginTop: 24, padding: "12px 14px", background: C.bg, borderRadius: 8, border: "1px solid #1e2533", fontSize: 12, color: C.dividerStrong }}>
        Earnings dates are estimates from Alpha Vantage. Confirm on company IR sites before trading.
      </div>
    </div>
  );
}
