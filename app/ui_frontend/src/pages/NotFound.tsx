import { C } from "../lib/theme";
import useDocumentTitle from "../hooks/useDocumentTitle";
import { Link } from "react-router-dom";

export default function NotFound() {
  useDocumentTitle("Not found");
  return (
    <div style={{ textAlign: "center", padding: "80px 24px" }}>
      <div style={{ fontSize: 64, marginBottom: 16 }}>404</div>
      <div style={{ color: C.textBright, fontSize: 22, fontWeight: 700, marginBottom: 8 }}>Page not found</div>
      <div style={{ color: C.textDim, fontSize: 14, marginBottom: 32 }}>
        That page doesn't exist. Check the address, or go back to the Dashboard.
      </div>
      <Link
        to="/"
        style={{
          background: C.accentSolid, color: "#fff", textDecoration: "none",
          padding: "10px 24px", borderRadius: 8, fontWeight: 600, fontSize: 14,
        }}
      >
        ← Back to Dashboard
      </Link>
    </div>
  );
}
