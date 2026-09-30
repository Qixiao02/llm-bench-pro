# -*- coding: utf-8 -*-
"""界面文字与翻译 (中文 / English) 的自动检查, 分四层:

1. 词法扫描器 (tests/i18n_lint.py): 字符串 / 模板字符串 (含嵌套的 ${ }) / 注释 / 正则字面量 / 除号的区分, 以及
   「含汉字又不是 t() 键的字符串」「t 被局部变量遮住」等规则本身的单元测试; 再拿它扫真实的 app.js, 确认能完整扫完、括号平衡;
2. 基线棘轮: 每个区域的违规数不能比 tests/i18n_baseline.json 多 (也不能比基线少却没更新基线);
3. 词典 (web/static/i18n.en.*.js): 格式、重复、占位符和 HTML 标签与中文一致、英文里没有汉字、tn 的值是 [单数, 复数];
   已经转完的区域 (基线为 0) 里 t() / tn() 用到的键必须都有英文;
4. index.html / app.css: 静态文字有英文词条、CSS 里生成的中文有 :lang(en) 覆盖、每个页面「更多」菜单里有语言项、翻译脚本按顺序加载。

需要 Node 的几项 (词法扫描器与 Node 逐个对拍字符串还原、词典解析对拍、正则模式检查、页头脚本与 I18N.detect 一致) 无 Node 自动跳过。
新加界面文字的规矩见 CONTRIBUTING.md「界面文字与翻译」; 命令行工具: python tests/i18n_lint.py --report。
"""
import json
import os
import re
import shutil
import subprocess
import unittest

from _util import temp_dir  # noqa: F401  (副作用: 把包目录注入 sys.path)
import i18n_lint as L

ROOT = L.ROOT
BS = chr(92)  # 反斜杠 (测试里要拼出 \n 中 这样的转义文字, 不直接在源码里写)
NODE = shutil.which("node")


def js(*parts):
    return "".join(parts)


def scan(src, path="x.js"):
    return L.Scan(path, src)


def kinds(src):
    sc = scan(src)
    return [(t.kind, src[t.start:t.end]) for t in sc.sig]


def bad(src, path="x.js"):
    """违规文字 (含汉字又不是词典键的字符串 / 模板字符串)。"""
    return [v.text for v in scan(src, path).violations]


ZH = u"中文"


