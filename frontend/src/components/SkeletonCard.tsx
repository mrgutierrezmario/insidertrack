import { C } from "../lib/theme";
// Injects @keyframes pulse once, then renders grey placeholder boxes.
let injected = false;
function ensureStyles() {
  if (injected) return;
  injected = true;
  const s = document.createElement("style");
  s.textContent = `@keyframes skPulse{0%,100%{opacity:.35}50%{opacity:.7}}
.sk-pulse{animation:skPulse 1.4s ease-in-out infinite}`;
  document.head.appendChild(s);
}

interface SkeletonCardProps {
  lines?: 1 | 2 | 3;
  height?: number;
}

export default function SkeletonCard({ lines = 2, height = 80 }: SkeletonCardProps) {
  ensureStyles();
  return (
    <div
      className="sk-pulse"
      style={{
        background: C.surface,
        border: "1px solid #1e2533",
        borderRadius: 10,
        padding: "16px 18px",
        height,
        display: "flex",
        flexDirection: "column",
        gap: 10,
        justifyContent: "center",
      }}
    >
      <div style={{ height: 14, background: C.surfaceAlt, borderRadius: 4, width: "55%" }} />
      {lines >= 2 && <div style={{ height: 11, background: C.surfaceAlt, borderRadius: 4, width: "80%" }} />}
      {lines >= 3 && <div style={{ height: 11, background: C.surfaceAlt, borderRadius: 4, width: "40%" }} />}
    </div>
  );
}
