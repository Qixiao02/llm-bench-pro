# -*- coding: utf-8 -*-
import json
import os
import random
import struct
import threading
import time
import unittest
import zlib

from _util import MockServer, load_json, temp_dir
import bench
import cdp
import gen
import gen_specs
import geneval


def sse(tokens=5, reasoning=False):
    key = "reasoning_content" if reasoning else "content"
    chunks = [b'data: {"choices":[{"delta":{"%s":"x"}}]}\n\n' % key.encode() for _ in range(tokens)]
    chunks.append(b'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":%d}}\n\ndata: [DONE]\n\n' % tokens)
    return b"".join(chunks)


class TestBench(unittest.TestCase):
    def setUp(self):
        bench._NO_IGNORE_EOS.clear()
        bench._REQ_EXTRA = {}
        bench._CANCEL = None

    def test_suites_not_mutated(self):
        before = json.dumps(bench.SUITES, sort_keys=True)
        m = MockServer(lambda *a: (200, sse(), "text/event-stream"))
        try:
            bench.run_suite(m.url + "/v1/chat/completions", "m", suite="quick", outdir=temp_dir(),
                            conc_ladder=[1], matrix_conc=1, lens=[1])
        finally:
            m.close()
        self.assertEqual(json.dumps(bench.SUITES, sort_keys=True), before)

    def test_ignore_eos_sent_and_fallback(self):
        def h(method, path, body):
            if path.startswith("/strict") and "ignore_eos" in body:
                return 400, {"error": "Unrecognized request argument supplied: ignore_eos"}, None
            return 200, sse(reasoning=True), "text/event-stream"
        m = MockServer(h)
        try:
            bench._REQ_EXTRA = {"ignore_eos": True}
            s = bench.stream_call(m.url + "/ok", {"model": "m", "messages": []}, {})
            self.assertTrue(m.calls[-1][2]["ignore_eos"])
            self.assertEqual(len(s["stamps"]), 5)  # 推理 delta 计入时间戳
            bench.stream_call(m.url + "/strict", {"model": "m", "messages": []}, {})
            self.assertNotIn("ignore_eos", m.calls[-1][2])
            self.assertIn(m.url + "/strict", bench._NO_IGNORE_EOS)
        finally:
            m.close()

    def test_cancel_marks_status(self):
        cancel = threading.Event()
        count = {"n": 0}

        def h(method, path, body):
            count["n"] += 1
            if count["n"] == 2:
                cancel.set()
            return 200, sse(), "text/event-stream"
        m = MockServer(h)
        out = temp_dir()
        try:
            loc = bench.run_suite(m.url + "/v1/chat/completions", "m", suite="quick", outdir=out, cancel=cancel)
        finally:
            m.close()
        doc = load_json(loc)
        self.assertEqual(doc["status"], "cancelled")
        self.assertLess(count["n"], 10)
        self.assertTrue(doc["overrides"]["fixed_output"])

