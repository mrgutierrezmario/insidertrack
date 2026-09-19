import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import Disclaimer from "./components/Disclaimer";
import { Routes, Route, NavLink, Link, useLocation } from "react-router-dom";
import SearchBar from "./components/SearchBar";
import ErrorBoundary from "./components/ErrorBoundary";
import { getUnseenAlertCount } from "./lib/api";
import useTheme from "./hooks/useTheme";
import useAdmin from "./hooks/useAdmin";

// Route-level code splitting. Each page becomes its own chunk, loaded on
// first navigation. Cuts the initial bundle by ~60%; the Suspense fallback
// covers the (usually <100ms) chunk fetch.
const Dashboard   = lazy(() => import("./pages/Dashboard"));
const Feed        = lazy(() => import("./pages/Feed"));
const Markets     = lazy(() => import("./pages/Markets"));
const News        = lazy(() => import("./pages/News"));
const Earnings    = lazy(() => import("./pages/Earnings"));
const Politicians = lazy(() => import("./pages/Politicians"));
const Leaderboard = lazy(() => import("./pages/Leaderboard"));
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

interface NavEntry { to: string; label: string; hint?: string; }
interface NavGroup { label: string; items: NavEntry[]; }

// Two plain links for the pages people open most, then groups by what the
// data *is* (who filed it), then analysis, context, and the visitor's own.
const TOP_LINKS: ReadonlyArray<NavEntry> = [
  { to: "/",         label: "Dashboard" },
  { to: "/activity", label: "Activity" },
];

const NAV_GROUPS: ReadonlyArray<NavGroup> = [
  { label: "Congress", items: [
    { to: "/feed",        label: "Congressional Trades", hint: "STOCK Act disclosures" },
    { to: "/politicians", label: "Politicians", hint: "Every member with a filing" },
    { to: "/leaderboard", label: "Leaderboard", hint: "Members ranked by results vs. SPY" },
  ]},
  { label: "Institutions", items: [
    { to: "/insiders", label: "Corporate Insiders", hint: "SEC Form 4" },
    { to: "/whales",   label: "Whales", hint: "Quarterly 13F holdings" },
    { to: "/filings",  label: "SEC Filings", hint: "Recent filings by institution" },
    { to: "/fed",      label: "Fed Officials", hint: "FOMC roster & disclosures" },
  ]},
  { label: "Signals", items: [
    { to: "/signals",   label: "Signal Scores", hint: "Composite score, 0–100, per ticker" },
    { to: "/outcomes",  label: "Outcomes", hint: "How past signals played out" },
    { to: "/simulator", label: "Simulator", hint: "Hypothetical returns vs. SPY" },
  ]},
  { label: "Markets", items: [
    { to: "/markets",  label: "Market Overview", hint: "Indices, movers, Fed rate" },
    { to: "/news",     label: "News", hint: "Headlines for tracked tickers" },
    { to: "/earnings", label: "Earnings", hint: "Upcoming reports" },
  ]},
  { label: "My Watch", items: [
    { to: "/watchlist", label: "Watchlist", hint: "Your tickers" },
    { to: "/alerts",    label: "Alerts", hint: "Rules & triggered events" },
  ]},
];

function useUnseenAlerts(enabled: boolean): number {
  const [count, setCount] = useState<number>(0);
  useEffect(() => {
    if (!enabled) { setCount(0); return; }
    const fetch = () => getUnseenAlertCount().then((r) => setCount(r.data?.unseen ?? 0)).catch(() => {});
    fetch();
    const t = setInterval(fetch, 60_000);
    return () => clearInterval(t);
  }, [enabled]);
  return count;
}

function GearIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

function Badge({ n }: { n: number }) {
  if (n <= 0) return null;
  return <span className="badge-count">{n > 99 ? "99+" : n}</span>;
}

/** One desktop menu: a button that opens a list of links; closes on outside click / Esc / navigation. */
function NavGroupMenu({ group, alerts }: { group: NavGroup; alerts: number }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  const { pathname } = useLocation();
  const active = group.items.some((i) => (i.to === "/" ? pathname === "/" : pathname.startsWith(i.to)));
  const badge = group.items.some((i) => i.to === "/alerts") ? alerts : 0;

  useEffect(() => { setOpen(false); }, [pathname]);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open]);

  return (
    <div ref={ref} className={"navgroup" + (active ? " navgroup--active" : "")}>
      <button type="button" className="navgroup__btn" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {group.label} <Badge n={badge} /> <span className="chev">▼</span>
      </button>
      {open && (
        <div className="navgroup__menu" role="menu">
          {group.items.map((i) => (
            <NavLink key={i.to} to={i.to} end={i.to === "/"} className={({ isActive }) => "navgroup__item" + (isActive ? " active" : "")} role="menuitem">
              <span>{i.label} {i.to === "/alerts" && <Badge n={alerts} />}</span>
              {i.hint && <small>{i.hint}</small>}
            </NavLink>
          ))}
        </div>
      )}
    </div>
  );
}

