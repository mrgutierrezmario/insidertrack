import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import {
  getAlertTypes, getAlertRules, createAlertRule, updateAlertRule, deleteAlertRule,
  getAlertEvents, markAlertsSeen, runAlerts,
} from "../lib/api";
import { card as themeCard , C} from "../lib/theme";
import useDocumentTitle from "../hooks/useDocumentTitle";
import useAdmin from "../hooks/useAdmin";

interface TypeMeta {
  label: string;
  thresholdLabel: string | null;
  thresholdDefault: number | null;
  color: string;
}

const TYPE_META: Record<string, TypeMeta> = {
  high_signal:   { label: "High signal score", thresholdLabel: "Min composite score", thresholdDefault: 70, color: C.success },
  momentum:      { label: "Bullish momentum",   thresholdLabel: null,                  thresholdDefault: null, color: C.accent },
  insider_buy:   { label: "Politician buy",     thresholdLabel: "Look-back days",       thresholdDefault: 7,  color: C.info },
  whale_new:     { label: "New whale position", thresholdLabel: null,                  thresholdDefault: null, color: C.warningSolid },
  earnings_soon: { label: "Earnings soon",      thresholdLabel: "Within N days",        thresholdDefault: 7,  color: C.warning },
  cluster_buy:   { label: "Insider cluster buy", thresholdLabel: "Min insiders buying",  thresholdDefault: 2,  color: C.success },
  skilled_buy:   { label: "Skilled member buy",  thresholdLabel: "Min beat-SPY %",       thresholdDefault: 60, color: C.info },
  ai_call:       { label: "AI Desk call",         thresholdLabel: "Min confidence %",     thresholdDefault: 0,  color: C.accent },
};

const EMPTY_META: TypeMeta = { label: "", thresholdLabel: null, thresholdDefault: null, color: C.textDim };

interface AlertRule {
  id: number;
  name: string;
  alert_type: string;
  ticker: string | null;
  threshold: number | null;
  notify_email: string | null;
  is_active: boolean;
  event_count: number;
}

interface AlertEvent {
  id: number;
  ticker: string;
  message: string;
  rule_name: string;
  triggered_at: string;
}

interface AlertTypeOption {
  value: string;
  description?: string;
}

interface AlertForm {
  name: string;
  alert_type: string;
  ticker: string;
  threshold: number | string;
  notify_email: string;
}

const card: CSSProperties = { ...themeCard, padding: "16px 18px" };
const inputStyle: CSSProperties = { background: C.bg, color: C.text, border: "1px solid var(--c-divider)", borderRadius: 6, padding: "7px 10px", fontSize: 13 };

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  try { return new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); }
  catch { return iso; }
}

