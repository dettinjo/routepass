import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { duration, hours, int, km } from "../lib/format";
import { usePrefs } from "../lib/hooks";
import { HBars, Legend, LineChart, StackedBars } from "./charts";
import { ICON, IconGear, IconInfo, IconMap, MetricIcon } from "./icons";
import { TilesMap } from "./maps";
import { Card, Empty, Seg, Skeleton, SportDot, Stat, useToast } from "./ui";

// Zones are an amount of intensity: one hue from light to dark (never status red for "hard").
const ZONE_COLORS = ["var(--seq-1)", "var(--seq-2)", "var(--seq-3)", "var(--seq-4)", "var(--seq-5)", "var(--seq-6)", "var(--seq-6)"];

interface ZoneBlock { seconds: number[]; total_s: number; polarization: { low_pct: number; threshold_pct: number; high_pct: number }; buckets: { start: string; values: Record<string, number> }[] }

function Polarization({ p }: { p: ZoneBlock["polarization"] }) {
  const parts = [
    { key: "low", label: "Easy", value: p.low_pct, color: "var(--seq-1)" },
    { key: "mid", label: "Threshold", value: p.threshold_pct, color: "var(--seq-4)" },
    { key: "high", label: "Hard", value: p.high_pct, color: "var(--seq-6)" },
  ];
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="progress" style={{ height: 14 }}>
        {parts.map((x) => <span key={x.key} style={{ width: `${x.value}%`, background: x.color }} title={`${x.label} ${x.value}%`} />)}
      </div>
      <Legend items={parts.map((x) => ({ key: x.key, label: `${x.label} ${x.value.toFixed(0)}%`, color: x.color }))} />
    </div>
  );
}

function ZoneCard({ title, block, zones, grain, onGrain }: { title: string; block: ZoneBlock; zones: number; grain: "month" | "year"; onGrain: (g: "month" | "year") => void }) {
  const series = Array.from({ length: zones }, (_, i) => ({ key: `Z${i + 1}`, label: `Z${i + 1}`, color: ZONE_COLORS[Math.min(i + (zones === 5 ? 1 : 0), 6)] }));
  const bars = block.buckets.slice(-24).map((b) => ({
    label: new Date(b.start).toLocaleDateString(undefined, grain === "year" ? { year: "numeric" } : { month: "short", year: "numeric" }),
    values: b.values,
  }));
  return (
    <Card title={title} icon={title.startsWith("Heart") ? MetricIcon.hr : MetricIcon.power} hint={`${hours(block.total_s)} h with data`}
      info={<>Endurance training usually works best with about 80% easy, little threshold and some hard time. Zones come from your max heart rate and FTP (<Link to="/settings/profile">profile</Link>).</>}
      actions={<Seg value={grain} onChange={onGrain} options={[{ value: "month", label: "Per month" }, { value: "year", label: "Per year" }]} />}>
      <div className="stack gap16">
        <Polarization p={block.polarization} />
        <HBars format={(v) => duration(v)} rows={block.seconds.map((s, i) => ({ label: `Zone ${i + 1}`, value: s, color: series[i].color }))} />
        {bars.length > 1 && <StackedBars data={bars} series={series} format={(v) => `${hours(v)} h`} height={180} />}
      </div>
    </Card>
  );
}

