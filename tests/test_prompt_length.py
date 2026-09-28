# -*- coding: utf-8 -*-
"""长输入按被测模型的实际 token 数拼(1.5): 测试开始时向服务校准, 各档实际长度要落在目标附近。
1.4 及以前按「每句 77.5 token」估算, 新一代分词器上每句只有 35 左右, 各档只有标称的 45%。
模拟服务器用一个假分词器: 每 2 个字符 1 个 token, 对话模板另算 12 个。"""
import json
import threading
import unittest

from _util import MockServer, load_json, temp_dir
import bench

TEMPLATE_TOKENS = 12


def fake_tokens(body):
    text = "".join(m["content"] for m in body.get("messages", []) if isinstance(m.get("content"), str))
    return len(text) // 2 + TEMPLATE_TOKENS


def sse(prompt_tokens, out=3):
    chunks = [b'data: {"choices":[{"delta":{"content":"x"}}]}\n\n' for _ in range(out)]
    chunks.append(b'data: {"choices":[],"usage":{"prompt_tokens":%d,"completion_tokens":%d}}\n\ndata: [DONE]\n\n'
                  % (prompt_tokens, out))
    return b"".join(chunks)


def tokenizer_server(fixed=None):
    """fixed: 不管输入多长都返回这个 prompt_tokens(模拟没有返回真实用量的服务)。"""
    return MockServer(lambda method, path, body: (200, sse(fixed if fixed is not None else fake_tokens(body),
                                                           min(int(body.get("max_tokens") or 3), 3)),
                                                  "text/event-stream"))


class PromptLengthCase(unittest.TestCase):
    def setUp(self):
        bench._NO_IGNORE_EOS.clear()
        bench._REQ_EXTRA = {}
        bench._CANCEL = None

    def tearDown(self):
        bench._CANCEL = None


class TestCalibration(PromptLengthCase):
    def test_calibration_measures_unit_and_overhead(self):
        m = tokenizer_server()
        try:
            cal = bench.calibrate_prompt(m.url + "/v1/chat/completions", {}, "m")
            self.assertEqual(cal["method"], "usage")
            self.assertAlmostEqual(cal["unit_tokens"], len(bench.ZH_UNIT) / 2.0, delta=0.5)
            head = len(bench.PREFILL_HEAD % (123456, 8)) // 2 + TEMPLATE_TOKENS
            self.assertAlmostEqual(cal["overhead_tokens"], head, delta=3)
            self.assertEqual([r for r, _ in cal["samples"]], list(bench.CAL_REPS))
            self.assertTrue(all(c[2]["max_tokens"] == 1 for c in m.calls))   # 校准请求只生成 1 个 token
        finally:
            m.close()

    def test_falls_back_when_usage_does_not_follow_length(self):
        m = tokenizer_server(fixed=10)   # 服务返回的输入 token 数固定不变
        try:
            cal = bench.calibrate_prompt(m.url + "/v1/chat/completions", {}, "m")
        finally:
            m.close()
        self.assertEqual((cal["method"], cal["unit_tokens"], cal["overhead_tokens"]), ("guess", bench.UNIT_GUESS, 0))
        self.assertIn("不随长度变化", cal["error"])

    def test_falls_back_when_request_fails(self):
        m = MockServer(lambda *a: (500, {"error": "boom"}, None))
        try:
            cal = bench.calibrate_prompt(m.url + "/v1/chat/completions", {}, "m")
        finally:
            m.close()
        self.assertEqual(cal["method"], "guess")
        self.assertIn("校准请求失败", cal["error"])

    def test_cancel_is_not_swallowed(self):
        m = tokenizer_server()
        ev = threading.Event()
        ev.set()
        bench._CANCEL = ev
        try:
            with self.assertRaises(bench.Cancelled):
                bench.calibrate_prompt(m.url + "/v1/chat/completions", {}, "m")
        finally:
            m.close()

    def test_resolve_ladder(self):
        cal = {"unit_tokens": 35.0, "overhead_tokens": 30}
        ladder = bench.resolve_ladder(["1K", "32K", ["8K", 103], ["1.5K"], ["自定义", 5]], cal)
        self.assertEqual(ladder, [("1K", 28, 1000), ("32K", 913, 32000), ("8K", 228, 8000),   # 旧写法的句数按标签重算
                                  ("1.5K", 42, 1500), ("自定义", 5, None)])                   # 认不出长度的保留原句数
        self.assertEqual(bench.label_tokens("128K"), 128000)
        self.assertIsNone(bench.label_tokens("128k tokens"))
        # 旧估算下与 1.4 的句数完全相同(校准不成时行为不变)
        old = bench.resolve_ladder(["1K", "8K", "16K", "128K"], {"unit_tokens": bench.UNIT_GUESS, "overhead_tokens": 0})
        self.assertEqual([r for _, r, _ in old], [13, 103, 206, 1652])


