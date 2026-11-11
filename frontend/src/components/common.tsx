"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { Badge, Card, Input } from "@/components/ui";
import { cn, scoreTone } from "@/lib/utils";

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function StatCard({
  label,
  value,
  icon: Icon,
  hint,
  tone = "primary",
}: {
  label: string;
  value: React.ReactNode;
  icon: React.ElementType;
  hint?: string;
  tone?: "primary" | "success" | "warning" | "fuchsia" | "sky";
}) {
  const tones = {
    primary: "from-indigo-500/15 to-indigo-500/5 text-indigo-600 dark:text-indigo-300",
    success: "from-emerald-500/15 to-emerald-500/5 text-emerald-600 dark:text-emerald-300",
    warning: "from-amber-500/15 to-amber-500/5 text-amber-600 dark:text-amber-300",
    fuchsia: "from-fuchsia-500/15 to-fuchsia-500/5 text-fuchsia-600 dark:text-fuchsia-300",
    sky: "from-sky-500/15 to-sky-500/5 text-sky-600 dark:text-sky-300",
  };
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-muted-foreground">{label}</p>
          <p className="mt-2 text-3xl font-semibold tabular-nums tracking-tight">{value}</p>
        </div>
        <div className={cn("grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br", tones[tone])}>
          <Icon className="h-5 w-5" />
        </div>
      </div>
      {hint && <p className="mt-3 text-xs text-muted-foreground">{hint}</p>}
    </Card>
  );
}

export function ScoreRing({ score, size = 56 }: { score: number; size?: number }) {
  const tone = scoreTone(score);
  const color = { success: "#10b981", primary: "#6366f1", warning: "#f59e0b", muted: "#94a3b8" }[tone];
  const r = (size - 8) / 2;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} aria-label={`Match ${Math.round(score)}%`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="currentColor" strokeWidth={5} className="text-muted" fill="none" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={color}
          strokeWidth={5}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c - (c * Math.min(100, score)) / 100}
          className="transition-all duration-700"
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center">
        <span className="text-sm font-semibold tabular-nums">{Math.round(score)}%</span>
      </div>
    </div>
  );
}

export function CompanyAvatar({ name, logo, className }: { name: string; logo?: string | null; className?: string }) {
  const [broken, setBroken] = useState(false);
  const initials = name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();
  const hue = [...name].reduce((a, ch) => a + ch.charCodeAt(0), 0) % 360;
  return logo && !broken ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={logo}
      alt=""
      referrerPolicy="no-referrer"
      onError={() => setBroken(true)}
      className={cn("h-11 w-11 shrink-0 rounded-xl border bg-white object-contain p-1", className)}
    />
  ) : (
    <div
      className={cn("grid h-11 w-11 shrink-0 place-items-center rounded-xl text-sm font-semibold text-white", className)}
      style={{ background: `linear-gradient(135deg, hsl(${hue} 70% 55%), hsl(${(hue + 40) % 360} 70% 45%))` }}
    >
      {initials || "?"}
    </div>
  );
}

export function SizeBadge({ size, label }: { size: string | null | undefined; label?: string }) {
  if (!size) return <Badge variant="muted">{label ?? "Size not verified"}</Badge>;
  const v = size === "small" ? "success" : size === "medium" ? "default" : "secondary";
  return <Badge variant={v}>{label ?? size}</Badge>;
}

export function EmptyState({ icon: Icon, title, description, action }: { icon: React.ElementType; title: string; description?: string; action?: React.ReactNode }) {
  return (
    <Card className="flex flex-col items-center justify-center gap-3 border-dashed px-6 py-16 text-center">
      <div className="grid h-12 w-12 place-items-center rounded-2xl bg-accent text-accent-foreground">
        <Icon className="h-6 w-6" />
      </div>
      <h3 className="text-base font-semibold">{title}</h3>
      {description && <p className="max-w-md text-sm text-muted-foreground">{description}</p>}
      {action}
    </Card>
  );
}

export function TagInput({
  value,
  onChange,
  placeholder,
  suggestions,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  suggestions?: string[];
}) {
  const [draft, setDraft] = useState("");
  const add = (t: string) => {
    const s = t.trim();
    if (s && !value.some((x) => x.toLowerCase() === s.toLowerCase())) onChange([...value, s]);
    setDraft("");
  };
  const remaining = (suggestions ?? []).filter((s) => !value.some((x) => x.toLowerCase() === s.toLowerCase())).slice(0, 8);
  return (
    <div className="space-y-2">
      <div className="flex min-h-9 flex-wrap items-center gap-1.5 rounded-lg border border-input bg-card p-1.5 shadow-sm focus-within:ring-2 focus-within:ring-ring">
        {value.map((t) => (
          <span key={t} className="inline-flex items-center gap-1 rounded-md bg-secondary px-2 py-0.5 text-xs font-medium">
            {t}
            <button type="button" aria-label={`Remove ${t}`} onClick={() => onChange(value.filter((x) => x !== t))} className="opacity-60 hover:opacity-100">
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              add(draft);
            } else if (e.key === "Backspace" && !draft && value.length) onChange(value.slice(0, -1));
          }}
          onBlur={() => draft && add(draft)}
          placeholder={value.length ? "" : placeholder}
          className="h-7 min-w-[120px] flex-1 border-0 bg-transparent px-1 shadow-none focus-visible:ring-0"
        />
      </div>
      {remaining.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {remaining.map((s) => (
            <button key={s} type="button" onClick={() => add(s)} className="rounded-md border border-dashed px-2 py-0.5 text-xs text-muted-foreground hover:border-primary hover:text-primary">
              + {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
