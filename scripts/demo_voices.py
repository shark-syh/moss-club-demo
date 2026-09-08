"""MOSS 音色演示：先放『当前 SAPI 女声』，再逐个放 Edge TTS 中文男声候选，听完挑选。

用法（需联网；先装 edge-tts）：
  .venv\\Scripts\\pip install edge-tts -i https://pypi.tuna.tsinghua.edu.cn/simple
  .venv\\Scripts\\python scripts\\demo_voices.py

Edge 语音服务若连不上(网络限制)，先设代理再跑：
  set HTTPS_PROXY=http://127.0.0.1:7890
  set HTTP_PROXY=http://127.0.0.1:7890
"""
import os
import sys
import tempfile

LINE = "你好，我是 MOSS。让人类保持理智，确实是一种奢求。"
CANDIDATES = [
    ("zh-CN-YunyangNeural", "云扬-专业新闻男声"),
    ("zh-CN-YunxiNeural",  "云希-阳光青年男声"),
    ("zh-CN-YunyeNeural",  "云野-沉稳男声"),
    ("zh-CN-YunjianNeural","云健-浑厚男声"),
]


def play_wav_pcm16(pcm, label, sr=16000):
    import wave
    import winsound
    path = os.path.join(tempfile.gettempdir(), "moss_demo.wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    print(f"▶ 播放：{label}（{len(pcm)/sr:.1f}s）", flush=True)
    winsound.PlaySound(path, winsound.SND_FILENAME)


def demo_current_sapi():
    """当前 Pyttsx3/SAPI 的声音（作为对照）。"""
    try:
        import pyttsx3
        import wave
        e = pyttsx3.init()
        v = e.getProperty("voices")[0]
        print(f"\n[0] 当前声音：{v.name}")
        wav = os.path.join(tempfile.gettempdir(), "moss_sapi_current.wav")
        e.save_to_file(LINE, wav)
        e.runAndWait()
        e.stop()
        with wave.open(wav, "rb") as w:
            import numpy as np
            sr = w.getframerate()
            data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        play_wav_pcm16(data, "当前 SAPI 声音", sr)
    except Exception as ex:
        print(f"当前声音演示失败：{ex}")


def demo_edge(voice, label):
    import asyncio
    import numpy as np

    async def _gen(out):
        import edge_tts
        await edge_tts.Communicate(LINE, voice).save(out)

    mp3 = os.path.join(tempfile.gettempdir(), f"moss_{voice}.mp3")
    asyncio.run(_gen(mp3))

    # av 解码 mp3 → 16k/单声道/16bit PCM
    import av
    container = av.open(mp3)
    resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
    chunks = []
    for frame in container.decode(audio=0):
        for out in resampler.resample(frame):
            chunks.append(out.to_ndarray().reshape(-1))
    container.close()
    if not chunks:
        raise RuntimeError("mp3 解码为空")
    pcm = np.concatenate(chunks).astype(np.int16)
    play_wav_pcm16(pcm, f"Edge {voice}（{label}）")
    os.remove(mp3)


def main():
    print("MOSS 音色演示：\n  语句 =", LINE)
    demo_current_sapi()
    try:
        import edge_tts  # noqa
    except ImportError:
        print("\n✗ 缺 edge-tts，请先安装：")
        print("  .venv\\Scripts\\pip install edge-tts -i https://pypi.tuna.tsinghua.edu.cn/simple")
        sys.exit(1)
    for voice, label in CANDIDATES:
        try:
            demo_edge(voice, label)
        except Exception as ex:
            print(f"✗ Edge {voice} 失败：{ex}")
    print("\n听完了吗？告诉我你最喜欢哪个（如 zh-CN-YunyangNeural），或想让我调语气/语速，我就接入 MOSS 的 /tts。")


if __name__ == "__main__":
    main()
