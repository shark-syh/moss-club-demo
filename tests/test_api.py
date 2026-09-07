"""上位机 HTTP 接口契约测试（/api/command）。

打桩 ASR(transcribe) 与 DeepSeek(decide)，覆盖
docs/软件接口协议.md 第 3、5 节约定的行为，
不依赖 whisper 模型、网络与真实桌面目录。
"""
from urllib.parse import unquote

import server
from fastapi.testclient import TestClient

# 超过 1000 字节的「像样」PCM（值域 ±300，避免全零被误判）
PCM = (b"\x00\x01" * 500) + (b"\xff\xfe" * 500)

client = TestClient(server.app)


def test_empty_body_is_400():
    r = client.post("/api/command", content=b"")
    assert r.status_code == 400


def test_short_recording_returns_contract_error():
    """录音太短 -> 400，且错误响应仍是协议约定的三字段结构。"""
    r = client.post("/api/command", content=b"\x00" * 10)
    assert r.status_code == 400
    body = r.json()
    assert set(body) == {"recognized_text", "reply", "tts_url"}
    assert body["recognized_text"] == ""
    assert body["tts_url"] == ""
    assert body["reply"]


def test_command_success_contract(monkeypatch):
    monkeypatch.setattr(server, "transcribe", lambda pcm: "打开社团嘉年华")
    monkeypatch.setattr(server, "decide", lambda text: "已打开社团嘉年华")

    r = client.post(
        "/api/command",
        content=PCM,
        headers={"Content-Type": "audio/pcm; rate=16000; channels=1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["recognized_text"] == "打开社团嘉年华"
    assert body["reply"] == "已打开社团嘉年华"
    # tts_url 必须指向本服务 /tts，且回复文本被 URL 编码
    assert body["tts_url"].startswith("http://testserver:8765/tts?text=")
    assert unquote(body["tts_url"].split("text=", 1)[1]) == "已打开社团嘉年华"


def test_internal_error_does_not_leak(monkeypatch):
    """500 时只返回固定话术，绝不泄露 Key / 本地路径 / 堆栈。"""

    def boom(pcm):
        raise RuntimeError("secret-key-123 C:\\Users\\hw\\Desktop")

    monkeypatch.setattr(server, "transcribe", boom)

    r = client.post("/api/command", content=PCM)
    assert r.status_code == 500
    body = r.json()
    assert set(body) == {"recognized_text", "reply", "tts_url"}
    assert body["reply"] == "服务暂时不可用，请使用备用演示模式。"
    assert "secret-key-123" not in r.text
    assert "C:\\Users" not in r.text
