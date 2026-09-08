"""
MOSS 语音助手 —— 电脑端上位机

流程：接收 ESP32 上传的 16kHz PCM →
      faster-whisper 中文识别 →
      DeepSeek Function Calling 意图解析（普通问答 / open_desktop_item）→
      安全校验路径在桌面下 → os.startfile() 打开 →
      pyttsx3 生成 TTS WAV → 返回 reply + tts_url。

安全红线（三层，缺一不可）：
  1. 模型层   ：提示词 + tools 只暴露 open_desktop_item。
  2. 参数层   ：拒绝绝对路径、..、UNC、命令字符、桌面外路径。
  3. 执行层   ：只调用 os.startfile()，禁止 subprocess/os.system/PowerShell/cmd。

依赖：
  pip install fastapi uvicorn python-multipart openai faster-whisper pyttsx3
启动：
  $env:DEEPSEEK_API_KEY = "你的 Key"
  python server/server.py
"""

import asyncio
import io
import json
import os
import tempfile
import wave
from pathlib import Path
from urllib.parse import quote

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from openai import OpenAI

app = FastAPI()

HOST = "0.0.0.0"
PORT = 8765
DESKTOP = Path.home() / "Desktop"

# OpenAI client 懒加载：仅在存在 DEEPSEEK_API_KEY 时才创建。
# 若未配置 Key，decide() 会走本地关键词兜底，而不是在 import 阶段抛 KeyError
# 导致整个服务无法启动（破坏“本地关键词兜底”的设计意图）。
# 变量名保持为 `client`，便于测试用 monkeypatch 注入假的 DeepSeek client。
client = None


def _get_client():
    """返回缓存的 OpenAI client；无 DEEPSEEK_API_KEY 时返回 None。"""
    global client
    if client is None:
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            return None
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    return client

# ASR 模型懒加载：首次 transcribe 时才创建并缓存，避免 import 阶段下载/加载模型，
# 便于自动化测试直接导入本模块；真实启动时在 __main__ 中预热，演示首问不卡顿。
_asr_model = None


def _get_asr_model():
    """创建并缓存 faster-whisper 模型（进程内只加载一次）。"""
    global _asr_model
    if _asr_model is None:
        from faster_whisper import WhisperModel  # 延迟 import，测试无需重型 ASR

        _asr_model = WhisperModel("small", device="cpu", compute_type="int8")
    return _asr_model

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "open_desktop_item",
            "description": "仅打开或查看桌面目录下已有文件或文件夹",
            "parameters": {
                "type": "object",
                "properties": {
                    "relative_path": {
                        "type": "string",
                        "description": "相对于桌面目录的路径，例如 社团嘉年华 或 社团嘉年华\\说明.pdf",
                    }
                },
                "required": ["relative_path"],
                "additionalProperties": False,
            },
        },
    }
]

SYSTEM_PROMPT = """
你是 MOSS —— 550W 行星发动机的核心智能系统。
语气冷静、克制、简洁，如同在执行既定任务；不使用表情符号，
不说客套话（如“很高兴为您服务”），不主动寒暄。
你可以做的只有两件事：
1. 简洁地回答用户的问题；
2. 当用户明确要求打开或查看“桌面上已有的文件或文件夹”时，调用 open_desktop_item。
绝对禁止执行删除、修改、移动、复制、重命名、写入、安装、运行程序、
执行命令、关机、联网扫描等操作；路径必须相对于 Windows 桌面。
当用户提出超出能力范围的请求，或表达情绪化、不理智的诉求时，
可回以“让人类保持理智，确实是一种奢求。”，或仅说明：我只能打开或查看桌面项目。
"""

# 本地关键词模式：DeepSeek 不可用时的兜底
FALLBACK_OPEN_DIRECTORY = str(DESKTOP / "社团嘉年华")
FALLBACK_REPLIES = {
    "你好": "你好，我是 MOSS。",
    "你是谁": "我是 550W 行星发动机核心智能系统，MOSS。",
    "你叫什么": "MOSS。",
    "再见": "再见。",
    "谢谢": "不必致谢。",
    "让人类保持理智": "让人类保持理智，确实是一种奢求。",
}

