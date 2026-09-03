/**
 * 图谱数据与工具（T-407 / REQ-407 / FR-031）。
 * brain API：GET /api/brain/graph → { nodes:[{id,label,type}], edges:[{source,target,relation}] }
 * 职责：brain JSON → graphology Graph（度数→尺寸、Louvain 社区、着色）、布局分档参数。
 * Ported from nashsu/llm_wiki (GPL-3.0)：graph-view.tsx / graph-layout-worker.ts 中的
 * 布局迭代分档、社区配色、节点尺寸与着色策略，按 KnowSeq 设计系统（dark 单主题）
 * 改写：调色板对齐 tokens.css，activeEdge 使用唯一 accent。
 */
import Graph from 'graphology';
import louvain from 'graphology-communities-louvain';
import { api } from '../api';

export interface BrainNode {
  id: string;
  label: string;
  type: string;
}

export interface BrainEdge {
  source: string;
  target: string;
  relation: string;
}

export interface BrainGraph {
  nodes: BrainNode[];
  edges: BrainEdge[];
}

export interface GraphResult {
  graph: Graph;
  /** 去重后度数（节点关联边数） */
  degree: Map<string, number>;
  /** 邻居与关系（详情面板关联边列表） */
  neighborsOf: Map<string, Array<{ id: string; relation: string }>>;
  /** 节点 → Louvain 社区 id */
  communityOf: Map<string, number>;
  communityCount: number;
}

export async function fetchBrainGraph(): Promise<BrainGraph> {
  return api<BrainGraph>('/api/brain/graph');
}

/* ---- 着色（数据编码色，与 UI 强调色分属不同维度） ---- */

const NODE_TYPE_COLORS: Record<string, string> = {
  entity: '#60a5fa',
  concept: '#c084fc',
  source: '#fb923c',
  query: '#4ade80',
  other: '#94a3b8',
};

const FALLBACK_NODE_COLORS = [
  '#38bdf8',
  '#34d399',
  '#fbbf24',
  '#fb7185',
  '#a78bfa',
  '#22d3ee',
  '#f97316',
  '#84cc16',
];

/** Louvain 社区配色（移植 COMMUNITY_COLORS 十二色循环） */
export const COMMUNITY_COLORS = [
  '#60a5fa',
  '#4ade80',
  '#fb923c',
  '#c084fc',
  '#f87171',
  '#2dd4bf',
  '#facc15',
  '#f472b6',
  '#a78bfa',
  '#38bdf8',
  '#34d399',
  '#fbbf24',
];

export function communityColor(community: number): string {
  return COMMUNITY_COLORS[community % COMMUNITY_COLORS.length] ?? NODE_TYPE_COLORS.other;
}

export function nodeColor(type: string): string {
  if (NODE_TYPE_COLORS[type]) return NODE_TYPE_COLORS[type];
  let hash = 0;
  for (const char of type) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return FALLBACK_NODE_COLORS[hash % FALLBACK_NODE_COLORS.length] ?? NODE_TYPE_COLORS.other;
}

/** type 模式图例：按出现顺序去重的 (type, count) */
export function typeLegend(nodes: BrainNode[]): Array<{ type: string; count: number }> {
  const counts = new Map<string, number>();
  for (const n of nodes) counts.set(n.type, (counts.get(n.type) ?? 0) + 1);
  return Array.from(counts, ([type, count]) => ({ type, count })).sort(
    (a, b) => b.count - a.count,
  );
}

/* ---- 布局参数（Ported from nashsu/llm_wiki (GPL-3.0)） ---- */

export const BASE_NODE_SIZE = 8;
export const MAX_NODE_SIZE = 28;
export const WORKER_LAYOUT_NODE_THRESHOLD = 220;

/** 迭代分档：>600/1200/2500 → 65/40/28，>250 → 90，其余 140 */
export function layoutIterations(nodeCount: number): number {
  if (nodeCount > 2500) return 28;
  if (nodeCount > 1200) return 40;
  if (nodeCount > 600) return 65;
  if (nodeCount > 250) return 90;
  return 140;
}

export function labelDensity(nodeCount: number): number {
  if (nodeCount > 2500) return 0.08;
  if (nodeCount > 1200) return 0.14;
  if (nodeCount > 600) return 0.24;
  return 0.4;
}

