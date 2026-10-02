"""Case dossier PDF with a tamper-evident evidence hash chain.

Compliance case-file layout: a graphite header band on every page carries the
case ID and a "CONFIDENTIAL - SYNTHETIC DEMO DATA" line; the footer carries
page numbers and the short integrity hash. Sections: plain-language case
summary (templated from the data), the ring graph exhibit, key accounts
table, transaction timeline, velocity metrics, taint trace summary, why it
was flagged, and a hash-chained evidence appendix.

Tamper evidence: every evidence record's SHA-256 includes the previous
record's hash (a classic hash chain). The final chain hash is printed on the
first page and in every footer; GET /api/verify/{ring} recomputes the chain
from the stored records and compares.
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime

import networkx as nx
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    PageTemplate,
    Paragraph,
    Table,
    TableStyle,
)

from engine import taint
from engine import velocity as vel
from engine.graph import fmt_ts
from engine.ring_image import render_ring_png


# ------------------------------------------------------------------ hash chain
def _record_hash(record: dict, prev_hash: str) -> str:
    payload = json.dumps(
        {"record": record, "prev": prev_hash}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def build_evidence_chain(records: list[dict]) -> list[dict]:
    """Hash-chain the evidence records; each carries {hash, prev_hash, seq}."""
    chain: list[dict] = []
    prev = "0" * 64
    for i, rec in enumerate(records):
        h = _record_hash(rec, prev)
        chain.append({"seq": i, "record": rec, "prev_hash": prev, "hash": h})
        prev = h
    return chain


def verify_evidence_chain(chain: list[dict]) -> dict:
    """Recompute the chain and report whether it is intact."""
    prev = "0" * 64
    for i, link in enumerate(chain):
        expected = _record_hash(link["record"], prev)
        if link["prev_hash"] != prev or link["hash"] != expected or link["seq"] != i:
            return {
                "valid": False,
                "broken_at": i,
                "final_hash": chain[-1]["hash"] if chain else prev,
            }
        prev = expected
    return {
        "valid": True,
        "broken_at": None,
        "final_hash": chain[-1]["hash"] if chain else prev,
    }


def evidence_records(ring: dict, g: nx.MultiDiGraph) -> list[dict]:
    """Canonical evidence records for a ring (what the hash chain covers)."""
    by_key: dict[str, tuple] = {}
    for u, v, k, d in g.edges(keys=True, data=True):
        by_key[k] = (u, v, d)
    recs: list[dict] = []
    recs.append(
        {
            "kind": "case",
            "ring_id": ring["ring_id"],
            "type": ring["type"],
            "score": ring["score"],
            "accounts": ring["accounts"],
            "banks": ring["banks"],
            "amount": ring["amount"],
            "window": [ring["start"], ring["end"]],
        }
    )
    for tid in ring["hit"]["txn_ids"]:
        edge = by_key.get(tid)
        if edge is None:
            continue
        u, v, d = edge
        recs.append(
            {
                "kind": "txn",
                "txn_id": tid,
                "src": u,
                "dst": v,
                "amount": round(d["amount"], 2),
                "time": fmt_ts(d["timestamp"]),
                "channel": d["channel"],
            }
        )
    return recs


# ------------------------------------------------------------------- PDF build
# Palette (matches the dashboard theme)
INK = colors.HexColor("#E7E9EE")
GRAPHITE = colors.HexColor("#161A21")
PAPER = colors.white
BORDER = colors.HexColor("#232934")
MUTED = colors.HexColor("#8B93A3")
AMBER = colors.HexColor("#D29922")
RED = colors.HexColor("#C74E4E")
ROW_ALT = colors.HexColor("#F3F5F8")

_STYLES = getSampleStyleSheet()
_H1 = ParagraphStyle(
    "H1",
    parent=_STYLES["Title"],
    fontSize=17,
    spaceAfter=2,
    textColor=colors.HexColor("#0F1115"),
    alignment=0,
)
_META = ParagraphStyle(
    "Meta", parent=_STYLES["BodyText"], fontSize=8, textColor=MUTED, spaceAfter=6
)
_H2 = ParagraphStyle(
    "H2",
    parent=_STYLES["Heading2"],
    fontSize=11,
    spaceBefore=12,
    spaceAfter=4,
    textColor=colors.HexColor("#0F1115"),
)
_BODY = ParagraphStyle("Body", parent=_STYLES["BodyText"], fontSize=9, leading=13)
_MONO = ParagraphStyle("Mono", parent=_STYLES["Code"], fontSize=6.0, leading=8)
_NOTE = ParagraphStyle("Note", parent=_BODY, fontSize=7.5, textColor=MUTED)


def case_story(ring: dict, g: nx.MultiDiGraph) -> str:
    """Plain-language summary generated from the ring's actual data."""
    t = ring["type"]
    h = ring["hit"]
    banks = ", ".join(ring["banks"])
    start = datetime.strptime(ring["start"], "%Y-%m-%d %H:%M:%S")
    end = datetime.strptime(ring["end"], "%Y-%m-%d %H:%M:%S")
    days = (end - start).total_seconds() / 86400
    if t == "cycle":
        return (
            f"Between {start:%d %b %Y} and {end:%d %b %Y} ({days:.1f} days), "
            f"{len(ring['accounts'])} accounts at {banks} passed roughly "
            f"{ring['amount']:,.0f} around a closed loop: the money left the "
            f"first account, moved through {h['length']} intermediaries, "
            f"and returned to where it started, keeping "
            f"{h['retention']:.0%} of its value after fees. Round-tripping "
            f"money like this through several accounts is a classic way to "
            f"obscure where funds came from."
        )
    if t == "mule_chain":
        delays = h.get("hop_delays_min", [])
        fastest = min(delays) if delays else 0
        return (
            f"On {start:%d %b %Y}, {ring['amount']:,.0f} entered account "
            f"{h['origin']} and was forwarded through {h['length']} "
            f"accounts at {banks} within {fastest:.0f}-{max(delays):.0f} "
            f"minutes per hop, finishing at {h['terminal']} after "
            f"{h['total_delay_min']:.0f} minutes with {h['retention']:.0%} "
            f"of the funds remaining. Accounts that receive and immediately "
            f"forward nearly all of the money they receive are typical of "
            f"money-mule networks."
        )
    dep = h.get("n_deposits", 0)
    return (
        f"Between {start:%d %b %Y} and {end:%d %b %Y}, {h['n_contributors']} "
        f"different accounts made {dep} cash deposits of just under 10,000 "
        f"each into one collector account, totalling {ring['amount']:,.0f} "
        f"across {banks}. "
        + (
            f"About {h['structuring_score']:.0%} of the deposits sat just "
            f"below the 10,000 reporting threshold, and "
            f"{h.get('consolidation_amount', 0):,.0f} was then wired out in "
            f"one go to {h.get('consolidation_to', 'a downstream account')}. "
            if h.get("structuring_score")
            else ""
        )
        + "Splitting large sums into many small deposits to dodge reporting "
        "rules is known as structuring or smurfing."
    )


