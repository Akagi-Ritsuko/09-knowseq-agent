"""会议音频转写源（T-104 REQ-104 / ADR-014）。

子进程调用 VibeASR.cpp 的 asr_infer CLI（VibeVoice-ASR-BitNet，本地 CPU 推理），
把拖入热文件夹（drop）的会议/通话录音转写为文本，写入 inbox/meeting/。

引擎与模型为外部可选组件（Windows 构建需 MinGW-w64），不进 Python 依赖；
未就绪时本源置 error 并给出明确提示，不影响其他采集源。
转写输出 schema 以引擎实际输出为准（说话人/时间戳字段待实测，见 T-113）。
"""
import json
import os
import subprocess
import threading
import wave
from pathlib import Path

from .base import CaptureSource

ROOT = Path(__file__).resolve().parent.parent.parent
POLL_INTERVAL = 10  # 热文件夹轮询间隔（秒）
AUDIO_EXTS = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac"}
THREADS = "4"  # asr_infer CPU 线程数（ADR-014：4 线程 RTF<1）


class MeetingSource(CaptureSource):
    name = "meeting"

    def __init__(self, config, inbox):
        super().__init__(config, inbox)
        self._state_path = inbox.root / ".meeting_state.json"
        self._processed: set = self._load_state()
        self._failed: set = set()  # 本次会话内失败的文件不重试；重启后自动重试

    # ---- 配置 ----
    def _engine_path(self) -> Path:
        return self._resolve(Path(self.config.get("sources.meeting.engine_path", "")))

    def _model_dir(self) -> Path:
        return self._resolve(Path(self.config.get("sources.meeting.model_dir", "")))

    @staticmethod
    def _resolve(p: Path) -> Path:
        return p if p.is_absolute() else ROOT / p

    def _hot_dirs(self) -> list[Path]:
        return [self.config.drop_dir]

    # ---- 引擎就绪探测 ----
    def engine_ready(self) -> tuple[bool, str]:
        exe = self._engine_path()
        if not exe.is_file():
            return False, (f"未找到 VibeASR.cpp 引擎可执行文件: {exe}"
                           "（需按 ADR-014 用 MinGW-w64 构建后配置 sources.meeting.engine_path）")
        mdir = self._model_dir()
        vae, lm = self._model_files()
        if not vae or not lm:
            return False, (f"模型目录缺少 gguf（vae/lm）: {mdir}"
                           "（huggingface-cli download microsoft/VibeVoice-ASR-BitNet --local-dir "
                           f"{mdir}）")
        return True, ""

    def _model_files(self) -> tuple[Path | None, Path | None]:
        mdir = self._model_dir()
        if not mdir.is_dir():
            return None, None
        vae = sorted(mdir.glob("*vae*.gguf"))
        lm = sorted(mdir.glob("*lm*.gguf"))
        return (vae[0] if vae else None, lm[0] if lm else None)

    # ---- 状态文件 ----
    def _load_state(self) -> set:
        try:
            with open(self._state_path, encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:  # noqa: BLE001
            return set()

    def _save_state(self) -> None:
        try:
            with open(self._state_path, "w", encoding="utf-8") as f:
                json.dump(sorted(self._processed), f, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            pass

    # ---- 转写 ----
    def _transcribe(self, audio: Path) -> str:
        exe = self._engine_path()
        vae, lm = self._model_files()
        cmd = [str(exe), "--vae-model", str(vae), "--lm-model", str(lm),
               "--audio", str(audio), "-t", THREADS]
        kwargs: dict = {"capture_output": True, "text": True,
                        "encoding": "utf-8", "errors": "replace"}
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW，避免弹出控制台
        proc = subprocess.run(cmd, **kwargs)  # noqa: S603
        if proc.returncode != 0:
            raise RuntimeError(f"asr_infer 失败（exit {proc.returncode}）: "
                               f"{(proc.stderr or proc.stdout or '').strip()[:500]}")
        out = (proc.stdout or "").strip()
        if not out:
            raise RuntimeError("asr_infer 无输出")
        return out

    @staticmethod
    def _format(raw: str) -> str:
        """输出 schema 以引擎实际为准：JSON 则原样代码块展示，否则当纯文本。"""
        try:
            data = json.loads(raw)
        except Exception:  # noqa: BLE001
            return raw
        return ("```json\n"
                + json.dumps(data, ensure_ascii=False, indent=2) + "\n```")

    @staticmethod
    def _duration(audio: Path) -> float | None:
        if audio.suffix.lower() != ".wav":
            return None
        try:
            with wave.open(str(audio), "rb") as w:
                return round(w.getnframes() / w.getframerate(), 1)
        except Exception:  # noqa: BLE001
            return None

    def _ingest(self, p: Path, key: str) -> None:
        try:
            raw = self._transcribe(p)
        except Exception as e:  # noqa: BLE001
            self._failed.add(key)
            self.status = "error"
            self.error = f"{p.name}: {e}"
            return  # 转写失败不落空文件（REQ-104）
        content = self._format(raw)
        if not content:
            return
        written = self.inbox.write_material(
            "meeting", p.stem, content,
            meta={"audio": str(p),
                  "duration_sec": self._duration(p),
                  "engine": str(self._engine_path()),
                  "model_dir": str(self._model_dir())},
            dedup=False)
        if written:
            self._processed.add(key)
            self._save_state()

    def _is_stable(self, p: Path) -> bool:
        try:
            s1 = p.stat().st_size
            self._stop_event.wait(0.5)
            s2 = p.stat().st_size
        except OSError:
            return False
        return s1 == s2

    # ---- 扫描热文件夹 ----
    def _scan(self) -> None:
        for d in self._hot_dirs():
            if not d.is_dir():
                continue
            for p in sorted(d.iterdir()):
                if not p.is_file() or p.suffix.lower() not in AUDIO_EXTS:
                    continue
                key = str(p.resolve())
                if key in self._processed or key in self._failed:
                    continue
                if not self._is_stable(p):
                    continue  # 仍在写入，等下一轮
                self._ingest(p, key)

    def _work(self, stop_event) -> None:
        ok, msg = self.engine_ready()
        if not ok:
            self.status = "error"
            self.error = msg
            return
        self.status = "running"
        self.error = ""
        while not stop_event.is_set():
            try:
                self._scan()
                self.status = "running"
            except Exception as e:  # noqa: BLE001
                self.status = "error"
                self.error = str(e)
            finally:
                stop_event.wait(POLL_INTERVAL)

    def info(self) -> dict:
        """状态聚合：额外携带引擎就绪状态（REQ-408 meeting 源展示）。"""
        ok, hint = self.engine_ready()
        return {**super().info(), "engine_ready": ok, "engine_hint": hint}

    def start(self):
        if self.status == "running":
            return
        if not self.enabled():
            self.status = "stopped"
            return
        self._spawn(self._work)

    def stop(self):
        super().stop()
        # 转写中的子进程随线程结束后由系统回收；M1 不做进程级强杀
