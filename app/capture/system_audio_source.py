"""系统声音捕获源（T-501 REQ-501 / ADR-017）。

用 pyaudiowpatch 抓默认输出设备 WASAPI loopback（系统播放的全部声音，
如会议软件扬声器输出），定长分段落 wav（默认 5 分钟/段，可配），
按序入队列由转写线程消费——完全复用 MeetingSource 的 asr_infer 子进程
转写链路，产物写入 inbox/meeting/，meta.capture = "system-audio" 标记。

双线程解耦：录音线程只分段落盘；转写线程按序消费队列。
转写耗时（RTF<1 但非零）不阻塞录音，不会漏音频。
stop 时收尾当前未满段入队，转写线程清空队列后退出（最后一段落稿）。
默认输出设备切换时自动关闭当前段并重建捕获流。
include_mic 可选混入默认麦克风（默认 false，numpy 线性重采样对齐采样率）。

实现要点：WASAPI loopback 在系统无活跃 render 流时不产生数据（read 阻塞），
故向默认输出设备并行 render 一条静音「哨兵流」保持音频引擎活跃，使分段、
设备探测与 stop 收尾在静音期同样可靠（思路参考 Meetily 的 WASAPI 采集方案，
Reference: Zackriya-Solutions/meetily (MIT)）。
"""
import datetime
import queue
import threading
import wave
from pathlib import Path

from .base import CaptureSource
from .meeting_source import MeetingSource

try:
    import pyaudiowpatch as pyaudio
except ImportError:  # 依赖未安装时保持可导入，start 时置 error 降级
    pyaudio = None

CHUNK = 1024  # 循环回放流每次读取帧数
DEVICE_CHECK_FRAMES = 100  # 默认输出设备探测间隔（约 100 CHUNK ≈ 2 秒）
SILENCE_PEAK = 100  # 段峰值幅度低于此值视为纯静音（跳过转写：asr_infer 对静音无输出）


