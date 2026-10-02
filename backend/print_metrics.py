"""Print the full ShadowFlow metric set from one real run.

Usage (from backend/):  ./.venv/bin/python print_metrics.py
Covers the pipeline (detection + benign filter), the adversary friction
before/after hardening, and the federation signal/case counts. These are the
numbers quoted in the README and demo script; seed 42 keeps them stable.
"""

from __future__ import annotations

from engine import federation as fed
from engine.adversary import run_adversary
from engine.pipeline import DetectionState, run_pipeline


def default_route(st: DetectionState) -> tuple[str, str]:
    """Same deterministic demo route as the API's _default_route()."""
    ring_accs = {a for r in st.rings for a in r["accounts"]}

    def pick(bank: str) -> str:
        for a in sorted(st.suspects):
            if (
                st.g.nodes[a].get("bank") == bank
                and a not in ring_accs
                and st.g.degree(a) <= 3
            ):
                return a
        return f"{bank}_0001"

    return pick("BankA"), pick("BankC")


def main() -> None:
    st = run_pipeline()
    m = st.metrics
    fc = st.filter_counts
    s = m["summary"]

    print("=" * 64)
    print("ShadowFlow run metrics (synthetic seed-42 data)")
    print("=" * 64)
    print(f"transactions          : {len(st.txns):,}")
    print(f"accounts              : {st.g.number_of_nodes():,}")
    print(f"edges                 : {st.g.number_of_edges():,}")
    print(f"alerts before filter  : {fc['alerts_before']:,}")
    print(f"alerts after filter   : {fc['alerts_after']:,}")
    print(f"cleared as benign     : {fc['alerts_filtered']:,}")
    print(
        f"rings detected        : {s['rings_detected_after']}/{s['rings_in_ground_truth']}"
    )
    for p, v in m["per_pattern"].items():
        a = v["after_filter"]
        print(
            f"  {p:<11}: P={a['precision']:.2f}  R={a['recall']:.2f}  F1={a['f1']:.2f}"
        )
    print(f"decoy false alarms    : {m['decoys']['after_filter']['total_flagged']}")
    print()

    src, tgt = default_route(st)
    rep = run_adversary(st.g, st.suspects, src, tgt, amount=50_000)
    adv = rep.summary()
    n_det = sum(1 for f in adv["frontier"] if f["detected"])
    print(f"adversary grid        : {len(adv['frontier'])} schemes, {n_det} detected")
    print(
        f"friction before/after : {adv['friction_before']:.2f}x -> {adv['friction_after']:.2f}x"
    )
    if adv["cheapest_evader"]:
        print(f"cheapest evader       : {adv['cheapest_evader']['label']}")
    print()

    fedstate = fed.build_signals(st.txns)
    fedstate.chains = fed.stitch_chains(fedstate)
    print(f"federation signals    : {len(fedstate.signals)}")
    print(f"cross-bank cases      : {len(fedstate.chains)}")
    print("=" * 64)


if __name__ == "__main__":
    main()
