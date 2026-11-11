"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, ChevronLeft, ChevronRight, ExternalLink, Pencil, Search } from "lucide-react";
import { toast } from "sonner";
import { CompanyAvatar, EmptyState, PageHeader, SizeBadge } from "@/components/common";
import { Badge, Button, Card, Input, NativeSelect, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { CompanyRow, Page } from "@/lib/types";
import { cn, safeHref, timeAgo } from "@/lib/utils";

export default function CompaniesPage() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [size, setSize] = useState<string[]>([]);
  const [withJobs, setWithJobs] = useState(true);
  const [sort, setSort] = useState("matches");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<number | null>(null);
  const [count, setCount] = useState("");

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 300);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => setPage(1), [debounced, size, withJobs, sort]);

  const data = useQuery({
    queryKey: ["companies", debounced, size, withJobs, sort, page],
    queryFn: () => api<Page<CompanyRow>>("/companies", { query: { q: debounced, size, with_jobs: withJobs, sort, page_no: page, page_size: 30 } }),
    placeholderData: keepPreviousData,
  });

  const update = useMutation({
    mutationFn: ({ id, employee_count }: { id: number; employee_count: number }) =>
      api(`/companies/${id}`, { method: "PUT", body: JSON.stringify({ employee_count }) }),
    onSuccess: () => {
      toast.success("Company size updated");
      setEditing(null);
      qc.invalidateQueries({ queryKey: ["companies"] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const d = data.data;
  return (
    <div>
      <PageHeader
        title="Companies"
        description={d ? `${d.total} companies in your discovery database — re-checked on every RUN, small & mid-sized first.` : "Loading…"}
      />
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="h-10 pl-9" placeholder="Search companies…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="flex flex-wrap gap-1.5">
          {["small", "medium", "large", "unknown"].map((s) => (
            <button
              key={s}
              onClick={() => setSize(size.includes(s) ? size.filter((x) => x !== s) : [...size, s])}
              className={cn("rounded-full border px-3 py-1.5 text-xs font-medium capitalize", size.includes(s) ? "border-primary bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted")}
            >
              {s === "unknown" ? "Size not verified" : s}
            </button>
          ))}
          <button
            onClick={() => setWithJobs(!withJobs)}
            className={cn("rounded-full border px-3 py-1.5 text-xs font-medium", withJobs ? "border-primary bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted")}
          >
            With matching jobs
          </button>
        </div>
        <NativeSelect className="h-10 lg:w-48" value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="matches">Most matching jobs</option>
          <option value="recent">Recently discovered</option>
          <option value="checked">Recently checked</option>
          <option value="name">Name A–Z</option>
        </NativeSelect>
      </div>

      {data.isLoading ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      ) : d && d.items.length ? (
        <>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {d.items.map((c) => (
              <Card key={c.id} className="flex flex-col p-4">
                <div className="flex items-start gap-3">
                  <CompanyAvatar name={c.name} logo={c.logo_url} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-semibold">{c.name}</p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      <SizeBadge size={c.size_category} label={c.employee_count ? `${c.size_label} · ~${c.employee_count}` : c.size_label} />
                      {c.company_type && <Badge variant="outline">{c.company_type}</Badge>}
                      {c.ats_type && <Badge variant="secondary">{c.ats_type} board</Badge>}
                    </div>
                  </div>
                </div>
                <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
                  <div className="rounded-lg bg-muted/60 p-2">
                    <div className="text-base font-semibold tabular-nums">{c.matching_jobs}</div>
                    <div className="text-muted-foreground">matches</div>
                  </div>
                  <div className="rounded-lg bg-muted/60 p-2">
                    <div className="text-base font-semibold tabular-nums">{c.best_score ? Math.round(c.best_score) + "%" : "—"}</div>
                    <div className="text-muted-foreground">best</div>
                  </div>
                  <div className="rounded-lg bg-muted/60 p-2">
                    <div className="text-base font-semibold tabular-nums">{c.open_jobs_count || "—"}</div>
                    <div className="text-muted-foreground">openings</div>
                  </div>
                </div>
                <div className="mt-3 text-xs text-muted-foreground">
                  Discovered via {c.discovered_via ?? "—"} · checked {c.last_checked_at ? timeAgo(c.last_checked_at) : "not yet"}
                </div>
                <div className="mt-auto flex flex-wrap items-center gap-2 pt-3">
                  {c.matching_jobs > 0 && (
                    <Button asChild size="sm" variant="outline">
                      <Link href={`/jobs?company=${c.id}`}>Jobs</Link>
                    </Button>
                  )}
                  {safeHref(c.careers_url) && (
                    <Button asChild size="sm" variant="ghost">
                      <a href={safeHref(c.careers_url)} target="_blank" rel="noopener noreferrer nofollow">
                        Careers <ExternalLink />
                      </a>
                    </Button>
                  )}
                  {editing === c.id ? (
                    <form
                      className="ml-auto flex gap-1"
                      onSubmit={(e) => {
                        e.preventDefault();
                        const n = parseInt(count, 10);
                        if (n > 0) update.mutate({ id: c.id, employee_count: n });
                      }}
                    >
                      <Input autoFocus className="h-8 w-24" type="number" min={1} placeholder="employees" value={count} onChange={(e) => setCount(e.target.value)} />
                      <Button size="sm" type="submit">
                        Set
                      </Button>
                    </form>
                  ) : (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="ml-auto"
                      title="Set verified employee count"
                      onClick={() => {
                        setEditing(c.id);
                        setCount(c.employee_count ? String(c.employee_count) : "");
                      }}
                    >
                      <Pencil /> Size
                    </Button>
                  )}
                </div>
              </Card>
            ))}
          </div>
          <div className="mt-4 flex items-center justify-between">
            <span className="text-sm text-muted-foreground">
              Page {d.page} of {Math.max(1, d.pages)}
            </span>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                <ChevronLeft /> Prev
              </Button>
              <Button variant="outline" size="sm" disabled={page >= d.pages} onClick={() => setPage(page + 1)}>
                Next <ChevronRight />
              </Button>
            </div>
          </div>
        </>
      ) : (
        <EmptyState icon={Building2} title="No companies yet" description="Companies are discovered automatically when you press RUN." />
      )}
    </div>
  );
}
