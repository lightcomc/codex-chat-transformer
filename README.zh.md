# Codex Chat Transformer

[English](README.md) | [Русский](README.ru.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.7+](https://img.shields.io/badge/Python-3.7%2B-blue.svg)](https://www.python.org/)
[![Zero external deps](https://img.shields.io/badge/deps-zero-green.svg)]()

一个用于管理 [Codex Desktop](https://github.com/openai/codex) 会话的工具 —— 在不同提供商之间转换聊天、将其固定到侧边栏，以及创建完整备份。

---

## 快速开始

安装：
```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/lightcomc/codex-chat-transformer/main/install.sh | bash
```
```powershell
# PowerShell
irm https://raw.githubusercontent.com/lightcomc/codex-chat-transformer/main/install.ps1 | iex
```

基本用法：
```bash
# 启动 GUI
codex_manager.cmd
```
```bash
# 保存当前提供商
python codex_chat_transformer.py --save-provider MyProvider
```
```bash
# 切换提供商 + 转换聊天
python codex_chat_transformer.py --use-provider MyProvider
```
```bash
# 完整备份
python codex_chat_transformer.py --backup
```

---

## 问题背景

Codex Desktop 为每种连接方式创建独立的「虚拟空间」。在订阅和 API 密钥之间切换时，聊天会「消失」——它们还在，但侧边栏会按 `model_provider` 过滤。尝试继续属于另一个提供商的聊天会返回 401，因为请求发送到了错误的端点。

---

## 功能

### 聊天转换

在不同提供商之间转换聊天。修改数据库和 JSONL 文件中的 `model_provider`。支持项目过滤和模型映射。自动创建备份。转换后提供验证报告。

```bash
python codex_chat_transformer.py --from openai --to MyProvider
```
```bash
python codex_chat_transformer.py --from openai --to MyProvider --dry-run
```
```bash
python codex_chat_transformer.py --from openai --to MyProvider --project my_project
```
```bash
python codex_chat_transformer.py --from openai --to MyProvider --from-model gpt-4 --to-model gpt-5.5
```
```bash
python codex_chat_transformer.py --from openai --to MyProvider --thread <ID>
```
```bash
python codex_chat_transformer.py --from openai --to MyProvider --skip-pinned
```

### 提供商管理

所有提供商都存储在同一个 `config.toml` 文件中 —— 每个作为 `[model_providers.*]` 部分。切换只会更改 `model_provider`、`model` 和 `model_reasoning_effort` 字段。配置文件保存在 `providers.json` 中，支持自动迁移旧格式。

> **注意：** 提供商 `openai` 受保护 —— URL 和 API 密钥字段为只读。要更改 OpenAI 凭据，请直接通过 Codex Desktop 进行身份验证。

将当前提供商保存为配置文件：
```bash
python codex_chat_transformer.py --save-provider MyProvider
```

切换：
```bash
python codex_chat_transformer.py --use-provider MyProvider
```

从 JSON 文件添加：
```bash
python codex_chat_transformer.py --add-provider provider.json
```
```bash
python codex_chat_transformer.py --add-provider provider.json --api-key sk-xxx
```

编辑：
```bash
python codex_chat_transformer.py --edit-provider MyProvider --set-model gpt-5.5
```
```bash
python codex_chat_transformer.py --edit-provider MyProvider --set-url https://new.url/v1
```
```bash
python codex_chat_transformer.py --edit-provider MyProvider --set-key sk-new
```
```bash
python codex_chat_transformer.py --edit-provider MyProvider --set-reasoning high
```

更改模型（不切换提供商）：
```bash
python codex_chat_transformer.py --set-model gpt-5.5
```

删除：
```bash
python codex_chat_transformer.py --remove-provider MyProvider
```

列表：
```bash
python codex_chat_transformer.py --providers
```

自动检测：
```bash
python codex_chat_transformer.py --detect-provider
```

### 固定聊天

使聊天在任何活跃提供商下都可见。固定的聊天始终显示在侧边栏中。用于在提供商之间切换时重新激活聊天。

```bash
python codex_chat_transformer.py --pin-top 10
```
```bash
python codex_chat_transformer.py --pin-top 10 --project my_project
```
```bash
python codex_chat_transformer.py --pin-list
```
```bash
python codex_chat_transformer.py --unpin-all
```

### 完整备份

将整个 `.codex` 文件夹打包为 ZIP：数据库、配置、身份验证、所有会话、`providers.json`。

```bash
python codex_chat_transformer.py --backup
```
```bash
python codex_chat_transformer.py --restore backup_20260518_120000
```
```bash
python codex_chat_transformer.py --restore-zip codex_backup_20260518.zip
```

### 诊断

只读健康检查：数据库、配置、身份验证、提供商、固定线程。

```bash
python codex_chat_transformer.py --doctor
```

### P2P 同步

通过 HTTP API + 网页面板在机器之间进行本地双向同步。两台机器运行相同的服务器。浏览器作为编排器 — Push 和 Pull 提供商、会话和项目文件。

```bash
# 启动同步服务器（自动选择空闲端口）
python codex_chat_transformer.py --sync-host

# 指定端口启动
python codex_chat_transformer.py --sync-host --sync-port 8080

# 连接到远程并拉取数据
python codex_chat_transformer.py --sync-pull 192.168.1.60:8080 --sync-pin A7B3C2
```

功能：
- 网页面板（深色主题，5 个标签页：连接、提供商、会话、文件、设置）
- 基于 PIN 的身份验证，带速率限制
- 双向：每个项目均可 Push 和 Pull
- 提供商导入模式：带密钥 / 不带密钥 / 跳过 / 保留两者
- 会话同步：下载 JSONL + 插入本地数据库
- 文件同步：SHA-256 哈希差异 + ZIP 打包
- 自动关联：会话 Push/Pull 时检测关联项目并提示文件同步
- 后台自动同步轮询（30秒–5分钟，可配置）
- 自动端口选择（尝试 8080-8099）
- UDP 广播用于局域网自动发现
- 文件同步前检查 Git 未提交更改
- 每次写入操作前自动备份

---

## GUI

GUI 是 CLI 的轻量封装（`import codex_chat_transformer as ct`），无代码重复。

### GUI 功能

- 一键切换提供商
- 后台线程转换 —— GUI 不会冻结
- 编辑提供商：按钮或右键上下文菜单
- 模型和推理能力可在信息面板中内联编辑
- 推理能力下拉菜单：low / medium / high / xhigh / default
- 自动检测应用程序旁边的 JSON 配置
- 导入时如缺少 API 密钥会提示输入
- 提供商 `openai` 为只读（通过 Codex 身份验证）
- 自动迁移旧版 `config.toml` 格式配置文件
- RU / EN 界面

### 启动

| 平台 | 命令 |
|---|---|
| Windows | `codex_manager.cmd`（双击） |
| PowerShell | `.\codex_manager.ps1` |
| Linux / macOS | `./codex_manager.sh` |

### 添加提供商

将 JSON 文件放在应用程序旁边 —— 它会被自动检测。如果没有 API 密钥，程序会提示输入。

```json
{
  "name": "NeuroGate API",
  "model": "gpt-5.5",
  "base_url": "https://api.example.com/v1",
  "wire_api": "responses",
  "model_reasoning_effort": "medium"
}
```

---

## 系统要求

- Python 3.7+
- Tkinter（包含在标准 Python 中）
- 无外部依赖

### 可选：系统托盘

系统托盘小组件，带彩色状态指示器：
- 红色 — 服务器已停止
- 黄色 — 服务器运行中，等待连接
- 绿色 — 正在同步

```bash
pip install pystray Pillow
python sync_tray.py
```

功能：启动/停止服务器、打开 Dashboard、开机自启（Windows/macOS）、单实例保护。
托盘完全可选 — 主工具和 Dashboard 无需它即可运行。

---

## 安全性

API 密钥在本地使用 base64 混淆存储（CLI 和 GUI 均如此）。这**不是**加密。请妥善保管 `providers.json` 和 `auth.json`。本工具不会将密钥发送到除已配置 API 端点之外的任何地方。

---

## 常见问题

**问：切换连接方式后聊天消失了。**

答：转换为当前提供商：先用 `--list` 查看名称，然后 `--from openai --to YourProvider`。必须关闭 Codex。

**问：聊天可见但发送时返回 401。**

答：JSONL 中的提供商未更新。重新运行转换 —— 数据库和 JSONL 都会更新。

**问：如何只转换一个项目的聊天？**

答：`--from openai --to MyProvider --project my_project`。按数据库中的 `project` 字段过滤。

**问：转换时如何映射模型？**

答：`--from openai --to MyProvider --from-model gpt-4 --to-model gpt-5.5`。替换 JSONL 文件中的模型名称。

**问：可以撤销吗？**

答：三种方式：
1. `--restore backup_YYYYMMDD_HHMMSS` —— 回滚数据库
2. `--restore-zip file.zip` —— 完整恢复
3. 反向转换：`--from YourProvider --to openai`

**问：必须关闭 Codex 吗？**

答：**是的。** Codex 会保持数据库打开，可能会覆盖更改。

**问：`--doctor` 做什么？**

答：只读诊断：检查数据库、配置、身份验证、提供商、固定线程。不更改任何内容。

**问：如何在不切换提供商的情况下更改模型？**

答：GUI：点击信息面板中的模型并输入新的。CLI：`--set-model gpt-5.5`。

**问：如何更改推理强度？**

答：GUI：信息面板中的下拉菜单。CLI：`--edit-provider NAME --set-reasoning high`。

**问：如何在两台电脑之间同步提供商？**

答：在两台机器上运行 `--sync-host`。在浏览器中打开 Dashboard，输入远程 IP + PIN，选择提供商并点击 Pull 或 Push。

**问：可以不用 Dashboard 进行同步吗？**

答：可以：`--sync-pull IP:PORT --pin XXXXXX` 会打开交互式 CLI 菜单。

---

## 存储位置

| 文件 | 内容 |
|---|---|
| `state_5.sqlite` → `threads` | 聊天元数据：提供商、标题、项目、令牌数 |
| `sessions/YYYY/MM/DD/rollout-*.jsonl` | 完整聊天历史 |
| `.codex-global-state.json` → `pinned-thread-ids` | 固定的聊天 |
| `config.toml` | 所有提供商 `[model_providers.*]` + 设置 |
| `auth.json` | 当前身份验证（API 密钥或 OAuth） |
| `providers.json` | 提供商配置文件（`provider_section` + `model` + 身份验证，b64 混淆） |

---

## 文件列表

```
codex_chat_transformer.py    — CLI：转换、提供商、固定、备份、诊断、编辑、同步
codex_manager_gui.py         — GUI：切换、编辑、更改模型、同步（CLI 封装）
codex_sync.py                — P2P 同步引擎：服务器、客户端、Dashboard、文件同步、自动同步
sync_tray.py                 — 系统托盘小组件（可选，需 pystray + Pillow）
test_smoke.py                — 冒烟测试（26 个测试）
codex_manager.cmd / .ps1     — Windows 启动器
codex_manager.sh             — Unix 启动器
providers_template.json      — 提供商模板
providers_example.json       — 提供商示例
CHANGELOG.md                 — 更新日志
install.sh / install.ps1     — 一键安装程序
```

## 许可证

[MIT](LICENSE)
