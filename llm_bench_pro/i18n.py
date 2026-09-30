# -*- coding: utf-8 -*-
"""服务端消息的中文 / 英文翻译 (纯标准库, 兼容 Python 3.8)。约定见 CONTRIBUTING.md「服务端消息与翻译」。

做法 (gettext 风格): 以中文原文为键, 中文原文继续留在代码里, 英文放在词典 i18n_en/<模块名>.py 里。

    t("上传的文件太大（{size} MB）", size=mb)       普通句子; 占位符用 {名字}, 值用同名的关键字参数
    tn("{n} 行", n)                                带数量; 英文词条是 (单数, 复数), {n} 默认就是 n
    t("更好", ctx="对比")                          同一个中文在不同场合译法不同: 词典键是 "对比|更好"

中文模式原样返回 (替换占位符); 英文模式查词典, 查不到就回退成中文并记进 MISSING (集合, 不刷屏)。
t / tn 永远不抛异常: 缺参数的占位符原样留着, 格式串有问题时原样返回。

语言的来源, 由高到低:
  1. set_lang() / use_lang() 设的当前线程 (上下文) 的语言: 服务端每个请求按请求头 X-Lang (没有就看 Accept-Language) 设一次,
     后台任务在启动时记下它, 任务线程和任务里的工作线程都沿用 (见 spawn / executor)
  2. set_default_lang() 设的进程语言: 命令行 --lang (preparse_lang)
  3. 环境变量 LLM_BENCH_LANG (zh / en)
  4. 系统区域: LANGUAGE / LC_ALL / LC_MESSAGES / LANG (以 zh 开头用中文, 否则英文); 都没有时 Windows 看用户界面语言
  5. 什么都读不到: DEFAULT_LANG (中文, 即代码里原文的语言)

线程: 语言存在 contextvars 里, 新线程不会继承。凡是要在线程里打日志 / 生成存进结果里的说明文字的地方,
不要直接用 threading.Thread / ThreadPoolExecutor, 改用 spawn() / executor(): 它们在创建线程 (提交任务) 时把当前的语言带过去。
tests/i18n_lint_py.py 会检查这一点。

在函数里调用 t(), 不要在模块级调用 (import 时语言还没定, 会固定成加载时的语言); 模块级常量里要显示的文字改成函数。
"""
import argparse
import contextlib
import contextvars
import functools
import importlib
import os
import re
import string
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

LANGS = ("zh", "en")
SOURCE_LANG = "zh"     # 代码里中文原文的语言: 这个语言不查词典
DEFAULT_LANG = "zh"    # 设置、环境变量、系统区域都读不到时用的语言
ENV_VAR = "LLM_BENCH_LANG"
DICT_PACKAGES = {"en": "i18n_en"}   # 语言 → 词典所在的包 (llm_bench_pro/i18n_en/<模块名>.py, 内容是 ENTRIES = {...})

MISSING = set()        # 英文模式下查不到的词典键 (带语境的是 "语境|原文"); 每个键只记一次
LOAD_ERRORS = []       # 词典文件加载失败的记录 (模块名: 原因); 正常为空, 测试会检查

_LANG = contextvars.ContextVar("llm_bench_lang", default=None)   # 当前线程 (上下文) 的语言; None = 没有单独设置
_process_lang = None                                             # 进程语言 (命令行 --lang)


# ---------------------------------------------------------------- 语言

def normalize_lang(value):
    """"zh" / "zh-CN" / "zh_TW.UTF-8" → "zh"; "en" / "en-US" → "en"; 其他 (含空值、不认识的语言) → None。"""
    if not isinstance(value, str):
        return None
    head = re.split(r"[-_.@]", value.strip().lower(), maxsplit=1)[0]
    return head if head in LANGS else None


def _checked(lang):
    n = normalize_lang(lang)
    if n is None:
        raise ValueError("unsupported language %r (use one of: %s)" % (lang, ", ".join(LANGS)))
    return n


