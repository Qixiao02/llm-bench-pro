# -*- coding: utf-8 -*-
"""geneval.py (代码生成作品的评测) 的中文 / 英文消息测试。约定见 CONTRIBUTING.md「服务端消息与翻译」。

不启动真实浏览器: 用脚本化的假页面 (FakePage) 驱动 Prober / probe_work, 像素统计换成固定值, 时间换成虚拟时钟;
评审用本地 MockServer。检查:
  1. 每项检查的说明 (checks[].detail)、notes、截图说明 (shots[].caption)、对照运行的结论: 中文和转换前逐字一致, 英文没有汉字
  2. 检查项的名称 (label) 是测试内容: 不随语言变, 前端靠它的前缀 (交互： / 源码特征 /) 去前缀
  3. 页面卡死后不做对照运行 (以前靠说明文字里的「卡死」判断, 现在不能再靠文字)
  4. 源码检查、浏览器池 (Evaluator)、评审失败的说明、命令行帮助
  5. 发给评审模型的重试提示是测试内容, 英文界面下也和中文一样
  6. gen.run_gen 在任务语言下跑完 (评测在线程池的工作线程里), 存进结果的评测说明是对应的语言
"""
import contextlib
import io
import json
import os
import re
import types
import unittest
from unittest import mock

from _util import MockServer, chat_reply, load_json, temp_dir  # 先设 LLM_BENCH_LANG=zh, 再导入包内模块
import cdp
import gen
import gen_specs
import geneval
import i18n
import sinks
from test_i18n_py import LangCase, STORED_TEXT_KEYS, assert_english, english_flow, zh_found


# ================================================================ 假页面 (不启动浏览器)

GOOD_STATS = {"w": 320, "h": 200, "lum_mean": 120.0, "lum_std": 40.0, "dominant_ratio": 0.6512, "colors": 12}
BLANK_STATS = {"w": 320, "h": 200, "lum_mean": 255.0, "lum_std": 0.0, "dominant_ratio": 1.0, "colors": 1}
FOUND = {"x": 100, "y": 100, "a": 50, "rank": [0, 50], "text": "Start"}
ASSERT_JS = "document.title === 'ready'"
COUNT_JS = "document.querySelectorAll('.item').length"
COMPLETE_HTML = "<!doctype html><html><head><meta name=viewport></head><body><script>1</script></body></html>"
TASK_ID = "__i18n_geneval_probe"


class Clock(object):
    """虚拟时钟: sleep 只推进时间, 不真的等, 检测里几十秒的等待瞬间跑完。"""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(float(seconds), 0.0)


class FakePage(object):
    """脚本化的假页面, 只实现 Prober 用到的方法。index 0 是检测页, 1 是对照运行的干净页。sc 是场景 (见 SCENARIOS)。"""

    def __init__(self, sc, index, clock):
        self.sc, self.index, self.clock = sc, index, clock
        self.events = []            # (时间, 方法, 参数), 和 cdp.Page.events 一样
        self.mobile = False
        self.reads = 0              # 探针计数被读了几次 (每读一次各计数增长一点)
        self.shots = 0
        self.measures = dict((js, list(v)) for js, v in sc["measures"].items())
        self.finds = list(sc["finds"])

    def _event(self, method, params):
        self.events.append((self.clock.monotonic(), method, params))

    def _errors(self, descriptions):
        for d in descriptions:
            self._event("Runtime.exceptionThrown", {"exceptionDetails": {"exception": {"description": d + "\n    at file:///w.js:1"}}})

    def send(self, method, params=None, timeout=15):
        sc, p = self.sc, params or {}
        if method == "Emulation.setDeviceMetricsOverride":
            self.mobile = bool(p.get("mobile"))
        elif method == "Page.navigate":
            if self.index == 1:
                if sc.get("control_fail"):
                    raise cdp.CDPError("Page.navigate: control page failed")
                self._errors(sc.get("control_errors") or [])
            else:
                if sc.get("fail_navigate"):
                    raise cdp.CDPError("Page.navigate: fake failure")
                self._errors(sc.get("mobile_errors" if self.mobile else "errors") or [])
                if not self.mobile:
                    for url, typ in sc.get("requests") or []:
                        self._event("Network.requestWillBeSent", {"request": {"url": url}, "type": typ})
        elif method == "Input.dispatchMouseEvent" and p.get("type") == "mousePressed" and self.index == 0:
            if sc.get("fail_on_press"):
                raise cdp.CDPError("Input.dispatchMouseEvent: fake failure")
            if sc.get("click_error"):
                self._errors([sc["click_error"]])
        return {}

    def evaluate(self, expr, timeout=10):
        sc = self.sc
        if expr == "1":
            if sc.get("hung") and self.index == 0:
                raise cdp.CDPError("Runtime.evaluate: timed out")
            return 1
        if expr == "JSON.stringify(window.__probe||{})":
            self.reads += 1
            return json.dumps({"raf": self.reads * 3, "draws": self.reads * 7, "mutations": self.reads * sc["mutation_step"],
                               "calls": {"click": self.reads * sc["handlers"]}, "listeners": {}, "dialogs": 0})
        if "scrollWidth" in expr:
            return json.dumps(sc["mobile"])
        if expr.lstrip().startswith("((re, css)"):   # geneval.FIND_JS
            return self.finds.pop(0) if len(self.finds) > 1 else self.finds[0]
        m = re.match(r"^\(\(\) => \{ try \{ return (.*); \} catch \(e\) \{ return null; \} \}\)\(\)$", expr, re.S)
        if m:
            values = self.measures.get(m.group(1), [None])
            return values.pop(0) if len(values) > 1 else values[0]
        raise AssertionError("假页面没有准备这个表达式的结果: %r" % expr[:80])

    def screenshot(self, fmt="png", scale=1.0, quality=70, width=1280, height=800):
        self.shots += 1
        if self.sc.get("fail_shot_after") is not None and self.index == 0 and self.shots > self.sc["fail_shot_after"]:
            raise cdp.CDPError("Page.captureScreenshot: fake failure")
        return b"fake-" + fmt.encode()

    def wait_event(self, method, timeout=15, since=0.0):
        if self.index == 0 and self.sc.get("loaded") is False:
            return None
        return {}

    def close(self):
        pass