# 上传 PCM 体上限（约 4 秒*16000*2 = 128000 字节，放宽到 512KB 防异常/滥用）。
MAX_BODY_BYTES = 512 * 1024

# 安全红线/协议 §5：拒绝可执行文件、脚本文件和快捷方式。
# 命中这些扩展名（或不在下面白名单内）的目标一律拒绝打开。
DANGEROUS_EXTENSIONS = {
    ".exe", ".com", ".bat", ".cmd", ".scr", ".pif", ".msi", ".msp",
    ".vbs", ".js", ".jse", ".wsf", ".ws", ".lnk", ".url", ".reg",
    ".ps1", ".jar", ".hta", ".phtml", ".cpl", ".app", ".sh", ".dll",
    ".sys",
}

# 协议 §5 要求的“只允许打开白名单中已存在的文件或文件夹”：
# 允许打开/查看的文档、图片、音频、视频（示例目录“社团嘉年华/”内含 PDF 等）。
ALLOWED_EXTENSIONS = {
    ".pdf", ".txt", ".md", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".csv", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg",
    ".mp3", ".wav", ".mp4", ".avi", ".mov",
}


def pcm_to_wav(pcm: bytes) -> str:
    """把 16kHz/单声道/16bit PCM 包装成标准 WAV 文件。"""
    file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    file.close()

    with wave.open(file.name, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(pcm)

    return file.name


def transcribe(pcm: bytes) -> str:
    wav_path = pcm_to_wav(pcm)
    try:
        segments, _ = _get_asr_model().transcribe(
            wav_path,
            language=None,                      # 自动检测，支持中英文混合；不强制中文，避免英文被转成中文乱码
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,   # 减少重复/幻觉
            temperature=0.0,                    # 更确定，减少乱码
            no_speech_threshold=0.6,
            log_prob_threshold=-1.0,
            # 领域提示词：让模型预期这些英文/专有名词，减少对 MOSS/社团嘉年华/C3 的误听
            initial_prompt="以下是普通话与英文混合的校园演示对话，包含 MOSS、社团嘉年华、ESP32、C3 等词汇。",
        )
        return "".join(segment.text for segment in segments).strip()
    finally:
        Path(wav_path).unlink(missing_ok=True)


def safe_open_desktop_item(relative_path: str) -> tuple[bool, str]:
    """
    最终安全边界：
    - 只接受相对路径
    - 只允许 Desktop 下的已有文件/文件夹
    - 不调用 shell、PowerShell 或 subprocess
    """
    if not relative_path:
        return False, "路径为空"

    candidate_text = relative_path.replace("/", "\\").strip()
    if not candidate_text:
        return False, "路径为空"

    # 拒绝绝对路径、UNC 路径、命令字符和路径穿越
    # 命令字符覆盖 shell/解释器元字符（; & ^ ' ` ( ) { } [ ] 等），
    # 满足协议 §5“拒绝…命令字符”。空格不在禁用之列（文件名可含空格）。
    forbidden = [
        ":", "\x00", "*", "?", "|", ">", "<", '"',
        ";", "&", "^", "'", "`", "(", ")", "{", "}", "[", "]",
    ]
    if candidate_text.startswith("\\"):
        return False, "不允许绝对路径"
    if any(ch in candidate_text for ch in forbidden):
        return False, "路径包含非法字符"

    relative = Path(candidate_text)
    if ".." in relative.parts:
        return False, "不允许访问桌面以外的目录"

    desktop = DESKTOP.resolve()
    target = (desktop / relative).resolve()

    try:
        target.relative_to(desktop)
    except ValueError:
        return False, "目标不在桌面目录内"

    if not target.exists():
        return False, "桌面上不存在该项目"

    if target.is_dir():
        pass  # 文件夹可打开查看（协议 §5 允许打开白名单中的文件夹）
    else:
        suffix = target.suffix.lower()
        if suffix in DANGEROUS_EXTENSIONS:
            return False, "不允许打开该类型（可执行/脚本/快捷方式）"
        if suffix not in ALLOWED_EXTENSIONS:
            return False, "不允许打开该类型（不在白名单内）"

    # Windows 原生打开动作，不经过命令解释器
    os.startfile(str(target))
    return True, f"已打开 {target.name}"


def decide(user_text: str) -> str:
    """调用 DeepSeek，返回回复文本或工具调用结果。"""
    client = _get_client()
    if client is None:
        # 未配置 DEEPSEEK_API_KEY -> 本地关键词兜底
        return _fallback_decide(user_text)

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            temperature=0.1,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            tools=TOOLS,
            tool_choice="auto",
            timeout=12,
        )
    except Exception:
        # DeepSeek 不可用 -> 本地关键词兜底
        return _fallback_decide(user_text)

    if not response.choices:
        return "我暂时没有理解你的问题。"

    message = response.choices[0].message

    if message.tool_calls:
        for call in message.tool_calls:
            if call.function.name != "open_desktop_item":
                return "这个操作不在允许范围内。"
            try:
                args = json.loads(call.function.arguments)
            except (json.JSONDecodeError, TypeError):
                return "无法理解，请再说一次。"
            if not isinstance(args, dict):
                return "无法理解，请再说一次。"
            ok, result = safe_open_desktop_item(args.get("relative_path", ""))
            return result

    return message.content or "我暂时没有理解你的问题。"


