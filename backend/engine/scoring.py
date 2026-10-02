"""Risk scoring: combine pattern hits + IsolationForest anomaly scores.

Per-account score  = 0.6 * pattern evidence + 0.4 * velocity anomaly,
both rescaled to 0-100, with human-readable reasons.

Per-ring score = f(best member pattern contribution, mean member anomaly,
type-specific modifiers like structuring score or retention).
"""

from __future__ import annotations

import numpy as np
from sklearn.ensemble import IsolationForest

from engine import velocity as vel


def dedup_hits(hits: list[dict], containment: float = 0.8) -> list[dict]:
    """Collapse nested variants of the same structure (e.g. chain sub-paths).

    Keeps longer / higher-scoring hits; drops any hit whose account set is
    >= containment-contained in an already-kept hit of the same type.
    """
    ordered = sorted(
        hits,
        key=lambda h: -(len(h.get("accounts", [])) * 10 + h.get("n_deposits", 0)),
    )
    kept: list[dict] = []
    kept_sets: list[set[str]] = []
    for h in ordered:
        s = set(h["accounts"])
        contained = any(len(s & k) / max(len(s), 1) >= containment for k in kept_sets)
        if not contained:
            kept.append(h)
            kept_sets.append(s)
    return kept


def _percentile_anomaly_scores(features: np.ndarray, seed: int = 42) -> np.ndarray:
    """IsolationForest anomaly score per row, percentile-ranked to 0-100."""
    if len(features) == 0:
        return np.array([])
    iso = IsolationForest(n_estimators=100, contamination="auto", random_state=seed)
    iso.fit(features)
    raw = -iso.decision_function(features)  # higher = more anomalous
    ranks = raw.argsort().argsort()  # rank 0..n-1
    return 100.0 * ranks / max(len(raw) - 1, 1)


def score_accounts(
    g,
    cycle_hits: list[dict],
    chain_hits: list[dict],
    smurf_hits: list[dict],
    suspect_accounts: set[str],
) -> tuple[dict, dict]:
    """Score every suspect account; returns (accounts, rings) dicts.

    Accounts filtered out as benign are not scored (they were excluded from
    pattern search) - the API layer handles them with fingerprint data.
    """
    accounts: dict[str, dict] = {}
    if not suspect_accounts:
        return accounts, {}

    # ---- pattern evidence per account ---------------------------------
    pattern_score: dict[str, float] = {a: 0.0 for a in suspect_accounts}
    pattern_reasons: dict[str, list[str]] = {a: [] for a in suspect_accounts}

    for h in cycle_hits:
        for a in h["accounts"]:
            if a in pattern_score:
                pattern_score[a] += 40.0
                pattern_reasons[a].append(
                    f"on a {h['length']}-hop money cycle returning "
                    f"{h['retention']:.0%} of funds in {h['window_hours']}h"
                )
    for h in chain_hits:
        for a in h["accounts"][1:-1]:  # middle accounts are the mules
            if a in pattern_score:
                pattern_score[a] += 30.0
                pattern_reasons[a].append(
                    f"forwards funds within {max(h['hop_delays_min']) // max(1, len(h['hop_delays_min'])):.0f}-"
                    f"min hops (chain of {h['length']} accounts, "
                    f"{h['retention']:.0%} retained)"
                )
        for a in (h["accounts"][0], h["accounts"][-1]):
            if a in pattern_score:
                pattern_score[a] += 20.0
                pattern_reasons[a].append(
                    f"endpoint of a {h['length']}-account pass-through chain"
                )
    for h in smurf_hits:
        if h["collector"] in pattern_score:
            pattern_score[h["collector"]] += 55.0
            pattern_reasons[h["collector"]].append(
                f"collected {h['n_deposits']} sub-threshold deposits "
                f"({h['structuring_score']:.0%} just under 10,000) in "
                f"{h['window_days']} days"
            )
        for a in h["depositors"]:
            if a in pattern_score:
                pattern_score[a] += 25.0
                pattern_reasons[a].append(
                    "deposited cash just under the reporting threshold "
                    "into a flagged collector"
                )

    # ---- IsolationForest on velocity features --------------------------
    accs = sorted(suspect_accounts)
    feats = np.array(
        [
            [
                vel.velocity_features(g, a)[k]
                for k in (
                    "txn_count",
                    "txns_per_hour",
                    "peak_burst_rate",
                    "pass_through_ratio",
                    "median_hold_min",
                    "amount_mean",
                    "amount_max",
                )
            ]
            for a in accs
        ]
    )
    anomaly = _percentile_anomaly_scores(feats)

    for a, ano in zip(accs, anomaly):
        v = vel.velocity_features(g, a)
        final = float(min(100.0, 0.6 * min(pattern_score[a], 100.0) + 0.4 * ano))
        reasons = list(pattern_reasons[a])
        if ano >= 90:
            reasons.append(
                f"velocity profile anomalous (isolation-forest {ano:.0f}/100): "
                f"{v['txn_count']:.0f} txns, burst {v['peak_burst_rate']:.0f}/h"
            )
        if v["pass_through_ratio"] > 0.9:
            reasons.append(f"pass-through ratio {v['pass_through_ratio']:.0%}")
        accounts[a] = {
            "score": round(final, 1),
            "pattern_score": round(min(pattern_score[a], 100.0), 1),
            "anomaly_score": round(float(ano), 1),
            "reasons": reasons or ["velocity outlier without a matched pattern"],
            "velocity": v,
        }

    # ---- ring-level scores ---------------------------------------------
    rings: dict[str, dict] = {}
    for i, h in enumerate(cycle_hits + chain_hits + smurf_hits):
        member_scores = [accounts[a]["score"] for a in h["accounts"] if a in accounts]
        member_anom = [
            accounts[a]["anomaly_score"] for a in h["accounts"] if a in accounts
        ]
        bonus = 0.0
        if h["type"] == "smurfing":
            bonus = 10.0 * h["structuring_score"]
        elif h["type"] == "cycle":
            bonus = 10.0 * (1.0 - h["retention"]) * 10  # low retention = fees paid
        elif h["type"] == "mule_chain":
            bonus = 10.0 * min(h["retention"], 1.0)
        score = (
            0.5 * max(member_scores or [0])
            + 0.3 * float(np.mean(member_anom or [0]))
            + 20.0
            + bonus
        )
        rings[f"ring_{h['type']}_{i}"] = {
            "hit": h,
            "score": round(min(score, 100.0), 1),
        }
    return accounts, rings
