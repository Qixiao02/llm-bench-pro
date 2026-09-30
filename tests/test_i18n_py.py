# -*- coding: utf-8 -*-
"""服务端「中文 / 英文消息」框架的测试。约定见 CONTRIBUTING.md「服务端消息与翻译」。

分五块:
  1. 检查工具本身 (tests/i18n_lint_py.py): 用小段源码验证每条规则
  2. 棘轮: 违规数不能比基线多 (也不能比基线宽); 允许清单没有过期条目; 词典和调用处对得上
  3. i18n.py: t / tn / 语境 / 缺词回退 / 语言来源的优先级 / 线程和线程池里的语言 / 命令行选项
  4. 英文输出扫描 (第二阶段的验收手段): english_flow() + assert_english() 可以复用, 见下面的示例测试
  5. 试点模块 (endpoints / export_html / sinks / bench 的一部分 / server 的一部分) 在英文下没有汉字, 中文下和以前逐字一致
"""
import contextlib
import http.client
import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

from _util import MockServer, ROOT, temp_dir  # 先设 LLM_BENCH_LANG=zh, 再导入包内模块
import i18n
import i18n_lint_py as lint
import bankman
import bench
import endpoints
import export_html
import gen
import iq
import server
import sinks
import store
import tasksets


# ================================================================ 英文输出扫描 (可复用)

# 存进结果里的、给人看的说明类字段 (出现在结果 JSON 各处)
STORED_TEXT_KEYS = ("error", "err", "errors", "notes", "note", "warnings", "warning", "reason", "msg", "message",
                    "detail", "hint", "fixed_output_note")


