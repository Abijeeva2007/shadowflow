"""Pattern detectors: temporal cycles, pass-through mule chains, smurfing.

All detectors run on the directed temporal multigraph and can be restricted to
a set of "suspect" accounts (survivors of the benign filter). When
allowed_nodes is None they run over every account - that is how we compute
false-alarm counts before vs. after the benign filter.

Note on MultiDiGraph edge tuples: with keys=True, data=True, edges come back
as (u, v, key, attrdict) where key is the txn_id.
"""

from __future__ import annotations

from datetime import timedelta

import networkx as nx

from engine import config


# --------------------------------------------------------------- cycles
def detect_cycles(
    g: nx.MultiDiGraph,
    allowed_nodes: set[str] | None = None,
    window_hours: float = config.CYCLE_WINDOW_HOURS,
    max_len: int = config.CYCLE_MAX_LEN,
    min_retention: float = config.CYCLE_MIN_RETENTION,
) -> list[dict]:
    """Temporal cycles: money returns to its origin within `window_hours`.

    Bounded DFS with time and amount pruning:
      - timestamps must strictly increase along the path,
      - total elapsed time <= window_hours,
      - at most max_len hops (default 6),
      - each hop may not grow the money by more than a 2% tolerance,
      - the loop's end/start amount ratio must be >= min_retention.

    Each distinct member-set is reported once (the best retention seen).

    Hit fields: `length` is the number of HOPS (edges) around the loop - a
    3-account loop has length 2. `retention` is end/start amount ratio.
    """
    window = timedelta(hours=window_hours)
    growth_tolerance = 1.02
    hits: dict[frozenset, dict] = {}
    origins = sorted(allowed_nodes) if allowed_nodes is not None else sorted(g.nodes)

    for origin in origins:
        # stack frames: (node, path, eids, times, amounts)
        stack: list[tuple] = []
        for _, v, k, d in g.out_edges(origin, keys=True, data=True):
            if v == origin or (allowed_nodes is not None and v not in allowed_nodes):
                continue
            stack.append((v, [origin, v], [k], [d["timestamp"]], [d["amount"]]))

        while stack:
            node, path, eids, times, amounts = stack.pop()
            if len(path) - 1 >= max_len:
                continue  # cannot close within max_len any more
            # try to close the loop back to origin
            for _, v, k, d in g.out_edges(node, keys=True, data=True):
                if v != origin:
                    continue
                dt = (d["timestamp"] - times[0]).total_seconds()
                if dt < 0 or dt > window.total_seconds():
                    continue
                if d["amount"] > amounts[-1] * growth_tolerance:
                    continue
                retention = d["amount"] / amounts[0]
                if retention < min_retention:
                    continue
                key = frozenset(path)
                hit = {
                    "type": "cycle",
                    "accounts": list(dict.fromkeys(path)),
                    "origin": origin,
                    "txn_ids": eids + [k],
                    "start": times[0],
                    "end": d["timestamp"],
                    "retention": round(retention, 4),
                    "window_hours": round(dt / 3600, 2),
                    "length": len(path) - 1,
                    "amount_start": round(amounts[0], 2),
                    "amount_end": round(d["amount"], 2),
                }
                if key not in hits or hits[key]["retention"] < retention:
                    hits[key] = hit
            # extend the path (only if still under max_len)
            if len(path) - 1 < max_len - 1:
                for _, v, k, d in g.out_edges(node, keys=True, data=True):
                    if v == origin or v in path:
                        continue
                    if allowed_nodes is not None and v not in allowed_nodes:
                        continue
                    dt = (d["timestamp"] - times[-1]).total_seconds()
                    if dt < 0:
                        continue  # never go backwards in time; equal is allowed
                    if (d["timestamp"] - times[0]) > window:
                        continue  # time pruning
                    if d["amount"] > amounts[-1] * growth_tolerance:
                        continue  # money must not grow around the loop
                    stack.append(
                        (
                            v,
                            path + [v],
                            eids + [k],
                            times + [d["timestamp"]],
                            amounts + [d["amount"]],
                        )
                    )
    return list(hits.values())