export function ZonesTab({ families, start }: { families: string[]; start?: string }) {
  const [grain, setGrain] = useState<"month" | "year">("month");
  const zones = useQuery<{ hr: ZoneBlock; power: ZoneBlock }>({ queryKey: ["zones", families, grain, start], queryFn: () => api("/insights/zones", { params: { family: families, grain, start } }) });
  const eff = useQuery<any[]>({ queryKey: ["efficiency", families, start], queryFn: () => api("/insights/efficiency", { params: { family: families, start } }) });
  const chart = useMemo(() => {
    const rows = (eff.data || []).filter((r) => r.ef_speed != null || r.ef_power != null);
    if (rows.length < 2) return null;
    const usePower = rows.filter((r) => r.ef_power != null).length > rows.length / 2;
    return {
      usePower,
      x: rows.map((r) => new Date(r.date).getTime() / 1000),
      series: [{ label: usePower ? "Power per heartbeat" : "Speed per heartbeat", color: "var(--line-1)", values: rows.map((r) => (usePower ? r.ef_power : r.ef_speed)) }],
      dec: rows.filter((r) => r.decoupling_pct != null),
    };
  }, [eff.data]);
  if (!zones.data) return <Skeleton h={300} />;
  const hasHr = zones.data.hr.total_s > 0;
  const hasPw = zones.data.power.total_s > 0;
  return (
    <div className="stack gap16">
      {!hasHr && !hasPw ? <Empty title="No heart-rate or power recordings yet" icon={MetricIcon.hr}>Recordings from Strava (API or data export) carry heart rate; Komoot tracks do not.</Empty> : (
        <div className={`grid ${hasHr && hasPw ? "g2" : ""}`}>
          {hasHr && <ZoneCard title="Heart-rate zones" block={zones.data.hr} zones={5} grain={grain} onGrain={setGrain} />}
          {hasPw && <ZoneCard title="Power zones" block={zones.data.power} zones={7} grain={grain} onGrain={setGrain} />}
        </div>
      )}
      <Card title="Aerobic efficiency" icon={MetricIcon.speed} hint="Output per heartbeat over time — rising means fitter at the same effort">
        {chart ? (
          <>
            <LineChart x={chart.x} series={chart.series} xTime height={220} yFormat={(v) => v.toFixed(2)} />
            {chart.dec.length > 0 && (
              <p className="small muted mt8">
                Heart-rate drift (decoupling) on long steady efforts: median {(() => { const v = chart.dec.map((r) => r.decoupling_pct).sort((a, b) => a - b); return v[Math.floor(v.length / 2)].toFixed(1); })()} % — under 5 % means a solid aerobic base.
              </p>
            )}
          </>
        ) : <Empty title="Not enough activities with heart rate" />}
      </Card>
    </div>
  );
}

export function TilesTab({ families, start }: { families: string[]; start?: string }) {
  const { data } = useQuery<any>({ queryKey: ["tiles", families, start], queryFn: () => api("/insights/tiles", { params: { family: families, start } }) });
  if (!data) return <Skeleton h={500} />;
  if (!data.total_tiles) return <Empty title="No GPS tracks yet" icon={IconMap} />;
  const years = Object.entries(data.new_by_year as Record<string, number>);
  return (
    <div className="stack gap16">
      <Card>
        <div className="stats">
          <Stat icon="days" label="Tiles visited" value={int(data.total_tiles)} />
          <Stat icon="climb" label="Max square" value={`${data.max_square}×${data.max_square}`} />
          <Stat icon="count" label="Max cluster" value={int(data.max_cluster)} title="Tiles whose four neighbours are all visited, connected" />
          <Stat icon="distance" label="Cluster tiles" value={int(data.cluster_tiles)} />
        </div>
        <p className="xs muted mt8 row nowrap" style={{ gap: 6, alignItems: "flex-start" }}><IconInfo size={ICON.inline} />Explorer tiles are the ~1.5 km map squares (zoom 14) your activities passed through — a game of filling in the map.</p>
      </Card>
      <Card title="Tile map" icon={IconMap} hint="Filled = cluster, dashed = max square">
        <TilesMap tiles={data.tiles} square={data.square_bounds} />
      </Card>
      {years.length > 1 && (
        <Card title="New tiles per year" icon={MetricIcon.count}>
          <StackedBars data={years.map(([y, n]) => ({ label: y, values: { n } }))} series={[{ key: "n", label: "New tiles", color: "var(--text-secondary)" }]} format={(v) => int(v)} height={180} />
        </Card>
      )}
    </div>
  );
}

