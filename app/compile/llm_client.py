"""OpenAI 兼容 LLM 客户端（T-202 REQ-202）。

Ported from nashsu/llm_wiki (GPL-3.0) —— src/lib/llm-client.ts、
llm-providers.ts（custom/OpenAI 兼容路径）、reasoning-detector.ts。

按 REQ-202 前置决策仅实现 OpenAI Chat Completions 兼容协议
（火山方舟/DeepSeek/Kimi/智谱/通义/Ollama/vLLM 均兼容）；
Provider 基类抽象预留日后扩展，加协议只增不改。

- stream_chat：唯一入口。requests stream=True + iter_lines 解析 SSE（NFR-202 零新依赖）
- has_usable_llm：base_url + model + .env LLM_API_KEY 齐备守卫
- 429 → RateLimitedError（队列层暂停 15min 自动恢复）
- 400/422 且错误文本提到 temperature → 去温度重试一次（Kimi 等只允许固定温度的端点）
- thinking 模型防护：ingest_reasoning 默认关闭时对已知端点显式发关闭信号；
  0 content + 大量 reasoning → 明确报错而非静默空响应
"""
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from ..config import Config

TEMPERATURE_OVERRIDE_KEYS = ("temperature", "top_p", "max_tokens", "stop")

REASONING_FIELD_RE = re.compile(r'"reasoning(?:_content)?"\s*:\s*"((?:[^"\\]|\\.)*)"')

REASONING_ONLY_THRESHOLD = 200  # 字符；超过则判定"只思考不回答"


class LlmError(RuntimeError):
    """LLM 请求/解析失败。"""


class LlmConnectionError(LlmError):
    """网络/端点不可达。"""


class RateLimitedError(LlmError):
    """429 限流：调用方应暂停一段时间后重试。"""


class StreamCancelled(LlmError):
    """stop_event 触发，流式请求被取消。"""


@dataclass
class StreamEvent:
    """单条 SSE 解析结果。"""

    content: str | None = None
    usage: dict | None = None
    finish_reason: str | None = None


@dataclass
class LlmResult:
    content: str
    usage: dict | None = None
    stop_reason: str | None = None


def count_reasoning_chars(raw_line: str) -> int:
    """统计一行 SSE 中 reasoning 字段的转义长度（0 vs 数百字符的阈值判断）。"""
    return sum(len(m.group(1)) for m in REASONING_FIELD_RE.finditer(raw_line))


def normalize_url(base_url: str) -> str:
    """base_url 归一化：补 /chat/completions（已带则不重复补）。"""
    u = base_url.strip().rstrip("/")
    if u.endswith("/chat/completions"):
        return u
    return u + "/chat/completions"


class Provider:
    """Provider adapter 抽象（build_request / parse_stream_line / parse_response）。"""

    def build_request(self, base_url: str, api_key: str, model: str,
                      messages: list[dict], *, stream: bool, overrides: dict,
                      ingest_reasoning: bool) -> tuple[str, dict, dict]:
        raise NotImplementedError

    def parse_stream_line(self, raw_line: str) -> StreamEvent | None:
        raise NotImplementedError

    def parse_response(self, payload: dict) -> LlmResult:
        raise NotImplementedError


class OpenAICompatProvider(Provider):
    def build_request(self, base_url: str, api_key: str, model: str,
                      messages: list[dict], *, stream: bool, overrides: dict,
                      ingest_reasoning: bool) -> tuple[str, dict, dict]:
        url = normalize_url(base_url)
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.get("role", "user"), "content": m.get("content", "")}
                         for m in messages],
            "stream": stream,
        }
        for key in TEMPERATURE_OVERRIDE_KEYS:
            if overrides.get(key) is not None:
                body[key] = overrides[key]
        self._apply_reasoning(body, base_url, model, ingest_reasoning)
        return url, headers, body

    @staticmethod
    def _apply_reasoning(body: dict, base_url: str, model: str,
                         ingest_reasoning: bool) -> None:
        """ingest_reasoning 默认 False：对 DeepSeek 推理系列显式关 thinking。

        覆盖任意 OpenAI 兼容端点（官方 api.deepseek.com 与火山方舟 ark 等）：
        结构化输出（JSON 契约）在推理模型上会被长思考拖慢甚至吞页，与
        ingest_reasoning 默认关闭的设计一致。Ollama 走 reasoning_effort。
        """
        if ":11434" in base_url:  # Ollama
            body["reasoning_effort"] = "medium" if ingest_reasoning else "none"
            return
        if not ingest_reasoning and re.search(r"deepseek-v[4-9]", model):
            body["thinking"] = {"type": "disabled"}

    def parse_stream_line(self, raw_line: str) -> StreamEvent | None:
        line = raw_line.strip()
        if not line.startswith("data:"):
            return None
        data = line[5:].strip()
        if not data or data == "[DONE]":
            return None
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        err = payload.get("error")
        if err is not None:  # 流中错误信封
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise LlmError(f"LLM 流式响应返回错误: {msg}")
        event = StreamEvent()
        if isinstance(payload.get("usage"), dict):
            event.usage = payload["usage"]
        choices = payload.get("choices") or []
        if choices and isinstance(choices[0], dict):
            choice = choices[0]
            if isinstance(choice.get("finish_reason"), str):
                event.finish_reason = choice["finish_reason"]
            delta = choice.get("delta") or {}
            event.content = _extract_text(delta.get("content"))
        return event if (event.content or event.usage or event.finish_reason) else None

    def parse_response(self, payload: dict) -> LlmResult:
        choices = payload.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            raise LlmError("LLM 响应缺少 choices")
        message = choices[0].get("message") or {}
        content = _extract_text(message.get("content")) or ""
        if not content:
            raise LlmError("LLM 返回空响应（检查端点/Key/模型名）")
        return LlmResult(content=content, usage=payload.get("usage"),
                         stop_reason=choices[0].get("finish_reason"))


