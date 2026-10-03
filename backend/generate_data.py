"""ShadowFlow synthetic data generator.

Creates ~1200 benign accounts (~400 per bank) across BankA/BankB/BankC and
~60k transactions over 90 days, then injects three families of laundering
patterns and records every one in data/ground_truth.json:

1. Circular wash routes      - money returns to the origin within 48h, minus a fee.
2. Rapid pass-through chains - each hop forwards 90-98% within 1-90 minutes.
3. Smurfing rings            - a large sum split into 15-40 deposits just under
                               10,000 from many accounts into one collector,
                               then consolidated and moved out.

Benign noise: payroll, shop payments, rent, utilities, P2P, inter-bank moves,
and employer revenue deposits. Six decoys look suspicious but are benign: the
original three (busy shop, big payroll, landlord) plus three "pattern mimics"
that imitate each crime family (a festival-cash collector, a gig-eco mule, a
festival-organiser loop) with harder numbers than the crimes themselves.

HARDENED DATA (deliberately harder for the detectors):
  - hop delays and amounts get jitter everywhere (rings are not on rails);
  - some ring hops are "hidden" (delay collapsed to 0-2 minutes, like one
    batch transfer seen as two edges) so a single detector pass can miss them;
  - ring accounts also lead normal lives (salaries, shopping, rent) so the
    benign filter has to weigh real evidence rather than traffic volume.

Run:  python generate_data.py
Output: data/transactions_BankA.csv, transactions_BankB.csv,
        transactions_BankC.csv, ground_truth.json

Cross-bank transactions appear in both banks' CSV files (like two subpoenas
returning overlapping logs); the detection engine dedupes by txn_id.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SEED = 42
# Benign traffic volume multiplier used by the benchmark (low/medium/high).
# 1.0 is the committed default and reproduces the seed-42 dataset exactly;
# only background benign volume scales - injected rings and decoys do not.
NOISE = 1.0
START = datetime(2026, 1, 1)  # 90-day window: 2026-01-01 .. 2026-03-31
DAYS = 90
BANKS = ["BankA", "BankB", "BankC"]
ACCOUNTS_PER_BANK = 400
SUB_THRESHOLD = 10_000.0

DATA_DIR = Path(__file__).parent / "data"

rng = random.Random(SEED)
nprng = np.random.default_rng(SEED)

_txn_counter = [0]
ground_truth: dict[str, list[dict[str, Any]]] = {
    "cycles": [],
    "mule_chains": [],
    "smurfing": [],
    "decoys": [],
}
_all_txn_rows: list[dict[str, Any]] = []
_all_accounts: dict[str, dict[str, str]] = {}
_ring_members: dict[str, str] = {}  # account -> ring_id (for normal-life traffic)


def _next_txn_id() -> str:
    _txn_counter[0] += 1
    return f"TXN{_txn_counter[0]:06d}"


def add_account(acc_id: str, bank: str, kind: str) -> None:
    _all_accounts[acc_id] = {"bank": bank, "kind": kind}


def account(bank: str, kind: str) -> str:
    """Create a fresh unique account id at `bank`."""
    i = len(_all_accounts) + 1
    acc = f"{bank}_{i:04d}"
    while acc in _all_accounts:
        i += 1
        acc = f"{bank}_{i:04d}"
    add_account(acc, bank, kind)
    return acc


def add_txn(
    timestamp: datetime,
    src: str,
    dst: str,
    amount: float,
    channel: str,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one transaction to the ledger. `meta` marks crime-ring hops."""
    row = {
        "txn_id": _next_txn_id(),
        "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "src_account": src,
        "dst_account": dst,
        "amount": round(amount, 2),
        "bank_src": _all_accounts[src]["bank"],
        "bank_dst": _all_accounts[dst]["bank"],
        "channel": channel,
    }
    _all_txn_rows.append(row)
    if meta is not None:
        row["pattern_meta"] = meta
    return row


def bank_of(acc: str) -> str:
    return _all_accounts[acc]["bank"]


def fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _jitter_time(ts: datetime, jitter_min: float) -> datetime:
    """Symmetric time jitter (rings are not on rails)."""
    return ts + timedelta(minutes=float(nprng.uniform(-jitter_min, jitter_min)))


