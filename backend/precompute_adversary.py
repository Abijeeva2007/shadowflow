"""Precompute the default adversary report into data/adversary_default.json.

The default 32-scheme search (plus the hardening re-search) costs ~a minute
of CPU on a 0.1-CPU free-tier box, so it is done once here instead of on
every page load. The API serves this file at startup; see load_adversary_default
in main.py.

Rerun after changing the adversary, the detectors or the dataset:

    cd backend && ./.venv/bin/python precompute_adversary.py

The committed seed-42 dataset is deterministic, so the result is stable.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine.adversary import run_adversary
from engine.pipeline import run_pipeline

OUT = Path(__file__).parent / "data" / "adversary_default.json"


def main() -> None:
    st = run_pipeline()
    # same quiet-account route the API's default run uses (main._default_route)
    ring_accs = {a for r in st.rings for a in r["accounts"]}

    def pick(bank: str) -> str | None:
        return next(
            (
                a
                for a in sorted(st.suspects)
                if st.g.nodes[a].get("bank") == bank
                and a not in ring_accs
                and st.g.degree(a) <= 3
            ),
            None,
        )

    src, tgt = pick("BankA"), pick("BankC")
    if not src or not tgt:
        raise SystemExit("no quiet suspect pair for the default route")

    report = run_adversary(st.g, st.suspects, src, tgt)
    OUT.write_text(json.dumps(report.summary(), indent=2) + "\n")
    print(
        f"wrote {OUT} ({OUT.stat().st_size // 1024} KB): "
        f"{report.n_schemes_tested} schemes, friction "
        f"{report.friction_before:.2f} -> {report.friction_after:.2f}, "
        f"route {src} -> {tgt}"
    )


if __name__ == "__main__":
    main()
