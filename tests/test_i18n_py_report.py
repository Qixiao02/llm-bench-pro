# -*- coding: utf-8 -*-
"""旧版速度测试 HTML 报告 (llm_bench_pro/report.py, GET /api/report) 的中英文测试。约定见 CONTRIBUTING.md「服务端消息与翻译」。

报告是一个自包含的 HTML 文件: 页面上的文字、表头、图表说明、结论、方法说明、页脚都按当前语言生成。
这里每个句子都配一对断言: 中文和转换前逐字一致, 英文是词典里的原句、页面里没有汉字 (模型名等数据除外)。
带数量的句子 (整格重跑几格、几个请求失败、丢弃几个请求、回放池几条、图片池几张) 测 0 / 1 / 多。
"""
import html as html_lib
import http.client
import re
import unittest
from unittest import mock

from _util import temp_dir  # noqa: F401  (副作用: 设 LLM_BENCH_LANG=zh, 把包目录注入 sys.path)
import bench
import i18n
import report
import sinks
import test_i18n_py as base   # 只当模块引用, 不 from-import 里面的 TestCase (免得被重复收集)
import test_report
from test_store import iq_doc, perf_doc


def visible(html):
    """页面上的文字: 去掉 <script> 和 <style> 的内容 (SVG 里的 <text> 保留)。"""
    html = re.sub(r"(?is)<script\b.*?</script>", "", html)
    return re.sub(r"(?is)<style\b.*?</style>", "", html)


def in_lang(lang, fn, *args, **kw):
    with i18n.use_lang(lang):
        return fn(*args, **kw)


def li_texts(html):
    return re.findall(r"<li>(.*?)</li>", html, re.S)


def doc_of(*phases, **kw):
    doc = perf_doc()
    doc["model"] = "m"
    doc["phases"] = list(phases)
    doc.update(kw)
    return doc


def conc_phase(*points):
    return {"id": "concurrency", "points": list(points)}


def cpt(conc, agg=100.0, ttft=0.5, **kw):
    p = {"conc": conc, "total": 4, "ok": 4, "fail": 0, "agg_tps": agg, "per_stream_tps_med": agg / max(conc, 1),
         "ttft_p95_s": ttft}
    p.update(kw)
    return p


def scn_phase(tpl, label, points=None, **task):
    t = {"tpl": tpl, "label": label, "validator": "json" if tpl == "json" else None, "max_tokens": 256,
         "requests_per_worker": 2}
    t.update(task)
    pts = points if points is not None else [{"conc": 2, "total": 4, "ok": 4, "fail": 0, "req_s": 1.0, "ttft_p95_s": .4,
                                            "e2e_p95_s": 1.2, "out_tokens_avg": 100.0}]
    return {"id": "scn_" + tpl, "task": t, "points": pts}


def open_phase(rate=2.0, done=1.0, shed=0, ts=None, duration=60):
    return {"id": "openloop", "duration_s": duration, "points": [
        {"rate": rate, "sent": 121, "shed": shed, "total": 118, "ok": 115, "fail": 3, "completed_rps": done,
         "max_inflight": 24, "ttft_p95_s": 1.1, "e2e_p95_s": 3.0, "inflight_ts": ts if ts is not None else [[0.0, 1], [1.0, 4]]}]}


class ReportCase(base.LangCase):
    """每个用例前后清干净语言状态; 提供 zh / en 两种语言下同一个入口的对照断言。"""

    def pair(self, fn, zh, en, *args, **kw):
        """fn 在中文下返回含 zh 的文字 (和转换前逐字一致), 在英文下返回含 en 的文字, 英文里没有汉字。"""
        got_zh = in_lang("zh", fn, *args, **kw)
        got_en = in_lang("en", fn, *args, **kw)
        self.assertIn(zh, got_zh)
        self.assertIn(en, got_en)
        base.assert_english(self, visible(got_en), what="report")
        self.assertEqual(i18n.MISSING, set())
        return got_zh, got_en


# ================================================================ 整个页面

