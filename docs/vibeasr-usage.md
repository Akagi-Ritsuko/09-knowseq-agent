# VibeASR.cpp（VibeVoice-ASR-BitNet）使用文档

> 会议音频本地转写引擎。纯 CPU 实时（RTF < 1），无需 GPU。
> 方案背景见 [ADR-014](adr/ADR-014-vibevoice-asr.md)；接入实现对应 REQ-104 / T-104。

## 1. 环境组成

| 组件 | 路径 | 说明 |
|---|---|---|
| 引擎可执行文件 | `D:\tools\VibeASR.cpp\build\bin\asr_infer.exe` | 约 3.1MB，已构建验证 |
| 引擎源码 | `D:\tools\VibeASR.cpp` | github.com/microsoft/VibeASR.cpp，含 `3rdparty/llama.cpp` 子模块（vibeasr-dev 分支） |
| 模型目录 | `models/vibeasr/` | 两个 gguf 文件（共约 1.6GB），来源 HF `microsoft/VibeVoice-ASR-BitNet` |
| 工具链 | `D:\tools\winlibs\mingw64\bin` | WinLibs MinGW-w64（GCC 16.1.0 UCRT），已加入用户 PATH |
| CMake | 4.4.3（系统 PATH） | ≥3.14 即可 |

模型文件：

```
models/vibeasr/
├── vibeasr-vae-encoder-i8_s.gguf     # VAE 编码器（I8_S 量化，~703MB）
└── vibeasr-lm-i2_s-embed-q6_k.gguf   # LM（BitNet 三值 I2_S，~992MB）
```

## 2. 快速开始

```powershell
# 转写一个 WAV 文件（中文/英文均可，任意采样率自动重采样至 24kHz）
D:\tools\VibeASR.cpp\build\bin\asr_infer.exe `
  --vae-model models/vibeasr/vibeasr-vae-encoder-i8_s.gguf `
  --lm-model  models/vibeasr/vibeasr-lm-i2_s-embed-q6_k.gguf `
  --audio test_zh.wav `
  -t 8 --greedy
```

输出为纯文本转写结果（stdout），stderr 输出耗时统计。

**本机实测**（9.5 秒中文音频，8 线程）：

| 阶段 | 耗时 |
|---|---|
| VAE 编码（声学 + 语义） | 4.08s |
| LM prefill（118 tok） | 0.57s |
| LM decode（24 tok） | 1.55s |
| **总计** | 7.55s → **RTF 0.79** |

## 3. 完整参数表（asr_infer --help）

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--vae-model <path>` | 必填 | VAE 编码器 gguf 路径 |
| `--lm-model <path>` | 必填 | LM gguf 路径 |
| `--audio <path>` | 必填 | 输入 WAV 文件路径 |
| `-t <n>` | 4 | 线程数（建议 = 物理核数） |
| `-c <n>` | 16384 | 上下文大小 |
| `-b <n>` | 2048 | batch 大小 |
| `--max-tokens <n>` | 16384 | 最大生成 token 数 |
| `--greedy` | 关 | 贪心解码（默认采样） |
| `--temperature <f>` | 0.7 | 采样温度 |
| `--top-p <f>` | 0.9 | top-p 采样 |
| `--sample-rate <n>` | 24000 | 目标采样率（引擎内部重采样） |
| `--compress-ratio <n>` | 3200 | 语音压缩比 |
| `--context <text>` | 空 | 热词/上下文提示，可提高专有名词识别准确率 |
| `--prompt-format <s>` | text | 输出格式：`text`（纯文本）或 `json`（带 keys，可含 speaker/timestamps 字段） |
| `--no-normalize` | 关 | 关闭音频归一化 |

## 4. 常用场景

### 4.1 带热词转写（提高人名/术语准确率）

```powershell
asr_infer.exe --vae-model ... --lm-model ... --audio meeting.wav `
  -t 8 --greedy --context "项目名 KnowSeq，参会人：张三、李四"
```

### 4.2 结构化输出（JSON，含 keys）

```powershell
asr_infer.exe ... --prompt-format json
```

> ADR-014 中 Speaker/Timestamps 字段以引擎实际输出为准（T-113 待实测确认，用 json 格式验证）。

### 4.3 长音频

引擎按 `--compress-ratio`（默认 3200）压缩语音特征，长会议音频直接传入即可；
RTF 约 0.8，即 1 小时会议约 45-50 分钟转写完成。对实时性要求高时可增大 `-t`。

## 5. 从源码重建（如需）

```powershell
cmake -S D:\tools\VibeASR.cpp -B D:\tools\VibeASR.cpp\build `
  -G "MinGW Makefiles" `
  -DCMAKE_BUILD_TYPE=Release `
  -DCMAKE_C_COMPILER=gcc -DCMAKE_CXX_COMPILER=g++ `
  -DCMAKE_MAKE_PROGRAM=mingw32-make `
  -DGGML_CCACHE=OFF

cmake --build D:\tools\VibeASR.cpp\build --target asr_infer -j 8
```

注意：

- **不支持 MSVC**，必须 GCC/Clang（MinGW-w64，推荐 WinLibs UCRT 版）。
- **务必加 `-DGGML_CCACHE=OFF`**：本机 ccache + MinGW 组合会挂起（无产物、无 gcc 子进程），已实测踩坑。
- 构建产物在 `build\bin\asr_infer.exe`。

## 6. 子进程集成约定（供 T-104 / `meeting_source` 实现）

```python
cmd = [
    engine_path,                    # config.yaml: sources.meeting.engine_path
    "--vae-model", vae_gguf,
    "--lm-model", lm_gguf,
    "--audio", wav_path,
    "-t", "8",
    "--greedy",
    # 可选: "--prompt-format", "json"
]
proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
transcript = proc.stdout.strip()    # 转写文本 → write_material(source=meeting) → inbox/meeting/
```

- stdout = 转写结果；stderr = 性能日志（不入库，仅 debug 用）。
- 引 exe 依赖 MinGW 运行时 DLL，`D:\tools\winlibs\mingw64\bin` 已在用户 PATH；
  若部署到无此 PATH 的环境，可将 `libgcc_s_seh-1.dll`、`libstdc++-6.dll`、`libwinpthread-1.dll`
  拷贝到 asr_infer.exe 同目录。

## 7. 常见问题

| 现象 | 原因/解决 |
|---|---|
| 报错找不到 DLL | 运行时 PATH 缺 MinGW 运行时，见第 6 节说明 |
| 构建卡住无产物 | ccache 挂起，加 `-DGGML_CCACHE=OFF` 重配 |
| 转写结果为空 | 检查 WAV 是否有效 PCM；非 WAV 格式先转 WAV（引擎只读 WAV） |
| 中文识别为繁体/简体混杂 | 用 `--greedy`；必要时 `--context` 提供领域词 |