class TestLadderHitsTarget(PromptLengthCase):
    def test_run_suite_lengths_hit_targets(self):
        m = tokenizer_server()
        out = temp_dir()
        try:
            loc = bench.run_suite(m.url + "/v1/chat/completions", "m", suite="quick", outdir=out,
                                  conc_ladder=[1], matrix_conc=2, lens=[1, 4, 16])
        finally:
            m.close()
        doc = load_json(loc)
        self.assertEqual(doc["bench_version"], "1.5.0")
        cal = doc["prompt_calibration"]
        self.assertEqual(cal["method"], "usage")
        for pid in ("prefill", "prefill_conc"):
            ph = next(p for p in doc["phases"] if p["id"] == pid)
            self.assertEqual([p["label"] for p in ph["points"]], ["1K", "4K", "16K"])
            for p in ph["points"]:
                self.assertEqual(p["target_tokens"], bench.label_tokens(p["label"]))
                # 按整句拼: 误差不超过半句(另留几个 token 给各阶段说明文字的差别)
                self.assertLessEqual(abs(p["in_tokens"] - p["target_tokens"]), cal["unit_tokens"] / 2 + 5,
                                     (pid, p["label"], p["in_tokens"]))

    def test_longctx_hits_target(self):
        m = tokenizer_server()
        try:
            cal = bench.calibrate_prompt(m.url + "/v1/chat/completions", {}, "m")
            ph = bench.phase_longctx(m.url + "/v1/chat/completions", {}, "m", 32768, 3, cal)
        finally:
            m.close()
        p = ph["points"][0]
        self.assertEqual((p["label"], p["target_tokens"]), ("32K", 32768))
        self.assertLess(abs(p["in_tokens"] / 32768.0 - 1), 0.02)

    def test_rag_context_hits_target(self):
        m = tokenizer_server()
        try:
            ph = bench.phase_scenario(m.url + "/v1/chat/completions", {}, "m", "rag",
                                      {"conc": [1], "requests_per_worker": 2, "max_tokens": 3, "rag_ctx": [4000, 16000]})
        finally:
            m.close()
        cal = ph["task"]["rag_calibration"]
        self.assertEqual(cal["method"], "usage")
        for p in ph["points"]:
            self.assertLess(abs(p["prompt_tokens_avg"] / float(p["ctx_tokens"]) - 1), 0.03, p)

    def test_old_behaviour_when_server_reports_no_usage(self):
        """服务不返回真实用量时退回旧估算, 各档句数与 1.4 相同, 结果里注明没校准成。"""
        m = tokenizer_server(fixed=10)
        out = temp_dir()
        try:
            loc = bench.run_suite(m.url + "/v1/chat/completions", "m", suite="quick", outdir=out,
                                  conc_ladder=[1], matrix_conc=1)
            sent = [c[2] for c in m.calls if c[2].get("max_tokens") == 96]   # prefill 阶段的请求
        finally:
            m.close()
        doc = load_json(loc)
        self.assertEqual(doc["prompt_calibration"]["method"], "guess")
        head = len(bench.PREFILL_HEAD % (0, 0))
        reps = sorted({(len(b["messages"][0]["content"]) - head) // len(bench.ZH_UNIT) for b in sent})
        self.assertEqual(reps, [26, 103])   # quick 套件 2K / 8K, 与 1.4 的句数相同


def limited_server(max_len, report_len):
    """最大上下文 max_len 的服务: report_len=True 时 /v1/models 报出 max_model_len(vLLM 的做法),
    否则 /v1/models 404, 只能等请求被拒绝才知道。超长请求返回 vLLM 的原话。"""
    def h(method, path, body):
        if method == "GET":
            if report_len and path.endswith("/v1/models"):
                return 200, {"data": [{"id": "m", "max_model_len": max_len}, {"id": "other"}]}, None
            return 404, {"error": "not found"}, None
        n = fake_tokens(body)
        if n + int(body.get("max_tokens") or 0) > max_len:
            return 400, {"error": {"message": "This model's maximum context length is %d tokens. However, you requested %d "
                                              "tokens in the messages." % (max_len, n)}}, None
        return 200, sse(n, min(int(body.get("max_tokens") or 3), 3)), "text/event-stream"
    return MockServer(h)


class TestContextLimit(PromptLengthCase):
    """长度变准以后, 超过模型最大上下文的档位要跳过并写明原因, 不能让整个测试失败。"""

    def run_suite(self, m, lens):
        loc = bench.run_suite(m.url + "/v1/chat/completions", "m", suite="quick", outdir=temp_dir(),
                              conc_ladder=[1], matrix_conc=2, lens=lens, retry_pause_s=0)
        return load_json(loc)

    def test_probe_env_reads_max_model_len(self):
        m = limited_server(5000, True)
        try:
            env = bench.probe_env(m.url, {}, "m")
        finally:
            m.close()
        self.assertEqual((env["models_visible"], env["max_model_len"]), (["m", "other"], 5000))

    def test_known_limit_skips_tiers_up_front(self):
        m = limited_server(5000, True)
        try:
            doc = self.run_suite(m, [1, 4, 8])
            posts = [c[2] for c in m.calls if c[0] == "POST"]
        finally:
            m.close()
        self.assertEqual(doc["status"], "done")
        for pid in ("prefill", "prefill_conc"):
            ph = next(p for p in doc["phases"] if p["id"] == pid)
            self.assertEqual([p["label"] for p in ph["points"]], ["1K", "4K"])
        self.assertEqual(sorted((s["phase"], s["label"]) for s in doc["length_skips"]),
                         [("prefill", "8K"), ("prefill_conc", "8K")])
        self.assertIn("最大上下文（5000 token）", doc["length_skips"][0]["reason"])
        self.assertTrue(all(fake_tokens(b) + int(b.get("max_tokens") or 0) <= 5000 for b in posts))  # 一个超长请求都没发

    def test_unknown_limit_skips_when_server_refuses(self):
        m = limited_server(5000, False)
        try:
            doc = self.run_suite(m, [1, 4, 8, 16])
        finally:
            m.close()
        self.assertEqual(doc["status"], "done")
        self.assertNotIn("max_model_len", doc["env"])
        pc = next(p for p in doc["phases"] if p["id"] == "prefill_conc")
        self.assertEqual([p["label"] for p in pc["points"]], ["1K", "4K"])
        self.assertTrue(all(not p.get("failed_attempts") for p in pc["points"]))    # 超长不整格重跑
        got = sorted((s["phase"], s["label"]) for s in doc["length_skips"])
        self.assertEqual(got, [("prefill", "16K"), ("prefill", "8K"), ("prefill_conc", "16K"), ("prefill_conc", "8K")])
        self.assertIn("maximum context length is 5000", doc["length_skips"][0]["reason"])

    def test_longctx_skipped_not_failed(self):
        m = limited_server(5000, False)
        try:
            cal = bench.calibrate_prompt(m.url + "/v1/chat/completions", {}, "m")
            ph = bench.phase_longctx(m.url + "/v1/chat/completions", {}, "m", 32768, 256, cal)
        finally:
            m.close()
        self.assertEqual(ph["points"], [])
        self.assertEqual(ph["skipped"][0]["label"], "32K")

    def test_other_http_errors_still_fail(self):
        m = MockServer(lambda method, path, body: (400, {"error": {"message": "invalid model name"}}, None))
        try:
            with self.assertRaises(Exception):
                bench.phase_prefill(m.url + "/v1/chat/completions", {}, "m", [("1K", 13, 1000)], 8, 1)
        finally:
            m.close()


if __name__ == "__main__":
    unittest.main()