def _mix_amount(amount: float, mix: float) -> float:
    """Multiplicative amount jitter (mix=0.05 -> +/-5%)."""
    return amount * float(nprng.uniform(1.0 - mix, 1.0 + mix))


def _noise(k: int) -> int:
    """Scale a benign-volume count by NOISE (identity when NOISE == 1.0)."""
    if NOISE == 1.0:
        return k
    return max(1, int(round(k * NOISE)))


# ------------------------------------------------------------------ benign world
def build_benign_world() -> dict[str, list[str]]:
    """Create accounts and benign background traffic; return the persons pool."""
    persons_of: dict[str, list[str]] = {}

    for bank in BANKS:
        hq = account(bank, "hq")
        # 1 HQ + 8 employers + 25 shops + 6 landlords + 3 utilities = 43,
        # so persons = 400 - 43 = 357 and total accounts per bank = 400.
        n_persons = ACCOUNTS_PER_BANK - 43
        persons = [account(bank, "person") for _ in range(n_persons)]
        persons_of[bank] = persons
        employers = [account(bank, "employer") for _ in range(8)]
        shops = [account(bank, "shop") for _ in range(25)]
        landlords = [account(bank, "landlord") for _ in range(6)]
        utilities = [account(bank, "utility") for _ in range(3)]

        # --- payroll: 8 employers x 30-70 employees x 3 monthly runs --------
        for emp in employers:
            n_emp = int(nprng.integers(30, 70))
            employees = rng.sample(persons, k=min(_noise(n_emp), len(persons)))
            pay_day = int(nprng.integers(1, 28))
            salary = float(nprng.uniform(2500, 4100))
            revenue_paid = 0.0
            for month in range(3):
                day = pay_day + 30 * month
                if day >= DAYS:
                    break
                d = START + timedelta(days=day)
                ts = d.replace(
                    hour=int(nprng.integers(9, 11)), minute=int(nprng.integers(0, 59))
                )
                for e in employees:
                    amt = salary * float(nprng.uniform(0.9, 1.1))
                    add_txn(
                        ts + timedelta(minutes=int(nprng.integers(0, 240))),
                        emp,
                        e,
                        amt,
                        "payroll",
                    )
                    revenue_paid += amt
                # employer receives matching revenue from HQ each month
                add_txn(ts - timedelta(hours=2), hq, emp, revenue_paid, "wire")

        # --- shops: 25 per bank, steady daily custom -------------------------
        for shop in shops:
            daily = int(nprng.integers(2, 12))
            popularity = float(nprng.uniform(0.4, 1.5))
            for day in range(DAYS):
                n_today = max(0, int(nprng.poisson(daily * popularity * NOISE)))
                d = START + timedelta(days=day)
                for _ in range(n_today):
                    cust = persons[int(nprng.integers(0, len(persons)))]
                    ts = d + timedelta(minutes=int(nprng.integers(8 * 60, 22 * 60)))
                    amt = min(float(nprng.lognormal(3.2, 0.9)), 4000.0)
                    channel = rng.choices(
                        ["card", "transfer", "cash", "wire"],
                        weights=[0.5, 0.3, 0.15, 0.05],
                    )[0]
                    add_txn(ts, cust, shop, amt, channel)

        # --- rent: 6 landlords x 4-12 tenants, monthly ------------------------
        for landlord in landlords:
            n_tenants = int(nprng.integers(4, 12))
            rent_day = int(nprng.integers(1, 6))
            for _t in range(_noise(n_tenants)):
                tenant = persons[int(nprng.integers(0, len(persons)))]
                amt = float(nprng.uniform(700, 2200))
                for month in range(3):
                    day = rent_day + 30 * month
                    if day >= DAYS:
                        continue
                    d = START + timedelta(days=day)
                    ts = d.replace(hour=10, minute=int(nprng.integers(0, 50)))
                    add_txn(ts, tenant, landlord, amt, "transfer")

        # --- utilities: 3 per bank, small steady payments ---------------------
        for util in utilities:
            for day in range(DAYS):
                d = START + timedelta(days=day)
                for _k in range(_noise(int(nprng.integers(5, 15)))):
                    payer = persons[int(nprng.integers(0, len(persons)))]
                    ts = d + timedelta(minutes=int(nprng.integers(7 * 60, 23 * 60)))
                    amt = float(nprng.uniform(40, 260))
                    add_txn(ts, payer, util, amt, "transfer")

        # --- P2P: 40 sparse pairs ---------------------------------------------
        for _k in range(40):
            a, b = rng.sample(persons, 2)
            for day in range(DAYS):
                if nprng.random() < 0.25 * NOISE:
                    d = START + timedelta(days=day)
                    ts = d + timedelta(minutes=int(nprng.integers(6 * 60, 24 * 60)))
                    amt = min(float(nprng.lognormal(4.0, 1.0)), 5000.0)
                    add_txn(ts, a, b, amt, "transfer")

        # --- employers also pay business expenses to shops occasionally -------
        for emp in employers:
            for _k in range(_noise(30)):
                shop = shops[int(nprng.integers(0, len(shops)))]
                day = int(nprng.integers(0, DAYS))
                d = START + timedelta(days=day)
                ts = d + timedelta(minutes=int(nprng.integers(9 * 60, 18 * 60)))
                add_txn(ts, emp, shop, float(nprng.uniform(100, 1500)), "card")

    # --- interbank: people moving money between their own accounts ----------
    for _k in range(_noise(80)):
        b1, b2 = rng.sample(BANKS, 2)
        a = persons_of[b1][int(nprng.integers(0, len(persons_of[b1])))]
        b = persons_of[b2][int(nprng.integers(0, len(persons_of[b2])))]
        for day in range(0, DAYS, 11):
            d = START + timedelta(days=day)
            ts = d + timedelta(minutes=int(nprng.integers(9 * 60, 18 * 60)))
            add_txn(ts, a, b, float(nprng.uniform(200, 3000)), "wire")

    return persons_of


