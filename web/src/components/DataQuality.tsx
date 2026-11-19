import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { useSavePrefs } from "../lib/hooks";
import { Attention } from "./ui";

/** One info note when training load is mostly estimated, with the values suggested from your own data. */
export function DataQualityNote() {
  const save = useSavePrefs();
  const { data } = useQuery<any>({ queryKey: ["data-quality"], queryFn: () => api("/insights/data-quality"), staleTime: 5 * 60_000 });
  if (!data || data.level === "high" || !data.missing?.length || !data.activities) return null;
  const hr = data.suggestions?.hr_max;
  const ftp = data.suggestions?.ftp;
  const pct = Math.round((1 - data.measured_share) * 100);
  return (
    <Attention
      title={() => "Fitness, zones and predictions are mostly estimated"}
      defaultOpen
      items={[{
        level: "info",
        text: <>{pct}% of your last {data.window_days} days' training load comes from duration alone. Adding {data.missing.map((m: any) => m.label.toLowerCase()).join(", ")} makes load, zones and race predictions use your heart rate{ftp ? " and power" : ""}.</>,
        action: (
          <div className="row">
            {hr && <button className="sm" disabled={save.isPending} onClick={() => save.mutate({ profile: { hr_max: hr } })}>Use {hr} bpm as max heart rate</button>}
            {ftp && <button className="sm" disabled={save.isPending} onClick={() => save.mutate({ profile: { ftp } })}>Use {ftp} W as FTP</button>}
            <Link to="/settings/profile" className="small">Open profile</Link>
          </div>
        ),
      }]}
    />
  );
}
