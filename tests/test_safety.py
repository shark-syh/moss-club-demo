"""safe_open_desktop_item 的安全边界单元测试（越权拦截）。

原则：
  - 不触碰真实桌面、不产生任何真实副作用；
  - 通过 monkeypatch 把模块级 DESKTOP 指向 pytest 临时目录；
  - 用记录器替换 os.startfile，断言「只有合法路径才会被调用」。
"""
import os

import pytest

import server


@pytest.fixture
def guarded(tmp_path, monkeypatch):
    """构造「临时桌面目录」+「startfile 调用记录器」。"""
    (tmp_path / "社团嘉年华").mkdir()
    (tmp_path / "社团嘉年华" / "说明.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "笔记.txt").write_bytes("你好".encode("utf-8"))

    calls = []
    monkeypatch.setattr(server, "DESKTOP", tmp_path)
    monkeypatch.setattr(os, "startfile", lambda path: calls.append(str(path)))
    return tmp_path, calls


@pytest.mark.parametrize(
    "bad_path",
    [
        "",                        # 空路径
        "   ",                     # 纯空白（也应视为空路径）
        "C:\\Windows\\System32",   # 绝对路径（含盘符冒号）
        "\\server\\share",         # UNC / 绝对路径
        "..\\Windows",             # 路径穿越
        "社团嘉年华\\..\\..\\Windows",
        "社团嘉年华\\..\\notes.txt",
        "a|b",                     # 命令/非法字符
        '"a"',
        "a<b",
        "a>b",
        "a?b",
        "a*b",
        "a\x00b",
    ],
)
def test_reject_unsafe_paths(guarded, bad_path):
    _, calls = guarded
    ok, msg = server.safe_open_desktop_item(bad_path)
    assert ok is False
    assert msg, "被拒绝时必须给出原因"
    assert calls == [], "被拒绝的路径绝不允许调用 os.startfile"


def test_missing_item_is_rejected(guarded):
    _, calls = guarded
    ok, msg = server.safe_open_desktop_item("不存在的文件夹")
    assert ok is False
    assert "不存在" in msg
    assert calls == []


def test_open_existing_file_inside_desktop(guarded):
    tmp_path, calls = guarded
    ok, msg = server.safe_open_desktop_item("社团嘉年华\\说明.pdf")
    assert ok is True
    assert "已打开" in msg
    assert calls == [str((tmp_path / "社团嘉年华" / "说明.pdf").resolve())]


def test_open_existing_directory(guarded):
    tmp_path, calls = guarded
    ok, _ = server.safe_open_desktop_item("社团嘉年华")
    assert ok is True
    assert calls == [str((tmp_path / "社团嘉年华").resolve())]


def test_forward_slash_is_normalized(guarded):
    """正斜杠应等价于反斜杠（server 会先做替换归一化）。"""
    tmp_path, calls = guarded
    ok, _ = server.safe_open_desktop_item("社团嘉年华/说明.pdf")
    assert ok is True
    assert calls == [str((tmp_path / "社团嘉年华" / "说明.pdf").resolve())]
