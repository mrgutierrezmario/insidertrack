import { C } from "../lib/theme";
import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

interface ErrorBoundaryProps { children: ReactNode }
interface ErrorBoundaryState { hasError: boolean; error: Error | null }

export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(_error: Error, _info: ErrorInfo): void {
    // hook for future logging — kept type-explicit so it's obvious how to wire
  }

  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <div style={{
        maxWidth: 520, margin: "80px auto", textAlign: "center",
        background: C.surface, border: "1px solid #7f1d1d",
        borderRadius: 12, padding: "2rem",
      }}>
        <div style={{ fontSize: "2rem", marginBottom: "0.75rem" }}>⚠️</div>
        <h2 style={{ color: "#fca5a5", fontWeight: 700, marginBottom: "0.5rem" }}>Something went wrong</h2>
        <p style={{ color: C.textMuted, fontSize: "0.85rem", marginBottom: "1.5rem" }}>
          {this.state.error?.message || "An unexpected error occurred."}
        </p>
        <button
          onClick={() => { this.setState({ hasError: false, error: null }); window.location.reload(); }}
          style={{
            background: C.accentSolid, color: "#fff", border: "none",
            borderRadius: 7, padding: "0.6rem 1.5rem",
            cursor: "pointer", fontSize: "0.9rem", fontWeight: 600,
          }}
        >
          Reload page
        </button>
      </div>
    );
  }
}
