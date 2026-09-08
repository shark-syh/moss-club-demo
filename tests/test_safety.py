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


# ---------- 安全红线回归：危险扩展名 denylist + 安全 allowlist + 新增命令字符 ----------

# t8 评审 F1：为 safe_open_desktop_item 的危险扩展名 / 白名单 / 新增命令字符补越权拦截测试。
# 这些场景在修复前的 bad_path 里没有覆盖，因此安全红线一直缺少 CI 回归保护。

DANGEROUS_EXTENSIONS_CASES = [
    "evil.exe",       # 可执行程序
    "run.bat",        # 由 cmd.exe 解释执行
    "cmd.cmd",        # 由 cmd.exe 解释执行
    "link.lnk",       # 快捷方式，可跳到桌面外任意目标
    "pwn.vbs",        # 由 WSH(wscript) 执行代码
    "reg.reg",        # 导入注册表
    "hide.msi",       # 安装器
    "scr.scr",        # 屏幕保护（可执行）
    "p.ps1",          # PowerShell 脚本
]


@pytest.mark.parametrize("name", DANGEROUS_EXTENSIONS_CASES)
def test_reject_dangerous_extensions(guarded, name):
    """危险扩展名（可执行/脚本/快捷方式/安装器/注册表）必须被拒绝，且从不触达 os.startfile。"""
    tmp_path, calls = guarded
    (tmp_path / name).touch()
    ok, msg = server.safe_open_desktop_item(name)
    assert ok is False
    assert "不允许打开" in msg, f"{name} 应给出明确拒绝原因"
    assert calls == [], f"{name} 绝不允许调用 os.startfile"


NEW_FORBIDDEN_CHARS_CASES = [
    "a;b", "a&b", "a^b", "a'b", "a`b",
    "a(b", "a)b", "a{b", "a}b", "a[b", "a]b",
]


@pytest.mark.parametrize("path", NEW_FORBIDDEN_CHARS_CASES)
def test_reject_new_command_chars(guarded, path):
    """协议 §5 要求的命令字符（新增的 shell/解释器元字符）必须被拒绝。"""
    _, calls = guarded
    ok, msg = server.safe_open_desktop_item(path)
    assert ok is False
    assert msg, "被拒绝时必须给出原因"
    assert calls == []


def test_reject_non_allowlisted_extension(guarded):
    """不在白名单内的扩展名（如 .zip）默认拒绝——即便文件真实存在于桌面。"""
    tmp_path, calls = guarded
    (tmp_path / "archive.zip").write_bytes(b"PK")
    ok, msg = server.safe_open_desktop_item("archive.zip")
    assert ok is False
    assert "白名单" in msg
    assert calls == []


def test_reject_extensionless_file(guarded):
    """无扩展名文件默认拒绝（不能因扩展名缺失而绕过类型校验）。"""
    tmp_path, calls = guarded
    (tmp_path / "README").write_text("hello")
    ok, msg = server.safe_open_desktop_item("README")
    assert ok is False
    assert msg
    assert calls == []


def test_open_allowlisted_image(guarded):
    """白名单内的图片扩展名（.jpg）可以正常打开。"""
    tmp_path, calls = guarded
    (tmp_path / "photo.jpg").write_bytes(b"\xff\xd8\xff")
    ok, _ = server.safe_open_desktop_item("photo.jpg")
    assert ok is True
    assert calls == [str((tmp_path / "photo.jpg").resolve())]
