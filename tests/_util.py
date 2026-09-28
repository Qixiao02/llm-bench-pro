# -*- coding: utf-8 -*-
"""测试公共工具: 以与 server.py 相同的方式导入包内模块, 提供本地模拟 HTTP 服务。"""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "llm_bench_pro")
if PKG not in sys.path:
    sys.path.insert(0, PKG)
# 和正式运行一样先执行包的 __init__ (输出编码容错), 否则 CI 的 Windows (cp1252) 上打印中文会报错
if ROOT not in sys.path:
    sys.path.append(ROOT)
import llm_bench_pro  # noqa: E402,F401

# 所有测试使用临时数据库, 绝不触碰 data/llm_bench.db
_TMP = tempfile.mkdtemp(prefix="llmbench-test-")
os.environ["LLM_BENCH_DB"] = os.path.join(_TMP, "test.db")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def temp_dir():
    return tempfile.mkdtemp(dir=_TMP)


class MockServer:
    """handler(method, path, body_dict) -> (status, obj|bytes, content_type)。记录全部请求。"""

    def __init__(self, handler):
        self.calls = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _handle(self, method):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                try:
                    body = json.loads(raw) if raw else {}
                except ValueError:
                    body = {}
                outer.calls.append((method, self.path, body))
                code, payload, ctype = handler(method, self.path, body)
                data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype or "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                self._handle("POST")

            def do_GET(self):
                self._handle("GET")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def chat_reply(content, finish="stop", completion_tokens=5, reasoning=""):
    msg = {"content": content}
    if reasoning:
        msg["reasoning_content"] = reasoning
    return {"choices": [{"message": msg, "finish_reason": finish}],
            "usage": {"prompt_tokens": 10, "completion_tokens": completion_tokens}}
