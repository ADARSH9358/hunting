"use client";

import Link from "next/link";
import { CheckCircle2, CircleAlert, CircleDashed, Loader2, Play, Radar, Square, XCircle } from "lucide-react";
import { Badge, Button, Card, Progress } from "@/components/ui";
import { useSearchRun } from "@/hooks/use-search";
import type { SearchSession } from "@/lib/types";
import { cn, fmtDate } from "@/lib/utils";

const STEPS = [
  "Load resume profile",
  "Generate keywords",
  "Search job sources",
  "Discover companies",
  "Find career pages",
  "Collect official postings",
  "Normalize",
  "De-duplicate",
  "Match to resume",
  "Save & summarise",
];
const STEP_AT = [2, 5, 8, 42, 48, 52, 80, 84, 90, 100];

export function SearchSummary({ s }: { s: SearchSession }) {
  const st = s.stats ?? {};
  const items: [string, number | undefined][] = [
    ["Job postings collected", st.total_collected],
    ["Companies checked", st.companies_checked],
    ["Matching jobs", st.matching_jobs],
    ["Highly relevant (75%+)", st.highly_relevant],
    ["Small-company openings", st.small_company_jobs],
    ["Medium-company openings", st.medium_company_jobs],
    ["New jobs discovered", st.new_jobs],
    ["Duplicates merged", st.duplicates_merged],
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {items.map(([label, v]) => (
        <div key={label} className="rounded-lg border bg-card p-3">
          <div className="text-2xl font-semibold tabular-nums">{v ?? 0}</div>
          <div className="text-xs text-muted-foreground">{label}</div>
        </div>
      ))}
    </div>
  );
}

export function RunPanel({ compact = false, lastRun }: { compact?: boolean; lastRun?: string | null }) {
  const { session, running, logs, run, stop } = useSearchRun();
  const done = session && !running;
  return (
    <Card className="relative overflow-hidden">
      <div className="pointer-events-none absolute -right-24 -top-24 h-64 w-64 rounded-full bg-gradient-to-br from-indigo-500/20 to-fuchsia-500/20 blur-3xl" />
      <div className="relative p-6">
        <div className="flex flex-col gap-5 md:flex-row md:items-center">
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <Radar className="h-5 w-5 text-primary" />
              <h2 className="text-lg font-semibold">Job discovery</h2>
              {session && (
                <Badge variant={running ? "default" : session.status === "completed" ? "success" : session.status === "failed" ? "destructive" : "warning"}>
                  {session.status}
                </Badge>
              )}
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              {running
                ? session?.current_step
                : `Searches job boards, discovers IT companies and checks their official career pages. Last run: ${lastRun ? fmtDate(lastRun) : "never"}.`}
            </p>
          </div>
          <div className="flex gap-2">
            {running ? (
              <Button size="xl" variant="outline" onClick={() => stop.mutate()} disabled={stop.isPending || session?.cancel_requested}>
                <Square className="fill-current" /> {session?.cancel_requested ? "Stopping…" : "Stop"}
              </Button>
            ) : (
              <Button size="xl" variant="gradient" onClick={() => run.mutate(undefined)} disabled={run.isPending} className="min-w-[160px]">
                {run.isPending ? <Loader2 className="animate-spin" /> : <Play className="fill-current" />}
                RUN
              </Button>
            )}
          </div>
        </div>

        {session && (
          <div className="mt-6 space-y-4">
            <div className="flex items-center gap-3">
              <Progress value={session.progress} />
              <span className="w-10 text-right text-sm tabular-nums text-muted-foreground">{session.progress}%</span>
            </div>
            {!compact && (
              <ol className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-5">
                {STEPS.map((label, i) => {
                  const reached = session.progress >= STEP_AT[i];
                  const current = running && reached && (i === STEPS.length - 1 || session.progress < STEP_AT[i + 1]);
                  return (
                    <li key={label} className={cn("flex items-center gap-1.5", reached ? "text-foreground" : "text-muted-foreground")}>
                      {current ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                      ) : reached ? (
                        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                      ) : (
                        <CircleDashed className="h-3.5 w-3.5" />
                      )}
                      {i + 1}. {label}
                    </li>
                  );
                })}
              </ol>
            )}
            {session.keywords?.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-xs text-muted-foreground">Keywords:</span>
                {session.keywords.map((k) => (
                  <Badge key={k} variant="secondary">
                    {k}
                  </Badge>
                ))}
              </div>
            )}
            {done && session.status !== "failed" && (
              <div className="space-y-3 rounded-xl border bg-accent/40 p-4">
                <div className="flex items-center gap-2 text-sm font-semibold">
                  <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                  {session.status === "completed" ? "Search completed successfully!" : "Search stopped — partial results saved."}
                </div>
                <SearchSummary s={session} />
                <div className="flex gap-2">
                  <Button asChild size="sm">
                    <Link href="/jobs">View matching jobs</Link>
                  </Button>
                  <Button asChild size="sm" variant="outline">
                    <Link href="/jobs?new=1">Only new jobs</Link>
                  </Button>
                </div>
              </div>
            )}
            {session.status === "failed" && (
              <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" /> {session.error}
              </div>
            )}
            {!compact && (
              <SourceStatus session={session} />
            )}
            {!compact && logs.length > 0 && (
              <details className="rounded-lg border bg-card" open={running}>
                <summary className="cursor-pointer px-4 py-2 text-sm font-medium">Live activity log ({logs.length})</summary>
                <div className="max-h-64 space-y-1 overflow-y-auto border-t p-3 font-mono text-xs scrollbar-thin">
                  {[...logs].reverse().map((l) => (
                    <div key={l.id} className={cn("flex gap-2", l.level === "warning" && "text-amber-600 dark:text-amber-400", l.level === "error" && "text-destructive")}>
                      <span className="shrink-0 text-muted-foreground">{new Date(l.ts.endsWith("Z") ? l.ts : l.ts + "Z").toLocaleTimeString()}</span>
                      {l.source && <span className="shrink-0 text-primary">[{l.source}]</span>}
                      <span className="break-all">{l.message}</span>
                    </div>
                  ))}
                </div>
              </details>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}

function SourceStatus({ session }: { session: SearchSession }) {
  const entries = Object.entries(session.source_results ?? {});
  if (!entries.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {entries.map(([k, r]) => {
        const Icon = r.status === "ok" ? CheckCircle2 : r.status === "needs_credentials" ? CircleDashed : XCircle;
        const v = r.status === "ok" ? "success" : r.status === "needs_credentials" ? "muted" : "warning";
        return (
          <Badge key={k} variant={v} title={r.error ?? r.status}>
            <Icon /> {k} {r.status === "ok" ? `· ${r.count}` : r.status === "needs_credentials" ? "· needs API key" : `· ${r.status}`}
          </Badge>
        );
      })}
    </div>
  );
}
