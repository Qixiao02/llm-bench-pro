# -*- coding: utf-8 -*-
"""题库管理 / 结果存储 / 图片检查 (bankman.py / store.py / vision_assets.py) 的中英文输出。

第二阶段「数据」区域的验收测试, 分四块:
  1. bankman: 下载 / 生成的日志 (带数量的句子单数 / 复数)、各下载途径的错误、抽样不足、命令行 (--help / status / download / build)
  2. 页面上的「更新题集」任务: 请求带 X-Lang 时, 任务日志里的每一行都是对应语言
  3. store: import_json_file 返回的 skipped: / error: 原因 (前缀是协议, 只翻原因)、抛出的错误、命令行
  4. vision_assets: check_image 的 msg (每种 code 和 level)、ImageError、scan_dir
每一块都是: 英文下没有汉字 (english_flow / assert_english), 中文下和转换前逐字一致 (期望的中文照旧代码的 % 写法拼出来)。
"""
import contextlib
import io
import json
import os
import random
import re
import struct
import threading
import time
import unittest
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from _util import temp_dir
import i18n
import bankman
import store
import vision_assets
import test_bankman as tb                        # 借它的本地模拟服务和小数据集 (只用模块里的东西, 不导入它的用例类)
from test_i18n_py import LangServerCase, assert_english, english_flow


def scrub(obj, *paths):
    """把临时路径换成 <dir>: 路径里可能有中文的用户名, 不是我们输出的文字。"""
    if isinstance(obj, str):
        for p in paths:
            obj = obj.replace(p, "<dir>")
        return obj
    if isinstance(obj, (list, tuple)):
        return [scrub(x, *paths) for x in obj]
    if isinstance(obj, dict):
        return dict((k, scrub(v, *paths)) for k, v in obj.items())
    return obj


def run_main(main, argv):
    """跑命令行入口, 返回 (返回值或 SystemExit 的退出码, 标准输出)。"""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            code = main(argv)
        except SystemExit as e:
            code = e.code
    return code, out.getvalue()


# ================================================================ 1. bankman

class _BankEnv(unittest.TestCase):
    """借 tests/test_bankman.py 的 setUp / tearDown: 本地模拟服务 (支持 Range) 和一套很小的「上游数据」,
    把下载地址、数据目录、题库目录都指到本地 / 临时位置。不跑它的用例。"""

    def setUp(self):
        inner = tb.BankmanCase("test_cancel")
        inner.setUp()
        self.addCleanup(inner.tearDown)
        self.fx, self.srv, self.kw = inner.fx, inner.srv, inner.kw
        nap = mock.patch.object(bankman.time, "sleep", lambda s: None)      # HuggingFace 的限流间隔和退避: 测试里不真等
        nap.start()
        self.addCleanup(nap.stop)
        i18n.MISSING.clear()
        self.addCleanup(i18n.set_default_lang, None)                        # main([..., "--lang", "en"]) 会设进程语言

    def scrubbed(self, obj):
        return scrub(obj, bankman.DATASETS, bankman.BANKS)

    def fresh(self):
        """换成新的数据目录和题库目录 (本地什么都没有)。"""
        d = temp_dir()
        bankman.DATASETS, bankman.BANKS = os.path.join(d, "datasets"), os.path.join(d, "banks")


class TestBankmanLogs(_BankEnv):
    def build_en(self, **kw):
        with english_flow() as flow:
            result = bankman.build(log=flow.lines.append, **dict(self.kw, **kw))
        assert_english(self, self.scrubbed(flow.lines), what="build log")
        self.assertEqual(flow.missing, [], "英文词典缺这些键")
        return flow.lines, result

    def build_zh(self, **kw):
        lines = []
        with i18n.use_lang("zh"):
            result = bankman.build(log=lines.append, **dict(self.kw, **kw))
        return lines, result

    def test_first_build_downloads_then_generates(self):
        d = bankman.DATASETS
        lines, (bank, path) = self.build_en()
        self.assertEqual(lines[0], "Download source: ModelScope (China); 6 question sets have no local data yet, downloading them to %s first" % d)
        names = ["GSM8K", "MMLU", "MATH-500", "ARC-Challenge", "HellaSwag", "C-Eval"]
        for i, name in enumerate(names, 1):
            self.assertIn("Progress %d / 6 · %s" % (i - 1, name), lines)
            self.assertIn("  [%d/6] %s: starting download, trying ModelScope (China) first" % (i, name), lines)
            self.assertTrue(any(re.match(r"^      %s: downloaded from ModelScope( OSS)?, \d+\.\d MB, \d+\.\d s$" % re.escape(name), x) for x in lines), name)
        self.assertIn("Progress 6 / 6 · data is local", lines)
        self.assertEqual(lines[-3], "Building the question bank from local data...")
        self.assertEqual(lines[-2], "Generated a new question bank: %s" % bank["bank_id"])
        self.assertRegex(lines[-1], r"^Done: %s, %d questions; downloaded \d+\.\d MB this time, took \d+ s$" % (bank["bank_id"], bank["total"]))
        # 本地数据里记的来源一直是中文名 (和以前存的一样), 不随下载时的语言变: 数据文件要在机器之间拷贝
        self.assertEqual({bankman.load_local(n)["source"] for n in bankman.DATASET_NAMES}, {"魔搭 OSS", "魔搭"})

    def test_first_build_in_chinese_is_unchanged(self):
        d = bankman.DATASETS
        lines, (bank, path) = self.build_zh()
        self.assertEqual(lines[0], "下载源：魔搭（国内）；本地缺少 6 个题集的数据，先下载到 %s" % d)
        self.assertEqual(lines[1], "进度 0 / 6 · GSM8K")
        self.assertEqual(lines[2], "  [1/6] GSM8K：开始下载（魔搭（国内）优先）")
        self.assertRegex(lines[3], r"^      GSM8K：从魔搭 OSS下载完成，\d+\.\d MB，\d+\.\d 秒$")
        self.assertIn("进度 6 / 6 · 数据已在本地", lines)
        self.assertEqual(lines[-3], "从本地数据生成题库…")
        self.assertEqual(lines[-2], "已生成新题库 %s" % bank["bank_id"])
        self.assertRegex(lines[-1], r"^完成：%s，共 %d 题；本次下载 \d+\.\d MB，用时 \d+ 秒$" % (bank["bank_id"], bank["total"]))
        self.assertTrue(any(x.startswith("      MATH-500：从魔搭下载完成，") for x in lines))

    def test_second_build_needs_no_network(self):
        self.build_en()
        lines, (bank, _) = self.build_en()
        self.assertEqual(lines[:3], ["All question set data is already local (%s); no network needed" % bankman.DATASETS,
                                     "Building the question bank from local data...",
                                     "The question bank is identical to the existing %s (same content, same id); nothing new to add" % bank["bank_id"]])
        lines, _ = self.build_zh()
        self.assertEqual(lines[:3], ["全部题集的数据都已在本地（%s），不需要联网" % bankman.DATASETS, "从本地数据生成题库…",
                                     "题库和已有的 %s 完全相同（内容一样，id 一样），不用新增" % bank["bank_id"]])

    def test_counts_use_singular_and_plural(self):
        bankman.download(bankman.Ctx(), only=["gsm8k", "mmlu", "math500", "arc", "hellaswag"])      # 只差 C-Eval
        lines, _ = self.build_en()
        self.assertEqual(lines[0], "Download source: ModelScope (China); 1 question set has no local data yet, downloading it to %s first" % bankman.DATASETS)
        self.assertEqual(lines[1], "Progress 0 / 1 · C-Eval")
        done = "完成：{bank_id}，共 {n} 题；本次下载 {mb:.1f} MB，用时 {secs:.0f} 秒"
        with i18n.use_lang("en"):
            self.assertEqual(i18n.tn(done, 1, bank_id="iq-x", mb=0.04, secs=1.2), "Done: iq-x, 1 question; downloaded 0.0 MB this time, took 1 s")
            self.assertEqual(i18n.tn(done, 0, bank_id="iq-x", mb=1.26, secs=0.4), "Done: iq-x, 0 questions; downloaded 1.3 MB this time, took 0 s")
            self.assertEqual(i18n.tn(done, 1234, bank_id="iq-x", mb=0, secs=61.6), "Done: iq-x, 1234 questions; downloaded 0.0 MB this time, took 62 s")
        self.assertEqual(i18n.MISSING, set())
        with i18n.use_lang("zh"):
            self.assertEqual(i18n.tn(done, 1, bank_id="iq-x", mb=0.04, secs=1.2), "完成：iq-x，共 1 题；本次下载 0.0 MB，用时 1 秒")

    def test_progress_lines_for_the_page_progress_bar(self):
        """页面按 /进度\\s*(\\d+)\\s*\\/\\s*(\\d+)/ 从任务日志里取进度条: 中文日志要一直能被它匹配。
        英文日志是 Progress x / y, 页面的正则要一起认 (前端不在这个区域, 见报告)。"""
        lines, _ = self.build_zh()
        pat = re.compile(r"进度\s*(\d+)\s*\/\s*(\d+)")
        got = [pat.search(x).groups() for x in lines if pat.search(x)]
        self.assertEqual((got[0], got[-1]), (("0", "6"), ("6", "6")))
        self.assertEqual(len(got), 7)
        self.fresh()
        lines, _ = self.build_en()
        pat_en = re.compile(r"Progress\s*(\d+)\s*\/\s*(\d+)")
        got = [pat_en.search(x).groups() for x in lines if pat_en.search(x)]
        self.assertEqual((got[0], got[-1], len(got)), (("0", "6"), ("6", "6"), 7))


