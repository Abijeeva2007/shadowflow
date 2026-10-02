/**
 * ShadowFlow theme - the single source of truth for every chart colour,
 * bank colour, risk colour, and node shape. Bloomberg-terminal graphite:
 * no gradients, no glow, no cyan.
 */

// ---- base surfaces / text ---------------------------------------------------
export const C = {
  bg: "#0F1115", // app background (graphite)
  panel: "#161A21", // panels / cards
  panel2: "#1B2029", // raised panels (inspector, table headers)
  border: "#232934", // 1px borders everywhere
  text: "#E7E9EE", // primary text
  muted: "#8B93A3", // secondary text
  faint: "#5A6272", // disabled / axis text
} as const;

// ---- semantic ----------------------------------------------------------------
export const RISK = {
  amber: "#D29922", // elevated risk
  red: "#C74E4E", // critical / detected / alarm
  green: "#63965D", // benign / evaded / verified
} as const;

// ---- banks: three muted colours + a node shape each ---------------------------
export const BANKS: Record<
  string,
  { color: string; shape: string; label: string }
> = {
  BankA: { color: "#5B7C99", shape: "round", label: "Bank A" }, // slate blue
  BankB: { color: "#7A6A54", shape: "square", label: "Bank B" }, // bronze
  BankC: { color: "#5E7D5A", shape: "diamond", label: "Bank C" }, // moss
};

export const bankColor = (bank: string | undefined) =>
  BANKS[bank ?? ""]?.color ?? C.muted;

export const bankShape = (bank: string | undefined) =>
  BANKS[bank ?? ""]?.shape ?? "round";

export const BANK_LIST = Object.keys(BANKS);

// ---- pattern types -------------------------------------------------------------
export const TYPES: Record<string, { color: string; label: string }> = {
  cycle: { color: "#A8763E", label: "Cycle" }, // burnt amber
  mule_chain: { color: "#8C5F7E", label: "Mule chain" }, // muted plum
  smurfing: { color: "#4E7D8C", label: "Smurfing" }, // desaturated teal
};

export const typeColor = (t: string | undefined) =>
  TYPES[t ?? ""]?.color ?? C.muted;
export const typeLabel = (t: string | undefined) =>
  TYPES[t ?? ""]?.label ?? t ?? "?";

// ---- risk scale (0-100) ----------------------------------------------------------
export function riskColor(score: number): string {
  if (score >= 80) return RISK.red;
  if (score >= 55) return RISK.amber;
  return C.muted;
}

// ---- taint (dirty money intensity) -------------------------------------------------
export const TAINT = {
  hot: "#C74E4E", // fraction ~1
  warm: "#A8763E", // mid
  cold: "#5A6272", // dusty
};

export function taintColor(fraction: number): string {
  if (fraction >= 0.66) return TAINT.hot;
  if (fraction >= 0.33) return TAINT.warm;
  return TAINT.cold;
}

// ---- sparkline / charts ---------------------------------------------------------------
export const SPARK = {
  line: "#D29922",
  fill: "rgba(210,153,34,0.12)",
  grid: C.border,
  axis: C.faint,
} as const;

// ---- funnel ------------------------------------------------------------------------------
export const FUNNEL = {
  fill: "#242B36",
  fillDone: "#2E3742",
  edge: "#3A4453",
  text: C.text,
} as const;
