"""电脑端语音测试（空格控制 + 噪音增强 + 可打断播报）：
  空闲/播音中按【空格】开始说话 → 说完再按【空格】结束 → 降噪/锁主声源/强化 → 识别 → MOSS 播放（可随时按空格打断并立刻开新一轮）。

只依赖 numpy + sounddevice。用法：
  .venv\\Scripts\\python scripts\\voice_test.py
服务器需已在另一个窗口启动；Ctrl+C 退出。
"""
import sys
import os
import json
import time
import wave
import tempfile
import urllib.request

import numpy as np
import sounddevice as sd
import winsound
import msvcrt

HOST = "http://127.0.0.1:8765"
TARGET_RATE = 16000


# ---------------- 录音（空格控制） ----------------
def resample(arr, from_rate, to_rate):
    n_out = int(len(arr) * to_rate / from_rate)
    idx = np.linspace(0, len(arr) - 1, n_out)
    return np.interp(idx, np.arange(len(arr)), arr).astype("int16")


def wait_space(prompt):
    print(prompt, end="", flush=True)
    while True:
        if msvcrt.kbhit() and msvcrt.getch() == b" ":
            print()
            return


def start_stream():
    try:
        stream = sd.InputStream(samplerate=TARGET_RATE, channels=1, dtype="int16")
        stream.start()
        return stream, TARGET_RATE
    except Exception:
        info = sd.query_devices(kind="input")
        dev_rate = int(info["default_samplerate"])
        stream = sd.InputStream(samplerate=dev_rate, channels=1, dtype="int16")
        stream.start()
        return stream, dev_rate


def record_until_space(max_seconds):
    stream, rate = start_stream()
    chunks = []
    start = time.time()
    print("\n🔴 录音中…（说完按【空格】结束）", flush=True)
    while True:
        data, _ = stream.read(1024)
        chunks.append(data.copy())
        if msvcrt.kbhit() and msvcrt.getch() == b" ":
            break
        if time.time() - start > max_seconds:
            print("\n(达到最长录音时间，自动结束)")
            break
    stream.stop()
    stream.close()
    pcm = np.concatenate(chunks).flatten()
    if rate != TARGET_RATE:
        pcm = resample(pcm, rate, TARGET_RATE)
        rate = TARGET_RATE
    return pcm, rate, (time.time() - start)


# ---------------- 噪音增强（纯 numpy） ----------------
def spectral_noise_reduce(x, sr, n_fft=512, hop=128, noise_frac=0.25, over_sub=1.5, floor_ratio=0.06):
    x = x.astype(np.float32)
    n = len(x)
    if n < n_fft * 2:
        return x.astype(np.int16), n
    n_frames = (n - n_fft) // hop + 1
    win = np.hanning(n_fft).astype(np.float32)
    frames = np.empty((n_frames, n_fft), dtype=np.float32)
    for i in range(n_frames):
        frames[i] = x[i * hop: i * hop + n_fft] * win
    spec = np.fft.rfft(frames, axis=1)
    mag = np.abs(spec)
    phase = np.angle(spec)
    energy = mag.sum(axis=1)
    n_noise = max(1, int(n_frames * noise_frac))
    idx = np.argsort(energy)[:n_noise]
    noise = mag[idx].mean(axis=0)
    reduced = np.maximum(mag - over_sub * noise, floor_ratio * mag)
    out_frames = np.fft.irfft(reduced * np.exp(1j * phase), n=n_fft, axis=1)
    out = np.zeros(n, dtype=np.float32)
    win_sum = np.zeros(n, dtype=np.float32)
    for i in range(n_frames):
        s = i * hop
        out[s: s + n_fft] += out_frames[i] * win
        win_sum[s: s + n_fft] += win * win
    out = out / np.maximum(win_sum, 1e-8)
    return out.astype(np.int16), n


