import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { TripView } from "../components/TripView";
import { BrandIcon, IconDownload, IconFilter, IconLeft, IconRight, IconSearch, IconSelect, IconSync, IconX, MetricIcon } from "../components/icons";
import { ActivityItem, FamilyChips } from "../components/shared";
import { Card, Empty, Modal, Seg, Skeleton, useToast } from "../components/ui";
import { api, qs } from "../lib/api";
import { FAMILY_LABEL } from "../lib/colors";
import { int } from "../lib/format";
import type { ActivityRow } from "../lib/types";

const SORTS = [
  { value: "date", label: "Newest" },
  { value: "distance", label: "Longest" },
  { value: "elevation", label: "Most climbing" },
  { value: "duration", label: "Longest time" },
  { value: "speed", label: "Fastest" },
  { value: "load", label: "Hardest (load)" },
  { value: "name", label: "Name" },
];
const PRESENCE: Record<string, string> = {
  both: "On both", strava_only: "Only on Strava", komoot_only: "Only on Komoot", synced: "Copied by RoutePass",
};

export default function Activities() {
  const [sp, setSp] = useSearchParams();
  const get = (k: string) => sp.get(k) || "";
  const families = sp.getAll("family");
  const page = Number(sp.get("page") || 1);
  const sort = get("sort") || "date";
  const order = get("order") || (sort === "name" ? "asc" : "desc");
  const [q, setQ] = useState(get("q"));
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<number[]>([]);
  const [trip, setTrip] = useState(false);
  const toast = useToast();
  const qc = useQueryClient();

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
    min_km: get("min_km"), max_km: get("max_km"), sort, order, page, per_page: 40,
  };
  const { data, isLoading, isFetching } = useQuery<{ items: ActivityRow[]; total: number; per_page: number }>({
    queryKey: ["activities", params],
    queryFn: () => api("/activities", { params }),
    placeholderData: keepPreviousData,
  });
  const pages = data ? Math.max(1, Math.ceil(data.total / data.per_page)) : 1;

  const toggle = (id: number) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  const bulk = useMutation({
    mutationFn: (direction: string) => api("/activities/bulk-sync", { method: "POST", body: { activity_ids: selected, direction } }),
    onSuccess: (r: any) => {
      const skipped = Object.keys(r.not_eligible).length;
      toast(`${r.queued} copies started${r.skipped_by_rules ? `, ${r.skipped_by_rules} skipped by rules` : ""}${skipped ? `, ${skipped} already there or without GPS` : ""}`);
      setSelected([]);
      setSelecting(false);
      qc.invalidateQueries({ queryKey: ["jobs"] });
      window.setTimeout(() => qc.invalidateQueries({ queryKey: ["activities"] }), 8000);
    },
    onError: (e: Error) => toast(e.message, true),
  });

  const active: { key: string; label: string; clear: Record<string, null> }[] = [];
  if (get("start") || get("end")) active.push({ key: "date", label: `${get("start") || "…"} → ${get("end") || "…"}`, clear: { start: null, end: null } });
  if (get("min_km") || get("max_km")) active.push({ key: "km", label: `${get("min_km") || 0}–${get("max_km") || "∞"} km`, clear: { min_km: null, max_km: null } });
  if (get("presence")) active.push({ key: "presence", label: PRESENCE[get("presence")] ?? get("presence"), clear: { presence: null } });
  families.forEach((f) => active.push({ key: f, label: FAMILY_LABEL[f], clear: {} }));
  const filterCount = active.length;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Activities</h1>
          <div className="sub">{data ? `${int(data.total)} activities` : " "} · each listed once, wherever it was recorded</div>
        </div>
        <div className="row nowrap">
          <a className="btn sm" href={`/api/v1/activities/export.csv${qs({ q: get("q"), family: families, presence: get("presence"), start: get("start"), end: get("end") })}`} title="Download the activities matching the filters as CSV">
            <IconDownload size={16} /><span className="hide-mobile">CSV</span>
          </a>
          <button className={selecting ? "primary sm" : "sm"} onClick={() => { setSelecting(!selecting); setSelected([]); }}>
            <IconSelect size={16} />{selecting ? "Done" : "Select"}
          </button>
        </div>
      </div>

      <div className="stack" style={{ gap: 10, marginBottom: 12 }}>
        <div className="row nowrap">
          <div className="search grow"><IconSearch size={17} /><input placeholder="Search activities" value={q} onChange={(e) => setQ(e.target.value)} type="search" /></div>
          <button className={filterCount ? "primary icon" : "icon"} onClick={() => setFiltersOpen(true)} aria-label="Filters" title="Filters">
            <IconFilter size={19} />
          </button>
          <select value={`${sort}:${order}`} onChange={(e) => { const [s, o] = e.target.value.split(":"); update({ sort: s, order: o }); }}
            style={{ width: 112, flex: "none", paddingRight: 4 }} aria-label="Sort">
            {SORTS.map((s) => <option key={s.value} value={`${s.value}:${s.value === "name" ? "asc" : "desc"}`}>{s.label}</option>)}
            {order !== (sort === "name" ? "asc" : "desc") && <option value={`${sort}:${order}`}>Custom</option>}
          </select>
        </div>
        {filterCount > 0 && (
          <div className="chips">
            {active.map((f) => (
              <button key={f.key} className="chip on removable"
                onClick={() => update(FAMILY_LABEL[f.key] ? { family: families.filter((x) => x !== f.key) } : f.clear)}>
                {f.label}<IconX size={14} />
              </button>
            ))}
            <button className="chip" onClick={() => update({ start: null, end: null, min_km: null, max_km: null, presence: null, family: [] })}>Clear all</button>
          </div>
        )}
      </div>

      <Card flush>
        {isLoading ? <div style={{ padding: 14 }}><Skeleton h={400} /></div> : !data?.items.length ? (
          <Empty title="No activities match" icon={IconSearch}>Change the filters, or connect your accounts in Settings.</Empty>
        ) : (
          <div className="list" style={{ opacity: isFetching ? 0.7 : 1 }}>
            {selecting && (
              <label className="item" style={{ cursor: "pointer" }}>
                <input type="checkbox" checked={data.items.every((a) => selected.includes(a.id))}
                  onChange={(e) => setSelected(e.target.checked ? [...new Set([...selected, ...data.items.map((a) => a.id)])] : selected.filter((id) => !data.items.some((a) => a.id === id)))} />
                <span className="small secondary">Select all on this page</span>
              </label>
            )}
            {data.items.map((a) => (
              <ActivityItem key={a.id} a={a} selectable={selecting} selected={selected.includes(a.id)} onToggle={toggle} />
            ))}
          </div>
        )}
        {data && pages > 1 && (
          <div className="row between" style={{ padding: "10px 14px", borderTop: "1px solid var(--border)" }}>
            <button className="sm" disabled={page <= 1} onClick={() => { update({ page: String(page - 1) }); window.scrollTo(0, 0); }}><IconLeft size={16} />Newer</button>
            <span className="small muted">{page} / {pages}</span>
            <button className="sm" disabled={page >= pages} onClick={() => { update({ page: String(page + 1) }); window.scrollTo(0, 0); }}>Older<IconRight size={16} /></button>
          </div>
        )}
      </Card>

      <p className="xs muted mt8 row" style={{ gap: 6 }}>
        <BrandIcon provider="strava" size={13} /><BrandIcon provider="komoot" size={13} /> on that platform · faded = not there · blue dot = copy made by RoutePass
      </p>

      {selecting && selected.length > 0 && (
        <div className="action-bar" role="toolbar">
          <b className="small" style={{ flex: "none" }}>{selected.length}</b>
          <button className="sm" disabled={bulk.isPending} onClick={() => bulk.mutate("strava_to_komoot")}><IconSync size={15} />To <BrandIcon provider="komoot" size={14} /></button>
          <button className="sm" disabled={bulk.isPending} onClick={() => bulk.mutate("komoot_to_strava")}><IconSync size={15} />To <BrandIcon provider="strava" size={14} /></button>
          <button className="sm" disabled={selected.length < 2} onClick={() => setTrip(true)}><MetricIcon.distance size={15} />Trip</button>
          <button className="sm ghost icon" onClick={() => setSelected([])} aria-label="Clear selection"><IconX size={16} /></button>
        </div>
      )}
      {trip && <TripView ids={selected} onClose={() => setTrip(false)} />}

      {filtersOpen && (
        <Modal title="Filters" onClose={() => setFiltersOpen(false)}
          footer={<><button onClick={() => update({ start: null, end: null, min_km: null, max_km: null, presence: null, family: [] })}>Reset</button><button className="primary" onClick={() => setFiltersOpen(false)}>Show {data ? int(data.total) : ""} activities</button></>}>
          <div className="stack">
            <div className="section-label">Sport</div>
            <FamilyChips value={families} onChange={(v) => update({ family: v })} />
          </div>
          <div className="stack">
            <div className="section-label">Platform</div>
            <Seg block value={get("presence") || "all"} onChange={(v) => update({ presence: v === "all" ? null : v })}
              options={[
                { value: "all", label: "All" },
                { value: "both", label: "Both" },
                { value: "strava_only", label: <BrandIcon provider="strava" size={16} title="Only on Strava" /> },
                { value: "komoot_only", label: <BrandIcon provider="komoot" size={16} title="Only on Komoot" /> },
                { value: "synced", label: "Copies" },
              ]} />
          </div>
          <div className="fields">
            <label className="field">From<input type="date" value={get("start")} onChange={(e) => update({ start: e.target.value })} /></label>
            <label className="field">To<input type="date" value={get("end")} onChange={(e) => update({ end: e.target.value })} /></label>
            <label className="field">Min km<input type="number" inputMode="decimal" value={get("min_km")} onChange={(e) => update({ min_km: e.target.value })} /></label>
            <label className="field">Max km<input type="number" inputMode="decimal" value={get("max_km")} onChange={(e) => update({ max_km: e.target.value })} /></label>
          </div>
        </Modal>
      )}
    </>
  );
}