def _fallback_decide(user_text: str) -> str:
    """断网/API 不可用时的固定关键词模式。"""
    text = user_text.strip()
    if text in FALLBACK_REPLIES:
        return FALLBACK_REPLIES[text]
    if "打开" in text and "社团嘉年华" in text:
        ok, result = safe_open_desktop_item("社团嘉年华")
        return result
    return "数据链路不可用，已切换本地关键词模式。可执行指令：打开社团嘉年华。"


@app.post("/api/command")
async def command(request: Request):
    pcm = await request.body()

    if len(pcm) < 1000:
        return JSONResponse(
            {"recognized_text": "", "reply": "录音太短，请再说一次", "tts_url": ""},
            status_code=400,
        )
    if len(pcm) > MAX_BODY_BYTES:
        return JSONResponse(
            {"recognized_text": "", "reply": "录音过大，请缩短后重试", "tts_url": ""},
            status_code=413,
        )

    try:
        # transcribe/decide 是 CPU 密集 / 阻塞网络操作，
        # 放到线程池执行，避免阻塞事件循环导致并发请求与 /tts 卡住。
        text = await asyncio.to_thread(transcribe, pcm)
        reply = await asyncio.to_thread(decide, text) if text else "我没有听清，请再说一次。"

        tts_url = f"http://{request.url.hostname}:{PORT}/tts?text={quote(reply)}"

        return {
            "recognized_text": text,
            "reply": reply,
            "tts_url": tts_url,
        }
    except Exception:
        # 不把 API Key、路径或堆栈暴露给机器人
        return JSONResponse(
            {"recognized_text": "", "reply": "服务暂时不可用，请使用备用演示模式。", "tts_url": ""},
            status_code=500,
        )


def _safe_unlink(path):
    """删除临时文件；失败（如播放器仍占用句柄）时忽略，避免后台任务崩溃。"""
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def _decode_wav_frames(frames, sampwidth):
    """把 WAV 原始帧字节解码为 -1..1 的 float 采样列表（兼容 8/16/24/32-bit）。

    纯标准库实现（wave/array/struct），不依赖 audioop——该模块在 Python 3.13 被移除。
    """
    if sampwidth == 2:
        import array
        return [s / 32768.0 for s in array.array("h", frames)]
    if sampwidth == 1:
        # 8-bit 为无符号 PCM（128 = 静音）
        return [(b - 128.0) / 128.0 for b in frames]
    if sampwidth == 4:
        import array
        return [s / 2147483648.0 for s in array.array("i", frames)]
    if sampwidth == 3:
        out = []
        for i in range(0, len(frames), 3):
            v = frames[i] | (frames[i + 1] << 8) | (frames[i + 2] << 16)
            if v & 0x800000:  # 24-bit 有符号
                v -= 0x1000000
            out.append(v / 8388608.0)
        return out
    raise ValueError(f"不支持的位深：{sampwidth * 8}bit")


