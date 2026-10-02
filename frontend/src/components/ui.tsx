"use client";

import { useState } from "react";
import { HelpCircle } from "lucide-react";
import { C, RISK, riskColor, bankColor } from "@/src/theme";
import { fmtMoney } from "@/lib/api";

/** "?" tooltip with plain-language copy. */
export function Hint({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-flex">
      <button
        aria-label="what is this?"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onClick={() => setOpen(!open)}
        className="text-ink-faint hover:text-ink-muted inline-flex"
      >
        <HelpCircle size={12} strokeWidth={1.75} />
      </button>
      {open && (
        <span className="absolute left-1/2 -translate-x-1/2 top-5 z-50 w-56 rounded border border-ink-border bg-ink-panel2 p-2 text-xxs font-normal normal-case tracking-normal text-ink-muted shadow-lg">
          {text}
        </span>
      )}
    </span>
  );
}

/** Rectangular skeleton placeholder. */
export function Skel({ h = 16, w }: { h?: number; w?: string | number }) {
  return <div className="skeleton" style={{ height: h, width: w ?? "100%" }} />;
}

/** Standard page loading state. */
export function PageSkel({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-3">
      <Skel h={24} w={280} />
      {Array.from({ length: rows }).map((_, i) => (
        <Skel key={i} h={52} />
      ))}
    </div>
  );
}

export function Empty({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="border border-dashed border-ink-border rounded p-8 text-center">
      <div className="text-sm text-ink-text">{title}</div>
      {sub && <div className="text-xxs text-ink-muted mt-1">{sub}</div>}
    </div>
  );
}

/** Tiny inline amount sparkline (SVG polyline). */
export function Sparkline({
  values,
  w = 90,
  h = 22,
}: {
  values: number[];
  w?: number;
  h?: number;
}) {
  if (!values || values.length < 2)
    return <span className="text-ink-faint text-xxs">-</span>;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const span = max - min || 1;
  const pts = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * (w - 2) + 1;
      const y = h - 2 - ((v - min) / span) * (h - 4);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg width={w} height={h} className="inline-block">
      <polyline
        points={pts}
        fill="none"
        stroke={RISK.amber}
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Horizontal risk bar with the numeric value. */
export function RiskBar({ score, w = 72 }: { score: number; w?: number }) {
  const color = riskColor(score);
  return (
    <span className="inline-flex items-center gap-2">
      <span className="num text-ink-text w-6 text-right">
        {score.toFixed(0)}
      </span>
      <span
        className="inline-block rounded-sm"
        style={{
          width: w,
          height: 5,
          background: "#232934",
        }}
      >
        <span
          className="block rounded-sm h-full"
          style={{ width: `${Math.min(score, 100)}%`, background: color }}
        />
      </span>
    </span>
  );
}

/** Semi-circular risk gauge for the inspector. */
export function RiskGauge({ score }: { score: number }) {
  const color = riskColor(score);
  const angle = (Math.min(score, 100) / 100) * 180;
  const rad = (angle * Math.PI) / 180;
  const r = 40;
  const cx = 46;
  const cy = 46;
  const x = cx + r * Math.cos(Math.PI - rad);
  const y = cy - r * Math.sin(rad);
  return (
    <div className="flex items-center gap-3">
      <svg width="92" height="52">
        <path
          d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`}
          fill="none"
          stroke={C.border}
          strokeWidth="6"
          strokeLinecap="round"
        />
        <path
          d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${x} ${y}`}
          fill="none"
          stroke={color}
          strokeWidth="6"
          strokeLinecap="round"
        />
        <text
          x={cx}
          y={cy - 4}
          textAnchor="middle"
          fill={C.text}
          fontSize="16"
          fontFamily="JetBrains Mono, monospace"
        >
          {score.toFixed(0)}
        </text>
      </svg>
      <div className="text-xxs text-ink-muted leading-4">
        risk score
        <br />
        <span style={{ color }}>0 = clear, 100 = critical</span>
      </div>
    </div>
  );
}

/** Coloured dot + label legend row. */
export function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xxs text-ink-muted">
      <span className="w-2 h-2 rounded-sm" style={{ background: color }} />
      {label}
    </span>
  );
}

/** Bank chip used across pages. */
export function BankChips({ banks }: { banks: string[] }) {
  return (
    <span className="inline-flex gap-1">
      {banks.map((b) => (
        <span
          key={b}
          className="inline-flex items-center gap-1 text-xxs text-ink-muted"
        >
          <span
            className="w-2 h-2 rounded-sm"
            style={{ background: bankColor(b) }}
          />
          {b.replace("Bank", "")}
        </span>
      ))}
    </span>
  );
}

/** Status chip: green valid / red broken, with short hash. */
export function VerifyChip({
  valid,
  hash,
}: {
  valid: boolean | null;
  hash?: string;
}) {
  if (valid === null) return null;
  return (
    <span
      className="chip"
      style={{
        borderColor: valid ? RISK.green : RISK.red,
        color: valid ? RISK.green : RISK.red,
      }}
    >
      {valid ? "CHAIN VALID" : "TAMPERED"}
      {hash ? ` · ${hash.slice(0, 8)}` : ""}
    </span>
  );
}

export { fmtMoney };
