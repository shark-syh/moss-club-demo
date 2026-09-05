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

import io
import json
import os
import tempfile
import wave
from pathlib import Path
from urllib.parse import quote

import pyttsx3
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from faster_whisper import WhisperModel
from openai import OpenAI

app = FastAPI()

HOST = "0.0.0.0"
PORT = 8765
DESKTOP = Path.home() / "Desktop"

client = OpenAI(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com",
)

# 预先加载 ASR 模型，避免每次请求重复加载
asr_model = WhisperModel("base", device="cpu", compute_type="int8")

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
你是学校展示用的 MOSS 机器人。
你只能做两类事情：
1. 回答普通问题；
2. 当用户明确要求打开或查看桌面文件、文件夹时调用 open_desktop_item。

绝对禁止执行删除、修改、移动、复制、重命名、写入、安装、
运行程序、执行命令、关机、联网扫描等操作。
路径必须是相对于 Windows 桌面的相对路径。
如果用户要求超出范围，直接说明只能打开或查看桌面项目。
"""

# 本地关键词模式：DeepSeek 不可用时的兜底
FALLBACK_OPEN_DIRECTORY = str(DESKTOP / "社团嘉年华")
FALLBACK_REPLIES = {
    "你好": "你好，我是 MOSS。",
    "你是谁": "我是社团嘉年华展示机器人。",
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
        segments, _ = asr_model.transcribe(
            wav_path,
            language="zh",
            beam_size=1,
            vad_filter=True,
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

    # 拒绝绝对路径、UNC 路径、命令字符和路径穿越
    forbidden = [":", "\x00", "*", "?", "|", ">", "<", '"']
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

    # Windows 原生打开动作，不经过命令解释器
    os.startfile(str(target))
    return True, f"已打开 {target.name}"


def decide(user_text: str) -> str:
    """调用 DeepSeek，返回回复文本或工具调用结果。"""
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

    message = response.choices[0].message

    if message.tool_calls:
        for call in message.tool_calls:
            if call.function.name != "open_desktop_item":
                return "这个操作不在允许范围内。"
            args = json.loads(call.function.arguments)
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
    return "DeepSeek 暂时不可用，我在本地关键词模式下。你可以说“打开社团嘉年华”。"


@app.post("/api/command")
async def command(request: Request):
    pcm = await request.body()

    if len(pcm) < 1000:
        return JSONResponse(
            {"reply": "录音太短，请再说一次", "tts_url": ""},
            status_code=400,
        )

    try:
        text = transcribe(pcm)
        reply = decide(text) if text else "我没有听清，请再说一次。"

        tts_url = f"http://{request.url.hostname}:{PORT}/tts?text={quote(reply)}"

        return {
            "recognized_text": text,
            "reply": reply,
            "tts_url": tts_url,
        }
    except Exception:
        # 不把 API Key、路径或堆栈暴露给机器人
        return JSONResponse(
            {"reply": "服务暂时不可用，请使用备用演示模式。", "tts_url": ""},
            status_code=500,
        )


@app.get("/tts")
def tts(text: str):
    output = Path(tempfile.mktemp(suffix=".wav"))

    engine = pyttsx3.init()
    engine.setProperty("rate", 175)
    engine.save_to_file(text, str(output))
    engine.runAndWait()
    engine.stop()

    return FileResponse(
        output,
        media_type="audio/wav",
        filename="moss_reply.wav",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
