"use client";

import { useRouter } from "next/navigation";
import { useCallback, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FileText, Loader2, Lock, ShieldCheck, UploadCloud } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/common";
import { Badge, Button, Card, CardContent } from "@/components/ui";
import { api } from "@/lib/api";
import type { Profile } from "@/lib/types";
import { cn, fmtDate } from "@/lib/utils";

const MAX_MB = 5;

export default function UploadPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const history = useQuery({
    queryKey: ["resume-history"],
    queryFn: () => api<{ id: number; filename: string; uploaded_at: string; is_active: boolean }[]>("/resume/history"),
  });

  const upload = useMutation({
    mutationFn: (f: File) => {
      const fd = new FormData();
      fd.append("file", f);
      return api<Profile>("/resume/upload", { method: "POST", body: fd });
    },
    onSuccess: (p) => {
      qc.invalidateQueries();
      toast.success("Resume analysed", { description: `${p.skills.length} skills · ${p.experience_level}` });
      router.push("/analysis");
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const pick = useCallback((f?: File | null) => {
    if (!f) return;
    const ok = /\.(pdf|docx)$/i.test(f.name);
    if (!ok) return toast.error("Please upload a PDF or DOCX file");
    if (f.size > MAX_MB * 1024 * 1024) return toast.error(`File is larger than ${MAX_MB} MB`);
    setFile(f);
  }, []);

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Upload resume" description="PDF or DOCX, up to 5 MB. Uploading a new resume replaces the active profile." />
      <Card>
        <CardContent className="p-6">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDrag(true);
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDrag(false);
              pick(e.dataTransfer.files?.[0]);
            }}
            onClick={() => input.current?.click()}
            className={cn(
              "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed px-6 py-14 text-center transition-colors",
              drag ? "border-primary bg-accent" : "border-border hover:border-primary/60 hover:bg-muted/40",
            )}
          >
            <div className="grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-indigo-500 to-fuchsia-500 text-white shadow-lg shadow-indigo-500/30">
              <UploadCloud className="h-7 w-7" />
            </div>
            <div>
              <p className="font-semibold">Drop your resume here, or click to browse</p>
              <p className="mt-1 text-sm text-muted-foreground">Text-based PDF or Word (.docx)</p>
            </div>
            <input ref={input} type="file" accept=".pdf,.docx" className="hidden" onChange={(e) => pick(e.target.files?.[0])} />
          </div>

          {file && (
            <div className="mt-5 flex items-center gap-3 rounded-xl border p-4">
              <FileText className="h-8 w-8 text-primary" />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{file.name}</p>
                <p className="text-xs text-muted-foreground">{(file.size / 1024).toFixed(0)} KB</p>
              </div>
              <Button onClick={() => upload.mutate(file)} disabled={upload.isPending} variant="gradient">
                {upload.isPending ? <Loader2 className="animate-spin" /> : <CheckCircle2 />}
                {upload.isPending ? "Analysing…" : "Upload & analyse"}
              </Button>
            </div>
          )}

          <div className="mt-6 grid gap-3 text-xs text-muted-foreground sm:grid-cols-3">
            <div className="flex items-start gap-2">
              <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" /> Files are validated by content, not just extension.
            </div>
            <div className="flex items-start gap-2">
              <Lock className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" /> Stored privately with random names; optional encryption at rest.
            </div>
            <div className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" /> Nothing is invented — every skill is verified against your resume.
            </div>
          </div>
        </CardContent>
      </Card>

      {!!history.data?.length && (
        <Card className="mt-6">
          <CardContent className="p-5">
            <h3 className="mb-3 text-sm font-semibold">Upload history</h3>
            <ul className="divide-y text-sm">
              {history.data.map((r) => (
                <li key={r.id} className="flex items-center justify-between py-2">
                  <span className="flex items-center gap-2">
                    <FileText className="h-4 w-4 text-muted-foreground" /> {r.filename}
                    {r.is_active && <Badge variant="success">active</Badge>}
                  </span>
                  <span className="text-xs text-muted-foreground">{fmtDate(r.uploaded_at)}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
