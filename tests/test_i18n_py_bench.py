# -*- coding: utf-8 -*-
"""速度测试引擎 (bench.py) 和后台浏览器 (cdp.py) 的中英文测试 (翻译第二阶段, 区域: bench)。约定见 CONTRIBUTING.md「服务端消息与翻译」。

每一块都是「英文的输出没有汉字」加「中文的输出和转换前逐字一致」:
  1. 各阶段的名字和场景名 (存进结果里的显示名) + 一整轮测试的日志 / 结果里的说明 (含放不下的档位、场景失败重跑)
  2. 任务集 / 回放文件的逐行检查 (check_task_line / check_task_text 的原因、提醒、提示) 和 ReplayPool 的报错
  3. 命令行 (bench --help、参数格式错误; cdp --help / --reap / --reap-all)
  4. 服务接口: 上传任务集 / 回放文件的检查报告跟请求头 X-Lang; 页面启动的速度测试按请求的语言存阶段名
  5. cdp.py: 浏览器启动失败的原因、回收遗留浏览器的输出、WebSocket / CDP / PNG 的报错
"""
import base64
import contextlib
import gc
import io
import json
import os
import re
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import warnings
import zlib
from unittest import mock

from _util import MockServer, temp_dir
import i18n
import bench
import cdp
import store
import vision_assets
from test_i18n_py import (LangCase, LangServerCase, STORED_TEXT_KEYS, assert_english, capture_plog, english_flow,
                          limited_server)
import server


def sse(prompt_tokens, out=3):
    chunks = [b'data: {"choices":[{"delta":{"content":"x"}}]}\n\n' for _ in range(out)]
    chunks.append(b'data: {"choices":[],"usage":{"prompt_tokens":%d,"completion_tokens":%d}}\n\ndata: [DONE]\n\n' % (prompt_tokens, out))
    return b"".join(chunks)


def fake_tokens(body):
    text = "".join(m["content"] for m in body.get("messages", []) if isinstance(m.get("content"), str))
    return len(text) // 2 + 12


def scenario_server(fail_without_eos=False, max_model_len=None):
    """模拟服务。fail_without_eos: 没带 ignore_eos 的请求 (场景 / 回放 / 资料校准) 一律返回 500, 其余正常。"""
    def handler(method, path, body):
        if method == "GET" and path.startswith("/v1/models"):
            item = {"id": "m"}
            if max_model_len:
                item["max_model_len"] = max_model_len
            return 200, {"data": [item]}, None
        if method == "POST":
            if fail_without_eos and not body.get("ignore_eos"):
                return 500, {"error": {"message": "scenario boom"}}, None
            return 200, sse(fake_tokens(body), min(int(body.get("max_tokens") or 3), 3)), "text/event-stream"
        return 404, {"error": "not found"}, None
    return MockServer(handler)


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


class BenchCase(LangCase):
    def setUp(self):
        LangCase.setUp(self)
        bench._NO_IGNORE_EOS.clear()      # 引擎的模块级状态: 别让前一个用例记下的端点影响这个
        bench._REQ_EXTRA = {}
        bench._CANCEL = None
        self.addCleanup(setattr, bench, "_CANCEL", None)


# ================================================================ 1. 阶段名、场景名和一整轮测试

ZH_NAMES = ["Prefill 阶梯", "提示词阶梯×并发", "单流解码", "并发阶梯", "场景 · 对话问答", "场景 · 代码生成", "场景 · 结构化抽取",
            "场景 · RAG 问答", "场景 · 图片理解", "场景 · 自定义任务集", "回放·闭环", "回放·开环 (泊松到达)", "长上下文驻留"]
EN_NAMES = ["Prefill ladder", "Prompt ladder × concurrency", "Single-stream decode", "Concurrency ladder", "Scenario · Chat Q&A",
            "Scenario · Code generation", "Scenario · Structured extraction", "Scenario · RAG Q&A", "Scenario · Image understanding",
            "Scenario · Custom task set", "Replay · closed-loop", "Replay · open-loop (Poisson arrivals)", "Long-context decode"]
ZH_LABELS = ["对话问答", "代码生成", "结构化抽取", "RAG 问答", "图片理解", "自定义任务集"]
EN_LABELS = ["Chat Q&A", "Code generation", "Structured extraction", "RAG Q&A", "Image understanding", "Custom task set"]


