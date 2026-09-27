import { describe, it, expect, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";

// The Dashboard's 30-day chart went blank after lightweight-charts moved to v5,
// which removed addLineSeries(). Pin the v5 call shape: addSeries(LineSeries, …).
const setData = vi.fn();
const addSeries = vi.fn((..._args: unknown[]) => ({ setData }));
const fakeChart = {
  addSeries,
  timeScale: () => ({ fitContent: vi.fn() }),
  subscribeCrosshairMove: vi.fn(),
  applyOptions: vi.fn(),
  remove: vi.fn(),
};
vi.mock("lightweight-charts", () => ({
  createChart: vi.fn(() => fakeChart),
  CrosshairMode: { Normal: 0 },
  LineSeries: "LineSeries",
}));

import LineChart from "./LineChart";

describe("<LineChart />", () => {
  it("draws each series with the v5 addSeries(LineSeries, …) API", async () => {
    render(
      <LineChart
        normalized
        series={[
          { label: "AAA", data: [{ date: "2026-09-01", value: 100 }, { date: "2026-09-02", value: 110 }] },
          { label: "BBB", data: [{ date: "2026-09-02", value: 50 }] },
        ]}
      />,
    );
    await waitFor(() => expect(addSeries).toHaveBeenCalledTimes(2));
    expect(addSeries.mock.calls[0][0]).toBe("LineSeries");
    // normalized: % change from each series' first point
    expect(setData).toHaveBeenCalledWith([
      { time: "2026-09-01", value: 0 },
      { time: "2026-09-02", value: 10 },
    ]);
  });
});
