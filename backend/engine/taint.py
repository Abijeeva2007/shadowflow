"""Proportional taint propagation (poison method).

Given a starting transaction (or an account + time), follow the dirty money
FORWARD in time. When funds mix in an account, outgoing transactions carry a
dirty share proportional to:

    dirty fraction = dirty balance / total balance at that moment

Implementation model: every account has a dirty pool and a clean pool.
Incoming dirty money adds `taint * amount` to the dirty pool and the rest to
the clean pool. Outgoing payments spend proportionally from both pools.

Honest scope notes (see also README):
  * This is a "proportional pooling" model, the standard first-order
    approximation. It ignores per-lot / FIFO accounting.
  * The edge that DELIVERED the dirty money into an account is excluded from
    that account's clean pool (otherwise the dirty money would dilute
    itself).
  * The trace is a tree: each outgoing payment is a child of the money that
    funded it, with its taint amount and fraction. Depth and minimum-taint
    caps keep the output readable and guarantee termination.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import networkx as nx


@dataclass
class TaintResult:
    root_txn: str | None
    root_account: str
    root_time: datetime
    root_amount: float
    total_dirty_out: float = 0.0
    tree: list[dict] = field(default_factory=list)
    terminals: dict[str, float] = field(default_factory=dict)
    events: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "root_txn": self.root_txn,
            "root_account": self.root_account,
            "root_time": self.root_time.strftime("%Y-%m-%d %H:%M:%S"),
            "root_amount": round(self.root_amount, 2),
            "total_traced": round(self.total_dirty_out, 2),
            "n_hops": len(self.tree),
            "terminals": {
                a: round(v, 2)
                for a, v in sorted(self.terminals.items(), key=lambda kv: -kv[1])
            },
            "tree": self.tree,
            "events": self.events,
        }


def trace_taint(
    g: nx.MultiDiGraph,
    txn_id: str | None = None,
    account: str | None = None,
    since: datetime | None = None,
    max_depth: int = 6,
    min_taint: float = 1.0,
) -> TaintResult:
    """Trace dirty money forward from a starting txn (preferred) or account.

    - txn_id: the whole amount of that transaction is treated as the dirty
      seed. It lands at its DESTINATION (like a deposit landing at a
      collector) and is then spent/mixed by the receiver's later payments.
      The seed txn itself appears in the tree as the root hop (taint 1.0).
    - account + since: the first inflow into `account` at/after `since` seeds
      the trace.
    - max_depth caps hops (seed = depth 0); min_taint stops dusty branches.
    """
    if txn_id is None and account is None:
        raise ValueError("provide txn_id or account")

    res = TaintResult(
        root_txn=txn_id,
        root_account="",
        root_time=since or datetime(2026, 1, 1),
        root_amount=0.0,
    )

    if txn_id is not None:
        edge = _find_edge(g, txn_id)
        if edge is None:
            raise KeyError(f"txn {txn_id} not found")
        u, v, k, d = edge
        res.root_account = v
        res.root_time = d["timestamp"]
        res.root_amount = d["amount"]
        root_node = {
            "parent": None,
            "txn_id": k,
            "src": u,
            "dst": v,
            "time": d["timestamp"].strftime("%Y-%m-%d %H:%M:%S"),
            "amount": round(d["amount"], 2),
            "taint_amount": round(d["amount"], 2),
            "taint_fraction": 1.0,
            "depth": 0,
        }
        res.tree.append(root_node)
        res.events.append(
            f"Root: {k} deposits {d['amount']:.2f} into {v} "
            f"at {d['timestamp']:%m-%d %H:%M} - all of it dirty"
        )
        _walk(
            g,
            v,
            d["timestamp"],
            d["amount"],
            0,
            max_depth,
            min_taint,
            res,
            parent=root_node,
            deliver_key=k,
        )
    else:
        assert account is not None and since is not None
        res.root_account = account
        res.root_time = since
        ins = sorted(
            g.in_edges(account, keys=True, data=True), key=lambda e: e[3]["timestamp"]
        )
        seeds = [e for e in ins if e[3]["timestamp"] >= since]
        if not seeds:
            res.events.append(f"No inflows to {account} at/after {since}")
            return res
        u, _, k, d = seeds[0]
        res.root_amount = d["amount"]
        root_node = {
            "parent": None,
            "txn_id": k,
            "src": u,
            "dst": account,
            "time": d["timestamp"].strftime("%Y-%m-%d %H:%M:%S"),
            "amount": round(d["amount"], 2),
            "taint_amount": round(d["amount"], 2),
            "taint_fraction": 1.0,
            "depth": 0,
        }
        res.tree.append(root_node)
        res.events.append(
            f"Root: inflow {k} of {d['amount']:.2f} into {account} "
            f"at {d['timestamp']:%m-%d %H:%M} - all of it dirty"
        )
        _walk(
            g,
            account,
            d["timestamp"],
            d["amount"],
            0,
            max_depth,
            min_taint,
            res,
            parent=root_node,
            deliver_key=k,
        )

    res.tree.sort(key=lambda n: (n["depth"], n["time"]))
    res.total_dirty_out = round(sum(n["taint_amount"] for n in res.tree), 2)
    return res


def _walk(
    g: nx.MultiDiGraph,
    holder: str,
    t_dirty: datetime,
    taint_amt: float,
    depth: int,
    max_depth: int,
    min_taint: float,
    res: TaintResult,
    parent: dict | None,
    deliver_key: str | None,
) -> None:
    """Move a taint bundle of `taint_amt` sitting at `holder` since `t_dirty`
    forward through holder's outgoing transactions."""
    if depth >= max_depth:
        res.terminals[holder] = res.terminals.get(holder, 0.0) + taint_amt
        res.events.append(f"{'  ' * depth}{holder} keeps {taint_amt:.2f} (depth cap)")
        return
    if taint_amt < min_taint:
        res.events.append(
            f"{'  ' * depth}taint {taint_amt:.2f} below " f"{min_taint} - not followed"
        )
        return

    # outgoing txns at/after the dirty money's arrival (batch semantics)
    outs = [
        e
        for e in g.out_edges(holder, keys=True, data=True)
        if e[3]["timestamp"] >= t_dirty
    ]
    outs.sort(key=lambda e: e[3]["timestamp"])

    clean = _clean_pool(g, holder, t_dirty, exclude_key=deliver_key)
    dirty_pool = taint_amt
    total_pool = clean + dirty_pool

    spent = 0.0
    for u, v, k, d in outs:
        if spent >= dirty_pool:
            break
        amt = d["amount"]
        # poison rule: this payment carries the proportional dirty share
        frac_out = (dirty_pool / total_pool) if total_pool > 0 else 1.0
        dirty_portion = min(amt * frac_out, dirty_pool - spent)
        if dirty_portion <= 0:
            break
        spent += dirty_portion
        node = {
            "parent": parent["txn_id"] if parent else None,
            "txn_id": k,
            "src": u,
            "dst": v,
            "time": d["timestamp"].strftime("%Y-%m-%d %H:%M:%S"),
            "amount": round(amt, 2),
            "taint_amount": round(dirty_portion, 2),
            "taint_fraction": round(dirty_portion / amt, 3) if amt else 0.0,
            "depth": depth + 1,
        }
        res.tree.append(node)
        res.events.append(
            f"{'  ' * (depth + 1)}{k}: {u} -> {v} {amt:.2f} "
            f"(dirty {dirty_portion:.2f}, {dirty_portion / max(amt, 1e-9):.0%})"
        )
        _walk(
            g,
            v,
            d["timestamp"],
            dirty_portion,
            depth + 1,
            max_depth,
            min_taint,
            res,
            parent=node,
            deliver_key=k,
        )

    if spent < dirty_pool:
        rest = dirty_pool - spent
        res.terminals[holder] = res.terminals.get(holder, 0.0) + rest
        res.events.append(f"{'  ' * (depth + 1)}{holder} keeps {rest:.2f} dirty")


def _clean_pool(
    g: nx.MultiDiGraph, acc: str, before: datetime, exclude_key: str | None
) -> float:
    """Clean money available at `acc` at time `before`.

    Approximation: inflows before `before` (minus the dirty delivering edge)
    minus outflows already made. Good enough for the demo's proportional
    story; exact double-entry accounting is out of scope.
    """
    clean = 0.0
    for _, _, k, d in g.in_edges(acc, keys=True, data=True):
        if d["timestamp"] <= before and k != exclude_key:
            clean += d["amount"]
    for _, _, k, d in g.out_edges(acc, keys=True, data=True):
        if d["timestamp"] < before:
            clean -= d["amount"]
    return max(clean, 0.0)


def _find_edge(g: nx.MultiDiGraph, txn_id: str):
    for u, v, k, d in g.edges(keys=True, data=True):
        if k == txn_id:
            return (u, v, k, d)
    return None