class TestLexer(unittest.TestCase):
    # ---------------- 字符串
    def test_string_escapes_are_cooked(self):
        src = js('"a', BS, "n", BS, "u4e2d", BS, "x41", BS, '"b"')
        sc = scan(src)
        self.assertEqual([t.value for t in sc.sig if t.kind == "str"], [u"a\n" + u"中" + u"A\"b"])
        self.assertEqual(scan(js("'", BS, "u{4e2d}", BS, "'x'")).sig[0].value, u"中'x")
        self.assertEqual(scan(js("'", BS, "ud83d", BS, "ude00'")).sig[0].value, u"\U0001F600")   # 代理对拼回一个字符
        self.assertEqual(scan(js('"ab', BS, "\ncd\"")).sig[0].value, "abcd")                       # 行尾的续行
        self.assertEqual(scan(js('"say ', BS, '"hi', BS, '" and \'x\'"')).sig[0].value, "say \"hi\" and 'x'")

    def test_quotes_inside_other_quotes(self):
        self.assertEqual([k for k, _ in kinds("""a = "it's" + 'say "hi"' ;""")], ["ident", "punct", "str", "punct", "str", "punct"])

    # ---------------- 模板字符串
    def test_template_segments(self):
        toks = scan("`a${b}c`").sig
        self.assertEqual([(t.kind, t.value) for t in toks], [("tmpl_head", "a"), ("ident", None), ("tmpl_tail", "c")])
        self.assertEqual(toks[0].tid, toks[2].tid)
        self.assertEqual(scan("`plain`").sig[0].kind, "tmpl")
        self.assertEqual(scan("`$5 {x}`").sig[0].value, "$5 {x}")            # $ 后面不是 { 就是普通文字

    def test_nested_templates_and_braces_in_expressions(self):
        toks = scan("`x${ `y${z}w` }v`").sig
        self.assertEqual([t.kind for t in toks], ["tmpl_head", "tmpl_head", "ident", "tmpl_tail", "tmpl_tail"])
        self.assertEqual(len(set(t.tid for t in toks if t.kind.startswith("tmpl"))), 2)
        self.assertEqual(toks[0].tid, toks[4].tid)
        self.assertEqual(toks[1].tid, toks[3].tid)
        for src in ("`${ {a:1}.a }`", "`${ [1].map(x=>{return x}) }`", "`${ \"}\" }`", "`${ '`' }`", "`${ /[}`]/.test(y) }`"):
            with self.subTest(src=src):
                sc = scan(src)
                self.assertEqual(sc.errors, [], src)
                self.assertEqual([t.kind for t in sc.sig if t.kind.startswith("tmpl")][0], "tmpl_head")

    def test_escaped_backtick_and_dollar(self):
        self.assertEqual(scan(js("`a", BS, "`b`")).sig[0].value, "a`b")
        self.assertEqual(scan(js("`", BS, "${x}`")).sig[0].kind, "tmpl")                     # \${ 不是插值

    # ---------------- 正则 vs 除号
    def test_division_and_regex(self):
        cases = [
            ("a / b / c", ["ident", "punct", "ident", "punct", "ident"]),
            ("(a+b)/2", ["punct", "ident", "punct", "ident", "punct", "punct", "num"]),
            ("arr[0]/2/3", ["ident", "punct", "num", "punct", "punct", "num", "punct", "num"]),
            ("x++ / 2", ["ident", "punct", "punct", "num"]),
            ("1/2/3", ["num", "punct", "num", "punct", "num"]),
            ("s.replace(/a/g,'b')", ["ident", "punct", "ident", "punct", "regex", "punct", "str", "punct"]),
            ("f=x=>/a/.test(x)", ["ident", "punct", "ident", "punct", "regex", "punct", "ident", "punct", "ident", "punct"]),
            ("return /[/]/.test(y)", ["ident", "regex", "punct", "ident", "punct", "ident", "punct"]),
            ("a?/x/:/y/", ["ident", "punct", "regex", "punct", "regex"]),
            ("[/a/,/b/]", ["punct", "regex", "punct", "regex", "punct"]),
            ("!/a/.test(x)", ["punct", "regex", "punct", "ident", "punct", "ident", "punct"]),
        ]
        for src, want in cases:
            with self.subTest(src=src):
                self.assertEqual([k for k, _ in kinds(src)], want)

    def test_regex_edge_cases(self):
        for src in ('/["\']/g', js("/", BS, "/a", BS, "/b/"), "/[/]+/", js("/", BS, "$", BS, "{x", BS, "}/"), "/`/g", "/'/", '/"/'):
            with self.subTest(src=src):
                toks = scan("x=" + src + ".test(s)").sig
                self.assertEqual([t.kind for t in toks][:3], ["ident", "punct", "regex"], src)
                self.assertEqual(scan("x=" + src).errors, [])
        # 花括号后面换了行 = 新语句的开头, 里面的 / 是正则
        self.assertEqual([k for k, _ in kinds("if(a){}\n/x/.test(y)")][-6], "regex")

    # ---------------- 注释
    def test_comments_do_not_confuse(self):
        sc = scan('a = "http://x" // it\'s a "comment"\nb = 1 /* "unterminated string? */ + 2')
        self.assertEqual([k for k, _ in kinds('a = "http://x" // it\'s\nb = 1')], ["ident", "punct", "str", "ident", "punct", "num"])
        self.assertEqual(sc.errors, [])
        self.assertEqual([k for k, _ in kinds("a /* c */ / b")], ["ident", "punct", "ident"])
        self.assertEqual([k for k, _ in kinds('s = "/* not a comment */"')], ["ident", "punct", "str"])
        self.assertEqual([k for k, _ in kinds("r = /a\\/*b/")], ["ident", "punct", "regex"])   # 正则里的 /* 不是注释

    def test_unterminated_things_are_reported(self):
        self.assertTrue(scan('a = "abc\nb = 2').errors)
        self.assertTrue(scan("a = `abc").errors)
        self.assertTrue(scan("a = /* abc").errors)
        self.assertTrue(scan("a = {").errors)
        self.assertTrue(scan("a = (]").errors)

    def test_numbers_and_operators(self):
        self.assertEqual([k for k, _ in kinds("a=1.5.toFixed(2)+.5+0x1F+1e-3+10n+1_000")].count("num"), 7)
        self.assertEqual([x for k, x in kinds("a?.b??c===d=>e...f")], ["a", "?.", "b", "??", "c", "===", "d", "=>", "e", "...", "f"])

    # ---------------- 规则: 含汉字的字符串
    def test_chinese_in_comment_and_regex_is_fine(self):
        self.assertEqual(bad("/* 中文 */ // 更多中文\nx = /进度\\s*(\\d+)/.exec(s)"), [])

    def test_chinese_in_string_and_template_is_flagged(self):
        self.assertEqual(bad('x = "%s"' % ZH), [ZH])
        self.assertEqual(bad("x = `%s`" % ZH), [ZH])
        self.assertEqual(bad("x = `<b>${n}</b> %s ${m}`" % ZH), ["${…}".join(["<b>", "</b> " + ZH + " ", ""])])
        self.assertEqual(bad("x = `<b>${ '%s' }</b>`" % ZH), [ZH])        # ${} 里面的字符串也算
        self.assertEqual(len(bad("x = `%s ${ `%s` }`" % (ZH, ZH))), 2)     # 嵌套的模板各算一个
        self.assertEqual(bad("x = `<b>${n}</b>`"), [])                     # 静态文字里没有汉字就不算

    def test_cjk_punctuation_counts_but_ascii_lookalikes_do_not(self):
        self.assertEqual(len(bad(u'a = ["，", "、", "（", "「"]')), 4)
        self.assertEqual(bad(u'a = ["—", "…", "·", "→", "×"]'), [])

    def test_translation_calls_exempt_only_their_first_argument(self):
        ok = ['t("%s")' % ZH, 'tn("{n} %s", n)' % ZH, 'td("%s")' % ZH, 'tm("%s")' % ZH, 'tk("%s")' % ZH, "t(`%s`)" % ZH,
              'I18N.t("%s")' % ZH, 't ( \n  "%s"\n )' % ZH, 't("%s", {a: n})' % ZH, 't("%s", null, "%s")' % (ZH, ZH)]
        for src in ok:
            with self.subTest(src=src):
                self.assertEqual(bad(src), [], src)
        flagged = ['t("a" + "%s")' % ZH, 't(x ? "%s" : "b")' % ZH, 'foo.t("%s")' % ZH, 'xt("%s")' % ZH, 'split("%s")' % ZH,
                   't("ok", {a: "%s"})' % ZH, 'function t(){} ; t("a", "%s")' % ZH]
        for src in flagged:
            with self.subTest(src=src):
                self.assertTrue(bad(src), src)

    def test_template_key_with_substitution_is_flagged_with_reason(self):
        v = scan("t(`%s ${x}`)" % ZH).violations
        self.assertEqual(len(v), 1)
        self.assertIn("${", v[0].reason)

    def test_call_extraction(self):
        sc = scan(js('a = t("更好", null, "对比") + tn("{n} 行", 3) + td("鹈鹕") + tm(e) + t(x) + tk("可用");'))
        got = [(c.name, c.dict_key(), c.dynamic) for c in sc.calls]
        self.assertEqual(got, [("t", "对比|更好", False), ("tn", "{n} 行", False), ("td", "鹈鹕", False), ("tm", None, True),
                               ("t", None, True), ("tk", "可用", False)])

    def test_placeholder_arguments_are_checked_against_the_key(self):
        def mism(src):
            R = L.Result()
            R.js["x.js"] = scan(src)
            return [(c.name, lack, extra) for c, lack, extra in L.placeholder_mismatches(R)]
        ok = ['t("共 {n} 行 {名字}", {n: 3, 名字: x})', 't("{a}", {"a": 1})', 't("{a}", {a})', 't("没有占位符")', 't("{{n}} 字面", {})',
              't("{a}", x)', 't("{a}", {...rest})', 't("{a}", {[k]: 1})', 'tn("{n} 行", n)', 'tn("{n} 行 {m}", n, {m: 1})', 'tn("{n} 行", n, {n: fmtInt(n)})',
              't("更好", null, "对比")', 't("{a} 和 {b}", {a: f(1, 2), b: `x${y}`})', 'td("{a}")', 'tm("{a}")', 't("没有", null)']
        for src in ok:
            with self.subTest(src=src):
                self.assertEqual(mism(src), [], src)
        self.assertEqual(mism('t("共 {n} 行")'), [("t", ["n"], [])])                       # 没传参数: 界面上会原样显示 {n}
        self.assertEqual(mism('t("共 {n} 行", {m: 1})'), [("t", ["n"], ["m"])])           # 名字写错了
        self.assertEqual(mism('t("没有占位符", {n: 1})'), [("t", [], ["n"])])            # 多传了
        self.assertEqual(mism('tn("{n} 行 {m}", n)'), [("tn", ["m"], [])])
        self.assertEqual(mism('tn("{n} 行", n, {k: 1})'), [("tn", [], ["k"])])

    # ---------------- 区域
    def test_areas_follow_banner_comments(self):
        src = "x = '%s'\n/* ======\n   基础工具\n   ====== */\ny = '%s'\n/* ======\n   任务集: 列表\n   ====== */\nz = '%s'\n" % (ZH, ZH, ZH)
        got = [(v.area, v.text) for v in scan(src, "web/static/app.js").violations]
        self.assertEqual(got, [(L.START_AREA, ZH), ("基础工具", ZH), ("任务集", ZH)])
        self.assertEqual(L.banner_title("/* ======\n   速度测试: 新建\n   ====== */"), "速度测试: 新建")
        self.assertIsNone(L.banner_title("/* 普通注释 */"))
        self.assertEqual(L.area_of_title("速度测试: 结果页 (结论 → 指标)"), ("速度测试: 结果页", "perf"))
        self.assertIsNone(L.area_of_title("没登记过的区域")[1])

    # ---------------- t 被局部变量遮住
    def test_shadowing_is_detected(self):
        def shadows(src, path="x.js"):
            return [(name, line) for _p, line, name, _b in scan(src, path).shadows]
        self.assertTrue(shadows('function f(){ const t = 1; return t("%s") }' % ZH))
        self.assertTrue(shadows('function f(a, t){ return t("%s") }' % ZH))
        self.assertTrue(shadows('const f = t => t("%s")' % ZH))
        self.assertTrue(shadows('function f(o){ const {a, t} = o; return t("%s") }' % ZH))
        self.assertTrue(shadows('function f(o){ const [a, t] = o; return t("%s") }' % ZH))
        self.assertTrue(shadows('function f(o){ return o.map(([k, t]) => t("%s")) }' % ZH))
        self.assertTrue(shadows('function f(){ for (const t of xs) {} return t("%s") }' % ZH))
        self.assertTrue(shadows('function f(){ const a = 1, t = 2; return t("%s") }' % ZH))
        self.assertTrue(shadows('function f(){ try {} catch (t) {} return t("%s") }' % ZH))
        self.assertTrue(shadows('function f(){ const tn = 1; return tn("{n}", 1) }'))
        # 不算遮住: 别的名字、属性、对象的键、别的顶层函数里的 t
        self.assertEqual(shadows('function f(){ return t("%s") }' % ZH), [])
        self.assertEqual(shadows('function f(x){ const tt = 1; return t("%s") + x.t + ({t: 1}).t }' % ZH), [])
        self.assertEqual(shadows('function g(t){ return t }\nfunction f(){ return t("%s") }' % ZH), [])
        self.assertEqual(shadows('function f(t){ return t }\n'), [])                       # 有变量 t 但没调用翻译函数
        self.assertEqual(shadows('function f(t){ return t(x) }'), [])                        # t(x): 不是翻译调用 (第一个参数不是字面量)

    def test_top_level_names_clash(self):
        for src in ("const t = 1;", "let tn = () => 1;", "function td(){}", "var I18N = {};", "class tm {}"):
            with self.subTest(src=src):
                self.assertTrue(scan(src, "web/static/app.js").clashes, src)
        self.assertFalse(scan("const t = 1;", "web/static/i18n.js").clashes)                # i18n.js 自己就是定义它们的地方
        self.assertFalse(scan("function f(){ const t = 1 }", "web/static/app.js").clashes)   # 只查顶层


