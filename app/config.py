"""配置加载与持久化（T-101 REQ-101 / NFR-002）。

- 非敏感项：config.yaml（web.port / paths / sources.*）
- 敏感项：.env（飞书凭据、LLM Key），由 set_env 写回，不入 config.yaml、不入日志。
"""
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict = {
    "web": {"port": 8765, "auto_start": True},
    "paths": {"inbox_dir": "inbox", "drop_dir": "drop"},
    "sources": {
        "screen": {"enabled": False},
        "clipboard": {"enabled": True, "interval": 2, "max_len": 50000},
        "feishu": {"enabled": False},
        "file": {"enabled": True, "dirs": []},
        "web": {"enabled": True},
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """把 override 递归合并进 base（override 优先），返回 base。"""
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


class Config:
    def __init__(self, config_path: Path | None = None, env_path: Path | None = None):
        self.config_path = config_path or (ROOT / "config.yaml")
        self.env_path = env_path or (ROOT / ".env")
        self.data: dict = _deep_merge(_deep_merge({}, DEFAULTS), self._load_yaml())
        load_dotenv(self.env_path)

    def _load_yaml(self) -> dict:
        try:
            with open(self.config_path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    # ---- 读取 ----
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    # ---- 写入与持久化 ----
    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def save(self) -> None:
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.data, f, allow_unicode=True, sort_keys=False)

    # ---- 敏感项（.env） ----
    def secret(self, name: str, default: str = "") -> str:
        return os.environ.get(name, default)

    def set_env(self, name: str, value: str) -> None:
        """写回 .env（不存在则创建），并同步到环境变量。"""
        self.env_path.parent.mkdir(parents=True, exist_ok=True)
        lines = self.env_path.read_text(encoding="utf-8").splitlines() if self.env_path.exists() else []
        found = False
        for i, line in enumerate(lines):
            if line.split("=", 1)[0].strip() == name:
                lines[i] = f"{name}={value}"
                found = True
                break
        if not found:
            lines.append(f"{name}={value}")
        self.env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.environ[name] = value

    # ---- 便捷路径 ----
    def _path(self, key: str, default: str) -> Path:
        d = self.get(key, default)
        p = Path(d)
        return p if p.is_absolute() else ROOT / p

    @property
    def inbox_dir(self) -> Path:
        return self._path("paths.inbox_dir", "inbox")

    @property
    def drop_dir(self) -> Path:
        return self._path("paths.drop_dir", "drop")