/** Phone drawer: all groups expanded, one tap to navigate. */
function Drawer({ open, onClose, alerts }: { open: boolean; onClose: () => void; alerts: number }) {
  const { pathname } = useLocation();
  useEffect(() => { onClose(); /* close on navigation */ }, [pathname]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = ""; };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Menu">
        <div className="drawer__head">
          <span style={{ fontWeight: 700 }}>Menu</span>
          <button type="button" className="iconbtn" aria-label="Close menu" onClick={onClose}>✕</button>
        </div>
        <div className="drawer__body">
          <div className="drawer__group">Overview</div>
          {TOP_LINKS.map((l) => (
            <NavLink key={l.to} to={l.to} end={l.to === "/"} className={({ isActive }) => "drawer__link" + (isActive ? " active" : "")}>{l.label}</NavLink>
          ))}
          {NAV_GROUPS.map((g) => (
            <div key={g.label}>
              <div className="drawer__group">{g.label}</div>
              {g.items.map((i) => (
                <NavLink key={i.to} to={i.to} end={i.to === "/"} className={({ isActive }) => "drawer__link" + (isActive ? " active" : "")}>
                  {i.label} {i.to === "/alerts" && <Badge n={alerts} />}
                </NavLink>
              ))}
            </div>
          ))}
          <div className="drawer__group">Settings</div>
          <NavLink to="/config" className={({ isActive }) => "drawer__link" + (isActive ? " active" : "")}>Settings</NavLink>
        </div>
        {/* The app bar hides the business name on phones; this is where it lives instead. */}
        <div className="drawer__foot">
          <img src="/logo-mark.svg" alt="" />
          <div>
            <div>Insider<b>Track</b></div>
            <small>M.G. Network &amp; Technology Solutions · v{__APP_VERSION__} · <a href="/guide" style={{ color: "inherit" }}>Guide</a> · <a href="/privacy" style={{ color: "inherit" }}>Privacy</a></small>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  useTheme(); // keeps <html data-theme> in sync with the stored preference
  const isAdmin = useAdmin();
  const alerts = useUnseenAlerts(isAdmin);
  const [drawer, setDrawer] = useState(false);
  const closeDrawer = useCallback(() => setDrawer(false), []);

  return (
    <Disclaimer>
      <header className="appbar">
        <Link to="/" className="appbar__brand" aria-label="InsiderTrack home">
          <img src="/logo-mark.svg" alt="" />
          <span className="appbar__wordmark">
            <span>Insider<b>Track</b></span>
            <small>M.G. Network &amp; Technology Solutions</small>
          </span>
        </Link>

        <nav className="appbar__nav only-desktop" aria-label="Primary">
          {TOP_LINKS.map((l) => (
            <NavLink key={l.to} to={l.to} end={l.to === "/"} className={({ isActive }) => "navlink" + (isActive ? " active" : "")}>{l.label}</NavLink>
          ))}
          <span className="appbar__sep" aria-hidden="true" />
          {NAV_GROUPS.map((g) => <NavGroupMenu key={g.label} group={g} alerts={alerts} />)}
        </nav>

        <div className="appbar__right">
          <SearchBar />
          <NavLink to="/config" className={({ isActive }) => "iconbtn only-desktop" + (isActive ? " active" : "")} aria-label="Settings" data-tip="Settings">
            <GearIcon />
          </NavLink>
          <button type="button" className="iconbtn only-mobile" aria-label="Open menu" onClick={() => setDrawer(true)}>☰</button>
        </div>
      </header>
      <Drawer open={drawer} onClose={closeDrawer} alerts={alerts} />

      <main className="main-content">
        <ErrorBoundary>
        <Suspense fallback={<div style={{ color: "var(--c-textFaint)", padding: "60px 0", textAlign: "center" }}>Loading…</div>}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/feed" element={<Feed />} />
          <Route path="/markets" element={<Markets />} />
          <Route path="/signals" element={<Signals />} />
          <Route path="/politicians" element={<Politicians />} />
          <Route path="/leaderboard" element={<Leaderboard />} />
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

      <footer className="site-footer">
        © {new Date().getFullYear()} M.G. Network &amp; Technology Solutions · Public filings only · Not financial advice
      </footer>
    </Disclaimer>
  );
}
