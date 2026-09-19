import { C } from "../lib/theme";
import { Link } from "react-router-dom";
import { useState } from "react";
import WatchlistButton from "./WatchlistButton";
import useAdmin from "../hooks/useAdmin";
import { deleteTrade } from "../lib/api";
import { safeHref } from "../lib/safeUrl";
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

/**
 * "Risk" is staleness: how old the trade is and how long the filer took to
 * disclose it. LOW/MEDIUM describe nearly every row, so only HIGH is worth a
 * badge — and it is labelled by what it means, not by a grade.
 */
function RiskBadge({ level }: { level: RiskLevel | null }) {
  if (level !== "HIGH") return null;
  const m = RISK_META[level];
  return (
    <span data-tip="Trade is over 5 weeks old, or was disclosed more than 5 weeks after it happened — the price has likely moved since." style={{
      background: m.bg, color: m.color, border: `1px solid ${m.border}`,
      borderRadius: 5, padding: "1px 7px", fontSize: 10, fontWeight: 700,
      letterSpacing: "0.04em", whiteSpace: "nowrap",
    }}>
      STALE
    </span>
  );
}

function tradeColor(trade: Trade): string {
  // Colour follows the bet, not the verb: a put purchase is bearish.
  if (trade.direction === "buy") return C.success;
  if (trade.direction === "sell") {
    return (trade.transaction_type || "").toLowerCase().includes("partial") ? C.warning : C.danger;
  }
  if ((trade.transaction_type || "").toLowerCase().includes("exchange")) return C.info;
  return C.textSoft;
}

const OWNER_LABEL: Record<NonNullable<Trade["owner"]>, string> = {
  self: "", spouse: "Spouse", child: "Child", joint: "Joint",
};

function Tag({ children, tip }: { children: string; tip: string }) {
  return (
    <span data-tip={tip} style={{
      background: C.surfaceAlt, color: C.textMuted, borderRadius: 5, padding: "1px 7px",
      fontSize: 10, fontWeight: 700, letterSpacing: "0.04em", whiteSpace: "nowrap",
    }}>
      {children}
    </span>
  );
}

function fmtDate(str: string | null | undefined): string {
  if (!str) return "—";
  const d = new Date(str + "T12:00:00");
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

interface TradeCardProps {
  trade: Trade;
  onRemoved?: (id: number) => void;
}

export default function TradeCard({ trade, onRemoved }: TradeCardProps) {
  const color = tradeColor(trade);
  const ownerLabel = trade.owner ? OWNER_LABEL[trade.owner] : "";
  const isPaper = (trade.source || "").endsWith("-paper");
  const isAdmin = useAdmin();
  const [removing, setRemoving] = useState(false);
  const remove = async () => {
    if (!window.confirm(`Remove this ${trade.ticker} row? It was read by the AI model from a scanned filing.`)) return;
    setRemoving(true);
    try { await deleteTrade(trade.id); onRemoved?.(trade.id); } finally { setRemoving(false); }
  };
  return (
    <div
      style={{
        background: C.surface,
        border: "1px solid var(--c-surfaceAlt)",
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
          {trade.asset_type === "option" && (
            <Tag tip={trade.direction
              ? "An option contract on this ticker. Direction follows the contract (long call / short put = bullish)."
              : "An option contract on this ticker. The filing doesn't say call or put, so it doesn't count toward the signal."}>
              OPTION
            </Tag>
          )}
          {trade.asset_type === "other" && <Tag tip="Not common stock (bond, note, fund). Doesn't count toward the signal.">OTHER</Tag>}
          {ownerLabel && <Tag tip="Who holds the position, per the filing — the STOCK Act covers spouses and dependent children too.">{ownerLabel.toUpperCase()}</Tag>}
          {trade.amends && <Tag tip={`From an amended report that replaced the one filed ${trade.amends}. Only the corrected version is shown.`}>AMENDED</Tag>}
          {isPaper && <Tag tip={`Filed on paper (a scanned, often handwritten form). Read by the site's AI model${trade.ai_confidence != null ? ` with ${Math.round(trade.ai_confidence * 100)}% confidence` : ""} — the asset name was matched to a ticker and the amount comes from a ticked box. Open the filing to check.`}>PAPER · AI-READ</Tag>}
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
          {trade.filing_url && (
            <> · <a href={safeHref(trade.filing_url)} target="_blank" rel="noreferrer" style={{ color: C.textMuted }}>filing ↗</a></>
          )}
        </div>
        {isAdmin && isPaper && (
          <button onClick={remove} disabled={removing}
            style={{ marginTop: 6, background: "none", border: "1px solid var(--c-surfaceAlt)", color: C.danger, borderRadius: 5, padding: "2px 8px", fontSize: "0.7rem", cursor: "pointer" }}>
            {removing ? "Removing…" : "Remove misread row"}
          </button>
        )}
      </div>
    </div>
  );
}