class FakeBrowser(object):
    version = "FakeChrome/1.0"

    def __init__(self, sc, clock):
        self.sc, self.clock, self.pages = sc, clock, []

    def new_page(self):
        page = FakePage(self.sc, len(self.pages), self.clock)
        self.pages.append(page)
        return page

    def close(self):
        pass


class Images(object):
    """替换 cdp.image_stats / cdp.image_diff: 按场景给固定的像素统计和帧差, 不用真的解码图片。"""

    def __init__(self, sc):
        self.stats, self.diffs = sc["stats"], sc["diffs"]
        self.n_stats = self.n_diffs = 0

    def image_stats(self, png):
        i, self.n_stats = self.n_stats, self.n_stats + 1
        return dict(self.stats[min(i, len(self.stats) - 1)])

    def image_diff(self, a, b, threshold=24):
        v = self.diffs[self.n_diffs % len(self.diffs)]
        self.n_diffs += 1
        return v


def make_spec(labels="en"):
    """一份覆盖各种步骤的评测规格。labels="zh" 时步骤名是中文 (真实题目的步骤名就是中文), "en" 时是英文 (扫描汉字用)。"""
    zh = labels == "zh"
    return {
        "animated": True, "idle": 1.0, "responsive": True,
        "setup": [{"find": "start", "do": "click", "optional": True}, {"wait": 0.3}],
        "steps": [
            {"label": "按空格键跳跃" if zh else "press space", "actions": [{"key": " "}], "settle": 0.6},
            {"label": "点击后出现提示" if zh else "click shows a hint", "actions": [{"click": [0.5, 0.5]}], "settle": 0.6,
             "assert": ASSERT_JS},
            {"label": "点击后数量增加" if zh else "click adds items", "actions": [{"click": [0.4, 0.4]}], "settle": 0.6,
             "count": COUNT_JS, "gain": 2},
            {"label": "找到按钮并点击" if zh else "find and click a button",
             "actions": [{"find": "go", "do": "click"}, {"find": "zz", "do": "hover", "optional": True}], "settle": 0.6},
            {"label": "滚动页面" if zh else "scroll the page", "actions": [{"wheel": 800}], "settle": 0.6, "native": True},
        ],
        "checklist": [{"id": "t1", "label": "x"}],
    }


def scenario(**over):
    sc = {"measures": {ASSERT_JS: [False, True], COUNT_JS: [3, 5]}, "finds": [FOUND, FOUND, None], "handlers": 1,
          "mutation_step": 2, "mobile": {"sw": 390, "cw": 390, "iw": 390, "meta": True}, "stats": [GOOD_STATS],
          "diffs": [0.05] + [0.001, 0.05] * 12, "html": COMPLETE_HTML}
    sc.update(over)
    return sc


LONG_ERRORS = ["TypeError: cannot read properties of undefined (reading 'x%d') " % i + "while drawing frame " * 6 for i in range(6)]

SCENARIOS = {
    "ok": scenario(),
    "no_handler": scenario(handlers=0, diffs=[0.05] + [0.001, 0.2] * 12),
    "assert_fails": scenario(measures={ASSERT_JS: [False, False], COUNT_JS: [3, 3]}),
    "assert_held_before": scenario(measures={ASSERT_JS: [True, True], COUNT_JS: [3, 5]}),
    "not_animated": scenario(diffs=[0.0] + [0.001, 0.05] * 12),
    "find_missing": scenario(finds=[None]),
    "load_timeout": scenario(loaded=False),
    "hung": scenario(hung=True),
    "blank": scenario(stats=[BLANK_STATS]),
    "errors_reproduced": scenario(errors=["ReferenceError: foo is not defined", "TypeError: bar is not a function",
                                          "ReferenceError: foo is not defined"],
                                  control_errors=["ReferenceError: foo is not defined"]),
    "errors_not_reproduced": scenario(errors=["Error: only in the check environment"]),
    "errors_long": scenario(errors=LONG_ERRORS, control_errors=LONG_ERRORS[:1]),
    "errors_long_not_reproduced": scenario(errors=LONG_ERRORS),
    "one_error_control_fails": scenario(errors=["Error: boom"], control_fail=True),
    "click_error": scenario(click_error="Error: handler blew up"),
    "click_fails": scenario(fail_on_press=True),
    "mobile_bad": scenario(mobile={"sw": 520.6, "cw": 390, "iw": 390, "meta": False}, stats=[GOOD_STATS, BLANK_STATS],
                           mobile_errors=["Error: layout script failed"]),
    "mobile_fine": scenario(mobile={"sw": 390, "cw": 390, "iw": 390, "meta": True}),
    "external_hard": scenario(requests=[("https://cdn.example.com/a.js", "Script"), ("https://cdn.example.com/b.css", "Stylesheet"),
                                        ("https://api.example.com/x", "Fetch"), ("wss://live.example.com/s", "WebSocket"),
                                        ("https://fonts.googleapis.com/css", "Stylesheet")]),
    "external_one_font": scenario(requests=[("https://fonts.gstatic.com/f.woff2", "Font")]),
    "external_soft_many": scenario(requests=[("https://fonts.gstatic.com/f.woff2", "Font"), ("https://img.example.com/a.png", "Image"),
                                             ("https://img.example.com/b.png", "Image")]),
    "interrupted_at_load": scenario(fail_navigate=True),
    "interrupted_mid_run": scenario(fail_shot_after=1),
    "incomplete_html": scenario(html="<html><script>let a = 1"),
}


class Probed(object):
    def __init__(self, report, browser, shots_files):
        self.report, self.browser, self.shots_files = report, browser, shots_files

    def check(self, cid):
        return next(c for c in self.report["checks"] if c["id"] == cid)

    def details(self):
        return dict((c["id"], c["detail"]) for c in self.report["checks"])

    def captions(self):
        return [s["caption"] for s in self.report["shots"]]


