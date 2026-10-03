"""ShadowFlow benchmark: 10 seeds x 3 benign-noise levels, plus ablations.

Writes docs/BENCHMARK.md and docs/benchmark.json (repo-root docs/).

For every (seed, noise) run this regenerates the dataset into a scratch
directory, runs the unmodified detection pipeline, and scores it against the
injected ground truth. Detector thresholds are NOT touched: this script only
measures. Noise scales background benign traffic volume only (low 0.5x,
medium 1.0x, high 1.5x); injected rings and decoys are identical in shape
across levels.

Ablations reported:
  - full pipeline vs. without the benign filter (ring level, the evaluate
    module already runs both);
  - with vs. without the Isolation Forest term (account level; the ablated
    score keeps the production weights and replaces the anomaly term with
    its neutral value of 50, i.e. score = 0.6 * pattern + 0.4 * 50);
  - adversary friction before vs. after hardening (10 runs, medium noise).

Usage: python benchmark.py   (or `make benchmark` from the repo root)
Runtime: about 2-3 minutes.
"""

from __future__ import annotations

import contextlib
import io
import json
import statistics
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import generate_data
from engine import adversary as adv
from engine import config
from engine.evaluate import truth_accounts
from engine.pipeline import run_pipeline

DOCS = Path(__file__).resolve().parent.parent / "docs"
SEEDS = list(range(1, 11))
NOISE_LEVELS = {"low": 0.5, "medium": 1.0, "high": 1.5}
PATTERNS = ("cycle", "mule_chain", "smurfing")
# Same cutoff the dashboard uses for its "elevated" amber band.
FLAG_CUTOFF = 55.0
NEUTRAL_ANOMALY = 50.0  # median percentile: the neutral stand-in for the IF term


# --------------------------------------------------------------------- helpers
def prf(pred: set, gt: set) -> dict:
    """Precision / recall / F1 of a predicted account set vs. ground truth."""
    tp = len(pred & gt)
    p = tp / len(pred) if pred else 0.0
    r = tp / len(gt) if gt else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(f, 3)}


def agg(vals: list) -> dict | None:
    """Mean and sample standard deviation of a list (None entries dropped)."""
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return {
        "mean": round(statistics.mean(vals), 4),
        "std": round(statistics.stdev(vals), 4) if len(vals) > 1 else 0.0,
        "n": len(vals),
    }


def ms(a: dict | None, nd: int = 3) -> str:
    if a is None:
        return "n/a"
    return f"{a['mean']:.{nd}f} ± {a['std']:.{nd}f}"


def default_route(st) -> tuple[str, str] | None:
    """Same quiet-account route main.py uses for the adversary demo."""
    ring_accs = {a for r in st.rings for a in r["accounts"]}

    def pick(bank: str):
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
    return (src, tgt) if src and tgt else None


