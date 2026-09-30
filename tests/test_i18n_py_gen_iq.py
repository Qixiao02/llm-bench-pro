# -*- coding: utf-8 -*-
"""代码生成引擎 (gen.py) 和能力评测引擎 (iq.py) 的中英文测试。约定见 CONTRIBUTING.md「服务端消息与翻译」。

  - 每个会输出文字的函数: 英文下没有汉字、句子读起来对 (带数量的 0 / 1 / 多), 中文和转换前逐字一致
  - 日志 (plog)、抛出的异常文字、存进结果里的说明 (notes / warnings / error / changes / rescued ...) 都按任务的语言生成,
    包括线程池工作线程里生成的
  - 前端靠 changes 里的关键词给作品分类 (web/static/app.js 的 changeKind), 英文改写时关键词不能丢

geneval 的检查项文字不在这里测: run_gen / reevaluate 的测试用一个假的评测器 (FakeEvaluator) 代替它, 不开浏览器。
"""
import contextlib
import io
import json
import os
import re
import threading
import time
import unittest
from unittest import mock

from _util import MockServer, chat_reply, load_json, temp_dir   # 先设 LLM_BENCH_LANG=zh, 再导入包内模块
import bankman
import geneval
import gen
import i18n
import iq
import sinks
import store
from test_i18n_py import LangCase, LangServerCase, STORED_TEXT_KEYS, assert_english, english_flow


# ================================================================ 公用: 假评测器 / 模拟服务 / 日志收集

class FakeEvaluator(object):
    """代替 geneval.Evaluator: 不开浏览器, 返回固定的英文检查结果 (一项通过、一项没通过)。"""

    def __init__(self, judge_cfg=None, browsers=2, log=None):
        self.judge_cfg = judge_cfg if judge_cfg and judge_cfg.get("base") and judge_cfg.get("model") else None
        self.method = "static"
        self.log = log

    def reap(self):
        return 0

    def meta(self):
        return {"eval_version": "test", "method": "static", "browser": None, "browser_error": None,
                "judge_model": self.judge_cfg["model"] if self.judge_cfg else None}

    def evaluate(self, task, html_path, html, cancel=None):
        report = {"method": "static", "checks": [{"id": "f1", "label": "Check A", "pass": True},
                                                 {"id": "f2", "label": "Check B", "pass": False}],
                  "exec_score": 50.0, "shots": [], "notes": ["Source-only check in tests"], "shots_dir": "x.shots"}
        if self.judge_cfg:
            report["judge"] = {"model": self.judge_cfg["model"], "score": 85.0}
        return report

    def close(self):
        pass


# 题目表换成英文名的几道题: 真实的题目表里作品名和标签是中文数据 (不翻), 日志里会带出来; 用它才能断言整段日志没有汉字
TEST_TASKS = [{"id": "t_ok", "name": "Page A", "tags": ["Basic", "Animation"], "prompt": "make page A", "features": []},
              {"id": "t_fail", "name": "Page B", "tags": ["Basic"], "prompt": "make page B", "features": []},
              {"id": "t_plain", "name": "Page D", "tags": ["Hard"], "prompt": "make page D", "features": []},
              {"id": "t_loop", "name": "Page E", "tags": ["Real-world"], "prompt": "make page E", "features": []},
              {"id": "t_cont", "name": "Page F", "tags": ["Hard"], "prompt": "make page F", "features": []},
              {"id": "t_think", "name": "Page G", "tags": ["Hard"], "prompt": "make page G", "features": []},
              {"id": "t_rescue", "name": "Page H", "tags": ["Hard"], "prompt": "make page H", "features": []}]

GOOD_HTML = ("<!doctype html><html><head><title>t</title></head><body><canvas></canvas><script>"
             "requestAnimationFrame(()=>{});/*" + "x" * 300 + "*/</script></body></html>")
FENCED = "Here you go:\n```html\n" + GOOD_HTML + "\n```"
DOC = "<!doctype html><html><body>ok</body></html>"


def sse_text(content="", reasoning="", finish="stop", chunk=7):
    out = []
    for key, text in (("reasoning_content", reasoning), ("content", content)):
        for i in range(0, len(text), chunk):
            out.append(b"data: " + json.dumps({"choices": [{"delta": {key: text[i:i + chunk]}}]}).encode() + b"\n\n")
    out.append(b"data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": finish}]}).encode() + b"\n\n")
    out.append(b'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":20}}\n\ndata: [DONE]\n\n')
    return b"".join(out)


def stream(content="", reasoning="", finish="stop", chunk=7):
    return 200, sse_text(content, reasoning, finish, chunk), "text/event-stream"


@contextlib.contextmanager
def zh_flow():
    """中文模式下收 gen / iq 的日志 (english_flow 的中文版), 对照转换前的中文用。"""
    lines, buf = [], io.StringIO()
    saved = (gen._GEN_PROGRESS, iq._IQ_PROGRESS)
    gen._GEN_PROGRESS = iq._IQ_PROGRESS = lines.append
    try:
        with i18n.use_lang("zh"), contextlib.redirect_stdout(buf):
            yield lines
    finally:
        gen._GEN_PROGRESS, iq._IQ_PROGRESS = saved


@contextlib.contextmanager
def gen_env(tasks=None):
    """run_gen / reevaluate 的运行环境: 英文名的题目表、临时的作品目录、假评测器。"""
    tmp = temp_dir()
    with mock.patch.object(gen, "GEN_TASKS", tasks or TEST_TASKS), mock.patch.object(gen, "ROOT", tmp), \
            mock.patch.object(gen, "WORKS", os.path.join(tmp, "works")), mock.patch.object(geneval, "Evaluator", FakeEvaluator):
        yield tmp


def run_gen_doc(handler, task_ids, lang="en", **kw):
    """在某个语言下跑一遍 run_gen (本地模拟服务), 返回 (日志行, 结果文档, 每题原始输出记录 {id: 文档})。"""
    m = MockServer(handler)
    try:
        with gen_env() as tmp:
            sink = sinks.JsonFileSink(os.path.join(tmp, "results"))
            flow = english_flow() if lang == "en" else zh_flow()
            with flow as f:
                gen.run_gen(m.url + "/v1/chat/completions", "m", task_ids=task_ids, conc=1, sink=sink, **kw)
            doc = load_json(sink.path)
            traces = {}
            for it in doc["items"]:
                if it.get("trace"):
                    traces[it["id"]] = load_json(os.path.join(tmp, it["trace"]))
    finally:
        m.close()
    return f, doc, traces


# ================================================================ gen: 不用模型服务的函数

class TestGenTexts(LangCase):
    def both(self, fn, en, zh):
        with i18n.use_lang("en"):
            got = fn()
            self.assertEqual(got, en)
            assert_english(self, got)
        with i18n.use_lang("zh"):
            self.assertEqual(fn(), zh)

    def raises(self, fn, en, zh):
        def msg():
            with self.assertRaises(ValueError) as cm:
                fn()
            return str(cm.exception)
        self.both(msg, en, zh)

    def test_sampling_errors(self):
        for sampling, en, zh in (
                ({"temperature": "abc"}, "Invalid sampling parameter temperature: 'abc'", "采样参数 temperature 无效: 'abc'"),
                ({"temperature": 5}, "Sampling parameter temperature must be between 0.0 and 2.0 (got 5.0)",
                 "采样参数 temperature 应在 0.0 到 2.0 之间: 5.0"),
                ({"top_k": 5000}, "Sampling parameter top_k must be between -1 and 1000 (got 5000)",
                 "采样参数 top_k 应在 -1 到 1000 之间: 5000"),
                ("greedy", "Unknown sampling mode: 'greedy'", "未知的采样方式: 'greedy'")):
            with self.subTest(sampling=sampling):
                self.raises(lambda: gen.resolve_sampling(True, sampling), en, zh)
                self.raises(lambda: gen.sampling_record(sampling), en, zh)
        with i18n.use_lang("en"):                                     # 正常的采样参数不受语言影响
            self.assertEqual(gen.resolve_sampling(False, {"temperature": "0.5"}), {"temperature": 0.5, "seed": 42})

    def test_repetition_text(self):
        loop = {"kind": "loop", "period": 40, "repeats": 150}
        similar = {"kind": "similar", "ratio": 0.0821}
        self.both(lambda: gen.repetition_text(loop), "a 40-character cycle repeated 150 times", "每 40 个字符循环一次，已重复 150 次")
        self.both(lambda: gen.repetition_text(similar),
                  "the last few thousand characters are highly repetitive: compression ratio 0.08, normal code is around 0.2 or higher",
                  "最近几千字内容高度雷同（压缩率 0.08，正常代码约 0.2 以上）")
        self.both(lambda: gen.repetition_text({"kind": "similar"}),
                  "the last few thousand characters are highly repetitive: compression ratio 0.00, normal code is around 0.2 or higher",
                  "最近几千字内容高度雷同（压缩率 0.00，正常代码约 0.2 以上）")

    def test_task_id_errors(self):
        self.raises(lambda: gen.normalize_task_ids(5), "tasks must be an array of question IDs", "tasks 应为题目 id 数组")
        self.raises(lambda: gen.normalize_task_ids(["pelican", 3]), "tasks must be an array of question IDs", "tasks 应为题目 id 数组")
        self.raises(lambda: gen.normalize_task_ids([]), "Select at least 1 question", "请至少选择 1 道题目")
        self.raises(lambda: gen.normalize_task_ids("nope"), "Unknown question ID: nope", "未知题目：nope")              # 1 个: 单数
        self.raises(lambda: gen.normalize_task_ids(["nope", "pelican", "zzz"]), "Unknown question IDs: nope, zzz", "未知题目：nope、zzz")   # 多个: 复数
        self.raises(lambda: gen.normalize_task_ids(["n%d" % i for i in range(12)]),
                    "Unknown question IDs: n0, n1, n2, n3, n4, n5, n6, n7", "未知题目：n0、n1、n2、n3、n4、n5、n6、n7")   # 最多列 8 个
        with i18n.use_lang("en"):
            self.assertEqual(gen.normalize_task_ids("pelican, snake"), ["pelican", "snake"])

    def test_eval_brief(self):
        def item(passed, total, lines, fails=(), judge=None):
            checks = [{"label": name, "pass": False} for name in fails] + [{"label": "ok", "pass": True}]
            ev = {"checks": checks}
            if judge is not None:
                ev["judge"] = judge
            return {"pass": passed, "total": total, "lines": lines, "eval": ev}
        cases = [
            (item(5, 5, 120), "runtime check 5/5 · 120 lines", "运行检测 5/5 · 120 行"),
            (item(4, 5, 1, ["Page loads"]), "runtime check 4/5 (failed: Page loads) · 1 line", "运行检测 4/5（未通过：Page loads） · 1 行"),
            (item(1, 5, 0, ["A", "B", "C", "D"]), "runtime check 1/5 (failed: A, B, C) · 0 lines", "运行检测 1/5（未通过：A、B、C） · 0 行"),
            (item(3, 3, 7, judge={"score": 84.6}), "runtime check 3/3 · review score 85 · 7 lines", "运行检测 3/3 · 评审 85 分 · 7 行"),
            (item(3, 3, 7, judge={"score": None, "error": "boom"}), "runtime check 3/3 · review failed · 7 lines", "运行检测 3/3 · 评审失败 · 7 行"),
        ]
        for it, en, zh in cases:
            with self.subTest(en=en):
                self.both(lambda: gen._eval_brief(it), en, zh)


