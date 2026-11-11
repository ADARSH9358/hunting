"use client";

const TOKEN_KEY = "jobhunt.token";

export class ApiError extends Error {
  status: number;
  data: unknown;
  constructor(status: number, message: string, data?: unknown) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

export const auth = {
  get: () => (typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY)),
  set: (t: string) => window.localStorage.setItem(TOKEN_KEY, t),
  clear: () => window.localStorage.removeItem(TOKEN_KEY),
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function messageFrom(data: any, fallback: string): string {
  const d = data?.detail;
  if (typeof d === "string") return d;
  if (d?.message) return d.message;
  if (Array.isArray(data?.errors) && data.errors[0]?.msg) return `${data.detail}: ${data.errors[0].msg}`;
  return fallback;
}

export type Query = Record<string, string | number | boolean | (string | number)[] | null | undefined>;

export function qs(params: Query = {}): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, String(x)));
    else sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function api<T = any>(path: string, init: RequestInit & { query?: Query } = {}): Promise<T> {
  const { query, headers, ...rest } = init;
  const token = auth.get();
  const isForm = typeof FormData !== "undefined" && rest.body instanceof FormData;
  const res = await fetch(`/api${path}${qs(query)}`, {
    ...rest,
    headers: {
      ...(isForm || !rest.body ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
  });
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (res.status === 401 && !path.startsWith("/auth/")) {
    auth.clear();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) window.location.href = "/login";
  }
  if (!res.ok) throw new ApiError(res.status, messageFrom(data, `Request failed (${res.status})`), data);
  return data as T;
}

export async function login(email: string, password: string) {
  const body = new URLSearchParams({ username: email, password });
  const res = await fetch("/api/auth/token", {
    method: "POST",
    body,
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, messageFrom(data, "Login failed"), data);
  auth.set(data.access_token);
}

export async function register(email: string, password: string, full_name?: string) {
  const data = await api<{ access_token: string }>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, full_name }),
  });
  auth.set(data.access_token);
}
