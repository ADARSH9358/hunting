"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Eye,
  Inbox,
  Loader2,
  Mail,
  PauseCircle,
  PlayCircle,
  Plus,
  RotateCw,
  Search,
  Send,
  ShieldCheck,
  Star,
  Trash2,
  Unplug,
} from "lucide-react";
import { toast } from "sonner";
import { EmptyState, PageHeader, StatCard } from "@/components/common";
import { EmailComposer, EmailStatusBadge } from "@/components/email";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
  NativeSelect,
  Skeleton,
  Switch,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
} from "@/components/ui";
import { api } from "@/lib/api";
import type { EmailSettings, EmailStats, EmailStatus, EmailTemplate, GmailAccountsResp, JobEmail, Page } from "@/lib/types";
import { cn, fmtDate, timeAgo } from "@/lib/utils";

const TABS = ["queue", "history", "templates", "settings"] as const;
type Tab = (typeof TABS)[number];

function ApplicationsInner() {
  const params = useSearchParams();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>((TABS as readonly string[]).includes(params.get("tab") ?? "") ? (params.get("tab") as Tab) : "queue");
  const [openId, setOpenId] = useState<number | null>(params.get("draft") ? Number(params.get("draft")) : null);
  const stats = useQuery({ queryKey: ["job-email-stats"], queryFn: () => api<EmailStats>("/job-emails/stats"), refetchInterval: 15_000 });

  // result of the Google OAuth round-trip
  useEffect(() => {
    const g = params.get("gmail");
    if (g === "connected") toast.success(`Gmail connected: ${params.get("account") ?? ""}`);
    if (g === "error") toast.error(params.get("message") ?? "Could not connect Gmail");
    if (g || params.get("draft")) router.replace(`/applications?tab=${params.get("tab") ?? "queue"}`, { scroll: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const s = stats.data;
  return (
    <div>
      <PageHeader
        title="Applications"
        description="Email recruiters straight from your Gmail – preview every message, or let approved automatic sending handle it."
        actions={
          s && (
            <Badge variant={s.auto_send_enabled ? "success" : "muted"} className="h-7 px-3">
              {s.auto_send_enabled ? <PlayCircle /> : <PauseCircle />} Auto-send {s.auto_send_enabled ? "on" : "off"}
            </Badge>
          )
        }
      />
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Ready to send" value={s?.by_status.ready ?? 0} icon={Inbox} />
        <StatCard label="Needs recipient" value={s?.by_status.pending ?? 0} icon={Mail} />
        <StatCard label="Sent (24h)" value={s ? `${s.sent_last_24h} / ${s.daily_limit}` : "–"} icon={Send} hint="vs. your automatic daily limit" />
        <StatCard label="Failed" value={s?.by_status.failed ?? 0} icon={RotateCw} />
      </div>

      <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)}>
        <TabsList className="mb-4">
          <TabsTrigger value="queue">Queue</TabsTrigger>
          <TabsTrigger value="history">History</TabsTrigger>
          <TabsTrigger value="templates">Templates</TabsTrigger>
          <TabsTrigger value="settings">Settings</TabsTrigger>
        </TabsList>
        <TabsContent value="queue">
          <EmailTable mode="queue" onOpen={setOpenId} />
        </TabsContent>
        <TabsContent value="history">
          <EmailTable mode="history" onOpen={setOpenId} />
        </TabsContent>
        <TabsContent value="templates">
          <Templates />
        </TabsContent>
        <TabsContent value="settings">
          <SettingsPanel />
        </TabsContent>
      </Tabs>
      <EmailComposer emailId={openId} onClose={() => setOpenId(null)} />
    </div>
  );
}

export default function ApplicationsPage() {
  return (
    <Suspense>
      <ApplicationsInner />
    </Suspense>
  );
}

/* ------------------------------------------------------------------ queue + history table */
function EmailTable({ mode, onOpen }: { mode: "queue" | "history"; onOpen: (id: number) => void }) {
  const qc = useQueryClient();
  const [status, setStatus] = useState<string>("");
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(1);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 300);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => setPage(1), [debounced, status, from, to]);

  const statuses: EmailStatus[] = status ? [status as EmailStatus] : mode === "queue" ? ["ready", "pending", "failed", "sending"] : ["sent", "failed", "skipped"];
  const list = useQuery({
    queryKey: ["job-emails", mode, statuses, debounced, from, to, page],
    queryFn: () => api<Page<JobEmail>>("/job-emails", { query: { status: statuses, q: debounced, date_from: from, date_to: to, page_no: page, page_size: 25 } }),
    placeholderData: keepPreviousData,
    refetchInterval: 15_000,
  });
  const retry = useMutation({
    mutationFn: (id: number) => api<JobEmail>(`/job-emails/${id}/retry`, { method: "POST" }),
    onSuccess: (d) => toast.success(`Sent to ${d.recipient_email}`),
    onError: (e) => toast.error((e as Error).message),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["job-emails"] });
      qc.invalidateQueries({ queryKey: ["job-email-stats"] });
    },
  });
  const settings = useQuery({ queryKey: ["email-settings"], queryFn: () => api<EmailSettings>("/job-emails/settings") });
  const runAuto = useMutation({
    mutationFn: () => api<{ queued: number }>("/job-emails/auto-send", { method: "POST" }),
    onSuccess: (d) => toast.success(d.queued ? `Sending ${d.queued} approved emails in the background (paced to respect Gmail limits)` : "Nothing qualifies for automatic sending right now"),
    onError: (e) => toast.error((e as Error).message),
  });

  const d = list.data;
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b p-3">
        <div className="relative min-w-[200px] flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-9" placeholder="Company, job title or recipient" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <NativeSelect className="w-auto" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
          <option value="">{mode === "queue" ? "All open" : "All finished"}</option>
          {(mode === "queue" ? ["ready", "pending", "failed"] : ["sent", "failed", "skipped"]).map((s) => (
            <option key={s} value={s}>{s[0].toUpperCase() + s.slice(1)}</option>
          ))}
        </NativeSelect>
        {mode === "history" && (
          <>
            <Input type="date" className="w-auto" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="From date" />
            <Input type="date" className="w-auto" value={to} onChange={(e) => setTo(e.target.value)} aria-label="To date" />
          </>
        )}
        {mode === "queue" && settings.data?.auto_send_enabled && (
          <Button size="sm" variant="outline" onClick={() => runAuto.mutate()} disabled={runAuto.isPending}>
            <PlayCircle /> Send approved queue now
          </Button>
        )}
      </div>
      {list.isLoading ? (
        <div className="space-y-2 p-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-12" />)}</div>
      ) : !d?.items.length ? (
        <EmptyState
          icon={mode === "queue" ? Inbox : Mail}
          title={mode === "queue" ? "No application emails waiting" : "No emails sent yet"}
          description={mode === "queue"
            ? "Each RUN drafts emails for matching jobs whose posting lists a recruiter email. You can also open any job and click “Email HR”."
            : "Sent and failed emails appear here with their Gmail message ID."}
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] text-sm">
            <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-4 py-2 font-medium">Company / job</th>
                <th className="px-4 py-2 font-medium">Recipient</th>
                <th className="px-4 py-2 font-medium">From · template</th>
                <th className="px-4 py-2 font-medium">Subject</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">{mode === "queue" ? "Updated" : "Sent"}</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y">
              {d.items.map((e) => (
                <tr key={e.id} className="cursor-pointer hover:bg-muted/40" onClick={() => onOpen(e.id)}>
                  <td className="px-4 py-3">
                    <div className="font-medium">{e.company_name}</div>
                    <div className="text-xs text-muted-foreground">
                      {e.job_title}
                      {e.match_score != null && <span className="ml-1">· {Math.round(e.match_score)}%</span>}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    {e.recipient_email ? (
                      <>
                        <div className="font-mono text-xs">{e.recipient_email}</div>
                        <div className="text-xs text-muted-foreground">{e.recipient_source === "posting" ? "from posting" : "entered by you"}</div>
                      </>
                    ) : (
                      <span className="text-xs text-amber-600">Not found – add manually</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs">
                    <div>{e.sender_email ?? <span className="text-muted-foreground">No account selected</span>}</div>
                    <div className="text-muted-foreground">{e.template_name}</div>
                  </td>
                  <td className="max-w-[240px] truncate px-4 py-3" title={e.subject}>{e.subject}</td>
                  <td className="px-4 py-3">
                    <EmailStatusBadge status={e.status} />
                    {e.mode === "auto" && e.status === "sent" && <div className="mt-1 text-[11px] text-muted-foreground">automatic</div>}
                    {e.status === "failed" && e.error_message && (
                      <div className="mt-1 max-w-[200px] truncate text-[11px] text-destructive" title={e.error_message}>{e.error_message}</div>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-xs text-muted-foreground">
                    {e.sent_at ? fmtDate(e.sent_at) : timeAgo(e.updated_at)}
                    {e.gmail_message_id && <div className="font-mono text-[10px]" title="Gmail message ID">{e.gmail_message_id}</div>}
                  </td>
                  <td className="px-4 py-3 text-right" onClick={(ev) => ev.stopPropagation()}>
                    {e.status === "failed" ? (
                      <Button size="sm" variant="outline" disabled={retry.isPending} onClick={() => retry.mutate(e.id)}>
                        <RotateCw /> Retry
                      </Button>
                    ) : (
                      <Button size="sm" variant="ghost" onClick={() => onOpen(e.id)}>
                        <Eye /> {e.status === "ready" || e.status === "pending" ? "Review" : "View"}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {d && d.pages > 1 && (
        <div className="flex items-center justify-end gap-2 border-t p-3 text-sm">
          <span className="text-muted-foreground">Page {d.page} of {d.pages}</span>
          <Button size="icon" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page"><ChevronLeft /></Button>
          <Button size="icon" variant="outline" disabled={page >= d.pages} onClick={() => setPage(page + 1)} aria-label="Next page"><ChevronRight /></Button>
        </div>
      )}
    </Card>
  );
}

/* ------------------------------------------------------------------ templates */
interface Draft {
  id?: number;
  name: string;
  subject: string;
  body: string;
  is_default: boolean;
}

function Templates() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["email-templates"], queryFn: () => api<EmailTemplate[]>("/email-templates") });
  const vars = useQuery({ queryKey: ["email-template-vars"], queryFn: () => api<{ name: string; description: string }[]>("/email-templates/variables") });
  const [draft, setDraft] = useState<Draft | null>(null);
  const [preview, setPreview] = useState<{ subject: string; body: string } | null>(null);
  useEffect(() => {
    if (!draft && list.data?.length) setDraft({ ...list.data[0] });
  }, [list.data, draft]);
  useEffect(() => setPreview(null), [draft?.id]);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["email-templates"] });
    qc.invalidateQueries({ queryKey: ["email-settings"] });
  };
  const save = useMutation({
    mutationFn: (d: Draft) => api<EmailTemplate>(d.id ? `/email-templates/${d.id}` : "/email-templates", { method: d.id ? "PUT" : "POST", body: JSON.stringify(d) }),
    onSuccess: (t) => {
      toast.success("Template saved");
      setDraft({ ...t });
      invalidate();
    },
    onError: (e) => toast.error((e as Error).message),
  });
  const remove = useMutation({
    mutationFn: (id: number) => api(`/email-templates/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Template deleted");
      setDraft(null);
      invalidate();
    },
    onError: (e) => toast.error((e as Error).message),
  });
  const makeDefault = useMutation({
    mutationFn: (id: number) => api(`/email-templates/${id}/default`, { method: "POST" }),
    onSuccess: () => {
      invalidate();
      setDraft((d) => (d ? { ...d, is_default: true } : d));
    },
  });
  const doPreview = useMutation({
    mutationFn: (d: Draft) => api<{ subject: string; body: string; unknown_variables: string[] }>("/email-templates/preview", { method: "POST", body: JSON.stringify({ subject: d.subject, body: d.body }) }),
    onSuccess: (r) => {
      setPreview(r);
      if (r.unknown_variables.length) toast.warning(`Unknown variables: ${r.unknown_variables.join(", ")}`);
    },
  });

  const insert = (name: string) => draft && setDraft({ ...draft, body: `${draft.body}{{${name}}}` });
  return (
    <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
      <Card className="h-fit p-2">
        {(list.data ?? []).map((t) => (
          <button key={t.id} onClick={() => setDraft({ ...t })}
            className={cn("flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-muted", draft?.id === t.id && "bg-accent font-medium")}>
            <span className="flex-1 truncate">{t.name}</span>
            {t.is_default && <Badge variant="default"><Star /> Default</Badge>}
          </button>
        ))}
        <Button variant="ghost" size="sm" className="mt-1 w-full justify-start" onClick={() => setDraft({ name: "New template", subject: "Application for {{job_title}} – {{candidate_name}}", body: "Dear {{hr_name}},\n\n", is_default: false })}>
          <Plus /> New template
        </Button>
      </Card>
      {draft && (
        <Card>
          <CardContent className="space-y-4 p-5">
            <div className="grid gap-4 sm:grid-cols-[1fr_auto] sm:items-end">
              <div className="space-y-1.5">
                <Label htmlFor="tname">Template name</Label>
                <Input id="tname" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
              </div>
              {draft.id && !draft.is_default && (
                <Button variant="outline" size="sm" onClick={() => makeDefault.mutate(draft.id!)}><Star /> Make default</Button>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tsubj">Subject</Label>
              <Input id="tsubj" value={draft.subject} onChange={(e) => setDraft({ ...draft, subject: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tbody">Message</Label>
              <Textarea id="tbody" className="min-h-[280px] leading-relaxed" value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} />
            </div>
            <div>
              <p className="mb-1.5 text-xs text-muted-foreground">Click a variable to insert it:</p>
              <div className="flex flex-wrap gap-1.5">
                {(vars.data ?? []).map((v) => (
                  <button key={v.name} title={v.description} onClick={() => insert(v.name)}
                    className="rounded-md border bg-muted/50 px-2 py-0.5 font-mono text-xs hover:bg-accent">{`{{${v.name}}}`}</button>
                ))}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => save.mutate(draft)} disabled={save.isPending}>{save.isPending && <Loader2 className="animate-spin" />} Save template</Button>
              <Button variant="outline" onClick={() => doPreview.mutate(draft)}><Eye /> Preview</Button>
              {draft.id && (
                <Button variant="ghost" className="ml-auto text-destructive" onClick={() => window.confirm(`Delete “${draft.name}”?`) && remove.mutate(draft.id!)}>
                  <Trash2 /> Delete
                </Button>
              )}
            </div>
            {preview && (
              <div className="rounded-lg border bg-muted/30 p-4">
                <p className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">Preview with your profile and your best-matching job</p>
                <p className="mb-3 font-medium">{preview.subject}</p>
                <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">{preview.body}</pre>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ settings */
function SettingsPanel() {
  const qc = useQueryClient();
  const accounts = useQuery({ queryKey: ["gmail-accounts"], queryFn: () => api<GmailAccountsResp>("/gmail/accounts") });
  const settings = useQuery({ queryKey: ["email-settings"], queryFn: () => api<EmailSettings>("/job-emails/settings") });
  const templates = useQuery({ queryKey: ["email-templates"], queryFn: () => api<EmailTemplate[]>("/email-templates") });
  const [limit, setLimit] = useState(10);
  const [minScore, setMinScore] = useState(60);
  const [resumeLink, setResumeLink] = useState("");
  useEffect(() => {
    if (settings.data) {
      setLimit(settings.data.daily_limit);
      setMinScore(settings.data.auto_min_score);
      setResumeLink(settings.data.resume_link ?? "");
    }
  }, [settings.data]);

  const put = useMutation({
    mutationFn: (patch: Partial<EmailSettings>) => api<EmailSettings>("/job-emails/settings", { method: "PUT", body: JSON.stringify(patch) }),
    onSuccess: (d) => {
      qc.setQueryData(["email-settings"], d);
      qc.invalidateQueries({ queryKey: ["job-email-stats"] });
      qc.invalidateQueries({ queryKey: ["gmail-accounts"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });
  const connect = useMutation({
    mutationFn: () => api<{ auth_url: string }>("/gmail/connect", { method: "POST" }),
    onSuccess: (d) => {
      window.location.href = d.auth_url;
    },
    onError: (e) => toast.error((e as Error).message),
  });
  const disconnect = useMutation({
    mutationFn: (id: number) => api(`/gmail/disconnect/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Gmail account disconnected and access revoked");
      qc.invalidateQueries({ queryKey: ["gmail-accounts"] });
      qc.invalidateQueries({ queryKey: ["email-settings"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const s = settings.data;
  const a = accounts.data;
  const connected = (a?.accounts ?? []).filter((x) => x.is_connected);
  const enableAuto = (v: boolean) => {
    if (v && !window.confirm(
      `Automatic sending will email recruiters for jobs matching ≥ ${minScore}% whose posting lists an email address, up to ${limit} per day, from ${connected.find((x) => x.id === s?.default_account_id)?.email ?? connected[0]?.email ?? "your Gmail"}.\n\nEach recruiter is emailed at most once per week. You can switch it off at any time.\n\nEnable automatic sending?`,
    )) return;
    put.mutate({ auto_send_enabled: v });
    toast(v ? "Automatic sending enabled" : "Automatic sending paused");
  };

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base"><Mail className="h-4 w-4" /> Gmail accounts</CardTitle>
          <CardDescription>Connected with Google OAuth. Only permission to <b>send</b> email is requested – the app cannot read your inbox. Tokens are encrypted and never leave the server.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {a && !a.configured && (
            <div className="rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm">
              <p className="font-medium">Gmail integration is not configured on the server.</p>
              <p className="mt-1 text-muted-foreground">
                Add <code>GOOGLE_CLIENT_ID</code> and <code>GOOGLE_CLIENT_SECRET</code> to the backend <code>.env</code> (see README → “Gmail setup”) and use this
                authorized redirect URI: <code className="break-all">{a.redirect_uri}</code>
              </p>
            </div>
          )}
          {(a?.accounts ?? []).map((acc) => (
            <div key={acc.id} className="flex flex-wrap items-center gap-3 rounded-lg border p-3 text-sm">
              <input type="radio" name="default-account" aria-label={`Send from ${acc.email} by default`} checked={s?.default_account_id === acc.id}
                disabled={!acc.is_connected} onChange={() => put.mutate({ default_account_id: acc.id })} />
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{acc.email}</div>
                <div className="text-xs text-muted-foreground">
                  {acc.is_connected ? `Connected ${timeAgo(acc.connected_at)}${acc.last_used_at ? ` · last sent ${timeAgo(acc.last_used_at)}` : ""}` : acc.last_error}
                </div>
              </div>
              {s?.default_account_id === acc.id && <Badge>Default sender</Badge>}
              {!acc.is_connected && <Badge variant="destructive">Reconnect needed</Badge>}
              <Button size="sm" variant="ghost" onClick={() => window.confirm(`Disconnect ${acc.email}? Google access will be revoked.`) && disconnect.mutate(acc.id)}>
                <Unplug /> Disconnect
              </Button>
            </div>
          ))}
          <Button onClick={() => connect.mutate()} disabled={connect.isPending || (a && !a.configured)}>
            {connect.isPending ? <Loader2 className="animate-spin" /> : <Plus />} {a?.accounts.length ? "Connect another Gmail" : "Connect Gmail"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base"><ShieldCheck className="h-4 w-4" /> Automatic sending</CardTitle>
          <CardDescription>Off by default. When on, each RUN emails recruiters for strong matches – only addresses found in the posting or entered by you, never guessed.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 text-sm">
          <div className={cn("flex items-center justify-between rounded-lg border p-3", s?.auto_send_enabled && "border-success/40 bg-success/5")}>
            <div>
              <div className="font-medium">{s?.auto_send_enabled ? "Automatic sending is ON" : "Automatic sending is OFF"}</div>
              <div className="text-xs text-muted-foreground">Switching it off pauses the queue immediately, even mid-run.</div>
            </div>
            <Switch checked={!!s?.auto_send_enabled} disabled={!connected.length} onCheckedChange={enableAuto} aria-label="Automatic sending" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="limit">Daily limit</Label>
              <Input id="limit" type="number" min={1} max={s?.daily_limit_max ?? 50} value={limit} onChange={(e) => setLimit(Number(e.target.value))}
                onBlur={() => s && limit !== s.daily_limit && put.mutate({ daily_limit: limit })} />
              <p className="text-xs text-muted-foreground">Max {s?.daily_limit_max ?? 50} (server cap)</p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="minscore">Minimum match score</Label>
              <Input id="minscore" type="number" min={0} max={100} value={minScore} onChange={(e) => setMinScore(Number(e.target.value))}
                onBlur={() => s && minScore !== s.auto_min_score && put.mutate({ auto_min_score: minScore })} />
              <p className="text-xs text-muted-foreground">Only for automatic sends</p>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="deftpl">Default template</Label>
            <NativeSelect id="deftpl" value={s?.default_template_id ?? templates.data?.find((t) => t.is_default)?.id ?? ""}
              onChange={(e) => put.mutate({ default_template_id: Number(e.target.value) })}>
              {(templates.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </NativeSelect>
          </div>
          <label className="flex items-center justify-between gap-3">
            <span>Attach my resume PDF by default</span>
            <Switch checked={!!s?.attach_resume} onCheckedChange={(v) => put.mutate({ attach_resume: v })} />
          </label>
          <label className="flex items-center justify-between gap-3">
            <span>Find recruiter emails and draft applications on every RUN</span>
            <Switch checked={!!s?.detect_on_run} onCheckedChange={(v) => put.mutate({ detect_on_run: v })} />
          </label>
          <div className="space-y-1.5">
            <Label htmlFor="rlink">Resume link (for {"{{resume_link}}"})</Label>
            <Input id="rlink" placeholder="https://drive.google.com/…" value={resumeLink} onChange={(e) => setResumeLink(e.target.value)}
              onBlur={() => s && resumeLink !== (s.resume_link ?? "") && put.mutate({ resume_link: resumeLink })} />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