def _table_style(n_rows: int) -> TableStyle:
    cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), GRAPHITE),
        ("TEXTCOLOR", (0, 0), (-1, 0), INK),
        ("FONTSIZE", (0, 0), (-1, -1), 7.2),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]
    for r in range(2, n_rows, 2):
        cmds.append(("BACKGROUND", (0, r), (-1, r), ROW_ALT))
    return TableStyle(cmds)


def build_dossier_pdf(
    ring: dict,
    g: nx.MultiDiGraph,
    accounts: dict,
    fingerprints: dict,
    chain: list[dict],
    trace: dict | None = None,
) -> bytes:
    """Render the dossier PDF for a ring; returns the PDF bytes."""
    buf = io.BytesIO()
    final_hash = chain[-1]["hash"] if chain else "N/A"
    short_hash = final_hash[:12]
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        title=f"ShadowFlow case {ring['ring_id']}",
        author="ShadowFlow (synthetic demo)",
    )
    M = 1.5 * cm
    frame = Frame(M, 1.9 * cm, A4[0] - 2 * M, A4[1] - 3.4 * cm, id="main")

    def header_footer(canvas, doc_):
        canvas.saveState()
        w, hgt = A4
        # ---- header band ----
        band_h = 1.35 * cm if doc_.page == 1 else 0.95 * cm
        canvas.setFillColor(GRAPHITE)
        canvas.rect(0, hgt - band_h, w, band_h, stroke=0, fill=1)
        canvas.setFillColor(AMBER)
        canvas.rect(0, hgt - band_h - 2, w, 2, stroke=0, fill=1)
        canvas.setFillColor(INK)
        canvas.setFont("Helvetica-Bold", 12 if doc_.page == 1 else 9)
        canvas.drawString(
            M,
            hgt - band_h + (0.42 if doc_.page == 1 else 0.28) * cm,
            f"CASE {ring['ring_id']}",
        )
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#9AA3B2"))
        canvas.drawRightString(
            w - M,
            hgt - band_h + 0.30 * cm,
            "CONFIDENTIAL - SYNTHETIC DEMO DATA, NOT A REAL INVESTIGATION",
        )
        if doc_.page == 1:
            canvas.drawString(
                M,
                hgt - band_h + 0.12 * cm,
                f"{ring['type'].replace('_', ' ').upper()} - RISK {ring['score']:.0f}/100 - "
                f"{len(ring['accounts'])} ACCOUNTS - {', '.join(ring['banks'])}",
            )
        # ---- footer ----
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 6.5)
        canvas.drawString(M, 1.05 * cm, f"integrity sha256:{short_hash}...")
        canvas.drawRightString(w - M, 1.05 * cm, f"Page {doc_.page}")
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(M, 1.35 * cm, w - M, 1.35 * cm)
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=header_footer)])
    story: list = []

    # ---- cover / case summary -------------------------------------------
    story.append(Paragraph("Case summary", _H1))
    story.append(
        Paragraph(
            f"Window {ring['start']} to {ring['end']} - amount {ring['amount']:,.2f} - "
            f"generated from the transaction graph, not hand-written.",
            _META,
        )
    )
    story.append(Paragraph(case_story(ring, g), _BODY))
    story.append(
        Paragraph(
            f"<b>Evidence chain (SHA-256, full):</b> <font size=6.5>{final_hash}</font>",
            _BODY,
        )
    )

    # ---- exhibit: ring graph ----------------------------------------------
    story.append(Paragraph("Exhibit A - flow of funds", _H2))
    png = render_ring_png(ring, g)
    if png:
        img = Image(io.BytesIO(png))
        ratio = img.imageWidth / img.imageHeight
        img.drawWidth = 16.6 * cm
        img.drawHeight = 16.6 * cm / ratio
        img.hAlign = "LEFT"
        story.append(img)
        story.append(
            Paragraph(
                "Node shape and colour mark the bank; arrows show direction; "
                "labels show amounts in thousands; left-to-right is time order.",
                _NOTE,
            )
        )
    else:
        story.append(Paragraph("(no flow graph available for this case)", _NOTE))

    # ---- key accounts ----------------------------------------------------
    story.append(Paragraph("Key accounts", _H2))
    rows = [["Account", "Bank", "Risk", "Burst/h", "Pass-through", "Note"]]
    for a in ring["accounts"][:10]:
        rec = accounts.get(a, {})
        v = rec.get("velocity", {})
        fp = fingerprints.get(a, {})
        rows.append(
            [
                a,
                g.nodes[a].get("bank", "?"),
                f"{rec.get('score', '-')}",
                f"{v.get('peak_burst_rate', '-')}",
                (
                    f"{v['pass_through_ratio']:.0%}"
                    if isinstance(v.get("pass_through_ratio"), (int, float))
                    else "-"
                ),
                (fp.get("note", "") or "")[:38],
            ]
        )
    tbl = Table(
        rows, colWidths=[3.1 * cm, 1.6 * cm, 1.3 * cm, 2.6 * cm, 2.2 * cm, 5.6 * cm]
    )
    tbl.setStyle(_table_style(len(rows)))
    story.append(tbl)

    # ---- timeline ---------------------------------------------------------
    story.append(Paragraph("Timeline of transactions", _H2))
    tl_rows = [["Time", "From -> To", "Amount", "Channel"]]
    txns_sorted = _ring_txns(ring, g)
    for u, v, k, d in txns_sorted[:35]:
        tl_rows.append(
            [fmt_ts(d["timestamp"]), f"{u} -> {v}", f"{d['amount']:,.2f}", d["channel"]]
        )
    if len(txns_sorted) > 35:
        tl_rows.append(
            [f"... {len(txns_sorted) - 35} more in evidence appendix", "", "", ""]
        )
    tbl2 = Table(tl_rows, colWidths=[3.2 * cm, 8.2 * cm, 2.6 * cm, 2.4 * cm])
    tbl2.setStyle(_table_style(len(tl_rows)))
    story.append(tbl2)

    # ---- velocity ---------------------------------------------------------
    story.append(Paragraph("Velocity metrics", _H2))
    vrows = [
        ["Account", "Txns/hour", "Peak burst", "Median hold (min)", "Pass-through"]
    ]
    for a in ring["accounts"][:10]:
        v = vel.velocity_features(g, a)
        hold = v["median_hold_min"]
        vrows.append(
            [
                a,
                f"{v['txns_per_hour']:.2f}",
                f"{v['peak_burst_rate']:.0f}",
                f"{hold:.0f}" if hold >= 0 else "n/a",
                f"{v['pass_through_ratio']:.0%}",
            ]
        )
    tbl3 = Table(vrows, colWidths=[4.6 * cm, 2.8 * cm, 2.6 * cm, 3.4 * cm, 3.0 * cm])
    tbl3.setStyle(_table_style(len(vrows)))
    story.append(tbl3)

    # ---- taint ------------------------------------------------------------
    story.append(Paragraph("Taint trace summary", _H2))
    if trace:
        story.append(
            Paragraph(
                f"Tracing the first flagged transaction forward: "
                f"{trace['total_traced']:,.2f} of dirty money moved across "
                f"{trace['n_hops']} hops. It ended up at: "
                + ", ".join(
                    f"{a} ({v:,.0f})" for a, v in list(trace["terminals"].items())[:5]
                )
                + ".",
                _BODY,
            )
        )
    else:
        story.append(Paragraph("No taint trace was run for this export.", _BODY))

    # ---- why flagged --------------------------------------------------------
    story.append(Paragraph("Why it was flagged", _H2))
    for a in ring["accounts"][:6]:
        rec = accounts.get(a, {})
        for r in rec.get("reasons", [])[:2]:
            story.append(Paragraph(f"- {a}: {r}", _BODY))

    # ---- evidence appendix ---------------------------------------------------
    story.append(Paragraph("Evidence appendix (hash-chained records)", _H2))
    story.append(
        Paragraph(
            "Each line is SHA-256(record || previous hash). Recompute via "
            "GET /api/verify/" + ring["ring_id"],
            _NOTE,
        )
    )
    for link in chain:
        story.append(
            Paragraph(
                f"{link['seq']:03d}  {link['hash'][:16]}...  "
                f"{json.dumps(link['record'], sort_keys=True)[:110]}",
                _MONO,
            )
        )

    doc.build(story)
    return buf.getvalue()


def _ring_txns(ring: dict, g: nx.MultiDiGraph) -> list[tuple]:
    out: list[tuple] = []
    wanted = set(ring["hit"]["txn_ids"])
    for u, v, k, d in g.edges(keys=True, data=True):
        if k in wanted:
            out.append((u, v, k, d))
    out.sort(key=lambda e: e[3]["timestamp"])
    return out


def export_pdf(
    ring: dict,
    g: nx.MultiDiGraph,
    accounts: dict,
    fingerprints: dict,
    trace_depth: int = 4,
) -> tuple[bytes, list[dict]]:
    """Full export: build evidence chain + PDF. Returns (pdf_bytes, chain)."""
    recs = evidence_records(ring, g)
    chain = build_evidence_chain(recs)
    # attach a taint trace for the first ring txn
    trace = None
    if ring["hit"]["txn_ids"]:
        try:
            t = taint.trace_taint(
                g=g,
                txn_id=ring["hit"]["txn_ids"][0],
                max_depth=trace_depth,
                min_taint=100.0,
            )
            trace = t.summary()
        except Exception:
            trace = None
    pdf = build_dossier_pdf(ring, g, accounts, fingerprints, chain, trace)
    return pdf, chain
