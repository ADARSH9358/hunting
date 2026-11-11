"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Filter, Search, SearchX, X } from "lucide-react";
import { EmptyState, PageHeader, TagInput } from "@/components/common";
import { JobCard, JobCardSkeleton, JobDetailSheet } from "@/components/jobs";
import { Badge, Button, Card, Input, Label, NativeSelect, Switch } from "@/components/ui";
import { api } from "@/lib/api";
import type { Job, Page, Preferences } from "@/lib/types";
import { cn } from "@/lib/utils";


interface Filters {
  q: string;
  min_score: number;
  max_experience: string;
  location: string[];
  include_remote: boolean;
  company_size: string[];
  work_mode: string[];
  job_type: string;
  salary_min: string;
  has_salary: boolean;
  posted_within_days: string;
  skills: string[];
  company_type: string;
  official_only: boolean;
  new_only: boolean;
  include_hidden: boolean;
  include_unavailable: boolean;
  sort: string;
}

const DEFAULTS: Filters = {
  q: "",
  min_score: 40,
  max_experience: "",
  location: [],
  include_remote: false,
  company_size: [],
  work_mode: [],
  job_type: "",
  salary_min: "",
  has_salary: false,
  posted_within_days: "",
  skills: [],
  company_type: "",
  official_only: false,
  new_only: false,
  include_hidden: false,
  include_unavailable: false,
  sort: "score",
};

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn("rounded-full border px-2.5 py-1 text-xs font-medium transition-colors", on ? "border-primary bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted")}
    >
      {children}
    </button>
  );
}

