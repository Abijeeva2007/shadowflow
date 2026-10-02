"""Evaluation: compare detections with the injected ground truth.

Matching rule: a detected ring matches a ground-truth ring when their account
sets have Jaccard overlap >= 0.5 (greedy 1:1 matching, highest overlap first).
For mule chains we also accept a hit contained in a ground-truth chain (the
chain detector may legitimately find a sub-path of a longer ring).

Outputs metrics.json with per-pattern precision/recall/F1 and decoy
false-alarm counts before vs. after the benign filter.
"""

from __future__ import annotations

import json

import networkx as nx

from engine import benign_filter, config, graph, patterns
from engine.scoring import dedup_hits


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def truth_accounts(record: dict) -> set:
    """Normalize a ground-truth record to its account set."""
    if "accounts" in record:
        return set(record["accounts"])
    # smurfing records: collector + depositors + exits
    s = set(record.get("depositors", []))
    if "collector" in record:
        s.add(record["collector"])
    s.update(record.get("exits", []))
    return s


def match_rings(
    detected: list[dict], truth: list[dict], min_jaccard: float = 0.5
) -> tuple[set[int], set[int]]:
    """Greedy 1:1 matching; returns (matched_truth_idx, matched_det_idx)."""
    pairs: list[tuple[float, int, int]] = []
    for i, t in enumerate(truth):
        ts = truth_accounts(t)
        for j, d in enumerate(detected):
            ds = set(d["accounts"])
            jw = jaccard(ts, ds)
            contained = ds.issubset(ts) and len(ds) >= 2
            if jw >= min_jaccard or contained:
                pairs.append((max(jw, 0.5 if contained else 0.0), i, j))
    pairs.sort(reverse=True)
    mt: set[int] = set()
    md: set[int] = set()
    for _, i, j in pairs:
        if i in mt or j in md:
            continue
        mt.add(i)
        md.add(j)
    return mt, md


def evaluate(
    g: nx.MultiDiGraph,
    ground_truth: dict,
    benign_set: set[str],
    thresholds: dict | None = None,
) -> dict:
    """Run all detectors twice (no filter vs. benign filter) and score them.

    `thresholds` may override detector sensitivity (used by the adversary
    lab's harden step): keys cycle_window_hours, cycle_min_retention,
    chain_max_delay_min, chain_min_forward, smurf_min_deposits.
    """
    th = thresholds or {}

    def run(allowed: set[str] | None) -> dict:
        cyc = dedup_hits(
            patterns.detect_cycles(
                g,
                allowed_nodes=allowed,
                window_hours=th.get("cycle_window_hours", config.CYCLE_WINDOW_HOURS),
                min_retention=th.get("cycle_min_retention", config.CYCLE_MIN_RETENTION),
            )
        )
        chn = dedup_hits(
            patterns.detect_passthrough_chains(
                g,
                allowed_nodes=allowed,
                max_delay_min=th.get("chain_max_delay_min", config.CHAIN_MAX_DELAY_MIN),
                min_forward=th.get("chain_min_forward", config.CHAIN_MIN_FORWARD),
            )
        )
        smf = dedup_hits(
            patterns.detect_smurfing(
                g,
                allowed_nodes=allowed,
                min_deposits=th.get("smurf_min_deposits", config.SMURF_MIN_DEPOSITS),
            )
        )
        return {"cycle": cyc, "mule_chain": chn, "smurfing": smf}

    before = run(None)
    after = run(benign_set)

    metrics: dict = {"per_pattern": {}, "decoys": {}}
    type_to_truth = {
        "cycle": ground_truth.get("cycles", []),
        "mule_chain": ground_truth.get("mule_chains", []),
        "smurfing": ground_truth.get("smurfing", []),
    }

    for ptype, truth in type_to_truth.items():
        mt_before, md_before = match_rings(before[ptype], truth)
        mt_after, md_after = match_rings(after[ptype], truth)

        def prf(n_detected: int, matched: set[int]) -> dict:
            tp = len(matched)
            fp = n_detected - tp
            fn = len(truth) - tp
            p = tp / (tp + fp) if tp + fp else 0.0
            r = tp / (tp + fn) if tp + fn else 0.0
            f1 = 2 * p * r / (p + r) if p + r else 0.0
            return {
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "precision": round(p, 3),
                "recall": round(r, 3),
                "f1": round(f1, 3),
            }

        metrics["per_pattern"][ptype] = {
            "before_filter": prf(len(before[ptype]), mt_before),
            "after_filter": prf(len(after[ptype]), mt_after),
        }

    # decoys: how many detectors fire on them (false alarms)?
    decoy_accs = [d["account"] for d in ground_truth.get("decoys", [])]
    for phase, res in (("before_filter", before), ("after_filter", after)):
        fa = {d["account"]: 0 for d in ground_truth.get("decoys", [])}
        for hits in res.values():
            for h in hits:
                for dacc in decoy_accs:
                    if dacc in h.get("accounts", []):
                        fa[dacc] += 1
        metrics["decoys"][phase] = {
            d["account"]: {
                "label": d["label"],
                "flagged": fa[d["account"]] > 0,
                "n_pattern_hits": fa[d["account"]],
            }
            for d in ground_truth.get("decoys", [])
        }
        metrics["decoys"][phase]["total_flagged"] = sum(
            1 for d in decoy_accs if fa[d] > 0
        )

    metrics["summary"] = {
        "rings_detected_before": sum(len(v) for v in before.values()),
        "rings_detected_after": sum(len(v) for v in after.values()),
        "rings_in_ground_truth": sum(len(v) for v in type_to_truth.values()),
    }
    return metrics


def main() -> dict:
    """Standalone entry point: python -m engine.evaluate"""
    txns = config.load_transactions()
    g = graph.build_graph(txns)
    gt = config.load_ground_truth()
    filt = benign_filter.run_filter(g)
    metrics = evaluate(g, gt, filt["suspects"])
    with open(config.DATA_DIR / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print(json.dumps(metrics, indent=2, default=str))
    return metrics


if __name__ == "__main__":
    main()
