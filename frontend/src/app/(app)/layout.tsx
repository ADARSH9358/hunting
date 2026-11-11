"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTheme } from "next-themes";
import {
  Bookmark,
  Briefcase,
  Building2,
  FileSearch,
  History,
  LayoutDashboard,
  LogOut,
  Mail,
  Menu,
  Moon,
  Play,
  Radar,
  Settings,
  Sun,
  Upload,
  X,
} from "lucide-react";
import { Button, Progress } from "@/components/ui";
import { api, auth } from "@/lib/api";
import type { SearchSession } from "@/lib/types";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/upload", label: "Upload Resume", icon: Upload },
  { href: "/analysis", label: "Resume Analysis", icon: FileSearch },
  { href: "/find", label: "Find Jobs", icon: Play },
  { href: "/jobs", label: "All Jobs", icon: Briefcase },
  { href: "/saved", label: "Saved Jobs", icon: Bookmark },
  { href: "/applications", label: "Applications", icon: Mail },
  { href: "/companies", label: "Companies", icon: Building2 },
  { href: "/history", label: "Search History", icon: History },
  { href: "/settings", label: "Settings", icon: Settings },
];

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return (
    <Button variant="ghost" size="icon" aria-label="Toggle theme" onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}>
      {mounted && resolvedTheme === "dark" ? <Sun /> : <Moon />}
    </Button>
  );
}

function ActiveSearchPill() {
  const { data } = useQuery({
    queryKey: ["search", "active", "pill"],
    queryFn: () => api<SearchSession | null>("/search/active"),
    refetchInterval: 4000,
  });
  if (!data) return null;
  return (
    <Link href="/find" className="hidden items-center gap-3 rounded-full border bg-card px-3 py-1.5 text-xs shadow-sm md:flex">
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
      </span>
      <span className="max-w-[220px] truncate text-muted-foreground">{data.current_step ?? "Searching…"}</span>
      <Progress value={data.progress} className="h-1.5 w-20" />
    </Link>
  );
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [open, setOpen] = useState(false);
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<{ email: string; full_name?: string }>("/auth/me"), enabled: ready });

  useEffect(() => {
    if (!auth.get()) router.replace("/login");
    else setReady(true);
  }, [router]);
  useEffect(() => setOpen(false), [pathname]);

  if (!ready) return null;

  const sidebar = (
    <nav className="flex h-full flex-col gap-1 p-3">
      <Link href="/dashboard" className="mb-4 flex items-center gap-2.5 px-3 py-2 text-[15px] font-semibold">
        <div className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-indigo-600 to-fuchsia-600 text-white shadow-md shadow-indigo-500/30">
          <Radar className="h-4 w-4" />
        </div>
        JobHunt AI
      </Link>
      {NAV.map(({ href, label, icon: Icon }) => {
        const activeLink = pathname === href || pathname.startsWith(href + "/");
        return (
          <Link
            key={href}
            href={href}
            className={cn(
              "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
              activeLink ? "bg-accent text-accent-foreground" : "text-sidebar-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <Icon className="h-4 w-4" />
            {label}
          </Link>
        );
      })}
      <div className="mt-auto space-y-2 border-t pt-3">
        <div className="truncate px-3 text-xs text-muted-foreground">{me.data?.email}</div>
        <button
          onClick={() => {
            auth.clear();
            router.replace("/login");
          }}
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-sidebar-foreground hover:bg-muted"
        >
          <LogOut className="h-4 w-4" /> Sign out
        </button>
      </div>
    </nav>
  );

  return (
    <div className="min-h-screen">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 border-r bg-sidebar lg:block">{sidebar}</aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 border-r bg-sidebar animate-fade-in">{sidebar}</aside>
        </div>
      )}
      <div className="lg:pl-60">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b bg-background/80 px-4 backdrop-blur md:px-8">
          <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setOpen(!open)} aria-label="Menu">
            {open ? <X /> : <Menu />}
          </Button>
          <div className="text-sm font-medium text-muted-foreground">{NAV.find((n) => pathname.startsWith(n.href))?.label}</div>
          <div className="ml-auto flex items-center gap-2">
            <ActiveSearchPill />
            <ThemeToggle />
          </div>
        </header>
        <main className="mx-auto max-w-7xl p-4 md:p-8">{children}</main>
      </div>
    </div>
  );
}