# ----------------------------------------------------------------------- decoys
def add_decoys(persons_of: dict[str, list[str]]) -> None:
    """Six accounts that look suspicious but are completely benign.

    The first three are volume outliers. The last three deliberately imitate
    each crime pattern (with numbers that are often *harder* than the real
    rings) but on ordinary, recurring relationships.
    """
    decoys: list[dict[str, Any]] = []

    # 1) A very busy shop: huge fan-in of small diverse payments.
    busy_shop = account("BankA", "shop")
    persons_a = persons_of["BankA"]
    for day in range(DAYS):
        d = START + timedelta(days=day)
        for _k in range(int(nprng.integers(60, 90))):
            cust = persons_a[int(nprng.integers(0, len(persons_a)))]
            ts = d + timedelta(minutes=int(nprng.integers(7 * 60, 23 * 60)))
            amt = min(float(nprng.lognormal(3.4, 1.0)), 5000.0)
            add_txn(ts, cust, busy_shop, amt, "card")
    decoys.append(
        {
            "account": busy_shop,
            "label": "busy_shop",
            "looks_like": "high fan-in, many small deposits",
            "is_criminal": False,
        }
    )

    # 2) A large payroll account paying 150 employees on a strict schedule.
    big_payroll = account("BankB", "employer")
    employees = [account("BankB", "person") for _ in range(150)]
    hq_b = account("BankB", "hq")
    for month in range(3):
        for pay_day in (1, 25):
            day = pay_day + 30 * month
            d = START + timedelta(days=day)
            revenue = 0.0
            ts = d.replace(hour=9, minute=int(nprng.integers(0, 59)))
            for e in employees:
                amt = float(nprng.uniform(1800, 3200))
                add_txn(
                    ts + timedelta(minutes=int(nprng.integers(0, 120))),
                    big_payroll,
                    e,
                    amt,
                    "payroll",
                )
                revenue += amt
            # revenue deposit so the employer has defined inflow
            add_txn(ts - timedelta(hours=3), hq_b, big_payroll, revenue, "wire")
    decoys.append(
        {
            "account": big_payroll,
            "label": "big_payroll",
            "looks_like": "large fan-out on a schedule",
            "is_criminal": False,
        }
    )

    # 3) A landlord with 40 tenants paying similar rent on the 1st.
    super_landlord = account("BankC", "landlord")
    for _t in range(40):
        tenant = account("BankC", "person")
        amt = float(nprng.uniform(900, 1400))
        for month in range(3):
            day = 1 + 30 * month
            d = START + timedelta(days=day)
            ts = d.replace(hour=12, minute=int(nprng.integers(0, 59)))
            add_txn(ts, tenant, super_landlord, amt, "transfer")
    decoys.append(
        {
            "account": super_landlord,
            "label": "super_landlord",
            "looks_like": "fan-in of similar amounts on one day",
            "is_criminal": False,
        }
    )

    # ---------------------------------------------------------------- mimics
    # 4) Festival-cash collector: fans 20 x 9,300 in within 3 days - structuring
    #    numbers - but the money goes straight back out to the same organisers
    #    (recurring, disclosed float; a petty-cash festival kitty, not smurfing).
    fest = account("BankA", "event_organiser")
    organisers = [account("BankA", "person") for _ in range(8)]
    for k in range(20):
        payer = organisers[k % len(organisers)]
        ts = START + timedelta(
            days=40 + (k % 3), hours=9 + (k % 12), minutes=int(nprng.integers(0, 59))
        )
        add_txn(ts, payer, fest, SUB_THRESHOLD * 0.93, "cash")
    # float returned to the same organisers afterwards (recurring relationship)
    for m, org in enumerate(organisers[:4]):
        ts = START + timedelta(days=44 + m, hours=10)
        add_txn(ts, fest, org, float(nprng.uniform(16_000, 22_000)), "wire")
    decoys.append(
        {
            "account": fest,
            "label": "festival_cash_kitty",
            "looks_like": "many sub-threshold cash deposits in one window",
            "is_criminal": False,
        }
    )

    # 5) Gig-eco payout float: a wage-float account for a marketplace platform.
    #    Receives one big top-up, instantly forwards ~95% to a payout partner -
    #    pass-through numbers - but on ONE recurring relationship every day.
    gig = account("BankB", "platform_float")
    payout_partner = account("BankC", "payout_partner")
    for day in range(DAYS):
        d = START + timedelta(days=day)
        top_up = float(nprng.uniform(18_000, 26_000))
        add_txn(
            d.replace(hour=8, minute=int(nprng.integers(0, 40))),
            persons_of["BankA"][day % len(persons_of["BankA"])],
            gig,
            top_up,
            "wire",
        )
        # payouts later that day (recurring partner -> benign business rhythm)
        for _p in range(int(nprng.integers(1, 4))):
            add_txn(
                d.replace(
                    hour=int(nprng.integers(10, 21)), minute=int(nprng.integers(0, 59))
                ),
                gig,
                payout_partner,
                top_up * float(nprng.uniform(0.88, 0.97)),
                "wire",
            )
    decoys.append(
        {
            "account": gig,
            "label": "gig_eco_payout_float",
            "looks_like": "high pass-through, near-90% forward ratio",
            "is_criminal": False,
        }
    )

    # 6) Seasonal festival organiser loop: a real closed money loop with better
    #    retention than the actual cycles - but recurring venue/supplier
    #    relationships that repeat every month (a business, not a wash trade).
    loop_a = account("BankA", "venue_operator")
    loop_b = account("BankC", "event_supplier")
    for month, day0 in enumerate((10, 40, 70)):
        amt = float(nprng.uniform(28_000, 34_000))
        t0 = START + timedelta(days=day0, hours=9)
        add_txn(t0, loop_a, loop_b, amt, "wire")
        # supplier pays venues and staff, then settles back with the organiser
        add_txn(
            t0 + timedelta(hours=int(nprng.integers(20, 40))),
            loop_b,
            loop_a,
            amt * float(nprng.uniform(0.92, 0.98)),
            "wire",
        )
    decoys.append(
        {
            "account": loop_a,
            "label": "seasonal_event_loop",
            "looks_like": "closed money loop with high retention",
            "is_criminal": False,
        }
    )
    decoys.append(
        {
            "account": loop_b,
            "label": "seasonal_event_loop_supplier",
            "looks_like": "closed money loop with high retention",
            "is_criminal": False,
        }
    )

    ground_truth["decoys"] = decoys


