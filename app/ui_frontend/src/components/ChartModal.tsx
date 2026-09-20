import { C } from "../lib/theme";
import { useEffect } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";

interface ChartModalProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
}

export default function ChartModal({ title, onClose, children }: ChartModalProps) {
  // Lock body scroll while open
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, []);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return createPortal(
    <div
      style={{
        position: "fixed", inset: 0, zIndex: 1000,
        background: C.bg,
        display: "flex", flexDirection: "column",
      }}
    >
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "14px 16px",
        borderBottom: "1px solid var(--c-surfaceAlt)",
      }}>
        <div>
          <span style={{ color: C.textBright, fontWeight: 600, fontSize: 15 }}>{title}</span>
          <span style={{ color: C.textDim, fontSize: 12, marginLeft: 10 }}>
            drag to explore · pinch to zoom
          </span>
        </div>
        <button
          onClick={onClose}
          style={{
            background: C.surfaceAlt, border: "1px solid var(--c-divider)",
            borderRadius: 8, color: C.textSoft,
            width: 36, height: 36, fontSize: 20, lineHeight: 1,
            cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
          }}
        >
          ×
        </button>
      </div>

      {/* Chart fills remaining space */}
      <div style={{ flex: 1, padding: "12px 8px 16px", minHeight: 0 }}>
        {children}
      </div>
    </div>,
    document.body
  );
}
