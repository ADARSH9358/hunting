"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bookmark,
  BookmarkCheck,
  Briefcase,
  Building2,
  CalendarDays,
  CheckCircle2,
  Clock,
  ExternalLink,
  EyeOff,
  Globe,
  Loader2,
  Mail,
  MapPin,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  Wallet,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";
import { CompanyAvatar, ScoreRing, SizeBadge } from "@/components/common";
import { Badge, Button, Card, Sheet, SheetContent, Skeleton, Tooltip } from "@/components/ui";
import { api } from "@/lib/api";
import type { Job, JobEmail, Page } from "@/lib/types";
import { useRouter } from "next/navigation";
import { EmailStatusBadge } from "@/components/email";
import { cn, fmtDate, safeHref, timeAgo } from "@/lib/utils";

const MODE: Record<string, { label: string; cls: string }> = {
  remote: { label: "Remote", cls: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300" },
  hybrid: { label: "Hybrid", cls: "bg-sky-500/10 text-sky-700 dark:text-sky-300" },
  onsite: { label: "Onsite", cls: "bg-amber-500/10 text-amber-700 dark:text-amber-300" },
  unknown: { label: "Work mode not specified", cls: "bg-muted text-muted-foreground" },
};

export function useJobActions() {
  const qc = useQueryClient();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["jobs"] });
    qc.invalidateQueries({ queryKey: ["saved"] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
    qc.invalidateQueries({ queryKey: ["job"] });
  };
  const save = useMutation({
    mutationFn: ({ id, saved }: { id: number; saved: boolean }) => api(`/jobs/${id}/save`, { method: saved ? "DELETE" : "POST" }),
    onSuccess: (_, v) => {
      toast.success(v.saved ? "Removed from saved jobs" : "Job saved");
      refresh();
    },
    onError: (e) => toast.error((e as Error).message),
  });
  const hide = useMutation({
    mutationFn: ({ id, hidden }: { id: number; hidden: boolean }) => api(`/jobs/${id}/hide`, { method: "POST", query: { hidden } }),
    onSuccess: (_, v) => {
      toast.message(v.hidden ? "Job hidden" : "Job restored");
      refresh();
    },
  });
  return { save, hide };
}

export function JobCard({ job, onOpen }: { job: Job; onOpen: (id: number) => void }) {
  const { save, hide } = useJobActions();
  const m = job.match;
  const mode = MODE[job.work_mode] ?? MODE.unknown;
  const official = job.sources.find((s) => s.is_official);
  return (
    <Card
      className={cn(
        "group relative p-5 transition-all hover:-translate-y-0.5 hover:shadow-md",
        job.status === "unavailable" && "opacity-60",
      )}
    >
      <div className="flex gap-4">
        <CompanyAvatar name={job.company.name} logo={job.company.logo_url} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {m?.is_new && <Badge variant="new">NEW</Badge>}
            {job.status === "unavailable" && <Badge variant="destructive">No longer listed</Badge>}
            {job.is_official ? (
              <Badge variant="success">
                <ShieldCheck /> Official posting
              </Badge>
            ) : (
              <Badge variant="muted">Job board listing</Badge>
            )}
          </div>
          <button onClick={() => onOpen(job.id)} className="mt-1.5 block text-left text-base font-semibold leading-snug hover:text-primary">
            {job.title}
          </button>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
            <span className="font-medium text-foreground/80">{job.company.name}</span>
            <SizeBadge size={job.company.size_category} label={job.company.size_label} />
            {job.company.company_type && <Badge variant="outline">{job.company.company_type}</Badge>}
          </div>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
              <MapPin className="h-3.5 w-3.5" />
              {job.location}
            </span>
            <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 font-medium", mode.cls)}>{mode.label}</span>
            <span className="inline-flex items-center gap-1.5">
              <Briefcase className="h-3.5 w-3.5" />
              {job.experience}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Wallet className="h-3.5 w-3.5" />
              {job.salary}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <CalendarDays className="h-3.5 w-3.5" />
              {job.date_posted ? `Posted ${timeAgo(job.date_posted)}` : "Post date not specified"}
            </span>
          </div>
          {m && m.matched_skills.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {m.matched_skills.slice(0, 6).map((s) => (
                <span key={s} className="rounded-md bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:text-emerald-300">
                  ✓ {s}
                </span>
              ))}
              {m.missing_skills.slice(0, 3).map((s) => (
                <span key={s} className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                  {s}
                </span>
              ))}
            </div>
          )}
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button size="sm" variant="outline" onClick={() => onOpen(job.id)}>
              View details
            </Button>
            {safeHref(job.apply_url) && (
              <Button size="sm" asChild>
                <a href={safeHref(job.apply_url)} target="_blank" rel="noopener noreferrer nofollow">
                  Apply now <ExternalLink />
                </a>
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={() => save.mutate({ id: job.id, saved: job.saved })} aria-label="Save job">
              {job.saved ? <BookmarkCheck className="text-primary" /> : <Bookmark />}
              {job.saved ? "Saved" : "Save"}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => hide.mutate({ id: job.id, hidden: !m?.hidden })}>
              <EyeOff /> {m?.hidden ? "Unhide" : "Hide"}
            </Button>
            <span className="ml-auto text-xs text-muted-foreground">
              via {official ? official.name : job.sources[0]?.name}
              {job.sources.length > 1 && ` +${job.sources.length - 1} more`}
            </span>
          </div>
        </div>
        {m && (
          <div className="hidden flex-col items-center gap-1 sm:flex">
            <ScoreRing score={m.score} size={64} />
            <span className="text-[11px] text-muted-foreground">match</span>
          </div>
        )}
      </div>
    </Card>
  );
}

