"""ShadowFlow API - FastAPI app serving the whole demo.

Local:   uvicorn main:app --reload --port 8000        (from the backend/ folder)
Render:  uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}

Detection runs ONCE at startup and the result is cached in memory, so the
first request after boot is fast. How long startup took is logged.
"""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from engine import config
from engine import federation as fed
from engine.adversary import run_adversary
from engine.dossier import build_evidence_chain, export_pdf, verify_evidence_chain
from engine.pipeline import DetectionState, run_pipeline
from engine.taint import trace_taint
from engine.velocity import burst_timeline, velocity_features

STATE: DetectionState | None = None
FED: fed.FederatedState | None = None
ADVERSARY_CACHE: dict | None = None
DOSSIER_CHAINS: dict[str, list[dict]] = {}  # ring_id -> hash chain at export time


def _allowed_origins() -> list[str]:
    """CORS allow-list from ALLOWED_ORIGINS (comma-separated).

    Defaults to the local dashboard origins (3000 and 3001, on both localhost
    and 127.0.0.1) so a dev server on either port can talk to the API. Set
    ALLOWED_ORIGINS to your deployed dashboard domain(s) in production - e.g.
    "https://your-app.vercel.app" - or "*" to allow any origin.
    """
    default = (
        "http://localhost:3000,http://localhost:3001,"
        "http://127.0.0.1:3000,http://127.0.0.1:3001"
    )
    raw = os.getenv("ALLOWED_ORIGINS", default).strip()
    if raw in ("", "*"):
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


def _ensure_data() -> None:
    """Regenerate the synthetic dataset on startup if it is missing.

    The generated CSVs + ground_truth.json are committed so deployment never
    has to regenerate them; this is the safety net for an empty/fresh data
    directory (e.g. a stripped build).
    """
    have = list(config.DATA_DIR.glob("transactions_*.csv"))
    truth = config.DATA_DIR / "ground_truth.json"
    if len(have) >= len(config.BANKS) and truth.exists():
        return
    print("ShadowFlow: data missing -> generating synthetic dataset (seed 42)...")
    import generate_data

    generate_data.main()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global STATE, FED
    t0 = time.perf_counter()
    _ensure_data()
    print("ShadowFlow: running detection pipeline (cached for all requests)...")
    STATE = run_pipeline()
    FED = fed.build_signals(STATE.txns)
    fed.stitch_chains(FED)
    elapsed = time.perf_counter() - t0
    print(
        f"ShadowFlow ready in {elapsed:.1f}s: {len(STATE.rings)} rings, "
        f"{len(FED.chains)} federated cases."
    )
    yield


app = FastAPI(
    title="ShadowFlow",
    version="0.1.0",
    description="Forensic demo: coordinated laundering detection",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------- models
class TraceRequest(BaseModel):
    txn_id: str | None = Field(None, description="starting transaction")
    account: str | None = Field(None, description="or: starting account")
    since: str | None = Field(None, description="with account: start time")
    max_depth: int = Field(6, ge=1, le=10)
    min_taint: float = Field(100.0, ge=0)


class AdversaryRequest(BaseModel):
    source: str | None = None
    target: str | None = None
    amount: float = Field(100_000.0, gt=0)
    # optional lever overrides from the UI sliders; when given, the grid is
    # built as the cross product of {baseline, lever} over all four levers
    hop_delay_hours: float | None = Field(None, ge=0, le=96)
    n_splits: int | None = Field(None, ge=1, le=8)
    n_decoys: int | None = Field(None, ge=0, le=100)
    n_banks: int | None = Field(None, ge=1, le=3)


class RevealRequest(BaseModel):
    hashed_id: str
    authorised_by: str = Field(
        ..., min_length=3, description="mock authorisation: officer name"
    )


def _state() -> DetectionState:
    if STATE is None:
        raise HTTPException(503, "engine still warming up - retry in a moment")
    return STATE


def _get_ring(ring_id: str) -> dict:
    try:
        return _state().ring(ring_id)
    except KeyError:
        raise HTTPException(
            404, f"unknown ring '{ring_id}'. " f"See GET /api/rings for valid ids."
        )


# -------------------------------------------------------------------- endpoints
@app.get("/health")
def healthcheck() -> dict:
    """Fast readiness probe for Render / uptime checks.

    Deliberately returns without touching detection state so it answers in
    milliseconds. By the time uvicorn serves requests the startup pipeline has
    already completed (lifespan runs before the socket accepts), so `ready`
    is True for any live request.
    """
    return {"status": "ok", "ready": STATE is not None}


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "rings": len(STATE.rings) if STATE else 0}


