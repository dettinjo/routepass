import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api } from "./api";
import type { Preferences, Status } from "./types";
import { useToast } from "../components/ui";

export function useStatus() {
  const qc = useQueryClient();
  const wasRunning = useRef(false);
  const q = useQuery<Status>({
    queryKey: ["status"],
    queryFn: () => api("/status"),
    refetchInterval: (query) => (query.state.data?.running ? 3000 : 30000),
  });
  useEffect(() => {
    const running = !!q.data?.running;
    if (wasRunning.current && !running) {
      // a cycle just finished: everything derived from activities may have changed
      qc.invalidateQueries({ predicate: (x) => x.queryKey[0] !== "status" });
    }
    wasRunning.current = running;
  }, [q.data?.running, qc]);
  return q;
}

export function useRunSync() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: (full: boolean = false) => api("/sync/run", { method: "POST", body: { full } }),
    onSuccess: (r: any) => {
      toast(r.status === "busy" ? "A sync is already running" : "Sync started");
      qc.invalidateQueries({ queryKey: ["status"] });
    },
    onError: (e: Error) => toast(e.message, true),
  });
}

export function usePrefs() {
  return useQuery<Preferences>({ queryKey: ["prefs"], queryFn: () => api("/settings") });
}

export function useSavePrefs() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: (patch: Record<string, any>) => api<Preferences>("/settings", { method: "PATCH", body: patch }),
    onSuccess: (data) => {
      qc.setQueryData(["prefs"], data);
      toast("Saved");
    },
    onError: (e: Error) => toast(e.message, true),
  });
}

export function useSportMeta() {
  return useQuery<{ strava: { key: string; label: string; family: string }[]; komoot: { key: string; label: string }[]; families: string[] }>({
    queryKey: ["meta-sports"],
    queryFn: () => api("/meta/sports"),
    staleTime: Infinity,
  });
}