class TestPhaseNamesAndScenarioLabels(BenchCase):
    def files(self):
        d = temp_dir()
        good = lambda c: json.dumps({"messages": [{"role": "user", "content": c}], "params": {"max_tokens": 8}})
        suite = {"prefill": ["1K", "2K"], "prefill_rep": 1, "prefill_conc": {"ladder": ["1K", "2K"], "conc": 2},
                 "decode_tok": 8, "decode_rep": 1, "conc": [1], "conc_rounds": 1, "longctx": [2048]}
        return {"custom": write(os.path.join(d, "custom.jsonl"), "\n".join(good("q%d" % i) for i in range(4)) + "\n"),
                "replay": write(os.path.join(d, "replay.jsonl"), "\n".join(good("r%d" % i) for i in range(6)) + "\n"),
                "suite": write(os.path.join(d, "suite.json"), json.dumps(suite))}

    def run_all(self, url, files, **extra):
        scn = {"tasks": ["chat", "code", "json", "rag", "vision", "custom"], "conc": [1], "requests_per_worker": 1,
               "max_tokens": 16, "rag_ctx": [1500], "vision_images": 1, "custom_file": files["custom"],
               "max_attempts": 2, "retry_pause_s": 0}
        replay = {"file": files["replay"], "closed": {"conc": [1], "requests_per_worker": 1, "max_attempts": 2, "retry_pause_s": 0},
                  "open": {"rates": [20], "duration_s": 1, "max_attempts": 2, "retry_pause_s": 0}}
        loc = bench.run_suite(url + "/v1/chat/completions", "m", suite="custom", custom=files["suite"], outdir=temp_dir(),
                              conc_ladder=[1], matrix_conc=2, scenarios=scn, replay=replay, retry_max_attempts=2, retry_pause_s=0, **extra)
        with open(loc, encoding="utf-8") as f:
            return json.load(f)

    def test_every_phase_is_named_in_the_language_of_the_run(self):
        files = self.files()
        m = scenario_server()
        try:
            with english_flow() as flow:
                doc_en = self.run_all(m.url, files)
            with i18n.use_lang("zh"), capture_plog() as lines_zh:
                doc_zh = self.run_all(m.url, files)
        finally:
            m.close()
        self.assertEqual([p["name"] for p in doc_zh["phases"]], ZH_NAMES)
        self.assertEqual([p["name"] for p in doc_en["phases"]], EN_NAMES)
        self.assertEqual([p["id"] for p in doc_en["phases"]], [p["id"] for p in doc_zh["phases"]])   # id 不随语言变: 前端按 id 认阶段
        self.assertEqual([p["task"]["label"] for p in doc_zh["phases"] if p["id"].startswith("scn_")], ZH_LABELS)
        self.assertEqual([p["task"]["label"] for p in doc_en["phases"] if p["id"].startswith("scn_")], EN_LABELS)
        assert_english(self, [p["name"] for p in doc_en["phases"]], what="phase names")
        flow.assert_clean(self, doc_en, keys=STORED_TEXT_KEYS)          # 日志、词典缺键、存进结果里的说明
        # 中文日志里还是原来的中文; 英文日志里是对应的英文
        self.assertIn("  任务集 4 条", lines_zh)
        self.assertIn("  Task set: 4 requests", flow.lines)
        self.assertIn("[phase] scenario:code (Code generation)", flow.lines)
        self.assertIn("[phase] scenario:code (代码生成)", lines_zh)
        self.assertIn("[phase] replay closed-loop", flow.lines)
        self.assertIn("[phase] replay 闭环", lines_zh)

    def test_open_loop_line_has_the_same_layout_in_both_languages(self):
        pat = r"^  rate=20     sent=\d+ shed=0 ok=\d+/\d+  %s=\s*\d+\.\d\d rps  ttft_p95=\s*\d+\.\d\ds  in-flight_max=\d+$"
        files = self.files()
        m = scenario_server()
        try:
            with english_flow() as flow:
                self.run_all(m.url, files)
            with i18n.use_lang("zh"), capture_plog() as lines_zh:
                self.run_all(m.url, files)
        finally:
            m.close()
        self.assertEqual(len([x for x in flow.lines if re.match(pat % "completed", x)]), 1, flow.lines)
        self.assertEqual(len([x for x in lines_zh if re.match(pat % "完成", x)]), 1, lines_zh)

    def test_open_loop_line_exact_text(self):
        rec = {"sent": 1234, "shed": 12, "ok": 1200, "total": 1222, "completed_rps": 19.876, "ttft_p95_s": 0.4321, "max_inflight": 128}
        empty = {"sent": 0, "shed": 0, "ok": 0, "total": 0, "completed_rps": 0, "ttft_p95_s": None, "max_inflight": 0}
        for lang, want_rec, want_empty in (
                ("zh", "  rate=%-6g sent=%d shed=%d ok=%d/%d  完成=%6.2f rps  ttft_p95=%6.2fs  in-flight_max=%d" % (2.5, 1234, 12, 1200, 1222, 19.876, 0.4321, 128),
                 "  rate=%-6g sent=%d shed=%d ok=%d/%d  完成=%6.2f rps  ttft_p95=%6.2fs  in-flight_max=%d" % (2.5, 0, 0, 0, 0, 0, 0, 0)),
                ("en", "  rate=2.5    sent=1234 shed=12 ok=1200/1222  completed= 19.88 rps  ttft_p95=  0.43s  in-flight_max=128",
                 "  rate=2.5    sent=0 shed=0 ok=0/0  completed=  0.00 rps  ttft_p95=  0.00s  in-flight_max=0")):
            for rec_, want in ((rec, want_rec), (empty, want_empty)):
                with self.subTest(lang=lang, rec=rec_["sent"]), i18n.use_lang(lang), capture_plog() as lines:
                    with mock.patch.object(bench, "_retry_cell", lambda *a, **k: dict(rec_)):
                        ph = bench.phase_replay_open("u", {}, "m", {"rates": [2.5], "duration_s": 5}, None)
                self.assertEqual(lines, [want])
                self.assertEqual(ph["name"], "回放·开环 (泊松到达)" if lang == "zh" else "Replay · open-loop (Poisson arrivals)")

    def test_scenario_label_function(self):
        for tpl, zh, en in zip(("chat", "code", "json", "rag", "vision", "custom"), ZH_LABELS, EN_LABELS):
            with self.subTest(tpl=tpl):
                with i18n.use_lang("zh"):
                    self.assertEqual(bench.scenario_label(tpl), zh)
                with i18n.use_lang("en"):
                    self.assertEqual(bench.scenario_label(tpl), en)
        self.assertEqual(sorted(bench.SCN_TEMPLATES), ["chat", "code", "custom", "json", "rag", "vision"])   # server.py 按它的键检查任务类型
        self.assertEqual(bench.SCN_TEMPLATES["json"]["validator"], "json")

    def test_skipped_tiers_and_long_context_phase_in_english(self):
        """放不下的档位: 开测前去掉 (知道最大上下文) / 被服务拒绝才跳过 (不知道); 长上下文阶段的名字和跳过记录都是英文。"""
        d = temp_dir()
        suite = {"prefill": ["1K", "2K", "8K"], "prefill_rep": 1, "prefill_conc": {"ladder": ["1K", "8K"], "conc": 2},
                 "decode_tok": 8, "decode_rep": 1, "conc": [1], "conc_rounds": 1, "longctx": [2048, 65536]}
        path = write(os.path.join(d, "suite.json"), json.dumps(suite))
        for max_len in (6000, None):
            m = limited_server(real_limit=3000, max_model_len=max_len)
            try:
                with english_flow() as flow:
                    loc = bench.run_suite(m.url + "/v1/chat/completions", "m", suite="custom", custom=path, outdir=temp_dir(),
                                          conc_ladder=[1], matrix_conc=2, retry_max_attempts=2, retry_pause_s=0)
            finally:
                m.close()
            with self.subTest(max_model_len=max_len):
                with open(loc, encoding="utf-8") as f:
                    doc = json.load(f)
                longctx = [p for p in doc["phases"] if p["id"] == "longctx"]
                self.assertEqual([p["name"] for p in longctx], ["Long-context decode"] * len(longctx))
                self.assertEqual(len(longctx), 1 if max_len else 2)         # 知道最大上下文: 64K 开测前就去掉; 不知道: 跑一次被拒绝
                reasons = [x["reason"] for x in doc["length_skips"]]
                self.assertTrue(reasons and all(r.startswith("Exceeds the model's maximum context") for r in reasons), reasons)
                self.assertTrue(any(x["label"] == "64K" for x in doc["length_skips"]))
                flow.assert_clean(self, doc, keys=STORED_TEXT_KEYS)

    def test_failing_scenario_cells_are_retried_and_reported_in_english(self):
        files = self.files()
        m = scenario_server(fail_without_eos=True)
        try:
            with english_flow() as flow:
                doc = self.run_all(m.url, files)
            with i18n.use_lang("zh"), capture_plog() as lines_zh:
                self.run_all(m.url, files)
        finally:
            m.close()
        self.assertIn("  chat C=1: 1/1 failed, rerunning in 0s (attempt 2/2)", flow.lines)
        self.assertIn("  replay C=1: 1/1 failed, rerunning in 0s (attempt 2/2)", flow.lines)
        self.assertIn("  chat C=1: 1/1 失败, 0s 后重跑 (尝试 2/2)", lines_zh)
        scn = {p["id"]: p for p in doc["phases"]}
        self.assertEqual(scn["scn_chat"]["points"][0]["attempts"], 2)
        rag = scn["scn_rag"]["task"]["rag_calibration"]
        self.assertEqual(rag["method"], "guess")
        self.assertRegex(rag["error"], r"^Calibration request failed: HTTP 500: ")
        self.assertTrue(scn["scn_chat"]["points"][0]["errors"])
        flow.assert_clean(self, doc, keys=STORED_TEXT_KEYS)


# ================================================================ 2. 任务集 / 回放文件的逐行检查

def msg(role="user", content="hi", **kw):
    d = {"role": role, "content": content}
    d.update(kw)
    return d


def jl(obj):
    return json.dumps(obj, ensure_ascii=False)


def img(url):
    return {"type": "image_url", "image_url": {"url": url}}


def png_of(w, h, rgb=(255, 255, 255)):
    return vision_assets.encode_png(w, h, [bytes(rgb) * w for _ in range(h)])


def data_url(data):
    return "data:image/png;base64," + base64.b64encode(data).decode()


