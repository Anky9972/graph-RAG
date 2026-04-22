import { useEffect, useRef, forwardRef, useImperativeHandle, useState } from 'react';
import * as d3 from 'd3';
import { X, Tag, FileText, Database } from 'lucide-react';

// 12-color categorical palette for node types
const TYPE_COLORS = [
  '#e63946', '#457b9d', '#2a9d8f', '#e9c46a', '#f4a261',
  '#6a4c93', '#1982c4', '#8ac926', '#ff595e', '#6a994e',
  '#bc4749', '#a8dadc'
];

export interface GraphOptions {
  colorByType: boolean;
  showLabels: boolean;
  showEdgeLabels: boolean;
  nodeRadius: number;
  linkDistance: number;
  chargeStrength: number;
  showCurvedEdges: boolean;
  nodeSizeByDegree: boolean;
  centerGravity: number;       // 0 = no gravity, 0.1 = default
}

export const DEFAULT_OPTIONS: GraphOptions = {
  colorByType: true,
  showLabels: true,
  showEdgeLabels: false,
  nodeRadius: 16,
  linkDistance: 120,
  chargeStrength: -300,
  showCurvedEdges: false,
  nodeSizeByDegree: false,
  centerGravity: 0.05,
};

interface GraphCanvasProps {
  data: { nodes: any[]; edges: any[] };
  onNodeUpdate?: (nodeId: string, newName: string) => void;
  options?: GraphOptions;
  highlightNodeIds?: Set<string>;  // nodes to highlight (from search)
}

export interface GraphCanvasHandle {
  exportPNG: () => void;
  exportSVG: () => void;
  fitView: () => void;
  highlightNode: (id: string) => void;
}

