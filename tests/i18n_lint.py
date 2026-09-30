# -*- coding: utf-8 -*-
"""界面文字与翻译的检查工具 (纯标准库, 兼容 Python 3.8)。

它做三件事:
  1. 用一个只认「字符串、模板字符串、注释、正则字面量」的 JS 词法扫描器扫 web/static/*.js:
     字符串 / 模板字符串的静态文字里出现汉字 (含中文标点), 除非它就是 t( / tn( / td( / tm( / tk( 调用的
     第一个参数 (词典的键), 就算「违规」= 还没翻译。注释和正则字面量里的汉字不算。
  2. 扫 web/index.html 的静态文字 (文本节点和 title / placeholder / aria-label / alt 属性): 中文原文
     在词典里没有英文, 就算违规。
  3. 扫 web/static/app.css 里 content:"中文" (伪元素生成的文字): 没有对应的 html:lang(en) 覆盖规则就算违规。
  4. 按「区域」(app.js 里 /* ==== 标题 ==== */ 横幅注释块, index.html 里 <!-- ==== 标题 ==== --> 注释) 汇总,
     和 tests/i18n_baseline.json 里每个区域「允许的违规数」比较 (棘轮: 只能减少, 不能增加)。

命令行 (在仓库根目录运行):
  python tests/i18n_lint.py --report              打印汇总和全部明细
  python tests/i18n_lint.py --summary             只打印按区域的汇总
  python tests/i18n_lint.py --report --area 任务集   只看名称含「任务集」的区域
  python tests/i18n_lint.py --check               和基线比较, 超出基线或基线过松时退出码为 1
  python tests/i18n_lint.py --update-baseline     把现在的数量写进基线 (只允许减少, 要增加加 --allow-increase)
  python tests/i18n_lint.py --missing             已经转成 t() 的键里, 词典里还没有英文的 (所有区域)
  python tests/i18n_lint.py --unused              词典里有、代码里没用到的条目
"""
import argparse
import bisect
import io
import json
import os
import re
import sys
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATIC = os.path.join(ROOT, "web", "static")

# 要扫的脚本和页面 (相对仓库根); 词典文件 web/static/i18n.en.*.js 本身不扫
JS_FILES = ["web/static/app.js", "web/static/i18n.js"]
HTML_FILES = ["web/index.html"]
CSS_FILES = ["web/static/app.css"]
ALLOW_FILE = os.path.join(HERE, "i18n_allow.txt")
BASELINE_FILE = os.path.join(HERE, "i18n_baseline.json")

# 翻译函数: t 普通句子 · tn 带数量 · td 数据里的中文名 · tm 服务端返回的提示 · tk 只做标记(常量里的中文, 用的时候再 t(x))
CALLS = ("t", "tn", "td", "tm", "tk")
# 这些名字是 i18n.js 的全局名字, app.js 里不能再声明同名的变量 / 函数
RESERVED = frozenset(CALLS + ("I18N", "applyStaticI18n"))

# 汉字和中文标点 (、。「」《》（），：；！？等全角符号), 含义和 web/static/i18n.js 里的一致
CJK_RE = re.compile(u"[\u3400-\u4dbf\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")

# 区域 → 词典文件。键是横幅标题的开头; 新加了横幅但没登记, 测试会提醒
AREAS = [
    # (横幅标题的开头, 区域名, 词典文件 i18n.en.<名>.js)
    ("基础工具", "基础工具", "common"),
    ("名词解释", "名词解释", "glossary"),
    ("主题", "主题", "common"),
    ("界面语言", "界面语言", "common"),
    ("导航 / 抽屉 / 弹窗", "导航 / 抽屉 / 弹窗 / 通用点击", "common"),
    ("自定义下拉", "自定义下拉", "common"),
    ("运行日志", "运行日志 + 状态轮询", "common"),
    ("图表层", "图表层", "common"),
    ("页面积木", "页面积木", "common"),
    ("多表格系统", "多表格系统", "common"),
    ("速度测试: 新建", "速度测试: 新建 / 列表 / 指标", "perf"),
    ("速度测试: 结果页", "速度测试: 结果页", "perf"),
    ("速度对比", "速度对比", "cmp"),
    ("能力测试", "能力测试", "iq"),
    ("代码生成", "代码生成", "gen"),
    ("作品列表", "代码生成: 作品列表", "gen"),
    ("任务集", "任务集", "tasks"),
    ("删除", "删除", "common"),
    ("模型管理", "模型管理", "models"),
    ("样式自检", "样式自检", "common"),
    ("导出报告", "导出报告 / 打开离线报告", "common"),
    ("启动", "启动", "common"),
]
DICT_NAMES = ("common", "html", "perf", "cmp", "iq", "gen", "tasks", "models", "glossary", "server")
START_AREA = "(文件开头)"


# ================================================================ 词法扫描

class Tok(object):
    """kind: comment ident num str regex punct tmpl tmpl_head tmpl_mid tmpl_tail
    tmpl* 是模板字符串的几段: `abc` 整个是 tmpl; `a${ 是 tmpl_head, }b${ 是 tmpl_mid, }c` 是 tmpl_tail;
    同一个模板的几段 tid 相同。value 是 str / tmpl* 还原转义后的文字。"""
    __slots__ = ("kind", "start", "end", "value", "tid")

    def __init__(self, kind, start, end, value=None, tid=0):
        self.kind, self.start, self.end, self.value, self.tid = kind, start, end, value, tid

    def __repr__(self):
        return "Tok(%s, %d-%d, %r)" % (self.kind, self.start, self.end, self.value)


_WS = re.compile(u"[ \t\v\f\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000\ufeff\n\r\u2028\u2029]+")
_LINE_END = re.compile(u"[\n\r\u2028\u2029]")
_IDENT = re.compile(u"(?:[A-Za-z_$]|(?![\\s\ufeff])[^\\x00-\\x7f])(?:[A-Za-z0-9_$]|(?![\\s\ufeff])[^\\x00-\\x7f])*")
_NUM = re.compile(r"0[xX][0-9a-fA-F_]+n?|0[bB][01_]+n?|0[oO][0-7_]+n?"
                  r"|(?:\d[\d_]*\.?[\d_]*|\.\d[\d_]*)(?:[eE][+-]?\d[\d_]*)?n?")
_PUNCT = re.compile(r">>>=|\.\.\.|===|!==|\*\*=|<<=|>>=|>>>|&&=|\|\|=|\?\?=|=>|==|!=|<=|>=|&&|\|\||\?\?|\?\.(?!\d)"
                    r"|\+\+|--|\+=|-=|\*=|/=|%=|&=|\|=|\^=|<<|>>|\*\*|[{}()\[\];,<>+\-*/%&|^!~?:=.@#]")