class TestTaskLineChecks(BenchCase):
    # (一行, 状态, 中文原因, 英文原因): 每个分支一条; 位置 / 数值都是占位符
    REASONS = [
        ('{"a": 1 "b": 2}', "bad", "不是合法的 JSON（第 9 个字符附近：缺少逗号，或者括号没有配对）",
         "Invalid JSON (near character 9: a comma is missing, or the brackets are unbalanced)"),
        ('{"a" 1}', "bad", "不是合法的 JSON（第 6 个字符附近：缺少冒号）", "Invalid JSON (near character 6: a colon is missing)"),
        ('{} {}', "bad", "不是合法的 JSON（第 4 个字符附近：一行里只能放一个 JSON 对象）",
         "Invalid JSON (near character 4: only one JSON object is allowed per line)"),
        ('{"a": }', "bad", "不是合法的 JSON（第 7 个字符附近：这里缺少值（可能多了逗号，或用了中文引号、单引号））",
         "Invalid JSON (near character 7: a value is missing here (there may be an extra comma, or curly or single quotes were used))"),
        ('{"a": "b', "bad", "不是合法的 JSON（第 7 个字符附近：字符串没有结束（缺少英文双引号））",
         "Invalid JSON (near character 7: the string is not closed (a closing double quote is missing))"),
        ('[1, 2]', "bad", '每行应是一个 JSON 对象，形如 {"messages": [...]}', 'Each line must be a JSON object, like {"messages": [...]}'),
        ('{}', "skip", "缺少 messages（消息列表）", "Missing messages (the message list)"),
        ('{"messages": []}', "skip", "messages 是空的", "messages is empty"),
        ('{"messages": ["x"]}', "bad", 'messages 第 1 条不是对象，应为 {"role": ..., "content": ...}',
         'Message 1 is not an object; expected {"role": ..., "content": ...}'),
        ('{"messages": [{"role": "user", "content": "ok"}, {}]}', "bad", "messages 第 2 条缺少 role", "Message 2 is missing role"),
        ('{"messages": [{"role": "robot", "content": "x"}]}', "bad", "messages 第 1 条的 role「robot」不认识（应为 system / user / assistant / tool）",
         'Message 1 has an unknown role "robot" (expected system / user / assistant / tool)'),
        ('{"messages": [{"role": "user"}]}', "bad", "messages 第 1 条缺少 content", "Message 1 is missing content"),
        ('{"messages": [{"role": "user", "content": 5}]}', "bad", "messages 第 1 条的 content 应为文字，或文字和图片组成的列表",
         "Message 1: content must be text, or a list of text and images"),
        (jl({"messages": [msg(content=["x"])]}), "bad", 'messages 第 1 条的 content 第 1 项应为 {"type": ...}',
         'Message 1: content item 1 must be {"type": ...}'),
        (jl({"messages": [msg(content=[{"type": "text", "text": "ok"}, {"type": "text"}])]}), "bad",
         "messages 第 1 条的 content 第 2 项缺少 text", "Message 1: content item 2 is missing text"),
        (jl({"messages": [msg(content=[{"type": "image_url", "image_url": {}}])]}), "bad",
         'messages 第 1 条的图片应写成 {"type": "image_url", "image_url": {"url": "..."}}',
         'Message 1: an image must be written as {"type": "image_url", "image_url": {"url": "..."}}'),
        (jl({"messages": [msg(content=[img("data:image/png,abc")])]}), "bad",
         "messages 第 1 条的第 1 张图不是 base64 格式的 data URL（应为 data:image/png;base64,…）",
         "Image 1 (message 1): not a base64 data URL (expected data:image/png;base64,…)"),
        (jl({"messages": [msg(content=[img("data:image/png;base64,abc")])]}), "bad",
         "messages 第 1 条的第 1 张图的 base64 数据已损坏", "Image 1 (message 1): the base64 data is corrupted"),
        (jl({"messages": [msg("system", "s"), msg(content=[img("ftp://x/a.png")])]}), "bad",
         "messages 第 2 条的第 1 张图的地址应为 data:image/…;base64,… 或 http(s) 网址",
         "Image 1 (message 2): the address must be data:image/…;base64,… or an http(s) URL"),
        (jl({"messages": [msg()], "params": []}), "bad", 'params 应为对象，如 {"max_tokens": 512}', 'params must be an object, like {"max_tokens": 512}'),
        (jl({"messages": [msg()], "params": {"response_format": {"type": "xml"}}}), "bad",
         'response_format 应为 {"type": "json_object"} 或 {"type": "json_schema", "json_schema": {...}}',
         'response_format must be {"type": "json_object"} or {"type": "json_schema", "json_schema": {...}}'),
        (jl({"messages": [msg()], "params": {"response_format": {"type": "json_schema", "json_schema": {}}}}), "bad",
         'json_schema 应写成 {"name": "名字", "schema": {JSON Schema}}',
         'json_schema must be written as {"name": "my_schema", "schema": {JSON Schema}}'),
        (jl({"messages": [msg()], "params": {"temperature": -1}}), "bad", "temperature 应为不小于 0 的数字",
         "temperature must be a number not less than 0"),
        (jl({"messages": [msg()], "meta": {"prompt_tokens": 60001}}), "skip", "输入约 60001 token，超过 60000 的上限，跳过",
         "Input is about 60001 tokens, over the limit of 60000; skipped"),
    ]

    def test_reasons_in_both_languages(self):
        for line, status, zh, en in self.REASONS:
            with self.subTest(line=line[:70]):
                with i18n.use_lang("zh"):
                    c = bench.check_task_line(line)
                self.assertEqual((c["status"], c["reason"]), (status, zh))
                with english_flow() as flow:
                    c = bench.check_task_line(line)
                self.assertEqual((c["status"], c["reason"]), (status, en))
                flow.assert_clean(self, c)

    def test_json_error_explanations_cover_every_known_python_message(self):
        """Python json 报错的开头 -> 大白话; 用手工构造的 JSONDecodeError, 不依赖当前 Python 版本的报错措辞。"""
        cases = [("Expecting ',' delimiter", "缺少逗号，或者括号没有配对", "a comma is missing, or the brackets are unbalanced"),
                 ("Expecting ':' delimiter", "缺少冒号", "a colon is missing"),
                 ("Expecting property name enclosed in double quotes", "键名要用英文双引号括起来，最后一项后面不能有逗号",
                  "keys must be in double quotes, and the last item cannot be followed by a comma"),
                 ("Illegal trailing comma before end of object", "最后一项后面不能有逗号", "the last item cannot be followed by a comma"),
                 ("Unterminated string starting at", "字符串没有结束（缺少英文双引号）", "the string is not closed (a closing double quote is missing)"),
                 ("Invalid control character at", "字符串里不能直接换行（要写成 \\n）", "a string cannot contain a raw line break (write it as \\n)"),
                 ("Extra data", "一行里只能放一个 JSON 对象", "only one JSON object is allowed per line"),
                 ("Expecting value", "这里缺少值（可能多了逗号，或用了中文引号、单引号）",
                  "a value is missing here (there may be an extra comma, or curly or single quotes were used)"),
                 ("Unexpected UTF-8 BOM (decode using utf-8-sig)", "文件开头有 BOM，请存为不带 BOM 的 UTF-8", "the file starts with a BOM; save it as UTF-8 without a BOM"),
                 ("Invalid \\escape", "Invalid \\escape", "Invalid \\escape")]      # 认不出的原样带上 Python 的原文
        for head, zh, en in cases:
            e = json.JSONDecodeError(head, "x" * 20, 7)                              # colno = 8
            with self.subTest(head=head):
                with i18n.use_lang("zh"):
                    self.assertEqual(bench._json_err_text(e), "第 8 个字符附近：" + zh)
                with i18n.use_lang("en"):
                    self.assertEqual(bench._json_err_text(e), "near character 8: " + en)
        for lang, want in (("zh", "第 0 个字符附近：x"), ("en", "near character 0: x")):      # 不是 JSONDecodeError: 没有位置
            with i18n.use_lang(lang):
                self.assertEqual(bench._json_err_text(ValueError("x")), want)
        for lang, want in (("zh", "第 3 个字符附近"), ("en", "near character 3")):            # 没有说明文字
            with i18n.use_lang(lang):
                self.assertEqual(bench._json_err_text(mock.Mock(msg="", colno=3)), want)

    def test_control_character_message_keeps_a_literal_backslash_n(self):
        e = json.JSONDecodeError("Invalid control character at", "x", 0)
        with i18n.use_lang("en"):
            self.assertTrue(bench._json_err_text(e).endswith("(write it as \\n)"))
            self.assertNotIn("\n", bench._json_err_text(e))
        with i18n.use_lang("zh"):
            self.assertTrue(bench._json_err_text(e).endswith("（要写成 \\n）"))

    def test_warnings_in_both_languages(self):
        url_img = jl({"messages": [msg(content=[img("https://example.com/a.png")])]})
        big = jl({"messages": [msg()], "params": {"max_tokens": 0, "max_completion_tokens": 100000}})
        cases = [(url_img, ["第 1 张图是网址，模型服务需要能访问到它"], ["Image 1 is a URL; the model service must be able to reach it"]),
                 (big, ["max_tokens 不是正整数，会按默认 4096", "max_completion_tokens 是 100000，超过上限，会按 8192"],
                  ["max_tokens is not a positive integer; the default of 4096 will be used",
                   "max_completion_tokens is 100000, which is over the limit; 8192 will be used"]),
                 (jl({"messages": [msg()], "params": {"max_tokens": "abc"}}), ["max_tokens 不是正整数，会按默认 4096"],
                  ["max_tokens is not a positive integer; the default of 4096 will be used"]),
                 (jl({"messages": [msg()], "params": {"max_tokens": 512}}), [], [])]
        for line, zh, en in cases:
            with self.subTest(line=line[:60]):
                with i18n.use_lang("zh"):
                    c = bench.check_task_line(line)
                self.assertEqual((c["status"], c["warns"]), ("ok", zh))
                with english_flow() as flow:
                    c = bench.check_task_line(line)
                self.assertEqual((c["status"], c["warns"]), ("ok", en))
                flow.assert_clean(self, c)

    def test_image_messages_from_the_image_checker_get_their_position(self):
        """图片检查器 (vision_assets.check_image) 的说明是别处生成的整句: 这里只负责把位置加在前面。
        图片的序号是整行按消息顺序数的 (第 1 条消息 2 张, 第 2 条消息的图是第 3 张), 同时说明它在第几条消息里。"""
        one = img(data_url(png_of(30, 30)))
        line = jl({"messages": [msg(content=[one, one]), msg("assistant", "ok"), msg(content=[one])]})
        for lang, warn, bad in (("zh", "第 1 张图looks a bit small", "messages 第 3 条的第 3 张图too tiny"),
                                ("en", "Image 1: looks a bit small", "Image 3 (message 3): too tiny")):
            fake = mock.Mock(side_effect=[{"ok": True, "msg": "looks a bit small"}, {"ok": True, "msg": ""}, {"ok": False, "msg": "too tiny"}])
            with self.subTest(lang=lang), i18n.use_lang(lang), mock.patch.object(bench.vision_assets, "check_image", fake):
                c = bench.check_task_line(line)
            self.assertEqual((c["status"], c["reason"], c["warns"], c["images"]), ("bad", bad, [warn], 3))
            self.assertEqual(fake.call_count, 3)

    def test_real_image_checks_are_not_disturbed(self):
        """真图片: 好图没有原因也没有提醒, 一张 1×1 的图被拒 (说明文字来自图片检查器, 这里只验证位置和状态)。"""
        tiny = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
        good = jl({"messages": [msg(content=[img(data_url(png_of(300, 300)))])]})
        c = bench.check_task_line(good)
        self.assertEqual((c["status"], c["reason"], c["warns"], c["images"]), ("ok", "", [], 1))
        for lang, prefix in (("zh", "messages 第 1 条的第 2 张图"), ("en", "Image 2 (message 1): ")):
            with i18n.use_lang(lang):
                c = bench.check_task_line(jl({"messages": [msg(content=[img(data_url(png_of(300, 300))), img(data_url(tiny))])]}))
            self.assertEqual(c["status"], "bad")
            self.assertTrue(c["reason"].startswith(prefix), c["reason"])

    def test_the_result_shape_is_unchanged(self):
        with i18n.use_lang("en"):
            c = bench.check_task_line(jl({"messages": [msg()], "params": {"response_format": {"type": "json_object"}}}))
        self.assertEqual(sorted(c), ["images", "json", "reason", "rec", "status", "warns"])
        self.assertEqual((c["status"], c["json"], c["images"]), ("ok", True, 0))

    def test_whole_file_report_and_hints(self):
        good = jl({"messages": [msg()]})
        array = json.dumps([{"messages": [msg()]}, {"messages": [msg()]}], indent=2)          # 每一行单独看都不是合法的 JSON
        spread = '{\n  "messages": [\n    {"role": "user", "content": "x"}\n  ]\n}'
        text = "\n".join([good, '{"a": 1 "b"}', '{"messages": []}', jl({"messages": [msg()], "params": {"max_tokens": 0}})])
        with i18n.use_lang("zh"):
            zh_array, zh_spread, zh_text = (bench.check_task_text(x) for x in (array, spread, text))
        with english_flow() as flow:
            en_array, en_spread, en_text = (bench.check_task_text(x) for x in (array, spread, text))
            en_limited = bench.check_task_text("\n".join('{"a": %d' % i for i in range(5)), limit=2)
        self.assertEqual(zh_array["hint"], "整个文件是一个 JSON 数组；任务集要求每行一个 JSON 对象（JSONL），可以参考「下载模板」")
        self.assertEqual(en_array["hint"], 'The whole file is a single JSON array, but a task set needs one JSON object per line (JSONL). '
                                           'See "Download template" for an example.')
        self.assertEqual(zh_spread["hint"], "一个请求被排版成了多行；任务集要求每个请求写在一行里（JSONL），可以参考「下载模板」")
        self.assertEqual(en_spread["hint"], 'A request is spread over several lines, but a task set needs each request on a single line (JSONL). '
                                            'See "Download template" for an example.')
        self.assertEqual([(p["line"], p["reason"]) for p in zh_text["problems"]],
                         [(2, "不是合法的 JSON（第 9 个字符附近：缺少逗号，或者括号没有配对）"), (3, "messages 是空的")])
        self.assertEqual([(p["line"], p["reason"]) for p in en_text["problems"]],
                         [(2, "Invalid JSON (near character 9: a comma is missing, or the brackets are unbalanced)"), (3, "messages is empty")])
        self.assertEqual([(w["line"], w["reason"]) for w in zh_text["warnings"]], [(4, "max_tokens 不是正整数，会按默认 4096")])
        self.assertEqual([(w["line"], w["reason"]) for w in en_text["warnings"]],
                         [(4, "max_tokens is not a positive integer; the default of 4096 will be used")])
        self.assertEqual((en_text["total"], en_text["valid"], en_text["skipped"], en_text["bad"]), (4, 2, 1, 1))
        self.assertEqual((en_limited["bad"], len(en_limited["problems"])), (5, 2))          # 只列前 limit 条
        for rep in (en_array, en_spread, en_text, en_limited):
            self.assertEqual(sorted(rep), sorted(zh_text))                                 # 结构没变
        flow.assert_clean(self, [en_array, en_spread, en_text, en_limited])

    def test_replay_pool_without_usable_requests(self):
        d = temp_dir()
        path = write(os.path.join(d, "bad.jsonl"), '{"messages": []}\n{"messages": [], "meta": {"prompt_tokens": 70000}}\nnope\n')
        empty = write(os.path.join(d, "empty.jsonl"), "")
        for lang, want_bad, want_empty in (
                ("zh", "文件里没有可用请求: %s (没有消息或超长跳过 2 行, 格式不对 1 行)" % path, "文件里没有可用请求: %s (没有消息或超长跳过 0 行, 格式不对 0 行)" % empty),
                ("en", "No usable requests in the file: %s (2 skipped for having no messages or being too long, 1 with a bad format)" % path,
                 "No usable requests in the file: %s (0 skipped for having no messages or being too long, 0 with a bad format)" % empty)):
            with self.subTest(lang=lang), i18n.use_lang(lang):
                with self.assertRaises(RuntimeError) as cm:
                    bench.ReplayPool(path)
                self.assertEqual(str(cm.exception), want_bad)
                with self.assertRaises(RuntimeError) as cm:
                    bench.ReplayPool(empty)
                self.assertEqual(str(cm.exception), want_empty)
        with i18n.use_lang("en"):
            ok = write(os.path.join(d, "ok.jsonl"), jl({"messages": [msg()]}) + "\n")
            self.assertEqual(len(bench.ReplayPool(ok)), 1)