const GraphCanvas = forwardRef<GraphCanvasHandle, GraphCanvasProps>(
  ({ data, onNodeUpdate, options = DEFAULT_OPTIONS, highlightNodeIds }, ref) => {
    const [activeNode, setActiveNode] = useState<any>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const svgRef = useRef<SVGSVGElement>(null);
    const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);
    const gRef = useRef<d3.Selection<SVGGElement, unknown, null, undefined> | null>(null);
    const simulationRef = useRef<d3.Simulation<any, any> | null>(null);
    const typeColorMap = useRef<Map<string, string>>(new Map());

    // ── Imperative API ─────────────────────────────────────────────────────
    useImperativeHandle(ref, () => ({
      exportPNG() {
        if (!svgRef.current) return;
        const svgEl = svgRef.current;
        const serializer = new XMLSerializer();
        const svgStr = serializer.serializeToString(svgEl);
        const canvas = document.createElement('canvas');
        canvas.width = svgEl.clientWidth * 2;
        canvas.height = svgEl.clientHeight * 2;
        const ctx = canvas.getContext('2d')!;
        const img = new Image();
        const blob = new Blob([svgStr], { type: 'image/svg+xml;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        img.onload = () => {
          ctx.fillStyle = '#fff';
          ctx.fillRect(0, 0, canvas.width, canvas.height);
          ctx.scale(2, 2);
          ctx.drawImage(img, 0, 0);
          URL.revokeObjectURL(url);
          const a = document.createElement('a');
          a.download = 'graph.png';
          a.href = canvas.toDataURL('image/png');
          a.click();
        };
        img.src = url;
      },
      exportSVG() {
        if (!svgRef.current) return;
        const serializer = new XMLSerializer();
        const svgStr = serializer.serializeToString(svgRef.current);
        const blob = new Blob([svgStr], { type: 'image/svg+xml;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.download = 'graph.svg';
        a.href = url;
        a.click();
        URL.revokeObjectURL(url);
      },
      fitView() {
        if (!svgRef.current || !zoomRef.current) return;
        d3.select(svgRef.current).transition().duration(600).call(
          zoomRef.current.transform, d3.zoomIdentity
        );
      },
      highlightNode(id: string) {
        if (!svgRef.current || !zoomRef.current) return;
        const node = simulationRef.current?.nodes().find((n: any) => n.id === id);
        if (!node || node.x === undefined) return;
        const svg = d3.select(svgRef.current);
        const w = svgRef.current.clientWidth;
        const h = svgRef.current.clientHeight;
        const t = d3.zoomIdentity.translate(w / 2 - node.x, h / 2 - node.y);
        svg.transition().duration(700).call(zoomRef.current.transform, t);
      }
    }));

    // ── Main D3 render effect ──────────────────────────────────────────────
    useEffect(() => {
      if (!data.nodes.length || !containerRef.current || !svgRef.current) return;

      const width = containerRef.current.clientWidth;
      const height = containerRef.current.clientHeight;

      // Build type→color map (stable)
      const types = [...new Set(data.nodes.map(n => n.type || 'Unknown'))];
      types.forEach((t, i) => {
        if (!typeColorMap.current.has(t)) {
          typeColorMap.current.set(t, TYPE_COLORS[i % TYPE_COLORS.length]);
        }
      });

      const svg = d3.select(svgRef.current);
      svg.selectAll('*').remove();

      const nodes: any[] = data.nodes.map(d => ({ ...d }));
      const nodeIds = new Set(nodes.map(n => n.id));
      const links: any[] = data.edges
        .filter(d => nodeIds.has(d.source) && nodeIds.has(d.target))
        .map(d => ({ ...d }));

      // Degree map for node-size-by-degree
      const degreeMap = new Map<string, number>();
      nodes.forEach(n => degreeMap.set(n.id, 0));
      links.forEach(l => {
        const sid = typeof l.source === 'object' ? l.source.id : l.source;
        const tid = typeof l.target === 'object' ? l.target.id : l.target;
        degreeMap.set(sid, (degreeMap.get(sid) || 0) + 1);
        degreeMap.set(tid, (degreeMap.get(tid) || 0) + 1);
      });
      const maxDegree = Math.max(1, ...degreeMap.values());

      const nodeR = (d: any) => {
        if (!options.nodeSizeByDegree) return options.nodeRadius;
        const deg = degreeMap.get(d.id) || 0;
        return Math.max(8, options.nodeRadius * (0.5 + 1.0 * (deg / maxDegree)));
      };

      // ── Defs: arrowhead markers ──────────────────────────────────────────
      const defs = svg.append('defs');
      if (options.colorByType) {
        types.forEach(t => {
          const color = typeColorMap.current.get(t) || '#000';
          defs.append('marker')
            .attr('id', `arrow-${t.replace(/\s+/g, '_')}`)
            .attr('viewBox', '-0 -5 10 10').attr('refX', options.nodeRadius + 10)
            .attr('refY', 0).attr('orient', 'auto')
            .attr('markerWidth', 6).attr('markerHeight', 6)
            .append('path').attr('d', 'M 0,-5 L 10,0 L 0,5').attr('fill', color);
        });
      } else {
        defs.append('marker')
          .attr('id', 'arrow-default')
          .attr('viewBox', '-0 -5 10 10').attr('refX', options.nodeRadius + 10)
          .attr('refY', 0).attr('orient', 'auto')
          .attr('markerWidth', 6).attr('markerHeight', 6)
          .append('path').attr('d', 'M 0,-5 L 10,0 L 0,5').attr('fill', '#666');
      }

      // ── Force simulation ──────────────────────────────────────────────────
      const sim = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(links).id((d: any) => d.id).distance(options.linkDistance))
        .force('charge', d3.forceManyBody().strength(options.chargeStrength))
        .force('center', d3.forceCenter(width / 2, height / 2).strength(options.centerGravity))
        .force('collide', d3.forceCollide().radius((d: any) => nodeR(d) + 14));

      simulationRef.current = sim;

      const g = svg.append('g').attr('class', 'graph-root');
      gRef.current = g;

      // ── Tooltip ───────────────────────────────────────────────────────────
      const tooltip = d3.select(containerRef.current)
        .selectAll('.graph-tooltip').data([null]).join('div')
        .attr('class', 'graph-tooltip')
        .style('position', 'absolute')
        .style('pointer-events', 'none')
        .style('background', '#000')
        .style('color', '#fff')
        .style('padding', '6px 12px')
        .style('font-family', '"JetBrains Mono", monospace')
        .style('font-size', '11px')
        .style('line-height', '1.5')
        .style('opacity', 0)
        .style('border', '1px solid #333')
        .style('z-index', '999')
        .style('max-width', '220px')
        .style('word-break', 'break-word');

      // ── Links ────────────────────────────────────────────────────────────
      const linkG = g.append('g').attr('class', 'links');

      // Adjacency set for hover highlight
      const adjacentIds = new Set<string>();

      // Straight lines or curved paths
      const linkEl = options.showCurvedEdges
        ? linkG.selectAll('path').data(links).enter().append('path')
            .attr('fill', 'none')
            .attr('stroke', (d: any) => {
              if (!options.colorByType) return '#aaa';
              const srcNode = nodes.find(n => n.id === (typeof d.source === 'object' ? d.source.id : d.source));
              return srcNode ? (typeColorMap.current.get(srcNode.type) || '#aaa') : '#aaa';
            })
            .attr('stroke-width', 1.5)
            .attr('stroke-opacity', 0.55)
            .attr('marker-end', (d: any) => {
              if (!options.colorByType) return 'url(#arrow-default)';
              const srcNode = nodes.find(n => n.id === (typeof d.source === 'object' ? d.source.id : d.source));
              const t = srcNode?.type?.replace(/\s+/g, '_') || 'Unknown';
              return `url(#arrow-${t})`;
            })
        : linkG.selectAll('line').data(links).enter().append('line')
            .attr('stroke', (d: any) => {
              if (!options.colorByType) return '#aaa';
              const srcNode = nodes.find(n => n.id === (typeof d.source === 'object' ? d.source.id : d.source));
              return srcNode ? (typeColorMap.current.get(srcNode.type) || '#aaa') : '#aaa';
            })
            .attr('stroke-width', 1.5)
            .attr('stroke-opacity', 0.55)
            .attr('marker-end', (d: any) => {
              if (!options.colorByType) return 'url(#arrow-default)';
              const srcNode = nodes.find(n => n.id === (typeof d.source === 'object' ? d.source.id : d.source));
              const t = srcNode?.type?.replace(/\s+/g, '_') || 'Unknown';
              return `url(#arrow-${t})`;
            });

      // ── Nodes ─────────────────────────────────────────────────────────────
      const node = g.append('g').attr('class', 'nodes')
        .selectAll<SVGGElement, any>('g').data(nodes).enter().append('g')
        .call(d3.drag<SVGGElement, any>()
          .on('start', (event, d) => { if (!event.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
          .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y; })
          .on('end', (event, d) => { if (!event.active) sim.alphaTarget(0); d.fx = null; d.fy = null; })
        )
        .on('mouseover', (_, d: any) => {
          // Build adjacent set
          adjacentIds.clear();
          adjacentIds.add(d.id);
          links.forEach(l => {
            const sid = typeof l.source === 'object' ? l.source.id : l.source;
            const tid = typeof l.target === 'object' ? l.target.id : l.target;
            if (sid === d.id) adjacentIds.add(tid);
            if (tid === d.id) adjacentIds.add(sid);
          });
          // Dim non-adjacent
          node.select('circle')
            .style('opacity', (n: any) => adjacentIds.has(n.id) ? 1 : 0.15)
            .style('stroke-width', (n: any) => n.id === d.id ? 4 : 2);
          (linkEl as any)
            .style('stroke-opacity', (l: any) => {
              const sid = typeof l.source === 'object' ? l.source.id : l.source;
              const tid = typeof l.target === 'object' ? l.target.id : l.target;
              return (sid === d.id || tid === d.id) ? 0.9 : 0.04;
            });
          tooltip
            .style('opacity', 1)
            .html(`<strong>${d.label}</strong><br/>ID: ${d.id}<br/>Type: ${d.type || '—'}<br/>Degree: ${degreeMap.get(d.id) || 0}`);
        })
        .on('mousemove', (event) => {
          const rect = containerRef.current!.getBoundingClientRect();
          tooltip
            .style('left', (event.clientX - rect.left + 14) + 'px')
            .style('top', (event.clientY - rect.top - 32) + 'px');
        })
        .on('mouseout', () => {
          adjacentIds.clear();
          node.select('circle')
            .style('opacity', (n: any) => {
              if (!highlightNodeIds || highlightNodeIds.size === 0) return 1;
              return highlightNodeIds.has(n.id) ? 1 : 0.2;
            })
            .style('stroke-width', (n: any) => highlightNodeIds?.has(n.id) ? 4 : 2);
          (linkEl as any).style('stroke-opacity', 0.55);
          tooltip.style('opacity', 0);
        })
        .on('click', (event, d: any) => {
          setActiveNode(d);
          // Zoom to node on single click
          if (!svgRef.current || !zoomRef.current) return;
          const w = svgRef.current.clientWidth;
          const h = svgRef.current.clientHeight;
          const t = d3.zoomIdentity.translate(w / 2 - d.x, h / 2 - d.y).scale(1.4);
          d3.select(svgRef.current).transition().duration(500).call(zoomRef.current.transform, t);
          event.stopPropagation();
        })
        .on('dblclick', (event, d: any) => {
          const newName = window.prompt('Update entity name:', d.label);
          if (newName && newName.trim() && newName.trim() !== d.label) {
            const updated = newName.trim();
            d.label = updated;
            d3.select(event.currentTarget).select('text.node-label').text(
              updated.length > 18 ? updated.substring(0, 16) + '…' : updated
            );
            if (onNodeUpdate) onNodeUpdate(d.id, updated);
          }
        });

      // Circle
      node.append('circle')
        .attr('r', (d: any) => nodeR(d))
        .attr('fill', (d: any) => options.colorByType
          ? (typeColorMap.current.get(d.type) || '#ccc')
          : '#fff')
        .attr('stroke', (d: any) => {
          if (highlightNodeIds && highlightNodeIds.size > 0) {
            return highlightNodeIds.has(d.id) ? '#ff0' : (options.colorByType
              ? d3.color(typeColorMap.current.get(d.type) || '#ccc')!.darker(1).toString()
              : '#000');
          }
          return options.colorByType
            ? d3.color(typeColorMap.current.get(d.type) || '#ccc')!.darker(1).toString()
            : '#000';
        })
        .attr('stroke-width', (d: any) => highlightNodeIds?.has(d.id) ? 4 : 2)
        .style('opacity', (d: any) => {
          if (!highlightNodeIds || highlightNodeIds.size === 0) return 1;
          return highlightNodeIds.has(d.id) ? 1 : 0.2;
        })
        .style('filter', 'drop-shadow(1px 2px 3px rgba(0,0,0,0.15))')
        .style('cursor', 'pointer');

      // Type abbreviation inside circle
      node.append('text')
        .attr('class', 'node-type-badge')
        .text((d: any) => (d.type || '?').substring(0, 2).toUpperCase())
        .attr('text-anchor', 'middle').attr('dy', '0.35em')
        .style('font-family', '"JetBrains Mono", monospace')
        .style('font-size', (d: any) => `${Math.max(8, nodeR(d) - 6)}px`)
        .style('font-weight', '700')
        .style('fill', (d: any) => {
          if (!options.colorByType) return '#000';
          const c = d3.color(typeColorMap.current.get(d.type) || '#ccc');
          if (!c) return '#000';
          const { r, g: gv, b } = c.rgb();
          return (r * 0.299 + gv * 0.587 + b * 0.114) > 150 ? '#111' : '#fff';
        })
        .style('pointer-events', 'none');

      // Node name label below circle
      if (options.showLabels) {
        node.append('text')
          .attr('class', 'node-label')
          .text((d: any) => d.label && d.label.length > 18 ? d.label.substring(0, 16) + '…' : d.label)
          .attr('text-anchor', 'middle')
          .attr('dy', (d: any) => nodeR(d) + 14)
          .style('font-family', '"JetBrains Mono", monospace')
          .style('font-size', '10px')
          .style('font-weight', '600')
          .style('fill', '#222')
          .style('pointer-events', 'none');
      }

      // Edge labels
      let edgeLabel: d3.Selection<SVGTextElement, any, SVGGElement, unknown> | null = null;
      if (options.showEdgeLabels) {
        edgeLabel = g.append('g').attr('class', 'edge-labels')
          .selectAll('text').data(links).enter().append('text')
          .text((d: any) => d.type || '')
          .style('font-family', '"JetBrains Mono", monospace')
          .style('font-size', '9px')
          .style('fill', '#777')
          .style('text-anchor', 'middle')
          .style('pointer-events', 'none')
          .attr('dy', -5);
      }

      // ── Tick ──────────────────────────────────────────────────────────────
      sim.on('tick', () => {
        if (options.showCurvedEdges) {
          (linkEl as d3.Selection<SVGPathElement, any, SVGGElement, unknown>)
            .attr('d', (d: any) => {
              const sx = d.source.x, sy = d.source.y;
              const tx = d.target.x, ty = d.target.y;
              const dx = tx - sx, dy = ty - sy;
              const dr = Math.sqrt(dx * dx + dy * dy) * 0.8;
              return `M${sx},${sy}A${dr},${dr} 0 0,1 ${tx},${ty}`;
            });
        } else {
          (linkEl as d3.Selection<SVGLineElement, any, SVGGElement, unknown>)
            .attr('x1', (d: any) => d.source.x).attr('y1', (d: any) => d.source.y)
            .attr('x2', (d: any) => d.target.x).attr('y2', (d: any) => d.target.y);
        }
        node.attr('transform', (d: any) => `translate(${d.x},${d.y})`);
        if (edgeLabel) {
          edgeLabel
            .attr('x', (d: any) => (d.source.x + d.target.x) / 2)
            .attr('y', (d: any) => (d.source.y + d.target.y) / 2);
        }
      });

      // ── Zoom / Pan ────────────────────────────────────────────────────────
      const zoom = d3.zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.03, 8])
        .on('zoom', (event) => g.attr('transform', event.transform));

      svg.call(zoom);
      // Click on SVG background resets highlighting and active node
      svg.on('click', () => {
        setActiveNode(null);
        node.select('circle').style('opacity', 1).style('stroke-width', 2);
        (linkEl as any).style('stroke-opacity', 0.55);
      });

      zoomRef.current = zoom;

      return () => { sim.stop(); };
    }, [data, options, highlightNodeIds]);

    return (
      <div ref={containerRef} style={{ width: '100%', height: '100%', position: 'relative', overflow: 'hidden' }}>
        <svg ref={svgRef} width="100%" height="100%" />

        {/* ── Node details modal ────────────────────────────────────────────── */}
        {activeNode && (
          <div className="gc-node-modal">
            <div className="gc-node-modal-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                <h3 className="mono-text" style={{ margin: 0, fontSize: '0.85rem' }}>NODE DETAILS</h3>
                <span className="gc-node-badge" style={{ background: typeColorMap.current.get(activeNode.type) || '#000' }}>
                  {activeNode.type || 'Unknown'}
                </span>
              </div>
              <button className="gc-node-close" onClick={() => setActiveNode(null)}>
                <X size={16} />
              </button>
            </div>

            <div className="gc-node-modal-body">
              <div className="gc-node-row">
                <span className="gc-node-key"><Tag size={12}/> Name:</span>
                <span className="gc-node-val" style={{ fontWeight: 600 }}>{activeNode.label || '—'}</span>
              </div>
              <div className="gc-node-row">
                <span className="gc-node-key"><Database size={12}/> UUID:</span>
                <span className="gc-node-val" style={{ wordBreak: 'break-all', fontSize: '0.7em' }}>{activeNode.id}</span>
              </div>

              {activeNode.properties && Object.keys(activeNode.properties).length > 0 && (
                <>
                  <div className="gc-node-divider" />
                  <div className="gc-node-section-title">PROPERTIES</div>
                  <div className="gc-node-props">
                    {Object.entries(activeNode.properties).map(([k, v]) => (
                      <div className="gc-node-prop-item" key={k}>
                        <span className="gc-node-prop-k">{k}:</span>
                        <span className="gc-node-prop-v">{String(v)}</span>
                      </div>
                    ))}
                  </div>
                </>
              )}

              {activeNode.description && (
                <>
                  <div className="gc-node-divider" />
                  <div className="gc-node-section-title"><FileText size={12}/> DESCRIPTION / SUMMARY</div>
                  <div className="gc-node-summary">
                    {activeNode.description}
                  </div>
                </>
              )}
            </div>
          </div>
        )}

        <style>{`
          .gc-node-modal {
            position: absolute;
            top: 20px;
            right: 20px;
            width: 320px;
            max-height: calc(100% - 40px);
            background: #fff;
            border: 3px solid #000;
            box-shadow: 6px 6px 0 rgba(0,0,0,0.1);
            display: flex;
            flex-direction: column;
            z-index: 1000;
            animation: slideInR 0.15s ease-out;
          }
          @keyframes slideInR { from { transform: translateX(20px); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
          
          .gc-node-modal-header {
            padding: 0.75rem 1rem;
            border-bottom: 3px solid #000;
            background: #fafafa;
            display: flex;
            align-items: center;
            justify-content: space-between;
          }
          .gc-node-close {
            background: none; border: none; cursor: pointer; padding: 2px; display: flex; align-items: center; opacity: 0.5; transition: 0.12s;
          }
          .gc-node-close:hover { opacity: 1; color: #ef4444; }
          
          .gc-node-badge {
            color: #fff;
            font-size: 0.6rem;
            font-family: var(--font-mono);
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 20px;
            text-transform: uppercase;
          }

          .gc-node-modal-body {
            padding: 1rem;
            overflow-y: auto;
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 0.6rem;
            background: #fff;
          }

          .gc-node-row {
            display: flex;
            align-items: flex-start;
            gap: 0.75rem;
            font-family: var(--font-mono);
            font-size: 0.8rem;
          }
          .gc-node-key { width: 60px; flex-shrink: 0; color: #777; display: flex; align-items: center; gap: 4px; }
          .gc-node-val { flex: 1; color: #111; }

          .gc-node-divider { height: 1px; border-bottom: 1px dashed #ccc; margin: 0.4rem 0; }
          .gc-node-section-title { font-family: var(--font-mono); font-size: 0.7rem; font-weight: 700; color: #444; letter-spacing: 1px; margin-bottom: 0.2rem; display: flex; align-items: center; gap: 6px; }

          .gc-node-props { display: flex; flex-direction: column; gap: 4px; background: #f8f8f8; border: 1px solid #ddd; padding: 0.5rem; }
          .gc-node-prop-item { font-family: var(--font-mono); font-size: 0.7rem; display: flex; gap: 6px; align-items: flex-start; }
          .gc-node-prop-k { color: #555; }
          .gc-node-prop-v { color: #111; word-break: break-all; }

          .gc-node-summary {
            font-family: var(--font-mono);
            font-size: 0.75rem;
            line-height: 1.5;
            color: #333;
            background: #fff9c4;
            border-left: 3px solid #fbc02d;
            padding: 0.5rem 0.75rem;
          }
        `}</style>
      </div>
    );
  }
);

GraphCanvas.displayName = 'GraphCanvas';
export default GraphCanvas;