class TestAllowList(unittest.TestCase):
    def test_allow_list_matches_source_line_fragment(self):
        d = temp_dir()
        path = os.path.join(d, "allow.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# 注释\n\nweb/static/app.js: label('%s')\nweb/index.html:  语言 / Language \n" % ZH)
        allow = L.load_allow(path)
        self.assertEqual([(a["file"], a["frag"]) for a in allow], [("web/static/app.js", "label('%s')" % ZH), ("web/index.html", "语言 / Language")])
        self.assertTrue(L._allowed(allow, "web/static/app.js", "x = label('%s') + 1" % ZH))
        self.assertFalse(L._allowed(allow, "web/static/other.js", "x = label('%s')" % ZH))
        self.assertEqual([a["used"] for a in allow], [1, 0])
        with open(path, "w", encoding="utf-8") as f:
            f.write("没有冒号的行\n")
        self.assertRaises(ValueError, L.load_allow, path)


class TestHtmlScan(unittest.TestCase):
    def items(self, html):
        return [(i.kind, i.key, i.area) for i in L.scan_html("t.html", html).items]

    def test_text_attributes_areas_and_whitespace(self):
        html = ("<!-- ======================== 页面A(说明) ======================== -->\n"
                "<h1 title=\"标&quot;题&quot;\">  你好\n   世界  </h1><input placeholder='请输入'><img alt=\"图\">\n"
                "<!-- ====== 页面B ====== -->\n<p>Hello</p><button aria-label=\"关闭\">x</button>")
        self.assertEqual(self.items(html), [("attr:title", u"标\"题\"", "页面A"), ("text", "你好 世界", "页面A"),
                                            ("attr:placeholder", "请输入", "页面A"), ("attr:alt", "图", "页面A"),
                                            ("attr:aria-label", "关闭", "页面B")])

    def test_skipped_elements_and_whole_element_keys(self):
        html = ("<script>var a='中文'</script><style>.a{content:'中文'}</style><svg><text>中文</text></svg><textarea>中文</textarea>"
                "<span translate=\"no\">中文</span><p data-i18n-html>先看 <code>x</code>，再<b>做</b>吧</p>")
        got = self.items(html)
        self.assertEqual([(k, key) for k, key, _a in got], [("html", u"先看 <code>x</code>，再<b>做</b>吧")])


