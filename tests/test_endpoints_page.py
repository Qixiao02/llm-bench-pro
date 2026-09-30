# -*- coding: utf-8 -*-
"""模型管理页面的后端: 保存时的字段检查、在测试里用过几次(地址写法不同但指向同一服务的算同一个, 只查一次表)、
最近用它跑过的测试(结果摘要、按类型筛选、最多 50 次)、测试连接(带上 Key 认框架、失败原因分类、出错说明里不回显 Key)、
参数校验与访问令牌、离线报告里没有 API Key。
全部用临时数据库和本地模拟服务(MockServer / 本机端口), 不访问真实模型, 跑完不会在项目里留下 data/。"""
import errno
import http.client
import json
import re
import socket
import ssl
import threading
import time
import unittest
import urllib.error
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from _util import MockServer
import endpoints
import server
import sinks
import store
from test_server import ServerCase
from test_store import gen_doc, iq_doc, perf_doc


def uniq():
    return uuid.uuid4().hex[:8]


class EndpointCase(ServerCase):
    """每个测试结束时删掉保存的模型(别的测试文件会检查模型列表是空的)。"""

    def tearDown(self):
        for ep in store.list_endpoints():
            store.delete_endpoint(ep["id"])

    def save(self, **body):
        st, _, d = self.request("POST", "/api/endpoints", body)
        self.assertEqual(st, 200, d)
        return d["endpoint"]

    def get(self, path, **params):
        return self.request("GET", path + ("?" + urllib.parse.urlencode(params) if params else ""))

    def listed(self):
        st, _, lst = self.get("/api/endpoints")
        self.assertEqual(st, 200)
        return {x["id"]: x for x in lst}


