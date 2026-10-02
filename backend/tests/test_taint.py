"""Hand-computed taint propagation tests (poison / proportional method)."""

from __future__ import annotations

from datetime import datetime

import networkx as nx
import pytest

from engine.taint import trace_taint


def _g() -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    # simple chain: A -> B -> C, B keeps nothing
    g.add_edge(
        "A",
        "B",
        key="t1",
        amount=1000.0,
        timestamp=datetime(2026, 1, 1, 10, 0),
        channel="w",
    )
    g.add_edge(
        "B",
        "C",
        key="t2",
        amount=950.0,
        timestamp=datetime(2026, 1, 1, 11, 0),
        channel="w",
    )
    return g


def test_chain_full_taint():
    res = trace_taint(g=_g(), txn_id="t1", max_depth=5, min_taint=1.0)
    assert len(res.tree) == 2
    # root hop: A->B carries all 1000 dirty
    n1 = next(n for n in res.tree if n["txn_id"] == "t1")
    assert n1["taint_amount"] == 1000.0
    assert n1["taint_fraction"] == 1.0
    # hop 2: B->C carries 950 dirty (B keeps 50 dirty)
    n2 = next(n for n in res.tree if n["txn_id"] == "t2")
    assert n2["taint_amount"] == 950.0
    assert n2["taint_fraction"] == 1.0
    assert res.terminals == {"B": pytest.approx(50.0), "C": pytest.approx(950.0)}
    assert res.total_dirty_out == 1950.0


def test_mixed_funds_poison_fraction():
    """Dirty 1000 lands at A which already holds clean 3000; A sends 2000.

    Poison rule: outgoing fraction = dirty/(dirty+clean) = 1000/4000 = 0.25
    => the 2000 payment carries 500 dirty; 500 dirty stays with A.
    """
    g = nx.MultiDiGraph()
    # dirty seed: S deposits 1000 into A at 10:00
    g.add_edge(
        "S",
        "A",
        key="seed",
        amount=1000.0,
        timestamp=datetime(2026, 1, 1, 10, 0),
        channel="w",
    )
    # clean inflow of 3000 BEFORE the dirty money arrives
    g.add_edge(
        "Z",
        "A",
        key="clean1",
        amount=3000.0,
        timestamp=datetime(2026, 1, 1, 9, 0),
        channel="w",
    )
    g.add_edge(
        "A",
        "C",
        key="t2",
        amount=2000.0,
        timestamp=datetime(2026, 1, 1, 12, 0),
        channel="w",
    )
    res = trace_taint(g=g, txn_id="seed", max_depth=5, min_taint=1.0)
    n2 = next(n for n in res.tree if n["txn_id"] == "t2")
    # clean pool at A before 10:00 = 3000 (clean1); dirty pool = 1000
    # frac_out = 1000 / 4000 = 0.25 -> dirty portion = 2000 * 0.25 = 500
    assert n2["taint_amount"] == pytest.approx(500.0, rel=1e-6)
    assert n2["taint_fraction"] == pytest.approx(0.25, rel=1e-6)
    # A keeps 500 dirty; C rests with the 500 that left (no out-edges)
    assert res.terminals["A"] == pytest.approx(500.0, rel=1e-6)
    assert res.terminals["C"] == pytest.approx(500.0, rel=1e-6)


def test_min_taint_and_depth_caps():
    g = _g()
    # max_depth=1: the seed hop plus exactly one further hop
    res = trace_taint(g=g, txn_id="t1", max_depth=1, min_taint=1.0)
    assert len(res.tree) == 2
    # min_taint above the seed: only the root hop is reported, nothing spreads
    res2 = trace_taint(g=g, txn_id="t1", max_depth=5, min_taint=10_000.0)
    assert len(res2.tree) == 1
    assert res2.tree[0]["taint_amount"] == 1000.0
    assert res2.total_dirty_out == 1000.0


def test_account_mode_starts_from_inflow():
    res = trace_taint(
        g=_g(),
        account="B",
        since=datetime(2026, 1, 1, 9, 0),
        max_depth=5,
        min_taint=1.0,
    )
    assert res.root_account == "B"
    assert res.root_amount == 1000.0
    assert res.tree[0]["txn_id"] == "t1"
    assert any(n["txn_id"] == "t2" for n in res.tree)


def test_real_data_trace():
    """Smoke test on real generated data: trace a mule chain hop."""
    from engine import pipeline

    st = pipeline.run_pipeline()
    ring = next(r for r in st.rings if r["type"] == "mule_chain")
    root_txn = ring["hit"]["txn_ids"][0]
    res = trace_taint(g=st.g, txn_id=root_txn, max_depth=6, min_taint=1.0)
    assert res.tree, "expected the trace to spread through the chain"
    assert res.total_dirty_out > 0
