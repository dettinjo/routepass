import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import { cssVar, SEQ } from "../lib/colors";

function useWidth<T extends HTMLElement>(): [React.RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.floor(e.contentRect.width)));
    ro.observe(ref.current);
    setW(Math.floor(ref.current.getBoundingClientRect().width));
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p;
}

interface TipState { x: number; y: number; content: ReactNode }

function Tooltip({ tip, width }: { tip: TipState | null; width: number }) {
  if (!tip) return null;
  const left = Math.min(Math.max(tip.x + 12, 0), Math.max(width - 190, 0));
  return <div className="tooltip" style={{ left, top: Math.max(tip.y - 10, 0) }}>{tip.content}</div>;
}

export interface Series { key: string; label: string; color: string }

/** Stacked vertical bars. One axis; 2px surface gaps between segments; hover tooltip per bar. */
export function StackedBars({
  data, series, height = 220, format, labelFor, onClick, tickEvery,
}: {
  data: { label: string; values: Record<string, number> }[];
  series: Series[];
  height?: number;
  format: (v: number) => string;
  labelFor?: (i: number) => string;
  onClick?: (i: number) => void;
  tickEvery?: number;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<TipState | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const padL = 44, padB = 22, padT = 8;
  const totals = data.map((d) => series.reduce((s, x) => s + (d.values[x.key] || 0), 0));
  const max = niceMax(Math.max(0, ...totals));
  const innerW = Math.max(width - padL, 10);
  const innerH = height - padB - padT;
  const slot = innerW / Math.max(data.length, 1);
  const barW = Math.max(Math.min(slot - 2, 40), 1);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * max);
  const every = tickEvery ?? Math.ceil(data.length / Math.max(1, Math.floor(innerW / 64)));
  return (
    <div className="chart" ref={ref} onMouseLeave={() => { setTip(null); setHover(null); }}>
      {width > 0 && (
        <svg width={width} height={height}>
          {ticks.map((t) => {
            const y = padT + innerH - (t / max) * innerH;
            return (
              <g key={t}>
                <line className="gridline" x1={padL} x2={width} y1={y} y2={y} />
                <text x={padL - 6} y={y + 4} textAnchor="end">{format(t)}</text>
              </g>
            );
          })}
          {data.map((d, i) => {
            let y = padT + innerH;
            const x = padL + i * slot + (slot - barW) / 2;
            const segs = series.filter((s) => (d.values[s.key] || 0) > 0);
            return (
              <g key={i} opacity={hover == null || hover === i ? 1 : 0.55}>
                {segs.map((s, si) => {
                  const h = ((d.values[s.key] || 0) / max) * innerH;
                  const gap = si < segs.length - 1 && h > 3 ? 2 : 0;
                  y -= h;
                  const top = si === segs.length - 1;
                  const r = Math.min(4, barW / 2, h);
                  const rectH = Math.max(h - gap, 0.5);
                  const path = top
                    ? `M${x},${y + rectH + gap} v${-(rectH - r)} q0,${-r} ${r},${-r} h${barW - 2 * r} q${r},0 ${r},${r} v${rectH - r} z`
                    : `M${x},${y + gap} h${barW} v${rectH} h${-barW} z`;
                  return <path key={s.key} d={path} fill={s.color} />;
                })}
                {(labelFor ? labelFor(i) !== "" : i % every === 0) && (
                  <text x={x + barW / 2} y={height - 6} textAnchor="middle">{labelFor ? labelFor(i) : d.label}</text>
                )}
                <rect
                  x={padL + i * slot} y={padT} width={slot} height={innerH} fill="transparent"
                  style={{ cursor: onClick ? "pointer" : "default" }}
                  onClick={() => onClick?.(i)}
                  onMouseMove={(e) => {
                    const box = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
                    setHover(i);
                    setTip({
                      x: e.clientX - box.left, y: e.clientY - box.top,
                      content: (
                        <>
                          <div className="tt-title">{d.label}</div>
                          {series.filter((s) => d.values[s.key]).map((s) => (
                            <div className="tt-row" key={s.key}><span><i className="sw" style={{ background: s.color }} />{s.label}</span><span>{format(d.values[s.key])}</span></div>
                          ))}
                          {segs.length > 1 && <div className="tt-row"><span>Total</span><span>{format(totals[i])}</span></div>}
                          {segs.length === 0 && <div className="muted">No activity</div>}
                        </>
                      ),
                    });
                  }}
                />
              </g>
            );
          })}
          <line x1={padL} x2={width} y1={padT + innerH} y2={padT + innerH} stroke="var(--border-strong)" />
        </svg>
      )}
      <Tooltip tip={tip} width={width} />
    </div>
  );
}

export function Legend({ items, line = false }: { items: Series[]; line?: boolean }) {
  return (
    <div className="legend">
      {items.map((s) => (
        <span className="item" key={s.key}><i className={line ? "ln" : "sw"} style={{ background: s.color }} />{s.label}</span>
      ))}
    </div>
  );
}