class TestReportPage(ReportCase):
    def setUp(self):
        super().setUp()
        self.a = test_report.rich_doc()
        self.b = test_report.rich_doc("run_20260101_000500_b", model="model-b", agg=1180.0, ttft=0.35)

    def test_chinese_is_the_default_and_the_lang_argument_matches_use_lang(self):
        default = report.render(self.a, self.b)
        self.assertEqual(default, report.render(self.a, self.b, lang="zh"))
        self.assertEqual(default, in_lang("zh", report.render, self.a, self.b))
        self.assertIn('<html lang="zh-CN">', default)
        self.assertEqual(report.render(self.a, self.b, lang="en"), in_lang("en", report.render, self.a, self.b))

    def test_lang_argument_only_applies_to_that_call(self):
        with i18n.use_lang("zh"):
            en = report.render(self.a, lang="en")
            self.assertEqual(i18n.current_lang(), "zh")           # 出来之后语言还是原来的
            self.assertIn('<html lang="en">', en)
        with i18n.use_lang("en"):
            self.assertIn('<html lang="en">', report.render(self.a))               # 不传 lang: 用当前语言
            self.assertIn('<html lang="zh-CN">', report.render(self.a, lang="zh"))
            self.assertEqual(i18n.current_lang(), "en")

    def test_english_page_has_no_chinese_and_no_missing_dictionary_keys(self):
        for name, args in (("single", (self.a,)), ("A/B", (self.a, self.b)), ("B/A", (self.b, self.a)),
                           ("empty", ({"run_id": "run_x", "model": "m", "phases": []},))):
            with self.subTest(name):
                with base.english_flow() as flow:
                    html = report.render(*args)
                flow.assert_clean(self)
                base.assert_english(self, visible(html), what=name)
                self.assertIn('<html lang="en">', html)

    def test_english_page_headings_and_tables(self):
        html = html_lib.unescape(report.render(self.a, self.b, lang="en"))
        for want in ("Key findings", "Concurrency ladder", "Prefill ladder", "Single-stream decode",
                     "Scenario · JSON extraction", "Scenario · Document Q&A", "Real-request replay · closed-loop",
                     "Real-request replay · open-loop (Poisson arrivals)", "Failures and reruns", "Methodology",
                     "<th>Concurrency</th>", "<th>Aggregate throughput tok/s</th>", "<th>Per-stream throughput tok/s</th>",
                     "<th>Input length</th>", "<th>Prefill throughput tok/s (A / B)</th>", "<th>E2E p95 s</th>",
                     "<th>JSON valid</th>", "<th>Context tokens</th>", "<th>Rate req/s</th>", "<th>Error sample</th>",
                     "<th>Start time (UTC)</th>", "Suite: quick", "Framework: vLLM", "Framework version: 1", "Tag: t",
                     "Rerun ×2"):
            self.assertIn(want, html)
        for gone in ("结论要点", "并发阶梯", "测量口径", "重跑×", "场景 ·"):
            self.assertNotIn(gone, html)

    def test_title_and_chart_text(self):
        zh, en = in_lang("zh", report.render, self.a, self.b), in_lang("en", report.render, self.a, self.b)
        self.assertIn("<title>model-a 压测报告 · A/B 对比 · t</title>", zh)
        self.assertIn("<h1>model-a 压测报告 · A/B 对比 · t</h1>", zh)
        self.assertIn("<title>model-a speed test report · A/B comparison · t</title>", en)
        self.assertIn("<h1>model-a speed test report · A/B comparison · t</h1>", en)
        self.assertNotIn("A/B", in_lang("en", report.render, self.a))          # 单次测试的标题没有对比后缀
        self.assertIn("<title>model-a speed test report · t</title>", in_lang("en", report.render, self.a))
        self.assertIn(">时间 (s)</text>", zh)                                   # 在途时间线 SVG 里的横轴说明
        self.assertIn(">Time (s)</text>", en)

    def test_non_perf_documents_are_rejected_in_the_current_language(self):
        for lang, want in (("zh", "仅支持性能测试运行 (run_*) 的报告"),
                           ("en", "Reports are only available for speed test runs (run_*)")):
            with self.subTest(lang=lang), self.assertRaises(ValueError) as cm:
                report.render(iq_doc(), lang=lang)
            self.assertEqual(str(cm.exception), want)
        with i18n.use_lang("en"), self.assertRaises(ValueError) as cm:
            report.render({"run_id": "run_x", "phases": "no"})
        base.assert_english(self, str(cm.exception))

    def test_user_data_stays_escaped_and_is_never_used_as_a_template(self):
        """模型名、标签是数据: 转义后原样出现; 里面的 {…} 不会被当成占位符。英文模式同样。"""
        a = test_report.rich_doc(model='<b>M&X</b>{0}{x:>5}"on')
        a["tag"] = 'tag"<i>{name}'
        for lang, title in (("zh", "&lt;b&gt;M&amp;X&lt;/b&gt;{0}{x:&gt;5}&quot;on 压测报告"),
                            ("en", "&lt;b&gt;M&amp;X&lt;/b&gt;{0}{x:&gt;5}&quot;on speed test report")):
            with self.subTest(lang=lang):
                html = report.render(a, lang=lang)
                self.assertIn("<title>%s · tag&quot;&lt;i&gt;{name}</title>" % title, html)
                self.assertNotIn("<b>M&X", html)
                self.assertNotIn("<i>", html)
        # A/B 结论里的模型名: 原样带进句子 (和以前一样不转义, 这里只确认花括号不被当成模板)
        b = test_report.rich_doc("run_20260101_000500_b", model="m{0}{name}", agg=1180.0, ttft=0.35)
        a2 = test_report.rich_doc(model="m{x}")
        for lang in ("zh", "en"):
            texts = li_texts(in_lang(lang, report._findings, [a2, b]))
            self.assertTrue(any("B (m{0}{name})" in x for x in texts), (lang, texts))
        self.assertEqual(i18n.MISSING, set())


