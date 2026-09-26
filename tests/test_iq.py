# -*- coding: utf-8 -*-
import json
import os
import threading
import time
import unittest

from _util import ROOT, MockServer, chat_reply, load_json, temp_dir  # noqa: F401  (设置 sys.path / 临时库)
import bankman
import iq


class TestAnswerExtraction(unittest.TestCase):
    def test_mcq(self):
        cases = [("B", "B"), ("\n\nB", "B"), ("**C**", "C"), ("(D)", "D"), ("B.", "B"), ("答案：C", "C"),
                 ("答案是 **A**", "A"), ("正确答案为（D）", "D"), ("The answer is B.", "B"),
                 ("A careful analysis shows the answer is C", "C"), ("A careful analysis shows nothing", None),
                 ("B. 巴黎是法国首都", "B"), ("\\boxed{D}", "D"), ("首先排除A，再排除B，最终答案：C", "C"),
                 ("", None), ("Apple", None), ("选 A", "A"), ("排除选项B后，选C", "C"), ("选项A和选项B都不对", None)]
        for text, want in cases:
            with self.subTest(text=text):
                self.assertEqual(iq.extract_mcq(text), want)

    def test_strip_think(self):
        self.assertEqual(iq.strip_think("<think>B</think>\nC"), "C")
        self.assertEqual(iq.strip_think("thinking...</think>\n\nD"), "D")
        self.assertEqual(iq.strip_think("<think>A is wrong, maybe B"), "")

    def test_math500_normalization(self):
        cases = [(r"\boxed{36}", r"\$36", True), (r"\boxed{5.4}", r"5.4 \text{ cents}", True),
                 (r"\boxed{180}", r"180^\circ", True), (r"\boxed{10080}", r"10,\!080", True),
                 (r"\boxed{\frac{1}{4}}", r"\frac14", True), (r"\boxed{x=3}", "3", True),
                 (r"\boxed{0.5}", r"\frac{1}{2}", True), (r"\boxed{3/8}", r"\frac{3}{8}", True),
                 (r"\boxed{-\dfrac{3}{8}}", r"-\frac{3}{8}", True), (r"\boxed{2\sqrt5}", r"2\sqrt{5}", True),
                 (r"\boxed{(-1, 6)}", "(-1,6)", True), (r"\boxed{\frac{1}{2}}", r"\frac{1}{2}", True),
                 (r"\boxed{4}", "3", False), (r"\boxed{37}", r"\$36", False), ("答案：3", "3", True)]
        for resp, gold, want in cases:
            with self.subTest(resp=resp, gold=gold):
                self.assertEqual(iq.judge_math500("推理\n" + resp, {"answer": gold}), want)

    def test_bank_gold_answers_self_consistent(self):
        """题库中每道题的标准答案放进 \\boxed{} / #### / 字母后必须判为正确(判分器与题库口径一致)。"""
        for fn in os.listdir(os.path.join(ROOT, "banks")):
            bank = bankman.load_bank(fn[:-5])
            for sub in bank["subjects"]:
                if sub["type"] == "instruct":
                    continue
                fmt = {"math500": "\\boxed{%s}", "math": "推理过程\n#### %s", "mcq": "%s"}[sub["type"]]
                bad = [it["answer"] for it in sub["items"] if not iq.JUDGES[sub["type"]](fmt % it["answer"], it)]
                self.assertEqual(bad, [], "%s/%s" % (fn, sub["id"]))