def keep_loudest_segment(x, sr, frame_ms=30, pad_ms=200, thresh_abs=250, thresh_ratio=0.12):
    x = x.astype(np.float32)
    n = len(x)
    frame = max(1, int(sr * frame_ms / 1000))
    pad = int(sr * pad_ms / 1000)
    m = n // frame
    if m < 2:
        return x.astype(np.int16)
    blocks = x[: m * frame].reshape(m, frame)
    rms = np.sqrt(np.mean(blocks ** 2, axis=1))
    max_rms = float(rms.max())
    thr = max(thresh_abs, max_rms * thresh_ratio)
    active = rms > thr
    segs = []
    i = 0
    while i < m:
        if active[i]:
            j = i
            while j + 1 < m and active[j + 1]:
                j += 1
            s = max(0, frame * i - pad)
            e = min(n, frame * (j + 1) + pad)
            energy = float(np.sum(rms[i: j + 1] ** 2))
            segs.append((energy, s, e))
            i = j + 1
        else:
            i += 1
    if not segs:
        return x.astype(np.int16)
    _, s, e = max(segs, key=lambda t: t[0])
    return x[s: e].astype(np.int16)


def normalize(x, peak=0.85):
    x = x.astype(np.float32)
    m = float(np.max(np.abs(x)))
    if m < 1:
        return x.astype(np.int16)
    return (x * (peak * 32767.0 / m)).astype(np.int16)


# ---------------- 与服务器交互 ----------------
def post_pcm(pcm):
    req = urllib.request.Request(
        HOST + "/api/command",
        data=pcm.tobytes(),
        headers={"Content-Type": "audio/pcm; rate=16000; channels=1"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def play_reply_interruptible(text, tts_url):
    """下载并播放 MOSS 回复；播放中按【空格】立即打断。返回是否被打断。"""
    with urllib.request.urlopen(tts_url, timeout=30) as r:
        audio = r.read()
    tmp = os.path.join(tempfile.gettempdir(), "moss_reply.wav")
    with open(tmp, "wb") as f:
        f.write(audio)
    with wave.open(tmp, "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        nf = w.getnframes()
        frames = w.readframes(nf)
    arr = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        arr = arr.reshape(-1, ch).mean(axis=1)
    duration = (nf / sr) + 0.15

    print(f"MOSS: {text}\n　　(按【空格】打断并立刻开始说话)")
    sd.play(arr, sr)
    start = time.time()
    interrupted = False
    while time.time() - start < duration:
        if msvcrt.kbhit() and msvcrt.getch() == b" ":
            sd.stop()
            interrupted = True
            break
        time.sleep(0.02)
    return interrupted


# ---------------- 主流程 ----------------
def main():
    max_seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
    print("=== MOSS 语音测试（空格控制 + 噪音增强 + 可打断）===")
    print("· 空闲/播音中，按【空格】开始说话 → 说完再按【空格】结束")
    print("· MOSS 说话时按【空格】= 打断并立刻开新一轮。Ctrl+C 退出。")
    try:
        interrupted = False
        while True:
            if not interrupted:
                winsound.MessageBeep()
                wait_space("\n按【空格】开始说话...")
            interrupted = False
            winsound.MessageBeep()
            pcm, rate, dur = record_until_space(max_seconds)
            orig = len(pcm) / rate

            pcm, _ = spectral_noise_reduce(pcm, rate)
            pcm = keep_loudest_segment(pcm, rate)
            if len(pcm) < int(0.3 * rate):
                print("没检测到有效人声，请靠近麦克风再说一次。")
                continue
            pcm = normalize(pcm)
            print(f"已采音 {orig:.1f}s，增强后有效人声约 {len(pcm)/rate:.1f}s，识别中...")

            resp = post_pcm(pcm)
            print("识别:", resp.get("recognized_text") or "(无识别)")
            if resp.get("tts_url"):
                try:
                    interrupted = play_reply_interruptible(resp.get("reply", ""), resp["tts_url"])
                except Exception as e:
                    print("播放失败，回复是：", resp.get("reply", ""), "| 原因:", e)
            else:
                print("MOSS:", resp.get("reply", ""))
    except KeyboardInterrupt:
        print("\n已退出。")


if __name__ == "__main__":
    main()
