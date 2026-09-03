/**
 * 图谱页（T-407 / REQ-407 / FR-031）。
 * brain 图谱 JSON → graphology → sigma.js v3 渲染：ForceAtlas2 布局（≥220 节点走 Web
 * Worker）、点击/悬停高亮（点击聚焦 1.5x 邻居、其余 dimmed）、缩放控件、详情面板
 * （label/type/度数/关联边）、Louvain 社区着色与 type 着色切换、搜索定位。
 * LightRAG 节点 id 为实体名，不对应 knowledge 文件路径，不做条目跳转。
 * Ported from nashsu/llm_wiki (GPL-3.0)：graph-view.tsx 的 SigmaContainer 子组件模式
 * （GraphLoader / GraphRenderSettings / EventHandler）与高亮 reducer、hover canvas 渲染。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type Graph from 'graphology';
import forceAtlas2 from 'graphology-layout-forceatlas2';
import {
  SigmaContainer,
  useLoadGraph,
  useRegisterEvents,
  useSetSettings,
  useSigma,
} from '@react-sigma/core';
import '@react-sigma/core/lib/style.css';
import type { NodeHoverDrawingFunction } from 'sigma/rendering';
import type { Sigma } from 'sigma';
import { useStatus } from '../status/StatusContext';
import {
  buildGraph,
  fetchBrainGraph,
  layoutIterations,
  labelDensity,
  labelSizeThreshold,
  nodeColor,
  communityColor,
  typeLegend,
  WORKER_LAYOUT_NODE_THRESHOLD,
  BASE_NODE_SIZE,
  type BrainGraph,
  type GraphResult,
} from '../lib/graph';

type HoverState = { node: string; neighbors: Set<string> } | null;
type ColorMode = 'type' | 'community';

/* ---- 主题调色板（对齐 tokens.css：dark 单主题，activeEdge 用唯一 accent） ---- */
const GRAPH_PALETTE = {
  defaultEdge: 'rgba(100,116,139,0.18)',
  label: '#e6e8eb',
  hoverLabelText: '#e6e8eb',
  hoverLabelBackground: 'rgba(12,13,16,0.94)',
  hoverLabelBorder: 'rgba(154,161,172,0.38)',
  hoverLabelShadow: 'rgba(0,0,0,0.55)',
  mutedNodeMixTarget: '#343a44',
  dimmedEdge: 'rgba(71,85,105,0.12)',
  activeEdge: '#3ecf8e',
} as const;

