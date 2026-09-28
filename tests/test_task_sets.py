# -*- coding: utf-8 -*-
"""任务集页面的后端: 名称与导入时间(元数据)、旧文件兜底、列表统计、详情分页 / 筛选 / 搜索 / 截断、图片、改名、删除、
下载文件名、重复导入、使用记录(写入与统计)、id 校验与访问令牌。
上传目录一律换成临时目录(与 TestScenarioUploadAPI 相同), 跑完不会在项目里留下 data/; 模型服务用本地 MockServer。"""
import base64
import hashlib
import json
import os
import time
import unittest
import urllib.parse
import uuid

from _util import MockServer, temp_dir
import bench
import server
import sinks
import store
import tasksets
import vision_assets as va
from test_scenario_assets import jpeg_of, png_of
from test_server import ServerCase
from test_store import perf_doc


def data_url(raw, mime="image/png"):
    return "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode())


def noisy_png(w, h):
    """像素随机的 PNG(压缩不了, data URL 足够长)。"""
    return va.encode_png(w, h, [os.urandom(3 * w) for _ in range(h)])


def line(text, **extra):
    return json.dumps(dict({"messages": [{"role": "user", "content": text}]}, **extra), ensure_ascii=False)


def fid_of(content):
    return "scn-" + hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


class TaskSetCase(ServerCase):
    def setUp(self):
        self._saved = (server.SCN_TASKS_DIR, server.SCN_IMAGES_DIR)
        server.SCN_TASKS_DIR, server.SCN_IMAGES_DIR = temp_dir(), temp_dir()

    def tearDown(self):
        server.SCN_TASKS_DIR, server.SCN_IMAGES_DIR = self._saved

    def upload(self, content, name="t.jsonl"):
        st, _, d = self.request("POST", "/api/scenario-upload", {"kind": "tasks", "name": name, "content": content})
        self.assertEqual(st, 200, d)
        return d

    def get(self, path, **params):
        return self.request("GET", path + ("?" + urllib.parse.urlencode(params) if params else ""))

    def sets(self):
        st, _, d = self.get("/api/task-sets")
        self.assertEqual((st, d["ok"]), (200, True))
        return {x["id"]: x for x in d["sets"]}, [x["id"] for x in d["sets"]]


