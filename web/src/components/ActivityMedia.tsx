import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { ActivityRow } from "../lib/types";
import {
  BrandIcon, ICON, IconAttention, IconExternal, IconLeft, IconPhotos, IconPlay, IconRefresh, IconRight, IconVisFriends,
  IconVisPrivate, IconVisPublic, providerName,
} from "./icons";
import { Callout, Card, Modal, Seg, useToast } from "./ui";

export const VIS = {
  public: { label: "Public", icon: IconVisPublic, hint: "Everyone" },
  friends: { label: "Friends", icon: IconVisFriends, hint: "Followers on Strava, friends on Komoot" },
  private: { label: "Private", icon: IconVisPrivate, hint: "Only you" },
} as const;
type Level = keyof typeof VIS;

/** Compact marker for lists: only private and mismatched activities need attention. */
export function VisibilityMark({ v }: { v?: ActivityRow["visibility"] }) {
  if (!v) return null;
  const levels = Object.values(v.by_provider).filter(Boolean) as Level[];
  if (v.mismatch) {
    const text = Object.entries(v.by_provider).map(([p, l]) => `${providerName(p)}: ${l ? VIS[l as Level].label.toLowerCase() : "unknown"}`).join(", ");
    return <span title={`Visibility differs — ${text}`} style={{ display: "inline-flex", color: "var(--warn)" }}><IconAttention size={ICON.inline} /></span>;
  }
  if (levels[0] === "private") return <span title="Private on every platform" style={{ display: "inline-flex" }} className="muted"><IconVisPrivate size={ICON.inline} /></span>;
  return null;
}

/** Who can see this activity, per platform, with one control to set both. */
export function VisibilityCard({ a }: { a: ActivityRow }) {
  const qc = useQueryClient();
  const toast = useToast();
  const v = a.visibility;
  const set = useMutation({
    mutationFn: ({ level, providers }: { level: Level; providers?: string[] }) =>
      api<any>(`/activities/${a.id}/visibility`, { method: "PUT", body: { level, providers } }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["activity", String(a.id)] });
      qc.invalidateQueries({ queryKey: ["activities"] });
      const failed = Object.entries(r.errors || {});
      if (failed.length) toast(`Could not change ${failed.map(([p]) => providerName(p)).join(", ")}: ${failed[0][1]}`, true);
      else toast("Visibility updated");
    },
    onError: (e: Error) => toast(e.message, true),
  });
  if (!v || !Object.keys(v.by_provider).length) return null;
  const levels = Object.values(v.by_provider).filter(Boolean) as Level[];
  const common = !v.mismatch && levels.length ? levels[0] : null;
  return (
    <Card title="Who can see it" icon={common ? VIS[common].icon : IconVisPublic}
      hint={v.mismatch ? "Different on the two platforms" : common ? VIS[common].hint : "Visibility not known yet"}>
      <div className="stack">
        <div className="vis-rows">
          {Object.entries(v.by_provider).map(([p, l]) => {
            const meta = l ? VIS[l as Level] : null;
            return (
              <span key={p} className="vis-row">
                <BrandIcon provider={p} size={ICON.header} />{providerName(p)}
                <span className="badge neutral">{meta ? <><meta.icon size={ICON.inline} />{meta.label}</> : "unknown"}</span>
              </span>
            );
          })}
        </div>
        {v.mismatch && (
          <Callout kind="warn">This activity is visible to different people on each platform. Pick one setting for both below.</Callout>
        )}
        <Seg block value={(common ?? "") as Level} onChange={(level) => set.mutate({ level })}
          options={(Object.keys(VIS) as Level[]).map((k) => ({ value: k, label: VIS[k].label }))} />
        {set.isPending && <span className="xs muted">Updating {Object.keys(v.by_provider).map(providerName).join(" and ")}…</span>}
      </div>
    </Card>
  );
}

interface Photo { id: string; url: string; thumb: string; caption?: string; provider: string; video?: string | null }

/** Photos from Strava and Komoot; tap one to see it large. */
export function PhotoGallery({ activityId }: { activityId: number }) {
  const [refresh, setRefresh] = useState(false);
  const { data, isLoading, refetch, isFetching } = useQuery<{ photos: Photo[]; counts: Record<string, number>; errors: Record<string, string> }>({
    queryKey: ["activity-media", activityId, refresh],
    queryFn: () => api(`/activities/${activityId}/media`, { params: { refresh: refresh || undefined } }),
    staleTime: 30 * 60_000,
  });
  const [open, setOpen] = useState<number | null>(null);
  const photos = data?.photos ?? [];
  useEffect(() => {
    if (open == null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") setOpen((i) => (i == null ? i : (i + 1) % photos.length));
      if (e.key === "ArrowLeft") setOpen((i) => (i == null ? i : (i - 1 + photos.length) % photos.length));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, photos.length]);
  if (isLoading) return null;
  const errs = Object.entries(data?.errors ?? {});
  if (!photos.length) return null; // nothing to show (or the platform could not be reached)
  const p = open != null ? photos[open] : null;
  return (
    <Card title="Photos" icon={IconPhotos}
      hint={Object.entries(data?.counts ?? {}).filter(([, n]) => n).map(([pr, n]) => `${n} from ${providerName(pr)}`).join(" · ") || undefined}
      actions={<button className="ghost icon sm" aria-label="Reload photos" title="Reload photos" disabled={isFetching} onClick={() => { setRefresh(true); refetch(); }}><IconRefresh size={ICON.button} className={isFetching ? "spin" : undefined} /></button>}>
      {photos.length > 0 && (
        <div className="photo-grid">
          {photos.map((ph, i) => (
            <button key={`${ph.provider}-${ph.id}`} className="photo" onClick={() => setOpen(i)} aria-label={ph.caption || `Photo ${i + 1}`}>
              <img src={ph.thumb} alt={ph.caption || ""} loading="lazy" referrerPolicy="no-referrer" />
              {ph.video && <span className="play"><IconPlay size={ICON.header} /></span>}
              <span className="src"><BrandIcon provider={ph.provider} size={12} /></span>
            </button>
          ))}
        </div>
      )}
      {errs.length > 0 && <p className="xs muted mt8">{errs.map(([pr]) => `${providerName(pr)} photos could not be loaded`).join("; ")}.</p>}
      {p && (
        <Modal title={<span className="row nowrap" style={{ gap: 6 }}><BrandIcon provider={p.provider} size={ICON.button} />Photo {open! + 1} of {photos.length}</span>} onClose={() => setOpen(null)}
          footer={<>
            <button className="icon" aria-label="Previous photo" onClick={() => setOpen((open! - 1 + photos.length) % photos.length)}><IconLeft size={ICON.button} /></button>
            <a className="btn" href={p.video || p.url} target="_blank" rel="noreferrer"><IconExternal size={ICON.button} />{p.video ? "Play video" : "Full size"}</a>
            <button className="icon" aria-label="Next photo" onClick={() => setOpen((open! + 1) % photos.length)}><IconRight size={ICON.button} /></button>
          </>}>
          <img src={p.url} alt={p.caption || ""} className="photo-large" referrerPolicy="no-referrer" />
          {p.caption && <p className="small secondary">{p.caption}</p>}
        </Modal>
      )}
    </Card>
  );
}