# ================================================================ 每一句的中英文对照

class TestReportSentences(ReportCase):
    def test_kpi_labels(self):
        doc = test_report.rich_doc()
        self.pair(report._kpi_cards, "最高并发聚合吞吐", "Aggregate throughput at max concurrency", [doc])
        for zh, en in (("单流解码吞吐", "Single-stream decode throughput"), ("最高并发 TTFT p95", "TTFT p95 at max concurrency"),
                       ("Prefill 吞吐(峰值中位)", "Prefill throughput (peak median)")):
            self.pair(report._kpi_cards, zh, en, [doc])

    def test_ab_findings_higher_and_lower(self):
        a = test_report.rich_doc()
        b = test_report.rich_doc("run_20260101_000500_b", model="model-b", agg=1180.0, ttft=0.35)
        # A 的总吞吐比 B 低: B 更高; A 的首字等待比 B 高: B 更低
        self.pair(report._findings, "并发 4 下聚合吞吐: B (model-b) 更高 15.3%（2000.0 vs 2360.0 tok/s）",
                  "Aggregate throughput at concurrency 4: B (model-b) is 15.3% higher (2000.0 vs 2360.0 tok/s).", [a, b])
        self.pair(report._findings, "并发 4 下 TTFT p95: B (model-b) 更低 42.9%（1.0 vs 0.7 s）",
                  "TTFT p95 at concurrency 4: B (model-b) is 42.9% lower (1.0 vs 0.7 s).", [a, b])
        # 反过来: A 更高、A 更低
        self.pair(report._findings, "并发 4 下聚合吞吐: A (model-b) 更高 18.0%（2360.0 vs 2000.0 tok/s）",
                  "Aggregate throughput at concurrency 4: A (model-b) is 18.0% higher (2360.0 vs 2000.0 tok/s).", [b, a])
        self.pair(report._findings, "并发 4 下 TTFT p95: A (model-b) 更低 30.0%（0.7 vs 1.0 s）",
                  "TTFT p95 at concurrency 4: A (model-b) is 30.0% lower (0.7 vs 1.0 s).", [b, a])

    def test_fixed_output_warnings(self):
        a = doc_of(conc_phase(cpt(1)), overrides={"fixed_output": False})
        b = doc_of(conc_phase(cpt(1)), overrides={"fixed_output": True})
        self.pair(report._findings, "⚠ 两次运行的固定输出长度(ignore_eos)设置不一致, 吞吐不可直接比较",
                  "⚠ The two runs used different fixed-output-length (ignore_eos) settings, so their throughput cannot be "
                  "compared directly.", [a, b])
        self.pair(report._findings, "⚠ 本次运行未固定输出长度(端点不支持 ignore_eos), 模型提前结束时吞吐会偏低, 跨后端对比需注意口径",
                  "⚠ This run did not fix the output length (the endpoint does not support ignore_eos). Throughput reads low "
                  "when the model stops early, so be careful when comparing across backends.", [a])
        # 固定了输出长度的单次测试: 没有这条
        self.assertNotIn("ignore_eos", in_lang("en", report._findings, [b]))

    def test_rerun_and_failure_counts_singular_and_plural(self):
        def doc(retry_cells, fails):
            pts = [cpt(c, attempts=2) for c in range(1, retry_cells + 1)]
            if fails:
                pts.append(cpt(99, fail=fails, ok=4 - min(fails, 4)))
            return doc_of(conc_phase(*pts))
        rerun = "整格重跑(明细见「失败与重跑」)"
        for n, en in ((1, "1 cell had failures, so the whole cell was rerun (see \"Failures and reruns\" for details)."),
                      (3, "3 cells had failures, so each whole cell was rerun (see \"Failures and reruns\" for details).")):
            self.pair(report._findings, "%d 个格子失败后%s" % (n, rerun), en, [doc(n, 0)])
        for n, en in ((1, "1 request failed in total (counted in the failure rate, not removed from the results)."),
                      (5, "5 requests failed in total (counted in the failure rate, not removed from the results).")):
            self.pair(report._findings, "共 %d 个请求失败(已计入失败率, 未从结果中剔除)" % n, en, [doc(0, n)])
        # 没有重跑也没有失败: 这两句都不出现
        for lang in ("zh", "en"):
            clean = in_lang(lang, report._findings, [doc_of(conc_phase(cpt(1)))])
            self.assertEqual(len(li_texts(clean)), 1)

    def test_nothing_to_report(self):
        self.pair(report._findings, "未发现需要关注的异常; 各阶段请求全部成功",
                  "No anomalies found; all requests succeeded in every phase.", [doc_of()])

    def test_json_validity_finding_uses_the_scenario_name_of_the_current_language(self):
        bad = [{"conc": 2, "total": 6, "ok": 6, "fail": 0, "json_total": 6, "json_ok": 3, "json_rate": 0.5}]
        doc = doc_of(scn_phase("json", "结构化抽取", bad))
        self.pair(report._findings, "⚠ 场景「结构化抽取」JSON 合法率最低 50% (并发 2): 结构化输出稳定性需关注",
                  "⚠ Scenario \"JSON extraction\" has a JSON validity rate as low as 50% (concurrency 2); "
                  "structured-output stability needs attention.", [doc])
        custom = doc_of(scn_phase("json", "我的场景", bad))       # 用户自己起的名字: 原样 (它是数据)
        self.assertIn("⚠ 场景「我的场景」JSON 合法率最低 50%", in_lang("zh", report._findings, [custom]))
        self.assertIn('⚠ Scenario "我的场景" has a JSON validity rate', in_lang("en", report._findings, [custom]))
        ok = [{"conc": 2, "total": 6, "ok": 6, "fail": 0, "json_total": 6, "json_ok": 6, "json_rate": 1.0}]
        for lang in ("zh", "en"):
            self.assertNotIn("JSON", in_lang(lang, report._findings, [doc_of(scn_phase("json", "结构化抽取", ok))]))

    def test_open_loop_findings_and_drop_counts(self):
        self.pair(report._findings, "⚠ 开环速率 2 req/s 下只完成 1 req/s (最大在途 24): 到达速率已超过服务能力, 请求越排越长",
                  "⚠ At an open-loop rate of 2 req/s only 1 req/s completed (max in-flight 24): the arrival rate exceeds "
                  "what the service can handle, so requests queue up longer and longer.", [doc_of(open_phase(2.0, 1.0))])
        for shed, zh, en in ((1, "⚠ 开环速率 2 有 1 个请求因在途超限(128)被丢弃计数",
                              "⚠ At open-loop rate 2, 1 request was dropped and counted because it exceeded the in-flight limit (128)."),
                             (4, "⚠ 开环速率 2 有 4 个请求因在途超限(128)被丢弃计数",
                              "⚠ At open-loop rate 2, 4 requests were dropped and counted because they exceeded the in-flight limit (128).")):
            self.pair(report._findings, zh, en, [doc_of(open_phase(2.0, 2.0, shed=shed))])
        # 完成速率接近目标、没有丢弃: 没有结论
        for lang in ("zh", "en"):
            self.assertEqual(len(li_texts(in_lang(lang, report._findings, [doc_of(open_phase(2.0, 1.9))]))), 1)

    def test_replay_pool_wrapped(self):
        doc = doc_of(replay={"wrapped": True})
        self.pair(report._findings, "回放池已回绕: 部分请求被重复发送, 若端点前缀缓存跨格生效, 后段吞吐可能偏高",
                  "The replay pool wrapped around: some requests were sent more than once, so if the endpoint's prefix "
                  "cache persists across cells, throughput in later cells may read high.", [doc])

    def test_length_label_for_old_results(self):
        for pt, zh, en in (({"label": "8K", "in_tokens": 3600}, "3.6K（原标 8K）", "3.6K (nominal 8K)"),
                           ({"label": "200K", "in_tokens": 99999}, "100K（原标 200K）", "100K (nominal 200K)"),
                           ({"label": "512K", "in_tokens": 250000}, "250K（原标 512K）", "250K (nominal 512K)"),
                           ({"label": "8K", "in_tokens": 8100}, "8K", "8K"),            # 差不到 10%: 原样
                           ({"label": "weird", "in_tokens": 5}, "weird", "weird")):
            self.assertEqual(in_lang("zh", report._len_label, pt), zh)
            self.assertEqual(in_lang("en", report._len_label, pt), en)
        doc = doc_of({"id": "prefill", "points": [{"label": "8K", "in_tokens": 3600, "prefill_tps_med": 5200.0}]})
        self.pair(report._prefill_sec, "3.6K（原标 8K）", "3.6K (nominal 8K)", [doc])      # 表格行和图的横轴标签都是它

    def test_empty_states(self):
        self.assertEqual(in_lang("zh", report.svg_area, [], []), '<p class="muted">无在途采样数据</p>')
        self.assertEqual(in_lang("en", report.svg_area, [], []), '<p class="muted">No in-flight samples</p>')
        self.assertIn('class="muted">无数据</td>', in_lang("zh", report._tbl, ["a", "b"], []))
        self.assertIn('class="muted">No data</td>', in_lang("en", report._tbl, ["a", "b"], []))
        self.assertIn(">时间 (s)</text>", in_lang("zh", report.svg_area, ["0", "1"], [1, 2]))
        self.assertIn(">Time (s)</text>", in_lang("en", report.svg_area, ["0", "1"], [1, 2]))
        # 只有阶段、没有数据点的报告也能出 (每张表都是「无数据」)
        doc = doc_of({"id": "prefill", "points": []}, {"id": "concurrency", "points": []})
        self.pair(report.render, "无数据", "No data", doc)

    def test_decode_language_names(self):
        cases = [{"lang": lang, "out_tokens": 256, "decode_tps_med": 55.5} for lang in ("zh", "en", "fr")]
        doc = doc_of({"id": "decode", "cases": cases})
        zh, en = self.pair(report._decode_sec, "<td>中文</td>", "<td>Chinese</td>", [doc])
        self.assertIn("<td>英文</td>", zh)
        self.assertIn("<td>English</td>", en)
        self.assertIn("<td>fr</td>", zh)
        self.assertIn("<td>fr</td>", en)                       # 不认识的语言代码原样
        self.assertIn("<th>Spec burst tok/chunk</th>", en)
        self.pair(report._decode_sec, "spec_burst > 1 提示投机采样生效(每 chunk 平均 token 数)",
                  "spec_burst > 1 means speculative decoding is active (average tokens per chunk)", [doc])

    def test_concurrency_notes_depend_on_fixed_output(self):
        fixed, loose = doc_of(conc_phase(cpt(1))), doc_of(conc_phase(cpt(1)), overrides={"fixed_output": False})
        head_zh, head_en = "实线=聚合吞吐(左轴), 虚线=TTFT p95(右轴); ", "Solid line = aggregate throughput (left axis), dashed line = TTFT p95 (right axis); "
        self.pair(report._conc_sec, head_zh + "固定输出长度(ignore_eos)保证跨后端可比",
                  head_en + "fixed output length (ignore_eos) keeps results comparable across backends", [fixed])
        self.pair(report._conc_sec, head_zh + "本次未固定输出长度", head_en + "output length was not fixed in this run", [loose])

    def test_matrix_section(self):
        pts = [{"label": "8K", "in_tokens": 8000, "ok": 4, "fail": 0, "ttft_avg_ms": 320.5, "itl_avg_ms": 22.1,
                "prefill_tps_agg": 9800.0, "decode_tps_agg": 210.5, "attempts": 2}]
        doc = doc_of({"id": "prefill_conc", "conc": 4, "points": pts})
        self.pair(report._matrix_sec, "提示词长度 × 并发矩阵 (并发 4)", "Prompt length × concurrency matrix (concurrency 4)", [doc])
        self.pair(report._matrix_sec, '<span class="tag warn">重跑×2</span>', '<span class="tag warn">Rerun ×2</span>', [doc])
        self.pair(report._matrix_sec, "<th>ITL p50 均值 ms</th>", "<th>ITL p50 avg ms</th>", [doc])
        self.pair(report._matrix_sec, "屏障同步起跑; 聚合吞吐 = 该档全部成功请求的 token ÷ 最大单请求耗时",
                  "Barrier-synchronized start; aggregate throughput = tokens of all successful requests in the tier ÷ the "
                  "longest single-request time", [doc])

    def test_scenario_notes(self):
        base_zh = "任务模板: %s · max_tokens 256 · 每并发 2 请求 · 不发送 ignore_eos, 测真实任务行为"
        base_en = "Task template: %s · max_tokens 256 · requests per worker 2 · ignore_eos is not sent, so real task behavior is measured"
        chat = doc_of(scn_phase("chat", "对话问答"))
        zh, en = self.pair(report._scenarios_sec, base_zh % "对话问答", base_en % "Chat Q&amp;A", [chat])   # 说明里的名字要转义
        self.assertIn("场景 · 对话问答", zh)
        self.assertIn("Scenario · Chat Q&A", html_lib.unescape(en))
        # 图片理解: 内置示例图片 / 自己上传的图片, 图片池和跳过的张数 (1 / 多)
        for src, n, skipped, zh, en in (
                ("builtin", 1, 1, "; 图片池 1 张(内置示例图片), 另有 1 张不能用已跳过",
                 "; image pool: 1 image (built-in samples), 1 more unusable image skipped"),
                ("builtin", 6, 0, "; 图片池 6 张(内置示例图片)", "; image pool: 6 images (built-in samples)"),
                ("files", 6, 3, "; 图片池 6 张, 另有 3 张不能用已跳过", "; image pool: 6 images, 3 more unusable images skipped"),
                ("files", 1, 0, "; 图片池 1 张", "; image pool: 1 image"),
                ("files", 0, 0, "; 图片池 0 张", "; image pool: 0 images")):
            task = dict(image_source=src, images=n, images_per_request=2)
            if skipped:
                task["images_skipped"] = skipped
            doc = doc_of(scn_phase("vision", "图片理解", **task))
            got_zh, got_en = self.pair(report._scenarios_sec, " · 图片 2 张/请求" + zh, " · images per request 2" + en, [doc])
            self.assertIn("场景 · 图片理解", got_zh)
            self.assertIn("Scenario · Image Q&A", html_lib.unescape(got_en))
        for size, zh, en in ((1, " · 任务集 1 条", " · task set size 1"), (300, " · 任务集 300 条", " · task set size 300")):
            self.pair(report._scenarios_sec, zh, en, [doc_of(scn_phase("custom", "自定义任务集", pool_size=size))])

    def test_scenario_table_headers(self):
        rag = scn_phase("rag", "RAG 问答", [{"conc": 2, "ctx_tokens": 4000, "total": 6, "ok": 6, "fail": 0, "req_s": 1.1,
                                             "ttft_p95_s": .6, "e2e_p95_s": 2.0, "out_tokens_avg": 260.0,
                                             "out_tokens_p90": 300.0, "json_total": 6, "json_ok": 5, "json_rate": .8,
                                             "attempts": 2}])
        doc = doc_of(rag)
        zh, en = self.pair(report._scenarios_sec, "<th>上下文 tokens</th>", "<th>Context tokens</th>", [doc])
        en = html_lib.unescape(en)
        for want_zh, want_en in (("<th>请求/秒</th>", "<th>Req/s</th>"), ("<th>端到端 p95 s</th>", "<th>E2E p95 s</th>"),
                                 ("<th>输出 tokens 均值–p90</th>", "<th>Out tokens avg–p90</th>"),
                                 ("<th>最大在途</th>", "<th>Max in-flight</th>"), ("<th>JSON 合法</th>", "<th>JSON valid</th>"),
                                 ("5 (80%) <span class=\"tag warn\">重跑×2</span>", "5 (80%) <span class=\"tag warn\">Rerun ×2</span>"),
                                 ("场景 · RAG 问答", "Scenario · Document Q&A")):
            self.assertIn(want_zh, zh)
            self.assertIn(want_en, en)

    def test_replay_section_pool_note_and_wrapped_flag(self):
        note_zh = "回放池 %d 条(跳过 1, 坏行 0); cursor 跨格推进避免重复请求命中前缀缓存"
        note_en = ("Replay pool: %d request%s (skipped 1, bad lines 0); the cursor advances across cells so repeated "
                   "requests do not hit the prefix cache")
        for size, s in ((0, "s"), (1, ""), (30, "s")):
            doc = doc_of({"id": "replay", "pool": {"size": size, "skipped": 1, "bad": 0}, "points": [
                {"conc": 8, "total": 16, "ok": 15, "fail": 1, "req_s": 2.4, "ttft_p95_s": .9, "e2e_p95_s": 2.5,
                 "prompt_tokens_avg": 800, "out_tokens_avg": 200, "max_inflight": 8, "pool_wrapped": size == 1}]})
            zh, en = self.pair(report._replay_sec, note_zh % size, note_en % (size, s), [doc])
            self.assertIn("<td>是</td>" if size == 1 else "<td></td>", zh)
            self.assertIn("<td>Yes</td>" if size == 1 else "<td></td>", en)
        self.pair(report._replay_sec, "真实请求回放 · 闭环", "Real-request replay · closed-loop", [doc])
        self.pair(report._replay_sec, "<th>池回绕</th>", "<th>Pool wrapped</th>", [doc])

    def test_open_loop_section(self):
        doc = doc_of(open_phase(2.0, 1.9, shed=3))
        self.pair(report._openloop_sec, "1.90 / 目标 2", "1.90 / target 2", [doc])
        self.pair(report._openloop_sec, '<h3>在途请求时间线 · 2 req/s <span class="muted">(峰值 24, 曲线持续抬升 = 排队堆积)</span></h3>',
                  '<h3>In-flight request timeline · 2 req/s <span class="muted">(peak 24; a steadily rising curve means '
                  'requests are piling up)</span></h3>', [doc])
        self.pair(report._openloop_sec, "泊松到达持续 60 秒(固定种子, 两次运行到达时间轴相同); 在途上限 128, 超限丢弃并计数",
                  "Poisson arrivals for 60s (fixed seed, so both runs share the same arrival timeline); in-flight limit 128, "
                  "requests over the limit are dropped and counted", [doc])
        self.pair(report._openloop_sec, "真实请求回放 · 开环 (泊松到达)", "Real-request replay · open-loop (Poisson arrivals)", [doc])
        self.pair(report._openloop_sec, "<th>速率 req/s</th><th>发送</th><th>丢弃</th>",
                  "<th>Rate req/s</th><th>Sent</th><th>Dropped</th>", [doc])
        self.pair(report._openloop_sec, "<th>完成 req/s</th><th>最大在途</th>", "<th>Completed req/s</th><th>Max in-flight</th>", [doc])
        # 没有在途采样: 不画时间线
        for lang in ("zh", "en"):
            self.assertNotIn("<h3>", in_lang(lang, report._openloop_sec, [doc_of(open_phase(ts=[]))]))

    def test_retry_disclosure_table(self):
        pt = cpt(4, attempts=2, fail=1, ok=7, errors=["HTTP 500"],
                 failed_attempts=[{"attempt": 1, "ok": 5, "fail": 3, "errors": ["ConnectionError: boom"]}])
        a, b = doc_of(conc_phase(pt)), doc_of(conc_phase(pt), model="m2")
        zh, en = self.pair(report._retry_sec, "<th>运行</th><th>阶段</th><th>尝试</th><th>ok/total</th><th>错误样本</th>",
                           "<th>Run</th><th>Phase</th><th>Attempt</th><th>ok/total</th><th>Error sample</th>", [a, b])
        self.pair(report._retry_sec, "失败与重跑披露", "Failures and reruns", [a, b])
        self.pair(report._retry_sec, "整格重跑: 有失败的格子等 30s 后重跑(最多 3 次), 这里列出每轮失败; 最终结果以最后一轮为准",
                  "Rerun the whole cell: a cell with failures waits 30s and runs again (up to 3 times); every failed round is "
                  "listed here, and the final result comes from the last round", [a, b])
        for html in (zh, en):
            self.assertIn("<td>Bconcurrency</td>", html)             # 两次测试的重跑行分别标 A / B
            self.assertIn("ConnectionError: boom", html)             # 错误样本是数据, 原样
        self.assertEqual(in_lang("en", report._retry_sec, [doc_of(conc_phase(cpt(1)))]), "")   # 没有失败: 整节不出

    def test_meta_badges_and_run_table(self):
        doc = doc_of(suite="quick", framework={"name": "vLLM", "version": "0.9"}, tag="t1", started_utc="2026-01-01T00:00:00+00:00")
        zh, en = self.pair(report._meta_sec, "套件: quick", "Suite: quick", [doc])
        for want_zh, want_en in (("框架: vLLM", "Framework: vLLM"), ("框架版本: 0.9", "Framework version: 0.9"),
                                 ("标签: t1", "Tag: t1"), ("<th>运行</th><th>模型</th><th>开始时间 (UTC)</th>",
                                                          "<th>Run</th><th>Model</th><th>Start time (UTC)</th>")):
            self.assertIn(want_zh, zh)
            self.assertIn(want_en, en)
        self.assertIn("bench: 1.1.0", en)
        self.assertIn("run: ", en)

    def test_methodology_keeps_the_bold_word(self):
        zh, en = in_lang("zh", report._method_sec), in_lang("en", report._method_sec)
        self.assertIn("<h2>测量口径</h2>", zh)
        self.assertIn("<h2>Methodology</h2>", en)
        self.assertIn("业务/回放场景<b>不</b>发送 ignore_eos", zh)
        self.assertIn("scenario and replay runs do <b>not</b> send ignore_eos", en)
        self.assertEqual((len(li_texts(zh)), len(li_texts(en))), (6, 6))
        self.assertTrue(all(x.endswith(".") for x in li_texts(en)))          # 完整的句子用句号结尾
        base.assert_english(self, visible(en))
        self.assertIn('style="border-left-color:#0E9AB0"', en)               # 结构 (样式) 两种语言一样
        self.assertEqual(re.sub(r"<li>.*?</li>|<h2>.*?</h2>", "", zh, flags=re.S),
                         re.sub(r"<li>.*?</li>|<h2>.*?</h2>", "", en, flags=re.S))

    def test_footer(self):
        fake = type("FakeDT", (report.datetime,), {"now": classmethod(lambda cls, tz=None: report.datetime(2026, 1, 2, 3, 4, tzinfo=tz))})
        doc = test_report.rich_doc()
        with mock.patch.object(report, "datetime", fake):
            zh, en = in_lang("zh", report.render, doc), in_lang("en", report.render, doc)
        self.assertIn("<footer>LLM Bench Pro v%s · 报告生成 v%s · 引擎 v1.1.0 · 生成于 2026-01-02 03:04 (UTC) · 数据与口径详见各节说明; "
                      "本文件自包含, 可离线打开与打印</footer>" % (report.APP_VERSION, report.REPORT_VERSION), zh)
        self.assertIn("<footer>LLM Bench Pro v%s · report generator v%s · engine v1.1.0 · generated 2026-01-02 03:04 (UTC) · see the "
                      "notes in each section for data and methodology; this file is self-contained and can be opened and printed "
                      "offline</footer>" % (report.APP_VERSION, report.REPORT_VERSION), en)