def run_probe(mod, name_or_sc, lang="zh", labels="en"):
    """用假页面跑一次 mod.probe_work (mod 可以是新的 geneval, 也可以是别处载入的旧版), 在 lang 语言下。"""
    sc = SCENARIOS[name_or_sc] if isinstance(name_or_sc, str) else name_or_sc
    clock, images = Clock(), Images(sc)
    browser = FakeBrowser(sc, clock)
    html_path = os.path.join(temp_dir(), "work.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(sc["html"])
    shots_dir = html_path[:-5] + ".shots"
    fake_time = types.SimpleNamespace(sleep=clock.sleep, monotonic=clock.monotonic)
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.dict(gen_specs.SPECS, {TASK_ID: make_spec(labels)}))
        stack.enter_context(mock.patch.object(cdp, "image_stats", images.image_stats))
        stack.enter_context(mock.patch.object(cdp, "image_diff", images.image_diff))
        stack.enter_context(mock.patch.object(mod, "time", fake_time))
        stack.enter_context(i18n.use_lang(lang))
        report = mod.probe_work(browser, html_path, TASK_ID, shots_dir)
    files = sorted(os.listdir(shots_dir)) if os.path.isdir(shots_dir) else None
    return Probed(report, browser, files)


def zh_outside_labels(obj):
    """对象里含汉字的字符串 (不算检查项名称 label: 它是测试内容, 中文是对的)。"""
    return [(p, s) for p, s in zh_found(obj) if not p.endswith(".label")]


# ================================================================ 1. 运行检测: 每项检查的说明、截图说明、notes

STEP_EN = "Screen change 5.00% (equal-length idle baseline 0.10%), DOM mutations 2 (baseline 2), event handler calls 1"
STEP_ZH = "画面变化 5.00%（等长空闲基线 0.10%），DOM 变更 2（基线 2），事件处理 1 次"
CONTROL_SAME_EN = ("Control run: the same errors occur with no check scripts injected, so the problem is in the "
                   "generated page itself")
CONTROL_SAME_ZH = "对照：不注入任何检测脚本单独运行同样报错，是作品自身的问题"
CONTROL_GONE_EN = ("Control run: no errors when run without the check scripts, so the errors may be caused by the "
                   "checking environment; please verify manually")
CONTROL_GONE_ZH = "对照：不注入检测脚本单独运行时没有报错，可能是检测环境引起的，请人工确认"


