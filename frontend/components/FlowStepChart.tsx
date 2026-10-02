"use client";

import { useMemo } from "react";
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import { C, RISK, bankColor } from "@/src/theme";
import type { CyElement } from "@/lib/types";
import { fmtMoney } from "@/lib/api";

/** Buckets the ring's transactions into a cumulative in/out step series for
 *  one account; the gap between the two steps is the money the account held. */
function buildSeries(elements: CyElement[], account: string, buckets = 70) {
  const edges = elements
    .filter((e) => e.data.source)
    .map((e) => ({
      t: new Date(e.data.time!.replace(" ", "T")).getTime(),
      amt: e.data.amount ?? 0,
      src: e.data.source!,
      dst: e.data.target!,
    }))
    .sort((a, b) => a.t - b.t);
  if (!edges.length) return { rows: [], span: 0 };
  const t0 = edges[0].t;
  const t1 = edges[edges.length - 1].t;
  const span = Math.max(t1 - t0, 1);
  const bw = span / buckets;

  const rows = Array.from({ length: buckets + 1 }, (_, i) => ({
    t: t0 + i * bw,
    label: new Date(t0 + i * bw).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }),
    inAmt: 0,
    outAmt: 0,
    cumIn: 0,
    cumOut: 0,
    held: 0,
  }));

  for (const e of edges) {
    const idx = Math.min(buckets, Math.max(0, Math.floor((e.t - t0) / bw)));
    if (e.dst === account) rows[idx].inAmt += e.amt;
    if (e.src === account) rows[idx].outAmt += e.amt;
  }
  let ci = 0,
    co = 0;
  for (const r of rows) {
    ci += r.inAmt;
    co += r.outAmt;
    r.cumIn = Math.round(ci);
    r.cumOut = Math.round(co);
    r.held = Math.round(ci - co);
  }
  return { rows, span };
}

export default function FlowStepChart({
  elements,
  account,
  bank,
}: {
  elements: CyElement[];
  account: string;
  bank?: string;
}) {
  const { rows } = useMemo(
    () => buildSeries(elements, account),
    [elements, account],
  );
  if (!rows.length) return null;

  const acc = account.split("_")[1] ?? account;
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <div className="text-xxs uppercase tracking-[0.14em] text-ink-muted">
          Money in / out ·{" "}
          <span
            className="num normal-case tracking-normal"
            style={{ color: bankColor(bank) }}
          >
            {acc}
          </span>
        </div>
        <div className="flex gap-3 text-xxs">
          <span className="inline-flex items-center gap-1 text-ink-muted">
            <span className="w-3 h-0.5" style={{ background: RISK.green }} /> in
            (cum.)
          </span>
          <span className="inline-flex items-center gap-1 text-ink-muted">
            <span className="w-3 h-0.5" style={{ background: RISK.red }} /> out
            (cum.)
          </span>
          <span className="inline-flex items-center gap-1 text-ink-muted">
            <span
              className="w-3 h-2"
              style={{ background: "rgba(210,153,34,0.25)" }}
            />{" "}
            held
          </span>
        </div>
      </div>
      <div style={{ height: 168 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={rows}
            margin={{ top: 4, right: 8, bottom: 0, left: 4 }}
          >
            <CartesianGrid
              stroke={C.border}
              strokeDasharray="2 4"
              vertical={false}
            />
            <XAxis
              dataKey="t"
              type="number"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(t) =>
                new Date(t).toLocaleString(undefined, {
                  month: "short",
                  day: "numeric",
                  hour: "2-digit",
                })
              }
              tick={{ fill: C.faint, fontSize: 9 }}
              stroke={C.border}
              minTickGap={48}
            />
            <YAxis
              tickFormatter={(v) => fmtMoney(Number(v))}
              tick={{ fill: C.faint, fontSize: 9 }}
              stroke={C.border}
              width={52}
            />
            <Tooltip
              contentStyle={{
                background: C.panel2,
                border: `1px solid ${C.border}`,
                borderRadius: 4,
                fontSize: 11,
              }}
              labelStyle={{ color: C.muted }}
              labelFormatter={(t) => new Date(Number(t)).toLocaleString()}
              formatter={(value: any, name: any) => {
                const names: Record<string, string> = {
                  cumIn: "money in (cum.)",
                  cumOut: "money out (cum.)",
                  held: "held",
                };
                return [
                  fmtMoney(Number(value)),
                  names[String(name)] ?? String(name),
                ];
              }}
            />
            {/* held money = vertical gap between the in and out steps */}
            <Area
              type="stepAfter"
              dataKey="held"
              stroke="none"
              fill="rgba(210,153,34,0.25)"
              isAnimationActive={false}
            />
            <Line
              type="stepAfter"
              dataKey="cumIn"
              stroke={RISK.green}
              strokeWidth={1.4}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="stepAfter"
              dataKey="cumOut"
              stroke={RISK.red}
              strokeWidth={1.4}
              dot={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="text-xxs text-ink-faint mt-1">
        The shaded band is how much money the account is holding at each moment:
        a thin band that snaps shut means funds passed straight through.
      </div>
    </div>
  );
}
