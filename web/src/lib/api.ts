export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type Params = Record<string, string | number | boolean | string[] | null | undefined>;

export function qs(params?: Params): string {
  if (!params) return "";
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, x));
    else sp.append(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown; params?: Params } = {}): Promise<T> {
  // The browser is signed in with a session cookie (Tailscale, Google or access-token login).
  const headers: Record<string, string> = {};
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`/api/v1${path}${qs(opts.params)}`, {
    method: opts.method || "GET",
    credentials: "same-origin",
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401) {
    window.dispatchEvent(new Event("routepass:unauthorized"));
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const data = await res.json();
      msg = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data);
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json();
}

export function downloadUrl(path: string): string {
  return `/api/v1${path}`;
}

export interface Me {
  authenticated: boolean; email: string | null; name: string | null; picture: string | null; method: string | null;
  methods: { google: boolean; tailscale: boolean; token: boolean };
}