# ================================================================ 3. 命令行

def flat(text):
    return " ".join(text.split())


class TestCommandLine(BenchCase):
    def run_main(self, main, argv, prog="prog"):
        out = io.StringIO()
        saved = (sys.argv[0], os.environ.get("COLUMNS"))
        sys.argv[0], os.environ["COLUMNS"] = prog, "200"
        try:
            with mock.patch.object(bench, "_PROGRESS_CB", None), contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                try:
                    code = main(argv)
                except SystemExit as e:
                    code = e.code
        finally:
            sys.argv[0] = saved[0]
            if saved[1] is None:
                os.environ.pop("COLUMNS", None)
            else:
                os.environ["COLUMNS"] = saved[1]
        return code, out.getvalue()

    def test_bench_help_in_english(self):
        code, text = self.run_main(bench.main, ["--lang", "en", "--help"])
        self.assertEqual(code, 0)
        assert_english(self, text.splitlines(), what="bench --help")
        text = flat(text)
        for phrase in ("llm-bench-pro inference benchmark engine",
                       "--url URL Full chat completions URL (or a base URL; it is normalized automatically)",
                       "--metrics-url METRICS_URL vLLM /metrics URL (for scraping framework metrics)",
                       "--tag TAG Run tag, e.g. '1.6.5 vs 1.6.3'",
                       "Results directory (default: data/results/; imported automatically when the web service starts)",
                       "Custom suite JSON file (used when suite=custom)",
                       "Custom concurrency ladder, comma-separated, e.g. 1,2,4,8",
                       "Concurrency for the prompt ladder x concurrency matrix (default: 4)",
                       "Custom input-length ladder (in K), comma-separated, e.g. 1,2,4,8,16",
                       "Backend framework name, e.g. 1Cat-vLLM / vLLM / SGLang",
                       "Framework version, e.g. 1.6.5-sm70main",
                       "Do not send ignore_eos (let the model end its output early)",
                       "Scenarios to run, comma-separated: chat/code/json/rag/vision/custom (none by default)",
                       "Scenario concurrency list, comma-separated, e.g. 4,8 (default: 4,8)",
                       "Requests per worker in each scenario (default: 3)",
                       "Context tiers for the RAG scenario (in tokens), comma-separated, e.g. 1500,4000,16000",
                       "Image folder for the image scenario (a server path); built-in sample images are used if omitted",
                       "Images per request in the image scenario, 1-4 (default: 1)",
                       "Custom task set JSONL (one {messages, params} per line)",      # 双花括号在 --help 里是单花括号
                       "Real-request replay JSONL file (one {messages, params} per line)",
                       "Closed-loop replay concurrency list, comma-separated, e.g. 8,16",
                       "Open-loop replay rate list (req/s), comma-separated, e.g. 2,5; open-loop runs only if given",
                       "Duration in seconds of each open-loop rate (default: 60)",
                       "Turn off warmup by batch shape",
                       "Where to save results: json = files in outdir (default) / db = SQLite database / both",
                       "SQLite database path (default: data/llm_bench.db or $LLM_BENCH_DB)",
                       "Language of the interface and logs"):
            self.assertIn(phrase, text)

    def test_bench_help_in_chinese_is_what_it_was(self):
        code, text = self.run_main(bench.main, ["--lang", "zh", "--help"])
        self.assertEqual(code, 0)
        text = flat(text)
        for phrase in ("llm-bench-pro 推理基准引擎", "完整 chat completions URL (或 base URL, 自动规整)", "vLLM /metrics 地址 (框架指标抓取)",
                       "运行标签, 如 '1.6.5 vs 1.6.3'", "结果目录 (默认 data/results/, 页面服务启动时自动导入)", "自定义套件 JSON 文件 (suite=custom 时)",
                       "自定义并发阶梯, 逗号分隔, 如 1,2,4,8", "提示词阶梯x并发的并发路数 (默认 4)", "自定义长度阶梯(K), 逗号分隔, 如 1,2,4,8,16",
                       "后端框架名称, 如 1Cat-vLLM / vLLM / SGLang", "框架版本号, 如 1.6.5-sm70main", "不发送 ignore_eos(允许模型提前结束输出)",
                       "任务场景, 逗号分隔: chat/code/json/rag/vision/custom (默认不启用任何场景)", "任务场景并发列表, 逗号分隔, 如 4,8 (默认 4,8)",
                       "任务场景每并发请求数 (默认 3)", "RAG 场景上下文档位(token), 逗号分隔, 如 1500,4000,16000",
                       "图片理解场景的图片目录(服务器路径); 不填用内置示例图片", "图片理解每请求图片数 1-4 (默认 1)",
                       "自定义任务集 JSONL (每行 {messages, params})", "真实请求回放 JSONL 文件 (每行 {messages, params})",
                       "回放闭环并发列表, 逗号分隔, 如 8,16", "回放开环速率列表(req/s), 逗号分隔, 如 2,5; 传了才跑开环",
                       "开环每档速率持续秒数 (默认 60)", "关闭按 batch shape 的预热", "结果落地: json=outdir 文件(默认) / db=SQLite 库 / both",
                       "SQLite 库路径 (默认 data/llm_bench.db 或 $LLM_BENCH_DB)"):
            self.assertIn(phrase, text)
        self.assertNotIn("{{", text)

    def test_bad_option_values(self):
        base = ["--url", "http://127.0.0.1:1", "--model", "m"]
        cases = [(["--conc-ladder", "1,a"], "--conc-ladder 格式错误, 应为逗号分隔整数", "Invalid --conc-ladder: expected comma-separated integers"),
                 (["--lens", "abc"], "--lens 格式错误: 应为 1-256 的逗号分隔整数(K)", "Invalid --lens: expected comma-separated integers from 1 to 256 (in K)"),
                 (["--lens", "0"], "--lens 格式错误: 应为 1-256 的逗号分隔整数(K)", "Invalid --lens: expected comma-separated integers from 1 to 256 (in K)"),
                 (["--scn", "chat", "--scn-conc", "4,x"], "--scn-conc 格式错误, 应为逗号分隔整数", "Invalid --scn-conc: expected comma-separated integers"),
                 (["--scn", "rag", "--rag-ctx", "1.5"], "--rag-ctx 格式错误, 应为逗号分隔整数", "Invalid --rag-ctx: expected comma-separated integers"),
                 (["--replay-file", "f.jsonl", "--replay-conc", "a"], "--replay-conc 格式错误, 应为逗号分隔整数", "Invalid --replay-conc: expected comma-separated integers"),
                 (["--replay-file", "f.jsonl", "--replay-rates", "1,b"], "--replay-rates 格式错误, 应为逗号分隔数字", "Invalid --replay-rates: expected comma-separated numbers")]
        for extra, zh, en in cases:
            for lang, want in (("zh", zh), ("en", en)):
                with self.subTest(args=extra, lang=lang):
                    out = io.StringIO()
                    with mock.patch.object(bench, "_PROGRESS_CB", None), contextlib.redirect_stdout(out):
                        with self.assertRaises(SystemExit) as cm:
                            bench.main(base + extra + ["--lang", lang])
                    self.assertEqual(cm.exception.code, 2)
                    self.assertEqual(out.getvalue().splitlines(), [want])
                    if lang == "en":
                        assert_english(self, out.getvalue().splitlines(), what="option error")
                    i18n.set_default_lang(None)      # --lang 设的是进程语言: 用完还原

    def test_startup_failures_through_the_cli(self):
        """命令行: 未知的任务场景 / 找不到回放文件, 都在 run_suite 开头抛出, 被 main 捕获后打印 (两种语言)。"""
        no_file = os.path.join(temp_dir(), "nope.jsonl")
        for extra, zh, en in ((["--scn", "nope"], "BENCH FAILED: 未知任务类型: nope (可选: chat/code/json/rag/vision/custom)",
                               "BENCH FAILED: Unknown task type: nope (choose from: chat/code/json/rag/vision/custom)"),
                              (["--replay-file", no_file], "BENCH FAILED: 回放文件不存在: %s" % no_file,
                               "BENCH FAILED: Replay file not found: %s" % no_file)):
            for lang, want in (("zh", zh), ("en", en)):
                with self.subTest(args=extra[0], lang=lang):
                    out = io.StringIO()
                    with mock.patch.object(bench, "_PROGRESS_CB", None), contextlib.redirect_stdout(out):
                        with self.assertRaises(SystemExit) as cm:
                            bench.main(["--url", "http://127.0.0.1:1", "--model", "m", "--lang", lang, "--outdir", temp_dir()] + extra)
                    i18n.set_default_lang(None)
                    self.assertEqual(cm.exception.code, 2)
                    self.assertEqual(out.getvalue().strip(), want)

    def test_cdp_help_and_reap_output(self):
        for lang, phrases in (("en", ("Headless browser maintenance", "Clean up leftover headless browsers whose owner process has exited",
                                      "Close all llmbench headless browsers (including leftovers from older versions); use only when no test is running")),
                              ("zh", ("后台浏览器维护", "回收所属进程已退出的后台浏览器", "关闭全部 llmbench 后台浏览器(含旧版本遗留), 确认没有评测在运行时使用"))):
            with self.subTest(lang=lang):
                code, text = self.run_main(cdp.main, ["--lang", lang, "--help"], prog="cdp")
                i18n.set_default_lang(None)
                self.assertEqual(code, 0)
                for p in phrases:
                    self.assertIn(p, flat(text))
                if lang == "en":
                    assert_english(self, text.splitlines(), what="cdp --help")

    def test_cdp_reap_count_is_singular_or_plural(self):
        for n, en, zh in ((0, "Processed 0 browsers", "共处理 0 个"), (1, "Processed 1 browser", "共处理 1 个"), (5, "Processed 5 browsers", "共处理 5 个")):
            for flag in ("--reap", "--reap-all"):
                for lang, want in (("en", en), ("zh", zh)):
                    with self.subTest(n=n, flag=flag, lang=lang):
                        with mock.patch.object(cdp, "reap_all_legacy", lambda log=print, _n=n: _n), \
                                mock.patch.object(cdp, "reap_orphans", lambda log=None, _n=n: _n):
                            code, text = self.run_main(cdp.main, [flag, "--lang", lang], prog="cdp")
                        i18n.set_default_lang(None)
                        self.assertEqual((code, text.splitlines()), (0, [want]))


