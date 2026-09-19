import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getPolitician, getPoliticianTrades, toggleTrack, getTechnicalSignals } from "../lib/api";
import { LABEL_COLORS , C} from "../lib/theme";
import useDocumentTitle from "../hooks/useDocumentTitle";
import useAdmin from "../hooks/useAdmin";
import TradeCard from "../components/TradeCard";
import ActivityChart from "../components/ActivityChart";
import WatchlistButton from "../components/WatchlistButton";
import TrackRecord from "../components/TrackRecord";
import SkeletonCard from "../components/SkeletonCard";
import type { SignalLabel, Trade } from "../types/api";

const PARTY_COLOR: Record<string, string> = { D: "#3b82f6", R: C.dangerSolid, I: C.info };

interface SignalRow {
  ticker: string;
  label: SignalLabel;
  composite_score: number;
}

interface PoliticianDetail {
  id: number;
  name: string;
  party: string | null;
  chamber: string | null;
  state: string | null;
  is_tracked: boolean;
  description: string | null;
  why_tracked: string | null;
}

function SignalPill({ ticker, signals }: { ticker: string; signals: SignalRow[] }) {
  const s = signals.find((x) => x.ticker === ticker);
  if (!s) return null;
  const color = LABEL_COLORS[s.label] || C.textSoft;
  return (
    <span style={{ color, fontSize: 11, fontWeight: 600, border: `1px solid ${color}44`, borderRadius: 4, padding: "1px 6px", marginLeft: 6 }}>
      {s.label} · {s.composite_score}
    </span>
  );
}

