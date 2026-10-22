import importlib.util
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "exe-build" / "app.py"
SPEC = importlib.util.spec_from_file_location("token_dashboard_app", APP_PATH)
app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(app)


class AppTests(unittest.TestCase):
    def test_ensure_runtime_repairs_partial_install_and_refreshes_embedded_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            exe_dir = root / "app"
            bundle = root / "bundle"
            runtime_source = bundle / "runtime"
            (runtime_source / "node_modules" / "codeburn" / "dist").mkdir(parents=True)
            (runtime_source / "node.exe").write_bytes(b"bundled-node")
            (runtime_source / "node_modules" / "codeburn" / "dist" / "cli.js").write_text("cli", encoding="utf-8")
            (bundle / "build.js").write_text("new build", encoding="utf-8")
            (bundle / "chart.umd.min.js").write_text("new chart", encoding="utf-8")
            partial = exe_dir / "_runtime"
            partial.mkdir(parents=True)
            (partial / "node.exe").write_bytes(b"partial")
            exe_dir.mkdir(exist_ok=True)
            (exe_dir / "build.js").write_text("old build", encoding="utf-8")
            (exe_dir / "chart.umd.min.js").write_text("old chart", encoding="utf-8")

            result = app.ensure_runtime(str(exe_dir), str(bundle))

            self.assertEqual(result, str(partial))
            self.assertEqual((partial / "node.exe").read_bytes(), b"bundled-node")
            self.assertTrue((partial / "node_modules" / "codeburn" / "dist" / "cli.js").is_file())
            self.assertEqual((exe_dir / "build.js").read_text(encoding="utf-8"), "new build")
            self.assertEqual((exe_dir / "chart.umd.min.js").read_text(encoding="utf-8"), "new chart")

    def test_collect_commits_outputs_only_after_successful_build(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            exe_dir = root / "app"
            runtime = root / "runtime"
            exe_dir.mkdir()
            runtime.mkdir()
            (exe_dir / "build.js").write_text("builder", encoding="utf-8")
            (exe_dir / "chart.umd.min.js").write_text("chart", encoding="utf-8")
            (exe_dir / "usage.json").write_text('{"records": []}', encoding="utf-8")
            (exe_dir / "看板.html").write_text("previous", encoding="utf-8")

            def successful_run(args, cwd, **kwargs):
                if str(args[1]).endswith("cli.js"):
                    Path(args[-1]).write_text(json.dumps({"records": []}), encoding="utf-8")
                    return SimpleNamespace(returncode=0, stdout=b"exported")
                Path(cwd, "看板.html").write_text("fresh", encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout=b"built")

            with patch.object(app.subprocess, "run", side_effect=successful_run):
                self.assertTrue(app.collect(str(exe_dir), str(runtime)))
            self.assertEqual((exe_dir / "usage.json").read_text(encoding="utf-8"), '{"records": []}')
            self.assertEqual((exe_dir / "看板.html").read_text(encoding="utf-8"), "fresh")
            self.assertFalse(list(exe_dir.glob(".dashboard-build-*")))
            self.assertFalse(list(exe_dir.glob(".usage-*.json")))

            (exe_dir / "usage.json").write_text('{"records": ["old"]}', encoding="utf-8")
            (exe_dir / "看板.html").write_text("stable", encoding="utf-8")

            def failed_build(args, cwd, **kwargs):
                if str(args[1]).endswith("cli.js"):
                    Path(args[-1]).write_text(json.dumps({"records": ["new"]}), encoding="utf-8")
                    return SimpleNamespace(returncode=0, stdout=b"")
                return SimpleNamespace(returncode=1, stdout=b"build error")

            with patch.object(app.subprocess, "run", side_effect=failed_build):
                self.assertFalse(app.collect(str(exe_dir), str(runtime)))
            self.assertEqual((exe_dir / "usage.json").read_text(encoding="utf-8"), '{"records": ["old"]}')
            self.assertEqual((exe_dir / "看板.html").read_text(encoding="utf-8"), "stable")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "看板.html").write_text("dashboard", encoding="utf-8")
        (self.root / "usage.json").write_text("private data", encoding="utf-8")
        self.state = {
            "exe_dir": str(self.root),
            "runtime_dir": str(self.root / "_runtime"),
            "busy": False,
            "lock": threading.Lock(),
        }
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.make_handler(self.state))
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server_thread.join, 2)
        self.addCleanup(self.server.shutdown)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.origin = self.base_url

    def request(self, path, origin=None):
        headers = {}
        if origin is not None:
            headers["Origin"] = origin
        return urlopen(Request(self.base_url + path, headers=headers, method="POST"))

    def test_http_serves_only_dashboard_and_rejects_cross_origin_refresh(self):
        with urlopen(self.base_url + "/%E7%9C%8B%E6%9D%BF.html") as response:
            self.assertEqual(response.read(), b"dashboard")
            self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        with self.assertRaises(HTTPError) as private_file:
            urlopen(self.base_url + "/usage.json")
        self.assertEqual(private_file.exception.code, 404)
        with self.assertRaises(HTTPError) as wrong_origin:
            self.request("/refresh", "http://attacker.invalid")
        self.assertEqual(wrong_origin.exception.code, 403)

    def test_refresh_failures_release_lock_and_concurrent_requests_get_429(self):
        with patch.object(app, "collect", side_effect=RuntimeError("test failure")):
            with self.assertRaises(HTTPError) as failed:
                self.request("/refresh", self.origin)
        self.assertEqual(failed.exception.code, 500)
        deadline = time.monotonic() + 2
        while self.state["busy"] and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(self.state["busy"])

        entered = threading.Event()
        release = threading.Event()

        def blocked_collect(*args):
            entered.set()
            release.wait(3)
            return True

        first_result = []

        def first_request():
            try:
                with patch.object(app, "collect", side_effect=blocked_collect):
                    with self.request("/refresh", self.origin) as response:
                        first_result.append(response.status)
            except Exception as exc:  # surfaced as an assertion below
                first_result.append(exc)

        thread = threading.Thread(target=first_request)
        thread.start()
        self.assertTrue(entered.wait(2), "first refresh should start")
        try:
            with self.assertRaises(HTTPError) as busy:
                self.request("/refresh", self.origin)
            self.assertEqual(busy.exception.code, 429)
        finally:
            release.set()
        thread.join(3)
        self.assertEqual(first_result, [204])
        self.assertFalse(self.state["busy"])


if __name__ == "__main__":
    unittest.main()