# ================================================================ 4. 服务接口

class TestUploadReportsFollowXLang(LangServerCase):
    """上传任务集 / 回放文件的检查报告 (bench.check_task_text) 按请求头 X-Lang 生成; 接口自己的 error 由 server.py 那部分负责。"""

    def setUp(self):
        self._saved = (server.SCN_TASKS_DIR, server.REPLAY_DIR)
        server.SCN_TASKS_DIR, server.REPLAY_DIR = temp_dir(), temp_dir()              # 都换成临时目录, 不碰 data/
        self.addCleanup(lambda: setattr(server, "SCN_TASKS_DIR", self._saved[0]))
        self.addCleanup(lambda: setattr(server, "REPLAY_DIR", self._saved[1]))

    CONTENT = "\n".join([jl({"messages": [msg()]}), '{"a": 1 "b"}', '{"messages": []}',
                         jl({"messages": [msg()], "params": {"max_tokens": 0}})])

    def test_task_set_upload_report(self):
        for path, body in (("/api/scenario-upload", {"kind": "tasks", "name": "t.jsonl", "content": self.CONTENT}),
                           ("/api/replay-upload", {"name": "r.jsonl", "content": self.CONTENT})):
            with self.subTest(path=path):
                st, d = self.request("POST", path, body, lang="en")
                self.assertEqual((st, d["ok"]), (200, True))
                check = d["check"]
                self.assertEqual([p["reason"] for p in check["problems"]],
                                 ["Invalid JSON (near character 9: a comma is missing, or the brackets are unbalanced)", "messages is empty"])
                self.assertEqual([w["reason"] for w in check["warnings"]], ["max_tokens is not a positive integer; the default of 4096 will be used"])
                assert_english(self, check, what="check report")
                st, d = self.request("POST", path, body, lang="zh")
                self.assertEqual([p["reason"] for p in d["check"]["problems"]],
                                 ["不是合法的 JSON（第 9 个字符附近：缺少逗号，或者括号没有配对）", "messages 是空的"])
                self.assertEqual([w["reason"] for w in d["check"]["warnings"]], ["max_tokens 不是正整数，会按默认 4096"])

    def test_whole_file_hint_in_the_report_of_a_rejected_upload(self):
        array = json.dumps([{"messages": [msg()]}, {"messages": [msg()]}], indent=2)
        st, d = self.request("POST", "/api/scenario-upload", {"kind": "tasks", "name": "a.json", "content": array}, lang="en")
        self.assertEqual((st, d["ok"]), (400, False))
        self.assertEqual(d["check"]["hint"], 'The whole file is a single JSON array, but a task set needs one JSON object per line (JSONL). '
                                             'See "Download template" for an example.')
        assert_english(self, d["check"], what="rejected check report")
        st, d = self.request("POST", "/api/replay-upload", {"name": "a.json", "content": array}, lang="zh")
        self.assertEqual(d["check"]["hint"], "整个文件是一个 JSON 数组；任务集要求每行一个 JSON 对象（JSONL），可以参考「下载模板」")


