# 贡献指南（CONTRIBUTING）

感谢参与 **MOSS 语音助手** 的共创！这是一个面向「社团嘉年华」现场演示的桌面机器人项目，欢迎所有人以任何方式参与开发、测试、文档或硬件改进。

---

## 1. 先了解项目

- 架构与安全红线：见 [README.md](README.md) 与 [docs/MOSS语音助手方案.md](docs/MOSS语音助手方案.md)。
- 硬件接线：见 [docs/接线方案与端口定义.md](docs/接线方案与端口定义.md)。
- 软硬件接口：见 [docs/软件接口协议.md](docs/软件接口协议.md)，开发前必须先确认请求、响应和音频格式。
- 当前代码：`firmware/esp32c3/moss_firmware.ino`、`server/server.py`。

## 2. 安全红线（必须遵守，评审时一票否决）

> **本项目的安全模型是硬约束：**
> - 文件操作只允许「打开/查看」桌面目录下已有的文件或文件夹。
> - 禁止任何修改、删除、移动、复制、重命名、写入、下载、安装、运行程序、执行系统命令、关机、格式化、注册表修改，以及访问桌面以外的路径。
> - 代码中不允许出现 `subprocess`、`os.system`、PowerShell、`cmd` 等命令执行方式。

任何涉及文件打开/执行权限的 PR，都**必须**：
1. 说明不突破上述红线；
2. 附上越权用例的拦截测试结果（如绝对路径、`..`、命令注入、危险指令）；
3. 至少 1 位 reviewer 通过。

## 3. 提交规范

### 分支命名
- 新功能：`feat/<功能名>`
- 修复：`fix/<bug名>`
- 文档：`docs/<主题>`
- 重构/优化：`refactor/<主题>`
- 测试：`test/<主题>`

### Commit Message
推荐采用常规提交前缀（中英文均可）：

```
feat: 增加 ASR 断网重试
fix: 修复 I2S 播放结束后未释放 DMA
docs: 补充外壳开孔建议
refactor: 抽取路径校验为独立函数
test: 增加路径穿越拦截用例
```

Commit 说明做了什么，而不是罗列文件。

### 3.1 版本管理（语义化版本 + 标签驱动）

- 版本号以 **git 标签**为准：`vX.Y.Z`（如 `v0.1.0`），写入仓库根目录 [`VERSION`](VERSION) 文件。
- 查看当前版本：`python scripts/version.py`
- 完整构建版本（含提交数与短哈希）：`python scripts/version.py full`
- 发版递增：`python scripts/version.py bump [patch|minor|major]` → 自动写入 `VERSION`、提交并打标签 `vX.Y.Z`，然后 `git push origin master --tags`。
- 已配置 `core.hooksPath=.githooks`，每次 commit 会自动刷新 `VERSION`；新克隆后请执行：
  `git config core.hooksPath .githooks`

## 4. 工作流程

1. 认领前先开 **Issue**：说明背景、改动点、验收标准。
2. 从 `main` 拉分支（`git checkout -b feat/xxx`）。
3. 小步提交，逻辑清晰。
4. 完成后提交 **Pull Request**，PR 描述包含：
   - 改动目标与范围；
   - 验证方式与结果（如固件烧录串口日志、连测记录、识别结果、打开文件截图）；
   - 是否触及安全边界及理由。
5. Reviewer 通过后合并；若有冲突/诉求，耐心沟通。

## 5. 验证与测试建议

- **上位机**：`pip install -r server/requirements.txt` 后，用一段 PCM/脚本测 `/api/command`；验证合法路径打开、非法路径拦截、空录音、超时兜底。
- **固件**：烧录后串口观察 `ESP32 IP`、录音、上传、播放日志；检查 WS2812 状态灯与 GPIO 是否符合预期。
- **端到端**：建议跑 30 次完整流程，记录失败原因与耗时。
- **接口联调**：必须按 [软件接口协议](docs/软件接口协议.md) 的顺序，从固定 PCM、固定 JSON、固定 WAV 逐步联调，再接入真实 ASR 和 DeepSeek。
- 任何改动尽量不要破坏现有默认配置（GPIO、端口 8765、模型 base）。

## 6. 环境说明

- **电脑端**：Windows 10/11，Python 3.11，`DEEPSEEK_API_KEY` 环境变量。
- **固件端**：Arduino IDE 2.x + `esp32 by Espressif Systems`，板卡 `ESP32C3 Dev Module`，库 `ArduinoJson`、`Adafruit NeoPixel`。
- 不同 ESP32-C3 板子的 GPIO 可能不同，请以实际丝印为准，并说明你用的板子型号。

## 7. 沟通

- 优先用 Issue / PR 讨论，保持讨论公开可追溯。
- 不确定的硬件、引脚、接线问题优先在 README 的「文档索引」与接线文档中查找，或开 Issue 询问。

---

祝贡献愉快！🎉
