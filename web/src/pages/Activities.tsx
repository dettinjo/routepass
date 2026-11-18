import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { RouteThumb } from "../components/charts";
import { IconLeft, IconLock, IconRight } from "../components/icons";
import { Card, Empty, ProviderBadges, Seg, Skeleton, SportDot, useToast } from "../components/ui";
import { TripView } from "../components/TripView";
import { api } from "../lib/api";
import { familyColor } from "../lib/colors";
import { activityDate, duration, int, km, speed } from "../lib/format";
import { decodePolyline } from "../lib/polyline";
import type { ActivityRow } from "../lib/types";
import { FamilyChips } from "./Dashboard";

const COLUMNS: { key: string; label: string; sort?: string; right?: boolean }[] = [
  { key: "name", label: "Activity", sort: "name" },
  { key: "date", label: "Date", sort: "date" },
  { key: "distance", label: "Distance", sort: "distance", right: true },
  { key: "duration", label: "Time", sort: "duration", right: true },
  { key: "elevation", label: "Elev.", sort: "elevation", right: true },
  { key: "speed", label: "Speed / pace", sort: "speed", right: true },
  { key: "hr", label: "HR", sort: "hr", right: true },
  { key: "power", label: "Power", sort: "power", right: true },
  { key: "load", label: "Load", sort: "load", right: true },
  { key: "platforms", label: "Platforms" },
];

