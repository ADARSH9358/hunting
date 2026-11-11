"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { BriefcaseBusiness, Building2, Loader2, Radar, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button, Card, CardContent, Input, Label, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui";
import { login, register } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");

  async function submit(mode: "login" | "register") {
    setLoading(true);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password, name || undefined);
      router.replace("/dashboard");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="relative hidden overflow-hidden bg-gradient-to-br from-indigo-700 via-violet-700 to-fuchsia-700 p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="absolute inset-0 opacity-20 bg-grid" />
        <div className="relative flex items-center gap-2 text-lg font-semibold">
          <div className="grid h-9 w-9 place-items-center rounded-xl bg-white/15 backdrop-blur">
            <Radar className="h-5 w-5" />
          </div>
          JobHunt AI
        </div>
        <div className="relative space-y-6">
          <h1 className="text-4xl font-bold leading-tight text-balance">Your personal AI job-search assistant.</h1>
          <p className="max-w-md text-white/80">
            Upload your resume once. Press <b>RUN</b> whenever you like — we search job boards and the official career pages of
            small, mid-sized and large IT companies, and rank every opening against your real experience.
          </p>
          <ul className="space-y-3 text-sm text-white/90">
            {[
              [Sparkles, "Resume analysis that never invents skills or experience"],
              [Building2, "Discovers small & mid-sized companies beyond the usual names"],
              [BriefcaseBusiness, "Transparent 0–100 match scores with matched & missing skills"],
            ].map(([Icon, text], i) => {
              const I = Icon as typeof Sparkles;
              return (
                <li key={i} className="flex items-center gap-3">
                  <I className="h-4 w-4 shrink-0" /> {text as string}
                </li>
              );
            })}
          </ul>
        </div>
        <p className="relative text-xs text-white/60">Only real postings from official or licensed sources. No fake jobs, ever.</p>
      </div>

      <div className="flex items-center justify-center p-6">
        <Card className="w-full max-w-md border-0 shadow-none sm:border sm:shadow-sm">
          <CardContent className="p-8">
            <div className="mb-6 space-y-1">
              <h2 className="text-2xl font-semibold tracking-tight">Welcome</h2>
              <p className="text-sm text-muted-foreground">Sign in or create an account to start your search.</p>
            </div>
            <Tabs defaultValue="login">
              <TabsList className="mb-6 grid w-full grid-cols-2">
                <TabsTrigger value="login">Sign in</TabsTrigger>
                <TabsTrigger value="register">Create account</TabsTrigger>
              </TabsList>
              {(["login", "register"] as const).map((mode) => (
                <TabsContent key={mode} value={mode}>
                  <form
                    className="space-y-4"
                    onSubmit={(e) => {
                      e.preventDefault();
                      submit(mode);
                    }}
                  >
                    {mode === "register" && (
                      <div className="space-y-2">
                        <Label htmlFor="name">Full name</Label>
                        <Input id="name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
                      </div>
                    )}
                    <div className="space-y-2">
                      <Label htmlFor={`email-${mode}`}>Email</Label>
                      <Input id={`email-${mode}`} type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor={`pw-${mode}`}>Password</Label>
                      <Input
                        id={`pw-${mode}`}
                        type="password"
                        required
                        minLength={8}
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        autoComplete={mode === "login" ? "current-password" : "new-password"}
                      />
                      {mode === "register" && <p className="text-xs text-muted-foreground">At least 8 characters.</p>}
                    </div>
                    <Button type="submit" className="w-full" disabled={loading}>
                      {loading && <Loader2 className="animate-spin" />}
                      {mode === "login" ? "Sign in" : "Create account"}
                    </Button>
                  </form>
                </TabsContent>
              ))}
            </Tabs>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
