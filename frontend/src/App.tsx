import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import Disclaimer from "./components/Disclaimer";
import { Routes, Route, NavLink } from "react-router-dom";
import SearchBar from "./components/SearchBar";
import ErrorBoundary from "./components/ErrorBoundary";
import { getUnseenAlertCount } from "./lib/api";

// Route-level code splitting. Each page becomes its own chunk, loaded on
// first navigation. Cuts the initial bundle by ~60%; the Suspense fallback
// covers the (usually <100ms) chunk fetch.
const Dashboard   = lazy(() => import("./pages/Dashboard"));
const Feed        = lazy(() => import("./pages/Feed"));
const Markets     = lazy(() => import("./pages/Markets"));
const News        = lazy(() => import("./pages/News"));
const Earnings    = lazy(() => import("./pages/Earnings"));
const Politicians = lazy(() => import("./pages/Politicians"));
const Politician  = lazy(() => import("./pages/Politician"));
const Ticker      = lazy(() => import("./pages/Ticker"));
const Simulator   = lazy(() => import("./pages/Simulator"));
const Whales      = lazy(() => import("./pages/Whales"));
const Filings     = lazy(() => import("./pages/Filings"));
const Config      = lazy(() => import("./pages/Config"));
const AdminConfig = lazy(() => import("./pages/AdminConfig"));
const Outcomes    = lazy(() => import("./pages/Outcomes"));
const Alerts      = lazy(() => import("./pages/Alerts"));
const Insiders    = lazy(() => import("./pages/Insiders"));
const Watchlist   = lazy(() => import("./pages/Watchlist"));
const Whale       = lazy(() => import("./pages/Whale"));
const Signals     = lazy(() => import("./pages/Signals"));
const Fed         = lazy(() => import("./pages/Fed"));
const Activity    = lazy(() => import("./pages/Activity"));
const NotFound    = lazy(() => import("./pages/NotFound"));

// NavLink's `style` prop accepts a function whose arg shape varies across
// react-router versions (isPending/isTransitioning were added later). We only
// read `isActive`, so destructure just that and stay forward-compatible.
const linkStyle = ({ isActive }: { isActive: boolean }): CSSProperties => ({
  color: isActive ? "#38bdf8" : "#94a3b8",
  textDecoration: "none",
  fontWeight: isActive ? 600 : 400,
  fontSize: "0.88rem",
  whiteSpace: "nowrap",
});

function AlertsLink() {
  const [count, setCount] = useState<number>(0);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const fetch = () => {
      getUnseenAlertCount()
        .then((r) => setCount(r.data?.unseen ?? 0))
        .catch(() => {});
    };
    fetch();
    timer.current = setInterval(fetch, 60_000);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, []);

  return (
    <NavLink to="/alerts" style={({ isActive }) => ({ ...linkStyle({ isActive }), display: "flex", alignItems: "center", gap: 5 })}>
      Alerts
      {count > 0 && (
        <span style={{
          background: "#ef4444", color: "#fff",
          fontSize: 9, fontWeight: 700,
          borderRadius: 10, padding: "1px 6px",
          lineHeight: 1.6, minWidth: 16, textAlign: "center",
          display: "inline-block",
        }}>
          {count > 99 ? "99+" : count}
        </span>
      )}
    </NavLink>
  );
}

interface NavEntry { to: string; label: string; }

const ALL_NAV: ReadonlyArray<NavEntry> = [
  { to: "/",           label: "Dashboard" },
  { to: "/watchlist",  label: "Watchlist" },
  { to: "/feed",       label: "Trade Feed" },
  { to: "/markets",    label: "Markets" },
  { to: "/signals",    label: "Signals" },
  { to: "/politicians",label: "Politicians" },
  { to: "/fed",         label: "Fed Officials" },
  { to: "/activity",    label: "Activity" },
  { to: "/whales",     label: "Whales" },
  { to: "/insiders",   label: "Insiders" },
  { to: "/filings",    label: "Filings" },
  { to: "/news",       label: "News" },
  { to: "/earnings",   label: "Earnings" },
  { to: "/simulator",  label: "Simulator" },
  { to: "/outcomes",   label: "Outcomes" },
  { to: "/alerts",     label: "Alerts" },
  { to: "/config",     label: "⚙ Config" },
];