# ------------------------------------------------------------------- one run
def run_one(seed: int, noise_name: str, noise_val: float) -> tuple[dict, dict | None]:
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="sf_bench_") as td:
        tmp = Path(td)
        generate_data.NOISE = noise_val
        with contextlib.redirect_stdout(io.StringIO()):
            generate_data.main(seed=seed, out_dir=tmp)
        config.DATA_DIR = tmp
        st = run_pipeline()

    m = st.metrics
    gt = st.ground_truth
    rec: dict = {"seed": seed, "noise": noise_name, "patterns": {}}
    for pt in PATTERNS:
        after = m["per_pattern"][pt]["after_filter"]
        before = m["per_pattern"][pt]["before_filter"]
        rec["patterns"][pt] = {
            "full": {
                k: after[k] for k in ("precision", "recall", "f1", "tp", "fp", "fn")
            },
            "no_filter": {
                k: before[k] for k in ("precision", "recall", "f1", "tp", "fp", "fn")
            },
        }
    rec["decoys"] = {
        "total": len(gt["decoys"]),
        "flagged_full": m["decoys"]["after_filter"]["total_flagged"],
        "flagged_no_filter": m["decoys"]["before_filter"]["total_flagged"],
    }
    rec["rings"] = {
        "ground_truth": m["summary"]["rings_in_ground_truth"],
        "flagged": m["summary"]["rings_detected_after"],
        "injected_found": sum(
            m["per_pattern"][p]["after_filter"]["tp"] for p in PATTERNS
        ),
        "injected_found_no_filter": sum(
            m["per_pattern"][p]["before_filter"]["tp"] for p in PATTERNS
        ),
    }
    rec["n_txns"] = len(st.txns)
    rec["n_suspects"] = len(st.suspects)

    # account level: production score vs. without the Isolation Forest term
    gt_accs: set = set()
    for key in ("cycles", "mule_chains", "smurfing"):
        for record in gt[key]:
            gt_accs |= truth_accounts(record)
    full_pred = {a for a, v in st.accounts.items() if v["score"] >= FLAG_CUTOFF}
    no_if_pred = {
        a
        for a, v in st.accounts.items()
        if 0.6 * v["pattern_score"] + 0.4 * NEUTRAL_ANOMALY >= FLAG_CUTOFF
    }
    rec["accounts"] = {
        "n_ground_truth": len(gt_accs),
        "full": prf(full_pred, gt_accs),
        "no_if": prf(no_if_pred, gt_accs),
    }

    # adversary (medium noise only: one representative graph per seed)
    adv_rec = None
    if noise_name == "medium":
        route = default_route(st)
        if route:
            with contextlib.redirect_stdout(io.StringIO()):
                rep = adv.run_adversary(
                    st.g, st.suspects, route[0], route[1], seed=seed
                )
            adv_rec = {
                "seed": seed,
                "friction_before": round(rep.friction_before, 3),
                "friction_after": round(rep.friction_after, 3),
                "n_schemes_tested": rep.n_schemes_tested,
                "baseline_detected": rep.baseline_detected,
            }
    rec["seconds"] = round(time.perf_counter() - t0, 1)
    return rec, adv_rec


# ---------------------------------------------------------------- aggregation
def aggregate(runs: list[dict], adv_runs: list[dict]) -> dict:
    out: dict = {"by_noise": {}, "pooled": {}, "adversary": None}
    for noise in NOISE_LEVELS:
        subset = [r for r in runs if r["noise"] == noise]
        out["by_noise"][noise] = {
            "patterns": {
                pt: {
                    "precision": agg(
                        [r["patterns"][pt]["full"]["precision"] for r in subset]
                    ),
                    "recall": agg(
                        [r["patterns"][pt]["full"]["recall"] for r in subset]
                    ),
                    "f1": agg([r["patterns"][pt]["full"]["f1"] for r in subset]),
                }
                for pt in PATTERNS
            },
            "decoys_flagged": agg([r["decoys"]["flagged_full"] for r in subset]),
            "decoys_total": subset[0]["decoys"]["total"] if subset else None,
            "rings_flagged": agg([r["rings"]["flagged"] for r in subset]),
            "injected_found": agg([r["rings"]["injected_found"] for r in subset]),
            "ground_truth_rings": (
                subset[0]["rings"]["ground_truth"] if subset else None
            ),
        }
    out["pooled"] = {
        "patterns": {
            pt: {
                "full": {
                    k: agg([r["patterns"][pt]["full"][k] for r in runs])
                    for k in ("precision", "recall", "f1")
                },
                "no_filter": {
                    k: agg([r["patterns"][pt]["no_filter"][k] for r in runs])
                    for k in ("precision", "recall", "f1")
                },
            }
            for pt in PATTERNS
        },
        "decoys_flagged": {
            "full": agg([r["decoys"]["flagged_full"] for r in runs]),
            "no_filter": agg([r["decoys"]["flagged_no_filter"] for r in runs]),
            "total": runs[0]["decoys"]["total"],
        },
        "accounts": {
            "full": {
                k: agg([r["accounts"]["full"][k] for r in runs])
                for k in ("precision", "recall", "f1")
            },
            "no_if": {
                k: agg([r["accounts"]["no_if"][k] for r in runs])
                for k in ("precision", "recall", "f1")
            },
        },
    }
    if adv_runs:
        out["adversary"] = {
            "friction_before": agg([a["friction_before"] for a in adv_runs]),
            "friction_after": agg([a["friction_after"] for a in adv_runs]),
            "n_schemes_tested": agg([a["n_schemes_tested"] for a in adv_runs]),
            "baseline_detected": sum(1 for a in adv_runs if a["baseline_detected"]),
            "n_runs": len(adv_runs),
        }
    return out