class TestTaskSetMeta(TaskSetCase):
    def test_import_saves_name_and_time_and_dedupes(self):
        content = line("你好 %s" % uuid.uuid4().hex)
        d = self.upload(content, "C:\\fakepath\\客服问答.jsonl")
        self.assertEqual((d["name"], d["exists"]), ("客服问答", False))            # 名称 = 文件名去掉路径和扩展名
        with open(tasksets.meta_path(server.SCN_TASKS_DIR, d["file_id"]), encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual(meta["name"], "客服问答")
        self.assertRegex(meta["imported_utc"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$")
        lst = self.request("GET", "/api/scenario-list")[2]
        self.assertEqual([(t["file_id"], t["name"]) for t in lst["tasks"]], [(d["file_id"], "客服问答")])
        again = self.upload(content, "别的名字.jsonl")                                # 内容完全相同: 不重复保存, 名称不变
        self.assertEqual((again["file_id"], again["name"], again["exists"]), (d["file_id"], "客服问答", True))
        self.assertEqual(sorted(os.listdir(server.SCN_TASKS_DIR)), sorted([d["file_id"] + ".jsonl", d["file_id"] + ".meta.json"]))
        self.assertEqual(self.upload(line("x"), ".jsonl")["name"], fid_of(line("x")))  # 文件名只剩扩展名: 用 id

    def test_old_file_without_meta(self):
        """3.6.0 之前导入的文件没有元数据: 名称用 id, 导入时间用文件修改时间; 再导入一次同样的内容时补上名称。"""
        content = line("旧文件 %s" % uuid.uuid4().hex)
        fid = fid_of(content)
        path = tasksets.file_path(server.SCN_TASKS_DIR, fid)
        with open(path, "wb") as f:
            f.write(content.encode("utf-8"))
        ts = 1767323045  # 2026-01-02T03:04:05Z
        os.utime(path, (ts, ts))
        item = self.sets()[0][fid]
        self.assertEqual((item["name"], item["named"], item["imported_utc"]), (fid, False, "2026-01-02T03:04:05"))
        d = self.upload(content, "补上的名字.txt")
        self.assertEqual((d["exists"], d["name"]), (True, "补上的名字"))
        item = self.sets()[0][fid]
        self.assertEqual((item["name"], item["named"], item["imported_utc"]), ("补上的名字", True, "2026-01-02T03:04:05"))

    def test_meta_broken_falls_back(self):
        d = self.upload(line("a %s" % uuid.uuid4().hex))
        with open(tasksets.meta_path(server.SCN_TASKS_DIR, d["file_id"]), "w", encoding="utf-8") as f:
            f.write("{坏了")
        item = self.sets()[0][d["file_id"]]
        self.assertEqual((item["name"], item["named"]), (d["file_id"], False))
        self.assertTrue(item["imported_utc"])

    def test_name_rules(self):
        self.assertEqual(tasksets.clean_name("  a\x00b\u202e c\n "), ("ab c", ""))    # 去掉控制字符和首尾空白
        self.assertEqual(tasksets.clean_name("\ufeff \t")[1], "名称不能为空")
        self.assertEqual(tasksets.clean_name("字" * 80), ("字" * 80, ""))
        self.assertIn("81", tasksets.clean_name("字" * 81)[1])
        self.assertEqual(tasksets.clean_name("😀" * 80)[1], "")                       # 按字数(码点)算, 不按字节
        self.assertEqual(tasksets.default_name("a.b.TXT", "scn-x"), "a.b")
        self.assertEqual(tasksets.default_name("/tmp/客服.v2.jsonl", "scn-x"), "客服.v2")
        self.assertEqual(tasksets.default_name("长" * 100 + ".jsonl", "scn-x"), "长" * 80)
        self.assertEqual(tasksets.download_name('a/b:c*"d?', "scn-x"), "a_b_c_d_.jsonl")
        self.assertEqual(tasksets.download_name(" .. ", "scn-x"), "scn-x.jsonl")


class TestTaskSetList(TaskSetCase):
    def content(self):
        img = data_url(png_of(64, 64))
        return "\n".join([
            line("abcde"),                                                                        # 1 可用, 5 字
            line("0123456789", params={"max_tokens": 256, "response_format": {"type": "json_object"}}),  # 2 可用 + JSON
            json.dumps({"messages": [{"role": "user", "content": [{"type": "text", "text": "看图"},
                                                                  {"type": "image_url", "image_url": {"url": img}}]}]}),  # 3 可用 + 图
            "",                                                                                   # 4 空行
            '{"messages":[{"role":"usr","content":"x"}]}',                                        # 5 有问题
            '{"no":"messages"}',                                                                  # 6 跳过
            line("y", params={"max_tokens": "abc"}),                                              # 7 可用 + 提醒
        ]) + "\n"

    def test_stats_sorting_and_cache(self):
        content = self.content()
        d = self.upload(content, "统计.jsonl")
        items, order = self.sets()
        it = items[d["file_id"]]
        self.assertEqual({k: it[k] for k in ("total", "valid", "bad", "skipped", "json", "image", "warnings")},
                         {"total": 6, "valid": 4, "bad": 1, "skipped": 1, "json": 1, "image": 1,
                          "warnings": 2})                                         # 图片偏小 + max_tokens 写错
        self.assertEqual((it["chars_avg"], it["chars_max"]), ((5 + 10 + 2 + 1) / 4.0, 10))  # 只算可用的行, 图片不算
        self.assertEqual((it["mt_top"], it["mt_unset"]), ([4096, 3], 2))   # 两行没写 + 一行写错(按默认 4096)
        self.assertEqual((it["size"], it["uses"], it["busy"]), (len(content.encode("utf-8")), 0, False))
        rep = bench.check_task_text(content)                               # 与上传时的检查报告一致
        self.assertEqual((it["total"], it["valid"], it["json"], it["image"]), (rep["total"], rep["valid"], rep["json"], rep["image"]))
        # 新导入的在前: 把第一个的导入时间改早
        d2 = self.upload(line("第二个 %s" % uuid.uuid4().hex), "第二个.jsonl")
        tasksets.write_meta(server.SCN_TASKS_DIR, d["file_id"], imported_utc="2020-01-01T00:00:00")
        self.assertEqual(self.sets()[1], [d2["file_id"], d["file_id"]])
        hits = server._task_file_check.cache_info().hits
        self.sets()
        self.assertEqual(server._task_file_check.cache_info().hits, hits + 2)  # 没变的文件不重读

    def test_scan_matches_check_task_text(self):
        """逐行索引与上传检查逐行一致: 行号(含空行、\\r\\n、\\r、开头的 BOM)、状态、原因。"""
        lines = [line("a"), "", '{"messages":[', line("b"), '["x"]', "   ", line("c", meta={"prompt_tokens": 99999})]
        text = "\ufeff" + lines[0] + "\r\n" + "\r".join(lines[1:4]) + "\n" + "\n".join(lines[4:])
        p = os.path.join(temp_dir(), "x.jsonl")
        with open(p, "wb") as f:
            f.write(text.encode("utf-8"))
        s = tasksets.scan_file(p)
        rep = bench.check_task_text(text)
        self.assertEqual({k: s["summary"][k] for k in ("total", "valid", "skipped", "bad")},
                         {k: rep[k] for k in ("total", "valid", "skipped", "bad")})
        self.assertEqual([(r[tasksets.NO], r[tasksets.REASON]) for r in s["rows"] if r[tasksets.ST] != "ok"],
                         [(p_["line"], p_["reason"]) for p_ in rep["problems"]])
        self.assertEqual([r[tasksets.NO] for r in s["rows"]], [1, 3, 4, 5, 7])


class TestTaskSetDetail(TaskSetCase):
    def make(self):
        rows = []
        for i in range(1, 31):
            if i % 10 == 0:
                rows.append('{"messages":[{"role":"usr","content":"坏行 %d"}]}' % i)       # 10 20 30 有问题
            elif i % 7 == 0:
                rows.append(line("第 %d 行 Apple" % i, params={"response_format": {"type": "json_object"}}))
            else:
                rows.append(line("第 %d 行 %s" % (i, "apple pie" if i % 2 else "banana"), meta={"note": "备注 %d" % i}))
        d = self.upload("\n".join(rows))
        return d["file_id"]

    def test_paging_filter_search(self):
        fid = self.make()
        st, _, d = self.get("/api/task-set", id=fid, limit=5)
        self.assertEqual((st, d["total"], [x["no"] for x in d["lines"]]), (200, 30, [1, 2, 3, 4, 5]))
        self.assertEqual(d["counts"], {"all": 30, "ok": 27, "bad": 3, "image": 0, "json": 4})
        self.assertEqual((len(d["set"]["chars"]), d["set"]["valid"], d["uses"]), (27, 27, []))
        self.assertEqual(d["lines"][0]["messages"][0], {"role": "user", "parts": [{"t": "text", "text": "第 1 行 apple pie"}]})
        self.assertEqual((d["lines"][0]["meta"], d["lines"][0]["mt"], d["lines"][0]["chars"]),
                         ({"note": "备注 1"}, 4096, len("第 1 行 apple pie")))
        d = self.get("/api/task-set", id=fid, offset=25, limit=5, head=0)[2]
        self.assertEqual(([x["no"] for x in d["lines"]], "set" in d), ([26, 27, 28, 29, 30], False))  # 翻页时不再带概况
        self.assertEqual(self.get("/api/task-set", id=fid, offset=40, head=0)[2]["lines"], [])
        d = self.get("/api/task-set", id=fid, status="bad", head=0)[2]
        self.assertEqual([(x["no"], x["status"]) for x in d["lines"]], [(10, "bad"), (20, "bad"), (30, "bad")])
        self.assertIn("usr", d["lines"][0]["reason"])
        d = self.get("/api/task-set", id=fid, status="json", head=0)[2]
        self.assertEqual([x["no"] for x in d["lines"]], [7, 14, 21, 28])
        d = self.get("/api/task-set", id=fid, q="APPLE", head=0)[2]           # 不分大小写; 数字按搜索之后算
        self.assertEqual(d["counts"], {"all": 17, "ok": 17, "bad": 0, "image": 0, "json": 4})  # 13 行 apple pie + 4 行 Apple
        d = self.get("/api/task-set", id=fid, q="备注 2", head=0)[2]           # 也搜 meta.note
        self.assertEqual([x["no"] for x in d["lines"]], [2, 22, 23, 24, 25, 26, 27, 29])
        d = self.get("/api/task-set", id=fid, q="坏行", status="bad", head=0)[2]  # 有问题的行也能按文字搜到
        self.assertEqual(d["total"], 3)
        for params in ({"status": "zz"}, {"limit": 0}, {"limit": 101}, {"limit": "x"}, {"offset": -1}):
            with self.subTest(params=params):
                st, _, e = self.get("/api/task-set", id=fid, **params)
                self.assertEqual((st, e["ok"]), (400, False))

    def test_truncation_and_full_line(self):
        long_text = "长" * 10000
        img = data_url(noisy_png(64, 64))
        content = "\n".join([line(long_text, meta={"note": "很长"}),
                             json.dumps({"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": img}}]}]}),
                             "{坏的 JSON " + "x" * 5000])
        fid = self.upload(content)["file_id"]
        d = self.get("/api/task-set", id=fid, head=0)[2]
        part = d["lines"][0]["messages"][0]["parts"][0]
        self.assertEqual((part["cut"], part["len"], len(part["text"])), (True, 10000, tasksets.TEXT_MAX))
        raw = d["lines"][2]["raw"]
        self.assertEqual((d["lines"][2]["messages"], raw["cut"], len(raw["text"])), (None, True, tasksets.TEXT_MAX))
        self.assertNotIn(img[30:90], json.dumps(d))                                 # 列表数据里没有图片的 base64
        st, _, full = self.get("/api/task-set-line", id=fid, line=1)
        self.assertEqual(full["line"]["messages"][0]["parts"][0], {"t": "text", "text": long_text})
        self.assertIn('"note": "很长"', full["pretty"])
        full = self.get("/api/task-set-line", id=fid, line=2)[2]
        self.assertIn("这里省略", full["pretty"])                                  # 原始 JSON 里图片只留开头
        self.assertNotIn(img[100:160], full["pretty"])
        self.assertIsNone(self.get("/api/task-set-line", id=fid, line=3)[2]["pretty"])  # 不是合法 JSON
        raw = self.get("/api/task-set-line", id=fid, line=2, raw=1)[2]
        self.assertEqual(raw["text"], content.split("\n")[1])                     # 复制用: 文件里这一行的原文
        self.assertEqual(self.get("/api/task-set-line", id=fid, line=9)[0], 404)
        self.assertEqual(self.get("/api/task-set-line", id=fid, line="x")[0], 400)

    def test_message_view_roles_and_tools(self):
        """逐行数据里的消息: 角色、工具调用(只给函数名)、没有文字的消息、params 与 meta 原样给页面。"""
        obj = {"messages": [{"role": "system", "content": "你是助手"},
                            {"role": "assistant", "content": None, "tool_calls": [
                                {"id": "c1", "type": "function", "function": {"name": "query_order", "arguments": "{}"}}, "坏的"]},
                            {"role": "tool", "tool_call_id": "c1", "content": "{\"ok\":true}"},
                            {"role": "user", "content": [{"type": "text", "text": "看"}, {"type": "input_audio", "input_audio": {}}]}],
               "params": {"max_tokens": 64, "top_p": 0.9}, "meta": {"note": "工具", "prompt_tokens": 12}}
        fid = self.upload(json.dumps(obj, ensure_ascii=False))["file_id"]
        ln = self.get("/api/task-set", id=fid, head=0)[2]["lines"][0]
        msgs = ln["messages"]
        self.assertEqual([m["role"] for m in msgs], ["system", "assistant", "tool", "user"])
        self.assertEqual((msgs[1]["parts"], msgs[1]["tool_calls"], msgs[1]["tool_calls_n"]), ([], ["query_order", "?"], 2))
        self.assertEqual(msgs[2]["tool_call_id"], "c1")
        self.assertEqual(msgs[3]["parts"][1], {"t": "other", "type": "input_audio"})
        self.assertEqual((ln["params"], ln["meta"], ln["mt"], ln["chars"]), (obj["params"], obj["meta"], 64, len("你是助手") + len('{"ok":true}') + 1))

    def test_image_endpoint(self):
        png, jpg = png_of(64, 48), jpeg_of(40, 30)
        msg = {"role": "user", "content": [{"type": "text", "text": "看图"},
                                           {"type": "image_url", "image_url": {"url": data_url(png)}},
                                           {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
                                           {"type": "image_url", "image_url": {"url": data_url(jpg, "image/png")}}]}
        broken = {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}]}
        fid = self.upload("\n".join([json.dumps({"messages": [msg]}), json.dumps({"messages": [broken]})]))["file_id"]
        st, h, body = self.get("/api/task-set-image", id=fid, line=1, idx=0)
        self.assertEqual((st, h["Content-Type"], body), (200, "image/png", png))
        self.assertIn("max-age", h["Cache-Control"])
        st, h, body = self.get("/api/task-set-image", id=fid, line=1, idx=2)   # 写的 image/png, 实际是 JPEG: 按真实格式
        self.assertEqual((st, h["Content-Type"], body), (200, "image/jpeg", jpg))
        st, _, e = self.get("/api/task-set-image", id=fid, line=1, idx=1)      # 网址形式: 不去下载
        self.assertEqual((st, e["ok"]), (400, False))
        self.assertIn("网址", e["error"])
        self.assertEqual(self.get("/api/task-set-image", id=fid, line=1, idx=3)[0], 404)  # 越界
        self.assertEqual(self.get("/api/task-set-image", id=fid, line=1, idx=-1)[0], 404)
        self.assertEqual(self.get("/api/task-set-image", id=fid, line=5, idx=0)[0], 404)
        self.assertEqual(self.get("/api/task-set-image", id=fid, line=1, idx="x")[0], 400)
        st, _, e = self.get("/api/task-set-image", id=fid, line=2, idx=0)      # 数据坏了
        self.assertEqual(st, 422)
        self.assertIn("不完整", e["error"])
        d = self.get("/api/task-set", id=fid, head=0)[2]
        imgs = d["lines"][0]["images"]
        self.assertEqual([(x["kind"], x.get("format"), x.get("width"), x.get("height")) for x in imgs],
                         [("data", "PNG", 64, 48), ("url", None, None, None), ("data", "JPEG", 40, 30)])
        self.assertEqual(imgs[1]["url"], "https://example.com/a.png")
        self.assertEqual([p["t"] for p in d["lines"][0]["messages"][0]["parts"]], ["text", "img", "img", "img"])
        self.assertEqual((d["lines"][1]["status"], d["lines"][1]["images"][0]["kind"]), ("bad", "data"))
        self.assertFalse(d["lines"][1]["images"][0]["ok"])


