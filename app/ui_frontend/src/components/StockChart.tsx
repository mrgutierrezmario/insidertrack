import { C } from "../lib/theme";
import { useEffect, useRef, useState } from "react";
import ChartModal from "./ChartModal";

// Time can be a string ("YYYY-MM-DD") for daily bars or a number (UNIX seconds)
// for intraday — both shapes are accepted by lightweight-charts.
type ChartTime = string | number;

interface Candle {
  time: ChartTime;
  open: number;
  high: number;
  low: number;
  close: number;
}

interface RawBar {
  time?: string;
  date?: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

interface StockChartProps {
  data: RawBar[];
  height?: number;
  interactive?: boolean;
  title?: string;
}

function toChartTime(timeStr: string | undefined): ChartTime {
  if (!timeStr) return 0;
  if (/^\d{4}-\d{2}-\d{2}$/.test(timeStr)) return timeStr;
  return Math.floor(new Date(timeStr.replace(" ", "T")).getTime() / 1000);
}

function timeToMs(t: ChartTime): number {
  if (typeof t === "string") return new Date(t + "T00:00:00").getTime();
  return t * 1000;
}

function findNearest(points: Candle[] | null | undefined, targetMs: number): Candle | null {
  if (!points?.length) return null;
  let best = points[0];
  let bestDiff = Math.abs(timeToMs(points[0].time) - targetMs);
  for (const pt of points) {
    const diff = Math.abs(timeToMs(pt.time) - targetMs);
    if (diff < bestDiff) { bestDiff = diff; best = pt; }
  }
  return best;
}

function fmtPrice(v: number): string {
  return `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function renderCandleTooltip(
  tooltip: HTMLDivElement | null,
  candle: Candle | null | undefined,
  timeVal: ChartTime,
  x: number,
  y: number,
  height: number,
  cw: number,
) {
  if (!tooltip || !candle) return;

  const isUp = candle.close >= candle.open;
  const color = isUp ? C.success : C.danger;
  const change = candle.close - candle.open;
  const changePct = ((change / candle.open) * 100).toFixed(2);
  const sign = change >= 0 ? "+" : "";

  const timeStr = typeof timeVal === "string"
    ? new Date(timeVal + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
    : new Date(timeVal * 1000).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

  tooltip.innerHTML = `
    <div style="color:#64748b;font-size:11px;margin-bottom:6px">${timeStr}</div>
    <div style="color:${color};font-size:14px;font-weight:700;margin-bottom:6px">
      ${fmtPrice(candle.close)}
      <span style="font-size:11px;font-weight:500">${sign}${changePct}%</span>
    </div>
    <div style="display:grid;grid-template-columns:auto 1fr;gap:3px 12px;font-size:12px">
      <span style="color:#64748b">Open</span><span style="color:#f1f5f9">${fmtPrice(candle.open)}</span>
      <span style="color:#64748b">High</span><span style="color:#4ade80">${fmtPrice(candle.high)}</span>
      <span style="color:#64748b">Low</span><span style="color:#f87171">${fmtPrice(candle.low)}</span>
      <span style="color:#64748b">Close</span><span style="color:#f1f5f9">${fmtPrice(candle.close)}</span>
    </div>
  `;
  tooltip.style.display = "block";

  const tW = tooltip.offsetWidth || 160;
  const tH = tooltip.offsetHeight || 110;
  let left = x + 14;
  if (left + tW > cw - 8) left = x - tW - 14;
  let top = y - tH / 2;
  if (top < 4) top = 4;
  if (top + tH > height - 4) top = height - tH - 4;
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
}

/**
 * interactive: passed to modal instance — do not set manually
 * title: shown in modal header
 */
export default function StockChart({ data, height = 300, interactive = false, title = "Chart" }: StockChartProps) {
  const [expanded, setExpanded] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const tooltipRef = useRef<HTMLDivElement | null>(null);
  // The lightweight-charts API surface is dynamic; using `any` here keeps the
  // file independent of the library's TypeScript declarations (which are
  // version-coupled and noisy).
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chartRef = useRef<any>(null);
  const mappedRef = useRef<Candle[]>([]);

  useEffect(() => {
    if (!containerRef.current || !data?.length) return;

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let chart: any;
    let resizeHandler: (() => void) | undefined;
    const tooltip = tooltipRef.current;

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    import("lightweight-charts").then((lc: any) => {
      const { createChart, CrosshairMode } = lc;
      if (!containerRef.current) return;

      chart = createChart(containerRef.current, {
        height,
        layout: { background: { color: C.bg }, textColor: C.textSoft },
        grid: { vertLines: { color: C.surfaceAlt }, horzLines: { color: C.surfaceAlt } },
        timeScale: { borderColor: C.surfaceAlt, timeVisible: true, secondsVisible: false },
        rightPriceScale: { borderColor: C.surfaceAlt },
        crosshair: {
          mode: CrosshairMode?.Normal ?? 0,
          vertLine: { color: C.dividerStrong, width: 1, style: 3, labelBackgroundColor: C.surfaceAlt },
          horzLine: { color: C.dividerStrong, width: 1, style: 3, labelBackgroundColor: C.surfaceAlt },
        },
        handleScroll: false,
        handleScale: false,
      });

      chartRef.current = chart;

      const candleSeries = chart.addCandlestickSeries({
        upColor: C.success, downColor: C.danger,
        borderUpColor: C.success, borderDownColor: C.danger,
        wickUpColor: C.success, wickDownColor: C.danger,
      });

      const mapped = data.map((d) => ({
        time: toChartTime(d.time ?? d.date),
        open: d.open, high: d.high, low: d.low, close: d.close,
      }));
      candleSeries.setData(mapped);
      mappedRef.current = mapped;
      chart.timeScale().fitContent();

      // ── Desktop: built-in crosshair ───────────────────────────────
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      chart.subscribeCrosshairMove((param: any) => {
        if (!param.time || param.point === undefined || !param.seriesData?.size) {
          if (tooltip) tooltip.style.display = "none";
          return;
        }
        const candle = param.seriesData.get(candleSeries) as Candle | undefined;
        renderCandleTooltip(tooltip, candle, param.time, param.point.x, param.point.y, height, containerRef.current?.clientWidth ?? 300);
      });

      // ── Mobile: direct touch → find nearest candle ────────────────
      const onTouch = (e: TouchEvent) => {
        e.preventDefault();
        const touch = e.touches[0] || e.changedTouches[0];
        if (!touch || !containerRef.current || !chartRef.current) return;

        const rect = containerRef.current.getBoundingClientRect();
        const x = touch.clientX - rect.left;
        const y = touch.clientY - rect.top;

        const t = chartRef.current.timeScale().coordinateToTime(x) as ChartTime | null;
        if (!t) return;
        const targetMs = timeToMs(t);

        const nearest = findNearest(mappedRef.current, targetMs);
        renderCandleTooltip(tooltip, nearest, nearest?.time ?? t, x, y, height, containerRef.current.clientWidth);
      };

      const onTouchEnd = () => {
        setTimeout(() => { if (tooltip) tooltip.style.display = "none"; }, 2000);
      };

      const el = containerRef.current;
      el.addEventListener("touchstart", onTouch, { passive: false });
      el.addEventListener("touchmove", onTouch, { passive: false });
      el.addEventListener("touchend", onTouchEnd);

      resizeHandler = () => {
        if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
      };
      window.addEventListener("resize", resizeHandler);

      return () => {
        el.removeEventListener("touchstart", onTouch);
        el.removeEventListener("touchmove", onTouch);
        el.removeEventListener("touchend", onTouchEnd);
      };
    });

    return () => {
      if (resizeHandler) window.removeEventListener("resize", resizeHandler);
      if (chart) chart.remove();
      chartRef.current = null;
    };
  }, [data, height]);

  const chartEl = (
    <div style={{ position: "relative", width: "100%" }}>
      <div ref={containerRef} style={{ width: "100%", touchAction: "none" }} />
      <div
        ref={tooltipRef}
        style={{
          display: "none",
          position: "absolute",
          top: 0, left: 0,
          background: C.surfaceAlt,
          border: "1px solid #334155",
          borderRadius: "8px",
          padding: "10px 12px",
          pointerEvents: "none",
          zIndex: 10,
          minWidth: "150px",
          boxShadow: "0 4px 12px rgba(0,0,0,0.4)",
        }}
      />
    </div>
  );

  if (interactive) return chartEl;

  return (
    <>
      <div style={{ position: "relative" }}>
        {chartEl}
        <button
          onClick={() => setExpanded(true)}
          title="Expand chart"
          style={{
            position: "absolute", top: 8, right: 8,
            background: "rgba(30,37,51,0.85)",
            border: "1px solid #334155",
            borderRadius: 6, color: C.textSoft,
            width: 32, height: 32,
            cursor: "pointer",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 15, zIndex: 5,
          }}
        >
          ⤢
        </button>
      </div>

      {expanded && (
        <ChartModal title={title} onClose={() => setExpanded(false)}>
          <StockChart
            data={data}
            height={window.innerHeight - 110}
            interactive={true}
            title={title}
          />
        </ChartModal>
      )}
    </>
  );
}