def set_lang(lang):
    """设置当前线程 (上下文) 的语言。None 或 "" 表示取消, 回到进程语言 / 环境变量 / 系统区域。返回设成的语言。"""
    if lang is None or lang == "":
        _LANG.set(None)
        return None
    n = _checked(lang)
    _LANG.set(n)
    return n


@contextlib.contextmanager
def use_lang(lang):
    """with use_lang("en"): ... 里临时换成这个语言 (None 表示不单独指定); 出来后恢复。"""
    token = _LANG.set(_checked(lang) if lang else None)
    try:
        yield
    finally:
        _LANG.reset(token)


def set_default_lang(lang):
    """设置进程语言 (所有没有单独设置语言的线程都用它), 命令行 --lang 用这个。None 表示取消。"""
    global _process_lang
    _process_lang = _checked(lang) if lang else None
    return _process_lang


def _locale_name():
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        v = (os.environ.get(var) or "").strip()
        if not v:
            continue
        v = v.split(":")[0] if var == "LANGUAGE" else v   # LANGUAGE 是 "zh_CN:en" 这样的列表, 取第一个
        if re.split(r"[.@]", v, maxsplit=1)[0].lower() in ("c", "posix"):
            continue   # C / POSIX / C.UTF-8 不是真正选了某种语言 (Docker 和服务器上很常见), 当作没设, 别让中文用户升级后突然看到英文
        return v
    return None


@functools.lru_cache(maxsize=1)
def _windows_ui_lang():
    """Windows 用户界面语言: 中文 "zh", 其他 "en"; 不是 Windows 或读不到返回 None。"""
    if os.name != "nt":
        return None
    try:
        import ctypes
        lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except Exception:
        return None
    return "zh" if (lid & 0x3FF) == 0x04 else "en"   # 低 10 位是主语言, 0x04 = 中文


def system_lang():
    """系统区域的语言 (zh / en); 读不到返回 None。有区域设置时以 zh 开头 (或 chinese) 用中文, 否则英文。"""
    name = _locale_name()
    if name:
        return "zh" if name.lower().startswith(("zh", "chinese")) else "en"
    return _windows_ui_lang()


def current_lang():
    """现在生效的语言: "zh" 或 "en"。来源顺序见文件开头。"""
    v = _LANG.get()
    if v:
        return v
    return _process_lang or normalize_lang(os.environ.get(ENV_VAR)) or system_lang() or DEFAULT_LANG


def html_lang():
    """<html lang="…"> 用的语言标记 (旧版 HTML 报告用)。"""
    return "en" if current_lang() == "en" else "zh-CN"


def _from_accept_language(text):
    """Accept-Language 头 → 第一个认识的语言 (按 q 值从高到低); 没有返回 None。"""
    ranked = []
    for i, part in enumerate(str(text or "").split(",")):
        piece = part.strip().split(";")
        tag, q = piece[0].strip(), 1.0
        for p in piece[1:]:
            p = p.strip()
            if p[:2].lower() == "q=":
                try:
                    q = float(p[2:])
                except ValueError:
                    q = -1.0
        lang = normalize_lang(tag)
        if lang and q > 0:
            ranked.append((-q, i, lang))
    return min(ranked)[2] if ranked else None


def lang_from_headers(headers):
    """请求头 → 语言: X-Lang (zh / en) 优先, 其次 Accept-Language, 都没有 (或不认识) 返回 None。
    headers 是有 get() 的对象 (http.server 的 self.headers)。"""
    get = getattr(headers, "get", None)
    if get is None:
        return None
    return normalize_lang(get("X-Lang")) or _from_accept_language(get("Accept-Language"))


# ---------------------------------------------------------------- 线程