@app.get("/api/summary")
def summary() -> dict:
    st = _state()
    m = st.metrics
    decoy_after = m.get("decoys", {}).get("after_filter", {})
    decoy_before = m.get("decoys", {}).get("before_filter", {})
    ring_accs = {a for r in st.rings for a in r["accounts"]}
    return {
        # funnel: raw alerts -> benign filter -> reviewed -> confirmed rings
        "accounts_total": st.filter_counts["accounts_total"],
        "reviewed": st.filter_counts["alerts_after"],
        "ring_accounts": len(ring_accs),
        "total_txns": int(len(st.txns)),
        "n_accounts": st.g.number_of_nodes(),
        "n_edges": st.g.number_of_edges(),
        "n_banks": len(config.BANKS),
        "date_range": [str(st.txns.timestamp.min()), str(st.txns.timestamp.max())],
        "flagged_rings": len(st.rings),
        "flagged_accounts": len(st.accounts),
        "alerts_before": st.filter_counts["alerts_before"],
        "alerts_after": st.filter_counts["alerts_after"],
        "accounts_filtered_benign": st.filter_counts["alerts_filtered"],
        "false_alarms_before": decoy_before.get("total_flagged", 0),
        "false_alarms_after": decoy_after.get("total_flagged", 0),
        "precision_recall": m.get("per_pattern", {}),
        "decoy_checks": m.get("decoys", {}).get("after_filter", {}),
        "rings_in_ground_truth": m.get("summary", {}).get("rings_in_ground_truth"),
    }


@app.get("/api/rings")
def rings() -> dict:
    st = _state()
    return {
        "rings": [
            {
                "ring_id": r["ring_id"],
                "type": r["type"],
                "score": r["score"],
                "n_accounts": len(r["accounts"]),
                "accounts": r["accounts"],
                "banks": r["banks"],
                "amount": r["amount"],
                "start": r["start"],
                "end": r["end"],
                "txn_count": len(r["hit"]["txn_ids"]),
                # amount-per-txn in time order, for a sparkline
                "sparkline": [
                    round(e[3]["amount"], 2)
                    for e in sorted(
                        (e for e in st.g.edges(keys=True, data=True) if e[2] in wanted),
                        key=lambda e: e[3]["timestamp"],
                    )
                ],
            }
            for r in st.rings
            if (wanted := set(r["hit"]["txn_ids"])) is not None
        ]
    }


