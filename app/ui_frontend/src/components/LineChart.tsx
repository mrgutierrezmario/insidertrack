import { C, resolvedPalette, resolveCss } from "../lib/theme";
import { useResolvedTheme } from "../hooks/useTheme";
import { useEffect, useRef, useState } from "react";
import ChartModal from "./ChartModal";

type ChartTime = string | number;

interface DataPoint {
  date: string;
  value: number;
}

interface SeriesInput {
  label: string;
  data: DataPoint[];
}

interface MappedPoint {
  time: ChartTime;
  value: number;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type SeriesApi = any;

interface BuiltSeries {
  label: string;
  color: string;
  seriesApi: SeriesApi;
  mappedData: MappedPoint[];
}

interface LineChartProps {
  series: SeriesInput[];
  height?: number;
  normalized?: boolean;
  interactive?: boolean;
  title?: string;
}

const PALETTE = [
  C.accent, C.success, C.warning, C.info,
  "#f472b6", "#facc15", "#34d399", C.danger,
  "#60a5fa", "#e879f9",
];

function timeToMs(t: ChartTime): number {
  if (typeof t === "string") return new Date(t + "T00:00:00").getTime();
  return t * 1000;
}

function findNearest<T extends { time: ChartTime }>(points: T[] | null | undefined, targetMs: number): T | null {
  if (!points?.length) return null;
  let best = points[0];
  let bestDiff = Math.abs(timeToMs(points[0].time) - targetMs);
  for (const pt of points) {
    const diff = Math.abs(timeToMs(pt.time) - targetMs);
    if (diff < bestDiff) { bestDiff = diff; best = pt; }
  }
  return best;
}

function formatVal(val: number | null, normalized: boolean): string {
  if (val == null) return "—";
  if (normalized) return `${val >= 0 ? "+" : ""}${val.toFixed(2)}%`;
  return `$${val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

// Escape strings before injecting into innerHTML. `label` flows from a series
// prop whose source ultimately includes ticker symbols pulled from the DB —
// if a malicious ticker ever entered through a non-validated path (whale 13F
// XML, OGE feeds) it would execute without this guard.
function htmlEscape(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderTooltip(
  tooltip: HTMLDivElement | null,
  builtSeries: BuiltSeries[],
  dateStr: string,
  getVal: (label: string) => number | null,
  normalized: boolean,
  x: number,
  y: number,
  height: number,
  cw: number,
) {
  if (!tooltip) return;
  const lines = builtSeries.map(({ label, color }) => {
    const val = getVal(label);
    return `<div style="display:flex;align-items:center;gap:6px">
      <span style="width:8px;height:8px;border-radius:50%;background:${color};flex-shrink:0"></span>
      <span style="color:var(--c-textSoft);font-size:11px;flex:1">${htmlEscape(label)}</span>
      <span style="color:var(--c-textBright);font-size:12px;font-weight:600">${formatVal(val, normalized)}</span>
    </div>`;
  }).join("");

  tooltip.innerHTML = `<div style="color:var(--c-textMuted);font-size:11px;margin-bottom:6px">${htmlEscape(dateStr)}</div>${lines}`;
  tooltip.style.display = "block";

  const tW = tooltip.offsetWidth || 180;
  const tH = tooltip.offsetHeight || 80;
  let left = x + 14;
  if (left + tW > cw - 8) left = x - tW - 14;
  let top = y - tH / 2;
  if (top < 4) top = 4;
  if (top + tH > height - 4) top = height - tH - 4;
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
}

/**
 * series: [{ label: string, data: [{ date: "YYYY-MM-DD", value: number }] }]
 * normalized: if true, each series is shown as % change from first point
 * interactive: passed to modal instance — do not set manually
 * title: shown in modal header
 */
export default function LineChart({ series, height = 300, normalized = false, interactive = false, title = "Chart" }: LineChartProps) {
  const theme = useResolvedTheme();
  const [expanded, setExpanded] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const tooltipRef = useRef<HTMLDivElement | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chartRef = useRef<any>(null);

  useEffect(() => {
    const R = resolvedPalette();
    if (!containerRef.current || !series?.length) return;

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
        layout: { background: { color: R.bg }, textColor: R.textSoft },
        grid: { vertLines: { color: R.surfaceAlt }, horzLines: { color: R.surfaceAlt } },
        timeScale: { borderColor: R.surfaceAlt, timeVisible: false },
        rightPriceScale: { borderColor: R.surfaceAlt },
        crosshair: {
          mode: CrosshairMode?.Normal ?? 0,
          vertLine: { color: R.divider, width: 1, style: 3, labelBackgroundColor: R.surfaceAlt },
          horzLine: { color: R.divider, width: 1, style: 3, labelBackgroundColor: R.surfaceAlt },
        },
        handleScroll: false,
        handleScale: false,
      });

      chartRef.current = chart;
      const builtSeries: BuiltSeries[] = [];

      series.forEach(({ label, data }, i) => {
        if (!data?.length) return;
        const base = normalized ? data[0].value : null;
        const color = resolveCss(PALETTE[i % PALETTE.length]);

        const seriesApi = chart.addLineSeries({
          color,
          lineWidth: 2,
          title: label,
          priceFormat: normalized
            ? { type: "price", precision: 2, minMove: 0.01 }
            : { type: "price" },
          lastValueVisible: true,
          priceLineVisible: false,
        });

        const mappedData = data.map((d) => ({
          time: d.date,
          value: normalized && base != null
            ? parseFloat((((d.value - base) / base) * 100).toFixed(2))
            : d.value,
        }));

        seriesApi.setData(mappedData);
        builtSeries.push({ label, color, seriesApi, mappedData });
      });

      chart.timeScale().fitContent();

      // ── Desktop: use built-in crosshair move ──────────────────────
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      chart.subscribeCrosshairMove((param: any) => {
        if (!param.time || param.point === undefined || !param.seriesData?.size) {
          if (tooltip) tooltip.style.display = "none";
          return;
        }
        const dateStr = new Date(param.time + "T00:00:00").toLocaleDateString("en-US", {
          month: "short", day: "numeric", year: "numeric",
        });
        renderTooltip(
          tooltip, builtSeries, dateStr,
          (label) => {
            const s = builtSeries.find((b) => b.label === label);
            return s ? (param.seriesData.get(s.seriesApi) as { value?: number } | undefined)?.value ?? null : null;
          },
          normalized,
          param.point.x, param.point.y, height, containerRef.current?.clientWidth ?? 300
        );
      });

      // ── Mobile: direct touch → find nearest data point ────────────
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

        const firstNearest = findNearest(builtSeries[0]?.mappedData, targetMs);
        const dateStr = firstNearest
          ? new Date(timeToMs(firstNearest.time)).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
          : "";

        renderTooltip(
          tooltip, builtSeries, dateStr,
          (label) => {
            const s = builtSeries.find((b) => b.label === label);
            return s ? findNearest(s.mappedData, targetMs)?.value ?? null : null;
          },
          normalized, x, y, height, containerRef.current.clientWidth
        );
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
  }, [series, height, normalized, theme]);

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
          border: "1px solid var(--c-divider)",
          borderRadius: "8px",
          padding: "10px 12px",
          pointerEvents: "none",
          zIndex: 10,
          minWidth: "160px",
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
            border: "1px solid var(--c-divider)",
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
          <LineChart
            series={series}
            height={window.innerHeight - 110}
            normalized={normalized}
            interactive={true}
            title={title}
          />
        </ChartModal>
      )}
    </>
  );
}