class TestTaskSetManage(TaskSetCase):
    def test_rename(self):
        d = self.upload(line("r %s" % uuid.uuid4().hex), "旧名.jsonl")
        fid, before = d["file_id"], d["imported_utc"]
        st, _, r = self.request("POST", "/api/task-set-rename", {"id": fid, "name": "  新\x00名\u202e \n"})
        self.assertEqual((st, r["name"]), (200, "新名"))
        item = self.sets()[0][fid]
        self.assertEqual((item["name"], item["imported_utc"]), ("新名", before))  # 导入时间不变
        self.assertEqual(self.request("POST", "/api/task-set-rename", {"id": fid, "name": "字" * 80})[0], 200)
        for name, code, word in (("", 400, "不能为空"), (" \t ", 400, "不能为空"), ("字" * 81, 400, "80"), (123, 400, "文字")):
            with self.subTest(name=name):
                st, _, e = self.request("POST", "/api/task-set-rename", {"id": fid, "name": name})
                self.assertEqual((st, e["ok"]), (code, False))
                self.assertIn(word, e["error"])
        self.assertEqual(self.sets()[0][fid]["name"], "字" * 80)
        self.assertEqual(self.request("POST", "/api/task-set-rename", {"id": "scn-0123456789ab", "name": "x"})[0], 404)

    def test_delete(self):
        d = self.upload(line("d %s" % uuid.uuid4().hex))
        fid = d["file_id"]
        path = tasksets.file_path(server.SCN_TASKS_DIR, fid)
        job = server.JOBS["perf"]
        self.assertTrue(job.try_start(None, "测试", files=[path]))              # 正在跑的测试在用: 拒绝
        try:
            st, _, e = self.request("POST", "/api/task-set-delete", {"id": fid})
            self.assertEqual(st, 409)
            self.assertIn("正在用", e["error"])
            self.assertTrue(self.sets()[0][fid]["busy"])
        finally:
            job.set(running=False)
        self.assertTrue(os.path.isfile(path))
        st, _, r = self.request("POST", "/api/task-set-delete", {"id": fid})
        self.assertEqual((st, r["ok"], r["uses"]), (200, True, 0))
        self.assertEqual(os.listdir(server.SCN_TASKS_DIR), [])                   # 元数据一起删掉
        self.assertEqual(self.request("POST", "/api/task-set-delete", {"id": fid})[0], 404)
        self.assertEqual(self.get("/api/task-set", id=fid)[0], 404)

    def test_download_name(self):
        content = line("下载 %s" % uuid.uuid4().hex) + "\n" + line("第二行") + "\n"
        d = self.upload(content, "客服 问答.jsonl")
        st, h, body = self.get("/api/task-set-download", id=d["file_id"])
        self.assertEqual((st, body), (200, content.encode("utf-8")))                   # 原文件, 一个字节都不改
        self.assertTrue(h["Content-Type"].startswith("application/x-ndjson"))
        disp = h["Content-Disposition"]
        self.assertIn('filename="%s.jsonl"' % d["file_id"], disp)               # 非 ASCII 名称: 纯 ASCII 的备用名用 id
        self.assertIn("filename*=UTF-8''" + urllib.parse.quote("客服 问答.jsonl", safe=""), disp)
        self.request("POST", "/api/task-set-rename", {"id": d["file_id"], "name": "my tasks v2"})
        disp = self.get("/api/task-set-download", id=d["file_id"])[1]["Content-Disposition"]
        self.assertIn('filename="my tasks v2.jsonl"', disp)