# ------------------------------------------------------------------- markdown
def render_markdown(data: dict) -> str:
    runs, agg_ = data["runs"], data["aggregates"]
    total_s = sum(r["seconds"] for r in runs)
    lines: list[str] = []
    a = lines.append

    a("# Benchmark: seeds and noise levels")
    a("")
    a(
        "Generated by `make benchmark` (backend/benchmark.py). Every combination "
        "regenerates the dataset for one seed at one benign-noise level and runs "
        "the unmodified detection pipeline against the injected ground truth: "
        f"**{len(SEEDS)} seeds (1-{SEEDS[-1]}) x {len(NOISE_LEVELS)} noise levels "
        f"= {len(runs)} runs**. Numbers are mean ± sample standard deviation over "
        "the 10 seeds. No detector threshold is changed by this script, and none "
        "was tuned to improve these numbers."
    )
    a("")
    a(
        "Noise levels scale background benign traffic volume only "
        "(low 0.5x, medium 1.0x, high 1.5x); injected rings and decoys are the "
        "same shape at every level. All data is synthetic - see "
        "[DATA_CARD](DATA_CARD.md)."
    )
    a("")

    # Table 1: per noise level, per pattern
    a("## Full pipeline per noise level")
    a("")
    a("| Noise | Pattern | Precision | Recall | F1 |")
    a("|---|---|---|---|---|")
    for noise in NOISE_LEVELS:
        nd = agg_["by_noise"][noise]
        for pt in PATTERNS:
            p = nd["patterns"][pt]
            a(
                f"| {noise} | {pt} | {ms(p['precision'])} | {ms(p['recall'])} "
                f"| {ms(p['f1'])} |"
            )
    a("")

    a("## Rings and look-alikes per noise level")
    a("")
    a("| Noise | Injected rings found | Rings flagged | Benign look-alikes flagged |")
    a("|---|---|---|---|")
    for noise in NOISE_LEVELS:
        nd = agg_["by_noise"][noise]
        a(
            f"| {noise} | {ms(nd['injected_found'], 2)} of {nd['ground_truth_rings']} "
            f"| {ms(nd['rings_flagged'], 2)} "
            f"| {ms(nd['decoys_flagged'], 2)} of {nd['decoys_total']} |"
        )
    a("")

    # Ablation 1: benign filter (ring level, pooled)
    a("## Ablation: full pipeline vs. without the benign filter")
    a("")
    a(
        'Ring level, pooled over all 30 runs. "Without filter" runs the same '
        "detectors over every account (the evaluate module's before-filter pass)."
    )
    a("")
    a("| Pattern | F1 with filter | F1 without filter |")
    a("|---|---|---|")
    for pt in PATTERNS:
        f = agg_["pooled"]["patterns"][pt]
        a(f"| {pt} | {ms(f['full']['f1'])} | {ms(f['no_filter']['f1'])} |")
    a("")
    dc = agg_["pooled"]["decoys_flagged"]
    a(
        f"Benign look-alikes flagged: **{ms(dc['full'], 2)} of {dc['total']} with "
        f"the filter, {ms(dc['no_filter'], 2)} of {dc['total']} without it.**"
    )
    a("")

    # Ablation 2: Isolation Forest (account level, pooled)
    a("## Ablation: with vs. without the Isolation Forest score")
    a("")
    a(
        f"Account level, pooled over all {len(runs)} runs: accounts scoring "
        f">= {FLAG_CUTOFF:g} (the dashboard's elevated band) vs. the ground-truth "
        "criminal accounts. The ablated score keeps the production weights and "
        "replaces the anomaly term with its neutral value 50 "
        "(`0.6 * pattern + 0.4 * 50`)."
    )
    a("")
    a("| Score | Precision | Recall | F1 |")
    a("|---|---|---|---|")
    fa = agg_["pooled"]["accounts"]["full"]
    na = agg_["pooled"]["accounts"]["no_if"]
    a(
        f"| full (pattern + Isolation Forest) | {ms(fa['precision'])} "
        f"| {ms(fa['recall'])} | {ms(fa['f1'])} |"
    )
    a(
        f"| without Isolation Forest | {ms(na['precision'])} "
        f"| {ms(na['recall'])} | {ms(na['f1'])} |"
    )
    a("")

    # Ablation 3: adversary
    a("## Ablation: adversary friction before vs. after hardening")
    a("")
    ad = agg_.get("adversary")
    if ad:
        a(
            f"Cheapest-evader friction score (cost of the cheapest scheme that "
            f"still evades detection, as a multiple of a naive one-hop transfer), "
            f"over {ad['n_runs']} runs at medium noise "
            f"(mean ± std; scheme grid tested: {ms(ad['n_schemes_tested'], 1)} "
            f"combinations per run)."
        )
        a("")
        a("| Metric | Value |")
        a("|---|---|")
        a(f"| Friction before hardening | {ms(ad['friction_before'], 2)} |")
        a(f"| Friction after hardening | {ms(ad['friction_after'], 2)} |")
        a(
            f"| Baseline naive scheme detected | {ad['baseline_detected']} "
            f"of {ad['n_runs']} runs |"
        )
    else:
        a("No adversary runs completed.")
    a("")

    a("## Notes and limits")
    a("")
    a(
        "- Synthetic data only: the generator creates the three pattern families "
        "and the detectors were written for those families, so these numbers "
        "describe this pipeline working as designed, not real-world accuracy."
    )
    a(
        "- Thresholds in `engine/config.py` are fixed for every run; nothing here "
        "is tuned per seed or per noise level."
    )
    a(
        f"- Total measured run time: {total_s:.0f}s of compute across "
        f"{len(runs)} pipeline runs."
    )
    a("- Raw per-run records and aggregates: " "[benchmark.json](benchmark.json).")
    a("")
    return "\n".join(lines)


