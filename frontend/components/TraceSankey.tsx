"use client";

import { useMemo } from "react";
import * as d3sankey from "d3-sankey";
import { C, bankColor, taintColor } from "@/src/theme";
import type { TraceNode } from "@/lib/types";

/**
 * Sankey of the taint trace tree. Each hop becomes a link from the parent
 * hop's source account to the hop's destination, weighted by the dirty
 * amount that travelled. Node ids are suffixed with depth so ring cycles
 * remain a DAG for the layout.
 */
export default function TraceSankey({
  tree,
  height = 240,
}: {
  tree: TraceNode[];
  height?: number;
}) {
  const W = 760;

  const { nodes, links } = useMemo(() => {
    const nodeMap = new Map<
      string,
      { id: string; label: string; bank: string }
    >();
    const linkAgg = new Map<string, number>();

    const bankOf = (acct: string) =>
      acct.startsWith("Bank") ? acct.split("_")[0] : "BankA";

    for (const n of tree) {
      const srcNode = n.parent
        ? tree.find((p) => p.txn_id === n.parent)
        : undefined;
      const from = srcNode ? srcNode.dst : n.src;
      const to = n.dst;

      for (const [acct, depth] of [
        [from, n.depth - (srcNode ? 0 : 0)] as const,
        [to, n.depth] as const,
      ]) {
        const id = `${acct}@${depth}`;
        if (!nodeMap.has(id))
          nodeMap.set(id, { id, label: acct, bank: bankOf(acct) });
      }
      // for the root hop the source sits at depth -1 relative to dst
      if (!srcNode) {
        const sid = `${n.src}@${n.depth - 1}`;
        if (!nodeMap.has(sid))
          nodeMap.set(sid, { id: sid, label: n.src, bank: bankOf(n.src) });
      }
      const fromId = srcNode
        ? `${from}@${n.depth - 1}`
        : `${n.src}@${n.depth - 1}`;
      const toId = `${to}@${n.depth}`;
      const key = `${fromId}->${toId}`;
      linkAgg.set(key, (linkAgg.get(key) ?? 0) + n.taint_amount);
    }

    const nodes = [...nodeMap.values()].map((n) => ({ ...n }));
    const links = [...linkAgg.entries()].map(([key, value]) => {
      const [fromId, toId] = key.split("->");
      return { source: fromId, target: toId, value };
    });
    return { nodes, links };
  }, [tree]);

  const layout = useMemo(() => {
    if (!nodes.length || !links.length) return null;
    try {
      const gen = d3sankey
        .sankey()
        .nodeWidth(10)
        .nodePadding(16)
        .extent([
          [4, 6],
          [W - 4, height - 6],
        ]);
      const res = gen({
        nodes: nodes.map((n) => ({ ...n })),
        links: links.map((l) => ({ ...l })),
      } as any);
      return res;
    } catch {
      return null;
    }
  }, [nodes, links, height]);

  if (!layout)
    return (
      <div className="text-xxs text-ink-faint">
        Run a trace to see where the money ended up.
      </div>
    );

  const path = d3sankey.sankeyLinkHorizontal();
  const maxVal = Math.max(...links.map((l) => l.value), 1);

  return (
    <svg
      viewBox={`0 0 ${W} ${height}`}
      className="w-full"
      style={{ maxHeight: height }}
    >
      {layout.links.map((l: any, i: number) => {
        const frac = l.value / maxVal;
        return (
          <path
            key={i}
            d={path(l) ?? undefined}
            fill="none"
            stroke={taintColor(frac)}
            strokeOpacity={0.35 + frac * 0.5}
            strokeWidth={Math.max(1, l.width)}
          />
        );
      })}
      {layout.nodes.map((n: any, i: number) => (
        <g key={i}>
          <rect
            x={n.x0}
            y={n.y0}
            width={n.x1 - n.x0}
            height={Math.max(2, n.y1 - n.y0)}
            fill={bankColor(n.bank)}
            stroke={C.border}
            strokeWidth={0.5}
          />
          <text
            x={n.x0 < W / 2 ? n.x1 + 4 : n.x0 - 4}
            y={(n.y0 + n.y1) / 2 + 3}
            textAnchor={n.x0 < W / 2 ? "start" : "end"}
            fontSize="8"
            fontFamily="JetBrains Mono, monospace"
            fill={C.muted}
          >
            {(n.label as string).split("_")[1] ?? n.label}
          </text>
        </g>
      ))}
    </svg>
  );
}
