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
from test_store import iq_doc


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

    def test_version(self):
        st, _, v = self.request("GET", "/api/version")
        self.assertEqual(st, 200)
        self.assertEqual(v["version"], server.APP_VERSION)
        self.assertFalse(v["auth"])
        self.assertIn("code_changed", v)

    def test_endpoint_conflict_requires_confirmation(self):
        job = server.JOBS["iq"]
        job.try_start("http://localhost:8011", "m")
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
            for _ in range(50):
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
