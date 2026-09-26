# -*- coding: utf-8 -*-
import http.client
import json
import os
import socket
import sys
import threading
import unittest

from _util import ROOT, temp_dir
import server
import sinks
import store
from test_store import iq_doc, perf_doc


class ServerCase(unittest.TestCase):
    token = ""

    @classmethod
    def setUpClass(cls):
        server.CONFIG.update(host="127.0.0.1", port=0, token=cls.token)
        cls.httpd = server.BenchServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        server.CONFIG["token"] = ""

    def request(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        data = json.dumps(body).encode() if body is not None else None
        c.request(method, path, body=data, headers=dict({"Content-Type": "application/json"}, **(headers or {})))
        r = c.getresponse()
        raw = r.read()
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = raw
        return r.status, dict(r.getheaders()), payload


class TestServer(ServerCase):
    def test_post_rejects_cross_origin_and_non_json(self):
        for headers, code in (({"Origin": "null"}, 403), ({"Origin": "http://evil.example"}, 403),
                              ({"Content-Type": "text/plain"}, 415)):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("POST", "/api/run-delete", {"run_id": "x"}, headers)[0], code)
        st = self.request("POST", "/api/run-delete", {"run_id": "x"}, {"Origin": "http://127.0.0.1:%d" % self.port})[0]
        self.assertNotIn(st, (403, 415))

    def test_path_traversal_blocked(self):
        for p in ["/works/../llm_bench_pro/server.py", "/works/..%2Fllm_bench_pro%2Fserver.py", "/works/..%5CREADME.md",
                  "/static/../../README.md", "/README.md", "/llm_bench_pro/store.py"]:
            with self.subTest(path=p):
                self.assertEqual(self.request("GET", p)[0], 404)

    def test_static_and_index(self):
        st, h, _ = self.request("GET", "/")
        self.assertEqual(st, 200)
        st, h, body = self.request("GET", "/static/app.js")
        self.assertEqual((st, h["Content-Type"].split(";")[0]), (200, "application/javascript"))
        self.assertIn(('const UI_VERSION="%s"' % server.APP_VERSION).encode(), body)  # 前后端版本号一致

    def test_endpoints_crud(self):
        """模型端点配置: 保存(自动命名)/列表/使用/删除 全链路。"""
        st, _, d = self.request("POST", "/api/endpoints",
                                {"url": "http://127.0.0.1:9000/v1", "model": "qwen-test", "api_key": "sk-abcdef1234"})
        self.assertEqual(st, 200)
        self.assertTrue(d["ok"])
        ep = d["endpoint"]
        self.assertTrue(ep["id"].startswith("ep_"))
        self.assertEqual(ep["api_key"], "sk-abcdef1234")
        self.assertIn("qwen-test", ep["name"])            # 自动命名含模型
        self.assertIn("127.0.0.1:9000", ep["name"])       # 与主机名
        st, _, lst = self.request("GET", "/api/endpoints")
        self.assertEqual([x["id"] for x in lst], [ep["id"]])
        st, _, d2 = self.request("POST", "/api/endpoint-use", {"id": ep["id"]})
        self.assertEqual((st, d2["ok"]), (200, True))
        st, _, d3 = self.request("POST", "/api/endpoints", {"url": "ftp://bad", "model": "m"})
        self.assertEqual(st, 400)                          # 非 http(s) 拒绝
        st, _, d4 = self.request("POST", "/api/endpoints", {"url": "http://x", "model": ""})
        self.assertEqual(st, 400)                          # 缺模型拒绝
        st, _, d5 = self.request("POST", "/api/endpoint-delete", {"id": ep["id"]})
        self.assertEqual((st, d5["ok"]), (200, True))
        st, _, lst2 = self.request("GET", "/api/endpoints")
        self.assertEqual(lst2, [])
        st, _, d6 = self.request("POST", "/api/endpoint-delete", {"id": ep["id"]})
        self.assertEqual(st, 404)

    def test_works_preview_injects_storage_shim(self):
        """沙箱预览的 localStorage 垫片: 只注入 HTML 预览响应, 不动落盘文件。"""
        d = temp_dir()
        with open(os.path.join(d, "game.html"), "wb") as f:
            f.write(b'<!doctype html><html><head><meta charset="utf-8"><title>t</title></head>'
                    b'<body><script>var best=+(localStorage.getItem("best")||0);</script></body></html>')
        with open(os.path.join(d, "shot.jpg"), "wb") as f:
            f.write(b"\xff\xd8fake")
        orig = server.WORKS
        server.WORKS = d
        try:
            st, h, body = self.request("GET", "/works/game.html")
            self.assertEqual(st, 200)
            self.assertTrue(h["Content-Type"].startswith("text/html"))
            self.assertIn(b"llm-bench-pro storage shim", body)
            self.assertTrue(body.startswith(b"<!doctype html>"))          # doctype 仍居首, 不触发 quirks mode
            self.assertLess(body.index(b"<head>"), body.index(b"storage shim"))  # 垫片在 head 开标签之后
            csp = next(v for k, v in h.items() if k.lower() == "content-security-policy")
            self.assertIn("sandbox", csp)
            self.assertNotIn("allow-same-origin", csp)
            self.assertIn("connect-src data: blob:", csp)
            self.assertNotIn("https:", csp)
            early = server._inject_works_shim(
                b"<!doctype html><script>localStorage.getItem('x')</script><html><body></body></html>")
            self.assertLess(early.index(b"storage shim"), early.index(b"<script>localStorage"))
            self.assertTrue(early.startswith(b"<!doctype html>"))
            header = server._inject_works_shim(b"<html><body><header class='a'>x</header></body></html>")
            self.assertLess(header.index(b"<html>"), header.index(b"storage shim"))
            self.assertLess(header.index(b"storage shim"), header.index(b"<header"))
            self.assertIn(b'localStorage.getItem("best")', body)         # 原始内容完整保留
            st, _, jpg = self.request("GET", "/works/shot.jpg")
            self.assertEqual((st, jpg[:2]), (200, b"\xff\xd8"))           # 非 HTML 不注入
        finally:
            server.WORKS = orig

    def test_version(self):
        st, _, v = self.request("GET", "/api/version")
        self.assertEqual(st, 200)
        self.assertEqual(v["version"], server.APP_VERSION)
        self.assertFalse(v["auth"])
        self.assertIn("code_changed", v)

    def test_endpoint_conflict_requires_confirmation(self):
        job = server.JOBS["iq"]
        job.try_start("http://127.0.0.1:8011", "m")
        try:
            body = {"base": "http://127.0.0.1:8011", "model": "m", "suite": "quick"}
            st, _, d = self.request("POST", "/api/start", body)
            self.assertEqual((st, d.get("code")), (409, "endpoint_busy"))
            threading.Event().wait(0.3)
            self.assertFalse(server.JOBS["perf"].snapshot()["running"], "被拒绝的请求不得启动任务")
            st, _, d = self.request("POST", "/api/start", dict(body, base="http://127.0.0.1:9999"))
            self.assertNotEqual(d.get("code"), "endpoint_busy")  # 不同端点不冲突
            server.JOBS["perf"].cancel.set()
        finally:
            job.set(running=False)
            for _ in range(300):  # 关闭端口的连接失败在本机可能需数秒/次, 任务收尾最长 ~20s
                if not server.JOBS["perf"].snapshot()["running"]:
                    break
                threading.Event().wait(0.1)

    def test_cancel_api(self):
        st, _, d = self.request("POST", "/api/cancel", {"job": "gen"})
        self.assertEqual(st, 409)
        self.assertEqual(self.request("POST", "/api/cancel", {"job": "nope"})[0], 400)
        job = server.JOBS["gen"]
        job.try_start(None, "x")
        try:
            st, _, d = self.request("POST", "/api/cancel", {"job": "gen"})
            self.assertEqual(st, 200)
            self.assertTrue(job.cancel.is_set())
            self.assertTrue(job.snapshot()["cancelling"])
        finally:
            job.set(running=False)

    def test_delete_and_compare(self):
        a, b = iq_doc("iq_20260102_000000_a"), iq_doc("iq_20260102_000000_b")
        b["items"][0]["ok"] = False
        sinks.SqliteSink().save(a)
        sinks.SqliteSink().save(b)
        st, _, d = self.request("GET", "/api/iq-compare?a=%s&b=%s" % (a["run_id"], b["run_id"]))
        self.assertTrue(d["ok"])
        self.assertEqual(d["overall"]["a_only"], 1)
        st, _, d = self.request("POST", "/api/run-delete", {"run_id": b["run_id"]})
        self.assertEqual((st, d["ok"]), (200, True))
        self.assertIsNone(store.get_run(b["run_id"]))
        self.assertEqual(self.request("POST", "/api/run-delete", {"run_id": "../x"})[0], 400)

    def test_resume_rejects_old_version(self):
        doc = iq_doc("iq_20260103_000000_old")
        doc.update(iq_version="1.2.0", status="cancelled")
        sinks.SqliteSink().save(doc)
        st, _, d = self.request("POST", "/api/iq-resume", {"run_id": doc["run_id"]})
        self.assertEqual(st, 409)
        self.assertIn("不能续跑", d["error"])

    def test_perf_summary_list(self):
        st, _, rows = self.request("GET", "/api/results?summary=1")
        self.assertEqual(st, 200)
        self.assertTrue(all("phases" not in r for r in rows))

    def test_replay_upload_scenarios_start(self):
        st, _, d = self.request("POST", "/api/replay-upload", {"name": "t", "content": "根本不是 JSONL"})
        self.assertEqual(st, 400)
        content = "\n".join(json.dumps({"messages": [{"role": "user", "content": "q%d" % i}], "params": {}})
                            for i in range(3))
        st, _, d = self.request("POST", "/api/replay-upload", {"name": "t.jsonl", "content": content})
        self.assertEqual((st, d["ok"], d["lines"]), (200, True, 3))
        fid = d["file_id"]
        self.assertRegex(fid, r"^replay-[0-9a-f]{12}$")
        st, _, d2 = self.request("POST", "/api/replay-upload", {"name": "再次", "content": content})
        self.assertEqual(d2["file_id"], fid)  # 内容寻址幂等
        st, _, lst = self.request("GET", "/api/replay-list")
        self.assertTrue(any(f["file_id"] == fid for f in lst["files"]))
        # 任务场景资产: 任务集 + 图片包(1x1 PNG)
        png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        st, _, d = self.request("POST", "/api/scenario-upload",
                                {"kind": "tasks", "name": "my.jsonl", "content": content})
        self.assertEqual((st, d["ok"], d["lines"]), (200, True, 3))
        tid = d["file_id"]
        self.assertRegex(tid, r"^scn-[0-9a-f]{12}$")
        st, _, d = self.request("POST", "/api/scenario-upload",
                                {"kind": "images", "files": [{"name": "a.png", "data": png}]})
        self.assertEqual((st, d["ok"], d["count"]), (200, True, 1))
        iid = d["image_id"]
        st, _, d = self.request("POST", "/api/scenario-upload",
                                {"kind": "images", "files": [{"name": "a.txt", "data": png}]})
        self.assertEqual(st, 400)  # 非图片扩展名
        st, _, d = self.request("POST", "/api/scenario-upload", {"kind": "nope"})
        self.assertEqual(st, 400)
        st, _, lst = self.request("GET", "/api/scenario-list")
        self.assertTrue(any(t["file_id"] == tid for t in lst["tasks"]))
        self.assertTrue(any(i["image_id"] == iid and i["count"] == 1 for i in lst["images"]))
        # 非法场景配置在启动前被拒
        for scen in ({"tasks": ["nope"]},                       # 未知模板
                     {"tasks": ["chat"], "conc": "999"},        # 并发越界
                     {"tasks": ["vision"]},                     # 缺图片来源
                     {"tasks": ["custom"]},                     # 缺任务集
                     {"tasks": ["custom"], "custom_file_id": "scn-deadbeefcafe"},  # 不存在的任务集
                     {"tasks": ["rag"], "rag_ctx": [10]}):      # 档位越界
            with self.subTest(scen=scen):
                st, _, e = self.request("POST", "/api/start",
                                        {"base": "http://127.0.0.1:1", "model": "m", "suite": "quick", "scenarios": scen})
                self.assertEqual(st, 400)
        # 合法场景可启动; 端口不可达, 任务快速失败, 不真正压测
        st, _, d = self.request("POST", "/api/start", {
            "base": "http://127.0.0.1:9", "model": "m", "suite": "quick", "warmup_shapes": False,
            "scenarios": {"tasks": ["chat", "rag", "vision", "custom"], "conc": [1], "requests_per_worker": 1,
                          "rag_ctx": [1500], "vision_src": {"image_id": iid, "images": 1},
                          "custom_file_id": tid, "replay": {"file_id": fid, "closed": {"conc": [1], "requests_per_worker": 1},
                                                            "open": {"rates": [1], "duration_s": 5}}}})
        self.assertEqual((st, d.get("ok"), d.get("scenarios"), d.get("replay")),
                         (200, True, ["chat", "rag", "vision", "custom"], True))
        server.JOBS["perf"].cancel.set()
        for _ in range(300):  # 等待任务收尾(机器上关闭端口连接失败较慢)
            if not server.JOBS["perf"].snapshot()["running"]:
                break
            threading.Event().wait(0.1)
        self.assertFalse(server.JOBS["perf"].snapshot()["running"])

    def test_report_endpoint(self):
        doc = perf_doc()
        doc["phases"].append({"id": "scn_json", "task": {"tpl": "json", "label": "结构化抽取", "validator": "json",
                                                         "max_tokens": 256, "requests_per_worker": 3},
                              "points": [{"conc": 2, "total": 2, "ok": 2, "fail": 0, "req_s": 1.5, "ttft_p95_s": 0.4,
                                          "e2e_p95_s": 1.2, "out_tokens_avg": 180.0, "json_total": 2, "json_ok": 2,
                                          "json_rate": 1.0}]})
        doc["phases"].append({"id": "scn_chat", "task": {"tpl": "chat", "label": "对话问答", "validator": None,
                                                         "max_tokens": 512, "requests_per_worker": 3},
                              "points": [{"conc": 2, "total": 2, "ok": 2, "fail": 0, "req_s": 1.7, "ttft_p95_s": 0.3,
                                          "e2e_p95_s": 1.0, "out_tokens_avg": 320.0, "out_tokens_p90": 400.0}]})
        sinks.SqliteSink().save(doc)
        st, h, body = self.request("GET", "/api/report?id=" + doc["run_id"])
        self.assertEqual(st, 200)
        self.assertIn("attachment", h.get("Content-Disposition", ""))
        self.assertIn(b"<svg", body)
        self.assertIn("结构化抽取".encode(), body)
        self.assertIn("对话问答".encode(), body)
        st, _, _b = self.request("GET", "/api/report?id=%s&cmp=%s" % (doc["run_id"], doc["run_id"]))
        self.assertEqual(st, 200)  # A/B(自身对比)也可生成
        iqrun = iq_doc()
        sinks.SqliteSink().save(iqrun)
        st, _, d = self.request("GET", "/api/report?id=" + iqrun["run_id"])
        self.assertEqual(st, 400)  # 非性能运行拒绝
        self.assertEqual(self.request("GET", "/api/report?id=../../etc")[0], 400)

    @unittest.skipUnless(hasattr(socket, "SO_EXCLUSIVEADDRUSE"), "仅 Windows 需要独占绑定")
    def test_exclusive_bind(self):
        with self.assertRaises(OSError):
            server.BenchServer(("127.0.0.1", self.port), server.Handler)


class TestServerToken(ServerCase):
    token = "s3cret"

    def test_token_required(self):
        self.assertEqual(self.request("GET", "/api/version")[0], 401)
        self.assertEqual(self.request("POST", "/api/cancel", {"job": "iq"})[0], 401)
        st, _, v = self.request("GET", "/api/version", headers={"X-Bench-Token": "s3cret"})
        self.assertEqual((st, v["auth"]), (200, True))
        st, h, _ = self.request("GET", "/?token=s3cret")
        self.assertEqual(st, 302)
        cookie = h["Set-Cookie"].split(";")[0]
        self.assertEqual(self.request("GET", "/api/version", headers={"Cookie": cookie})[0], 200)
        self.assertEqual(self.request("GET", "/api/version", headers={"X-Bench-Token": "wrong"})[0], 401)


if __name__ == "__main__":
    unittest.main()
