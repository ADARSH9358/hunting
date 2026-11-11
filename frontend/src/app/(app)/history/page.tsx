"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowDownRight, ArrowUpRight, History } from "lucide-react";
import { EmptyState, PageHeader } from "@/components/common";
import { SearchSummary } from "@/components/run-panel";
import { Badge, Button, Card, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { Page, SearchSession } from "@/lib/types";
import { fmtDate } from "@/lib/utils";

const TONE: Record<string, "success" | "default" | "warning" | "destructive" | "muted"> = {
  completed: "success",
  running: "default",
  queued: "default",
  cancelled: "warning",
  failed: "destructive",
};

export default function HistoryPage() {
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<number | null>(null);
  const q = useQuery({ queryKey: ["history", page], queryFn: () => api<Page<SearchSession>>("/search/history", { query: { page_no: page, page_size: 20 } }) });
  const d = q.data;
  return (
    <div>
      <PageHeader title="Search history" description="Every RUN is recorded, so you can compare results over time." />
      {q.isLoading ? (
        <Skeleton className="h-64" />
      ) : d && d.items.length ? (
        <div className="space-y-3">
          {d.items.map((s) => {
            const dur = s.stats?.duration_seconds;
            return (
              <Card key={s.id} className="p-4">
                <div className="flex flex-wrap items-center gap-3">
                  <span className="font-mono text-xs text-muted-foreground">#{s.id}</span>
                  <Badge variant={TONE[s.status] ?? "muted"}>{s.status}</Badge>
                  <span className="text-sm">{fmtDate(s.created_at)}</span>
                  {dur != null && <span className="text-xs text-muted-foreground">{Math.round(dur)}s</span>}
                  <div className="ml-auto flex items-center gap-4 text-sm">
                    <span>
                      <b className="tabular-nums">{s.stats?.matching_jobs ?? 0}</b> matching
                    </span>
                    <span>
                      <b className="tabular-nums">{s.stats?.new_jobs ?? 0}</b> new
                    </span>
                    <span>
                      <b className="tabular-nums">{s.stats?.companies_checked ?? 0}</b> companies
                    </span>
                    {s.delta_matching != null && s.delta_matching !== 0 && (
                      <span className={s.delta_matching > 0 ? "flex items-center text-emerald-600" : "flex items-center text-muted-foreground"}>
                        {s.delta_matching > 0 ? <ArrowUpRight className="h-4 w-4" /> : <ArrowDownRight className="h-4 w-4" />}
                        {Math.abs(s.delta_matching)} vs previous
                      </span>
                    )}
                    <Button size="sm" variant="ghost" onClick={() => setExpanded(expanded === s.id ? null : s.id)}>
                      {expanded === s.id ? "Hide" : "Details"}
                    </Button>
                  </div>
                </div>
                {expanded === s.id && (
                  <div className="mt-4 space-y-3 border-t pt-4">
                    <SearchSummary s={s} />
                    {s.keywords?.length > 0 && <p className="text-xs text-muted-foreground">Keywords: {s.keywords.join(", ")}</p>}
                    <div className="flex flex-wrap gap-1.5">
                      {Object.entries(s.source_results ?? {}).map(([k, r]) => (
                        <Badge key={k} variant={r.status === "ok" ? "success" : r.status === "needs_credentials" ? "muted" : "warning"} title={r.error}>
                          {k}: {r.status === "ok" ? r.count : r.status}
                        </Badge>
                      ))}
                    </div>
                    {s.error && <p className="text-sm text-destructive">{s.error}</p>}
                  </div>
                )}
              </Card>
            );
          })}
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>
              Prev
            </Button>
            <Button size="sm" variant="outline" disabled={page >= d.pages} onClick={() => setPage(page + 1)}>
              Next
            </Button>
          </div>
        </div>
      ) : (
        <EmptyState icon={History} title="No searches yet" description="Your RUN history will appear here." />
      )}
    </div>
  );
}
