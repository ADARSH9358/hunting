"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleDashed, KeyRound, Loader2, Monitor, Moon, PlugZap, ShieldCheck, Sun, TriangleAlert } from "lucide-react";
import { useTheme } from "next-themes";
import { toast } from "sonner";
import { PageHeader } from "@/components/common";
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, Label, Switch } from "@/components/ui";
import { api } from "@/lib/api";
import type { SourceRow } from "@/lib/types";
import { cn, timeAgo } from "@/lib/utils";

interface SettingsResp {
  small_company_max: number;
  medium_company_max: number;
  llm_provider: string;
  task_backend: string;
  database: string;
  resume_encryption: boolean;
}

const STATUS: Record<string, { label: string; variant: "success" | "muted" | "warning" | "default" | "secondary"; icon: typeof CheckCircle2 }> = {
  ok: { label: "Working", variant: "success", icon: CheckCircle2 },
  available: { label: "Ready", variant: "default", icon: CheckCircle2 },
  needs_credentials: { label: "Needs API key", variant: "muted", icon: KeyRound },
  via_provider: { label: "Via licensed provider", variant: "secondary", icon: PlugZap },
  error: { label: "Error", variant: "warning", icon: TriangleAlert },
  timeout: { label: "Timeout", variant: "warning", icon: TriangleAlert },
  blocked: { label: "Not permitted", variant: "warning", icon: TriangleAlert },
};

export default function SettingsPage() {
  const qc = useQueryClient();
  const { theme, setTheme } = useTheme();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<SettingsResp>("/settings") });
  const sources = useQuery({ queryKey: ["sources"], queryFn: () => api<SourceRow[]>("/sources") });
  const [small, setSmall] = useState(50);
  const [medium, setMedium] = useState(500);
  useEffect(() => {
    if (settings.data) {
      setSmall(settings.data.small_company_max);
      setMedium(settings.data.medium_company_max);
    }
  }, [settings.data]);

  const saveSizes = useMutation({
    mutationFn: () => api("/settings", { method: "PUT", body: JSON.stringify({ small_company_max: small, medium_company_max: medium }) }),
    onSuccess: () => {
      toast.success("Company size ranges updated");
      qc.invalidateQueries();
    },
    onError: (e) => toast.error((e as Error).message),
  });
  const toggle = useMutation({
    mutationFn: ({ key, enabled }: { key: string; enabled: boolean }) => api(`/sources/${key}`, { method: "PUT", query: { enabled } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }),
  });

  const groups: [string, (s: SourceRow) => boolean][] = [
    ["Official company sources (ATS boards & career pages)", (s) => s.is_official_company_source],
    ["Job boards & aggregators", (s) => !s.is_official_company_source && ["job_board_api", "aggregator", "licensed"].includes(s.kind)],
    ["Major portals (no public API — covered via licensed providers)", (s) => s.kind === "portal"],
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="Settings" />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Appearance</CardTitle>
          </CardHeader>
          <CardContent className="flex gap-2">
            {[
              ["light", Sun, "Light"],
              ["dark", Moon, "Dark"],
              ["system", Monitor, "System"],
            ].map(([k, Icon, l]) => {
              const I = Icon as typeof Sun;
              return (
                <button
                  key={k as string}
                  onClick={() => setTheme(k as string)}
                  className={cn("flex flex-1 flex-col items-center gap-1 rounded-lg border p-3 text-xs", theme === k ? "border-primary bg-primary/10 text-primary" : "hover:bg-muted")}
                >
                  <I className="h-4 w-4" /> {l as string}
                </button>
              );
            })}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Company size ranges</CardTitle>
            <CardDescription>Small: 1–{small} · Medium: {small + 1}–{medium} · Large: {medium + 1}+</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label className="text-xs">Small up to</Label>
                <Input type="number" min={1} value={small} onChange={(e) => setSmall(Number(e.target.value))} />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Medium up to</Label>
                <Input type="number" min={2} value={medium} onChange={(e) => setMedium(Number(e.target.value))} />
              </div>
            </div>
            <Button size="sm" onClick={() => saveSizes.mutate()} disabled={saveSizes.isPending}>
              {saveSizes.isPending && <Loader2 className="animate-spin" />} Save ranges
            </Button>
            <p className="text-xs text-muted-foreground">Sizes are only assigned when a verified employee count exists — otherwise “Size not verified”.</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">System</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {settings.data && (
              <>
                <Row label="LLM provider" value={settings.data.llm_provider === "none" ? "Not configured (rule-based)" : settings.data.llm_provider} ok={settings.data.llm_provider !== "none"} />
                <Row label="Background tasks" value={settings.data.task_backend} ok />
                <Row label="Database" value={settings.data.database} ok={settings.data.database === "postgresql"} />
                <Row label="Resume encryption" value={settings.data.resume_encryption ? "Enabled" : "Disabled"} ok={settings.data.resume_encryption} />
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldCheck className="h-4 w-4" /> Job sources & integrations
          </CardTitle>
          <CardDescription>
            Only official APIs, public job feeds, licensed providers and robots.txt-permitted career pages are used. No CAPTCHA, login or anti-bot bypassing. Add API keys in
            the backend <code>.env</code> to enable keyed sources.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {groups.map(([title, pred]) => (
            <div key={title}>
              <h3 className="mb-2 text-sm font-semibold">{title}</h3>
              <div className="divide-y rounded-lg border">
                {(sources.data ?? []).filter(pred).map((s) => {
                  const st = STATUS[s.status] ?? { label: s.status, variant: "muted" as const, icon: CircleDashed };
                  return (
                    <div key={s.key} className="flex flex-wrap items-center gap-3 p-3 text-sm">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">{s.name}</span>
                          <Badge variant={st.variant}>
                            <st.icon /> {st.label}
                          </Badge>
                          {s.last_run_at && s.status === "ok" && <span className="text-xs text-muted-foreground">{s.last_job_count} jobs · {timeAgo(s.last_run_at)}</span>}
                        </div>
                        {s.notes && <p className="mt-0.5 text-xs text-muted-foreground">{s.notes}</p>}
                        {s.last_error && s.status !== "ok" && <p className="mt-0.5 text-xs text-amber-600">{s.last_error}</p>}
                      </div>
                      {s.kind !== "portal" && (
                        <Switch checked={s.enabled} onCheckedChange={(v) => toggle.mutate({ key: s.key, enabled: v })} aria-label={`Enable ${s.name}`} />
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

function Row({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("font-medium", ok ? "text-foreground" : "text-amber-600")}>{value}</span>
    </div>
  );
}