class TestPerfJobStoresNamesInTheRequestLanguage(LangServerCase):
    """页面启动的速度测试: 任务线程沿用请求的语言, 存进结果的阶段名和场景名跟着变 (线程池里的工作线程也是)。"""

    def wait_idle(self, timeout=90):
        end = time.time() + timeout
        while time.time() < end:
            st = self.request("GET", "/api/status")[1]
            if not st["running"]:
                return st
            time.sleep(0.05)
        self.fail("任务没有在 %d 秒内结束" % timeout)

    def start(self, url, lang):
        # 模型名带上语言: 结果的 run_id 由「开始时间 (精确到秒) + 模型名」组成, 同一秒里开始的两次测试不能撞成同一个 id
        body = {"base": url, "model": "m-" + lang, "suite": "quick", "conc_ladder": "1", "matrix_conc": "2", "metrics": False,
                "scenarios": {"tasks": ["chat", "json"], "conc": [1], "requests_per_worker": 1, "max_tokens": 64}}
        st, d = self.request("POST", "/api/start", body, lang=lang)
        self.assertEqual((st, d.get("ok")), (200, True), d)
        return self.wait_idle()

    def test_phase_and_scenario_names(self):
        m = scenario_server()
        try:
            st_en = self.start(m.url, "en")
            doc_en = store.get_run(st_en["run_id"])
            st_zh = self.start(m.url, "zh")
            doc_zh = store.get_run(st_zh["run_id"])
        finally:
            m.close()
        self.assertEqual([p["name"] for p in doc_en["phases"]],
                         ["Prefill ladder", "Prompt ladder × concurrency", "Single-stream decode", "Concurrency ladder",
                          "Scenario · Chat Q&A", "Scenario · Structured extraction"])
        self.assertEqual([p["name"] for p in doc_zh["phases"]],
                         ["Prefill 阶梯", "提示词阶梯×并发", "单流解码", "并发阶梯", "场景 · 对话问答", "场景 · 结构化抽取"])
        self.assertEqual([p["task"]["label"] for p in doc_en["phases"] if p["id"].startswith("scn_")], ["Chat Q&A", "Structured extraction"])
        assert_english(self, [x["msg"] for x in st_en["log"]], what="job log")
        assert_english(self, doc_en, keys=STORED_TEXT_KEYS, what="stored result")