# ------------------------------------------------------- injected crime rings
def inject_cycles(n_rings: int = 5) -> None:
    """Circular wash routes: money returns to origin within 48h minus a fee."""
    for r in range(n_rings):
        size = int(nprng.integers(3, 7))  # 3..6 accounts
        home_bank = nprng.choice(BANKS)
        accounts = [account(home_bank, "mule")]
        for _ in range(size - 1):
            # 80% same bank, else another bank (so at least one hop crosses)
            b = home_bank if nprng.random() < 0.8 else nprng.choice(BANKS)
            accounts.append(account(b, "mule"))
        for a in accounts:
            _ring_members[a] = f"CYC{r + 1}"
        origin = accounts[0]
        start_day = int(nprng.integers(5, DAYS - 3))
        start = START + timedelta(days=start_day, hours=int(nprng.integers(6, 20)))
        amount0 = float(nprng.uniform(30_000, 90_000))
        fee_rate = float(nprng.uniform(0.005, 0.02))

        txns: list[dict[str, Any]] = []
        amt = amount0
        loop = accounts + [origin]  # close the loop back to the origin
        # Sample hop delays so the TOTAL stays under 46h without clamping
        # (clamping would make several hops share a timestamp).
        delays: list[int] = []
        while True:
            delays = [int(nprng.integers(20, 24 * 60)) for _ in range(len(loop) - 1)]
            if sum(delays) <= 46 * 60:
                break
        elapsed_min = 0.0
        for i in range(len(loop) - 1):
            # jitter each delay, but a few hops "hide" by collapsing to 0-2 min
            hidden = nprng.random() < 0.18
            d_min = (
                float(nprng.uniform(0, 2))
                if hidden
                else max(0.0, delays[i] * float(nprng.uniform(0.7, 1.3)))
            )
            elapsed_min += d_min
            amt = _mix_amount(amt * (1 - fee_rate), 0.04)
            ts = _jitter_time(start + timedelta(minutes=elapsed_min), 3)
            txns.append(
                add_txn(
                    ts,
                    loop[i],
                    loop[i + 1],
                    amt,
                    "wire",
                    meta={"ring_id": f"CYC{r + 1}", "hop": i},
                )
            )
        ground_truth["cycles"].append(
            {
                "ring_id": f"CYC{r + 1}",
                "type": "cycle",
                "accounts": accounts,
                "origin": origin,
                "amount_injected": round(amount0, 2),
                "fee_rate": round(fee_rate, 4),
                "start": fmt(start),
                "end": txns[-1]["timestamp"],
                "txn_ids": [t["txn_id"] for t in txns],
            }
        )