class TestDescribeChanges(LangCase):
    """存进作品条目和 <题>.gen.json 的「框架对模型输出做过的处理」: 按任务语言生成。"""

    ROUND1 = {"n": 1, "mode": "first"}

    def trace(self, *joins, **extra):
        return dict({"rounds": [self.ROUND1] + [{"n": k + 2, "mode": "prefix", "join": j} for k, j in enumerate(joins)]}, **extra)

    def cases(self):
        seam = "```html\n<!doctype html><html>\n```html\n<body>x</body></html>\n```"
        snippet = "a" * 30 + " " + "b" * 9 + "…"           # 说明文字取前 40 个字符, 换行换成空格, 超过 40 个字符加省略号
        return [
            ("raw", DOC, DOC, None, ["Saved the model output as is, with no changes"], ["原样保存了模型输出，没有做任何修改"]),
            ("fence only", "```html\n" + DOC + "\n```", DOC, None,
             ["Removed the Markdown code fence before the code", "Removed the Markdown code fence after the code"],
             ["去掉了代码前面的 Markdown 代码块标记", "去掉了代码后面的 Markdown 代码块标记"]),
            ("thinking", "<think>plan</think>" + DOC, DOC, None,
             ["Removed thinking text mixed into the answer (19 characters)"], ["去掉了混在正文里的思考过程（19 个字符）"]),
            ("prose with fences", "Sure:\n```html\n" + DOC + "\n```\nThat's all.", DOC, None,
             ['Removed explanatory text before the code (5 characters) and code fence markers: "Sure:"',
              'Removed explanatory text after the code (11 characters) and code fence markers: "That\'s all."'],
             ["去掉了代码前面的说明文字（5 个字符）和代码块标记：「Sure:」", "去掉了代码后面的说明文字（11 个字符）和代码块标记：「That's all.」"]),
            ("prose 1 character", "x" + DOC, DOC, None,
             ['Removed explanatory text before the code (1 character): "x"'], ["去掉了代码前面的说明文字（1 个字符）：「x」"]),
            ("prose after", DOC + "\nbye", DOC, None,
             ['Removed explanatory text after the code (3 characters): "bye"'], ["去掉了代码后面的说明文字（3 个字符）：「bye」"]),
            ("prose long", DOC + "\n" + "a" * 30 + "\n" + "b" * 30, DOC, None,
             ['Removed explanatory text after the code (61 characters): "%s"' % snippet],
             ["去掉了代码后面的说明文字（61 个字符）：「%s」" % snippet]),
            ("seam fence", seam, gen.extract_html(seam), None,
             ["Removed a stray code fence at the continuation seam"], ["删除了续写接缝处多余的代码块标记"]),
            ("whole file re-output", DOC, DOC, self.trace({"replaced": True}),
             ["In continuation round 2, the model rewrote the whole file from the start; the rewritten version was used"],
             ["第 2 轮续写时模型从头重写了整个文件，采用了重写后的版本"]),
            ("restart line", DOC, DOC, self.trace({"line_restart": True, "overlap": 17}),
             ["Joined continuation round 2 (the model restarted from the truncated line; removed 17 duplicated characters)"],
             ["接上第 2 轮续写（模型从被截断的那一行重新写，去掉了重复的半行（17 个字符））"]),
            ("restart line 1", DOC, DOC, self.trace({"line_restart": True, "overlap": 1}),
             ["Joined continuation round 2 (the model restarted from the truncated line; removed 1 duplicated character)"],
             ["接上第 2 轮续写（模型从被截断的那一行重新写，去掉了重复的半行（1 个字符））"]),
            ("all bits", DOC, DOC, self.trace({"overlap": 25, "fence": True, "newline": True}),
             ["Joined continuation round 2 (removed 25 characters duplicated from the text above, removed the code fence at the start, "
              "added 1 line break)"],
             ["接上第 2 轮续写（去掉了与上文重复的 25 个字符，去掉了开头的代码块标记，补了 1 个换行）"]),
            ("overlap 1", DOC, DOC, self.trace({"overlap": 1}),
             ["Joined continuation round 2 (removed 1 character duplicated from the text above)"], ["接上第 2 轮续写（去掉了与上文重复的 1 个字符）"]),
            ("direct join", DOC, DOC, self.trace({}), ["Joined continuation round 2 (appended directly)"], ["接上第 2 轮续写（直接拼接）"]),
            ("three rounds", DOC, DOC, self.trace({"overlap": 9}, {"replaced": True}, {}),
             ["Joined continuation round 2 (removed 9 characters duplicated from the text above)",
              "In continuation round 3, the model rewrote the whole file from the start; the rewritten version was used",
              "Joined continuation round 4 (appended directly)"],
             ["接上第 2 轮续写（去掉了与上文重复的 9 个字符）", "第 3 轮续写时模型从头重写了整个文件，采用了重写后的版本", "接上第 4 轮续写（直接拼接）"]),
            ("rescued first", DOC, DOC, self.trace({}, rescued="THE RESCUE TEXT"), ["THE RESCUE TEXT", "Joined continuation round 2 (appended directly)"],
             ["THE RESCUE TEXT", "接上第 2 轮续写（直接拼接）"]),          # 存进结果的 rescued 说明排在最前面
        ]

    def test_every_branch_in_english_and_chinese(self):
        for name, raw, html, trace, en, zh in self.cases():
            with self.subTest(case=name):
                with i18n.use_lang("en"):
                    got = gen.describe_changes(raw, html, trace)
                    self.assertEqual(got, en)
                    assert_english(self, got)
                with i18n.use_lang("zh"):
                    self.assertEqual(gen.describe_changes(raw, html, trace), zh)
        self.assertEqual(i18n.MISSING, set())

    def test_english_keeps_the_keywords_the_frontend_matches(self):
        """web/static/app.js 的 changeKind 用关键词给 changes 分类: 改为不思考 → rescued; 续写|重写 → stitched; 原样保存 → raw; 其他 → trimmed。
        英文下对应的关键词 (regenerated without thinking / continuation / as is) 必须还在, 前端才能用同样的规则给英文文字分类。"""
        def kind(changes, lang):
            text = "\n".join(changes)
            patterns = [("rescued", "改为不思考"), ("stitched", "续写|重写"), ("raw", "原样保存")] if lang == "zh" else \
                [("rescued", "regenerated without thinking"), ("stitched", "continuation"), ("raw", "as is")]
            for name, pattern in patterns:
                if re.search(pattern, text):
                    return name
            return "trimmed"
        seen = set()
        for name, raw, html, trace, en, zh in self.cases():
            with i18n.use_lang("en"):
                got_en = gen.describe_changes(raw, html, trace)
            with i18n.use_lang("zh"):
                got_zh = gen.describe_changes(raw, html, trace)
            with self.subTest(case=name):
                self.assertEqual(kind(got_en, "en"), kind(got_zh, "zh"), (got_en, got_zh))
            seen.add(kind(got_zh, "zh"))
        # rescued: 存进结果的说明本身 (按任务语言生成), 中英文各两种
        for lang, texts in (("en", ["Thinking got stuck in repetition and no code was written; regenerated without thinking",
                                    "Thinking used up the output limit and no code was written; regenerated without thinking"]),
                            ("zh", ["思考过程陷入重复，没写出代码；改为不思考、直接重新生成", "思考过程用完了输出长度，没写出代码；改为不思考、直接重新生成"])):
            for text in texts:
                with i18n.use_lang(lang):
                    got = gen.describe_changes(DOC, DOC, self.trace(rescued=text))
                self.assertEqual(kind(got, lang), "rescued", got)
                seen.add(kind(got, lang))
        self.assertEqual(seen, {"raw", "trimmed", "stitched", "rescued"})     # 四类都有例子, 上面的比较才有意义