_STR_DQ = re.compile(r'"(?:[^"\\\n\r]|\\(?:\r\n|[\s\S]))*"')
_STR_SQ = re.compile(r"'(?:[^'\\\n\r]|\\(?:\r\n|[\s\S]))*'")
_TMPL_CHUNK = re.compile(r"(?:[^`\\$]|\\[\s\S]|\$(?!\{))*")
_ESC = re.compile(r"\\(?:u\{([0-9a-fA-F]+)\}|u([0-9a-fA-F]{4})|x([0-9a-fA-F]{2})|(\r\n|[\s\S]))")
_SIMPLE_ESC = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
# 这些词后面出现的 / 是正则的开头 (不是除号)
_REGEX_KW = frozenset(["return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw",
                       "case", "do", "else", "yield", "await", "extends"])


def cook(body):
    """字符串 / 模板里的转义还原成真正的文字: \\n \\uXXXX \\u{...} \\xHH \\' 行尾的续行等。"""
    def rep(m):
        if m.group(1):
            return chr(int(m.group(1), 16))
        if m.group(2):
            return chr(int(m.group(2), 16))
        if m.group(3):
            return chr(int(m.group(3), 16))
        ch = m.group(4)
        if ch in ("\n", "\r\n", "\r", u"\u2028", u"\u2029"):
            return ""
        return _SIMPLE_ESC.get(ch, ch)
    s = _ESC.sub(rep, body) if "\\" in body else body
    if any(0xD800 <= ord(c) <= 0xDFFF for c in s):  # \ud83d\ude00 这样的代理对拼回一个字符
        s = s.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")
    return s


def _regex_allowed(src, last, i):
    """i 处的 / 是正则的开头还是除号: 看前一个记号 (前面是「值」就是除号)。"""
    if last is None:
        return True
    k = last.kind
    if k in ("tmpl_head", "tmpl_mid"):
        return True
    if k in ("num", "str", "regex", "tmpl", "tmpl_tail"):
        return False
    text = src[last.start:last.end]
    if k == "ident":
        return text in _REGEX_KW
    if k == "punct":
        if text in (")", "]", "++", "--"):
            return False
        if text == "}":  # 花括号后面换了行: 当作新语句的开头
            return "\n" in src[last.end:i]
        return True
    return True


def _scan_regex(src, i, n):
    """从 i (指向开头的 /) 扫到正则结束 (含标志位), 返回结束位置; 不是正则返回 -1。字符组 [...] 里的 / 不算结束。"""
    j = i + 1
    in_class = False
    while j < n:
        c = src[j]
        if c == "\\":
            j += 2
            continue
        if c in "\n\r\u2028\u2029":
            return -1
        if in_class:
            if c == "]":
                in_class = False
        elif c == "[":
            in_class = True
        elif c == "/":
            j += 1
            while j < n and (src[j].isalnum() or src[j] in "_$"):
                j += 1
            return j
        j += 1
    return -1


def tokenize(src):
    """返回 (记号列表(含注释, 不含空白), 错误列表[(偏移, 说明)])。"""
    n = len(src)
    toks, errors = [], []
    stack = []  # "{" 普通花括号; 整数 = 模板字符串里 ${ 的模板编号
    tid = 0
    last = None
    i = 0
    while i < n:
        m = _WS.match(src, i)
        if m:
            i = m.end()
            continue
        c = src[i]
        tok = None
        if c == "/":
            nx = src[i + 1:i + 2]
            if nx == "/":
                m = _LINE_END.search(src, i)
                j = m.start() if m else n
                toks.append(Tok("comment", i, j))
                i = j
                continue
            if nx == "*":
                j = src.find("*/", i + 2)
                if j < 0:
                    errors.append((i, "块注释没有结束"))
                    j = n
                else:
                    j += 2
                toks.append(Tok("comment", i, j))
                i = j
                continue
            if _regex_allowed(src, last, i):
                j = _scan_regex(src, i, n)
                if j > 0:
                    tok = Tok("regex", i, j)
        elif c == '"' or c == "'":
            m = (_STR_DQ if c == '"' else _STR_SQ).match(src, i)
            if m:
                tok = Tok("str", i, m.end(), cook(src[i + 1:m.end() - 1]))
            else:
                errors.append((i, "字符串没有结束"))
                m = _LINE_END.search(src, i)
                j = m.start() if m else n
                tok = Tok("str", i, j, src[i + 1:j])
        elif c == "`" or (c == "}" and stack and stack[-1] != "{"):
            if c == "`":
                tid += 1
                cur, head = tid, True
            else:
                cur, head = stack.pop(), False
            j = _TMPL_CHUNK.match(src, i + 1).end()
            value = cook(src[i + 1:j])
            if j < n and src[j] == "`":
                tok = Tok("tmpl" if head else "tmpl_tail", i, j + 1, value, cur)
            elif j < n and src[j] == "$":
                tok = Tok("tmpl_head" if head else "tmpl_mid", i, j + 2, value, cur)
                stack.append(cur)
            else:
                errors.append((i, "模板字符串没有结束"))
                tok = Tok("tmpl" if head else "tmpl_tail", i, n, value, cur)
        if tok is None:
            if c == "{":
                stack.append("{")
            elif c == "}":
                if stack and stack[-1] == "{":
                    stack.pop()
                else:
                    errors.append((i, "多出来的 }"))
            if c.isdigit() or (c == "." and src[i + 1:i + 2].isdigit()):
                m = _NUM.match(src, i)
                tok = Tok("num", i, m.end())
            elif _IDENT.match(src, i):
                m = _IDENT.match(src, i)
                tok = Tok("ident", i, m.end())
            else:
                m = _PUNCT.match(src, i)
                if m:
                    tok = Tok("punct", i, m.end())
                else:  # 认不出的字符 (比如没被字符串包住的 \\): 当作一个符号, 由括号检查等去发现问题
                    tok = Tok("punct", i, i + 1)
                    errors.append((i, "认不出的字符 %r" % c))
        toks.append(tok)
        last = tok
        i = tok.end
    if stack:
        errors.append((n, "文件结束时还有 %d 个没闭合的 { 或 ${" % len(stack)))
    return toks, errors


def check_brackets(src, toks):
    """括号 ( ) [ ] { } 和模板里的 ${ } 配对检查: 词法扫描错位 (比如把正则当成除号) 几乎都会在这里现形。"""
    errors, stack = [], []
    pairs = {")": "(", "]": "[", "}": "{"}
    for t in toks:
        k = t.kind
        if k == "punct":
            x = src[t.start:t.end]
            if x in ("(", "[", "{"):
                stack.append((x, t.start))
            elif x in pairs:
                if not stack or stack[-1][0] != pairs[x]:
                    errors.append((t.start, "括号 %s 对不上" % x))
                else:
                    stack.pop()
        elif k == "tmpl_head":
            stack.append(("${", t.start))
        elif k == "tmpl_mid":
            if not stack or stack[-1][0] != "${":
                errors.append((t.start, "模板里的 } 对不上"))
            else:
                stack.pop()
            stack.append(("${", t.start))
        elif k == "tmpl_tail":
            if not stack or stack[-1][0] != "${":
                errors.append((t.start, "模板里的 } 对不上"))
            else:
                stack.pop()
    for x, at in stack:
        errors.append((at, "括号 %s 没有闭合" % x))
    return errors


