# -*- coding: utf-8 -*-
"""代码生成评分标准: 以「能不能用」为准。
只有 能打开 / 不白屏 / 不报错 / 题目要求的核心操作有反应 算分; 动画、手机适配、外网依赖、代码写完整、代码关键词只作提示;
没有在浏览器里实际运行不打分。前端 (web/static/app.js 的 genChecks) 用同一份用例 tests/js/gen_score_cases.json。"""
import json
import os
import unittest

from _util import load_json  # noqa: F401  (保证 tests 目录在路径里)
import endpoints
import gen
import gen_specs
import geneval

CASES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "js", "gen_score_cases.json")


def cases():
    with open(CASES_PATH, encoding="utf-8") as f:
        return json.load(f)


def report_of(c):
    checks = [{"id": i, "label": i, "pass": p, "detail": ""} for i, p in c["checks"]]
    r = {"method": c["method"], "checks": checks, "shots": [], "notes": [], "external": []}
    if c.get("control"):
        r["control"] = c["control"]
    return r


class TestUsableStandard(unittest.TestCase):
    def test_shared_cases(self):
        for c in cases():
            with self.subTest(c["name"]):
                r = report_of(c)
                sc = gen_specs.score_checks(r["checks"], r["method"], r.get("control"))
                self.assertEqual(sc, dict(c["expect"], score=c["expect"]["score"]))

    def test_mark_scored_and_apply_eval(self):
        for c in cases():
            with self.subTest(c["name"]):
                r = geneval.mark_scored(report_of(c))
                e = c["expect"]
                self.assertEqual([x["id"] for x in r["checks"] if x["scored"]], e["core"])          # 每项检查都带着算不算分
                self.assertEqual((r["exec_pass"], r["exec_total"], r["exec_score"]), (e["pass"], e["total"], e["score"]))
                item = geneval.apply_eval({"id": "t"}, r)
                self.assertEqual((item["pass"], item["total"], item["exec_score"]), (e["pass"], e["total"], e["score"]))
                self.assertEqual(len(item["checks"]), len(c["checks"]))                            # 兼容字段仍是全部检查项

    def test_every_task_has_a_core_assertion(self):
        """每道题至少有一条核心断言: 有操作步骤的看操作, 没有的(纯动画)看动画; 操作步骤不超过 3 条。"""
        for t in gen.GEN_TASKS:
            spec = gen_specs.get(t["id"])
            steps = len(spec["steps"])
            self.assertLessEqual(steps, 3, t["id"])
            self.assertTrue(steps or spec["animated"], "%s 没有操作步骤也不是动画题, 没有核心断言" % t["id"])

    def test_static_evaluation_has_no_score(self):
        ev = geneval.Evaluator(None, browsers=1)
        ev._no_browser = True                                                    # 找不到浏览器: 只能看代码
        task = {"id": "snake", "name": "贪吃蛇", "features": [r"canvas", r"keydown"]}
        html = "<!doctype html><html><canvas></canvas><script>document.onkeydown=()=>1</script></html>"
        report = ev.evaluate(task, "/tmp/none/snake.html", html)
        self.assertEqual(report["method"], "static")
        self.assertEqual((report["exec_pass"], report["exec_total"], report["exec_score"]), (0, 0, None))
        self.assertFalse(any(c["scored"] for c in report["checks"]))              # 关键词只作参考
        item = geneval.apply_eval({"id": "snake"}, report)
        self.assertEqual((item["pass"], item["total"], item["exec_score"]), (0, 0, None))
        self.assertIn("没有实际运行", gen._eval_brief(dict(item, lines=3)))

    def test_eval_brief_lists_only_scored_failures(self):
        r = geneval.mark_scored(report_of(cases()[0]))
        r["checks"][0]["pass"] = False                                            # complete(提示项)没通过
        r["checks"][5]["pass"] = False                                            # step2 没通过
        item = geneval.apply_eval({"id": "t", "lines": 9}, r)
        brief = gen._eval_brief(item)
        self.assertIn("运行检测 4/5", brief)
        self.assertIn("step2", brief)
        self.assertNotIn("complete", brief)                                        # 提示项没通过不写

    def test_old_runs_are_scored_by_check_id(self):
        """旧任务的记录里没有 scored 标记、exec_score 是按全部检查项算的: 模型页的通过率按检查项 id 现算, 与代码生成页一致。"""
        old = {"id": "snake", "exec_score": 55.6, "eval": {"method": "browser", "checks": [
            {"id": "complete", "pass": True}, {"id": "load", "pass": True}, {"id": "nonblank", "pass": True},
            {"id": "animated", "pass": False}, {"id": "step1", "pass": True}, {"id": "no_error", "pass": True},
            {"id": "responsive", "pass": False}, {"id": "self_contained", "pass": False}]}}
        static = {"id": "tetris", "exec_score": 60.0, "eval": {"method": "static", "checks": [{"id": "doctype", "pass": True}]}}
        legacy = {"id": "pelican", "exec_score": 90.0}                              # 更早的、没有 eval 的
        env = {"id": "koi", "eval": {"method": "browser", "control": {"reproduced": False}, "checks": [
            {"id": "load", "pass": True}, {"id": "step1", "pass": True}, {"id": "no_error", "pass": False}]}}
        s = endpoints.gen_summary([old, static, legacy, env], 4)
        self.assertEqual((s["done"], s["exec"], s["method"]), (4, 100.0, "mixed"))   # 只平均实际运行的两件, 都是 100
        self.assertEqual(endpoints._usable_score(static), None)
        self.assertEqual(endpoints._usable_score(legacy), None)
        old["eval"]["checks"][4]["pass"] = False                                     # step1 没反应: 4 项里过 3 项
        self.assertEqual(endpoints._usable_score(old), 75.0)


if __name__ == "__main__":
    unittest.main()