class TestBankmanRoutes(_BankEnv):
    def test_falls_back_to_the_next_route(self):
        del self.srv.files["/sail/open_data/gsm8k/test.jsonl"]
        raw = "/gh/openai/grade-school-math/master/grade_school_math/data/test.jsonl"
        self.srv.files["/mirror2/" + self.srv.url + raw] = self.fx["gsm"].encode()      # 只有镜像 2 可用
        host = self.srv.url.replace("http://", "")
        logs = []
        with english_flow() as flow:
            bankman.download(bankman.Ctx(log=logs.append), only=["gsm8k"])
        assert_english(self, logs)
        self.assertEqual(flow.missing, [])
        self.assertEqual(logs[:4], ["Progress 0 / 1 · GSM8K", "  [1/1] GSM8K: starting download, trying ModelScope (China) first",
                                    "      GSM8K: ModelScope OSS unavailable (HTTP Error 404: Not Found), trying the next one",
                                    "      Using %s" % host])
        self.assertRegex(logs[4], r"^      GSM8K: downloaded from GitHub, \d+\.\d MB, \d+\.\d s$")
        self.assertEqual(logs[5], "Progress 1 / 1 · data is local")
        self.assertEqual(bankman.load_local("gsm8k")["source"], "GitHub")

    def test_global_mode_names_the_preferred_source(self):
        logs = []
        with i18n.use_lang("en"):
            bankman.download(bankman.Ctx(log=logs.append, mode="global"), only=["hellaswag"])
        self.assertIn("  [1/1] HellaSwag: starting download, trying GitHub / HuggingFace (overseas) first", logs)
        with i18n.use_lang("zh"):
            bankman.download(bankman.Ctx(log=logs.append, mode="global"), only=["hellaswag"], force=True)
        self.assertIn("  [1/1] HellaSwag：开始下载（GitHub / HuggingFace（海外）优先）", logs)

    def test_all_routes_failed_lists_every_reason(self):
        del self.srv.files["/bj/open_data/hellaswag/hellaswag_val.jsonl"]
        for lang, want in (("en", "All download routes for HellaSwag failed: ModelScope OSS (HTTP Error 404: Not Found); HuggingFace (HTTP Error 404: Not Found)"),
                           ("zh", "HellaSwag 所有下载途径都失败：魔搭 OSS（HTTP Error 404: Not Found）；HuggingFace（HTTP Error 404: Not Found）")):
            with self.subTest(lang=lang):
                logs = []
                with i18n.use_lang(lang):
                    with self.assertRaises(RuntimeError) as cm:
                        bankman.download(bankman.Ctx(log=logs.append), only=["hellaswag"])
                self.assertEqual(str(cm.exception), want)
                if lang == "en":
                    assert_english(self, [str(cm.exception)] + logs)
                    self.assertEqual(logs[-1], "      HellaSwag: HuggingFace unavailable (HTTP Error 404: Not Found), trying the next one")
                else:
                    self.assertEqual(logs[-1], "      HellaSwag：HuggingFace不可用（HTTP Error 404: Not Found），换下一个")

    def test_archive_problems(self):
        partial = tb.make_tar([("data/test/%s_test.csv" % s, self.fx["mmlu_csv"][s].encode()) for s in tb.SUBS_MMLU[:2]])
        self.srv.files["/bj/open_data/mmlu/data.tar"] = partial
        self.srv.files["/sail/open_data/mmlu/data.tar"] = partial
        self.srv.files["/bj/open_data/arc/ARC-V1-Feb2018.zip"] = tb.make_zip([("x/ARC-Challenge/other.jsonl", b"{}\n")])
        self.srv.files["/bj/open_data/c-eval/ceval-exam.zip"] = tb.make_zip(
            [("val/logic_val.csv", "id,question,A,B,C,D,answer,explanation\n1,q,a,b,c,d,A,\n".encode())])
        cases = [("mmlu", "Subjects missing from the archive: high_school_biology, professional_law", "压缩包里缺少科目: high_school_biology, professional_law"),
                 ("arc", "ARC-Challenge-Test.jsonl not found in the archive", "压缩包里没有 ARC-Challenge-Test.jsonl"),
                 ("ceval", "Subjects missing from the archive: law", "压缩包里缺少科目: law")]
        for name, en, zh in cases:
            for lang, want in (("en", en), ("zh", zh)):
                with self.subTest(dataset=name, lang=lang), i18n.use_lang(lang):
                    with self.assertRaises(RuntimeError) as cm:
                        bankman.routes_for(bankman.Ctx(), name)[0][1]()
                    self.assertEqual(str(cm.exception), want)
                    if lang == "en":
                        assert_english(self, str(cm.exception))
        # 各途径的原因带进「所有途径都失败」里 (带途径名: ModelScope OSS / ModelScope OSS (Hangzhou))
        logs = []
        with i18n.use_lang("en"):
            with self.assertRaises(RuntimeError) as cm:
                bankman.first_ok(bankman.Ctx(log=logs.append), "mmlu", bankman.routes_for(bankman.Ctx(), "mmlu"))
        msg = str(cm.exception)
        self.assertTrue(msg.startswith("All download routes for MMLU failed: ModelScope OSS (Subjects missing from the archive: "), msg)
        self.assertIn("; ModelScope OSS (Hangzhou) (Subjects missing", msg)
        assert_english(self, [msg] + logs)

    def test_route_names_follow_the_language(self):
        ctx = bankman.Ctx()
        with i18n.use_lang("en"):
            got = [[label for label, _ in bankman.routes_for(ctx, n)] for n in ("gsm8k", "math500", "mmlu")]
        self.assertEqual(got, [["ModelScope OSS", "GitHub", "HuggingFace"], ["ModelScope", "hf-mirror", "HuggingFace"],
                               ["ModelScope OSS", "ModelScope OSS (Hangzhou)", "hf-mirror", "HuggingFace"]])
        with i18n.use_lang("zh"):
            self.assertEqual([label for label, _ in bankman.routes_for(ctx, "mmlu")][:2], ["魔搭 OSS", "魔搭 OSS（杭州）"])
        self.assertEqual(i18n.MISSING, set())

    def test_github_and_range_errors(self):
        # GitHub 和镜像都连不上: 服务端一律 404
        for lang, want in (("en", "Can't connect to GitHub or any of its mirrors"), ("zh", "GitHub 和它的镜像都连不上")):
            with self.subTest(lang=lang), i18n.use_lang(lang):
                with self.assertRaises(RuntimeError) as cm:
                    bankman.gh_text(bankman.Ctx(), "no/such", "main", "x.txt")
                self.assertEqual(str(cm.exception), want)
        # 测速能通、整个下载却失败
        flaky = _OddServer("flaky")
        self.addCleanup(flaky.close)
        bankman.GH_RAW, bankman.GH_MIRRORS = flaky.url + "/{repo}/{branch}/{path}", [flaky.url + "/m1/{raw}"]
        for lang, want in (("en", "Download from the GitHub mirrors failed: HTTP Error 500: Internal Server Error"),
                           ("zh", "GitHub 镜像下载失败：HTTP Error 500: Internal Server Error")):
            with self.subTest(lang=lang, case="flaky"), i18n.use_lang(lang):
                with self.assertRaises(RuntimeError) as cm:
                    bankman.gh_text(bankman.Ctx(), "r", "b", "p.txt")
                self.assertEqual(str(cm.exception), want)
        # 服务器不认 Range
        plain = _OddServer("norange", body=b"x" * 5000)
        self.addCleanup(plain.close)
        for lang, want in (("en", "The server does not support partial downloads (HTTP Range requests)"), ("zh", "服务器不支持分段下载")):
            with self.subTest(lang=lang, case="range"), i18n.use_lang(lang):
                with self.assertRaises(RuntimeError) as cm:
                    bankman.Ctx().size(plain.url + "/a")
                self.assertEqual(str(cm.exception), want)
                with self.assertRaises(RuntimeError) as cm:
                    bankman.Ctx().get(plain.url + "/a", (9 << 20, (9 << 20) + 10))
                self.assertEqual(str(cm.exception), want)
        self.assertEqual(bankman.Ctx().get(plain.url + "/a", (10, 19)), b"x" * 10)     # 靠前的范围整读后截取: 不报错

    def test_cancel_message(self):
        ev = threading.Event()
        ev.set()
        for lang, want in (("en", "Stopped"), ("zh", "已停止")):
            with self.subTest(lang=lang), i18n.use_lang(lang):
                with self.assertRaises(bankman.Cancelled) as cm:
                    bankman.build(cancel=ev, **self.kw)
                self.assertEqual(str(cm.exception), want)
                with self.assertRaises(bankman.Cancelled) as cm:
                    bankman.Ctx(cancel=ev).check()
                self.assertEqual(str(cm.exception), want)