# ------------------------------------------------------- pass-through chains
def detect_passthrough_chains(
    g: nx.MultiDiGraph,
    allowed_nodes: set[str] | None = None,
    max_delay_min: float = config.CHAIN_MAX_DELAY_MIN,
    min_forward: float = config.CHAIN_MIN_FORWARD,
    min_length: int = 3,
) -> list[dict]:
    """Pass-through mule chains.

    An edge u->v extends a chain ending at u when:
      - v is not already in the chain,
      - v forwards >= min_forward of the amount it received on that edge,
      - v's forwarding edge leaves within max_delay minutes of the receipt,
      - timestamps strictly increase.

    A chain is reported when it has >= min_length hops. Each distinct
    account-set is reported once (the longest variant seen).
    """
    results: dict[frozenset, dict] = {}
    # seed: every edge that its receiver quickly forwards
    active: list[tuple] = []
    for u, v, k, d in g.edges(keys=True, data=True):
        if allowed_nodes is not None and (
            u not in allowed_nodes or v not in allowed_nodes
        ):
            continue
        active.append(([u, v], [k], [d["timestamp"]], [d["amount"]]))

    while active:
        nxt: list[tuple] = []
        for accounts, eids, times, amounts in active:
            tail = accounts[-1]
            t_last, amt_last = times[-1], amounts[-1]
            for _, w, k2, d2 in g.out_edges(tail, keys=True, data=True):
                if w in accounts:
                    continue
                if allowed_nodes is not None and w not in allowed_nodes:
                    continue
                delay = (d2["timestamp"] - t_last).total_seconds() / 60.0
                if delay < 0 or delay > max_delay_min:
                    continue
                if d2["amount"] < amt_last * min_forward:
                    continue
                nxt.append(
                    (
                        accounts + [w],
                        eids + [k2],
                        times + [d2["timestamp"]],
                        amounts + [d2["amount"]],
                    )
                )
            hops = len(accounts) - 1
            if hops >= min_length:
                key = frozenset(accounts)
                hit = {
                    "type": "mule_chain",
                    "accounts": accounts,
                    "origin": accounts[0],
                    "terminal": accounts[-1],
                    "txn_ids": list(eids),
                    "start": times[0],
                    "end": times[-1],
                    "length": hops,
                    "total_delay_min": round(
                        (times[-1] - times[0]).total_seconds() / 60.0, 1
                    ),
                    "amount_in": round(amounts[0], 2),
                    "amount_out": round(amounts[-1], 2),
                    "retention": (
                        round(amounts[-1] / amounts[0], 4) if amounts[0] else 0.0
                    ),
                    "hop_delays_min": [
                        round((times[i + 1] - times[i]).total_seconds() / 60.0, 1)
                        for i in range(len(times) - 1)
                    ],
                }
                # keep the longest variant per account-set
                if key not in results or results[key]["length"] < hops:
                    results[key] = hit
                # chains can keep growing, so also keep them in `nxt` via extension
        active = nxt
        if len(active) > 200_000:
            break  # safety valve for pathological graphs
    return list(results.values())


# ----------------------------------------------------------------- smurfing
def detect_smurfing(
    g: nx.MultiDiGraph,
    allowed_nodes: set[str] | None = None,
    window_days: float = config.SMURF_WINDOW_DAYS,
    min_deposits: int = config.SMURF_MIN_DEPOSITS,
    threshold: float = config.THRESHOLD,
) -> list[dict]:
    """Smurfing: many sub-threshold deposits into one collector within a
    window from many distinct contributors, followed by consolidation.

    Structuring score = fraction of deposits sitting just below the threshold
    (between SMURF_JUST_BELOW_MIN x threshold and SMURF_JUST_BELOW x threshold).
    """
    window = timedelta(days=window_days)
    hits: list[dict] = []
    candidates = sorted(allowed_nodes) if allowed_nodes is not None else sorted(g.nodes)

    for collector in candidates:
        ins = sorted(
            ((u, k, d) for u, _, k, d in g.in_edges(collector, keys=True, data=True)),
            key=lambda e: e[2]["timestamp"],
        )
        # candidate deposits: sub-threshold, at least half the threshold
        deps = [
            (u, k, d) for u, k, d in ins if threshold * 0.5 <= d["amount"] < threshold
        ]
        if len(deps) < min_deposits:
            continue

        best: dict | None = None
        best_key: tuple = ()
        lo = 0
        for hi in range(len(deps)):
            while deps[hi][2]["timestamp"] - deps[lo][2]["timestamp"] > window:
                lo += 1
            n = hi - lo + 1
            if n < min_deposits:
                continue
            group = deps[lo : hi + 1]
            contributors = {u for u, _, _ in group}
            if len(contributors) < min_deposits:
                continue
            amounts = [d["amount"] for _, _, d in group]
            just_below = sum(
                1
                for a in amounts
                if threshold * config.SMURF_JUST_BELOW_MIN
                <= a
                <= threshold * config.SMURF_JUST_BELOW
            )
            struct_score = just_below / len(amounts)
            span_days = (
                group[-1][2]["timestamp"] - group[0][2]["timestamp"]
            ).total_seconds() / 86400
            # rank windows by deposit count, then structuring score
            score_key = (n, struct_score)
            if best is None or score_key > best_key:
                best_key = score_key
                best = {
                    "type": "smurfing",
                    "collector": collector,
                    "accounts": sorted(contributors | {collector}),
                    "depositors": sorted(contributors),
                    "txn_ids": [k for _, k, _ in group],
                    "start": group[0][2]["timestamp"],
                    "end": group[-1][2]["timestamp"],
                    "n_deposits": n,
                    "n_contributors": len(contributors),
                    "structuring_score": round(struct_score, 3),
                    "total_amount": round(sum(amounts), 2),
                    "window_days": round(span_days, 2),
                }
        if best is None:
            continue

        # consolidation: large outgoing txn after the deposit window
        for _, v, k, d in g.out_edges(collector, keys=True, data=True):
            if (
                d["timestamp"] >= best["start"]
                and d["amount"] >= best["total_amount"] * 0.3
            ):
                best["consolidation_txn"] = k
                best["consolidation_to"] = v
                best["consolidation_amount"] = round(d["amount"], 2)
                best["consolidation_time"] = d["timestamp"]
                best["accounts"] = sorted(set(best["accounts"]) | {v})
                break
        hits.append(best)
    return hits