class TestCssScan(unittest.TestCase):
    def test_content_needs_lang_en_override(self):
        css = ("/* ======\n   4. 组件\n   ====== */\n"
               ".a::before{content:\"（\"}\n"
               "html:lang(en) .a::before{content:\"(\"}\n"
               ".b::after{content:\"开\"}\n"
               "@media (max-width:860px){ .c{content:\"必填：\"} html:lang(en) .c{content:\"Required: \"} }\n"
               ".d{content:\"x\"}")
        items = L.CssScan("t.css", css).items
        self.assertEqual([(i.key, i.area, i.line) for i in items], [("开", "4. 组件", 6)])


class TestDictionaryParser(unittest.TestCase):
    def parse(self, src, name="i18n.en.x.js"):
        D = L.Dictionaries()
        L.parse_dictionary(name, src, D)
        return D

    def test_entries_arrays_concat_comments_and_patterns(self):
        D = self.parse(js('/* 说明 */\nI18N.add("en", {\n  "a": "A",  /* c */\n  "{n} 行": ["{n} row", "{n} rows"],\n  "长": "one " +\n    "two",\n});\n',
                          'I18N.add("enData", {"数据": "Data"});\n',
                          "I18N.addPattern([/^x(.+)$/, \"X$1\"], [/^y$/, (m) => tm(m) + \"!\"]);"))
        self.assertEqual(D.errors, [])
        self.assertEqual(D.en, {"a": "A", "{n} 行": ["{n} row", "{n} rows"], "长": "one two"})
        self.assertEqual(D.en_data, {"数据": "Data"})
        self.assertEqual([(p[2], p[3]) for p in D.patterns], [("/^x(.+)$/", "X$1"), ("/^y$/", "<函数>")])

    def test_errors_are_reported_with_line_numbers(self):
        D = self.parse('I18N.add("en", {\n  "a": "A",\n  "a": "B"\n});\nI18N.add("fr", {});\nfoo();\nI18N.add("en", {"b" "c"});\n')
        msgs = [m for _f, _l, m in D.errors]
        self.assertTrue(any("重复" in m for m in msgs), msgs)
        self.assertTrue(any("en" in m and "enData" in m for m in msgs), msgs)
        self.assertTrue(any("I18N" in m for m in msgs), msgs)
        self.assertTrue(any(l == 3 for _f, l, _m in D.errors))

    def test_same_key_with_different_values_across_files_conflicts(self):
        D = L.Dictionaries()
        L.parse_dictionary("a.js", 'I18N.add("en", {"x": "1", "y": "same"});', D)
        L.parse_dictionary("b.js", 'I18N.add("en", {"x": "2", "y": "same"});', D)
        self.assertEqual([(lang, k) for lang, k, _v in D.conflicts], [("en", "x")])

    def test_placeholder_and_tag_helpers(self):
        self.assertEqual(L.placeholders("{a} 和 {名字} {{x}} {}"), ["a", u"名字"])
        self.assertEqual(L.html_tags('<b>{n}</b> <span class="x">y</span><br>'), ["</b>", "</span>", "<b>", "<br>", '<span class="x">'])
        self.assertEqual(L.norm_key("  a \n   b\t c "), "a b c")