# ================================================================ 单个 JS 文件的分析

class Violation(object):
    __slots__ = ("path", "line", "col", "area", "kind", "text", "src_line", "reason")

    def __init__(self, path, line, col, area, kind, text, src_line, reason=""):
        self.path, self.line, self.col, self.area, self.kind = path, line, col, area, kind
        self.text, self.src_line, self.reason = text, src_line, reason

    def where(self):
        return "%s:%d:%d" % (self.path, self.line, self.col)


class Call(object):
    __slots__ = ("path", "line", "name", "key", "ctx", "area", "dynamic", "params")

    def __init__(self, path, line, name, key, ctx, area, dynamic, params=None):
        self.path, self.line, self.name, self.key, self.ctx, self.area, self.dynamic = path, line, name, key, ctx, area, dynamic
        self.params = params  # 占位符参数对象里的键 (set); 没传参数是空集; 传的不是字面量对象 (变量、展开 ...) 是 None, 不检查

    def dict_key(self):
        return (self.ctx + "|" + self.key) if self.ctx else self.key


def banner_title(comment_text):
    """/* ====… 标题 ====… */ 这种横幅注释的标题 (第一行有意义的文字); 不是横幅返回 None。"""
    body = comment_text[2:-2] if comment_text.endswith("*/") else comment_text[2:]
    lines = [ln.strip() for ln in body.splitlines()]
    if not lines or not re.match(r"^={5,}$", lines[0].replace(" ", "")):
        return None
    for ln in lines[1:]:
        if ln and not re.match(r"^=+$", ln.replace(" ", "")):
            return ln
    return None


def area_of_title(title):
    """横幅标题 → (区域名, 词典文件); 没登记的 (None 词典) 由测试报错。"""
    for prefix, label, dic in AREAS:
        if title.startswith(prefix):
            return label, dic
    return re.split(u"[(\uff08]", title)[0].strip(), None


