# Tokens Usage Dashboard (Chinese UI)

**A local Windows dashboard for AI token usage and WorkBuddy credits.**

[中文说明](README.md)

This project reads local AI-client usage logs through CodeBurn and adds a parser for model-token and credit records in WorkBuddy project JSONL files. The generated Chinese dashboard reports RMB estimates, provider/client rankings, daily trends, and detailed usage tables. Exchange and credit rates are source constants, not live prices.

## Features

- Local CodeBurn export plus local WorkBuddy JSONL parsing.
- Beijing-calendar-day aggregation. Free models use token-share percentages; paid models use cost-share percentages.
- Project, tool, client, and provider rankings sorted by their displayed metric.
- Chart.js is embedded in the generated HTML for offline viewing.
- Two Windows frontends are available: a browser dashboard served only on `127.0.0.1`, and an optional native Tkinter window that starts no HTTP server.
- The native window refreshes CodeBurn before first display. HTML snapshots older than 60 minutes show a freshness warning to avoid mistaking stale totals for today's data.
- The native window can optionally write startup diagnostics when `TOKEN_DASH_DEBUG_FILE` is set; no diagnostic file is written by default.
- The native window refreshes CodeBurn before its first render; the HTML dashboard warns when its CodeBurn snapshot is older than 60 minutes.

## Agent and model coverage

This is a local usage dashboard; it does not call, host, or execute agents or LLMs. Agent support means that the pinned CodeBurn 0.9.27 dependency can read usage from local logs. WorkBuddy is parsed separately by this project's JSONL parser. Verify the upstream adapter list in the [CodeBurn 0.9.27 README](https://github.com/getagentseal/codeburn/blob/v0.9.27/README.md).

The 42 clients/agents adapted by CodeBurn 0.9.27 are: Amp, Antigravity, Claude Code, Cline, Cline CLI, Codebuff, Codex, CodeWhale, Command Code, Copilot, Crush, Cursor, Cursor Agent, DeepSeek Harness, Devin, Droid, Forge, Gemini CLI, Goose, Grok Bot, Grok Build, Hermes Agent, IBM Bob, KiloCode, Kimi, Kimi Code, Kiro, LingTai TUI, Mistral Vibe, Mux, OMP, Open Design, OpenClaude, OpenClaw, OpenCode, Pi, Qwen, Quick Desktop, Warp, ZCode, Zed, and Zerostack. Vercel AI Gateway usage can also be imported separately; it is a gateway data source, not a client/agent.

Model names are used only for local usage reporting and vendor classification. This does not mean the dashboard can invoke or run those models. Explicit vendor labels cover OpenAI, Anthropic, Google, xAI, Mistral AI, Cohere, Meta, Perplexity, Amazon, Microsoft, NVIDIA, AI21 Labs, DeepSeek, Kimi/Moonshot, Qwen, Zhipu, Doubao, Tencent, Baidu, MiniMax, 01.AI, StepFun, and explicit local-runner identifiers (Ollama, LM Studio, llama.cpp). Unrecognized model IDs are grouped as Other. Classification uses name patterns; custom aliases from third-party gateways may need additional rules.

**Coverage limits:** Whether a record appears depends on the client version, retained local logs, and the upstream adapter format. Support is not guaranteed for every version or configuration. For an unsupported client or a model shown as Other, submit a redacted model ID/log sample so an adapter can be added and tested. Do not upload personal usage snapshots or logs containing credentials.

## Development and tests

Requirements: Windows, Node.js 22, npm, and Python 3.11. Building the executable uses PyInstaller 6.20.0.

```powershell
node --test tests/dashboard.test.js
python -m unittest discover -s tests -p 'test_*.py' -v
```

Prepare CodeBurn, copy the Node runtime, and build both Windows frontends:

```powershell
.\exe-build\build.ps1 -NodeExe "C:\Path\To\Node22\node.exe"
```

Build artifacts go to `exe-build/dist/` and are excluded from Git. Running `刷新数据.bat` scans the current Windows user's local usage logs and replaces the local `usage.json` and `看板.html` files.

## Privacy and licensing

The built executables bundle Python/Tk, Node.js, and CodeBurn; target PCs do not need Python, Node.js, or npm installed. On first launch, the native app extracts Node/CodeBurn to an _runtime folder beside the executable, so keep it in a directory writable by the current user.

`usage.json`, the generated dashboard, executables, runtime dependencies, and preview images are excluded by `.gitignore`. They may reveal usage data, model names, project paths, or session information and must not be committed to a public repository. Runtime statistics remain on the local machine. The local HTTP server serves only the dashboard and accepts same-origin refresh requests.

No project license is included. Third-party notices are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Rights not expressly granted remain with the author.
