"use client";

import { useCallback, useMemo, useState } from "react";
import Link from "next/link";
import { api, fmtMoney, typeColor, typeLabel, fmtTime } from "@/lib/api";
import type { Ring } from "@/lib/types";
import {
  PageSkel,
  Sparkline,
  RiskBar,
  BankChips,
  Empty,
} from "@/src/components/ui";
import { useApiData, WakingState, ErrorState } from "@/src/components/ApiGate";

type SortKey = "score" | "amount" | "n_accounts" | "type" | "start";

export default function RingsPage() {
  const { data, error, waking, reload } = useApiData<{ rings: Ring[] }>(
    useCallback(() => api<{ rings: Ring[] }>("/api/rings"), []),
    "rings",
  );
  const rings = data?.rings ?? null;
  const [sortKey, setSortKey] = useState<SortKey>("score");
  const [asc, setAsc] = useState(false);
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [minRisk, setMinRisk] = useState(0);

  const shown = useMemo(() => {
    if (!rings) return null;
    const arr = rings
      .filter((r) => typeFilter === "all" || r.type === typeFilter)
      .filter((r) => r.score >= minRisk);
    arr.sort((a, b) => {
      const va = a[sortKey];
      const vb = b[sortKey];
      const cmp =
        typeof va === "number" && typeof vb === "number"
          ? va - vb
          : String(va).localeCompare(String(vb));
      return asc ? cmp : -cmp;
    });
    return arr;
  }, [rings, sortKey, asc, typeFilter, minRisk]);

  function header(key: SortKey, label: string) {
    return (
      <th
        className="th th-sortable"
        onClick={() => {
          if (sortKey === key) setAsc(!asc);
          else {
            setSortKey(key);
            setAsc(false);
          }
        }}
      >
        {label} {sortKey === key ? (asc ? "▲" : "▼") : ""}
      </th>
    );
  }

  if (error)
    return <ErrorState error={`API error: ${error}`} onRetry={reload} />;
  if (!shown)
    return waking ? <WakingState onRetry={reload} /> : <PageSkel rows={8} />;

  const types = [
    "all",
    ...Array.from(new Set((rings ?? []).map((r) => r.type))),
  ];

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h1 className="text-lg font-semibold">Flagged rings</h1>
        <span className="num text-xxs text-ink-faint">
          {shown.length} of {(rings ?? []).length} rings
        </span>
      </div>

      {/* ---- filters ---- */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-1">
          <span className="text-xxs uppercase tracking-[0.14em] text-ink-muted mr-1">
            Type
          </span>
          {types.map((t) => (
            <button
              key={t}
              onClick={() => setTypeFilter(t)}
              className={t === typeFilter ? "btn-active" : "btn-ghost"}
              style={
                t !== "all" ? { borderColor: `${typeColor(t)}66` } : undefined
              }
            >
              {t === "all" ? "All" : typeLabel(t)}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 ml-auto">
          <span className="text-xxs uppercase tracking-[0.14em] text-ink-muted">
            Min risk
          </span>
          <input
            type="range"
            min={0}
            max={100}
            step={5}
            value={minRisk}
            onChange={(e) => setMinRisk(Number(e.target.value))}
            className="w-40"
          />
          <span className="num text-xs text-ink-text w-6">{minRisk}</span>
        </div>
      </div>

      {/* ---- table ---- */}
      {shown.length === 0 ? (
        <Empty
          title="No rings match the filters"
          sub="Lower the minimum risk or clear the type filter."
        />
      ) : (
        <div className="panel overflow-x-auto">
          <table className="w-full min-w-[980px]">
            <thead>
              <tr>
                {header("type", "Type")}
                <th className="th">Ring</th>
                {header("score", "Risk")}
                {header("n_accounts", "Accts")}
                <th className="th">Banks</th>
                {header("amount", "Total")}
                <th className="th">Flow</th>
                {header("start", "Window")}
                <th className="th"></th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
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
                  <td className="td">
                    <Sparkline values={r.sparkline} />
                    <span className="text-xxs text-ink-faint ml-1.5">
                      {r.txn_count} txns
                    </span>
                  </td>
                  <td className="td num text-xxs text-ink-muted">
                    {fmtTime(r.start)}
                    <span className="text-ink-faint"> → </span>
                    {fmtTime(r.end)}
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
        </div>
      )}
    </div>
  );
}
