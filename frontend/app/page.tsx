"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Activity, Filter, SearchCheck, AlertTriangle } from "lucide-react";
import { api, fmtMoney, typeColor, typeLabel, bankColor } from "@/lib/api";
import { C, RISK, FUNNEL } from "@/src/theme";
import type { Summary, Ring } from "@/lib/types";
import { Hint, PageSkel, RiskBar, BankChips, Skel } from "@/src/components/ui";
import { useApiData, WakingState, ErrorState } from "@/src/components/ApiGate";

/** Decoy checks include a `total_flagged` roll-up key that is not an account. */
function decoyCount(s: Summary): number {
  return Object.keys(s.decoy_checks).filter((k) => k !== "total_flagged")
    .length;
}

function Kpi({
  icon: Icon,
  label,
  value,
  sub,
  hint,
}: {
  icon: any;
  label: string;
  value: string | number;
  sub?: string;
  hint?: string;
}) {
  return (
    <div className="panel px-3 py-2.5">
      <div className="flex items-center gap-1.5 text-xxs uppercase tracking-[0.14em] text-ink-muted">
        <Icon size={12} strokeWidth={1.75} />
        {label}
        {hint && <Hint text={hint} />}
      </div>
      <div className="num text-xl font-medium mt-1 text-ink-text">{value}</div>
      {sub && <div className="text-xxs text-ink-faint mt-0.5">{sub}</div>}
    </div>
  );
}