class TestProbeMessages(LangCase):
    """probe_work 全流程 (假页面): 说明文字中文和转换前逐字一致, 英文没有汉字。"""

    def probe(self, name, lang, labels=None):
        return run_probe(geneval, name, lang, labels or ("zh" if lang == "zh" else "en"))

    def details(self, name, lang):
        return self.probe(name, lang).details()

    def test_all_checks_pass(self):
        self.assertEqual(self.details("ok", "zh"), {
            "complete": "", "load": "", "nonblank": "主色占比 65.1%，颜色数 12",
            "animated": "画面变化 5.00%，rAF 3 次，绘制调用 7 次",
            "step1": STEP_ZH, "step2": "功能断言通过", "step3": "功能断言通过（计数 3 → 5，需增加 2）",
            "step4": "命中「Start」；未找到元素 zz；" + STEP_ZH, "step5": STEP_ZH,
            "no_error": "", "responsive": "内容宽 390px / 设备宽 390px", "self_contained": ""})
        self.assertEqual(self.details("ok", "en"), {
            "complete": "", "load": "", "nonblank": "Dominant color covers 65.1% of the screen, color count 12",
            "animated": "Screen change 5.00%, rAF calls 3, draw calls 7",
            "step1": STEP_EN, "step2": "Functional assertion passed",
            "step3": "Functional assertion passed (count 3 → 5, must increase by 2)",
            "step4": 'Matched "Start"; Element not found: zz; ' + STEP_EN, "step5": STEP_EN,
            "no_error": "", "responsive": "Content width 390px / device width 390px", "self_contained": ""})

    def test_screenshot_captions(self):
        self.assertEqual(self.probe("ok", "zh").captions(), [
            "首屏（加载后约 1.2 秒）", "空闲 1.0 秒后", "交互「按空格键跳跃」之后", "交互「点击后出现提示」之后",
            "交互「点击后数量增加」之后", "交互「找到按钮并点击」之后", "交互「滚动页面」之后", "移动端 390px 视口"])
        en = self.probe("ok", "en")
        self.assertEqual(en.captions(), [
            "First screen (about 1.2 s after load)", "After 1.0 s idle", 'After interaction "press space"',
            'After interaction "click shows a hint"', 'After interaction "click adds items"',
            'After interaction "find and click a button"', 'After interaction "scroll the page"', "Mobile 390px viewport"])
        self.assertEqual(en.shots_files[0], "01_initial.jpg")   # 文件名不随语言变

    def test_interaction_failures(self):
        no_handler = {"zh": self.details("no_handler", "zh"), "en": self.details("no_handler", "en")}
        self.assertEqual(no_handler["zh"]["step1"], "画面变化 20.00%（等长空闲基线 0.10%），DOM 变更 2（基线 2），事件处理 0 次；"
                                                    "作品没有处理该输入，变化来自自身动画或样式")
        self.assertEqual(no_handler["en"]["step1"],
                         "Screen change 20.00% (equal-length idle baseline 0.10%), DOM mutations 2 (baseline 2), event handler calls 0; "
                         "the generated page did not handle this input, so the change comes from its own animation or styling")
        self.assertNotIn("作品没有处理", no_handler["zh"]["step5"])          # 原生交互 (native) 不要求处理器响应
        self.assertNotIn("did not handle", no_handler["en"]["step5"])
        held = {"zh": self.details("assert_held_before", "zh")["step2"], "en": self.details("assert_held_before", "en")["step2"]}
        self.assertEqual(held["zh"], "功能断言在操作前已成立，无法确认由本次操作产生")
        self.assertEqual(held["en"], "Functional assertion already held before the action; cannot confirm this action caused it")
        failed_zh, failed_en = self.details("assert_fails", "zh"), self.details("assert_fails", "en")
        self.assertEqual((failed_zh["step2"], failed_zh["step3"]), ("功能断言未通过", "功能断言未通过（计数 3 → 3，需增加 2）"))
        self.assertEqual((failed_en["step2"], failed_en["step3"]),
                         ("Functional assertion failed", "Functional assertion failed (count 3 → 3, must increase by 2)"))
        self.assertEqual((self.details("find_missing", "zh")["step4"], self.details("find_missing", "en")["step4"]),
                         ("未找到元素 go", "Element not found: go"))

    def test_load_animation_and_blank_screen(self):
        self.assertEqual(self.details("load_timeout", "zh")["load"], "加载超时")
        self.assertEqual(self.details("load_timeout", "en")["load"], "Load timed out")
        self.assertEqual(self.details("not_animated", "zh")["animated"], "画面变化 0.00%，rAF 3 次，绘制调用 7 次")
        self.assertEqual(self.details("not_animated", "en")["animated"], "Screen change 0.00%, rAF calls 3, draw calls 7")
        zh, en = self.details("blank", "zh"), self.details("blank", "en")
        self.assertEqual((zh["nonblank"], zh["no_error"], zh["responsive"]),
                         ("主色占比 100.0%，颜色数 1", "首屏白屏，无法确认脚本正常运行", "桌面首屏白屏，不检查移动端"))
        self.assertEqual((en["nonblank"], en["no_error"], en["responsive"]),
                         ("Dominant color covers 100.0% of the screen, color count 1", "Blank first screen; cannot confirm the script ran normally",
                          "Blank first screen on desktop; mobile not checked"))

    def test_hung_page_gets_no_control_run_in_any_language(self):
        """页面卡死后不做对照运行。以前靠说明文字里有没有「卡死」判断, 说明文字随语言变以后不能再靠文字。"""
        zh, en = self.probe("hung", "zh"), self.probe("hung", "en")
        for probed, lang in ((zh, "zh"), (en, "en")):
            self.assertEqual(len(probed.browser.pages), 1, lang)
            self.assertIsNone(probed.report["control"], lang)
            self.assertEqual([c["id"] for c in probed.report["checks"]][:4], ["complete", "load", "no_error", "nonblank"])
        self.assertEqual((zh.details()["load"], zh.details()["no_error"], zh.details()["step3"]),
                         ("主线程无响应(疑似死循环)", "页面卡死, 无法继续检测", "页面卡死，未检测"))
        self.assertEqual((en.details()["load"], en.details()["no_error"], en.details()["step3"]),
                         ("Main thread not responding (possible infinite loop)", "Page hung; cannot continue the runtime check",
                          "Page hung; not checked"))

    def test_error_lists_are_counted_and_the_control_run_is_appended(self):
        cases = (
            ("errors_reproduced", "3 条：ReferenceError: foo is not defined；TypeError: bar is not a function。" + CONTROL_SAME_ZH,
             "3 errors: ReferenceError: foo is not defined; TypeError: bar is not a function. " + CONTROL_SAME_EN, True),
            ("errors_not_reproduced", "1 条：Error: only in the check environment。" + CONTROL_GONE_ZH,
             "1 error: Error: only in the check environment. " + CONTROL_GONE_EN, False))
        for name, zh, en, reproduced in cases:
            with self.subTest(name=name):
                p_zh, p_en = self.probe(name, "zh"), self.probe(name, "en")
                self.assertEqual(p_zh.details()["no_error"], zh)
                self.assertEqual(p_en.details()["no_error"], en)
                for p in (p_zh, p_en):
                    self.assertEqual(p.report["control"]["reproduced"], reproduced)
                    self.assertEqual(len(p.browser.pages), 2)                   # 有对照运行

    def test_long_error_lists_are_cut_the_same_way(self):
        zh, en = self.details("errors_long", "zh")["no_error"], self.details("errors_long", "en")["no_error"]
        self.assertTrue(zh.startswith("6 条：TypeError: cannot read properties of undefined (reading 'x0')"))
        self.assertTrue(en.startswith("6 errors: TypeError: cannot read properties of undefined (reading 'x0')"))
        self.assertEqual(zh.index("。对照"), 300)                   # 错误部分最多 300 个字符
        self.assertEqual(en.index(". Control run: "), 300)
        self.assertLessEqual(len(zh), 420)                         # 加上对照结论最多 420 个字符
        self.assertLessEqual(len(en), 420)
        self.assertTrue(zh.endswith(CONTROL_SAME_ZH))
        gone_zh = self.details("errors_long_not_reproduced", "zh")["no_error"]
        gone_en = self.details("errors_long_not_reproduced", "en")["no_error"]
        self.assertTrue(gone_zh.endswith(CONTROL_GONE_ZH))         # 中文的结论短, 完整保留
        self.assertEqual(len(gone_en), 420)                        # 英文的结论更长: 整条最多 420 个字符, 尾巴被截掉
        self.assertTrue((". " + CONTROL_GONE_EN).startswith(gone_en[300:]))

    def test_control_run_failure_is_stored_as_an_error_not_translated(self):
        for lang, want in (("zh", "1 条：Error: boom"), ("en", "1 error: Error: boom")):
            p = self.probe("one_error_control_fails", lang)
            self.assertEqual(p.report["control"], {"error": "Page.navigate: control page failed"})   # 异常原文原样存
            self.assertEqual(p.details()["no_error"], want)

    def test_error_thrown_by_an_interaction(self):
        zh, en = self.probe("click_error", "zh"), self.probe("click_error", "en")
        self.assertEqual(zh.details()["step2"], "交互触发异常：Error: handler blew up")
        self.assertEqual(en.details()["step2"], "Interaction raised an exception: Error: handler blew up")
        self.assertEqual(zh.details()["step4"], "命中「Start」；未找到元素 zz；交互触发异常：Error: handler blew up")
        self.assertEqual(en.details()["step4"], 'Matched "Start"; Element not found: zz; Interaction raised an exception: Error: handler blew up')
        self.assertEqual(zh.details()["no_error"], "4 条：Error: handler blew up。" + CONTROL_GONE_ZH)
        self.assertEqual(en.details()["no_error"], "4 errors: Error: handler blew up. " + CONTROL_GONE_EN)

    def test_page_not_responding_and_warm_up_failure(self):
        zh, en = self.probe("click_fails", "zh"), self.probe("click_fails", "en")
        self.assertEqual(zh.details()["step2"], "页面无响应：Input.dispatchMouseEvent: fake failure")
        self.assertEqual(en.details()["step2"], "Page not responding: Input.dispatchMouseEvent: fake failure")
        self.assertEqual(zh.report["notes"], ["预热动作失败: Input.dispatchMouseEvent: fake failure"])
        self.assertEqual(en.report["notes"], ["Warm-up action failed: Input.dispatchMouseEvent: fake failure"])

    def test_mobile_problems(self):
        zh, en = self.probe("mobile_bad", "zh"), self.probe("mobile_bad", "en")
        self.assertEqual(zh.details()["responsive"], "缺少 viewport meta；布局宽 520px 超出设备宽 390px；移动端白屏")   # 520.6 取整成 520
        self.assertEqual(en.details()["responsive"],
                         "Missing viewport meta tag; Layout width 520px exceeds device width 390px; Blank screen on mobile")
        self.assertEqual(zh.report["notes"], ["移动端加载异常：Error: layout script failed"])
        self.assertEqual(en.report["notes"], ["Exception while loading on mobile: Error: layout script failed"])

    def test_external_dependencies(self):
        urls = ["https://cdn.example.com/a.js", "https://cdn.example.com/b.css", "https://api.example.com/x"]   # 最多列 3 个, 网络字体不算
        self.assertEqual(self.details("external_hard", "zh")["self_contained"], "外部依赖被拦截：" + "，".join(urls))
        self.assertEqual(self.details("external_hard", "en")["self_contained"], "External dependencies blocked: " + ", ".join(urls))

    def test_soft_external_links_are_counted_with_singular_and_plural(self):
        one = {"zh": self.details("external_one_font", "zh")["self_contained"], "en": self.details("external_one_font", "en")["self_contained"]}
        many = {"zh": self.details("external_soft_many", "zh")["self_contained"], "en": self.details("external_soft_many", "en")["self_contained"]}
        self.assertEqual(one["zh"], "仅网络字体/图片等外链 1 个（已拦截，不影响功能）")
        self.assertEqual(one["en"], "Only 1 external link, such as a web font or image (blocked; no effect on functionality)")
        self.assertEqual(many["zh"], "仅网络字体/图片等外链 3 个（已拦截，不影响功能）")
        self.assertEqual(many["en"], "Only 3 external links, such as web fonts or images (blocked; no effect on functionality)")
        for name in ("external_one_font", "external_soft_many"):
            self.assertTrue(self.probe(name, "en").check("self_contained")["pass"])      # 只有网络字体 / 图片不算失败

    def test_interrupted_runs(self):
        zh, en = self.probe("interrupted_at_load", "zh"), self.probe("interrupted_at_load", "en")
        self.assertEqual(zh.report["notes"], ["检测中断: Page.navigate: fake failure"])
        self.assertEqual(en.report["notes"], ["Runtime check interrupted: Page.navigate: fake failure"])
        self.assertEqual(zh.details()["load"], "Page.navigate: fake failure")            # 异常原文原样存
        self.assertEqual(en.details()["load"], "Page.navigate: fake failure")
        self.assertEqual(zh.details()["step1"], "检测中断，未执行")
        self.assertEqual(en.details()["step1"], "Runtime check interrupted; not run")
        self.assertEqual(zh.details()["no_error"], "检测中断，未执行。" + CONTROL_GONE_ZH)   # 中断不是卡死: 仍会做对照运行
        self.assertEqual(en.details()["no_error"], "Runtime check interrupted; not run. " + CONTROL_GONE_EN)
        mid_zh, mid_en = self.probe("interrupted_mid_run", "zh"), self.probe("interrupted_mid_run", "en")
        self.assertEqual(mid_zh.details()["probe"], "检测中断（页面无响应或超时）：Page.captureScreenshot: fake failure")
        self.assertEqual(mid_en.details()["probe"],
                         "Runtime check interrupted (page not responding or timed out): Page.captureScreenshot: fake failure")

    def test_every_scenario_in_english_has_no_chinese_and_behaves_like_chinese(self):
        """所有场景: 英文下 (检查项名称 label 除外) 没有汉字, 词典没有缺键; 通过与否、有没有对照运行、截图和中文一样。"""
        for name in SCENARIOS:
            with self.subTest(scenario=name):
                with english_flow() as flow:
                    en = self.probe(name, "en")
                flow.assert_clean(self)
                self.assertEqual(zh_outside_labels(en.report), [])
                zh = self.probe(name, "zh", labels="en")
                self.assertEqual([(c["id"], c["pass"]) for c in en.report["checks"]], [(c["id"], c["pass"]) for c in zh.report["checks"]])
                self.assertEqual((en.shots_files, len(en.browser.pages)), (zh.shots_files, len(zh.browser.pages)))
                self.assertEqual((en.report["control"] or {}).get("reproduced"), (zh.report["control"] or {}).get("reproduced"))
                self.assertEqual(len(en.report["notes"]), len(zh.report["notes"]))

    def test_incomplete_html_is_a_failed_check_without_detail(self):
        for lang in ("zh", "en"):
            probed = self.probe("incomplete_html", lang)
            self.assertFalse(probed.check("complete")["pass"])
            self.assertEqual(probed.check("complete")["detail"], "")


