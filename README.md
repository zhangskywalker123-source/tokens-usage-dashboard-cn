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
- 原生窗口版支持通过 `TOKEN_DASH_DEBUG_FILE` 显式启用启动诊断日志；默认不写诊断文件。

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

`usage.json`、生成的 `看板.html`、EXE、运行时依赖和预览图均被 `.gitignore` 排除。它们可能包含个人用量、模型名称、项目路径或会话信息，不应提交到公共仓库。运行看板时，统计文件保留在本机；本地 HTTP 服务只提供看板页面，并仅接受同源刷新请求。

仓库不附带项目开源许可证。第三方组件的许可证信息见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)；未明确授予的项目代码复用权利仍归作者所有。