function HamburgerNav() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label="Toggle menu"
        style={{
          display: "none",
          background: "transparent", border: "1px solid #1e2533",
          color: "#94a3b8", borderRadius: 6,
          padding: "4px 10px", cursor: "pointer", fontSize: 18,
          lineHeight: 1,
        }}
        className="hamburger-btn"
      >
        ☰
      </button>

      {open && (
        <div
          onClick={() => setOpen(false)}
          style={{ position: "fixed", inset: 0, zIndex: 200, background: "rgba(0,0,0,0.55)" }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              position: "absolute", top: 0, right: 0,
              width: 230, height: "100dvh",
              background: "#0d1117", borderLeft: "1px solid #1e2533",
              display: "flex", flexDirection: "column",
            }}
          >
            {/* Header */}
            <div style={{ padding: "16px 20px 12px", borderBottom: "1px solid #1e2533", flexShrink: 0 }}>
              <span style={{ color: "#38bdf8", fontWeight: 700, fontSize: 15 }}>📈 InsiderTrack</span>
            </div>

            {/* Scrollable link list */}
            <div style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}>
              {ALL_NAV.map(({ to, label }) => (
                <NavLink
                  key={to}
                  to={to}
                  onClick={() => setOpen(false)}
                  style={({ isActive }) => ({
                    display: "block",
                    padding: "11px 20px",
                    color: isActive ? "#38bdf8" : "#94a3b8",
                    textDecoration: "none",
                    fontWeight: isActive ? 600 : 400,
                    fontSize: "0.92rem",
                    background: isActive ? "rgba(56,189,248,0.07)" : "transparent",
                    borderLeft: isActive ? "2px solid #38bdf8" : "2px solid transparent",
                  })}
                >
                  {label}
                </NavLink>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export default function App() {
  return (
    <Disclaimer>
      <style>{`
        @media (max-width: 900px) {
          .desktop-nav { display: none !important; }
          .hamburger-btn { display: block !important; }
          .main-content { padding: 1rem !important; }
        }
      `}</style>
      <div style={{ minHeight: "100vh" }}>
        <nav style={{
          display: "flex",
          padding: "0.6rem 1.25rem",
          borderBottom: "1px solid #1e2533",
          background: "#0d1117",
          alignItems: "center",
          gap: "1rem",
        }}>
          <span style={{ color: "#38bdf8", fontWeight: 700, whiteSpace: "nowrap", flexShrink: 0 }}>
            📈 InsiderTrack
          </span>

          {/* Desktop links */}
          <div className="desktop-nav" style={{
            display: "flex", gap: "1rem", alignItems: "center",
            overflowX: "auto", flex: 1, scrollbarWidth: "none",
          }}>
            <NavLink to="/" style={linkStyle}>Dashboard</NavLink>
            <NavLink to="/watchlist" style={linkStyle}>Watchlist</NavLink>
            <NavLink to="/feed" style={linkStyle}>Trade Feed</NavLink>
            <NavLink to="/markets" style={linkStyle}>Markets</NavLink>
            <NavLink to="/signals" style={linkStyle}>Signals</NavLink>
            <NavLink to="/politicians" style={linkStyle}>Politicians</NavLink>
            <NavLink to="/fed" style={linkStyle}>Fed Officials</NavLink>
            <NavLink to="/activity" style={linkStyle}>Activity</NavLink>
            <NavLink to="/whales" style={linkStyle}>Whales</NavLink>
            <NavLink to="/insiders" style={linkStyle}>Insiders</NavLink>
            <NavLink to="/filings" style={linkStyle}>Filings</NavLink>
            <NavLink to="/news" style={linkStyle}>News</NavLink>
            <NavLink to="/earnings" style={linkStyle}>Earnings</NavLink>
            <NavLink to="/simulator" style={linkStyle}>Simulator</NavLink>
            <NavLink to="/outcomes" style={linkStyle}>Outcomes</NavLink>
            <AlertsLink />
          </div>

          {/* Right side */}
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flexShrink: 0, marginLeft: "auto" }}>
            <SearchBar />
            <NavLink to="/config" style={linkStyle} className="desktop-nav">⚙ Config</NavLink>
            <HamburgerNav />
          </div>
        </nav>

        <main className="main-content" style={{ padding: "2rem" }}>
          <ErrorBoundary>
          <Suspense fallback={<div style={{ color: "#475569", padding: "60px 0", textAlign: "center" }}>Loading…</div>}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/feed" element={<Feed />} />
            <Route path="/markets" element={<Markets />} />
            <Route path="/signals" element={<Signals />} />
            <Route path="/politicians" element={<Politicians />} />
            <Route path="/fed" element={<Fed />} />
            <Route path="/activity" element={<Activity />} />
            <Route path="/politician/:id" element={<Politician />} />
            <Route path="/ticker/:symbol" element={<Ticker />} />
            <Route path="/whales" element={<Whales />} />
            <Route path="/filings" element={<Filings />} />
            <Route path="/news" element={<News />} />
            <Route path="/earnings" element={<Earnings />} />
            <Route path="/simulator" element={<Simulator />} />
            <Route path="/outcomes" element={<Outcomes />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/insiders" element={<Insiders />} />
            <Route path="/watchlist" element={<Watchlist />} />
            <Route path="/whale/:id" element={<Whale />} />
            <Route path="/config" element={<Config />} />
            <Route path="/admin" element={<AdminConfig />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
          </Suspense>
          </ErrorBoundary>
        </main>

        <footer style={{
          borderTop: "1px solid #1e2533",
          padding: "1rem 2rem",
          textAlign: "center",
          color: "#334155",
          fontSize: "0.75rem",
          letterSpacing: "0.02em",
        }}>
          © {new Date().getFullYear()} M.G. Network & Technology Solutions. All rights reserved.
        </footer>
      </div>
    </Disclaimer>
  );
}
