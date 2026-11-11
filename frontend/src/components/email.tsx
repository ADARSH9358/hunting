"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, CircleDashed, Clock, ExternalLink, FileText, Loader2, Paperclip, Send, SkipForward, Sparkles, XCircle } from "lucide-react";
import { toast } from "sonner";
import { Badge, Button, Input, Label, NativeSelect, Sheet, SheetContent, Skeleton, Switch, Textarea } from "@/components/ui";
import { api, auth } from "@/lib/api";
import type { EmailStatus, EmailTemplate, GmailAccountsResp, JobEmail, ResumeFile } from "@/lib/types";
import { fmtDate, safeHref } from "@/lib/utils";

export const EMAIL_STATUS: Record<EmailStatus, { label: string; variant: "success" | "muted" | "warning" | "default" | "destructive" | "secondary"; icon: typeof CheckCircle2 }> = {
  pending: { label: "Pending", variant: "muted", icon: CircleDashed },
  ready: { label: "Ready to send", variant: "default", icon: Clock },
  sending: { label: "Sending", variant: "secondary", icon: Loader2 },
  sent: { label: "Sent", variant: "success", icon: CheckCircle2 },
  failed: { label: "Failed", variant: "destructive", icon: XCircle },
  skipped: { label: "Skipped", variant: "muted", icon: SkipForward },
};

export function EmailStatusBadge({ status }: { status: EmailStatus }) {
  const s = EMAIL_STATUS[status] ?? EMAIL_STATUS.pending;
  return (
    <Badge variant={s.variant}>
      <s.icon className={status === "sending" ? "animate-spin" : undefined} /> {s.label}
    </Badge>
  );
}

/** Fetch the attachment with the bearer token and open it in a new tab (no token in URLs). */
export async function openAttachment(emailId: number) {
  const win = window.open("", "_blank");
  try {
    const res = await fetch(`/api/job-emails/${emailId}/attachment`, { headers: { Authorization: `Bearer ${auth.get() ?? ""}` } });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d?.detail ?? "Could not load the resume");
    }
    const url = URL.createObjectURL(await res.blob());
    if (win) win.location.href = url;
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch (e) {
    win?.close();
    toast.error((e as Error).message);
  }
}

