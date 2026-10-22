import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
NATIVE_PATH = ROOT / "exe-build" / "native_dashboard.py"
SPEC = importlib.util.spec_from_file_location("native_dashboard", NATIVE_PATH)
native = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native)


class NativeDashboardTests(unittest.TestCase):
    def test_embedded_runtime_extracts_from_root_and_legacy_nested_archive_locations(self):
        for archive_relative_path in ('runtime.zip', 'runtime.zip/runtime.zip', 'bundle/runtime.zip'):
            with self.subTest(archive=archive_relative_path), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                archive_path = root / archive_relative_path
                archive_path.parent.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(archive_path, 'w') as archive:
                    archive.writestr('node.exe', b'node-runtime')
                    archive.writestr('node_modules/codeburn/dist/cli.js', b'codeburn-cli')

                progress = []
                runtime_dir = native.ensure_runtime(str(root / 'app'), str(root), lambda _: None, progress.append)

                self.assertEqual((Path(runtime_dir) / 'node.exe').read_bytes(), b'node-runtime')
                self.assertEqual(
                    (Path(runtime_dir) / 'node_modules/codeburn/dist/cli.js').read_bytes(), b'codeburn-cli'
                )
                self.assertEqual(progress, [1.0])

    def test_native_spec_places_runtime_archive_at_meipass_root(self):
        spec = (ROOT / 'exe-build' / 'TokenDashGUI.spec').read_text(encoding='utf-8')
        self.assertIn("datas=[('bundle/runtime.zip', '.')],", spec)

    def test_installer_script_places_program_in_named_folder_and_creates_shortcut(self):
        powershell = shutil.which('powershell.exe')
        if not powershell:
            self.skipTest('Windows PowerShell is unavailable')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = root / 'payload'
            parent = root / 'install-root'
            desktop = root / 'desktop'
            payload.mkdir()
            parent.mkdir()
            (payload / 'app.exe').write_bytes(b'test executable')
            shutil.copy2(ROOT / 'exe-build' / 'installer.ps1', payload / 'install.ps1')
            result = subprocess.run([
                powershell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                str(payload / 'install.ps1'), '-ParentPath', str(parent), '-DesktopPath', str(desktop), '-NoLaunch',
            ], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)

            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            installed = parent / 'Tokens用量统计中文看板'
            self.assertEqual((installed / 'Tokens用量统计中文看板.exe').read_bytes(), b'test executable')
            self.assertTrue((desktop / 'Tokens用量统计中文看板.lnk').is_file())

    def test_model_vendor_classification_covers_major_families_without_guessing_local_execution(self):
        cases = {
            'grok-4': ('xAI', '国外'),
            'mistral-large-latest': ('Mistral AI', '国外'),
            'command-r-plus': ('Cohere', '国外'),
            'meta-llama/llama-4': ('Meta', '国外'),
            'sonar-pro': ('Perplexity', '国外'),
            'llama-3.1-sonar-small-128k-online': ('Perplexity', '国外'),
            'amazon.nova-pro': ('Amazon', '国外'),
            'microsoft/phi-4': ('Microsoft', '国外'),
            'nvidia/nemotron': ('NVIDIA', '国外'),
            'qwen3-max': ('阿里巴巴', '国内'),
            'llava:latest': ('其他', '-'),
            'ollama/qwen3.5:9b': ('本地模型', '本地'),
        }
        for model, expected in cases.items():
            with self.subTest(model=model):
                self.assertEqual(native.vendor_of(model), expected)

    def test_native_startup_refreshes_codeburn_before_loading_snapshot(self):
        events = []

        def prepare_runtime(exe_dir, meipass, log, prog_cb=None):
            events.append("runtime")
            return "runtime-dir"

        def refresh(exe_dir, runtime_dir, log):
            events.append("collect")
            self.assertEqual(runtime_dir, "runtime-dir")
            return True, ""

        with patch.object(native, "ensure_runtime", side_effect=prepare_runtime), \
                patch.object(native, "collect", side_effect=refresh):
            result = native.prepare_initial_snapshot("app-dir", "bundle-dir", lambda _: None)

        self.assertEqual(events, ["runtime", "collect"])
        self.assertEqual(result, ("runtime-dir", True, ""))

    def test_native_collect_passes_a_nonexistent_output_path_to_codeburn(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "usage.json").write_text('{"records": ["old"]}', encoding="utf-8")
            (root / "看板.html").write_text("old html", encoding="utf-8")

            def fake_run(args, cwd, **kwargs):
                if str(args[1]).endswith("cli.js"):
                    output = Path(args[-1])
                    self.assertFalse(output.exists(), "CodeBurn refuses to overwrite the mkstemp placeholder")
                    output.write_text(json.dumps({"records": []}), encoding="utf-8")
                else:
                    Path(cwd, "看板.html").write_text("fresh html", encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout=b"")

            with patch.object(native.subprocess, "run", side_effect=fake_run):
                self.assertEqual(native.collect(str(root), str(root / "_runtime"), lambda _: None), (True, ""))

            self.assertEqual((root / "usage.json").read_text(encoding="utf-8"), '{"records": []}')
            self.assertEqual((root / "看板.html").read_text(encoding="utf-8"), "old html")

    def test_time_normalization_and_aggregate_ties_are_deterministic(self):
        ts = native.parse_ts_ms("2026-10-22 09:30:00")
        self.assertEqual(native.bj_day(ts), "2026-10-22")
        self.assertIsNone(native.parse_ts_ms("not-a-time"))

        rows = native.agg_by([
            {"model": "small", "cost": 0, "inputTokens": 20},
            {"model": "large", "cost": 0, "inputTokens": 80},
        ], lambda row: row["model"])
        self.assertEqual([row["key"] for row in rows], ["large", "small"])

    def test_native_data_model_ranks_workbuddy_client_models_projects_and_tools(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            project_dir = home / ".workbuddy" / "projects" / "fixture"
            project_dir.mkdir(parents=True)
            usage_file = root / "usage.json"
            today = native.bj_now_day()
            timestamp = today + "T12:00:00"
            wb_rows = [
                {
                    "id": "deepseek-call", "timestamp": timestamp,
                    "providerData": {"messageId": "deepseek-call", "model": "deepseek-r1"},
                    "message": {"usage": {"inputTokens": 400, "outputTokens": 100}},
                },
                {
                    "id": "qwen-call", "timestamp": timestamp,
                    "providerData": {"messageId": "qwen-call", "model": "qwen-plus"},
                    "message": {"usage": {"input_tokens": 100, "output_tokens": 0}},
                },
                {
                    "id": "credit-call", "timestamp": timestamp,
                    "providerData": {"toolResult": {"rawResponse": {"credit": 5.71}}},
                },
                {
                    "id": "credit-call", "timestamp": timestamp,
                    "providerData": {"toolResult": {"rawResponse": {"credit": 5.71}}},
                },
            ]
            (project_dir / "events.jsonl").write_text(
                "\n".join(json.dumps(row) for row in wb_rows) + "\n", encoding="utf-8"
            )
            data = {
                "generated": timestamp,
                "summary": [],
                "records": [{
                    "provider": "codex", "model": "gpt-5", "timestamp": timestamp,
                    "inputTokens": 10, "outputTokens": 0, "cacheReadTokens": 0,
                    "cacheWriteTokens": 0, "cost": 0.01,
                }],
                "projects": [
                    {"Project": "small", "Share (%)": 10, "Cost (USD)": 1},
                    {"Project": "large", "Share (%)": 50, "Cost (USD)": 5},
                ],
                "tools": [{"Tool": "few", "Calls": 1}, {"Tool": "many", "Calls": 10}],
            }
            usage_file.write_text(json.dumps(data), encoding="utf-8")

            original_expanduser = native.os.path.expanduser

            def expanduser(path):
                return str(home) if path == "~" else original_expanduser(path)

            with patch.object(native.os.path, "expanduser", side_effect=expanduser):
                result = native.build_data(str(root))

            self.assertEqual(result["by_client"][0]["key"], "workbuddy")
            detail_rows = result["client_details"]["workbuddy"]["rows"]
            self.assertEqual([row["model"] for row in detail_rows], [
                "图片生成等工具（积分）", "deepseek-r1", "qwen-plus",
            ])
            self.assertEqual(result["wb"]["count"], 1)
            self.assertEqual([project["Project"] for project in result["projects"]], ["large", "small"])
            self.assertEqual([tool["Tool"] for tool in result["tools"]], ["many", "few"])
            self.assertEqual([client[0] for client in result["clients"]], ["workbuddy", "codex"])


if __name__ == "__main__":
    unittest.main()
