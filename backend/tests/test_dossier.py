"""Tests for the tamper-evident dossier hash chain and PDF export."""

from __future__ import annotations

import hashlib
import json

from engine.dossier import (
    build_evidence_chain,
    verify_evidence_chain,
)

RECORDS = [
    {"kind": "case", "ring_id": "CYCLE-01", "amount": 1000.0},
    {"kind": "txn", "txn_id": "TXN000001", "amount": 1000.0},
    {"kind": "txn", "txn_id": "TXN000002", "amount": 980.0},
    {"kind": "txn", "txn_id": "TXN000003", "amount": 950.0},
]


def test_chain_builds_with_prev_linkage():
    chain = build_evidence_chain(RECORDS)
    assert len(chain) == 4
    assert chain[0]["prev_hash"] == "0" * 64
    for i in range(1, len(chain)):
        assert chain[i]["prev_hash"] == chain[i - 1]["hash"]
    # hash 0 recomputes independently from its inputs (sha256 of canonical
    # json {"record":..., "prev":...}) - not just copied from the builder
    payload = json.dumps(
        {"record": RECORDS[0], "prev": "0" * 64}, sort_keys=True, separators=(",", ":")
    )
    assert chain[0]["hash"] == hashlib.sha256(payload.encode()).hexdigest()
    assert chain[0]["hash"] != chain[0]["prev_hash"]


def test_verify_valid_chain():
    chain = build_evidence_chain(RECORDS)
    res = verify_evidence_chain(chain)
    assert res["valid"] is True
    assert res["broken_at"] is None
    assert res["final_hash"] == chain[-1]["hash"]


def test_tampered_record_is_detected():
    chain = build_evidence_chain(RECORDS)
    # flip one number in record 2
    chain[2]["record"]["amount"] = 9.99
    res = verify_evidence_chain(chain)
    assert res["valid"] is False
    assert res["broken_at"] == 2


def test_removed_record_is_detected():
    chain = build_evidence_chain(RECORDS)
    del chain[1]  # evidence disappears...
    for i, link in enumerate(chain):  # ...and the culprit renumbers the rest
        link["seq"] = i
    res = verify_evidence_chain(chain)
    assert res["valid"] is False
    assert res["broken_at"] == 1


def test_empty_chain_is_trivially_valid():
    res = verify_evidence_chain(build_evidence_chain([]))
    assert res["valid"] is True
    assert res["final_hash"] == "0" * 64


def test_dossier_pdf_smoke():
    """Full export on a real ring: PDF bytes start with %PDF and chain matches."""
    from engine import pipeline

    st = pipeline.run_pipeline()
    ring = st.rings[0]
    from engine.dossier import export_pdf

    pdf, chain = export_pdf(ring, st.g, st.accounts, st.fingerprints)
    assert pdf[:4] == b"%PDF"
    # reportlab compresses streams, so a 2-page dossier is only a few KB -
    # this just checks the full section list rendered (a bare stub would be <1KB)
    assert len(pdf) > 4_000
    assert verify_evidence_chain(chain)["valid"] is True
