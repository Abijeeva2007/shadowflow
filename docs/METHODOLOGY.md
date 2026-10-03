# Methodology

How each part of ShadowFlow works, in plain language, and what its
assumptions are. All thresholds live in `backend/engine/config.py` and are
fixed for every run; nothing here is tuned per dataset.

## Order of operations

1. Load the payment logs and build a directed graph (one node per account,
   one edge per payment).
2. Fingerprint every account and clear the ones that look like ordinary
   business (the benign filter).
3. Run three pattern detectors over the remaining suspects.
4. Score what is left (pattern evidence + an Isolation Forest anomaly term).
5. Everything downstream - taint tracing, the adversary lab, federation, the
   dossier PDF - reads that one in-memory result.

## The benign filter

Each account gets a business-rhythm fingerprint: how regular the gaps between
its payments are, how steady its daily volume is, how many different
counterparties it has, how often it repeats the same counterparty, and what
share of inflow it passes straight out.

An account is cleared as benign when it has enough history (at least 5
payments), diverse counterparties (at least 5), a steady rhythm (daily volume
variation <= 0.8, or at least 30% repeat counterparties), and it is not a
pass-through: paying out more than 90% of what comes in *on one-shot
relationships* is mule-like, while high pass-through on recurring business
relationships (an employer funding salaries) is not.

On the seed-42 data this clears 1,185 of 1,635 accounts. Cleared accounts are
excluded from pattern search; the benchmark reports what the same detectors
find without this step (see [BENCHMARK](BENCHMARK.md)).

## Detector 1 - money cycles

Looks for closed loops in the graph: a path that returns to its origin
carrying at least 85% of the money within 72 hours, up to 6 hops, searched
with a bounded depth-first walk. A fee-taking wash trade retains less than
the bound, so the retention threshold is what separates a cycle from ordinary
round payments. Nested variants of the same loop are collapsed (one hit whose
account set is mostly contained in another counts once).

## Detector 2 - mule chains (pass-through)

Looks for rapid forwarding chains: each hop must pass on at least 85% of what
it received within 120 minutes. The middle accounts of a detected chain are
the mules; the first and last accounts get a smaller score contribution
because they can be an ordinary payer and payee.

## Detector 3 - smurfing

Looks for fan-in just under the reporting threshold: at least 10 deposits
into one collector within 7 days, each between 80% and 99.5% of 10,000, then
consolidation out. The structuring score is how close the deposits sit to the
threshold.

## Scoring

Account score = 0.6 x pattern evidence + 0.4 x Isolation Forest percentile
(both rescaled 0-100), plus written reasons a reviewer can read. The Isolation
Forest is fit on timing/velocity features (transaction counts, burst rate,
pass-through ratio, hold time, amount stats) of the accounts that reached the
detectors. Ring scores combine the best member score, mean member anomaly and
a type-specific bonus.

The benchmark ablates the Isolation Forest term; see
[BENCHMARK](BENCHMARK.md) for what changes.

## Taint tracing - the proportional assumption

Forward tracing uses the **proportional (poison) method**: every account has
a dirty pool and a clean pool; an incoming payment adds `taint x amount` to
the dirty pool; outgoing payments spend from both pools in proportion to
their shares. So if an account holds 20% dirty money, every payment out of it
carries 20% taint.

This is the standard first-order approximation and it is an assumption, not
fact: it ignores per-lot / FIFO accounting (in reality a specific batch of
dirty notes can be followed more precisely), and banks that mix funds in
different ways will diverge from it. The edge that delivered the dirty money
is excluded from the clean pool so dirty money cannot dilute itself. Output
is a tree capped by depth and a minimum-taint cut-off.

## The adversary lab and the Friction Score

The adversary searches a fixed grid of evasion schemes (about 32 combinations
over hop delay, splits, timing jitter, decoy accounts and number of banks)
and reports which ones the detectors catch.

The default report is computed once ahead of time into
`backend/data/adversary_default.json` (regenerate it with
`python precompute_adversary.py`) and the page loads that file, so opening
the Adversary Lab never starts a search. The "Run" button searches live with
your lever settings, capped at 4 schemes, one run at a time (a second run is
rejected with a "busy" message) and with a 20 second timeout. On the 0.1-CPU
free-tier host a live search needs longer than that, so the button reports
that the search is still running and the result shows up on the next load.
The benchmark in [BENCHMARK](BENCHMARK.md) still searches the full grid.

**The Friction Score (LFS) is a proxy defined in this project.** It is not an
industry metric. For a scheme it is

```
LFS = (2 x hop_delay_hours + 0.05 + 0.05 x decoys + 2 x fee_pct + extra_accounts)
      / the same terms for a naive one-hop transfer
```

so the naive scheme scores 1.0 and larger scores mean the evader must burn
more time, fees and mule accounts for the same result. Hardening reads the
cheapest scheme that got through, tightens the matching detector threshold,
and re-measures: across 10 benchmark runs the cheapest evasion rose from
2.98x to 8.93x (see [BENCHMARK](BENCHMARK.md)).

## Federation - what it does and does not protect

Each bank runs detection only on its own logs and shares the minimum: a salted
hash of the account id, the pattern type, a time window, a coarse amount
bucket and a direction. A coordinator stitches a joint case whenever hashed
ids from two or three banks line up. Revealing an account behind a hash needs
a (mock) authorisation step that is recorded.

What this protects in the demo:

- the coordinator never sees raw account ids, names or exact amounts;
- each bank's detector sees only its own customers;
- cross-bank rings become visible without pooling raw logs.

What it does **not** protect:

- the salt is one shared secret in the environment; anyone holding it can
  hash-guess ids from a small id space (this is not private set intersection
  or per-bank key material);
- amount buckets and time windows leak coarse structure;
- the authorisation step is a demo input field, not real access control;
- all three banks still run inside one process on one machine.

Treat it as a workflow demonstration of minimum-necessary sharing, not a
cryptography result.
