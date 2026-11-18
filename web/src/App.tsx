import { useEffect, useState } from "react";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import { Logo } from "./components/Logo";
import { IconChart, IconHome, IconList, IconRefresh, IconSettings, IconSync } from "./components/icons";
import { useRunSync, useStatus } from "./lib/hooks";
import { ago } from "./lib/format";
import { setToken } from "./lib/api";
import Dashboard from "./pages/Dashboard";
import Activities from "./pages/Activities";
import ActivityPage from "./pages/Activity";
import Insights from "./pages/Insights";
import SyncPage from "./pages/Sync";
import Settings from "./pages/Settings";

const NAV = [
  { to: "/", label: "Home", icon: IconHome, end: true },
  { to: "/activities", label: "Activities", icon: IconList },
  { to: "/insights", label: "Insights", icon: IconChart },
  { to: "/sync", label: "Sync", icon: IconSync },
  { to: "/settings", label: "Settings", icon: IconSettings },
];

function TokenGate() {
  const [value, setValue] = useState("");
  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 16 }}>
      <form className="card stack" style={{ width: "min(420px, 100%)" }} onSubmit={(e) => { e.preventDefault(); setToken(value.trim()); location.reload(); }}>
        <div className="brand"><Logo />RoutePass</div>
        <p className="secondary">This instance needs its API token (<span className="mono">ROUTEPASS_API_TOKEN</span>). It is stored in this browser only.</p>
        <input type="password" autoFocus placeholder="API token" value={value} onChange={(e) => setValue(e.target.value)} />
        <button className="primary" type="submit">Continue</button>
      </form>
    </div>
  );
}

function SyncButton({ compact = false }: { compact?: boolean }) {
  const { data } = useStatus();
  const run = useRunSync();
  const busy = data?.running || run.isPending;
  if (compact) {
    return (
      <button className="ghost icon" onClick={() => run.mutate(false)} disabled={busy} aria-label="Sync now"
        title={data?.last_run ? `Last sync ${ago(data.last_run.started_at)}` : "Sync now"}>
        <IconRefresh size={22} className={busy ? "spin" : ""} />
      </button>
    );
  }
  const last = data?.last_run;
  return (
    <div className="stack" style={{ gap: 6 }}>
      <button className="primary" onClick={() => run.mutate(false)} disabled={busy}>
        <IconRefresh className={busy ? "spin" : ""} />{busy ? "Syncing…" : "Sync now"}
      </button>
      <div className="xs muted" style={{ textAlign: "center" }}>
        {last ? <>Last sync {ago(last.started_at)}{last.status !== "ok" && last.status !== "running" && <> · <span style={{ color: "var(--warn)" }}>{last.status}</span></>}</> : "Not synced yet"}
      </div>
    </div>
  );
}

export default function App() {
  const [locked, setLocked] = useState(false);
  useEffect(() => {
    const on = () => setLocked(true);
    window.addEventListener("routepass:unauthorized", on);
    return () => window.removeEventListener("routepass:unauthorized", on);
  }, []);
  if (locked) return <TokenGate />;
  return (
    <div className="app">
      <aside className="sidebar">
        <Link to="/" className="brand"><Logo />RoutePass</Link>
        <nav className="nav stack" style={{ gap: 2 }}>
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}><Icon size={19} />{label}</NavLink>
          ))}
        </nav>
        <div className="sidebar-foot"><SyncButton /></div>
      </aside>
      <header className="topbar">
        <Link to="/" className="brand"><Logo size={26} />RoutePass</Link>
        <SyncButton compact />
      </header>
      <main className="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/activities" element={<Activities />} />
          <Route path="/activities/:id" element={<ActivityPage />} />
          <Route path="/insights" element={<Insights />} />
          <Route path="/insights/:tab" element={<Insights />} />
          <Route path="/sync" element={<SyncPage />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<div className="empty"><h3>Not found</h3></div>} />
        </Routes>
      </main>
      <nav className="bottom-nav" aria-label="Main">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end}>
            <span className="tab-ico"><Icon size={21} /></span>
            {label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