# ================================================================ gen: gen_complete 的日志和 trace (本地模拟服务)

FIRST = "<!doctype html><html><body>\n<p>partial"
LOOP_TEXT = "<!doctype html><html><body><svg><path d='M0 0 " + "t60 0 " * 20000
SIMILAR_TEXT = "<!doctype html><html><body><script>\n" + "".join(
    "const LANE_TOP_LX%d=340, LANE_TOP_RX%d=386, LANE_TOP_LY%d=170;\n" % (i, i, i) for i in range(1000, 3000))
RESTART_MARK = "直接输出完整 HTML 代码"          # gen_complete 思考耗尽后重新生成时追加给模型的提示 (测试内容)


class TestGenCompleteLogs(LangCase):
    def complete(self, handler, lang="en", thinking=False, tier_max=100):
        m = MockServer(handler)
        trace = {}
        try:
            with (english_flow() if lang == "en" else zh_flow()) as flow:
                gen.gen_complete(m.url + "/v1/chat/completions", "m", "PROMPT", tier_max, {}, thinking=thinking, trace=trace)
        finally:
            m.close()
        lines = flow.lines if lang == "en" else flow
        return flow, lines, trace

    def test_continuation_failure_keeps_the_partial_text(self):
        def h(method, path, body):
            return stream(FIRST, finish="length") if len(body["messages"]) == 1 else (500, {"error": "boom"}, None)
        flow, lines, trace = self.complete(h)
        self.assertEqual(lines, ["    ↻ Truncated; continuation round 1 (thinking off, output code directly)",
                                 "    ⚠ Continuation failed; keeping the part generated so far: HTTP Error 500: Internal Server Error"])
        flow.assert_clean(self, trace, keys=STORED_TEXT_KEYS)
        self.assertEqual(trace["rounds"][1]["error"], "HTTP Error 500: Internal Server Error")
        _, zh, _ = self.complete(h, lang="zh")
        self.assertEqual(zh, ["    ↻ 截断, 续写第 1 轮(关闭思考直出代码)",
                              "    ⚠ 续写失败, 保留已生成部分: HTTP Error 500: Internal Server Error"])

    def test_whole_file_reoutput(self):
        def h(method, path, body):
            return stream(FIRST, finish="length") if len(body["messages"]) == 1 else stream("<!doctype html><html><body>again</body></html>")
        flow, lines, trace = self.complete(h)
        self.assertEqual(lines[1], "    ↻ The continuation re-output the whole file from the start; using the new content")
        self.assertEqual(trace["rounds"][1]["join"], {"replaced": True})
        flow.assert_clean(self)
        _, zh, _ = self.complete(h, lang="zh")
        self.assertEqual(zh[1], "    ↻ 续写从头重新输出了整个文件, 改用新内容")

    def test_repetition_in_the_answer_stops_generation(self):
        for name, text, en, zh in (
                ("loop", LOOP_TEXT,
                 r"^    ⚠ Model stuck in repetition \(a \d+-character cycle repeated \d+ times\); stopped generating, no continuation$",
                 r"^    ⚠ 模型陷入重复输出\(每 \d+ 个字符循环一次，已重复 \d+ 次\), 停止生成、不再续写$"),
                ("similar", SIMILAR_TEXT,
                 r"^    ⚠ Model stuck in repetition \(the last few thousand characters are highly repetitive: compression ratio \d\.\d\d, "
                 r"normal code is around 0\.2 or higher\); stopped generating, no continuation$",
                 r"^    ⚠ 模型陷入重复输出\(最近几千字内容高度雷同（压缩率 \d\.\d\d，正常代码约 0\.2 以上）\), 停止生成、不再续写$")):
            def h(method, path, body):
                return stream(text, finish="length", chunk=500)
            with self.subTest(kind=name):
                flow, lines, trace = self.complete(h, tier_max=100000)
                self.assertEqual(len(lines), 1, lines)
                self.assertRegex(lines[0], en)
                self.assertEqual(trace["degenerate"]["kind"], "loop" if name == "loop" else "similar")
                flow.assert_clean(self, trace, keys=STORED_TEXT_KEYS)
                _, zh_lines, _ = self.complete(h, lang="zh", tier_max=100000)
                self.assertRegex(zh_lines[0], zh)

    def test_thinking_that_produces_no_code_is_rescued_and_the_note_is_stored_in_the_task_language(self):
        good = "```html\n" + GOOD_HTML + "\n```"

        def loop(method, path, body):
            if RESTART_MARK in body["messages"][0]["content"]:
                return stream(good)
            return stream("", reasoning="think again " * 3000, finish="length", chunk=400)

        def exhausted(method, path, body):
            if RESTART_MARK in body["messages"][0]["content"]:
                return stream(good)
            return stream("", reasoning=" ".join("w%d" % i for i in range(300)), finish="length")
        for handler, en_line, en_note, zh_note in (
                (loop, "    ⚠ Thinking stuck in repetition; stopped thinking",
                 "Thinking got stuck in repetition and no code was written; regenerated without thinking",
                 "思考过程陷入重复，没写出代码；改为不思考、直接重新生成"),
                (exhausted, None, "Thinking used up the output limit and no code was written; regenerated without thinking",
                 "思考过程用完了输出长度，没写出代码；改为不思考、直接重新生成")):
            with self.subTest(note=en_note[:20]):
                flow, lines, trace = self.complete(handler, thinking=True, tier_max=100000)
                if en_line:
                    self.assertIn(en_line, lines)
                self.assertIn("    ↻ Truncated; continuation round 1 (thinking off, output code directly)", lines)
                self.assertEqual(trace["rescued"], en_note)
                flow.assert_clean(self)
                assert_english(self, trace["rescued"])
                _, zh_lines, zh_trace = self.complete(handler, lang="zh", thinking=True, tier_max=100000)
                self.assertEqual(zh_trace["rescued"], zh_note)

    def test_still_unfinished_after_four_rounds(self):
        def h(method, path, body):
            n = len(body["messages"])
            return stream("\nchunk %d line\nx = %d;\n" % (n, n), finish="length")
        flow, lines, trace = self.complete(h)
        self.assertEqual(lines[-1], "    ⚠ Still unfinished after 4 continuation rounds")
        self.assertEqual([x for x in lines if x.startswith("    ↻")],
                         ["    ↻ Truncated; continuation round %d (thinking off, output code directly)" % k for k in (1, 2, 3)])
        self.assertTrue(trace["unfinished"])
        flow.assert_clean(self)
        _, zh, _ = self.complete(h, lang="zh")
        self.assertEqual(zh[-1], "    ⚠ 续写 4 轮仍未闭合")
        with i18n.use_lang("en"):                                                   # 单数: 现在走不到, 词条也要对
            self.assertEqual(i18n.tn("    ⚠ 续写 {n} 轮仍未闭合", 1), "    ⚠ Still unfinished after 1 continuation round")


# ================================================================ gen: run_gen 整个流程 (英文 / 中文)

def mixed_handler(method, path, body):
    """按题目分派: A 正常 (带说明文字和代码块标记), B 请求失败, D 没有 HTML, E 陷入重复。"""
    prompt = body["messages"][0]["content"]
    if "page A" in prompt:
        return stream(FENCED)
    if "page B" in prompt:
        return 500, {"error": "boom"}, None
    if "page E" in prompt:
        return stream("·" * 30000, finish="length", chunk=400)
    return stream("hello")


def thinking_handler(method, path, body):
    """思考模式: F 拼接两轮续写 (带说明文字), G 思考耗尽没写出正文, H 思考耗尽后改为不思考重新生成成功。"""
    msgs = body["messages"]
    prompt = msgs[0]["content"]
    if "page F" in prompt:
        if len(msgs) == 1:
            return stream("Here you go:\n```html\n<!doctype html><html><head><title>t</title></head><body><canvas></canvas><script>\n"
                          "let simYears = 1;\nfunction step(){ simYe", finish="length")
        return stream("ars += 1; }requestAnimationFrame(step);/*" + "y" * 250 + "*/\n</script></body></html>\n```\nHope it helps.")
    if "page G" in prompt:
        return stream("", reasoning="x" * 50)
    if RESTART_MARK in prompt:
        return stream("```html\n" + GOOD_HTML + "\n```")
    return stream("", reasoning=" ".join("w%d" % i for i in range(300)), finish="length")