function NewRuleForm({ types, onCreated }: { types: AlertTypeOption[]; onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<AlertForm>({ name: "", alert_type: "high_signal", ticker: "", threshold: 70, notify_email: "" });
  const [saving, setSaving] = useState(false);
  const meta: TypeMeta = TYPE_META[form.alert_type] || EMPTY_META;

  const submit = async () => {
    setSaving(true);
    try {
      await createAlertRule({
        name: form.name.trim() || meta.label,
        alert_type: form.alert_type,
        ticker: form.ticker.trim() || null,
        threshold: meta.thresholdLabel ? Number(form.threshold) : null,
        notify_email: form.notify_email.trim() || null,
      });
      setForm({ name: "", alert_type: "high_signal", ticker: "", threshold: 70, notify_email: "" });
      setOpen(false);
      onCreated();
    } finally { setSaving(false); }
  };

  if (!open) {
    return (
      <button onClick={() => setOpen(true)}
        style={{ background: C.accentSolid, color: "#fff", border: "none", borderRadius: 7, padding: "8px 16px", fontSize: 13, cursor: "pointer", fontWeight: 600 }}>
        + New Alert Rule
      </button>
    );
  }

  return (
    <div style={{ ...card, display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ color: C.textBright, fontWeight: 600, fontSize: 14 }}>New Alert Rule</div>
      <input style={inputStyle} placeholder="Rule name (optional)"
        value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <select style={{ ...inputStyle, flex: 1, minWidth: 160 }} value={form.alert_type}
          onChange={(e) => {
            const m = TYPE_META[e.target.value];
            setForm({ ...form, alert_type: e.target.value, threshold: m?.thresholdDefault ?? "" });
          }}>
          {(types.length ? types : Object.keys(TYPE_META).map((v) => ({ value: v }))).map((t) => (
            <option key={t.value} value={t.value}>{TYPE_META[t.value]?.label || t.value}</option>
          ))}
        </select>
        <input style={{ ...inputStyle, width: 110, textTransform: "uppercase" }} placeholder="Ticker (any)"
          value={form.ticker} onChange={(e) => setForm({ ...form, ticker: e.target.value })} />
        {meta.thresholdLabel && (
          <input style={{ ...inputStyle, width: 130 }} type="number" placeholder={meta.thresholdLabel}
            value={form.threshold} onChange={(e) => setForm({ ...form, threshold: e.target.value })} />
        )}
      </div>
      {meta.thresholdLabel && <div style={{ color: C.textDim, fontSize: 11 }}>{meta.thresholdLabel}</div>}
      <input style={inputStyle} placeholder="Notify email (optional)"
        value={form.notify_email} onChange={(e) => setForm({ ...form, notify_email: e.target.value })} />
      <div style={{ display: "flex", gap: 8 }}>
        <button onClick={submit} disabled={saving}
          style={{ background: C.accentSolid, color: "#fff", border: "none", borderRadius: 6, padding: "7px 16px", fontSize: 13, cursor: "pointer" }}>
          {saving ? "Saving…" : "Create"}
        </button>
        <button onClick={() => setOpen(false)}
          style={{ background: C.surfaceAlt, color: C.textMuted, border: "none", borderRadius: 6, padding: "7px 12px", fontSize: 13, cursor: "pointer" }}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function RuleCard({ rule, onToggle, onDelete, canEdit }: { rule: AlertRule; onToggle: (rule: AlertRule) => void; onDelete: (id: number) => void; canEdit: boolean }) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const meta: TypeMeta = TYPE_META[rule.alert_type] || EMPTY_META;

  return (
    <div style={{ ...card, display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 16px" }}>
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: rule.is_active ? (meta.color || C.success) : C.divider }} />
          <span style={{ color: C.textBright, fontWeight: 600, fontSize: 14 }}>{rule.name}</span>
          {rule.ticker && <span style={{ color: C.accent, fontSize: 12, fontWeight: 700 }}>{rule.ticker}</span>}
        </div>
        <div style={{ color: C.textDim, fontSize: 12, marginTop: 3 }}>
          {meta.label || rule.alert_type}
          {rule.threshold != null && ` · threshold ${rule.threshold}`}
          {rule.notify_email && ` · emails ${rule.notify_email}`}
          {` · ${rule.event_count} fired`}
        </div>
      </div>
      {canEdit && <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <button onClick={() => onToggle(rule)}
          style={{ background: C.surfaceAlt, color: rule.is_active ? C.textMuted : C.success, border: "1px solid var(--c-divider)", borderRadius: 6, padding: "4px 10px", fontSize: 12, cursor: "pointer" }}>
          {rule.is_active ? "Pause" : "Resume"}
        </button>
        {confirmDelete ? (
          <>
            <span style={{ color: C.danger, fontSize: 12 }}>Delete?</span>
            <button onClick={() => onDelete(rule.id)}
              style={{ background: C.dangerDeep, color: "var(--c-danger)", border: "none", borderRadius: 6, padding: "4px 10px", fontSize: 12, cursor: "pointer", fontWeight: 700 }}>
              Yes
            </button>
            <button onClick={() => setConfirmDelete(false)}
              style={{ background: C.surfaceAlt, color: C.textMuted, border: "none", borderRadius: 6, padding: "4px 10px", fontSize: 12, cursor: "pointer" }}>
              No
            </button>
          </>
        ) : (
          <button onClick={() => setConfirmDelete(true)}
            style={{ background: "transparent", color: C.textDim, border: "1px solid var(--c-surfaceAlt)", borderRadius: 6, padding: "4px 10px", fontSize: 12, cursor: "pointer" }}>
            Delete
          </button>
        )}
      </div>}
    </div>
  );
}

export default function Alerts() {
  const isAdmin = useAdmin();
  useDocumentTitle("Alerts");
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [events, setEvents] = useState<AlertEvent[]>([]);
  const [types, setTypes] = useState<AlertTypeOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState("");
  const [lastEvaluated, setLastEvaluated] = useState<string | null>(
    () => localStorage.getItem("insidertrack_alerts_last_run") || null
  );

  const load = () => {
    setLoading(true);
    Promise.all([getAlertRules(), getAlertEvents({ limit: 100 }), getAlertTypes()])
      .then(([r, e, t]) => {
        setRules(r.data as unknown as AlertRule[]);
        setEvents(e.data as unknown as AlertEvent[]);
        setTypes(t.data as AlertTypeOption[]);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    if (isAdmin) markAlertsSeen().catch(() => {}); // "seen" is an admin flag
  }, []);

  const toggleRule = async (rule: AlertRule) => {
    await updateAlertRule(rule.id, { is_active: !rule.is_active });
    load();
  };

  const removeRule = async (id: number) => {
    await deleteAlertRule(id);
    load();
  };

  const runNow = async () => {
    setMsg("Evaluating…");
    try {
      const r = await runAlerts();
      const data = r.data as { new_events?: number; rules?: number };
      setMsg(`Done — ${data.new_events ?? 0} new alert(s) from ${data.rules ?? 0} rule(s).`);
      const ts = new Date().toISOString();
      localStorage.setItem("insidertrack_alerts_last_run", ts);
      setLastEvaluated(ts);
      load();
    } catch {
      setMsg("Evaluation failed.");
    }
  };

  return (
    <div style={{ maxWidth: 900, margin: "0 auto" }}>
      <div className="page-head">
        <div>
          <h1>Alerts</h1>
          <p style={{ color: C.textDim, margin: 0, fontSize: 13 }}>
            Define conditions on signals, insiders, whales, and earnings — get notified when they fire.
          </p>
          {lastEvaluated && (
            <p style={{ color: C.textDim, margin: "4px 0 0", fontSize: 11 }}>
              Last evaluated: {new Date(lastEvaluated).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
            </p>
          )}
        </div>
        {isAdmin && <button onClick={runNow}
          style={{ background: "rgba(74,222,128,0.08)", color: C.success, border: "1px solid rgba(74,222,128,0.2)", borderRadius: 6, padding: "7px 14px", fontSize: 12, cursor: "pointer" }}>
          ↻ Evaluate Now
        </button>}
      </div>

      {msg && (
        <div style={{ ...card, marginBottom: 16, color: C.textSoft, fontSize: 13, padding: "10px 14px" }}>{msg}</div>
      )}

      {isAdmin && <div style={{ marginBottom: 16 }}>
        <NewRuleForm types={types} onCreated={load} />
      </div>}

      <h2 style={{ color: C.textSoft, fontSize: 13, fontWeight: 600, margin: "20px 0 10px" }}>
        Rules ({rules.length})
      </h2>
      {loading ? (
        <p style={{ color: C.textDim }}>Loading…</p>
      ) : rules.length === 0 ? (
        <p style={{ color: C.textDim, fontSize: 13 }}>{isAdmin ? "No rules yet. Create one above." : "No alert rules are configured yet."}</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {rules.map((r) => (
            <RuleCard key={r.id} rule={r} onToggle={toggleRule} onDelete={removeRule} canEdit={isAdmin} />
          ))}
        </div>
      )}

      <h2 style={{ color: C.textSoft, fontSize: 13, fontWeight: 600, margin: "26px 0 10px" }}>
        Triggered Alerts ({events.length})
      </h2>
      {events.length === 0 ? (
        <p style={{ color: C.textDim, fontSize: 13 }}>Nothing has triggered yet. Try "Evaluate Now".</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {events.map((e) => (
            <div key={e.id} style={{ ...card, padding: "10px 14px", display: "flex", gap: 12, alignItems: "flex-start" }}>
              <span style={{ color: C.accent, fontWeight: 700, fontSize: 13, minWidth: 52 }}>{e.ticker}</span>
              <div style={{ flex: 1 }}>
                <div style={{ color: C.text, fontSize: 13 }}>{e.message}</div>
                <div style={{ color: C.textDim, fontSize: 11, marginTop: 2 }}>
                  {e.rule_name} · {fmtDate(e.triggered_at)}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
