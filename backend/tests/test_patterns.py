"""Hand-computed tests for the pattern detectors (cycle, chain, smurfing).

Each test builds a tiny temporal multigraph with known structure and checks
the detector finds exactly the expected hit (or rejects a near-miss).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import networkx as nx
import pytest

from engine import patterns

T0 = datetime(2026, 1, 1, 9, 0)


def _g(edges: list[tuple[str, str, str, float, datetime]]) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    for u, v, k, amt, ts in edges:
        g.add_edge(u, v, key=k, amount=amt, timestamp=ts, channel="wire")
    return g


# ------------------------------------------------------------------- cycles
def test_cycle_detected_within_window():
    # A->B (9:00), B->C (9:10), C->A (9:40): closed loop, retention 0.95
    g = _g(
        [
            ("A", "B", "t1", 1000.0, T0),
            ("B", "C", "t2", 980.0, T0.replace(minute=10)),
            ("C", "A", "t3", 950.0, T0.replace(hour=9, minute=40)),
        ]
    )
    hits = patterns.detect_cycles(g, window_hours=72, min_retention=0.85)
    assert len(hits) == 1
    hit = hits[0]
    assert set(hit["accounts"]) == {"A", "B", "C"}
    assert hit["origin"] == "A"
    assert hit["retention"] == pytest.approx(0.95, rel=1e-6)
    assert hit["length"] == 2  # length counts HOPS: 3 accounts, 2 edges


def test_cycle_too_slow_is_rejected():
    # Same loop but the closing edge lands 80h after the start (> 72h window)
    g = _g(
        [
            ("A", "B", "t1", 1000.0, T0),
            ("B", "C", "t2", 980.0, T0.replace(minute=10)),
            ("C", "A", "t3", 950.0, T0 + timedelta(hours=80)),
        ]
    )
    assert patterns.detect_cycles(g, window_hours=72, min_retention=0.85) == []


def test_cycle_too_much_leakage_is_rejected():
    # 60% retention is below the 85% minimum
    g = _g(
        [
            ("A", "B", "t1", 1000.0, T0),
            ("B", "C", "t2", 980.0, T0.replace(minute=10)),
            ("C", "A", "t3", 600.0, T0.replace(hour=9, minute=40)),
        ]
    )
    assert patterns.detect_cycles(g, window_hours=72, min_retention=0.85) == []


# ------------------------------------------------------------ mule chains
def test_passthrough_chain_detected():
    # A->B->C->D forwarding ~95% within minutes
    g = _g(
        [
            ("A", "B", "t1", 1000.0, T0),
            ("B", "C", "t2", 960.0, T0.replace(minute=12)),
            ("C", "D", "t3", 930.0, T0.replace(minute=31)),
        ]
    )
    hits = patterns.detect_passthrough_chains(g, max_delay_min=120, min_forward=0.85)
    assert len(hits) == 1
    hit = hits[0]
    assert hit["accounts"] == ["A", "B", "C", "D"]
    assert hit["length"] == 3
    assert hit["retention"] == pytest.approx(0.93, rel=1e-6)
    assert hit["total_delay_min"] == pytest.approx(31.0, rel=1e-6)


def test_slow_hop_breaks_chain():
    # B waits 3 hours before forwarding -> exceeds the 120-minute cap
    g = _g(
        [
            ("A", "B", "t1", 1000.0, T0),
            ("B", "C", "t2", 960.0, T0.replace(hour=12)),
            ("C", "D", "t3", 930.0, T0.replace(hour=12, minute=15)),
        ]
    )
    assert (
        patterns.detect_passthrough_chains(g, max_delay_min=120, min_forward=0.85) == []
    )


def test_low_forward_ratio_breaks_chain():
    # B forwards only 50% -> below the 85% requirement
    g = _g(
        [
            ("A", "B", "t1", 1000.0, T0),
            ("B", "C", "t2", 500.0, T0.replace(minute=5)),
            ("C", "D", "t3", 480.0, T0.replace(minute=20)),
        ]
    )
    assert (
        patterns.detect_passthrough_chains(g, max_delay_min=120, min_forward=0.85) == []
    )


# ---------------------------------------------------------------- smurfing
def test_smurfing_detected_with_consolidation():
    # 12 different contributors send 9,500 each (just below 10,000) into
    # COL within 2 days; COL wires the pile out afterwards.
    edges = []
    for i in range(12):
        edges.append((f"P{i}", "COL", f"d{i}", 9500.0, T0 + timedelta(hours=i * 3)))
    edges.append(("COL", "EXIT", "out", 100_000.0, T0 + timedelta(days=3)))
    g = _g(edges)
    hits = patterns.detect_smurfing(g, min_deposits=10, window_days=7)
    assert len(hits) == 1
    hit = hits[0]
    assert hit["collector"] == "COL"
    assert hit["n_contributors"] == 12
    assert hit["n_deposits"] == 12
    assert hit["structuring_score"] == pytest.approx(1.0, rel=1e-6)
    assert hit["total_amount"] == pytest.approx(114_000.0, rel=1e-6)
    assert hit["consolidation_txn"] == "out"


def test_smurfing_rejected_when_deposits_above_threshold():
    # Same shape but every deposit is 12,000 -> not structuring
    edges = []
    for i in range(12):
        edges.append((f"P{i}", "COL", f"d{i}", 12_000.0, T0 + timedelta(hours=i * 3)))
    g = _g(edges)
    assert patterns.detect_smurfing(g, min_deposits=10, window_days=7) == []


def test_smurfing_rejected_when_too_few_contributors():
    # 5 contributors x 9,500 -> below min_deposits=10
    edges = []
    for i in range(5):
        edges.append((f"P{i}", "COL", f"d{i}", 9500.0, T0 + timedelta(hours=i * 3)))
    g = _g(edges)
    assert patterns.detect_smurfing(g, min_deposits=10, window_days=7) == []


# ------------------------------------------------------- real-data smoke
def test_real_data_finds_all_ground_truth_types():
    """Smoke test on the hardened dataset: all three detector families fire.

    The hardened generator (hidden hops, jittered amounts, ring accounts with
    normal lives) keeps recall below 1.0 by design, so we assert the detectors
    still find the majority of the 15 injected rings and every pattern type
    is represented at least once.
    """
    from engine import pipeline

    st = pipeline.run_pipeline()
    types = {r["type"] for r in st.rings}
    assert types == {"cycle", "mule_chain", "smurfing"}
    assert len(st.rings) >= 10  # hardened data: not all 15 are recoverable