/** 颜色混合（向 muted 目标靠拢实现灰化）· Ported from nashsu/llm_wiki (GPL-3.0) mixColor */
function mixColor(color1: string, color2: string, ratio: number): string {
  const hex = (c: string) => parseInt(c, 16);
  const r1 = hex(color1.slice(1, 3));
  const g1 = hex(color1.slice(3, 5));
  const b1 = hex(color1.slice(5, 7));
  const r2 = hex(color2.slice(1, 3));
  const g2 = hex(color2.slice(3, 5));
  const b2 = hex(color2.slice(5, 7));
  const r = Math.round(r1 + (r2 - r1) * ratio);
  const g = Math.round(g1 + (g2 - g1) * ratio);
  const b = Math.round(b1 + (b2 - b1) * ratio);
  return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`;
}

/* ---- hover 标签 canvas 渲染（Ported from nashsu/llm_wiki (GPL-3.0)） ---- */

function drawRoundedRect(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
) {
  const safeRadius = Math.min(radius, width / 2, height / 2);
  context.beginPath();
  context.moveTo(x + safeRadius, y);
  context.lineTo(x + width - safeRadius, y);
  context.quadraticCurveTo(x + width, y, x + width, y + safeRadius);
  context.lineTo(x + width, y + height - safeRadius);
  context.quadraticCurveTo(x + width, y + height, x + width - safeRadius, y + height);
  context.lineTo(x + safeRadius, y + height);
  context.quadraticCurveTo(x, y + height, x, y + height - safeRadius);
  context.lineTo(x, y + safeRadius);
  context.quadraticCurveTo(x, y, x + safeRadius, y);
  context.closePath();
}

function createGraphNodeHoverRenderer(palette: typeof GRAPH_PALETTE): NodeHoverDrawingFunction {
  return (context, data, settings) => {
    const label = typeof data.label === 'string' ? data.label : '';
    const labelSize = settings.labelSize;
    const font = settings.labelFont;
    const weight = settings.labelWeight;
    const nodeRadius = Math.max(data.size, labelSize / 2) + 3;

    context.save();
    context.shadowOffsetX = 0;
    context.shadowOffsetY = 2;
    context.shadowBlur = 10;
    context.shadowColor = palette.hoverLabelShadow;
    context.fillStyle = palette.hoverLabelBackground;
    context.strokeStyle = palette.hoverLabelBorder;
    context.lineWidth = 1;

    context.beginPath();
    context.arc(data.x, data.y, nodeRadius, 0, Math.PI * 2);
    context.closePath();
    context.fill();
    context.stroke();

    if (label) {
      context.font = `${weight} ${labelSize}px ${font}`;
      const paddingX = 8;
      const paddingY = 4;
      const gap = 6;
      const textWidth = context.measureText(label).width;
      const boxWidth = Math.ceil(textWidth + paddingX * 2);
      const boxHeight = Math.ceil(labelSize + paddingY * 2);
      const boxX = data.x + nodeRadius + gap;
      const boxY = data.y - boxHeight / 2;

      drawRoundedRect(context, boxX, boxY, boxWidth, boxHeight, 5);
      context.fill();
      context.stroke();

      context.shadowBlur = 0;
      context.shadowOffsetY = 0;
      context.fillStyle = palette.hoverLabelText;
      context.fillText(label, boxX + paddingX, data.y + labelSize / 3);
    }

    context.restore();
  };
}

/* ---- 拓扑 key（数据不变则跳过重布局） ---- */

function hashParts(parts: readonly string[]): string {
  let hash = 2166136261;
  for (const part of parts) {
    for (let i = 0; i < part.length; i++) {
      hash ^= part.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    hash ^= 0xff;
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

function graphDataKey(graph: Graph): string {
  const nodeIds: string[] = [];
  const edgeIds: string[] = [];
  graph.forEachNode((id) => nodeIds.push(id));
  graph.forEachEdge((_e, _attrs, source, target) => edgeIds.push(`${source}->${target}`));
  nodeIds.sort();
  edgeIds.sort();
  return `${hashParts(nodeIds)}:${hashParts(edgeIds)}:${nodeIds.length}:${edgeIds.length}`;
}

// 布局位置缓存：数据重渲染 / 着色切换时不重复布局
const positionCache = new Map<string, { x: number; y: number }>();

/* ---- SigmaContainer 子组件：加载 + 布局 ---- */

function GraphLoader({ result }: { result: GraphResult }) {
  const loadGraph = useLoadGraph();
  const sigma = useSigma();
  const lastLayoutKey = useRef('');
  const pendingKey = useRef('');

  useEffect(() => {
    const graph = result.graph;
    const dataKey = graphDataKey(graph);
    const needsLayout = dataKey !== lastLayoutKey.current && dataKey !== pendingKey.current;
    let cancelled = false;
    let worker: Worker | null = null;

    // 恢复缓存坐标（着色切换等重建场景避免抖动）
    graph.forEachNode((id) => {
      const cached = positionCache.get(id);
      if (cached) {
        graph.setNodeAttribute(id, 'x', cached.x);
        graph.setNodeAttribute(id, 'y', cached.y);
      }
    });

    const recordPositions = () => {
      graph.forEachNode((id, attrs) => {
        positionCache.set(id, { x: attrs.x, y: attrs.y });
      });
    };

    const runMainThreadLayout = () => {
      const settings = forceAtlas2.inferSettings(graph);
      forceAtlas2.assign(graph, {
        iterations: layoutIterations(graph.order),
        settings: {
          ...settings,
          gravity: 1,
          scalingRatio: graph.order > 400 ? 6 : 4,
          strongGravityMode: true,
          barnesHutOptimize: graph.order > 50,
        },
      });
      recordPositions();
      lastLayoutKey.current = dataKey;
    };

    if (needsLayout && graph.order > 1 && graph.order < WORKER_LAYOUT_NODE_THRESHOLD) {
      runMainThreadLayout();
    }

    loadGraph(graph);

    if (needsLayout && graph.order >= WORKER_LAYOUT_NODE_THRESHOLD) {
      try {
        worker = new Worker(new URL('../lib/graph-layout-worker.ts', import.meta.url), {
          type: 'module',
        });
      } catch (err) {
        console.warn('[Graph] worker 启动失败，回退主线程布局', err);
      }
      if (!worker) {
        runMainThreadLayout();
        loadGraph(graph);
        return undefined;
      }
      pendingKey.current = dataKey;
      const nodes: Array<{ id: string; x: number; y: number }> = [];
      graph.forEachNode((id, attrs) => {
        nodes.push({ id, x: attrs.x, y: attrs.y });
      });
      const edges: Array<{ source: string; target: string; weight: number }> = [];
      graph.forEachEdge((_e, _attrs, source, target) => {
        edges.push({ source, target, weight: 1 });
      });
      worker.onmessage = (
        event: MessageEvent<{ key: string; positions: Array<{ id: string; x: number; y: number }> }>,
      ) => {
        if (cancelled || event.data.key !== dataKey) return;
        for (const { id, x, y } of event.data.positions) {
          if (!graph.hasNode(id)) continue;
          graph.setNodeAttribute(id, 'x', x);
          graph.setNodeAttribute(id, 'y', y);
          positionCache.set(id, { x, y });
        }
        lastLayoutKey.current = dataKey;
        if (pendingKey.current === dataKey) pendingKey.current = '';
        sigma.refresh();
      };
      worker.onerror = (event) => {
        if (cancelled) return;
        console.warn('[Graph] 布局 worker 失败，回退主线程', event.message);
        if (pendingKey.current === dataKey) pendingKey.current = '';
        runMainThreadLayout();
        loadGraph(graph);
      };
      worker.postMessage({
        key: dataKey,
        nodes,
        edges,
        iterations: layoutIterations(graph.order),
        scalingRatio: graph.order > 400 ? 6 : 4,
      });
    } else if (needsLayout) {
      // 单节点或已在主线程完成布局
      if (graph.order <= 1) lastLayoutKey.current = dataKey;
    }

    return () => {
      cancelled = true;
      if (pendingKey.current === dataKey) pendingKey.current = '';
      worker?.terminate();
    };
  }, [loadGraph, sigma, result]);

  return null;
}

/* ---- SigmaContainer 子组件：渲染设置（高亮 / dimmed reducers） ---- */

function GraphRenderSettings({
  hoverState,
  selected,
  selectedNeighbors,
  nodeCount,
}: {
  hoverState: HoverState;
  selected: string | null;
  selectedNeighbors: Set<string> | null;
  nodeCount: number;
}) {
  const sigma = useSigma();
  const setSettings = useSetSettings();

  useEffect(() => {
    setSettings({
      hideEdgesOnMove: true,
      hideLabelsOnMove: true,
      labelColor: { color: GRAPH_PALETTE.label },
      labelDensity: labelDensity(nodeCount),
      labelRenderedSizeThreshold: labelSizeThreshold(nodeCount),
      renderEdgeLabels: false,
      defaultDrawNodeHover: createGraphNodeHoverRenderer(GRAPH_PALETTE),
      nodeReducer: (node, attrs) => {
        const result = { ...attrs };
        const hasHover = !!hoverState;
        const hasSelect = !!selected;
        const isHoverNode = hoverState?.node === node;
        const isHoverNeighbor = hoverState?.neighbors.has(node) ?? false;
        const isSelected = selected === node;
        const isSelectedNeighbor = selectedNeighbors?.has(node) ?? false;

        if (isSelected) {
          result.size = (attrs.size ?? BASE_NODE_SIZE) * 1.5;
          result.zIndex = 10;
          result.forceLabel = true;
        }
        if (isHoverNode) {
          result.size = (attrs.size ?? BASE_NODE_SIZE) * 1.4;
          result.zIndex = 10;
          result.forceLabel = true;
        }
        if (
          (hasHover && !isHoverNode && !isHoverNeighbor) ||
          (hasSelect && !isSelected && !isSelectedNeighbor)
        ) {
          result.color = mixColor(attrs.color ?? '#94a3b8', GRAPH_PALETTE.mutedNodeMixTarget, 0.75);
          result.label = '';
          result.size = (attrs.size ?? BASE_NODE_SIZE) * 0.6;
        }
        return result;
      },
      edgeReducer: (_edge, attrs) => {
        const result = { ...attrs };
        // graphology 不把端点存为边属性，需经 extremities 取回
        const ends = sigma.getGraph().extremities(_edge);
        const source = String(ends[0] ?? '');
        const target = String(ends[1] ?? '');
        const hasHover = !!hoverState;
        const hasSelect = !!selected;
        const hoverEdge =
          hasHover && (source === hoverState?.node || target === hoverState?.node);
        const selectedEdge = hasSelect && (source === selected || target === selected);

        if ((hasHover && !hoverEdge) || (hasSelect && !selectedEdge)) {
          result.color = GRAPH_PALETTE.dimmedEdge;
          result.size = 0.3;
        }
        if (hoverEdge || selectedEdge) {
          result.color = GRAPH_PALETTE.activeEdge;
          result.size = Math.max(2, (attrs.size ?? 1) * 1.5);
        }
        return result;
      },
    });
    sigma.refresh();
  }, [setSettings, sigma, hoverState, selected, selectedNeighbors, nodeCount]);

  return null;
}

/* ---- SigmaContainer 子组件：事件 ---- */

function EventHandler({
  onSelect,
  onHoverChange,
}: {
  onSelect: (nodeId: string | null) => void;
  onHoverChange: (state: HoverState) => void;
}) {
  const registerEvents = useRegisterEvents();
  const sigma = useSigma();

  useEffect(() => {
    registerEvents({
      clickNode: ({ node }) => onSelect(node),
      clickStage: () => onSelect(null),
      enterNode: ({ node }) => {
        sigma.getContainer().style.cursor = 'pointer';
        const graph = sigma.getGraph();
        onHoverChange({ node, neighbors: new Set(graph.neighbors(node)) });
      },
      leaveNode: () => {
        sigma.getContainer().style.cursor = 'default';
        onHoverChange(null);
      },
    });
  }, [registerEvents, sigma, onSelect, onHoverChange]);

  return null;
}

/* ---- 主组件 ---- */

export default function GraphPage() {
  const { brain } = useStatus();
  const ready = brain.data?.ready === true;

  const [data, setData] = useState<BrainGraph | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [colorMode, setColorMode] = useState<ColorMode>('type');
  const [selected, setSelected] = useState<string | null>(null);
  const [hoverState, setHoverState] = useState<HoverState>(null);
  const [query, setQuery] = useState('');

  const containerRef = useRef<Sigma | null>(null);
  const loadSeq = useRef(0);

  const load = useCallback(async () => {
    const seq = ++loadSeq.current;
    setLoading(true);
    setErr(null);
    try {
      const d = await fetchBrainGraph();
      if (seq !== loadSeq.current) return;
      setData(d);
    } catch (e) {
      if (seq !== loadSeq.current) return;
      setErr(e instanceof Error ? e.message : '加载图谱失败');
      setData(null);
    } finally {
      if (seq === loadSeq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (ready) void load();
  }, [ready, load]);

  // brain JSON → graphology（度数尺寸 + Louvain 社区 + 着色）
  const graphData = useMemo(
    () => (data ? buildGraph(data, colorMode) : null),
    [data, colorMode],
  );

  const selectedNeighbors = useMemo(() => {
    if (!graphData || !selected) return null;
    return new Set((graphData.neighborsOf.get(selected) ?? []).map((n) => n.id));
  }, [graphData, selected]);

  const detail = useMemo(() => {
    if (!graphData || !selected || !graphData.graph.hasNode(selected)) return null;
    const attrs = graphData.graph.getNodeAttributes(selected);
    return {
      label: String(attrs.label ?? selected),
      type: String(attrs.nodeType ?? 'entity'),
      degree: graphData.degree.get(selected) ?? 0,
      community: (attrs.community as number) ?? 0,
      neighbors: graphData.neighborsOf.get(selected) ?? [],
    };
  }, [graphData, selected]);

  const focusNode = useCallback((id: string) => {
    const sigma = containerRef.current;
    if (!sigma) return;
    if (!sigma.getGraph().hasNode(id)) return;
    // 相机 x/y 是归一化显示坐标，必须经 getNodeDisplayData 换算（节点原始坐标在 0-100 空间）
    const display = sigma.getNodeDisplayData(id);
    if (!display) return;
    sigma.getCamera().animate({ x: display.x, y: display.y, ratio: 0.5 }, { duration: 250 });
  }, []);

  const selectNode = useCallback(
    (id: string, focus: boolean) => {
      setSelected(id);
      if (focus) focusNode(id);
    },
    [focusNode],
  );

  const handleSelect = useCallback((nodeId: string | null) => {
    setSelected(nodeId);
  }, []);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q || !data) return [];
    return data.nodes
      .filter((n) => n.label.toLowerCase().includes(q) || n.id.toLowerCase().includes(q))
      .slice(0, 8);
  }, [query, data]);

  const legend = useMemo(() => {
    if (!data) return [];
    if (colorMode === 'type') {
      return typeLegend(data.nodes).map((t) => ({ label: `${t.type} ×${t.count}`, color: nodeColor(t.type) }));
    }
    if (!graphData) return [];
    const counts = new Map<number, number>();
    for (const c of graphData.communityOf.values()) counts.set(c, (counts.get(c) ?? 0) + 1);
    return Array.from(counts.keys())
      .sort((a, b) => a - b)
      .map((c) => ({ label: `社区 ${c + 1} ×${counts.get(c) ?? 0}`, color: communityColor(c) }));
  }, [data, graphData, colorMode]);

  const empty = ready && !loading && !err && data !== null && graphData !== null && graphData.graph.order === 0;
  const showCanvas = graphData !== null && graphData.graph.order > 0;

  return (
    <section className="page graph-page">
      <div className="page-head">
        <div>
          <h1>图谱</h1>
          <p className="page-desc">
            大脑知识图谱（FR-031）：ForceAtlas2 布局 · 点击节点聚焦 1.5× 邻居 · Louvain 社区着色
          </p>
        </div>
        <div className="page-head-side">
          {graphData && graphData.graph.order > 0 && (
            <span className="stat-inline">
              {graphData.graph.order} 节点 · {graphData.graph.size} 关系
            </span>
          )}
          <button className="btn btn-ghost btn-sm" onClick={() => void load()} disabled={!ready || loading}>
            {loading ? '加载中…' : '刷新'}
          </button>
        </div>
      </div>

      {!ready && (
        <div className="empty">
          <strong>大脑未就绪</strong>
          大脑索引尚未构建——请先在「编译」页完成编译入库，再回到本页查看图谱。
        </div>
      )}

      {ready && err && (
        <div className="empty">
          <strong>加载失败</strong>
          {err}
          <div style={{ marginTop: 'var(--sp-3)' }}>
            <button className="btn btn-sm" onClick={() => void load()}>
              重试
            </button>
          </div>
        </div>
      )}

      {ready && !err && empty && (
        <div className="empty">
          <strong>图谱为空</strong>
          大脑索引中没有可展示的实体——请先完成编译入库（knowledge/ 素材提炼），再刷新本页。
        </div>
      )}

      {ready && !err && loading && data === null && (
        <div className="empty">
          <strong>加载中</strong>
          正在从大脑索引导出图谱…
        </div>
      )}

      {showCanvas && graphData && (
        <div className="graph-shell">
          <SigmaContainer
            ref={containerRef}
            className="graph-canvas"
            style={{ position: 'absolute', inset: 0 }}
          >
            <GraphLoader result={graphData} />
            <GraphRenderSettings
              hoverState={hoverState}
              selected={selected}
              selectedNeighbors={selectedNeighbors}
              nodeCount={graphData.graph.order}
            />
            <EventHandler onSelect={handleSelect} onHoverChange={setHoverState} />
          </SigmaContainer>

          {/* 工具栏：搜索 + 着色切换 */}
          <div className="graph-toolbar">
            <div className="gt-search">
              <input
                type="text"
                placeholder="搜索节点…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              {matches.length > 0 && (
                <div className="graph-search-pop">
                  {matches.map((n) => (
                    <button key={n.id} className="gsp-item" onClick={() => selectNode(n.id, true)}>
                      <span
                        className="legend-dot"
                        style={{
                          background:
                            colorMode === 'community'
                              ? communityColor(graphData.communityOf.get(n.id) ?? 0)
                              : nodeColor(n.type),
                        }}
                      />
                      {n.label}
                      <em>{n.type}</em>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="tabs gp-mode">
              <button
                className={`tab ${colorMode === 'type' ? 'active' : ''}`}
                onClick={() => setColorMode('type')}
              >
                按类型
              </button>
              <button
                className={`tab ${colorMode === 'community' ? 'active' : ''}`}
                onClick={() => setColorMode('community')}
              >
                按社区
              </button>
            </div>
          </div>

          {/* 缩放控件 */}
          <div className="graph-zoom">
            <button
              className="gzoom-btn"
              title="放大"
              onClick={() => containerRef.current?.getCamera().animatedZoom({ duration: 200 })}
            >
              +
            </button>
            <button
              className="gzoom-btn"
              title="缩小"
              onClick={() => containerRef.current?.getCamera().animatedUnzoom({ duration: 200 })}
            >
              −
            </button>
            <button
              className="gzoom-btn"
              title="重置视图"
              onClick={() => containerRef.current?.getCamera().animatedReset({ duration: 300 })}
            >
              ⤢
            </button>
          </div>

          {/* 图例 */}
          {legend.length > 0 && (
            <div className="graph-legend">
              {legend.map((item) => (
                <span key={item.label} className="legend-item">
                  <span className="legend-dot" style={{ background: item.color }} />
                  {item.label}
                </span>
              ))}
            </div>
          )}

          {/* 详情面板 */}
          {detail && (
            <aside className="graph-detail">
              <div className="gd-head">
                <strong className="gd-title">{detail.label}</strong>
                <button className="gd-close" title="关闭" onClick={() => setSelected(null)}>
                  ×
                </button>
              </div>
              <div className="gd-meta">
                <span className="chip chip-sm">{detail.type}</span>
                <span className="chip chip-sm">社区 {detail.community + 1}</span>
                <span className="chip chip-sm">{detail.degree} 度</span>
              </div>
              <div className="gd-neighbors">
                {detail.neighbors.length === 0 && <p className="gd-hint">无关联节点</p>}
                {detail.neighbors.map((nb) => (
                  <button key={`${nb.id}`} className="gd-link" onClick={() => selectNode(nb.id, true)}>
                    <span className="gd-rel">{nb.relation}</span>
                    <span className="gd-nlabel">
                      {graphData.graph.hasNode(nb.id)
                        ? String(graphData.graph.getNodeAttribute(nb.id, 'label') ?? nb.id)
                        : nb.id}
                    </span>
                  </button>
                ))}
              </div>
            </aside>
          )}
        </div>
      )}
    </section>
  );
}
