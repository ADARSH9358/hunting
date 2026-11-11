"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Save, SlidersHorizontal, Wand2 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader, TagInput } from "@/components/common";
import { RunPanel } from "@/components/run-panel";
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, Label, NativeSelect, Switch } from "@/components/ui";
import { api } from "@/lib/api";
import type { DashboardStats, Preferences } from "@/lib/types";
import { cn } from "@/lib/utils";

type PrefResponse = Preferences & { suggested: Preferences };
const SIZES = [
  ["small", "Small (1–50)"],
  ["medium", "Medium (51–500)"],
  ["large", "Large (501+)"],
  ["unknown", "Size not verified"],
] as const;
const WEIGHTS = [
  ["skills", "Technical skills", 35],
  ["experience", "Relevant experience", 25],
  ["role", "Role compatibility", 20],
  ["education", "Education", 10],
  ["location", "Location & work preference", 10],
] as const;

export default function FindJobsPage() {
  const qc = useQueryClient();
  const stats = useQuery({ queryKey: ["dashboard"], queryFn: () => api<DashboardStats>("/dashboard/stats") });
  const prefs = useQuery({ queryKey: ["preferences"], queryFn: () => api<PrefResponse>("/resume/preferences"), retry: false });
  const [p, setP] = useState<Preferences | null>(null);
  useEffect(() => {
    if (prefs.data) {
      const { suggested: _s, ...rest } = prefs.data;
      void _s;
      setP(rest);
    }
  }, [prefs.data]);

  const save = useMutation({
    mutationFn: (v: Preferences) => api<Preferences>("/resume/preferences", { method: "PUT", body: JSON.stringify(v) }),
    onSuccess: () => {
      toast.success("Search preferences saved");
      qc.invalidateQueries({ queryKey: ["preferences"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const set = <K extends keyof Preferences>(k: K, v: Preferences[K]) => p && setP({ ...p, [k]: v });
  const weights = { ...Object.fromEntries(WEIGHTS.map(([k, , d]) => [k, d])), ...(p?.weights ?? {}) } as Record<string, number>;

  return (
    <div className="space-y-6">
      <PageHeader title="Find jobs" description="Press RUN for a fresh search. Press it again any time to discover newly posted jobs." />
      <RunPanel lastRun={stats.data?.last_completed_search?.finished_at} />

      {prefs.isError && <p className="text-sm text-muted-foreground">Upload a resume to configure your search.</p>}
      {p && (
        <Card>
          <CardHeader className="flex-row items-start justify-between gap-4">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <SlidersHorizontal className="h-4 w-4" /> Search configuration
              </CardTitle>
              <CardDescription>Suggested from your resume — adjust anything. Saved settings apply to every RUN.</CardDescription>
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  if (prefs.data) setP({ ...p, ...prefs.data.suggested });
                  toast.message("Suggestions from your resume applied — save to keep them.");
                }}
              >
                <Wand2 /> Use suggestions
              </Button>
              <Button size="sm" onClick={() => save.mutate(p)} disabled={save.isPending}>
                {save.isPending ? <Loader2 className="animate-spin" /> : <Save />} Save
              </Button>
            </div>
          </CardHeader>
          <CardContent className="grid gap-6 lg:grid-cols-2">
            <div className="space-y-5">
              <div className="space-y-1.5">
                <Label>Preferred job roles</Label>
                <TagInput value={p.preferred_roles} onChange={(v) => set("preferred_roles", v)} suggestions={prefs.data?.suggested.preferred_roles} placeholder="e.g. Backend Developer" />
              </div>
              <div className="space-y-1.5">
                <Label>Preferred technologies</Label>
                <TagInput value={p.preferred_technologies} onChange={(v) => set("preferred_technologies", v)} suggestions={prefs.data?.suggested.preferred_technologies} />
              </div>
              <div className="space-y-1.5">
                <Label>Preferred locations</Label>
                <TagInput value={p.preferred_locations} onChange={(v) => set("preferred_locations", v)} placeholder="e.g. Bengaluru, Pune, Remote" />
              </div>
              <div className="space-y-1.5">
                <Label>Countries (for remote-region checks)</Label>
                <TagInput value={p.countries} onChange={(v) => set("countries", v)} placeholder="e.g. India" />
              </div>
            </div>
            <div className="space-y-5">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label>Min experience (yrs)</Label>
                  <Input type="number" min={0} max={50} step={0.5} value={p.min_experience_years} onChange={(e) => set("min_experience_years", Number(e.target.value))} />
                </div>
                <div className="space-y-1.5">
                  <Label>Max experience (yrs)</Label>
                  <Input type="number" min={0} max={50} step={0.5} value={p.max_experience_years} onChange={(e) => set("max_experience_years", Number(e.target.value))} />
                </div>
                <div className="space-y-1.5">
                  <Label>Work mode</Label>
                  <NativeSelect value={p.remote_preference} onChange={(e) => set("remote_preference", e.target.value as Preferences["remote_preference"])}>
                    <option value="any">Any</option>
                    <option value="remote">Remote</option>
                    <option value="hybrid">Hybrid</option>
                    <option value="onsite">Onsite</option>
                  </NativeSelect>
                </div>
                <div className="space-y-1.5">
                  <Label>Posted within</Label>
                  <NativeSelect value={p.posted_within_days} onChange={(e) => set("posted_within_days", Number(e.target.value))}>
                    {[1, 3, 7, 14, 30, 60, 90].map((d) => (
                      <option key={d} value={d}>
                        {d === 1 ? "24 hours" : `${d} days`}
                      </option>
                    ))}
                  </NativeSelect>
                </div>
              </div>
              <div className="space-y-1.5">
                <Label>Minimum match score: {p.min_match_score}%</Label>
                <input type="range" min={0} max={95} step={5} value={p.min_match_score} onChange={(e) => set("min_match_score", Number(e.target.value))} className="w-full accent-[hsl(var(--primary))]" />
              </div>
              <div className="space-y-2">
                <Label>Company sizes to search</Label>
                <div className="flex flex-wrap gap-2">
                  {SIZES.map(([k, label]) => {
                    const on = p.company_sizes.includes(k);
                    return (
                      <button
                        key={k}
                        type="button"
                        onClick={() => set("company_sizes", on ? p.company_sizes.filter((x) => x !== k) : [...p.company_sizes, k])}
                        className={cn("rounded-full border px-3 py-1 text-xs font-medium transition-colors", on ? "border-primary bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted")}
                      >
                        {label}
                      </button>
                    );
                  })}
                </div>
              </div>
              <div className="flex items-center justify-between rounded-lg border p-3">
                <div>
                  <p className="text-sm font-medium">Prioritise small & medium companies</p>
                  <p className="text-xs text-muted-foreground">Their career pages are checked first on every RUN.</p>
                </div>
                <Switch checked={p.prioritize_small_medium} onCheckedChange={(v) => set("prioritize_small_medium", v)} />
              </div>
              <details className="rounded-lg border p-3">
                <summary className="cursor-pointer text-sm font-medium">Matching weights (advanced)</summary>
                <div className="mt-3 space-y-2">
                  {WEIGHTS.map(([k, label]) => (
                    <div key={k} className="flex items-center gap-3 text-sm">
                      <span className="w-48 text-muted-foreground">{label}</span>
                      <input
                        type="range"
                        min={0}
                        max={60}
                        value={weights[k]}
                        onChange={(e) => set("weights", { ...weights, [k]: Number(e.target.value) })}
                        className="flex-1 accent-[hsl(var(--primary))]"
                      />
                      <span className="w-8 text-right tabular-nums">{weights[k]}</span>
                    </div>
                  ))}
                  <p className="text-xs text-muted-foreground">Weights are normalised to 100. Scores are recomputed on the next RUN.</p>
                </div>
              </details>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
