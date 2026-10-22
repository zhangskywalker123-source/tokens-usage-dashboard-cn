# -*- coding: utf-8 -*-
"""Tokens 用量统计中文看板 - 单文件 exe
双击运行：统计本机各 AI 工具 token 用量，生成中文看板，
内置本地服务打开看板，页面右上角「刷新数据」可重新统计并更新。
"""
import os
import json
import sys
import shutil
import subprocess
import time
import tempfile
import webbrowser
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import quote, unquote, urlsplit

APP_NAME = "Tokens 用量统计中文看板"


def log(msg):
    print(msg, flush=True)


def find_dirs():
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        meipass = sys._MEIPASS
    else:
        exe_dir = os.path.dirname(os.path.abspath(__file__))
        meipass = exe_dir
    return exe_dir, meipass


def ensure_runtime(exe_dir, meipass):
    """准备运行时；不完整的解压会从包内资源补齐。"""
    runtime_dir = os.path.join(exe_dir, "_runtime")
    node = os.path.join(runtime_dir, "node.exe")
    bundle_dir = os.path.join(meipass, "bundle")
    asset_dir = meipass
    if not os.path.isdir(os.path.join(asset_dir, "runtime")) and os.path.isdir(os.path.join(bundle_dir, "runtime")):
        asset_dir = bundle_dir

    src = os.path.join(asset_dir, "runtime")
    required = (node, os.path.join(runtime_dir, "node_modules", "codeburn", "dist", "cli.js"))
    if not all(os.path.isfile(item) for item in required):
        if not os.path.isdir(src):
            raise FileNotFoundError(f"内置运行时不存在：{src}")
        log("首次运行，正在准备运行环境，约需 10 秒……")
        t = time.time()
        os.makedirs(exe_dir, exist_ok=True)
        shutil.copytree(src, runtime_dir, dirs_exist_ok=True)
        if not all(os.path.isfile(item) for item in required):
            raise RuntimeError("运行时文件仍不完整，请删除程序旁的 _runtime 文件夹后重试。")
        log(f"环境准备完成（{time.time() - t:.1f} 秒）")

    for fname in ("build.js", "chart.umd.min.js"):
        fpath = os.path.join(exe_dir, fname)
        source = os.path.join(asset_dir, fname)
        if not os.path.isfile(source):
            raise FileNotFoundError(f"内置资源不存在：{source}")
        fd, staged = tempfile.mkstemp(prefix=f".{fname}.", suffix=".tmp", dir=exe_dir)
        os.close(fd)
        try:
            shutil.copyfile(source, staged)
            os.replace(staged, fpath)
        finally:
            if os.path.exists(staged):
                os.unlink(staged)
    return runtime_dir


def collect(exe_dir, runtime_dir):
    """运行 codeburn export + build.js，成功返回 True。"""
    node = os.path.join(runtime_dir, "node.exe")
    cli = os.path.join(runtime_dir, "node_modules", "codeburn", "dist", "cli.js")
    env = dict(os.environ)
    env["NODE_PATH"] = os.path.join(runtime_dir, "node_modules")
    usage_json = os.path.join(exe_dir, "usage.json")
    fd, staged_usage = tempfile.mkstemp(prefix=".usage-", suffix=".json", dir=exe_dir)
    os.close(fd)
    build_dir = None

    try:
        log("正在扫描本机各 AI 工具的用量数据（codex / claude / cursor 等）……")
        r1 = subprocess.run(
            [node, cli, "export", "--format", "json", "-o", staged_usage],
            cwd=exe_dir, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        if r1.returncode != 0 or not os.path.isfile(staged_usage):
            log("统计失败：")
            log(r1.stdout.decode("utf-8", "ignore")[-2000:])
            return False
        with open(staged_usage, "r", encoding="utf-8") as f:
            usage = json.load(f)
        if not isinstance(usage, dict) or not isinstance(usage.get("records"), list):
            log("统计失败：CodeBurn 导出的数据格式不正确。")
            return False

        build_dir = tempfile.mkdtemp(prefix=".dashboard-build-", dir=exe_dir)
        for fname in ("build.js", "chart.umd.min.js"):
            shutil.copy2(os.path.join(exe_dir, fname), os.path.join(build_dir, fname))
        shutil.copy2(staged_usage, os.path.join(build_dir, "usage.json"))

        log("正在生成中文看板……")
        r2 = subprocess.run([node, os.path.join(build_dir, "build.js")],
                            cwd=build_dir, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if r2.returncode != 0:
            log("看板生成失败：")
            log(r2.stdout.decode("utf-8", "ignore")[-2000:])
            return False
        generated_html = os.path.join(build_dir, "看板.html")
        if not os.path.isfile(generated_html):
            log("看板生成失败：没有生成 看板.html。")
            return False

        os.replace(staged_usage, usage_json)
        os.replace(generated_html, os.path.join(exe_dir, "看板.html"))
        return True
    except (OSError, ValueError) as exc:
        log(f"统计或看板生成失败：{exc}")
        return False
    finally:
        for item in (staged_usage, build_dir):
            if item and os.path.exists(item):
                if os.path.isdir(item):
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    os.unlink(item)


def make_handler(state):
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _valid_host(self):
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_address[1]}"

        def _same_origin(self):
            expected = f"http://127.0.0.1:{self.server.server_address[1]}"
            return self._valid_host() and self.headers.get("Origin") == expected

        def do_GET(self):
            if not self._valid_host() or unquote(urlsplit(self.path).path) != "/看板.html":
                self.send_error(404)
                return
            target = os.path.join(state["exe_dir"], "看板.html")
            try:
                with open(target, "rb") as f:
                    body = f.read()
            except OSError:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if urlsplit(self.path).path != "/refresh":
                self.send_error(404)
                return
            if not self._same_origin():
                self.send_error(403)
                return
            with state["lock"]:
                if state["busy"]:
                    self.send_response(429)
                    self.end_headers()
                    return
                state["busy"] = True
            try:
                ok = collect(state["exe_dir"], state["runtime_dir"])
                self.send_response(204 if ok else 500)
                self.end_headers()
            except Exception as exc:
                log(f"刷新失败：{exc}")
                self.send_error(500)
            finally:
                with state["lock"]:
                    state["busy"] = False

    return Handler


def main():
    exe_dir, meipass = find_dirs()
    try:
        runtime_dir = ensure_runtime(exe_dir, meipass)
    except Exception as exc:
        log(f"运行环境准备失败：{exc}")
        log("可按任意键退出。")
        try:
            input()
        except EOFError:
            pass
        return

    if not collect(exe_dir, runtime_dir):
        log("可按任意键退出。")
        try:
            input()
        except EOFError:
            pass
        return

    # 内置本地服务：看页面 + 提供 /refresh 重新统计
    state = {"exe_dir": exe_dir, "runtime_dir": runtime_dir, "busy": False, "lock": threading.Lock()}

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/{quote('看板.html')}"
    log(f"完成！看板地址：{url}")
    webbrowser.open(url)
    log("提示：使用期间请保持本窗口打开，关闭窗口即退出（看板页面也会随之失效）。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