# ----------------------------------------------------------------------- main
def main() -> None:
    t_start = time.perf_counter()
    runs: list[dict] = []
    adv_runs: list[dict] = []
    failures: list[str] = []

    for noise_name, noise_val in NOISE_LEVELS.items():
        for seed in SEEDS:
            try:
                rec, adv_rec = run_one(seed, noise_name, noise_val)
            except Exception as e:  # keep going; report honestly
                failures.append(f"seed {seed}/{noise_name}: {type(e).__name__}: {e}")
                continue
            runs.append(rec)
            if adv_rec:
                adv_runs.append(adv_rec)
            print(
                f"seed {seed:>2} {noise_name:>6}: {rec['seconds']:>4}s  "
                f"found {rec['rings']['injected_found']}/15  "
                f"decoys {rec['decoys']['flagged_full']}/7  "
                f"{'adv ' + str(round(adv_rec['friction_before'], 1)) + '->' + str(round(adv_rec['friction_after'], 1)) if adv_rec else ''}"
            )

    elapsed = time.perf_counter() - t_start
    data = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
        "seeds": SEEDS,
        "noise_levels": NOISE_LEVELS,
        "flag_cutoff": FLAG_CUTOFF,
        "neutral_anomaly": NEUTRAL_ANOMALY,
        "n_runs": len(runs),
        "elapsed_seconds": round(elapsed, 1),
        "failures": failures,
        "runs": runs,
        "adversary_runs": adv_runs,
        "aggregates": aggregate(runs, adv_runs),
    }

    DOCS.mkdir(exist_ok=True)
    with open(DOCS / "benchmark.json", "w") as f:
        json.dump(data, f, indent=2)
    with open(DOCS / "BENCHMARK.md", "w") as f:
        f.write(render_markdown(data))

    print(
        f"\n{len(runs)} runs in {elapsed:.0f}s -> docs/BENCHMARK.md, docs/benchmark.json"
    )
    if failures:
        print("FAILURES:")
        for f_ in failures:
            print(" -", f_)
    # leave no scratch data behind and keep config pointing at the real data
    config.DATA_DIR = config.BACKEND_DIR / "data"
    generate_data.NOISE = 1.0


if __name__ == "__main__":
    main()