class TestRunGen(LangCase):
    def test_english_run_logs_stored_errors_and_changes_have_no_chinese(self):
        flow, doc, traces = run_gen_doc(mixed_handler, ["t_ok", "t_fail", "t_plain", "t_loop"])
        lines = flow.lines
        self.assertRegex(lines[0], r'^== gen v2\.3\.0 \| m \| 4 questions \| conc=1 \| sampling \{.*\} \| evaluation: code-only check \(browser not found\) ==$')
        self.assertEqual(lines[1], "▶ Started: Page A (Basic/Animation)")
        self.assertEqual(lines[2], "  ✓ [Page A] runtime check 1/2 (failed: Check B) · 1 line · progress 1/4")
        self.assertEqual(lines[3], "▶ Started: Page B (Basic)")
        self.assertEqual(lines[4], "  ✗ [Page B] Failed: HTTP Error 500: Internal Server Error · progress 2/4")
        self.assertEqual(lines[5:7], ["▶ Started: Page D (Hard)", "  ✗ [Page D] No valid HTML in the output (5 characters extracted) · progress 3/4"])
        self.assertEqual(lines[7], "▶ Started: Page E (Real-world)")
        self.assertRegex(lines[8], r"^    ⚠ Model stuck in repetition \(a 1-character cycle repeated \d+ times\); stopped generating, no continuation$")
        self.assertEqual(lines[9], "  ✗ [Page E] The model got stuck in repetition and did not produce valid HTML · progress 4/4")
        self.assertRegex(lines[10], r"^done => ")
        self.assertEqual(len(lines), 11, lines)
        errors = {it["id"]: it["error"] for it in doc["items"] if it.get("error")}
        self.assertEqual(errors["t_plain"], "No valid HTML in the output (5 characters extracted)")
        self.assertEqual(errors["t_loop"], "The model got stuck in repetition and did not produce valid HTML")
        self.assertTrue(errors["t_fail"].startswith("HTTP Error 500: Internal Server Error"))
        ok = next(it for it in doc["items"] if it["id"] == "t_ok")
        self.assertEqual(ok["changes"], ['Removed explanatory text before the code (12 characters) and code fence markers: "Here you go:"',
                                         "Removed the Markdown code fence after the code"])
        self.assertEqual(traces["t_ok"]["changes"], ok["changes"])
        flow.assert_clean(self, doc, keys=STORED_TEXT_KEYS)
        assert_english(self, [it.get("changes") for it in doc["items"]], what="changes")
        for tid, trace in traces.items():
            assert_english(self, [trace.get("changes"), trace.get("rescued")], what="trace " + tid)
            assert_english(self, trace, keys=STORED_TEXT_KEYS, what="trace " + tid)

    def test_chinese_run_is_unchanged(self):
        flow, doc, traces = run_gen_doc(mixed_handler, ["t_ok", "t_fail", "t_plain", "t_loop"], lang="zh")
        lines = flow
        self.assertRegex(lines[0], r'^== gen v2\.3\.0 \| m \| 4 题 \| conc=1 \| 采样 \{.*\} \| 评测: 源码检查\(未找到浏览器\) ==$')
        self.assertEqual(lines[1], "▶ 开始: Page A (Basic/Animation)")
        self.assertEqual(lines[2], "  ✓ [Page A] 运行检测 1/2（未通过：Check B） · 1 行 · 进度 1/4")
        self.assertEqual(lines[4], "  ✗ [Page B] 失败: HTTP Error 500: Internal Server Error · 进度 2/4")
        self.assertEqual(lines[6], "  ✗ [Page D] 输出中没有有效的 HTML(提取到 5 字) · 进度 3/4")
        self.assertRegex(lines[8], r"^    ⚠ 模型陷入重复输出\(每 1 个字符循环一次，已重复 \d+ 次\), 停止生成、不再续写$")
        self.assertEqual(lines[9], "  ✗ [Page E] 模型陷入重复输出，没有写出有效的 HTML · 进度 4/4")
        self.assertRegex(lines[10], r"^完成 => ")
        ok = next(it for it in doc["items"] if it["id"] == "t_ok")
        self.assertEqual(ok["changes"], ["去掉了代码前面的说明文字（12 个字符）和代码块标记：「Here you go:」", "去掉了代码后面的 Markdown 代码块标记"])

    def test_thinking_mode_stored_notes_and_failures(self):
        flow, doc, traces = run_gen_doc(thinking_handler, ["t_cont", "t_think", "t_rescue"], thinking=True)
        lines = flow.lines
        self.assertRegex(lines[0], r'^== gen v2\.3\.0 \| m \| 3 questions \| conc=1 \| sampling \{"temperature": 0\.6, .*\} \| evaluation: code-only check')
        self.assertIn("    ↻ Truncated; continuation round 1 (thinking off, output code directly)", lines)
        self.assertIn("  ✗ [Page G] Thinking used up the output limit without producing an answer (50 characters of thinking) · progress 2/3", lines)
        items = {it["id"]: it for it in doc["items"]}
        self.assertEqual(items["t_think"]["error"], "Thinking used up the output limit without producing an answer (50 characters of thinking)")
        self.assertEqual(items["t_cont"]["changes"][0], "Joined continuation round 2 (appended directly)")
        self.assertEqual(items["t_cont"]["changes"][1:],
                         ['Removed explanatory text before the code (12 characters) and code fence markers: "Here you go:"',
                          'Removed explanatory text after the code (14 characters) and code fence markers: "Hope it helps."'])
        rescue = "Thinking used up the output limit and no code was written; regenerated without thinking"
        self.assertEqual(items["t_rescue"]["rescued"], rescue)                       # 作品条目里的摘要
        self.assertEqual(traces["t_rescue"]["rescued"], rescue)                      # <题>.gen.json 里的
        self.assertEqual(items["t_rescue"]["changes"][0], rescue)
        flow.assert_clean(self, doc, keys=STORED_TEXT_KEYS)
        assert_english(self, [it.get("changes") for it in doc["items"]] + [it.get("rescued") for it in doc["items"]], what="notes")
        # 思考失败的只有一个字的情况: 单数
        flow, doc, _ = run_gen_doc(lambda m, p, b: stream("", reasoning="x"), ["t_think"], thinking=True)
        self.assertEqual(doc["items"][0]["error"], "Thinking used up the output limit without producing an answer (1 character of thinking)")
        flow, doc, _ = run_gen_doc(thinking_handler, ["t_think"], thinking=True, lang="zh")
        self.assertEqual(doc["items"][0]["error"], "思考耗尽未产出正文(思考50字)")

    def test_judge_model_shows_in_the_header_and_the_summary(self):
        flow, doc, _ = run_gen_doc(lambda m, p, b: stream(FENCED), ["t_ok"], judge={"base": "http://127.0.0.1:1", "model": "judge-m"})
        self.assertRegex(flow.lines[0], r"^== gen v2\.3\.0 \| m \| 1 question \| conc=1 \| sampling \{.*\} \| evaluation: code-only check \(browser not found\) \+ visual review judge-m ==$")
        self.assertRegex(flow.lines[2], r"^  ✓ \[Page A\] runtime check 1/2 \(failed: Check B\) · review score 85 · 1 line · progress 1/1$")
        flow.assert_clean(self, doc, keys=STORED_TEXT_KEYS)
        flow, doc, _ = run_gen_doc(lambda m, p, b: stream(FENCED), ["t_ok"], lang="zh", judge={"base": "http://127.0.0.1:1", "model": "judge-m"})
        self.assertRegex(flow[0], r"评测: 源码检查\(未找到浏览器\) \+ 视觉评审 judge-m ==$")
        self.assertRegex(flow[2], r"^  ✓ \[Page A\] 运行检测 1/2（未通过：Check B） · 评审 85 分 · 1 行 · 进度 1/1$")

    def test_cancel_message_stored_and_logged(self):
        for done, en_line, zh_line in ((1, "Cancelled: kept 1 completed generated page", "已取消: 保留已完成的 1 件作品"),
                                       (0, "Cancelled: kept 0 completed generated pages", "已取消: 保留已完成的 0 件作品")):
            for lang in ("en", "zh"):
                cancel = threading.Event()
                if not done:
                    cancel.set()
                state = {"n": 0}

                def h(method, path, body):
                    state["n"] += 1
                    if state["n"] >= 2:
                        cancel.set()
                    return stream(FENCED)
                with self.subTest(done=done, lang=lang):
                    flow, doc, _ = run_gen_doc(h, ["t_ok", "t_plain", "t_fail"], lang=lang, cancel=cancel)
                    lines = flow.lines if lang == "en" else flow
                    self.assertIn(en_line if lang == "en" else zh_line, lines)
                    self.assertEqual((doc["status"], doc["error"]), ("cancelled", "Cancelled by user" if lang == "en" else "用户取消"))
                    if lang == "en":
                        flow.assert_clean(self, doc, keys=STORED_TEXT_KEYS)

    def test_cancel_after_generation_before_evaluation(self):
        cancel = threading.Event()
        orig = gen.extract_html
        with mock.patch.object(gen, "extract_html", lambda resp: (cancel.set(), orig(resp))[1]):
            flow, doc, _ = run_gen_doc(lambda m, p, b: stream(FENCED), ["t_ok"], cancel=cancel)
        self.assertIn("  · [Page A] Generated; cancelled before evaluation", flow.lines)
        self.assertIn("  ✓ [Page A] generated, not evaluated · progress 1/1", flow.lines)
        flow.assert_clean(self, doc, keys=STORED_TEXT_KEYS)

    def test_trace_file_failure_is_logged(self):
        real_open = open

        def fake_open(path, *a, **kw):
            if str(path).endswith(".gen.json.tmp"):
                raise OSError("disk full")
            return real_open(path, *a, **kw)
        with mock.patch.object(gen, "open", fake_open, create=True):
            flow, doc, _ = run_gen_doc(lambda m, p, b: stream(FENCED), ["t_ok"])
        self.assertIn("  ⚠ [Page A] Failed to save the raw output: disk full", flow.lines)
        flow.assert_clean(self, doc, keys=STORED_TEXT_KEYS)
        with mock.patch.object(gen, "open", fake_open, create=True):
            flow, doc, _ = run_gen_doc(lambda m, p, b: stream(FENCED), ["t_ok"], lang="zh")
        self.assertIn("  ⚠ [Page A] 原始输出留档失败: disk full", flow)

    def test_bad_arguments_raise_translated_errors_before_anything_starts(self):
        m = MockServer(lambda *a: stream(FENCED))
        try:
            with gen_env() as tmp:
                sink = sinks.JsonFileSink(os.path.join(tmp, "results"))
                for lang, msgs in (("en", ["Unknown question ID: nope", "Select at least 1 question",
                                           "Sampling parameter temperature must be between 0.0 and 2.0 (got 9.0)"]),
                                   ("zh", ["未知题目：nope", "请至少选择 1 道题目", "采样参数 temperature 应在 0.0 到 2.0 之间: 9.0"])):
                    with i18n.use_lang(lang):
                        for kw, want in zip(({"task_ids": ["nope"]}, {"task_ids": []}, {"sampling": {"temperature": 9}}), msgs):
                            with self.assertRaises(ValueError) as cm:
                                gen.run_gen(m.url, "m", sink=sink, **kw)
                            self.assertEqual(str(cm.exception), want)
                self.assertEqual(m.calls, [])
        finally:
            m.close()


