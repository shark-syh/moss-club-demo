# AI 协作说明（AGENTS.md）—— 请任何 AI Agent 在编辑本项目前先阅读

> 你正在参与维护 **MOSS 语音助手**（仓库：`shark-syh/moss-club-demo`，公开仓库，主分支 `master`）。
> 本文件是给「使用其他 AI 工具/Agent 编辑本仓库」的**统一约定**，也是 GitHub 推送规则与文档管理的要求。
> 请先通读本文件，再动手改代码或文档；完成后按末尾「提交前检查清单」自查。

---

## 1. 项目是什么（一句话）

ESP32-C3 桌面语音助手机器人：按键录音 → 电脑端 ASR 识别 → DeepSeek 理解意图 → 只允许安全打开桌面上的文件/文件夹 → TTS 语音播报。用于学校「社团嘉年华」现场演示。

- 硬件端固件：`firmware/esp32c3/moss_firmware.ino`
- 电脑端上位机：`server/server.py` + `server/requirements.txt`
- 方案/接线/提示词文档：`docs/`
- 入口文档：`README.md`；协作规范：`CONTRIBUTING.md`

---

## 2. GitHub 推送规则（务必遵守）

### 2.1 仓库与分支
- 仓库：`https://github.com/shark-syh/moss-club-demo.git`
- 默认/主分支：**`master`**（已开启分支保护）
- `master` 的规则：**必须走 Pull Request**、**禁止 force push**、**禁止删除分支**。只有仓库 owner（`shark-syh`）作为管理员能直接推 `master`；**协作者不能直接推 `master`，也不能 `--force` 推送**。

### 2.2 分支命名
- 新功能：`feat/<功能名>`（如 `feat/add-retry`）
- 修复：`fix/<bug名>`
- 文档：`docs/<主题>`
- 重构/优化：`refactor/<主题>`
- 测试：`test/<主题>`

### 2.3 提交信息（Commit Message）
用常规提交前缀，中文或英文均可，说明「做了什么」而不是罗列文件：
```
feat: 增加 ASR 断网重试
fix: 修复 I2S 播放结束后未释放 DMA
docs: 补充外壳开孔建议
refactor: 抽取路径校验为独立函数
test: 增加路径穿越拦截用例
chore(version): v0.2.0
```

### 2.4 推荐工作流（AI 编辑完的推送方式）
```powershell
git pull
git checkout -b <分支名>     # 例如 feat/xxx
# ……修改代码 / 文档 / 测试……
git add .
git commit -m "<遵循约定的提交信息>"
git push origin <分支名>      # 推到你自己的分支，绝不要直接推 master
```
推完在 GitHub 网页开 **Pull Request**，填好 PR 模板（含：改动说明、验证结果、是否触及安全边界），等待 owner 审核合并。

### 2.5 权限与身份
- **不要**用 `git --force` 推 `master`。
- **不要在**代码、提交信息、注释或 `VERSION` 写死任何真实密钥/令牌。`DEEPSEEK_API_KEY` 用环境变量注入，`.env`、`DEEPSEEK_API_KEY.txt`、`*.wav`/`*.pcm` 等已被 `.gitignore` 排除。
- 推送时仓库使用本机已保存的 GitHub 凭据（浏览器授权一次即可）；若所在环境的 `github.com` git 通道不稳定，可改用 OpenSSL 后端（`git -c http.sslBackend=openssl`），或改用 GitHub API 提交，但**禁止在仓库里留下任何令牌**。

---

## 3. 版本管理（语义化版本 + 标签驱动）

- 版本号以 **git 标签**（`vX.Y.Z`）为唯一事实来源，写入根目录 `VERSION` 文件。
- 脚本：`scripts/version.py`
  - 查看当前版本：`python scripts/version.py`
  - 查看完整版（标签+提交数+短哈希）：`python scripts/version.py full`
  - 发版递增并打标签：`python scripts/version.py bump [patch|minor|major]` → 自动写入 `VERSION` + 提交 + 打标签 `vX.Y.Z`，之后 `git push origin master --tags`
- 钩子：`.githooks/pre-commit` 会在每次提交时自动刷新 `VERSION`。新克隆后请激活一次：
  `git config core.hooksPath .githooks`
- **AI 注意**：改动前先 `git pull`；若改了涉及功能/接口的代码，建议相应 `bump` 版本。

---

## 4. 文档管理

- **`README.md`**：项目入口与汇总，含「文档索引」表。若新增功能/文件，请同步更新 README 的相关章节与索引，保持入口准确。
- **`docs/`**：详细方案文档（如 `MOSS语音助手方案.md`、`接线方案与端口定义.md`、`AI开发提示词-MOSS语音助手项目.md`）。改动硬件、协议、架构时，更新对应文档，避免文档与代码脱节。
- **`CONTRIBUTING.md`**：多人协作规范（安全红线、提交规范、验证建议）。新增约定请尽量写进这里，其他人/Agent 才能遵从。
- **`.github/`**：issue/PR 模板。开 PR 时**按模板填写**，尤其是「是否触及安全边界」和「验证结果」。

---

## 5. 安全红线（评审一票否决，绝不能突破）

> 文件操作**只允许「打开/查看」**桌面目录下已有的文件或文件夹。
> **禁止**任何修改、删除、移动、复制、重命名、写入、下载、安装、运行任意程序、执行系统命令、关机、格式化、注册表修改，以及访问桌面以外路径。
> 代码（尤其 `server.py`）**不允许**出现 `subprocess`、`os.system`、PowerShell、`cmd` 等命令执行方式。

任何涉及文件打开/执行权限的改动，都必须在 PR 中说明「为何未突破红线」并附越权拦截测试结果（绝对路径、`..`、命令注入、危险指令）。

---

## 6. 提交前检查清单（AI 每次改完必查）

- [ ] 已 `git pull` 拉取最新代码，避免基于过期版本修改
- [ ] 分支命名与提交信息符合第 2 节约定
- [ ] 未出现 `subprocess`/`os.system`/`cmd`/PowerShell 等危险调用（除非明确且合规）
- [ ] 未提交任何密钥、.env、秘钥文件、二进制产物
- [ ] 涉及功能/接口改动：`python scripts/version.py` 版本是否需要更新
- [ ] 文档（README / docs / CONTRIBUTING）与改动同步更新
- [ ] PR 描述已按 `.github/PULL_REQUEST_TEMPLATE.md` 填好「验证结果」与「是否触及安全边界」
- [ ] 推送的是**自己的分支**，不是直接推 `master`（owner 除外）

---

*本文件由项目维护者维护；如与 README/CONTRIBUTING 冲突，以仓库内最新的 README、CONTRIBUTING 与分支保护设置为准。*