class TestCheckLabelsAreContent(LangCase):
    """检查项名称 (label) 是测试内容: 不随语言变。前端按 id 显示大白话名称, 并用正则去掉「交互：」「源码特征 /」前缀。"""

    FIXED = {"complete": "代码完整输出（</html> 闭合、script 配对）", "load": "页面加载完成且未卡死",
             "nonblank": "首屏有实际渲染内容（非白屏/纯色）", "animated": "空闲时持续动画/渲染",
             "no_error": "运行无未捕获异常/控制台错误", "responsive": "移动端 390px 适配（viewport 声明、无横向溢出）",
             "self_contained": "单文件自包含（无外部脚本/样式/接口依赖）"}

    def test_labels_are_the_same_in_every_language(self):
        labels = {}
        for lang in ("zh", "en"):
            labels[lang] = dict((c["id"], c["label"]) for c in run_probe(geneval, "ok", lang, "en").report["checks"])
        self.assertEqual(labels["zh"], labels["en"])
        for cid, label in self.FIXED.items():
            self.assertEqual(labels["en"][cid], label)
        self.assertEqual(labels["en"]["step1"], "交互：press space")           # 前缀不变, 后面是题目里的步骤名
        self.assertTrue(all(labels["en"]["step%d" % i].startswith("交互：") for i in range(1, 6)))

    def test_skipped_checks_keep_their_labels(self):
        hung = run_probe(geneval, "hung", "en", "en")
        self.assertEqual(hung.check("nonblank")["label"], self.FIXED["nonblank"])
        self.assertEqual(hung.check("animated")["label"], self.FIXED["animated"])
        self.assertEqual(hung.check("responsive")["label"], self.FIXED["responsive"])
        self.assertEqual(hung.check("step2")["label"], "交互：click shows a hint")
        self.assertEqual(hung.check("no_error")["label"], "运行无未捕获异常")     # 卡死时 no_error 的名称比正常的短, 以前就是这样

    def test_source_checks_keep_their_labels_and_prefixes(self):
        task = {"features": [r"<canvas", r"keydown"]}
        for lang in ("zh", "en"):
            with i18n.use_lang(lang):
                report = geneval.static_checks("<html><canvas></canvas></html>", task)
            labels = dict((c["id"], c["label"]) for c in report["checks"])
            self.assertEqual(labels, {"doctype": "HTML 文档结构", "complete": self.FIXED["complete"], "self_contained": "无外部脚本/样式依赖",
                                      "f1": "源码特征 /<canvas/", "f2": "源码特征 /keydown/"})

    def test_apply_eval_still_copies_the_labels_into_features(self):
        with i18n.use_lang("en"):
            report = geneval.static_checks("<html></html>", {"features": ["a"]})
            report["exec_score"] = 0.0
            item = geneval.apply_eval({}, report)
        self.assertEqual(item["features"], ["HTML 文档结构", self.FIXED["complete"], "无外部脚本/样式依赖", "源码特征 /a/"])


