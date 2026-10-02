"""Shared configuration and data loading for the ShadowFlow engine."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

# Load .env from the backend folder if present (all keys optional; the
# defaults below are what the demo uses).
BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

DATA_DIR = BACKEND_DIR / "data"
PDF_EXPORT_DIR = DATA_DIR / "dossiers"
PDF_EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# --- Federation shared secret -------------------------------------------------
# In this prototype the salt is a "shared secret" agreed by all banks out of
# band. In a real system this would be managed by a key ceremony per bank pair.
FEDERATION_SALT: str = os.getenv("FEDERATION_SALT", "shadowflow-demo-salt-2026")
FEDERATION_SECRET: str = os.getenv("FEDERATION_SECRET", "shadowflow-demo-secret-2026")

# --- Detection thresholds -----------------------------------------------------
THRESHOLD = 10_000.0  # structuring reporting threshold
CYCLE_WINDOW_HOURS = 72  # temporal cycle window
CYCLE_MAX_LEN = 6  # max cycle length (bounded DFS)
CYCLE_MIN_RETENTION = 0.85  # min amount retention around the loop
CHAIN_MAX_DELAY_MIN = 120  # mule chain max delay per hop
CHAIN_MIN_FORWARD = 0.85  # mule chain min forward ratio per hop
SMURF_MIN_DEPOSITS = 10  # fan-in minimum deposit count
SMURF_WINDOW_DAYS = 7  # fan-in window
SMURF_JUST_BELOW = 0.995  # "just below" threshold band upper bound
SMURF_JUST_BELOW_MIN = 0.80  # "just below" band lower bound
BENIGN_MAX_TXN_COUNT = 5  # accounts with fewer txns are "thin-file"
BANKS = ["BankA", "BankB", "BankC"]


def load_transactions() -> pd.DataFrame:
    """Load and merge all bank CSVs, deduped by txn_id, sorted by time."""
    frames: list[pd.DataFrame] = []
    for csv in sorted(DATA_DIR.glob("transactions_*.csv")):
        frames.append(pd.read_csv(csv))
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=["txn_id"]).reset_index(drop=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def load_ground_truth() -> dict:
    """Load the injected ground truth rings."""
    import json

    with open(DATA_DIR / "ground_truth.json") as f:
        return json.load(f)
