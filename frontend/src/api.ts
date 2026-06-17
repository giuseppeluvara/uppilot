// Client API: sessione Django + CSRF. Tutte le richieste passano dal proxy Vite.

function getCookie(name: string): string {
  const match = document.cookie.match(new RegExp("(^|; )" + name + "=([^;]*)"));
  return match ? decodeURIComponent(match[2]) : "";
}

export async function ensureCsrf(): Promise<void> {
  await fetch("/api/auth/csrf/", { credentials: "include" });
}

type Opts = { method?: string; json?: unknown; form?: FormData };

async function request<T>(path: string, opts: Opts = {}): Promise<T> {
  const method = opts.method ?? "GET";
  const headers: Record<string, string> = {};
  let body: BodyInit | undefined;

  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  } else if (opts.form) {
    body = opts.form;
  }
  if (method !== "GET") headers["X-CSRFToken"] = getCookie("csrftoken");

  const res = await fetch("/api" + path, { method, headers, body, credentials: "include" });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail ?? JSON.stringify(data);
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function download(path: string, filename: string): Promise<void> {
  const res = await fetch("/api" + path, { credentials: "include" });
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export const api = {
  get: <T>(p: string) => request<T>(p),
  post: <T>(p: string, json?: unknown) => request<T>(p, { method: "POST", json }),
  patch: <T>(p: string, json?: unknown) => request<T>(p, { method: "PATCH", json }),
  upload: <T>(p: string, form: FormData) => request<T>(p, { method: "POST", form }),
  download,
};