export default function Politician() {
  const { id } = useParams<{ id: string }>();
  const [politician, setPolitician] = useState<PoliticianDetail | null>(null);
  useDocumentTitle(politician?.name ?? "Politician");
  const isAdmin = useAdmin();
  const [trades, setTrades] = useState<Trade[]>([]);
  const [signals, setSignals] = useState<SignalRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    const pid = Number(id);
    Promise.all([
      getPolitician(pid),
      getPoliticianTrades(pid),
      getTechnicalSignals().catch(() => ({ data: [] as SignalRow[] })),
    ]).then(([polRes, tradesRes, sigRes]) => {
      setPolitician(polRes.data as PoliticianDetail);
      setTrades(tradesRes.data as Trade[]);
      const sigData = sigRes.data as { signals?: SignalRow[] } | SignalRow[];
      setSignals(
        Array.isArray(sigData) ? sigData : (sigData?.signals ?? []),
      );
    }).finally(() => setLoading(false));
  }, [id]);

  const handleTrack = async () => {
    if (!politician || !id) return;
    await toggleTrack(Number(id), !politician.is_tracked);
    setPolitician((p) => (p ? { ...p, is_tracked: !p.is_tracked } : p));
  };

  if (loading) {
    return (
      <div style={{ maxWidth: 900, margin: "0 auto" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <SkeletonCard lines={2} height={80} />
          <SkeletonCard lines={1} height={48} />
          <SkeletonCard lines={3} height={120} />
        </div>
      </div>
    );
  }

  if (!politician) return <p style={{ color: C.textMuted }}>Politician not found.</p>;

  const buys = trades.filter((t) => t.direction === "buy").length;
  const sells = trades.filter((t) => t.direction === "sell").length;
  const partyColor = (politician.party && PARTY_COLOR[politician.party]) || C.textSoft;

  // Unique tickers this politician traded
  const tickers = [
    ...new Set(trades.map((t) => t.ticker).filter((t): t is string => Boolean(t))),
  ].sort();

  return (
    <div style={{ maxWidth: 900, margin: "0 auto" }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1.5rem", flexWrap: "wrap", gap: 12 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 6 }}>
            <h1 style={{ fontSize: "1.5rem", fontWeight: 700, margin: 0 }}>{politician.name}</h1>
            {politician.party && (
              <span style={{ color: partyColor, fontWeight: 700, fontSize: 13, border: `1px solid ${partyColor}44`, borderRadius: 5, padding: "2px 8px" }}>
                {politician.party}
              </span>
            )}
          </div>
          <p style={{ color: C.textMuted, margin: 0, fontSize: 14 }}>
            {[politician.chamber, politician.state].filter(Boolean).join(" · ")}
          </p>
        </div>
        {isAdmin ? (
          <button
            onClick={handleTrack}
            style={{
              background: politician.is_tracked ? "#7c3aed" : C.surfaceAlt,
              color: C.text, border: "none",
              padding: "0.5rem 1.25rem", borderRadius: 6, cursor: "pointer", fontWeight: 600,
            }}
          >
            {politician.is_tracked ? "✓ Tracking" : "Track"}
          </button>
        ) : politician.is_tracked ? (
          <span style={{ background: "rgba(124,58,237,0.15)", color: C.info, padding: "0.4rem 0.9rem", borderRadius: 6, fontSize: "0.8rem", fontWeight: 600 }}>Tracked</span>
        ) : null}
      </div>

      {/* Bio / description */}
      {politician.description && (
        <div style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 10, padding: "14px 18px", marginBottom: "1.5rem" }}>
          <p style={{ color: C.textSoft, fontSize: 13, margin: 0, lineHeight: 1.7 }}>{politician.description}</p>
          {politician.why_tracked && (
            <p style={{ color: C.dividerStrong, fontSize: 12, margin: "10px 0 0", fontStyle: "italic" }}>
              Why tracked: {politician.why_tracked}
            </p>
          )}
        </div>
      )}

      {/* Summary stats */}
      {trades.length > 0 && (
        <div style={{ display: "flex", gap: "1rem", marginBottom: "1.5rem", flexWrap: "wrap" }}>
          <div style={{ background: C.successBg, border: "1px solid var(--c-successDeep)", borderRadius: 8, padding: "0.75rem 1.25rem" }}>
            <div style={{ color: C.success, fontSize: "1.25rem", fontWeight: 700 }}>{buys}</div>
            <div style={{ color: C.textMuted, fontSize: "0.75rem" }}>Purchases</div>
          </div>
          <div style={{ background: C.dangerBg, border: "1px solid var(--c-dangerDeep)", borderRadius: 8, padding: "0.75rem 1.25rem" }}>
            <div style={{ color: C.danger, fontSize: "1.25rem", fontWeight: 700 }}>{sells}</div>
            <div style={{ color: C.textMuted, fontSize: "0.75rem" }}>Sales</div>
          </div>
          <div style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8, padding: "0.75rem 1.25rem" }}>
            <div style={{ color: C.text, fontSize: "1.25rem", fontWeight: 700 }}>{trades.length}</div>
            <div style={{ color: C.textMuted, fontSize: "0.75rem" }}>Total Trades</div>
          </div>
          <div style={{ background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8, padding: "0.75rem 1.25rem" }}>
            <div style={{ color: C.accent, fontSize: "1.25rem", fontWeight: 700 }}>{tickers.length}</div>
            <div style={{ color: C.textMuted, fontSize: "0.75rem" }}>Tickers</div>
          </div>
        </div>
      )}

      {politician && <TrackRecord politicianId={politician.id} />}

      {/* Tickers traded with signal scores */}
      {tickers.length > 0 && (
        <div style={{ marginBottom: "1.5rem" }}>
          <h2 style={{ fontSize: "0.9rem", fontWeight: 600, color: C.textMuted, marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Tickers Traded
          </h2>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {tickers.map((t) => (
              <div key={t} style={{ display: "flex", alignItems: "center", background: C.surface, border: "1px solid var(--c-surfaceAlt)", borderRadius: 7, padding: "5px 10px", gap: 6 }}>
                <Link to={`/ticker/${t}`} style={{ color: C.accent, fontWeight: 700, textDecoration: "none", fontSize: 13 }}>{t}</Link>
                <WatchlistButton ticker={t} />
                <SignalPill ticker={t} signals={signals} />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Activity chart */}
      {trades.length > 0 && (
        <div style={{ marginBottom: "2rem" }}>
          <h2 style={{ fontSize: "0.9rem", fontWeight: 600, color: C.textMuted, marginBottom: "0.75rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Trade Activity by Month
          </h2>
          <ActivityChart trades={trades} height={220} />
        </div>
      )}

      <h2 style={{ fontSize: "0.9rem", fontWeight: 600, color: C.textMuted, marginBottom: "1rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>
        Trade History ({trades.length})
      </h2>
      <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
        {trades.map((t) => (
          <TradeCard key={t.id} trade={{ ...t, politician: t.politician } as Trade} />
        ))}
      </div>
    </div>
  );
}