def _extract_text(content: Any) -> str | None:
    """delta/message.content 兼容：str 直取；blocks 数组拼接 text。"""
    if isinstance(content, str):
        return content or None
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content
                 if isinstance(b, dict) and isinstance(b.get("text"), str)]
        joined = "".join(parts)
        return joined or None
    return None


def has_usable_llm(config: Config) -> bool:
    """base_url + model + LLM_API_KEY 齐备才可用（Key 不落日志，NFR-201）。"""
    return bool(config.get("compile.llm.base_url") and config.get("compile.llm.model")
                and config.secret("LLM_API_KEY"))


def stream_chat(config: Config, messages: list[dict], *, overrides: dict | None = None,
                stop_event: Any = None, provider: Provider | None = None) -> LlmResult:
    """唯一入口：OpenAI 兼容流式对话（streaming=false 时走普通请求）。

    overrides 支持 temperature/top_p/max_tokens/stop；temperature 缺省取配置值。
    stop_event（threading.Event）置位时中断并抛 StreamCancelled。
    """
    base_url = config.get("compile.llm.base_url") or ""
    model = config.get("compile.llm.model") or ""
    api_key = config.secret("LLM_API_KEY") or ""
    if not (base_url and model and api_key):
        raise LlmError("LLM 未配置：需要 compile.llm.base_url、compile.llm.model 与 .env LLM_API_KEY")
    provider = provider or OpenAICompatProvider()
    streaming = bool(config.get("compile.llm.streaming", True))
    final_overrides = dict(overrides or {})
    final_overrides.setdefault(
        "temperature", float(config.get("compile.llm.temperature", 0.7)))
    ingest_reasoning = bool(config.get("compile.llm.ingest_reasoning", False))
    url, headers, body = provider.build_request(
        base_url, api_key, model, messages, stream=streaming,
        overrides=final_overrides, ingest_reasoning=ingest_reasoning)

    timeout_min = float(config.get("compile.llm.request_timeout_min", 30))
    deadline = time.monotonic() + timeout_min * 60

    def _post(payload: dict) -> requests.Response:
        try:
            return requests.post(url, headers=headers, json=payload,
                                 stream=streaming, timeout=(30, 300))
        except requests.RequestException as e:
            raise LlmConnectionError(f"无法连接 LLM 端点 {url}: {e}") from e

    resp = _post(body)
    if resp.status_code == 429:
        resp.close()
        raise RateLimitedError(_http_error(resp, url, "限流（429）"))
    if resp.status_code in (400, 422) and body.get("temperature") is not None:
        text = _safe_text(resp)
        resp.close()
        if re.search(r"temperature", text, re.IGNORECASE):
            # 端点不接受该温度（如 Kimi 固定 1）：去温度重试一次
            body = {k: v for k, v in body.items() if k != "temperature"}
            resp = _post(body)
    if resp.status_code != 200:
        resp.close()
        raise LlmError(_http_error(resp, url, f"HTTP {resp.status_code}"))

    if not streaming:
        try:
            return provider.parse_response(resp.json())
        finally:
            resp.close()

    parts: list[str] = []
    usage: dict | None = None
    finish_reason: str | None = None
    reasoning_chars = 0
    try:
        for raw in resp.iter_lines(chunk_size=1024):
            if stop_event is not None and stop_event.is_set():
                raise StreamCancelled("LLM 流式请求被取消")
            if time.monotonic() > deadline:
                raise LlmError(f"LLM 请求超时（超过 {timeout_min:.0f} 分钟）")
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace")
            reasoning_chars += count_reasoning_chars(line)
            event = provider.parse_stream_line(line)
            if event is None:
                continue
            if event.usage:
                usage = event.usage
            if event.finish_reason:
                finish_reason = event.finish_reason
            if event.content:
                parts.append(event.content)
    except (StreamCancelled, LlmError):
        raise
    except requests.RequestException as e:
        raise LlmConnectionError(f"LLM 流式读取中断: {e}") from e
    finally:
        resp.close()

    content = "".join(parts)
    if not content:
        if reasoning_chars >= REASONING_ONLY_THRESHOLD:
            raise LlmError(
                f"模型只输出了 {reasoning_chars} 字符的思考内容、没有最终回答"
                "（保持 compile.llm.ingest_reasoning=false；或增大 max_tokens）")
        raise LlmError("LLM 返回空响应（检查端点/Key/模型名）")
    return LlmResult(content=content, usage=usage, stop_reason=finish_reason)


def _safe_text(resp: requests.Response) -> str:
    try:
        return resp.text
    except Exception:  # noqa: BLE001
        return ""


def _http_error(resp: requests.Response, url: str, prefix: str) -> str:
    """错误消息只含状态与响应体片段，不含请求头（NFR-201 Key 不落日志）。"""
    text = _safe_text(resp)[:500]
    return f"LLM {prefix} @ {url}: {text}"
