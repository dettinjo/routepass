import { useCallback, useMemo, useState } from "react";
import { duration } from "../lib/format";
import type { TrackPoint } from "../lib/types";
import { LineChart } from "./charts";
import { MetricIcon, type MetricKey } from "./icons";

interface Channel {
  key: string;
  label: string;
  icon: MetricKey;
  color: string;
  values: (number | null)[];
  fmt: (v: number) => string;
  axis?: (v: number) => string;
  unit?: string;
  fill?: boolean;
  invert?: boolean;
  height: number;
}

const paceFmt = (v: number) => `${Math.floor(v)}:${String(Math.round((v % 1) * 60) % 60).padStart(2, "0")}`;

function percentile(values: number[], p: number): number {
  const s = [...values].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(s.length * p))];
}

/** Synced per-channel charts with one shared readout. Hover or drag anywhere on any chart. */
export function StreamStack({ points, family, onHover }: { points: TrackPoint[]; family: string; onHover: (i: number | null) => void }) {
  const [idx, setIdx] = useState<number | null>(null);
  const byDistance = points.some((p) => p.d != null && p.d > 0);
  const x = useMemo(() => points.map((p) => (byDistance ? (p.d ?? 0) / 1000 : p.t / 60)), [points, byDistance]);
  const xFormat = useCallback((v: number) => (byDistance ? `${v.toFixed(v < 10 ? 1 : 0)} km` : `${Math.round(v)} min`), [byDistance]);

  const channels = useMemo<Channel[]>(() => {
    const foot = family === "run" || family === "walk";
    let speed: (number | null)[];
    let speedCh: Pick<Channel, "label" | "fmt" | "invert" | "unit" | "axis">;
    if (foot) {
      // Pace in min/km; stops (< 2.2 km/h) and outliers are gaps, not 20:00 spikes.
      const raw = points.map((p) => (p.v != null && p.v > 0.6 ? 1000 / p.v / 60 : null));
      const valid = raw.filter((v): v is number => v != null);
      const cap = valid.length ? percentile(valid, 0.97) * 1.15 : Infinity;
      speed = raw.map((v) => (v != null && v <= cap ? v : null));
      speedCh = { label: "Pace", unit: "min/km", fmt: paceFmt, invert: true };
    } else {
      speed = points.map((p) => (p.v != null ? p.v * 3.6 : null));
      speedCh = { label: "Speed", unit: "km/h", fmt: (v) => `${v.toFixed(1)} km/h`, axis: (v) => `${Math.round(v)}` };
    }
    let gapPace: (number | null)[] | null = null;
    if (foot && points.some((p) => p.gap != null && p.gap > 0.6)) {
      const rawGap = points.map((p) => (p.gap != null && p.gap > 0.6 ? 1000 / p.gap / 60 : null));
      const validGap = rawGap.filter((v): v is number => v != null);
      const capGap = validGap.length ? percentile(validGap, 0.97) * 1.15 : Infinity;
      gapPace = rawGap.map((v) => (v != null && v <= capGap ? v : null));
    }
    const all: Channel[] = [
      { key: "ele", label: "Elevation", unit: "m", icon: "elevation", color: "var(--series-6)", values: points.map((p) => p.ele), fmt: (v) => `${Math.round(v)} m`, axis: (v) => `${Math.round(v)}`, fill: true, height: 150 },
      { key: "v", icon: "speed", color: "var(--series-1)", values: speed, height: 120, ...speedCh },
      ...(gapPace ? [{ key: "gap", label: "GAP", unit: "min/km", icon: "climb" as MetricKey, color: "var(--series-3)", values: gapPace, fmt: paceFmt, invert: true, height: 115 }] : []),
      { key: "hr", label: "Heart rate", unit: "bpm", icon: "hr", color: "var(--series-8)", values: points.map((p) => p.hr), fmt: (v) => `${Math.round(v)} bpm`, axis: (v) => `${Math.round(v)}`, height: 120 },
      { key: "pw", label: "Power", unit: "W", icon: "power", color: "var(--series-7)", values: points.map((p) => p.pw), fmt: (v) => `${Math.round(v)} W`, axis: (v) => `${Math.round(v)}`, height: 120 },
      { key: "cad", label: "Cadence", unit: "rpm", icon: "count", color: "var(--series-4)", values: points.map((p) => p.cad), fmt: (v) => `${Math.round(v)}`, height: 100 },
      { key: "temp", label: "Temperature", unit: "°C", icon: "temp", color: "var(--series-2)", values: points.map((p) => p.temp), fmt: (v) => `${v.toFixed(1)} °C`, axis: (v) => `${Math.round(v)}`, height: 100 },
    ];
    return all.filter((c) => c.values.some((v) => v != null && v !== 0));
  }, [points, family]);

  const series = useMemo(
    () => channels.map((c) => [{ label: c.label, color: c.color, values: c.values, fill: c.fill, width: 1.6 }]),
    [channels],
  );

  const onCursor = useCallback(
    (i: number | null) => {
      setIdx(i);
      onHover(i);
    },
    [onHover],
  );

  const p = idx != null ? points[idx] : null;
  return (
    <div>
      <div className="readout" aria-live="polite">
        <div>
          <div className="r-label"><MetricIcon.distance size={13} />{byDistance ? "Distance" : "Time"}</div>
          <div className="r-value">{p ? xFormat(x[idx!]) : "–"}</div>
        </div>
        <div>
          <div className="r-label"><MetricIcon.time size={13} />Elapsed</div>
          <div className="r-value">{p ? duration(p.t, true) : "–"}</div>
        </div>
        {channels.map((c) => {
          const Icon = MetricIcon[c.icon];
          const v = idx != null ? c.values[idx] : null;
          return (
            <div key={c.key}>
              <div className="r-label"><Icon size={13} />{c.label}</div>
              <div className="r-value" style={{ color: v != null ? c.color : undefined }}>{v != null ? c.fmt(v) : "–"}</div>
            </div>
          );
        })}
      </div>
      <p className="xs muted" style={{ margin: "-2px 0 4px", visibility: idx == null ? "visible" : "hidden" }}>Hover or drag across the charts — the map follows.</p>
      {channels.map((c, i) => {
        const Icon = MetricIcon[c.icon];
        return (
          <div key={c.key}>
            <div className="stream-title"><Icon size={14} />{c.label}{c.unit && <span className="muted" style={{ fontWeight: 500 }}>({c.unit})</span>}</div>
            <LineChart
              x={x}
              series={series[i]}
              height={c.height + (i === channels.length - 1 ? 24 : 0)}
              xFormat={xFormat}
              yFormat={c.fmt}
              yAxisFormat={c.axis}
              syncKey="streams"
              onCursor={onCursor}
              invertY={c.invert}
              showXAxis={i === channels.length - 1}
              tooltip={false}
            />
          </div>
        );
      })}
    </div>
  );
}
