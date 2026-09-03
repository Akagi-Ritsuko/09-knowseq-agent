"""REVIEW 项持久化仓库（T-210 REQ-210）。

Ported from nashsu/llm_wiki (GPL-3.0) — src/stores/review-store.ts + src/lib/review-utils.ts。

与原实现差异：
- reviewIdFor 原为 FNV-1a 哈希，按 REQ-210 改为内容派生 id 直接拼接
  ``{type}::{normalize_title(title)}``（无哈希），便于人工辨识与跨进程稳定；
- load 时仍按内容派生 id 折叠（normalizeReviewItems 迁移语义），旧格式自动归一；
- detail/文案中文；created 为本地时间 ISO 8601（秒精度）；
- 增加 resolved_note 扩展字段记录人工处理备注。
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .blocks import ReviewBlock

# REVIEW 标题前缀剥离（对齐原 REVIEW_TITLE_PREFIX_RE，中英七种前缀）
REVIEW_TITLE_PREFIX_RE = re.compile(
    r"^(missing[\s-]?page[:：]\s*|duplicate[\s-]?page[:：]\s*|possible[\s-]?duplicate[:：]\s*"
    r"|缺失页面[:：]\s*|缺少页面[:：]\s*|重复页面[:：]\s*|疑似重复[:：]\s*)",
    re.IGNORECASE,
)


def normalize_review_title(title: str) -> str:
    """归一 REVIEW 标题：剥已知前缀 → 空白折叠单空格 → strip → lower。

    内容派生稳定 id 的基础：同一问题不同措辞前缀/大小写归一到同一 id。
    """
    text = REVIEW_TITLE_PREFIX_RE.sub("", title.lstrip(), count=1)
    return re.sub(r"\s+", " ", text).strip().lower()


def review_id_for(item: ReviewItem) -> str:
    """内容派生稳定 id：``{type}::{normalize_title(title)}``（REQ-210，无哈希）。"""
    return f"{item.type}::{normalize_review_title(item.title)}"


@dataclass
class ReviewItem:
    """一条待人工处理的 review（REQ-210 字段序；resolved_note/pages/search 为扩展）。"""

    id: str = ""
    type: str = ""
    title: str = ""
    detail: str = ""
    status: str = "open"  # open | resolved
    created: str = ""
    source_path: str = ""
    resolved_note: str = ""
    pages: list[str] = field(default_factory=list)
    search: list[str] = field(default_factory=list)


def from_block(block: ReviewBlock, source_path: str = "") -> ReviewItem:
    """REVIEW 解析块 → ReviewItem（id/created 由 store.add 时派生）。"""
    return ReviewItem(
        type=block.type,
        title=block.title,
        detail=block.detail,
        pages=list(block.pages),
        search=list(block.search),
        source_path=source_path,
    )


def _union(a: list[str], b: list[str]) -> list[str]:
    """保序去重合并（对齐原 unionField）。"""
    return list(dict.fromkeys([*(a or []), *(b or [])]))


def _merge(old: ReviewItem, new: ReviewItem, *, prefer_new: bool) -> ReviewItem:
    """同 id 两项合并。

    - status：任一 resolved 即 resolved（resolve 后重复出现不回退为 open）；
    - detail/source_path：prefer_new=True 为 add 语义（incoming 非空优先），
      False 为 load 折叠语义（首个出现者优先，对齐原 normalizeReviewItems）；
    - created：取最早（ISO 字符串字典序可比），空串守卫；
    - pages/search：并集；resolved_note：非空者胜。
    """
    first, second = (new, old) if prefer_new else (old, new)
    created = old.created or new.created
    if old.created and new.created:
        created = min(old.created, new.created)
    return ReviewItem(
        id=old.id,
        type=old.type,
        title=old.title,
        detail=first.detail or second.detail,
        status="resolved" if "resolved" in (old.status, new.status) else "open",
        created=created,
        source_path=first.source_path or second.source_path,
        resolved_note=old.resolved_note or new.resolved_note,
        pages=_union(old.pages, new.pages),
        search=_union(old.search, new.search),
    )


def normalize_review_items(items: Iterable[ReviewItem]) -> list[ReviewItem]:
    """按内容派生 id 折叠重复项（load 迁移语义：首见 detail、最早 created、resolved 胜出）。"""
    by_id: dict[str, ReviewItem] = {}
    for item in items:
        key = review_id_for(item)
        existing = by_id.get(key)
        if existing is None:
            by_id[key] = replace(item, id=key)
        else:
            by_id[key] = _merge(existing, item, prefer_new=False)
    return list(by_id.values())


class ReviewStore:
    """轻量 JSON 持久化仓库：``<base_dir>/.knowseq/reviews.json``。

    与 cache.py 同款线程安全范式：Lock 保护 load-modify-save；缺文件/损坏
    一律空兜底；写盘失败尽力而为（内存态权威）。
    """

    def __init__(self, base_dir: Path):
        self._path = Path(base_dir) / ".knowseq" / "reviews.json"
        self._lock = threading.Lock()

    # ---- 持久化 ----
    def _load(self) -> list[ReviewItem]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001  缺失/损坏视为空
            return []
        if not isinstance(raw, list):
            return []
        fields = ReviewItem.__dataclass_fields__
        items: list[ReviewItem] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            filtered = {k: v for k, v in entry.items() if k in fields and v is not None}
            try:
                items.append(ReviewItem(**filtered))
            except TypeError:
                continue
        return normalize_review_items(items)  # 旧格式 id 迁移 + 折叠

    def _save(self, items: list[ReviewItem]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = [asdict(i) for i in items]
            self._path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass  # 持久化尽力而为

    # ---- 操作 ----
    def add(self, items: Iterable[ReviewItem]) -> list[ReviewItem]:
        """合并入库：同 id 已存在则按 add 语义合并（incoming detail 优先、
        resolved 保留、created 取早），新项记当前时间。返回合并后全量。"""
        with self._lock:
            current = self._load()
            by_id = {i.id: i for i in current}
            now = datetime.now().isoformat(timespec="seconds")
            for raw in items:
                item = replace(raw, id=review_id_for(raw))
                existing = by_id.get(item.id)
                if existing is None:
                    item.created = item.created or now
                    by_id[item.id] = item
                else:
                    by_id[item.id] = _merge(existing, item, prefer_new=True)
            merged = list(by_id.values())
            self._save(merged)
            return merged

    def list(self, status: str | None = None) -> list[ReviewItem]:
        """列出 review；status 过滤（"open"/"resolved"）。"""
        with self._lock:
            items = self._load()
        if status is None:
            return items
        return [i for i in items if i.status == status]

    def resolve(self, item_id: str, note: str | None = None) -> bool:
        """标记 resolved（附处理备注）；未命中返回 False。"""
        with self._lock:
            items = self._load()
            for i, item in enumerate(items):
                if item.id == item_id:
                    items[i] = replace(
                        item, status="resolved",
                        resolved_note=note if note else item.resolved_note)
                    self._save(items)
                    return True
            return False