# ================================================================ 2. 源码检查、浏览器池、评审、命令行

TASK = {"id": "snake", "name": "Snake", "prompt": "make a snake game", "features": [r"<canvas", r"keydown"]}
HTML = "<!doctype html><html><canvas></canvas><script>// keydown\nlet a = 1</script></html>"


class TestStaticChecks(LangCase):
    """没有浏览器时的降级: 只检查源码, 结果标注 method=static。"""

    def test_details_and_default_note(self):
        for lang, detail, note in (("zh", "已去除注释后匹配", "未找到无头浏览器，降级为源码检查"),
                                   ("en", "Matched after stripping comments", "Headless browser not found; falling back to a code-only check")):
            with self.subTest(lang=lang):
                with i18n.use_lang(lang):
                    report = geneval.static_checks(HTML, TASK)
                    custom = geneval.static_checks(HTML, TASK, "my note")
                self.assertEqual(report["method"], "static")
                self.assertEqual(report["notes"], [note])
                self.assertEqual(custom["notes"], ["my note"])                         # 调用方给的说明原样用
                self.assertEqual(dict((c["id"], c["detail"]) for c in report["checks"]),
                                 {"doctype": "", "complete": "", "self_contained": "", "f1": detail, "f2": detail})
                self.assertEqual([c["pass"] for c in report["checks"]], [True, True, True, True, False])   # 注释里的 keydown 不算

    def test_english_has_no_chinese_outside_labels(self):
        with english_flow() as flow:
            report = geneval.static_checks(HTML, TASK)
        flow.assert_clean(self)
        self.assertEqual(zh_outside_labels(report), [])
        assert_english(self, report["notes"])


class FakeChrome(object):
    """替换 cdp.Browser: 不启动真实浏览器。"""
    version = "FakeChrome/1.0"

    def __init__(self, *a, **k):
        pass

    def close(self):
        pass


