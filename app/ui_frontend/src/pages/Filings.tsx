import { safeHref } from "../lib/safeUrl";
import { fmtDate } from "../lib/format";
import { C } from "../lib/theme";
import useDocumentTitle from "../hooks/useDocumentTitle";
import { useEffect, useState } from "react";
import { getRecentFilings, getWhalePositions, getWhales } from "../lib/api";
import type { WhaleHolder } from "../types/api";

interface Filing {
  accession_number?: string;
  form: string;
  period: string;
  filing_date: string;
  index_url: string;
}

interface Institution {
  institution: string;
  sic_description?: string | null;
  filings?: Filing[];
  error?: string | null;
}

interface Position {
  ticker: string;
  value_fmt: string;
  quarter: string;
}

interface Positions {
  positions?: Position[];
}


function fmtPeriod(d: string | null | undefined): string {
  if (!d) return "—";
  const dt = new Date(d + "T00:00:00");
  const q = Math.ceil((dt.getMonth() + 1) / 3);
  return `Q${q} ${dt.getFullYear()}`;
}

const FORM_COLOR: Record<string, string> = { "13F-HR": C.accent, "13F-HR/A": C.info };

function FilingRow({ f }: { f: Filing }) {
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", alignItems: "center",
      padding: "10px 0",
      borderBottom: "1px solid var(--c-surfaceAlt)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span style={{
          background: "rgba(56,189,248,0.1)",
          color: FORM_COLOR[f.form] || C.accent,
          border: `1px solid rgba(56,189,248,0.2)`,
          borderRadius: 5, padding: "2px 8px", fontSize: 11, fontWeight: 600,
          whiteSpace: "nowrap",
        }}>
          {f.form}
        </span>
        <div>
          <div style={{ color: C.textBright, fontSize: 13 }}>
            Period: <strong>{fmtPeriod(f.period)}</strong>
          </div>
          <div style={{ color: C.textDim, fontSize: 11 }}>Filed {fmtDate(f.filing_date)}</div>
        </div>
      </div>
      <a
        href={safeHref(f.index_url)}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          color: C.accent, fontSize: 12, textDecoration: "none",
          border: "1px solid rgba(56,189,248,0.25)",
          borderRadius: 6, padding: "4px 10px",
          whiteSpace: "nowrap",
        }}
      >
        View on SEC →
      </a>
    </div>
  );
}

function HoldingsPanel({ holderId }: { holderId: number | null }) {
  const [positions, setPositions] = useState<Positions | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!holderId) return;
    setLoading(true);
    getWhalePositions(holderId)
      .then((r) => setPositions(r.data as Positions))
      .catch(() => setPositions(null))
      .finally(() => setLoading(false));
  }, [holderId]);

  if (!holderId) return null;

  const items = positions?.positions ?? [];
  return (
    <div style={{ borderTop: "1px solid var(--c-surfaceAlt)", padding: "12px 20px 16px" }}>
      {loading && <p style={{ color: C.textDim, fontSize: 12 }}>Loading holdings…</p>}
      {!loading && positions && items.length === 0 && (
        <p style={{ color: C.textDim, fontSize: 12 }}>No position data yet — click "↻ Sync 13F Holdings" on the Whales page to parse holdings.</p>
      )}
      {!loading && items.length > 0 && (
        <>
          <div style={{ color: C.textMuted, fontSize: 11, marginBottom: 8 }}>
            {items.length} positions · {items[0]?.quarter}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 6 }}>
            {items.slice(0, 20).map((p) => (
              <div key={p.ticker} style={{ background: C.bg, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, padding: "6px 10px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ color: C.accent, fontWeight: 700, fontSize: 13 }}>{p.ticker}</span>
                <span style={{ color: C.textSoft, fontSize: 12 }}>{p.value_fmt}</span>
              </div>
            ))}
          </div>
          {items.length > 20 && (
            <p style={{ color: C.textDim, fontSize: 11, marginTop: 6 }}>+{items.length - 20} more positions</p>
          )}
        </>
      )}
    </div>
  );
}