class TestBankmanErrors(_BankEnv):
    def test_offline_with_missing_data(self):
        d = bankman.DATASETS
        with english_flow() as flow:
            with self.assertRaises(RuntimeError) as cm:
                bankman.build(offline=True, **self.kw)
        self.assertEqual(flow.missing, [])
        self.assertEqual(str(cm.exception), "Offline mode is on, but local data is missing for GSM8K, MMLU, MATH-500, ARC-Challenge, HellaSwag, "
                                            "C-Eval. Update the question sets once on a machine with internet access, then copy %s over." % d)
        assert_english(self, scrub(str(cm.exception), d))
        with i18n.use_lang("zh"):
            with self.assertRaises(RuntimeError) as cm:
                bankman.build(offline=True, **self.kw)
        self.assertEqual(str(cm.exception), "离线模式下本地缺少这些题集的数据：GSM8K、MMLU、MATH-500、ARC-Challenge、HellaSwag、C-Eval。"
                                            "请在能联网的机器上先更新一次题集，再把 %s 拷贝过来" % d)
        bankman.download(bankman.Ctx(), only=["gsm8k", "math500"])                     # 缺的少了: 名单跟着变
        with i18n.use_lang("en"):
            with self.assertRaises(RuntimeError) as cm:
                bankman.build(offline=True, **self.kw)
        self.assertIn("local data is missing for MMLU, ARC-Challenge, HellaSwag, C-Eval.", str(cm.exception))

    def test_sampling_errors_singular_plural_and_chinese(self):
        rng = random.Random(1)
        cases = [(bankman.sample_mmlu, ({}, 8, rng), "MMLU subject anatomy has fewer than 8 valid questions", "MMLU 科目 anatomy 有效题目不足 8 道"),
                 (bankman.sample_mmlu, ({}, 1, rng), "MMLU subject anatomy has fewer than 1 valid question", "MMLU 科目 anatomy 有效题目不足 1 道"),
                 (bankman.sample_ceval, ({}, 4, rng, ["logic"]), "C-Eval subject logic has fewer than 4 valid questions", "C-Eval 科目 logic 有效题目不足 4 道"),
                 (bankman.sample_ceval, ({}, 1, rng, ["law"]), "C-Eval subject law has fewer than 1 valid question", "C-Eval 科目 law 有效题目不足 1 道")]
        for fn, args, en, zh in cases:
            for lang, want in (("en", en), ("zh", zh)):
                with self.subTest(fn=fn.__name__, n=args[1], lang=lang), i18n.use_lang(lang):
                    with self.assertRaises(RuntimeError) as cm:
                        fn(*args)
                    self.assertEqual(str(cm.exception), want)

    def test_empty_subject_and_missing_bank(self):
        bankman.download(bankman.Ctx(), only=list(bankman.DATASET_NAMES))
        for lang, want in (("en", "Question set ifeval_zh is empty; the question bank was not generated"), ("zh", "题集 ifeval_zh 为空，题库未生成")):
            with self.subTest(lang=lang), i18n.use_lang(lang):
                with self.assertRaises(RuntimeError) as cm:
                    bankman.build(**dict(self.kw, ifeval_n=0))
                self.assertEqual(str(cm.exception), want)
        for lang, want in (("en", "Question bank not found: iq-nope"), ("zh", "题库不存在: iq-nope")):
            with self.subTest(lang=lang, case="load_bank"), i18n.use_lang(lang):
                with self.assertRaises(FileNotFoundError) as cm:
                    bankman.load_bank("iq-nope")
                self.assertEqual(str(cm.exception), want)