class TestScenarios(unittest.TestCase):
    """任务模板场景(chat/code/json/rag/vision/custom) / 真实请求回放(闭环+开环) / 预热与整格重跑。"""

    def setUp(self):
        bench._NO_IGNORE_EOS.clear()
        bench._REQ_EXTRA = {}
        bench._CANCEL = None

    def test_json_text_ok(self):
        self.assertTrue(bench._json_text_ok('{"a": 1}', ["a"]))
        self.assertTrue(bench._json_text_ok('```json\n{"a": 1}\n```', ["a"]))  # 围栏剥离
        self.assertFalse(bench._json_text_ok('{"b": 1}', ["a"]))  # 缺必需键
        self.assertFalse(bench._json_text_ok("不是 JSON"))
        self.assertFalse(bench._json_text_ok('[1,2]', ["a"]))  # 非对象

    def _run_phase(self, tpl_id, cfg, handler=None):
        m = MockServer(handler or (lambda *a: (200, sse(), "text/event-stream")))
        try:
            bench._REQ_EXTRA = {"ignore_eos": True}  # 场景请求不得携带固定输出
            return bench.phase_scenario(m.url + "/v1/chat/completions", {}, "m", tpl_id,
                                        dict({"retry_pause_s": 0, "conc": [2], "requests_per_worker": 2}, **cfg)), m
        finally:
            pass  # 调用方负责 close

    def test_json_tpl_contract_and_no_ignore_eos(self):
        ph, m = self._run_phase("json", {})
        try:
            self.assertEqual(ph["id"], "scn_json")
            self.assertEqual((ph["task"]["tpl"], ph["task"]["validator"]), ("json", "json"))
            self.assertEqual(len(m.calls), 4)
            for c in m.calls:
                self.assertNotIn("ignore_eos", c[2])
                self.assertEqual(c[2]["response_format"]["type"], "json_schema")
            pt = ph["points"][0]
            self.assertEqual((pt["ok"], pt["total"]), (4, 4))
            self.assertEqual((pt["json_total"], pt["json_ok"]), (4, 0))  # sse 内容非 JSON
            self.assertEqual(pt["json_rate"], 0.0)
        finally:
            m.close()

    def test_built_in_templates_shape(self):
        for tpl_id in ("chat", "code", "rag"):
            with self.subTest(tpl=tpl_id):
                ph, m = self._run_phase(tpl_id, {"rag_ctx": [1200]} if tpl_id == "rag" else {})
                try:
                    self.assertEqual(ph["id"], "scn_" + tpl_id)
                    self.assertIsNone(ph["task"]["validator"])
                    for c in m.calls:
                        self.assertNotIn("ignore_eos", c[2])
                        self.assertNotIn("response_format", c[2])  # 未声明契约的模板不带 response_format
                    if tpl_id == "rag":
                        self.assertEqual(ph["points"][0]["ctx_tokens"], 1200)
                        # 上下文规模落在档位 ±30% (资料 ~110 token/段 + 提问)
                        user = m.calls[0][2]["messages"][-1]["content"]
                        self.assertAlmostEqual(len(user), 1200, delta=1200 * 0.3)
                    else:
                        self.assertNotIn("ctx_tokens", ph["points"][0])
                    self.assertEqual(ph["points"][0]["ok"], 4)
                finally:
                    m.close()

    def test_templates_seed_deterministic(self):
        r1, r2 = random.Random("json-x-2-0"), random.Random("json-x-2-0")
        b1, b2 = bench._scn_json_body("m", r1, 256, False), bench._scn_json_body("m", r2, 256, False)
        self.assertEqual(b1["messages"][0], b2["messages"][0])              # system 相同
        self.assertEqual(b1["messages"][1]["content"].split("]", 1)[1],     # 除 uuid 盐外正文相同
                         b2["messages"][1]["content"].split("]", 1)[1])
        b3 = bench._scn_json_body("m", random.Random("json-x-2-0"), 256, True)
        self.assertEqual(b3["chat_template_kwargs"], {"enable_thinking": False})
        c1, c2 = (bench._scn_rag_body("m", random.Random("rag-4-2-1"), 512, "s", 1200) for _ in range(2))
        self.assertEqual(c1["messages"][1]["content"], c2["messages"][1]["content"])  # 同 seed 同资料组合

    def test_vision_body_and_missing_dir(self):
        d = temp_dir()
        with open(os.path.join(d, "a.png"), "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n\n")
        with open(os.path.join(d, "b.jpg"), "wb") as f:
            f.write(b"\xff\xd8\xff\xe0")
        imgs = bench._load_vision_images(d)
        self.assertEqual(len(imgs), 2)
        self.assertTrue(imgs[0].startswith("data:image/png;base64,"))
        body = bench._scn_vision_body("m", random.Random("v"), 512, "盐", imgs, 2)
        parts = body["messages"][0]["content"]
        self.assertEqual([p["type"] for p in parts], ["text", "image_url", "image_url"])
        self.assertIn("盐", parts[0]["text"])                              # 盐在文本里(防前缀缓存)
        self.assertTrue(parts[1]["image_url"]["url"].startswith("data:image/"))
        with self.assertRaises(RuntimeError):                               # 无目录快速失败
            bench._load_vision_images(os.path.join(d, "nope"))
        with self.assertRaises(RuntimeError):                               # 空目录快速失败
            bench._load_vision_images(temp_dir())

    def test_custom_tpl_uses_pool_cursor(self):
        d = temp_dir()
        p = os.path.join(d, "tasks.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            for i in range(8):
                f.write(json.dumps({"messages": [{"role": "user", "content": "t%d" % i}],
                                    "params": {"max_tokens": 100, "temperature": 0.5}}) + "\n")
        ph, m = self._run_phase("custom", {"custom_file": p})
        try:
            self.assertEqual(ph["id"], "scn_custom")
            sent = [c[2]["messages"][0]["content"] for c in m.calls]
            self.assertEqual(len(sent), 4)
            self.assertEqual(len(set(sent)), 4)                             # cursor 推进不重发
            self.assertEqual(m.calls[0][2]["max_tokens"], 100)              # 保留行内 params
            self.assertEqual(m.calls[0][2]["temperature"], 0.5)
            self.assertEqual(ph["task"]["pool_size"], 8)
            self.assertFalse(ph["points"][0]["pool_wrapped"])
        finally:
            m.close()

    def test_replay_pool_load_and_body(self):
        d = temp_dir()
        p = os.path.join(d, "rp.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps({"messages": [{"role": "user", "content": "a"}], "params": {"temperature": 0.7, "max_tokens": 2000}}) + "\n")
            f.write(json.dumps({"messages": [{"role": "user", "content": "b"}], "params": {"max_completion_tokens": 9999}}) + "\n")
            f.write("{坏行\n")
            f.write(json.dumps({"no": "messages"}) + "\n")                                   # 无 messages 跳过
            f.write(json.dumps({"messages": [{"role": "user", "content": "big"}], "meta": {"prompt_tokens": 99999}}) + "\n")  # 超限跳过
            f.write(json.dumps({"messages": [{"role": "user", "content": "c"}], "params": {"enable_thinking": True, "max_tokens": "abc"}}) + "\n")  # 脏 max_tokens 回退
        pool = bench.ReplayPool(p)
        self.assertEqual(len(pool), 3)
        self.assertEqual((pool.skipped, pool.bad), (2, 1))

        def body_of(content):  # 池会被固定种子洗牌, 按内容定位记录
            rec = next(r for r in pool.pool if r["messages"][0]["content"] == content)
            return bench._replay_body("m", rec, pool)
        b1, b2, b3 = body_of("a"), body_of("b"), body_of("c")
        self.assertEqual((b1["max_tokens"], b1["temperature"]), (2000, 0.7))
        self.assertEqual(b2["max_tokens"], 8192)              # 9999 截到 cap
        self.assertEqual(b3["max_tokens"], 4096)              # 脏值回退默认
        self.assertEqual(b3["chat_template_kwargs"], {"enable_thinking": True})
        pool.reserve(2)
        pool.reserve(2)
        self.assertTrue(pool.wrapped)                          # cursor 越过池长

    def test_replay_closed_no_repeat(self):
        d = temp_dir()
        p = os.path.join(d, "rp.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            for i in range(6):
                f.write(json.dumps({"messages": [{"role": "user", "content": "q%d" % i}], "params": {"max_tokens": 50}}) + "\n")
        m = MockServer(lambda *a: (200, sse(), "text/event-stream"))
        try:
            pool = bench.ReplayPool(p)
            ph = bench.phase_replay_closed(m.url + "/v1/chat/completions", {}, "m",
                                           {"conc": [2], "requests_per_worker": 2, "retry_pause_s": 0}, pool)
        finally:
            m.close()
        sent = [c[2]["messages"][0]["content"] for c in m.calls]
        self.assertEqual(len(sent), 4)
        self.assertEqual(len(set(sent)), 4)                    # cursor 推进: 不重发同一请求
        self.assertTrue(set(sent) <= {"q%d" % i for i in range(6)})
        pt = ph["points"][0]
        self.assertEqual((pt["ok"], pt["total"]), (4, 4))
        self.assertFalse(pt["pool_wrapped"])
        self.assertGreaterEqual(pt["max_inflight"], 1)

    def test_openloop_cell_and_determinism(self):
        r1 = random.Random("openloop-rate-%g" % 3.0)
        r2 = random.Random("openloop-rate-%g" % 3.0)
        self.assertEqual([r1.expovariate(3.0) for _ in range(50)],
                         [r2.expovariate(3.0) for _ in range(50)])  # A/B 到达时间轴相同
        d = temp_dir()
        p = os.path.join(d, "rp.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            for i in range(30):  # 池大于发送量, 不应回绕
                f.write(json.dumps({"messages": [{"role": "user", "content": "q%d" % i}], "params": {}}) + "\n")
        m = MockServer(lambda *a: (200, sse(), "text/event-stream"))
        try:
            pool = bench.ReplayPool(p)
            pt = bench._open_rate_cell(m.url + "/v1/chat/completions", {}, "m", 8.0, 1.6, pool)
        finally:
            m.close()
        self.assertEqual(pt["rate"], 8.0)
        self.assertGreater(pt["sent"], 2)
        self.assertEqual((pt["shed"], pt["fail"]), (0, 0))
        self.assertEqual(pt["ok"], pt["sent"])
        self.assertIsInstance(pt["inflight_ts"], list)
        self.assertGreaterEqual(pt["max_inflight"], 1)
        self.assertFalse(pt["pool_wrapped"])

    def test_openloop_sheds_over_limit(self):
        orig = bench.MAX_OPEN_INFLIGHT
        bench.MAX_OPEN_INFLIGHT = 1

        def h(method, path, body):
            time.sleep(0.25)
            return 200, sse(), "text/event-stream"
        d = temp_dir()
        p = os.path.join(d, "rp.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            for i in range(10):
                f.write(json.dumps({"messages": [{"role": "user", "content": "q%d" % i}], "params": {}}) + "\n")
        m = MockServer(h)
        try:
            pool = bench.ReplayPool(p)
            pt = bench._open_rate_cell(m.url + "/v1/chat/completions", {}, "m", 40.0, 0.5, pool)
        finally:
            m.close()
            bench.MAX_OPEN_INFLIGHT = orig
        self.assertGreater(pt["shed"], 0)                      # 在途超限丢弃并计数
        self.assertEqual(pt["total"], pt["sent"] - pt["shed"])

    def test_retry_cell_disclosure(self):
        state = {"n": 0}

        def once():
            state["n"] += 1
            bad = state["n"] == 1
            return {"ok": 0 if bad else 2, "fail": 2 if bad else 0, "total": 2,
                    "errors": ["boom"] if bad else []}
        rec = bench._retry_cell(once, "t", 3, 0.0)
        self.assertEqual(rec["attempts"], 2)
        self.assertEqual(len(rec["failed_attempts"]), 1)
        self.assertEqual(rec["failed_attempts"][0]["errors"], ["boom"])
        self.assertEqual(rec["ok"], 2)

    def test_shape_warmup_not_in_phases(self):
        m = MockServer(lambda *a: (200, sse(), "text/event-stream"))
        out = temp_dir()
        try:
            loc = bench.run_suite(m.url + "/v1/chat/completions", "m", suite="quick", outdir=out,
                                  conc_ladder=[1], matrix_conc=1, lens=[1],
                                  warmup_shapes=True, retry_pause_s=0)
        finally:
            m.close()
        doc = load_json(loc)
        self.assertEqual([p["id"] for p in doc["phases"]], ["prefill", "prefill_conc", "decode", "concurrency"])
        self.assertTrue(doc["overrides"]["warmup_shapes"])
        posts = [c for c in m.calls if c[0] == "POST"]
        # 4 个预热请求(单发 + 3 个形状) + 5 个正式请求(prefill 1 + 矩阵 1 + 解码 2 + 并发 1)
        self.assertEqual(len(posts), 9)

class TestGenEval(unittest.TestCase):
    def test_specs_cover_all_tasks(self):
        ids = {t["id"] for t in gen.GEN_TASKS}
        self.assertEqual(ids - set(gen_specs.SPECS), set())
        for tid in ids:
            self.assertTrue(gen_specs.get(tid)["checklist"], tid)

    def test_static_checks_ignore_comments(self):
        task = {"features": [r"click"]}
        html = "<!doctype html><html><script>// click here\n/* click */let a=1</script></html>"
        checks = {c["id"]: c["pass"] for c in geneval.static_checks(html, task)["checks"]}
        self.assertTrue(checks["complete"])
        self.assertFalse(checks["f1"])  # 注释里的关键词不算
        self.assertFalse(geneval.source_complete("<html><script>let a=1"))
        quoted = "<!doctype html><html><script>let s=\"<script>\";</script></html>"
        self.assertTrue(geneval.source_complete(quoted))  # 字符串里的 <script> 不算未闭合

    def test_png_decode_and_diff(self):
        def png(w, h, rgb):
            raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
            chunk = lambda t, d: struct.pack("!I", len(d)) + t + d + struct.pack("!I", zlib.crc32(t + d) & 0xffffffff)  # noqa: E731
            return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack("!IIBBBBB", w, h, 8, 2, 0, 0, 0))
                    + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
        black, white = png(8, 4, (0, 0, 0)), png(8, 4, (255, 255, 255))
        self.assertEqual(cdp.decode_png(black)[:3], (8, 4, 3))
        self.assertEqual(cdp.image_stats(black)["colors"], 1)
        self.assertEqual(cdp.image_diff(black, black), 0)
        self.assertEqual(cdp.image_diff(black, white), 1.0)

    def test_judge_parse_requires_all_items(self):
        checklist = [{"id": "t1", "label": "a"}, {"id": "visual", "label": "b"}]
        ok = geneval._parse_judge('x {"items":[{"id":"t1","score":8},{"id":"visual","score":12}],"summary":"s"}', checklist)
        self.assertEqual([i["score"] for i in ok["items"]], [8, 10])  # 超范围截断到 10
        self.assertEqual(ok["score"], 90.0)
        with self.assertRaises(ValueError):
            geneval._parse_judge('{"items":[{"id":"t1","score":8}]}', checklist)


def sse_text(content="", reasoning="", finish="stop", chunk=7):
    out = []
    for key, text in (("reasoning_content", reasoning), ("content", content)):
        for i in range(0, len(text), chunk):
            out.append(b"data: " + json.dumps({"choices": [{"delta": {key: text[i:i + chunk]}}]}).encode() + b"\n\n")
    out.append(b"data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": finish}]}).encode() + b"\n\n")
    out.append(b'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":20}}\n\ndata: [DONE]\n\n')
    return b"".join(out)


