import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { exportCSV } from "./csv";

// jsdom's Blob does not implement .text(), so we intercept the Blob constructor
// and stash the string parts. Tests assert on `lastBlobText` directly.
let lastBlobText = "";
let lastBlobType = "";
const RealBlob = global.Blob;
class CapturingBlob {
  constructor(parts, opts) {
    lastBlobText = (parts || []).join("");
    lastBlobType = opts?.type || "";
  }
}

describe("exportCSV", () => {
  let anchorClicks, downloadName;

  beforeEach(() => {
    lastBlobText = ""; lastBlobType = ""; anchorClicks = 0; downloadName = "";
    global.Blob = CapturingBlob;
    global.URL.createObjectURL = vi.fn(() => "blob:mock-url");
    global.URL.revokeObjectURL = vi.fn();
    HTMLAnchorElement.prototype.click = function () {
      anchorClicks++;
      downloadName = this.download;
    };
  });

  afterEach(() => {
    global.Blob = RealBlob;
    vi.restoreAllMocks();
  });

  it("creates a CSV Blob, triggers download, and revokes the URL", () => {
    exportCSV(["a", "b"], [["1", "2"], ["3", "4"]], "demo");
    expect(lastBlobType).toBe("text/csv");
    expect(anchorClicks).toBe(1);
    expect(global.URL.revokeObjectURL).toHaveBeenCalledWith("blob:mock-url");
    expect(lastBlobText.split("\n")[0]).toBe("a,b");
  });

  it("quotes values and escapes embedded double-quotes", () => {
    exportCSV(["x"], [['hello "world"'], ["plain"]], "q");
    expect(lastBlobText).toContain('"hello ""world"""');
    expect(lastBlobText).toContain('"plain"');
    expect(lastBlobText.split("\n")[0]).toBe("x");
  });

  it("treats null and undefined as empty strings", () => {
    exportCSV(["c"], [[null], [undefined]], "n");
    const rows = lastBlobText.split("\n");
    expect(rows[1]).toBe('""');
    expect(rows[2]).toBe('""');
  });

  it("uses today's ISO date in the filename", () => {
    exportCSV(["a"], [["1"]], "report");
    const today = new Date().toISOString().slice(0, 10);
    expect(downloadName).toBe(`report-${today}.csv`);
  });
});