def zh_found(obj, keys=None, _path="$", _inside=False):
    """递归找出对象里含汉字或中文标点的字符串, 返回 [(路径, 文字)]。
    keys 不为 None 时只看这些键下面的字符串 (存进结果里的说明类字段: STORED_TEXT_KEYS), 其他字段 (作品名、阶段名等
    数据名称) 不查; keys 为 None 时所有字符串都查 (接口返回的整个 error / 日志行)。"""
    out = []
    if isinstance(obj, str):
        if (keys is None or _inside) and lint.has_zh(obj):
            out.append((_path, obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(zh_found(v, keys, "%s.%s" % (_path, k), _inside or (keys is not None and k in keys)))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            out.extend(zh_found(v, keys, "%s[%d]" % (_path, i), _inside))
    return out


def assert_english(case, obj, keys=None, what=""):
    """断言 obj (日志行列表 / 接口返回 / 存进结果的文档) 里没有汉字和中文标点; 有的话列出路径和文字。"""
    bad = zh_found(obj, keys)
    case.assertEqual(bad, [], "%s英文输出里还有中文: %s" % (what + " " if what else "", "; ".join("%s = %r" % p for p in bad[:8])))


class Flow(object):
    def __init__(self):
        self.lines = []      # 三个引擎的 plog 通过进度回调交出来的日志行 (bench / iq / gen)
        self.stdout = ""     # 同一时间打印到标准输出的全部文字
        self.missing = []    # 这段流程里 t() / tn() 查不到英文的键 (回退成了中文)

    def assert_clean(self, case, obj=None, keys=None):
        """日志行和标准输出没有汉字, 也没有查不到英文的键; 给了 obj (存进结果的文档 / 接口返回) 时它也要干净。"""
        assert_english(case, self.lines, what="log lines")
        assert_english(case, self.stdout.splitlines(), what="stdout")
        case.assertEqual(self.missing, [], "英文词典缺这些键 (t() 回退成了中文)")
        if obj is not None:
            assert_english(case, obj, keys=keys, what="result")


@contextlib.contextmanager
def english_flow():
    """在英文模式下跑一段流程 (with 块里), 收集 plog 的全部输出: 进度回调和标准输出都收。
    线程里的日志 (i18n.spawn / i18n.executor 创建的) 也会收进来。用法:
        with english_flow() as flow:
            bench.calibrate_prompt(...)           # 或者任何会打日志 / 生成说明文字的流程
        flow.assert_clean(self, result_doc, keys=STORED_TEXT_KEYS)   # 日志和存进结果里的说明没有汉字, 词典没有缺键
    """
    flow, buf = Flow(), io.StringIO()
    saved = (bench._PROGRESS_CB, iq._IQ_PROGRESS, gen._GEN_PROGRESS)
    missing_before = set(i18n.MISSING)
    i18n.MISSING.clear()                  # 这段流程里新查不到的才算, 以前用例记下的不干扰
    bench._PROGRESS_CB = iq._IQ_PROGRESS = gen._GEN_PROGRESS = flow.lines.append
    try:
        with i18n.use_lang("en"), contextlib.redirect_stdout(buf):
            yield flow
    finally:
        bench._PROGRESS_CB, iq._IQ_PROGRESS, gen._GEN_PROGRESS = saved
        flow.stdout = buf.getvalue()
        flow.missing = sorted(i18n.MISSING)
        i18n.MISSING.update(missing_before)


@contextlib.contextmanager
def capture_plog():
    """只收 bench.plog 的日志行 (不改语言), 中文模式对比用。"""
    lines, saved = [], bench._PROGRESS_CB
    bench._PROGRESS_CB = lines.append
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            yield lines
    finally:
        bench._PROGRESS_CB = saved


@contextlib.contextmanager
def fake_dictionary(entries, lang="en"):
    """临时换掉英文词典 (测 t / tn 本身时不依赖真实词条)。"""
    i18n.dictionary(lang)
    saved = i18n._merged[lang]
    i18n._merged[lang] = dict(entries)
    try:
        yield
    finally:
        i18n._merged[lang] = saved


class LangCase(unittest.TestCase):
    """每个用例前后都把语言状态清干净 (语言存在线程的上下文里, 不清会串到后面的测试)。"""

    def setUp(self):
        i18n.set_lang(None)
        i18n.set_default_lang(None)
        i18n.MISSING.clear()
        self.addCleanup(i18n.set_lang, None)
        self.addCleanup(i18n.set_default_lang, None)


def tearDownModule():
    i18n.set_lang(None)
    i18n.set_default_lang(None)


# ================================================================ 1. 检查工具本身

def scan(src, name="x.py"):
    viol, calls = lint.scan_source(src, name)
    return [(v.rule, v.scope) for v in viol], calls


class TestLintRules(unittest.TestCase):
    """用小段源码验证 tests/i18n_lint_py.py 的每条规则: 该报的报, 不该报的不报。"""

    def rules(self, src, name="x.py"):
        return sorted(r for r, _ in scan(src, name)[0])

    def test_han_string_is_a_violation_but_docstring_and_comment_are_not(self):
        src = 'def f():\n    """文档里的中文"""\n    # 注释里的中文\n    return "提示"\n'
        self.assertEqual(scan(src)[0], [("han", "f")])
        self.assertEqual(self.rules('X = "abc"\n'), [])

    def test_t_key_and_ctx_are_allowed_everything_else_is_not(self):
        src = 'from i18n import t\ndef f(n):\n    return t("键 {n}", n=n, ctx="语境") + "另一句"\n'
        self.assertEqual(scan(src)[0], [("han", "f")])   # 只有「另一句」

    def test_fstring_static_part_is_a_violation_once(self):
        self.assertEqual(scan('def f(x):\n    return f"共 {x} 个，{x} 行"\n')[0], [("han", "f")])
        self.assertEqual(scan('def f(x):\n    return f"{x}"\n')[0], [])
        self.assertEqual(scan("def f(x):\n    return f\"{'中文' if x else 'a'}\"\n")[0], [("han", "f")])  # 表达式里的字符串也查

    def test_cjk_punctuation_without_han_is_a_violation(self):
        self.assertEqual(scan('def f():\n    return "；".join([])\n')[0], [("punct", "f")])
        self.assertEqual(scan('def f():\n    return "…" + "—" + "·"\n')[0], [])   # 英文排版也用的符号不算

    def test_scope_names(self):
        src = ('BIZ = ["中"]\nclass C:\n    K = "类里"\n    def m(self):\n        def inner():\n            return "内层"\n'
               '        return "方法"\n')
        got = dict((s, r) for r, s in scan(src)[0])
        self.assertEqual(sorted(got), ["BIZ", "C.K", "C.m", "C.m.inner"])

    def test_key_must_be_a_plain_string_constant_with_chinese(self):
        for bad in ('t(name)', 't("a" + "b")', 't(f"中 {x}")', 't("hello")', 't("中 %s", x)', 't("中 %d")'):
            with self.subTest(call=bad):
                self.assertIn("key", self.rules("from i18n import t\ndef f(name, x):\n    return %s\n" % bad))
        # 相邻字符串字面量合并成一个常量, 是合法的键
        self.assertEqual(self.rules('from i18n import t\ndef f():\n    return t("上半句"\n             "下半句")\n'), [])

    def test_args_star_and_arity(self):
        self.assertIn("args", self.rules('from i18n import t\ndef f(kw):\n    return t("中 {a}", **kw)\n'))
        self.assertIn("args", self.rules('from i18n import t\ndef f():\n    return t("中", "多余")\n'))
        self.assertIn("args", self.rules('from i18n import tn\ndef f():\n    return tn("中")\n'))
        self.assertEqual(self.rules('from i18n import tn\ndef f(n):\n    return tn("{n} 行", n)\n'), [])

    def test_format_string_must_be_valid(self):
        for bad in ('"中 {}"', '"中 {0}"', '"中 }"', '"中 {a.b}"', '"中 {ctx}"'):
            with self.subTest(key=bad):
                self.assertIn("format", self.rules("from i18n import t\ndef f():\n    return t(%s)\n" % bad))
        self.assertEqual(self.rules('from i18n import t\ndef f():\n    return t("JSON 是 {{}} 和 {{\\"a\\": 1}}")\n'), [])

    def test_t_at_module_or_class_level_is_flagged(self):
        self.assertIn("module", self.rules('from i18n import t\nX = t("中")\n'))
        self.assertIn("module", self.rules('from i18n import t\nclass C:\n    X = t("中")\n'))
        self.assertIn("module", self.rules('from i18n import t\ndef f(x=t("中")):\n    return x\n'))   # 默认值在 def 时就求值
        self.assertEqual(self.rules('from i18n import t\nF = lambda: t("中")\ndef g():\n    return t("中")\n'), [])

    def test_threads_must_use_the_i18n_helpers(self):
        self.assertEqual(self.rules("import threading\nthreading.Thread(target=f)\n"), ["thread"])
        self.assertEqual(self.rules("from concurrent.futures import ThreadPoolExecutor\nwith ThreadPoolExecutor(2) as ex:\n    pass\n"), ["thread"])
        self.assertEqual(self.rules("import concurrent.futures as cf\nwith cf.ThreadPoolExecutor(2) as ex:\n    pass\n"), ["thread"])
        self.assertEqual(self.rules("import threading\nthreading.Thread(target=f)\n", name="i18n.py"), [])   # 封装它们的地方除外
        self.assertEqual(self.rules("import i18n\ni18n.spawn(f)\nwith i18n.executor(2) as ex:\n    pass\n"), [])

    def test_shadowing_t_in_a_function_that_calls_t(self):
        self.assertIn("shadow", self.rules('from i18n import t\ndef f():\n    t = 1\n    return t("中")\n'))
        self.assertIn("shadow", self.rules('from i18n import t\ndef f(t):\n    return t("中")\n'))
        self.assertIn("shadow", self.rules('from i18n import t\ndef f(xs):\n    for t in xs:\n        pass\n    return t("中")\n'))
        self.assertEqual(self.rules('from i18n import t\ndef f():\n    t = 1\n    return t\n'), [])   # 没调用 t(): 没有问题
        self.assertEqual(self.rules('from i18n import t\ndef f(xs):\n    return [t.strip() for t in xs], t("中")\n'), [])  # 推导式自己的作用域

    def test_import_is_required(self):
        self.assertIn("import", self.rules('def f():\n    return t("中")\n'))
        self.assertEqual(self.rules('try:\n    from . import i18n\nexcept ImportError:\n    import i18n\nt = i18n.t\n'
                                    'def f():\n    return t("中")\n'), [])
        self.assertIn("import", self.rules('def f():\n    return i18n.t("中")\n'))
        self.assertEqual(self.rules('import i18n\ndef f():\n    return i18n.t("中")\n'), [])

    def test_call_records(self):
        _, calls = scan('from i18n import t, tn\ndef f(n):\n    t("甲 {a}", a=1, ctx="乙")\n    tn("{n} 行", n)\n')
        self.assertEqual([(c.fn, c.key, c.raw, c.ctx, c.kwargs) for c in calls],
                         [("t", "乙|甲 {a}", "甲 {a}", "乙", ("a",)), ("tn", "{n} 行", "{n} 行", None, ())])

    def test_allowlist_scope_and_fragment(self):
        entries = lint.load_allow(self._allow_file("f.py:PROMPTS\nf.py:Cls.run\nf.py:work:提示\nf.py:<module>\n"))
        src = ('PROMPTS = ["甲"]\nclass Cls:\n    def run(self):\n        return "乙"\n'
               'def work():\n    def inner():\n        return "提示词"\n    return "输出", inner\nprint("丙")\n')
        viol, _ = lint.scan_source(src, "f.py")
        bad, allowed, stale = lint.apply_allow({"f.py": (viol, [])}, entries)
        self.assertEqual([v.text for v in bad["f.py"]], ["输出"])                  # 只有函数里不含「提示」的这一条
        self.assertEqual(sorted(v.text for v in allowed["f.py"]), ["丙", "乙", "提示词", "甲"])
        self.assertEqual(stale, [])
        # 过期条目 (匹配不到任何字符串) 会被列出来
        bad, allowed, stale = lint.apply_allow({"f.py": (viol, [])}, lint.load_allow(self._allow_file("f.py:NOPE\n")))
        self.assertEqual([e.scope for e in stale], ["NOPE"])

    def _allow_file(self, text):
        path = os.path.join(temp_dir(), "allow.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_allowlist_format_errors(self):
        with self.assertRaises(ValueError):
            lint.load_allow(self._allow_file("只有文件名\n"))

    def test_dictionary_checks_catch_the_usual_mistakes(self):
        scan_ = {"m.py": lint.scan_source('from i18n import t, tn\ndef f(n):\n    t("甲 {a}", a=1)\n    tn("{n} 行", n)\n'
                                          '    t("丙 {c}", c=2)\n', "m.py")}

        def kinds(entries):
            return sorted(p.kind for p in lint.check_dictionary(scan_, {"m": entries, "common": {}}))
        ok = {"甲 {a}": "A {a}", "{n} 行": ("{n} line", "{n} lines"), "丙 {c}": "C {c}"}
        self.assertEqual(kinds(ok), [])
        self.assertEqual(kinds(dict(ok, **{"甲 {a}": "A {b}"})), ["kwargs", "placeholder"])   # 英文用了别的名字, 调用处也没传
        self.assertEqual(kinds(dict(ok, **{"甲 {a}": "甲 {a}"})), ["han"])
        self.assertEqual(kinds(dict(ok, **{"{n} 行": "{n} lines"})), ["type"])              # tn 的英文必须是二元组
        self.assertEqual(kinds(dict(ok, **{"甲 {a}": ("A {a}", "B {a}")})), ["type"])       # t 的英文必须是字符串
        self.assertEqual(kinds(dict(ok, **{"丙 {c}": "C {c} {d}"})), ["kwargs", "placeholder"])
        gone = dict(ok)
        del gone["甲 {a}"]
        self.assertEqual(kinds(gone), ["missing"])
        self.assertEqual(kinds(dict(ok, 没用到="unused")), ["unused"])
        self.assertEqual(kinds(dict(ok, **{"{n} 行": ("{n} line", "{k} lines")})), ["kwargs", "placeholder"])


# ================================================================ 2. 棘轮和词典

def _lint_state():
    scan_ = lint.scan_all()
    bad, allowed, stale = lint.apply_allow(scan_, lint.load_allow())
    return scan_, bad, allowed, stale, lint.load_baseline()


class TestRatchet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scan, cls.bad, cls.allowed, cls.stale, cls.base = _lint_state()
        cls.cur = lint.counts(cls.bad)

    def test_no_file_has_more_violations_than_its_baseline(self):
        more = ["%s: %d 处, 基线 %d 处" % (fn, n, self.base.get(fn, 0)) for fn, n in self.cur.items() if n > self.base.get(fn, 0)]
        self.assertEqual(more, [], "有对外文字没走 t() / tn() (python tests/i18n_lint_py.py --report -f 文件名 看明细): " + "; ".join(more))

    def test_baseline_is_not_looser_than_reality(self):
        problems = [msg for fn, msg in lint.ratchet_problems(self.cur, self.base) if "多了" not in msg]
        self.assertEqual(problems, [], "基线要跟着降下来: python tests/i18n_lint_py.py --update-baseline")

    def test_every_file_is_in_the_baseline(self):
        self.assertEqual(sorted(set(self.cur) - set(self.base)), [])

    def test_code_hygiene_rules_are_zero_everywhere(self):
        """这几条不靠基线放宽: t() 的写法、模块级调用、线程、变量名遮住 t、没导入。"""
        hard = [v for vs in self.bad.values() for v in vs if v.rule not in ("han", "punct")]
        self.assertEqual(["%s:%d [%s] %s" % (v.file, v.line, v.rule, v.text) for v in hard], [])

    def test_allowlist_has_no_stale_entries(self):
        self.assertEqual(["第 %d 行: %s" % (e.line, e.raw) for e in self.stale], [])

    def test_pilot_files_are_fully_converted(self):
        for fn in ("__init__.py", "endpoints.py", "export_html.py", "sinks.py", "i18n.py"):
            with self.subTest(file=fn):
                self.assertEqual(self.cur[fn], 0)
                self.assertEqual(self.base[fn], 0)

    def test_all_thread_creation_goes_through_i18n(self):
        """线程和线程池共 15 处 (server 1 / bench 8 / gen 2 / iq 1 / bankman 1 / cdp 1 / sinks 1) 都已改成 i18n.spawn / i18n.executor。"""
        self.assertEqual([v for vs in self.bad.values() for v in vs if v.rule == "thread"], [])
        by_file = {}
        for fn in self.scan:
            with open(os.path.join(lint.PKG, fn), encoding="utf-8") as f:
                text = f.read()
            n = text.count("i18n.spawn(") + text.count("i18n.executor(")
            if fn != "i18n.py" and n:
                by_file[fn] = n
        for fn, want in {"bankman.py": 1, "bench.py": 8, "cdp.py": 1, "gen.py": 2, "iq.py": 1, "server.py": 1, "sinks.py": 1}.items():
            self.assertGreaterEqual(by_file.get(fn, 0), want, fn)      # 之后可以再加, 不能少


class TestDictionary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scan = lint.scan_all()
        cls.dicts, cls.load_problems = lint.load_dicts()
        cls.problems = cls.load_problems + lint.check_dictionary(cls.scan, cls.dicts)

    def only(self, *kinds):
        return ["%s: %s" % (p.where, p.text) for p in self.problems if p.kind in kinds]

    def test_dictionary_files_exist_for_every_module(self):
        want = {"bench", "server", "gen", "geneval", "iq", "store", "bankman", "report", "tasksets", "endpoints",
                "vision_assets", "cdp", "gen_specs", "sinks", "common", "export_html"}
        self.assertEqual(sorted(want - set(self.dicts)), [])

    def test_dictionary_files_load_and_are_plain_literals(self):
        self.assertEqual(self.only("load"), [])
        self.assertEqual(self.only("format"), [])

    def test_every_key_used_in_code_has_an_english_entry(self):
        self.assertEqual(self.only("missing"), [], "python tests/i18n_lint_py.py --missing 也能列出来")

    def test_placeholders_match_and_call_sites_pass_every_argument(self):
        self.assertEqual(self.only("placeholder", "kwargs"), [])

    def test_english_has_no_chinese(self):
        self.assertEqual(self.only("han"), [])

    def test_plural_entries_are_pairs_and_plain_entries_are_strings(self):
        self.assertEqual(self.only("type"), [])

    def test_no_unused_duplicate_or_misplaced_entries(self):
        self.assertEqual(self.only("unused", "stale", "dup", "conflict"), [])

    def test_runtime_dictionary_matches_the_files(self):
        """i18n.py 实际加载的词典 (import) 和检查工具读到的 (不执行) 一样, 词典文件都能正常加载。"""
        i18n.reload_dictionaries()
        by_module = i18n.entries_by_module("en")
        self.assertEqual(i18n.LOAD_ERRORS, [])
        self.assertEqual({k: v for k, v in by_module.items()}, {k: v for k, v in self.dicts.items()})
        merged = i18n.dictionary("en")
        self.assertEqual(len(merged), sum(len(v) for v in self.dicts.values()))   # 没有重复的键被覆盖


# ================================================================ 3. i18n.py

class TestTranslate(LangCase):
    def test_tests_run_in_chinese_regardless_of_the_machine_language(self):
        """tests/_util.py 在导入包之前设了 LLM_BENCH_LANG=zh: 现有测试里断言的中文提示不受系统语言影响。"""
        self.assertEqual(os.environ.get("LLM_BENCH_LANG"), "zh")
        self.assertEqual(i18n.current_lang(), "zh")

    def test_zh_returns_the_original_with_placeholders_filled(self):
        with i18n.use_lang("zh"):
            self.assertEqual(i18n.t("共 {n} 行，{name}", n=3, name="甲"), "共 3 行，甲")
            self.assertEqual(i18n.t("没有占位符"), "没有占位符")
            self.assertEqual(i18n.t("{x:.1f}% 和 {y:>4}", x=12.345, y="a"), "12.3% 和    a")
            self.assertEqual(i18n.t("JSON 是 {{\"a\": {v}}}", v=1), "JSON 是 {\"a\": 1}")   # {{ }} 是字面花括号
            self.assertEqual(i18n.tn("{n} 行", 1), "1 行")
            self.assertEqual(i18n.tn("{n} 行", 5), "5 行")
        self.assertEqual(i18n.MISSING, set())   # 中文模式不查词典, 不记缺词

    def test_en_lookup_ctx_and_fallback(self):
        entries = {"你好 {name}": "Hello {name}", "对比|更好": "better", "更好": "nicer", "带数量 {n}": ("{n} item", "{n} items")}
        with fake_dictionary(entries), i18n.use_lang("en"):
            self.assertEqual(i18n.t("你好 {name}", name="A"), "Hello A")
            self.assertEqual(i18n.t("更好", ctx="对比"), "better")      # 词典键 "对比|更好"
            self.assertEqual(i18n.t("更好"), "nicer")
            self.assertEqual(i18n.t("没有词条 {a}", a=1), "没有词条 1")    # 查不到: 回退中文 (仍替换占位符)
            self.assertEqual(i18n.t("没有词条 {a}", a=2), "没有词条 2")
            self.assertEqual(i18n.t("再来", ctx="某处"), "再来")
        self.assertEqual(i18n.MISSING, {"没有词条 {a}", "某处|再来"})      # 集合: 同一个键只记一次, 带语境的键带前缀

    def test_plural(self):
        with fake_dictionary({"{n} 行": ("{n} line", "{n} lines"), "只有一种 {n}": "only {n}"}), i18n.use_lang("en"):
            self.assertEqual([i18n.tn("{n} 行", k) for k in (0, 1, 2, 1.0)], ["0 lines", "1 line", "2 lines", "1.0 line"])   # n == 1 用单数, 值原样显示
            self.assertEqual(i18n.tn("只有一种 {n}", 1), "only 1")      # 词条是字符串时单复数一样
            self.assertEqual(i18n.tn("{n} 行", 3, n="3,000"), "3,000 lines")   # 调用处给的 n 优先 (千分位等)
            self.assertEqual(i18n.tn("共 {n} 行 ({k})", 2, k="x"), "共 2 行 (x)")   # 没词条: 回退中文
        self.assertEqual(i18n.MISSING, {"共 {n} 行 ({k})"})

    def test_missing_arguments_and_bad_templates_never_raise(self):
        with fake_dictionary({}), i18n.use_lang("zh"):
            self.assertEqual(i18n.t("缺 {a} 和 {b:.1f}", a=1), "缺 1 和 {b:.1f}")   # 缺的参数原样留着占位符
            self.assertEqual(i18n.t("坏格式 {"), "坏格式 {")
            self.assertEqual(i18n.t("单个 } 号"), "单个 } 号")
            self.assertIn("位置", i18n.t("位置 {} {0}"))                          # 位置占位符: 不抛异常就行
            self.assertEqual(i18n.t("位置 {}"), "位置 {0}")
            self.assertEqual(i18n.t("{n:d} 项", n="3"), "3 项")                    # 格式说明不适用: 退回 str()
            self.assertEqual(i18n.t("{a.b}", a=1), "{a.b}")
            self.assertEqual(i18n.t(12345), "12345")                              # 键不是字符串也不抛
            self.assertEqual(i18n.t("值里有 {x}", x="{y}"), "值里有 {y}")           # 值里的花括号不会被再当成占位符
            e = ValueError("boom")
            self.assertEqual(i18n.t("异常 {e}", e=e), "异常 boom")

    def test_a_broken_dictionary_file_does_not_break_the_others(self):
        real = i18n.importlib.import_module

        def fake(name, *a):
            if name.endswith(".endpoints"):
                raise SyntaxError("boom")
            return real(name, *a)
        try:
            with mock.patch.object(i18n.importlib, "import_module", fake):
                i18n.reload_dictionaries()
                d = i18n.dictionary("en")
                errors = list(i18n.LOAD_ERRORS)
        finally:
            i18n.reload_dictionaries()
        self.assertEqual([e.split(":")[0] for e in errors], ["endpoints"])
        self.assertNotIn("服务地址不能为空", d)                # 坏的那个文件里的词条当作没有 (回退成中文)
        self.assertIn("用户取消", d)                          # 其他文件照常
        self.assertEqual(i18n.LOAD_ERRORS, [])                # 重新加载后恢复正常

    def test_use_lang_rejects_unknown_languages(self):
        with self.assertRaises(ValueError):
            with i18n.use_lang("fr"):
                pass
        self.assertEqual(i18n.current_lang(), "zh")

    def test_english_dictionary_is_lazy(self):
        """中文模式不加载词典 (不拖慢启动); 第一次需要英文时才加载。"""
        code = ("import sys, os\nos.environ['LLM_BENCH_LANG']='zh'\nsys.path.insert(0, %r)\nimport i18n\n"
                "i18n.t('中文 {a}', a=1)\nprint(bool(i18n._merged))\ni18n.set_lang('en')\ni18n.t('中文 {a}', a=1)\nprint(bool(i18n._merged))\n"
                % lint.PKG)
        r = subprocess.run([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT, timeout=60)
        self.assertEqual(r.stdout.decode().split(), ["False", "True"], r.stderr.decode("utf-8", "replace"))


class TestLanguageResolution(LangCase):
    """语言来源的优先级: set_lang > 命令行 (进程语言) > LLM_BENCH_LANG > 系统区域 > 默认。"""

    def env(self, **kw):
        keep = {k: v for k, v in os.environ.items() if k not in ("LLM_BENCH_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")}
        keep.update(kw)
        return mock.patch.dict(os.environ, keep, clear=True)

    def setUp(self):
        LangCase.setUp(self)
        self.win = mock.patch.object(i18n, "_windows_ui_lang", return_value=None)   # 不受这台机器的 Windows 界面语言影响
        self.win.start()
        self.addCleanup(self.win.stop)

    def test_normalize(self):
        for raw, want in (("zh", "zh"), ("ZH-cn", "zh"), ("zh_TW.UTF-8", "zh"), ("en", "en"), ("en-US", "en"), (" en_GB ", "en"),
                          ("fr", None), ("", None), (None, None), ("chinese", None), (5, None)):
            self.assertEqual(i18n.normalize_lang(raw), want, raw)

    def test_explicit_beats_everything(self):
        with self.env(LLM_BENCH_LANG="zh", LANG="zh_CN.UTF-8"):
            i18n.set_default_lang("zh")
            i18n.set_lang("en")
            self.assertEqual(i18n.current_lang(), "en")
            i18n.set_lang(None)                      # 取消后回到下一层
            self.assertEqual(i18n.current_lang(), "zh")
            with self.assertRaises(ValueError):
                i18n.set_lang("fr")
            with self.assertRaises(ValueError):
                i18n.set_default_lang("fr")

    def test_process_language_beats_environment(self):
        with self.env(LLM_BENCH_LANG="zh"):
            i18n.set_default_lang("en")
            self.assertEqual(i18n.current_lang(), "en")

    def test_env_beats_system_locale(self):
        with self.env(LLM_BENCH_LANG="en", LANG="zh_CN.UTF-8"):
            self.assertEqual(i18n.current_lang(), "en")
        with self.env(LLM_BENCH_LANG="zh", LANG="en_US.UTF-8"):
            self.assertEqual(i18n.current_lang(), "zh")
        with self.env(LLM_BENCH_LANG="fr", LANG="en_US.UTF-8"):     # 不认识的值当作没设
            self.assertEqual(i18n.current_lang(), "en")
        with self.env(LLM_BENCH_LANG="fr", LANG="zh_CN.UTF-8"):
            self.assertEqual(i18n.current_lang(), "zh")

    def test_system_locale(self):
        for env, want in (({"LANG": "zh_CN.UTF-8"}, "zh"), ({"LANG": "zh_TW"}, "zh"), ({"LANG": "en_US.UTF-8"}, "en"),
                          ({"LANG": "de_DE"}, "en"),
                          # C / POSIX / C.UTF-8 不算选了语言(Docker 和服务器上很常见): 当作没设, 用默认(中文, 和升级前一样)
                          ({"LANG": "C"}, "zh"), ({"LANG": "C.UTF-8"}, "zh"), ({"LANG": "POSIX"}, "zh"), ({"LC_ALL": "C", "LANG": "C.utf8"}, "zh"),
                          ({"LC_ALL": "C", "LANG": "en_US.UTF-8"}, "en"),               # LC_ALL=C 没有信息, 继续看后面的
                          ({"LC_ALL": "C", "LANG": "zh_CN.UTF-8"}, "zh"),
                          ({"LC_ALL": "en_US.UTF-8", "LANG": "zh_CN.UTF-8"}, "en"),    # LC_ALL 最高
                          ({"LC_MESSAGES": "zh_CN.UTF-8", "LANG": "en_US.UTF-8"}, "zh"),
                          ({"LANGUAGE": "zh_CN:en", "LANG": "en_US.UTF-8"}, "zh"),      # LANGUAGE 是列表, 取第一个
                          ({"LANGUAGE": "en:zh_CN", "LC_ALL": "zh_CN.UTF-8"}, "en")):
            with self.subTest(env=env), self.env(**env):
                self.assertEqual(i18n.current_lang(), want)

    def test_windows_ui_language_and_default(self):
        with self.env():                                            # 没有任何区域环境变量
            self.win.stop()
            try:
                for ui, want in (("zh", "zh"), ("en", "en"), (None, i18n.DEFAULT_LANG)):
                    with mock.patch.object(i18n, "_windows_ui_lang", return_value=ui):
                        self.assertEqual(i18n.current_lang(), want, ui)
            finally:
                self.win.start()
        self.assertEqual(i18n.DEFAULT_LANG, "zh")                   # 什么都读不到时用代码里原文的语言
        with self.env(LANG="en_US.UTF-8"):                          # 有环境变量时不看 Windows
            with mock.patch.object(i18n, "_windows_ui_lang", return_value="zh"):
                self.assertEqual(i18n.current_lang(), "en")

    def test_use_lang_restores(self):
        with self.env(LLM_BENCH_LANG="zh"):
            with i18n.use_lang("en"):
                self.assertEqual(i18n.current_lang(), "en")
                with i18n.use_lang("zh"):
                    self.assertEqual(i18n.current_lang(), "zh")
                self.assertEqual(i18n.current_lang(), "en")
            self.assertEqual(i18n.current_lang(), "zh")
            with i18n.use_lang(None):                               # None: 不单独指定
                self.assertEqual(i18n.current_lang(), "zh")

    def test_html_lang(self):
        with i18n.use_lang("en"):
            self.assertEqual(i18n.html_lang(), "en")
        with i18n.use_lang("zh"):
            self.assertEqual(i18n.html_lang(), "zh-CN")

    def test_language_from_request_headers(self):
        class H(dict):
            def get(self, k, d=None):
                return dict.get(self, k, d)
        cases = [({"X-Lang": "en"}, "en"), ({"X-Lang": "zh"}, "zh"), ({"X-Lang": "zh-CN"}, "zh"), ({}, None),
                 ({"X-Lang": "fr"}, None),
                 ({"X-Lang": "en", "Accept-Language": "zh-CN,zh;q=0.9"}, "en"),                 # X-Lang 优先
                 ({"X-Lang": "fr", "Accept-Language": "en-US"}, "en"),                          # 不认识时看 Accept-Language
                 ({"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}, "zh"),
                 ({"Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8"}, "en"),
                 ({"Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5,zh;q=0.6"}, "zh"),                # 按 q 值排, 取第一个认识的
                 ({"Accept-Language": "zh;q=0.3, en;q=0.9"}, "en"),
                 ({"Accept-Language": "fr, de;q=0.5"}, None), ({"Accept-Language": "*"}, None),
                 ({"Accept-Language": "en;q=0"}, None), ({"Accept-Language": "en;q=abc, zh"}, "zh"), ({"Accept-Language": ""}, None)]
        for headers, want in cases:
            with self.subTest(headers=headers):
                self.assertEqual(i18n.lang_from_headers(H(headers)), want)
        self.assertIsNone(i18n.lang_from_headers(None))


class TestThreads(LangCase):
    """线程和线程池里沿用创建 / 提交时的语言, 之后原线程改语言不影响它们。"""

    def test_spawn_carries_the_language_as_a_snapshot(self):
        seen, go, done = [], threading.Event(), threading.Event()

        def child():
            go.wait(5)                     # 等原线程改完语言再读
            seen.append(i18n.current_lang())
            done.set()
        i18n.set_lang("en")
        th = i18n.spawn(child, name="probe")
        i18n.set_lang("zh")                # 创建之后再改: 线程里应该还是创建时的语言
        go.set()
        self.assertTrue(done.wait(5))
        self.assertEqual(seen, ["en"])
        self.assertTrue(th.daemon)
        self.assertEqual(th.name, "probe")

    def test_spawn_passes_arguments_and_can_be_started_later(self):
        out = []
        th = i18n.spawn(lambda a, b=0: out.append((a, b, i18n.current_lang())), args=(1,), kwargs={"b": 2}, start=False)
        self.assertFalse(th.is_alive())
        with i18n.use_lang("en"):
            pass
        th.start()
        th.join(5)
        self.assertEqual(out[0][:2], (1, 2))

    def test_executor_workers_use_the_language_of_the_submitter(self):
        got = {}
        release = threading.Event()

        def work(tag):
            release.wait(5)
            return (tag, i18n.current_lang())

        with i18n.executor(max_workers=2) as ex:
            with i18n.use_lang("en"):
                f_en = [ex.submit(work, "a"), ex.submit(work, "b")]
            with i18n.use_lang("zh"):
                f_zh = ex.submit(work, "c")   # 同一个池、被复用的工作线程: 也要是提交者的语言
            i18n.set_lang("zh")
            release.set()
            got["en"] = [f.result(5) for f in f_en]
            got["zh"] = f_zh.result(5)
            with i18n.use_lang("en"):
                got["map"] = list(ex.map(work, ["x", "y", "z"]))   # map 也一样
        self.assertEqual(got["en"], [("a", "en"), ("b", "en")])
        self.assertEqual(got["zh"], ("c", "zh"))
        self.assertEqual(got["map"], [("x", "en"), ("y", "en"), ("z", "en")])

    def test_executor_propagates_exceptions_like_the_standard_one(self):
        with i18n.executor(1) as ex:
            f = ex.submit(lambda: 1 / 0)
            self.assertRaises(ZeroDivisionError, f.result, 5)
        self.assertIsInstance(i18n.executor(1), i18n.ThreadPoolExecutor)

    @unittest.skipIf(getattr(sys.flags, "thread_inherit_context", 0), "这个 Python 让线程自动继承上下文")
    def test_plain_threads_would_lose_the_language(self):
        """这就是为什么不能直接用 threading.Thread / ThreadPoolExecutor (检查工具的 thread 规则也会拦)。"""
        seen = []
        i18n.set_default_lang(None)
        with mock.patch.dict(os.environ, {"LLM_BENCH_LANG": "zh"}), i18n.use_lang("en"):
            th = threading.Thread(target=lambda: seen.append(i18n.current_lang()))
            th.start()
            th.join(5)
        self.assertEqual(seen, ["zh"])

    def test_language_of_a_thread_does_not_leak_into_the_starter(self):
        def child():
            i18n.set_lang("en")
        with i18n.use_lang("zh"):
            i18n.spawn(child).join(5)
            self.assertEqual(i18n.current_lang(), "zh")


class TestCommandLine(LangCase):
    def test_preparse_forms(self):
        for argv, want in ((["--lang", "en"], "en"), (["--lang=en"], "en"), (["x", "--lang", "zh", "y"], "zh"),
                           (["--lang", "en", "--lang", "zh"], "zh"), (["--lang", "fr"], None), (["--lang"], None),
                           (["--", "--lang", "en"], None), ([], None), (["--language", "en"], None)):
            with self.subTest(argv=argv):
                i18n.set_default_lang(None)
                before = list(argv)
                self.assertEqual(i18n.preparse_lang(argv), want)
                self.assertEqual(argv, before)                            # 不改动 argv
                self.assertEqual(i18n._process_lang, want)

    def test_preparse_reads_sys_argv_by_default(self):
        with mock.patch.object(sys, "argv", ["prog", "--lang", "en"]):
            self.assertEqual(i18n.preparse_lang(), "en")
        self.assertEqual(i18n.current_lang(), "en")

    def test_add_lang_arg(self):
        import argparse
        ap = argparse.ArgumentParser()
        i18n.add_lang_arg(ap)
        self.assertIsNone(ap.parse_args([]).lang)
        self.assertEqual(ap.parse_args(["--lang", "en"]).lang, "en")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            ap.parse_args(["--lang", "fr"])
        # 子命令解析器: 不覆盖主解析器已经解析到的值
        top = argparse.ArgumentParser()
        i18n.add_lang_arg(top)
        sub = top.add_subparsers(dest="cmd").add_parser("run")
        i18n.add_lang_arg(sub, sub=True)
        self.assertEqual(top.parse_args(["--lang", "en", "run"]).lang, "en")
        self.assertEqual(top.parse_args(["run", "--lang", "zh"]).lang, "zh")
        self.assertIsNone(top.parse_args(["run"]).lang)

    def _help(self, parse, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            parse(argv)
        self.assertEqual(cm.exception.code, 0)
        return out.getvalue()

    def test_server_help_in_english_has_no_chinese(self):
        text = self._help(server.parse_args, ["--lang", "en", "--help"])
        assert_english(self, text.splitlines(), what="--help")
        self.assertIn("Port to listen on", text)
        self.assertIn("--lang {zh,en}", text)
        self.assertIn("Language of the interface and logs", text)

    def test_server_help_in_chinese_is_unchanged(self):
        i18n.set_default_lang(None)
        text = self._help(server.parse_args, ["--lang", "zh", "--help"])
        for line in ("监听端口 (默认 18080)", "监听地址 (默认 127.0.0.1 仅本机; 局域网访问用 0.0.0.0, 建议同时设置 --token)",
                     "访问令牌; 设置后需用 http://主机:端口/?token=令牌 打开页面", "LLM Bench Pro 服务"):
            self.assertIn(line, text)
        self.assertIn("界面和日志的语言：zh 中文，en 英文（默认按环境变量 LLM_BENCH_LANG，再按系统语言）", text)

    def test_lang_option_overrides_the_environment_variable(self):
        with mock.patch.dict(os.environ, {"LLM_BENCH_LANG": "zh"}):
            text = self._help(server.parse_args, ["--lang", "en", "--help"])
        self.assertIn("Port to listen on", text)
        i18n.set_default_lang(None)
        with mock.patch.dict(os.environ, {"LLM_BENCH_LANG": "en"}):
            text = self._help(server.parse_args, ["--help"])         # 没有 --lang: 用环境变量
        self.assertIn("Port to listen on", text)

    def test_parse_args_keeps_working(self):
        a = server.parse_args(["18099", "--lang", "en", "--host", "0.0.0.0"])
        self.assertEqual((a.port, a.host, a.lang), (18099, "0.0.0.0", "en"))
        self.assertEqual(server.parse_args([]).lang, None)

    def _run_module(self, args, lang_env="zh"):
        env = dict(os.environ, PYTHONIOENCODING="utf-8", LLM_BENCH_LANG=lang_env)
        env.pop("PYTHONUTF8", None)
        r = subprocess.run([sys.executable] + args, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")

    def test_every_entry_point_accepts_lang_and_shows_it_in_help(self):
        """run.py / bench / geneval / store / bankman / cdp 都有 --lang; --lang 的说明按 --lang 指定的语言显示 (环境变量是 zh)。"""
        entries = [["run.py"], ["-m", "llm_bench_pro.bench"], ["-m", "llm_bench_pro.geneval"], ["-m", "llm_bench_pro.store"],
                   ["-m", "llm_bench_pro.bankman"], ["-m", "llm_bench_pro.cdp"], ["-m", "llm_bench_pro.server"]]
        for entry in entries:
            with self.subTest(entry=entry):
                code, out, err = self._run_module(entry + ["--lang", "en", "--help"])
                self.assertEqual(code, 0, err)
                self.assertIn("--lang {zh,en}", out)
                self.assertIn("Language of the interface and logs", out)
                code, out, err = self._run_module(entry + ["--lang", "zh", "--help"], lang_env="en")
                self.assertEqual(code, 0, err)
                self.assertIn("界面和日志的语言", out)
                code, out, err = self._run_module(entry + ["--lang=en", "--help"])   # 等号写法
                self.assertIn("Language of the interface and logs", out)

    def test_store_subcommand_accepts_lang_after_the_command(self):
        code, out, err = self._run_module(["-m", "llm_bench_pro.store", "check", "--lang", "en", "--help"])
        self.assertEqual(code, 0, err)
        self.assertIn("Language of the interface and logs", out)

    def test_server_help_via_run_py_has_no_chinese(self):
        code, out, err = self._run_module(["run.py", "--lang", "en", "--help"])
        self.assertEqual(code, 0, err)
        assert_english(self, out.splitlines(), what="python run.py --lang en --help")


# ================================================================ 5. 试点: 服务端接口 (请求头 X-Lang)

class LangServerCase(unittest.TestCase):
    token = ""

    @classmethod
    def setUpClass(cls):
        server.CONFIG.update(host="127.0.0.1", port=0, token=cls.token)
        cls.httpd = server.BenchServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        server.CONFIG["token"] = ""

    def request(self, method, path, body=None, lang=None, headers=None):
        hdrs = {"Content-Type": "application/json"}
        if lang:
            hdrs["X-Lang"] = lang
        hdrs.update(headers or {})
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        c.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=hdrs)
        r = c.getresponse()
        raw = r.read()
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = raw.decode("utf-8", "replace")
        return r.status, payload

    def error_of(self, method, path, body=None, lang=None, headers=None):
        st, d = self.request(method, path, body, lang, headers)
        return st, (d.get("error") if isinstance(d, dict) else d)


class TestApiErrorsFollowXLang(LangServerCase):
    def setUp(self):
        self._saved = server.SCN_TASKS_DIR
        server.SCN_TASKS_DIR = temp_dir()              # 任务集目录换成临时目录, 不碰 data/
        self.addCleanup(setattr, server, "SCN_TASKS_DIR", self._saved)

    def both(self, method, path, body, zh, en, status):
        """同一个请求: 英文 (X-Lang: en) 返回 en 且没有汉字; 中文 (X-Lang: zh 和不带请求头) 与以前逐字一致。"""
        st, msg = self.error_of(method, path, body, lang="en")
        self.assertEqual((st, msg), (status, en))
        assert_english(self, msg, what=path)
        self.assertEqual(self.error_of(method, path, body, lang="zh"), (status, zh))
        self.assertEqual(self.error_of(method, path, body), (status, zh))

    def test_probe(self):
        bad_url_zh = "服务地址要以 http:// 或 https:// 开头，中间不能有空格，比如 http://127.0.0.1:8000"
        bad_url_en = "The service URL must start with http:// or https:// and contain no spaces, e.g. http://127.0.0.1:8000"
        self.both("POST", "/api/probe", {"base": 5}, "base / api_key 应为文字", "base and api_key must be strings", 400)
        self.both("POST", "/api/probe", {"base": "ftp://x"}, bad_url_zh, bad_url_en, 400)
        self.both("POST", "/api/probe", {"base": "http://127.0.0.1:1", "api_key": "a\nb"},
                  "API Key 中间不能有换行或其他控制字符", "The API key cannot contain line breaks or other control characters", 400)

    def test_probe_failures_reported_by_the_service(self):
        """测试连接连上了、但服务返回的不是模型列表: 说明是英文 (服务原文和异常类名本来就是英文)。"""
        m = MockServer(lambda method, path, body: (200, {"nope": 1}, None))
        try:
            st, d = self.request("POST", "/api/probe", {"base": m.url}, lang="en")
            self.assertEqual((st, d["ok"], d["code"]), (200, False, "bad_json"))
            self.assertEqual(d["error"], "NotModelList: The response is not a model list (no data array)")
            assert_english(self, d)
            st, d = self.request("POST", "/api/probe", {"base": m.url}, lang="zh")
            self.assertEqual(d["error"], "NotModelList: 返回的不是模型列表（没有 data 数组）")
        finally:
            m.close()
        m = MockServer(lambda method, path, body: (401, {"error": "bad key"}, None))
        try:
            st, d = self.request("POST", "/api/probe", {"base": m.url, "api_key": "sk-abcdef1234"}, lang="en")
            self.assertEqual(d["code"], "auth")
            assert_english(self, d)
        finally:
            m.close()

    def test_task_set_pages(self):
        self.both("GET", "/api/task-set?id=zzz", None, "任务集 id 不对（应为 scn- 加 12 位十六进制数字）",
                  "Invalid task set id (expected scn- followed by 12 hex digits)", 400)
        self.both("GET", "/api/task-set?id=scn-000000000000", None, "任务集不存在（可能已被删除）",
                  "The task set does not exist (it may have been deleted)", 404)
        self.both("GET", "/api/task-set-line?id=scn-000000000000&line=1", None, "任务集不存在（可能已被删除）",
                  "The task set does not exist (it may have been deleted)", 404)
        self.both("POST", "/api/task-set-delete", {"id": "scn-000000000000"}, "任务集不存在（可能已被删除）",
                  "The task set does not exist (it may have been deleted)", 404)
        content = json.dumps({"messages": [{"role": "user", "content": "q"}]}) + "\n"
        st, up = self.request("POST", "/api/scenario-upload", {"kind": "tasks", "name": "a.jsonl", "content": content})
        self.assertEqual(st, 200, up)
        fid = up["file_id"]
        self.both("GET", "/api/task-set?id=%s&offset=x" % fid, None, "offset / limit 应为整数", "offset and limit must be integers", 400)
        self.both("GET", "/api/task-set?id=%s&limit=99999" % fid, None,
                  "offset 不能小于 0，limit 应为 1–%d" % tasksets.PAGE_MAX,
                  "offset must be at least 0 and limit must be between 1 and %d" % tasksets.PAGE_MAX, 400)
        self.both("GET", "/api/task-set?id=%s&status=zzz" % fid, None,
                  "status 应为 %s 之一" % " / ".join(tasksets.FILTERS),
                  "status must be one of %s" % " / ".join(tasksets.FILTERS), 400)
        self.both("GET", "/api/task-set-line?id=%s&line=abc" % fid, None, "line 应为行号", "line must be a line number", 400)
        self.both("GET", "/api/task-set-line?id=%s&line=99" % fid, None, "没有第 99 行（或者这一行是空行）",
                  "There is no line 99 (or that line is blank)", 404)
        self.both("GET", "/api/task-set-image?id=%s&line=x&idx=0" % fid, None, "line / idx 应为整数",
                  "line and idx must be integers", 400)
        self.both("POST", "/api/task-set-rename", {"id": fid, "name": 5}, "name 应为文字", "name must be a string", 400)
        job = server.JOBS["perf"]
        job.try_start(None, "m", files=[tasksets.file_path(server.SCN_TASKS_DIR, fid)])   # 有速度测试正在读这个文件
        try:
            self.both("POST", "/api/task-set-delete", {"id": fid}, "有速度测试正在用这个任务集，等测试结束（或停止它）之后再删除",
                      "A speed test is using this task set. Delete it after the test finishes (or stop the test).", 409)
        finally:
            job.set(running=False, files=[])

    def test_endpoint_pages(self):
        self.both("POST", "/api/endpoints", {"url": "", "model": "m"}, "服务地址不能为空", "The service URL cannot be empty", 400)
        self.both("POST", "/api/endpoints", {"url": "http://x", "model": ""}, "模型名称不能为空", "The model name cannot be empty", 400)
        self.both("POST", "/api/endpoints", {"url": "http://x", "model": "m", "name": "名" * 65},
                  "名称最多 64 个字（现在 65 个）", "The name can be at most 64 characters (currently 65)", 400)
        self.both("POST", "/api/endpoints", {"url": 5, "model": "m"}, "url 应为文字", "url must be a string", 400)
        self.both("POST", "/api/endpoints", {"id": "x y", "url": "http://x", "model": "m"},
                  "模型 id 不对（应为 ep_ 开头的字母、数字、下划线）",
                  "Invalid model id (expected ep_ followed by letters, digits or underscores)", 400)
        self.both("POST", "/api/endpoint-use", {"id": "ep_nope"}, "这个模型不存在（可能已被删除）",
                  "This model does not exist (it may have been deleted)", 404)
        self.both("GET", "/api/endpoint-runs?id=ep_nope", None, "这个模型不存在（可能已被删除）",
                  "This model does not exist (it may have been deleted)", 404)
        st, d = self.request("POST", "/api/endpoints", {"url": "http://127.0.0.1:9000", "model": "m-i18n"})
        self.assertEqual(st, 200, d)
        ep = d["endpoint"]["id"]
        try:
            self.both("GET", "/api/endpoint-runs?id=%s&kind=zzz" % ep, None, "kind 应为 all / perf / iq / gen 之一",
                      "kind must be one of all / perf / iq / gen", 400)
            self.both("GET", "/api/endpoint-runs?id=%s&limit=abc" % ep, None, "limit 应为整数", "limit must be an integer", 400)
            self.both("GET", "/api/endpoint-runs?id=%s&limit=999" % ep, None, "limit 应为 1–%d" % endpoints.RUNS_MAX,
                      "limit must be between 1 and %d" % endpoints.RUNS_MAX, 400)
        finally:
            self.request("POST", "/api/endpoint-delete", {"id": ep})

    def test_cancel_and_conflict_messages(self):
        self.both("POST", "/api/cancel", {"job": "nope"}, "job 应为 perf / iq / gen / bank", "job must be one of perf / iq / gen / bank", 400)
        self.both("POST", "/api/cancel", {"job": "perf"}, "没有运行中的性能测试", "No speed test is running", 409)
        self.both("POST", "/api/cancel", {"job": "iq"}, "没有运行中的能力评测", "No capability test is running", 409)
        self.both("POST", "/api/cancel", {"job": "gen"}, "没有运行中的代码生成", "No code generation run is running", 409)
        self.both("POST", "/api/cancel", {"job": "bank"}, "没有运行中的题集更新", "No question set update is running", 409)
        job = server.JOBS["iq"]
        job.try_start("http://127.0.0.1:8011", "m")
        try:
            body = {"base": "http://127.0.0.1:8011", "model": "m", "suite": "quick"}
            st, d = self.request("POST", "/api/start", body, lang="en")
            self.assertEqual((st, d["code"], d["conflict"]), (409, "endpoint_busy", "capability test"))
            self.assertEqual(d["error"], "The capability test is using the same model endpoint. Running both at the same time "
                                         "would distort the throughput and latency data of the speed test.")
            assert_english(self, d)
            st, d = self.request("POST", "/api/start", body, lang="zh")
            self.assertEqual((d["conflict"], d["error"]), ("能力评测", "能力评测正在使用同一模型端点。同时运行会使性能测试的吞吐和延迟数据失真。"))
        finally:
            job.set(running=False)

    def test_same_kind_already_running_message(self):
        job = server.JOBS["perf"]
        job.try_start("http://127.0.0.1:8997", "m")
        try:
            body = {"base": "http://127.0.0.1:8997", "model": "m"}
            st, d = self.request("POST", "/api/start", body, lang="en")
            self.assertEqual((st, d["error"]), (409, "Another speed test is already running"))
            st, d = self.request("POST", "/api/start", body, lang="zh")
            self.assertEqual((st, d["error"]), (409, "已有性能测试在运行"))
        finally:
            job.set(running=False)

    def test_accept_language_is_the_fallback(self):
        zh = "服务地址不能为空"
        body = {"url": "", "model": "m"}
        self.assertEqual(self.error_of("POST", "/api/endpoints", body, headers={"Accept-Language": "en-US,en;q=0.9"})[1],
                         "The service URL cannot be empty")
        self.assertEqual(self.error_of("POST", "/api/endpoints", body, headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})[1], zh)
        self.assertEqual(self.error_of("POST", "/api/endpoints", body, lang="zh", headers={"Accept-Language": "en-US"})[1], zh)   # X-Lang 优先
        self.assertEqual(self.error_of("POST", "/api/endpoints", body, lang="en", headers={"Accept-Language": "zh-CN"})[1],
                         "The service URL cannot be empty")
        self.assertEqual(self.error_of("POST", "/api/endpoints", body, headers={"Accept-Language": "fr"})[1], zh)   # 都不认识: 默认 (测试里是 zh)

    def test_language_does_not_leak_between_requests(self):
        body = {"url": "", "model": "m"}
        seq = [("en", "The service URL cannot be empty"), ("zh", "服务地址不能为空"), ("en", "The service URL cannot be empty"),
               (None, "服务地址不能为空")]
        for lang, want in seq * 2:
            self.assertEqual(self.error_of("POST", "/api/endpoints", body, lang=lang)[1], want)

    def test_concurrent_requests_keep_their_own_language(self):
        body = {"url": "", "model": "m"}
        results, errors = [], []

        def one(lang, want):
            try:
                for _ in range(10):
                    results.append(self.error_of("POST", "/api/endpoints", body, lang=lang)[1] == want)
            except Exception as e:      # noqa: BLE001
                errors.append(e)
        ths = [threading.Thread(target=one, args=("en", "The service URL cannot be empty")),
               threading.Thread(target=one, args=("zh", "服务地址不能为空")),
               threading.Thread(target=one, args=("en", "The service URL cannot be empty")),
               threading.Thread(target=one, args=("zh", "服务地址不能为空"))]
        for th in ths:
            th.start()
        for th in ths:
            th.join(30)
        self.assertEqual(errors, [])
        self.assertEqual((len(results), all(results)), (40, True))

    def test_framework_errors(self):
        st, d = self.request("POST", "/api/probe", {"base": "http://x"}, lang="en", headers={"Content-Type": "text/plain"})
        self.assertEqual((st, d["error"]), (415, "Content-Type must be application/json"))
        st, d = self.request("POST", "/api/probe", {"base": "http://x"}, headers={"Content-Type": "text/plain"})
        self.assertEqual((st, d["error"]), (415, "Content-Type 必须为 application/json"))
        st, d = self.request("POST", "/api/probe", {"base": "http://x"}, lang="en", headers={"Origin": "http://evil.example"})
        self.assertEqual((st, d["error"]), (403, "Cross-origin requests are not allowed"))
        st, d = self.request("POST", "/api/probe", {"base": "http://x"}, headers={"Origin": "http://evil.example"})
        self.assertEqual((st, d["error"]), (403, "拒绝跨源请求"))


class TestTokenMessagesFollowXLang(LangServerCase):
    token = "s3cret"

    def test_token_required(self):
        st, d = self.request("GET", "/api/version", lang="en")
        self.assertEqual((st, d["error"]), (401, "Access token required"))
        st, d = self.request("GET", "/api/version")
        self.assertEqual((st, d["error"]), (401, "需要访问令牌"))
        st, d = self.request("POST", "/api/cancel", {"job": "perf"}, lang="en")
        self.assertEqual((st, d["error"]), (401, "Access token required"))
        st, page = self.request("GET", "/", lang="en")
        self.assertEqual(st, 401)
        self.assertIn("This service requires an access token. Open it with <code>http://HOST:PORT/?token=TOKEN</code>.", page)
        assert_english(self, page, what="401 page")
        st, page = self.request("GET", "/", lang="zh")
        self.assertIn("该服务启用了访问令牌，请使用 <code>http://主机:端口/?token=令牌</code> 打开。</p>", page)
        self.assertTrue(page.startswith("<!doctype html><meta charset=utf-8><title>LLM Bench Pro</title>"
                                        "<p style='font:14px system-ui;margin:40px'>该服务启用了访问令牌"))


# ================================================================ 5. 试点: 页面启动的后台任务

def fake_tokens(body):
    text = "".join(m["content"] for m in body.get("messages", []) if isinstance(m.get("content"), str))
    return len(text) // 2 + 12


def sse(prompt_tokens, out=3):
    chunks = [b'data: {"choices":[{"delta":{"content":"x"}}]}\n\n' for _ in range(out)]
    chunks.append(b'data: {"choices":[],"usage":{"prompt_tokens":%d,"completion_tokens":%d}}\n\ndata: [DONE]\n\n' % (prompt_tokens, out))
    return b"".join(chunks)


def limited_server(real_limit=3000, max_model_len=6000, delay=0.0):
    """模拟服务: 假分词器 (每 2 个字符 1 个 token); 超过 real_limit 的请求返回 400「maximum context length」;
    max_model_len 不为 None 时 /v1/models 里报告它 (启动前就能把放不下的档位去掉), 为 None 时只能被服务拒绝时才知道。"""
    def handler(method, path, body):
        if method == "GET" and path.startswith("/v1/models"):
            item = {"id": "m"}
            if max_model_len:
                item["max_model_len"] = max_model_len
            return 200, {"data": [item]}, None
        if method == "POST":
            n = fake_tokens(body)
            if n > real_limit:
                return 400, {"error": {"message": "This model's maximum context length is %d tokens" % real_limit}}, None
            if delay:
                time.sleep(delay)
            return 200, sse(n, min(int(body.get("max_tokens") or 3), 3)), "text/event-stream"
        return 404, {"error": "not found"}, None
    return MockServer(handler)


class TestJobsRunInTheLanguageOfTheRequestThatStartedThem(LangServerCase):
    def wait_idle(self, kind="perf", timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            st = self.request("GET", "/api/%s" % {"perf": "status", "iq": "iq-status", "gen": "gen-status", "bank": "bank-status"}[kind])[1]
            if not st["running"]:
                return st
            time.sleep(0.05)
        self.fail("任务没有在 %d 秒内结束" % timeout)

    def lines(self, status):
        return [x["msg"] for x in status["log"]]

    def start_perf(self, mock_url, lang, **extra):
        body = {"base": mock_url, "model": "m", "suite": "quick", "conc_ladder": "1", "matrix_conc": "2", "metrics": False}
        body.update(extra)
        st, d = self.request("POST", "/api/start", body, lang=lang)
        self.assertEqual((st, d.get("ok")), (200, True), d)

    def test_perf_job_in_english_logs_and_stored_notes_have_no_chinese(self):
        """英文请求启动的速度测试: 日志 (含线程池工作线程里打的) 和存进结果里的说明 (含工作线程里生成的) 都是英文。"""
        m = limited_server(real_limit=3000, max_model_len=6000)
        try:
            self.start_perf(m.url, "en", force=True)      # force: 记一条「和别的测试同用一个端点」的说明进结果
            st = self.wait_idle()
        finally:
            m.close()
        lines = self.lines(st)
        self.assertIsNone(st["error"], st)
        self.assertGreater(len(lines), 8)
        assert_english(self, lines, what="job log")
        text = "\n".join(lines)
        self.assertIn("Length calibration: ", text)
        self.assertIn("8K skipped: Exceeds the model's maximum context (6000 tokens)", text)      # 启动前就去掉的档位 (任务线程)
        self.assertRegex(text, r"warmup skip: Exceeds the model's maximum context \(service replied: HTTP 400")   # 工作线程里的日志
        self.assertRegex(text, r"4K and longer tiers skipped: Exceeds the model's maximum context \(service replied: HTTP 400")
        doc = store.get_run(st["run_id"])
        self.assertEqual(doc["status"], "done")
        assert_english(self, doc, keys=STORED_TEXT_KEYS, what="stored result")
        reasons = {(s["phase"], s["label"]): s["reason"] for s in doc["length_skips"]}
        self.assertEqual(reasons[("prefill", "8K")], "Exceeds the model's maximum context (6000 tokens)")
        self.assertTrue(reasons[("prefill_conc", "8K")].startswith("Exceeds the model's maximum context"))
        # 这一条是在线程池的工作线程里生成的 (放不下的判断在 worker 里), 也是英文
        self.assertTrue(reasons[("prefill_conc", "4K")].startswith("Exceeds the model's maximum context (service replied: HTTP 400"))
        self.assertEqual(doc["notes"], ["The other test was using the same endpoint when this run started, so the data may be affected"])

    def test_perf_job_without_model_len_skips_are_found_by_the_service_rejection(self):
        m = limited_server(real_limit=3000, max_model_len=None)
        try:
            self.start_perf(m.url, "en", force=True, conflict_with="speed test")
            st = self.wait_idle()
        finally:
            m.close()
        lines = self.lines(st)
        assert_english(self, lines, what="job log")
        self.assertRegex("\n".join(lines), r"8K and longer tiers skipped: Exceeds the model's maximum context \(service replied")
        doc = store.get_run(st["run_id"])
        assert_english(self, doc, keys=STORED_TEXT_KEYS, what="stored result")
        self.assertEqual(doc["notes"], ["The speed test was using the same endpoint when this run started, so the data may be affected"])

    def test_same_job_in_chinese_is_unchanged(self):
        m = limited_server(real_limit=3000, max_model_len=6000)
        try:
            self.start_perf(m.url, "zh", force=True)
            st = self.wait_idle()
        finally:
            m.close()
        text = "\n".join(self.lines(st))
        self.assertIn("  长度校准: 每句 ", text)
        self.assertIn("  8K 跳过: 超过模型的最大上下文（6000 token）", text)
        self.assertRegex(text, r"warmup skip: 超过模型的最大上下文（服务返回：HTTP 400")
        self.assertRegex(text, r"  4K 及更长的档位跳过: 超过模型的最大上下文（服务返回：HTTP 400")
        self.assertRegex(text, r"  warmup shape: 输入x\d+句 × 并发\d+")
        doc = store.get_run(st["run_id"])
        self.assertEqual(doc["notes"], ["启动时其他测试正在使用同一端点，数据可能受干扰"])
        self.assertEqual({(s["phase"], s["label"]) for s in doc["length_skips"]} >= {("prefill", "8K"), ("prefill_conc", "4K")}, True)

    def test_a_later_request_in_another_language_does_not_change_the_job(self):
        """任务启动时记下语言: 运行途中来自另一种语言的请求 (包括停止) 不影响它的日志和结果里的文字。"""
        m = limited_server(real_limit=10 ** 9, max_model_len=None, delay=0.15)
        try:
            self.start_perf(m.url, "en", lens="1")
            for _ in range(200):                          # 等它开始跑
                st = self.request("GET", "/api/status", lang="zh")[1]
                if len(st["log"]) >= 3:
                    break
                time.sleep(0.05)
            self.assertEqual(server.JOBS["perf"].lang, "en")
            st, d = self.request("POST", "/api/cancel", {"job": "perf"}, lang="zh")   # 中文界面点了停止
            self.assertEqual((st, d), (200, {"ok": True}))
            st = self.wait_idle()
        finally:
            m.close()
        lines = self.lines(st)
        assert_english(self, lines, what="job log")
        self.assertIn("Stop requested: no new requests will be started, and results already completed are kept", lines)
        self.assertIn("Cancelled: completed phases have been saved", lines)
        doc = store.get_run(st["run_id"])
        self.assertEqual((doc["status"], doc["error"]), ("cancelled", "Cancelled by user"))
        # 停止请求自己的应答用请求的语言; 中文请求的提示是中文
        st2, d2 = self.request("POST", "/api/cancel", {"job": "perf"}, lang="zh")
        self.assertEqual((st2, d2["error"]), (409, "没有运行中的性能测试"))

    def test_every_job_kind_records_the_language_and_workers_inherit_it(self):
        """perf / iq / gen / bank 四种任务: 启动请求的语言传到任务线程, 以及任务里 spawn 出的线程和线程池的工作线程。"""
        seen = {}

        def probe(kind):
            def target_lang():
                inner = {}
                th = i18n.spawn(lambda: inner.__setitem__("spawn", i18n.current_lang()))
                th.join(5)
                with i18n.executor(2) as ex:
                    inner["pool"] = ex.submit(i18n.current_lang).result(5)
                seen[kind] = dict(inner, job=i18n.current_lang())
            return target_lang

        def fake_run_suite(*a, **kw):
            probe("perf")()
            raise RuntimeError("stop here")               # 抛出去: 任务的 error 里带着异常, 顺便看它的语言

        def fake_run_iq(*a, **kw):
            probe("iq")()

        def fake_run_gen(*a, **kw):
            probe("gen")()

        def fake_build(*a, **kw):
            probe("bank")()
            return {"bank_id": "iq-fake"}, "x"
        fake_bank = {"bank_id": "iq-fake", "subjects": []}
        with mock.patch.object(bench, "run_suite", fake_run_suite), mock.patch.object(iq, "run_iq", fake_run_iq), \
                mock.patch.object(gen, "run_gen", fake_run_gen), mock.patch.object(bankman, "build", fake_build), \
                mock.patch.object(bankman, "load_bank", lambda bank_id: fake_bank):
            for lang in ("en", "zh"):
                seen.clear()
                self.assertEqual(self.request("POST", "/api/start", {"base": "http://127.0.0.1:1", "model": "m"}, lang=lang)[1]["ok"], True)
                self.wait_idle("perf")
                self.assertEqual(self.request("POST", "/api/iq-start", {"base": "http://127.0.0.1:2", "model": "m", "bank_id": "iq-fake"}, lang=lang)[1]["ok"], True)
                self.wait_idle("iq")
                self.assertEqual(self.request("POST", "/api/gen-start", {"base": "http://127.0.0.1:3", "model": "m", "tasks": ["pelican"]}, lang=lang)[1]["ok"], True)
                self.wait_idle("gen")
                self.assertEqual(self.request("POST", "/api/bank-update", {"offline": True}, lang=lang)[1]["ok"], True)
                self.wait_idle("bank")
                for kind in ("perf", "iq", "gen", "bank"):
                    self.assertEqual(seen.get(kind), {"job": lang, "spawn": lang, "pool": lang}, (lang, kind))
        st = self.request("GET", "/api/status")[1]
        self.assertTrue(st["error"].startswith("RuntimeError: stop here"))       # 异常记录照旧


# ================================================================ 5. 试点: 各模块

class TestEndpointsModule(LangCase):
    BODIES = [
        ({"url": 5}, "url 应为文字", "url must be a string"),
        ({"url": ""}, "服务地址不能为空", "The service URL cannot be empty"),
        ({"url": "http://" + "a" * 600}, "服务地址最多 500 个字（现在 607 个）", "The service URL can be at most 500 characters (currently 607)"),
        ({"url": "ftp://x"}, "服务地址要以 http:// 或 https:// 开头，中间不能有空格，比如 http://127.0.0.1:8000",
         "The service URL must start with http:// or https:// and contain no spaces, e.g. http://127.0.0.1:8000"),
        ({"url": "http://h", "model": ""}, "模型名称不能为空", "The model name cannot be empty"),
        ({"url": "http://h", "model": "m" * 129}, "模型名称最多 128 个字（现在 129 个）", "The model name can be at most 128 characters (currently 129)"),
        ({"url": "http://h", "model": "m", "name": "n" * 65}, "名称最多 64 个字（现在 65 个）", "The name can be at most 64 characters (currently 65)"),
        ({"url": "http://h", "model": "m", "api_key": "k" * 8193}, "API Key 最多 8192 个字", "The API key can be at most 8192 characters"),
        ({"url": "http://h", "model": "m", "api_key": "a\nb"}, "API Key 中间不能有换行或其他控制字符",
         "The API key cannot contain line breaks or other control characters"),
    ]

    def test_clean_fields_messages_zh_exact_en_no_chinese(self):
        for body, zh, en in self.BODIES:
            with self.subTest(body=str(body)[:40]):
                with i18n.use_lang("zh"):
                    self.assertEqual(endpoints.clean_fields(body), (None, zh))
                with i18n.use_lang("en"):
                    got = endpoints.clean_fields(body)
                    self.assertEqual(got, (None, en))
                    assert_english(self, got[1])
        self.assertEqual(i18n.MISSING, set())

    def test_not_model_list_message(self):
        with i18n.use_lang("en"):
            with self.assertRaises(endpoints.NotModelList) as cm:
                endpoints.models_of({"nope": 1})
            self.assertEqual(str(cm.exception), "The response is not a model list (no data array)")
        with i18n.use_lang("zh"):
            with self.assertRaises(endpoints.NotModelList) as cm:
                endpoints.models_of({"nope": 1})
            self.assertEqual(str(cm.exception), "返回的不是模型列表（没有 data 数组）")

    def test_bad_url_is_a_function_not_a_frozen_constant(self):
        self.assertFalse(hasattr(endpoints, "BAD_URL"))
        with i18n.use_lang("en"):
            en = endpoints.bad_url()
        with i18n.use_lang("zh"):
            zh = endpoints.bad_url()
        self.assertNotEqual(en, zh)


class TestExportHtmlModule(LangCase):
    def compose(self, lang, title=""):
        with i18n.use_lang(lang):
            return export_html.compose("dash", {"api": {}}, {"theme": "dark", "ls": {}}, title)

    def test_default_title_and_generator_follow_the_language(self):
        zh, en = self.compose("zh"), self.compose("en")
        self.assertIn("<title>LLM Bench Pro 离线报告</title>", zh)
        self.assertIn('<meta name="generator" content="LLM Bench Pro 离线报告">', zh)
        self.assertIn("<title>LLM Bench Pro offline report</title>", en)
        self.assertIn('<meta name="generator" content="LLM Bench Pro offline report">', en)
        self.assertIn("<title>我的报告</title>", self.compose("en", "我的报告"))   # 调用方给的标题原样用

    def test_structure_error_message(self):
        for lang, want in (("zh", "web/index.html 结构变了, 找到 0 处 <title>LLM Bench Pro</title>"),
                           ("en", "The structure of web/index.html has changed: found 0 occurrences of <title>LLM Bench Pro</title>")):
            with self.subTest(lang=lang), i18n.use_lang(lang), mock.patch.object(export_html, "_read", return_value="<html></html>"):
                with self.assertRaises(RuntimeError) as cm:
                    export_html.compose("dash", {}, {}, "")
                self.assertEqual(str(cm.exception), want)
                if lang == "en":
                    assert_english(self, str(cm.exception))


class TestSinksModule(LangCase):
    def test_heartbeat_thread_runs_in_the_language_of_the_starter(self):
        """sinks 自己起的心跳线程用 i18n.spawn: 沿用启动它的线程 (任务线程) 的语言。"""
        seen, stop = [], threading.Event()

        def fake_heartbeat(run_id, db):
            seen.append(i18n.current_lang())
            stop.set()
        db = os.path.join(temp_dir(), "hb.db")
        doc = {"run_id": "run_20260101_000000_hb", "status": "running", "kind": "perf", "phases": [], "started_utc": "2026-01-01T00:00:00+00:00",
               "url": "http://x/v1/chat/completions", "model": "m", "suite": "quick"}
        sink = sinks.SqliteSink(db)
        sink.HEARTBEAT_S = 0.01
        with mock.patch.object(store, "heartbeat", fake_heartbeat), i18n.use_lang("en"):
            sink.save(doc)
            self.assertTrue(stop.wait(10))
            sink.save(dict(doc, status="done"))       # 收尾: 心跳线程停下
        self.assertEqual(seen[0], "en")


class TestBenchPilot(LangCase):
    """bench.py 试点: 校准 / 上下文超长 / 重跑 / 预热的日志 (带数量) 和存进结果里的说明。"""

    def setUp(self):
        LangCase.setUp(self)
        bench._NO_IGNORE_EOS.clear()      # 引擎的模块级状态: 别让前一个用例记下的端点 (端口可能被复用) 影响这个
        bench._REQ_EXTRA = {}
        bench._CANCEL = None
        self.addCleanup(setattr, bench, "_CANCEL", None)

    def failing_server(self, code=500):
        return MockServer(lambda *a: (code, {"error": "boom"}, None))

    def test_calibration_errors_stored_in_results(self):
        url = None
        m = self.failing_server()
        try:
            url = m.url + "/v1/chat/completions"
            with english_flow():
                cal = bench.calibrate_prompt(url, {}, "m")
                cal_rag = bench.calibrate_rag(url, {}, "m")
            with i18n.use_lang("zh"):
                cal_zh = bench.calibrate_prompt(url, {}, "m")
        finally:
            m.close()
        self.assertEqual(cal["method"], "guess")
        self.assertRegex(cal["error"], r'^Calibration request failed: HTTP 500: ')
        self.assertRegex(cal_rag["error"], r'^Calibration request failed: ')
        assert_english(self, [cal, cal_rag], keys=STORED_TEXT_KEYS)
        self.assertRegex(cal_zh["error"], r'^校准请求失败：HTTP 500: ')

    def test_calibration_when_usage_does_not_follow_length(self):
        m = MockServer(lambda method, path, body: (200, sse(10), "text/event-stream"))
        try:
            with english_flow():
                cal = bench.calibrate_prompt(m.url + "/v1/chat/completions", {}, "m")
            with i18n.use_lang("zh"):
                cal_zh = bench.calibrate_prompt(m.url + "/v1/chat/completions", {}, "m")
        finally:
            m.close()
        self.assertEqual(cal["error"], "The input token count returned by the service does not change with length "
                                       "(it may not be returning real usage)")
        self.assertIn("不随长度变化", cal_zh["error"])
        with english_flow():
            self.assertEqual(bench._cal_text(cal), "Calibration failed; using the old estimate of 77.5 tokens per sentence "
                                                   "(The input token count returned by the service does not change with length "
                                                   "(it may not be returning real usage))")

    def test_cal_text_and_context_messages(self):
        usage = {"method": "usage", "unit_tokens": 34.56, "overhead_tokens": 27}
        guess = {"method": "guess", "unit_tokens": 77.5, "overhead_tokens": 0, "error": "boom"}
        with i18n.use_lang("zh"):
            self.assertEqual(bench._cal_text(usage), "每句 %.1f token，说明文字和对话模板 %d token（实测）" % (34.56, 27))
            self.assertEqual(bench._cal_text(guess), "没能校准，按旧估算每句 %.1f token（%s）" % (77.5, "boom"))
            self.assertEqual(bench._cal_text(dict(guess, error=None)), "没能校准，按旧估算每句 %.1f token（%s）" % (77.5, ""))
            self.assertEqual(bench.fit_context([("8K", 1, 8000)], 6000, 96, "prefill")[1][0]["reason"], "超过模型的最大上下文（%d token）" % 6000)
        with i18n.use_lang("en"):
            self.assertEqual(bench._cal_text(usage), "34.6 tokens per sentence, 27 tokens for the instructions and chat template (measured)")
            self.assertEqual(bench._cal_text(dict(guess, error=None)), "Calibration failed; using the old estimate of 77.5 tokens per sentence ()")
            keep, skipped = bench.fit_context([("2K", 1, 2000), ("8K", 1, 8000)], 6000, 96, "prefill")
            self.assertEqual([x[0] for x in keep], ["2K"])
            self.assertEqual(skipped, [{"phase": "prefill", "label": "8K", "reason": "Exceeds the model's maximum context (6000 tokens)"}])
        err = bench.HTTPStatusError("http://x", 400, "Bad", {}, '{"error": "maximum context length is 10"}')
        with i18n.use_lang("zh"):
            self.assertEqual(bench.ctx_overflow(err), "超过模型的最大上下文（服务返回：%s）" % str(err)[:160])
        with i18n.use_lang("en"):
            self.assertEqual(bench.ctx_overflow(err), "Exceeds the model's maximum context (service replied: %s)" % str(err)[:160])
            self.assertIsNone(bench.ctx_overflow(bench.HTTPStatusError("http://x", 500, "Bad", {}, "boom")))

    def test_retry_log_line_with_counts(self):
        def attempts():
            calls = iter([{"ok": 1, "total": 3, "fail": 2}, {"ok": 3, "total": 3, "fail": 0}])
            return lambda: next(calls)
        with english_flow() as flow:
            bench._retry_cell(attempts(), "matrix 4K", max_attempts=3, pause_s=0.0)
        self.assertEqual(flow.lines, ["  matrix 4K: 2/3 failed, rerunning in 0s (attempt 2/3)"])
        with capture_plog() as lines, i18n.use_lang("zh"):
            bench._retry_cell(attempts(), "矩阵 4K", max_attempts=3, pause_s=0.0)
        self.assertEqual(lines, ["  %s: %d/%d 失败, %.0fs 后重跑 (尝试 %d/%d)" % ("矩阵 4K", 2, 3, 0.0, 2, 3)])

    def test_warmup_log_uses_singular_and_plural(self):
        cfg = {"prefill": [("1K", 1, 1000), ("2K", 5, 2000)], "prefill_conc": None, "conc": []}
        m = MockServer(lambda method, path, body: (200, sse(10), "text/event-stream"))
        try:
            with english_flow() as flow:
                bench._warmup(m.url + "/v1/chat/completions", {}, "m", cfg, True)
            with capture_plog() as lines, i18n.use_lang("zh"):
                bench._warmup(m.url + "/v1/chat/completions", {}, "m", cfg, True)
        finally:
            m.close()
        self.assertEqual(flow.lines, ["  warmup shape: input x1 sentence × concurrency 1", "  warmup shape: input x5 sentences × concurrency 1"])
        flow.assert_clean(self)
        self.assertEqual(lines, ["  warmup shape: 输入x%d句 × 并发%d" % (1, 1), "  warmup shape: 输入x%d句 × 并发%d" % (5, 1)])

    def test_vision_image_logs(self):
        d = temp_dir()
        for i in range(8):                                                          # 8 张都不是图片 (内容不对): 前 5 张逐个写, 其余合并成一行 (带数量)
            with open(os.path.join(d, "%d.png" % i), "wb") as f:
                f.write(b"not a png")
        with english_flow() as flow:
            with self.assertRaises(RuntimeError) as cm:
                bench._load_vision_images(d)
        self.assertIn("  Also skipped 3 more unusable images", flow.lines)
        self.assertTrue(str(cm.exception).startswith("No usable images in the image folder: "))
        with english_flow() as flow:
            with self.assertRaises(RuntimeError) as cm:
                bench._load_vision_images(os.path.join(d, "nope"))
        self.assertEqual(str(cm.exception), "Image folder not found: %s (the image scenario needs an uploaded image pack or a folder on the server)"
                         % os.path.join(d, "nope"))
        with i18n.use_lang("zh"):
            with capture_plog() as lines:
                with self.assertRaises(RuntimeError) as cm:
                    bench._load_vision_images(d)
        self.assertIn("  另外还跳过 3 张不能用的图片", lines)

    def test_image_pool_and_task_set_logs(self):
        for lang, pool, pic, tasks in (("zh", "  图片池 6 张(内置示例图片), 每请求 2 张", None, "  任务集 3 条"),
                                       ("en", "  Image pool: 6 images (built-in samples), 2 per request", None, "  Task set: 3 requests")):
            with self.subTest(lang=lang), i18n.use_lang(lang), capture_plog() as lines:
                with mock.patch.object(bench, "_scenario_request", lambda *a, **k: None), mock.patch.object(bench, "_cell_metrics", side_effect=RuntimeError("stop")):
                    with self.assertRaises(RuntimeError):
                        bench.phase_scenario("http://x/v1/chat/completions", {}, "m", "vision", {"conc": [1], "requests_per_worker": 1, "vision_images": 2})
                self.assertEqual(lines[0], pool)
        path = os.path.join(temp_dir(), "t.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(json.dumps({"messages": [{"role": "user", "content": "q%d" % i}]}) for i in range(3)))
        one = os.path.join(temp_dir(), "one.jsonl")
        with open(one, "w", encoding="utf-8") as f:
            f.write(json.dumps({"messages": [{"role": "user", "content": "q"}]}))
        for lang, file, want in (("zh", path, "  任务集 3 条"), ("en", path, "  Task set: 3 requests"), ("en", one, "  Task set: 1 request")):
            with self.subTest(lang=lang, file=file), i18n.use_lang(lang), capture_plog() as lines:
                with mock.patch.object(bench, "_cell_metrics", side_effect=RuntimeError("stop")):
                    with self.assertRaises(RuntimeError):
                        bench.phase_scenario("http://x/v1/chat/completions", {}, "m", "custom", {"conc": [1], "requests_per_worker": 1, "custom_file": file})
                self.assertEqual(lines[0], want)

    def test_run_suite_startup_errors(self):
        with english_flow():
            with self.assertRaises(RuntimeError) as cm:
                bench.run_suite("http://127.0.0.1:1/v1/chat/completions", "m", scenarios={"tasks": ["nope"]}, outdir=temp_dir())
            self.assertEqual(str(cm.exception), "Unknown task type: nope (choose from: chat/code/json/rag/vision/custom)")
            with self.assertRaises(RuntimeError) as cm:
                bench.run_suite("http://127.0.0.1:1/v1/chat/completions", "m", replay={"file": "/no/such/file"}, outdir=temp_dir())
            self.assertEqual(str(cm.exception), "Replay file not found: /no/such/file")
        with i18n.use_lang("zh"):
            with self.assertRaises(RuntimeError) as cm:
                bench.run_suite("http://127.0.0.1:1/v1/chat/completions", "m", scenarios={"tasks": ["nope"]}, outdir=temp_dir())
            self.assertEqual(str(cm.exception), "未知任务类型: nope (可选: chat/code/json/rag/vision/custom)")

    def test_cancel_result_error_is_stored_in_the_task_language(self):
        m = limited_server(real_limit=10 ** 9, max_model_len=None)
        cancel = threading.Event()
        cancel.set()
        try:
            with english_flow() as flow:
                loc = bench.run_suite(m.url + "/v1/chat/completions", "m", suite="quick", outdir=temp_dir(), cancel=cancel)
        finally:
            m.close()
        with open(loc, encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual((doc["status"], doc["error"]), ("cancelled", "Cancelled by user"))
        self.assertIn("Cancelled: completed phases have been saved", flow.lines)
        flow.assert_clean(self)

    def test_ignore_eos_rejection_log_and_stored_note(self):
        """端点拒绝 ignore_eos: 日志和 overrides 里的说明都是英文。"""
        def handler(method, path, body):
            if method == "POST" and body.get("ignore_eos"):
                return 400, {"error": "unknown field ignore_eos"}, None
            if method == "POST":
                return 200, sse(fake_tokens(body), 3), "text/event-stream"
            return 404, {}, None
        m = MockServer(handler)
        try:
            with english_flow() as flow:
                loc = bench.run_suite(m.url + "/v1/chat/completions", "m", suite="quick", outdir=temp_dir(), conc_ladder=[1], matrix_conc=2)
        finally:
            m.close()
        with open(loc, encoding="utf-8") as f:
            doc = json.load(f)
        self.assertIn("  The endpoint does not support ignore_eos; fixed output length turned off", flow.lines)
        self.assertEqual(doc["overrides"]["fixed_output_note"], "The endpoint does not support ignore_eos, so the output length was not fixed")
        flow.assert_clean(self, doc, keys=STORED_TEXT_KEYS)

    def test_cli_english_run_end_to_end(self):
        """命令行 python -m llm_bench_pro.bench --lang en (环境变量是 zh): 跑完一遍, 日志和结果文件里存的说明都没有汉字。"""
        m = limited_server(real_limit=3000, max_model_len=6000)
        out = temp_dir()
        try:
            env = dict(os.environ, PYTHONIOENCODING="utf-8", LLM_BENCH_LANG="zh", LLM_BENCH_DB=os.path.join(out, "cli.db"))
            r = subprocess.run([sys.executable, "-m", "llm_bench_pro.bench", "--lang", "en", "--url", m.url, "--model", "m",
                                "--suite", "quick", "--conc-ladder", "1", "--matrix-conc", "2", "--outdir", out, "--sink", "json"],
                               cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
        finally:
            m.close()
        text = r.stdout.decode("utf-8", "replace")
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        lines = [x for x in text.splitlines() if not x.startswith("done =>")]     # 这一行带临时目录的路径, 路径里可能有中文
        assert_english(self, lines, what="bench CLI output")
        self.assertIn("  8K skipped: Exceeds the model's maximum context (6000 tokens)", lines)
        self.assertTrue(any(x.startswith("  warmup shape: input x") for x in lines))
        files = [f for f in os.listdir(out) if f.endswith(".json")]
        self.assertEqual(len(files), 1)
        with open(os.path.join(out, files[0]), encoding="utf-8") as f:
            doc = json.load(f)
        assert_english(self, doc, keys=STORED_TEXT_KEYS, what="bench CLI result")
        self.assertTrue(any(s["reason"].startswith("Exceeds the model's maximum context") for s in doc["length_skips"]))

    def test_cli_main_takes_argv_and_lang(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            bench.main(["--lang", "en", "--help"])
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("--lang {zh,en}", out.getvalue())
        self.assertIn("Language of the interface and logs", out.getvalue())


class TestServerStartupMessages(LangCase):
    def test_legacy_dir_notes_follow_the_language(self):
        def build():
            root = temp_dir()
            data = os.path.join(root, "data")
            os.makedirs(os.path.join(root, "results"))
            os.makedirs(os.path.join(root, "works", "gen_a"))
            os.makedirs(os.path.join(root, "works", "gen_b"))
            os.makedirs(os.path.join(data, "works", "gen_a"))
            return root, data
        for lang, moved, left, merged in (("zh", "results/ 已搬到 data/results/", "works/ 里有 1 项和 data/works/ 重名，没有搬动，请手动核对后删除旧目录", None),
                                          ("en", "results/ was moved to data/results/",
                                           "works/ has 1 item with the same name in data/works/. It was not moved; please check it and delete "
                                           "the old directory manually", None)):
            with self.subTest(lang=lang), i18n.use_lang(lang):
                root, data = build()
                notes = server.migrate_legacy_dirs(root, data)
                self.assertEqual(notes, [(moved, False), (left, True)])
                if lang == "en":
                    assert_english(self, [n for n, _ in notes])
        with i18n.use_lang("en"):                                                  # 重名的有好几项: 复数
            root, data = build()
            os.makedirs(os.path.join(data, "works", "gen_b"))
            self.assertEqual(server.migrate_legacy_dirs(root, data)[1][0],
                             "works/ has 2 items with the same name in data/works/. They were not moved; please check them and delete "
                             "the old directory manually")
        with i18n.use_lang("en"):                                                  # 全搬进去了: 「已并入」
            root, data = build()
            os.rmdir(os.path.join(root, "works", "gen_a"))
            os.makedirs(os.path.join(data, "works"), exist_ok=True)
            self.assertEqual([n for n, _ in server.migrate_legacy_dirs(root, data)], ["results/ was moved to data/results/", "works/ was merged into data/works/"])
        with i18n.use_lang("en"), mock.patch.object(server.os, "rename", side_effect=OSError("locked")):
            root, data = build()
            note = server.migrate_legacy_dirs(root, os.path.join(root, "data2"))[0][0]
            self.assertEqual(note, "Moving results/ to data/ failed (locked). Close any program that is using these files and restart the "
                                   "service, or move it to data/results/ manually")

    def test_port_in_use_message(self):
        holder = socket.socket()
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        saved = dict(server.CONFIG)
        try:
            for lang, first in (("en", "✗ Cannot listen on 127.0.0.1:%d (" % port), ("zh", "✗ 无法监听 127.0.0.1:%d（" % port)):
                with self.subTest(lang=lang):
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as cm:
                        server.main([str(port), "--lang", lang])
                    self.assertEqual(cm.exception.code, 1)
                    self.assertTrue(out.getvalue().startswith(first), out.getvalue())
                    self.assertIn("python run.py %d" % (port + 1), out.getvalue())
                    i18n.set_default_lang(None)
        finally:
            holder.close()
            server.CONFIG.clear()
            server.CONFIG.update(saved)


class TestOtherEntryPoints(LangCase):
    def help_text(self, main, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            main(argv)
        return out.getvalue()

    def test_main_functions_accept_lang(self):
        import cdp
        import geneval
        for name, main in (("store", store.main), ("bankman", bankman.main), ("geneval", geneval.main)):
            with self.subTest(entry=name):
                i18n.set_default_lang(None)
                text = self.help_text(main, ["--lang", "en", "--help"])
                self.assertIn("Language of the interface and logs", text)
                text = self.help_text(main, ["--lang", "zh", "--help"])
                self.assertIn("界面和日志的语言", text)
        i18n.set_default_lang(None)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cdp.main(["--lang", "en"]), 0)         # cdp 没有动作时打印帮助
        self.assertIn("Language of the interface and logs", out.getvalue())
        i18n.set_default_lang(None)


if __name__ == "__main__":
    unittest.main()
