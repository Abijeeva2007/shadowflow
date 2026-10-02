"""Per-account velocity metrics: how fast money moves through an account."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd


def txn_count(g, acc: str) -> int:
    return g.in_degree(acc) + g.out_degree(acc)


def txns_per_hour(g, acc: str) -> float:
    """Average transactions per hour over the account's active span."""
    ts = _all_timestamps(g, acc)
    if len(ts) < 2:
        return float(len(ts))
    span_h = max((ts[-1] - ts[0]).total_seconds() / 3600.0, 1.0)
    return (len(ts) - 1) / span_h


def peak_burst_rate(g, acc: str, window_min: int = 60) -> float:
    """Max number of transactions in any sliding `window_min` window."""
    ts = _all_timestamps(g, acc)
    if not ts:
        return 0.0
    window = timedelta(minutes=window_min)
    best, lo = 0, 0
    for hi in range(len(ts)):
        while ts[hi] - ts[lo] > window:
            lo += 1
        best = max(best, hi - lo + 1)
    return float(best)


def median_hold_time(g, acc: str) -> float | None:
    """Median minutes between receiving money and sending it on.

    Approximation: pair each incoming amount with the next outgoing amount
    of similar size (within 25%); report the median delay of matched pairs.
    Returns None if the account has no matched in/out pairs.
    """
    ins = [(d["timestamp"], d["amount"]) for _, _, d in g.in_edges(acc, data=True)]
    outs = [(d["timestamp"], d["amount"]) for _, _, d in g.out_edges(acc, data=True)]
    ins.sort()
    outs.sort()
    if not ins or not outs:
        return None
    delays: list[float] = []
    for t_in, amt_in in ins:
        # first outgoing after t_in whose amount is close to amt_in
        for t_out, amt_out in outs:
            if t_out <= t_in:
                continue
            if amt_in * 0.75 <= amt_out <= amt_in * 1.25:
                delays.append((t_out - t_in).total_seconds() / 60.0)
                break
    return float(np.median(delays)) if delays else None


def pass_through_ratio(g, acc: str) -> float | None:
    """Fraction of received money sent on (out_sum / in_sum). None if no inflow."""
    in_sum = sum(d["amount"] for _, _, d in g.in_edges(acc, data=True))
    out_sum = sum(d["amount"] for _, _, d in g.out_edges(acc, data=True))
    if in_sum == 0:
        return None
    return out_sum / in_sum


def chain_velocity(g, accounts: list[str]) -> dict:
    """Velocity metrics for a chain of accounts (ordered as given).

    Reports per-hop delays and the total time from first money-in to last
    money-out across the chain.
    """
    delays: list[float] = []
    t_first_in: datetime | None = None
    t_last_out: datetime | None = None
    for i, acc in enumerate(accounts):
        outs = sorted(g.out_edges(acc, data=True), key=lambda e: e[2]["timestamp"])
        ins = sorted(g.in_edges(acc, data=True), key=lambda e: e[2]["timestamp"])
        if ins and not t_first_in:
            t_first_in = ins[0][2]["timestamp"]
        if outs:
            t_last_out = outs[-1][2]["timestamp"]
        if i > 0:
            # delay between this account's first in-edge and first out-edge
            first_in = ins[0][2]["timestamp"] if ins else None
            first_out = outs[0][2]["timestamp"] if outs else None
            if first_in and first_out and first_out > first_in:
                delays.append((first_out - first_in).total_seconds() / 60.0)
    total_delay = (
        (t_last_out - t_first_in).total_seconds() / 60.0
        if t_first_in and t_last_out
        else None
    )
    return {
        "hop_delays_min": [round(d, 1) for d in delays],
        "median_hop_delay_min": float(np.median(delays)) if delays else None,
        "total_time_min": round(total_delay, 1) if total_delay else None,
    }


def velocity_features(g, acc: str) -> dict[str, float]:
    """The full velocity feature dict used by scoring and the UI."""
    return {
        "txn_count": float(txn_count(g, acc)),
        "txns_per_hour": round(txns_per_hour(g, acc), 3),
        "peak_burst_rate": round(peak_burst_rate(g, acc), 1),
        "pass_through_ratio": (
            round(pass_through_ratio(g, acc), 3)
            if pass_through_ratio(g, acc) is not None
            else 0.0
        ),
        "median_hold_min": (
            round(median_hold_time(g, acc), 1)
            if median_hold_time(g, acc) is not None
            else -1.0
        ),
        "amount_mean": round(
            (
                float(np.mean([d["amount"] for _, _, d in g.in_edges(acc, data=True)]))
                if g.in_degree(acc)
                else 0.0
            ),
            2,
        ),
        "amount_max": round(
            (
                float(np.max([d["amount"] for _, _, d in g.in_edges(acc, data=True)]))
                if g.in_degree(acc)
                else 0.0
            ),
            2,
        ),
    }


def burst_timeline(g, acc: str, bucket: str = "1h") -> list[dict]:
    """Transaction counts bucketed over time for a Recharts timeline."""
    ts = _all_timestamps(g, acc)
    if not ts:
        return []
    s = pd.Series(1, index=pd.DatetimeIndex(ts))
    freq = {"1h": "1h", "6h": "6h", "1D": "1D"}[bucket]
    counts = s.resample(freq).sum()
    return [{"time": str(t), "count": int(c)} for t, c in counts.items() if c > 0]


def _all_timestamps(g, acc: str) -> list[datetime]:
    ts = [d["timestamp"] for _, _, d in g.in_edges(acc, data=True)]
    ts += [d["timestamp"] for _, _, d in g.out_edges(acc, data=True)]
    return sorted(ts)