class TestStatistics(unittest.TestCase):
    def test_mcnemar(self):
        self.assertEqual(iq.mcnemar(0, 0), 1.0)
        self.assertAlmostEqual(iq.mcnemar(0, 10), 2 * 0.5 ** 10)
        self.assertAlmostEqual(iq.mcnemar(5, 5), 1.0)
        self.assertLess(iq.mcnemar(300, 200), 0.001)  # 大样本走卡方近似

    def test_compare_runs(self):
        a = {"bank_id": "b", "items": [{"sid": "s", "idx": i, "ok": i < 8} for i in range(10)]}
        b = {"bank_id": "b", "items": [{"sid": "s", "idx": i, "ok": i < 3} for i in range(10)]}
        r = iq.compare_runs(a, b)
        self.assertTrue(r["same_bank"])
        self.assertEqual((r["overall"]["a_only"], r["overall"]["b_only"], r["overall"]["n"]), (5, 0, 10))
        self.assertEqual(r["overall"]["diff"], -50.0)
        self.assertAlmostEqual(r["overall"]["p"], round(2 * 0.5 ** 5, 4))

    def test_resolve_sampling(self):
        self.assertEqual(iq.resolve_sampling(True), {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "seed": 42})
        self.assertEqual(iq.resolve_sampling(False), {"temperature": 0.0})
        self.assertEqual(iq.resolve_sampling(True, "greedy"), {"temperature": 0.0})
        custom = iq.resolve_sampling(True, {"temperature": "0.7", "top_p": "", "top_k": "40"})
        self.assertEqual(custom, {"temperature": 0.7, "top_k": 40, "seed": 42})
        self.assertEqual(iq.resolve_sampling(True, custom), custom)  # 幂等


class TestRequests(unittest.TestCase):
    def setUp(self):
        iq._DROPPED.clear()
        iq._CTX_LIMIT.clear()

    def test_context_overflow_fits_max_tokens(self):
        def h(method, path, body):
            if body["max_tokens"] + 10 > 10000:
                return 400, {"message": "This model's maximum context length is 10000 tokens. However, you requested "
                                        "%d tokens (10 in the messages, %d in the completion)." % (body["max_tokens"] + 10, body["max_tokens"])}, None
            return 200, chat_reply("B"), None
        m = MockServer(h)
        try:
            r = iq.ask(m.url + "/v1/chat/completions", "m", "q", 8, True, {})
            self.assertEqual((r["content"], r["max_tokens"]), ("B", 10000 - 10 - 32))  # 按报错直接收缩, 不逐次减半
            self.assertEqual(len(m.calls), 2)
            iq.ask(m.url + "/v1/chat/completions", "m", "q", 8, True, {})
            self.assertEqual(len(m.calls), 3)  # 上下文长度按端点缓存, 不再先撞一次 400
        finally:
            m.close()

    def test_context_overflow_unparsed_halves(self):
        def h(method, path, body):
            if body["max_tokens"] > 9000:
                return 400, {"message": "max_tokens is too large"}, None
            return 200, chat_reply("B"), None
        m = MockServer(h)
        try:
            r = iq.ask(m.url + "/v1/chat/completions", "m", "q", 8, True, {})
            self.assertEqual([c[2]["max_tokens"] for c in m.calls], [32768, 16384, 8192])
            self.assertEqual(r["max_tokens"], 8192)
        finally:
            m.close()

    def test_rejected_keys_ignore_echoed_input(self):
        d1 = json.dumps({"detail": [{"type": "missing", "loc": ["body", "messages"], "msg": "Field required",
                                     "input": {"top_k": 20, "seed": 42}}]})
        self.assertEqual(iq._rejected_keys(d1, ["top_k", "seed"]), set())
        d2 = json.dumps({"detail": [{"type": "extra_forbidden", "loc": ["body", "top_k"],
                                     "msg": "Extra inputs are not permitted", "input": 20}]})
        self.assertEqual(iq._rejected_keys(d2, ["top_k", "seed"]), {"top_k"})

    def test_optional_params_dropped_only_when_named(self):
        def h(method, path, body):
            if path.startswith("/kw") and "top_k" in body:
                return 400, {"error": "Unrecognized request argument supplied: top_k"}, None
            if path.startswith("/other"):
                return 400, {"error": "prompt too long"}, None
            return 200, chat_reply("C"), None
        m = MockServer(h)
        try:
            r = iq.ask(m.url + "/kw", "m", "q", 8, True, {})
            self.assertEqual(r["content"], "C")
            self.assertEqual(iq.dropped_params(m.url + "/kw"), ["top_k"])
            self.assertIn("chat_template_kwargs", m.calls[-1][2])  # 思考开关不受影响
            with self.assertRaises(Exception) as ctx:
                iq.ask(m.url + "/other", "m", "q", 8, True, {})
            self.assertIn("prompt too long", getattr(ctx.exception, "detail", ""))
            self.assertEqual(iq.dropped_params(m.url + "/other"), [])
        finally:
            m.close()


