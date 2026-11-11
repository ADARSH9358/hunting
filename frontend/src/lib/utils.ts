import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

function toDate(iso: string): Date {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z");
}

export function timeAgo(iso?: string | null): string {
  if (!iso) return "Not specified";
  const s = Math.floor((Date.now() - toDate(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const days = Math.floor(h / 24);
  if (days < 30) return `${days}d ago`;
  return toDate(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function fmtDate(iso?: string | null): string {
  if (!iso) return "Not specified";
  return toDate(iso).toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function months(m?: number | null): string {
  if (!m) return "0 mo";
  const y = Math.floor(m / 12);
  const r = m % 12;
  return [y ? `${y} yr${y > 1 ? "s" : ""}` : "", r ? `${r} mo` : ""].filter(Boolean).join(" ");
}

export function scoreTone(score: number): "success" | "primary" | "warning" | "muted" {
  if (score >= 75) return "success";
  if (score >= 60) return "primary";
  if (score >= 40) return "warning";
  return "muted";
}

export function safeHref(url?: string | null): string | undefined {
  if (!url) return undefined;
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:" ? u.toString() : undefined;
  } catch {
    return undefined;
  }
}
