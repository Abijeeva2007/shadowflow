"""Business-rhythm fingerprint filter.

For every account we compute a fingerprint:
  - counterparty diversity       (# distinct counterparties)
  - inflow_cv                    (CV of inflow inter-arrival times; reported)
  - daily_volume_cv              (CV of per-day transaction counts; low = steady)
  - periodic_fraction            (share of txns with counterparties seen >=3x,
                                  i.e. recurring relationships like payroll)
  - repeat_counterparty_ratio    (share of txns with counterparties seen >=2x)
  - in_out_ratio / pass_through  (money balance shape)

Accounts with high diversity + steady rhythm + low pass-through are marked
benign and EXCLUDED from pattern search. This is what shrinks the noisy graph.

Honesty notes:
  * The raw inter-arrival CV alone is misleading for businesses that close at
    night (8h gaps every evening inflate it), so the verdict uses daily-volume
    steadiness and relationship recurrence, which are robust to that.
  * This is a heuristic filter, not a guarantee: an adversary who mimics a
    business rhythm gets through (the Adversary Lab demonstrates exactly this).
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

import networkx as nx
import numpy as np

from engine import config
from engine.graph import bank_of


def cv_inter_arrival(times: list[datetime]) -> float:
    """Coefficient of variation of inter-arrival times (higher = irregular)."""
    if len(times) < 3:
        return 1.0
    t = sorted(times)
    gaps = np.array([(t[i + 1] - t[i]).total_seconds() for i in range(len(t) - 1)])
    if gaps.mean() == 0:
        return 1.0
    return float(gaps.std() / gaps.mean())


def daily_volume_cv(times: list[datetime], days: int = 90) -> float:
    """CV of per-day transaction counts (low = steady daily business)."""
    if not times:
        return 1.0
    day_idx = np.array([(t - times[0]).days for t in times])
    counts = np.bincount(day_idx, minlength=days)
    if counts.mean() == 0:
        return 1.0
    return float(counts.std() / counts.mean())


def fingerprint(g: nx.MultiDiGraph, acc: str) -> dict:
    """Compute the business-rhythm fingerprint for one account."""
    ins = sorted(g.in_edges(acc, data=True), key=lambda e: e[2]["timestamp"])
    outs = sorted(g.out_edges(acc, data=True), key=lambda e: e[2]["timestamp"])

    in_times = [d["timestamp"] for _, _, d in ins]
    in_amounts = [d["amount"] for _, _, d in ins]
    out_sum = sum(d["amount"] for _, _, d in outs)
    in_sum = sum(in_amounts)

    all_times = in_times + [d["timestamp"] for _, _, d in outs]
    all_times.sort()
    counterparties: Counter[str] = Counter()
    for u, _, _ in ins:
        counterparties[u] += 1
    for _, v, _ in outs:
        counterparties[v] += 1
    n_txns = len(ins) + len(outs)
    n_txn_list = list(counterparties.values())

    # share of txns whose counterparty appears >= 2x / >= 3x (recurring)
    repeat2 = sum(c for c in n_txn_list if c >= 2)
    repeat3 = sum(c for c in n_txn_list if c >= 3)

    if in_sum > 0:
        ptr = out_sum / in_sum
        io_ratio = in_sum / out_sum if out_sum > 0 else None
    else:
        ptr = None
        io_ratio = None

    return {
        "account": acc,
        "bank": bank_of(g, acc),
        "n_txns": n_txns,
        "counterparty_diversity": len(counterparties),
        "inflow_cv": round(cv_inter_arrival(in_times), 3),
        "daily_volume_cv": round(daily_volume_cv(all_times), 3),
        "periodic_fraction": round(repeat3 / n_txns, 3) if n_txns else 0.0,
        "repeat_counterparty_ratio": round(repeat2 / n_txns, 3) if n_txns else 0.0,
        "in_out_ratio": None if io_ratio is None else round(io_ratio, 3),
        "pass_through_ratio": None if ptr is None else round(ptr, 3),
        "in_sum": round(in_sum, 2),
        "out_sum": round(out_sum, 2),
    }


def is_benign(fp: dict) -> tuple[bool, str]:
    """Decide benign-ness from a fingerprint; returns (verdict, reason).

    Rule: enough history + high counterparty diversity + steady rhythm
    (steady daily volume OR recurring relationships) + low pass-through.
    """
    if fp["n_txns"] < config.BENIGN_MAX_TXN_COUNT:
        return False, f"thin file: only {fp['n_txns']} txns"
    if fp["counterparty_diversity"] < 5:
        return False, f"low counterparty diversity ({fp['counterparty_diversity']})"
    # High pass-through alone is NOT damning: an employer receives revenue and
    # pays salaries with it. What makes a mule is high pass-through on
    # one-shot relationships (nobody ever transacts with them again).
    recurring_business = fp["repeat_counterparty_ratio"] >= 0.8
    if (
        fp["pass_through_ratio"] is not None
        and fp["pass_through_ratio"] > 0.9
        and not recurring_business
    ):
        return (
            False,
            f"pass-through {fp['pass_through_ratio']:.0%} on one-shot links (mule-like)",
        )
    steady = fp["daily_volume_cv"] <= 0.8 or fp["repeat_counterparty_ratio"] >= 0.3
    if not steady:
        return False, (
            f"erratic activity (daily CV {fp['daily_volume_cv']}, "
            f"recurrence {fp['repeat_counterparty_ratio']:.0%})"
        )
    return True, (
        f"steady business rhythm: {fp['counterparty_diversity']} counterparties, "
        f"daily CV {fp['daily_volume_cv']}, "
        f"pass-through {fp['pass_through_ratio'] if fp['pass_through_ratio'] is not None else 0:.0%}"
    )


def run_filter(g: nx.MultiDiGraph) -> dict:
    """Fingerprint every account and split into benign vs suspect sets."""
    fps: dict[str, dict] = {}
    benign: set[str] = set()
    reasons: dict[str, str] = {}
    for acc in g.nodes:
        fp = fingerprint(g, acc)
        ok, why = is_benign(fp)
        fps[acc] = fp
        if ok:
            benign.add(acc)
        reasons[acc] = why
    suspects = set(g.nodes) - benign
    decoys = config.load_ground_truth().get("decoys", [])
    return {
        "fingerprints": fps,
        "benign": benign,
        "suspects": suspects,
        "counts": {
            "accounts_total": g.number_of_nodes(),
            "alerts_before": g.number_of_nodes(),  # every account starts suspect
            "alerts_after": len(suspects),
            "alerts_filtered": len(benign),
        },
        "reasons": reasons,
        "decoy_check": {
            d["account"]: {"label": d["label"], "is_benign": d["account"] in benign}
            for d in decoys
        },
    }
