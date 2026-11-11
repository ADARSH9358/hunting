"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Briefcase, Cpu, GraduationCap, Loader2, Plus, Save, Sparkles, Trash2, Upload, UserRound } from "lucide-react";
import { toast } from "sonner";
import { EmptyState, PageHeader, TagInput } from "@/components/common";
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, Label, NativeSelect, Skeleton, Textarea } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { EducationItem, ExperienceItem, Profile } from "@/lib/types";
import { months } from "@/lib/utils";

const CATEGORY_LABEL: Record<string, string> = {
  language: "Programming languages",
  framework: "Frameworks & libraries",
  database: "Databases",
  cloud: "Cloud",
  devops: "DevOps",
  ai_ml: "AI / ML",
  data: "Data",
  mobile: "Mobile",
  concept: "Concepts & practices",
  testing: "Testing",
  tool: "Tools",
  other: "Other",
};

export default function AnalysisPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["profile"], queryFn: () => api<Profile>("/resume/profile"), retry: false });
  const [draft, setDraft] = useState<Profile | null>(null);
  useEffect(() => {
    if (q.data) setDraft(structuredClone(q.data));
  }, [q.data]);

  const save = useMutation({
    mutationFn: (p: Profile) =>
      api<Profile>("/resume/profile", {
        method: "PUT",
        body: JSON.stringify({
          candidate: p.candidate,
          email: p.email,
          phone: p.phone,
          location: p.location,
          summary: p.summary,
          experience: p.experience.map(({ title, company, start, end, employment_type, responsibilities }) => ({
            title, company, start, end, employment_type, responsibilities: responsibilities ?? [],
          })),
          education: p.education.map(({ degree, institution, year }) => ({ degree, institution, year })),
          skills: p.skills,
          certifications: p.certifications,
          job_roles: p.job_roles,
          preferred_industries: p.preferred_industries,
          transferable_skills: p.transferable_skills,
        }),
      }),
    onSuccess: (p) => {
      qc.setQueryData(["profile"], p);
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast.success("Profile saved", { description: "Your next RUN will use the updated profile." });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  if (q.error && (q.error as ApiError).status === 404)
    return (
      <EmptyState
        icon={Upload}
        title="No resume yet"
        description="Upload a resume to see its AI analysis."
        action={
          <Button asChild>
            <Link href="/upload">Upload resume</Link>
          </Button>
        }
      />
    );
  if (!draft) return <Skeleton className="h-96 w-full" />;

  const set = <K extends keyof Profile>(k: K, v: Profile[K]) => setDraft({ ...draft, [k]: v });
  const setExp = (i: number, patch: Partial<ExperienceItem>) =>
    set("experience", draft.experience.map((e, j) => (j === i ? { ...e, ...patch } : e)));
  const setEdu = (i: number, patch: Partial<EducationItem>) =>
    set("education", draft.education.map((e, j) => (j === i ? { ...e, ...patch } : e)));

  return (
    <div className="space-y-6">
      <PageHeader
        title="Resume analysis"
        description="Review and correct what we extracted. Everything here was found in your resume — nothing is invented."
        actions={
          <>
            <Badge variant={draft.analysis_method === "llm" ? "default" : "secondary"}>
              <Sparkles /> {draft.analysis_method === "llm" ? "AI-extracted (verified)" : "Rule-based extraction"}
            </Badge>
            {draft.edited_by_user && <Badge variant="outline">edited by you</Badge>}
            <Button onClick={() => save.mutate(draft)} disabled={save.isPending}>
              {save.isPending ? <Loader2 className="animate-spin" /> : <Save />} Save changes
            </Button>
          </>
        }
      />

      <div className="grid gap-4 md:grid-cols-4">
        {[
          ["Experience level", draft.experience_level ?? "—"],
          ["Professional experience", months(draft.professional_experience_months)],
          ["Internship experience", months(draft.internship_experience_months)],
          ["Relevant (tech) experience", months(draft.relevant_experience_months)],
        ].map(([l, v]) => (
          <Card key={l} className="p-4">
            <p className="text-xs text-muted-foreground">{l}</p>
            <p className="mt-1 text-lg font-semibold">{v}</p>
          </Card>
        ))}
      </div>
      <p className="-mt-3 text-xs text-muted-foreground">
        Internships and full-time roles are counted separately. For matching, internships count at 50% toward a job&apos;s experience requirement.
      </p>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <UserRound className="h-4 w-4" /> Candidate
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {(["candidate", "email", "phone", "location"] as const).map((k) => (
              <div key={k} className="space-y-1.5">
                <Label className="capitalize">{k === "candidate" ? "Name" : k}</Label>
                <Input value={(draft[k] as string) ?? ""} onChange={(e) => set(k, e.target.value)} />
              </div>
            ))}
            <div className="space-y-1.5">
              <Label>Summary</Label>
              <Textarea value={draft.summary ?? ""} onChange={(e) => set("summary", e.target.value)} rows={4} />
            </div>
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Cpu className="h-4 w-4" /> Skills ({draft.skills.length})
            </CardTitle>
            <CardDescription>Used for matching. Add skills you actually have; remove anything incorrect.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <TagInput value={draft.skills} onChange={(v) => set("skills", v)} placeholder="Add a skill and press Enter" />
            <div className="grid gap-3 sm:grid-cols-2">
              {Object.entries(draft.skills_by_category ?? {}).map(([cat, list]) => (
                <div key={cat}>
                  <p className="mb-1 text-xs font-medium text-muted-foreground">{CATEGORY_LABEL[cat] ?? cat}</p>
                  <div className="flex flex-wrap gap-1">
                    {list.map((s) => (
                      <Badge key={s} variant="secondary">
                        {s}
                      </Badge>
                    ))}
                  </div>
                </div>
              ))}
            </div>
            <div className="space-y-1.5 border-t pt-4">
              <Label>Target job roles</Label>
              <TagInput value={draft.job_roles} onChange={(v) => set("job_roles", v)} placeholder="e.g. Backend Developer" />
            </div>
            <div className="space-y-1.5">
              <Label>Transferable skills</Label>
              <TagInput value={draft.transferable_skills} onChange={(v) => set("transferable_skills", v)} />
            </div>
            <div className="space-y-1.5">
              <Label>Preferred industries</Label>
              <TagInput value={draft.preferred_industries} onChange={(v) => set("preferred_industries", v)} />
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-base">
            <Briefcase className="h-4 w-4" /> Experience
          </CardTitle>
          <Button size="sm" variant="outline" onClick={() => set("experience", [...draft.experience, { title: "", company: "", start: "", end: "Present", employment_type: "full_time", responsibilities: [] }])}>
            <Plus /> Add role
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {draft.experience.length === 0 && <p className="text-sm text-muted-foreground">No dated roles were detected. Add them manually for accurate experience matching.</p>}
          {draft.experience.map((e, i) => (
            <div key={i} className="rounded-xl border p-4">
              <div className="grid gap-3 md:grid-cols-6">
                <div className="space-y-1 md:col-span-2">
                  <Label className="text-xs">Title</Label>
                  <Input value={e.title ?? ""} onChange={(ev) => setExp(i, { title: ev.target.value })} />
                </div>
                <div className="space-y-1 md:col-span-2">
                  <Label className="text-xs">Company</Label>
                  <Input value={e.company ?? ""} onChange={(ev) => setExp(i, { company: ev.target.value })} />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Start</Label>
                  <Input placeholder="Jan 2023" value={e.start ?? ""} onChange={(ev) => setExp(i, { start: ev.target.value })} />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">End</Label>
                  <Input placeholder="Present" value={e.end ?? ""} onChange={(ev) => setExp(i, { end: ev.target.value })} />
                </div>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <NativeSelect className="w-44" value={e.employment_type ?? "full_time"} onChange={(ev) => setExp(i, { employment_type: ev.target.value as ExperienceItem["employment_type"] })}>
                  <option value="full_time">Full-time</option>
                  <option value="internship">Internship</option>
                  <option value="contract">Contract</option>
                  <option value="part_time">Part-time</option>
                  <option value="freelance">Freelance</option>
                </NativeSelect>
                {e.months != null && <Badge variant="secondary">{months(e.months)}</Badge>}
                {e.relevant && <Badge variant="success">tech-relevant</Badge>}
                <Button size="sm" variant="ghost" className="ml-auto text-destructive" onClick={() => set("experience", draft.experience.filter((_, j) => j !== i))}>
                  <Trash2 /> Remove
                </Button>
              </div>
              {!!e.responsibilities?.length && (
                <ul className="mt-3 list-disc space-y-0.5 pl-5 text-sm text-muted-foreground">
                  {e.responsibilities.map((r, k) => (
                    <li key={k}>{r}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-base">
              <GraduationCap className="h-4 w-4" /> Education
            </CardTitle>
            <Button size="sm" variant="outline" onClick={() => set("education", [...draft.education, { degree: "", institution: "", year: "" }])}>
              <Plus /> Add
            </Button>
          </CardHeader>
          <CardContent className="space-y-3">
            {draft.education.map((e, i) => (
              <div key={i} className="grid grid-cols-6 gap-2">
                <Input className="col-span-3" placeholder="Degree" value={e.degree ?? ""} onChange={(ev) => setEdu(i, { degree: ev.target.value })} />
                <Input className="col-span-2" placeholder="Institution" value={e.institution ?? ""} onChange={(ev) => setEdu(i, { institution: ev.target.value })} />
                <Input placeholder="Year" value={e.year ?? ""} onChange={(ev) => setEdu(i, { year: ev.target.value })} />
              </div>
            ))}
            <p className="text-xs text-muted-foreground">Highest level detected: {draft.education_level ?? "not detected"}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Projects & certifications</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {draft.projects.map((p, i) => (
              <div key={i} className="rounded-lg border p-3">
                <p className="font-medium">{p.name}</p>
                {p.description && <p className="mt-1 text-sm text-muted-foreground">{p.description}</p>}
                <div className="mt-2 flex flex-wrap gap-1">
                  {p.technologies.map((t) => (
                    <Badge key={t} variant="secondary">
                      {t}
                    </Badge>
                  ))}
                </div>
              </div>
            ))}
            <div className="space-y-1.5">
              <Label>Certifications</Label>
              <TagInput value={draft.certifications} onChange={(v) => set("certifications", v)} />
            </div>
            {draft.previous_companies.length > 0 && (
              <p className="text-xs text-muted-foreground">Previous companies: {draft.previous_companies.join(", ")}</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