/** Horizontal funnel bar: raw alerts -> benign filter -> reviewed -> confirmed. */
function Funnel({ s }: { s: Summary }) {
  const stages = [
    {
      label: "Raw alerts (every account)",
      n: s.accounts_total,
      fill: FUNNEL.fill,
    },
    {
      label: "Cleared by benign filter",
      n: s.accounts_filtered_benign,
      fill: "#223022",
    },
    { label: "Reviewed by detectors", n: s.reviewed, fill: FUNNEL.fillDone },
    { label: "Confirmed in rings", n: s.ring_accounts, fill: "#3A2A1C" },
  ];
  const max = Math.max(...stages.map((x) => x.n));
  return (
    <div className="panel">
      <div className="panel-head">
        Investigation funnel
        <Hint text="Every account starts as a raw alert. The benign filter clears steady business accounts; detectors review what remains; accounts that end up inside a confirmed ring are shown last." />
      </div>
      <div className="p-3 space-y-2">
        {stages.map((st) => (
          <div key={st.label} className="flex items-center gap-3">
            <div className="w-44 text-xxs text-ink-muted shrink-0">
              {st.label}
            </div>
            <div
              className="flex-1 h-5 rounded-sm relative"
              style={{ background: "#12151B" }}
            >
              <div
                className="h-full rounded-sm border"
                style={{
                  width: `${(st.n / max) * 100}%`,
                  background: st.fill,
                  borderColor: FUNNEL.edge,
                }}
              />
              <span className="num absolute right-2 top-0.5 text-xxs text-ink-muted">
                {st.n.toLocaleString()}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Accuracy table with inline P/R/F1 bars - real numbers, no faking. */
function Accuracy({ s }: { s: Summary }) {
  const rows = Object.entries(s.precision_recall);
  const cell = (
    label: string,
    v: number,
    tp?: number,
    fp?: number,
    fn?: number,
  ) => (
    <td className="td">
      <div className="flex items-center gap-2">
        <span
          className="num w-10 text-right"
          style={{
            color: v >= 0.8 ? RISK.green : v >= 0.5 ? RISK.amber : RISK.red,
          }}
        >
          {(v * 100).toFixed(0)}%
        </span>
        <span
          className="inline-block w-24 h-1.5 rounded-sm"
          style={{ background: C.border }}
        >
          <span
            className="block h-full rounded-sm"
            style={{
              width: `${v * 100}%`,
              background:
                v >= 0.8 ? RISK.green : v >= 0.5 ? RISK.amber : RISK.red,
            }}
          />
        </span>
        <span className="num text-xxs text-ink-faint">
          {tp !== undefined ? `tp ${tp} · fp ${fp} · fn ${fn}` : ""}
        </span>
      </div>
      <span className="sr-only">{label}</span>
    </td>
  );
  return (
    <div className="panel">
      <div className="panel-head">
        Detector accuracy vs ground truth
        <Hint text="Detected rings are matched 1:1 against the rings the data generator injected (Jaccard >= 0.5). These are the honest numbers on hardened synthetic data - hidden hops and jitter keep them below 100%." />
      </div>
      <table className="w-full">
        <thead>
          <tr>
            <th className="th">Pattern</th>
            <th className="th">After benign filter</th>
            <th className="th">Before filter</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([ptype, v]) => (
            <tr key={ptype} className="tbody-row">
              <td className="td">
                <span
                  className="badge"
                  style={{
                    color: typeColor(ptype),
                    background: `${typeColor(ptype)}1a`,
                    border: `1px solid ${typeColor(ptype)}55`,
                  }}
                >
                  {typeLabel(ptype)}
                </span>
              </td>
              {cell(
                "after",
                v.after_filter.f1,
                v.after_filter.tp,
                v.after_filter.fp,
                v.after_filter.fn,
              )}
              {cell("before", v.before_filter.f1)}
            </tr>
          ))}
          <tr className="tbody-row">
            <td className="td text-ink-muted">
              Decoy false alarms{" "}
              <Hint text="Benign accounts built to imitate crime patterns (a busy shop, a big payroll, a landlord, a festival cash kitty, a payout float and two seasonal event loops). Flagged decoys are false alarms; the detector should clear them." />
            </td>
            <td
              className="td num"
              style={{
                color: s.false_alarms_after === 0 ? RISK.green : RISK.amber,
              }}
            >
              {s.false_alarms_after} of {decoyCount(s)} flagged
            </td>
            <td className="td num text-ink-muted">
              {s.false_alarms_before} flagged
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

export default function OverviewPage() {
  const { data, error, waking, reload } = useApiData<Summary>(
    useCallback(() => api<Summary>("/api/summary"), []),
    "summary",
  );
  const [rings, setRings] = useState<Ring[] | null>(null);

  useEffect(() => {
    api<{ rings: Ring[] }>("/api/rings")
      .then((d) => setRings(d.rings))
      .catch(() => {});
  }, []);

  if (error)
    return (
      <ErrorState
        error={`Could not reach the ShadowFlow API: ${error}`}
        onRetry={reload}
      />
    );
  if (!data)
    return waking ? <WakingState onRetry={reload} /> : <PageSkel rows={5} />;

  const topRings = (rings ?? []).slice(0, 6);

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between">
        <h1 className="text-lg font-semibold">Overview</h1>
        <span className="num text-xxs text-ink-faint">
          {data.date_range[0]} - {data.date_range[1]} · {data.n_banks} banks
        </span>
      </div>

      {/* ---- KPI strip ---- */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-2">
        <Kpi
          icon={Activity}
          label="Transactions"
          value={data.total_txns.toLocaleString()}
          sub="90-day window"
        />
        <Kpi
          icon={SearchCheck}
          label="Accounts"
          value={data.n_accounts.toLocaleString()}
          sub={`${data.n_edges.toLocaleString()} edges`}
        />
        <Kpi
          icon={Filter}
          label="Cleared benign"
          value={data.accounts_filtered_benign.toLocaleString()}
          sub="by rhythm fingerprint"
          hint="Accounts whose counterparty diversity, timing regularity and pass-through ratio look like ordinary business."
        />
        <Kpi
          icon={AlertTriangle}
          label="Flagged rings"
          value={data.flagged_rings}
          sub={`of ${data.rings_in_ground_truth} injected`}
        />
        <Kpi
          icon={AlertTriangle}
          label="Ring accounts"
          value={data.ring_accounts.toLocaleString()}
          sub={`${data.reviewed.toLocaleString()} reviewed`}
        />
        <Kpi
          icon={SearchCheck}
          label="Decoy alarms"
          value={`${data.false_alarms_after}/${decoyCount(data)}`}
          sub="benign look-alikes flagged"
          hint="Decoys are benign accounts built to imitate crime patterns. A good run flags none of them."
        />
      </div>

      {/* ---- funnel + accuracy ---- */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3 items-start">
        <Funnel s={data} />
        <Accuracy s={data} />
      </div>

      {/* ---- top rings ---- */}
      <div className="panel">
        <div className="panel-head">
          Top rings by risk
          <Link
            href="/rings"
            className="ml-auto normal-case tracking-normal text-ink-faint hover:text-ink-text"
          >
            all rings →
          </Link>
        </div>
        {topRings.length === 0 ? (
          <Skel h={36 * 6} />
        ) : (
          <table className="w-full">
            <thead>
              <tr>
                <th className="th">Type</th>
                <th className="th">Ring</th>
                <th className="th">Risk</th>
                <th className="th">Accounts</th>
                <th className="th">Banks</th>
                <th className="th">Amount</th>
                <th className="th">Window</th>
                <th className="th"></th>
              </tr>
            </thead>
            <tbody>
              {topRings.map((r) => (
                <tr key={r.ring_id} className="tbody-row">
                  <td className="td">
                    <span
                      className="badge"
                      style={{
                        color: typeColor(r.type),
                        background: `${typeColor(r.type)}1a`,
                        border: `1px solid ${typeColor(r.type)}55`,
                      }}
                    >
                      {typeLabel(r.type)}
                    </span>
                  </td>
                  <td className="td num text-ink-text">{r.ring_id}</td>
                  <td className="td">
                    <RiskBar score={r.score} />
                  </td>
                  <td className="td num">{r.n_accounts}</td>
                  <td className="td">
                    <BankChips banks={r.banks} />
                  </td>
                  <td className="td num">{fmtMoney(r.amount)}</td>
                  <td className="td num text-xxs text-ink-muted">
                    {r.start.slice(5, 16)}
                  </td>
                  <td className="td">
                    <Link
                      href={`/case/${r.ring_id}`}
                      className="text-risk-amber hover:underline"
                    >
                      open case
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
