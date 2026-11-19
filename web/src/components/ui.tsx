import { createContext, useCallback, useContext, useEffect, useState, type ComponentType, type ReactNode } from "react";
import { familyColor } from "../lib/colors";
import { BrandIcon, ICON, IconAttention, IconChecksI, IconDone, IconInfo, IconMore, IconPending, IconRight, IconStatusFailed, IconStatusSkipped, IconTrendDown, IconTrendUp, IconWarn, IconX, MetricIcon, SportIcon, type MetricKey, providerName } from "./icons";

export function Card({ title, hint, icon: Icon, actions, children, className = "", flush = false, id, info }: {
  title?: ReactNode; hint?: ReactNode; icon?: ComponentType<{ size?: number }>; actions?: ReactNode;
  children: ReactNode; className?: string; flush?: boolean; id?: string; info?: ReactNode;
}) {
  return (
    <section className={`card ${flush ? "flush" : ""} ${className}`} id={id}>
      {(title || actions) && (
        <div className="card-head">
          <div className="title">
            {Icon && <span className="card-ico"><Icon size={ICON.header} /></span>}
            <div>
              {title && <h2 className="row nowrap" style={{ gap: 6 }}>{title}{info && <InfoTip>{info}</InfoTip>}</h2>}
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

export function Stat({ label, value, unit, delta, title, icon, info }: {
  label: string; value: ReactNode; unit?: string; delta?: number | null; title?: string; icon?: MetricKey; info?: ReactNode;
}) {
  const Icon = icon ? MetricIcon[icon] : null;
  return (
    <div className="stat" title={title}>
      {Icon && <span className="s-ico"><Icon size={ICON.header} /></span>}
      <div className="s-body">
        <span className="label row nowrap" style={{ gap: 4 }}>{label}{info && <InfoTip>{info}</InfoTip>}</span>
        <span className="value">{value}{unit && <small>{unit}</small>}</span>
        {delta != null && Number.isFinite(delta) && (
          // A change in volume is not good or bad by itself: direction icon + sign, no status colour.
          <span className="delta">{delta >= 0 ? <IconTrendUp size={ICON.inline} /> : <IconTrendDown size={ICON.inline} />}{delta >= 0 ? "+" : "−"}{Math.abs(delta).toFixed(0)}%</span>
        )}
      </div>
    </div>
  );
}

/** Small ⓘ that explains a term on hover / focus / tap. */
export function InfoTip({ children, label = "What does this mean?" }: { children: ReactNode; label?: string }) {
  return (
    <span className="tip" tabIndex={0} role="button" aria-label={label} onClick={(e) => e.stopPropagation()}>
      <IconInfo size={ICON.inline} />
      <span className="tip-pop" role="tooltip">{children}</span>
    </span>
  );
}

export type Severity = "info" | "warn" | "bad";
const SEVERITY_RANK: Record<Severity, number> = { info: 0, warn: 1, bad: 2 };
const SeverityIcon = ({ level, size = ICON.header }: { level: Severity; size?: number }) =>
  level === "info" ? <IconInfo size={size} className="att-ico info" /> : level === "bad" ? <IconStatusFailed size={size} className="att-ico bad" /> : <IconWarn size={size} className="att-ico warn" />;

/** One alert block per page: coloured by its most serious item, a count, and one action per item. */
export function Attention({ items, title, defaultOpen }: {
  items: { level: Severity; text: ReactNode; action?: ReactNode }[]; title?: (n: number) => ReactNode; defaultOpen?: boolean;
}) {
  if (!items.length) return null;
  const top = items.reduce<Severity>((m, i) => (SEVERITY_RANK[i.level] > SEVERITY_RANK[m] ? i.level : m), "info");
  const label = title ? title(items.length) : items.length === 1 ? "1 thing needs attention" : `${items.length} things need attention`;
  return (
    <details className={`attention ${top}`} open={defaultOpen ?? (items.length <= 2 || top !== "info")}>
      <summary><SeverityIcon level={top} />{label}<IconRight size={ICON.button} className="chev" /></summary>
      <ul>
        {items.map((i, k) => (
          <li key={k}>
            <SeverityIcon level={i.level} size={ICON.button} />
            <div className="grow"><span>{i.text}</span>{i.action}</div>
          </li>
        ))}
      </ul>
    </details>
  );
}

/** Progress toward a target. `expected` marks where you should be by today; only the gap behind it is coloured. */
export function ProgressBar({ value, max, expected, color, label, right }: {
  value: number; max: number; expected?: number | null; color?: string; label?: ReactNode; right?: ReactNode;
}) {
  const pct = (v: number) => Math.max(0, Math.min(100, max > 0 ? (v / max) * 100 : 0));
  const v = pct(value);
  const e = expected != null ? pct(expected) : null;
  return (
    <div>
      <div className="pbar" role="progressbar" aria-valuenow={Math.round(v)} aria-valuemin={0} aria-valuemax={100}
        style={{ "--pbar-color": color ?? "var(--text-secondary)" } as React.CSSProperties}>
        <span className="fill" style={{ width: `${v}%` }} />
        {e != null && e > v + 0.5 && <span className="behind" style={{ left: `${v}%`, width: `${e - v}%` }} />}
        {e != null && <span className="tick" style={{ left: `${e}%` }} title="Where you should be by today" />}
      </div>
      {(label || right) && <div className="pbar-meta"><span>{label}</span><span>{right}</span></div>}
    </div>
  );
}

/** ⋯ overflow menu for secondary and destructive actions. Closes after a choice. */
export function Menu({ children, label = "More actions" }: { children: ReactNode; label?: string }) {
  return (
    <details className="menu" onClick={(e) => {
      const t = e.target as HTMLElement;
      if (t.closest("button, a") && !t.closest("summary")) (e.currentTarget as HTMLDetailsElement).open = false;
    }}>
      <summary aria-label={label} title={label}><IconMore size={ICON.header} /></summary>
      <div className="menu-pop">{children}</div>
    </details>
  );
}

/** "Saved ✓" marker for settings that save as you type / change. */
export function SavedMark({ at }: { at: number | null }) {
  const [show, setShow] = useState(false);
  useEffect(() => {
    if (!at) return;
    setShow(true);
    const t = window.setTimeout(() => setShow(false), 2500);
    return () => window.clearTimeout(t);
  }, [at]);
  return show ? <span className="saved-mark" role="status"><IconChecksI size={ICON.inline} />Saved</span> : null;
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
  return <div className={`callout ${kind}`}><Icon size={ICON.header} /><div>{children}</div></div>;
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
          <button className="ghost icon sm" onClick={onClose} aria-label="Close"><IconX size={ICON.header} /></button>
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

/** Status = icon + word, coloured by severity (red only when something is broken). */
export function StatusBadge({ status, label }: { status: string; label?: string }) {
  const cls = { done: "good", ok: "good", finished: "good", completed: "good", failed: "bad", error: "bad", queued: "info", running: "info", partial: "warn", missed: "warn", skipped: "neutral", planned: "neutral", idle: "neutral" }[status] ?? "neutral";
  const Icon = ["done", "ok", "finished", "completed"].includes(status) ? IconDone
    : status === "failed" || status === "error" ? IconStatusFailed
      : status === "partial" || status === "missed" ? IconAttention
        : status === "skipped" ? IconStatusSkipped
          : status === "running" ? IconPending : IconPending;
  return <span className={`badge ${cls}`}><Icon size={ICON.inline} className={status === "running" ? "spin" : undefined} />{label ?? status}</span>;
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