class TestEvaluatorMessages(LangCase):
    """Evaluator (浏览器池和编排): 说明文字存进评测结果的 notes / browser_error / judge.error, 日志走 log。"""

    def setUp(self):
        LangCase.setUp(self)
        self.html_path = os.path.join(temp_dir(), "w.html")

    def evaluate(self, ev):
        return ev.evaluate(TASK, self.html_path, HTML)

    def test_no_browser_on_this_machine(self):
        cfg = {"base": "http://127.0.0.1:9", "model": "judge-m"}      # 没有截图时不会去连评审服务
        want = {
            "zh": ("本机没有找到 Chrome / Edge 浏览器",
                   "后台浏览器不可用，作品没有实际运行，只检查了源代码：本机没有找到 Chrome / Edge 浏览器",
                   "无截图（未进行浏览器运行检测），跳过视觉评审"),
            "en": ("No Chrome / Edge browser found on this machine",
                   "Headless browser unavailable; the generated page was not actually run, only its source code was checked: "
                   "No Chrome / Edge browser found on this machine",
                   "No screenshots (no browser runtime check was performed); visual review skipped")}
        for lang, (error, note, judge_error) in want.items():
            with self.subTest(lang=lang), mock.patch.object(geneval.cdp, "find_browser", return_value=None), i18n.use_lang(lang):
                ev = geneval.Evaluator(cfg, browsers=1)
                self.assertEqual((ev.method, ev.browser_error, ev.meta()["browser_error"]), ("static", error, error))
                report = self.evaluate(ev)
                self.assertEqual(report["method"], "static")
                self.assertEqual(report["notes"], [note])
                self.assertEqual(report["judge"], {"model": "judge-m", "error": judge_error})

    def test_unknown_reason(self):
        for lang, want in (("zh", "未知原因"), ("en", "unknown reason")):
            with self.subTest(lang=lang), mock.patch.object(geneval.cdp, "find_browser", return_value=None), i18n.use_lang(lang):
                ev = geneval.Evaluator(None, browsers=1)
                ev.browser_error = None
                sep = "：" if lang == "zh" else ": "
                self.assertTrue(self.evaluate(ev)["notes"][0].endswith(sep + want))

    def test_browser_that_cannot_start(self):
        want = {"zh": ("后台浏览器出错，作品没有实际运行，只检查了源代码：cannot launch",
                       "  ⚠ 后台浏览器无法启动，本次作品只能做源码检查：cannot launch",
                       "后台浏览器不可用，作品没有实际运行，只检查了源代码：cannot launch"),
                "en": ("Headless browser error; the generated page was not actually run, only its source code was checked: cannot launch",
                       "  ⚠ Cannot start the headless browser; pages in this run can only get a code-only check: cannot launch",
                       "Headless browser unavailable; the generated page was not actually run, only its source code was checked: cannot launch")}
        for lang, (first, log_line, third) in want.items():
            lines = []
            with self.subTest(lang=lang), mock.patch.object(geneval.cdp, "find_browser", return_value="fake"), \
                    mock.patch.object(geneval.cdp, "Browser", side_effect=RuntimeError("cannot launch")), i18n.use_lang(lang):
                ev = geneval.Evaluator(None, browsers=1, log=lines.append)
                self.assertEqual(self.evaluate(ev)["notes"], [first])
                self.assertEqual(lines, [])
                self.assertEqual(self.evaluate(ev)["notes"], [first])          # 连续启动失败两次: 写一条日志, 之后不再尝试
                self.assertEqual(lines, [log_line])
                self.assertEqual(self.evaluate(ev)["notes"], [third])
                self.assertEqual(ev.meta()["browser_error"], "cannot launch")  # 系统 / 底层异常原文原样带上

    def test_closed_evaluator(self):
        for lang, want in (("zh", "评测已结束"), ("en", "The evaluation has ended")):
            with self.subTest(lang=lang), mock.patch.object(geneval.cdp, "find_browser", return_value="fake"), i18n.use_lang(lang):
                ev = geneval.Evaluator(None, browsers=1)
                ev.close()
                with self.assertRaises(RuntimeError) as cm:
                    ev._acquire()
                self.assertEqual(str(cm.exception), want)
                self.assertTrue(self.evaluate(ev)["notes"][0].endswith(want))    # 关掉以后再评测: 降级成源码检查, 原因写进 notes

    def test_browser_crash_and_review_progress_log(self):
        def crash(*a):
            raise RuntimeError("browser crashed")

        def probed(browser, html_path, task_id, shots_dir):
            report = geneval.static_checks(HTML, TASK, "n")
            report["method"] = "browser"
            report["shots"] = [{"name": "01", "file": "01.jpg", "caption": "cap"}]
            return report
        for lang, crash_note, review_line in (
                ("zh", "后台浏览器出错，作品没有实际运行，只检查了源代码：browser crashed", "    评审中: Snake"),
                ("en", "Headless browser error; the generated page was not actually run, only its source code was checked: browser crashed",
                 "    Reviewing: Snake")):
            lines = []
            cfg = {"base": "http://127.0.0.1:9", "model": "judge-m"}
            with self.subTest(lang=lang), mock.patch.object(geneval.cdp, "find_browser", return_value="fake"), \
                    mock.patch.object(geneval.cdp, "Browser", FakeChrome), i18n.use_lang(lang):
                with mock.patch.object(geneval, "probe_work", crash):
                    report = self.evaluate(geneval.Evaluator(None, browsers=1, log=lines.append))
                self.assertEqual(report["notes"], [crash_note])
                with mock.patch.object(geneval, "probe_work", probed), \
                        mock.patch.object(geneval, "judge_work", lambda *a, **k: {"model": "judge-m", "score": 50.0}):
                    report = self.evaluate(geneval.Evaluator(cfg, browsers=1, log=lines.append))
                self.assertEqual(report["judge"]["score"], 50.0)
                self.assertEqual(lines, [review_line])

    def test_worker_threads_use_the_language_of_the_task(self):
        """gen 里的评测在 i18n.executor 的工作线程里跑: 线程里生成的说明沿用任务的语言。"""
        with mock.patch.object(geneval.cdp, "find_browser", return_value=None), english_flow() as flow:
            ev = geneval.Evaluator(None, browsers=1)
            with i18n.executor(2) as ex:
                report = ex.submit(ev.evaluate, TASK, self.html_path, HTML).result()
        flow.assert_clean(self, report, keys=STORED_TEXT_KEYS)
        self.assertTrue(report["notes"][0].startswith("Headless browser unavailable; "))
        self.assertEqual(zh_outside_labels(report), [])


class TestJudgeMessages(LangCase):
    """评审失败的说明存进评审结果的 error; 发给评审模型的重试提示是测试内容, 不随语言变。"""

    IDS = [c["id"] for c in gen_specs.get("snake")["checklist"] + gen_specs.GENERIC_CHECKLIST]

    def judge(self, reply, lang):
        calls = []

        def handler(method, path, body):
            calls.append(body)
            return 200, chat_reply(reply), None
        m = MockServer(handler)
        try:
            with i18n.use_lang(lang):
                report = geneval.static_checks(HTML, TASK, "note")
                result = geneval.judge_work({"base": m.url, "model": "judge-m", "api_key": ""}, TASK, HTML, report, temp_dir())
        finally:
            m.close()
        return result, calls

    def test_output_without_json(self):
        want = {"zh": "ValueError: 评审输出中没有包含 items 的 JSON",
                "en": "ValueError: The judge output contains no JSON object with an items list"}
        retry = "上面的输出无法解析（评审输出中没有包含 items 的 JSON）。请只输出符合要求格式的 JSON 对象，包含全部清单项。"
        for lang in ("zh", "en"):
            with self.subTest(lang=lang):
                result, calls = self.judge("no json here", lang)
                self.assertEqual(result, {"model": "judge-m", "error": want[lang]})
                self.assertEqual(len(calls), 2)                                # 解析失败时带上原输出重试一次
                self.assertEqual(calls[1]["messages"][-2], {"role": "assistant", "content": "no json here"})
                self.assertEqual(calls[1]["messages"][-1], {"role": "user", "content": retry})   # 英文界面下也是中文原文
        assert_english(self, self.judge("no json here", "en")[0])

    def test_output_missing_checklist_items(self):
        missing = self.IDS[1:]
        want = {"zh": "ValueError: 评审缺少清单项 " + "、".join(missing),
                "en": "ValueError: The judge output is missing checklist items: " + ", ".join(missing)}
        retry = "上面的输出无法解析（评审缺少清单项 %s）。请只输出符合要求格式的 JSON 对象，包含全部清单项。" % "、".join(missing)
        for lang in ("zh", "en"):
            with self.subTest(lang=lang):
                result, calls = self.judge(json.dumps({"items": [{"id": "t1", "score": 8}]}), lang)
                self.assertEqual(result["error"], want[lang])
                self.assertEqual(calls[1]["messages"][-1]["content"], retry)
        assert_english(self, self.judge(json.dumps({"items": [{"id": "t1", "score": 8}]}), "en")[0])

    def test_parse_errors_carry_the_chinese_original(self):
        checklist = [{"id": "t1", "label": "a"}, {"id": "t2", "label": "b"}, {"id": "visual", "label": "c"}]
        with i18n.use_lang("en"):
            with self.assertRaises(ValueError) as cm:
                geneval._parse_judge('{"items":[{"id":"t1","score":8}]}', checklist)
            self.assertEqual(str(cm.exception), "The judge output is missing checklist items: t2, visual")
            self.assertEqual(cm.exception.zh, "评审缺少清单项 t2、visual")
            with self.assertRaises(ValueError) as cm:
                geneval._find_judge_json("nothing here")
            self.assertEqual(cm.exception.zh, "评审输出中没有包含 items 的 JSON")
        with i18n.use_lang("zh"):
            with self.assertRaises(ValueError) as cm:
                geneval._parse_judge("nothing here", checklist)
            self.assertEqual((str(cm.exception), cm.exception.zh), ("评审输出中没有包含 items 的 JSON",) * 2)

    def test_a_good_reply_gives_the_same_result_in_every_language(self):
        reply = json.dumps({"items": [{"id": i, "score": 7, "reason": "ok"} for i in self.IDS], "summary": "fine"})
        zh, en = self.judge(reply, "zh")[0], self.judge(reply, "en")[0]
        self.assertEqual(zh, en)
        self.assertEqual((zh["score"], zh["summary"], zh["model"]), (70.0, "fine", "judge-m"))


