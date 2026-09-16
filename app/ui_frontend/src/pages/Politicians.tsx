import { C } from "../lib/theme";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { isAxiosError } from "axios";
import { getPoliticians, createPolitician, updatePolitician, toggleTrack, deletePolitician } from "../lib/api";
import ConfirmModal from "../components/ConfirmModal";

const PARTY_COLOR: Record<string, string> = { D: "#3b82f6", R: C.dangerSolid, I: C.info };
const CHAMBER_LABEL: Record<string, string> = { house: "House", senate: "Senate" };

interface PoliticianRow {
  id: number;
  name: string;
  chamber: string;
  party: string | null;
  state: string | null;
  description: string | null;
  why_tracked: string | null;
  is_tracked: boolean;
  trade_count?: number;
}

interface PoliticianForm {
  name: string;
  chamber: string;
  party: string;
  state: string;
  description: string;
  why_tracked: string;
}

interface EditNotes {
  description: string;
  why_tracked: string;
}

const inputStyle = {
  background: C.bg, color: C.text,
  border: "1px solid #1e2533", borderRadius: 6,
  padding: "0.5rem 0.75rem", fontSize: "0.85rem", width: "100%",
};

const EMPTY_FORM: PoliticianForm = { name: "", chamber: "house", party: "R", state: "", description: "", why_tracked: "" };

export default function Politicians() {
  const [politicians, setPoliticians] = useState<PoliticianRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState<PoliticianForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [editNotes, setEditNotes] = useState<EditNotes>({ description: "", why_tracked: "" });
  const [error, setError] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<PoliticianRow | null>(null);
  const [nameFilter, setNameFilter] = useState("");
  const navigate = useNavigate();

  const load = () =>
    getPoliticians()
      .then((r) => setPoliticians(r.data as PoliticianRow[]))
      .finally(() => setLoading(false));

  useEffect(() => { load(); }, []);

  const handleAdd = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError("");
    setSaving(true);
    try {
      await createPolitician({ ...form } as unknown as Parameters<typeof createPolitician>[0]);
      setForm(EMPTY_FORM);
      setShowAdd(false);
      load();
    } catch (err) {
      const detail = isAxiosError(err) ? (err.response?.data as { detail?: string } | undefined)?.detail : null;
      setError(detail || "Failed to add politician");
    } finally { setSaving(false); }
  };

  const handleTrack = async (p: PoliticianRow) => {
    await toggleTrack(p.id, !p.is_tracked);
    setPoliticians((list) => list.map((x) => x.id === p.id ? { ...x, is_tracked: !x.is_tracked } : x));
  };

  const startEdit = (p: PoliticianRow) => {
    setEditId(p.id);
    setEditNotes({ description: p.description ?? "", why_tracked: p.why_tracked ?? "" });
  };

  const saveEdit = async (id: number) => {
    await updatePolitician(id, editNotes);
    setPoliticians((list) => list.map((x) => x.id === id ? { ...x, ...editNotes } : x));
    setEditId(null);
  };

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    await deletePolitician(deleteTarget.id);
    setPoliticians((list) => list.filter((x) => x.id !== deleteTarget.id));
    setDeleteTarget(null);
  };

  const visiblePoliticians = nameFilter
    ? politicians.filter((p) => p.name.toLowerCase().includes(nameFilter.toLowerCase()))
    : politicians;
  const tracked = visiblePoliticians.filter((p) => p.is_tracked);
  const untracked = visiblePoliticians.filter((p) => !p.is_tracked);

  return (
    <div>
      {deleteTarget && (
        <ConfirmModal
          message={`Remove Politician — permanently delete ${deleteTarget.name} and all their trades? This cannot be undone.`}
          confirmLabel="Remove Permanently"
          danger
          onConfirm={handleDeleteConfirm}
          onCancel={() => setDeleteTarget(null)}
        />
      )}

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem" }}>
        <div>
          <h1 style={{ fontSize: "1.5rem", fontWeight: 700 }}>Politicians</h1>
          <p style={{ color: C.textMuted, fontSize: "0.85rem", marginTop: 4 }}>
            Why we track each person — and add new ones to watch.
          </p>
        </div>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <input
            placeholder="Search name…"
            value={nameFilter}
            onChange={(e) => setNameFilter(e.target.value)}
            style={{
              background: C.surface, color: C.text,
              border: "1px solid #1e2533", borderRadius: 6,
              padding: "0.45rem 0.85rem", fontSize: "0.85rem", width: 160,
            }}
          />
          <button
            onClick={() => { setShowAdd((v) => !v); setError(""); }}
            style={{ background: showAdd ? C.surfaceAlt : C.accentSolid, color: "#fff", border: "none", padding: "0.5rem 1.25rem", borderRadius: 6, cursor: "pointer" }}
          >
            {showAdd ? "Cancel" : "+ Add Person"}
          </button>
        </div>
      </div>

      {showAdd && (
        <form onSubmit={handleAdd}
          style={{ background: C.surface, border: "1px solid #1e2533", borderRadius: 10, padding: "1.5rem", marginBottom: "2rem" }}>
          <h2 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "1rem", color: C.textSoft }}>Add new politician to track</h2>
          {error && <p style={{ color: C.danger, marginBottom: "0.75rem", fontSize: "0.85rem" }}>{error}</p>}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: "0.75rem", marginBottom: "0.75rem" }}>
            <div>
              <label style={{ color: C.textMuted, fontSize: "0.75rem", display: "block", marginBottom: 4 }}>Full name *</label>
              <input style={inputStyle} value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder="e.g. Jane Smith" required />
            </div>
            <div>
              <label style={{ color: C.textMuted, fontSize: "0.75rem", display: "block", marginBottom: 4 }}>Chamber *</label>
              <select style={inputStyle} value={form.chamber} onChange={(e) => setForm((f) => ({ ...f, chamber: e.target.value }))}>
                <option value="house">House</option>
                <option value="senate">Senate</option>
              </select>
            </div>
            <div>
              <label style={{ color: C.textMuted, fontSize: "0.75rem", display: "block", marginBottom: 4 }}>Party</label>
              <select style={inputStyle} value={form.party} onChange={(e) => setForm((f) => ({ ...f, party: e.target.value }))}>
                <option value="R">Republican (R)</option>
                <option value="D">Democrat (D)</option>
                <option value="I">Independent (I)</option>
              </select>
            </div>
            <div>
              <label style={{ color: C.textMuted, fontSize: "0.75rem", display: "block", marginBottom: 4 }}>State (e.g. CA)</label>
              <input style={inputStyle} value={form.state} onChange={(e) => setForm((f) => ({ ...f, state: e.target.value.toUpperCase().slice(0, 2) }))} placeholder="TX" maxLength={2} />
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem", marginBottom: "1rem" }}>
            <div>
              <label style={{ color: C.textMuted, fontSize: "0.75rem", display: "block", marginBottom: 4 }}>Bio / description</label>
              <textarea style={{ ...inputStyle, resize: "vertical", minHeight: 72 }} value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} placeholder="Brief background on this person..." />
            </div>
            <div>
              <label style={{ color: C.textMuted, fontSize: "0.75rem", display: "block", marginBottom: 4 }}>Why we track them</label>
              <textarea style={{ ...inputStyle, resize: "vertical", minHeight: 72 }} value={form.why_tracked} onChange={(e) => setForm((f) => ({ ...f, why_tracked: e.target.value }))} placeholder="What makes their trades worth watching..." />
            </div>
          </div>
          <button type="submit" disabled={saving}
            style={{ background: C.accentSolid, color: "#fff", border: "none", padding: "0.5rem 1.5rem", borderRadius: 6, cursor: "pointer", opacity: saving ? 0.6 : 1 }}>
            {saving ? "Adding..." : "Add & Track"}
          </button>
        </form>
      )}

      {loading ? (
        <p style={{ color: C.textMuted }}>Loading...</p>
      ) : (
        <>
          <PoliticianGroup title={`Tracking (${tracked.length})`} items={tracked}
            onTrack={handleTrack} onEdit={startEdit} onSaveEdit={saveEdit}
            onCancelEdit={() => setEditId(null)} onDelete={setDeleteTarget}
            editId={editId} editNotes={editNotes} setEditNotes={setEditNotes} navigate={navigate} />
          {untracked.length > 0 && (
            <PoliticianGroup title={`Not tracking (${untracked.length})`} items={untracked}
              onTrack={handleTrack} onEdit={startEdit} onSaveEdit={saveEdit}
              onCancelEdit={() => setEditId(null)} onDelete={setDeleteTarget}
              editId={editId} editNotes={editNotes} setEditNotes={setEditNotes} navigate={navigate} muted />
          )}
        </>
      )}
    </div>
  );
}

