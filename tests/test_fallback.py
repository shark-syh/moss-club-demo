"""本地关键词兜底（_fallback_decide）与 decide() 异常降级测试。

DeepSeek 断网/不可用时，上位机必须能退回本地关键词模式，
且「打开社团嘉年华」只经由 safe_open_desktop_item 处理。
"""
import server


def test_fallback_exact_greeting():
    assert server._fallback_decide("你好") == "你好，我是 MOSS。"


def test_fallback_open_keywords(monkeypatch):
    monkeypatch.setattr(
        server,
        "safe_open_desktop_item",
        lambda rel: (True, f"已打开 {rel}"),
    )
    reply = server._fallback_decide("帮我打开社团嘉年华文件夹")
    assert reply == "已打开 社团嘉年华"


def test_fallback_unknown_never_opens_file(monkeypatch):
    def fail(*a, **k):
        raise AssertionError("无关键词的请求不应触达文件打开")

    monkeypatch.setattr(server, "safe_open_desktop_item", fail)
    reply = server._fallback_decide("今天天气怎么样")
    assert "本地关键词模式" in reply


def test_decide_falls_back_when_api_down(monkeypatch):
    class FakeCompletions:
        def create(self, **kwargs):
            raise ConnectionError("api down")

    class FakeClient:
        class chat:
            completions = FakeCompletions()

    monkeypatch.setattr(server, "client", FakeClient())
    monkeypatch.setattr(
        server,
        "safe_open_desktop_item",
        lambda rel: (True, f"已打开 {rel}"),
    )
    assert "已打开 社团嘉年华" in server.decide("打开社团嘉年华")
