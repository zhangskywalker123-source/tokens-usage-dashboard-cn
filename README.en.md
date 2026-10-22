# Tokens Usage Dashboard (Chinese UI)

**A local Windows dashboard for AI token usage and WorkBuddy credits.**

[中文说明](README.md)

This project reads local AI-client usage logs through CodeBurn and adds a parser for model-token and credit records in WorkBuddy project JSONL files. The generated Chinese dashboard reports RMB estimates, provider/client rankings, daily trends, and detailed usage tables. Exchange and credit rates are source constants, not live prices.

## Features

- Local CodeBurn export plus local WorkBuddy JSONL parsing.
- Beijing-calendar-day aggregation. Free models use token-share percentages; paid models use cost-share percentages.
- Project, tool, client, and provider rankings sorted by their displayed metric.
- Chart.js is embedded in the generated HTML for offline viewing.
- The Windows single-file executable serves the dashboard from a loopback-only HTTP server.

## Development and tests

Requirements: Windows, Node.js 22, npm, and Python 3.11. Building the executable uses PyInstaller 6.20.0.

```powershell
node --test tests/dashboard.test.js
python -m unittest discover -s tests -p 'test_app.py' -v
```

Prepare the CodeBurn dependency, copy the Node runtime, and build the executable:

```powershell
.\exe-build\build.ps1 -NodeExe "C:\Path\To\Node22\node.exe"
```

Build artifacts go to `exe-build/dist/` and are excluded from Git. Running `刷新数据.bat` scans the current Windows user's local usage logs and replaces the local `usage.json` and `看板.html` files.

## Privacy and licensing

`usage.json`, the generated dashboard, executables, runtime dependencies, and preview images are excluded by `.gitignore`. They may reveal usage data, model names, project paths, or session information and must not be committed to a public repository. Runtime statistics remain on the local machine. The local HTTP server serves only the dashboard and accepts same-origin refresh requests.

No project license is included. Third-party notices are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Rights not expressly granted remain with the author.