class TestCommandLine(LangCase):
    def help(self, lang):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            geneval.main(["--lang", lang, "--help"])
        self.assertEqual(cm.exception.code, 0)
        return " ".join(out.getvalue().split())                     # 折行的空白统一掉

    def test_help_in_english_has_no_chinese(self):
        text = self.help("en")
        for want in ("Evaluate generated pages: runtime check + visual review", "--run RUN Code generation run ID",
                     "--tasks TASKS Only evaluate these questions, comma-separated", "--lang {zh,en}"):
            self.assertIn(want, text)
        assert_english(self, text, what="geneval --help")

    def test_help_in_chinese_is_unchanged(self):
        text = self.help("zh")
        for want in ("生成作品评测: 运行检测 + 视觉评审", "--run RUN gen 运行 ID", "--tasks TASKS 只评测这些题, 逗号分隔"):
            self.assertIn(want, text)


def sse_text(content, chunk=200):
    """OpenAI 流式返回 (本地模拟服务用): 正文切成小块。"""
    out = [b"data: " + json.dumps({"choices": [{"delta": {"content": content[i:i + chunk]}}]}).encode() + b"\n\n"
           for i in range(0, len(content), chunk)]
    out.append(b"data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]}).encode() + b"\n\n")
    out.append(b'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":20}}\n\ndata: [DONE]\n\n')
    return b"".join(out)


GOOD_PAGE = ("```html\n<!doctype html><html><head><title>t</title></head><body><canvas></canvas><script>"
             "requestAnimationFrame(()=>{});/*" + "x" * 300 + "*/</script></body></html>\n```")


class TestStoredInGenRuns(LangCase):
    """gen.run_gen 跑完后存进结果的评测说明 (评测在 i18n.executor 的工作线程里做, 没有浏览器时降级成源码检查)。
    只看 geneval 产生的字段; gen.py 自己的日志和说明由它自己的测试管。"""

    def run_gen(self, lang):
        m = MockServer(lambda method, path, body: (200, sse_text(GOOD_PAGE), "text/event-stream"))
        tmp = temp_dir()
        try:
            with mock.patch.object(gen, "ROOT", tmp), mock.patch.object(gen, "WORKS", os.path.join(tmp, "works")), \
                    mock.patch.object(geneval.cdp, "find_browser", return_value=None), \
                    i18n.use_lang(lang), contextlib.redirect_stdout(io.StringIO()):
                sink = sinks.JsonFileSink(os.path.join(tmp, "results"))
                gen.run_gen(m.url + "/v1/chat/completions", "m", task_ids=["matrix"], conc=1, sink=sink,
                            judge={"base": m.url, "model": "judge-m", "api_key": ""})
            return load_json(sink.path)
        finally:
            m.close()

    def test_eval_notes_follow_the_task_language(self):
        want = {
            "zh": ("本机没有找到 Chrome / Edge 浏览器",
                   "后台浏览器不可用，作品没有实际运行，只检查了源代码：本机没有找到 Chrome / Edge 浏览器",
                   "无截图（未进行浏览器运行检测），跳过视觉评审", "已去除注释后匹配"),
            "en": ("No Chrome / Edge browser found on this machine",
                   "Headless browser unavailable; the generated page was not actually run, only its source code was checked: "
                   "No Chrome / Edge browser found on this machine",
                   "No screenshots (no browser runtime check was performed); visual review skipped", "Matched after stripping comments")}
        for lang, (browser_error, note, judge_error, detail) in want.items():
            with self.subTest(lang=lang):
                doc = self.run_gen(lang)
                item = doc["items"][0]
                self.assertEqual(doc["status"], "done")
                self.assertEqual(doc["eval"]["browser_error"], browser_error)
                self.assertEqual(item["eval"]["notes"], [note])
                self.assertEqual(item["eval"]["judge"]["error"], judge_error)
                self.assertEqual([c["detail"] for c in item["eval"]["checks"]][3:], [detail, detail])
                self.assertEqual(item["features"][0], "HTML 文档结构")        # 检查项名称是测试内容: 两种语言一样
        doc = self.run_gen("en")
        self.assertEqual(zh_outside_labels({"eval": doc["eval"], "item_eval": doc["items"][0]["eval"]}), [])


if __name__ == "__main__":
    unittest.main()