def _bank(n_subjects=2, n_items=6):
    return {"bank_id": "test-bank", "subjects": [
        {"id": "s%d" % k, "name": "S%d" % k, "type": "mcq",
         "items": [{"q": "q%d" % i, "choices": list("abcd"), "answer": "B"} for i in range(n_items)]}
        for k in range(n_subjects)]}


class TestRunLifecycle(unittest.TestCase):
    def test_budgets_override_clamped_and_recorded(self):
        """各题型输出预算: 覆盖模板默认、越界钳制、记录进 params 与口径文案; 未配置的键保持默认。"""
        bodies = []

        def h(method, path, body):
            bodies.append(body)
            return 200, chat_reply("B"), None
        m = MockServer(h)
        try:
            import sinks
            sink = sinks.JsonFileSink(temp_dir())
            bank = {"bank_id": "tb", "subjects": [
                {"id": "mc", "name": "MC", "type": "mcq",
                 "items": [{"q": "q", "choices": list("abcd"), "answer": "B"}]},
                {"id": "m5", "name": "M5", "type": "math500",
                 "items": [{"q": "q", "answer": "1"}]},
            ]}
            iq.run_iq(m.url + "/v1/chat/completions", "m", bank=bank, sink=sink,
                      budgets={"math500": 128, "mcq": 999999, "junk": 1, "math": "bad"})
            doc = load_json(sink.path)
            self.assertEqual(doc["params"]["budgets"]["math500"], 128)      # 覆盖生效
            self.assertEqual(doc["params"]["budgets"]["mcq"], 32768)        # 钳到上限
            self.assertEqual(doc["params"]["budgets"]["math"], 2048)        # 非法值忽略 → 默认
            self.assertNotIn("junk", doc["params"]["budgets"])              # 白名单外丢弃
            mts = {b["max_tokens"] for b in bodies}
            self.assertIn(128, mts)                                         # 请求真的用了新预算
            self.assertIn(32768, mts)
            self.assertIn("输出预算", doc["max_tokens_policy"])
            self.assertIn("128", doc["max_tokens_policy"])
        finally:
            m.close()

    def test_truncation_marked(self):
        m = MockServer(lambda *a: (200, chat_reply("", finish="length", completion_tokens=32768, reasoning="x" * 50), None))
        try:
            import sinks
            sink = sinks.JsonFileSink(temp_dir())
            iq.run_iq(m.url + "/v1/chat/completions", "m", bank=_bank(1, 3), sink=sink, thinking=True)
            import json
            doc = load_json(sink.path)
            self.assertEqual(doc["overall"]["truncated"], 3)
            self.assertEqual(doc["items"][0]["resp"], "")          # 空串 = 没有正式回答
            self.assertEqual(doc["items"][0]["rtail"], "x" * 50)   # 答错时留思考结尾
            self.assertEqual(doc["sampling"]["temperature"], 0.6)
            self.assertIn("macro_acc", doc["overall"])
        finally:
            m.close()

    def test_cancel_then_resume(self):
        import json
        import sinks
        cancel = threading.Event()
        counter = {"n": 0}

        def h(method, path, body):
            counter["n"] += 1
            if counter["n"] == 3:
                cancel.set()
            time.sleep(0.05)
            return 200, chat_reply("B"), None
        m = MockServer(h)
        try:
            out = temp_dir()
            sink = sinks.JsonFileSink(out)
            iq.run_iq(m.url + "/v1/chat/completions", "m", bank=_bank(2, 6), conc=1, sink=sink, cancel=cancel)
            doc = load_json(sink.path)
            self.assertEqual(doc["status"], "cancelled")
            done_before = len(doc["items"])
            self.assertTrue(0 < done_before < 12)
            iq.run_iq(m.url + "/v1/chat/completions", "m", bank=_bank(2, 6), sink=sinks.JsonFileSink(out), resume=doc)
            doc2 = load_json(sink.path)
            self.assertEqual(doc2["status"], "done")
            self.assertEqual(len(doc2["items"]), 12)
            self.assertEqual(len({(i["sid"], i["idx"]) for i in doc2["items"]}), 12)  # 无重复作答
            self.assertEqual(doc2["overall"]["correct"], 12)
            self.assertLessEqual(counter["n"], 13)  # 续跑只补未完成的题(停止瞬间至多多发 1 个请求)
        finally:
            m.close()

    def test_resume_rejects_other_version(self):
        with self.assertRaises(ValueError):
            iq.run_iq("http://x", "m", bank=_bank(), resume={"iq_version": "1.0.0", "items": [], "subjects": []})