export default function Activities() {
  const [sp, setSp] = useSearchParams();
  const nav = useNavigate();
  const get = (k: string) => sp.get(k) || "";
  const families = sp.getAll("family");
  const page = Number(sp.get("page") || 1);
  const sort = get("sort") || "date";
  const order = get("order") || "desc";
  const [q, setQ] = useState(get("q"));
  const [selected, setSelected] = useState<number[]>([]);
  const [trip, setTrip] = useState(false);
  const toast = useToast();
  const qc = useQueryClient();
  const toggle = (id: number) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  const bulk = useMutation({
    mutationFn: (direction: string) => api("/activities/bulk-sync", { method: "POST", body: { activity_ids: selected, direction } }),
    onSuccess: (r: any) => {
      const skipped = Object.keys(r.not_eligible).length;
      toast(`${r.queued} copies started${r.skipped_by_rules ? `, ${r.skipped_by_rules} skipped by rules` : ""}${skipped ? `, ${skipped} not eligible (already there / no GPS)` : ""}`);
      setSelected([]);
      qc.invalidateQueries({ queryKey: ["jobs"] });
      window.setTimeout(() => qc.invalidateQueries({ queryKey: ["activities"] }), 8000);
    },
    onError: (e: Error) => toast(e.message, true),
  });

  const update = (patch: Record<string, string | string[] | null>) => {
    const next = new URLSearchParams(sp);
    for (const [k, v] of Object.entries(patch)) {
      next.delete(k);
      if (Array.isArray(v)) v.forEach((x) => next.append(k, x));
      else if (v) next.set(k, v);
    }
    if (!("page" in patch)) next.delete("page");
    setSp(next, { replace: true });
  };

  useEffect(() => {
    const t = setTimeout(() => q !== get("q") && update({ q }), 300);
    return () => clearTimeout(t);
  }, [q]); // eslint-disable-line react-hooks/exhaustive-deps

  const params = {
    q: get("q"), family: families, presence: get("presence"), start: get("start"), end: get("end"),
    min_km: get("min_km"), max_km: get("max_km"), sort, order, page, per_page: 50,
  };
  const { data, isLoading, isFetching } = useQuery<{ items: ActivityRow[]; total: number; per_page: number }>({
    queryKey: ["activities", params],
    queryFn: () => api("/activities", { params }),
    placeholderData: keepPreviousData,
  });
  const pages = data ? Math.max(1, Math.ceil(data.total / data.per_page)) : 1;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Activities</h1>
          <div className="sub">{data ? `${int(data.total)} activities` : " "} — every activity once, wherever it was recorded</div>
        </div>
      </div>

      <Card>
        <div className="stack">
          <div className="row" style={{ gap: 12 }}>
            <input placeholder="Search names…" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 220 }} />
            <label className="row small secondary" style={{ gap: 6 }}>From <input type="date" value={get("start")} onChange={(e) => update({ start: e.target.value })} /></label>
            <label className="row small secondary" style={{ gap: 6 }}>To <input type="date" value={get("end")} onChange={(e) => update({ end: e.target.value })} /></label>
            <label className="row small secondary" style={{ gap: 6 }}>km
              <input type="number" placeholder="min" value={get("min_km")} onChange={(e) => update({ min_km: e.target.value })} style={{ width: 70 }} />
              <input type="number" placeholder="max" value={get("max_km")} onChange={(e) => update({ max_km: e.target.value })} style={{ width: 70 }} />
            </label>
            <Seg
              value={(get("presence") || "all") as string}
              options={[
                { value: "all", label: "All" }, { value: "both", label: "On both" }, { value: "strava_only", label: "Strava only" },
                { value: "komoot_only", label: "Komoot only" }, { value: "synced", label: "Synced copies" },
              ]}
              onChange={(v) => update({ presence: v === "all" ? null : v })}
            />
          </div>
          <FamilyChips value={families} onChange={(v) => update({ family: v })} />
        </div>
      </Card>

      <Card flush className="mt16">
        {isLoading ? <div style={{ padding: 16 }}><Skeleton h={400} /></div> : !data?.items.length ? (
          <Empty title="No activities match">Adjust the filters, or connect providers in Settings.</Empty>
        ) : (
          <div className="table-wrap" style={{ opacity: isFetching ? 0.7 : 1 }}>
            <table>
              <thead>
                <tr>
                  <th style={{ width: 32 }}>
                    <input type="checkbox" aria-label="Select page" checked={data.items.length > 0 && data.items.every((a) => selected.includes(a.id))}
                      onChange={(e) => setSelected(e.target.checked ? [...new Set([...selected, ...data.items.map((a) => a.id)])] : selected.filter((id) => !data.items.some((a) => a.id === id)))} />
                  </th>
                  <th style={{ width: 52 }} />
                  {COLUMNS.map((c) => (
                    <th key={c.key} className={`${c.sort ? "sortable" : ""} ${c.right ? "r" : ""}`}
                      onClick={() => c.sort && update({ sort: c.sort, order: sort === c.sort && order === "desc" ? "asc" : "desc" })}>
                      {c.label}{sort === c.sort && (order === "desc" ? " ↓" : " ↑")}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.items.map((a) => (
                  <tr key={a.id} className="click" onClick={() => nav(`/activities/${a.id}`)}>
                    <td onClick={(e) => e.stopPropagation()}><input type="checkbox" aria-label={`Select ${a.name}`} checked={selected.includes(a.id)} onChange={() => toggle(a.id)} /></td>
                    <td><RouteThumb points={a.polyline ? decodePolyline(a.polyline) : []} color={familyColor(a.family)} /></td>
                    <td>
                      <div className="name-cell"><span className="t">{a.name}</span>{a.sync_locked && <IconLock width={13} height={13} className="muted" />}</div>
                      <div className="small muted row" style={{ gap: 6 }}>
                        <SportDot family={a.family} />{a.sport_label}{a.trainer && " · indoor"}{a.commute && " · commute"}
                      </div>
                    </td>
                    <td className="small secondary" style={{ whiteSpace: "nowrap" }}>{activityDate(a)}</td>
                    <td className="r">{km(a.distance_m)}</td>
                    <td className="r">{duration(a.moving_time_s)}</td>
                    <td className="r">{int(a.elevation_gain_m)}</td>
                    <td className="r" style={{ whiteSpace: "nowrap" }}>{speed(a.avg_speed_ms, a.family)}</td>
                    <td className="r">{int(a.avg_hr)}</td>
                    <td className="r">{int(a.avg_power)}</td>
                    <td className="r">{int(a.load)}</td>
                    <td><ProviderBadges providers={a.providers} copies={a.copies} all /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && pages > 1 && (
          <div className="row between" style={{ padding: "10px 16px", borderTop: "1px solid var(--border)" }}>
            <span className="small muted">Page {page} of {pages}</span>
            <div className="row">
              <button className="sm" disabled={page <= 1} onClick={() => update({ page: String(page - 1) })}><IconLeft />Prev</button>
              <button className="sm" disabled={page >= pages} onClick={() => update({ page: String(page + 1) })}>Next<IconRight /></button>
            </div>
          </div>
        )}
      </Card>
      {selected.length > 0 && (
        <div className="bulk-bar" role="toolbar">
          <span style={{ fontWeight: 600 }}>{selected.length} selected</span>
          <button className="sm" disabled={bulk.isPending} onClick={() => bulk.mutate("strava_to_komoot")}>Copy to Komoot</button>
          <button className="sm" disabled={bulk.isPending} onClick={() => bulk.mutate("komoot_to_strava")}>Copy to Strava</button>
          <button className="sm" disabled={selected.length < 2} onClick={() => setTrip(true)} title="Combine the selected activities, e.g. the stages of a multi-day tour">Analyse as trip</button>
          <button className="sm ghost" onClick={() => setSelected([])}>Clear</button>
        </div>
      )}
      {trip && <TripView ids={selected} onClose={() => setTrip(false)} />}
      <p className="small muted mt8">
        <span className="prov strava" style={{ width: 14, height: 14, fontSize: 9 }}>S</span> Strava ·{" "}
        <span className="prov komoot" style={{ width: 14, height: 14, fontSize: 9 }}>K</span> Komoot · faded = copy created by RoutePass · grey = not on that platform
      </p>
    </>
  );
}
