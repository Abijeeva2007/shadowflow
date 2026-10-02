"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import dagre from "cytoscape-dagre";
import { ZoomIn, ZoomOut, Maximize2 } from "lucide-react";
import { C, RISK, bankColor, taintColor, BANK_LIST, BANKS } from "@/src/theme";
import type { CyElement, RingGraph } from "@/lib/types";
import { fmtMoney } from "@/lib/api";

// register the dagre layout once
let dagreRegistered = false;
function registerDagre() {
  if (!dagreRegistered) {
    cytoscape.use(dagre);
    dagreRegistered = true;
  }
}

/** Map of txn_id -> hop delay label ("+12m") computed from time order. */
function delayLabels(elements: CyElement[]): Record<string, string> {
  const edges = elements.filter((e) => e.data.source);
  edges.sort((a, b) => a.data.time!.localeCompare(b.data.time!));
  // previous transaction that ARRIVED at this edge's source
  const lastArrival: Record<string, number> = {};
  const out: Record<string, string> = {};
  for (const e of edges) {
    const t = new Date(e.data.time!.replace(" ", "T")).getTime();
    const prev = lastArrival[e.data.source!];
    if (prev !== undefined) {
      const m = Math.round((t - prev) / 60000);
      out[e.data.id] = m >= 60 ? `+${(m / 60).toFixed(1)}h` : `+${m}m`;
    }
    lastArrival[e.data.source!] = t;
    lastArrival[e.data.target!] = t;
  }
  return out;
}

/**
 * Fan-shaped graphs (smurfing: one origin feeding dozens of parallel accounts)
 * read better top-to-bottom; chains and cycles keep the temporal
 * left-to-right flow. Detect fans by peak node degree.
 */
function isFanShape(elements: CyElement[]): boolean {
  const deg: Record<string, number> = {};
  for (const e of elements) {
    if (!e.data.source) continue;
    deg[e.data.source!] = (deg[e.data.source!] ?? 0) + 1;
    deg[e.data.target!] = (deg[e.data.target!] ?? 0) + 1;
  }
  return Math.max(0, ...Object.values(deg)) > 8;
}

interface Props {
  graph: RingGraph;
  /** txn ids reached by the time scrubber; null = all reached */
  visibleTxnIds: Set<string> | null;
  /** txn ids carrying traced taint */
  traceEdges: Set<string>;
  /** txn_id -> dirty fraction (trace overlay colour) */
  traceFractions: Record<string, number>;
  selectedEdgeId: string | null;
  onEdgeClick: (data: CyElement["data"] | null) => void;
  onNodeClick: (id: string) => void;
}

