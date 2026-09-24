/** Interactive approval dependency graph (spec §11) — layered SVG with click
 * to inspect, pan/zoom-lite and state colours. */
import React, { useMemo, useState } from "react";
import { StatusBadge } from "./ui";

const STATE_FILL: Record<string, string> = {
  COMPLETED: "#10b981",
  APPROVED: "#10b981",
  READY: "#2dd4bf",
  SUBMITTED: "#3b82f6",
  QUERY_RAISED: "#f59e0b",
  WAITING: "#f59e0b",
  BLOCKED: "#ef4444",
  REJECTED: "#ef4444",
  NOT_STARTED: "#475569",
};

const CATEGORY_EMOJI: Record<string, string> = {
  BUSINESS: "🏢", LAND: "🗺️", ENVIRONMENT: "🌿", SAFETY: "🦺", LABOUR: "👷",
  INDUSTRY_SPECIFIC: "🏭", TAX: "🧾", UTILITIES: "⚡", TRADE: "🚢",
};

export default function ApprovalGraph({
  nodes,
  edges,
  onSelect,
  selected,
}: {
  nodes: any[];
  edges: { from: string; to: string }[];
  onSelect: (id: string) => void;
  selected?: string | null;
}) {
  const [hover, setHover] = useState<string | null>(null);

  const layout = useMemo(() => {
    const layers = new Map<number, any[]>();
    for (const n of nodes) {
      const arr = layers.get(n.layer) || [];
      arr.push(n);
      layers.set(n.layer, arr);
    }
    const layerKeys = [...layers.keys()].sort((a, b) => a - b);
    const positions = new Map<string, { x: number; y: number; n: any }>();
    const rowH = 108;
    const colW = 172;
    let maxRows = 0;
    layerKeys.forEach((layer, li) => {
      const row = layers.get(layer)!;
      maxRows = Math.max(maxRows, row.length);
      row.forEach((n, i) => {
        positions.set(n.id, { x: 110 + li * colW, y: 70 + i * rowH, n });
      });
    });
    const width = 120 + layerKeys.length * colW;
    const height = 120 + maxRows * rowH;
    return { positions, width, height };
  }, [nodes]);

  if (!nodes.length) {
    return <div className="p-8 text-center text-sm text-slate-500">Run the analysis to build the dependency graph.</div>;
  }

  return (
    <div className="overflow-auto rounded-2xl border border-white/8 bg-[radial-gradient(ellipse_at_top,rgba(37,99,235,0.06),transparent_60%)]">
      <svg width={layout.width} height={layout.height} className="min-w-full" role="img" aria-label="Approval dependency graph">
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#334155" />
          </marker>
        </defs>
        {/* edges */}
        {edges.map((e, i) => {
          const a = layout.positions.get(e.from);
          const b = layout.positions.get(e.to);
          if (!a || !b) return null;
          const x1 = a.x + 62, y1 = a.y + 18, x2 = b.x - 62, y2 = b.y + 18;
          const mx = (x1 + x2) / 2;
          const highlight = selected === e.from || selected === e.to || hover === e.from || hover === e.to;
          return (
            <path
              key={i}
              d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`}
              fill="none"
              stroke={highlight ? "#4aa8f0" : "#1e293b"}
              strokeWidth={highlight ? 2 : 1.4}
              markerEnd="url(#arrow)"
            />
          );
        })}
        {/* nodes */}
        {[...layout.positions.entries()].map(([id, p]) => {
          const isActive = selected === id || hover === id;
          const fill = STATE_FILL[p.n.state] || "#475569";
          const critical = p.n.is_on_critical_path;
          return (
            <g
              key={id}
              transform={`translate(${p.x - 62},${p.y})`}
              onClick={() => onSelect(id)}
              onMouseEnter={() => setHover(id)}
              onMouseLeave={() => setHover(null)}
              className="cursor-pointer"
              role="button"
              aria-label={p.n.name}
              tabIndex={0}
              onKeyDown={(e) => { if (e.key === "Enter") onSelect(id); }}
            >
              <rect
                width={124}
                height={36}
                rx={10}
                fill={isActive ? "rgba(37,99,235,0.16)" : "rgba(15,23,42,0.85)"}
                stroke={isActive ? "#4aa8f0" : critical ? "rgba(45,212,191,0.5)" : "rgba(255,255,255,0.1)"}
                strokeWidth={isActive ? 2 : 1}
              />
              <circle cx={14} cy={18} r={5} fill={fill} />
              <text x={26} y={16} fontSize={8.5} fill="#94a3b8" className="uppercase">
                {(p.n.category || "").slice(0, 10)}
              </text>
              <text x={26} y={27} fontSize={9} fill="#e2e8f0">
                {p.n.name.length > 24 ? p.n.name.slice(0, 23) + "…" : p.n.name}
              </text>
              {critical ? <circle cx={116} cy={9} r={3.4} fill="#2dd4bf" /> : null}
              {/* honesty markers from the enriched graph data (§17) */}
              {p.n.requires_verification ? (
                <text x={8} y={32} fontSize={7} fill="#f59e0b">⚠ verify</text>
              ) : null}
              {p.n.information_required && !p.n.requires_verification ? (
                <text x={8} y={32} fontSize={7} fill="#60a5fa">ℹ info needed</text>
              ) : null}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