class TestBankmanCommandLine(_BankEnv):
    NAMES = ("GSM8K", "MMLU", "MATH-500", "ARC-Challenge", "HellaSwag", "C-Eval")

    def test_status_when_nothing_is_downloaded(self):
        d = bankman.DATASETS
        code, out = run_main(bankman.main, ["status", "--lang", "en"])
        self.assertIsNone(code)
        want = ["%-14s %s  %6d rows  %s" % (n, "missing   ", 0, "") for n in self.NAMES]
        want.append("Local data directory: %s | Can build offline: no" % d)
        self.assertEqual(out.splitlines(), want)
        assert_english(self, scrub(out.splitlines(), d))
        i18n.set_default_lang(None)
        code, out = run_main(bankman.main, ["status", "--lang", "zh"])
        want = ["%-14s %s  %6d 行  %s" % (n, "缺少  ", 0, "") for n in self.NAMES]
        want.append("本地数据目录: %s | 可以离线生成: 否" % d)
        self.assertEqual(out.splitlines(), want)

    def test_status_after_download_shows_the_source_in_the_current_language(self):
        bankman.download(bankman.Ctx())                      # 中文下载: 本地数据里的来源是中文名
        d = bankman.DATASETS

        def rows(name):
            r = bankman.load_local(name)["rows"]
            return sum(len(v) for v in r.values()) if isinstance(r, dict) else len(r)
        stored = {n: bankman.load_local(n)["source"] for n in bankman.DATASET_NAMES}
        self.assertEqual(set(stored.values()), {"魔搭 OSS", "魔搭"})
        en_name = {"魔搭 OSS": "ModelScope OSS", "魔搭": "ModelScope"}
        code, out = run_main(bankman.main, ["status", "--lang", "en"])
        want = ["%-14s %s  %6d rows  %s" % (bankman.DATASET_NAMES[n], "downloaded", rows(n), en_name[stored[n]]) for n in bankman.DATASET_NAMES]
        want.append("Local data directory: %s | Can build offline: yes" % d)
        self.assertEqual(out.splitlines(), want)
        assert_english(self, scrub(out.splitlines(), d))
        i18n.set_default_lang(None)
        code, out = run_main(bankman.main, ["status", "--lang", "zh"])
        want = ["%-14s %s  %6d 行  %s" % (bankman.DATASET_NAMES[n], "已下载", rows(n), stored[n]) for n in bankman.DATASET_NAMES]
        want.append("本地数据目录: %s | 可以离线生成: 是" % d)
        self.assertEqual(out.splitlines(), want)

    def test_source_names_of_local_data(self):
        """本地数据里的来源名 (以前存的和现在存的都是中文名) 按当前语言显示; 认不出的原样。"""
        with i18n.use_lang("en"):
            self.assertEqual([bankman.source_text(x) for x in ("魔搭 OSS", "魔搭", "魔搭 OSS（杭州）", "GitHub", "HuggingFace", "自己拷贝的", "", None)],
                             ["ModelScope OSS", "ModelScope", "ModelScope OSS (Hangzhou)", "GitHub", "HuggingFace", "自己拷贝的", "", None])
            self.assertEqual([bankman.route_key(x) for x in ("ModelScope OSS", "ModelScope", "ModelScope OSS (Hangzhou)", "GitHub", "x")],
                             ["魔搭 OSS", "魔搭", "魔搭 OSS（杭州）", "GitHub", "x"])
            self.assertEqual([bankman.source_text(x) for x in (5, ["魔搭"], {})], [5, ["魔搭"], {}])         # 手改坏的数据 (来源不是文字): 原样返回, 不报错
        with i18n.use_lang("zh"):
            self.assertEqual([bankman.source_text(x) for x in ("魔搭 OSS", "魔搭", "魔搭 OSS（杭州）", "GitHub")], ["魔搭 OSS", "魔搭", "魔搭 OSS（杭州）", "GitHub"])
            self.assertEqual(bankman.route_key("魔搭 OSS"), "魔搭 OSS")
        # local_status 给页面 (/api/datasets) 用: 来源名跟着请求的语言
        os.makedirs(bankman.DATASETS, exist_ok=True)
        with open(os.path.join(bankman.DATASETS, "gsm8k.json"), "w", encoding="utf-8") as f:
            json.dump({"id": "gsm8k", "source": "魔搭 OSS（杭州）", "rows": [{"question": "q", "answer": "#### 1"}]}, f, ensure_ascii=False)
        with i18n.use_lang("en"):
            self.assertEqual(bankman.local_status()["datasets"][0]["source"], "ModelScope OSS (Hangzhou)")
        with i18n.use_lang("zh"):
            self.assertEqual(bankman.local_status()["datasets"][0]["source"], "魔搭 OSS（杭州）")
        self.assertEqual(i18n.MISSING, set())

    def test_source_modes(self):
        """SOURCE_MODES 里只剩取值 (页面接口用它检查 source), 显示名改成 mode_name(): 模块级不能调用翻译。"""
        for mode in ("modelscope", "global"):
            self.assertIn(mode, bankman.SOURCE_MODES)
        self.assertNotIn("other", bankman.SOURCE_MODES)
        self.assertNotIn(["modelscope"], bankman.SOURCE_MODES)      # 不可哈希的也只是「不在里面」, 不报错
        self.assertEqual(bankman.Ctx(mode="other").mode, "modelscope")
        with i18n.use_lang("en"):
            self.assertEqual((bankman.mode_name("modelscope"), bankman.mode_name("global")), ("ModelScope (China)", "GitHub / HuggingFace (overseas)"))
        with i18n.use_lang("zh"):
            self.assertEqual((bankman.mode_name("modelscope"), bankman.mode_name("global")), ("魔搭（国内）", "GitHub / HuggingFace（海外）"))

    def test_download_and_build_commands(self):
        d = bankman.DATASETS
        code, out = run_main(bankman.main, ["download", "--lang", "en"])
        lines = out.splitlines()
        self.assertEqual(lines[0], "Progress 0 / 6 · GSM8K")
        self.assertEqual(lines[-1], "Progress 6 / 6 · data is local")
        assert_english(self, scrub(lines, d))
        i18n.set_default_lang(None)
        code, out = run_main(bankman.main, ["build", "--lang", "en"])
        lines = out.splitlines()
        self.assertEqual(lines[0], "All question set data is already local (%s); no network needed" % d)
        self.assertRegex(lines[-1], r"^built: iq-[0-9a-f]{12} \| total: \d+ => ")             # 这一行本来就是英文, 没有翻译
        assert_english(self, scrub(lines[:-1], d, bankman.BANKS))
        i18n.set_default_lang(None)
        code, out = run_main(bankman.main, ["download", "--lang", "zh"])
        self.assertEqual(out.splitlines()[:2], ["进度 0 / 6 · GSM8K", "  [1/6] GSM8K：本地已有，跳过下载"])
        i18n.set_default_lang(None)
        code, out = run_main(bankman.main, ["download", "--lang", "en", "--force", "--source", "global"])
        self.assertIn("  [1/6] GSM8K: starting download, trying GitHub / HuggingFace (overseas) first", out.splitlines())
        assert_english(self, scrub(out.splitlines(), d))

    def test_command_line_failures(self):
        d = bankman.DATASETS
        code, out = run_main(bankman.main, ["build", "--offline", "--lang", "en"])
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("Failed: Offline mode is on, but local data is missing for GSM8K, MMLU"), out)
        assert_english(self, scrub(out.splitlines(), d))
        i18n.set_default_lang(None)
        code, out = run_main(bankman.main, ["build", "--offline", "--lang", "zh"])
        self.assertEqual((code, out.startswith("失败：离线模式下本地缺少这些题集的数据：GSM8K、MMLU")), (1, True))
        for lang, want in (("en", "Stopped: the data already downloaded is kept locally\n"), ("zh", "已停止：已经下载好的数据留在本地\n")):
            i18n.set_default_lang(None)
            with mock.patch.object(bankman, "build", side_effect=KeyboardInterrupt):
                code, out = run_main(bankman.main, ["build", "--lang", lang])
            self.assertEqual((code, out), (130, want))
        for lang, want in (("en", "Failed: disk full\n"), ("zh", "失败：disk full\n")):
            i18n.set_default_lang(None)
            with mock.patch.object(bankman, "build", side_effect=OSError("disk full")):
                code, out = run_main(bankman.main, ["build", "--lang", lang])
            self.assertEqual((code, out), (1, want))

    def test_help_has_no_chinese_in_english(self):
        code, out = run_main(bankman.main, ["--lang", "en", "--help"])
        self.assertEqual(code, 0)
        assert_english(self, out.splitlines(), what="bankman --help")
        flat = " ".join(out.split())
        for text in ("Question bank for capability tests: download data locally / build the bank from local data",
                     "build = download whatever is missing, then build the bank (default); download = only download the data; status = show the local data",
                     "Preferred download source (default: ModelScope, in China)", "HTTP proxy for downloads, e.g. http://127.0.0.1:7890",
                     "Do not use the network; build only from local data", "With download, re-download all data"):
            self.assertIn(text, flat)
        i18n.set_default_lang(None)
        code, out = run_main(bankman.main, ["--lang", "zh", "--help"])
        flat = " ".join(out.split())
        for text in ("能力评测题库: 下载数据到本地 / 从本地数据生成题库", "build=缺什么下载什么再生成(默认); download=只下载数据; status=看本地数据",
                     "下载源偏好(默认魔搭, 国内)", "下载用的 HTTP 代理, 如 http://127.0.0.1:7890", "不联网, 只用本地数据生成", "download 时重新下载全部数据"):
            self.assertIn(text, flat)