class TestAnswerArchive(unittest.TestCase):
    """逐题查看: 回答留档、思考结尾、按要求作答题逐条规则。"""

    def test_think_part_and_clip(self):
        self.assertEqual(iq.think_part("<think>abc</think>def"), "abc")
        self.assertEqual(iq.think_part("abc</think>def"), "abc")          # 模板预置开标签
        self.assertEqual(iq.think_part("<think>still thinking"), "still thinking")  # 思考被截断
        self.assertEqual(iq.think_part("plain"), "")
        self.assertEqual(iq.clip_text("short"), "short")
        out = iq.clip_text("a" * 3000 + "b" * 4000 + "c" * 4000)
        self.assertTrue(out.startswith("a" * 2000) and out.endswith("c" * 4000))
        self.assertIn("中间省略 5000 字", out)

    def test_run_keeps_answers(self):
        def h(method, path, body):
            if body["messages"][0]["content"].startswith("one"):
                return 200, chat_reply("1 + 4 = 5\n#### 5"), None
            return 200, chat_reply("x" * 8000 + "\n#### 7", reasoning="r" * 2000), None
        m = MockServer(h)
        try:
            import sinks
            sink = sinks.JsonFileSink(temp_dir())
            bank = {"bank_id": "tb", "subjects": [{"id": "m", "name": "M", "type": "math",
                                                   "items": [{"q": "one", "answer": "5"}, {"q": "two", "answer": "8"}]}]}
            iq.run_iq(m.url + "/v1/chat/completions", "m", bank=bank, sink=sink)
            items = {it["idx"]: it for it in load_json(sink.path)["items"]}
            self.assertEqual(items[0]["resp"], "1 + 4 = 5\n#### 5")     # 答对的题也留档
            self.assertNotIn("rtail", items[0])
            self.assertFalse(items[1]["ok"])
            self.assertIn("中间省略", items[1]["resp"])                  # 过长: 截取头尾
            self.assertTrue(items[1]["resp"].endswith("#### 7"))
            self.assertEqual(items[1]["rtail"], "r" * iq.RTAIL_KEEP)
            self.assertNotIn("tail", items[1])
        finally:
            m.close()

    def test_instruct_detail_matches_judge(self):
        texts = ["北京", "好", "3.14", "A\nB\nC", '{"ok": true}', '{"name": "a", "age": 1}', "春天来了，花都开了。",
                 "因为下雨所以带伞", "1 2 3 4 5", "x" * 70, ""]
        for item in bankman.ifeval_zh_items():
            for text in texts:
                det = iq.instruct_detail(text, item)
                self.assertEqual(iq.judge_instruct(text, item), all(r["pass"] for r in det), (item["q"], text))
        det = iq.instruct_detail("量" * 60, {"q": "用不超过50个字介绍量子计算。"})
        self.assertEqual(det, [{"text": "不超过 50 个字", "pass": False, "actual": "实际 60 字"}])
        self.assertEqual(iq.rule_info({"t": "regex", "v": "^81$"}), {"text": "格式符合题目要求", "tech": "^81$"})
        self.assertEqual(iq.rule_text({"t": "json_keys", "v": ["name", "age"]}), "是合法的 JSON，且包含 name、age")


