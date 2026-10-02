export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Re-export the single source of truth for colours.
export {
  C,
  RISK,
  BANKS,
  BANK_LIST,
  TYPES,
  TAINT,
  SPARK,
  FUNNEL,
  bankColor,
  bankShape,
  typeColor,
  typeLabel,
  riskColor,
  taintColor,
} from "@/src/theme";

export function fmtMoney(n: number | undefined | null): string {
  if (n === undefined || n === null) return "-";
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toFixed(0);
}

export function fmtTime(iso: string | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso.replace(" ", "T"));
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail =
        typeof body.detail === "string"
          ? body.detail
          : Array.isArray(body.detail)
            ? body.detail.map((d: any) => d.msg ?? JSON.stringify(d)).join("; ")
            : JSON.stringify(body);
    } catch {
      /* keep statusText */
    }
    throw Object.assign(new Error(`API ${res.status}: ${detail}`), {
      status: res.status,
    });
  }
  return res.json() as Promise<T>;
}