def inject_mule_chains(n_chains: int = 5) -> None:
    """Rapid pass-through chains: 4-7 accounts, 90-98% forwarded in 1-90 min."""
    for c in range(n_chains):
        length = int(nprng.integers(4, 8))
        cross = nprng.random() < 0.6
        accounts: list[str] = []
        for i in range(length):
            if i == 0:
                b = nprng.choice(BANKS)
            elif cross and i % 2 == 1:
                b = BANKS[(BANKS.index(bank_of(accounts[i - 1])) + 1) % 3]
            else:
                b = (
                    bank_of(accounts[i - 1])
                    if nprng.random() < 0.6
                    else nprng.choice(BANKS)
                )
            accounts.append(account(b, "mule"))
        for a in accounts:
            _ring_members[a] = f"MULE{c + 1}"
        start_day = int(nprng.integers(5, DAYS - 2))
        start = START + timedelta(
            days=start_day,
            hours=int(nprng.integers(8, 21)),
            minutes=int(nprng.integers(0, 59)),
        )
        amount = float(nprng.uniform(40_000, 120_000))

        txns = []
        amt = amount
        elapsed_min = 0.0
        for i in range(length - 1):
            forward = float(nprng.uniform(0.90, 0.98))
            # jittered hop delay; a few hops "hide" at 0-2 minutes
            hidden = nprng.random() < 0.18
            delay = (
                float(nprng.uniform(0, 2)) if hidden else float(nprng.integers(1, 91))
            )
            elapsed_min += delay
            amt = _mix_amount(amt * forward, 0.03)
            ts = _jitter_time(start + timedelta(minutes=elapsed_min), 2)
            txns.append(
                add_txn(
                    ts,
                    accounts[i],
                    accounts[i + 1],
                    amt,
                    "wire",
                    meta={"ring_id": f"MULE{c + 1}", "hop": i},
                )
            )
        ground_truth["mule_chains"].append(
            {
                "ring_id": f"MULE{c + 1}",
                "type": "mule_chain",
                "accounts": accounts,
                "origin": accounts[0],
                "terminal": accounts[-1],
                "amount_injected": round(amount, 2),
                "start": fmt(start),
                "end": txns[-1]["timestamp"],
                "txn_ids": [t["txn_id"] for t in txns],
            }
        )


