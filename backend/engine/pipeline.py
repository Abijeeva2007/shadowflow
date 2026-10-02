"""Full detection pipeline: load -> graph -> filter -> detect -> score.

`run_pipeline()` executes once and returns a DetectionState that the API,
adversary lab and federation modules all reuse. The heavy work happens here
so the API can serve everything from memory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import networkx as nx
import pandas as pd

from engine import benign_filter, config, evaluate, graph, patterns, scoring


@dataclass
class DetectionState:
    """Everything the dashboard needs, computed once at startup."""

    txns: pd.DataFrame
    g: nx.MultiDiGraph
    fingerprints: dict
    benign: set
    suspects: set
    filter_reasons: dict
    filter_counts: dict
    rings: list[dict]  # scored rings (one per structure)
    accounts: dict  # per-account scores + reasons
    metrics: dict  # precision/recall/F1 vs ground truth
    ground_truth: dict
    by_id: dict = field(default_factory=dict)  # ring_id -> ring record

    def ring(self, ring_id: str) -> dict:
        if ring_id not in self.by_id:
            raise KeyError(f"unknown ring {ring_id}")
        return self.by_id[ring_id]


def run_pipeline() -> DetectionState:
    """Run the complete detection pipeline and cache the results."""
    txns = config.load_transactions()
    g = graph.build_graph(txns)

    filt = benign_filter.run_filter(g)
    suspects = filt["suspects"]

    # detections on the filtered graph (this is what we present)
    cyc = scoring.dedup_hits(patterns.detect_cycles(g, allowed_nodes=suspects))
    chn = scoring.dedup_hits(
        patterns.detect_passthrough_chains(g, allowed_nodes=suspects)
    )
    smf = scoring.dedup_hits(patterns.detect_smurfing(g, allowed_nodes=suspects))

    accounts, rings_scored = scoring.score_accounts(g, cyc, chn, smf, suspects)

    # assemble ring records with stable ids
    rings: list[dict] = []
    by_id: dict[str, dict] = {}
    counters = {"cycle": 0, "mule_chain": 0, "smurfing": 0}
    prefix = {"cycle": "CYCLE", "mule_chain": "CHAIN", "smurfing": "SMURF"}
    for hit_key, rec in rings_scored.items():
        h = rec["hit"]
        counters[h["type"]] += 1
        ring_id = f"{prefix[h['type']]}-{counters[h['type']]:02d}"
        banks = sorted({g.nodes[a].get("bank", "?") for a in h["accounts"]})
        total = (
            h.get("total_amount") or h.get("amount_in") or h.get("amount_start") or 0
        )
        ring = {
            "ring_id": ring_id,
            "type": h["type"],
            "score": rec["score"],
            "accounts": h["accounts"],
            "banks": banks,
            "amount": round(float(total), 2),
            "start": h["start"].strftime("%Y-%m-%d %H:%M:%S"),
            "end": h["end"].strftime("%Y-%m-%d %H:%M:%S"),
            "hit": h,
        }
        rings.append(ring)
        by_id[ring_id] = ring
    rings.sort(key=lambda r: -r["score"])

    # metrics vs ground truth (reuse the evaluate module's matchers)
    gt = config.load_ground_truth()
    metrics = evaluate.evaluate(g, gt, suspects)
    with open(config.DATA_DIR / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)

    return DetectionState(
        txns=txns,
        g=g,
        fingerprints=filt["fingerprints"],
        benign=filt["benign"],
        suspects=suspects,
        filter_reasons=filt["reasons"],
        filter_counts=filt["counts"],
        rings=rings,
        accounts=accounts,
        metrics=metrics,
        ground_truth=gt,
        by_id=by_id,
    )
