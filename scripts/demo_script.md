# ShadowFlow — 3-Minute Demo Script

**Before the demo:** `make data && make run` (backend :8000, frontend :3000). Wait for backend warmup (~15 s — `curl localhost:8000/api/health`). Open a browser tab on http://localhost:3000 and keep a spare tab ready for the dossier PDF (http://localhost:8000/api/rings/SMURF-01/dossier.pdf). Numbers below are the seed-42 run; yours will match because the seed is fixed.

---

### 0:00–0:20 — Raw noisy graph

Open the **Overview** page. Point at the KPI cards: **70,021 transactions, 1,635 accounts, 3 banks over 90 days** — and somewhere in there, hidden laundering networks.

> "Three banks' logs, seventy thousand payments. Somewhere in this haystack are 15 laundering networks. This is the haystack."

### 0:20–0:50 — Benign filter shrinks the haystack

On the same page: **alerts 1,635 → 450** — the "business rhythm fingerprint" cleared 1,185 accounts (steady salaries, shops, rent, bills) with only **2 false alarms** on the seven decoys we planted (a busy shop, a big payroll, a landlord, a festival cash kitty, a payout float, two seasonal-event loops — all look suspicious; five clear, and the two event loops are flagged because they are structurally identical to wash cycles).

> "Every account gets a rhythm fingerprint: who they pay, how regular, how much passes through. Normal business gets cleared — 72% of accounts drop out. We even planted benign look-alikes: most clear, the two that don't are genuinely indistinguishable from the real thing."

### 0:50–1:20 — Three ring types light up

Click **Rings** in the nav — 13 flagged rings (of 15 injected), sortable by score. Then open any **CYCLE-01** case (or the top-scored one).

> "The suspects go through three detectors: closed loops that return the money within 72 hours, mule chains forwarding ≥85% within 2 minutes per hop, and smurfing — many sub-threshold deposits into one collector. **13 of 15 injected rings found; F1 is 0.67 for cycles, 0.89 for mule chains, 1.00 for smurfing — measured against ground truth, no detector tuning.**"

### 1:20–2:10 — Case view: replay, then trace a deposit forward

In the case view:

1. Press **Play** on the time slider — edges appear in time order; the money in/out step chart below shows funds pooling and passing through. Click a node for risk reasons and velocity.
2. Click any edge → the taint trace runs instantly: edges light up along the forward path with **"% dirty" fraction labels**, following how funds mix and dilute as they hop through accounts.

> "The slider replays the story in time order. Now watch the money itself: proportional taint — when dirty and clean funds mix in an account, outgoing payments carry the dirty share. The labels show the poison diluting hop by hop."

### 2:10–2:40 — Adversary Lab: the detector gets harder to beat

Open **Adversary Lab**. Hit **Run** — the laundering agent tries 33 schemes against the detector (delays, splits, jitter, decoys, more banks). The scatter shows the evasion frontier; the baseline scheme is caught.

Then show **hardening**: Friction Score **2.98× → 8.93×** the naive scheme's cost.

> "We turned the detector against itself: the agent searches for the cheapest evasion. Then we harden the thresholds — shorter chain window, stricter retention — and the cheapest way out jumps from roughly 3× to 9× the naive cost. The detector gets better because it met an adversary."

### 2:40–3:00 — Export the dossier, verify the evidence

Back on the case page: **Export dossier** (PDF downloads; also at http://localhost:8000/api/rings/SMURF-01/dossier.pdf). Show the hash on page 1, then **Verify integrity** — `chain_valid: true`. 

> "The dossier is a plain-language case file with an evidence hash chain — flip one number and verification breaks. That's the deliverable an investigator would hand over."

---

**If you only have 90 seconds:** Overview (numbers) → a case view (replay + trace) → dossier export + verify.

**Live-try fallbacks:** Rings page has sortable type badges; Federation page shows the hashed investigator view with a mock reveal (type an officer name, 3+ chars). If the backend is still warming up, pages show loading/error banners with the exact command to start it.