class TestReevaluate(LangCase):
    def make_run(self, tmp, tasks=("t_ok", "t_plain")):
        """先用 run_gen 在库里生成一个运行 (中文模式, 不关心日志), 返回 (run_id, 库路径)。"""
        db = os.path.join(tmp, "re.db")
        m = MockServer(lambda method, path, body: stream(FENCED))
        try:
            sink = sinks.SqliteSink(db)
            with zh_flow():
                gen.run_gen(m.url + "/v1/chat/completions", "m", task_ids=list(tasks), conc=1, sink=sink)
        finally:
            m.close()
        return sink.run_id, db

    def re_eval(self, run_id, db, lang="en", **kw):
        lines = []
        flow = english_flow() if lang == "en" else zh_flow()
        with flow as f:
            outcome = None
            try:
                gen.reevaluate(run_id, db_path=db, browsers=1, log=lines.append, **kw)
            except Exception as e:      # noqa: BLE001
                outcome = e
        return f, lines, outcome

    def test_progress_lines_and_final_line_in_english_and_chinese(self):
        with gen_env() as tmp:
            run_id, db = self.make_run(tmp)
            f, lines, err = self.re_eval(run_id, db)
            self.assertIsNone(err)
            self.assertEqual(lines[0], "== re-evaluation %s | 2 generated pages | static ==" % run_id)
            self.assertRegex(lines[1], r"^  ✓ \[Page A\] runtime check 1/2 \(failed: Check B\) · 1 line · progress 1/2$")
            self.assertRegex(lines[2], r"^  ✓ \[Page D\] runtime check 1/2 \(failed: Check B\) · 1 line · progress 2/2$")
            self.assertEqual(lines[-1], "Re-evaluation done")
            f.assert_clean(self)
            f, lines, err = self.re_eval(run_id, db, lang="zh")
            self.assertEqual(lines[0], "== 重新评测 %s | 2 件作品 | static ==" % run_id)
            self.assertRegex(lines[1], r"^  ✓ \[Page A\] 运行检测 1/2（未通过：Check B） · 1 行 · 进度 1/2$")
            self.assertEqual(lines[-1], "重新评测完成")
            f, lines, err = self.re_eval(run_id, db, only={"t_ok"})
            self.assertEqual(lines[0], "== re-evaluation %s | 1 generated page | static ==" % run_id)      # 单数
            f, lines, err = self.re_eval(run_id, db, judge={"base": "http://127.0.0.1:1", "model": "judge-m"})
            self.assertEqual(lines[0], "== re-evaluation %s | 2 generated pages | static + visual review judge-m ==" % run_id)
            self.assertRegex(lines[1], r"review score 85 · ")
            f.assert_clean(self)

    def test_missing_file_and_kept_results(self):
        with gen_env() as tmp:
            run_id, db = self.make_run(tmp)
            doc = store.get_run(run_id, db_path=db)
            for it in doc["items"]:                                        # 上次是浏览器检测, 这次 (假评测器) 是源码检查: 保留上次的
                it["eval"]["method"] = "browser"
                store.update_gen_item(run_id, it, db_path=db)
            f, lines, err = self.re_eval(run_id, db)
            self.assertEqual(lines[1:3], ["  · [Page A] Browser check failed; keeping the previous runtime check and review",
                                          "  · [Page D] Browser check failed; keeping the previous runtime check and review"])
            f.assert_clean(self)
            f, lines, err = self.re_eval(run_id, db, lang="zh")
            self.assertEqual(lines[1], "  · [Page A] 浏览器检测失败，保留上次的运行检测和评审")
            for it in doc["items"]:
                os.remove(gen.work_path(it["file"]))
            f, lines, err = self.re_eval(run_id, db)
            self.assertEqual(lines[1], "  ✗ [Page A] Generated page file is missing: works/%s/t_ok.html" % run_id)
            f.assert_clean(self)
            f, lines, err = self.re_eval(run_id, db, lang="zh")
            self.assertEqual(lines[1], "  ✗ [Page A] 作品文件缺失: works/%s/t_ok.html" % run_id)

    def test_unknown_run_and_cancel(self):
        with gen_env() as tmp:
            run_id, db = self.make_run(tmp, tasks=("t_ok",))
            for lang, want in (("en", "Code generation run not found: gen_x"), ("zh", "生成运行不存在: gen_x")):
                f, lines, err = self.re_eval("gen_x", db, lang=lang)
                self.assertIsInstance(err, KeyError)
                self.assertEqual(err.args[0], want)
            for lang, want in (("en", "Re-evaluation cancelled"), ("zh", "重新评测已取消")):
                cancel, seen = threading.Event(), []

                def log(msg):
                    seen.append(msg)
                    if "✓" in msg:
                        cancel.set()          # 最后一件评完时收到取消
                flow = english_flow() if lang == "en" else zh_flow()
                with flow as f:
                    gen.reevaluate(run_id, db_path=db, browsers=1, log=log, cancel=cancel)
                self.assertEqual(seen[-1], want)
                if lang == "en":
                    f.assert_clean(self)


# ================================================================ iq: 不用模型服务的函数