class SystemAudioSource(MeetingSource):
    name = "system_audio"

    def __init__(self, config, inbox):
        # 显式走基类 __init__：跳过 MeetingSource 的热文件夹状态（本源不扫 drop）
        CaptureSource.__init__(self, config, inbox)
        self._queue: queue.Queue = queue.Queue()
        self._seg_dir = inbox.root / ".system_audio"  # 临时分段 wav（inbox 源扫描范围外）
        self._seg_count = 0  # 段序号（仅录音线程读写，设备切换后保持连续）

    # ---- 生命周期 ----
    def start(self):
        if self.status == "running":
            return
        if not self.enabled():
            self.status = "stopped"
            return
        ok, msg = self.engine_ready()
        if not ok:
            self.status = "error"  # 引擎/模型未就绪：error 降级，不影响其他源
            self.error = msg
            return
        self._queue = queue.Queue()  # 新一轮新队列；旧转写线程持有旧引用清空后退出
        self._spawn(self._work)

    def stop(self):
        CaptureSource.stop(self)
        # 录音线程检测 stop_event → 收尾当前未满段入队；
        # 转写线程按序清空队列后退出（最后一段完成转写落稿）。

    def _work(self, stop_event) -> None:
        self._seg_count = 0
        started = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._seg_dir.mkdir(parents=True, exist_ok=True)
        q = self._queue
        rec = threading.Thread(target=self._record_loop,
                               args=(stop_event, q, started),
                               name="capture-system_audio-rec", daemon=True)
        tr = threading.Thread(target=self._transcribe_loop, args=(stop_event, q),
                              name="capture-system_audio-asr", daemon=True)
        rec.start()
        tr.start()
        rec.join()
        tr.join()

    # ---- 录音线程 ----
    def _record_loop(self, stop_event, q: queue.Queue, started: str) -> None:
        seg_seconds = max(30, int(self.config.get("sources.system_audio.segment_seconds", 300)))
        include_mic = bool(self.config.get("sources.system_audio.include_mic", False))
        if pyaudio is None:
            self.status = "error"
            self.error = "未安装 pyaudiowpatch（pip install pyaudiowpatch）"
            return
        pa = pyaudio.PyAudio()
        try:
            while not stop_event.is_set():
                lb = self._open_loopback(pa)
                if lb is None:
                    self.status = "error"
                    self.error = "未找到默认输出设备的 WASAPI loopback 设备"
                    return
                mic = self._open_mic(pa) if include_mic else None
                sent = self._open_sentinel(pa)
                if sent is None:
                    self.status = "error"
                    self.error = "无法打开默认输出设备（WASAPI 共享模式哨兵流），loopback 无法稳定采集"
                    return
                self.status = "running"
                self.error = ""
                try:
                    # 返回即设备切换（部分段已收尾入队）或 stop；外层循环重建流
                    self._capture_stream(pa, lb, sent, mic, seg_seconds,
                                         started, stop_event, q)
                finally:
                    if mic is not None:
                        try:
                            mic[0].close()
                        except Exception:  # noqa: BLE001
                            pass
                    try:
                        sent[0].close()
                    except Exception:  # noqa: BLE001
                        pass
        finally:
            pa.terminate()

    def _capture_stream(self, pa, lb_dev: dict, sent, mic, seg_seconds: int,
                        started: str, stop_event, q: queue.Queue) -> None:
        """在单个 loopback 设备上录音：分段落盘；设备切换/stop 时收尾部分段。

        sent = (哨兵输出流, 静音帧)：录音循环中持续 render 静音保持引擎活跃。
        """
        rate = int(lb_dev["defaultSampleRate"])
        ch = int(lb_dev["maxInputChannels"])
        seg_frames = seg_seconds * rate
        stream = pa.open(format=pyaudio.paInt16, channels=ch, rate=rate,
                         input=True, input_device_index=int(lb_dev["index"]),
                         frames_per_buffer=CHUNK)
        wf = None
        path = None
        n_in_seg = 0
        n_reads = 0
        try:
            while not stop_event.is_set():
                if wf is None:
                    path = self._seg_dir / f"system_audio_{started}_seg{self._seg_count:03d}.wav"
                    self._seg_count += 1
                    wf = wave.open(str(path), "wb")
                    wf.setnchannels(ch)
                    wf.setsampwidth(2)
                    wf.setframerate(rate)
                    n_in_seg = 0
                data = stream.read(CHUNK, exception_on_overflow=False)
                try:
                    sent[0].write(sent[1])  # 哨兵续静音（写失败不阻断录音）
                except Exception:  # noqa: BLE001
                    pass
                if mic is not None:
                    data = self._mix_mic(data, rate, ch, mic)
                wf.writeframes(data)
                n_in_seg += CHUNK
                n_reads += 1
                # 默认输出设备切换探测（降频，约 2 秒一次）。
                # 注意：loopback 是虚拟设备，index 与真实输出设备不同——
                # 必须重新解析「当前默认输出对应的 loopback」再比对 index。
                if n_reads % DEVICE_CHECK_FRAMES == 0:
                    cur = self._open_loopback(pa)
                    if cur is not None and int(cur["index"]) != int(lb_dev["index"]):
                        self._close_segment(wf, path, q)
                        wf = path = None
                        return  # 外层循环重建捕获流
                # 段满 → 依序落盘转写
                if n_in_seg >= seg_frames:
                    self._close_segment(wf, path, q)
                    wf = path = None
            # stop：收尾当前未满段（REQ-501）
            if wf is not None:
                self._close_segment(wf, path, q)
                wf = path = None
        finally:
            if wf is not None:
                try:
                    wf.close()
                except Exception:  # noqa: BLE001
                    pass
            try:
                stream.close()
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _close_segment(wf: wave.Wave_write, path: Path, q: queue.Queue) -> None:
        """关闭当前段并入队转写；空段（仅 44 字节 wav 头）跳过。"""
        try:
            wf.close()
        finally:
            try:
                if path.exists() and path.stat().st_size > 44:
                    q.put(path)
            except OSError:
                pass

    # ---- 设备定位 ----
    @staticmethod
    def _open_loopback(pa):
        """定位默认输出设备对应的 WASAPI loopback 设备。"""
        default_name = ""
        try:
            wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_out = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
            default_name = default_out.get("name", "")
            if default_out.get("isLoopbackDevice"):
                return default_out
        except Exception:  # noqa: BLE001
            pass
        try:
            for lb in pa.get_loopback_device_info_generator():
                if default_name and default_name in lb["name"]:
                    return lb
            return next(iter(pa.get_loopback_device_info_generator()))
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _open_sentinel(pa):
        """静音哨兵流：向默认输出设备 render 静音，保持 WASAPI 共享模式引擎活跃。

        无活跃 render 流时 loopback capture 不产生数据（read 阻塞），
        哨兵使分段、设备探测与 stop 收尾在静音期同样可靠。
        思路参考：Reference: Zackriya-Solutions/meetily (MIT)
        """
        try:
            out = pa.get_device_info_by_index(
                pa.get_host_api_info_by_type(pyaudio.paWASAPI)["defaultOutputDevice"])
            ch = int(out["maxOutputChannels"])
            rate = int(out["defaultSampleRate"])
            stream = pa.open(format=pyaudio.paInt16, channels=ch, rate=rate,
                             output=True, output_device_index=int(out["index"]),
                             frames_per_buffer=CHUNK)
            silence = b"\x00\x00" * (CHUNK * ch)
            return (stream, silence)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _open_mic(pa):
        """打开默认输入设备（单声道）；失败返回 None 并跳过混音，不阻塞主流程。"""
        try:
            info = pa.get_default_input_device_info()
            rate = int(info["defaultSampleRate"])
            stream = pa.open(format=pyaudio.paInt16, channels=1, rate=rate,
                             input=True, input_device_index=int(info["index"]),
                             frames_per_buffer=CHUNK)
            return (stream, rate)
        except Exception:  # noqa: BLE001
            return None

    # ---- 麦克风混音 ----
    @staticmethod
    def _mix_mic(data: bytes, lb_rate: int, lb_ch: int, mic) -> bytes:
        """麦克风混入 loopback：线性重采样对齐采样率、复制声道、逐样本相加截幅。"""
        import numpy as np

        stream, mic_rate = mic
        mic_frames = max(1, int(CHUNK * mic_rate / lb_rate))
        try:
            mic_data = stream.read(mic_frames, exception_on_overflow=False)
        except Exception:  # noqa: BLE001
            return data
        mic_np = np.frombuffer(mic_data, dtype=np.int16).astype(np.float32)
        if mic_np.size == 0:
            return data
        loop = np.frombuffer(data, dtype=np.int16).astype(np.float32).reshape(-1, lb_ch)
        n_out = loop.shape[0]
        if mic_np.size > 1:
            mic_rs = np.interp(np.linspace(0.0, mic_np.size - 1, n_out),
                               np.arange(mic_np.size), mic_np)
        else:
            mic_rs = np.full(n_out, float(mic_np[0]))
        out = np.clip(loop + np.repeat(mic_rs[:, None], lb_ch, axis=1),
                      -32767.0, 32767.0).astype(np.int16)
        return out.tobytes()

    # ---- 转写线程 ----
    def _transcribe_loop(self, stop_event, q: queue.Queue) -> None:
        """按序消费段队列转写；stop 后清空队列退出（保证最后一段落稿）。"""
        while True:
            try:
                path = q.get(timeout=1.0)
            except queue.Empty:
                if stop_event.is_set():
                    return
                continue
            self._ingest_segment(path)

    @staticmethod
    def _is_silent(p: Path) -> bool:
        """段峰值幅度检测：纯静音段（峰值 < SILENCE_PEAK）无语音内容。

        会议中的静默期属正常现象，纯静音输入会让 asr_infer 无输出而误报
        error——此处跳过转写，避免误报并省去无效推理。
        """
        try:
            import numpy as np

            with wave.open(str(p)) as wf:
                raw = wf.readframes(wf.getnframes())
            if not raw:
                return True
            peak = int(np.abs(np.frombuffer(raw, dtype=np.int16)).max())
            return peak < SILENCE_PEAK
        except Exception:  # noqa: BLE001
            return False  # 检测失败按非静音处理，走正常转写链路

    def _ingest_segment(self, p: Path) -> None:
        """转写单个分段 wav → write_material(source=meeting) → 成功后删 wav 控磁盘。"""
        try:
            if self._is_silent(p):  # 纯静音段：无语音内容，跳过转写直接清理
                p.unlink(missing_ok=True)
                return
            raw = self._transcribe(p)
            content = self._format(raw)
        except Exception as e:  # noqa: BLE001
            # 转写失败：保留 wav 排查，仅记 error，不覆盖 running 状态（REQ-501）
            self.error = f"{p.name}: {e}"
            return
        if not content:
            return
        self.inbox.write_material(
            "meeting", p.stem, content,
            meta={"capture": "system-audio",
                  "audio": str(p),
                  "duration_sec": self._duration(p),
                  "engine": str(self._engine_path()),
                  "model_dir": str(self._model_dir())},
            dedup=False)
        try:
            p.unlink()
        except OSError:
            pass

    def info(self) -> dict:
        # 继承 MeetingSource：聚合 engine_ready/engine_hint（采集页引擎 chip 展示）
        return {**super().info()}