class TestReviewRegressions(unittest.TestCase):
    """1.4.0 审查修复的回归用例。"""

    def test_mcq_first_line_and_case(self):
        cases = [("C\n\n解释：A 选项错误", "C"), ("D\nExplanation: others are wrong.", "D"),
                 ("Answer: A careful reading shows nothing", None), ("选项B正确", "B"),
                 ("Option C is correct.", "C"), ("答案：B，因为 A 不对", "B"), ("\\boxed{D}", "D")]
        for text, want in cases:
            with self.subTest(text=text):
                self.assertEqual(iq.extract_mcq(text), want)

    def test_mcq_echo_choice_text(self):
        item = {"choices": ["Paris", "London", "Berlin", "Rome"], "answer": "B"}
        self.assertTrue(iq.judge_mcq("London", item))
        self.assertFalse(iq.judge_mcq("Rome", item))

    def test_math500_equivalents(self):
        cases = [("2516_{8}", "2516_8", True), ("5r^{5}", "5r^5", True),
                 ("-2, 1+\\sqrt{5}, 1-\\sqrt{5}", "1\\pm\\sqrt{5},-2", True),
                 ("36\\degree", "36^\\circ", True), ("10{,}080", "10,\\!080", True),
                 ("\u2212120", "-120", True), ("1,2", "12", False), ("1, 2", "1, 3", False)]
        for pred, gold, want in cases:
            with self.subTest(pred=pred, gold=gold):
                self.assertEqual(iq.math_equal(pred, gold), want)

    def test_gsm8k_extraction(self):
        cases = [("#### **18**\n（共 3 步）", "18", True), ("#### 16\n更正：#### 18", "18", True),
                 ("\\boxed{18}\n验证完毕，共 3 步。", "18", True), ("#### 1,234", "1234", True)]
        for text, gold, want in cases:
            with self.subTest(text=text):
                self.assertEqual(iq.judge_math(text, {"answer": gold}), want)

    def test_ifeval_rules(self):
        items = bankman.ifeval_zh_items()
        by_prefix = lambda p: next(x for x in items if x["q"].startswith(p))  # noqa: E731
        json_item = next(x for x in items if any(c.get("t") == "json_equals" for c in x["checks"]))
        self.assertFalse(iq.judge_instruct('{"ok": false}', json_item))
        self.assertTrue(iq.judge_instruct('```JSON\n{"ok": true}\n```', json_item))
        keys_item = next(x for x in items if any(c.get("t") == "json_keys" for c in x["checks"]))
        self.assertFalse(iq.judge_instruct('["name", "age"]', keys_item))
        three = next(x for x in items if "3个要点" in x["q"] or "三个要点" in x["q"])
        self.assertFalse(iq.judge_instruct("1. 补水\n2. 代谢\n3. 护肤\n4. 其他", three))

    def test_select_indices_stratified(self):
        sub = {"items": [{"sub": "s%d" % (i // 8)} for i in range(80)]}
        idx = iq.select_indices(sub, 10)
        self.assertEqual(len(idx), 10)
        self.assertEqual(len({sub["items"][i]["sub"] for i in idx}), 10)
        self.assertEqual(iq.select_indices(sub, None), list(range(80)))
        self.assertEqual(iq.select_indices({"items": [{}] * 5}, 3), [0, 1, 2])

    def test_compare_excludes_errors_and_other_bank(self):
        a = {"bank_id": "b", "items": [{"sid": "s", "idx": i, "ok": True} for i in range(10)]}
        b = {"bank_id": "b", "items": [{"sid": "s", "idx": i, "ok": False, "err": "timeout"} for i in range(10)]}
        self.assertEqual(iq.compare_runs(a, b)["overall"]["n"], 0)
        r = iq.compare_runs(a, dict(a, bank_id="other"))
        self.assertFalse(r["same_bank"])
        self.assertIsNone(r["overall"]["significant"])

    def test_macro_merges_mmlu(self):
        subs = [{"id": "mmlu_a", "correct": 10, "n": 10}, {"id": "mmlu_b", "correct": 0, "n": 10},
                {"id": "gsm8k", "correct": 0, "n": 10}]
        self.assertEqual(iq.macro_accuracy(subs), 25.0)

    def test_consecutive_errors_abort_then_resume_retries(self):
        import sinks
        state = {"down": True, "n": 0}

        def h(method, path, body):
            state["n"] += 1
            if state["down"]:
                return 503, {"error": "unavailable"}, None
            return 200, chat_reply("B"), None
        m = MockServer(h)
        try:
            out = temp_dir()
            sink = sinks.JsonFileSink(out)
            with self.assertRaises(RuntimeError):
                iq.run_iq(m.url + "/v1/chat/completions", "m", bank=_bank(2, 20), conc=1, sink=sink)
            doc = load_json(sink.path)
            self.assertEqual(doc["status"], "failed")
            self.assertLess(state["n"], 15)
            state["down"] = False
            iq.run_iq(m.url + "/v1/chat/completions", "m", bank=_bank(2, 20), sink=sinks.JsonFileSink(out), resume=doc)
            doc2 = load_json(sink.path)
            self.assertEqual((doc2["status"], doc2["overall"]["errors"], doc2["overall"]["correct"]), ("done", 0, 40))
        finally:
            m.close()

    def test_resume_sqlite_after_errors(self):
        """SQLite 子表只追加: 续跑删除失败条目后整体重写, 结果不重复。"""
        import sinks
        import store
        state = {"n": 0}

        def h(method, path, body):
            state["n"] += 1
            if state["n"] in (2, 5):
                return 500, {"error": "boom"}, None
            return 200, chat_reply("B"), None
        m = MockServer(h)
        try:
            db = os.path.join(temp_dir(), "t.db")
            sink = sinks.SqliteSink(db)
            iq.run_iq(m.url + "/v1/chat/completions", "m", bank=_bank(1, 6), conc=1, sink=sink)
            doc = store.get_run(sink.run_id, db_path=db)
            self.assertEqual(doc["overall"]["errors"], 2)
            iq.run_iq(m.url + "/v1/chat/completions", "m", bank=_bank(1, 6), sink=sinks.SqliteSink(db), resume=doc)
            doc2 = store.get_run(sink.run_id, db_path=db)
            self.assertEqual(len(doc2["items"]), 6)
            self.assertEqual((doc2["overall"]["errors"], doc2["overall"]["correct"]), (0, 6))
        finally:
            m.close()

    def test_trunc_only_when_wrong(self):
        import sinks
        m = MockServer(lambda *a: (200, chat_reply("B", finish="length"), None))
        try:
            sink = sinks.JsonFileSink(temp_dir())
            iq.run_iq(m.url + "/v1/chat/completions", "m", bank=_bank(1, 4), sink=sink)
            doc = load_json(sink.path)
            self.assertEqual((doc["overall"]["correct"], doc["overall"]["truncated"]), (4, 0))
        finally:
            m.close()


if __name__ == "__main__":
    unittest.main()
