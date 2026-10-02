"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  Play,
  Pause,
  Download,
  ShieldCheck,
  FileSearch,
  ArrowLeft,
} from "lucide-react";
import RingGraph from "@/components/RingGraph";
import FlowStepChart from "@/components/FlowStepChart";
import TraceSankey from "@/components/TraceSankey";
import {
  api,
  API_URL,
  fmtMoney,
  fmtTime,
  typeColor,
  typeLabel,
  bankColor,
  C,
  RISK,
} from "@/lib/api";
import type {
  AccountDetail,
  RingGraph as RingGraphData,
  TraceResult,
  VerifyResult,
  CyElement,
} from "@/lib/types";
import {
  Hint,
  PageSkel,
  RiskGauge,
  VerifyChip,
  Empty,
  Skel,
} from "@/src/components/ui";
import { useApiData, WakingState, ErrorState } from "@/src/components/ApiGate";

const SPEEDS = [1, 2, 4];
const BASE_MS = 550;

export default function CasePage() {
  const params = useParams<{ ringId: string }>();
  const ringId = params?.ringId ?? "";

  // time replay
  const [edgeTimes, setEdgeTimes] = useState<{ id: string; t: number }[]>([]);
  const [idx, setIdx] = useState<number>(0); // txns revealed
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const playTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  // selection + panels
  const [selectedEdge, setSelectedEdge] = useState<CyElement["data"] | null>(
    null,
  );
  const [accountId, setAccountId] = useState<string | null>(null);
  const [acct, setAcct] = useState<AccountDetail | null>(null);
  const [acctErr, setAcctErr] = useState<string | null>(null);
  const [tab, setTab] = useState<"account" | "trace">("account");

  // trace + verify
  const [trace, setTrace] = useState<TraceResult | null>(null);
  const [traceBusy, setTraceBusy] = useState(false);
  const [verify, setVerify] = useState<VerifyResult | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  // ---- load graph ---------------------------------------------------------
  const loadGraph = useCallback(async (): Promise<RingGraphData> => {
    const g = await api<RingGraphData>(`/api/rings/${ringId}/graph`);
    const times = g.elements
      .filter((e) => e.data.source)
      .map((e) => ({
        id: e.data.id,
        t: new Date(e.data.time!.replace(" ", "T")).getTime(),
      }))
      .sort((a, b) => a.t - b.t);
    setEdgeTimes(times);
    setIdx(times.length); // start fully revealed
    const first = g.elements.find((e) => e.data.kind === "account");
    if (first) setAccountId(first.data.id);
    return g;
  }, [ringId]);

  const {
    data: graph,
    error,
    waking,
    reload,
  } = useApiData<RingGraphData>(
    ringId
      ? loadGraph
      : async () => {
          throw new Error("missing ring id");
        },
    ringId,
  );

  // reset per-case panels when the graph (re)loads
  useEffect(() => {
    setTrace(null);
    setVerify(null);
    setSelectedEdge(null);
    setAcct(null);
  }, [graph]);

  // ---- replay --------------------------------------------------------------
  useEffect(() => {
    if (playing) {
      playTimer.current = setInterval(() => {
        setIdx((i) => {
          const next = i + 1;
          if (next >= edgeTimes.length) {
            setPlaying(false);
            return edgeTimes.length;
          }
          return next;
        });
      }, BASE_MS / speed);
    }
    return () => {
      if (playTimer.current) clearInterval(playTimer.current);
    };
  }, [playing, speed, edgeTimes.length]);

  const visibleTxnIds = useMemo(() => {
    if (!edgeTimes.length) return null;
    return new Set(edgeTimes.slice(0, idx).map((x) => x.id));
  }, [idx, edgeTimes]);

  const currentTime =
    idx > 0 && edgeTimes.length
      ? fmtTime(
          new Date(
            edgeTimes[Math.min(idx, edgeTimes.length) - 1].t,
          ).toISOString(),
        )
      : null;

  // ---- account panel --------------------------------------------------------
  useEffect(() => {
    if (!accountId) return;
    setAcct(null);
    setAcctErr(null);
    api<AccountDetail>(`/api/accounts/${accountId}`)
      .then(setAcct)
      .catch((e) => setAcctErr(String(e.message ?? e)));
  }, [accountId]);

  // ---- trace ----------------------------------------------------------------
  const runTrace = useCallback(async () => {
    if (!selectedEdge) return;
    setTraceBusy(true);
    try {
      const res = await api<TraceResult>("/api/trace", {
        method: "POST",
        body: JSON.stringify({
          txn_id: selectedEdge.id,
          max_depth: 6,
          min_taint: 100,
        }),
      });
      setTrace(res);
    } catch (e: any) {
      setTrace(null);
    } finally {
      setTraceBusy(false);
    }
  }, [selectedEdge]);

  const traceEdges = useMemo(
    () => new Set(trace?.tree.map((n) => n.txn_id) ?? []),
    [trace],
  );
  const traceFractions = useMemo(() => {
    const m: Record<string, number> = {};
    trace?.tree.forEach((n) => (m[n.txn_id] = n.taint_fraction));
    return m;
  }, [trace]);

  // ---- export / verify --------------------------------------------------------
  async function doVerify() {
    setBusy("verify");
    try {
      setVerify(await api<VerifyResult>(`/api/verify/${ringId}`));
    } catch (e: any) {
      setVerify(null);
    } finally {
      setBusy(null);
    }
  }

  if (error)
    return (
      <div>
        <ErrorState error={`API error: ${error}`} onRetry={reload} />
        <Link href="/rings" className="btn-ghost mt-3">
          <ArrowLeft size={13} /> back to rings
        </Link>
      </div>
    );
  if (!graph)
    return waking ? <WakingState onRetry={reload} /> : <PageSkel rows={6} />;

  const ringMeta = graph;
  const accounts = graph.elements.filter((e) => e.data.kind === "account");
  const neighbours = accounts.filter((e) => e.data.kind === "neighbour");
  const selectedBank = acct?.bank;

  return (
    <div className="space-y-3">
      {/* ---------------- top bar ---------------- */}
      <div className="flex items-center gap-3 flex-wrap">
        <Link href="/rings" className="btn-ghost !px-2" aria-label="back">
          <ArrowLeft size={13} />
        </Link>
        <h1 className="num text-base font-semibold">{ringId}</h1>
        <span
          className="badge"
          style={{
            color: typeColor(graph.type),
            background: `${typeColor(graph.type)}1a`,
            border: `1px solid ${typeColor(graph.type)}55`,
          }}
        >
          {typeLabel(graph.type)}
        </span>
        <span className="chip border-ink-border text-ink-muted">
          risk{" "}
          <span style={{ color: RISK.amber }}>{graph.score.toFixed(0)}</span>
        </span>
        <span className="num text-xxs text-ink-faint">
          {graph.window[0]} → {graph.window[1]}
        </span>

        <div className="ml-auto flex items-center gap-2">
          {verify && (
            <VerifyChip
              valid={verify.chain_valid && (verify.matches_export ?? true)}
              hash={verify.current_final_hash}
            />
          )}
          <button
            className="btn-ghost"
            onClick={doVerify}
            disabled={busy === "verify"}
          >
            <ShieldCheck size={13} /> Verify integrity
          </button>
          <a
            className="btn-primary"
            href={`${API_URL}/api/rings/${ringId}/dossier.pdf`}
            target="_blank"
            rel="noreferrer"
          >
            <Download size={13} /> Export dossier
          </a>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-3 items-start">
        {/* ---------------- left column ---------------- */}
        <div className="space-y-3 min-w-0">
          {/* graph */}
          <div className="panel overflow-hidden">
            <div className="panel-head">
              Flow of funds · in time order
              <span className="ml-auto normal-case tracking-normal text-ink-faint">
                click a node for its file · click an edge to trace it
              </span>
            </div>
            <RingGraph
              graph={graph}
              visibleTxnIds={visibleTxnIds}
              traceEdges={traceEdges}
              traceFractions={traceFractions}
              selectedEdgeId={selectedEdge?.id ?? null}
              onEdgeClick={(d) => {
                setSelectedEdge(d);
                if (d) setTab("trace");
              }}
              onNodeClick={(id) => {
                setAccountId(id);
                setTab("account");
              }}
            />

            {/* ---- scrubber ---- */}
            <div className="border-t border-ink-border px-3 py-2.5">
              <div className="flex items-center gap-3">
                <button
                  className={playing ? "btn-active" : "btn-ghost"}
                  onClick={() => {
                    if (!playing && idx >= edgeTimes.length) setIdx(0);
                    setPlaying(!playing);
                  }}
                  aria-label={playing ? "pause" : "play"}
                >
                  {playing ? <Pause size={13} /> : <Play size={13} />}
                </button>
                <div className="flex gap-1">
                  {SPEEDS.map((s) => (
                    <button
                      key={s}
                      className={
                        s === speed
                          ? "btn-active !h-7 !px-2"
                          : "btn-ghost !h-7 !px-2"
                      }
                      onClick={() => setSpeed(s)}
                    >
                      {s}x
                    </button>
                  ))}
                </div>

                <div className="relative flex-1 h-8">
                  {/* tick per transaction */}
                  <div className="absolute top-0 left-0 right-0 h-2">
                    {edgeTimes.map((e, i) => (
                      <span
                        key={e.id}
                        className="scrub-tick"
                        style={{
                          left: `${(i / Math.max(edgeTimes.length - 1, 1)) * 100}%`,
                          background: i < idx ? RISK.amber : "#2e3742",
                        }}
                      />
                    ))}
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={edgeTimes.length}
                    value={idx}
                    onChange={(e) => {
                      setPlaying(false);
                      setIdx(Number(e.target.value));
                    }}
                    className="w-full absolute bottom-1"
                    aria-label="time scrubber"
                  />
                </div>

                <span className="num text-xxs text-ink-muted w-56 text-right whitespace-nowrap">
                  {currentTime ?? "start"} · {idx}/{edgeTimes.length} txns
                </span>
              </div>
              <div className="text-xxs text-ink-faint mt-1">
                Unreached transfers stay visible but dimmed, so the shape of the
                whole ring is never lost while you replay it.
              </div>
            </div>
          </div>

          {/* ---- hold-time step chart ---- */}
          <div className="panel p-3">
            {accountId ? (
              <FlowStepChart
                elements={graph.elements}
                account={accountId}
                bank={
                  selectedBank ??
                  accounts.find((a) => a.data.id === accountId)?.data.bank
                }
              />
            ) : (
              <Empty title="Click a node to see its money in / out over time" />
            )}
          </div>
        </div>

        {/* ---------------- right inspector ---------------- */}
        <div className="panel flex flex-col" style={{ minHeight: 620 }}>
          <div className="flex border-b border-ink-border">
            {(["account", "trace"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`flex-1 h-9 text-xxs uppercase tracking-[0.14em] ${
                  tab === t
                    ? "text-ink-text border-b-2 border-risk-amber"
                    : "text-ink-muted hover:text-ink-text"
                }`}
              >
                {t === "account" ? "Account" : "Trace"}
              </button>
            ))}
          </div>

          {tab === "account" && (
            <div
              className="p-3 space-y-3 overflow-y-auto"
              style={{ maxHeight: 580 }}
            >
              {acctErr && <div className="err-banner">{acctErr}</div>}
              {!acct && !acctErr && <Skel h={120} />}
              {acct && (
                <>
                  <div>
                    <div className="num text-sm text-ink-text">
                      {acct.account}
                    </div>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span
                        className="inline-block w-2 h-2 rounded-sm"
                        style={{ background: bankColor(acct.bank) }}
                      />
                      <span className="text-xxs text-ink-muted">
                        {acct.bank}
                      </span>
                      {acct.benign && (
                        <span
                          className="chip"
                          style={{ borderColor: RISK.green, color: RISK.green }}
                        >
                          cleared benign
                        </span>
                      )}
                      {acct.in_rings.length > 0 && (
                        <span
                          className="chip"
                          style={{ borderColor: RISK.amber, color: RISK.amber }}
                        >
                          in {acct.in_rings.join(", ")}
                        </span>
                      )}
                    </div>
                  </div>

                  <RiskGauge score={acct.risk_score} />

                  <div>
                    <div className="text-xxs uppercase tracking-[0.14em] text-ink-muted mb-1">
                      Why it was flagged
                    </div>
                    <ul className="space-y-1.5">
                      {acct.reasons.map((r, i) => (
                        <li
                          key={i}
                          className="text-xxs text-ink-muted leading-4 pl-2 border-l border-ink-border"
                        >
                          {r}
                        </li>
                      ))}
                    </ul>
                  </div>

                  <div>
                    <div className="text-xxs uppercase tracking-[0.14em] text-ink-muted mb-1 flex items-center gap-1">
                      Velocity
                      <Hint text="How fast money moves through this account. Pass-through is the share of everything received that was sent straight out again - near 100% is mule-like." />
                    </div>
                    <table className="w-full">
                      <tbody>
                        {[
                          ["Transactions", acct.velocity.txn_count.toFixed(0)],
                          [
                            "Peak burst",
                            `${acct.velocity.peak_burst_rate.toFixed(0)} / hour`,
                          ],
                          [
                            "Median hold",
                            acct.velocity.median_hold_min >= 0
                              ? `${acct.velocity.median_hold_min.toFixed(0)} min`
                              : "no matched pairs",
                          ],
                          [
                            "Pass-through",
                            `${(acct.velocity.pass_through_ratio * 100).toFixed(0)}%`,
                          ],
                          [
                            "Largest inflow",
                            fmtMoney(acct.velocity.amount_max),
                          ],
                        ].map(([k, v]) => (
                          <tr key={k}>
                            <td className="td !h-7 !px-0 text-ink-muted !border-ink-border/60">
                              {k}
                            </td>
                            <td className="td !h-7 !px-0 num text-right !border-ink-border/60">
                              {v}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {acct.filter_reason && (
                    <div className="text-xxs text-ink-faint border-t border-ink-border pt-2">
                      Benign filter: {acct.filter_reason}
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {tab === "trace" && (
            <div
              className="p-3 space-y-3 overflow-y-auto"
              style={{ maxHeight: 580 }}
            >
              {!selectedEdge && (
                <Empty
                  title="Click any transfer in the graph"
                  sub="Then trace how the dirty money spreads forward from it."
                />
              )}
              {selectedEdge && (
                <>
                  <div className="border border-ink-border rounded p-2.5">
                    <div className="num text-xs text-ink-text">
                      {selectedEdge.id}
                    </div>
                    <div className="text-xxs text-ink-muted mt-0.5">
                      {selectedEdge.source} → {selectedEdge.target}
                    </div>
                    <div className="num text-xxs text-ink-muted">
                      {fmtMoney(selectedEdge.amount)} ·{" "}
                      {fmtTime(selectedEdge.time)} · {selectedEdge.channel}
                    </div>
                    <button
                      className="btn-primary mt-2 w-full justify-center"
                      onClick={runTrace}
                      disabled={traceBusy}
                    >
                      <FileSearch size={13} />
                      {traceBusy ? "Tracing…" : "Trace dirty money"}
                    </button>
                  </div>

                  {trace && (
                    <>
                      <div className="grid grid-cols-2 gap-2">
                        <div className="panel2 rounded border border-ink-border p-2">
                          <div className="text-xxs text-ink-faint">
                            dirty traced
                          </div>
                          <div
                            className="num text-sm"
                            style={{ color: RISK.red }}
                          >
                            {fmtMoney(trace.total_traced)}
                          </div>
                        </div>
                        <div className="panel2 rounded border border-ink-border p-2">
                          <div className="text-xxs text-ink-faint">hops</div>
                          <div className="num text-sm text-ink-text">
                            {trace.n_hops}
                          </div>
                        </div>
                      </div>

                      <div>
                        <div className="text-xxs uppercase tracking-[0.14em] text-ink-muted mb-1 flex items-center gap-1">
                          Where the money ended up
                          <Hint text="Proportional (poison) model: when dirty funds mix with clean ones in an account, outgoing payments carry the same dirty share. Bands are weighted by the dirty amount." />
                        </div>
                        <TraceSankey tree={trace.tree} />
                      </div>

                      <div>
                        <div className="text-xxs uppercase tracking-[0.14em] text-ink-muted mb-1">
                          Trace log
                        </div>
                        <div className="space-y-0.5 max-h-44 overflow-y-auto">
                          {trace.events.slice(0, 40).map((e, i) => (
                            <div
                              key={i}
                              className="text-xxs text-ink-faint num leading-4"
                            >
                              {e}
                            </div>
                          ))}
                        </div>
                      </div>
                    </>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