class Scan(object):
    """一个 JS 文件的扫描结果。"""

    def __init__(self, path, src):
        self.path, self.src = path, src
        self.toks, self.errors = tokenize(src)
        self.errors = self.errors + check_brackets(src, self.toks)
        self._nl = [m.start() for m in re.finditer("\n", src)]
        self.sig = [t for t in self.toks if t.kind != "comment"]
        self.texts = [src[t.start:t.end] for t in self.sig]
        self.banners = []  # [(偏移, 标题)]
        for t in self.toks:
            if t.kind == "comment" and src.startswith("/*", t.start):
                title = banner_title(src[t.start:t.end])
                if title:
                    self.banners.append((t.start, title))
        self._banner_at = [b[0] for b in self.banners]
        self.violations, self.calls, self.shadows, self.clashes = [], [], [], []
        self._analyze()

    # ---- 位置
    def line_col(self, off):
        line = bisect.bisect_right(self._nl, off - 1) + 1
        start = self._nl[line - 2] + 1 if line > 1 else 0
        return line, off - start + 1

    def src_line(self, off):
        line, _ = self.line_col(off)
        a = self._nl[line - 2] + 1 if line > 1 else 0
        b = self._nl[line - 1] if line - 1 < len(self._nl) else len(self.src)
        return self.src[a:b]

    def area(self, off):
        i = bisect.bisect_right(self._banner_at, off) - 1
        if i < 0:
            return START_AREA if self.path.endswith("app.js") else os.path.basename(self.path)
        return area_of_title(self.banners[i][1])[0]

    # ---- 分析
    def _analyze(self):
        sig, texts, n = self.sig, self.texts, len(self.sig)
        exempt = set()  # 是词典的键 (t( 的第一个参数) 的记号下标
        # 括号配对 / 父括号 (模板里的 ${ } 也算一层)
        match, parent, stack = [-1] * n, [-1] * n, []
        for i, t in enumerate(sig):
            k, x = t.kind, texts[i]
            closer = (k == "punct" and x in (")", "]", "}")) or k in ("tmpl_mid", "tmpl_tail")
            if closer and stack:
                o = stack.pop()
                match[o], match[i] = i, o
            parent[i] = stack[-1] if stack else -1
            if (k == "punct" and x in ("(", "[", "{")) or k in ("tmpl_head", "tmpl_mid"):
                stack.append(i)
        self._match, self._parent = match, parent

        # ---- 翻译函数的调用
        for i in range(n - 2):
            if sig[i].kind != "ident" or texts[i] not in CALLS or texts[i + 1] != "(":
                continue
            prev = texts[i - 1] if i else ""
            if prev in ("function", "?.") or (prev == "." and not (i >= 2 and texts[i - 2] == "I18N")):
                continue
            j = i + 2
            f = sig[j]
            line = self.line_col(sig[i].start)[0]
            area = self.area(sig[i].start)
            if f.kind in ("str", "tmpl") and texts[j + 1] in (",", ")"):
                ctx = None
                if texts[i] == "t":  # t("更好", null, "对比"): 第三个参数是语境
                    args = self._split_args(i + 1)
                    if len(args) >= 3 and args[2][1] - args[2][0] == 1 and sig[args[2][0]].kind == "str":
                        ctx = sig[args[2][0]].value
                        exempt.add(args[2][0])  # 语境也是词典键的一部分, 可以写中文
                exempt.add(j)
                args = self._split_args(i + 1)
                pi = 1 if texts[i] == "t" else 2 if texts[i] == "tn" else None  # 占位符参数是第几个参数
                params = set() if pi is None or len(args) <= pi else self._object_keys(args[pi])
                self.calls.append(Call(self.path, line, texts[i], f.value, ctx, area, False, params))
            else:
                self.calls.append(Call(self.path, line, texts[i], None, None, area, True))

        # ---- 违规: 含汉字的字符串 / 模板字符串
        seen_tid = set()
        segs_by_tid = {}  # 同一个模板 (含中间夹着的别的模板) 的几段静态文字, 靠 tid 区分
        for u in sig:
            if u.kind.startswith("tmpl"):
                segs_by_tid.setdefault(u.tid, []).append(u.value)
        for j, t in enumerate(sig):
            if t.kind == "str":
                if j in exempt or not CJK_RE.search(t.value):
                    continue
                self._add_violation(t, "str", t.value, "")
            elif t.kind in ("tmpl", "tmpl_head"):
                if t.kind == "tmpl" and j in exempt:
                    continue
                if t.tid in seen_tid:
                    continue
                seen_tid.add(t.tid)
                segs = segs_by_tid[t.tid]
                if not any(CJK_RE.search(s) for s in segs):
                    continue
                reason = ""
                if t.kind == "tmpl_head" and j >= 2 and texts[j - 1] == "(" and texts[j - 2] in CALLS:
                    reason = "t() 的键不能带 ${}: 把要翻译的文字拆成 ${t(\"…\")} 片段, 或改用 {占位符}"
                self._add_violation(t, "tmpl", "${…}".join(segs), reason)
        self.violations.sort(key=lambda v: (v.line, v.col))

        self._find_shadows()

    def _add_violation(self, tok, kind, text, reason):
        line, col = self.line_col(tok.start)
        self.violations.append(Violation(self.path, line, col, self.area(tok.start), kind, text,
                                         self.src_line(tok.start), reason))

    def _object_keys(self, arg):
        """一个参数 [起, 止) 如果是字面量对象 {a, b: 1, "c": 2}, 返回它的键 (set); null / undefined 当没传; 别的写法 (变量、展开、计算键) 返回 None。"""
        sig, texts = self.sig, self.texts
        a, b = arg
        if b - a == 1 and texts[a] in ("null", "undefined"):
            return set()
        if texts[a] != "{" or self._match[a] != b - 1:
            return None
        keys, k = set(), a + 1
        while k < b - 1:
            t0 = sig[k]
            if t0.kind == "ident" and (texts[k + 1] in (",", "}") or texts[k + 1] == ":"):
                keys.add(texts[k])
            elif t0.kind == "str" and texts[k + 1] == ":":
                keys.add(t0.value)
            else:
                return None  # 展开、计算键、方法简写 ...
            depth = 0  # 跳到这一项的结尾 (下一个 depth 0 的逗号)
            while k < b - 1:
                x, kd = texts[k], sig[k].kind
                if (kd == "punct" and x in ("(", "[", "{")) or kd == "tmpl_head":
                    depth += 1
                elif (kd == "punct" and x in (")", "]", "}")) or kd == "tmpl_tail":
                    depth -= 1
                elif x == "," and kd == "punct" and depth == 0:
                    break
                k += 1
            k += 1
        return keys

    def _split_args(self, open_idx):
        """open_idx 是调用的 (, 返回每个参数的 [起, 止) 记号下标。"""
        sig, texts = self.sig, self.texts
        close = self._match[open_idx]
        args, start, depth = [], open_idx + 1, 0
        end = close if close > 0 else len(sig)
        for k in range(open_idx + 1, end):
            x, kd = texts[k], sig[k].kind
            if (kd == "punct" and x in ("(", "[", "{")) or kd == "tmpl_head":
                depth += 1
            elif (kd == "punct" and x in (")", "]", "}")) or kd == "tmpl_tail":
                depth -= 1
            elif x == "," and kd == "punct" and depth == 0:
                args.append((start, k))
                start = k + 1
        if start < end:
            args.append((start, end))
        return args

    # ---- 变量名遮住翻译函数
    def _is_param_list(self, o):
        sig, texts, match = self.sig, self.texts, self._match
        c = match[o]
        if c < 0:
            return False
        nxt = texts[c + 1] if c + 1 < len(sig) else ""
        before = texts[o - 1] if o else ""
        if nxt == "=>":
            return True
        if nxt == "{":
            if before in ("function", "catch"):
                return True
            if before in ("if", "for", "while", "switch", "with", "else", "return", "do"):
                return False
            return o > 0 and sig[o - 1].kind == "ident"
        return False

    def _in_binding_pattern(self, p):
        """p 是某个标识符的父括号下标: 它是不是在参数列表 / const {…} 这样的解构声明里。"""
        texts, parent = self.texts, self._parent
        q = p
        while q >= 0 and texts[q] in ("[", "{"):
            if q > 0 and texts[q - 1] in ("const", "let", "var"):
                return True
            q = parent[q]
        return q >= 0 and texts[q] == "(" and self._is_param_list(q)

    def _bindings(self, names):
        """代码里把 names 里的名字声明成变量 / 参数的位置 (下标)。宁可多报: 只在同一条顶层语句里还调用了翻译函数时才算问题。"""
        sig, texts, parent, match = self.sig, self.texts, self._parent, self._match
        n, out = len(sig), []
        for i in range(n):
            if sig[i].kind != "ident" or texts[i] not in names:
                continue
            prev = texts[i - 1] if i else ""
            nxt = texts[i + 1] if i + 1 < n else ""
            if prev in (".", "?."):
                continue
            if prev in ("const", "let", "var", "function", "class") or nxt == "=>":
                out.append(i)
                continue
            p = parent[i]
            if p >= 0 and prev in ("(", ",", "[", "{", "...", ":") and nxt in (",", ")", "]", "}", "="):
                if self._in_binding_pattern(p):
                    out.append(i)
        # const a=1, t=2 这种逗号连着的声明
        stops = ("const", "let", "var", "function", "if", "for", "while", "return", "switch", "try", "throw", "class")
        for k in range(n):
            if texts[k] not in ("const", "let", "var") or sig[k].kind != "ident":
                continue
            p = parent[k]
            end = match[p] if p >= 0 and match[p] > 0 else n
            for j in range(k + 1, end):
                if parent[j] != p:
                    continue
                if texts[j] == ";" or (texts[j] in stops and texts[j - 1] != ","):
                    break
                if sig[j].kind == "ident" and texts[j] in names and texts[j - 1] == "," and \
                        j + 1 < n and texts[j + 1] in ("=", ",", ";"):
                    out.append(j)
        return sorted(set(out))

    def _find_shadows(self):
        """1) 顶层声明了 t / tn / td / tm / tk / I18N 同名的变量 (会和 i18n.js 冲突);
        2) 同一条顶层语句 (一个函数 / 一个常量) 里, 既有 t("…") 这样的翻译调用, 又把 t 声明成了局部变量 / 参数。"""
        sig, texts, parent = self.sig, self.texts, self._parent
        n = len(sig)
        starts = []
        for i in range(n):
            if parent[i] != -1:
                continue
            at = sig[i].start
            if (at == 0 or self.src[at - 1] in "\n\r") and (i == 0 or texts[i - 1] in (";", "}")):
                starts.append(i)
        if not starts or starts[0] != 0:
            starts.insert(0, 0)
        bind = self._bindings(RESERVED)
        if os.path.basename(self.path) != "i18n.js":  # i18n.js 自己就是定义这些全局名字的地方
            for b in bind:  # 顶层声明
                if parent[b] == -1 and b > 0 and texts[b - 1] in ("const", "let", "var", "function", "class"):
                    line = self.line_col(sig[b].start)[0]
                    self.clashes.append((self.path, line, texts[b]))
        calls = []  # 翻译函数的调用 (第一个参数是字符串或模板): (下标, 名字)
        for i in range(n - 2):
            if sig[i].kind == "ident" and texts[i] in CALLS and texts[i + 1] == "(" and \
                    sig[i + 2].kind in ("str", "tmpl", "tmpl_head") and (i == 0 or texts[i - 1] not in (".", "?.", "function")):
                calls.append(i)
        by_stmt = {}
        for b in bind:
            if texts[b] not in CALLS:
                continue
            by_stmt.setdefault(bisect.bisect_right(starts, b) - 1, ([], []))[0].append(b)
        for c in calls:
            s = bisect.bisect_right(starts, c) - 1
            if s in by_stmt:
                by_stmt[s][1].append(c)
        for s, (bs, cs) in sorted(by_stmt.items()):
            for c in cs:
                name = texts[c]
                same = [b for b in bs if texts[b] == name]
                if same:
                    self.shadows.append((self.path, self.line_col(sig[c].start)[0], name,
                                         self.line_col(sig[same[0]].start)[0]))


