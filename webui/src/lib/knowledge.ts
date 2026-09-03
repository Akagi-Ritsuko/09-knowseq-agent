/**
 * 知识库条目领域逻辑（T-406 / REQ-406）。
 * slug 解析策略部分移植自 nashsu/llm_wiki (GPL-3.0)
 * src/lib/wiki-page-resolver.ts 的 resolveRelatedSlug——按 KnowSeq 的
 * 扁平条目模型（五类目录 + slug 全局唯一）简化为线性查找。
 */

export const CATEGORIES = [
  'decisions',
  'lessons',
  'concepts',
  'connections',
  'queries',
] as const;
export type Category = (typeof CATEGORIES)[number];

export const CATEGORY_LABELS: Record<Category, string> = {
  decisions: '决策',
  lessons: '教训',
  concepts: '概念',
  connections: '关联',
  queries: '疑问',
};

export interface KnowledgeEntry {
  type: string;
  slug: string;
  path: string;
}

/**
 * 把 wikilink 目标解析为条目相对路径；找不到返回 null（断链）。
 * 接受三种形态（对齐源 resolveRelatedSlug 语义）：
 *   1. 类内路径：`lessons/foo`   → path 精确匹配
 *   2. 带扩展名：`foo.md`        → slug 匹配（slug 全局唯一）
 *   3. 裸 slug：  `foo`          → slug 匹配
 */
export function resolveWikiTarget(target: string, entries: KnowledgeEntry[]): string | null {
  const t = target.trim().replace(/\.md$/, '');
  if (!t) return null;
  if (t.includes('/')) {
    const hit = entries.find((e) => e.path === `${t}.md`);
    return hit ? hit.path : null;
  }
  const hit = entries.find((e) => e.slug === t);
  return hit ? hit.path : null;
}

/** 按 slug（大小写不敏感）过滤条目，用于列表搜索框。 */
export function filterEntries(entries: KnowledgeEntry[], q: string): KnowledgeEntry[] {
  const needle = q.trim().toLowerCase();
  if (!needle) return entries;
  return entries.filter((e) => e.slug.toLowerCase().includes(needle));
}
