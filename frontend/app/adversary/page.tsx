"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ResponsiveContainer,
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Line,
  ReferenceLine,
  ZAxis,
} from "recharts";
import { Play, FlaskConical } from "lucide-react";
import { api, C, RISK } from "@/lib/api";
import type { AdversaryResult, FrontierPoint } from "@/lib/types";
import { Hint, PageSkel, Empty } from "@/src/components/ui";
import { isWakingErr, WakingState, ErrorState } from "@/src/components/ApiGate";

const LEVERS = [
  {
    key: "hop_delay_hours" as const,
    label: "Added delay per hop",
    min: 0,
    max: 96,
    step: 6,
    unit: "h",
    hint: "Money sits still between hops. Long delays break the 72-hour cycle window and the 120-minute chain rule - at the cost of time.",
  },
  {
    key: "n_splits" as const,
    label: "Parallel splits",
    min: 1,
    max: 4,
    step: 1,
    unit: " paths",
    hint: "Cut the sum into several parallel routes so no single chain carries the whole amount.",
  },
  {
    key: "n_decoys" as const,
    label: "Decoy transactions",
    min: 0,
    max: 40,
    step: 5,
    unit: "",
    hint: "Sprinkle ordinary-looking payments around the scheme to hide the signal in noise.",
  },
  {
    key: "n_banks" as const,
    label: "Banks routed through",
    min: 1,
    max: 3,
    step: 1,
    unit: "",
    hint: "Each extra bank means another legal process to follow the money across.",
  },
];

/** Rolling detection rate over cost - the empirical "detection probability". */
function rollingRate(
  points: { cost: number; detected: boolean }[],
  window = 7,
) {
  const sorted = [...points].sort((a, b) => a.cost - b.cost);
  return sorted.map((p, i) => {
    const lo = Math.max(0, i - Math.floor(window / 2));
    const hi = Math.min(sorted.length, i + Math.ceil(window / 2));
    const slice = sorted.slice(lo, hi);
    return {
      cost: p.cost,
      rate: slice.filter((x) => x.detected).length / slice.length,
    };
  });
}

