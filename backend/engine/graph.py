"""Directed temporal transaction multigraph over all banks combined.

The graph is a MultiDiGraph: each transaction is an edge keyed by txn_id with
attributes (amount, timestamp, channel, banks). Parallel edges between the
same pair of accounts are kept, because repeat payments matter for forensics.
"""

from __future__ import annotations

from datetime import datetime

import networkx as nx
import pandas as pd


def build_graph(txns: pd.DataFrame) -> nx.MultiDiGraph:
    """Build a directed multigraph from a transactions dataframe.

    Edge key = txn_id. Edge attrs: amount (float), timestamp (datetime),
    channel (str), bank_src, bank_dst.
    """
    g = nx.MultiDiGraph()
    for row in txns.itertuples(index=False):
        src, dst = row.src_account, row.dst_account
        if src not in g:
            g.add_node(src, bank=row.bank_src)
        if dst not in g:
            g.add_node(dst, bank=row.bank_dst)
        g.add_edge(
            src,
            dst,
            key=row.txn_id,
            amount=float(row.amount),
            timestamp=row.timestamp.to_pydatetime(),
            channel=str(row.channel),
            bank_src=row.bank_src,
            bank_dst=row.bank_dst,
        )
    return g


def bank_of(g: nx.MultiDiGraph, acc: str) -> str:
    return g.nodes[acc].get("bank", "?")


def txn_edge(g: nx.MultiDiGraph, txn_id: str) -> tuple[str, str, dict]:
    """Return (src, dst, attrs) for an edge keyed by txn_id."""
    for u, v, k, d in g.edges(keys=True, data=True):
        if k == txn_id:
            return u, v, d
    raise KeyError(f"txn {txn_id} not found in graph")


def fmt_ts(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d %H:%M:%S")