interface CardHandlers {
  onTrack: (p: PoliticianRow) => void;
  onEdit: (p: PoliticianRow) => void;
  onSaveEdit: (id: number) => void;
  onCancelEdit: () => void;
  onDelete: (p: PoliticianRow) => void;
  editId: number | null;
  editNotes: EditNotes;
  setEditNotes: React.Dispatch<React.SetStateAction<EditNotes>>;
  navigate: (path: string) => void;
}

function PoliticianGroup({ title, items, muted, ...handlers }: { title: string; items: PoliticianRow[]; muted?: boolean } & CardHandlers) {
  return (
    <div style={{ marginBottom: "2rem" }}>
      <h2 style={{ fontSize: "0.85rem", fontWeight: 600, color: muted ? C.textDim : C.textSoft, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "0.75rem" }}>
        {title}
      </h2>
      <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
        {items.map((p) => <PoliticianCard key={p.id} p={p} muted={muted} {...handlers} />)}
      </div>
    </div>
  );
}

function PoliticianCard({ p, muted, onTrack, onEdit, onSaveEdit, onCancelEdit, onDelete, editId, editNotes, setEditNotes, navigate }: { p: PoliticianRow; muted?: boolean } & CardHandlers) {
  const isEditing = editId === p.id;
  const partyColor = (p.party && PARTY_COLOR[p.party]) || C.textMuted;

  return (
    <div style={{
      background: muted ? "#0f1117" : C.surface,
      border: `1px solid ${muted ? "#111827" : C.surfaceAlt}`,
      borderRadius: 10, padding: "1.25rem", opacity: muted ? 0.7 : 1,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: isEditing || p.description ? "0.75rem" : 0 }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: 4 }}>
            <button onClick={() => navigate(`/politician/${p.id}`)}
              style={{ background: "none", border: "none", color: C.accent, fontWeight: 700, fontSize: "1rem", cursor: "pointer", padding: 0 }}>
              {p.name}
            </button>
            <span style={{ background: partyColor + "22", color: partyColor, fontSize: "0.7rem", fontWeight: 600, padding: "1px 8px", borderRadius: 4 }}>
              {p.party}
            </span>
            <span style={{ color: C.textDim, fontSize: "0.75rem" }}>{CHAMBER_LABEL[p.chamber] || p.chamber} · {p.state}</span>
            {(p.trade_count ?? 0) > 0 && (
              <span style={{ background: C.surfaceAlt, color: C.textMuted, fontSize: "0.7rem", padding: "1px 8px", borderRadius: 4 }}>
                {p.trade_count} trade{p.trade_count !== 1 ? "s" : ""}
              </span>
            )}
          </div>
          {!isEditing && p.description && <p style={{ color: C.textSoft, fontSize: "0.82rem", marginBottom: p.why_tracked ? "0.5rem" : 0, lineHeight: 1.5 }}>{p.description}</p>}
          {!isEditing && p.why_tracked && (
            <div style={{ display: "flex", gap: "0.5rem", alignItems: "flex-start" }}>
              <span style={{ color: C.accent, fontSize: "0.75rem", fontWeight: 600, whiteSpace: "nowrap", marginTop: 2 }}>Why we track:</span>
              <p style={{ color: C.textMuted, fontSize: "0.82rem", lineHeight: 1.5, margin: 0 }}>{p.why_tracked}</p>
            </div>
          )}
          {!isEditing && !p.description && !p.why_tracked && (
            <p style={{ color: "#374151", fontSize: "0.8rem", fontStyle: "italic" }}>No description yet — click edit to add one.</p>
          )}
        </div>

        <div style={{ display: "flex", gap: "0.5rem", marginLeft: "1rem", flexShrink: 0 }}>
          <button onClick={() => onEdit(p)}
            style={{ background: C.surfaceAlt, color: C.textSoft, border: "none", padding: "0.3rem 0.75rem", borderRadius: 5, cursor: "pointer", fontSize: "0.78rem" }}>
            Edit
          </button>
          <button onClick={() => onTrack(p)}
            style={{ background: p.is_tracked ? "#7c3aed22" : C.surfaceAlt, color: p.is_tracked ? C.info : C.textMuted, border: `1px solid ${p.is_tracked ? "#7c3aed44" : C.surfaceAlt}`, padding: "0.3rem 0.75rem", borderRadius: 5, cursor: "pointer", fontSize: "0.78rem" }}>
            {p.is_tracked ? "✓ Tracking" : "Track"}
          </button>
          <button onClick={() => onDelete(p)}
            style={{ background: "transparent", color: "#374151", border: "none", padding: "0.3rem 0.5rem", borderRadius: 5, cursor: "pointer", fontSize: "0.78rem" }}
            title="Remove politician">
            ✕
          </button>
        </div>
      </div>

      {isEditing && (
        <div style={{ borderTop: "1px solid #1e2533", paddingTop: "0.75rem" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem", marginBottom: "0.75rem" }}>
            <div>
              <label style={{ color: C.textMuted, fontSize: "0.72rem", display: "block", marginBottom: 3 }}>Bio</label>
              <textarea style={{ background: C.bg, color: C.text, border: "1px solid #334155", borderRadius: 5, padding: "0.4rem 0.6rem", fontSize: "0.82rem", width: "100%", resize: "vertical", minHeight: 72 }}
                value={editNotes.description} onChange={(e) => setEditNotes((n) => ({ ...n, description: e.target.value }))} />
            </div>
            <div>
              <label style={{ color: C.textMuted, fontSize: "0.72rem", display: "block", marginBottom: 3 }}>Why we track</label>
              <textarea style={{ background: C.bg, color: C.text, border: "1px solid #334155", borderRadius: 5, padding: "0.4rem 0.6rem", fontSize: "0.82rem", width: "100%", resize: "vertical", minHeight: 72 }}
                value={editNotes.why_tracked} onChange={(e) => setEditNotes((n) => ({ ...n, why_tracked: e.target.value }))} />
            </div>
          </div>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button onClick={() => onSaveEdit(p.id)}
              style={{ background: C.accentSolid, color: "#fff", border: "none", padding: "0.35rem 1rem", borderRadius: 5, cursor: "pointer", fontSize: "0.82rem" }}>
              Save
            </button>
            <button onClick={onCancelEdit}
              style={{ background: C.surfaceAlt, color: C.textSoft, border: "none", padding: "0.35rem 1rem", borderRadius: 5, cursor: "pointer", fontSize: "0.82rem" }}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
