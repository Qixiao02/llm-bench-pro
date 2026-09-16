# -*- coding: utf-8 -*-
import json
import os
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

    def test_stitch(self):
        prev = "<script>\nfunction a(){\n  ctx.fillStyle = '#0"
        self.assertEqual(gen._stitch(prev, "  ctx.fillStyle = '#000';\n}\n"), "<script>\nfunction a(){\n  ctx.fillStyle = '#000';\n}\n")
        self.assertEqual(gen._stitch("abc\nlet x = 1;\nlet y", "```html\nlet x = 1;\nlet y = 2;"), "abc\nlet x = 1;\nlet y = 2;")
        self.assertEqual(gen._stitch("abcdef", "00;"), "abcdef00;")

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