export function JobCardSkeleton() {
  return (
    <Card className="p-5">
      <div className="flex gap-4">
        <Skeleton className="h-11 w-11 rounded-xl" />
        <div className="flex-1 space-y-3">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="h-4 w-full" />
        </div>
        <Skeleton className="h-16 w-16 rounded-full" />
      </div>
    </Card>
  );
}

const BREAKDOWN_LABEL: Record<string, string> = {
  skills: "Technical skills",
  experience: "Relevant experience",
  role: "Role compatibility",
  education: "Education",
  location: "Location & work preference",
};

export function JobDetailSheet({ jobId, onClose }: { jobId: number | null; onClose: () => void }) {
  const qc = useQueryClient();
  const { save } = useJobActions();
  const q = useQuery({ queryKey: ["job", jobId], queryFn: () => api<Job>(`/jobs/${jobId}`), enabled: !!jobId });
  const explain = useMutation({
    mutationFn: () => api<{ llm_explanation: string }>(`/jobs/${jobId}/explain`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["job", jobId] }),
    onError: (e) => toast.error((e as Error).message),
  });
  const router = useRouter();
  const emails = useQuery({
    queryKey: ["job-emails-for-job", jobId],
    queryFn: () => api<Page<JobEmail>>("/job-emails", { query: { job_id: jobId, page_size: 5 } }),
    enabled: !!jobId,
  });
  const draft = useMutation({
    mutationFn: () => api<JobEmail>("/job-emails/drafts", { method: "POST", body: JSON.stringify({ job_id: jobId }) }),
    onSuccess: (d) => router.push(`/applications?draft=${d.id}`),
    onError: (e) => toast.error((e as Error).message),
  });
  const lastEmail = emails.data?.items[0];
  const job = q.data;
  const m = job?.match;
  return (
    <Sheet open={!!jobId} onOpenChange={(o) => !o && onClose()}>
      <SheetContent title={job?.title ?? "Job details"}>
        {!job ? (
          <div className="space-y-4 p-6">
            <Skeleton className="h-8 w-2/3" />
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-40 w-full" />
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto scrollbar-thin">
            <div className="border-b bg-gradient-to-b from-accent/60 to-transparent p-6 pr-14">
              <div className="flex items-start gap-4">
                <CompanyAvatar name={job.company.name} logo={job.company.logo_url} className="h-14 w-14" />
                <div className="min-w-0 flex-1">
                  <h2 className="text-xl font-semibold leading-tight">{job.title}</h2>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                    <span className="font-medium text-foreground">{job.company.name}</span>
                    <SizeBadge size={job.company.size_category} label={job.company.size_label} />
                    {job.company.employee_count && (
                      <span className="text-xs">
                        ~{job.company.employee_count} employees ({job.company.size_source})
                      </span>
                    )}
                  </div>
                </div>
                {m && <ScoreRing score={m.score} size={72} />}
              </div>
              <div className="mt-5 flex flex-wrap gap-2">
                {safeHref(job.apply_url) && (
                  <Button asChild>
                    <a href={safeHref(job.apply_url)} target="_blank" rel="noopener noreferrer nofollow">
                      Apply now <ExternalLink />
                    </a>
                  </Button>
                )}
                <Button variant="outline" onClick={() => save.mutate({ id: job.id, saved: job.saved })}>
                  {job.saved ? <BookmarkCheck className="text-primary" /> : <Bookmark />} {job.saved ? "Saved" : "Save job"}
                </Button>
                {lastEmail ? (
                  <Button variant="outline" onClick={() => router.push(`/applications?draft=${lastEmail.id}`)}>
                    <Mail /> Application email <EmailStatusBadge status={lastEmail.status} />
                  </Button>
                ) : (
                  <Button variant="outline" onClick={() => draft.mutate()} disabled={draft.isPending}>
                    <Mail /> Email HR
                  </Button>
                )}
                {safeHref(job.company.careers_url) && (
                  <Button variant="ghost" asChild>
                    <a href={safeHref(job.company.careers_url)} target="_blank" rel="noopener noreferrer nofollow">
                      <Building2 /> Company careers page
                    </a>
                  </Button>
                )}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 p-6 text-sm sm:grid-cols-3">
              {[
                ["Location", job.location, MapPin],
                ["Work mode", MODE[job.work_mode]?.label ?? "Not specified", Globe],
                ["Employment type", job.employment_type, Briefcase],
                ["Experience", job.experience, Clock],
                ["Salary", job.salary, Wallet],
                ["Date posted", job.date_posted ? fmtDate(job.date_posted) : "Not specified", CalendarDays],
              ].map(([label, value, Icon]) => {
                const I = Icon as typeof MapPin;
                return (
                  <div key={label as string} className="rounded-lg border bg-card p-3">
                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      <I className="h-3.5 w-3.5" /> {label as string}
                    </div>
                    <div className="mt-1 font-medium">{value as string}</div>
                  </div>
                );
              })}
            </div>

            {m && (
              <div className="space-y-5 px-6 pb-6">
                <section>
                  <h3 className="mb-2 text-sm font-semibold">Why this job matches</h3>
                  <p className="text-sm text-muted-foreground">{m.explanation}</p>
                  {m.experience_fit && <p className="mt-1 text-sm text-muted-foreground">{m.experience_fit}</p>}
                </section>

                {m.breakdown && (
                  <section className="space-y-2.5">
                    <h3 className="text-sm font-semibold">Score breakdown</h3>
                    {Object.entries(m.breakdown).map(([k, b]) => (
                      <div key={k}>
                        <div className="flex items-center justify-between text-xs">
                          <Tooltip content={b.note}>
                            <span className="cursor-help font-medium underline decoration-dotted underline-offset-2">{BREAKDOWN_LABEL[k] ?? k}</span>
                          </Tooltip>
                          <span className="tabular-nums text-muted-foreground">
                            {b.points} / {Math.round((b.weight / Object.values(m.breakdown!).reduce((a, x) => a + x.weight, 0)) * 100)} pts
                          </span>
                        </div>
                        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
                          <div className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-fuchsia-500" style={{ width: `${b.score}%` }} />
                        </div>
                      </div>
                    ))}
                  </section>
                )}

                <section className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
                      <CheckCircle2 className="h-4 w-4 text-emerald-500" /> Matched skills
                    </h3>
                    <div className="flex flex-wrap gap-1.5">
                      {m.matched_skills.length ? (
                        m.matched_skills.map((s) => (
                          <Badge key={s} variant="success">
                            {s}
                          </Badge>
                        ))
                      ) : (
                        <span className="text-xs text-muted-foreground">None detected</span>
                      )}
                    </div>
                  </div>
                  <div>
                    <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
                      <XCircle className="h-4 w-4 text-muted-foreground" /> Missing skills
                    </h3>
                    <div className="flex flex-wrap gap-1.5">
                      {m.missing_skills.length ? (
                        m.missing_skills.map((s) => (
                          <Badge key={s} variant="muted">
                            {s}
                          </Badge>
                        ))
                      ) : (
                        <span className="text-xs text-muted-foreground">None — you cover every listed skill</span>
                      )}
                    </div>
                  </div>
                </section>

                {m.gaps.length > 0 && (
                  <section className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4">
                    <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-amber-700 dark:text-amber-300">
                      <TriangleAlert className="h-4 w-4" /> Potential eligibility gaps
                    </h3>
                    <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                      {m.gaps.map((g) => (
                        <li key={g}>{g}</li>
                      ))}
                    </ul>
                  </section>
                )}

                <section className="rounded-lg border p-4">
                  <div className="flex items-center justify-between">
                    <h3 className="flex items-center gap-1.5 text-sm font-semibold">
                      <Sparkles className="h-4 w-4 text-primary" /> AI assessment
                    </h3>
                    {!m.llm_explanation && (
                      <Button size="sm" variant="outline" onClick={() => explain.mutate()} disabled={explain.isPending}>
                        {explain.isPending && <Loader2 className="animate-spin" />} Generate
                      </Button>
                    )}
                  </div>
                  <p className="mt-2 whitespace-pre-line text-sm text-muted-foreground">
                    {m.llm_explanation ?? "Optional narrative from the configured LLM. The score itself is deterministic and shown above."}
                  </p>
                </section>
              </div>
            )}

            <section className="border-t px-6 py-5">
              <h3 className="mb-3 text-sm font-semibold">Where this job was found</h3>
              <div className="space-y-2">
                {job.sources.map((s) => (
                  <div key={s.key + s.url} className="flex flex-wrap items-center gap-2 rounded-lg border p-3 text-sm">
                    {s.is_official ? (
                      <Badge variant="success">
                        <ShieldCheck /> Official company source
                      </Badge>
                    ) : (
                      <Badge variant="muted">Third-party job board</Badge>
                    )}
                    <span className="font-medium">{s.name}</span>
                    {s.status !== "active" && <Badge variant="destructive">no longer listed</Badge>}
                    <span className="text-xs text-muted-foreground">
                      first seen {timeAgo(s.first_seen_at)} · last seen {timeAgo(s.last_seen_at)}
                    </span>
                    {safeHref(s.url) && (
                      <a className="ml-auto inline-flex items-center gap-1 text-xs text-primary hover:underline" href={safeHref(s.url)} target="_blank" rel="noopener noreferrer nofollow">
                        Original listing <ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                  </div>
                ))}
              </div>
              <dl className="mt-4 grid grid-cols-2 gap-2 text-xs text-muted-foreground sm:grid-cols-3">
                <div>
                  <dt>Date discovered</dt>
                  <dd className="font-medium text-foreground">{fmtDate(job.first_seen_at)}</dd>
                </div>
                <div>
                  <dt>Last verified</dt>
                  <dd className="font-medium text-foreground">{job.last_verified_at ? fmtDate(job.last_verified_at) : "Not verified on an official source"}</dd>
                </div>
                <div>
                  <dt>Availability</dt>
                  <dd className="font-medium text-foreground">{job.status === "active" ? "Currently listed" : "No longer listed"}</dd>
                </div>
              </dl>
            </section>

            <section className="border-t px-6 py-5">
              <h3 className="mb-3 text-sm font-semibold">Job description</h3>
              {job.skills.length > 0 && (
                <div className="mb-3 flex flex-wrap gap-1.5">
                  {job.skills.map((s) => (
                    <Badge key={s} variant="secondary">
                      {s}
                    </Badge>
                  ))}
                </div>
              )}
              <div className="whitespace-pre-line text-sm leading-relaxed text-foreground/85">{job.description || "Not specified"}</div>
            </section>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
