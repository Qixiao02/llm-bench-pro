# -*- coding: utf-8 -*-
"""离线 HTML 报告的内容级校验: 自包含性/转义/SVG 完整性/章节结构/AB 对比/数值落位。

report.py 的输出是直接落盘给用户离线打开的单文件, 任何外部依赖或未转义注入都是缺陷,
这里按"交付物"标准断言, 而不是只冒烟一个 200。
"""
import re
import unittest

from _util import temp_dir  # noqa: F401  (副作用: 把包目录注入 sys.path)
import report
from test_store import iq_doc, perf_doc

SVG_NS = "http://www.w3.org/2000/svg"


def rich_doc(run_id="run_20260101_000000_a", model="model-a", agg=1000.0, ttft=0.5):
    """覆盖全部章节的合成 run: 并发(含重跑披露)/解码/场景 json+rag/回放闭环/开环。"""
    doc = perf_doc(run_id)
    doc["model"] = model
    doc["phases"] += [
        {"id": "concurrency", "points": [
            {"conc": 1, "total": 4, "ok": 4, "fail": 0, "agg_tps": agg, "per_stream_tps_med": agg,
             "ttft_p50_s": .1, "ttft_p95_s": ttft},
            {"conc": 4, "total": 8, "ok": 7, "fail": 1, "agg_tps": agg * 2, "per_stream_tps_med": agg / 2,
             "ttft_p50_s": .2, "ttft_p95_s": ttft * 2, "attempts": 2,
             "failed_attempts": [{"attempt": 1, "ok": 5, "fail": 3, "errors": ["ConnectionError: boom <x>"]}]},
        ]},
        {"id": "decode", "cases": [{"lang": "zh", "out_tokens": 256, "decode_tps_med": 55.5,
                                    "decode_tps_best": 61.2, "itl_p50_ms_med": 18.1,
                                    "itl_p95_ms": 40.0, "spec_burst_med": 1.0}]},
        {"id": "scn_json", "task": {"tpl": "json", "label": "结构化抽取", "validator": "json",
                                    "max_tokens": 256, "requests_per_worker": 3},
         "points": [{"conc": 2, "total": 6, "ok": 6, "fail": 0, "req_s": 1.5, "ttft_p95_s": .4,
                     "e2e_p95_s": 1.2, "out_tokens_avg": 180.0,
                     "json_total": 6, "json_ok": 5, "json_rate": 0.833, "attempts": 2}]},
        {"id": "scn_rag", "task": {"tpl": "rag", "label": "RAG 问答", "validator": None,
                                   "max_tokens": 512, "requests_per_worker": 3},
         "points": [{"conc": 2, "ctx_tokens": 4000, "total": 6, "ok": 6, "fail": 0, "req_s": 1.1,
                     "ttft_p95_s": .6, "e2e_p95_s": 2.0, "out_tokens_avg": 260.0, "out_tokens_p90": 300.0},
                    {"conc": 2, "ctx_tokens": 16000, "total": 6, "ok": 5, "fail": 1, "req_s": .8,
                     "ttft_p95_s": .9, "e2e_p95_s": 3.0, "out_tokens_avg": 240.0}]},
        {"id": "replay", "pool": {"size": 30, "skipped": 1, "bad": 0, "wrapped": False},
         "points": [{"conc": 8, "total": 16, "ok": 15, "fail": 1, "req_s": 2.4, "ttft_p95_s": .9,
                     "e2e_p95_s": 2.5, "prompt_tokens_avg": 800, "out_tokens_avg": 200,
                     "max_inflight": 8, "pool_wrapped": False}]},
        {"id": "openloop", "duration_s": 60, "points": [{"rate": 2.0, "sent": 121, "shed": 3, "total": 118,
                        "ok": 115, "fail": 3, "completed_rps": 1.9, "max_inflight": 24,
                        "ttft_p95_s": 1.1, "e2e_p95_s": 3.0,
                        "inflight_ts": [[0.0, 0], [1.0, 4], [2.0, 9], [3.0, 7]]}]},
    ]
    return doc