export function labelSizeThreshold(nodeCount: number): number {
  if (nodeCount > 2500) return 18;
  if (nodeCount > 1200) return 14;
  if (nodeCount > 600) return 10;
  return 6;
}

export function edgeVisibilityThreshold(nodeCount: number): number {
  if (nodeCount > 2500) return 0.16;
  if (nodeCount > 1200) return 0.1;
  if (nodeCount > 700) return 0.05;
  return 0;
}

function densityScale(nodeCount: number): number {
  if (nodeCount <= 150) return 1;
  return Math.max(0.35, Math.sqrt(150 / nodeCount));
}

/** 度数开方比例 → 节点尺寸（Ported from nashsu/llm_wiki nodeSize） */
export function nodeSize(degree: number, maxDegree: number, nodeCount: number): number {
  if (maxDegree === 0) return BASE_NODE_SIZE;
  const ratio = degree / maxDegree;
  return (BASE_NODE_SIZE + Math.sqrt(ratio) * (MAX_NODE_SIZE - BASE_NODE_SIZE)) * densityScale(nodeCount);
}

/* ---- brain JSON → graphology Graph ---- */

/**
 * 构建 graphology Graph：随机初始坐标 + 度数尺寸 + Louvain 社区属性 + 着色。
 * 重复边（同向或反向已存在）跳过，relation 合并到已有边。
 */
export function buildGraph(data: BrainGraph, colorMode: 'type' | 'community'): GraphResult {
  const graph = new Graph({ multi: false, allowSelfLoops: false });
  const degree = new Map<string, number>();
  const neighborsOf = new Map<string, Array<{ id: string; relation: string }>>();
  const communityOf = new Map<string, number>();

  for (const node of data.nodes) {
    if (graph.hasNode(node.id)) continue;
    graph.addNode(node.id, {
      x: Math.random() * 100,
      y: Math.random() * 100,
      size: BASE_NODE_SIZE,
      color: nodeColor(node.type),
      label: node.label || node.id,
      nodeType: node.type,
      community: 0,
    });
    degree.set(node.id, 0);
    neighborsOf.set(node.id, []);
  }

  for (const edge of data.edges) {
    if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target)) continue;
    if (edge.source === edge.target) continue;
    const key = `${edge.source}->${edge.target}`;
    const reverse = `${edge.target}->${edge.source}`;
    if (graph.hasEdge(key)) {
      const prev = graph.getEdgeAttribute(key, 'relation') as string;
      if (edge.relation && !prev.includes(edge.relation)) {
        graph.setEdgeAttribute(key, 'relation', `${prev} / ${edge.relation}`);
      }
      continue;
    }
    if (graph.hasEdge(reverse)) {
      const prev = graph.getEdgeAttribute(reverse, 'relation') as string;
      if (edge.relation && !prev.includes(edge.relation)) {
        graph.setEdgeAttribute(reverse, 'relation', `${prev} / ${edge.relation}`);
      }
      continue;
    }
    graph.addEdgeWithKey(key, edge.source, edge.target, { relation: edge.relation || 'related' });
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
    neighborsOf.get(edge.source)?.push({ id: edge.target, relation: edge.relation });
    neighborsOf.get(edge.target)?.push({ id: edge.source, relation: edge.relation });
  }

  // Louvain 社区（graphology-communities-louvain，写入节点 community 属性）
  try {
    louvain.assign(graph);
  } catch {
    // 单节点/无边图无法分社区：全部归社区 0
    graph.forEachNode((id) => graph.setNodeAttribute(id, 'community', 0));
  }

  const maxDegree = Math.max(1, ...degree.values());
  let communityCount = 0;
  graph.forEachNode((id, attrs) => {
    const community = (attrs.community as number) ?? 0;
    communityOf.set(id, community);
    if (community + 1 > communityCount) communityCount = community + 1;
    graph.setNodeAttribute(id, 'size', nodeSize(degree.get(id) ?? 0, maxDegree, graph.order));
    if (colorMode === 'community') {
      graph.setNodeAttribute(id, 'color', communityColor(community));
    }
  });

  return { graph, degree, neighborsOf, communityOf, communityCount };
}