def inject_smurfing(n_cases: int = 5) -> None:
    """One big sum split into sub-threshold deposits, then consolidated out."""
    for s in range(n_cases):
        collector = account(nprng.choice(BANKS), "collector")
        n_splits = int(nprng.integers(15, 41))  # 15..40 deposits
        # Each deposit is deliberately just under the reporting threshold;
        # the total laundered sum emerges from the number of splits.
        spread_days = int(nprng.integers(2, 6))
        start_day = int(nprng.integers(5, DAYS - spread_days - 2))
        day0 = START + timedelta(days=start_day)

        deposits = []
        depositors: list[str] = []
        total = 0.0
        for _k in range(n_splits):
            depositor = account(nprng.choice(BANKS), "smurf")
            depositors.append(depositor)
            _ring_members[depositor] = f"SMRF{s + 1}"
            ts = day0 + timedelta(
                hours=float(nprng.uniform(0, spread_days * 24)),
                minutes=int(nprng.integers(0, 60)),
            )
            ts = ts.replace(hour=int(nprng.integers(9, 22)))
            amt = SUB_THRESHOLD * float(nprng.uniform(0.85, 0.995))
            total += amt
            deposits.append(
                add_txn(
                    ts,
                    depositor,
                    collector,
                    amt,
                    "cash",
                    meta={"ring_id": f"SMRF{s + 1}", "hop": _k},
                )
            )
        _ring_members[collector] = f"SMRF{s + 1}"

        last_ts = max(
            datetime.strptime(d["timestamp"], "%Y-%m-%d %H:%M:%S") for d in deposits
        )
        mule1 = account(nprng.choice(BANKS), "mule")
        mule2 = account(nprng.choice(BANKS), "mule")
        _ring_members[mule1] = f"SMRF{s + 1}"
        _ring_members[mule2] = f"SMRF{s + 1}"
        consolidated = total * float(nprng.uniform(0.93, 0.99))
        t_out1 = last_ts + timedelta(hours=int(nprng.integers(6, 30)))
        t1 = add_txn(
            t_out1,
            collector,
            mule1,
            consolidated * 0.6,
            "wire",
            meta={"ring_id": f"SMRF{s + 1}", "hop": n_splits},
        )
        t2 = add_txn(
            t_out1 + timedelta(hours=int(nprng.integers(1, 20))),
            mule1,
            mule2,
            consolidated * 0.58,
            "wire",
            meta={"ring_id": f"SMRF{s + 1}", "hop": n_splits + 1},
        )
        ground_truth["smurfing"].append(
            {
                "ring_id": f"SMRF{s + 1}",
                "type": "smurfing",
                "collector": collector,
                "depositors": depositors,
                "exits": [mule1, mule2],
                "total_amount": round(total, 2),
                "n_deposits": n_splits,
                "start": deposits[0]["timestamp"],
                "end": t2["timestamp"],
                "txn_ids": [d["txn_id"] for d in deposits]
                + [t1["txn_id"], t2["txn_id"]],
            }
        )