class TestReportContract(unittest.TestCase):
    def setUp(self):
        self.a = rich_doc()
        self.b = rich_doc("run_20260101_000500_b", model="model-b", agg=1180.0, ttft=0.35)
        self.html = report.render(self.a, self.b)

    def test_rejects_non_perf_doc(self):
        with self.assertRaises(ValueError):
            report.render(iq_doc())

    def test_self_contained_offline(self):
        h = self.html
        self.assertNotIn("<script", h)          # 无脚本
        self.assertNotIn("<link", h)            # 无外链样式
        self.assertNotIn(" src=", h)            # 无外部资源加载
        urls = set(re.findall(r"https?://[^\"'<>\s]+", h))
        self.assertEqual(urls, {SVG_NS})        # 唯一允许的 URL: svg 命名空间

    def test_html_escaping_everywhere(self):
        a = rich_doc(model='<b>M&X</b>"on')
        a["tag"] = 'tag"<i>'
        a["phases"][0]["points"][0]["label"] = "1K<script>"
        h = report.render(a)
        for raw in ("<b>M&X", "on\"", '<i>', "<script>"):
            self.assertNotIn(raw, h, "未转义注入: %r" % raw)
        self.assertIn("&lt;b&gt;M&amp;X&lt;/b&gt;&quot;on", h)      # 标题/图例/元信息表
        self.assertIn("tag&quot;&lt;i&gt;", h)                      # 徽章
        self.assertIn("1K&lt;script&gt;", h)                        # 轴标签

    def test_svg_integrity(self):
        h = self.html
        opens, closes = h.count("<svg"), h.count("</svg>")
        self.assertGreaterEqual(opens, 3)                          # 并发 + prefill + 开环在途
        self.assertEqual(opens, closes)
        ds = re.findall(r'<path d="([^"]*)"', h)
        self.assertTrue(ds)
        for d in ds:
            self.assertRegex(d, r"^M[\d.]")                        # 路径必须从 M 开始且非空
        for seg in d.split(" "):
            self.assertRegex(seg, r"^([ML][\d.]+,[\d.]+|Z)$")
        for cx, cy in re.findall(r'<circle cx="([\d.]+)" cy="([\d.]+)"', h):
            self.assertLessEqual(float(cx), 780.0 + .01)
            self.assertGreaterEqual(float(cy), 0)

    def test_sections_present(self):
        for sec in ("结论要点", "并发阶梯", "Prefill 阶梯", "单流解码", "场景 · 结构化抽取",
                    "场景 · RAG 问答", "真实请求回放 · 闭环", "真实请求回放 · 开环",
                    "失败与重跑披露", "测量口径"):
            self.assertIn(sec, self.html)

    def test_ab_compare_semantics(self):
        h = self.html
        self.assertIn("A/B 对比", h)
        self.assertIn("A: model-a", h)
        self.assertIn("B: model-b", h)
        # A=1000 vs B=1180 → A 相对 B 为 -15.3%
        self.assertIn("(-15.3%)", h)
        # KPI 双值同格
        self.assertIn("1000.0 / 1180.0", h)

    def test_single_run_no_ab(self):
        h = report.render(self.a)
        self.assertNotIn("A/B 对比", h)
        self.assertNotIn("B: ", h)
        self.assertNotIn("A: ", h)

    def test_retry_and_scenario_disclosure(self):
        h = self.html
        self.assertIn("重跑×2", h)                                # attempts>1 的场景格披露徽章
        self.assertIn("boom &lt;x&gt;", h)                       # 错误样本转义
        self.assertIn("JSON 合法", h)                             # validator=json 才有该列
        self.assertIn("5 (83%)", h)                              # 5/6 合法
        self.assertIn("上下文 tokens", h)                         # rag 按上下文分档
        self.assertIn("回放池 30 条(跳过 1, 坏行 0)", h)
        self.assertIn("<td>Bconcurrency</td>", h)                # B 运行的重试行必须标 B

    def test_numbers_rendered(self):
        h = self.html
        self.assertIn("55.5", h)            # 解码吞吐
        self.assertIn("121", h)             # 开环发送
        self.assertIn("24", h)              # 开环最大在途
        self.assertIn("在途请求时间线", h)
        self.assertIn("目标 2", h)          # 完成速率 vs 目标

    def test_footer_meta(self):
        h = self.html
        self.assertIn(report.APP_VERSION, h)
        self.assertIn("报告生成 v%s" % report.REPORT_VERSION, h)
        self.assertIn("自包含", h)


if __name__ == "__main__":
    unittest.main()
