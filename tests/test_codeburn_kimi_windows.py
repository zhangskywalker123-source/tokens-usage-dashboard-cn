import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "exe-build" / "bundle" / "runtime"
NODE = RUNTIME / "node.exe"
CODEBURN = RUNTIME / "node_modules" / "codeburn" / "dist" / "cli.js"


class WindowsKimiDesktopCodeBurnTests(unittest.TestCase):
    def test_embedded_kimi_code_wire_is_exported_from_windows_appdata_root(self):
        if not NODE.is_file() or not CODEBURN.is_file():
            self.skipTest("Bundled CodeBurn runtime is prepared by exe-build/build.ps1")

        with tempfile.TemporaryDirectory(prefix="token-dashboard-kimi-test-") as temp:
            root = Path(temp)
            home = root / "home"
            appdata = home / "AppData" / "Roaming"
            local_appdata = root / "local"
            session = (
                appdata / "kimi-desktop" / "daimon-share" / "daimon" / "runtime"
                / "kimi-code" / "home" / "sessions" / "wd_fixture_0123456789ab" / "conv-fixture"
            )
            wire = session / "agents" / "main" / "wire.jsonl"
            wire.parent.mkdir(parents=True)
            session.mkdir(parents=True, exist_ok=True)
            (session / "state.json").write_text(json.dumps({
                "createdAt": "2026-10-20T10:00:00.000Z",
                "updatedAt": "2026-10-20T10:01:00.000Z",
                "workDir": "C:/fixture-project",
                "agents": {"main": {"parentAgentId": None}},
            }), encoding="utf-8")

            events = [
                {"type": "metadata", "protocol_version": "1.4", "created_at": 1792490400000},
                {"type": "turn.prompt", "input": [{"type": "text", "text": "synthetic fixture"}], "time": 1792490400000},
                {"type": "llm.request", "model": "kimi-k3", "modelAlias": "fixture-model", "turnStep": "0.1", "time": 1792490401000},
                {"type": "usage.record", "model": "fixture-model", "usage": {
                    "inputOther": 123, "output": 45, "inputCacheRead": 7, "inputCacheCreation": 2,
                }, "usageScope": "turn", "time": 1792490402000},
            ]
            newline = chr(10)
            wire.write_text(newline.join(json.dumps(event) for event in events) + newline, encoding="utf-8")

            output = root / "usage.json"
            env = os.environ.copy()
            env.update({
                "USERPROFILE": str(home),
                "HOME": str(home),
                "APPDATA": str(appdata),
                "LOCALAPPDATA": str(local_appdata),
            })
            for key in list(env):
                if key.startswith("CODEBURN_") or key in {"KIMI_CODE_HOME", "KIMI_SHARE_DIR"}:
                    env.pop(key, None)

            appdata_probe = subprocess.run(
                [str(NODE), "-e", "process.stdout.write(process.env.APPDATA || 'unset')"],
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            self.assertEqual(appdata_probe.stdout, str(appdata))

            result = subprocess.run(
                [str(NODE), str(CODEBURN), "export", "--format", "json", "-o", str(output)],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            exported = json.loads(output.read_text(encoding="utf-8"))
            calls = [row for row in exported.get("records", []) if row.get("provider") == "kimicode"]
            providers = sorted({str(row.get("provider")) for row in exported.get("records", [])})
            self.assertEqual(
                len(calls), 1,
                "record providers: " + repr(providers) + "; stdout: " + result.stdout[-1000:] + "; stderr: " + result.stderr[-1000:],
            )
            self.assertEqual(calls[0]["model"], "kimi-k3")
            self.assertEqual(calls[0]["inputTokens"], 123)
            self.assertEqual(calls[0]["outputTokens"], 45)

    def test_vscode_copilot_chat_session_is_exported_from_windows_appdata_root(self):
        if not NODE.is_file() or not CODEBURN.is_file():
            self.skipTest("Bundled CodeBurn runtime is prepared by exe-build/build.ps1")

        with tempfile.TemporaryDirectory(prefix="token-dashboard-vscode-test-") as temp:
            root = Path(temp)
            home = root / "home"
            appdata = home / "AppData" / "Roaming"
            local_appdata = root / "local"
            chat_dir = appdata / "Code" / "User" / "workspaceStorage" / "workspace-fixture" / "chatSessions"
            chat_dir.mkdir(parents=True)
            chat_file = chat_dir / "session-fixture.jsonl"
            entries = [
                {"kind": 0, "v": {"version": 3, "creationDate": 1792490400000, "sessionId": "session-fixture", "requests": []}},
                {"kind": 2, "k": ["requests"], "v": [{
                    "requestId": "request-fixture",
                    "modelId": "copilot/claude-sonnet-4.6",
                    "completionTokens": 45,
                    "result": {"metadata": {"promptTokens": 123, "outputTokens": 45, "resolvedModel": "claude-sonnet-4-6"}},
                }]},
            ]
            newline = chr(10)
            chat_file.write_text(newline.join(json.dumps(entry) for entry in entries) + newline, encoding="utf-8")

            output = root / "usage.json"
            env = os.environ.copy()
            env.update({
                "USERPROFILE": str(home),
                "HOME": str(home),
                "APPDATA": str(appdata),
                "LOCALAPPDATA": str(local_appdata),
            })
            for key in list(env):
                if key.startswith("CODEBURN_") or key in {"KIMI_CODE_HOME", "KIMI_SHARE_DIR"}:
                    env.pop(key, None)

            result = subprocess.run(
                [str(NODE), str(CODEBURN), "export", "--format", "json", "-o", str(output)],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            exported = json.loads(output.read_text(encoding="utf-8"))
            calls = [row for row in exported.get("records", []) if row.get("provider") == "copilot"]
            self.assertEqual(len(calls), 1, "no Copilot record exported from the synthetic Windows workspaceStorage")
            self.assertEqual(calls[0]["inputTokens"], 123)
            self.assertEqual(calls[0]["outputTokens"], 45)


if __name__ == "__main__":
    unittest.main()