def spawn(target, args=(), kwargs=None, name=None, daemon=True, start=True):
    """创建 (并默认启动) 一个线程, 线程里沿用现在的语言。所有后台线程都要用它, 不要直接 threading.Thread。
    参数和 threading.Thread 一样, daemon 默认 True; 返回 Thread。"""
    ctx = contextvars.copy_context()   # 现在的语言等上下文变量的快照: 之后原线程再改语言, 不影响这个线程
    th = threading.Thread(target=ctx.run, args=(target,) + tuple(args), kwargs=dict(kwargs or {}), name=name, daemon=daemon)
    if start:
        th.start()
    return th


class Executor(ThreadPoolExecutor):
    """线程池: 每个任务在提交时的语言下运行 (submit / map 都是), 池里的工作线程再被别的语言的任务复用也不会串。"""

    def submit(self, fn, /, *args, **kwargs):
        ctx = contextvars.copy_context()   # 每个任务各拷一份: Context 同一时刻只能被一个线程进入
        return super().submit(ctx.run, fn, *args, **kwargs)


def executor(max_workers=None, **kwargs):
    """线程池, 用法同 ThreadPoolExecutor(max_workers=...); 所有线程池都要用它, 不要直接 ThreadPoolExecutor。"""
    return Executor(max_workers=max_workers, **kwargs)


# ---------------------------------------------------------------- 命令行

def preparse_lang(argv=None):
    """在创建 argparse 之前调用: 从 argv (默认 sys.argv[1:]) 里找 --lang xx / --lang=xx, 找到 zh / en 就设成进程语言
    (set_default_lang), 这样 --help 的文字也是这个语言。返回找到的语言, 没有返回 None。不改动 argv。"""
    args = list(sys.argv[1:] if argv is None else argv)
    found, i = None, 0
    while i < len(args):
        a = args[i]
        if a == "--":
            break
        if a == "--lang" and i + 1 < len(args):
            found = normalize_lang(args[i + 1]) or found
            i += 1
        elif a.startswith("--lang="):
            found = normalize_lang(a[len("--lang="):]) or found
        i += 1
    if found:
        set_default_lang(found)
    return found


def add_lang_arg(ap, sub=False):
    """给 argparse 解析器加 --lang zh|en。sub=True 用于子命令解析器 (不覆盖主解析器已经解析到的值)。
    要先调用 preparse_lang(argv), 帮助文字才是对应的语言。"""
    ap.add_argument("--lang", choices=LANGS, default=argparse.SUPPRESS if sub else None,
                    help=t("界面和日志的语言：zh 中文，en 英文（默认按环境变量 LLM_BENCH_LANG，再按系统语言）"))
    return ap


# ---------------------------------------------------------------- 词典

_dict_lock = threading.Lock()
_merged = {}      # 语言 → 合并后的 {键: 词条}
_by_module = {}   # 语言 → {模块名: {键: 词条}}


def _load_modules(lang):
    pkg = DICT_PACKAGES.get(lang)
    out = {}
    if not pkg:
        return out
    here = os.path.dirname(os.path.abspath(__file__))
    prefix = (__package__ + ".") if __package__ else ""   # 包内导入和顶层导入 (server.py 的方式) 各用各的路径
    try:
        names = sorted(fn[:-3] for fn in os.listdir(os.path.join(here, pkg)) if fn.endswith(".py") and not fn.startswith("_"))
    except OSError:
        return out
    for name in names:
        try:
            mod = importlib.import_module("%s%s.%s" % (prefix, pkg, name))
            out[name] = dict(getattr(mod, "ENTRIES", {}))
        except Exception as e:   # 一个词典文件坏了不该让程序崩: 记下来, 这个文件的词条当作没有
            LOAD_ERRORS.append("%s: %s: %s" % (name, type(e).__name__, e))
            out[name] = {}
    return out


def dictionary(lang="en"):
    """某个语言合并后的词典 {键: 词条}; 首次需要时才加载 (中文模式不加载, 不拖慢启动)。"""
    d = _merged.get(lang)
    if d is None:
        with _dict_lock:
            d = _merged.get(lang)
            if d is None:
                mods = _load_modules(lang)
                merged = {}
                for name in sorted(mods):
                    merged.update(mods[name])   # 同一个键在几个文件里都有时后加载的算数 (测试不允许重复)
                _by_module[lang] = mods
                d = _merged[lang] = merged
    return d