class TestTaskSetUses(TaskSetCase):
    def test_usage_written_and_counted(self):
        d = self.upload(line("用 %s" % uuid.uuid4().hex), "压测用.jsonl")
        fid = d["file_id"]
        cfg = server._parse_scenarios({"scenarios": {"tasks": ["custom"], "custom_file_id": fid}})
        self.assertEqual(cfg["task_set"], {"id": fid, "name": "压测用"})
        bench._CANCEL, bench._REQ_EXTRA = None, {}
        m = MockServer(lambda method, path, body: (400, {"error": {"message": "bad"}}, None))
        try:  # 阶段结果里记下用的是哪个任务集(请求失败也记)
            ph = bench.phase_scenario(m.url + "/v1/chat/completions", {}, "m", "custom",
                                      dict(cfg, conc=[1], requests_per_worker=1, max_attempts=1, retry_pause_s=0))
        finally:
            m.close()
        self.assertEqual(ph["task"]["task_set"], {"id": fid, "name": "压测用"})
        self.assertEqual(ph["task"]["pool_size"], 1)
        tag = uuid.uuid4().hex[:8]

        def run(rid, when, task_set=None, pid="scn_custom", extra=None):
            doc = perf_doc("run_%s_%s" % (when, tag + rid))
            doc["started_utc"] = "2026-03-0%sT00:00:00+00:00" % when[-1]
            task = {"tpl": "custom", "label": "自定义任务集", "pool_size": 1}
            if task_set:
                task["task_set"] = task_set
            doc["phases"].append({"id": pid, "task": task, "points": [dict({"conc": 1, "total": 1, "ok": 1, "fail": 0}, **(extra or {}))]})
            sinks.SqliteSink().save(doc)
            return doc["run_id"]
        r1 = run("a", "20260301", {"id": fid, "name": "压测用"})
        r2 = run("b", "20260302", {"id": fid, "name": "当时的名字"})
        run("c", "20260303", {"id": "scn-ffffffffffff", "name": "别的"})
        run("d", "20260304")                                                     # 旧测试: 没有记录
        run("e", "20260305", extra={"task_set": "不是记录"})                     # LIKE 筛进来, 但 task 里没有记录: 不算
        run("f", "20260306", {"id": fid, "name": "压测用"}, pid="scn_chat")      # 不是自定义任务集阶段: 不算
        uses = store.task_set_uses()
        self.assertEqual([u["run_id"] for u in uses[fid]], [r2, r1])            # 新的在前
        self.assertEqual((uses[fid][0]["name"], uses[fid][0]["model"], uses[fid][0]["status"]), ("当时的名字", "m", "done"))
        item = self.sets()[0][fid]
        self.assertEqual((item["uses"], item["last_used"]), (2, "2026-03-02T00:00:00+00:00"))
        d = self.get("/api/task-set", id=fid)[2]
        self.assertEqual([u["run_id"] for u in d["uses"]], [r2, r1])
        self.assertEqual(self.request("POST", "/api/run-delete", {"run_id": r2})[0], 200)  # 删掉的测试不再计入
        self.assertEqual(self.sets()[0][fid]["uses"], 1)
        st, _, r = self.request("POST", "/api/task-set-delete", {"id": fid})
        self.assertEqual((st, r["uses"]), (200, 1))
        self.assertEqual([u["run_id"] for u in store.task_set_uses()[fid]], [r1])  # 已经跑完的测试结果不受影响

    def test_max_tokens_rule(self):
        """实际发送的 max_tokens 与检查时的提醒一致: 不是正整数按默认值, 超过上限按上限。"""
        rp = type("RP", (), {"mt_default": 4096, "mt_cap": 8192})()
        for params, want in (({}, 4096), ({"max_tokens": 256}, 256), ({"max_completion_tokens": 300}, 300),
                             ({"max_tokens": -5}, 4096), ({"max_tokens": "abc"}, 4096), ({"max_tokens": 0, "max_completion_tokens": 64}, 64),
                             ({"max_tokens": 99999}, 8192)):
            with self.subTest(params=params):
                body = bench._replay_body("m", {"messages": [], "params": params}, rp)
                self.assertEqual((body["max_tokens"], "max_completion_tokens" in body), (want, False))
                self.assertEqual(bench.task_max_tokens(params), want)


