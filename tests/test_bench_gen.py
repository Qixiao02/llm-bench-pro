# -*- coding: utf-8 -*-
import json
import os
import struct
import threading
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


if __name__ == "__main__":
    unittest.main()