export default function AdversaryPage() {
  const [result, setResult] = useState<AdversaryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [waking, setWaking] = useState(false);
  const [wakeAttempts, setWakeAttempts] = useState(0);
  const [busy, setBusy] = useState(false);
  const [levers, setLevers] = useState<Record<string, number>>({
    hop_delay_hours: 48,
    n_splits: 2,
    n_decoys: 10,
    n_banks: 2,
  });

  const run = useCallback(async (overrides: Record<string, number>) => {
    setBusy(true);
    setError(null);
    try {
      const res = await api<AdversaryResult>("/api/adversary/run", {
        method: "POST",
        body: JSON.stringify(overrides),
      });
      setResult(res);
      setWaking(false);
    } catch (e: any) {
      if (isWakingErr(e)) {
        // backend still booting: keep retrying until the first result lands
        setWaking(true);
        setError(null);
        setWakeAttempts((a) => a + 1);
      } else {
        setError(String(e.message ?? e));
        setWaking(false);
      }
    } finally {
      setBusy(false);
    }
  }, []);

  // default 32-scheme grid on first load so the page is never empty
  useEffect(() => {
    run({});
  }, [run]);

  // auto-retry the initial grid while the backend is waking up (only before
  // the first result, so manual lever runs are never overridden)
  useEffect(() => {
    if (waking && !result) {
      const t = setTimeout(() => run({}), 3000);
      return () => clearTimeout(t);
    }
  }, [waking, wakeAttempts, result, run]);

  const points = useMemo(() => {
    if (!result) return [];
    return result.frontier.map((f: FrontierPoint) => ({
      cost: f.friction,
      detected: f.detected,
      label: f.label,
      z: 10,
    }));
  }, [result]);

  const rateLine = useMemo(
    () =>
      rollingRate(points.map((p) => ({ cost: p.cost, detected: p.detected }))),
    [points],
  );

  const cheapestEvaders = useMemo(() => {
    if (!result) return [];
    return result.frontier
      .filter((f) => !f.detected)
      .sort((a, b) => a.friction - b.friction)
      .slice(0, 6);
  }, [result]);

  if (error && !result)
    return <ErrorState error={`API error: ${error}`} onRetry={() => run({})} />;
  if (!result)
    return waking ? (
      <WakingState onRetry={() => run({})} />
    ) : (
      <PageSkel rows={5} />
    );

  const delta = result.friction_after - result.friction_before;

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <h1 className="text-lg font-semibold flex items-center gap-2">
          <FlaskConical size={17} className="text-risk-amber" />
          Adversary Lab
          <Hint text="A laundering agent searches for the cheapest way to move money past the current detector. The Friction Score is what that costs a criminal relative to a naive transfer - a higher number means the detector is forcing more work." />
        </h1>
        <span className="num text-xxs text-ink-faint">
          {result.n_schemes_tested} schemes tested · baseline{" "}
          {result.baseline_detected ? (
            <span style={{ color: RISK.green }}>CAUGHT</span>
          ) : (
            <span style={{ color: RISK.red }}>EVADING</span>
          )}
        </span>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[280px_1fr] gap-3 items-start">
        {/* ---------------- levers ---------------- */}
        <div className="panel">
          <div className="panel-head">Evasion levers</div>
          <div className="p-3 space-y-4">
            {LEVERS.map((l) => (
              <div key={l.key}>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xxs uppercase tracking-[0.14em] text-ink-muted flex items-center gap-1">
                    {l.label}
                    <Hint text={l.hint} />
                  </span>
                  <span className="num text-xs text-ink-text">
                    {levers[l.key]}
                    {l.unit}
                  </span>
                </div>
                <input
                  type="range"
                  min={l.min}
                  max={l.max}
                  step={l.step}
                  value={levers[l.key]}
                  onChange={(e) =>
                    setLevers((s) => ({
                      ...s,
                      [l.key]: Number(e.target.value),
                    }))
                  }
                  className="w-full"
                />
              </div>
            ))}

            <button
              className="btn-primary w-full justify-center"
              onClick={() => run(levers)}
              disabled={busy}
            >
              <Play size={13} />
              {busy ? "Running grid…" : "Run schemes"}
            </button>

            {error && <div className="err-banner">{error}</div>}

            <div className="border-t border-ink-border pt-3">
              <div className="text-xxs uppercase tracking-[0.14em] text-ink-muted mb-1.5 flex items-center gap-1">
                Hardened thresholds
                <Hint text="After seeing which schemes evade, the lab tightens the detector thresholds that failed and reports the new friction cost." />
              </div>
              {Object.entries(result.hardened_thresholds).map(([k, v]) => (
                <div key={k} className="flex justify-between text-xxs py-0.5">
                  <span className="text-ink-faint">{k.replace(/_/g, " ")}</span>
                  <span className="num text-ink-muted">{v}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ---------------- results ---------------- */}
        <div className="space-y-3 min-w-0">
          {/* friction before / after */}
          <div className="panel px-3 py-2.5 flex items-center gap-6 flex-wrap">
            <div>
              <div className="text-xxs uppercase tracking-[0.14em] text-ink-muted">
                Friction before hardening
              </div>
              <div className="num text-xl text-ink-text">
                {result.friction_before.toFixed(2)}×
                <span className="text-xxs text-ink-faint ml-1.5">
                  naive cost
                </span>
              </div>
            </div>
            <div className="text-ink-faint">→</div>
            <div>
              <div className="text-xxs uppercase tracking-[0.14em] text-ink-muted">
                After hardening
              </div>
              <div className="num text-xl" style={{ color: RISK.green }}>
                {result.friction_after.toFixed(2)}×
              </div>
            </div>
            <span
              className="chip ml-auto"
              style={{
                borderColor: delta > 0 ? RISK.green : RISK.red,
                color: delta > 0 ? RISK.green : RISK.red,
              }}
            >
              {delta >= 0 ? "+" : ""}
              {delta.toFixed(2)}× harder to evade
            </span>
          </div>

          {/* frontier scatter */}
          <div className="panel">
            <div className="panel-head">
              Evasion frontier
              <span className="ml-auto normal-case tracking-normal text-ink-faint">
                cost to criminal (× naive) vs detection outcome
              </span>
            </div>
            <div className="p-3" style={{ height: 300 }}>
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart
                  margin={{ top: 8, right: 16, bottom: 18, left: 4 }}
                >
                  <CartesianGrid stroke={C.border} strokeDasharray="2 4" />
                  <XAxis
                    type="number"
                    dataKey="cost"
                    name="cost"
                    tick={{ fill: C.faint, fontSize: 9 }}
                    stroke={C.border}
                    label={{
                      value: "cost to criminal (× naive scheme)",
                      position: "insideBottom",
                      offset: -10,
                      fill: C.faint,
                      fontSize: 9,
                    }}
                  />
                  <YAxis
                    type="number"
                    dataKey="y"
                    domain={[-0.15, 1.15]}
                    ticks={[0, 1]}
                    tickFormatter={(v) =>
                      v === 1 ? "detected" : v === 0 ? "evaded" : ""
                    }
                    tick={{ fill: C.faint, fontSize: 9 }}
                    stroke={C.border}
                    width={64}
                  />
                  <ZAxis range={[36, 36]} />
                  <Tooltip
                    contentStyle={{
                      background: C.panel2,
                      border: `1px solid ${C.border}`,
                      borderRadius: 4,
                      fontSize: 11,
                    }}
                    formatter={(v: any, n: any) =>
                      n === "cost" ? [Number(v).toFixed(2) + "×", "cost"] : v
                    }
                    labelFormatter={() => ""}
                  />
                  {cheapestEvaders[0] && (
                    <ReferenceLine
                      x={cheapestEvaders[0].friction}
                      stroke={RISK.amber}
                      strokeDasharray="4 3"
                      label={{
                        value: "cheapest evasion",
                        fill: RISK.amber,
                        fontSize: 9,
                        position: "insideTopLeft",
                      }}
                    />
                  )}
                  <Scatter
                    name="detected"
                    data={points.map((p) => ({
                      ...p,
                      y: 1 + (Math.random() - 0.5) * 0.06,
                    }))}
                    fill="none"
                    shape={(props: any) => (
                      <circle
                        cx={props.cx}
                        cy={props.cy}
                        r={4}
                        fill={RISK.red}
                        fillOpacity={0.85}
                      />
                    )}
                    isAnimationActive={false}
                  />
                  <Scatter
                    name="evaded"
                    data={points.map((p) => ({
                      ...p,
                      y: (Math.random() - 0.5) * 0.06,
                    }))}
                    fill="none"
                    shape={(props: any) => (
                      <circle
                        cx={props.cx}
                        cy={props.cy}
                        r={4}
                        fill={RISK.green}
                        fillOpacity={0.85}
                      />
                    )}
                    isAnimationActive={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="rate"
                    data={rateLine.map((r) => ({ cost: r.cost, rate: r.rate }))}
                    stroke={C.muted}
                    strokeWidth={1.2}
                    strokeDasharray="5 3"
                    dot={false}
                    isAnimationActive={false}
                  />
                </ScatterChart>
              </ResponsiveContainer>
              <div className="flex gap-4 text-xxs text-ink-muted -mt-2 px-1">
                <span className="inline-flex items-center gap-1.5">
                  <span
                    className="w-2 h-2 rounded-full"
                    style={{ background: RISK.red }}
                  />{" "}
                  caught
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span
                    className="w-2 h-2 rounded-full"
                    style={{ background: RISK.green }}
                  />{" "}
                  evaded
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="w-3 h-0.5" style={{ background: C.muted }} />{" "}
                  local detection rate
                </span>
              </div>
            </div>
          </div>

          {/* cheapest evaders */}
          <div className="panel">
            <div className="panel-head">
              Cheapest evading schemes
              <Hint text="Schemes the detector missed, sorted by how cheap they are for a criminal. The cheapest one defines the Friction Score." />
            </div>
            {cheapestEvaders.length === 0 ? (
              <div className="p-3">
                <Empty title="No scheme in this grid evaded the detector" />
              </div>
            ) : (
              <table className="w-full">
                <thead>
                  <tr>
                    <th className="th">Scheme</th>
                    <th className="th">Time cost</th>
                    <th className="th">Fees</th>
                    <th className="th">Extra accounts</th>
                    <th className="th">Friction</th>
                  </tr>
                </thead>
                <tbody>
                  {cheapestEvaders.map((f) => (
                    <tr key={f.label} className="tbody-row">
                      <td className="td num text-ink-text">{f.label}</td>
                      <td className="td num">{f.cost_hours.toFixed(1)} h</td>
                      <td className="td num">{f.fee_pct.toFixed(1)}%</td>
                      <td className="td num">{f.extra_accounts}</td>
                      <td className="td num" style={{ color: RISK.amber }}>
                        {f.friction.toFixed(2)}×
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