export default function RingGraph({
  graph,
  visibleTxnIds,
  traceEdges,
  traceFractions,
  selectedEdgeId,
  onEdgeClick,
  onNodeClick,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const handlers = useRef({ onEdgeClick, onNodeClick });
  handlers.current = { onEdgeClick, onNodeClick };
  const [hover, setHover] = useState<{
    id: string;
    x: number;
    y: number;
  } | null>(null);

  const delays = useMemo(() => delayLabels(graph.elements), [graph.elements]);
  const amounts = useMemo(
    () =>
      graph.elements
        .filter((e) => e.data.source)
        .map((e) => e.data.amount ?? 0),
    [graph.elements],
  );
  const amtMin = Math.min(...(amounts.length ? amounts : [0]));
  const amtMax = Math.max(...(amounts.length ? amounts : [1]));

  // ---- create graph once per ring ----------------------------------------
  useEffect(() => {
    if (!containerRef.current) return;
    registerDagre();
    const fan = isFanShape(graph.elements);
    const edgeLabel = (e: any) => {
      const amt = fmtMoney(e.data("amount"));
      const d = delays[e.data("id")];
      return d ? `${amt} ${d}` : amt;
    };
    const cy = cytoscape({
      container: containerRef.current,
      elements: graph.elements as ElementDefinition[],
      wheelSensitivity: 0.2,
      style: [
        {
          selector: "node",
          style: {
            label: (n: any) => n.id().split("_")[1] ?? n.id(),
            "font-family": "JetBrains Mono, monospace",
            "font-size": 8,
            color: C.text,
            "text-valign": "bottom",
            "text-margin-y": 5,
            "text-background-color": C.bg,
            "text-background-opacity": 1,
            "text-background-padding": "2px",
            "text-background-shape": "roundrectangle",
            width: fan
              ? "mapData(risk, 0, 100, 9, 16)"
              : "mapData(risk, 0, 100, 16, 34)",
            height: fan
              ? "mapData(risk, 0, 100, 9, 16)"
              : "mapData(risk, 0, 100, 16, 34)",
            "background-color": (n: any) => bankColor(n.data("bank")),
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            shape: (n: any): any => {
              const shapes: Record<string, string> = {
                BankA: "ellipse",
                BankB: "round-rectangle",
                BankC: "diamond",
              };
              return shapes[String(n.data("bank"))] ?? "ellipse";
            },
            "border-width": 1,
            "border-color": C.border,
          },
        },
        {
          selector: "node[roles]",
          style: {
            "border-width": 2.5,
            "border-color": (n: any) =>
              (n.data("roles") ?? []).includes("origin")
                ? RISK.amber
                : RISK.green,
          },
        },
        {
          selector: "edge",
          style: {
            width: (e: any) => {
              const a = e.data("amount") ?? 0;
              const f = (a - amtMin) / Math.max(amtMax - amtMin, 1);
              return 1.5 + f * 4.5;
            },
            "curve-style": "bezier",
            "line-color": "#3A4453",
            "target-arrow-color": "#3A4453",
            "arrow-scale": 0.9,
            "target-arrow-shape": "triangle",
            label: fan ? undefined : edgeLabel,
            "font-family": "JetBrains Mono, monospace",
            "font-size": 7,
            color: C.muted,
            "text-background-color": C.bg,
            "text-background-opacity": 1,
            "text-background-padding": "1px",
            "text-rotation": "autorotate",
            "source-text-offset": 0,
          },
        },
        {
          selector: "edge.unreached",
          style: { opacity: 0.14 },
        },
        {
          selector: "edge.traced",
          style: {
            label: edgeLabel,
            "line-color": (e: any) =>
              taintColor(traceFractions[e.data("id")] ?? 0),
            "target-arrow-color": (e: any) =>
              taintColor(traceFractions[e.data("id")] ?? 0),
            width: (e: any) => {
              const a = e.data("amount") ?? 0;
              const f = (a - amtMin) / Math.max(amtMax - amtMin, 1);
              return 2.5 + f * 4;
            },
            color: C.text,
            "font-size": 8,
            "z-index": 10,
          },
        },
        {
          selector: "edge.selected",
          style: {
            label: edgeLabel,
            "line-color": RISK.amber,
            "target-arrow-color": RISK.amber,
            color: RISK.amber,
            "z-index": 9,
          },
        },
        {
          selector: "node.dim",
          style: { opacity: 0.25 },
        },
      ],
      layout: {
        name: "dagre",
        rankDir: fan ? "TB" : "LR",
        rankSep: fan ? 55 : 70,
        nodeSep: fan ? 14 : 24,
        edgeSep: 12,
        padding: 24,
        animate: false,
      } as any,
    });

    cy.on("tap", "edge", (evt) =>
      handlers.current.onEdgeClick(evt.target.data()),
    );
    cy.on("tap", "node", (evt) =>
      handlers.current.onNodeClick(evt.target.id()),
    );
    cy.on("tap", (evt) => {
      if (evt.target === cy) handlers.current.onEdgeClick(null);
    });
    cy.on("mouseover", "node", (evt) => {
      const pos = evt.renderedPosition || evt.target.renderedPosition();
      setHover({ id: evt.target.id(), x: pos.x, y: pos.y });
    });
    cy.on("mouseout", "node", () => setHover(null));

    cyRef.current = cy;
    return () => {
      cy.destroy();
      cyRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph.ring_id]);

  // ---- time-scrub dimming (update classes, do not re-layout) --------------
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.batch(() => {
      cy.edges().forEach((e) => {
        const reached = !visibleTxnIds || visibleTxnIds.has(e.id());
        e.toggleClass("unreached", !reached);
      });
      cy.nodes().forEach((n) => {
        const reached =
          !visibleTxnIds ||
          n
            .connectedEdges()
            .some((e: any) => visibleTxnIds.has(String(e.id())));
        n.toggleClass("dim", !reached);
      });
    });
  }, [visibleTxnIds]);

  // ---- trace + selection overlays -----------------------------------------
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.batch(() => {
      cy.edges().forEach((e) => {
        e.toggleClass("traced", traceEdges.has(e.id()));
        e.toggleClass("selected", e.id() === selectedEdgeId);
      });
    });
  }, [traceEdges, selectedEdgeId]);

  const zoom = (f: number) => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.zoom({
      level: cy.zoom() * f,
      renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 },
    });
  };

  return (
    <div className="relative h-[430px]">
      <div ref={containerRef} className="absolute inset-0" />

      {/* hover tooltip with the full account id */}
      {hover && (
        <div
          className="absolute z-20 pointer-events-none chip border-ink-faint bg-ink-panel2 text-ink-text"
          style={{ left: hover.x + 14, top: hover.y - 10 }}
        >
          {hover.id}
        </div>
      )}

      {/* zoom / fit controls */}
      <div className="absolute top-2 right-2 flex flex-col gap-1 z-10">
        <button
          className="btn-ghost !h-7 !px-1.5"
          onClick={() => zoom(1.25)}
          aria-label="zoom in"
        >
          <ZoomIn size={13} />
        </button>
        <button
          className="btn-ghost !h-7 !px-1.5"
          onClick={() => zoom(0.8)}
          aria-label="zoom out"
        >
          <ZoomOut size={13} />
        </button>
        <button
          className="btn-ghost !h-7 !px-1.5"
          onClick={() => cyRef.current?.fit(undefined, 30)}
          aria-label="fit to view"
        >
          <Maximize2 size={13} />
        </button>
      </div>

      {/* legend */}
      <div className="absolute bottom-2 left-3 z-10 flex items-center gap-4 bg-ink-bg/85 border border-ink-border rounded px-2.5 py-1.5">
        {BANK_LIST.map((b) => (
          <span
            key={b}
            className="inline-flex items-center gap-1.5 text-xxs text-ink-muted"
          >
            <span
              className="inline-block w-2.5 h-2.5"
              style={{
                background: BANKS[b].color,
                borderRadius:
                  BANKS[b].shape === "round"
                    ? "50%"
                    : BANKS[b].shape === "square"
                      ? 1
                      : 0,
                transform:
                  BANKS[b].shape === "diamond"
                    ? "rotate(45deg) scale(0.8)"
                    : undefined,
              }}
            />
            {BANKS[b].label}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5 text-xxs text-ink-muted">
          <span
            className="inline-block w-2.5 h-2.5 rounded-full border-2"
            style={{ borderColor: RISK.amber }}
          />
          origin
        </span>
        <span className="inline-flex items-center gap-1.5 text-xxs text-ink-muted">
          <span
            className="inline-block w-2.5 h-2.5 rounded-full border-2"
            style={{ borderColor: RISK.green }}
          />
          final
        </span>
        <span className="text-xxs text-ink-faint">
          edge width = amount · label = amount + hop delay
        </span>
      </div>
    </div>
  );
}
