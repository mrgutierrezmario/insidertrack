import { C } from "../lib/theme";
/**
 * SVG bar chart showing buy vs sell counts grouped by month.
 * trades: array of trade objects with transaction_type and trade_date/disclosure_date
 */

interface TradeLike {
  trade_date?: string | null;
  disclosure_date?: string | null;
  transaction_type?: string | null;
}

interface ActivityChartProps {
  trades: TradeLike[];
  height?: number;
}

interface MonthCounts {
  buys: number;
  sells: number;
}

export default function ActivityChart({ trades, height = 220 }: ActivityChartProps) {
  if (!trades?.length) return null;

  // Group by month
  const monthly: Record<string, MonthCounts> = {};
  trades.forEach((t) => {
    const dateStr = t.trade_date || t.disclosure_date || "";
    const month = dateStr.substring(0, 7);
    if (!month) return;
    if (!monthly[month]) monthly[month] = { buys: 0, sells: 0 };
    const type = (t.transaction_type || "").toLowerCase();
    if (type.includes("purchase")) monthly[month].buys++;
    else if (type.includes("sale")) monthly[month].sells++;
  });

  const months = Object.keys(monthly).sort();
  if (!months.length) return null;

  const maxCount = Math.max(...months.map((m) => Math.max(monthly[m].buys, monthly[m].sells)), 1);

  const PAD_L = 32;
  const PAD_R = 12;
  const PAD_T = 12;
  const PAD_B = 36;
  const chartW = 760;
  const chartH = height - PAD_T - PAD_B;

  const colW = (chartW - PAD_L - PAD_R) / months.length;
  const barW = Math.min(colW * 0.35, 20);

  const yScale = (count: number) => chartH - (count / maxCount) * chartH;

  // Y-axis ticks
  const yTicks: number[] = [];
  for (let i = 0; i <= maxCount; i++) {
    if (maxCount <= 5 || i % Math.ceil(maxCount / 4) === 0) yTicks.push(i);
  }

  return (
    <div style={{ background: C.bg, border: "1px solid var(--c-surfaceAlt)", borderRadius: 8, padding: "1rem" }}>
      <div style={{ color: C.textSoft, fontSize: "0.75rem", marginBottom: "0.5rem", display: "flex", gap: "1rem" }}>
        <span><span style={{ color: C.success }}>■</span> Buys</span>
        <span><span style={{ color: C.danger }}>■</span> Sells</span>
      </div>
      <svg
        viewBox={`0 0 ${chartW} ${height}`}
        style={{ width: "100%", height }}
        preserveAspectRatio="none"
      >
        {/* Y-axis gridlines + labels */}
        {yTicks.map((tick) => {
          const y = PAD_T + yScale(tick);
          return (
            <g key={tick}>
              <line x1={PAD_L} x2={chartW - PAD_R} y1={y} y2={y} stroke={C.surfaceAlt} strokeWidth={1} />
              <text x={PAD_L - 4} y={y + 4} fill={C.textDim} fontSize={10} textAnchor="end">{tick}</text>
            </g>
          );
        })}

        {/* Bars */}
        {months.map((month, i) => {
          const cx = PAD_L + i * colW + colW / 2;
          const { buys, sells } = monthly[month];
          const buyH = (buys / maxCount) * chartH;
          const sellH = (sells / maxCount) * chartH;
          const labelMonth = month.substring(5); // MM

          return (
            <g key={month}>
              {/* Buy bar */}
              {buys > 0 && (
                <rect
                  x={cx - barW - 1}
                  y={PAD_T + yScale(buys)}
                  width={barW}
                  height={buyH}
                  fill={C.success}
                  opacity={0.85}
                  rx={2}
                />
              )}
              {/* Sell bar */}
              {sells > 0 && (
                <rect
                  x={cx + 1}
                  y={PAD_T + yScale(sells)}
                  width={barW}
                  height={sellH}
                  fill={C.danger}
                  opacity={0.85}
                  rx={2}
                />
              )}
              {/* Month label */}
              <text
                x={cx}
                y={height - 4}
                fill={C.textMuted}
                fontSize={9}
                textAnchor="middle"
              >
                {labelMonth}/{month.substring(2, 4)}
              </text>
            </g>
          );
        })}

        {/* Baseline */}
        <line x1={PAD_L} x2={chartW - PAD_R} y1={PAD_T + chartH} y2={PAD_T + chartH} stroke={C.surfaceAlt} strokeWidth={1} />
      </svg>
    </div>
  );
}