def entries_by_module(lang="en"):
    """{模块名: {键: 词条}}, 给测试和检查工具用。"""
    dictionary(lang)
    return _by_module[lang]


def reload_dictionaries():
    """丢掉已加载的词典 (改了词典文件后重新加载; 测试用)。"""
    with _dict_lock:
        _merged.clear()
        _by_module.clear()
        del LOAD_ERRORS[:]
    for name in [m for m in sys.modules if m.split(".")[-2:-1] == [DICT_PACKAGES["en"]]]:
        del sys.modules[name]


# ---------------------------------------------------------------- 翻译

class _Keep(object):
    """format 里缺参数的占位符: 原样留着 {名字} (带格式说明时 {名字:说明}), 一眼能看出是哪个参数漏了。"""
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name

    def __format__(self, spec):
        return "{%s%s}" % (self.name, (":" + spec) if spec else "")

    def __str__(self):
        return "{%s}" % self.name

    __repr__ = __str__


class _Args(dict):
    def __missing__(self, key):
        return _Keep(key)


class _SafeFormatter(string.Formatter):
    """format_map 失败后的逐个占位符处理: 一个占位符有问题不影响其他的。"""

    def get_value(self, key, args, kwargs):
        if isinstance(key, int):
            return _Keep(str(key))
        return kwargs[key] if key in kwargs else _Keep(key)

    def get_field(self, field_name, args, kwargs):
        try:
            return super().get_field(field_name, args, kwargs)
        except (AttributeError, KeyError, IndexError, TypeError, ValueError):
            return _Keep(field_name), field_name

    def format_field(self, value, format_spec):
        try:
            return format(value, format_spec)
        except (ValueError, TypeError):
            return str(value)


def _fill(template, kw):
    """替换 {名字}; {{ 和 }} 是字面的花括号。不抛异常。"""
    if "{" not in template and "}" not in template:
        return template
    try:
        return template.format_map(_Args(kw))
    except Exception:
        try:
            return _SafeFormatter().vformat(template, (), kw)
        except Exception:
            return template


def _entry(key, ctx):
    """词条 (英文模式下的 str 或 (单数, 复数)); 中文模式或查不到返回 None (查不到时记进 MISSING)。"""
    lang = current_lang()
    if lang == SOURCE_LANG:
        return None
    dk = ctx + "|" + key if ctx else key
    v = dictionary(lang).get(dk)
    if v is None or v == "" or v == ():
        MISSING.add(dk)
        return None
    return v


def t(_key, *, ctx=None, **kw):
    """翻译一句话: 键是中文原文, 占位符 {名字} 用同名关键字参数替换; ctx 是语境 (词典键 "语境|原文")。
    中文模式返回原文; 英文模式返回词典里的英文, 查不到回退成中文。
    占位符名字不能是 ctx (语境参数); 字面的花括号写成 {{ }}。"""
    key = _key if isinstance(_key, str) else str(_key)
    v = _entry(key, ctx)
    if isinstance(v, (tuple, list)):
        v = v[0] if v else None
    return _fill(v if isinstance(v, str) else key, kw)


def tn(_key, _n, *, ctx=None, **kw):
    """带数量的句子: 英文词条是 (单数, 复数), _n == 1 用单数; 占位符 {n} 默认就是 _n
    (要千分位之类的显示格式, 自己传 n="3,000")。中文只有一种写法。"""
    key = _key if isinstance(_key, str) else str(_key)
    kw.setdefault("n", _n)
    v = _entry(key, ctx)
    if isinstance(v, (tuple, list)):
        try:
            one = _n == 1
        except Exception:
            one = False
        v = v[0] if one or len(v) < 2 else v[1]
    return _fill(v if isinstance(v, str) else key, kw)
