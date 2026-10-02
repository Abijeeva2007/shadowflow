"use client";

import { useCallback, useState } from "react";
import { Lock, Unlock, ShieldCheck } from "lucide-react";
import {
  api,
  fmtTime,
  typeColor,
  typeLabel,
  bankColor,
  C,
  RISK,
} from "@/lib/api";
import type { FederationSignals, RevealResult } from "@/lib/types";
import { Hint, PageSkel, Empty } from "@/src/components/ui";
import { useApiData, WakingState, ErrorState } from "@/src/components/ApiGate";

export default function FederationPage() {
  const { data, error, waking, reload } = useApiData<FederationSignals>(
    useCallback(() => api<FederationSignals>("/api/federation/signals"), []),
    "federation",
  );
  const [selectedCase, setSelectedCase] = useState<string | null>(null);
  const [officer, setOfficer] = useState("");
  const [revealed, setRevealed] = useState<Record<string, RevealResult>>({});
  const [revealBusy, setRevealBusy] = useState<string | null>(null);

  async function reveal(hashedId: string) {
    setRevealBusy(hashedId);
    try {
      const res = await api<RevealResult>("/api/federation/reveal", {
        method: "POST",
        body: JSON.stringify({ hashed_id: hashedId, authorised_by: officer }),
      });
      setRevealed((r) => ({ ...r, [hashedId]: res }));
    } catch (e: any) {
      setRevealed((r) => ({
        ...r,
        [hashedId]: { revealed: false, reason: String(e.message ?? e) },
      }));
    } finally {
      setRevealBusy(null);
    }
  }

  if (error)
    return <ErrorState error={`API error: ${error}`} onRetry={reload} />;
  if (!data)
    return waking ? <WakingState onRetry={reload} /> : <PageSkel rows={6} />;

  const caseObj = data.cases.find((c) => c.case_id === selectedCase);
  const signals = selectedCase
    ? data.signals.filter((s) => new Set(caseObj?.hashed_ids).has(s.hashed_id))
    : data.signals;

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h1 className="text-lg font-semibold">Cross-bank federation</h1>
        <span className="num text-xxs text-ink-faint">
          {data.n_signals} signals · {data.cases.length} joint cases
        </span>
      </div>
      <p className="text-xs text-ink-muted max-w-3xl">
        Each bank analysed only its own logs and shared the minimum: a salted
        hash of the account, the pattern type, a time window, a coarse amount
        bucket and a direction. The coordinator stitches joint cases from these
        signals alone.
        <Hint text="Workflow demo, not a cryptographic guarantee: anyone holding the shared salt could hash-guess account ids, and amount buckets leak coarse structure. Real systems use per-bank keys plus private set intersection." />
      </p>

      {/* ---------------- two columns ---------------- */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3 items-start">
        {/* -------- coordinator column -------- */}
        <div className="panel">
          <div className="panel-head">
            <Lock size={12} className="text-ink-muted" />
            Coordinator sees
            <span className="ml-auto normal-case tracking-normal text-ink-faint">
              hashed IDs only
            </span>
          </div>

          {/* joint cases */}
          <div className="border-b border-ink-border p-3 space-y-2">
            <div className="text-xxs uppercase tracking-[0.14em] text-ink-muted">
              Joint cases
            </div>
            {data.cases.map((c) => (
              <button
                key={c.case_id}
                onClick={() =>
                  setSelectedCase(c.case_id === selectedCase ? null : c.case_id)
                }
                className={`w-full text-left border rounded px-3 py-2 transition-colors ${
                  selectedCase === c.case_id
                    ? "border-risk-amber/60 bg-risk-amber/5"
                    : "border-ink-border hover:border-ink-faint"
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className="num text-xs text-ink-text">{c.case_id}</span>
                  {c.pattern_types.map((t) => (
                    <span
                      key={t}
                      className="badge"
                      style={{
                        color: typeColor(t),
                        background: `${typeColor(t)}1a`,
                        border: `1px solid ${typeColor(t)}55`,
                      }}
                    >
                      {typeLabel(t)}
                    </span>
                  ))}
                  <span className="ml-auto num text-xxs text-ink-muted">
                    {c.n_signals} signals · {c.banks.length} banks
                  </span>
                </div>
                <div className="num text-xxs text-ink-faint mt-0.5">
                  {c.banks.join(" + ")} · window {fmtTime(c.window_start)} →{" "}
                  {fmtTime(c.window_end)}
                </div>
              </button>
            ))}
            {data.cases.length === 0 && (
              <Empty title="No cross-bank cases stitched" />
            )}
          </div>

          {/* bank-lane visual for the selected case */}
          {caseObj && (
            <div className="border-b border-ink-border p-3">
              <div className="text-xxs uppercase tracking-[0.14em] text-ink-muted mb-2">
                Case {caseObj.case_id} across bank lanes
              </div>
              <BankLanes
                banks={data.banks}
                signals={data.signals.filter((s) =>
                  new Set(caseObj.hashed_ids).has(s.hashed_id),
                )}
              />
            </div>
          )}

          {/* signal list (hashed) */}
          <div className="p-3">
            <div className="text-xxs uppercase tracking-[0.14em] text-ink-muted mb-2">
              {selectedCase
                ? `Signals in ${selectedCase}`
                : "All shared signals"}{" "}
              · {signals.length}
            </div>
            <div className="max-h-[300px] overflow-y-auto space-y-1">
              {signals.slice(0, 60).map((s, i) => (
                <div
                  key={i}
                  className="flex items-center gap-2 text-xxs border border-ink-border rounded px-2 h-7"
                >
                  <span
                    className="w-2 h-2 rounded-sm shrink-0"
                    style={{ background: bankColor(s.bank) }}
                  />
                  <span className="num text-ink-muted">{s.hashed_id}</span>
                  <span
                    className="badge"
                    style={{ color: typeColor(s.pattern_type) }}
                  >
                    {typeLabel(s.pattern_type)}
                  </span>
                  <span className="text-ink-faint">{s.direction}</span>
                  <span className="text-ink-faint">{s.amount_bucket}</span>
                  <span className="ml-auto text-ink-faint num">
                    {fmtTime(s.window[0])}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* -------- investigator column -------- */}
        <div className="panel flex flex-col">
          <div className="panel-head">
            <ShieldCheck size={12} className="text-risk-amber" />
            Investigator sees
            <span className="ml-auto normal-case tracking-normal text-ink-faint">
              after mock authorisation
            </span>
          </div>

          <div className="p-3 border-b border-ink-border">
            <label className="text-xxs uppercase tracking-[0.14em] text-ink-muted block mb-1">
              Authorising officer
            </label>
            <input
              value={officer}
              onChange={(e) => setOfficer(e.target.value)}
              placeholder="Name (min 3 characters)"
              className="w-full bg-ink border border-ink-border rounded px-2.5 h-8 text-xs text-ink-text placeholder:text-ink-faint focus:border-ink-faint outline-none"
            />
            <div className="text-xxs text-ink-faint mt-1.5">
              Mock authorisation for the demo - in production this would be dual
              control plus legal process. Pick a signal on the left, then
              request the reveal here.
            </div>
          </div>

          <div
            className="p-3 space-y-2 overflow-y-auto"
            style={{ maxHeight: 430 }}
          >
            {Object.keys(revealed).length === 0 && (
              <Empty
                title="Nothing revealed yet"
                sub="Request a reveal from a hashed signal to see the account behind it."
              />
            )}
            {Object.entries(revealed).map(([hash, res]) => (
              <div
                key={hash}
                className="border border-ink-border rounded p-2.5"
              >
                <div className="flex items-center gap-2">
                  {res.revealed ? (
                    <Unlock size={12} style={{ color: RISK.green }} />
                  ) : (
                    <Lock size={12} style={{ color: RISK.red }} />
                  )}
                  <span className="num text-xxs text-ink-faint">{hash}</span>
                  <span
                    className="ml-auto chip"
                    style={{
                      borderColor: res.revealed ? RISK.green : RISK.red,
                      color: res.revealed ? RISK.green : RISK.red,
                    }}
                  >
                    {res.revealed ? "REVEALED" : "DENIED"}
                  </span>
                </div>
                {res.revealed ? (
                  <div className="mt-1.5 text-xs">
                    <span className="num text-ink-text">{res.account_id}</span>
                    <span className="text-ink-faint text-xxs ml-2">
                      authorised by {res.authorised_by}
                    </span>
                  </div>
                ) : (
                  <div className="mt-1.5 text-xxs" style={{ color: RISK.red }}>
                    {res.reason ?? "authorisation required"}
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* quick reveal list */}
          <div className="p-3 border-t border-ink-border mt-auto">
            <div className="text-xxs uppercase tracking-[0.14em] text-ink-muted mb-2">
              Request reveal
            </div>
            <div className="max-h-[150px] overflow-y-auto space-y-1">
              {signals.slice(0, 20).map((s, i) => {
                const r = revealed[s.hashed_id];
                return (
                  <div key={i} className="flex items-center gap-2 text-xxs">
                    <span className="num text-ink-faint truncate w-24">
                      {s.hashed_id}
                    </span>
                    {r?.revealed ? (
                      <span className="num" style={{ color: RISK.green }}>
                        {r.account_id}
                      </span>
                    ) : (
                      <button
                        className="btn-ghost !h-6 !px-2"
                        onClick={() => reveal(s.hashed_id)}
                        disabled={
                          revealBusy === s.hashed_id ||
                          officer.trim().length < 3
                        }
                      >
                        {revealBusy === s.hashed_id ? "…" : "reveal"}
                      </button>
                    )}
                    <span className="text-ink-faint ml-auto">{s.bank}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      <div className="border border-ink-border rounded px-3 py-2 text-xxs text-ink-faint">
        <b className="text-ink-muted">What this demo shows (and does not):</b>{" "}
        the coordinator joins signals on salted HMAC hashes without seeing raw
        customer data. This is a workflow demonstration, not a cryptographic
        guarantee - see the tooltip above for the honest caveats.
      </div>
    </div>
  );
}

/** Three horizontal bank lanes with hashed signals plotted on them. */
function BankLanes({
  banks,
  signals,
}: {
  banks: string[];
  signals: FederationSignals["signals"];
}) {
  const W = 620;
  const rowH = 34;
  const H = banks.length * rowH + 8;
  const times = signals.flatMap((s) => [
    new Date(s.window[0].replace(" ", "T")).getTime(),
    new Date(s.window[1].replace(" ", "T")).getTime(),
  ]);
  const t0 = Math.min(...times);
  const t1 = Math.max(...times);
  const x = (t: number) => 60 + ((t - t0) / Math.max(t1 - t0, 1)) * (W - 80);

  // connect same-hash signals across lanes (the coordinator's stitch)
  const byHash = new Map<string, FederationSignals["signals"]>();
  for (const s of signals) {
    byHash.set(s.hashed_id, [...(byHash.get(s.hashed_id) ?? []), s]);
  }

  const laneY = (bank: string) => banks.indexOf(bank) * rowH + 17;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
      {banks.map((b) => (
        <g key={b}>
          <line
            x1={54}
            y1={laneY(b)}
            x2={W - 10}
            y2={laneY(b)}
            stroke={C.border}
            strokeWidth={6}
            strokeLinecap="round"
          />
          <text
            x={0}
            y={laneY(b) + 3}
            fontSize="9"
            fill={C.muted}
            fontFamily="JetBrains Mono, monospace"
          >
            {b}
          </text>
        </g>
      ))}
      {[...byHash.entries()].map(([hash, sigs]) => {
        if (sigs.length < 2) return null;
        const pts = sigs
          .map((s) => ({ s, y: laneY(s.bank) }))
          .sort((a, b2) => a.y - b2.y);
        return (
          <polyline
            key={hash}
            points={pts
              .map(
                (p) =>
                  `${x(new Date(p.s.window[0].replace(" ", "T")).getTime())},${p.y}`,
              )
              .join(" ")}
            fill="none"
            stroke={RISK.amber}
            strokeWidth={1}
            strokeOpacity={0.7}
            strokeDasharray="3 2"
          />
        );
      })}
      {signals.map((s, i) => (
        <circle
          key={i}
          cx={x(new Date(s.window[0].replace(" ", "T")).getTime())}
          cy={laneY(s.bank)}
          r={4}
          fill={bankColor(s.bank)}
          stroke={C.bg}
          strokeWidth={1}
        />
      ))}
    </svg>
  );
}