# ================================================================ 5. cdp.py

class FakeProc(object):
    def __init__(self, poll_value=None, returncode=None):
        self._poll, self.returncode = poll_value, returncode

    def poll(self):
        return self._poll

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def fake_popen(poll_value=None, returncode=None, output=b""):
    def popen(args, **kw):
        if output and kw.get("stderr") is not None:
            kw["stderr"].write(output)            # 浏览器的输出 (启动日志文件)
        return FakeProc(poll_value, returncode)
    return popen


class CdpCase(LangCase):
    def setUp(self):
        LangCase.setUp(self)
        base = temp_dir()                          # 临时目录 (含浏览器的用户目录) 全放在测试自己的目录里
        patcher = mock.patch.object(tempfile, "gettempdir", lambda: base)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.base = base

    def launch_error(self, scenario):
        """让 Browser() 在不启动真浏览器的前提下走到各个失败分支, 返回异常文字。"""
        patches = [mock.patch.object(cdp, "close_via_devtools", lambda *a, **k: False)]
        args = {"path": "/fake/chrome", "timeout": 0.3}
        if scenario == "no_browser":
            patches.append(mock.patch.object(cdp, "find_browser", lambda: None))
            args = {}
        elif scenario == "cannot_start":
            patches.append(mock.patch.object(cdp.subprocess, "Popen", mock.Mock(side_effect=OSError("boom"))))
        elif scenario == "not_ready":
            patches += [mock.patch.object(cdp.subprocess, "Popen", fake_popen(None, None, b"starting\nlistening on nothing\n")),
                        mock.patch.object(cdp, "_read_port", lambda p: None)]
        elif scenario == "not_ready_silent":
            patches += [mock.patch.object(cdp.subprocess, "Popen", fake_popen(None, None)), mock.patch.object(cdp, "_read_port", lambda p: None)]
        elif scenario == "exited":
            patches += [mock.patch.object(cdp.subprocess, "Popen", fake_popen(7, 7, b"crash: bad flag\n")),
                        mock.patch.object(cdp, "_read_port", lambda p: None)]
        elif scenario == "exited_silent":
            patches += [mock.patch.object(cdp.subprocess, "Popen", fake_popen(1, 1)), mock.patch.object(cdp, "_read_port", lambda p: None)]
        elif scenario == "no_debug_port":
            args["timeout"] = 1
            patches += [mock.patch.object(cdp.subprocess, "Popen", fake_popen(None, None)), mock.patch.object(cdp, "_read_port", lambda p: 9222),
                        mock.patch.object(cdp.Browser, "_http", mock.Mock(side_effect=OSError("boom")))]
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            with self.assertRaises(RuntimeError) as cm:
                cdp.Browser(**args)
        self.assertEqual(os.listdir(self.base), [], "启动失败后浏览器的用户目录要清掉")
        return str(cm.exception)


class TestBrowserLaunchFailures(CdpCase):
    CASES = [("no_browser", "未找到 Chrome/Edge/Chromium (可设 LLM_BENCH_BROWSER 指定路径)",
              "Chrome/Edge/Chromium not found (set LLM_BENCH_BROWSER to specify the path)"),
             ("cannot_start", "无法启动浏览器 /fake/chrome: boom", "Cannot start the browser /fake/chrome: boom"),
             ("not_ready", "浏览器 0 秒内没有准备好：/fake/chrome。浏览器输出：starting / listening on nothing",
              "The browser was not ready within 0 s: /fake/chrome. Browser output: starting / listening on nothing"),
             ("not_ready_silent", "浏览器 0 秒内没有准备好：/fake/chrome", "The browser was not ready within 0 s: /fake/chrome"),
             ("exited", "浏览器启动后立即退出（退出码 7）：/fake/chrome。浏览器输出：crash: bad flag",
              "The browser exited right after starting (exit code 7): /fake/chrome. Browser output: crash: bad flag"),
             ("exited_silent", "浏览器启动后立即退出（退出码 1）：/fake/chrome", "The browser exited right after starting (exit code 1): /fake/chrome"),
             ("no_debug_port", "浏览器已启动但无法连接调试端口 9222: boom",
              "The browser started but the debugging port 9222 is not reachable: boom")]

    def test_reasons_in_both_languages(self):
        for scenario, zh, en in self.CASES:
            with self.subTest(scenario=scenario):
                with i18n.use_lang("zh"):
                    self.assertEqual(self.launch_error(scenario), zh)
                with english_flow() as flow:
                    got = self.launch_error(scenario)
                self.assertEqual(got, en)
                flow.assert_clean(self, got)

    def test_seconds_are_whole_numbers(self):
        """「%d 秒」按整数显示 (以前是 %d 截断小数)。"""
        b = cdp.Browser.__new__(cdp.Browser)
        log = os.path.join(self.base, "chrome-launch.log")
        b._log = open(log, "wb")
        self.addCleanup(b._log.close)
        b.path, b.proc = "/x/chrome", FakeProc(returncode=0)
        for lang, want in (("zh", "浏览器 29 秒内没有准备好：/x/chrome"), ("en", "The browser was not ready within 29 s: /x/chrome")):
            with i18n.use_lang(lang):
                self.assertEqual(b._failure_reason(False, 29.999), want)

    def test_browser_output_is_trimmed_to_the_last_three_lines(self):
        b = cdp.Browser.__new__(cdp.Browser)
        b._log = open(os.path.join(self.base, "chrome-launch.log"), "wb")
        self.addCleanup(b._log.close)
        b._log.write(b"a\nb\n\nc\nd\ne\n")
        b.path, b.proc = "/x/chrome", FakeProc(returncode=-9)
        with i18n.use_lang("en"):
            self.assertEqual(b._failure_reason(True, 1), "The browser exited right after starting (exit code -9): /x/chrome. "
                                                          "Browser output: c / d / e")
        with i18n.use_lang("zh"):
            self.assertEqual(b._failure_reason(True, 1), "浏览器启动后立即退出（退出码 -9）：/x/chrome。浏览器输出：c / d / e")