function JobsInner() {
  const params = useSearchParams();
  const [f, setF] = useState<Filters>({ ...DEFAULTS, new_only: params.get("new") === "1" });
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<number | null>(null);
  const [showFilters, setShowFilters] = useState(false);
  const [companyId, setCompanyId] = useState<string | null>(params.get("company"));

  useEffect(() => {
    const t = setTimeout(() => setF((x) => ({ ...x, q })), 350);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => setPage(1), [f]);

  const prefs = useQuery({
    queryKey: ["preferences"],
    queryFn: () => api<Preferences>("/resume/preferences"),
    retry: false,
  });
  const prefLocs = [...(prefs.data?.preferred_locations ?? []), ...(prefs.data?.countries ?? [])];
  // Start with the user's preferred locations applied, once, when they load.
  const [prefApplied, setPrefApplied] = useState(false);
  useEffect(() => {
    if (!prefApplied && prefs.data) {
      setPrefApplied(true);
      if (prefLocs.length) setF((x) => (x.location.length ? x : { ...x, location: prefLocs }));
    }
  }, [prefs.data, prefApplied]); // eslint-disable-line react-hooks/exhaustive-deps

  const set = <K extends keyof Filters>(k: K, v: Filters[K]) => setF((x) => ({ ...x, [k]: v }));
  const toggle = (k: "company_size" | "work_mode", v: string) => set(k, f[k].includes(v) ? f[k].filter((x) => x !== v) : [...f[k], v]);

  const jobs = useQuery({
    queryKey: ["jobs", "list", f, page, companyId],
    queryFn: () =>
      api<Page<Job>>("/jobs", {
        query: {
          q: f.q,
          min_score: f.min_score,
          max_experience: f.max_experience,
          location: f.location,
          include_remote: f.include_remote,
          company_size: f.company_size,
          work_mode: f.work_mode,
          job_type: f.job_type,
          salary_min: f.salary_min,
          has_salary: f.has_salary,
          posted_within_days: f.posted_within_days,
          skills: f.skills,
          company_type: f.company_type,
          official_only: f.official_only,
          new_only: f.new_only,
          include_hidden: f.include_hidden,
          include_unavailable: f.include_unavailable,
          sort: f.sort,
          company_id: companyId,
          page_no: page,
          page_size: 20,
        },
      }),
    placeholderData: keepPreviousData,
  });

  const activeCount = (Object.keys(DEFAULTS) as (keyof Filters)[]).filter(
    (k) => k !== "sort" && k !== "q" && JSON.stringify(f[k]) !== JSON.stringify(DEFAULTS[k]),
  ).length;

  const filters = (
    <div className="space-y-5 text-sm">
      <div className="space-y-1.5">
        <Label>Minimum match: {f.min_score}%</Label>
        <input type="range" min={0} max={95} step={5} value={f.min_score} onChange={(e) => set("min_score", Number(e.target.value))} className="w-full accent-[hsl(var(--primary))]" />
      </div>
      <div className="space-y-2">
        <Label>Company size</Label>
        <div className="flex flex-wrap gap-1.5">
          {[
            ["small", "Small"],
            ["medium", "Medium"],
            ["large", "Large"],
            ["unknown", "Not verified"],
          ].map(([k, l]) => (
            <Chip key={k} on={f.company_size.includes(k)} onClick={() => toggle("company_size", k)}>
              {l}
            </Chip>
          ))}
        </div>
      </div>
      <div className="space-y-2">
        <Label>Remote / Hybrid / Onsite</Label>
        <div className="flex flex-wrap gap-1.5">
          {["remote", "hybrid", "onsite", "unknown"].map((k) => (
            <Chip key={k} on={f.work_mode.includes(k)} onClick={() => toggle("work_mode", k)}>
              {k === "unknown" ? "Not specified" : k[0].toUpperCase() + k.slice(1)}
            </Chip>
          ))}
        </div>
      </div>
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <Label>Location</Label>
          {prefLocs.length > 0 && (
            <button type="button" className="text-xs text-primary hover:underline" onClick={() => set("location", prefLocs)}>
              Use my preferences
            </button>
          )}
        </div>
        <TagInput value={f.location} onChange={(v) => set("location", v)} placeholder="e.g. Bengaluru, India, Remote" />
        <label className="flex items-center justify-between gap-3 pt-1">
          <span className="text-xs text-muted-foreground">Also include remote jobs</span>
          <Switch checked={f.include_remote} onCheckedChange={(v) => set("include_remote", v)} />
        </label>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1.5">
          <Label>Max yrs required</Label>
          <Input type="number" min={0} placeholder="Any" value={f.max_experience} onChange={(e) => set("max_experience", e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label>Posted within</Label>
          <NativeSelect value={f.posted_within_days} onChange={(e) => set("posted_within_days", e.target.value)}>
            <option value="">Any time</option>
            <option value="1">24 hours</option>
            <option value="3">3 days</option>
            <option value="7">7 days</option>
            <option value="14">14 days</option>
            <option value="30">30 days</option>
          </NativeSelect>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1.5">
          <Label>Job type</Label>
          <NativeSelect value={f.job_type} onChange={(e) => set("job_type", e.target.value)}>
            <option value="">Any</option>
            <option value="full">Full-time</option>
            <option value="part">Part-time</option>
            <option value="contract">Contract</option>
            <option value="intern">Internship</option>
          </NativeSelect>
        </div>
        <div className="space-y-1.5">
          <Label>Company type</Label>
          <NativeSelect value={f.company_type} onChange={(e) => set("company_type", e.target.value)}>
            <option value="">Any</option>
            {["Startup", "AI startup", "SaaS / Product", "Product-based", "Service-based", "Remote-first"].map((t) => (
              <option key={t}>{t}</option>
            ))}
          </NativeSelect>
        </div>
      </div>
      <div className="space-y-1.5">
        <Label>Minimum salary (annual, in posting currency)</Label>
        <Input type="number" min={0} placeholder="Any" value={f.salary_min} onChange={(e) => set("salary_min", e.target.value)} />
      </div>
      <div className="space-y-1.5">
        <Label>Must include skills</Label>
        <TagInput value={f.skills} onChange={(v) => set("skills", v)} placeholder="e.g. Python" />
      </div>
      <div className="space-y-3 border-t pt-4">
        {(
          [
            ["new_only", "Only NEW jobs"],
            ["official_only", "Only official company postings"],
            ["has_salary", "Salary disclosed"],
            ["include_hidden", "Show hidden jobs"],
            ["include_unavailable", "Show expired / unavailable"],
          ] as const
        ).map(([k, l]) => (
          <label key={k} className="flex items-center justify-between gap-3">
            <span>{l}</span>
            <Switch checked={f[k]} onCheckedChange={(v) => set(k, v)} />
          </label>
        ))}
      </div>
      {activeCount > 0 && (
        <Button variant="ghost" size="sm" className="w-full" onClick={() => setF({ ...DEFAULTS, q: f.q, sort: f.sort })}>
          <X /> Reset filters
        </Button>
      )}
    </div>
  );

  const d = jobs.data;
  return (
    <div>
      <PageHeader title="All jobs" description={d ? `${d.total} jobs match your filters` : "Loading…"} />
      {companyId && (
        <div className="mb-3">
          <Badge variant="secondary">
            Filtered to one company
            <button aria-label="Clear company filter" onClick={() => setCompanyId(null)}>
              <X />
            </button>
          </Badge>
        </div>
      )}
      <div className="mb-4 flex flex-col gap-3 sm:flex-row">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="h-10 pl-9" placeholder="Search title, company or description…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <NativeSelect className="h-10 sm:w-52" value={f.sort} onChange={(e) => set("sort", e.target.value)}>
          <option value="score">Sort: Best match</option>
          <option value="date">Sort: Most recent</option>
          <option value="discovered">Sort: Recently discovered</option>
          <option value="salary">Sort: Highest salary</option>
          <option value="company">Sort: Company A–Z</option>
        </NativeSelect>
        <Button variant="outline" className="h-10 lg:hidden" onClick={() => setShowFilters(!showFilters)}>
          <Filter /> Filters {activeCount > 0 && <Badge>{activeCount}</Badge>}
        </Button>
      </div>
      <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
        <Card className={cn("h-fit p-5 lg:sticky lg:top-20", !showFilters && "hidden lg:block")}>{filters}</Card>
        <div className="space-y-3">
          {jobs.isLoading ? (
            Array.from({ length: 4 }).map((_, i) => <JobCardSkeleton key={i} />)
          ) : d && d.items.length ? (
            <>
              {d.items.map((j) => (
                <JobCard key={j.id} job={j} onOpen={setOpen} />
              ))}
              <div className="flex items-center justify-between pt-2">
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
            <EmptyState icon={SearchX} title="No jobs match these filters" description="Try lowering the minimum match score, clearing filters, or press RUN to search for new openings." />
          )}
        </div>
      </div>
      <JobDetailSheet jobId={open} onClose={() => setOpen(null)} />
    </div>
  );
}

export default function JobsPage() {
  return (
    <Suspense>
      <JobsInner />
    </Suspense>
  );
}