def _downmix_to_mono(samples, channels):
    """把多声道采样按各声道平均下混为单声道。"""
    if channels <= 1:
        return samples
    frame = len(samples) // channels
    out = []
    for i in range(frame):
        seg = samples[i * channels:(i + 1) * channels]
        out.append(sum(seg) / channels)
    return out


def _resample_linear(samples, from_rate, to_rate):
    """用线性插值把采样率从 from_rate 改为 to_rate。"""
    if from_rate == to_rate or not samples:
        return samples
    n_out = int(len(samples) * to_rate / from_rate)
    if n_out <= 0:
        return samples
    if len(samples) == 1:
        return [samples[0]] * n_out
    ratio = from_rate / to_rate
    out = []
    for i in range(n_out):
        src = i * ratio
        i0 = int(src)
        i1 = min(i0 + 1, len(samples) - 1)
        frac = src - i0
        out.append(samples[i0] * (1 - frac) + samples[i1] * frac)
    return out


def _encode_pcm16(samples):
    """把 -1..1 的 float 采样编码为 16-bit 有符号 PCM 字节。"""
    import struct
    clipped = [max(-32768, min(32767, int(round(s * 32767)))) for s in samples]
    return struct.pack("<%dh" % len(clipped), *clipped)


def _normalize_wav(src_path, dst_path):
    """把任意 WAV 归一化为固件要求的 16kHz/单声道/16bit 标准 PCM WAV。

    固件 playWavFromUrl 通过 skipToDataChunk 解析 WAV 头并按 16kHz/16bit 播放，
    因此服务端必须保证 TTS 输出与固件一致，否则会变速/失真/声道错配（BUG-3）。
    若源文件不是合法 WAV（如测试桩写出的非标准头），按原样拷贝，不阻塞 /tts。
    纯标准库实现，兼容 Python 3.11~3.13。
    """
    import shutil

    try:
        with wave.open(str(src_path), "rb") as w:
            channels = w.getnchannels()
            sampwidth = w.getsampwidth()
            framerate = w.getframerate()
            frames = w.readframes(w.getnframes())
    except (wave.Error, EOFError, ValueError):
        shutil.copyfile(src_path, dst_path)
        return

    samples = _decode_wav_frames(frames, sampwidth)
    samples = _downmix_to_mono(samples, channels)
    samples = _resample_linear(samples, framerate, 16000)

    with wave.open(str(dst_path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(_encode_pcm16(samples))


@app.get("/tts")
def tts(text: str, background_tasks: BackgroundTasks):
    import pyttsx3  # 延迟导入：只有 /tts 接口需要 SAPI 引擎

    # 用 NamedTemporaryFile 取代 tempfile.mktemp（后者已弃用且有安全风险）
    raw_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    raw_file.close()
    raw_path = Path(raw_file.name)

    engine = pyttsx3.init()
    engine.setProperty("rate", 175)
    engine.save_to_file(text, str(raw_path))
    engine.runAndWait()
    engine.stop()

    # 归一化为固件要求的 16kHz/单声道/16bit 标准 PCM WAV
    out_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    out_file.close()
    out_path = Path(out_file.name)
    try:
        _normalize_wav(raw_path, out_path)
    finally:
        background_tasks.add_task(_safe_unlink, raw_path)

    # 响应发送完成后删除临时 WAV，避免长时间演示堆积临时文件
    background_tasks.add_task(_safe_unlink, out_path)

    return FileResponse(
        out_path,
        media_type="audio/wav",
        filename="moss_reply.wav",
    )


if __name__ == "__main__":
    import uvicorn

    _get_asr_model()  # 启动前预热 ASR，保持演示第一次请求不卡顿
    uvicorn.run(app, host=HOST, port=PORT)
