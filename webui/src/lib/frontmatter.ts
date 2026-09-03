/**
 * 简易 frontmatter 解析（T-406）。
 * KnowSeq 条目 frontmatter 字段有限（type/title/created/updated/tags/
 * related/sources/status/description/origin 等），为展示用途解析为
 * 字符串 / 字符串数组即可，不引入完整 YAML parser 依赖。
 * 仅识别条目 schema 实际产出的形态：`key: value`、`key: [a, b]`、
 * 行式数组（`key:` 后跟 `- item`）、成对引号包裹值。
 */

export type FrontmatterValue = string | string[];

export interface ParsedEntry {
  data: Record<string, FrontmatterValue>;
  body: string;
}

export function parseFrontmatter(content: string): ParsedEntry {
  const norm = content.replace(/\r\n/g, '\n');
  if (!norm.startsWith('---\n')) return { data: {}, body: norm };

  const lines = norm.split('\n');
  let fenceLine = -1;
  for (let i = 1; i < lines.length; i++) {
    if (lines[i].trimEnd() === '---') {
      fenceLine = i;
      break;
    }
  }
  if (fenceLine < 0) return { data: {}, body: norm };

  const data: Record<string, FrontmatterValue> = {};
  let lastKey: string | null = null;
  for (const rawLine of lines.slice(1, fenceLine)) {
    const line = rawLine.trimEnd();
    if (!line.trim()) continue;

    const listMatch = line.match(/^\s*-\s+(.*)$/);
    if (listMatch && lastKey && /^\s/.test(rawLine)) {
      const prev = data[lastKey];
      const arr = Array.isArray(prev) ? prev : [];
      arr.push(stripQuotes(listMatch[1].trim()));
      data[lastKey] = arr;
      continue;
    }

    const kv = line.match(/^([A-Za-z_][\w-]*):\s*(.*)$/);
    if (!kv) continue;
    const key = kv[1];
    const value = kv[2].trim();
    lastKey = key;
    if (value === '') {
      data[key] = [];
    } else if (value.startsWith('[') && value.endsWith(']')) {
      const inner = value.slice(1, -1).trim();
      data[key] = inner
        ? inner.split(',').map((s) => stripQuotes(s.trim())).filter(Boolean)
        : [];
    } else {
      data[key] = stripQuotes(value);
    }
  }
  // `key:` 后无行式数组项 → 回退为空串，避免把空数组误当列表展示
  for (const [k, v] of Object.entries(data)) {
    if (Array.isArray(v) && v.length === 0) data[k] = '';
  }
  const body = lines
    .slice(fenceLine + 1)
    .join('\n')
    .replace(/^\n+/, '');
  return { data, body };
}

function stripQuotes(s: string): string {
  if (s.length >= 2 && ((s[0] === '"' && s.endsWith('"')) || (s[0] === "'" && s.endsWith("'")))) {
    return s.slice(1, -1);
  }
  return s;
}