# ================================================================ 词典

class Dictionaries(object):
    """web/static/i18n.en.*.js 里 I18N.add / I18N.addPattern 写的内容 (静态解析, 不执行 JS)。"""

    def __init__(self):
        self.en, self.en_data = {}, {}
        self.patterns = []   # (文件, 行, 正则源码, 替换)
        self.where = {}      # (语言, 键) → [(文件名, 行, 值)]
        self.errors = []     # (文件, 行, 说明)
        self.conflicts = []  # (语言, 键, [(文件, 值)...]): 不同文件给同一个键写了不同的值
        self.files = []

    def keys_of(self, lang):
        return self.en if lang == "en" else self.en_data


class _ParseError(Exception):
    def __init__(self, line, msg):
        Exception.__init__(self, msg)
        self.line, self.msg = line, msg


def dict_files():
    out = []
    if os.path.isdir(STATIC):
        for name in sorted(os.listdir(STATIC)):
            if re.match(r"^i18n\.en\.[A-Za-z0-9_-]+\.js$", name):
                out.append(os.path.join(STATIC, name))
    return out


def parse_dictionary(path, src, D):
    """把一个词典文件的内容并进 D。文件里只允许 I18N.add("en"|"enData", {键: 值, ...}); 和 I18N.addPattern([/正则/, "替换"], ...);"""
    fname = os.path.basename(path)
    scan = Scan(fname, src)
    for off, msg in scan.errors:
        D.errors.append((fname, scan.line_col(off)[0], "词法错误: " + msg))
    sig, texts = scan.sig, scan.texts
    n = len(sig)
    pos = [0]

    def cur():
        return texts[pos[0]] if pos[0] < n else ""

    def line():
        return scan.line_col(sig[min(pos[0], n - 1)].start)[0] if n else 1

    def expect(x):
        if cur() != x:
            raise _ParseError(line(), "这里应该是 %s, 实际是 %s" % (x, cur() or "文件结束"))
        pos[0] += 1

    def string():
        """一个字符串 (可以用 + 连接几段, 长句拆行时用)。"""
        if pos[0] >= n or sig[pos[0]].kind not in ("str", "tmpl"):
            raise _ParseError(line(), "这里应该是一个字符串")
        parts = [sig[pos[0]].value]
        pos[0] += 1
        while cur() == "+" and pos[0] + 1 < n and sig[pos[0] + 1].kind in ("str", "tmpl"):
            parts.append(sig[pos[0] + 1].value)
            pos[0] += 2
        return "".join(parts)

    def value():
        if cur() == "[":
            pos[0] += 1
            items = []
            while cur() != "]":
                items.append(string())
                if cur() == ",":
                    pos[0] += 1
                elif cur() != "]":
                    raise _ParseError(line(), "数组里应该是逗号或 ]")
            pos[0] += 1
            return items
        return string()

    def statement():
        expect("I18N")
        expect(".")
        fn = cur()
        pos[0] += 1
        expect("(")
        if fn == "add":
            lang = string()
            if lang not in ("en", "enData"):
                raise _ParseError(line(), "I18N.add 的语言只能是 \"en\" 或 \"enData\"")
            expect(",")
            expect("{")
            seen = {}
            while cur() != "}":
                ln = line()
                key = string()
                expect(":")
                val = value()
                if key in seen:
                    D.errors.append((fname, ln, "同一个 I18N.add 里键重复了: %s" % key[:40]))
                seen[key] = val
                D.where.setdefault((lang, key), []).append((fname, ln, val))
                target = D.keys_of(lang)
                if key in target and target[key] != val:
                    D.conflicts.append((lang, key, [(f, v) for f, _l, v in D.where[(lang, key)]]))
                target[key] = val
                if cur() == ",":
                    pos[0] += 1
                elif cur() != "}":
                    raise _ParseError(line(), "键值之间应该是逗号或 }")
            pos[0] += 1
        elif fn == "addPattern":
            while cur() != ")":
                ln = line()
                expect("[")
                if pos[0] >= n or sig[pos[0]].kind != "regex":
                    raise _ParseError(line(), "模式的第一项应该是正则字面量 /…/")
                rx = texts[pos[0]]
                pos[0] += 1
                expect(",")
                if sig[pos[0]].kind in ("str", "tmpl"):
                    repl = string()
                else:  # 函数: 跳到这一项的结尾
                    depth, start = 0, pos[0]
                    while pos[0] < n and not (cur() == "]" and depth == 0):
                        if cur() in ("(", "[", "{"):
                            depth += 1
                        elif cur() in (")", "]", "}"):
                            depth -= 1
                        pos[0] += 1
                    repl = "<函数>"
                    if pos[0] == start:
                        raise _ParseError(line(), "模式的第二项是空的")
                expect("]")
                D.patterns.append((fname, ln, rx, repl))
                if cur() == ",":
                    pos[0] += 1
                elif cur() != ")":
                    raise _ParseError(line(), "模式之间应该是逗号或 )")
        else:
            raise _ParseError(line(), "只允许 I18N.add(...) 和 I18N.addPattern(...), 这里是 I18N.%s" % fn)
        expect(")")
        if cur() == ";":
            pos[0] += 1

    while pos[0] < n:
        start = pos[0]
        try:
            statement()
        except _ParseError as e:
            D.errors.append((fname, e.line, e.msg))
            pos[0] = max(pos[0], start + 1)
            while pos[0] < n and cur() != ";" and texts[pos[0]] != "I18N":  # 跳到下一条语句
                pos[0] += 1
            if cur() == ";":
                pos[0] += 1
    D.files.append(fname)


def load_dictionaries(paths=None):
    D = Dictionaries()
    for p in (paths if paths is not None else dict_files()):
        with io.open(p, encoding="utf-8") as f:
            parse_dictionary(p, f.read(), D)
    return D


# 占位符 {名字} 和 HTML 标签: 中英文必须一致 (与 i18n.js 里的规则相同)
PH_RE = re.compile(u"\\{\\{|\\}\\}|\\{([A-Za-z_\u4e00-\u9fff][\\w\u4e00-\u9fff]*)\\}")
TAG_RE = re.compile(r"</?[A-Za-z][^<>]*>")


def placeholders(s):
    return sorted(m.group(1) for m in PH_RE.finditer(s) if m.group(1))


def html_tags(s):
    return sorted(re.sub(r"\s+", " ", m.group(0)) for m in TAG_RE.finditer(s))