class TestReapingLeftoverBrowsers(CdpCase):
    def make_profiles(self, names):
        """在测试自己的临时目录里造几个浏览器用户目录: "dead" 的归属进程已经退出, "alive" 的还在 (用本进程), None 没有归属记录。"""
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        for name, owner in names.items():
            d = os.path.join(self.base, name)
            os.makedirs(d, exist_ok=True)
            if owner:
                pid = dead.pid if owner == "dead" else os.getpid()
                write(os.path.join(d, "llmbench-owner.json"), json.dumps({"pid": pid, "created": 1.0}))
        return dead.pid

    def test_reap_orphans_log_lines(self):
        names = {"llmbench-chrome-dead": "dead", "llmbench-chrome-alive": "alive", "llmbench-chrome-noowner": None}
        for lang, template in (("zh", "  已关闭遗留的后台浏览器(所属进程 %d 已退出): llmbench-chrome-dead"),
                               ("en", "  Closed a leftover headless browser (its owner process %d has exited): llmbench-chrome-dead")):
            with self.subTest(lang=lang), i18n.use_lang(lang), mock.patch.object(cdp, "close_via_devtools", lambda *a, **k: True):
                pid = self.make_profiles(names)                    # 上一轮把 dead 清掉了: 重新造 (其余的原样还在)
                lines = []
                self.assertEqual(cdp.reap_orphans(lines.append), 1)
                self.assertEqual(lines, [template % pid])
                if lang == "en":
                    assert_english(self, lines, what="reap log")
        self.assertEqual(sorted(os.listdir(self.base)), ["llmbench-chrome-alive", "llmbench-chrome-noowner"])   # 归属进程还在 / 没有记录的不动

    def test_reap_all_lines_for_each_combination(self):
        table = [(True, True, "浏览器已关闭  目录已删除", "browser closed  directory deleted"),
                 (True, False, "浏览器已关闭  目录删除失败(可能仍被占用)", "browser closed  directory deletion failed (may still be in use)"),
                 (False, True, "浏览器未在运行  目录已删除", "browser not running  directory deleted"),
                 (False, False, "浏览器未在运行  目录删除失败(可能仍被占用)", "browser not running  directory deletion failed (may still be in use)")]
        for closed, removed, zh, en in table:
            for lang, tail in (("zh", zh), ("en", en)):
                with self.subTest(closed=closed, removed=removed, lang=lang), i18n.use_lang(lang):
                    d = os.path.join(self.base, "llmbench-chrome-x")
                    os.makedirs(d, exist_ok=True)
                    write(os.path.join(d, "DevToolsActivePort"), "9333\n")
                    lines = []
                    with mock.patch.object(cdp, "close_via_devtools", lambda port, timeout=3, _c=closed: _c), \
                            mock.patch.object(cdp, "_remove_profile", lambda path, tries=20, _r=removed: _r):
                        self.assertEqual(cdp.reap_all_legacy(lines.append), 1)
                    self.assertEqual(lines, ["llmbench-chrome-x  " + tail])
                    if lang == "en":
                        assert_english(self, lines, what="reap-all log")

    def test_reap_all_prints_by_default(self):
        os.makedirs(os.path.join(self.base, "llmbench-chrome-p"))
        out = io.StringIO()
        with i18n.use_lang("en"), contextlib.redirect_stdout(out):
            self.assertEqual(cdp.reap_all_legacy(), 1)
        self.assertRegex(out.getvalue(), r"^llmbench-chrome-p  browser not running  directory (deleted|deletion failed \(may still be in use\))\n$")


def tcp_server(reply):
    """本地的假 WebSocket 服务: 收到请求后回一段固定字节 (None 就直接关闭连接)。"""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)

    def loop():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            try:
                c.recv(4096)
                if reply is not None:
                    c.sendall(reply)
            finally:
                c.close()
    threading.Thread(target=loop, daemon=True).start()
    return srv, srv.getsockname()[1]


class FakeWS(object):
    def send(self, text):
        pass

    def close(self):
        pass


def make_page(alive=True):
    p = cdp.Page.__new__(cdp.Page)
    p.ws, p._id, p._lock, p._results = FakeWS(), 0, threading.Lock(), {}
    p._cond, p.events, p._alive = threading.Condition(), [], alive
    return p


def png_header(w=2, h=2, depth=8, ctype=2, interlace=0):
    def chunk(kind, data):
        return struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack("!IIBBBBB", w, h, depth, ctype, 0, 0, interlace)) + chunk(b"IEND", b"")


class TestCdpErrors(LangCase):
    def both(self, make_exc, zh, en):
        """同一件事: 中文和以前逐字一样, 英文没有汉字 (报错文字里没有系统错误原文, 这里的都是本模块自己的说明)。"""
        with i18n.use_lang("zh"):
            self.assertEqual(str(make_exc()), zh)
        with english_flow() as flow:
            got = str(make_exc())
        self.assertEqual(got, en)
        flow.assert_clean(self, got)

    def raised(self, fn, *a, **k):
        def make():
            try:
                fn(*a, **k)
            except Exception as e:
                return e
            self.fail("没有抛出异常")
        return make

    def test_websocket_handshake_failures(self):
        for reply, zh, en in ((None, "WebSocket 握手失败", "WebSocket handshake failed"),
                              (b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n",
                               "WebSocket 握手被拒: b'HTTP/1.1 403 Forbidden\\r\\nContent-Length: 0'",
                               "WebSocket handshake rejected: b'HTTP/1.1 403 Forbidden\\r\\nContent-Length: 0'")):
            srv, port = tcp_server(reply)
            try:
                with self.subTest(reply=reply), warnings.catch_warnings():
                    warnings.simplefilter("ignore", ResourceWarning)     # 握手失败时构造函数没关掉 socket (原有行为), 只是个警告
                    self.both(self.raised(cdp.WebSocket, "ws://127.0.0.1:%d/x" % port, 3), zh, en)
                    gc.collect()                                          # 让警告在过滤器还生效的这里出现
            finally:
                srv.close()

    def test_websocket_closed_by_the_peer(self):
        for feed, zh, en in ((b"", "WebSocket 连接关闭", "WebSocket connection closed"),
                             (b"\x88\x00", "WebSocket 被对端关闭", "WebSocket closed by the peer")):
            def make(feed=feed):
                a, b = socket.socketpair()
                b.close()
                ws = cdp.WebSocket.__new__(cdp.WebSocket)
                ws.sock, ws._buf, ws._send_lock = a, feed, threading.Lock()
                try:
                    ws.recv()
                except Exception as e:
                    return e
                finally:
                    a.close()
            with self.subTest(feed=feed):
                self.both(make, zh, en)

    def test_page_send_and_evaluate(self):
        for method in ("Page.navigate", "Runtime.evaluate"):
            with self.subTest(method=method):
                self.both(self.raised(lambda m=method: make_page().send(m, timeout=0.05)),
                          "%s 超时或连接断开(页面可能卡死)" % method, "%s timed out or the connection dropped (the page may be frozen)" % method)
        for text, zh, en in (("Uncaught ReferenceError", "evaluate 异常: Uncaught ReferenceError", "evaluate raised an exception: Uncaught ReferenceError"),
                             (None, "evaluate 异常: None", "evaluate raised an exception: None")):
            def make(text=text):
                p = make_page()
                with mock.patch.object(p, "send", lambda *a, **k: {"exceptionDetails": {"text": text}}):
                    try:
                        p.evaluate("x")
                    except Exception as e:
                        return e
            with self.subTest(text=text):
                self.both(make, zh, en)
        with i18n.use_lang("en"):
            p = make_page()
            with mock.patch.object(p, "send", lambda *a, **k: {"result": {"value": 5}}):
                self.assertEqual(p.evaluate("1+4"), 5)                                # 没有异常时照常返回

    def test_page_send_error_reply_keeps_the_service_text(self):
        p = make_page()
        p._results[1] = {"id": 1, "error": {"message": "no such thing"}}
        with i18n.use_lang("en"):
            with self.assertRaises(cdp.CDPError) as cm:
                p.send("A.b")
        self.assertEqual(str(cm.exception), "A.b: no such thing")

    def test_png_decoder_errors(self):
        for data, zh, en in ((b"GIF89a", "非 PNG", "Not a PNG"),
                             (png_header(depth=16), "不支持的 PNG 格式", "Unsupported PNG format"),
                             (png_header(interlace=1), "不支持的 PNG 格式", "Unsupported PNG format"),
                             (png_header(ctype=3), "不支持的 PNG 格式", "Unsupported PNG format")):
            with self.subTest(data=data[:12]):
                self.both(self.raised(cdp.decode_png, data), zh, en)
                self.both(self.raised(cdp.image_stats, data), zh, en)

    def test_wait_event_still_finds_events(self):
        p = make_page()
        p.events = [(1.0, "A", {"a": 1}), (2.0, "B", {"b": 2}), (3.0, "B", {"b": 3})]
        self.assertEqual(p.wait_event("B", timeout=0.05, since=2.5), {"b": 3})
        self.assertIsNone(p.wait_event("C", timeout=0.05))


if __name__ == "__main__":
    unittest.main()
