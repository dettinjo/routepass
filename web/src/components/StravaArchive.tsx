import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { ago, int } from "../lib/format";
import { IconImport } from "./icons";
import { Callout } from "./ui";

interface ArchiveState {
  phase: string; file?: string; total?: number; done?: number; new?: number; updated?: number; tracks?: number;
  skipped?: number; error?: string | null; finished_at?: string; available?: string[];
}

/** Upload Strava's free "Download your account" export and import it. */
export function StravaArchive() {
  const qc = useQueryClient();
  const [upload, setUpload] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { data: st } = useQuery<ArchiveState>({
    queryKey: ["strava-archive"],
    queryFn: () => api("/import/strava-archive"),
    refetchInterval: (q) => (["queued", "importing", "tracks"].includes(q.state.data?.phase ?? "") || upload != null ? 2000 : false),
  });

  const send = (file: File) => {
    setError(null);
    setUpload(0);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/v1/import/strava-archive");
    xhr.withCredentials = true;
    xhr.setRequestHeader("Content-Type", "application/zip");
    xhr.upload.onprogress = (e) => e.lengthComputable && setUpload(e.loaded / e.total);
    xhr.onload = () => {
      setUpload(null);
      if (xhr.status >= 300) {
        try { setError(JSON.parse(xhr.responseText).detail); } catch { setError(`Upload failed (${xhr.status})`); }
      }
      qc.invalidateQueries({ queryKey: ["strava-archive"] });
    };
    xhr.onerror = () => { setUpload(null); setError("Upload failed — check the connection and try again."); };
    xhr.send(file);
  };

  const busy = upload != null || ["queued", "importing", "tracks"].includes(st?.phase ?? "");
  const pct = st?.total ? Math.round(((st.done ?? 0) / st.total) * 100) : 0;
  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="section-label">Import your Strava data export</div>
      <p className="small secondary">
        Works without the Strava API: every Strava user can download their complete history for free, including the
        original recordings.
      </p>
      <ol className="small secondary" style={{ margin: 0, paddingLeft: 20, display: "grid", gap: 4 }}>
        <li>On strava.com (not the app): <a href="https://www.strava.com/athlete/delete_your_account" target="_blank" rel="noreferrer">Settings → My Account → Download or delete your account → Get started</a>, then <b>Request download</b>.</li>
        <li>Strava e-mails a link within a few hours — download the zip.</li>
        <li>Upload it here unchanged. Re-importing a newer export later only adds what is new.</li>
      </ol>
      {error && <Callout kind="bad">{error}</Callout>}
      {upload != null && (
        <div className="stack" style={{ gap: 4 }}>
          <span className="small">Uploading… {Math.round(upload * 100)}%</span>
          <div className="progress"><span style={{ width: `${upload * 100}%`, background: "var(--accent)" }} /></div>
        </div>
      )}
      {st && ["queued", "importing", "tracks"].includes(st.phase) && (
        <div className="stack" style={{ gap: 4 }}>
          <span className="small">
            {st.phase === "tracks" ? `Attaching recordings… ${int(st.tracks)} done` : `Reading activities… ${int(st.done)} of ${int(st.total)}`}
          </span>
          <div className="progress"><span style={{ width: `${st.phase === "tracks" ? 100 : pct}%`, background: "var(--accent)" }} /></div>
        </div>
      )}
      {st?.phase === "finished" && (
        <Callout kind="good">
          Imported {ago(st.finished_at)}: {int(st.new)} new, {int(st.updated)} updated, {int(st.tracks)} recordings
          {st.skipped ? `, ${st.skipped} skipped` : ""}. Duplicates with Komoot were merged.
        </Callout>
      )}
      {st?.phase === "error" && <Callout kind="bad">Import failed: {st.error}</Callout>}
      <label className={`btn ${busy ? "" : "primary"}`} style={{ alignSelf: "flex-start", cursor: busy ? "default" : "pointer", opacity: busy ? 0.6 : 1 }}>
        <IconImport size={17} />Choose Strava export (.zip)
        <input type="file" accept=".zip,application/zip" disabled={busy} style={{ display: "none" }}
          onChange={(e) => { const f = e.target.files?.[0]; if (f) send(f); e.target.value = ""; }} />
      </label>
    </div>
  );
}
