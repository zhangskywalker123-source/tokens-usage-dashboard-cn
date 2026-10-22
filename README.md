# Tokens 用量统计中文看板

**A local Windows dashboard for AI token usage and WorkBuddy credits.**

[English README](README.en.md)

本项目读取本机 AI 客户端日志，通过 CodeBurn 汇总常见客户端用量，并补充解析 WorkBuddy 项目 JSONL 中的模型 token 与积分记录。看板以中文展示人民币金额、供应商/客户端排行、按日趋势和明细；美元汇率及积分单价是可配置源码常量。

## 功能

- CodeBurn 本地导出与 WorkBuddy JSONL 本地解析。
- 按北京时间自然日汇总；免费模型按 token 占比展示，付费模型按花费占比展示。
- 项目、工具、客户端和供应商排行按指标降序排列。
- Chart.js 内嵌 HTML，生成页可离线浏览。
- 提供浏览器版和可选 Tkinter 原生窗口版两个 Windows 前端。浏览器版的服务仅绑定 `127.0.0.1`；原生版不启动 HTTP 服务。
- 原生版首次显示前自动刷新 CodeBurn；HTML 快照超过 60 分钟会显示过期提示，避免把旧汇总误当成今日数据。
- 原生窗口版支持通过 `TOKEN_DASH_DEBUG_FILE` 显式启用启动诊断日志；默认不写诊断文件。
- 原生窗口版启动时先刷新 CodeBurn 快照；若导出数据超过 60 分钟，HTML 看板会显示过期提醒。

## Agent 与模型支持范围

本项目是本地用量看板，不调用、托管或执行 Agent/大模型。Agent 支持是指锁定依赖 CodeBurn 0.9.27 能从本机日志读取用量；WorkBuddy 通过本项目自己的 JSONL 解析器读取。CodeBurn 的上游适配清单可在 [CodeBurn 0.9.27 README](https://github.com/getagentseal/codeburn/blob/v0.9.27/README.md) 核对。

CodeBurn 0.9.27 适配的 42 种客户端/Agent：Amp、Antigravity、Claude Code、Cline、Cline CLI、Codebuff、Codex、CodeWhale、Command Code、Copilot、Crush、Cursor、Cursor Agent、DeepSeek Harness、Devin、Droid、Forge、Gemini CLI、Goose、Grok Bot、Grok Build、Hermes Agent、IBM Bob、KiloCode、Kimi、Kimi Code、Kiro、LingTai TUI、Mistral Vibe、Mux、OMP、Open Design、OpenClaude、OpenClaw、OpenCode、Pi、Qwen、Quick Desktop、Warp、ZCode、Zed、Zerostack。另有 Vercel AI Gateway 用量导入；它是网关数据源，不计作客户端/Agent。

模型名称只用于本地统计和供应商归类，不代表看板支持调用或运行相应模型。显式归类覆盖 OpenAI、Anthropic、Google、xAI、Mistral AI、Cohere、Meta、Perplexity、Amazon、Microsoft、NVIDIA、AI21 Labs、DeepSeek、Kimi/Moonshot、Qwen、智谱、豆包、腾讯、百度、MiniMax、零一万物、阶跃星辰及明确的本地运行器（Ollama、LM Studio、llama.cpp）；未识别的模型名归入「其他」。归类基于模型 ID 关键词，第三方网关自定义别名可能需要按实际模型名补充规则。

**边界说明：**CodeBurn 是否能统计到具体记录，还取决于对应客户端版本、日志是否留存及上游适配器格式；本项目不承诺所有版本和配置均有日志。若某客户端没有被上游适配，或模型仍显示为「其他」，请提交脱敏后的模型 ID/日志样例以便添加并测试适配，不要上传个人用量快照或含密钥的日志。

## 开发与测试

前置条件：Windows、Node.js 22、npm、Python 3.11；构建 EXE 需要 PyInstaller 6.20.0。

```powershell
node --test tests/dashboard.test.js
python -m unittest discover -s tests -p 'test_*.py' -v
```

准备 CodeBurn 依赖、复制 Node 运行时并构建浏览器版与原生窗口版 EXE：

```powershell
.\exe-build\build.ps1 -NodeExe "C:\Path\To\Node22\node.exe"
```

构建产物写入 `exe-build/dist/`，不会进入 Git。若只需手动刷新开发目录数据，可运行 `刷新数据.bat`；该操作会扫描当前 Windows 用户的本机用量日志并覆盖本地 `usage.json` 与 `看板.html`。

## 隐私与发布

构建时同时生成 Tokens用量看板安装程序.exe。运行后选择安装父目录，程序会创建“Tokens用量统计中文看板”子文件夹，将主 EXE 放入其中并创建桌面快捷方式。首次释放的运行时及本地数据也保留在该文件夹。安装器使用 Windows 自带的 IExpress 和 PowerShell，不需要额外安装打包工具。

构建出的 EXE 已内置 Python/Tk、Node.js 和 CodeBurn 运行时；目标电脑无需预装 Python、Node.js 或 npm。首次启动会将 Node/CodeBurn 解压到主程序旁的 _runtime 目录。安装目录需允许当前用户写入。

`usage.json`、生成的 `看板.html`、EXE、运行时依赖和预览图均被 `.gitignore` 排除。它们可能包含个人用量、模型名称、项目路径或会话信息，不应提交到公共仓库。运行看板时，统计文件保留在本机；本地 HTTP 服务只提供看板页面，并仅接受同源刷新请求。

仓库不附带项目开源许可证。第三方组件的许可证信息见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)；未明确授予的项目代码复用权利仍归作者所有。
