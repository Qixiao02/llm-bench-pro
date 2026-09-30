# -*- coding: utf-8 -*-
import base64
import http.client
import json
import os
import socket
import subprocess
import sys
import threading
import time
import unittest

from _util import ROOT, temp_dir
import server
import sinks
import store
import vision_assets
from test_store import gen_doc, iq_doc, perf_doc


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
            with open(os.path.join(d, "game.gen.json"), "w", encoding="utf-8") as f:
                f.write('{"task": "game", "rounds": []}')
            st, h2, body2 = self.request("GET", "/works/game.gen.json")
            self.assertEqual((st, h2["Content-Type"].split(";")[0], body2["task"]), (200, "application/json", "game"))
            self.assertNotIn("Content-Security-Policy", h2)
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

    def test_client_disconnect_is_quiet(self):
        """浏览器中途断开(刷新 / 关页面)不打印堆栈; 其他异常照常打印。"""
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stderr(out):
            for exc in (ConnectionAbortedError(10053, "aborted"), ConnectionResetError(10054, "reset"), BrokenPipeError(32, "pipe")):
                try:
                    raise exc
                except OSError:
                    self.httpd.handle_error(None, ("127.0.0.1", 1))
        self.assertEqual(out.getvalue(), "")
        with contextlib.redirect_stderr(out):
            try:
                raise ValueError("boom")
            except ValueError:
                self.httpd.handle_error(None, ("127.0.0.1", 1))
        self.assertIn("ValueError: boom", out.getvalue())

    def test_bank_update_runs_in_background(self):
        """更新题集是后台任务: 立即返回, 进度在 /api/bank-status, 可以停止; 同时只能跑一个; 选的下载源和离线参数传到位。"""
        import bankman
        started, release, calls = threading.Event(), threading.Event(), []

        def fake_build(proxy=None, mode="modelscope", log=None, cancel=None, offline=False, **kw):
            calls.append((mode, offline, proxy))
            log("进度 0 / 6 · GSM8K")
            started.set()
            while not release.is_set():
                if cancel.is_set():
                    raise bankman.Cancelled("已停止")
                time.sleep(0.02)
            return {"bank_id": "iq-fake", "total": 1, "subjects": []}, "x"

        def wait_idle():
            for _ in range(200):
                s = self.request("GET", "/api/bank-status")[2]
                if not s["running"]:
                    return s
                time.sleep(0.05)
            self.fail("题集更新没有结束")
        orig = bankman.build
        bankman.build = fake_build
        try:
            st, _, d = self.request("POST", "/api/bank-update", {"source": "modelscope", "proxy": "http://127.0.0.1:7890"})
            self.assertTrue(d["ok"] and d["started"])
            self.assertTrue(started.wait(5))
            self.assertEqual(self.request("POST", "/api/bank-update", {})[0], 409)       # 同时只能跑一个
            s = self.request("GET", "/api/bank-status")[2]
            self.assertTrue(s["running"])
            self.assertIn("进度 0 / 6", s["log"][0]["msg"])
            self.assertTrue(self.request("POST", "/api/cancel", {"job": "bank"})[2]["ok"])
            s = wait_idle()
            self.assertIsNone(s["error"])                                                 # 停止不算出错
            self.assertTrue(any("已停止" in x["msg"] for x in s["log"]))
            release.set()
            self.request("POST", "/api/bank-update", {"source": "global", "offline": True})
            s = wait_idle()
            self.assertEqual(s["run_id"], "iq-fake")
            self.assertEqual(calls, [("modelscope", False, "http://127.0.0.1:7890"), ("global", True, None)])
        finally:
            bankman.build = orig
        d = self.request("GET", "/api/datasets")[2]
        self.assertEqual(len(d["datasets"]), 6)
        self.assertIn("ready", d)

    def test_works_open_mode(self):
        """新标签页打开(?open=1): 仍是沙箱(不同源, 碰不到接口), 但像普通网页一样可以加载外部字体和脚本。"""
        d = temp_dir()
        with open(os.path.join(d, "game.html"), "wb") as f:
            f.write(b"<!doctype html><html><head></head><body><script>1</script></body></html>")
        orig = server.WORKS
        server.WORKS = d
        try:
            csp_of = lambda h: next(v for k, v in h.items() if k.lower() == "content-security-policy")  # noqa: E731
            st, h, body = self.request("GET", "/works/game.html?open=1")
            self.assertEqual(st, 200)
            self.assertTrue(csp_of(h).startswith("sandbox allow-scripts"))
            self.assertNotIn("allow-same-origin", csp_of(h))
            self.assertNotIn("src", csp_of(h))                 # 不限制外部资源
            self.assertIn(b"llm-bench-pro storage shim", body)
            st, h, _ = self.request("GET", "/works/game.html")   # 预览仍是评测时的环境: 不联网
            self.assertIn("connect-src data: blob:", csp_of(h))
            self.assertNotIn("sandbox", server.WORKS_CSP_META)  # 离线报告的 meta 版本不含 meta 不支持的 sandbox
            self.assertIn("script-src", server.WORKS_CSP_META)
        finally:
            server.WORKS = orig

    def _bank(self):
        import bankman
        bdir = temp_dir()
        bank = {"bank_id": "tb-exp", "subjects": [
            {"id": "s", "name": "S", "type": "mcq", "items": [
                {"q": "q0", "choices": list("abcd"), "answer": "B"}, {"q": "q1", "choices": list("abcd"), "answer": "A"},
                {"q": "q2", "choices": list("abcd"), "answer": "C"}]},
            {"id": "ins", "name": "I", "type": "instruct", "items": [{"q": "用不超过50个字介绍量子计算。", "checks": []}]}]}
        with open(os.path.join(bdir, "tb-exp.json"), "w", encoding="utf-8") as f:
            json.dump(bank, f, ensure_ascii=False)
        old = bankman.BANKS
        bankman.BANKS = bdir
        self.addCleanup(setattr, bankman, "BANKS", old)

    def _iq_pair(self, suffix):
        import iq
        a = iq_doc("iq_20260105_000000_a" + suffix)
        a.update(bank_id="tb-exp", iq_version=iq.IQ_VERSION)
        a["items"][0]["resp"] = "B"
        a["items"].append({"sid": "ins", "idx": 0, "ok": False, "in": 1, "out": 30, "finish": "stop", "resp": "量" * 60})
        a["items"].append({"sid": "s", "idx": 0, "ok": False, "in": 1, "out": 2, "finish": "stop", "resp": "C", "pred": "C"})  # 续跑后同题第二条
        b = iq_doc("iq_20260105_000000_b" + suffix)
        b.update(bank_id="tb-exp")
        for doc in (a, b):
            sinks.SqliteSink().save(doc)
        return a, b

    def test_iq_answers_all_matches_single(self):
        """离线报告一次取全部回答, 与逐题接口 iq_answer 的结果逐项相同(同题多条记录以最后一条为准)。"""
        self._bank()
        a, b = self._iq_pair("x")
        ids = [a["run_id"], b["run_id"]]
        allv = server.iq_answers_all(ids)
        self.assertEqual(sorted(allv), ["ins|0", "s|0", "s|1", "s|2"])
        for key, e in allv.items():
            sid, idx = key.split("|")
            one = server.iq_answer(",".join(ids), sid, idx)
            self.assertEqual({k: one[k] for k in ("type", "prompt", "answers")}, e, key)
        self.assertEqual(allv["s|0"]["answers"][a["run_id"]]["pred"], "C")
        self.assertEqual(server.iq_answers_all(["../x"]), {})

    def test_export_html(self):
        """离线报告: 同一套页面(内联 CSS / ECharts / app.js) + 这几次测试的数据; 四个页面都能导出; 参数不对 400。"""
        import re
        self._bank()
        p1, p2 = perf_doc("run_20260105_000000_p1"), perf_doc("run_20260105_000000_p2")
        a, b = self._iq_pair("e")
        g = gen_doc("gen_20260105_000000_g1")
        wd = temp_dir()
        os.makedirs(os.path.join(wd, g["run_id"]))
        with open(os.path.join(wd, g["run_id"], "snake.html"), "wb") as f:
            f.write(b"<!doctype html><html><head><title>s</title></head><body><script>var x='</script>'.length</script></body></html>")
        g["items"][0]["file"] = "works/%s/snake.html" % g["run_id"]
        for doc in (p1, p2, g):
            sinks.SqliteSink().save(doc)
        orig = server.WORKS
        server.WORKS = wd

        def export(**body):
            st, h, raw = self.request("POST", "/api/export-html", body)
            return st, h, raw

        def data_of(html):
            m = re.search(rb'<script type="application/json" id="llmb-offline">(.*?)</script>', html, re.S)
            return json.loads(m.group(1).decode("utf-8"))
        try:
            st, h, html = export(page="dash", id=p1["run_id"], cmp=[p2["run_id"]], title="速度测试 · m",
                                 state={"theme": "light", "ls": {"llm-bench-pro-dt": "{}", "llm-bench-pro-terms": "pro",
                                                                 "llm-bench-pro-iq-form": "{\"iqBase\":\"http://10.0.0.1\"}"}},
                                 ui={"panels": [["dash-conc", "table"], ["x", "bad"]], "qb": {"filter": "bad"}})
            self.assertEqual((st, h["Content-Type"].split(";")[0]), (200, "text/html"))
            self.assertIn(("const UI_VERSION=\"%s\"" % server.APP_VERSION).encode(), html)   # 同一套页面代码, 内联
            self.assertNotIn(b'src="/static', html)
            self.assertNotIn(b'href="/static', html)
            self.assertEqual(html.count(b"<script"), html.count(b"</script>"))             # 内联内容没有提前结束脚本
            self.assertIn("<title>速度测试 · m</title>".encode(), html)
            d = data_of(html)
            self.assertEqual((d["page"], d["sel"]), ("dash", {"a": p1["run_id"], "cmp": [p2["run_id"]]}))
            self.assertEqual(sorted(d["api"]["perfRuns"]), sorted([p1["run_id"], p2["run_id"]]))
            self.assertEqual([r["run_id"] for r in d["api"]["perfList"]], [p1["run_id"], p2["run_id"]])
            self.assertTrue(d["api"]["version"]["offline"])
            self.assertNotIn("db", d["api"]["version"])                                   # 不带本机路径
            self.assertEqual(d["ui"]["panels"], [["dash-conc", "table"]])
            st_json = re.search(rb"window\.LLMB_OFF_STATE=(\{.*?\})</script>", html).group(1)
            state = json.loads(st_json.decode("utf-8"))
            self.assertEqual(state["theme"], "light")
            self.assertNotIn("llm-bench-pro-iq-form", state["ls"])                         # 表单里填过的地址不带
            self.assertIn("llm-bench-pro-dt", state["ls"])
            self.assertEqual(state["ls"]["llm-bench-pro-terms"], "pro")                    # 当前的术语模式(大白话 / 专业)带进报告

            st, _, html = export(page="iq", id=a["run_id"], cmp=[b["run_id"]])
            d = data_of(html)
            self.assertEqual([r["run_id"] for r in d["api"]["iqList"]], [a["run_id"], b["run_id"]])
            self.assertEqual(len(d["api"]["iqItems"]["questions"]), 4)
            self.assertEqual(sorted(d["api"]["iqAnswers"]), ["ins|0", "s|0", "s|1", "s|2"])
            self.assertEqual(sorted(d["api"]["iqCompare"]), sorted(["%s|%s" % (a["run_id"], b["run_id"]), "%s|%s" % (b["run_id"], a["run_id"])]))
            self.assertIn("量" * 60, json.dumps(d, ensure_ascii=False))                    # 回答原文也在报告里
            self.assertEqual(html.count(b"<script"), html.count(b"</script>"))

            st, _, html = export(page="gen", id=g["run_id"])
            d = data_of(html)
            work = d["files"]["works/%s/snake.html" % g["run_id"]]
            self.assertIn("llm-bench-pro storage shim", work)                             # 与在线预览同样带存储垫片
            self.assertIn("'</script>'.length", work)                                     # 作品原文完整
            self.assertEqual(html.count(b"<script"), html.count(b"</script>"))
            self.assertIn("script-src", d["worksCsp"])

            for body in ({"page": "x", "id": p1["run_id"]}, {"page": "dash", "id": "../x"}, {"page": "dash", "id": a["run_id"]},
                         {"page": "iq", "id": "iq_20990101_000000_none"}, {"page": "gen", "id": g["run_id"], "cmp": "x"},
                         {"page": "dash", "id": p1["run_id"], "cmp": {"a": 1}}):
                with self.subTest(body=body):
                    st, _, err = export(**body)
                    self.assertEqual(st, 400)
                    self.assertFalse(err["ok"])
        finally:
            server.WORKS = orig

    def test_export_html_gen_thumbnails(self):
        """离线报告里作品列表的缩略图: 复用报告本来就带着的检查截图(每张只带一份, 文件不会因此变大); 没有截图的作品不带;
        界面状态里作品列表的难度 / 搜索 / 页码 / 每页件数只收认识的字段并限制范围。"""
        import re
        g = gen_doc("gen_20260105_000000_thumb")
        wd = temp_dir()
        run_dir = os.path.join(wd, g["run_id"])
        os.makedirs(os.path.join(run_dir, "snake.shots"))
        with open(os.path.join(run_dir, "snake.html"), "wb") as f:
            f.write(b"<!doctype html><html><body>snake</body></html>")
        idle = b"\xff\xd8\xff\xe0" + b"THUMBNAIL-IDLE-MARK" * 30 + b"\xff\xd9"
        first = b"\xff\xd8\xff\xe0" + b"FIRST-SCREEN-MARK" * 30 + b"\xff\xd9"
        for name, data in (("01_initial.jpg", first), ("02_idle.jpg", idle)):
            with open(os.path.join(run_dir, "snake.shots", name), "wb") as f:
                f.write(data)
        it = g["items"][0]
        it["file"] = "works/%s/snake.html" % g["run_id"]
        it["eval"] = {"method": "browser", "checks": [{"id": "load", "label": "打开", "pass": True, "detail": ""}], "shots_dir": "snake.shots",
                      "shots": [{"name": "01_initial", "file": "01_initial.jpg", "caption": "首屏"},
                                {"name": "02_idle", "file": "02_idle.jpg", "caption": "空闲后"}]}
        g["items"].append({"id": "tetris", "name": "俄罗斯方块", "pass": 1, "total": 2, "stars": None,
                           "eval": {"method": "static", "checks": [{"id": "doctype", "label": "x", "pass": True, "detail": ""}], "shots": []}})
        sinks.SqliteSink().save(g)
        orig = server.WORKS
        server.WORKS = wd

        def export(**body):
            st, _, raw = self.request("POST", "/api/export-html", dict({"page": "gen", "id": g["run_id"]}, **body))
            self.assertEqual(st, 200)
            m = re.search(rb'<script type="application/json" id="llmb-offline">(.*?)</script>', raw, re.S)
            return raw, json.loads(m.group(1).decode("utf-8"))
        try:
            html, d = export()
            key = "works/%s/snake.shots/" % g["run_id"]
            self.assertTrue(d["files"][key + "02_idle.jpg"].startswith("data:image/jpeg;base64,"))   # 缩略图用的那张在报告里
            self.assertIn(key + "01_initial.jpg", d["files"])
            self.assertEqual(len([k for k in d["files"] if k.endswith(".jpg")]), 2)              # 只带这件作品的两张截图
            payload = base64.b64encode(idle)
            self.assertEqual(html.count(payload), 1)                                                   # 同一张截图只嵌一份: 列表和详情共用
            self.assertNotIn("works/%s/tetris" % g["run_id"], "".join(d["files"]))                     # 只看代码的作品没有截图可带

            ui = {"genFilter": "static", "genSort": "pass", "genView": {"tier": "困难", "q": "蛇", "page": 3, "size": 24}}
            self.assertEqual(export(ui=ui)[1]["ui"]["genView"], {"tier": "困难", "q": "蛇", "page": 3, "size": 24})
            self.assertEqual(export(ui=ui)[1]["ui"]["genFilter"], "static")
            bad = {"genView": {"tier": "x" * 50, "q": "y" * 200, "page": -1, "size": 7}}
            self.assertEqual(export(ui=bad)[1]["ui"]["genView"], {"tier": "x" * 20, "q": "y" * 80, "page": 0, "size": 12})
            for junk in ({"page": True, "size": True}, {"page": "2", "size": "24"}, {"page": 10 ** 9}, {}):
                with self.subTest(junk=junk):
                    v = export(ui={"genView": junk})[1]["ui"]["genView"]
                    self.assertEqual((v["page"], v["size"]), (0, 12))
            self.assertNotIn("genView", export(ui={"genView": "x"})[1]["ui"])
            self.assertNotIn("genView", export()[1]["ui"])
            # 每页件数的本地偏好跟着报告走, 别的表单偏好(地址、Key)不带
            raw, _ = export(state={"theme": "dark", "ls": {"llm-bench-pro-gen-works": '{"size":24}', "llm-bench-pro-gen-judge": '{"genJudgeBase":"http://10.0.0.1"}'}})
            state = json.loads(re.search(rb"window\.LLMB_OFF_STATE=(\{.*?\})</script>", raw).group(1).decode("utf-8"))
            self.assertEqual(state["ls"]["llm-bench-pro-gen-works"], '{"size":24}')
            self.assertNotIn("llm-bench-pro-gen-judge", state["ls"])
        finally:
            server.WORKS = orig

    def test_export_state_terms_mode(self):
        """离线报告带着导出时的术语模式(plain 大白话 / pro 专业); 只收这两个值, 其他值丢掉, 没选过的就不带(报告按默认大白话显示)。"""
        st = server._export_state
        self.assertIn("llm-bench-pro-terms", server.EXPORT_LS_KEYS)
        for mode in ("plain", "pro"):
            self.assertEqual(st({"theme": "dark", "ls": {"llm-bench-pro-terms": mode}})["ls"]["llm-bench-pro-terms"], mode)
        for bad in ("PRO", "专业", "<script>", "", "plain ", None, 1, ["pro"]):
            with self.subTest(bad=bad):
                self.assertNotIn("llm-bench-pro-terms", st({"theme": "dark", "ls": {"llm-bench-pro-terms": bad}})["ls"])
        self.assertNotIn("llm-bench-pro-terms", st({"theme": "dark", "ls": {}})["ls"])
        self.assertNotIn("llm-bench-pro-terms", st(None)["ls"])
        self.assertEqual(st({"theme": "light", "ls": {"llm-bench-pro-terms": "pro", "llm-bench-pro-x": "1"}}),
                         {"theme": "light", "ls": {"llm-bench-pro-terms": "pro", "llm-bench-pro-theme": "light"}})   # 只带白名单里的偏好

    def test_iq_items_and_answer(self):
        import bankman
        import iq
        bdir = temp_dir()
        bank = {"bank_id": "tb-items", "subjects": [
            {"id": "s", "name": "S", "type": "mcq", "items": [
                {"q": "q0", "choices": list("abcd"), "answer": "B", "sub": "anatomy"},
                {"q": "q1", "choices": list("abcd"), "answer": "A"},
                {"q": "q2", "choices": list("abcd"), "answer": "C"}]},
            {"id": "ins", "name": "I", "type": "instruct", "items": [{"q": "用不超过50个字介绍量子计算。", "checks": []}]}]}
        with open(os.path.join(bdir, "tb-items.json"), "w", encoding="utf-8") as f:
            json.dump(bank, f, ensure_ascii=False)
        old = bankman.BANKS
        bankman.BANKS = bdir
        try:
            a = iq_doc("iq_20260104_000000_a")
            a.update(bank_id="tb-items", iq_version=iq.IQ_VERSION)
            a["items"][0]["resp"] = "B"
            a["items"].append({"sid": "ins", "idx": 0, "ok": False, "in": 1, "out": 30, "finish": "stop", "resp": "量" * 60})
            b = iq_doc("iq_20260104_000000_b")
            b.update(bank_id="tb-items")
            b["items"][0]["ok"] = False
            c = iq_doc("iq_20260104_000000_c")  # 题集不同
            for doc in (a, b, c):
                sinks.SqliteSink().save(doc)
            st, _, d = self.request("GET", "/api/iq-items?id=%s&cmp=%s,%s" % (a["run_id"], b["run_id"], c["run_id"]))
            self.assertEqual(st, 200)
            self.assertTrue(d["ok"] and d["bank_found"])
            self.assertEqual([(q["sid"], q["idx"]) for q in d["questions"]], [("s", 0), ("s", 1), ("s", 2), ("ins", 0)])
            self.assertEqual({k: d["questions"][0][k] for k in ("q", "answer", "sub")}, {"q": "q0", "answer": "B", "sub": "anatomy"})
            self.assertEqual(d["questions"][3]["rules"], [{"text": "不超过 50 个字"}])
            self.assertEqual([s["type"] for s in d["subjects"]], ["mcq", "instruct"])
            ra = d["runs"][a["run_id"]]["recs"]
            self.assertEqual(ra["s|0"], {"ok": True, "pred": "B", "finish": "stop", "out": 1, "has": "resp"})
            self.assertEqual((ra["s|1"]["trunc"], ra["s|1"]["has"]), (True, "tail"))
            self.assertEqual(ra["s|2"]["err"], "timeout")
            self.assertNotIn("量" * 60, json.dumps(d, ensure_ascii=False))  # 列表不带回答原文
            self.assertFalse(d["runs"][b["run_id"]]["recs"]["s|0"]["ok"])
            self.assertEqual(d["runs"][c["run_id"]], {"same_bank": False, "recs": {}})

            st, _, d = self.request("GET", "/api/iq-answer?ids=%s,%s&sid=s&idx=0" % (a["run_id"], b["run_id"]))
            self.assertEqual((d["answers"][a["run_id"]]["text"], d["answers"][a["run_id"]]["full"]), ("B", True))
            self.assertIs(d["answers"][b["run_id"]]["kept"], False)  # 旧版没保存答对题的回答
            self.assertIn("只输出正确选项的字母", d["prompt"])
            st, _, d = self.request("GET", "/api/iq-answer?ids=%s&sid=ins&idx=0" % a["run_id"])
            self.assertEqual(d["answers"][a["run_id"]]["rules"], [{"text": "不超过 50 个字", "pass": False, "actual": "实际 60 字"}])
            st, _, d = self.request("GET", "/api/iq-answer?ids=%s&sid=s&idx=0" % b["run_id"])
            self.assertIsNone(d["prompt"])  # 其他评测版本: 提示模板可能不同, 不给原文
            for path in ("/api/iq-items?id=../x", "/api/iq-items?id=%s&cmp=../y" % a["run_id"],
                         "/api/iq-answer?ids=%s&sid=s&idx=zz" % a["run_id"], "/api/iq-answer?ids=&sid=s&idx=0"):
                self.assertFalse(self.request("GET", path)[2]["ok"], path)
            bankman.BANKS = temp_dir()  # 题集文件缺失: 仍返回对错记录
            st, _, d = self.request("GET", "/api/iq-items?id=%s" % a["run_id"])
            self.assertFalse(d["bank_found"])
            self.assertNotIn("q", d["questions"][0])
            self.assertEqual(len(d["runs"][a["run_id"]]["recs"]), 4)
        finally:
            bankman.BANKS = old

    def test_migrate_legacy_dirs(self):
        """2.9 之前 results/、works/ 在项目根: 启动时搬进 data/, 重名不覆盖。"""
        root = temp_dir()
        data = os.path.join(root, "data")
        os.makedirs(os.path.join(root, "results"))
        open(os.path.join(root, "results", "iq_x.json"), "w").close()
        os.makedirs(os.path.join(root, "works", "gen_a"))
        open(os.path.join(root, "works", "gen_a", "snake.html"), "w").close()
        notes = server.migrate_legacy_dirs(root, data)
        self.assertEqual([attention for _, attention in notes], [False, False])
        self.assertTrue(os.path.isfile(os.path.join(data, "results", "iq_x.json")))
        self.assertTrue(os.path.isfile(os.path.join(data, "works", "gen_a", "snake.html")))
        self.assertFalse(os.path.exists(os.path.join(root, "results")) or os.path.exists(os.path.join(root, "works")))
        os.makedirs(os.path.join(root, "works", "gen_a"))  # 两边都有: 不重名的搬过去, 重名的留在原处并提示
        os.makedirs(os.path.join(root, "works", "gen_b"))
        notes = server.migrate_legacy_dirs(root, data)
        self.assertTrue(os.path.isdir(os.path.join(data, "works", "gen_b")))
        self.assertTrue(os.path.isdir(os.path.join(root, "works", "gen_a")))
        self.assertEqual(len(notes), 1)
        self.assertTrue(notes[0][1])
        self.assertEqual(server.migrate_legacy_dirs(temp_dir(), data), [])  # 没有旧目录: 什么都不做

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
        # 上传的文件写到临时目录: 以前这里直接写进项目的 data/, 在真实环境跑测试会留下 1×1 的测试图片包
        saved = (server.REPLAY_DIR, server.SCN_TASKS_DIR, server.SCN_IMAGES_DIR)
        server.REPLAY_DIR, server.SCN_TASKS_DIR, server.SCN_IMAGES_DIR = temp_dir(), temp_dir(), temp_dir()
        try:
            self._replay_upload_scenarios_start()
        finally:
            server.REPLAY_DIR, server.SCN_TASKS_DIR, server.SCN_IMAGES_DIR = saved

    def _replay_upload_scenarios_start(self):
        st, _, d = self.request("POST", "/api/replay-upload", {"name": "t", "content": "根本不是 JSONL"})
        self.assertEqual(st, 400)
        content = "\n".join(json.dumps({"messages": [{"role": "user", "content": "q%d" % i}], "params": {}})
                            for i in range(3))
        st, _, d = self.request("POST", "/api/replay-upload", {"name": "t.jsonl", "content": content})
        self.assertEqual((st, d["ok"], d["lines"]), (200, True, 3))
        fid = d["file_id"]
        self.assertRegex(fid, r"^scn-[0-9a-f]{12}$")  # 旧接口: 回放用的请求文件现在就是任务集
        st, _, d2 = self.request("POST", "/api/replay-upload", {"name": "再次", "content": content})
        self.assertEqual(d2["file_id"], fid)  # 内容寻址幂等
        st, _, lst = self.request("GET", "/api/replay-list")
        self.assertTrue(any(f["file_id"] == fid for f in lst["files"]))
        # 任务场景资产: 任务集 + 图片包。1×1 的 PNG 太小, 看图模型会拒绝, 不收
        tiny = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        png = base64.b64encode(vision_assets.sample_images()[0][2]).decode()
        st, _, d = self.request("POST", "/api/scenario-upload",
                                {"kind": "tasks", "name": "my.jsonl", "content": content})
        self.assertEqual((st, d["ok"], d["lines"]), (200, True, 3))
        tid = d["file_id"]
        self.assertRegex(tid, r"^scn-[0-9a-f]{12}$")
        st, _, d = self.request("POST", "/api/scenario-upload",
                                {"kind": "images", "files": [{"name": "a.png", "data": tiny}]})
        self.assertEqual((st, d["ok"], d["files"][0]["code"]), (400, False, "too_small"))
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
                     {"tasks": ["vision"], "vision_src": {"image_id": "img-000000000000"}},  # 不存在的图片包
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


class TestConsoleEncoding(unittest.TestCase):
    def test_print_survives_non_utf8_stdout(self):
        """输出被重定向、编码不是 UTF-8 时 (英文 Windows 为 cp1252, 中文 Windows 为 GBK),
        打印 ⚠ 和中文不能抛错中断任务, 编不了的字符换成 ?"""
        code = "import llm_bench_pro; print('\\u26a0 \\u4e2d\\u6587 ok')"
        # cp1252 = 指定编码时的默认 (strict); cp1252:surrogateescape = Windows 重定向输出时的默认
        for io_enc in ("cp1252", "cp1252:surrogateescape"):
            env = dict(os.environ, PYTHONIOENCODING=io_enc)
            env.pop("PYTHONUTF8", None)
            r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            self.assertEqual(r.returncode, 0, io_enc + ": " + r.stderr.decode("utf-8", "replace"))
            self.assertEqual(r.stdout.strip(), b"? ?? ok", io_enc)


if __name__ == "__main__":
    unittest.main()
