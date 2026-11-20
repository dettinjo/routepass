import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ICON, IconRefresh, IconSparkles, IconTarget } from "./icons";
import { Card, InfoTip, useToast } from "./ui";
import { api } from "../lib/api";
import { ago } from "../lib/format";

/** The AI coach's look at one activity, on request. */
export function CoachAnalysis({ activityId }: { activityId: number }) {
  const qc = useQueryClient();
  const toast = useToast();
  const key = ["activity-analysis", activityId];
  const { data } = useQuery<any>({
    queryKey: key, queryFn: () => api(`/activities/${activityId}/analysis`),
    refetchInterval: (q) => ((q.state.data as any)?.working ? 4000 : false),
  });
  const ask = useMutation({
    mutationFn: () => api<any>(`/activities/${activityId}/analysis`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: key }),
    onError: (e: Error) => toast(e.message, true),
  });
  if (!data) return null;
  const an = data.analysis || {};
  const working = data.working || ask.isPending;
  if (!data.available && !an.headline) {
    return (
      <Card title="Coach analysis" icon={IconSparkles}>
        <p className="small muted" style={{ margin: 0 }}>The AI coach can explain this activity — pacing, climbs, how it compares. <Link to="/settings/training">Add a Gemini key</Link></p>
      </Card>
    );
  }
  return (
    <Card title="Coach analysis" icon={IconSparkles}
      hint={an.headline ? `AI coach · ${ago(an.created_at)}` : "Pacing, climbs and how it compares with your similar activities"}
      actions={data.available && (
        <button className="sm" disabled={working} onClick={() => ask.mutate()}>
          <IconRefresh size={ICON.button} className={working ? "spin" : undefined} />{working ? "Analysing…" : an.headline ? "Again" : "Analyse"}
        </button>
      )}>
      {working && <div className="coach-working" role="status" style={{ marginBottom: an.headline ? 10 : 0 }}><IconSparkles size={ICON.button} className="pulse" /><span>The AI coach is looking at this activity… Gemini can take a minute or two.</span></div>}
      {an.headline && (
        <div className="stack" style={{ gap: 8 }}>
          <p className="review-headline">{an.headline}</p>
          {an.points?.length > 0 && <ul className="plain-list small">{an.points.map((p: string, i: number) => <li key={i}>{p}</li>)}</ul>}
          {an.compared && <p className="small secondary" style={{ margin: 0 }}><b>Compared:</b> {an.compared}</p>}
          {an.next_time && <p className="small" style={{ margin: 0, display: "flex", gap: 6, alignItems: "flex-start" }}><IconTarget size={ICON.inline} style={{ marginTop: 3, flex: "none" }} /><span><b>Next time:</b> {an.next_time}</span></p>}
        </div>
      )}
      {!working && an.error && (
        <p className="xs muted row nowrap" style={{ gap: 4, margin: an.headline ? "8px 0 0" : 0 }}>
          {an.headline ? "The last try failed" : "The AI coach didn't answer"} ({ago(an.error_at || an.created_at)})<InfoTip label="Why">{an.error}</InfoTip> — try again later.
        </p>
      )}
    </Card>
  );
}
