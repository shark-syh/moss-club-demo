#!/usr/bin/env python3
"""MOSS 语音助手仓库 · 语义化版本管理脚本

版本号以 git 标签（vX.Y.Z）为唯一事实来源，自动写入根目录 VERSION 文件。

用法：
  python scripts/version.py            # 打印当前版本（如 0.1.0）
  python scripts/version.py write      # 把当前版本写入根目录 VERSION 文件
  python scripts/version.py full       # 打印完整版本（标签-提交数-短哈希）
  python scripts/version.py bump       # 递增 patch 版本（0.1.1）
  python scripts/version.py bump minor # 递增 minor 版本（0.2.0）
  python scripts/version.py bump major # 递增 major 版本（1.0.0）

bump 会：写入 VERSION -> 提交 VERSION -> 打标签 vX.Y.Z。
打标签后请 git push origin master --tags 同步到 GitHub。
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION"
DEFAULT_VERSION = "0.1.0"


def git(*args):
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, text=True
        )
        return out.stdout.strip()
    except Exception:
        return ""


def latest_tag():
    tag = git("describe", "--tags", "--abbrev=0")
    if tag and re.match(r"^v\d+\.\d+\.\d+$", tag):
        return tag
    return None


def current_version():
    tag = latest_tag()
    return tag[1:] if tag else DEFAULT_VERSION


def full_version():
    return git("describe", "--tags", "--always", "--dirty") or current_version()


def write():
    ver = current_version()
    VERSION_FILE.write_text(ver + "\n", encoding="utf-8")
    return ver


def bump(part):
    ver = current_version()
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", ver)
    if not m:
        print("当前版本不是纯语义化 x.y.z：", ver)
        sys.exit(1)
    major, minor, patch = (int(x) for x in m.groups())
    if part == "major":
        major += 1
        minor = patch = 0
    elif part == "minor":
        minor += 1
        patch = 0
    elif part == "patch":
        patch += 1
    else:
        print("part 必须是 patch|minor|major")
        sys.exit(1)

    new = f"{major}.{minor}.{patch}"
    write()
    git("add", "VERSION")
    git("commit", "-m", f"chore(version): v{new}", "--", "VERSION")
    git("tag", "-a", f"v{new}", "-m", f"v{new}")
    print(f"已写入并提交 v{new}，并打标签 v{new}")
    print("下一步：git push origin master --tags")
    return new


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "write":
        print(write())
    elif cmd == "full":
        print(full_version())
    elif cmd == "bump":
        part = sys.argv[2] if len(sys.argv) > 2 else "patch"
        print(bump(part))
    else:
        print(current_version())


if __name__ == "__main__":
    main()