@app.get("/api/rings/{ring_id}/graph")
def ring_graph(ring_id: str) -> dict:
    """Cytoscape-ready elements for one ring."""
    st = _state()
    ring = _get_ring(ring_id)
    accounts = set(ring["accounts"])
    origin = ring["hit"].get("origin")
    terminal = ring["hit"].get("terminal") or ring["hit"].get("collector")
    elements: list[dict] = []
    for a in ring["accounts"]:
        rec = st.accounts.get(a, {})
        elements.append(
            {
                "data": {
                    "id": a,
                    "label": a,
                    "bank": st.g.nodes[a].get("bank", "?"),
                    "kind": "account",
                    "risk": rec.get("score", 0),
                    "degree": st.g.degree(a),
                    "roles": [
                        *(["origin"] if a == origin else []),
                        *(["terminal"] if a == terminal else []),
                    ],
                }
            }
        )
    wanted = set(ring["hit"]["txn_ids"])
    for u, v, k, d in st.g.edges(keys=True, data=True):
        if k in wanted:
            elements.append(
                {
                    "data": {
                        "id": k,
                        "source": u,
                        "target": v,
                        "amount": round(d["amount"], 2),
                        "time": d["timestamp"].strftime("%Y-%m-%d %H:%M:%S"),
                        "channel": d["channel"],
                        "label": f"{d['amount']:,.0f}",
                    }
                }
            )
    # any flagged neighbour accounts not in the ring (context, dimmed in UI)
    neighbours: set[str] = set()
    for a in ring["accounts"]:
        for _, w in st.g.out_edges(a):
            if w not in accounts and w in st.accounts:
                neighbours.add(w)
        for w, _ in st.g.in_edges(a):
            if w not in accounts and w in st.accounts:
                neighbours.add(w)
    for n in sorted(neighbours)[:12]:
        rec = st.accounts.get(n, {})
        elements.append(
            {
                "data": {
                    "id": n,
                    "label": n,
                    "bank": st.g.nodes[n].get("bank", "?"),
                    "kind": "neighbour",
                    "risk": rec.get("score", 0),
                    "degree": st.g.degree(n),
                }
            }
        )
    return {
        "ring_id": ring_id,
        "type": ring["type"],
        "score": ring["score"],
        "window": [ring["start"], ring["end"]],
        "elements": elements,
    }


@app.get("/api/accounts/{account_id}")
def account_detail(account_id: str) -> dict:
    st = _state()
    if account_id not in st.g:
        raise HTTPException(404, f"unknown account '{account_id}'")
    rec = st.accounts.get(account_id, {})
    fp = st.fingerprints.get(account_id, {})
    return {
        "account": account_id,
        "bank": st.g.nodes[account_id].get("bank", "?"),
        "risk_score": rec.get("score", 0),
        "pattern_score": rec.get("pattern_score"),
        "anomaly_score": rec.get("anomaly_score"),
        "reasons": rec.get("reasons", ["no pattern hits; low or no risk"]),
        "velocity": velocity_features(st.g, account_id),
        "fingerprint": fp,
        "benign": account_id in st.benign,
        "filter_reason": st.filter_reasons.get(account_id),
        "burst_timeline": burst_timeline(st.g, account_id, bucket="6h"),
        "in_rings": [r["ring_id"] for r in st.rings if account_id in r["accounts"]],
    }


@app.post("/api/trace")
def trace(req: TraceRequest) -> dict:
    st = _state()
    if not req.txn_id and not req.account:
        raise HTTPException(422, "provide 'txn_id' or 'account' (+'since')")
    try:
        since = datetime.strptime(req.since, "%Y-%m-%d %H:%M:%S") if req.since else None
        res = trace_taint(
            g=st.g,
            txn_id=req.txn_id,
            account=req.account,
            since=since,
            max_depth=req.max_depth,
            min_taint=req.min_taint,
        )
        return res.summary()
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


# -------------------------------------------------------------------- adversary
def _default_route() -> tuple[str, str]:
    """Deterministic demo route: quiet suspect accounts that are NOT part of
    any already-flagged ring, so detection verdicts measure the new scheme."""
    st = _state()
    ring_accs = {a for r in st.rings for a in r["accounts"]}
    src = next(
        (
            a
            for a in sorted(st.suspects)
            if st.g.nodes[a].get("bank") == "BankA"
            and a not in ring_accs
            and st.g.degree(a) <= 3
        ),
        "BankA_0001",
    )
    tgt = next(
        (
            a
            for a in sorted(st.suspects)
            if st.g.nodes[a].get("bank") == "BankC"
            and a not in ring_accs
            and st.g.degree(a) <= 3
        ),
        "BankC_0001",
    )
    return src, tgt