class _OddServer(object):
    """两种不正常的服务: flaky = 带 Range 的请求 (测速) 给数据、整个下载返回 500; norange = 忽略 Range, 一律 200 整个文件。"""

    def __init__(self, mode, body=b"question,answer\n" * 200):
        outer = self
        self.mode, self.body = mode, body

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                rng = self.headers.get("Range")
                if outer.mode == "flaky":
                    if not rng:
                        self.send_response(500)
                        self.end_headers()
                        return
                    self.send_response(206)
                    self.send_header("Content-Range", "bytes 0-1023/%d" % len(outer.body))
                    data = outer.body[:1024]
                else:
                    self.send_response(200)
                    data = outer.body
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


# ================================================================ 2. 「更新题集」任务的日志语言

class TestBankUpdateJobLanguage(LangServerCase):
    """页面点「更新题集」(POST /api/bank-update): 任务日志里的每一行都用发起请求的语言, 之后别的语言的请求不改它。"""

    def setUp(self):
        inner = tb.BankmanCase("test_cancel")
        inner.setUp()
        self.addCleanup(inner.tearDown)
        self.fx, self.srv = inner.fx, inner.srv

    def wait_idle(self, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            st = self.request("GET", "/api/bank-status")[1]
            if not st["running"]:
                return st
            time.sleep(0.05)
        self.fail("任务没有在 %d 秒内结束" % timeout)

    def start(self, lang, **body):
        st, d = self.request("POST", "/api/bank-update", dict(body), lang=lang)
        self.assertEqual((st, d.get("ok")), (200, True), d)

    def test_success_log_follows_the_request_language(self):
        # GSM8K 的魔搭不通, 走 GitHub 镜像 (在线程池里测速)
        del self.srv.files["/sail/open_data/gsm8k/test.jsonl"]
        raw = "/gh/openai/grade-school-math/master/grade_school_math/data/test.jsonl"
        self.srv.files["/mirror2/" + self.srv.url + raw] = self.fx["gsm"].encode()
        self.start("en")
        st = self.wait_idle()
        lines = [x["msg"] for x in st["log"]]
        self.assertIsNone(st["error"], lines)
        assert_english(self, scrub(lines, bankman.DATASETS, bankman.BANKS), what="job log")
        self.assertEqual(lines[0], "Download source: ModelScope (China); 6 question sets have no local data yet, downloading them to %s first" % bankman.DATASETS)
        self.assertIn("      GSM8K: ModelScope OSS unavailable (HTTP Error 404: Not Found), trying the next one", lines)
        self.assertIn("Progress 6 / 6 · data is local", lines)
        self.assertRegex(lines[-1], r"^Done: iq-[0-9a-f]{12}, \d+ questions; downloaded ")
        self.assertRegex(st["run_id"], r"^iq-[0-9a-f]{12}$")
        st2 = self.request("GET", "/api/bank-status", lang="zh")[1]                  # 之后中文请求来读状态: 日志还是英文的
        self.assertEqual([x["msg"] for x in st2["log"]][0], lines[0])

    def test_same_job_in_chinese(self):
        self.start("zh")
        st = self.wait_idle()
        lines = [x["msg"] for x in st["log"]]
        self.assertIsNone(st["error"], lines)
        self.assertEqual(lines[0], "下载源：魔搭（国内）；本地缺少 6 个题集的数据，先下载到 %s" % bankman.DATASETS)
        self.assertIn("进度 6 / 6 · 数据已在本地", lines)
        self.assertRegex(lines[-1], r"^完成：iq-[0-9a-f]{12}，共 \d+ 题；本次下载 ")

    def test_failure_reason_is_in_the_task_language(self):
        """离线但本地缺数据: 任务失败, error 里的原因是任务语言。"""
        self.start("en", offline=True)
        st = self.wait_idle()
        self.assertTrue(st["error"].startswith("RuntimeError: Offline mode is on, but local data is missing for GSM8K, MMLU"), st["error"])
        assert_english(self, scrub(st["error"], bankman.DATASETS))
        self.assertIn("FAILED: " + st["error"], [x["msg"] for x in st["log"]])
        self.start("zh", offline=True)
        st = self.wait_idle()
        self.assertTrue(st["error"].startswith("RuntimeError: 离线模式下本地缺少这些题集的数据：GSM8K、MMLU"), st["error"])


# ================================================================ 3. store

def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


PERF = {"run_id": "run_20260101_000000_m", "status": "done", "kind": "perf", "phases": [{"id": "decode", "x": 1}],
        "started_utc": "2026-01-01T00:00:00Z", "finished_utc": "2026-01-01T00:10:00Z", "url": "http://x/v1/chat/completions", "model": "m",
        "suite": "quick"}
IQ = {"run_id": "iq_20260101_000001_m", "kind": "iq", "status": "done", "model": "m", "subjects": [{"id": "s", "name": "S", "n": 1, "correct": 1}],
      "items": [{"sid": "s", "idx": 0, "ok": True, "in": 5, "out": 6}], "overall": {"acc": 1.0, "n": 1, "correct": 1},
      "started_utc": "2026-01-01T00:00:01Z", "finished_utc": "2026-01-01T00:01:00Z"}
GEN = {"run_id": "gen_20260101_000002_m", "kind": "gen", "status": "done", "model": "m",
       "items": [{"id": "t1", "name": "N", "file": "f.html", "pass": 1, "total": 2}],
       "started_utc": "2026-01-01T00:00:02Z", "finished_utc": "2026-01-01T00:02:00Z"}


class _StoreEnv(unittest.TestCase):
    def setUp(self):
        self.reset()
        i18n.MISSING.clear()
        self.addCleanup(i18n.set_default_lang, None)

    def reset(self):
        """换一个新的库和结果目录。"""
        self.dir = temp_dir()
        self.db = os.path.join(self.dir, "t.db")
        self.res = os.path.join(self.dir, "results")
        os.makedirs(self.res)


class TestStoreImportReasons(_StoreEnv):
    """import_json_file 返回 inserted | skipped:<原因> | replaced | error:<原因>: 前缀是协议不能变, 只翻原因。"""

    ZH = ["error:非对象 JSON", "skipped:无法识别类型", "inserted", "skipped:未变化", "skipped:内容不同(加 --force 覆盖)", "replaced",
          "skipped:已删除", "inserted", "skipped:库内原生运行"]
    EN = ["error:not a JSON object", "skipped:unknown run type", "inserted", "skipped:unchanged", "skipped:content differs (use --force to overwrite)",
          "replaced", "skipped:previously deleted", "inserted", "skipped:run already in the database (not imported from a file)"]

    def sequence(self):
        db, res = self.db, self.res
        got = []
        p = os.path.join(res, "list.json")
        write_json(p, [1, 2])
        got.append(store.import_json_file(p, db_path=db))
        p = os.path.join(res, "zzz.json")
        write_json(p, {"foo": 1})
        got.append(store.import_json_file(p, db_path=db))
        p = os.path.join(res, IQ["run_id"] + ".json")
        write_json(p, IQ)
        got.append(store.import_json_file(p, db_path=db))
        got.append(store.import_json_file(p, db_path=db))
        write_json(p, dict(IQ, model="m2"))
        got.append(store.import_json_file(p, db_path=db))
        got.append(store.import_json_file(p, force=True, db_path=db))
        store.delete_run(IQ["run_id"], db)
        got.append(store.import_json_file(p, db_path=db))
        got.append(store.import_json_file(p, force=True, db_path=db))
        pn = os.path.join(res, PERF["run_id"] + ".json")                         # 库里已有的同名运行不是从文件导入的 (原生)
        write_json(pn, PERF)
        with store.session(db) as conn:
            store.upsert_header(conn, PERF, status="done", heartbeat=False)
        got.append(store.import_json_file(pn, db_path=db))
        return got

    def test_reasons_in_both_languages(self):
        with i18n.use_lang("zh"):
            self.assertEqual(self.sequence(), self.ZH)
        self.reset()                                                              # 换一个新库和目录, 再用英文走一遍
        with english_flow() as flow:
            got = self.sequence()
        self.assertEqual(got, self.EN)
        self.assertEqual(flow.missing, [])
        assert_english(self, got)

    def test_prefixes_are_the_protocol_in_every_language(self):
        for lang in ("zh", "en"):
            with self.subTest(lang=lang), i18n.use_lang(lang):
                self.reset()
                got = self.sequence()
                self.assertEqual([x.split(":", 1)[0] for x in got], ["error", "skipped", "inserted", "skipped", "skipped", "replaced", "skipped",
                                                                     "inserted", "skipped"])

    def test_read_errors_keep_the_system_text(self):
        p = os.path.join(self.res, "bad.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write("{not json")
        for lang in ("zh", "en"):
            with self.subTest(lang=lang), i18n.use_lang(lang):
                got = store.import_json_file(p, db_path=self.db)
                self.assertTrue(got.startswith("error:JSONDecodeError: "), got)
        self.assertTrue(store.import_json_file(os.path.join(self.res, "missing.json"), db_path=self.db).startswith("error:FileNotFoundError: "))

    def test_import_dir_summary_and_lines(self):
        write_json(os.path.join(self.res, IQ["run_id"] + ".json"), IQ)
        write_json(os.path.join(self.res, GEN["run_id"] + ".json"), GEN)
        write_json(os.path.join(self.res, "run_20260202_000000_bad.json"), [1])
        want = {"zh": ["  gen_20260101_000002_m.json -> inserted", "  iq_20260101_000001_m.json -> inserted",
                       "  run_20260202_000000_bad.json -> error:非对象 JSON"],
                "en": ["  gen_20260101_000002_m.json -> skipped:unchanged", "  iq_20260101_000001_m.json -> skipped:unchanged",
                       "  run_20260202_000000_bad.json -> error:not a JSON object"]}
        want_summary = {"zh": {"inserted": 2, "replaced": 0, "skipped": 0, "errors": ["run_20260202_000000_bad.json: 非对象 JSON"]},
                        "en": {"inserted": 0, "replaced": 0, "skipped": 2, "errors": ["run_20260202_000000_bad.json: not a JSON object"]}}
        for lang in ("zh", "en"):                                                # 中文先导入; 英文再导入一遍: 已经导入过, 变成 skipped:unchanged
            lines = []
            with i18n.use_lang(lang):
                summary = store.import_dir(self.res, db_path=self.db, log=lines.append)
            self.assertEqual((lines, summary), (want[lang], want_summary[lang]), lang)
        assert_english(self, [lines, summary])


class TestStoreErrors(_StoreEnv):
    def raises(self, exc, fn, *a, **k):
        with self.assertRaises(exc) as cm:
            fn(*a, **k)
        return cm.exception.args[0]

    def test_unknown_run_type(self):
        with store.session(self.db) as conn:
            for lang, want in (("zh", "无法识别运行类型: x1"), ("en", "Cannot determine the run type: x1")):
                with i18n.use_lang(lang):
                    self.assertEqual(self.raises(ValueError, store.upsert_header, conn, {"run_id": "x1"}), want)

    def test_delete_a_running_run(self):
        with store.session(self.db) as conn:
            store.upsert_header(conn, dict(PERF, status="running"), status="running")       # 刚写过心跳: 还在运行
        for lang, want in (("zh", "运行尚未结束，请先停止后再删除"), ("en", "The run has not finished yet. Stop it first, then delete it.")):
            with i18n.use_lang(lang):
                self.assertEqual(self.raises(ValueError, store.delete_run, PERF["run_id"], self.db), want)

    def test_save_endpoint_errors(self):
        url_zh, url_en = "API 地址必须以 http:// 或 https:// 开头", "The service URL must start with http:// or https://"
        cases = [({"model": "m"}, ValueError, url_zh, url_en), ({"url": "ftp://x", "model": "m"}, ValueError, url_zh, url_en),
                 ({"url": "http://x", "model": ""}, ValueError, "模型名称不能为空", "The model name cannot be empty"),
                 ({"id": "ep_nope", "url": "http://x", "model": "m"}, KeyError, "配置不存在或已被删除",
                  "The configuration does not exist or has been deleted")]
        for ep, exc, zh, en in cases:
            for lang, want in (("zh", zh), ("en", en)):
                with self.subTest(ep=str(ep), lang=lang), i18n.use_lang(lang):
                    self.assertEqual(self.raises(exc, store.save_endpoint, ep, self.db), want)
        with i18n.use_lang("en"):
            self.assertEqual(store.save_endpoint({"url": "http://h:1/v1", "model": "m1"}, self.db)["name"], "m1 · h:1")      # 默认名字不翻译
        self.assertEqual(i18n.MISSING, set())

    def test_export_missing_run(self):
        for lang, want in (("zh", "run 不存在: run_nope"), ("en", "Run not found: run_nope")):
            with i18n.use_lang(lang):
                self.assertEqual(self.raises(KeyError, store.export_run, "run_nope", os.path.join(self.dir, "out"), self.db), want)

    def test_roundtrip_check_marks_missing_runs(self):
        write_json(os.path.join(self.res, IQ["run_id"] + ".json"), IQ)
        write_json(os.path.join(self.res, GEN["run_id"] + ".json"), GEN)
        store.import_json_file(os.path.join(self.res, IQ["run_id"] + ".json"), db_path=self.db)                # 只导入一个
        for lang, want in (("zh", ["gen_20260101_000002_m.json (缺失)"]), ("en", ["gen_20260101_000002_m.json (missing)"])):
            with i18n.use_lang(lang):
                self.assertEqual(store.check_roundtrip(self.res, self.db), want)


class TestStoreCommandLine(_StoreEnv):
    def main(self, argv, lang):
        i18n.set_default_lang(None)
        return run_main(store.main, ["--db", self.db] + argv + ["--lang", lang])

    def test_commands_in_english_and_chinese(self):
        write_json(os.path.join(self.res, IQ["run_id"] + ".json"), IQ)
        write_json(os.path.join(self.res, GEN["run_id"] + ".json"), GEN)
        out_dir = os.path.join(self.dir, "export")
        cases = [
            (["init"], "ok: %s" % self.db, "ok: %s" % self.db),
            (["import", "--results", self.res],
             "  gen_20260101_000002_m.json -> inserted\n  iq_20260101_000001_m.json -> inserted\n"
             "导入完成: {\"inserted\": 2, \"replaced\": 0, \"skipped\": 0, \"errors\": []}",
             "  gen_20260101_000002_m.json -> skipped:unchanged\n  iq_20260101_000001_m.json -> skipped:unchanged\n"
             "Import complete: {\"inserted\": 0, \"replaced\": 0, \"skipped\": 2, \"errors\": []}"),
            (["export", "--out", out_dir], "导出 2 个 => %s" % out_dir, "Exported 2 runs => %s" % out_dir),
            (["export", "--out", out_dir, "--run", IQ["run_id"]], "导出 1 个 => %s" % out_dir, "Exported 1 run => %s" % out_dir),
            (["export", "--out", out_dir, "--kind", "perf"], "导出 0 个 => %s" % out_dir, "Exported 0 runs => %s" % out_dir),
            (["stale"], "标记中断: 0", "Marked as interrupted: 0"),
            (["check", "--results", self.res], "往返一致", "Round trip consistent"),
        ]
        for argv, zh, en in cases:
            code, out = self.main(argv, "zh")
            self.assertEqual((code, out.rstrip("\n")), (0, zh), argv)
            code, out = self.main(argv, "en")
            self.assertEqual((code, out.rstrip("\n")), (0, en), argv)
            assert_english(self, scrub(out.splitlines(), self.dir), what="store " + " ".join(argv))
        # 往返不一致: 库里有、文件被改过
        write_json(os.path.join(self.res, GEN["run_id"] + ".json"), dict(GEN, model="changed"))
        code, out = self.main(["check", "--results", self.res], "zh")
        self.assertEqual((code, out.strip()), (1, "不一致: ['gen_20260101_000002_m.json']"))
        code, out = self.main(["check", "--results", self.res], "en")
        self.assertEqual((code, out.strip()), (1, "Round trip inconsistent: ['gen_20260101_000002_m.json']"))

    def test_import_with_a_bad_file_reports_the_error_in_the_language(self):
        write_json(os.path.join(self.res, "run_20260202_000000_bad.json"), [1])
        code, out = self.main(["import", "--results", self.res], "en")
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines()[-1], 'Import complete: {"inserted": 0, "replaced": 0, "skipped": 0, '
                                               '"errors": ["run_20260202_000000_bad.json: not a JSON object"]}')
        assert_english(self, out.splitlines())

    def test_help_texts(self):
        for argv in ([], ["import"], ["export"], ["check"], ["stale"], ["init"]):
            with self.subTest(argv=argv):
                i18n.set_default_lang(None)
                code, out = run_main(store.main, argv + ["--help", "--lang", "en"])
                self.assertEqual(code, 0)
                assert_english(self, out.splitlines(), what="store %s --help" % " ".join(argv))
        i18n.set_default_lang(None)
        code, out = run_main(store.main, ["--lang", "en", "--help"])
        flat = " ".join(out.split())
        for text in ("llm-bench-pro SQLite results database", "Database path (default: data/llm_bench.db or $LLM_BENCH_DB)", "Create the database and tables",
                     "Import data/results/*.json (idempotent)", "Export as JSON", "Mark running runs whose heartbeat has timed out as interrupted",
                     "Verify that the database round-trips to data/results/*.json"):
            self.assertIn(text, flat)
        i18n.set_default_lang(None)
        code, out = run_main(store.main, ["import", "--lang", "en", "--help"])
        self.assertIn("Delete already-imported runs whose content has changed and import them again", " ".join(out.split()))
        i18n.set_default_lang(None)
        code, out = run_main(store.main, ["--lang", "zh", "--help"])
        flat = " ".join(out.split())
        for text in ("llm-bench-pro SQLite 结果库", "库路径 (默认 data/llm_bench.db 或 $LLM_BENCH_DB)", "建库建表", "导入 data/results/*.json (幂等)", "导出为 JSON",
                     "把心跳超时的 running 运行标记为 interrupted", "校验库与 data/results/*.json 往返等价"):
            self.assertIn(text, flat)


# ================================================================ 4. vision_assets

def _chunk(typ, body):
    return struct.pack(">I", len(body)) + typ + body + struct.pack(">I", zlib.crc32(typ + body) & 0xFFFFFFFF)


def png(w, h, idat=b"x", ihdr=None, iend=True):
    """只有结构 (每块的 CRC 都对) 的 PNG: check_image 只看块结构和 IHDR 里的宽高, 不解压图像。"""
    out = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr if ihdr is not None else struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    if idat is not None:
        out += _chunk(b"IDAT", idat)
    return out + (_chunk(b"IEND", b"") if iend else b"")


def jpeg(w, h, eoi=True):
    out = b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    out += b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" + struct.pack(">HH", h, w) + b"\x03" + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    out += b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00" + b"\x12\x34\x56"
    return out + (b"\xff\xd9" if eoi else b"")


def webp(kind, w, h, declared=None):
    if kind == "VP8X":
        body = b"VP8X" + struct.pack("<I", 10) + b"\x00\x00\x00\x00" + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little")
    else:
        body = kind.encode() + struct.pack("<I", 10) + b"\x00" * 10
    return b"RIFF" + struct.pack("<I", 4 + len(body) if declared is None else declared) + b"WEBP" + body


def gif(w, h, short=False):
    head = b"GIF89a" + struct.pack("<HH", w, h)
    return head if short else head + b"\xf7\x00\x00" + b"\x00" * 4 + b"\x3b"


def vision_cases():
    """(标签, 数据, 文件名, code, level, ok, 中文说明, 英文说明); 中文照旧代码的 % 写法拼。"""
    ok_png = png(224, 224)
    small = "尺寸 %d×%d 偏小，可能影响回答效果（推荐 %d×%d 以上）"
    small_en = "Size %d×%d is on the small side and may affect answer quality (recommended: 224×224 or larger)"
    trunc = "文件不完整（%s 没有正常结束，可能下载或拷贝时被截断了）"
    trunc_en = "Incomplete file (%s data does not end properly; it may have been truncated during download or copying)"
    unsupported = "是 %s 格式，暂不支持，请转成 JPG 或 PNG 再用"
    unsupported_en = "%s format is not supported yet; convert it to JPG or PNG first"
    mismatch = "扩展名是 %s，实际是 %s 图片，已按 %s 处理"
    mismatch_en = "The extension is %s, but the file is actually a %s image; it was handled as %s"
    return [
        ("empty", b"", "a.png", "empty", "bad", False, "文件是空的", "The file is empty"),
        ("garbage", b"hello world", "a.png", "unsupported", "bad", False, "不是能识别的图片（只支持 JPG / PNG / WebP / GIF）",
         "Not a recognizable image (only JPG / PNG / WebP / GIF are supported)"),
        ("bmp", b"BM" + b"\x00" * 60, "a.png", "unsupported", "bad", False, unsupported % "BMP", unsupported_en % "BMP"),
        ("tiff", b"II*\x00" + b"\x00" * 60, "a.png", "unsupported", "bad", False, unsupported % "TIFF", unsupported_en % "TIFF"),
        ("heic", b"\x00\x00\x00\x18ftypheic" + b"\x00" * 30, "a.jpg", "unsupported", "bad", False, unsupported % "HEIC", unsupported_en % "HEIC"),
        ("avif", b"\x00\x00\x00\x18ftypavif" + b"\x00" * 30, None, "unsupported", "bad", False, unsupported % "AVIF", unsupported_en % "AVIF"),
        ("svg", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", "a.png", "unsupported", "bad", False, unsupported % "SVG", unsupported_en % "SVG"),
        ("png truncated", ok_png[:-5], "a.png", "broken", "bad", False, trunc % "PNG", trunc_en % "PNG"),
        ("jpeg truncated", jpeg(300, 200, eoi=False), "a.jpg", "broken", "bad", False, trunc % "JPEG", trunc_en % "JPEG"),
        ("webp truncated", webp("VP8X", 300, 200, declared=5000), "a.webp", "broken", "bad", False, trunc % "WebP", trunc_en % "WebP"),
        ("gif truncated", gif(300, 200, short=True), "a.gif", "broken", "bad", False, trunc % "GIF", trunc_en % "GIF"),
        ("png checksum", bytes(bytearray(ok_png[:16]) + bytes([ok_png[16] ^ 1]) + ok_png[17:]), "a.png", "broken", "bad", False,
         "文件已损坏（PNG 数据校验不通过）", "Corrupted file (PNG checksum failed)"),
        ("png no header", b"\x89PNG\r\n\x1a\n" + _chunk(b"tEXt", b"abc") + _chunk(b"IDAT", b"x") + _chunk(b"IEND", b""), "a.png", "broken", "bad", False,
         "文件已损坏（PNG 缺少文件头）", "Corrupted file (PNG header is missing)"),
        ("png no data", png(224, 224, idat=None), "a.png", "broken", "bad", False, "文件已损坏（PNG 里没有图像数据）", "Corrupted file (the PNG contains no image data)"),
        ("jpeg no size", jpeg(0, 10), "a.jpg", "broken", "bad", False, "文件已损坏（JPEG 里读不出宽高）",
         "Corrupted file (cannot read the width and height from the JPEG)"),
        ("webp no size", webp("XXXX", 300, 200), "a.webp", "broken", "bad", False, "文件已损坏（WebP 里读不出宽高）",
         "Corrupted file (cannot read the width and height from the WebP)"),
        ("too small", png(10, 10), "a.png", "too_small", "bad", False, "只有 %d×%d 像素，太小，看图模型会直接拒绝（每边至少 %d 像素）" % (10, 10, 28),
         "Only 10×10 pixels, too small; vision models will reject it (each side must be at least 28 pixels)"),
        ("too large", png(9000, 100), "a.png", "too_large", "bad", False, "尺寸 %d×%d，边长超过 %d 像素，请缩小后再用" % (9000, 100, 8192),
         "Size 9000×100 is too large (a side is longer than 8192 pixels); downscale it first"),
        ("too big", png(224, 224, idat=b"\0" * (21 << 20)), "big.png", "too_big", "bad", False, "有 %s，超过单张 20 MB 的上限" % "21.0 MB",
         "21.0 MB exceeds the 20 MB limit per image"),
        ("ok", ok_png, "a.png", "", "ok", True, "", ""),
        ("ok no name", ok_png, None, "", "ok", True, "", ""),
        ("small warn", png(100, 100), "a.png", "", "warn", True, small % (100, 100, 224, 224), small_en % (100, 100)),
        ("extension mismatch", ok_png, "a.jpg", "", "warn", True, mismatch % (".jpg", "PNG", "PNG"), mismatch_en % (".jpg", "PNG", "PNG")),
        ("both notes", png(100, 100), "a.gif", "", "warn", True, small % (100, 100, 224, 224) + "；" + mismatch % (".gif", "PNG", "PNG"),
         small_en % (100, 100) + ". " + mismatch_en % (".gif", "PNG", "PNG")),
    ]


class TestVisionAssets(unittest.TestCase):
    FIELDS = {"name", "bytes", "format", "width", "height", "ext", "ok", "level", "code", "msg"}

    def setUp(self):
        i18n.MISSING.clear()

    def test_check_image_messages_in_both_languages(self):
        for label, data, name, code, level, ok, zh, en in vision_cases():
            with self.subTest(case=label):
                with i18n.use_lang("zh"):
                    c_zh = vision_assets.check_image(data, name=name)
                with english_flow() as flow:
                    c_en = vision_assets.check_image(data, name=name)
                self.assertEqual((c_zh["code"], c_zh["level"], c_zh["ok"], c_zh["msg"]), (code, level, ok, zh))
                self.assertEqual((c_en["code"], c_en["level"], c_en["ok"], c_en["msg"]), (code, level, ok, en))
                self.assertEqual(dict(c_en, msg=None), dict(c_zh, msg=None))                # 除说明外的字段两种语言完全一样
                self.assertEqual(set(c_en), self.FIELDS)
                self.assertEqual(flow.missing, [])
                assert_english(self, c_en["msg"], what=label)

    def test_image_error_carries_the_code_and_a_translated_message(self):
        with i18n.use_lang("en"):
            with self.assertRaises(vision_assets.ImageError) as cm:
                vision_assets.image_info(b"BM" + b"\x00" * 60)
            self.assertEqual((cm.exception.code, str(cm.exception)), ("unsupported", "BMP format is not supported yet; convert it to JPG or PNG first"))
            with self.assertRaises(vision_assets.ImageError) as cm:
                vision_assets.image_info(png(224, 224)[:-5])
            self.assertEqual((cm.exception.code, str(cm.exception)[:16]), ("broken", "Incomplete file "))
        with i18n.use_lang("zh"):
            with self.assertRaises(vision_assets.ImageError) as cm:
                vision_assets.image_info(b"")
            self.assertEqual((cm.exception.code, str(cm.exception)), ("unsupported", "文件是空的"))
        self.assertEqual(i18n.MISSING, set())

    def test_scan_dir_reports_files_over_the_size_limit_without_reading_them(self):
        d = temp_dir()
        with open(os.path.join(d, "01.png"), "wb") as f:
            f.write(png(224, 224))
        with open(os.path.join(d, "02-bad.png"), "wb") as f:
            f.write(b"not a png")
        with open(os.path.join(d, "03-huge.png"), "wb") as f:
            f.seek((21 << 20) + 5)
            f.write(b"\0")
        with open(os.path.join(d, "04.txt"), "wb") as f:
            f.write(b"ignored")
        want = {"zh": ["", "不是能识别的图片（只支持 JPG / PNG / WebP / GIF）", "有 %s，超过单张 20 MB 的上限" % "21.0 MB"],
                "en": ["", "Not a recognizable image (only JPG / PNG / WebP / GIF are supported)", "21.0 MB exceeds the 20 MB limit per image"]}
        for lang in ("zh", "en"):
            with self.subTest(lang=lang), i18n.use_lang(lang):
                good, checks = vision_assets.scan_dir(d, keep_data=False)
                self.assertEqual([n for n, _, _ in good], ["01.png"])
                self.assertEqual([c["msg"] for c in checks], want[lang])
                self.assertEqual([c["code"] for c in checks], ["", "unsupported", "too_big"])
        assert_english(self, want["en"])

    def test_notes_are_joined_by_the_language_of_the_list(self):
        """收下但提示的几条: 中文用「；」连接; 英文是各自独立的句子, 用句号连接 (不写成「…; The …」)。"""
        with i18n.use_lang("en"):
            msg = vision_assets.check_image(png(100, 100), name="a.gif")["msg"]
        self.assertEqual(msg.count(". "), 1)
        self.assertNotIn("; The", msg)
        with i18n.use_lang("zh"):
            self.assertEqual(vision_assets.check_image(png(100, 100), name="a.gif")["msg"].count("；"), 1)


if __name__ == "__main__":
    unittest.main()
