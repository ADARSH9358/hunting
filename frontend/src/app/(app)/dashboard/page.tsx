"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Building2, CalendarClock, Flame, Layers, Sparkles, Star, Upload, Users } from "lucide-react";
import { EmptyState, PageHeader, StatCard } from "@/components/common";
import { JobCard, JobCardSkeleton, JobDetailSheet } from "@/components/jobs";
import { RunPanel } from "@/components/run-panel";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { DashboardStats, Job, Page } from "@/lib/types";
import { fmtDate, months } from "@/lib/utils";

export default function DashboardPage() {
  const [open, setOpen] = useState<number | null>(null);
  const stats = useQuery({ queryKey: ["dashboard"], queryFn: () => api<DashboardStats>("/dashboard/stats") });
  const top = useQuery({
    queryKey: ["jobs", "top"],
    queryFn: () => api<Page<Job>>("/jobs", { query: { page_size: 5, sort: "score" } }),
  });
  const s = stats.data;

  if (stats.isLoading)
    return (
      <div className="space-y-6">
        <Skeleton className="h-24 w-full" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      </div>
    );

  if (s && !s.profile)
    return (
      <>
        <PageHeader title="Welcome to JobHunt AI" description="Let's start with your resume." />
        <EmptyState
          icon={Upload}
          title="Upload your resume to begin"
          description="We'll analyse your skills and real experience, then search job boards and company career pages for matching roles."
          action={
            <Button asChild variant="gradient" size="lg">
              <Link href="/upload">Upload resume</Link>
            </Button>
          }
        />
      </>
    );

  const p = s!.profile!;
  return (
    <div className="space-y-6">
      <PageHeader title={`Hi${p.candidate ? `, ${p.candidate.split(" ")[0]}` : ""} 👋`} description="Here's what your AI job-search assistant has found." />

      <Card>
        <CardContent className="grid gap-6 p-5 md:grid-cols-4">
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Candidate</p>
            <p className="mt-1 font-semibold">{p.candidate ?? "Not specified"}</p>
            <Badge className="mt-2">{p.experience_level ?? "Level not determined"}</Badge>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Experience</p>
            <p className="mt-1 text-sm">
              <b>{months(p.professional_experience_months)}</b> professional
            </p>
            <p className="text-sm">
              <b>{months(p.internship_experience_months)}</b> internships
            </p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Skills extracted · {p.skills_count}</p>
            <div className="mt-2 flex flex-wrap gap-1">
              {p.top_skills.map((x) => (
                <Badge key={x} variant="secondary">
                  {x}
                </Badge>
              ))}
            </div>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Last search</p>
            <p className="mt-1 flex items-center gap-1.5 text-sm">
              <CalendarClock className="h-4 w-4 text-muted-foreground" />
              {s?.last_completed_search?.finished_at ? fmtDate(s.last_completed_search.finished_at) : "No searches yet"}
            </p>
            <Link href="/analysis" className="mt-2 inline-block text-xs text-primary hover:underline">
              Review resume analysis →
            </Link>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <StatCard label="Total jobs discovered" value={s!.total_jobs} icon={Layers} hint={`${s!.matching_jobs} at ≥${s!.min_match_score}% match`} />
        <StatCard label="Highly relevant" value={s!.highly_relevant} icon={Star} tone="success" hint="Match score 75% or higher" />
        <StatCard label="Small company openings" value={s!.small_company_jobs} icon={Users} tone="fuchsia" hint="1–50 employees (verified)" />
        <StatCard label="Medium company openings" value={s!.medium_company_jobs} icon={Building2} tone="sky" hint="51–500 employees (verified)" />
        <StatCard label="New jobs discovered" value={s!.new_jobs} icon={Sparkles} tone="warning" hint="Found in the latest run" />
      </div>

      <RunPanel compact lastRun={s?.last_completed_search?.finished_at} />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-3 lg:col-span-2">
          <div className="flex items-center justify-between">
            <h2 className="flex items-center gap-2 font-semibold">
              <Flame className="h-4 w-4 text-orange-500" /> Top matches
            </h2>
            <Button asChild variant="link" size="sm">
              <Link href="/jobs">View all jobs →</Link>
            </Button>
          </div>
          {top.isLoading ? (
            <JobCardSkeleton />
          ) : top.data?.items.length ? (
            top.data.items.map((j) => <JobCard key={j.id} job={j} onOpen={setOpen} />)
          ) : (
            <EmptyState icon={Sparkles} title="No jobs yet" description="Press RUN to start your first search." />
          )}
        </div>
        <Card className="h-fit">
          <CardHeader>
            <CardTitle className="text-base">Match distribution</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {Object.entries(s!.score_distribution).map(([band, n]) => {
              const total = Object.values(s!.score_distribution).reduce((a, b) => a + b, 0) || 1;
              return (
                <div key={band}>
                  <div className="flex justify-between text-xs">
                    <span>{band}%</span>
                    <span className="tabular-nums text-muted-foreground">{n}</span>
                  </div>
                  <div className="mt-1 h-2 overflow-hidden rounded-full bg-muted">
                    <div className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-fuchsia-500" style={{ width: `${(n / total) * 100}%` }} />
                  </div>
                </div>
              );
            })}
            <div className="border-t pt-3 text-xs text-muted-foreground">
              {s!.official_jobs} matching jobs come from official company sources · {s!.companies_tracked} companies tracked
            </div>
          </CardContent>
        </Card>
      </div>
      <JobDetailSheet jobId={open} onClose={() => setOpen(null)} />
    </div>
  );
}
