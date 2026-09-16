import { C } from "../lib/theme";
import { useEffect } from "react";

interface ConfirmModalProps {
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
  confirmLabel?: string;
  danger?: boolean;
}

export default function ConfirmModal({ message, onConfirm, onCancel, confirmLabel = "Confirm", danger = false }: ConfirmModalProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onCancel(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 1000,
      background: "rgba(0,0,0,0.6)", backdropFilter: "blur(2px)",
      display: "flex", alignItems: "center", justifyContent: "center",
    }} onClick={onCancel}>
      <div
        style={{
          background: C.surface, border: "1px solid #334155",
          borderRadius: 12, padding: "1.75rem 2rem",
          maxWidth: 400, width: "90%", textAlign: "center",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <p style={{ color: C.text, fontSize: "0.95rem", marginBottom: "1.5rem", lineHeight: 1.5 }}>
          {message}
        </p>
        <div style={{ display: "flex", gap: "0.75rem", justifyContent: "center" }}>
          <button
            onClick={onCancel}
            style={{
              background: C.surfaceAlt, color: C.textSoft,
              border: "1px solid #334155", borderRadius: 7,
              padding: "0.55rem 1.25rem", cursor: "pointer", fontSize: "0.88rem",
            }}
          >
            Cancel
          </button>
          <button
            autoFocus
            onClick={onConfirm}
            style={{
              background: danger ? C.dangerDeep : C.accentSolid,
              color: danger ? "#fca5a5" : "#fff",
              border: `1px solid ${danger ? "#991b1b" : C.accentSolid}`,
              borderRadius: 7, padding: "0.55rem 1.25rem",
              cursor: "pointer", fontSize: "0.88rem", fontWeight: 600,
            }}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