function InstitutionCard({ inst, whaleHolder }: { inst: Institution; whaleHolder: WhaleHolder | null }) {
  const [open, setOpen] = useState(false);
  const filings = inst.filings ?? [];
  const hasFilings = filings.length > 0;
  const latest = filings[0];

  return (
    <div style={{
      background: C.surface,
      border: "1px solid var(--c-surfaceAlt)",
      borderRadius: 12,
      overflowX: "auto", WebkitOverflowScrolling: "touch",
    }}>
      {/* Header */}
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          width: "100%", background: "none", border: "none", cursor: "pointer",
          padding: "16px 20px",
          display: "flex", justifyContent: "space-between", alignItems: "center",
          textAlign: "left",
        }}
      >
        <div>
          <div style={{ color: C.textBright, fontWeight: 600, fontSize: 15 }}>{inst.institution}</div>
          {inst.sic_description && (
            <div style={{ color: C.textDim, fontSize: 11, marginTop: 2 }}>{inst.sic_description}</div>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {latest && (
            <div style={{ textAlign: "right" }}>
              <div style={{ color: C.textMuted, fontSize: 11 }}>Latest 13F</div>
              <div style={{ color: C.textSoft, fontSize: 12 }}>{fmtPeriod(latest.period)}</div>
            </div>
          )}
          {hasFilings ? (
            <span style={{ color: C.accent, fontSize: 16 }}>{open ? "▲" : "▼"}</span>
          ) : (
            <span style={{ color: C.textDim, fontSize: 12 }}>No filings found</span>
          )}
        </div>
      </button>

      {/* Filing rows */}
      {open && hasFilings && (
        <div style={{ padding: "0 20px 16px" }}>
          {filings.map((f, i) => <FilingRow key={f.accession_number || f.filing_date + String(i)} f={f} />)}
        </div>
      )}

      {open && whaleHolder && <HoldingsPanel holderId={whaleHolder.id} />}

      {inst.error && (
        <div style={{ padding: "0 20px 14px", color: C.textDim, fontSize: 12 }}>
          ⚠ {inst.error}
        </div>
      )}
    </div>
  );
}

export default function Filings() {
  useDocumentTitle("SEC Filings");
  const [data, setData] = useState<Institution[]>([]);
  const [whales, setWhales] = useState<WhaleHolder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getWhales().then((r) => setWhales(r.data as WhaleHolder[])).catch(() => {});
    getRecentFilings(3)
      .then((r) => setData(r.data as Institution[]))
      .catch(() => setError("Could not load filings from SEC EDGAR."))
      .finally(() => setLoading(false));
  }, []);

  const matchWhale = (instName: string): WhaleHolder | null => {
    const lower = instName.toLowerCase();
    return whales.find((w) => {
      const wname = w.name.toLowerCase();
      return wname.includes(lower.split(" ")[0]) || lower.includes(wname.split(" ")[0]);
    }) || null;
  };

  return (
    <div style={{ maxWidth: 900, margin: "0 auto" }}>
      <div className="page-head">
        <div>
          <h1>SEC Filings</h1>
          <p style={{ color: C.textDim, margin: 0, fontSize: 13 }}>
            SEC 13F-HR filings — required quarterly from funds managing &gt;$100M in US equities.
            Data pulled live from{" "}
            <a href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=13F-HR" target="_blank" rel="noopener noreferrer" style={{ color: C.accent }}>
              SEC EDGAR
            </a>.
          </p>
        </div>
        <span style={{
          background: "rgba(74,222,128,0.08)", color: C.success,
          border: "1px solid rgba(74,222,128,0.2)",
          borderRadius: 6, padding: "4px 10px", fontSize: 11, whiteSpace: "nowrap",
        }}>
          Live SEC Data
        </span>
      </div>

      {loading && (
        <div style={{ color: C.textDim, textAlign: "center", padding: "60px 0" }}>
          Fetching from SEC EDGAR…
        </div>
      )}

      {error && (
        <div style={{ color: C.danger, textAlign: "center", padding: "40px 0" }}>{error}</div>
      )}

      {!loading && !error && (
        <>
          <div style={{ color: C.textDim, fontSize: 12, marginBottom: 16 }}>
            Tracking {data.length} major institutions · Click any row to expand recent filings
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {data.map((inst, i) => (
              <InstitutionCard key={inst.institution} inst={inst} whaleHolder={matchWhale(inst.institution)} />
            ))}
          </div>

          <div style={{ marginTop: 24, padding: "14px 16px", background: C.bg, borderRadius: 8, border: "1px solid var(--c-surfaceAlt)", fontSize: 12, color: C.textDim, lineHeight: 1.6 }}>
            <strong style={{ color: C.textMuted }}>About 13F filings:</strong> The SEC requires institutional investment managers with ≥$100M in US equity assets to file Form 13F within 45 days of each quarter end. Filings disclose long equity positions — they do not include short positions, options strategies, or non-US holdings. Each filing reflects holdings as of the quarter end date, not the current date.
          </div>
        </>
      )}
    </div>
  );
}
