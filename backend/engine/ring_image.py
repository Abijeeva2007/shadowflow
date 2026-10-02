"""Ring graph image for the dossier PDF (matplotlib, dashboard palette)."""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")  # headless; must run before pyplot import
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import networkx as nx

from engine.graph import fmt_ts

# Same palette the web dashboard uses (graphite + muted banks + amber/red).
BG = "#0F1115"
PANEL = "#161A21"
BORDER = "#232934"
TEXT = "#E7E9EE"
MUTED = "#8B93A3"
BANK_COLORS = {"BankA": "#5B7C99", "BankB": "#7A6A54", "BankC": "#5E7D5A"}
RISK = "#D29922"  # amber
CRIT = "#C74E4E"  # red

SHAPES = {"BankA": "o", "BankB": "s", "BankC": "D"}


def render_ring_png(ring: dict, g: nx.MultiDiGraph, max_px: int = 1400) -> bytes:
    """Left-to-right temporal layout of the ring; returns PNG bytes."""
    wanted = set(ring["hit"]["txn_ids"])
    edges = [
        (u, v, k, d) for u, v, k, d in g.edges(keys=True, data=True) if k in wanted
    ]
    nodes: list[str] = []
    for u, v, _, _ in edges:
        for a in (u, v):
            if a not in nodes:
                nodes.append(a)
    if not nodes:
        return b""

    # ---- temporal layering (left = earliest) --------------------------------
    times = {
        a: min(d["timestamp"] for u, v, k, d in edges if a in (u, v)) for a in nodes
    }
    order = sorted(nodes, key=lambda a: times[a])
    pos: dict[str, tuple[float, float]] = {}
    layer = 0
    for i, a in enumerate(order):
        if i > 0 and times[a] > times[order[i - 1]]:
            layer += 1
        # fan out vertically within the same timestamp bucket
        same = [b for j, b in enumerate(order) if times[b] == times[a] and j < i]
        y = 0.0
        if same:
            y = (len(same) + 1) / 2 * (0.55 if i % 2 else -0.55)
        pos[a] = (layer, y)

    fig, ax = plt.subplots(figsize=(7.2, 3.2), dpi=200)
    fig.patch.set_facecolor(PANEL)
    ax.set_facecolor(PANEL)

    # ---- edges (arrows + amount labels) ------------------------------------
    for u, v, k, d in edges:
        (x0, y0), (x1, y1) = pos[u], pos[v]
        ax.annotate(
            "",
            xy=(x1, y1),
            xytext=(x0, y0),
            arrowprops=dict(
                arrowstyle="-|>", color=MUTED, lw=1.1, shrinkA=14, shrinkB=14
            ),
        )
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        ax.text(
            mx,
            my + 0.18,
            f"{d['amount']/1000:,.1f}k",
            ha="center",
            va="bottom",
            fontsize=5.6,
            color=TEXT,
        )

    # ---- nodes (shape by bank, size by degree-in-ring, ring outline origin) --
    for a in nodes:
        bank = g.nodes[a].get("bank", "?")
        x, y = pos[a]
        deg = sum(1 for u, v, _, _ in edges if a in (u, v))
        size = 220 + 60 * min(deg, 4)
        ax.scatter(
            [x],
            [y],
            s=size,
            c=BANK_COLORS.get(bank, MUTED),
            marker=SHAPES.get(bank, "o"),
            zorder=3,
            edgecolors=RISK,
            linewidths=1.0,
        )
        ax.text(x, y - 0.42, a, ha="center", va="top", fontsize=5.2, color=TEXT)
        short = a.split("_", 1)[-1]
        ax.text(
            x,
            y,
            short,
            ha="center",
            va="center",
            fontsize=4.8,
            color="#0F1115",
            weight="bold",
            zorder=4,
        )

    ax.set_xticks(sorted({p[0] for p in pos.values()}))
    ax.set_xticklabels(
        [fmt_ts(times[a]) for a in order[: len({p[0] for p in pos.values()})]],
        fontsize=4.5,
        color=MUTED,
    )
    ax.tick_params(colors=BORDER, length=0)
    for s in ax.spines.values():
        s.set_color(BORDER)
    ax.set_yticks([])
    for t in ax.get_xticklabels():
        t.set_color(MUTED)
    ax.margins(0.12, 0.28)

    legend = [
        mpatches.Patch(color=BANK_COLORS[b], label=b) for b in sorted(BANK_COLORS)
    ]
    ax.legend(
        handles=legend,
        loc="upper right",
        fontsize=4.5,
        facecolor=PANEL,
        edgecolor=BORDER,
        labelcolor=TEXT,
    )

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=PANEL, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
