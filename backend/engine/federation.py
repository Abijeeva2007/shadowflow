"""Privacy-preserving cross-bank linking (simulated federation).

Each bank runs detection on ONLY its own transaction rows (its own copy of
the graph). Instead of sharing raw data, each bank emits "signals":

    {hashed_account_id, pattern_type, time window, amount bucket, direction}

The coordinator (this platform) joins signals across banks on equal hashed
account ids and stitches cross-bank chains.

What this protects (and what it does NOT) - be honest:
  * Protects: bulk sharing of raw customer data between banks; the coordinator
    cannot browse accounts it has not matched and not asked to reveal.
  * Does NOT protect: because every bank hashes the SAME account ids with the
    SAME shared salt, the coordinator (or any bank) can build a dictionary
    attack against known ids - this simulation even ships the mapping used by
    the demo. Frequency/timing correlation and amount buckets leak extra
    structure. A real deployment would need per-bank salts + a private set
    intersection or secure MPC protocol, plus governance. This prototype is
    a *workflow* demo of the signal-exchange pattern, NOT a cryptographic
    guarantee.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field

import pandas as pd

from engine import config, patterns
from engine import graph as graph_mod


def hash_account(account_id: str, salt: str | None = None) -> str:
    """Salted HMAC-SHA256 of an account id (the banks' pseudonymisation)."""
    salt = salt or config.FEDERATION_SALT
    return hmac.new(salt.encode(), account_id.encode(), hashlib.sha256).hexdigest()[:16]


def amount_bucket(amount: float) -> str:
    """Coarse amount bucket shared in signals."""
    if amount < 1_000:
        return "<1k"
    if amount < 10_000:
        return "1k-10k"
    if amount < 100_000:
        return "10k-100k"
    return "100k+"


@dataclass
class Signal:
    bank: str
    hashed_id: str
    pattern_type: str
    direction: str  # inbound | outbound
    window_start: str
    window_end: str
    amount_bucket: str
    pattern_score: float
    # kept ONLY on the bank side, never shown in the federated view:
    account_id: str | None = None


@dataclass
class FederatedState:
    signals: list[Signal] = field(default_factory=list)
    chains: list[dict] = field(default_factory=list)
    banks: list[str] = field(default_factory=list)


def _bank_dataframe(txns: pd.DataFrame, bank: str) -> pd.DataFrame:
    """A bank's own log: only txns where this bank is src or dst.

    Note: for cross-bank txns both banks hold their copy - that is exactly
    how subpoena logs work, and the join below relies on shared timestamps.
    """
    return txns[(txns.bank_src == bank) | (txns.bank_dst == bank)].copy()


def run_local_detection(txns: pd.DataFrame, bank: str) -> list[dict]:
    """Bank-side detection: build the bank-only graph and find hits.

    Local benign filtering is skipped on purpose for the demo (bank graphs
    are small); local hits are what the bank is willing to signal about.
    """
    df = _bank_dataframe(txns, bank)
    g = graph_mod.build_graph(df)
    cyc = patterns.detect_cycles(g)
    chn = patterns.detect_passthrough_chains(g)
    smf = patterns.detect_smurfing(g)
    out: list[dict] = []
    for h in cyc:
        out.append({"hit": h, "accounts": h["accounts"]})
    for h in chn:
        out.append({"hit": h, "accounts": h["accounts"]})
    for h in smf:
        out.append({"hit": h, "accounts": h["accounts"]})
    return out


def build_signals(txns: pd.DataFrame, banks: list[str] | None = None) -> FederatedState:
    """Run local detection at every bank and produce the shared signals."""
    banks = banks or config.BANKS
    state = FederatedState(banks=banks)
    for bank in banks:
        for hit in run_local_detection(txns, bank):
            h = hit["hit"]
            ptype = h["type"]
            start = h["start"].strftime("%Y-%m-%d %H:%M:%S")
            end = h["end"].strftime("%Y-%m-%d %H:%M:%S")
            amount = (
                h.get("amount_start")
                or h.get("amount_in")
                or h.get("total_amount")
                or 0
            )
            for acc in hit["accounts"]:
                direction = (
                    "outbound"
                    if acc == h.get("origin")
                    else (
                        "inbound"
                        if acc == h.get("collector") or acc == h.get("terminal")
                        else "transit"
                    )
                )
                state.signals.append(
                    Signal(
                        bank=bank,
                        hashed_id=hash_account(acc),
                        pattern_type=ptype,
                        direction=direction,
                        window_start=start,
                        window_end=end,
                        amount_bucket=amount_bucket(float(amount)),
                        pattern_score=round(
                            min(
                                50.0
                                + 50.0
                                * (
                                    h.get("structuring_score", 0.5)
                                    if ptype == "smurfing"
                                    else (
                                        (1 - h.get("retention", 0.9))
                                        if ptype == "cycle"
                                        else h.get("retention", 0.9)
                                    )
                                ),
                                100.0,
                            ),
                            1,
                        ),
                        account_id=acc,  # bank-side only; not shared
                    )
                )
    return state


def stitch_chains(state: FederatedState, min_banks: int = 2) -> list[dict]:
    """Coordinator: join signals on hashed ids and stitch cross-bank chains.

    Two signals link when they share a hashed account id AND overlap in time
    (same pattern type OR same account). Groups touching >= min_banks banks
    become federated cases.
    """
    # group signals by hashed id
    by_hash: dict[str, list[Signal]] = {}
    for s in state.signals:
        by_hash.setdefault(s.hashed_id, []).append(s)

    # union-find over signals that share a hash or overlap in time+type
    parent: list[int] = list(range(len(state.signals)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    sigs = state.signals
    # same hashed id -> same group (indices by position, not equality)
    idx_by_hash: dict[str, int] = {}
    for i, s in enumerate(sigs):
        if s.hashed_id in idx_by_hash:
            union(idx_by_hash[s.hashed_id], i)
        else:
            idx_by_hash[s.hashed_id] = i

    # same bank-pair time-window + type overlap -> same group
    for i in range(len(sigs)):
        for j in range(i + 1, len(sigs)):
            a, b = sigs[i], sigs[j]
            if a.pattern_type != b.pattern_type:
                continue
            # time windows overlap?
            if a.window_start <= b.window_end and b.window_start <= a.window_end:
                union(i, j)

    groups: dict[int, list[Signal]] = {}
    for i in range(len(sigs)):
        groups.setdefault(find(i), []).append(sigs[i])

    chains: list[dict] = []
    for members in groups.values():
        banks_touched = sorted({m.bank for m in members})
        if len(banks_touched) < min_banks:
            continue
        hashes = sorted({m.hashed_id for m in members})
        chains.append(
            {
                "case_id": f"FED-{len(chains) + 1:02d}",
                "banks": banks_touched,
                "pattern_types": sorted({m.pattern_type for m in members}),
                "n_accounts": len(hashes),
                "hashed_ids": hashes,
                "window_start": min(m.window_start for m in members),
                "window_end": max(m.window_end for m in members),
                "amount_bucket": max(
                    (m.amount_bucket for m in members),
                    key=lambda b: ["<1k", "1k-10k", "10k-100k", "100k+"].index(b),
                ),
                "n_signals": len(members),
                "member_signal_ids": [id(m) for m in members],
            }
        )
    chains.sort(key=lambda c: -c["n_signals"])
    state.chains = chains
    return chains


def reveal_account(
    state: FederatedState,
    hashed_id: str,
    authorised_by: str,
    _secret_mapping: dict[str, str] | None = None,
) -> dict:
    """Investigator view: reveal the real account id behind a hash.

    MOCK AUTHORISATION: in this prototype the "reveal" just checks that a
    request reason was provided, then looks the id up in the mapping that the
    banks contributed to the coordinator. There is NO real cryptographic
    access control here - a production system would require dual control,
    audit logging, and legal process. The demo shows the two-view UX.
    """
    if not authorised_by or len(authorised_by.strip()) < 3:
        return {
            "revealed": False,
            "reason": "authorisation required: provide an investigating officer name",
        }
    mapping = _secret_mapping or {
        s.hashed_id: s.account_id for s in state.signals if s.account_id
    }
    acc = mapping.get(hashed_id)
    if acc is None:
        return {"revealed": False, "reason": "unknown hash"}
    sigs = [s for s in state.signals if s.hashed_id == hashed_id]
    return {
        "revealed": True,
        "hashed_id": hashed_id,
        "account_id": acc,
        "banks": sorted({s.bank for s in sigs}),
        "authorised_by": authorised_by,
        "note": "mock authorisation for demo; not a production access-control mechanism",
    }


def federated_summary(state: FederatedState) -> dict:
    by_bank: dict[str, int] = {b: 0 for b in state.banks}
    for s in state.signals:
        by_bank[s.bank] += 1
    return {
        "banks": state.banks,
        "n_signals": len(state.signals),
        "signals_per_bank": by_bank,
        "n_federated_cases": len(state.chains),
        "cases": state.chains,
    }