# ------------------------------------------------------ ring accounts live on
def give_ring_accounts_normal_lives() -> None:
    """Ring accounts also do ordinary things: salaries in, shopping out.

    Without this the benign filter could trivially separate rings by traffic
    volume alone. Roughly 2/3 of ring members get 2-6 ordinary transactions.
    """
    persons_by_bank: dict[str, list[str]] = {}
    for acc_id, info in _all_accounts.items():
        if info["kind"] == "person":
            persons_by_bank.setdefault(info["bank"], []).append(acc_id)

    n_added = 0
    for acc, _ring in sorted(_ring_members.items()):
        if nprng.random() > 0.66:
            continue
        bank = _all_accounts[acc]["bank"]
        persons = persons_by_bank.get(bank) or persons_by_bank["BankA"]
        ring_txn_times = [
            datetime.strptime(r["timestamp"], "%Y-%m-%d %H:%M:%S")
            for r in _all_txn_rows
            if r["src_account"] == acc or r["dst_account"] == acc
        ]
        base = min(ring_txn_times) if ring_txn_times else START
        for _k in range(int(nprng.integers(2, 7))):
            # salaries, shopping, rent - within +/-30 days of the ring activity
            ts = base + timedelta(
                days=float(nprng.uniform(-20, 30)),
                hours=int(nprng.integers(7, 23)),
                minutes=int(nprng.integers(0, 59)),
            )
            ts = min(max(ts, START), START + timedelta(days=DAYS - 1))
            kind = int(nprng.integers(0, 3))
            if kind == 0:  # salary in
                src = persons[int(nprng.integers(0, len(persons)))]
                add_txn(ts, src, acc, float(nprng.uniform(900, 3200)), "payroll")
            elif kind == 1:  # shopping out
                dst = persons[int(nprng.integers(0, len(persons)))]
                add_txn(
                    ts, acc, dst, min(float(nprng.lognormal(3.0, 0.8)), 2000.0), "card"
                )
            else:  # rent
                dst = persons[int(nprng.integers(0, len(persons)))]
                add_txn(ts, acc, dst, float(nprng.uniform(600, 1500)), "transfer")
            n_added += 1
    print(f"ring-account normal-life txns added: {n_added}")


# ------------------------------------------------------------------------ main
def main(seed: int | None = None, out_dir: Path | None = None) -> None:
    """Generate the dataset; defaults reproduce the committed seed-42 data.

    `seed` and `out_dir` let the benchmark regenerate other seeds into a
    scratch directory without touching data/. Module state is reset so main()
    is safe to call repeatedly within one process.
    """
    global rng, nprng, DATA_DIR
    if seed is None:
        seed = SEED
    rng = random.Random(seed)
    nprng = np.random.default_rng(seed)
    _txn_counter[0] = 0
    ground_truth.clear()
    ground_truth.update({"cycles": [], "mule_chains": [], "smurfing": [], "decoys": []})
    _all_txn_rows.clear()
    _all_accounts.clear()
    _ring_members.clear()
    if out_dir is not None:
        DATA_DIR = out_dir
    persons_of = build_benign_world()
    add_decoys(persons_of)
    inject_cycles(5)
    inject_mule_chains(5)
    inject_smurfing(5)
    give_ring_accounts_normal_lives()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for bank in BANKS:
        rows = [
            r for r in _all_txn_rows if r["bank_src"] == bank or r["bank_dst"] == bank
        ]
        # Strip pattern_meta: the ground-truth labels must NOT ship inside the
        # transaction logs the detector reads (that would be cheating).
        df = pd.DataFrame(rows).drop(columns=["pattern_meta"], errors="ignore")
        df.to_csv(DATA_DIR / f"transactions_{bank}.csv", index=False)
        print(f"{bank}: {len(df)} txns")

    with open(DATA_DIR / "ground_truth.json", "w") as f:
        json.dump(ground_truth, f, indent=2)

    n_crime = sum(
        len(g["txn_ids"])
        for k in ("cycles", "mule_chains", "smurfing")
        for g in ground_truth[k]
    )
    print(f"total txns: {len(_all_txn_rows)}, accounts: {len(_all_accounts)}")
    print(
        f"rings: cycles={len(ground_truth['cycles'])}, "
        f"mule_chains={len(ground_truth['mule_chains'])}, "
        f"smurfing={len(ground_truth['smurfing'])}, "
        f"decoys={len(ground_truth['decoys'])}, criminal txns={n_crime}"
    )


if __name__ == "__main__":
    main()
