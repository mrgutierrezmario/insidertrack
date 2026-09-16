import { C } from "../lib/theme";
import { Link } from "react-router-dom";
import WatchlistButton from "./WatchlistButton";
import type { RiskLevel, Trade } from "../types/api";

interface RiskMetaEntry {
  color: string;
  bg: string;
  border: string;
}

const RISK_META: Record<RiskLevel, RiskMetaEntry> = {
  LOW:    { color: C.success, bg: "rgba(74,222,128,0.1)",  border: "rgba(74,222,128,0.25)" },
  MEDIUM: { color: C.warningSolid, bg: "rgba(251,191,36,0.1)",  border: "rgba(251,191,36,0.25)" },
  HIGH:   { color: C.danger, bg: "rgba(248,113,113,0.1)", border: "rgba(248,113,113,0.25)" },
};

function RiskBadge({ level }: { level: RiskLevel | null }) {
  if (!level) return null;
  const m = RISK_META[level] ?? RISK_META.MEDIUM;
  return (
    <span style={{
      background: m.bg, color: m.color, border: `1px solid ${m.border}`,
      borderRadius: 5, padding: "1px 7px", fontSize: 10, fontWeight: 700,
      letterSpacing: "0.04em", whiteSpace: "nowrap",
    }}>
      {level} RISK
    </span>
  );
}

function tradeColor(type: string | null | undefined): string {
  if (!type) return C.textSoft;
  const t = type.toLowerCase();
  if (t.includes("purchase")) return C.success;
  if (t.includes("sale") && t.includes("partial")) return C.warning;
  if (t.includes("sale")) return C.danger;
  if (t.includes("exchange")) return C.info;
  return C.textSoft;
}

function fmtDate(str: string | null | undefined): string {
  if (!str) return "—";
  const d = new Date(str + "T12:00:00");
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

interface TradeCardProps {
  trade: Trade;
}

export default function TradeCard({ trade }: TradeCardProps) {
  const color = tradeColor(trade.transaction_type);
  return (
    <div
      style={{
        background: C.surface,
        border: "1px solid #1e2533",
        borderRadius: 8,
        padding: "1rem",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-start",
        gap: "1rem",
      }}
    >
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: 4, flexWrap: "wrap" }}>
          <Link
            to={`/ticker/${trade.ticker}`}
            style={{ color: C.accent, fontWeight: 700, fontSize: "1.1rem", textDecoration: "none" }}
          >
            {trade.ticker}
          </Link>
          <span style={{ color, fontSize: "0.8rem" }}>
            {trade.transaction_type}
          </span>
          <RiskBadge level={trade.risk_level} />
          {trade.ticker && <WatchlistButton ticker={trade.ticker} />}
        </div>
        {trade.asset_name && (
          <div style={{ color: C.textMuted, fontSize: "0.8rem", marginBottom: 2 }}>{trade.asset_name}</div>
        )}
        {trade.politician && (
          <Link
            to={`/politician/${trade.politician.id}`}
            style={{ color: C.textSoft, fontSize: "0.85rem", textDecoration: "none" }}
          >
            {trade.politician.name}
            {(trade.politician.party || trade.politician.state)
              ? ` (${[trade.politician.party, trade.politician.state].filter(Boolean).join(" · ")})`
              : ""}
          </Link>
        )}
      </div>
      <div style={{ textAlign: "right", flexShrink: 0 }}>
        <div style={{ color: C.text, fontSize: "0.85rem", marginBottom: 4 }}>{trade.amount_range}</div>
        <div style={{ color: C.textMuted, fontSize: "0.75rem" }}>
          Traded {fmtDate(trade.trade_date)}
        </div>
        <div style={{ color: C.textDim, fontSize: "0.7rem", marginTop: 2 }}>
          Disclosed {fmtDate(trade.disclosure_date)}
        </div>
      </div>
    </div>
  );
}