def norm_key(s):
    """静态 HTML 里的键: 首尾空白去掉, 中间连续的空白 (含换行缩进) 合成一个空格; 与 i18n.js 的 normKey 一致。"""
    return re.sub(r"\s+", " ", s).strip()


# ================================================================ 允许清单

def load_allow(path=ALLOW_FILE):
    """每行 `文件: 内容片段`; 文件里那一行源码 (违规文字所在的行) 含这个片段就算允许。# 开头是注释。"""
    out = []
    if not os.path.exists(path):
        return out
    with io.open(path, encoding="utf-8") as f:
        for n, raw in enumerate(f, 1):
            s = raw.rstrip("\r\n")
            if not s.strip() or s.lstrip().startswith("#"):
                continue
            if ":" not in s:
                raise ValueError("%s 第 %d 行格式不对, 应该是「文件: 内容片段」" % (path, n))
            fn, frag = s.split(":", 1)
            out.append({"file": fn.strip(), "frag": frag.strip(), "line": n, "used": 0})
    return out


def _allowed(allow, path, src_line):
    for a in allow:
        if a["file"] == path and a["frag"] and a["frag"] in src_line:
            a["used"] += 1
            return True
    return False


# ================================================================ index.html 静态文字

HTML_ATTRS = ("title", "placeholder", "aria-label", "alt")
_VOID = frozenset(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"])
_SKIP_TAGS = frozenset(["script", "style", "svg", "textarea", "noscript", "template"])


class HtmlItem(object):
    __slots__ = ("path", "line", "col", "area", "kind", "key", "src_line")

    def __init__(self, path, line, col, area, kind, key, src_line):
        self.path, self.line, self.col, self.area, self.kind, self.key, self.src_line = path, line, col, area, kind, key, src_line


class _HtmlScan(HTMLParser):
    def __init__(self, path, src):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.path, self.src = path, src
        self._nl = [m.start() for m in re.finditer("\n", src)]
        self.items = []
        self.area = "(页面开头)"
        self.stack = []  # {"tag", "skip", "whole", "from"}
        self.banners = []

    def _off(self):
        line, col = self.getpos()
        return (self._nl[line - 2] + 1 if line > 1 else 0) + col

    def _line_src(self, line):
        a = self._nl[line - 2] + 1 if line > 1 else 0
        b = self._nl[line - 1] if line - 1 < len(self._nl) else len(self.src)
        return self.src[a:b]

    def _skipping(self):
        return any(e["skip"] for e in self.stack)

    def _whole(self):
        return any(e["whole"] for e in self.stack)

    def handle_comment(self, data):
        m = re.match(r"^\s*={5,}\s*(.*?)\s*={5,}\s*$", data)
        if m and m.group(1):
            title = m.group(1)
            self.area = re.split(u"[(\uff08]", title)[0].strip()
            self.banners.append(self.area)

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        line, col = self.getpos()
        skip = tag in _SKIP_TAGS or d.get("translate") == "no" or "data-i18n-skip" in d
        if not self._skipping():
            if not self._whole():
                for a in HTML_ATTRS:
                    v = d.get(a)
                    if v and CJK_RE.search(v):
                        self.items.append(HtmlItem(self.path, line, col, self.area, "attr:" + a, norm_key(v), self._line_src(line)))
        if tag in _VOID:
            return
        whole = "data-i18n-html" in d
        self.stack.append({"tag": tag, "skip": skip, "whole": whole,
                           "from": self._off() + len(self.get_starttag_text() or ""), "line": line, "col": col})

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                e = self.stack[i]
                del self.stack[i:]
                if e["whole"] and not self._skipping():
                    inner = self.src[e["from"]:self._off()]
                    if CJK_RE.search(inner):
                        self.items.append(HtmlItem(self.path, e["line"], e["col"], self.area, "html", norm_key(inner),
                                                   self._line_src(e["line"])))
                return

    def handle_data(self, data):
        if self._skipping() or self._whole() or not CJK_RE.search(data):
            return
        line, col = self.getpos()
        self.items.append(HtmlItem(self.path, line, col, self.area, "text", norm_key(data), self._line_src(line)))


def scan_html(path, src):
    p = _HtmlScan(path, src)
    p.feed(src)
    p.close()
    return p


# ================================================================ app.css 里生成的文字

_CSS_COMMENT = re.compile(r"/\*[\s\S]*?\*/")
_CSS_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_CSS_CONTENT = re.compile(r"""content\s*:\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')""")
_LANG_EN = "html:lang(en) "


class CssItem(object):
    __slots__ = ("path", "line", "col", "area", "kind", "key", "src_line")

    def __init__(self, path, line, area, key, src_line):
        self.path, self.line, self.col, self.area, self.kind, self.key, self.src_line = path, line, 1, area, "css", key, src_line


class CssScan(object):
    """伪元素 content: "中文" 生成的文字翻译不了词典, 英文界面靠 html:lang(en) 选择器覆盖 (切换语言时 JS 改 <html lang>)。
    覆盖规则的选择器 = html:lang(en) + 原来的选择器 (空白不计), 里面也有 content。没有覆盖的算违规。"""

    def __init__(self, path, src):
        self.path = path
        nl = [m.start() for m in re.finditer("\n", src)]
        banners = []

        def blank(m):  # 注释换成同样长度的空白 (换行保留), 位置和行号不变
            text = m.group(0)
            if text.startswith("/*"):
                title = banner_title(text)
                if title:
                    banners.append((m.start(), re.split(u"[:\uff1a(\uff08]", title)[0].strip()))
            return re.sub(r"[^\n]", " ", text)

        clean = _CSS_COMMENT.sub(blank, src)
        self.banners = [b[1] for b in banners]
        starts = [b[0] for b in banners]
        rules = []
        for m in _CSS_RULE.finditer(clean):
            sels = [re.sub(r"\s+", " ", x.strip()) for x in m.group(1).split(",") if x.strip()]
            for c in _CSS_CONTENT.finditer(m.group(2)):
                rules.append((sels, cook(c.group(1)[1:-1]), m.start(2) + c.start()))
        covered = set()  # 有 html:lang(en) 覆盖的原选择器
        for sels, _text, _at in rules:
            for sel in sels:
                if sel.startswith(_LANG_EN):
                    covered.add(sel[len(_LANG_EN):])
        self.items = []
        for sels, text, at in rules:
            if not CJK_RE.search(text):
                continue
            if all(sel in covered for sel in sels):
                continue
            line = bisect.bisect_right(nl, at - 1) + 1
            i = bisect.bisect_right(starts, at) - 1
            a = nl[line - 2] + 1 if line > 1 else 0
            b = nl[line - 1] if line - 1 < len(nl) else len(src)
            self.items.append(CssItem(path, line, banners[i][1] if i >= 0 else "(文件开头)", text, src[a:b]))


# ================================================================ 汇总

class Result(object):
    def __init__(self):
        self.js = {}            # 路径 → Scan
        self.html = {}          # 路径 → _HtmlScan
        self.css = {}           # 路径 → CssScan
        self.css_missing = []   # app.css 里没有 :lang(en) 覆盖的中文 content (已去掉允许清单里的)
        self.dicts = None
        self.violations = []    # JS 违规 (已去掉允许清单里的)
        self.html_missing = []  # index.html 里词典没有英文的静态文字 (已去掉允许清单里的)
        self.allow = []
        self.counts = {}        # 文件 → {区域: 数量} (JS 违规 + HTML 缺词条), 区域按出现顺序
        self.order = {}         # 文件 → [区域, ...] 出现顺序 (含 0 违规的区域)
        self.errors = []        # 词法 / 括号错误 (必须为空)


_CACHE = {}


def _read(path):
    with io.open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


def analyze():
    """扫描所有脚本和页面, 汇总每个区域的违规数。结果按文件修改时间缓存 (同一进程里多次调用很快)。"""
    files = [os.path.join(ROOT, p) for p in JS_FILES + HTML_FILES + CSS_FILES] + dict_files() + [ALLOW_FILE]
    key = tuple((p, os.path.getmtime(p)) for p in files if os.path.exists(p))
    if key in _CACHE:
        return _CACHE[key]
    R = Result()
    R.dicts = load_dictionaries()
    R.allow = load_allow()
    for path in JS_FILES:
        if not os.path.exists(os.path.join(ROOT, path)):
            continue
        sc = Scan(path, _read(path))
        R.js[path] = sc
        for off, msg in sc.errors:
            R.errors.append("%s:%d: %s" % (path, sc.line_col(off)[0], msg))
        order = [START_AREA if path.endswith("app.js") else os.path.basename(path)]
        for _off, title in sc.banners:
            label = area_of_title(title)[0]
            if label not in order:
                order.append(label)
        R.order[path] = order
        R.counts[path] = dict((a, 0) for a in order)
        for v in sc.violations:
            if _allowed(R.allow, path, v.src_line):
                continue
            R.violations.append(v)
            R.counts[path][v.area] = R.counts[path].get(v.area, 0) + 1
    for path in HTML_FILES:
        if not os.path.exists(os.path.join(ROOT, path)):
            continue
        hs = scan_html(path, _read(path))
        R.html[path] = hs
        order = ["(页面开头)"] + [b for b in hs.banners]
        seen = []
        for a in order:
            if a not in seen:
                seen.append(a)
        R.order[path] = seen
        R.counts[path] = dict((a, 0) for a in seen)
        for it in hs.items:
            if isinstance(R.dicts.en.get(it.key), str):
                continue
            if _allowed(R.allow, path, it.src_line):
                continue
            R.html_missing.append(it)
            R.counts[path][it.area] = R.counts[path].get(it.area, 0) + 1
    for path in CSS_FILES:
        if not os.path.exists(os.path.join(ROOT, path)):
            continue
        cs = CssScan(path, _read(path))
        R.css[path] = cs
        order = ["(文件开头)"]
        for a in cs.banners:
            if a not in order:
                order.append(a)
        R.order[path] = order
        R.counts[path] = dict((a, 0) for a in order)
        for it in cs.items:
            if _allowed(R.allow, path, it.src_line):
                continue
            R.css_missing.append(it)
            R.counts[path][it.area] = R.counts[path].get(it.area, 0) + 1
    _CACHE.clear()
    _CACHE[key] = R
    return R


def load_baseline(path=BASELINE_FILE):
    if not os.path.exists(path):
        return {}
    with io.open(path, encoding="utf-8") as f:
        data = json.load(f)
    return dict((k, v) for k, v in data.items() if isinstance(v, dict))


def baseline_doc(counts, order):
    doc = {}
    for path in sorted(counts):
        doc[path] = dict((a, counts[path].get(a, 0)) for a in order[path] + [x for x in counts[path] if x not in order[path]])
    return doc


NOTE = (u"每个区域当前允许的违规数 (JS: 含汉字又不是 t()/tn()/td()/tm()/tk() 键的字符串; HTML: 词典里还没有英文的静态文字)。"
        u"只能减少不能增加: 翻完一个区域后运行 python tests/i18n_lint.py --update-baseline 把它降下来。")


def write_baseline(doc, path=BASELINE_FILE):
    lines = ["{", '  "_说明": %s,' % json.dumps(NOTE, ensure_ascii=False)]
    files = sorted(doc)
    for fi, fn in enumerate(files):
        lines.append("  %s: {" % json.dumps(fn, ensure_ascii=False))
        items = list(doc[fn].items())
        for i, (a, c) in enumerate(items):
            lines.append("    %s: %d%s" % (json.dumps(a, ensure_ascii=False), c, "," if i < len(items) - 1 else ""))
        lines.append("  }%s" % ("," if fi < len(files) - 1 else ""))
    lines.append("}")
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def compare_baseline(R, baseline=None):
    """返回 (超出基线的, 基线过松的): 各是 [(文件, 区域, 现在, 基线)]。基线里没有的区域按 0 算。"""
    base = baseline if baseline is not None else load_baseline()
    over, slack = [], []
    for path in sorted(R.counts):
        for area, n in R.counts[path].items():
            b = base.get(path, {}).get(area, 0)
            if n > b:
                over.append((path, area, n, b))
            elif n < b:
                slack.append((path, area, n, b))
        for area, b in base.get(path, {}).items():
            if area not in R.counts[path] and b:
                slack.append((path, area, 0, b))
    return over, slack


# ---- 已转换的键 vs 词典
def used_keys(R):
    """代码里 t/tn/tk/td/tm 用到的字面量键: {(名字类型, 词典键): [Call]}; 类型 t=普通(t,tk) n=tn d=td m=tm。"""
    out = {}
    for sc in R.js.values():
        for c in sc.calls:
            if c.dynamic:
                continue
            kind = {"t": "t", "tk": "t", "tn": "n", "td": "d", "tm": "m"}[c.name]
            out.setdefault((kind, c.dict_key()), []).append(c)
    return out


def missing_translations(R):
    """代码里用了 t() / tn() / tk() (词典 en) 和 td() (词典 enData) 的字面量键、词典里却没有英文的: [(Call, 类型, 键)]。
    tm() 不查: 服务端提示带变化的部分靠正则模式, 也可能本来就不用翻译。"""
    out = []
    for (kind, key), calls in sorted(used_keys(R).items(), key=lambda kv: kv[0]):
        if (kind in ("t", "n") and key not in R.dicts.en) or (kind == "d" and key not in R.dicts.en_data):
            out.extend((c, kind, key) for c in calls)
    return out


def placeholder_mismatches(R):
    """t() / tn() 调用传的占位符参数和键里的 {名字} 对不上: [(Call, 缺的, 多的)]。
    键里有 {x} 而调用没传 x, 界面上会原样显示 {x}; 传了键里没有的, 是写错了名字 (tn 的 {n} 默认就是数量, 传不传都行)。"""
    out = []
    for sc in R.js.values():
        for c in sc.calls:
            if c.dynamic or c.params is None or c.name not in ("t", "tn"):
                continue
            want = set(placeholders(c.key))
            have = set(c.params)
            if c.name == "tn":
                have.discard("n")
                want.discard("n")
            if want != have:
                out.append((c, sorted(want - have), sorted(have - want)))
    return out


# ================================================================ 命令行

def _p(*a):
    print(" ".join(str(x) for x in a))


def report(R, args):
    base = load_baseline()
    want = args.area
    for path in sorted(R.counts):
        total = sum(R.counts[path].values())
        b_total = sum(base.get(path, {}).values())
        kind = u"静态文字缺英文词条" if path.endswith(".html") else u"没有 :lang(en) 覆盖的 content 文字" if path.endswith(".css") else u"未翻译的字符串"
        _p(u"\n[%s] %s: %d (基线 %d)" % (path, kind, total, b_total))
        w = max([len(a) for a in R.order[path]] + [6])
        for a in R.order[path]:
            if want and want not in a:
                continue
            n = R.counts[path].get(a, 0)
            b = base.get(path, {}).get(a, 0)
            dic = "html" if path.endswith(".html") else "css" if path.endswith(".css") else next((d for p, l, d in AREAS if l == a), "-") or "-"
            flag = u"  <-- 超出基线" if n > b else (u"  (基线可降)" if n < b else "")
            _p(u"  %s  %5d  基线 %5d  词典 %s%s" % (a.ljust(w), n, b, dic, flag))
    if args.summary:
        return
    _p(u"\n---- 明细 ----")
    for v in R.violations:
        if want and want not in v.area:
            continue
        txt = v.text.replace("\n", "\\n")
        _p(u"%s  [%s]  %s%s" % (v.where(), v.area, txt if len(txt) <= 70 else txt[:70] + u"…",
                                 (u"   <-- " + v.reason) if v.reason else ""))
    for it in R.html_missing + R.css_missing:
        if want and want not in it.area:
            continue
        txt = it.key
        _p(u"%s:%d:%d  [%s]  %s %s" % (it.path, it.line, it.col, it.area, it.kind, txt if len(txt) <= 70 else txt[:70] + u"…"))
    problems = []
    for sc in R.js.values():
        for p, ln, name, bl in sc.shadows:
            problems.append(u"%s:%d: 这里调用了 %s(), 但同一条顶层语句里第 %d 行把 %s 声明成了变量 (会遮住翻译函数, 请把变量改名)" % (p, ln, name, bl, name))
        for p, ln, name in sc.clashes:
            problems.append(u"%s:%d: 顶层声明了 %s, 和 i18n.js 的全局名字冲突" % (p, ln, name))
    for e in R.errors:
        problems.append(e)
    for d in R.dicts.errors:
        problems.append(u"词典 %s:%d: %s" % d)
    if problems:
        _p(u"\n---- 必须先修的问题 ----")
        for x in problems:
            _p(x)


def main(argv=None):
    ap = argparse.ArgumentParser(description=u"界面文字与翻译检查")
    ap.add_argument("--report", action="store_true", help=u"打印汇总和明细")
    ap.add_argument("--summary", action="store_true", help=u"只打印按区域的汇总")
    ap.add_argument("--area", default="", help=u"只看名称里含这个词的区域")
    ap.add_argument("--check", action="store_true", help=u"和基线比较, 有问题退出码为 1")
    ap.add_argument("--update-baseline", action="store_true", help=u"把现在的数量写进基线 (只允许减少)")
    ap.add_argument("--allow-increase", action="store_true", help=u"配合 --update-baseline: 允许某个区域的数量变多")
    ap.add_argument("--missing", action="store_true", help=u"已转成 t() 但词典里没有英文的键")
    ap.add_argument("--unused", action="store_true", help=u"词典里有、代码里没用到的条目")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    R = analyze()
    if args.update_baseline:
        over, _slack = compare_baseline(R)
        if over and not args.allow_increase and os.path.exists(BASELINE_FILE):  # 第一次生成基线不受限
            _p(u"下面这些区域的违规数比基线多, 没有写入基线 (要写入请先修掉, 或加 --allow-increase):")
            for path, a, n, b in over:
                _p(u"  %s [%s] 现在 %d, 基线 %d" % (path, a, n, b))
            return 1
        write_baseline(baseline_doc(R.counts, R.order))
        _p(u"已写入 %s" % BASELINE_FILE)
        return 0
    if args.missing:
        miss = missing_translations(R)
        for c, kind, key in miss:
            _p(u"%s:%d [%s] %s(%s)" % (c.path, c.line, c.area, c.name, json.dumps(key, ensure_ascii=False)))
        _p(u"共 %d 处缺英文词条" % len(miss))
        bad = placeholder_mismatches(R)
        for c, lack, extra in bad:
            _p(u"%s:%d [%s] %s(%s) 占位符和传的参数对不上: 没传 %s, 多传了 %s" % (c.path, c.line, c.area, c.name, json.dumps(c.key, ensure_ascii=False), lack, extra))
        return 1 if (miss or bad) else 0
    if args.unused:
        used = set(k for (kind, k) in used_keys(R))
        html_keys = set(it.key for hs in R.html.values() for it in hs.items)
        n = 0
        for lang, table in (("en", R.dicts.en), ("enData", R.dicts.en_data)):
            for k in table:
                if lang == "en" and (k in used or k in html_keys):
                    continue
                if lang == "enData" and k in used:
                    continue
                if lang == "en" and "|" in k and k.split("|", 1)[1] in used:
                    continue
                w = R.dicts.where.get((lang, k), [("?", 0, "")])[0]
                if w[0] == "i18n.en.server.js":  # 服务端提示是运行时 tm(d.error) 传进来的, 代码里看不到字面量
                    continue
                n += 1
                _p(u"%s:%d [%s] %s" % (w[0], w[1], lang, k[:60]))
        _p(u"共 %d 条没用到 (运行时才拼出来的键、td() 传变量的数据名可能是误报)" % n)
        return 0
    if args.check:
        over, slack = compare_baseline(R)
        for path, a, n, b in over:
            _p(u"超出基线: %s [%s] 现在 %d, 基线 %d" % (path, a, n, b))
        for path, a, n, b in slack:
            _p(u"基线可以降低: %s [%s] 现在 %d, 基线 %d (运行 --update-baseline)" % (path, a, n, b))
        mism = placeholder_mismatches(R)
        for c, lack, extra in mism:
            _p(u"占位符对不上: %s:%d %s(%s) 没传 %s, 多传了 %s" % (c.path, c.line, c.name, json.dumps(c.key, ensure_ascii=False), lack, extra))
        bad = bool(over or slack or R.errors or R.dicts.errors or mism)
        _p(u"检查%s" % (u"通过" if not bad else u"没通过"))
        return 1 if bad else 0
    report(R, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