export function GearTab({ families, start }: { families?: string[]; start?: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: prefs } = usePrefs();
  const { data } = useQuery<{ gear: any[]; devices: any[] }>({ queryKey: ["gear", families, start], queryFn: () => api("/insights/gear", { params: { family: families, start } }) });
  const save = useMutation({
    mutationFn: (gear_targets: Record<string, unknown>) => api("/settings", { method: "PATCH", body: { gear_targets } }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["gear"] }); qc.invalidateQueries({ queryKey: ["prefs"] }); toast("Saved"); },
  });
  const [editing, setEditing] = useState<string | null>(null);
  const [label, setLabel] = useState("");
  const [service, setService] = useState("");
  if (!data) return <Skeleton h={300} />;
  if (!data.gear.length && !data.devices.length) {
    return <Empty title="No gear recorded" icon={IconGear}>Gear comes from Strava (API or data export), where bikes and shoes are assigned to activities.</Empty>;
  }
  const row = (g: any, editable: boolean) => (
    <div key={g.key} className="item" style={{ cursor: "default", alignItems: "flex-start" }}>
      <span className="card-ico"><IconGear size={ICON.header} /></span>
      <div className="main-col">
        <b className="small">{g.label}{g.label !== g.key && <span className="muted" style={{ fontWeight: 400 }}> · {g.key}</span>}</b>
        <div className="metrics">
          <span><MetricIcon.distance size={ICON.inline} />{km(g.distance_m, 0)} km</span>
          <span><MetricIcon.time size={ICON.inline} />{hours(g.moving_time_s)} h</span>
          <span><MetricIcon.elevation size={ICON.inline} />{int(g.elevation_m)} m</span>
          <span className="extra">{g.count} activities · {g.first_date} – {g.last_date}</span>
        </div>
        <div className="row" style={{ gap: 4 }}>{g.families.map((f: string) => <SportDot key={f} family={f} />)}</div>
        {g.service_km && (
          <div className="stack mt8" style={{ gap: 4 }}>
            <div className="progress"><span style={{ width: `${Math.min(100, (g.distance_m / 1000 / g.service_km) * 100)}%`, background: g.service_due ? "var(--bad)" : "var(--good)" }} /></div>
            <span className="xs" style={{ color: g.service_due ? "var(--bad)" : "var(--text-muted)" }}>{g.service_due ? "Service due" : `${int(g.remaining_km)} km to service (every ${int(g.service_km)} km)`}</span>
          </div>
        )}
        {editable && editing === g.key && (
          <div className="fields mt8">
            <label className="field">Name<input value={label} onChange={(e) => setLabel(e.target.value)} /></label>
            <label className="field">Service every (km)<input type="number" inputMode="numeric" value={service} onChange={(e) => setService(e.target.value)} /></label>
            <div className="row">
              <button className="sm primary" onClick={() => { save.mutate({ ...(prefs?.gear_targets ?? {}), [g.key]: { label: label || undefined, service_km: service ? Number(service) : null } }); setEditing(null); }}>Save</button>
              <button className="sm ghost" onClick={() => setEditing(null)}>Cancel</button>
            </div>
          </div>
        )}
      </div>
      {editable && editing !== g.key && <button className="sm ghost" onClick={() => { setEditing(g.key); setLabel(g.label === g.key ? "" : g.label); setService(g.service_km ? String(g.service_km) : ""); }}>Edit</button>}
    </div>
  );
  return (
    <div className="stack gap16">
      {data.gear.length > 0 && <Card title="Bikes & shoes" icon={IconGear} hint="Give gear a name and a service interval" flush><div className="list">{data.gear.map((g) => row(g, true))}</div></Card>}
      {data.devices.length > 0 && <Card title="Recording devices" icon={MetricIcon.time} flush><div className="list">{data.devices.map((g) => row(g, false))}</div></Card>}
    </div>
  );
}