/** Preview / edit / send one application email. */
export function EmailComposer({ emailId, onClose }: { emailId: number | null; onClose: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["job-email", emailId], queryFn: () => api<JobEmail>(`/job-emails/${emailId}`), enabled: !!emailId });
  const accounts = useQuery({ queryKey: ["gmail-accounts"], queryFn: () => api<GmailAccountsResp>("/gmail/accounts"), enabled: !!emailId });
  const templates = useQuery({ queryKey: ["email-templates"], queryFn: () => api<EmailTemplate[]>("/email-templates"), enabled: !!emailId });
  const resumes = useQuery({ queryKey: ["resumes"], queryFn: () => api<ResumeFile[]>("/resume/history"), enabled: !!emailId });
  const e = q.data;
  const locked = e ? ["sent", "sending"].includes(e.status) : true;

  const [form, setForm] = useState({ recipient_email: "", hr_name: "", subject: "", body: "" });
  useEffect(() => {
    if (e) setForm({ recipient_email: e.recipient_email ?? "", hr_name: e.hr_name ?? "", subject: e.subject, body: e.body });
  }, [e]);
  const dirty = !!e && (form.recipient_email !== (e.recipient_email ?? "") || form.hr_name !== (e.hr_name ?? "") || form.subject !== e.subject || form.body !== e.body);

  const refresh = (data: JobEmail) => {
    qc.setQueryData(["job-email", emailId], data);
    qc.invalidateQueries({ queryKey: ["job-emails"] });
    qc.invalidateQueries({ queryKey: ["job-email-stats"] });
    qc.invalidateQueries({ queryKey: ["job-emails-for-job", data.job_id] });
  };
  const update = useMutation({
    mutationFn: (patch: Record<string, unknown>) => api<JobEmail>(`/job-emails/${emailId}`, { method: "PUT", body: JSON.stringify(patch) }),
    onSuccess: refresh,
    onError: (err) => toast.error((err as Error).message),
  });
  const saveText = () => {
    if (!e) return Promise.resolve(e);
    const patch: Record<string, string> = {};
    if (form.recipient_email !== (e.recipient_email ?? "")) patch.recipient_email = form.recipient_email;
    if (form.hr_name !== (e.hr_name ?? "")) patch.hr_name = form.hr_name;
    if (form.subject !== e.subject) patch.subject = form.subject;
    if (form.body !== e.body) patch.body = form.body;
    return Object.keys(patch).length ? update.mutateAsync(patch) : Promise.resolve(e);
  };
  const send = useMutation({
    mutationFn: async () => {
      await saveText();
      const path = e?.status === "failed" ? "retry" : "send";
      return api<JobEmail>(`/job-emails/${emailId}/${path}`, { method: "POST" });
    },
    onSuccess: (data) => {
      refresh(data);
      toast.success(`Application sent to ${data.recipient_email}`);
    },
    onError: (err) => {
      toast.error((err as Error).message);
      q.refetch();
      qc.invalidateQueries({ queryKey: ["job-emails"] });
    },
  });
  const skip = useMutation({
    mutationFn: () => api<JobEmail>(`/job-emails/${emailId}/skip`, { method: "POST" }),
    onSuccess: (d) => {
      refresh(d);
      toast("Marked as skipped");
      onClose();
    },
  });

  const noAccounts = accounts.data && accounts.data.accounts.filter((a) => a.is_connected).length === 0;
  return (
    <Sheet open={!!emailId} onOpenChange={(o) => !o && onClose()}>
      <SheetContent title="Application email">
        {!e ? (
          <div className="space-y-4 p-6">
            <Skeleton className="h-8 w-2/3" />
            <Skeleton className="h-64 w-full" />
          </div>
        ) : (
          <div className="flex flex-1 flex-col overflow-hidden">
            <div className="border-b p-6 pr-14">
              <div className="flex flex-wrap items-center gap-2">
                <EmailStatusBadge status={e.status} />
                {e.mode === "auto" && e.status === "sent" && <Badge variant="secondary">Sent automatically</Badge>}
                {e.match_score != null && <Badge variant="outline">{Math.round(e.match_score)}% match</Badge>}
              </div>
              <h2 className="mt-2 text-lg font-semibold leading-tight">{e.job_title}</h2>
              <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                <span className="font-medium text-foreground">{e.company_name}</span>
                {safeHref(e.job_url) && (
                  <a className="inline-flex items-center gap-1 text-primary hover:underline" href={safeHref(e.job_url)} target="_blank" rel="noopener noreferrer nofollow">
                    View posting <ExternalLink className="h-3 w-3" />
                  </a>
                )}
              </div>
              {e.status === "sent" && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Sent {fmtDate(e.sent_at)} from {e.sender_email} · Gmail message ID <span className="font-mono">{e.gmail_message_id}</span>
                </p>
              )}
              {e.status === "failed" && e.error_message && (
                <p className="mt-3 flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {e.error_message}
                </p>
              )}
            </div>

            <div className="flex-1 space-y-4 overflow-y-auto p-6 scrollbar-thin">
              {noAccounts && !locked && (
                <p className="rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm">
                  Connect a Gmail account in <a className="font-medium underline" href="/applications?tab=settings">Applications → Settings</a> before sending.
                </p>
              )}
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="to">To (HR / recruiter email)</Label>
                  <Input id="to" type="email" value={form.recipient_email} disabled={locked} placeholder="Not found in the posting – enter it"
                    onChange={(ev) => setForm({ ...form, recipient_email: ev.target.value })} />
                  <p className="text-xs text-muted-foreground">
                    {e.recipient_source === "posting" ? "Found in the job posting" : e.recipient_source === "manual" ? "Entered by you" : "No address in the posting – nothing is guessed"}
                  </p>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="hr">Recruiter name</Label>
                  <Input id="hr" value={form.hr_name} disabled={locked} placeholder="Hiring Manager" onChange={(ev) => setForm({ ...form, hr_name: ev.target.value })} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="from">Send from</Label>
                  <NativeSelect id="from" disabled={locked} value={e.sender_account_id ?? ""}
                    onChange={(ev) => ev.target.value && update.mutate({ sender_account_id: Number(ev.target.value) })}>
                    <option value="">Choose a Gmail account…</option>
                    {(accounts.data?.accounts ?? []).filter((a) => a.is_connected || a.id === e.sender_account_id).map((a) => (
                      <option key={a.id} value={a.id}>{a.email}</option>
                    ))}
                  </NativeSelect>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="tpl">Template</Label>
                  <NativeSelect id="tpl" disabled={locked} value={e.template_id ?? ""}
                    onChange={(ev) => {
                      if (!ev.target.value) return;
                      if (e.edited_by_user && !window.confirm("Switching template replaces your edited subject and message. Continue?")) return;
                      update.mutate({ template_id: Number(ev.target.value) });
                    }}>
                    {(templates.data ?? []).map((t) => (
                      <option key={t.id} value={t.id}>{t.name}{t.is_default ? " (default)" : ""}</option>
                    ))}
                  </NativeSelect>
                </div>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="subj">Subject</Label>
                <Input id="subj" value={form.subject} disabled={locked} onChange={(ev) => setForm({ ...form, subject: ev.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="body">Message</Label>
                <Textarea id="body" className="min-h-[280px] font-[inherit] leading-relaxed" value={form.body} disabled={locked}
                  onChange={(ev) => setForm({ ...form, body: ev.target.value })} />
              </div>

              <div className="flex flex-wrap items-center gap-3 rounded-lg border p-3 text-sm">
                <Paperclip className="h-4 w-4 text-muted-foreground" />
                <Switch checked={e.attach_resume} disabled={locked} onCheckedChange={(v) => update.mutate({ attach_resume: v })} aria-label="Attach resume" />
                <span>Attach resume</span>
                <NativeSelect className="h-8 w-auto max-w-[220px]" disabled={locked || !e.attach_resume} value={e.resume_id ?? ""}
                  onChange={(ev) => ev.target.value && update.mutate({ resume_id: Number(ev.target.value) })}>
                  {(resumes.data ?? []).map((r) => (
                    <option key={r.id} value={r.id}>{r.filename}</option>
                  ))}
                </NativeSelect>
                {e.attach_resume && e.resume_id && (
                  <Button size="sm" variant="ghost" onClick={() => openAttachment(e.id)}>
                    <FileText /> Preview
                  </Button>
                )}
              </div>
            </div>

            {!locked && (
              <div className="flex flex-wrap items-center gap-2 border-t bg-card p-4">
                <Button onClick={() => send.mutate()} disabled={send.isPending || !form.recipient_email || noAccounts}>
                  {send.isPending ? <Loader2 className="animate-spin" /> : <Send />} {e.status === "failed" ? "Retry send" : "Send email"}
                </Button>
                <Button variant="outline" disabled={!dirty || update.isPending} onClick={() => saveText().then(() => toast.success("Draft saved"))}>
                  Save draft
                </Button>
                {e.status !== "skipped" && (
                  <Button variant="ghost" onClick={() => skip.mutate()}>
                    <SkipForward /> Skip
                  </Button>
                )}
                <span className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
                  <Sparkles className="h-3 w-3" /> Nothing is sent until you click Send
                </span>
              </div>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
