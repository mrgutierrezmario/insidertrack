import { C } from "../lib/theme";
import { useState } from "react";
import type { FormEvent } from "react";
import { projectInvestment, getSimulatorGrowth } from "../lib/api";
import LineChart from "../components/LineChart";

interface ProjectionResult {
  ticker: string;
  triggered_by: string;
  entry_date: string;
  entry_price: number;
  current_price: number;
  shares: number;
  investment: number;
  current_value: number;
  pct_return: number;
  profit: number;
}

interface GrowthPoint {
  date: string;
  value: number;
}

interface GrowthSeries {
  points?: GrowthPoint[];
  spy_points?: GrowthPoint[];
  entry_date?: string;
  triggered_by?: string;
}

export default function Simulator() {
  const [ticker, setTicker] = useState("");
  const [amount, setAmount] = useState(100);
  const [result, setResult] = useState<ProjectionResult | null>(null);
  const [growth, setGrowth] = useState<GrowthSeries | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError("");
    setResult(null);
    setGrowth(null);
    setLoading(true);
    try {
      const sym = ticker.trim().toUpperCase();
      const [projRes, growthRes] = await Promise.allSettled([
        projectInvestment(sym, amount),
        getSimulatorGrowth(sym, amount),
      ]);
      if (projRes.status === "fulfilled") {
        setResult(projRes.value.data as ProjectionResult);
      } else {
        const reason = projRes.reason as { response?: { data?: { detail?: string } } } | undefined;
        setError(reason?.response?.data?.detail || "Something went wrong");
      }
      if (growthRes.status === "fulfilled") {
        setGrowth(growthRes.value.data as GrowthSeries);
      }
    } finally {
      setLoading(false);
    }
  };

  const isProfit = result && result.profit >= 0;

  const growthSeries = growth?.points?.length
    ? [
        { label: `$${amount} in ${ticker.toUpperCase()}`, data: growth.points },
        ...(growth.spy_points?.length
          ? [{ label: `$${amount} in SPY (benchmark)`, data: growth.spy_points }]
          : []),
      ]
    : null;

  return (
    <div style={{ maxWidth: 680 }}>
      <h1 style={{ fontSize: "1.5rem", fontWeight: 700, marginBottom: "0.5rem" }}>Investment Simulator</h1>
      <p style={{ color: C.textMuted, marginBottom: "1.5rem", fontSize: "0.9rem" }}>
        See what $X would be worth if you'd invested when a tracked insider disclosed their purchase.
      </p>

      <form onSubmit={handleSubmit} style={{ display: "flex", gap: "0.75rem", marginBottom: "2rem", flexWrap: "wrap" }}>
        <input
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          placeholder="Ticker (e.g. NVDA)"
          required
          style={{
            background: C.surface, color: C.text,
            border: "1px solid #1e2533", borderRadius: 6,
            padding: "0.5rem 1rem", fontSize: "0.9rem", width: 160,
          }}
        />
        <input
          type="number"
          value={amount}
          onChange={(e) => setAmount(Number(e.target.value))}
          min={1}
          placeholder="Amount ($)"
          style={{
            background: C.surface, color: C.text,
            border: "1px solid #1e2533", borderRadius: 6,
            padding: "0.5rem 1rem", fontSize: "0.9rem", width: 140,
          }}
        />
        <button
          type="submit"
          disabled={loading}
          style={{
            background: C.accentSolid, color: "#fff", border: "none",
            padding: "0.5rem 1.5rem", borderRadius: 6, cursor: "pointer",
            opacity: loading ? 0.6 : 1,
          }}
        >
          {loading ? "Calculating..." : "Project"}
        </button>
      </form>

      {error && <p style={{ color: C.danger, marginBottom: "1rem" }}>{error}</p>}

      {result && (
        <div style={{ background: C.surface, border: "1px solid #1e2533", borderRadius: 10, padding: "1.5rem", marginBottom: "1.5rem" }}>
          <div style={{ fontSize: "1rem", color: C.textSoft, marginBottom: "1rem" }}>
            Simulating <strong style={{ color: C.accent }}>{result.ticker}</strong> based on{" "}
            <strong style={{ color: C.text }}>{result.triggered_by}</strong>'s disclosure
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginBottom: "1.5rem" }}>
            {[
              ["Entry date", result.entry_date],
              ["Entry price", `$${result.entry_price}`],
              ["Current price", `$${result.current_price}`],
              ["Shares bought", result.shares],
            ].map(([label, value]) => (
              <div key={label}>
                <div style={{ color: C.textDim, fontSize: "0.75rem", marginBottom: 2 }}>{label}</div>
                <div style={{ color: C.text, fontWeight: 600 }}>{value}</div>
              </div>
            ))}
          </div>

          <div style={{
            borderTop: "1px solid #1e2533", paddingTop: "1rem",
            display: "flex", justifyContent: "space-between", alignItems: "center",
          }}>
            <div>
              <div style={{ color: C.textDim, fontSize: "0.75rem" }}>Current value</div>
              <div style={{ color: C.text, fontSize: "1.4rem", fontWeight: 700 }}>
                ${result.current_value}
              </div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div style={{ color: C.textDim, fontSize: "0.75rem" }}>Return on ${result.investment}</div>
              <div style={{ color: isProfit ? C.success : C.danger, fontSize: "1.4rem", fontWeight: 700 }}>
                {isProfit ? "+" : ""}{result.pct_return}%
              </div>
              <div style={{ color: isProfit ? C.success : C.danger, fontSize: "0.9rem" }}>
                ({isProfit ? "+" : ""}${result.profit})
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Growth chart */}
      {growthSeries && growth && (
        <div>
          <h2 style={{ fontSize: "1rem", fontWeight: 600, color: C.textSoft, marginBottom: "0.75rem" }}>
            Portfolio Growth Since Entry
          </h2>
          <div style={{ background: C.bg, border: "1px solid #1e2533", borderRadius: 8 }}>
            <LineChart series={growthSeries} height={280} normalized={false} title="Portfolio Growth Since Entry" />
          </div>
          {growth.triggered_by && (() => {
            const myReturn = growth.points?.at(-1)?.value ?? 0;
            const spyReturn = growth.spy_points?.at(-1)?.value ?? 0;
            const outperform = myReturn - spyReturn;
            return (
              <p style={{ color: C.textDim, fontSize: "0.75rem", marginTop: "0.5rem" }}>
                Entry: {growth.entry_date} · Triggered by {growth.triggered_by}
                {(growth.spy_points?.length ?? 0) > 0 && (
                  <span style={{ marginLeft: 10, color: outperform >= 0 ? C.success : C.danger, fontWeight: 600 }}>
                    {outperform >= 0 ? "+" : ""}${outperform.toFixed(2)} vs SPY
                  </span>
                )}
              </p>
            );
          })()}
        </div>
      )}
    </div>
  );
}