class TestEndpointFields(unittest.TestCase):
    def test_clean_fields(self):
        f, err = endpoints.clean_fields({"url": " http://127.0.0.1:18199/v1/chat/completions \n", "model": " Qwen3-8B\x00 ",
                                         "api_key": "  sk-demo-1234\n", "name": ""})
        self.assertEqual(err, "")
        self.assertEqual(f, {"url": "http://127.0.0.1:18199", "model": "Qwen3-8B", "api_key": "sk-demo-1234",
                             "name": "Qwen3-8B · 127.0.0.1:18199"})                    # 名称不填: 模型 · 主机
        self.assertEqual(endpoints.clean_fields({"url": "https://H.example/v1/", "model": "m"})[0]["url"], "https://H.example")
        self.assertEqual(endpoints.clean_fields({"url": "http://h:1", "model": "m", "name": " 名‮字 "})[0]["name"], "名字")
        for body, word in (({"url": "", "model": "m"}, "不能为空"), ({"url": "ftp://h", "model": "m"}, "http://"),
                           ({"url": "http://", "model": "m"}, "http://"), ({"url": "http://a b", "model": "m"}, "http://"),
                           ({"url": "http://h:abc", "model": "m"}, "http://"), ({"url": "http://u:p@h", "model": "m"}, "http://"),
                           ({"url": "http://h", "model": " \t"}, "模型名称不能为空"),
                           ({"url": "http://h", "model": "m" * 129}, "128"), ({"url": "http://h", "model": "m", "name": "名" * 65}, "64"),
                           ({"url": "http://h", "model": "m", "api_key": "sk-a\nb"}, "换行"),
                           ({"url": ["http://h"], "model": "m"}, "文字"), ({"url": "http://h", "model": 7}, "文字")):
            with self.subTest(body=body):
                f, err = endpoints.clean_fields(body)
                self.assertIsNone(f)
                self.assertIn(word, err)
        self.assertEqual(endpoints.clean_fields({"url": "http://h", "model": "m", "name": "名" * 64})[1], "")  # 按字数算
        self.assertLessEqual(len(endpoints.clean_fields({"url": "http://h", "model": "m" * 128})[0]["name"]), endpoints.NAME_MAX)

    def test_mask_key(self):
        self.assertEqual(endpoints.mask_key("sk-1234567890abcdef"), "sk-1…cdef")
        self.assertEqual(endpoints.mask_key("sk-demo-1234"), "sk…34")               # 短的只露头尾各 2 个
        self.assertEqual(endpoints.mask_key("abc"), "••••")                          # 更短的全遮住
        self.assertEqual(endpoints.mask_key(""), "")
        for n in range(1, 40):
            key = "k" * n
            self.assertNotEqual(endpoints.mask_key(key), key)
            self.assertLessEqual(sum(1 for c in endpoints.mask_key(key) if c == "k"), max(0, n // 2))  # 最多露一半

    def test_url_key_same_service(self):
        same = ["http://127.0.0.1:18199/v1/chat/completions", "http://127.0.0.1:18199", "http://127.0.0.1:18199/v1/",
                "HTTP://LOCALHOST:18199/v1", " http://[::1]:18199 ", "http://localhost:18199/v1/chat/completions/"]
        self.assertEqual(len({endpoints.url_key(u) for u in same}), 1, [endpoints.url_key(u) for u in same])
        self.assertEqual(endpoints.url_key("http://h"), endpoints.url_key("http://h:80/v1"))
        self.assertEqual(endpoints.url_key("https://h"), endpoints.url_key("https://H:443"))
        for a, b in (("http://h:8000", "http://h:8001"), ("http://h:8000", "https://h:8000"), ("http://h/a", "http://h/b"),
                     ("http://h:8000", "http://h:8000/gateway")):
            with self.subTest(a=a, b=b):
                self.assertNotEqual(endpoints.url_key(a), endpoints.url_key(b))
        self.assertTrue(endpoints.url_key("http://h:abc"))                          # 解析不了也不报错
        self.assertTrue(endpoints.url_key(None) == endpoints.url_key(""))

    def test_probe_fail_codes(self):
        def http_err(code, body=b""):
            import io
            return urllib.error.HTTPError("http://h/v1/models", code, "x", {}, io.BytesIO(body))
        cases = [(http_err(401, b'{"error":"bad key"}'), "auth", 401), (http_err(403), "auth", 403), (http_err(404), "not_found", 404),
                 (http_err(502), "server", 502), (http_err(429), "http", 429),
                 (urllib.error.URLError(socket.timeout("timed out")), "timeout", None), (socket.timeout("timed out"), "timeout", None),
                 (urllib.error.URLError(ConnectionRefusedError(10061, "refused")), "refused", None),
                 (urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed")), "dns", None),
                 (urllib.error.URLError(ssl.SSLError(1, "CERTIFICATE_VERIFY_FAILED")), "tls", None),
                 (urllib.error.URLError(ConnectionResetError(104, "reset")), "reset", None),
                 (http.client.RemoteDisconnected("closed"), "reset", None),
                 (urllib.error.URLError(OSError(errno.ENETUNREACH, "Network is unreachable")), "unreachable", None),
                 (json.JSONDecodeError("x", "<html>", 0), "bad_json", None), (endpoints.NotModelList("x"), "bad_json", None),
                 (http.client.InvalidURL("nonnumeric port"), "bad_url", None), (RuntimeError("??"), "other", None)]
        for e, code, st in cases:
            with self.subTest(e=repr(e)):
                got = endpoints.probe_fail(e)
                self.assertEqual(got[:2], (code, st))
                self.assertTrue(got[2])
        self.assertIn("bad key", endpoints.probe_fail(http_err(401, b'{"error":"bad key"}'))[2])  # 服务端说的原因带上

    def test_models_of(self):
        self.assertEqual(endpoints.models_of({"data": [{"id": "a", "max_model_len": 131072}, {"id": "b", "max_model_len": "x"},
                                                       {"id": 3}, "zz", {"id": "c", "max_model_len": True}]}),
                         [{"id": "a", "max_model_len": 131072}, {"id": "b", "max_model_len": None}, {"id": "c", "max_model_len": None}])
        for bad in ({"object": "list"}, [], "x", {"data": "x"}):
            with self.assertRaises(endpoints.NotModelList):
                endpoints.models_of(bad)

    def test_summaries(self):
        s = endpoints.perf_summary([("prefill", None), ("decode", {"cases": [{"lang": "en", "decode_tps_med": 90.04}, {"lang": "zh", "decode_tps_med": 98.14}]}),
                                    ("concurrency", {"points": [{"conc": 1, "agg_tps": 95.1}, {"conc": 64, "agg_tps": 548.94}, {"conc": 32, "agg_tps": None}]}),
                                    ("scn_chat", None), ("scn_json", None)])
        self.assertEqual(s, {"phases": 5, "scn": 2, "peak_tps": 548.9, "peak_conc": 64, "decode_tps": 98.1})
        self.assertEqual(endpoints.perf_summary([]), {"phases": 0, "scn": 0})
        items = [{"exec_score": 80, "judge_score": 70, "eval": {"method": "browser"}}, {"exec_score": 60, "eval": {"method": "static"}},
                 {"error": "boom", "exec_score": 0}]
        self.assertEqual(endpoints.gen_summary(items, 33), {"done": 2, "planned": 33, "exec": 80.0, "judge": 70.0, "method": "mixed"})   # 只平均实际运行的
        self.assertEqual(endpoints.gen_summary(items[1:2], None), {"done": 1, "planned": 1, "method": "static"})   # 没有实际运行: 不打分
        self.assertEqual(endpoints.gen_summary([], 4), {"done": 0, "planned": 4})


def run_doc(kind, rid, url, model, started, **extra):
    doc = {"perf": perf_doc, "iq": iq_doc, "gen": gen_doc}[kind](rid)
    doc.update(url=url, model=model, started_utc=started, **extra)
    sinks.SqliteSink().save(doc)
    return doc["run_id"]


class TestEndpointUsage(EndpointCase):
    def test_counts_match_same_service_written_differently(self):
        port, tag = 20000 + int(uniq(), 16) % 20000, uniq()
        base, model = "http://127.0.0.1:%d" % port, "usage-%s" % tag
        a = self.save(url=base + "/v1", model=model, api_key="sk-usage-0123456789", name="甲")
        b = self.save(url=base, model=model + "-b")                                  # 同一个服务, 另一个模型
        c = self.save(url="http://127.0.0.1:%d" % (port + 1), model=model)          # 同一个模型名, 另一个端口
        self.assertEqual(a["url"], base)                                             # 保存时去掉 /v1
        rid = lambda k, i: "%s_2026030%d_000000_%s" % ({"perf": "run", "iq": "iq", "gen": "gen"}[k], i, tag + str(i))  # noqa: E731
        run_doc("perf", rid("perf", 1), base + "/v1/chat/completions", model, "2026-03-01T00:00:00+00:00")
        run_doc("perf", rid("perf", 2), "http://LOCALHOST:%d/v1/" % port, model, "2026-03-02T00:00:00+00:00")
        run_doc("iq", rid("iq", 3), base, model, "2026-03-03T00:00:00+00:00")
        run_doc("gen", rid("gen", 4), "http://[::1]:%d/v1/chat/completions" % port, model, "2026-03-04T00:00:00+00:00")
        run_doc("perf", rid("perf", 5), base + "/v1/chat/completions", model + "-b", "2026-03-05T00:00:00+00:00")
        run_doc("iq", rid("iq", 6), "http://127.0.0.1:%d/v1/chat/completions" % (port + 1), model, "2026-03-06T00:00:00+00:00")
        run_doc("gen", rid("gen", 7), base + "/gateway/v1/chat/completions", model, "2026-03-07T00:00:00+00:00")  # 路径不同: 不算
        calls = []
        orig = store.run_targets
        store.run_targets = lambda *a, **k: calls.append(1) or orig(*a, **k)
        try:
            eps = self.listed()
        finally:
            store.run_targets = orig
        self.assertEqual(len(calls), 1)                                              # 三个模型也只查一次 runs 表
        self.assertEqual(eps[a["id"]]["uses"], {"perf": 2, "iq": 1, "gen": 1, "total": 4, "last_utc": "2026-03-04T00:00:00+00:00"})
        self.assertEqual(eps[b["id"]]["uses"], {"perf": 1, "iq": 0, "gen": 0, "total": 1, "last_utc": "2026-03-05T00:00:00+00:00"})
        self.assertEqual(eps[c["id"]]["uses"]["total"], 1)
        self.assertEqual(eps[a["id"]]["api_key"], "sk-usage-0123456789")             # 新建面板一键填入要用
        self.assertEqual(self.request("POST", "/api/run-delete", {"run_id": rid("perf", 2)})[0], 200)
        self.assertEqual(self.listed()[a["id"]]["uses"]["perf"], 1)                  # 删掉的测试不再计入
        st, _, d = self.request("POST", "/api/endpoints", {"url": base, "model": model})
        self.assertEqual(d["endpoint"]["uses"]["total"], 3)                           # 保存后返回的也带「用过几次」
        self.assertTrue(all("uses" in x for x in d["endpoints"]))

    def test_last_used_is_fill_time_only(self):
        """「最近使用」只记一键填入: 新建时为空, 编辑不改; 列表按 最近填入(没有就按添加时间) 排。"""
        a = self.save(url="http://127.0.0.1:1", model="m-%s" % uniq())
        self.assertIsNone(a["last_used_utc"])
        b = self.save(url="http://127.0.0.1:2", model="m-%s" % uniq())
        st, _, u = self.request("POST", "/api/endpoint-use", {"id": a["id"]})
        self.assertEqual((st, u["ok"], u["id"]), (200, True, a["id"]))
        self.assertRegex(u["last_used_utc"], r"^\d{4}-\d\d-\d\dT")
        edited = self.save(id=b["id"], url="http://127.0.0.1:2/v1", model=b["model"], name="改过")
        self.assertEqual((edited["name"], edited["last_used_utc"], edited["url"]), ("改过", None, "http://127.0.0.1:2"))
        self.assertEqual(self.listed()[a["id"]]["last_used_utc"], u["last_used_utc"])
        store.delete_endpoint(a["id"])
        store.delete_endpoint(b["id"])


class TestEndpointRuns(EndpointCase):
    def test_recent_runs_with_summaries(self):
        port, tag = 20000 + int(uniq(), 16) % 20000, uniq()
        base, model = "http://127.0.0.1:%d" % port, "runs-%s" % tag
        ep = self.save(url=base, model=model, api_key="sk-runs-secret-0123456789")
        p = perf_doc("run_20260401_000000_%s" % tag)
        p.update(url=base + "/v1/chat/completions", model=model, started_utc="2026-04-01T00:00:00+00:00")
        p["phases"] = [{"id": "decode", "cases": [{"lang": "zh", "decode_tps_med": 98.1}]},
                       {"id": "concurrency", "points": [{"conc": 1, "agg_tps": 95.1}, {"conc": 16, "agg_tps": 812.4}]},
                       {"id": "scn_chat", "points": []}]
        sinks.SqliteSink().save(p)
        i = iq_doc("iq_20260402_000000_%s" % tag)
        i.update(url=base, model=model, started_utc="2026-04-02T00:00:00+00:00", overall={"acc": 79.2, "correct": 19, "n": 24})
        sinks.SqliteSink().save(i)
        g = gen_doc("gen_20260403_000000_%s" % tag)
        g.update(url=base + "/v1", model=model, started_utc="2026-04-03T00:00:00+00:00", planned=33, status="failed", error="E" * 500)
        g["items"] = [{"id": "snake", "exec_score": 80.0, "eval": {"method": "browser"}}, {"id": "tetris", "error": "timeout"}]
        sinks.SqliteSink().save(g)
        run_doc("perf", "run_20260404_000000_%s" % tag, base, model + "-other", "2026-04-04T00:00:00+00:00")  # 别的模型: 不算
        st, _, d = self.get("/api/endpoint-runs", id=ep["id"])
        self.assertEqual(st, 200, d)
        self.assertEqual((d["total"], d["counts"], d["kind"], d["limit"]), (3, {"perf": 1, "iq": 1, "gen": 1}, "all", 50))
        self.assertEqual([(r["kind"], r["run_id"]) for r in d["runs"]], [("gen", g["run_id"]), ("iq", i["run_id"]), ("perf", p["run_id"])])
        gen_r, iq_r, perf_r = d["runs"]
        self.assertEqual(perf_r["summary"], {"phases": 3, "scn": 1, "peak_tps": 812.4, "peak_conc": 16, "decode_tps": 98.1})
        self.assertEqual((perf_r["suite"], perf_r["framework"], perf_r["status"]), ("quick", "vLLM", "done"))
        self.assertEqual(iq_r["summary"], {"acc": 79.2, "correct": 19, "n": 24})
        self.assertEqual(gen_r["summary"], {"done": 1, "planned": 33, "exec": 80.0, "method": "browser"})
        self.assertEqual((gen_r["status"], len(gen_r["error"])), ("failed", 200))  # 出错说明截短
        self.assertNotIn("sk-runs-secret", json.dumps(d))                             # 不带 Key
        d = self.get("/api/endpoint-runs", id=ep["id"], kind="iq")[2]
        self.assertEqual(([r["run_id"] for r in d["runs"]], d["total"], d["matched"]), ([i["run_id"]], 3, 1))
        d = self.get("/api/endpoint-runs", id=ep["id"], limit=2)[2]
        self.assertEqual((len(d["runs"]), d["matched"]), (2, 3))

    def test_at_most_50(self):
        tag = uniq()
        base, model = "http://127.0.0.1:%d" % (20000 + int(tag, 16) % 20000), "many-%s" % tag
        ep = self.save(url=base, model=model)
        docs = []
        for n in range(55):
            doc = iq_doc("iq_20260501_%06d_%s" % (n, tag))
            doc.update(url=base, model=model, started_utc="2026-05-01T00:%02d:%02d+00:00" % (n // 60, n % 60))
            docs.append(doc)
        with store.session() as conn, store.write_tx(conn):  # 一次写完, 快一些
            for doc in docs:
                store.insert_children(conn, doc, store.upsert_header(conn, doc), {})
        d = self.get("/api/endpoint-runs", id=ep["id"])[2]
        self.assertEqual((len(d["runs"]), d["total"], d["matched"]), (50, 55, 55))
        self.assertEqual(d["runs"][0]["run_id"], docs[-1]["run_id"])                  # 新的在前
        self.assertEqual(self.listed()[ep["id"]]["uses"]["iq"], 55)

    def test_params_checked(self):
        ep = self.save(url="http://127.0.0.1:3", model="p-%s" % uniq())
        for params, code in (({}, 400), ({"id": "../x"}, 400), ({"id": "ep_" + "a" * 61}, 400), ({"id": "ep_nope_0"}, 404),
                             ({"id": ep["id"], "kind": "zz"}, 400), ({"id": ep["id"], "limit": 0}, 400),
                             ({"id": ep["id"], "limit": 51}, 400), ({"id": ep["id"], "limit": "x"}, 400)):
            with self.subTest(params=params):
                st, _, e = self.get("/api/endpoint-runs", **params)
                self.assertEqual((st, e["ok"]), (code, False))
                self.assertTrue(e["error"])
        st, _, d = self.get("/api/endpoint-runs", id=ep["id"], kind="gen", limit=1)
        self.assertEqual((st, d["runs"], d["total"]), (200, [], 0))


class TestEndpointSaveApi(EndpointCase):
    def test_validation_and_ids(self):
        st, _, e = self.request("POST", "/api/endpoints", {"id": "ep_1_deadbeef", "url": "http://h", "model": "m"})
        self.assertEqual((st, e["ok"]), (404, False))                                # 改一个不存在的
        for body in ({"id": "../x", "url": "http://h", "model": "m"}, {"id": 5, "url": "http://h", "model": "m"},
                     {"url": "http://h", "model": "m", "name": "名" * 65}, {"url": "http://h", "model": "m", "api_key": 123},
                     {"url": "javascript:alert(1)", "model": "m"}):
            with self.subTest(body=body):
                st, _, e = self.request("POST", "/api/endpoints", body)
                self.assertEqual((st, e["ok"]), (400, False))
        ep = self.save(url=" http://127.0.0.1:9/v1/chat/completions ", model=" m1 ", api_key=" sk-x \n")
        self.assertEqual((ep["url"], ep["model"], ep["api_key"], ep["name"]), ("http://127.0.0.1:9", "m1", "sk-x", "m1 · 127.0.0.1:9"))
        for path in ("/api/endpoint-use", "/api/endpoint-delete"):
            for body, code in (({}, 400), ({"id": ["x"]}, 400), ({"id": "ep_1_00000000"}, 404)):
                with self.subTest(path=path, body=body):
                    st, _, e = self.request("POST", path, body)
                    self.assertEqual((st, e["ok"]), (code, False))
        st, _, d = self.request("POST", "/api/endpoint-delete", {"id": ep["id"]})
        self.assertEqual((st, d, self.listed()), (200, {"ok": True, "id": ep["id"]}, {}))


class KeyedMock:
    """本机模拟服务: 要求 Authorization: Bearer <key>; /v1/models 给模型列表(带 max_model_len), /version 给版本;
    Key 不对时 401, 出错说明里原样带上收到的 Key(有的服务就是这样)。记下每个请求的路径和 Authorization。"""

    def __init__(self, key, models_body=None, delay=0.0):
        self.calls = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                auth = self.headers.get("Authorization") or ""
                outer.calls.append((self.path, auth))
                if delay:
                    time.sleep(delay)
                if auth != "Bearer " + key:
                    code, body = 401, {"error": {"message": "Incorrect API key provided: %s" % auth[7:]}}
                elif self.path == "/v1/models":
                    code, body = 200, models_body if models_body is not None else {
                        "object": "list", "data": [{"id": "demo-a", "max_model_len": 131072}, {"id": "demo-b"}]}
                elif self.path == "/version":
                    code, body = 200, {"version": "0.8.5"}
                else:
                    code, body = 404, {"detail": "Not Found"}
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                try:
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:  # 测试超时已经放弃了这个连接
                    pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class TestProbe(EndpointCase):
    def probe(self, base, key="", expect=200):
        st, _, d = self.request("POST", "/api/probe", {"base": base, "api_key": key})
        self.assertEqual(st, expect, d)
        return d

    def test_key_sent_to_framework_detection(self):
        m = KeyedMock("sk-demo-1234")
        try:
            d = self.probe(m.url + "/v1/chat/completions", "sk-demo-1234")
            self.assertTrue(d["ok"], d)
            self.assertEqual((d["base"], d["count"], d["framework"], d["fw_version"]), (m.url, 2, "vLLM", "0.8.5"))
            self.assertEqual(d["models"], [{"id": "demo-a", "max_model_len": 131072}, {"id": "demo-b", "max_model_len": None}])
            self.assertIsInstance(d["latency_ms"], int)
            self.assertIn(("/version", "Bearer sk-demo-1234"), m.calls)                # 认框架时也带上 Key
            self.assertNotIn(("/version", ""), m.calls)
        finally:
            m.close()

    def test_failure_codes(self):
        secret = "sk-wrong-key-0123456789"
        m = KeyedMock("sk-demo-1234")
        try:
            d = self.probe(m.url, secret)
            self.assertEqual((d["ok"], d["code"], d["status"]), (False, "auth", 401))
            self.assertNotIn(secret, d["error"])                                     # 服务回显的 Key 遮住
            self.assertIn(endpoints.mask_key(secret), d["error"])
            d = self.probe(m.url)
            self.assertEqual((d["code"], d["status"]), ("auth", 401))                 # 没填 Key
        finally:
            m.close()
        m = MockServer(lambda method, path, body: (404, {"detail": "Not Found"}, None))
        try:
            d = self.probe(m.url + "/nope")
            self.assertEqual((d["code"], d["status"]), ("not_found", 404))
        finally:
            m.close()
        for payload in (b"<html>hello</html>", {"object": "list"}):
            m = MockServer(lambda method, path, body, p=payload: (200, p, "text/html" if isinstance(p, bytes) else None))
            try:
                self.assertEqual(self.probe(m.url)["code"], "bad_json")                 # 不是 OpenAI 兼容接口
            finally:
                m.close()
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()                                                                    # 这个端口上没有服务
        d = self.probe("http://127.0.0.1:%d" % port)
        self.assertEqual((d["ok"], d["code"]), (False, "refused"), d)

    def test_timeout(self):
        m = KeyedMock("k", delay=1.5)
        orig = server.PROBE_TIMEOUT
        server.PROBE_TIMEOUT = 0.3
        try:
            d = self.probe(m.url, "k")
            self.assertEqual((d["ok"], d["code"]), (False, "timeout"), d)
        finally:
            server.PROBE_TIMEOUT = orig
            m.close()

    def test_slow_service_within_budget(self):
        """服务慢: 模型列表用掉大半时间后, 认框架只用剩下的时间, 整个测试连接不会拖到十几秒。"""
        m = KeyedMock("k", delay=0.4)
        orig = server.PROBE_TIMEOUT
        try:
            server.PROBE_TIMEOUT = 1.2                                            # 模型列表用掉 0.4 秒, 只剩不到 1 秒: 不认框架
            t0 = time.time()
            d = self.probe(m.url, "k")
            took = time.time() - t0
            self.assertEqual((d["ok"], d["framework"]), (True, None), d)
            self.assertLess(took, 1.2)
            self.assertEqual([p for p, _ in m.calls], ["/v1/models"])
            server.PROBE_TIMEOUT = 4                                              # 剩得多: 照常认框架
            d = self.probe(m.url, "k")
            self.assertEqual((d["ok"], d["framework"], d["fw_version"]), (True, "vLLM", "0.8.5"), d)
        finally:
            server.PROBE_TIMEOUT = orig
            m.close()

    def test_params_checked(self):
        for body in ({"base": 123}, {"base": ["http://h"]}, {"base": "ftp://h"}, {"base": ""}, {"base": "http://h", "api_key": 5},
                     {"base": "http://h:abc"}, {"base": "http://h", "api_key": "sk\nx"}):
            with self.subTest(body=body):
                st, _, d = self.request("POST", "/api/probe", body)
                self.assertEqual((st, d["ok"]), (400, False))
                self.assertIn(d["code"], ("bad_url", "bad_key"))


class TestEndpointToken(EndpointCase):
    token = "s3cret"

    def test_token_required(self):
        auth = {"X-Bench-Token": "s3cret"}
        for path in ("/api/endpoints", "/api/endpoint-runs?id=ep_1_00000000"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 401)
                self.assertIn(self.request("GET", path, headers=auth)[0], (200, 404))
        for path, body in (("/api/endpoints", {"url": "ftp://x", "model": "m"}), ("/api/endpoint-use", {"id": "ep_1_00000000"}),
                           ("/api/endpoint-delete", {"id": "ep_1_00000000"}), ("/api/probe", {"base": "ftp://x"})):
            with self.subTest(path=path):
                self.assertEqual(self.request("POST", path, body)[0], 401)
                self.assertIn(self.request("POST", path, body, auth)[0], (400, 404))


class TestExportHasNoKey(EndpointCase):
    def test_offline_report_has_no_api_key(self):
        secret = "sk-export-secret-%s" % uniq()
        self.save(url="http://127.0.0.1:18199", model="m", api_key=secret)
        doc = perf_doc("run_20260601_000000_%s" % uniq())
        doc["url"] = "http://127.0.0.1:18199/v1/chat/completions"
        sinks.SqliteSink().save(doc)
        st, _, html = self.request("POST", "/api/export-html", {"page": "dash", "id": doc["run_id"], "title": "速度测试",
                                                                "state": {"theme": "dark", "ls": {"llm-bench-pro-dt": "{}"}}})
        self.assertEqual(st, 200)
        self.assertFalse(secret.encode() in html, "离线报告里出现了 API Key")          # (不用 assertNotIn: 失败时会把整个报告打印出来)
        self.assertFalse(endpoints.mask_key(secret).encode("utf-8") in html, "离线报告里出现了遮住的 Key")  # 报告里根本不带模型列表
        m = re.search(rb'<script type="application/json" id="llmb-offline">(.*?)</script>', html, re.S)
        data = m.group(1).decode("utf-8")
        self.assertNotIn("api_key", data)                                             # 报告带的数据里没有 Key 字段
        self.assertNotIn("endpoints", json.loads(data)["api"])


if __name__ == "__main__":
    unittest.main()
