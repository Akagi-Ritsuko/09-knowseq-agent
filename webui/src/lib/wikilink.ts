/**
 * Ported from nashsu/llm_wiki (GPL-3.0) — src/lib/wikilink-transform.ts
 * （unwrapWikilink 移植自同项目 src/lib/wiki-page-resolver.ts）。
 *
 * 将条目正文中的 Obsidian 式 `[[target]]` / `[[target|alias]]` 转为
 * `[label](#target)` 标准链接，使 marked 等渲染器按链接（而非裸文本）
 * 呈现；应用内在渲染容器上拦截 `#` 开头的点击并路由跳转。
 *
 * 裁剪适配：transformImageEmbeds（`![[…]]` 图片嵌入）不移植——KnowSeq
 * 条目为纯文本知识卡，无图片嵌入场景。
 *
 * 保留源语义：围栏代码块（```…```）与行内代码（`…`）中的 wikilink
 * 不改写，避免文档示例被破坏。
 */

/** 把 `[[target]]` / `[[target|alias]]` 包装转换为 `{ slug, label }`。
 * frontmatter 的 related/sources 字段有时写成 wikilink 而非裸 slug，
 * 展示时剥掉括号噪音、按 target 查找。非 wikilink 输入原样返回。 */
export function unwrapWikilink(s: string): { slug: string; label: string } {
  const m = s.match(/^\[\[([^\]|]+)(?:\|([^\]]*))?\]\]$/);
  if (!m) return { slug: s, label: s };
  const target = m[1].trim();
  const alias = m[2]?.trim();
  return { slug: target, label: alias && alias.length > 0 ? alias : target };
}

export function transformWikilinks(body: string): string {
  if (!body.includes('[[')) return body;

  // 按三反引号围栏切分，捕获组保留下围栏内容；奇数下标 = 围栏内部，
  // 原样透传。
  const parts = body.split(/(```[\s\S]*?```)/g);
  return parts
    .map((part, idx) => (idx % 2 === 1 ? part : transformOutsideCode(part)))
    .join('');
}

const WIKILINK_RE = /\[\[([^\]|\n]+)(?:\|([^\]\n]*))?\]\]/g;

function transformOutsideCode(text: string): string {
  if (!text.includes('[[')) return text;

  // 再按行内代码 span 切分，反引号内容保持原样。
  const parts = text.split(/(`[^`\n]+`)/g);
  return parts
    .map((part, idx) => (idx % 2 === 1 ? part : replaceWikilinks(part)))
    .join('');
}

function replaceWikilinks(text: string): string {
  return text.replace(WIKILINK_RE, (_match, rawTarget: string, rawAlias?: string) => {
    const target = rawTarget.trim();
    const alias = rawAlias?.trim() ?? '';
    const label = alias.length > 0 ? alias : target;
    // 编码 target：空格 / 括号 / # 不会破坏 markdown 链接解析。
    const href = `#${encodeURIComponent(target)}`;
    // 转义 label 中的方括号，防止提前终止链接文本。
    const escapedLabel = label.replace(/\[/g, '\\[').replace(/\]/g, '\\]');
    return `[${escapedLabel}](${href})`;
  });
}

/** 容错 decodeURIComponent（源 wiki-reader 点击处理同款守卫）。 */
export function safeDecodeUri(s: string): string {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
}
