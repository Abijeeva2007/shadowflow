"""API tests for the adversary endpoints on the free-tier-safe code path.

The precomputed default must be served WITHOUT running a search, a second
run while one is in flight must be rejected (409 busy), and a slow search
must time out (504) instead of blocking the API.
"""

from __future__ import annotations

import time
import types

import networkx as nx
import pytest
from fastapi.testclient import TestClient

import main
from engine.adversary import AdversaryReport, cap_grid, default_grid

CACHED = {
    "baseline_detected": True,
    "n_schemes_tested": 33,
    "friction_before": 2.98,
    "friction_after": 8.93,
    "hardened_thresholds": {"chain_max_delay_min": 180},
    "frontier": [],
}


@pytest.fixture
def client(monkeypatch):
    """A tiny fake engine state so no 70k-row pipeline is needed."""
    g = nx.MultiDiGraph()
    g.add_node("A_src", bank="BankA")
    g.add_node("B_dst", bank="BankC")
    monkeypatch.setattr(
        main,
        "STATE",
        types.SimpleNamespace(g=g, suspects={"A_src", "B_dst"}, rings=[]),
    )
    monkeypatch.setattr(main, "ADVERSARY_CACHE", dict(CACHED))
    monkeypatch.setattr(main, "_ADV_BUSY", False)
    # never let a test call the real search
    monkeypatch.setattr(main, "run_adversary", _boom("run_adversary must not run"))
    return TestClient(main.app)


def _boom(msg: str):
    def _f(*_a, **_k):
        raise AssertionError(msg)

    return _f


def test_frontier_serves_precomputed(client):
    res = client.get("/api/adversary/frontier")
    assert res.status_code == 200
    assert res.json()["friction_before"] == 2.98


def test_frontier_503_while_computing(client, monkeypatch):
    monkeypatch.setattr(main, "ADVERSARY_CACHE", None)
    res = client.get("/api/adversary/frontier")
    assert res.status_code == 503
    assert "computing" in res.json()["detail"]


def test_default_run_serves_cache_without_searching(client):
    """Opening the page must not trigger a 32-scheme search."""
    res = client.post("/api/adversary/run", json={})
    assert res.status_code == 200
    assert res.json()["friction_after"] == 8.93


def test_busy_run_returns_409(client, monkeypatch):
    monkeypatch.setattr(main, "_ADV_BUSY", True)
    res = client.post(
        "/api/adversary/run",
        json={"hop_delay_hours": 24, "n_splits": 2, "n_decoys": 5, "n_banks": 2},
    )
    assert res.status_code == 409
    assert "already in progress" in res.json()["detail"]


def test_slow_run_times_out_with_504(client, monkeypatch):
    monkeypatch.setattr(main, "ADV_RUN_TIMEOUT_S", 0.3)
    monkeypatch.setattr(main, "run_adversary", _slow_report(2.0))
    res = client.post(
        "/api/adversary/run",
        json={"hop_delay_hours": 24, "n_splits": 2, "n_decoys": 5, "n_banks": 2},
    )
    assert res.status_code == 504
    assert "exceeded" in res.json()["detail"]
    # the abandoned worker finishes on its own and releases the busy flag
    for _ in range(50):
        if not main._ADV_BUSY:
            break
        time.sleep(0.1)
    assert main._ADV_BUSY is False


def _slow_report(seconds: float):
    def _f(*_a, **_k):
        time.sleep(seconds)
        return AdversaryReport(friction_before=3.0, friction_after=9.0)

    return _f


def test_run_is_capped_and_clears_busy(client, monkeypatch):
    seen: dict = {}

    def _fake(*_a, **k):
        seen.update(k)
        return AdversaryReport(friction_before=3.0, friction_after=9.0)

    monkeypatch.setattr(main, "run_adversary", _fake)
    res = client.post(
        "/api/adversary/run",
        json={"hop_delay_hours": 24, "n_splits": 2, "n_decoys": 5, "n_banks": 2},
    )
    assert res.status_code == 200
    assert seen["max_schemes"] == main.ADV_RUN_MAX_SCHEMES
    assert main._ADV_BUSY is False  # lock released after the run


def test_cap_grid_thins_deterministically():
    grid = default_grid()
    assert len(grid) == 32
    first = cap_grid(grid, 8)
    assert len(first) == 8
    assert first == cap_grid(grid, 8)  # deterministic
    assert all(p in grid for p in first)
    assert cap_grid(grid, None) == grid
    assert cap_grid([grid[0]], 8) == [grid[0]]


def test_health_is_lock_free_and_immediate(client, monkeypatch):
    """The readiness probe must not touch the adversary lock or any helper."""
    monkeypatch.setattr(
        main, "peak_rss_mb", _boom("health must not touch the memory helper")
    )
    t0 = time.perf_counter()
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "ready": True}  # faked STATE, no pipeline
    assert time.perf_counter() - t0 < 0.5