class TestIqTexts(LangCase):
    def both(self, fn, en, zh):
        with i18n.use_lang("en"):
            got = fn()
            self.assertEqual(got, en)
            assert_english(self, got)
        with i18n.use_lang("zh"):
            self.assertEqual(fn(), zh)

    def test_budget_policy(self):
        buds = iq.normalize_budgets({"math500": 128})
        self.both(lambda: iq.budget_policy(buds, True),
                  "Thinking mode: a shared limit of 32768 tokens for thinking and the answer (reduced automatically if it exceeds the context)",
                  "思考模式: 统一上限 32768(思考与正文共享, 超上下文自动收缩)")
        self.both(lambda: iq.budget_policy(buds, False),
                  "Output budget (tokens): multiple choice 16 · GSM8K 2048 · MATH-500 128 · instruction following 320",
                  "输出预算: 选择题 16 · GSM8K 2048 · MATH-500 128 · 指令 320")

    def test_clip_marker_singular_and_plural(self):
        self.assertEqual(iq.clip_text("short"), "short")
        with i18n.use_lang("en"):
            long = iq.clip_text("a" * 3000 + "b" * 4000 + "c" * 4000)
            self.assertTrue(long.startswith("a" * 2000) and long.endswith("c" * 4000))
            self.assertIn("\n… (5000 characters omitted from the middle) …\n", long)
            self.assertEqual(iq.clip_text("a" * 11, keep=10, head=2), "aa\n… (1 character omitted from the middle) …\n" + "a" * 8)
            assert_english(self, long)
        with i18n.use_lang("zh"):
            self.assertIn("\n…（中间省略 5000 字）…\n", iq.clip_text("a" * 3000 + "b" * 4000 + "c" * 4000))
            self.assertEqual(iq.clip_text("a" * 11, keep=10, head=2), "aa\n…（中间省略 1 字）…\n" + "a" * 8)

    def test_rule_texts(self):
        cases = [({"t": "max_chars", "v": 50}, "At most 50 characters", "不超过 50 个字"),
                 ({"t": "max_chars", "v": 1}, "At most 1 character", "不超过 1 个字"),
                 ({"t": "min_chars", "v": 20}, "At least 20 characters", "至少 20 个字"),
                 ({"t": "min_chars", "v": 1}, "At least 1 character", "至少 1 个字"),
                 ({"t": "max_words", "v": 5}, "At most 5 English words", "不超过 5 个英文单词"),
                 ({"t": "max_words", "v": 1}, "At most 1 English word", "不超过 1 个英文单词"),
                 ({"t": "contains", "v": "spring"}, 'Must contain "spring"', "必须包含“spring”"),
                 ({"t": "not_contains", "v": "very"}, 'Must not contain "very"', "不能出现“very”"),
                 ({"t": "starts_with", "v": "Hi"}, 'Starts with "Hi"', "以“Hi”开头"),
                 ({"t": "ends_with", "v": "."}, 'Ends with "."', "以“.”结尾"),
                 ({"t": "line_count", "v": 3}, "Exactly 3 lines", "正好 3 行"),
                 ({"t": "line_count", "v": 1}, "Exactly 1 line", "正好 1 行"),
                 ({"t": "line_count", "v": 0}, "Exactly 0 lines", "正好 0 行"),
                 ({"t": "regex", "v": "^81$"}, "Matches the format required by the question", "格式符合题目要求"),
                 ({"t": "json_keys", "v": ["name", "age"]}, "Is valid JSON and contains the keys name, age", "是合法的 JSON，且包含 name、age"),
                 ({"t": "json_keys", "v": ["name"]}, "Is valid JSON and contains the keys name", "是合法的 JSON，且包含 name"),
                 ({"t": "json_equals", "v": {"ok": True}}, 'JSON content equals {"ok": true}', 'JSON 内容等于 {"ok": true}'),
                 ({"t": "weird", "v": 3}, "weird 3", "weird 3")]
        for ck, en, zh in cases:
            with self.subTest(rule=ck):
                self.both(lambda: iq.rule_text(ck), en, zh)
        with i18n.use_lang("en"):
            self.assertEqual(iq.rule_info({"t": "regex", "v": "^81$"}), {"text": "Matches the format required by the question", "tech": "^81$"})

    def test_instruct_detail_actual_counts(self):
        def details(text, check, lang):
            with i18n.use_lang(lang):
                return iq.instruct_detail(text, {"q": "not in the built-in rules", "checks": [check]})
        for check, text, en, zh in (({"t": "max_chars", "v": 50}, "x" * 60, "Actual: 60 characters", "实际 60 字"),
                                    ({"t": "min_chars", "v": 5}, "x", "Actual: 1 character", "实际 1 字"),
                                    ({"t": "max_words", "v": 3}, "one two three four", "Actual: 4 words", "实际 4 个单词"),
                                    ({"t": "max_words", "v": 3}, "one", "Actual: 1 word", "实际 1 个单词"),
                                    ({"t": "line_count", "v": 2}, "a\nb\nc", "Actual: 3 lines", "实际 3 行"),
                                    ({"t": "line_count", "v": 1}, "a", "Actual: 1 line", "实际 1 行")):
            with self.subTest(check=check, text=text):
                self.assertEqual(details(text, check, "en")[0]["actual"], en)
                self.assertEqual(details(text, check, "zh")[0]["actual"], zh)
        row = details("abc", {"t": "contains", "v": "x"}, "en")[0]
        self.assertEqual(row, {"text": 'Must contain "x"', "pass": False})              # 没有数量的规则不带 actual
        for item in bankman.ifeval_zh_items():                                        # 内置规则: 不含题库数据的几类, 英文下没有汉字
            with i18n.use_lang("en"):
                det = iq.instruct_detail("春天来了。", item)
            self.assertEqual(all(r["pass"] for r in det), iq.judge_instruct("春天来了。", item))
            for ck, row in zip(iq.instruct_rules(item), det):
                if ck["t"] in ("max_chars", "min_chars", "max_words", "line_count", "regex"):
                    assert_english(self, [row["text"], row.get("actual", "")], what=str(ck))

    def test_run_warnings(self):
        def result(n_ok, with_thinking_share, thinking, ignored=None, n_err=0):
            items = [{"sid": "s", "idx": i, "ok": True, "rc": 100 if i < int(n_ok * with_thinking_share) else 0} for i in range(n_ok)]
            items += [{"sid": "s", "idx": 100 + i, "ok": False, "err": "boom"} for i in range(n_err)]
            d = {"items": items, "thinking": thinking}
            if ignored is not None:
                d["ignored_params"] = ignored
            return d
        self.both(lambda: iq.run_warnings(result(20, 0.05, True)),
                  ["Thinking mode may not be in effect: only 5% of the answers contain thinking content; the endpoint may not support "
                   "enable_thinking, or the model template may use a different switch name"],
                  ["思考模式可能未生效：仅 5% 的回答包含思考内容。端点可能不支持 enable_thinking，或模型模板的开关名称不同"])
        self.both(lambda: iq.run_warnings(result(20, 0.6, False)),
                  ["In non-thinking mode, 60% of the answers still contain thinking content, so the thinking switch may not be working "
                   "and short-output questions such as multiple choice may be cut off by the output limit"],
                  ["非思考模式下仍有 60% 的回答包含思考内容，思考开关可能未生效，选择题等短输出题可能因输出上限被截断"])
        self.both(lambda: iq.run_warnings(result(20, 0, False, ["top_k", "seed"])),
                  ["The endpoint does not support these parameters, so they were removed automatically: top_k, seed"],
                  ["端点不支持以下参数，已自动去掉：top_k、seed"])
        self.both(lambda: iq.run_warnings(result(20, 0, False, n_err=1)),
                  ["1 question request failed (counted as incorrect); resume the run to retry it"],
                  ["1 题请求失败（计为答错），可续跑重试这些题"])
        self.both(lambda: iq.run_warnings(result(20, 0, False, n_err=3)),
                  ["3 question requests failed (counted as incorrect); resume the run to retry them"],
                  ["3 题请求失败（计为答错），可续跑重试这些题"])
        self.assertEqual(iq.run_warnings(result(20, 0, False)), [])


# ================================================================ iq: run_iq 整个流程 (英文 / 中文)

def mk_bank(n_subjects=2, n_items=6, kinds=("mcq",)):
    return {"bank_id": "test-bank", "subjects": [
        {"id": "s%d" % k, "name": "S%d" % k, "type": kinds[k % len(kinds)],
         "items": [{"q": "q%d-%d" % (k, i), "choices": list("abcd"), "answer": "B"} for i in range(n_items)]} for k in range(n_subjects)]}


def run_iq_doc(handler, bank, lang="en", **kw):
    """在某个语言下跑一遍 run_iq (本地模拟服务), 返回 (日志, 结果文档, 抛出的异常或 None)。"""
    m = MockServer(handler)
    err = None
    try:
        sink = sinks.JsonFileSink(temp_dir())
        with (english_flow() if lang == "en" else zh_flow()) as flow:
            try:
                iq.run_iq(m.url + "/v1/chat/completions", "m", bank=bank, sink=sink, conc=1, **kw)
            except Exception as e:      # noqa: BLE001
                err = e
        doc = load_json(sink.path) if sink.run_id else None
    finally:
        m.close()
    return flow, doc, err