@unittest.skipUnless(NODE, "node 不可用, 跳过与 Node 对拍的检查")
class TestAgainstNode(unittest.TestCase):
    def node_json(self, code, stdin=None):
        p = subprocess.run([NODE, "-e", code], input=stdin, capture_output=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        return json.loads(p.stdout.decode("utf-8"))

    def test_lexer_agrees_with_node_on_every_literal_in_app_js(self):
        """扫描器认出的每个字符串 / 模板 / 正则, 交给 Node 自己解释: 还原出的文字必须一样, 正则必须能编译。"""
        with open(os.path.join(ROOT, "web", "static", "app.js"), encoding="utf-8") as f:
            sc = scan(f.read(), "web/static/app.js")
        src = sc.src
        strs = [(src[t.start:t.end], t.value) for t in sc.sig if t.kind in ("str", "tmpl")]
        regs = [src[t.start:t.end] for t in sc.sig if t.kind == "regex"]
        self.assertGreater(len(strs), 5000)
        self.assertGreater(len(regs), 50)
        data = json.dumps({"strs": [s for s, _v in strs], "regs": regs})
        out = self.node_json(
            "const d=JSON.parse(require('fs').readFileSync(0,'utf8'));"
            "const vals=d.strs.map(s=>eval(s));const regs=d.regs.map(r=>{const x=eval(r);return x instanceof RegExp});"
            "process.stdout.write(JSON.stringify({vals,regs}))", stdin=data.encode("utf-8"))
        want = [v for _s, v in strs]
        wrong = [(strs[i][0][:60], want[i], out["vals"][i]) for i in range(len(want)) if want[i] != out["vals"][i]]
        self.assertEqual(wrong[:5], [])
        self.assertTrue(all(out["regs"]))

    def test_dictionary_parse_agrees_with_node_evaluation(self):
        """静态解析出来的词典 = 真的执行 i18n.js + 各词典文件得到的 I18N.en / I18N.enData / 模式数。"""
        D = L.load_dictionaries()
        files = [os.path.join(L.STATIC, "i18n.js")] + L.dict_files()
        code = ("const vm=require('vm'),fs=require('fs');const c={console:console,window:{},navigator:{language:'zh-CN'},localStorage:{getItem(){return null}}};"
                "vm.createContext(c);const files=JSON.parse(process.argv[1]);"
                "for(const f of files)vm.runInContext(fs.readFileSync(f,'utf8'),c,{filename:f});"
                "process.stdout.write(vm.runInContext('JSON.stringify({en:I18N.en,enData:I18N.enData,patterns:I18N.patterns.map(p=>[p.re.source,typeof p.to==\"string\"?p.to:null,(new RegExp(p.re.source+\"|\")).exec(\"\").length-1]),dups:I18N.dups})',c))")
        p = subprocess.run([NODE, "-e", code, json.dumps(files)], capture_output=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        got = json.loads(p.stdout.decode("utf-8"))
        self.assertEqual(got["en"], D.en)
        self.assertEqual(got["enData"], D.en_data)
        self.assertEqual(got["dups"], [], "不同文件给同一个键写了不同的英文")
        self.assertEqual(len(got["patterns"]), len(D.patterns))
        for (source, to, groups), (fname, line, rx, repl) in zip(got["patterns"], D.patterns):
            if to is not None:  # 替换文字里的 $n 不能超过括号个数
                refs = [int(x) for x in re.findall(r"\$(\d)", to)]
                self.assertTrue(all(1 <= r <= groups for r in refs), "%s:%d 模式 %s 的替换 %r 引用了不存在的括号" % (fname, line, rx, to))

    def test_head_script_language_choice_matches_i18n_detect(self):
        """index.html 头部那段抢在首屏前选语言的脚本, 和 I18N.detect 在各种输入下选的一样 (两处写了同一套规则)。"""
        with open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8") as f:
            html = f.read()
        head = next(m for m in re.findall(r"<script>([\s\S]*?)</script>", html) if "llm-bench-pro-lang" in m)
        with open(os.path.join(L.STATIC, "i18n.js"), encoding="utf-8") as f:
            i18n = f.read()
        combos = [(off, stored, nav, url) for off in (None, "zh", "en", "xx") for stored in (None, "zh", "en", "xx")
                  for nav in ("zh-CN", "en-US", "de", None) for url in (None, "zh", "en", "xx")]
        code = ("const vm=require('vm');const {head,i18n,combos}=JSON.parse(require('fs').readFileSync(0,'utf8'));const out=[];"
                "for(const [off,stored,nav,url] of combos){"
                " const el={lang:'',dataset:{},classList:{add(){},remove(){}}};"
                " const w={};if(off!==null)w.LLMB_OFF_STATE={theme:'dark',ls:{'llm-bench-pro-lang':off}};"
                " const ctx={window:w,document:{documentElement:el},localStorage:{getItem:k=>k==='llm-bench-pro-lang'?stored:null},"
                "  navigator:nav===null?{}:{language:nav},matchMedia:()=>({matches:false}),setTimeout(){},"
                "  location:{search:url===null?'':'?lang='+url}};"
                " vm.createContext(ctx);"
                " vm.runInContext(head,ctx);"
                " const headLang=el.lang==='en'?'en':'zh';"
                " const c2={window:w,localStorage:ctx.localStorage,navigator:ctx.navigator,location:ctx.location,URLSearchParams,console};vm.createContext(c2);"
                " out.push([headLang,vm.runInContext(i18n+';I18N.lang',c2)])}"
                "process.stdout.write(JSON.stringify(out))").replace("const ctx={window:w,", "const ctx={URLSearchParams,window:w,")
        payload = json.dumps({"head": head, "i18n": i18n, "combos": combos}).encode("utf-8")   # 脚本比较长, 走标准输入 (命令行长度有上限)
        p = subprocess.run([NODE, "-e", code], input=payload, capture_output=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        for combo, (a, b) in zip(combos, json.loads(p.stdout.decode("utf-8"))):
            self.assertEqual(a, b, "页头脚本与 I18N.detect 在 %r 下选的语言不一样" % (combo,))


    def test_auto_detect_switch_and_head_script_agree(self):
        """AUTO_DETECT 是两处写的同一个开关 (i18n.js 和 index.html 页头脚本): 一处打开另一处没改, 页头选的语言就和 i18n.js 对不上。"""
        with open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8") as f:
            html = f.read()
        head = next(m for m in re.findall(r"<script>([\s\S]*?)</script>", html) if "llm-bench-pro-lang" in m)
        with open(os.path.join(L.STATIC, "i18n.js"), encoding="utf-8") as f:
            js = f.read()
        auto = re.search(r"AUTO_DETECT:(true|false)", js).group(1) == "true"
        self.assertEqual(auto, "navigator.language" in re.sub(r"/\*[\s\S]*?\*/", "", head),
                         "i18n.js 的 AUTO_DETECT 和 index.html 页头脚本按浏览器语言选语言的写法不一致")
        self.assertIn("READY:false" if not auto else "READY:", js)


class TestRealFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.R = L.analyze()

    def test_scripts_are_scanned_completely_and_balanced(self):
        for path in L.JS_FILES:
            sc = self.R.js[path]
            self.assertEqual(sc.errors, [], "%s 词法 / 括号有问题" % path)
        app = self.R.js["web/static/app.js"]
        self.assertGreater(len(app.toks), 50000)
        self.assertGreaterEqual(len(app.banners), 20)   # 横幅注释划分的区域
        # 汉字只应该出现在字符串 / 模板 / 注释 / 正则里; 少数对象的键写成了中文标识符 (数据键), 其余出现在这里就是扫描错位了
        cjk_code = [app.src[t.start:t.end] for t in app.toks if t.kind in ("ident", "punct", "num") and L.CJK_RE.search(app.src[t.start:t.end])]
        self.assertLess(len(cjk_code), 20, cjk_code)

    def test_dictionary_files_scanned_without_errors(self):
        self.assertEqual(self.R.dicts.errors, [])
        self.assertEqual(self.R.dicts.conflicts, [], "不同文件给同一个键写了不同的英文")
        self.assertGreaterEqual(len(self.R.dicts.files), len(L.DICT_NAMES))

    def test_every_banner_is_registered_with_a_dictionary(self):
        for path, sc in self.R.js.items():
            for _off, title in sc.banners:
                label, dic = L.area_of_title(title)
                self.assertIsNotNone(dic, "%s 里新增了横幅区域「%s」, 请在 tests/i18n_lint.py 的 AREAS 里登记它用哪个词典文件" % (path, title))
                self.assertIn(dic, L.DICT_NAMES)

    def test_dictionary_files_are_the_documented_ones(self):
        have = sorted(os.path.basename(p)[len("i18n.en."):-len(".js")] for p in L.dict_files())
        self.assertEqual(have, sorted(L.DICT_NAMES))

    def test_no_translation_name_is_shadowed_or_redeclared(self):
        problems = []
        for sc in self.R.js.values():
            for p, ln, name, bl in sc.shadows:
                problems.append("%s:%d 调用了 %s(), 但第 %d 行把 %s 声明成了变量 (会遮住翻译函数, 请把变量改名)" % (p, ln, name, bl, name))
            for p, ln, name in sc.clashes:
                problems.append("%s:%d 顶层声明了 %s, 和 i18n.js 的全局名字冲突" % (p, ln, name))
        self.assertEqual(problems, [])

    def test_allow_list_has_no_unused_entries(self):
        unused = [a for a in self.R.allow if not a["used"]]
        self.assertEqual([(a["file"], a["frag"]) for a in unused], [], "tests/i18n_allow.txt 里有没用上的条目, 请删掉")


class TestRatchet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.R = L.analyze()
        cls.base = L.load_baseline()

    def test_violations_do_not_exceed_baseline(self):
        over, _slack = L.compare_baseline(self.R, self.base)
        msg = "\n".join("  %s [%s] 现在 %d, 基线 %d" % x for x in over)
        self.assertEqual(over, [], "下面这些区域出现了新的未翻译文字 (含汉字又不是 t()/tn()/td()/tm()/tk() 的键; HTML 是没有英文词条的静态文字; "
                                   "CSS 是没有 :lang(en) 覆盖的 content)。用 python tests/i18n_lint.py --report --area 名称 看位置:\n" + msg)

    def test_baseline_is_tight(self):
        _over, slack = L.compare_baseline(self.R, self.base)
        msg = "\n".join("  %s [%s] 现在 %d, 基线 %d" % x for x in slack)
        self.assertEqual(slack, [], "下面这些区域的违规数比基线少了, 请运行 python tests/i18n_lint.py --update-baseline 把基线降下来 (棘轮只能往下走):\n" + msg)

    def test_baseline_file_is_well_formed(self):
        self.assertTrue(self.base)
        for path, areas in self.base.items():
            for area, n in areas.items():
                self.assertIsInstance(n, int, (path, area))
                self.assertGreaterEqual(n, 0, (path, area))


class TestDictionaries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.R = L.analyze()
        cls.D = cls.R.dicts

    def entries(self, lang="en"):
        table = self.D.en if lang == "en" else self.D.en_data
        for k, v in table.items():
            w = self.D.where.get((lang, k), [("?", 0, None)])[0]
            yield k, v, "%s:%d" % (w[0], w[1])

    def test_english_has_no_chinese(self):
        for lang in ("en", "enData"):
            for k, v, where in self.entries(lang):
                for s in (v if isinstance(v, list) else [v]):
                    self.assertIsNone(L.CJK_RE.search(s), "%s 「%s」的英文里有汉字: %s" % (where, k, s))

    def test_placeholders_and_html_tags_match_the_chinese(self):
        for k, v, where in self.entries("en"):
            zh = k[k.index("|") + 1:] if k in self._context_keys() else k  # 带语境的键 "语境|原文"
            for s in (v if isinstance(v, list) else [v]):
                self.assertEqual(L.placeholders(s), L.placeholders(zh), "%s 「%s」的占位符和中文不一致: %s" % (where, k, s))
                self.assertEqual(L.html_tags(s), L.html_tags(zh), "%s 「%s」的 HTML 标签和中文不一致: %s" % (where, k, s))

    def _context_keys(self):
        """带语境的键 "语境|原文": 词典本身分不出来, 看代码里有没有 t(原文, null, 语境) 这样用。"""
        return set(c.dict_key() for sc in self.R.js.values() for c in sc.calls if c.ctx)

    def test_plural_values_are_two_item_arrays_and_only_for_tn(self):
        used = L.used_keys(self.R)
        tn_keys = set(k for (kind, k) in used if kind == "n")
        t_keys = set(k for (kind, k) in used if kind == "t")
        self.assertEqual(sorted(tn_keys & t_keys), [], "同一个键既用在 t() 又用在 tn() 里")
        for k, v, where in self.entries("en"):
            if isinstance(v, list):
                self.assertEqual(len(v), 2, "%s 「%s」: 数量写法要 [单数, 复数] 两项" % (where, k))
                self.assertTrue(all(isinstance(x, str) for x in v))
                self.assertIn("{n}", k, "%s 「%s」: [单数, 复数] 只给 tn(\"… {n} …\", n) 用, 键里要有 {n}" % (where, k))
            if k in tn_keys:
                self.assertIsInstance(v, list, "%s 「%s」在代码里用 tn(), 英文要写成 [单数, 复数]" % (where, k))
            if k in t_keys:
                self.assertIsInstance(v, str, "%s 「%s」在代码里用 t(), 英文要写成一个字符串" % (where, k))

    def test_finished_areas_have_english_for_every_key(self):
        """基线为 0 的区域 = 已经转完: 里面 t() / tn() / tk() 用到的键必须在词典里都有英文。其余区域转换到一半, 缺英文只在 --missing 里列出。"""
        base = L.load_baseline()
        done = set(a for a, n in base.get("web/static/app.js", {}).items() if n == 0) | \
            set(a for a, n in base.get("web/static/i18n.js", {}).items() if n == 0)
        missing = ["%s:%d [%s] %s(%s)" % (c.path, c.line, c.area, c.name, json.dumps(key, ensure_ascii=False))
                   for c, kind, key in L.missing_translations(self.R) if c.area in done]
        self.assertEqual(missing, [], "这些已经转完的区域里用到的键在 web/static/i18n.en.*.js 里还没有英文:\n" + "\n".join(missing))

    def test_key_shapes(self):
        for (kind, key), calls in L.used_keys(self.R).items():
            c = calls[0]
            self.assertNotEqual(key.strip(), "", "%s:%d %s() 的键是空的" % (c.path, c.line, c.name))
            if kind == "n":
                self.assertIn("{n}", key, "%s:%d tn() 的键里要有 {n}: %s" % (c.path, c.line, key))
        for k, _v, where in self.entries("en"):
            self.assertNotEqual(k.strip(), "", where)


class TestCallSites(unittest.TestCase):
    def test_placeholders_match_the_arguments_passed(self):
        """t("… {名字}", {名字: 值}) 里键的占位符和传的参数一一对上 (传变量的不查); 对不上界面上会原样显示 {名字}。"""
        R = L.analyze()
        bad = ["%s:%d %s(%s) 没传 %s, 多传了 %s" % (c.path, c.line, c.name, json.dumps(c.key, ensure_ascii=False), lack, extra)
               for c, lack, extra in L.placeholder_mismatches(R)]
        self.assertEqual(bad, [])


class TestIndexHtml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8") as f:
            cls.html = f.read()

    def test_i18n_scripts_load_before_app_js_in_order(self):
        tags = re.findall(r'<script src="/static/([^"]+)"></script>', self.html)
        self.assertEqual(tags[0], "vendor/echarts.min.js")
        self.assertEqual(tags[-1], "app.js")
        self.assertEqual(tags[1], "i18n.js")
        dicts = tags[2:-1]
        self.assertEqual(dicts, ["i18n.en.%s.js" % n for n in L.DICT_NAMES])
        self.assertEqual(sorted(dicts), sorted(os.path.basename(p) for p in L.dict_files()))

    def test_language_switch_is_everywhere(self):
        self.assertEqual(self.html.count("data-theme-toggle"), 6)                        # 六个页面各一个「更多」菜单
        menu = self.html.count('data-lang-toggle><svg class="icon"><use href="#i-globe"/></svg>语言 / Language')
        self.assertEqual(menu, self.html.count("data-theme-toggle"))                     # 每个菜单里都有「语言 / Language」
        self.assertIn('id="langBtn" data-lang-toggle', self.html)                       # 侧栏底部的语言按钮
        self.assertIn('id="langAbbr"', self.html)
        self.assertLess(self.html.index('id="themeBtn"'), self.html.index('id="langBtn"'))
        self.assertLess(self.html.index('id="langBtn"'), self.html.index('id="railPin"'))

    def test_static_text_of_finished_html_areas_is_translated(self):
        R = L.analyze()
        base = L.load_baseline().get("web/index.html", {})
        finished = [a for a, n in base.items() if n == 0]
        self.assertIn("侧栏", finished)
        left = ["%s:%d [%s] %s" % (i.path, i.line, i.area, i.key[:50]) for i in R.html_missing if i.area in finished]
        self.assertEqual(left, [])

    def test_exports_carry_the_language_key(self):
        with open(os.path.join(ROOT, "llm_bench_pro", "server.py"), encoding="utf-8") as f:
            self.assertIn('"llm-bench-pro-lang"', f.read().split("EXPORT_LS_KEYS")[1][:400])


if __name__ == "__main__":
    unittest.main()