class TestGenGeneration(unittest.TestCase):
    def setUp(self):
        gen.iq._DROPPED.clear()

    def test_extract_html(self):
        doc = "<!doctype html><html><body>hi</body></html>"
        cases = [("```html\n<!doctype html><html>\n```html\n<body>x</body></html>\n```", "<!doctype html><html>\n<body>x</body></html>"),
                 ("```css\nbody{}\n```\n```html\n%s\n```" % doc, doc),
                 ("先安装：\n```\nnpm i\n```\n```html\n%s\n```" % doc, doc),
                 ("```html\n<!doctype html><html><script>const s='```';</script></html>\n```",
                  "<!doctype html><html><script>const s='```';</script></html>"),
                 ("说明文字\n" + doc + "\n以上。", doc),
                 ("<think>很长的思考", "")]
        for text, want in cases:
            with self.subTest(text=text[:30]):
                self.assertEqual(gen.extract_html(text), want)

    def test_task_ids_are_exact(self):
        self.assertIsNone(gen.normalize_task_ids(None))
        self.assertEqual(gen.normalize_task_ids("ecomdetail"), ["ecomdetail"])
        self.assertEqual(gen.normalize_task_ids(["snake", "tetris"]), ["snake", "tetris"])
        with self.assertRaises(ValueError):
            gen.normalize_task_ids([])
        with self.assertRaises(ValueError):
            gen.normalize_task_ids(["nope"])

    def test_code_excerpt_keeps_script(self):
        html = "<!doctype html><html><head><style>" + ("x" * 5000) + "</style></head><body><script>" + ("GAME" * 8000) + "</script></body></html>"
        out = geneval._code_excerpt(html, 8000)
        self.assertIn("GAME", out)
        self.assertIn("<script>", out)
        # 脚本后部的逻辑不能因为只留开头而被裁掉; 字符串里的 </script> 也不能把后面截断
        tail = "TAIL_MARKER_987"
        long = ("<!doctype html><html><head><style>" + ("x" * 8000) + "</style></head><body><script>"
                + "var s='</script>';" + ("a" * 20000) + tail + "function game(){return 1}</script></body></html>")
        out = geneval._code_excerpt(long, 12000)
        self.assertIn(tail, out)
        self.assertIn("function game", out)
        self.assertIn("var s=", out)

    def test_stitch(self):
        prev = "<script>\nfunction a(){\n  ctx.fillStyle = '#0"
        self.assertEqual(gen._stitch(prev, "  ctx.fillStyle = '#000';\n}\n"), "<script>\nfunction a(){\n  ctx.fillStyle = '#000';\n}\n")
        self.assertEqual(gen._stitch("abc\nlet x = 1;\nlet y", "```html\nlet x = 1;\nlet y = 2;"), "abc\nlet x = 1;\nlet y = 2;")
        self.assertEqual(gen._stitch("abcdef", "00;"), "abcdef00;")
        self.assertEqual(gen._stitch("let x = 1", "\nlet y = 2"), "let x = 1\nlet y = 2")
        self.assertEqual(gen._stitch("<script>\na", "\nalert(1)\n</script>"), "<script>\na\nalert(1)\n</script>")
        self.assertEqual(gen._stitch("myfunction", "function draw(){}"), "myfunction\nfunction draw(){}")
        self.assertEqual(gen._stitch("let x = 1", "let y = 2"), "let x = 1\nlet y = 2")
        self.assertEqual(gen._stitch("simYe", "ars += 1"), "simYears += 1")
        self.assertEqual(gen._stitch("<p>partial", "</p></body></html>"), "<p>partial</p></body></html>")

    def test_chat_stream_and_json_fallback(self):
        def h(method, path, body):
            if path.startswith("/json"):
                return 200, {"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}], "usage": {"completion_tokens": 1}}, None
            return 200, sse_text("hello world", reasoning="think" * 5, finish="length"), "text/event-stream"
        m = MockServer(h)
        try:
            content, usage, finish, reasoning = gen.chat(m.url + "/v1", {"model": "m", "messages": []}, {})
            self.assertEqual((content, finish, usage["completion_tokens"], reasoning), ("hello world", "length", 20, "think" * 5))
            self.assertTrue(m.calls[0][2]["stream"])
            self.assertEqual(gen.chat(m.url + "/json", {"model": "m", "messages": []}, {})[0], "hi")
        finally:
            m.close()

    def test_chat_cancel(self):
        cancel = threading.Event()
        cancel.set()
        m = MockServer(lambda *a: (200, sse_text("x" * 100), "text/event-stream"))
        try:
            with self.assertRaises(gen.Cancelled):
                gen.chat(m.url + "/v1", {"model": "m", "messages": []}, {}, cancel)
        finally:
            m.close()

    def test_continuation_prefix(self):
        first = "```html\n<!doctype html><html><body>\n<script>\nlet simYears = 1;\nfunction step(){ simYe"
        second = "ars += 1; }\n</script></body></html>\n```"

        def h(method, path, body):
            if len(body["messages"]) == 1:
                return 200, sse_text(first, finish="length"), "text/event-stream"
            ok = body.get("continue_final_message") and body["messages"][-1] == {"role": "assistant", "content": first}
            return 200, sse_text(second if ok else "WRONG"), "text/event-stream"
        m = MockServer(h)
        try:
            full, _, _, cont, _ = gen.gen_complete(m.url + "/v1", "m", "p", 100, {})
            html = gen.extract_html(full)
            self.assertEqual(cont, 1)
            self.assertIn("simYears += 1;", html)
            self.assertTrue(html.endswith("</html>"))
        finally:
            m.close()

    def test_continuation_context_overflow_keeps_partial(self):
        first = "<!doctype html><html><body>\n<p>partial"

        def h(method, path, body):
            if len(body["messages"]) == 1:
                return 200, sse_text(first, finish="length"), "text/event-stream"
            if body["max_tokens"] > 700:
                return 400, {"message": "This model's maximum context length is 1000 tokens. However, you requested "
                                        "1300 tokens (300 in the messages, 1000 in the completion)."}, None
            return 200, sse_text("</p></body></html>"), "text/event-stream"
        m = MockServer(h)
        try:
            full, _, _, cont, _ = gen.gen_complete(m.url + "/v1", "m", "p", 1000, {})
            self.assertEqual(full, first + "</p></body></html>")  # 按报错收缩 max_tokens 后续写成功
            self.assertEqual(m.calls[-1][2]["max_tokens"], 1000 - 300 - 32)
        finally:
            m.close()
        m = MockServer(lambda method, path, body: (200, sse_text(first, finish="length"), "text/event-stream")
                       if len(body["messages"]) == 1 else (500, {"error": "boom"}, None))
        try:
            full, _, _, _, _ = gen.gen_complete(m.url + "/v1", "m", "p", 1000, {})
            self.assertEqual(full, first)  # 续写失败时保留已生成部分
        finally:
            m.close()

    def test_continuation_fallback_when_prefix_rejected(self):
        first = "<!doctype html><html><body>\n<p>part one"

        def h(method, path, body):
            if "continue_final_message" in body:
                return 400, {"detail": [{"type": "extra_forbidden", "loc": ["body", "continue_final_message"],
                                         "msg": "Extra inputs are not permitted"}]}, None
            if len(body["messages"]) == 1:
                return 200, sse_text(first, finish="length"), "text/event-stream"
            if len(body["messages"]) == 3:
                return 200, sse_text(" and two</p></body></html>"), "text/event-stream"
            return 200, sse_text("WRONG"), "text/event-stream"
        m = MockServer(h)
        try:
            full, _, _, cont, _ = gen.gen_complete(m.url + "/v1", "m", "p", 100, {})
            self.assertEqual(full, "<!doctype html><html><body>\n<p>part one and two</p></body></html>")
        finally:
            m.close()


class TestGenEvalRobustness(unittest.TestCase):
    def test_key_params(self):
        self.assertEqual(geneval._key_params(".")[0]["windowsVirtualKeyCode"], 190)
        p, text = geneval._key_params("!")
        self.assertEqual((p["windowsVirtualKeyCode"], p["modifiers"], text), (49, 8, "!"))
        self.assertEqual(geneval._key_params("@")[0]["code"], "Digit2")
        self.assertEqual(geneval._key_params("中")[0]["windowsVirtualKeyCode"], 0)
        self.assertEqual(geneval._key_params("A")[0]["modifiers"], 8)

    def test_judge_parse_tolerant(self):
        ck = [{"id": "t%d" % i, "label": str(i)} for i in range(1, 6)]
        scores = (8, 6, 7, 9, 5)

        def items(fmt):
            return ",".join(fmt % (i, v) for i, v in zip(range(1, 6), scores))
        texts = ['说明 {见下}\n```json\n{"items":[%s],"summary":"ok"}\n```\n补充 {x}' % items('{"id":"T%d","score":"%d"}'),
                 '{"items":[%s],}' % items('{"id":"t%d","score":"%d/10"}'),
                 '{“items”：[%s]}' % items('{"id":"t%d","score":%d}')]
        for t in texts:
            with self.subTest(t=t[:20]):
                self.assertEqual([i["score"] for i in geneval._parse_judge(t, ck)["items"]], list(scores))
        hundred = geneval._parse_judge('{"items":[%s]}' % items('{"id":"t%d","score":%d5}'), ck)
        self.assertEqual([i["score"] for i in hundred["items"]], [9, 7, 8, 10, 6])
        missing = geneval._parse_judge('{"items":[%s]}' % ",".join('{"id":"t%d","score":8}' % i for i in range(1, 5)), ck)
        self.assertEqual((missing["items"][-1]["score"], missing["score"]), (None, 80.0))

    def test_browser_pool_recovers_from_broken_browsers(self):
        class FakeBrowser:
            version = "fake"

            def close(self):
                pass

        def probe(*a):
            time.sleep(0.1)
            raise RuntimeError("browser crashed")
        orig = (geneval.cdp.Browser, geneval.probe_work, geneval.cdp.find_browser)
        geneval.cdp.Browser, geneval.probe_work, geneval.cdp.find_browser = FakeBrowser, probe, lambda: "fake"
        try:
            ev = geneval.Evaluator(None, browsers=2)
            task = {"id": "snake", "name": "s", "features": []}
            d = temp_dir()
            threads = [threading.Thread(target=ev.evaluate, args=(task, os.path.join(d, "w%d.html" % i), "<html></html>"))
                       for i in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(10)
            self.assertFalse(any(t.is_alive() for t in threads))  # 浏览器损坏后等待者会被唤醒, 不会永久等待
            ev.close()
            self.assertRaises(RuntimeError, ev._acquire)
        finally:
            geneval.cdp.Browser, geneval.probe_work, geneval.cdp.find_browser = orig


if __name__ == "__main__":
    unittest.main()