/** Horizontal bars with labels (zones, rankings). */
export function HBars({ rows, format, color = "var(--series-1)" }: {
  rows: { label: ReactNode; value: number; sub?: ReactNode; color?: string }[]; format: (v: number) => string; color?: string;
}) {
  const max = Math.max(...rows.map((r) => r.value), 1);
  return (
    <div className="stack" style={{ gap: 8 }}>
      {rows.map((r, i) => (
        <div key={i} style={{ display: "grid", gridTemplateColumns: "minmax(70px, 120px) 1fr 70px", gap: 10, alignItems: "center", fontSize: 12 }}>
          <span className="secondary">{r.label}</span>
          <div className="bar-track"><div className="bar-fill" style={{ width: `${(r.value / max) * 100}%`, background: r.color ?? color }} /></div>
          <span className="num" style={{ textAlign: "right" }}>{format(r.value)}{r.sub && <span className="muted"> {r.sub}</span>}</span>
        </div>
      ))}
    </div>
  );
}

function seqColor(v: number, max: number): string {
  if (!v) return SEQ[0];
  const idx = Math.min(SEQ.length - 1, 1 + Math.floor((v / max) * (SEQ.length - 1.0001)));
  return SEQ[idx];
}

/** GitHub-style year calendar. Sequential single hue; tooltip per day. */
export function CalendarHeatmap({ year, days, metric, format, onDay }: {
  year: number; days: Record<string, number>; metric: string; format: (v: number) => string; onDay?: (d: string) => void;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<TipState | null>(null);
  const start = new Date(Date.UTC(year, 0, 1));
  const offset = (start.getUTCDay() + 6) % 7;
  const total = (year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)) ? 366 : 365;
  const weeks = Math.ceil((total + offset) / 7);
  const cell = Math.max(Math.min(Math.floor((width - 30) / weeks) - 2, 18), 6);
  const step = cell + 2;
  const vals = Object.values(days);
  const max = vals.length ? [...vals].sort((a, b) => a - b)[Math.floor(vals.length * 0.95)] || Math.max(...vals) : 1;
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const cells = [];
  for (let i = 0; i < total; i++) {
    const d = new Date(start.getTime() + i * 86400000);
    const key = d.toISOString().slice(0, 10);
    const pos = i + offset;
    const v = days[key] || 0;
    cells.push(
      <rect key={key} x={30 + Math.floor(pos / 7) * step} y={16 + (pos % 7) * step} width={cell} height={cell} rx={2}
        fill={seqColor(v, max)} style={{ cursor: onDay && v ? "pointer" : "default" }}
        onClick={() => v && onDay?.(key)}
        onMouseMove={(e) => {
          const box = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
          setTip({ x: e.clientX - box.left, y: e.clientY - box.top, content: <><div className="tt-title">{d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" })}</div><div className="tt-row"><span>{metric}</span><span>{v ? format(v) : "–"}</span></div></> });
        }}
      />,
    );
  }
  return (
    <div className="chart" ref={ref} onMouseLeave={() => setTip(null)}>
      {width > 0 && (
        <svg width={width} height={16 + 7 * step + 4}>
          {months.map((m, i) => {
            const doy = Math.floor((Date.UTC(year, i, 1) - start.getTime()) / 86400000);
            return <text key={m} x={30 + Math.floor((doy + offset) / 7) * step} y={10}>{m}</text>;
          })}
          {["Mon", "", "Wed", "", "Fri", "", ""].map((d, i) => d && <text key={i} x={0} y={16 + i * step + cell - 1}>{d}</text>)}
          {cells}
        </svg>
      )}
      <Tooltip tip={tip} width={width} />
    </div>
  );
}

/** Weekday × hour grid (habits). */
export function GridHeatmap({ grid }: { grid: number[][] }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<TipState | null>(null);
  const max = Math.max(1, ...grid.flat());
  const cw = Math.max((width - 36) / 24 - 2, 4);
  const ch = 18;
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  return (
    <div className="chart" ref={ref} onMouseLeave={() => setTip(null)}>
      {width > 0 && (
        <svg width={width} height={7 * (ch + 2) + 20}>
          {grid.map((row, d) => (
            <g key={d}>
              <text x={0} y={d * (ch + 2) + 13}>{days[d]}</text>
              {row.map((v, h) => (
                <rect key={h} x={36 + h * (cw + 2)} y={d * (ch + 2)} width={cw} height={ch} rx={2} fill={seqColor(v, max)}
                  onMouseMove={(e) => {
                    const box = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
                    setTip({ x: e.clientX - box.left, y: e.clientY - box.top, content: <><div className="tt-title">{days[d]} {h}:00–{h + 1}:00</div><div className="tt-row"><span>Activities</span><span>{v}</span></div></> });
                  }} />
              ))}
            </g>
          ))}
          {[0, 6, 12, 18, 23].map((h) => <text key={h} x={36 + h * (cw + 2) + cw / 2} y={7 * (ch + 2) + 14} textAnchor="middle">{h}h</text>)}
        </svg>
      )}
      <Tooltip tip={tip} width={width} />
    </div>
  );
}

/** Thin wrapper around uPlot: crosshair + tooltip; colors resolved from CSS tokens. */
export function LineChart({
  x, series, height = 240, xTime = false, xFormat, yFormat, onCursor, syncKey, logX = false, fill = false, yRange,
}: {
  x: number[];
  series: { label: string; color: string; values: (number | null)[]; dash?: boolean; fill?: boolean; width?: number }[];
  height?: number;
  xTime?: boolean;
  xFormat?: (v: number) => string;
  yFormat?: (v: number) => string;
  onCursor?: (idx: number | null) => void;
  syncKey?: string;
  logX?: boolean;
  fill?: boolean;
  yRange?: [number | null, number | null];
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const plotRef = useRef<uPlot | null>(null);
  const [tip, setTip] = useState<TipState | null>(null);
  const cursorCb = useRef(onCursor);
  cursorCb.current = onCursor;

  const data = useMemo(() => [x, ...series.map((s) => s.values)] as uPlot.AlignedData, [x, series]);

  useEffect(() => {
    if (!ref.current || width === 0) return;
    const muted = cssVar("--text-muted");
    const grid = cssVar("--grid");
    const opts: uPlot.Options = {
      width,
      height,
      padding: [8, 8, 0, 0],
      cursor: {
        drag: { x: false, y: false },
        points: { size: 8, width: 2, stroke: cssVar("--surface-1") },
        sync: syncKey ? { key: syncKey } : undefined,
      },
      legend: { show: false },
      scales: {
        x: { time: xTime, distr: logX ? 3 : 1 },
        y: yRange ? { range: (_u, min, max) => [yRange[0] ?? min, yRange[1] ?? max] } : {},
      },
      axes: [
        { stroke: muted, grid: { show: false }, ticks: { stroke: grid }, font: "11px system-ui", values: xFormat ? (_u, vals) => vals.map((v) => xFormat(v)) : undefined },
        { stroke: muted, grid: { stroke: grid, width: 1 }, ticks: { show: false }, font: "11px system-ui", size: 62, values: yFormat ? (_u, vals) => vals.map((v) => yFormat(v)) : undefined },
      ],
      series: [
        {},
        ...series.map((s) => {
          const c = cssVar(s.color);
          return {
            label: s.label, stroke: c, width: s.width ?? 2, dash: s.dash ? [4, 4] : undefined,
            fill: s.fill || fill ? c + "26" : undefined, points: { show: false }, spanGaps: false,
          };
        }),
      ],
      hooks: {
        setCursor: [
          (u) => {
            const idx = u.cursor.idx;
            cursorCb.current?.(idx ?? null);
            if (idx == null || u.cursor.left == null || u.cursor.left < 0) { setTip(null); return; }
            const xv = u.data[0][idx];
            setTip({
              x: u.cursor.left + 62,
              y: (u.cursor.top ?? 0),
              content: (
                <>
                  <div className="tt-title">{xFormat ? xFormat(xv) : xTime ? new Date(xv * 1000).toLocaleDateString() : xv}</div>
                  {series.map((s, i) => {
                    const v = u.data[i + 1][idx];
                    return v == null ? null : (
                      <div className="tt-row" key={s.label}><span><i className="sw" style={{ background: s.color }} />{s.label}</span><span>{yFormat ? yFormat(v as number) : (v as number).toFixed(1)}</span></div>
                    );
                  })}
                </>
              ),
            });
          },
        ],
      },
    };
    plotRef.current?.destroy();
    plotRef.current = new uPlot(opts, data, ref.current);
    return () => { plotRef.current?.destroy(); plotRef.current = null; };
  }, [width, height, data, xTime, logX, syncKey]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="chart" ref={ref} style={{ minHeight: height }} onMouseLeave={() => { setTip(null); cursorCb.current?.(null); }}>
      <Tooltip tip={tip} width={width} />
    </div>
  );
}

/** Small route outline from an encoded polyline — used as list thumbnails. */
export function RouteThumb({ points, size = 36, color = "var(--accent)" }: { points: [number, number][]; size?: number; color?: string }) {
  if (points.length < 2) return <div style={{ width: size, height: size, borderRadius: 6, background: "var(--surface-2)" }} />;
  const lats = points.map((p) => p[0]), lngs = points.map((p) => p[1]);
  const minLat = Math.min(...lats), maxLat = Math.max(...lats), minLng = Math.min(...lngs), maxLng = Math.max(...lngs);
  const k = Math.cos(((minLat + maxLat) / 2) * Math.PI / 180);
  const w = (maxLng - minLng) * k || 1e-6, h = maxLat - minLat || 1e-6;
  const s = (size - 6) / Math.max(w, h);
  const ox = (size - w * s) / 2, oy = (size - h * s) / 2;
  const d = points.map((p, i) => `${i ? "L" : "M"}${(ox + (p[1] - minLng) * k * s).toFixed(1)},${(oy + (maxLat - p[0]) * s).toFixed(1)}`).join("");
  return (
    <svg width={size} height={size} style={{ background: "var(--surface-2)", borderRadius: 6, flex: "none" }}>
      <path d={d} fill="none" stroke={color} strokeWidth={1.6} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