class TestTaskSetIds(TaskSetCase):
    def test_bad_ids_rejected(self):
        for bad in ("", "scn-XYZ", "../x", "scn-0123456789abc", "scn-0123456789a/"):
            with self.subTest(id=bad):
                for path in ("/api/task-set", "/api/task-set-line", "/api/task-set-image", "/api/task-set-download"):
                    st, _, e = self.get(path, id=bad, line=1, idx=0)
                    self.assertEqual((st, e["ok"]), (400, False), path)
                for path in ("/api/task-set-rename", "/api/task-set-delete"):
                    self.assertEqual(self.request("POST", path, {"id": bad, "name": "x"})[0], 400, path)
        self.assertEqual(self.request("POST", "/api/task-set-delete", {"id": ["scn-0123456789ab"]})[0], 400)
        st, _, e = self.get("/api/task-set", id="scn-0123456789ab")
        self.assertEqual((st, e["error"]), (404, "任务集不存在（可能已被删除）"))


class TestTaskSetToken(TaskSetCase):
    token = "s3cret"

    def test_token_required(self):
        auth = {"X-Bench-Token": "s3cret"}
        for path in ("/api/task-sets", "/api/task-set?id=scn-0123456789ab", "/api/task-set-line?id=scn-0123456789ab&line=1",
                     "/api/task-set-image?id=scn-0123456789ab&line=1&idx=0", "/api/task-set-download?id=scn-0123456789ab"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 401)
                self.assertIn(self.request("GET", path, headers=auth)[0], (200, 404))
        for path in ("/api/task-set-rename", "/api/task-set-delete"):
            self.assertEqual(self.request("POST", path, {"id": "scn-0123456789ab", "name": "x"})[0], 401)
            self.assertEqual(self.request("POST", path, {"id": "scn-0123456789ab", "name": "x"}, auth)[0], 404)


if __name__ == "__main__":
    unittest.main()
