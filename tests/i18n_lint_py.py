#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""服务端「中文 / 英文消息」检查工具 (只用标准库 ast, 不导入被检查的代码, 兼容 Python 3.8)。

它做两件事。

一、扫描 llm_bench_pro/*.py, 找出没有走 t() / tn() 的对外文字。规则 (每一条违规都算进所在文件的违规数):

  han      含汉字的字符串常量 / f-string 的静态部分, 又不是下面几种之一:
             - t() / tn() 的第一个参数 (词典的键) 和 ctx= 参数
             - docstring 和单独成行的字符串 (开发者文档)
             - 登记在 tests/i18n_py_allow.txt 里的 (测试内容、词表数据等不翻译的东西)
  punct    只含中文标点 (、。，：；（）「」等) 没有汉字的字符串: 英文界面里同样是漏
  key      t() / tn() 的第一个参数不是「含中文的字符串常量」(变量 / f-string / 拼接 / 旧的 %s 写法), 检查抓不到
  args     t() / tn() 的参数写法不对 (用了 * / **、位置参数个数不对)
  format   t() / tn() 的键不是合法的 {名字} 格式串 (裸 {} 、{0}、单个 } 、字面花括号没写成 {{ }})
  module   t() / tn() 写在模块级或类体里: import 时就被翻译, 之后再改语言不生效 (要放进函数里)
  thread   直接用 threading.Thread / ThreadPoolExecutor / Timer: 线程里的日志会丢掉任务语言 (改用 i18n.spawn / i18n.executor)
  shadow   函数里把 t / tn 当变量名, 同一个函数里又调用 t() (调用的会是那个变量)
  import   模块里调用了 t() / tn(), 却没有导入它们

二、检查英文词典 llm_bench_pro/i18n_en/<模块名>.py (内容是 ENTRIES = {"中文原文": "English"}, 只能是字面量, 这里不执行它):
  每个 t() / tn() 用到的键在本模块的词典 (或 common.py) 里都有英文; 词典里的键都被用到; 同一个键不能出现在两个词典文件里
  (好几个模块都用的放 common.py); 英文里没有汉字和中文标点; 中英文的占位符一致, 调用处也给足了参数;
  t() 的英文是字符串, tn() 的英文是 (单数, 复数) 二元组。

用法 (在仓库根目录):
  python tests/i18n_lint_py.py                       检查: 违规数不超过基线 (也不能比基线小太多)、允许清单没有过期条目、词典没问题
  python tests/i18n_lint_py.py --report              按文件汇总 + 全部明细
  python tests/i18n_lint_py.py --report -f server.py 只看某个文件的明细 (可以重复 -f)
  python tests/i18n_lint_py.py --scopes -f bench.py  按函数 / 常量汇总 (带行号范围): 拆分大文件、分给几个人时用
  python tests/i18n_lint_py.py --missing             t() / tn() 用到了、词典里还没有英文的键
  python tests/i18n_lint_py.py --unused              词典里有、代码里没用到的条目
  python tests/i18n_lint_py.py --update-baseline     把基线降到当前数量 (只降不升; 要升要加 --allow-increase)

允许清单 tests/i18n_py_allow.txt 每行一条 (# 开头是注释), 只对 han / punct 两条规则有效:
  文件名:范围                只要字符串在这个范围里就放过。范围是函数名、模块级变量名 (如 BIZ_RULES)、
                             类名, 或者 类名.方法名 (方法名重名时用); 范围是外层函数时里面嵌套的函数也算
  文件名:范围:文字片段        再限定: 字符串里要含有这段文字才放过 (一个函数里既有测试内容又有对外提示时用)
  范围写 <module> 表示不在任何函数 / 变量赋值里的模块级语句。
"""
import argparse
import ast
import json
import os
import re
import string
import sys
from collections import OrderedDict, namedtuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "llm_bench_pro")
DICT_DIR = os.path.join(PKG, "i18n_en")
ALLOW_FILE = os.path.join(HERE, "i18n_py_allow.txt")
BASELINE_FILE = os.path.join(HERE, "i18n_py_baseline.json")


def _char_class(*ranges):
    """[起-止...] 形式的正则字符类 (用码点写, 免得源文件里出现看不见的字符)。"""
    return re.compile("[" + "".join("%s-%s" % (chr(a), chr(b)) for a, b in ranges) + "]")


# 汉字: 基本区 + 扩展 A + 兼容区 + 扩展 B 及以后
HAN_RE = _char_class((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0x20000, 0x2FA1F))
# 中文专用的标点和全角符号 (、。「」《》（），：；！？ 等; 不含 “ ” … — · 这类英文排版也用的); 与前端检查工具的范围一致
PUNCT_RE = _char_class((0x3000, 0x303F), (0xFF00, 0xFFEF))
# 键里残留的 % 旧写法: %s %d %5.1f %-6s (不含 argparse 用的 %(default)s 和 %%)
_PERCENT_RE = re.compile(r"(?<!%)%[-+ #0]*\d*(?:\.\d+)?[sdfrxXeEgGci]")
_IDENT_RE = re.compile(r"^[^\W\d]\w*$")

THREAD_NAMES = ("Thread", "ThreadPoolExecutor", "Timer")
RESERVED_NAMES = ("ctx", "_key", "_n")   # t() / tn() 自己的参数名, 不能当占位符名字
RULES = OrderedDict([
    ("han", "含汉字的字符串没有走 t() / tn()"),
    ("punct", "含中文标点的字符串没有走 t() / tn()"),
    ("key", "t() / tn() 的第一个参数必须是含中文的字符串常量"),
    ("args", "t() / tn() 的参数写法不对"),
    ("format", "t() / tn() 的键不是合法的 {名字} 格式串"),
    ("module", "t() / tn() 不能写在模块级或类体里"),
    ("thread", "线程 / 线程池要用 i18n.spawn / i18n.executor"),
    ("shadow", "t / tn 被当成了变量名"),
    ("import", "调用了 t() / tn() 但没有导入"),
])

Violation = namedtuple("Violation", "file line col rule scope outer text")
# 一处 t() / tn() 调用: fn 为 "t" / "tn"; key 为词典里的键 (带 ctx 时是 "语境|原文"); raw 是中文原文;
# kwargs 为调用时给的占位符名 (不含 ctx)
Call = namedtuple("Call", "file line fn key raw ctx kwargs scope")
DictProblem = namedtuple("DictProblem", "kind where text")


def has_han(s):
    return bool(HAN_RE.search(s))


def has_zh(s):
    """汉字或中文标点。"""
    return bool(HAN_RE.search(s) or PUNCT_RE.search(s))


def placeholders(text):
    """格式串里的占位符名集合; 格式不合法时抛 ValueError。"""
    names = set()
    for _lit, field, _spec, _conv in string.Formatter().parse(text):
        if field is not None:
            names.add(re.split(r"[.\[]", field, maxsplit=1)[0])
    return names


def _format_problem(text):
    """键 / 词条作为 str.format 模板的问题; 没问题返回空串。"""
    try:
        fields = [f for _lit, f, _spec, _conv in string.Formatter().parse(text) if f is not None]
    except ValueError as e:
        return "格式串不合法 (%s); 字面的 { } 要写成 {{ }}" % e
    for f in fields:
        if not _IDENT_RE.match(f):
            return "占位符 {%s} 必须是 {名字} 的形式 (不能是 {} / {0} / 带 . 或 [ ]); 字面的 { } 要写成 {{ }}" % f
        if f in RESERVED_NAMES:
            return "占位符名字 %s 是保留的 (t / tn 自己的参数名), 换一个名字" % f
    return ""


# ---------------------------------------------------------------- 允许清单

AllowEntry = namedtuple("AllowEntry", "file scope frag line raw")


def load_allow(path=ALLOW_FILE):
    entries = []
    if not os.path.isfile(path):
        return entries
    with open(path, encoding="utf-8") as f:
        for no, raw in enumerate(f, 1):
            line = re.split(r"(?:^|\s)#", raw, maxsplit=1)[0].strip()
            if not line:
                continue
            parts = line.split(":", 2)
            if len(parts) < 2 or not parts[0].strip() or not parts[1].strip():
                raise ValueError("%s 第 %d 行格式不对 (应为 文件名:范围[:文字片段]): %s" % (os.path.basename(path), no, raw.strip()))
            entries.append(AllowEntry(parts[0].strip(), parts[1].strip(), parts[2].strip() if len(parts) > 2 else "", no, raw.strip()))
    return entries


def _scope_match(scope, entry_scope):
    """scope 是 "A.B.C" 形式的完整范围; entry_scope 是单个名字或 "A.B" 这样的连续片段。"""
    if entry_scope == "<module>":
        return scope == "<module>"
    return ("." + entry_scope + ".") in ("." + scope + ".")


def allow_match(v, entries):
    """v 匹配到的第一条允许清单条目; 没有返回 None。"""
    for e in entries:
        if e.file == v.file and _scope_match(v.scope, e.scope) and (not e.frag or e.frag in v.text):
            return e
    return None


# ---------------------------------------------------------------- 扫描

def _t_call_name(node):
    """Call 节点是 t(...) / tn(...) / i18n.t(...) / i18n.tn(...) 时返回 "t" / "tn", 否则 None。"""
    f = node.func
    if isinstance(f, ast.Name) and f.id in ("t", "tn"):
        return f.id
    if isinstance(f, ast.Attribute) and f.attr in ("t", "tn") and isinstance(f.value, ast.Name) and f.value.id == "i18n":
        return f.attr
    return None


def _thread_call_name(node):
    f = node.func
    name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
    return name if name in THREAD_NAMES else None


def _is_str(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _target_name(target):
    """赋值目标的名字 (用作范围名): X = ... / X: T = ... / X[k] = ... / X.a = ... / A, B = ..."""
    while isinstance(target, (ast.Subscript, ast.Attribute)):
        target = target.value
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, (ast.Tuple, ast.List)) and target.elts:
        return _target_name(target.elts[0])
    return None


def _exempt_ids(tree):
    """不算违规的字符串节点: docstring / 单独成行的字符串 / t() 的键和 ctx=。"""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and _is_str(node.value):
            ids.add(id(node.value))
        elif isinstance(node, ast.Call) and _t_call_name(node):
            if node.args and _is_str(node.args[0]):
                ids.add(id(node.args[0]))
            for kw in node.keywords:
                if kw.arg == "ctx" and _is_str(kw.value):
                    ids.add(id(kw.value))
    return ids


def _all_args(args):
    return list(getattr(args, "posonlyargs", [])) + list(args.args) + list(args.kwonlyargs) + [args.vararg, args.kwarg]


def _scope_binds(body_nodes, args=None):
    """一个作用域自己绑定的名字 (不含嵌套函数 / 类 / 推导式内部)。返回 {名字: 第一处的行号}。"""
    out = {}

    def bind(name, node):
        out.setdefault(name, getattr(node, "lineno", 0))

    def walk(node):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bind(node.name, node)
            return  # 内部是另一个作用域
        if isinstance(node, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            return
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bind(node.id, node)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bind(node.name, node)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                bind((a.asname or a.name).split(".")[0], node)
        for child in ast.iter_child_nodes(node):
            walk(child)

    if args is not None:
        for a in _all_args(args):
            if a is not None:
                bind(a.arg, a)
    for n in body_nodes:
        walk(n)
    return out


class _Scanner(ast.NodeVisitor):
    def __init__(self, fname, tree):
        self.fname = fname
        self.exempt = _exempt_ids(tree)
        self.chain = []     # 范围名 (类 / 函数 / 模块级变量)
        self.kinds = []     # 与 chain 一一对应: "class" / "func" / "var"
        self.in_func = 0
        self.violations = []
        self.calls = []
        self.bare = set()          # 以裸名调用的 t / tn
        self.uses_attr = False     # 有 i18n.t(...) 这种写法的调用

    # ---- 记录
    @property
    def scope(self):
        return ".".join(self.chain) or "<module>"

    @property
    def outer(self):
        """按函数 / 常量汇总时用的范围: 类.方法、函数、模块级变量 (嵌套函数并进外层函数)。"""
        if not self.chain:
            return "<module>"
        return ".".join(self.chain[:2]) if self.kinds[0] == "class" else self.chain[0]

    def add(self, node, rule, text, line=None, scope=None):
        self.violations.append(Violation(self.fname, line or getattr(node, "lineno", 0), getattr(node, "col_offset", 0),
                                         rule, scope or self.scope, self.outer, text))

    def check_text(self, node, text):
        if has_han(text):
            self.add(node, "han", text)
        elif PUNCT_RE.search(text):
            self.add(node, "punct", text)

    # ---- 字符串
    def visit_Constant(self, node):
        if isinstance(node.value, str) and id(node) not in self.exempt:
            self.check_text(node, node.value)

    def visit_JoinedStr(self, node):
        static = "".join(v.value for v in node.values if _is_str(v))
        if static and id(node) not in self.exempt:
            self.check_text(node, static)
        for v in node.values:
            if isinstance(v, ast.FormattedValue):
                self.visit(v.value)  # {表达式} 里可能还有别的字符串

    # ---- 范围
    def _function(self, node, name):
        args = node.args
        for d in list(args.defaults) + [d for d in args.kw_defaults if d is not None]:
            self.visit(d)
        for a in _all_args(args):
            if a is not None and a.annotation is not None:
                self.visit(a.annotation)
        if getattr(node, "returns", None) is not None:
            self.visit(node.returns)
        body = node.body if isinstance(node.body, list) else [node.body]
        # shadow: 函数里绑定了 t / tn, 又在这个函数里 (含嵌套函数) 调用 t()
        binds = _scope_binds(body, args)
        called = {_t_call_name(n) for b in body for n in ast.walk(b) if isinstance(n, ast.Call)}
        for nm in ("t", "tn"):
            if nm in binds and nm in called:
                self.add(node, "shadow", "变量 %s 遮住了 %s(): 改个变量名, 或者这个函数里改用 i18n.%s()" % (nm, nm, nm),
                         line=binds[nm], scope=".".join(self.chain + [name]))
        if name:
            self.chain.append(name)
            self.kinds.append("func")
        self.in_func += 1
        for b in body:
            self.visit(b)
        self.in_func -= 1
        if name:
            self.chain.pop()
            self.kinds.pop()

    def visit_FunctionDef(self, node):
        for d in node.decorator_list:
            self.visit(d)
        self._function(node, node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node):
        self._function(node, "")

    def visit_ClassDef(self, node):
        for d in node.decorator_list:
            self.visit(d)
        for b in node.bases:
            self.visit(b)
        for k in node.keywords:
            self.visit(k.value)
        self.chain.append(node.name)
        self.kinds.append("class")
        for b in node.body:
            self.visit(b)
        self.chain.pop()
        self.kinds.pop()

    def _assign(self, targets, value):
        name = None if self.in_func else next((n for n in map(_target_name, targets) if n), None)
        for tg in targets:
            self.visit(tg)
        if value is not None:
            if name:
                self.chain.append(name)
                self.kinds.append("var")
            self.visit(value)
            if name:
                self.chain.pop()
                self.kinds.pop()

    def visit_Assign(self, node):
        self._assign(node.targets, node.value)

    def visit_AnnAssign(self, node):
        self._assign([node.target], node.value)

    def visit_AugAssign(self, node):
        self._assign([node.target], node.value)

    # ---- 调用
    def visit_Call(self, node):
        fn = _t_call_name(node)
        if fn:
            if isinstance(node.func, ast.Name):
                self.bare.add(fn)
            else:
                self.uses_attr = True
            self._t_call(node, fn)
        elif _thread_call_name(node) and self.fname != "i18n.py":
            self.add(node, "thread", "%s(...)" % _thread_call_name(node))
        self.generic_visit(node)

    def _t_call(self, node, fn):
        if not self.in_func:
            self.add(node, "module", "%s(...)" % fn)
        starred = [a for a in node.args if isinstance(a, ast.Starred)] + [k for k in node.keywords if k.arg is None]
        if starred:
            self.add(node, "args", "%s() 不能用 * / ** 展开参数, 占位符要逐个写成关键字参数" % fn)
        want = 1 if fn == "t" else 2
        if len(node.args) != want and not starred:
            self.add(node, "args", "%s() 要 %d 个位置参数 (%s), 给了 %d 个; 占位符要用关键字参数" % (
                fn, want, "中文原文" if fn == "t" else "中文原文, 数量", len(node.args)))
        if not node.args:
            self.add(node, "key", "%s() 缺少中文原文" % fn)
            return
        first = node.args[0]
        if not _is_str(first):
            self.add(node, "key", "%s() 的第一个参数不是字符串常量 (%s)" % (fn, type(first).__name__))
            return
        raw = first.value
        if not has_zh(raw):
            self.add(node, "key", "%s() 的键里没有汉字 (只有英文的文字不用翻译): %s" % (fn, raw))
        if _PERCENT_RE.search(raw):
            self.add(node, "key", "%s() 的键里有 %% 旧写法, 改成 {名字}: %s" % (fn, raw))
        problem = _format_problem(raw)
        if problem:
            self.add(node, "format", "%s: %s" % (raw, problem))
        ctx = None
        for kw in node.keywords:
            if kw.arg == "ctx":
                if _is_str(kw.value):
                    ctx = kw.value.value
                else:
                    self.add(node, "key", "ctx= 必须是字符串常量")
        names = tuple(kw.arg for kw in node.keywords if kw.arg and kw.arg != "ctx")
        self.calls.append(Call(self.fname, node.lineno, fn, (ctx + "|" + raw) if ctx else raw, raw, ctx, names, self.scope))


def scan_source(source, fname="<test>.py"):
    """扫描一段源码。返回 (违规列表 [Violation], 调用列表 [Call])。语法错误抛 SyntaxError。"""
    tree = ast.parse(source, fname)
    sc = _Scanner(fname, tree)
    sc.visit(tree)
    viol = sc.violations
    if sc.bare or sc.uses_attr:
        binds = _scope_binds(tree.body)   # 模块级绑定的名字: import / 赋值 / def / class
        for nm in sorted(sc.bare):
            if nm not in binds:
                viol.append(Violation(fname, 1, 0, "import", "<module>", "<module>",
                                      "模块里调用了 %s() 却没有导入它 (try 里写 from . import i18n, 之后 t, tn = i18n.t, i18n.tn)" % nm))
        if sc.uses_attr and "i18n" not in binds:
            viol.append(Violation(fname, 1, 0, "import", "<module>", "<module>", "模块里调用了 i18n.t() 却没有导入 i18n"))
    viol.sort(key=lambda v: (v.line, v.col, v.rule))
    return viol, sc.calls


def scan_all(pkg_dir=PKG):
    """扫描 llm_bench_pro/*.py。返回 {文件名: (违规列表, 调用列表)} (违规还没按允许清单过滤)。"""
    out = OrderedDict()
    for fn in sorted(os.listdir(pkg_dir)):
        if fn.endswith(".py"):
            with open(os.path.join(pkg_dir, fn), encoding="utf-8") as f:
                out[fn] = scan_source(f.read(), fn)
    return out


def apply_allow(scan, entries):
    """按允许清单过滤。返回 ({文件: [违规]}, {文件: [被放过的]}, 没有匹配到任何字符串的过期条目列表)。"""
    used = set()
    bad, allowed = OrderedDict(), OrderedDict()
    for fn, (viol, _calls) in scan.items():
        bad[fn], allowed[fn] = [], []
        for v in viol:
            e = allow_match(v, entries) if v.rule in ("han", "punct") else None
            if e:
                used.add(e)
                allowed[fn].append(v)
            else:
                bad[fn].append(v)
    stale = [e for e in entries if e not in used]
    return bad, allowed, stale


def load_baseline(path=BASELINE_FILE):
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def counts(bad):
    return OrderedDict((fn, len(v)) for fn, v in bad.items())


def write_baseline(counts_by_file, path=BASELINE_FILE):
    """一行一个文件, 按文件名排序: 多人各改各的文件时 git 合并不容易冲突。"""
    items = sorted(counts_by_file.items())
    text = "{\n" + ",\n".join(" %s: %d" % (json.dumps(k), v) for k, v in items) + "\n}\n"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def ratchet_problems(cur, base):
    """当前违规数和基线的比较: 多了不行, 基线比现状宽 (少了没有把基线降下来) 也不行。返回 [(文件, 说明)]。"""
    out = []
    for fn, n in cur.items():
        limit = base.get(fn, 0)
        if n > limit:
            out.append((fn, "违规 %d 处, 基线 %d 处 (多了 %d 处; 用 --report -f %s 看明细)" % (n, limit, n - limit, fn)))
        elif n < limit:
            out.append((fn, "违规 %d 处, 基线还是 %d 处 (请运行 python tests/i18n_lint_py.py --update-baseline 把基线降下来)" % (n, limit)))
    for fn in base:
        if fn not in cur:
            out.append((fn, "基线里有这个文件, 但它已经不存在了 (运行 --update-baseline 清掉)"))
    return out


# ---------------------------------------------------------------- 英文词典

def load_dicts(dict_dir=DICT_DIR):
    """读词典文件 (不执行): 返回 ({模块名: {键: 词条}}, [DictProblem])。ENTRIES 只能是字面量。"""
    dicts, problems = OrderedDict(), []
    if not os.path.isdir(dict_dir):
        return dicts, problems
    for fn in sorted(os.listdir(dict_dir)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        name = fn[:-3]
        dicts[name] = {}
        with open(os.path.join(dict_dir, fn), encoding="utf-8") as f:
            src = f.read()
        try:
            tree = ast.parse(src, fn)
        except SyntaxError as e:
            problems.append(DictProblem("load", fn, "语法错误: %s" % e))
            continue
        node = next((n for n in tree.body if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == "ENTRIES" for t in n.targets)), None)
        if node is None or not isinstance(node.value, ast.Dict):
            problems.append(DictProblem("load", fn, "没有 ENTRIES = {...}"))
            continue
        seen = set()
        for k in node.value.keys:
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                if k.value in seen:
                    problems.append(DictProblem("dup", "%s:%d" % (fn, k.lineno), "同一个文件里键写了两次: %s" % k.value))
                seen.add(k.value)
        try:
            entries = ast.literal_eval(node.value)
        except (ValueError, SyntaxError) as e:
            problems.append(DictProblem("load", fn, "ENTRIES 只能是字面量 (字符串 / 元组 / 字典), 不能有拼接或函数调用: %s" % e))
            continue
        dicts[name] = entries
    return dicts, problems


def _forms(entry):
    """词条里的英文写法 (str 一种, tuple 每个写法一种)。"""
    return [entry] if isinstance(entry, str) else list(entry)


def check_dictionary(scan, dicts):
    """词典和调用处对一遍。返回 [DictProblem] (kind: missing / unused / stale / dup / type / han / format /
    placeholder / kwargs / conflict)。scan 是 scan_all() 的结果。"""
    problems = []
    common = dicts.get("common", {})
    raw_of, fns_of, sites = {}, {}, {}      # 键 → 中文原文 / 用了哪些调用 / 调用位置
    used_in = {}                            # 模块名 → 用到的键
    used_all = set()
    for fn, (_viol, calls) in scan.items():
        mod = fn[:-3]
        for c in calls:
            used_in.setdefault(mod, set()).add(c.key)
            used_all.add(c.key)
            raw_of.setdefault(c.key, set()).add((c.ctx, c.raw))
            fns_of.setdefault(c.key, set()).add(c.fn)
            sites.setdefault(c.key, []).append(c)
    for key, raws in raw_of.items():
        if len(raws) > 1:
            problems.append(DictProblem("conflict", "键 " + key, "不同的 (语境, 原文) 撞成了同一个词典键: %s" % sorted(raws, key=str)))
    # 每个键只能在一个词典文件里
    owners = {}
    for mod, entries in dicts.items():
        for key in entries:
            owners.setdefault(key, []).append(mod)
    for key, mods in owners.items():
        if len(mods) > 1:
            problems.append(DictProblem("dup", "%s.py" % "、".join(mods), "同一个键在多个词典文件里: %s (只留一份; 好几个模块都用的放 common.py)" % key))
    # 调用处 → 词条
    for fn, (_viol, calls) in scan.items():
        mod = fn[:-3]
        for c in calls:
            entry = dicts.get(mod, {}).get(c.key)
            if entry is None:
                entry = common.get(c.key)
            where = "%s:%d" % (fn, c.line)
            if entry is None:
                other = [m for m in owners.get(c.key, []) if m not in (mod, "common")]
                hint = ("; 它在 %s.py 里有, 别的模块也用到了就挪进 common.py" % other[0]) if other else ""
                problems.append(DictProblem("missing", where, "词典里没有英文: %s%s" % (c.key, hint)))
                continue
            if c.fn == "tn" and "t" in fns_of[c.key]:
                problems.append(DictProblem("type", where, "同一个键既用 t() 又用 tn(): %s" % c.key))
            want_names = placeholders(c.raw) - ({"n"} if c.fn == "tn" else set())
            given = set(c.kwargs)
            lost = sorted(want_names - given)
            if lost:
                problems.append(DictProblem("kwargs", where, "中文原文里的占位符没有传值: %s" % ", ".join("{%s}" % x for x in lost)))
            for form in _forms(entry):
                if isinstance(form, str):
                    en_names = placeholders(form) - ({"n"} if c.fn == "tn" else set())
                    lost = sorted(en_names - given)
                    if lost:
                        problems.append(DictProblem("kwargs", where, "英文里的占位符调用处没有传值: %s" % ", ".join("{%s}" % x for x in lost)))
    # 词条本身
    for mod, entries in dicts.items():
        for key, entry in entries.items():
            where = "%s.py" % mod
            tn_used = "tn" in fns_of.get(key, ())
            if tn_used:
                if not (isinstance(entry, tuple) and len(entry) == 2 and all(isinstance(x, str) for x in entry)):
                    problems.append(DictProblem("type", where, "tn() 的英文必须是 (单数, 复数) 二元组: %s" % key))
            elif not isinstance(entry, str):
                problems.append(DictProblem("type", where, "t() 的英文必须是字符串 (带数量的用 tn 并写成二元组): %s" % key))
            if key not in used_all:
                problems.append(DictProblem("unused", where, "词典里有、代码里没用到 (改了原文没同步? 或者已经不需要了): %s" % key))
            elif mod != "common" and key not in used_in.get(mod, ()):
                problems.append(DictProblem("stale", where, "这个键只在别的模块里用到, 词典要放在用它的模块 (好几个模块用就放 common.py): %s" % key))
            raws = raw_of.get(key)
            raw = next(iter(raws))[1] if raws and len(raws) == 1 else None
            for form in _forms(entry):
                if not isinstance(form, str) or not form.strip():
                    problems.append(DictProblem("type", where, "英文不能为空: %s" % key))
                    continue
                if has_zh(form):
                    problems.append(DictProblem("han", where, "英文里不能有汉字或中文标点: %s => %s" % (key, form)))
                bad = _format_problem(form)
                if bad:
                    problems.append(DictProblem("format", where, "英文格式串不对 (%s): %s" % (bad, form)))
                elif raw is not None and not _format_problem(raw):
                    drop = {"n"} if tn_used else set()
                    a, b = placeholders(raw) - drop, placeholders(form) - drop
                    if a != b:
                        problems.append(DictProblem("placeholder", where, "中英文占位符不一致 (中文 %s, 英文 %s): %s" % (
                            sorted(a), sorted(b), key)))
    return problems


# ---------------------------------------------------------------- 命令行

def _short(text, n=70):
    text = text.replace("\n", "\\n")
    return text if len(text) <= n else text[:n - 1] + "…"


def main(argv=None):
    ap = argparse.ArgumentParser(description="服务端消息翻译检查 (规则见文件开头的说明)",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", action="store_true", help="按文件汇总, 并列出全部明细")
    ap.add_argument("--scopes", action="store_true", help="按函数 / 常量汇总 (配合 -f)")
    ap.add_argument("--missing", action="store_true", help="用到了、词典里还没有英文的键")
    ap.add_argument("--unused", action="store_true", help="词典里有、代码里没用到的条目")
    ap.add_argument("-f", "--file", action="append", default=[], help="只看这个文件 (例如 server.py), 可重复")
    ap.add_argument("--update-baseline", action="store_true", help="把基线降到当前数量")
    ap.add_argument("--allow-increase", action="store_true", help="--update-baseline 时允许把基线调高 / 新增文件")
    ap.add_argument("--no-allow", action="store_true", help="不套用允许清单 (看看有多少字符串)")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
    scan = scan_all()
    entries = [] if args.no_allow else load_allow()
    bad, allowed, stale = apply_allow(scan, entries)
    base = load_baseline()
    cur = counts(bad)

    if args.update_baseline:
        new = dict(base)
        refused = []
        for fn, n in cur.items():
            if fn not in base:
                if n and not args.allow_increase:
                    refused.append("%s: 新文件有 %d 处违规, 不能直接进基线 (要先改掉, 或者加 --allow-increase)" % (fn, n))
                    continue
            elif n > base[fn] and not args.allow_increase:
                refused.append("%s: 违规数 %d 比基线 %d 多了, 基线只降不升 (要升请加 --allow-increase)" % (fn, n, base[fn]))
                continue
            new[fn] = n
        for fn in list(new):
            if fn not in cur:
                del new[fn]
        write_baseline(new)
        print("基线已更新: %s (合计 %d)" % (os.path.relpath(BASELINE_FILE, ROOT), sum(new.values())))
        for r in refused:
            print("  没改: " + r)
        return 1 if refused else 0

    dicts, dict_problems = load_dicts()
    dict_problems = dict_problems + check_dictionary(scan, dicts)

    if args.missing or args.unused:
        kinds = ("missing",) if args.missing else ("unused", "stale")
        found = [p for p in dict_problems if p.kind in kinds]
        for p in found:
            print("%s: %s" % (p.where, p.text))
        print("共 %d 条" % len(found))
        return 1 if found else 0

    shown = args.file or list(cur)
    if args.scopes:
        for fn in shown:
            per = OrderedDict()
            for v in bad.get(fn, []):
                d = per.setdefault(v.outer, [v.line, v.line, 0])
                d[0], d[1], d[2] = min(d[0], v.line), max(d[1], v.line), d[2] + 1
            print("%s: 共 %d 处" % (fn, cur.get(fn, 0)))
            for key, (lo, hi, n) in sorted(per.items(), key=lambda kv: kv[1][0]):
                print("  %5d 处  行 %d-%d  %s" % (n, lo, hi, key))
        return 0

    if args.report:
        by_rule = OrderedDict((fn, {}) for fn in bad)
        for fn, vs in bad.items():
            for v in vs:
                by_rule[fn][v.rule] = by_rule[fn].get(v.rule, 0) + 1
        print("%-18s %6s %6s %6s   %s" % ("文件", "违规", "基线", "已允许", "规则分布"))
        for fn in cur:
            print("%-18s %6d %6s %6d   %s" % (fn, cur[fn], base.get(fn, "-"), len(allowed[fn]),
                                              " ".join("%s=%d" % kv for kv in by_rule[fn].items())))
        print("%-18s %6d %6d %6d" % ("合计", sum(cur.values()), sum(base.values()), sum(len(v) for v in allowed.values())))
        for fn in shown:
            vs = bad.get(fn, [])
            if vs:
                print("\n== %s (%d) ==" % (fn, len(vs)))
            for v in vs:
                print("%s:%d:%d [%s] %s | %s" % (v.file, v.line, v.col, v.rule, v.scope, _short(v.text)))
        if stale:
            print("\n允许清单里有过期条目 (没有匹配到任何字符串):")
            for e in stale:
                print("  第 %d 行: %s" % (e.line, e.raw))
        for p in dict_problems:
            print("[词典 %s] %s: %s" % (p.kind, p.where, p.text))
        return 0

    # 默认: 检查
    problems = ["%s: %s" % (fn, msg) for fn, msg in ratchet_problems(cur, base)]
    for e in stale:
        problems.append("允许清单第 %d 行没有匹配到任何字符串 (过期了, 请删掉): %s" % (e.line, e.raw))
    for p in dict_problems:
        problems.append("[词典 %s] %s: %s" % (p.kind, p.where, p.text))
    for p in problems:
        print(p)
    print("合计违规 %d 处 (基线 %d 处), 已允许 %d 处; 词典问题 %d 个" % (
        sum(cur.values()), sum(base.values()), sum(len(v) for v in allowed.values()), len(dict_problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
