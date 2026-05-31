#!/usr/bin/env python3
"""
二游更新日历 — 本地 HTTP 服务器
=================================
监听 localhost:8888，提供静态文件服务 + POST /api/update 端点。
纯标准库实现，无第三方依赖。

用法：
    python server.py
"""

import os
import sys
import json
import re
import subprocess
import ssl
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

PORT = 8888
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


class CalendarHandler(SimpleHTTPRequestHandler):
    """自定义请求处理：静态文件 + API 端点"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SCRIPT_DIR, **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/update":
            self._handle_update()
        elif parsed.path == "/api/analyze":
            self._handle_analyze()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error":"Not Found"}')

    def _handle_update(self):
        try:
            fetch_script = os.path.join(SCRIPT_DIR, "fetch_updates.py")
            index_path = os.path.join(SCRIPT_DIR, "index.html")

            result = subprocess.run(
                [sys.executable, fetch_script, "--sync-html", index_path],
                cwd=SCRIPT_DIR,
                capture_output=True,
                text=True,
                timeout=30,
            )

            output = result.stdout + result.stderr

            # 即使脚本返回非零退出码（如网络搜索部分失败），只要执行了就返回 success
            if result.returncode == 0:
                status_code = 200
                resp = json.dumps({
                    "success": True,
                    "message": "数据更新完成",
                    "log": output[-3000:],
                }, ensure_ascii=False)
            elif "文件不存在" in output:
                status_code = 500
                resp = json.dumps({
                    "success": False,
                    "error": "data.json 文件不存在",
                    "log": output[-3000:],
                }, ensure_ascii=False)
            else:
                # 脚本执行了但可能有部分搜索失败，仍算成功
                status_code = 200
                resp = json.dumps({
                    "success": True,
                    "message": "更新完成（部分搜索可能失败，详见日志）",
                    "log": output[-3000:],
                }, ensure_ascii=False)

            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(resp.encode("utf-8"))

        except subprocess.TimeoutExpired:
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            resp = json.dumps({
                "success": True,
                "message": "更新请求已提交（超时，脚本可能仍在后台运行）",
                "log": "脚本执行超过 30 秒，已超时",
            }, ensure_ascii=False)
            self.wfile.write(resp.encode("utf-8"))
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            resp = json.dumps({
                "success": False,
                "error": str(e),
                "log": "",
            }, ensure_ascii=False)
            self.wfile.write(resp.encode("utf-8"))

    def _handle_analyze(self):
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len).decode("utf-8")
            req_data = json.loads(body)
            game_name = req_data.get("name", "").strip()

            if not game_name or len(game_name) < 2:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": "游戏名至少需要 2 个字符",
                }, ensure_ascii=False).encode("utf-8"))
                return

            fetch_script = os.path.join(SCRIPT_DIR, "fetch_updates.py")
            data_path = os.path.join(SCRIPT_DIR, "data.json")

            result = subprocess.run(
                [sys.executable, fetch_script, "--analyze-only", game_name, "--data", data_path],
                cwd=SCRIPT_DIR,
                capture_output=True,
                text=True,
                timeout=120,
            )

            output = result.stdout + result.stderr

            if result.returncode != 0:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": False,
                    "error": f"分析失败，脚本退出码: {result.returncode}",
                }, ensure_ascii=False).encode("utf-8"))
                return

            # 提取 stdout 中最后一个 JSON 对象
            json_match = re.search(r'\{[\s\S]*"cycle_days"[\s\S]*\}', output)
            if not json_match:
                json_match = re.search(r'\{[\s\S]*\}', output)

            if not json_match:
                raise ValueError("未找到有效的分析结果")

            analyze_result = json.loads(json_match.group(0))

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": True,
                "data": analyze_result,
            }, ensure_ascii=False).encode("utf-8"))

        except subprocess.TimeoutExpired:
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": False,
                "error": "分析超时（超过 2 分钟），请检查网络后重试",
            }, ensure_ascii=False).encode("utf-8"))
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": False,
                "error": str(e),
            }, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format, *args):
        # 精简日志输出
        sys.stdout.write("[server] %s\n" % (args[0]))


def main():
    print(f"二游更新日历 — 本地服务器")
    print(f"地址: http://localhost:{PORT}")
    print(f"目录: {SCRIPT_DIR}")
    print(f"按 Ctrl+C 停止服务器\n")

    server = HTTPServer(("localhost", PORT), CalendarHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务器已停止")
        server.shutdown()


if __name__ == "__main__":
    main()