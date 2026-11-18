import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { familyColor } from "../lib/colors";
import { IconX } from "./icons";

export function Card({ title, hint, actions, children, className = "", flush = false }: {
  title?: ReactNode; hint?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; flush?: boolean;
}) {
  return (
    <section className={`card ${flush ? "flush" : ""} ${className}`}>
      {(title || actions) && (
        <div className="card-head" style={flush ? { padding: "16px 16px 0" } : undefined}>
          <div>
            {title && <h2>{title}</h2>}
            {hint && <div className="hint">{hint}</div>}
          </div>
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, unit, delta, title }: { label: string; value: ReactNode; unit?: string; delta?: number | null; title?: string }) {
  return (
    <div className="stat" title={title}>
      <span className="label">{label}</span>
      <span className="value">
        {value}
        {unit && <small>{unit}</small>}
      </span>
      {delta != null && Number.isFinite(delta) && (
        <span className={`delta ${delta >= 0 ? "up" : "down"}`}>
          {delta >= 0 ? "▲" : "▼"} {Math.abs(delta).toFixed(0)}% vs prev.
        </span>
      )}
    </div>
  );
}

export function Seg<T extends string>({ value, options, onChange }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="seg" role="group">
      {options.map((o) => (
        <button key={o.value} className={o.value === value ? "on" : ""} onClick={() => onChange(o.value)} type="button">
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <label className="row" style={{ cursor: "pointer", gap: 10 }}>
      <span className="switch">
        <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} aria-label={label} />
        <span />
      </span>
      {label && <span>{label}</span>}
    </label>
  );
}

export function Tabs<T extends string>({ value, tabs, onChange }: { value: T; tabs: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.value} role="tab" className={t.value === value ? "on" : ""} onClick={() => onChange(t.value)}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function ProviderBadges({ providers, copies = [], all = false }: { providers: string[]; copies?: string[]; all?: boolean }) {
  const list = all ? ["strava", "komoot"] : providers;
  return (
    <span className="row" style={{ gap: 3, flexWrap: "nowrap" }}>
      {list.map((p) => {
        const has = providers.includes(p);
        const copy = copies.includes(p);
        return (
          <span
            key={p}
            className={`prov ${has ? p : "off"} ${copy ? "copy" : ""}`}
            title={`${p === "strava" ? "Strava" : "Komoot"}: ${has ? (copy ? "copy created by RoutePass" : "original") : "missing"}`}
          >
            {p === "strava" ? "S" : "K"}
          </span>
        );
      })}
    </span>
  );
}

export const SportDot = ({ family }: { family: string }) => <span className="sport-dot" style={{ background: familyColor(family) }} />;

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

export function Modal({ title, onClose, children, footer }: { title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true">
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="ghost sm" onClick={onClose} aria-label="Close"><IconX /></button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

export function Skeleton({ h = 120 }: { h?: number }) {
  return <div className="skeleton" style={{ height: h }} />;
}

export function StatusBadge({ status }: { status: string }) {
  const cls = { done: "good", ok: "good", failed: "bad", error: "bad", queued: "info", running: "info", partial: "warn", skipped: "" }[status] ?? "";
  return <span className={`badge ${cls}`}>{status}</span>;
}

const ToastCtx = createContext<(msg: string, bad?: boolean) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<{ msg: string; bad: boolean } | null>(null);
  const show = useCallback((msg: string, bad = false) => {
    setToast({ msg, bad });
    window.setTimeout(() => setToast(null), bad ? 6000 : 3000);
  }, []);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      {toast && <div className={`toast ${toast.bad ? "bad" : ""}`} role="status">{toast.msg}</div>}
    </ToastCtx.Provider>
  );
}