# ================================================================ 场景名

class TestScenarioNames(ReportCase):
    def test_every_builtin_template_has_an_english_name_and_the_chinese_name_is_bench_s_label(self):
        """结果里存的 label 是 bench.SCN_TEMPLATES 的中文原名; 报告在中文下显示原名 (输出不变), 在英文下按场景类型换名字。
        以后 bench 新增 / 改名场景模板, 这里会提醒同步 report._scn_names()。"""
        with i18n.use_lang("zh"):
            zh_names = report._scn_names()
        self.assertEqual(sorted(zh_names), sorted(bench.SCN_TEMPLATES))
        for tpl, spec in bench.SCN_TEMPLATES.items():
            self.assertEqual(zh_names[tpl], spec["label"], tpl)
        with i18n.use_lang("en"):
            en_names = report._scn_names()
        base.assert_english(self, en_names)
        self.assertEqual(en_names, {"chat": "Chat Q&A", "code": "Coding", "json": "JSON extraction", "rag": "Document Q&A",
                                    "vision": "Image Q&A", "custom": "Custom task set"})
        self.assertEqual(i18n.MISSING, set())

    def test_names_that_are_not_the_builtin_label_are_kept_as_they_are(self):
        def label(lang, task, fallback="chat"):
            return in_lang(lang, report._scn_label, {"id": "scn_" + fallback, "task": task}, fallback)
        builtin = {"tpl": "chat", "label": bench.SCN_TEMPLATES["chat"]["label"]}
        self.assertEqual((label("zh", builtin), label("en", builtin)), ("对话问答", "Chat Q&A"))
        for task in ({"tpl": "chat", "label": "我的场景"}, {"tpl": "chat", "label": "Chat Q&A"},
                     {"tpl": "rag", "label": "对话问答"}, {"tpl": ["x"], "label": "对话问答"}):
            with self.subTest(task=task):
                self.assertEqual((label("zh", task), label("en", task)), (task["label"], task["label"]))
        # 没有 label: 用 fallback (场景 id 去掉 scn_); 没有 task: 同样
        self.assertEqual((label("zh", {}, "abc"), label("en", {}, "abc")), ("abc", "abc"))
        self.assertEqual(in_lang("en", report._scn_label, {"id": "scn_chat"}, "chat"), "chat")


