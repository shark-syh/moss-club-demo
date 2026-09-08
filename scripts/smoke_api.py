"""联调自测：向上位机 /api/command 发送 PCM，验证返回 JSON。

用法（在仓库目录、服务器已启动时）：
  .venv\\Scripts\\python scripts\\smoke_api.py                # 发送一段合成的 4 秒音频
  .venv\\Scripts\\python scripts\\smoke_api.py 某录音.wav      # 用真实录音（建议 16k/单声道/16bit）

若传了 .wav，会转成 16kHz/单声道/16bit PCM 再上传。
无论识别结果如何，只要返回三字段 JSON 即说明链路通了。
"""
import io
import json
import math
import struct
import sys
import urllib.request
import wave

from pathlib import Path

HOST = "http://127.0.0.1:8765"
SAMPLE_RATE = 16000


def make_synthetic_pcm(seconds=4, rate=16000, freq=300, amp=1500):
    """生成一段带一点谐波的音频，避免纯静音被当作空录音。"""
    n = rate * seconds
    pcm = bytearray()
    for i in range(n):
        v = int(amp * math.sin(2 * math.pi * freq * i / rate))
        v += int((amp // 2) * math.sin(2 * math.pi * freq * 2 * i / rate))
        v += int((amp // 3) * math.sin(2 * math.pi * freq * 3 * i / rate))
        v = max(-32768, min(32767, v))
        pcm += struct.pack("<h", v)
    return bytes(pcm)


def wav_to_pcm(path: str) -> bytes:
    """把 WAV 转为 16kHz/单声道/16bit PCM 字节。"""
    with wave.open(path, "rb") as w:
        params = w.getparams()
        frames = w.readframes(params.nframes)
    if params.framerate == SAMPLE_RATE and params.nchannels == 1 and params.sampwidth == 2:
        return frames
    # 简单重采样：不满足标准格式时打印提示，仍按原数据发送（由服务端包装）
    print(f"提示：WAV 为 {params.framerate}Hz/{params.nchannels}ch/{params.sampwidth*8}bit，"
          f"建议用 16kHz/单声道/16bit；将按原格式发送。")
    # 用 wave 直接重采样到 16k 单声道 16bit（线性插值）
    import array
    data = array.array("h", frames if params.sampwidth == 2 else [])
    out = array.array("h")
    ratio = params.framerate / SAMPLE_RATE
    for idx in range(int(params.nframes / ratio)):
        src = int(idx * ratio)
        if src < params.nframes:
            ch = data[src * params.nchannels] if params.nchannels == 1 else data[src * params.nchannels]
            out.append(ch)
    return out.tobytes()


def main():
    pcm = None
    if len(sys.argv) > 1:
        pcm = wav_to_pcm(sys.argv[1])
        print(f"使用录音文件: {sys.argv[1]}（{len(pcm)} 字节）")
    else:
        pcm = make_synthetic_pcm()
        print(f"使用合成音频（{len(pcm)} 字节）。注意：非真实语音，识别结果可能为空。")

    req = urllib.request.Request(
        HOST + "/api/command",
        data=pcm,
        headers={"Content-Type": "audio/pcm; rate=16000; channels=1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            print("HTTP", resp.status)
            print(json.dumps(json.loads(body), ensure_ascii=False, indent=2))
    except urllib.error.HTTPError as e:
        print("HTTP 错误", e.code)
        print(e.read().decode("utf-8", errors="replace"))
    except Exception as e:
        print("请求失败:", e)


if __name__ == "__main__":
    main()