class TestRunIq(LangCase):
    def test_english_run_logs_and_stored_texts_have_no_chinese(self):
        def h(method, path, body):
            prompt = body["messages"][0]["content"]
            if "q0-1" in prompt:
                return 500, {"error": "boom"}, None
            if "q0-2" in prompt:
                return 200, chat_reply("", finish="length", completion_tokens=16, reasoning="r" * 30), None
            return 200, chat_reply("B"), None
        flow, doc, err = run_iq_doc(h, mk_bank(2, 6))
        self.assertIsNone(err)
        lines = flow.lines
        self.assertRegex(lines[0], r'^== iq v1\.4\.0 \| m \| bank=test-bank \| 12 questions \| conc=1 \| non-thinking \| sampling \{"temperature": 0\.0\} ==$')
        subject_lines = [x for x in lines if x.startswith("  [s")]
        self.assertEqual(len(subject_lines), 2)
        self.assertRegex(subject_lines[0], r"^  \[s0\] 4/6 = 66\.7% \(CI \d+\.\d-\d+\.\d\)  truncated 1  failed requests 1$")
        self.assertRegex(subject_lines[1], r"^  \[s1\] 6/6 = 100\.0% \(CI \d+\.\d-100\.0\)$")
        self.assertIn("  progress 12/12", lines)
        warning = "1 question request failed (counted as incorrect); resume the run to retry it"
        self.assertEqual(doc["warnings"], [warning])
        self.assertIn("  ⚠ " + warning, lines)
        self.assertRegex(lines[-1], r"^Overall: 10/12 = 83\.3% \(CI \d+\.\d-\d+\.\d, subject average 83\.3%\) => ")
        self.assertEqual(doc["max_tokens_policy"], "Output budget (tokens): multiple choice 16 · GSM8K 2048 · MATH-500 4096 · instruction following 320")
        flow.assert_clean(self, doc, keys=STORED_TEXT_KEYS)
        flow_zh, doc_zh, _ = run_iq_doc(h, mk_bank(2, 6), lang="zh")
        self.assertRegex(flow_zh[0], r"^== iq v1\.4\.0 \| m \| bank=test-bank \| 12 题 \| conc=1 \| 非思考 \| 采样 \{\"temperature\": 0\.0\} ==$")
        zh_subject = [x for x in flow_zh if x.startswith("  [s")]
        self.assertRegex(zh_subject[0], r"^  \[s0\] 4/6 = 66\.7% \(CI \d+\.\d-\d+\.\d\)  截断1  请求失败1$")
        self.assertEqual(doc_zh["warnings"], ["1 题请求失败（计为答错），可续跑重试这些题"])
        self.assertIn("  ⚠ 1 题请求失败（计为答错），可续跑重试这些题", flow_zh)
        self.assertEqual(doc_zh["max_tokens_policy"], "输出预算: 选择题 16 · GSM8K 2048 · MATH-500 4096 · 指令 320")
        self.assertRegex(flow_zh[-1], r"^总体: 10/12 = 83\.3% \(CI \d+\.\d-\d+\.\d, 科目宏平均 83\.3%\) => ")

    def test_header_counts_thinking_and_progress_lines(self):
        flow, doc, err = run_iq_doc(lambda m, p, b: (200, chat_reply("B", reasoning="thinking " * 20), None), mk_bank(1, 1), thinking=True)
        self.assertRegex(flow.lines[0], r"\| 1 question \| conc=1 \| thinking mode \(max_tokens≤32768\) \| sampling ")
        self.assertEqual(doc["max_tokens_policy"], "Thinking mode: a shared limit of 32768 tokens for thinking and the answer (reduced automatically if it exceeds the context)")
        flow, doc, err = run_iq_doc(lambda m, p, b: (200, chat_reply("B"), None), {"bank_id": "empty", "subjects": []})
        self.assertRegex(flow.lines[0], r"\| 0 questions \| conc=1 \| non-thinking \| sampling ")
        self.assertRegex(flow.lines[-1], r"^Overall: 0/0 = 0\.0% \(CI 0\.0-0\.0, subject average 0\.0%\) => ")
        flow, doc, err = run_iq_doc(lambda m, p, b: (200, chat_reply("B"), None), mk_bank(1, 45))
        self.assertIn("  progress 20/45", flow.lines)
        self.assertIn("  progress 40/45", flow.lines)
        self.assertIn("  progress 45/45", flow.lines)
        flow.assert_clean(self, doc, keys=STORED_TEXT_KEYS)
        flow, doc, err = run_iq_doc(lambda m, p, b: (200, chat_reply("B"), None), mk_bank(1, 45), lang="zh")
        self.assertIn("  进度 20/45", flow)

    def test_thinking_switch_and_endpoint_parameter_warnings_are_stored_in_english(self):
        flow, doc, err = run_iq_doc(lambda m, p, b: (200, chat_reply("B"), None), mk_bank(2, 8), thinking=True)
        self.assertEqual(doc["warnings"], ["Thinking mode may not be in effect: only 0% of the answers contain thinking content; the endpoint may not "
                                           "support enable_thinking, or the model template may use a different switch name"])
        flow.assert_clean(self, doc, keys=STORED_TEXT_KEYS)

        def reject(method, path, body):
            if "top_k" in body:
                return 400, {"error": "Unrecognized request argument supplied: top_k"}, None
            if "seed" in body:
                return 400, {"error": "Unrecognized request argument supplied: seed"}, None
            return 200, chat_reply("B", reasoning="thinking " * 20), None
        flow, doc, err = run_iq_doc(reject, mk_bank(1, 12), thinking=True)
        self.assertEqual(doc["warnings"], ["The endpoint does not support these parameters, so they were removed automatically: seed, top_k"])
        self.assertIn("  ⚠ The endpoint does not support these parameters, so they were removed automatically: seed, top_k", flow.lines)
        flow.assert_clean(self, doc, keys=STORED_TEXT_KEYS)
        flow, doc, err = run_iq_doc(reject, mk_bank(1, 12), thinking=True, lang="zh")
        self.assertEqual(doc["warnings"], ["端点不支持以下参数，已自动去掉：seed、top_k"])

    def test_long_answers_get_the_omission_marker_in_the_task_language(self):
        """回答太长时中间插的标记是在线程池的工作线程里生成的: 也要按任务的语言。"""
        bank = {"bank_id": "tb", "subjects": [{"id": "m", "name": "M", "type": "math", "items": [{"q": "two", "answer": "8"}]}]}
        h = lambda m, p, b: (200, chat_reply("x" * 8000 + "\n#### 7"), None)          # noqa: E731
        flow, doc, err = run_iq_doc(h, bank)
        self.assertIn("\n… (2007 characters omitted from the middle) …\n", doc["items"][0]["resp"])
        self.assertTrue(doc["items"][0]["resp"].endswith("#### 7"))
        flow.assert_clean(self)
        flow, doc, err = run_iq_doc(h, bank, lang="zh")
        self.assertIn("\n…（中间省略 2007 字）…\n", doc["items"][0]["resp"])

    @staticmethod
    def cancel_after(k):
        """完成第 k 道题时收到取消: 第 k 个请求先等 0.2 秒 (主循环有时间处理完前面的题) 再置位取消并回答, 之后的请求延迟 0.5 秒
        (主循环先处理完第 k 题、抛取消, 不会再多完成一题), 所以取消时完成的题数是确定的 k。"""
        cancel, state = threading.Event(), {"n": 0}

        def handler(method, path, body):
            state["n"] += 1
            if state["n"] == k:
                time.sleep(0.2)
                cancel.set()
            elif state["n"] > k:
                time.sleep(0.5)
            return 200, chat_reply("B"), None
        return handler, cancel

    def test_cancel_and_resume_messages_with_counts(self):
        for k, en_cancel, en_resume in (
                (3, "Cancelled: 3 questions completed; you can resume it on the page", r"resuming, 3 questions already done ==$"),
                (1, "Cancelled: 1 question completed; you can resume it on the page", r"resuming, 1 question already done ==$")):
            with self.subTest(completed=k):
                handler, cancel = self.cancel_after(k)
                flow, doc, err = run_iq_doc(handler, mk_bank(2, 6), cancel=cancel)
                self.assertIsNone(err)
                self.assertEqual((doc["status"], doc["error"], len(doc["items"])), ("cancelled", "Cancelled by user", k))
                self.assertIn(en_cancel, flow.lines)
                flow.assert_clean(self, doc, keys=STORED_TEXT_KEYS)
                flow2, doc2, err = run_iq_doc(lambda m, p, b: (200, chat_reply("B"), None), mk_bank(2, 6), resume=doc)
                self.assertIsNone(err)
                self.assertRegex(flow2.lines[0], en_resume)
                self.assertEqual((doc2["status"], len(doc2["items"])), ("done", 12))
                flow2.assert_clean(self, doc2, keys=STORED_TEXT_KEYS)
                handler, cancel = self.cancel_after(k)
                flow_zh, doc_zh, err = run_iq_doc(handler, mk_bank(2, 6), lang="zh", cancel=cancel)
                self.assertEqual(doc_zh["error"], "用户取消")
                self.assertIn("已取消: 已完成 %d 题, 可在页面上续跑" % k, flow_zh)
                flow2_zh, doc2_zh, err = run_iq_doc(lambda m, p, b: (200, chat_reply("B"), None), mk_bank(2, 6), lang="zh", resume=doc_zh)
                self.assertRegex(flow2_zh[0], r" \| 续跑, 已有 %d 题 ==$" % k)

    def test_resume_of_another_version_is_refused_with_a_translated_message(self):
        for lang, want in (("en", "This run was made with capability test version 1.0.0; the current version is %s. Scoring differs between "
                                  "versions, so it cannot be resumed. Run the test again instead." % iq.IQ_VERSION),
                           ("zh", "该运行由评测程序 1.0.0 生成，当前为 %s，判分口径不同，不能续跑，请重新运行" % iq.IQ_VERSION)):
            with i18n.use_lang(lang):
                with self.assertRaises(ValueError) as cm:
                    iq.run_iq("http://127.0.0.1:1", "m", bank=mk_bank(), sink=sinks.JsonFileSink(temp_dir()),
                              resume={"iq_version": "1.0.0", "items": [], "subjects": []})
                self.assertEqual(str(cm.exception), want)
                if lang == "en":
                    assert_english(self, str(cm.exception))

    def test_consecutive_failures_abort_message_is_stored_as_the_run_error(self):
        flow, doc, err = run_iq_doc(lambda m, p, b: (503, {"error": "unavailable"}, None), mk_bank(2, 20))
        self.assertIsInstance(err, RuntimeError)
        want = re.compile(r"^Stopped after 10 consecutive failed requests \(latest error: HTTPError: HTTP Error 503: Service Unavailable \| .*\)\. "
                          r"Fix the endpoint and resume the run\.$")
        self.assertRegex(str(err), want)
        self.assertEqual(doc["status"], "failed")
        self.assertRegex(doc["error"], r"^RuntimeError: Stopped after 10 consecutive failed requests")
        flow.assert_clean(self, doc, keys=STORED_TEXT_KEYS)
        flow_zh, doc_zh, err = run_iq_doc(lambda m, p, b: (503, {"error": "unavailable"}, None), mk_bank(2, 20), lang="zh")
        self.assertRegex(str(err), r"^连续 10 题请求失败，已中止（最近错误：HTTPError: HTTP Error 503: Service Unavailable \| .*）。修复端点后可续跑$")
        with i18n.use_lang("en"):                                                   # 单数: 现在走不到 (至少 10 题), 词条也要对
            self.assertEqual(i18n.tn("连续 {n} 题请求失败，已中止（最近错误：{error}）。修复端点后可续跑", 1, error="boom"),
                             "Stopped after 1 consecutive failed request (latest error: boom). Fix the endpoint and resume the run.")