# ================================================================ 接口: /api/report 跟随请求头 X-Lang

class TestReportEndpointFollowsXLang(base.LangServerCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.doc = test_report.rich_doc("run_20260930_000000_rpt", model="model-a")
        cls.other = test_report.rich_doc("run_20260930_000100_rpt", model="model-b", agg=1180.0, ttft=0.35)
        cls.iq = iq_doc("iq_20260930_000200_rpt")
        for doc in (cls.doc, cls.other, cls.iq):
            sinks.SqliteSink().save(doc)

    def test_report_page_language(self):
        path = "/api/report?id=" + self.doc["run_id"]
        st, en = self.request("GET", path, lang="en")
        self.assertEqual(st, 200)
        self.assertIn('<html lang="en">', en)
        self.assertIn("Key findings", en)
        base.assert_english(self, visible(en), what=path)
        for kw in ({"lang": "zh"}, {}):                       # 显式中文和不带请求头 (默认中文) 一样
            st, zh = self.request("GET", path, **kw)
            self.assertEqual(st, 200)
            self.assertIn('<html lang="zh-CN">', zh)
            self.assertIn("结论要点", zh)
        st, ab = self.request("GET", "%s&cmp=%s" % (path, self.other["run_id"]), lang="en")
        self.assertEqual(st, 200)
        self.assertIn("A/B comparison", ab)
        self.assertIn("Aggregate throughput at concurrency 4: B (model-b) is 15.3% higher", ab)
        base.assert_english(self, visible(ab), what="A/B")

    def test_the_response_is_still_an_attachment(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        c.request("GET", "/api/report?id=" + self.doc["run_id"], headers={"X-Lang": "en"})
        r = c.getresponse()
        r.read()
        self.assertEqual(r.status, 200)
        self.assertTrue(r.getheader("Content-Type", "").startswith("text/html"))
        self.assertIn("run_20260930_000000_rpt_report.html", r.getheader("Content-Disposition", ""))

    def test_non_perf_run_error_message(self):
        path = "/api/report?id=" + self.iq["run_id"]
        for lang, want in (("en", "Reports are only available for speed test runs (run_*)"),
                           ("zh", "仅支持性能测试运行 (run_*) 的报告"), (None, "仅支持性能测试运行 (run_*) 的报告")):
            with self.subTest(lang=lang):
                st, err = self.error_of("GET", path, lang=lang)
                self.assertEqual(st, 400)
                self.assertIn(want, err)
        base.assert_english(self, self.error_of("GET", path, lang="en")[1])


if __name__ == "__main__":
    unittest.main()