@app.post("/api/adversary/run")
def adversary_run(req: AdversaryRequest) -> dict:
    global ADVERSARY_CACHE
    st = _state()
    src = req.source or _default_route()[0]
    tgt = req.target or _default_route()[1]
    for acc in (src, tgt):
        if acc not in st.g:
            raise HTTPException(404, f"unknown account '{acc}'")
    if any(
        v is not None
        for v in (req.hop_delay_hours, req.n_splits, req.n_decoys, req.n_banks)
    ):
        from engine.adversary import SchemeParams

        delays = sorted({0.0, float(req.hop_delay_hours or 0)})
        splits = sorted({1, int(req.n_splits or 1)})
        decoys = sorted({0, int(req.n_decoys or 0)})
        banks = sorted({1, int(req.n_banks or 1)})
        grid = [
            SchemeParams(
                hop_delay_hours=d,
                n_splits=s,
                jitter=0.1 if s > 1 else 0,
                n_decoys=c,
                n_banks=b,
            )
            for d in delays
            for s in splits
            for c in decoys
            for b in banks
        ]
    else:
        grid = None  # default demo grid
    report = run_adversary(st.g, st.suspects, src, tgt, amount=req.amount, grid=grid)
    ADVERSARY_CACHE = report.summary()
    return ADVERSARY_CACHE


@app.get("/api/adversary/frontier")
def adversary_frontier() -> dict:
    if ADVERSARY_CACHE is None:
        raise HTTPException(404, "no adversary run yet - POST /api/adversary/run first")
    return ADVERSARY_CACHE


# -------------------------------------------------------------------- federation
@app.get("/api/federation/signals")
def federation_signals() -> dict:
    if FED is None:
        raise HTTPException(503, "federation still warming up")
    return {
        "banks": FED.banks,
        "n_signals": len(FED.signals),
        "signals": [
            {
                "bank": s.bank,
                "hashed_id": s.hashed_id,
                "pattern_type": s.pattern_type,
                "direction": s.direction,
                "window": [s.window_start, s.window_end],
                "amount_bucket": s.amount_bucket,
                "pattern_score": s.pattern_score,
            }
            for s in FED.signals
        ],
        "cases": FED.chains,
    }


@app.post("/api/federation/reveal")
def federation_reveal(req: RevealRequest) -> dict:
    if FED is None:
        raise HTTPException(503, "federation still warming up")
    return fed.reveal_account(FED, req.hashed_id, req.authorised_by)


# -------------------------------------------------------------------- dossier
@app.get("/api/rings/{ring_id}/dossier.pdf")
def dossier_pdf(ring_id: str) -> Response:
    st = _state()
    ring = _get_ring(ring_id)
    pdf, chain = export_pdf(ring, st.g, st.accounts, st.fingerprints)
    DOSSIER_CHAINS[ring_id] = chain
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="shadowflow_{ring_id}.pdf"'},
    )


@app.get("/api/verify/{ring_id}")
def verify(ring_id: str) -> dict:
    """Recompute the evidence hash chain from the data and compare with the
    hash that was printed on the exported dossier (if one was exported)."""
    st = _state()
    ring = _get_ring(ring_id)
    from engine.dossier import evidence_records

    recs = evidence_records(ring, st.g)
    chain = build_evidence_chain(recs)
    res = verify_evidence_chain(chain)
    exported = DOSSIER_CHAINS.get(ring_id)
    out = {
        "ring_id": ring_id,
        "chain_valid": res["valid"],
        "n_records": len(chain),
        "current_final_hash": res["final_hash"],
        "dossier_on_file": exported is not None,
    }
    if exported is not None:
        out["exported_final_hash"] = exported[-1]["hash"]
        out["matches_export"] = exported[-1]["hash"] == res["final_hash"]
    return out


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