# ================================================================ 带数量的句子: 每一条 tn 词条 0 / 1 / 多 都对

class TestCountedSentences(LangCase):
    def test_every_counted_sentence_has_a_singular_and_a_plural_form(self):
        """gen.py / iq.py 里用了 tn() 的每一句: 英文 n == 1 用单数, 0 和多个用复数, 数字和占位符都填进去了 (有的数量在流程里走不到, 这里逐条补上)。"""
        import i18n_lint_py as lint
        scan = lint.scan_all()
        calls = {c.key: c for fn in ("gen.py", "iq.py") for c in scan[fn][1] if c.fn == "tn"}
        self.assertGreaterEqual(len(calls), 25)
        with i18n.use_lang("en"):
            for key, call in sorted(calls.items()):
                extra = {name: "X" for name in call.kwargs}
                one, two, zero = (i18n.tn(call.raw, n, ctx=call.ctx, **extra) for n in (1, 2, 0))
                with self.subTest(key=key):
                    self.assertNotEqual(one, two, "单数和复数写成了一样")
                    self.assertEqual(two.replace("2", "0"), zero)                 # 0 用复数
                    if "{n}" in i18n.dictionary("en")[key][0]:                    # 有的句子只靠数量选单复数, 英文里不写数字
                        self.assertIn("1", one)
                        self.assertIn("2", two)
                    assert_english(self, [one, two, zero])
                    self.assertNotIn("{", one + two + zero)                        # 占位符都填了
        self.assertEqual(i18n.MISSING, set())


# ================================================================ 接口和后台任务: 请求的语言传到 gen / iq 的任务线程

class TestGenIqApi(LangServerCase):
    def wait_idle(self, kind, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            st = self.request("GET", "/api/%s" % {"iq": "iq-status", "gen": "gen-status"}[kind])[1]
            if not st["running"]:
                return st
            time.sleep(0.05)
        self.fail("任务没有在 %d 秒内结束" % timeout)

    def test_gen_start_validation_errors_follow_x_lang(self):
        base = {"base": "http://127.0.0.1:1", "model": "m"}
        for body, en, zh in (
                (dict(base, tasks=["nope"]), "Unknown question ID: nope", "未知题目：nope"),
                (dict(base, tasks=["nope", "zzz"]), "Unknown question IDs: nope, zzz", "未知题目：nope、zzz"),
                (dict(base, tasks=[]), "Select at least 1 question", "请至少选择 1 道题目"),
                (dict(base, tasks=5), "tasks must be an array of question IDs", "tasks 应为题目 id 数组"),
                (dict(base, sampling={"temperature": 9}), "Sampling parameter temperature must be between 0.0 and 2.0 (got 9.0)",
                 "采样参数 temperature 应在 0.0 到 2.0 之间: 9.0")):
            with self.subTest(body=body):
                st, msg = self.error_of("POST", "/api/gen-start", body, lang="en")
                self.assertEqual((st, msg), (400, en))
                assert_english(self, msg)
                self.assertEqual(self.error_of("POST", "/api/gen-start", body, lang="zh"), (400, zh))
                self.assertEqual(self.error_of("POST", "/api/gen-start", body), (400, zh))

    def test_question_rules_and_actual_counts_follow_x_lang(self):
        """逐题查看里按要求作答题的检查规则说明 (/api/iq-items) 和实际字数 (/api/iq-answer) 按请求的语言现算, 不存进库。"""
        items = [x for x in bankman.ifeval_zh_items() if any(c["t"] in ("max_chars", "min_chars", "max_words", "line_count") for c in x["checks"])][:4]
        bank = {"bank_id": "ins-bank", "subjects": [{"id": "ins", "name": "INS", "type": "instruct", "items": items}]}
        m = MockServer(lambda method, path, body: (200, chat_reply("春天来了，花都开了。"), None))
        try:
            sink = sinks.SqliteSink()
            with zh_flow():
                iq.run_iq(m.url + "/v1/chat/completions", "m-iq-rules", bank=bank, sink=sink, conc=1)
        finally:
            m.close()
        run_id = sink.run_id
        with mock.patch.object(bankman, "load_bank", lambda bank_id: bank):
            st, en = self.request("GET", "/api/iq-items?id=%s" % run_id, lang="en")
            st, zh = self.request("GET", "/api/iq-items?id=%s" % run_id, lang="zh")
            st, ans_en = self.request("GET", "/api/iq-answer?ids=%s&sid=ins&idx=0" % run_id, lang="en")
            st, ans_zh = self.request("GET", "/api/iq-answer?ids=%s&sid=ins&idx=0" % run_id, lang="zh")
        self.assertTrue(en["ok"] and zh["ok"] and ans_en["ok"] and ans_zh["ok"], (en, ans_en))
        self.assertEqual(len(en["questions"]), len(items))
        with i18n.use_lang("zh"):
            want_zh = [[iq.rule_text(c) for c in iq.instruct_rules(q)] for q in items]
        with i18n.use_lang("en"):
            want_en = [[iq.rule_text(c) for c in iq.instruct_rules(q)] for q in items]
        self.assertEqual([[r["text"] for r in q["rules"]] for q in zh["questions"]], want_zh)
        self.assertEqual([[r["text"] for r in q["rules"]] for q in en["questions"]], want_en)
        self.assertNotEqual(want_en, want_zh)
        for q, ck_list in zip(en["questions"], [iq.instruct_rules(x) for x in items]):
            for row, ck in zip(q["rules"], ck_list):
                if ck["t"] in ("max_chars", "min_chars", "max_words", "line_count", "regex"):
                    assert_english(self, row["text"], what="rule " + str(ck))
        rows_en, rows_zh = ans_en["answers"][run_id]["rules"], ans_zh["answers"][run_id]["rules"]
        actual_en = [r["actual"] for r in rows_en if "actual" in r]
        actual_zh = [r["actual"] for r in rows_zh if "actual" in r]
        self.assertTrue(actual_en and len(actual_en) == len(actual_zh), (rows_en, rows_zh))
        self.assertTrue(all(re.match(r"^Actual: \d+ (character|characters|word|words|line|lines)$", x) for x in actual_en), actual_en)
        self.assertTrue(all(re.match(r"^实际 \d+ (字|个单词|行)$", x) for x in actual_zh), actual_zh)

    def test_gen_job_started_with_x_lang_en_runs_in_english(self):
        m = MockServer(mixed_handler)
        try:
            with gen_env():
                body = {"base": m.url, "model": "m-gen-job", "tasks": ["t_ok", "t_fail", "t_plain"], "conc": 1}
                st, d = self.request("POST", "/api/gen-start", body, lang="en")
                self.assertEqual((st, d.get("ok")), (200, True), d)
                status = self.wait_idle("gen")
                run_id = status["run_id"]
                lines = [x["msg"] for x in status["log"]]
                doc = store.get_run(run_id)
        finally:
            m.close()
        self.assertIsNone(status["error"], status)
        assert_english(self, lines, what="job log")
        self.assertIn("▶ Started: Page A (Basic/Animation)", lines)
        self.assertIn("  ✗ [Page D] No valid HTML in the output (5 characters extracted) · progress 3/3", lines)
        assert_english(self, doc, keys=STORED_TEXT_KEYS, what="stored run")
        items = {it["id"]: it for it in doc["items"]}
        self.assertEqual(items["t_plain"]["error"], "No valid HTML in the output (5 characters extracted)")
        self.assertEqual(items["t_ok"]["changes"][-1], "Removed the Markdown code fence after the code")

    def test_iq_job_started_with_x_lang_en_runs_in_english(self):
        bank = mk_bank(1, 12)
        m = MockServer(lambda method, path, body: (200, chat_reply("B"), None))
        try:
            with mock.patch.object(bankman, "load_bank", lambda bank_id: bank):
                body = {"base": m.url, "model": "m-iq-job", "bank_id": "test-bank", "conc": 1, "thinking": True}
                st, d = self.request("POST", "/api/iq-start", body, lang="en")
                self.assertEqual((st, d.get("ok")), (200, True), d)
                status = self.wait_idle("iq")
                doc = store.get_run(status["run_id"])
        finally:
            m.close()
        self.assertIsNone(status["error"], status)
        lines = [x["msg"] for x in status["log"]]
        assert_english(self, lines, what="job log")
        self.assertTrue(any("thinking mode (max_tokens≤32768)" in x for x in lines), lines)
        self.assertTrue(doc["warnings"][0].startswith("Thinking mode may not be in effect: only 0% of the answers"), doc["warnings"])
        self.assertTrue(doc["max_tokens_policy"].startswith("Thinking mode: a shared limit of 32768 tokens"))
        assert_english(self, doc, keys=STORED_TEXT_KEYS, what="stored run")


if __name__ == "__main__":
    unittest.main()
