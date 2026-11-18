import { createContext, useCallback, useContext, useEffect, useState, type ComponentType, type ReactNode } from "react";
import { familyColor } from "../lib/colors";
import { BrandIcon, IconDone, IconInfo, IconPending, IconWarn, IconX, MetricIcon, SportIcon, type MetricKey, providerName } from "./icons";

export function Card({ title, hint, icon: Icon, actions, children, className = "", flush = false, id }: {
  title?: ReactNode; hint?: ReactNode; icon?: ComponentType<{ size?: number }>; actions?: ReactNode;
  children: ReactNode; className?: string; flush?: boolean; id?: string;
}) {
  return (
    <section className={`card ${flush ? "flush" : ""} ${className}`} id={id}>
      {(title || actions) && (
        <div className="card-head">
          <div className="title">
            {Icon && <span className="card-ico"><Icon size={17} /></span>}
            <div>
              {title && <h2>{title}</h2>}
              {hint && <div className="hint">{hint}</div>}
            </div>
          </div>
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, unit, delta, title, icon }: {
  label: string; value: ReactNode; unit?: string; delta?: number | null; title?: string; icon?: MetricKey;
}) {
  const Icon = icon ? MetricIcon[icon] : null;
  return (
    <div className="stat" title={title}>
      {Icon && <span className="s-ico"><Icon size={17} /></span>}
      <div className="s-body">
        <span className="label">{label}</span>
        <span className="value">{value}{unit && <small>{unit}</small>}</span>
        {delta != null && Number.isFinite(delta) && (
          <span className={`delta ${delta >= 0 ? "up" : "down"}`}>{delta >= 0 ? "▲" : "▼"} {Math.abs(delta).toFixed(0)}%</span>
        )}
      </div>
    </div>
  );
}

export function Seg<T extends string>({ value, options, onChange, block = false }: {
  value: T; options: { value: T; label: ReactNode }[]; onChange: (v: T) => void; block?: boolean;
}) {
  return (
    <div className={`seg ${block ? "block" : ""}`} role="group">
      {options.map((o) => (
        <button key={o.value} className={o.value === value ? "on" : ""} onClick={() => onChange(o.value)} type="button">{o.label}</button>
      ))}
    </div>
  );
}

export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: ReactNode }) {
  return (
    <label className="row nowrap" style={{ cursor: "pointer", gap: 10 }}>
      <span className="switch">
        <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} aria-label={typeof label === "string" ? label : undefined} />
        <span />
      </span>
      {label && <span>{label}</span>}
    </label>
  );
}

export function Tabs<T extends string>({ value, tabs, onChange }: { value: T; tabs: { value: T; label: ReactNode }[]; onChange: (v: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.value} role="tab" aria-selected={t.value === value} className={t.value === value ? "on" : ""} onClick={() => onChange(t.value)}>{t.label}</button>
      ))}
    </div>
  );
}

/** Strava + Komoot marks: full colour where the activity exists, faded where it is missing,
 *  a dot where the record is a copy made by RoutePass. */
export function ProviderBadges({ providers, copies = [], size = 15 }: { providers: string[]; copies?: string[]; size?: number }) {
  return (
    <span className="prov-set">
      {["strava", "komoot"].map((p) => {
        const has = providers.includes(p);
        const copy = copies.includes(p);
        return (
          <span key={p} className={`prov ${has ? "" : "off"} ${copy ? "copy" : ""}`}
            title={`${providerName(p)}: ${has ? (copy ? "copy created by RoutePass" : "original") : "not there"}`}>
            <BrandIcon provider={p} size={size} />
          </span>
        );
      })}
    </span>
  );
}

export function SportBadge({ sport, family, size = 42 }: { sport: string; family: string; size?: number }) {
  const color = familyColor(family);
  return (
    <span className="sport-badge" style={{ width: size, height: size, background: `color-mix(in srgb, ${color} 16%, transparent)`, color }}>
      <SportIcon sport={sport} family={family} size={Math.round(size * 0.52)} />
    </span>
  );
}

export const SportDot = ({ family }: { family: string }) => (
  <span style={{ width: 9, height: 9, borderRadius: 3, background: familyColor(family), display: "inline-block", flex: "none" }} />
);

export function Empty({ title, children, icon: Icon }: { title: string; children?: ReactNode; icon?: ComponentType<{ size?: number }> }) {
  return (
    <div className="empty">
      {Icon && <Icon size={28} />}
      <h3>{title}</h3>
      {children}
    </div>
  );
}

export function Callout({ kind = "info", children }: { kind?: "info" | "warn" | "bad" | "good"; children: ReactNode }) {
  const Icon = kind === "warn" || kind === "bad" ? IconWarn : kind === "good" ? IconDone : IconInfo;
  return <div className={`callout ${kind}`}><Icon size={18} /><div>{children}</div></div>;
}

export function Modal({ title, onClose, children, footer }: { title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = ""; };
  }, [onClose]);
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true">
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="ghost icon sm" onClick={onClose} aria-label="Close"><IconX /></button>
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
  const cls = { done: "good", ok: "good", finished: "good", failed: "bad", error: "bad", queued: "info", running: "info", partial: "warn", skipped: "" }[status] ?? "";
  const Icon = status === "done" || status === "ok" ? IconDone : status === "failed" || status === "error" ? IconWarn : IconPending;
  return <span className={`badge ${cls}`}><Icon size={13} />{status}</span>;
}

const ToastCtx = createContext<(msg: string, bad?: boolean) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<{ msg: string; bad: boolean } | null>(null);
  const show = useCallback((msg: string, bad = false) => {
    setToast({ msg, bad });
    window.setTimeout(() => setToast(null), bad ? 6000 : 3500);
  }, []);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      {toast && <div className={`toast ${toast.bad ? "bad" : ""}`} role="status">{toast.msg}</div>}
    </ToastCtx.Provider>
  );
}
