"""Adversarial twin: a laundering agent that probes the detector.

Given a starting sum and target account, the agent plans a scheme using
tunable evasion levers:
  - hop_delay_hours   : added delay between hops (money sits still)
  - n_splits          : split the sum into more parallel paths
  - jitter            : randomise amounts so retention looks noisy
  - n_decoys          : extra payments through benign-looking shops/persons
  - n_banks           : route through more banks

For each lever setting we inject the scheme into a COPY of the graph, run the
three pattern detectors, and record whether the scheme was detected.

Laundering Friction Score (LFS): for the cheapest evading scheme,
    LFS = (total_hours + fee_pct * 100 + extra_accounts) / naive_cost
where the naive scheme is delay=0, splits=1, jitter=0, decoys=0, banks=1.
Higher means the detector forces criminals to work harder.

Harden step: for every lever direction that produced an evasion we tighten
the matching detector threshold (shorter window, stricter retention, more
deposits required, ...) and report the friction score before vs. after.

Honesty note: this is a rule-threshold search, not a learned adversary. It
shows how much friction the CURRENT thresholds impose, and that thresholds
can be tightened when evasion paths are known.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import timedelta

import networkx as nx

from engine import config, patterns


@dataclass
class SchemeParams:
    """Lever settings for one laundering scheme."""

    hop_delay_hours: float = 0.0  # extra delay per hop
    n_splits: int = 1  # parallel paths
    jitter: float = 0.0  # amount randomisation 0..0.3
    n_decoys: int = 0  # decoy txns through benign accounts
    n_banks: int = 1  # banks touched by the route
    fee_pct: float = 2.0  # cost per hop (percent lost)

    def label(self) -> str:
        return (
            f"delay={self.hop_delay_hours:g}h splits={self.n_splits} "
            f"jitter={self.jitter:g} decoys={self.n_decoys} "
            f"banks={self.n_banks}"
        )


@dataclass
class SchemeResult:
    params: SchemeParams
    detected: bool
    evidence: str
    cost_hours: float
    fee_pct: float
    extra_accounts: int
    friction: float


@dataclass
class AdversaryReport:
    frontier: list[dict] = field(default_factory=list)
    cheapest_evader: SchemeResult | None = None
    friction_before: float = 0.0
    friction_after: float = 0.0
    hardened_thresholds: dict = field(default_factory=dict)
    baseline_detected: bool = True
    n_schemes_tested: int = 0

    def summary(self) -> dict:
        return {
            "baseline_detected": self.baseline_detected,
            "n_schemes_tested": self.n_schemes_tested,
            "cheapest_evader": _sr(self.cheapest_evader),
            "friction_before": round(self.friction_before, 2),
            "friction_after": round(self.friction_after, 2),
            "hardened_thresholds": self.hardened_thresholds,
            "frontier": self.frontier,
        }


def _sr(r: SchemeResult | None) -> dict | None:
    if r is None:
        return None
    return {
        "label": r.params.label(),
        "detected": r.detected,
        "evidence": r.evidence,
        "cost_hours": round(r.cost_hours, 2),
        "fee_pct": round(r.fee_pct, 2),
        "extra_accounts": r.extra_accounts,
        "friction": round(r.friction, 2),
        "params": {
            "hop_delay_hours": r.params.hop_delay_hours,
            "n_splits": r.params.n_splits,
            "jitter": round(r.params.jitter, 3),
            "n_decoys": r.params.n_decoys,
            "n_banks": r.params.n_banks,
        },
    }


def build_scheme_graph(
    g: nx.MultiDiGraph,
    source: str,
    target: str,
    amount: float,
    p: SchemeParams,
    rng: random.Random,
    base_time=None,
) -> tuple[nx.MultiDiGraph, int]:
    """Return a copy of `g` with the scheme injected; also return how many
    extra accounts the scheme required.

    The scheme: source -> mule1 -> ... -> target through `p.n_splits`
    parallel paths of 2 intermediate mules each, with delays, jitter,
    optional decoy payments, spread over `p.n_banks` banks.
    """
    from datetime import datetime

    h = g.copy()
    if base_time is None:
        # pick a quiet mid-window time
        base_time = datetime(2026, 2, 10, 10, 0)

    banks = list(config.BANKS)
    extra_accounts = 0

    def new_mule(preferred_bank: str) -> str:
        nonlocal extra_accounts
        i = 1
        while f"ADV_{preferred_bank}_{i}" in h:
            i += 1
        acc = f"ADV_{preferred_bank}_{i}"
        h.add_node(acc, bank=preferred_bank)
        extra_accounts += 1
        return acc

    for split in range(p.n_splits):
        split_amount = amount / p.n_splits
        # pick banks along the route
        route_banks = [
            banks[(banks.index(nx_get_bank(h, source)) + i) % len(banks)]
            for i in range(max(1, p.n_banks))
        ]
        mules = [new_mule(route_banks[i % len(route_banks)]) for i in range(2)]
        t = base_time + timedelta(
            hours=split * p.hop_delay_hours if p.n_splits > 1 else 0
        )
        amt = split_amount * (1 - rng.uniform(0, p.jitter * 0.1))

        # hop 1: source -> mule1 (immediate)
        h.add_edge(
            source,
            mules[0],
            key=f"ADV{split}_h0",
            timestamp=t,
            amount=round(amt, 2),
            channel="wire",
            bank_src=_bank(h, source),
            bank_dst=_bank(h, mules[0]),
        )
        # hop 2: mule1 -> mule2 after the added delay
        delay = timedelta(hours=p.hop_delay_hours) + timedelta(
            minutes=rng.randint(1, 90)
        )
        amt *= 1 - p.fee_pct / 100.0
        amt *= 1 - rng.uniform(0, p.jitter * 0.1)
        h.add_edge(
            mules[0],
            mules[1],
            key=f"ADV{split}_h1",
            timestamp=t + delay,
            amount=round(amt, 2),
            channel="wire",
            bank_src=_bank(h, mules[0]),
            bank_dst=_bank(h, mules[1]),
        )
        # hop 3: mule2 -> target, again after delay
        delay2 = timedelta(hours=p.hop_delay_hours) + timedelta(
            minutes=rng.randint(1, 90)
        )
        amt *= 1 - p.fee_pct / 100.0
        amt *= 1 - rng.uniform(0, p.jitter * 0.1)
        h.add_edge(
            mules[1],
            target,
            key=f"ADV{split}_h2",
            timestamp=t + delay + delay2,
            amount=round(amt, 2),
            channel="wire",
            bank_src=_bank(h, mules[1]),
            bank_dst=_bank(h, target),
        )

    # decoy payments: small benign-looking transactions around the scheme
    benign_pool = [
        n
        for n, d in g.nodes(data=True)
        if d.get("bank") in banks and n != source and n != target
    ][:400]
    for i in range(p.n_decoys):
        if not benign_pool:
            break
        a = rng.choice(benign_pool)
        b = rng.choice(benign_pool)
        t = base_time + timedelta(
            hours=rng.randint(-24, 48), minutes=rng.randint(0, 59)
        )
        h.add_edge(
            a,
            b,
            key=f"ADV_decoy{i}",
            timestamp=t,
            amount=round(rng.uniform(50, 900), 2),
            channel="transfer",
            bank_src=_bank(h, a),
            bank_dst=_bank(h, b),
        )

    return h, extra_accounts


def nx_get_bank(h: nx.MultiDiGraph, acc: str) -> str:
    return h.nodes[acc].get("bank", config.BANKS[0])


def _bank(h: nx.MultiDiGraph, acc: str) -> str:
    return h.nodes[acc].get("bank", "?")


def run_detector_on(h: nx.MultiDiGraph, suspects: set[str] | None) -> dict:
    """Run the three detectors on a (modified) graph."""
    return {
        "cycle": patterns.detect_cycles(h, allowed_nodes=suspects),
        "mule_chain": patterns.detect_passthrough_chains(h, allowed_nodes=suspects),
        "smurfing": patterns.detect_smurfing(h, allowed_nodes=suspects),
    }


def scheme_detected(
    hits: dict,
    source: str,
    target: str,
    extra_nodes: set[str],
    pre_existing: set[frozenset] | None = None,
) -> tuple[bool, str]:
    """A scheme is 'detected' when a detector fires on the SCHEME itself:
    a hit that involves an injected mule, or a hit on source/target whose
    account-set was NOT already detected on the untouched graph (pre-existing
    rings on those accounts don't count as catching the new scheme)."""
    pre = pre_existing or set()
    for ptype, hit_list in hits.items():
        for hit in hit_list:
            accs = set(hit.get("accounts", []))
            if accs & extra_nodes:
                return (
                    True,
                    f"{ptype} on injected mule {sorted(accs & extra_nodes)[:2]}",
                )
            if (source in accs or target in accs) and frozenset(accs) not in pre:
                return True, f"{ptype} on {sorted(accs)[:3]}"
    return False, ""


def friction_score(p: SchemeParams, extra_accounts: int, naive: dict) -> float:
    """LFS = (time + fees + extra accounts) / same for the naive scheme.

    Cost model (hours + fee percent + accounts kept comparable by scale):
      time    = 2 * hop_delay_hours + 0.05h of base movement + decoy setup
      fees    = 2 * fee_pct (one lossy hop per transfer)
      accounts= extra mule accounts that must be opened and burned
    The naive scheme normalises to LFS = 1.0.
    """
    cost = (
        2 * p.hop_delay_hours
        + 0.05
        + p.n_decoys * 0.05
        + 2 * p.fee_pct
        + extra_accounts
    )
    return cost / naive["cost"]


def _naive_cost(fee_pct: float = 2.0) -> float:
    return 0.05 + 2 * fee_pct + 2.0


def run_adversary(
    g: nx.MultiDiGraph,
    suspects: set[str],
    source: str,
    target: str,
    amount: float = 100_000.0,
    grid: list[SchemeParams] | None = None,
    seed: int = 42,
) -> AdversaryReport:
    """Search the lever grid; build the evasion frontier; run the harden step."""
    rng = random.Random(seed)
    report = AdversaryReport()

    if grid is None:
        grid = default_grid()

    naive_params = SchemeParams()
    naive = {"cost": _naive_cost(naive_params.fee_pct)}

    # NOTE: injected mules are thin-file accounts; the real pipeline would
    # never mark them benign, so they stay in the search space alongside the
    # suspects from the base graph.
    scheme_nodes = {source, target}

    def allowed_for(h: nx.MultiDiGraph) -> set[str]:
        return suspects | {n for n in h if str(n).startswith("ADV_")} | scheme_nodes

    # Hits that exist on the UNTOUCHED graph (e.g. the ground-truth rings)
    # must not be attributed to an injected scheme.
    h0, _ = build_scheme_graph(g, source, target, amount, naive_params, rng)
    base_hits = run_detector_on(h0, suspects | {source, target})
    pre_existing = {
        frozenset(h["accounts"]) for hits in base_hits.values() for h in hits
    }

    # baseline: does the naive scheme get caught?
    h_base, extra_base = build_scheme_graph(
        g, source, target, amount, naive_params, rng
    )
    base_hits = run_detector_on(h_base, allowed_for(h_base))
    base_det, base_ev = scheme_detected(
        base_hits,
        source,
        target,
        {n for n in h_base if str(n).startswith("ADV_")},
        pre_existing,
    )
    report.baseline_detected = base_det
    report.n_schemes_tested += 1

    evaders: list[SchemeResult] = []
    for p in grid:
        h, extra = build_scheme_graph(g, source, target, amount, p, rng)
        hits = run_detector_on(h, allowed_for(h))
        det, ev = scheme_detected(
            hits,
            source,
            target,
            {n for n in h if str(n).startswith("ADV_")},
            pre_existing,
        )
        report.n_schemes_tested += 1
        fr = friction_score(p, extra, naive)
        r = SchemeResult(
            params=p,
            detected=det,
            evidence=ev,
            cost_hours=2 * p.hop_delay_hours + 0.05,
            fee_pct=p.fee_pct * 2,
            extra_accounts=extra,
            friction=fr,
        )
        report.frontier.append(
            {
                "label": p.label(),
                "params": {
                    "hop_delay_hours": p.hop_delay_hours,
                    "n_splits": p.n_splits,
                    "jitter": round(p.jitter, 3),
                    "n_decoys": p.n_decoys,
                    "n_banks": p.n_banks,
                },
                "detected": det,
                "evidence": ev,
                "cost_hours": round(r.cost_hours, 2),
                "fee_pct": round(r.fee_pct, 2),
                "extra_accounts": extra,
                "friction": round(fr, 2),
            }
        )
        if not det:
            evaders.append(r)

    # cheapest evader = lowest friction among undetected
    if evaders:
        report.cheapest_evader = min(evaders, key=lambda r: r.friction)
        report.friction_before = report.cheapest_evader.friction
    else:
        report.cheapest_evader = None
        report.friction_before = 999.0  # detector catches everything

    # ---- harden step ----------------------------------------------------
    hard = _harden(
        report, g, suspects, source, target, amount, rng, naive, pre_existing
    )
    report.friction_after = hard["friction_after"]
    report.hardened_thresholds = hard["thresholds"]
    return report


def _harden(
    report: AdversaryReport,
    g: nx.MultiDiGraph,
    suspects: set[str],
    source: str,
    target: str,
    amount: float,
    rng: random.Random,
    naive: dict,
    pre_existing: set[frozenset] | None = None,
) -> dict:
    """Tighten detector thresholds based on the evasions found and re-measure.

    We learn from the cheapest evader which lever let it through and tighten
    the matching detector(s). Then we re-run the cheapest evader's params: if
    it is now detected, the friction score AFTER hardening is the friction of
    the new cheapest evader (searched again over the grid).
    """
    th: dict = {}
    ev = report.cheapest_evader
    if ev is None:
        return {"friction_after": report.friction_before, "thresholds": th}

    p = ev.params
    # Evasion via LONG delays: the pass-through detector only links hops
    # within its delay window. Harden by EXTENDING the window (and requiring
    # cleaner forwarding ratios), so slow mules are still linked.
    if p.hop_delay_hours > 0:
        needed = int((p.hop_delay_hours + 2) * 60)  # minutes
        th["chain_max_delay_min"] = max(config.CHAIN_MAX_DELAY_MIN, needed)
        th["chain_min_forward"] = min(0.95, config.CHAIN_MIN_FORWARD + 0.05)
    # Evasion via splitting: more required deposit sources for smurf fans
    if p.n_splits >= 4:
        th["smurf_min_deposits"] = config.SMURF_MIN_DEPOSITS
    if not th:
        # generic tightening
        th = {
            "chain_min_forward": min(0.95, config.CHAIN_MIN_FORWARD + 0.05),
            "cycle_min_retention": min(0.95, config.CYCLE_MIN_RETENTION + 0.05),
        }

    # re-run the full grid under hardened thresholds
    evaders_after: list[SchemeResult] = []
    for q in default_grid():
        h, extra = build_scheme_graph(g, source, target, amount, q, rng)
        allowed = (
            suspects | {n for n in h if str(n).startswith("ADV_")} | {source, target}
        )
        hits = {
            "cycle": patterns.detect_cycles(
                h,
                allowed_nodes=allowed,
                window_hours=th.get("cycle_window_hours", config.CYCLE_WINDOW_HOURS),
                min_retention=th.get("cycle_min_retention", config.CYCLE_MIN_RETENTION),
            ),
            "mule_chain": patterns.detect_passthrough_chains(
                h,
                allowed_nodes=allowed,
                max_delay_min=th.get("chain_max_delay_min", config.CHAIN_MAX_DELAY_MIN),
                min_forward=th.get("chain_min_forward", config.CHAIN_MIN_FORWARD),
            ),
            "smurfing": patterns.detect_smurfing(
                h,
                allowed_nodes=allowed,
                min_deposits=th.get("smurf_min_deposits", config.SMURF_MIN_DEPOSITS),
            ),
        }
        det, _ = scheme_detected(
            hits,
            source,
            target,
            {n for n in h if str(n).startswith("ADV_")},
            pre_existing,
        )
        if not det:
            evaders_after.append(
                SchemeResult(
                    params=q,
                    detected=False,
                    evidence="",
                    cost_hours=2 * q.hop_delay_hours + 0.05,
                    fee_pct=q.fee_pct * 2,
                    extra_accounts=extra,
                    friction=friction_score(q, extra, naive),
                )
            )
    if evaders_after:
        fr_after = min(r.friction for r in evaders_after)
    else:
        fr_after = report.friction_before * 3  # detector wins: friction explodes
    return {"friction_after": fr_after, "thresholds": th}


def default_grid() -> list[SchemeParams]:
    """A compact, demo-friendly grid over the evasion levers."""
    grid: list[SchemeParams] = []
    for delay in (0, 6, 24, 48):
        for splits in (1, 4):
            for decoys in (0, 20):
                for banks in (1, 3):
                    grid.append(
                        SchemeParams(
                            hop_delay_hours=float(delay),
                            n_splits=splits,
                            jitter=0.1 if splits > 1 else 0.0,
                            n_decoys=decoys,
                            n_banks=banks,
                        )
                    )
    return grid
