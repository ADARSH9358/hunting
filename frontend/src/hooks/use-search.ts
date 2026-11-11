"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import type { Preferences, SearchLog, SearchSession } from "@/lib/types";

const ACTIVE = ["queued", "running"];

/** Shared RUN-button state: start, poll live progress + logs, stop. */
export function useSearchRun() {
  const qc = useQueryClient();
  const [searchId, setSearchId] = useState<number | null>(null);
  const [logs, setLogs] = useState<SearchLog[]>([]);
  const lastLog = useRef(0);
  const notified = useRef<number | null>(null);

  // pick up a search already running (e.g. after page reload / from another tab)
  const active = useQuery({
    queryKey: ["search", "active"],
    queryFn: () => api<SearchSession | null>("/search/active"),
    refetchInterval: searchId ? false : 10_000,
  });
  useEffect(() => {
    if (active.data && !searchId) setSearchId(active.data.id);
  }, [active.data, searchId]);

  const status = useQuery({
    queryKey: ["search", "status", searchId],
    enabled: !!searchId,
    queryFn: async () => {
      const s = await api<SearchSession>(`/search/status/${searchId}`, { query: { after_log_id: lastLog.current } });
      if (s.logs?.length) {
        lastLog.current = s.logs[s.logs.length - 1].id;
        setLogs((prev) => [...prev, ...s.logs!].slice(-400));
      }
      return s;
    },
    refetchInterval: (q) => (q.state.data && !ACTIVE.includes(q.state.data.status) ? false : 1500),
  });

  const session = status.data;
  const running = !!session && ACTIVE.includes(session.status);

  useEffect(() => {
    if (!session || ACTIVE.includes(session.status) || notified.current === session.id) return;
    notified.current = session.id;
    qc.invalidateQueries({ queryKey: ["jobs"] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
    qc.invalidateQueries({ queryKey: ["companies"] });
    qc.invalidateQueries({ queryKey: ["history"] });
    qc.invalidateQueries({ queryKey: ["search", "active"] });
    if (session.status === "completed")
      toast.success("Search completed", { description: `${session.stats.matching_jobs ?? 0} matching jobs · ${session.stats.new_jobs ?? 0} new` });
    else if (session.status === "cancelled") toast.message("Search stopped", { description: "Results collected so far were saved." });
    else if (session.status === "failed") toast.error("Search failed", { description: session.error ?? undefined });
  }, [session, qc]);

  const run = useMutation({
    mutationFn: (overrides?: Partial<Preferences>) =>
      api<{ search_id: number }>("/search/run", { method: "POST", body: JSON.stringify(overrides ? { overrides } : {}) }),
    onSuccess: (d) => {
      lastLog.current = 0;
      setLogs([]);
      notified.current = null;
      setSearchId(d.search_id);
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (e) => {
      const err = e as ApiError;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const existing = (err.data as any)?.detail?.search_id;
      if (err.status === 409 && existing) {
        setSearchId(existing);
        toast.info("A search is already running — showing its progress.");
      } else toast.error(err.message);
    },
  });

  const stop = useMutation({
    mutationFn: () => api(`/search/stop/${searchId}`, { method: "POST" }),
    onSuccess: () => toast.message("Stopping… saving results collected so far"),
    onError: (e) => toast.error((e as Error).message),
  });

  return { session, running, logs, run, stop, searchId };
}
