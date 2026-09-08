"""pytest 公共配置：让测试可以直接导入 server/ 模块。

server.py 在 import 阶段会初始化 OpenAI client（读取 DEEPSEEK_API_KEY），
这里先注入一个哑 Key，避免测试依赖真实密钥；
同时把 server/ 目录加入 sys.path，使 `import server` 可用。
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("DEEPSEEK_API_KEY", "test-dummy-key")

SERVER_DIR = Path(__file__).resolve().parent.parent / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
