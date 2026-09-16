#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
iq.py — 能力评测引擎: 标准题集跑题 + 确定性判分 + Wilson 置信区间 + 配对显著性
题型: 选择题(MMLU/ARC/HellaSwag/C-Eval) / GSM8K(####) / MATH-500(\\boxed + 规范化等价判断) / 指令遵循(规则校验)
说明: 生成式 0-shot 中文指令口径, 分数用于同一题集下不同模型/后端的横向对比, 不能与公开榜单直接对照。
"""
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict, deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone

try:
    from . import bankman, sinks  # 包内导入
except ImportError:
    import bankman  # server.py 以包目录为 sys.path 顶层导入
    import sinks

# 1.1: 修正 MATH-500 boxed 判分(1.0 的 math500 分数无效)
# 1.2: 思考模式输出预算 32K、截断单独标记、选择题答案提取加固、记录模型答案与错题尾部
# 1.3: GSM8K/MATH-500 基础预算 2048/4096; 采样可配置(思考默认 0.6/0.95/20); 增量保存/取消/续跑; 宏平均; McNemar
# 1.4: 按题量抽题时在科目内分层轮转(原先 MMLU 每组只考前 1–2 个科目); 选择题提取修正(首行裸字母/大小写/冠词 A/复述选项);
#      MATH-500 等价判断增强(上下标花括号/集合无序/±/°/{,}/单位/根号); GSM8K 取最后一个 ####;
#      指令遵循规则修正; 请求失败可续跑重试, 连续失败中止; 截断仅标记答错的题; 解析上下文上限; 思考开关自检
IQ_VERSION = "1.4.0"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根(包上一级)
THINK_MAX_TOKENS = 32768   # 思考模式 max_tokens 上限(思考与正文共享); 端点上下文不足时按报错收缩
THINK_TIMEOUT = 1800
PLAIN_TIMEOUT = 300
MAX_CONSECUTIVE_ERRORS = 10

_OPTIONAL_KEYS = ("chat_template_kwargs", "top_k", "seed", "ignore_eos")  # 非 OpenAI 标准字段, 端点明确拒绝时剔除
_DROPPED = {}      # url -> 已确认不支持的可选字段
_CTX_LIMIT = {}    # url -> 从报错中解析出的模型上下文长度
_REJECT_WORDS = r"(?:unrecognized|unsupported|unknown|unexpected|extra|invalid|not permitted|not supported|not allowed|forbidden)"
_CONTEXT_REJECT = re.compile(r"context length|context_length|maximum context|max_tokens|max_completion_tokens", re.I)


def dropped_params(url):
    return sorted(_DROPPED.get(url, ()))


def _error_texts(detail):
    """错误正文中的说明文字(排除回显的请求体 input, 避免请求字段名本身被当成“被拒绝的字段”)。"""
    try:
        obj = json.loads(detail)
    except (ValueError, TypeError):
        return [detail or ""], []
    texts, locs = [], []

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("loc"), list):
                locs.append(([str(x) for x in o["loc"]], "%s %s" % (o.get("type", ""), o.get("msg", ""))))
            for k, v in o.items():
                if k == "input":
                    continue
                if isinstance(v, str) and k in ("message", "msg", "error", "detail", "type"):
                    texts.append(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(obj)
    return texts, locs


def _rejected_keys(detail, present):
    texts, locs = _error_texts(detail)
    keys = set()
    for loc, why in locs:
        if re.search(r"extra|forbidden|not permitted|unexpected|unrecognized", why, re.I):
            keys.update(k for k in present if k in loc)
    for t in texts:
        for k in present:
            kk = re.escape(k)
            if re.search(_REJECT_WORDS + r"[^.\n]{0,80}?\b" + kk + r"\b", t, re.I) or \
                    re.search(r"\b" + kk + r"\b['\"]?\s*(?:is|are)?\s*" + _REJECT_WORDS, t, re.I):
                keys.add(k)
    return keys


def post_chat(url, payload, headers, timeout):
    """POST chat/completions。可选字段仅在错误说明明确指向该字段时剔除重试并按端点记住;
    其他 4xx(如超上下文)原样抛出, 错误正文挂在 detail 属性上。"""
    drop = _DROPPED.get(url, set())
    if drop:
        payload = {k: v for k, v in payload.items() if k not in drop}
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            e.detail = e.read().decode("utf-8", "replace")[:2000]
        except Exception:
            e.detail = ""
        if e.code in (400, 422):
            named = _rejected_keys(e.detail, [k for k in _OPTIONAL_KEYS if k in payload])
            if named:
                _DROPPED.setdefault(url, set()).update(named)
                return post_chat(url, payload, headers, timeout)
        raise


def strip_think(text):
    """剥离思考内容: 成对 <think>…</think> 删除; 仅有 </think>(模板预置开标签)时丢弃其前全部内容;
    有 <think> 却未闭合(思考被截断)时视为没有正文。"""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    i = text.rfind("</think>")
    if i >= 0:
        text = text[i + len("</think>"):]
    j = text.find("<think>")
    if j >= 0:
        text = text[:j]
    return text.strip()


def resolve_sampling(thinking, sampling=None):
    """采样参数(幂等)。official/None: 思考模式 temperature 0.6 / top_p 0.95 / top_k 20(Qwen3 官方推荐, 思考时贪心解码易陷入重复),
    非思考模式贪心; greedy: 一律贪心; dict: 自定义 temperature/top_p/top_k。temperature>0 时固定 seed 便于复现。"""
    if isinstance(sampling, dict):
        out = {}
        for k in ("temperature", "top_p", "top_k"):
            v = sampling.get(k)
            if v not in (None, ""):
                out[k] = int(v) if k == "top_k" else float(v)
        out.setdefault("temperature", 0.0)
    elif sampling == "greedy":
        out = {"temperature": 0.0}
    else:
        out = {"temperature": 0.6, "top_p": 0.95, "top_k": 20} if thinking else {"temperature": 0.0}
    if out["temperature"] > 0:
        out["seed"] = 42
    return out


def _context_fit(detail, prompt_tokens_guess):
    """从超上下文报错中解析上下文长度与输入 token 数, 返回可用的 max_tokens 或 None。"""
    m = re.search(r"maximum context length is (\d+)", detail or "", re.I)
    if not m:
        return None, None
    ctx = int(m.group(1))
    used = re.search(r"(\d+)\s+(?:tokens\s+)?in the messages|has\s+(\d+)\s+input tokens|(\d+)\s+input tokens", detail, re.I)
    inp = int(next(g for g in used.groups() if g)) if used else prompt_tokens_guess
    return ctx, max(16, ctx - inp - 32)


def ask(url, model, prompt, max_tokens, thinking, headers, sampling=None):
    """单题请求。返回 {content, finish, usage, reasoning_chars, max_tokens}。
    思考模式 max_tokens 提到 THINK_MAX_TOKENS; 端点报超上下文时按报错中的上下文长度收缩(解析不到才减半), 并按端点缓存。"""
    mt = max(max_tokens, THINK_MAX_TOKENS) if thinking else max_tokens
    guess = len(prompt.encode("utf-8")) // 2 + 64  # 保守估计的输入 token 数(偏大)
    if url in _CTX_LIMIT:
        mt = max(max_tokens, min(mt, _CTX_LIMIT[url] - guess))
    params = resolve_sampling(thinking, sampling)
    tried = set()
    while True:
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": mt,
                   "chat_template_kwargs": {"enable_thinking": bool(thinking), "thinking": bool(thinking)}}
        payload.update(params)
        try:
            d = post_chat(url, payload, headers, THINK_TIMEOUT if thinking else PLAIN_TIMEOUT)
        except urllib.error.HTTPError as e:
            detail = getattr(e, "detail", "")
            if e.code in (400, 413, 422) and _CONTEXT_REJECT.search(detail) and mt not in tried and mt > 16:
                tried.add(mt)
                ctx, fit = _context_fit(detail, guess)
                if ctx:
                    _CTX_LIMIT[url] = ctx
                new = fit if fit and fit < mt else mt // 2
                if new < 16:
                    raise
                mt = new
                continue
            raise
        ch = d["choices"][0]
        msg = ch.get("message") or {}
        raw = msg.get("content") or ""
        reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
        content = strip_think(raw)
        return {"content": content, "finish": ch.get("finish_reason") or "", "usage": d.get("usage") or {},
                "reasoning_chars": len(reasoning) + max(0, len(raw) - len(content)), "max_tokens": mt}


# ---------------------------------------------------------------- 提示模板

def prompt_mcq(item):
    lines = [item["q"], ""]
    for letter, c in zip("ABCD", item["choices"]):
        lines.append(f"{letter}. {c}")
    lines.append("")
    lines.append("只输出正确选项的字母（A、B、C 或 D），不要输出任何解释。")
    return "\n".join(lines), 16


def prompt_math(item):
    return (item["q"] + "\n\n请一步步推理，最后单独一行以 \"#### <最终数字答案>\" 的格式给出答案。"), 2048


def prompt_math500(item):
    tail = "\n\n请推理后给出最终答案，并把答案单独放在最后一行，格式：\\boxed{答案}"
    return item["q"] + tail, 4096


def prompt_instruct(item):
    return item["q"] + "\n\n严格按指令要求输出，不要额外解释或客套。", 320


PROMPTS = {"mcq": prompt_mcq, "math": prompt_math, "math500": prompt_math500, "instruct": prompt_instruct}


# ---------------------------------------------------------------- 选择题

_LETTER_END = r"(?![ \t]*[A-Za-z0-9])"  # 字母后不能紧跟英文单词(排除冠词 “A map…”)
_MCQ_EXPLICIT = [
    r"(?:最终答案|正确答案|答案|正确选项|应选|选择|选)\s*(?:是|为|应为|应该是|选)?\s*[:：]?\s*[*_【\[(（]*\s*([A-D])" + _LETTER_END,
    r"(?i:(?:the\s+)?(?:final\s+|correct\s+|best\s+)?answer)\s*(?i:is|would be|:)?\s*[*_\[(]*\s*(?i:option\s+)?([A-D])" + _LETTER_END,
    r"选项\s*[*_【\[(（]*([A-D])[*_】\])）]*\s*(?:是|为)?(?:正确|对)",
    r"(?i:option)\s+([A-D])\s+(?i:is\s+(?:the\s+)?correct)",
    r"\\boxed\{\s*\(?([A-D])\)?\s*\}",
]


def _plain(s):
    return re.sub(r"[\s*_`\"'“”‘’。．.，,：:;；!！?？()（）【】\[\]]+", "", s or "").lower()


def extract_mcq(resp, item=None):
    """选择题答案提取(按优先级):
    整段只有一个字母 > 明确表述(答案是X / answer is X / 选项X正确 / \\boxed{X}, 取最后一处) >
    首行是裸字母或“字母+分隔符”(如 “C” 换行后写解释、“B. …”) > 回答原文与某个选项内容一致。无法确定返回 None。"""
    text = (resp or "").strip()
    if not text:
        return None
    m = re.match(r"^[\s*_`'\"(（\[【#>]*([A-D])[\s*_`'\")）\]】.。:：、]*$", text)
    if m:
        return m.group(1)
    for p in _MCQ_EXPLICIT:
        found = re.findall(p, text)
        if found:
            return found[-1]
    first = text.splitlines()[0].strip()
    m = re.match(r"^[*_`#>\s(（\[【]*([A-D])(?:[*_`)）\]】]*\s*$|[*_`)）\]】]*[.。:：、)）])", first)
    if m:
        return m.group(1)
    if item and item.get("choices"):
        body = re.sub(r"^(?:最终答案|正确答案|答案|answer)\s*(?:是|为|is)?\s*[:：]?", "", text, flags=re.I)
        norm = _plain(body)
        hits = [l for l, c in zip("ABCD", item["choices"]) if norm and _plain(str(c)) == norm]
        if len(hits) == 1:
            return hits[0]
    return None


def judge_mcq(resp, item):
    return extract_mcq(resp, item) == item["answer"]


# ---------------------------------------------------------------- GSM8K

_NUM = r"-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"


def _clean_num(s):
    return s.replace(",", "").rstrip(".")


def last_boxed(resp):
    """取最后一个 \\boxed{...} 的内容, 支持嵌套花括号; 无则返回 None。"""
    resp = resp or ""
    i = resp.rfind("\\boxed")
    if i < 0:
        return None
    j = resp.find("{", i)
    if j < 0:
        return None
    depth = 0
    for k in range(j, len(resp)):
        if resp[k] == "{":
            depth += 1
        elif resp[k] == "}":
            depth -= 1
            if depth == 0:
                return resp[j + 1:k]
    return None


def extract_math(resp):
    """GSM8K: 最后一个 ####(允许 markdown/$) > \\boxed{} > “答案是 X” > 全文最后一个数字。数字不合并逗号列表。"""
    t = resp or ""
    marks = re.findall(r"####\s*[*$\\{(（]*\s*(" + _NUM + r")", t)
    if marks:
        return _clean_num(marks[-1])
    boxed = last_boxed(t)
    if boxed:
        nums = re.findall(r"(?<![\d.])" + _NUM, boxed)
        if nums:
            return _clean_num(nums[-1])
    ans = re.findall(r"(?:最终答案|答案|answer)\s*(?:是|为|is)?\s*[:：]?\s*[*$]*\s*(" + _NUM + r")", t, re.I)
    if ans:
        return _clean_num(ans[-1])
    nums = re.findall(r"(?<![\d.])" + _NUM, t)
    return _clean_num(nums[-1]) if nums else None


def judge_math(resp, item):
    cand = extract_math(resp)
    if cand is None:
        return False
    gold = _clean_num(str(item["answer"]))
    try:
        return abs(float(cand) - float(gold)) < 1e-6
    except ValueError:
        return cand == gold


# ---------------------------------------------------------------- MATH-500

def _strip_cmd_arg(s, cmd):
    """\\text{abc} -> abc (保留参数去掉命令)。"""
    return re.sub(r"\\" + cmd + r"\{([^{}]*)\}", r"\1", s)


def _norm_ans(s):
    """答案规范化, 以 MATH 官方评测 strip_string 为基础并扩充常见等价写法。"""
    s = str(s).strip().replace("\n", "")
    s = s.replace("\u2212", "-").replace("°", "").replace("\\degree", "").replace("{,}", ",")
    s = s.replace("\\!", "").replace("\\,", "").replace("\\;", "").replace("\\ ", " ")
    s = re.sub(r"\\[dt]frac", r"\\frac", s)
    s = s.replace("\\left", "").replace("\\right", "")
    s = s.replace("^{\\circ}", "").replace("^\\circ", "")
    s = s.replace("\\$", "").replace("$", "")
    s = re.sub(r"(?<=[\d}])\s*\\(?:text|mbox|mathrm)\{\s*[A-Za-z][^{}]*\}\s*$", "", s)  # 末尾英文单位: 5.4 \text{ cents}
    s = re.sub(r"(?<=\d)\s*(?:元|美元|度|个|厘米|米|千米|公里|分钟|小时|秒|天|人|岁|cm|m|km)$", "", s)
    for cmd in ("text", "textbf", "mathrm", "mbox"):
        s = _strip_cmd_arg(s, cmd)
    s = s.replace("\\%", "").replace("%", "")
    s = re.sub(r"^\s*[A-Za-z]\s*\\in\s*", "", s)  # x \in (0,9)
    s = s.replace(" .", " 0.").replace("{.", "{0.")
    if s.startswith("."):
        s = "0" + s
    parts = s.split("=")
    if len(parts) == 2 and len(parts[0].strip()) <= 2:  # "x = 5" -> "5"
        s = parts[1]
    s = re.sub(r"\\sqrt(\d+|[A-Za-z])", r"\\sqrt{\1}", s)
    s = s.replace(" ", "")
    s = re.sub(r"([_^])\{([A-Za-z0-9]+)\}", r"\1\2", s)  # 2516_{8} -> 2516_8, r^{5} -> r^5
    s = re.sub(r"\\frac(\d)(\d)", r"\\frac{\1}{\2}", s)
    s = re.sub(r"\\frac(\d)\{", r"\\frac{\1}{", s)
    s = re.sub(r"\\frac\{([^{}]+)\}(\d)", r"\\frac{\1}{\2}", s)
    m = re.fullmatch(r"(-?\d+)/(\d+)", s)
    if m:
        s = "\\frac{%s}{%s}" % m.groups()
    if re.fullmatch(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?", s):  # 仅千分位才去逗号, 避免 “1,2” 被当成 12
        s = s.replace(",", "")
    s = s.rstrip(".")
    if re.fullmatch(r"-?\d+\.0+", s):
        s = s.split(".")[0]
    return s


def _to_float(s):
    m = re.fullmatch(r"(-?)\\frac\{(-?[\d.]+)\}\{(-?[\d.]+)\}", s)
    if m:
        v = float(m.group(2)) / float(m.group(3))
        return -v if m.group(1) else v
    return float(s)


def _split_top(s):
    """按顶层逗号拆分(忽略括号内的逗号)。"""
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return [x for x in out if x != ""]


def _atom_equal(a, b):
    if a == b:
        return True
    try:
        return abs(_to_float(a) - _to_float(b)) < 1e-9
    except (ValueError, ZeroDivisionError):
        return False


def _collection(s):
    """集合 \\{…\\} -> ('set', 元素) ; 顶层逗号列表 -> ('list', 元素); 其余 None。展开 ±。"""
    kind = None
    inner = s
    if s.startswith("\\{") and s.endswith("\\}"):
        kind, inner = "set", s[2:-2]
    elems = _split_top(inner)
    if kind is None:
        if len(elems) < 2 or "\\cup" in s:
            return None
        kind = "list"
    out = []
    for e in elems:
        if "\\pm" in e:
            out += [e.replace("\\pm", "+"), e.replace("\\pm", "-")]
        else:
            out.append(e)
    return kind, out


def math_equal(pred, gold):
    if pred is None:
        return False
    a, b = _norm_ans(pred), _norm_ans(gold)
    if _atom_equal(a, b):
        return True
    ca, cb = _collection(a), _collection(b)
    if ca and cb and len(ca[1]) == len(cb[1]):
        rest = list(cb[1])
        for x in ca[1]:  # 集合/逗号列表按无序多重集比较(元组题答案带括号, 已由整体字符串比较覆盖)
            hit = next((i for i, y in enumerate(rest) if _atom_equal(x, y)), None)
            if hit is None:
                return False
            rest.pop(hit)
        return True
    return False


def extract_math500(resp):
    cand = last_boxed(resp or "")
    if cand is None:
        last = [l for l in (resp or "").strip().splitlines() if l.strip()]
        cand = re.split(r"[:：=]", last[-1])[-1] if last else None
    return cand.strip() if cand else None


def judge_math500(resp, item):
    return math_equal(extract_math500(resp), item["answer"])


# ---------------------------------------------------------------- 指令遵循

# 规则以代码为准(按题面匹配), 修正题库构建时写入的旧规则; 新题库由 bankman.ifeval_zh_items() 生成同样的规则
_IFEVAL_RULES = {x["q"]: x["checks"] for x in bankman.ifeval_zh_items()}


def judge_instruct(resp, item):
    text = (resp or "").strip()
    for ck in _IFEVAL_RULES.get(item.get("q"), item.get("checks", [])):
        t, v = ck.get("t"), ck.get("v")
        try:
            if t == "max_chars" and len(text) > v:
                return False
            if t == "min_chars" and len(text) < v:
                return False
            if t == "max_words" and len(text.split()) > v:
                return False
            if t == "contains" and v not in text:
                return False
            if t == "not_contains" and v in text:
                return False
            if t == "starts_with" and not text.startswith(v):
                return False
            if t == "ends_with" and not text.endswith(v):
                return False
            if t == "line_count" and text.count("\n") + 1 != v:
                return False
            if t == "regex" and not re.search(v, text):
                return False
            if t in ("json_keys", "json_equals"):
                raw = re.sub(r"^```[A-Za-z]*\s*|\s*```$", "", text).strip()
                obj = json.loads(raw)
                if t == "json_keys" and not (isinstance(obj, dict) and all(k in obj for k in v)):
                    return False
                if t == "json_equals" and obj != v:
                    return False
        except Exception:
            return False
    return True


JUDGES = {"mcq": judge_mcq, "math": judge_math, "math500": judge_math500, "instruct": judge_instruct}
EXTRACTORS = {"mcq": extract_mcq, "math": lambda r, item=None: extract_math(r),
              "math500": lambda r, item=None: extract_math500(r), "instruct": lambda r, item=None: None}


# ---------------------------------------------------------------- 抽题

def select_indices(sub, limit):
    """按题量抽题: 带子科目(sub)的题组在子科目间分层轮转, 保证覆盖面; 返回原题号(升序)。"""
    items = sub["items"]
    n = len(items)
    if not limit or limit >= n:
        return list(range(n))
    groups = OrderedDict()
    for i, it in enumerate(items):
        groups.setdefault(it.get("sub"), deque()).append(i)
    if len(groups) <= 1:
        return list(range(limit))
    out, queues = [], list(groups.values())
    while len(out) < limit:
        for q in queues:
            if q and len(out) < limit:
                out.append(q.popleft())
    return sorted(out)


# ---------------------------------------------------------------- 统计

def wilson(correct, n, z=1.96):
    """Wilson 95% 置信区间。"""
    if n == 0:
        return (0.0, 0.0)
    p = correct / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - m) / d), min(1.0, (c + m) / d))


def mcnemar(b, c):
    """配对 McNemar 检验双侧 p 值。b = A 对 B 错, c = A 错 B 对。n≤5000 精确二项, 否则连续性校正卡方。"""
    n = b + c
    if n == 0:
        return 1.0
    if n <= 5000:
        k = min(b, c)
        return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)
    chi2 = (abs(b - c) - 1) ** 2 / n
    return min(1.0, math.erfc(math.sqrt(chi2 / 2)))


def compare_runs(a, b):
    """两次运行按 (科目, 题号) 配对比较, 只统计双方都有有效结果(非请求失败)的题。题集不同时不给显著性结论。"""
    def index(doc):
        return {(it["sid"], it["idx"]): bool(it.get("ok")) for it in doc.get("items", []) if not it.get("err")}
    same_bank = a.get("bank_id") == b.get("bank_id")
    ia, ib = index(a), index(b)
    keys = sorted(set(ia) & set(ib), key=lambda k: (str(k[0]), k[1]))

    def stats(ks):
        n = len(ks)
        both = sum(1 for k in ks if ia[k] and ib[k])
        a_only = sum(1 for k in ks if ia[k] and not ib[k])
        b_only = sum(1 for k in ks if not ia[k] and ib[k])
        p = mcnemar(a_only, b_only) if same_bank else None
        return {"n": n, "a_only": a_only, "b_only": b_only,
                "acc_a": round(100.0 * (both + a_only) / n, 1) if n else None,
                "acc_b": round(100.0 * (both + b_only) / n, 1) if n else None,
                "diff": round(100.0 * (b_only - a_only) / n, 1) if n else None,
                "p": None if p is None else round(p, 4),
                "significant": None if p is None else (bool(n) and p < 0.05)}
    subjects = {sid: stats([k for k in keys if k[0] == sid]) for sid in sorted({k[0] for k in keys})}
    params_match = (a.get("params") or {}) == (b.get("params") or {})
    return {"same_bank": same_bank, "params_match": params_match, "overall": stats(keys), "subjects": subjects}


def macro_accuracy(subjects):
    """科目宏平均: MMLU 四个分组先按题数合并成一个科目, 避免 MMLU 在宏平均中占 4 份权重。"""
    groups = OrderedDict()
    for s in subjects:
        key = "mmlu" if str(s["id"]).startswith("mmlu") else s["id"]
        g = groups.setdefault(key, [0, 0])
        g[0] += s["correct"]
        g[1] += s["n"]
    accs = [100.0 * c / n for c, n in groups.values() if n]
    return round(sum(accs) / len(accs), 1) if accs else 0


def run_warnings(result):
    """运行后自检: 思考开关是否生效、被端点拒绝的参数、请求失败。"""
    out = []
    valid = [r for r in result["items"] if not r.get("err")]
    with_rc = [r for r in valid if "rc" in r]
    if len(with_rc) >= 10:
        share = sum(1 for r in with_rc if r["rc"] > 0) / len(with_rc)
        if result.get("thinking") and share < 0.2:
            out.append("思考模式可能未生效：仅 %.0f%% 的回答包含思考内容。端点可能不支持 enable_thinking，或模型模板的开关名称不同" % (share * 100))
        if not result.get("thinking") and share > 0.5:
            out.append("非思考模式下仍有 %.0f%% 的回答包含思考内容，思考开关可能未生效，选择题等短输出题可能因输出上限被截断" % (share * 100))
    if result.get("ignored_params"):
        out.append("端点不支持以下参数，已自动去掉：%s" % "、".join(result["ignored_params"]))
    errs = len(result["items"]) - len(valid)
    if errs:
        out.append("%d 题请求失败（计为答错），可续跑重试这些题" % errs)
    return out


class Cancelled(Exception):
    """用户取消运行。"""


_IQ_PROGRESS = None


def plog(msg):
    print(msg, flush=True)
    if _IQ_PROGRESS:
        try:
            _IQ_PROGRESS(str(msg))
        except Exception:
            pass


# ---------------------------------------------------------------- 运行

def run_iq(url, model, api_key="", bank=None, conc=8, outdir=None, tag="",
           framework=None, fw_version=None, subject_ids=None, limit_per_subject=None, thinking=False, sink=None,
           sampling=None, cancel=None, resume=None):
    """跑能力评测。逐题增量保存; cancel(threading.Event)置位后停止派发新题并以 cancelled 状态收尾;
    resume 传入同版本运行文档时: 请求失败的题会重新作答, 其余已有结果的题跳过。sink 默认写 outdir/<run_id>.json。"""
    outdir = outdir or os.path.join(ROOT, "results")
    headers = {"Authorization": "Bearer " + api_key} if api_key else {}
    sink = sink or sinks.JsonFileSink(outdir)
    if resume:
        if resume.get("iq_version") != IQ_VERSION:
            raise ValueError("该运行由评测程序 %s 生成，当前为 %s，判分口径不同，不能续跑，请重新运行"
                             % (resume.get("iq_version"), IQ_VERSION))
        result = resume
        params = result.get("params") or {}
        subject_ids, limit_per_subject = params.get("subject_ids"), params.get("limit_per_subject")
        thinking, conc = bool(result.get("thinking")), result.get("conc") or conc
        sampling = result.get("sampling")
        failed_sids = {r["sid"] for r in result["items"] if r.get("err")}
        result["items"] = [r for r in result["items"] if not r.get("err")]  # 失败的题重新作答
        result["subjects"] = [s for s in result["subjects"] if s["id"] not in failed_sids]  # 对应科目重新汇总
        result["resumed_utc"] = datetime.now(timezone.utc).isoformat()
        for k in ("error", "finished_utc", "overall", "warnings"):
            result.pop(k, None)
        if hasattr(sink, "reset"):
            sink.reset(result)  # 子表只追加: 删除了失败条目后需整体重写
    else:
        run_id = "iq_%s_%s" % (datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"), re.sub(r"[^A-Za-z0-9.-]", "_", model))
        sampling = resolve_sampling(thinking, sampling)
        result = {"kind": "iq", "iq_version": IQ_VERSION, "run_id": run_id, "tag": tag,
                  "url": url, "model": model, "conc": conc,
                  "bank_id": bank["bank_id"], "bank_manifest": bank.get("manifest"),
                  "framework": {"name": framework or "", "version": fw_version or ""},
                  "thinking": bool(thinking), "sampling": sampling,
                  "params": {"subject_ids": subject_ids or None, "limit_per_subject": limit_per_subject or None},
                  "max_tokens_policy": ("思考模式: 上限 %d(超上下文自动收缩)" % THINK_MAX_TOKENS) if thinking else "非思考: 按题型基础预算",
                  "started_utc": datetime.now(timezone.utc).isoformat(),
                  "subjects": [], "items": []}
    subjects = bank["subjects"]
    if subject_ids:
        subjects = [s for s in subjects if s["id"] in subject_ids]

    def save():
        dp = dropped_params(url)
        if dp:
            result["ignored_params"] = dp
        sink.save(result)

    total_all = sum(len(select_indices(s, limit_per_subject)) for s in subjects)
    plog("== iq v%s | %s | bank=%s | %d 题 | conc=%d | %s | 采样 %s%s ==" % (
        IQ_VERSION, result["model"], bank["bank_id"], total_all, conc,
        "思考模式(max_tokens≤%d)" % THINK_MAX_TOKENS if thinking else "非思考",
        json.dumps(sampling, ensure_ascii=False), " | 续跑, 已有 %d 题" % len(result["items"]) if resume else ""))
    result["status"] = "running"
    save()
    try:
        _run_subjects(url, result["model"], headers, subjects, limit_per_subject, conc, thinking, sampling,
                      total_all, result, save, cancel)
    except BaseException as e:
        cancelled = isinstance(e, Cancelled)
        result["status"] = "cancelled" if cancelled else ("interrupted" if isinstance(e, KeyboardInterrupt) else "failed")
        result["error"] = "用户取消" if cancelled else "%s: %s" % (type(e).__name__, str(e)[:300])
        result["warnings"] = run_warnings(result)
        result["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save()
        if cancelled:
            plog("已取消: 已完成 %d 题, 可在页面上续跑" % len(result["items"]))
            return sink.location
        raise
    subs = result["subjects"]
    tot_c = sum(s["correct"] for s in subs)
    tot_n = sum(s["n"] for s in subs)
    lo, hi = wilson(tot_c, tot_n)
    result["overall"] = {"correct": tot_c, "n": tot_n,
                         "acc": round(tot_c / tot_n * 100, 1) if tot_n else 0,
                         "macro_acc": macro_accuracy(subs),
                         "ci_lo": round(lo * 100, 1), "ci_hi": round(hi * 100, 1),
                         "in_tokens": sum(s["in_tokens"] for s in subs),
                         "out_tokens": sum(s["out_tokens"] for s in subs),
                         "truncated": sum(s.get("truncated", 0) for s in subs),
                         "errors": sum(s.get("errors", 0) for s in subs)}
    result["warnings"] = run_warnings(result)
    result["finished_utc"] = datetime.now(timezone.utc).isoformat()
    result["status"] = "done"
    save()
    for w in result["warnings"]:
        plog("  ⚠ " + w)
    plog("总体: %d/%d = %.1f%% (CI %.1f-%.1f, 科目宏平均 %.1f%%) => %s" % (
        tot_c, tot_n, result["overall"]["acc"], lo * 100, hi * 100, result["overall"]["macro_acc"], sink.location))
    return sink.location


def _run_subjects(url, model, headers, subjects, limit_per_subject, conc, thinking, sampling, total_all, result, save, cancel):
    """逐科目跑题: 已有结果的题跳过(续跑); 完成的题实时追加到 result['items'], 每 20 题保存一次; 科目完成后写入汇总。
    cancel 置位时撤销未开始的题并抛出 Cancelled; 连续 MAX_CONSECUTIVE_ERRORS 题请求失败时中止(状态 failed, 可续跑)。"""
    done = {(r["sid"], r["idx"]) for r in result["items"]}
    finished_subjects = {s["id"] for s in result["subjects"]}
    counter = [len(result["items"])]
    consecutive_err = [0]

    for sub in subjects:
        if sub["id"] in finished_subjects:
            continue
        stype = sub["type"]
        chosen = select_indices(sub, limit_per_subject)
        pending = [(idx, sub["items"][idx]) for idx in chosen if (sub["id"], idx) not in done]

        def worker(idx_item, sid=sub["id"], judge=JUDGES[stype], extract=EXTRACTORS[stype], prompter=PROMPTS[stype]):
            idx, item = idx_item
            if cancel is not None and cancel.is_set():
                return None
            prompt, mt = prompter(item)
            rec = {"sid": sid, "idx": idx, "ok": False}
            try:
                r = ask(url, model, prompt, mt, thinking, headers, sampling)
            except Exception as e:
                detail = getattr(e, "detail", "")
                rec["err"] = ("%s: %s%s" % (type(e).__name__, str(e), (" | " + detail[:300]) if detail else ""))[:400]
                return rec
            content, usage = r["content"], r["usage"]
            rec.update({"ok": bool(judge(content, item)), "in": usage.get("prompt_tokens", 0),
                        "out": usage.get("completion_tokens", 0), "finish": r["finish"], "rc": r["reasoning_chars"]})
            if r["max_tokens"] != (max(mt, THINK_MAX_TOKENS) if thinking else mt):
                rec["mt"] = r["max_tokens"]  # 因上下文限制收缩过的输出上限
            pred = extract(content, item)
            if pred is not None:
                rec["pred"] = str(pred)[:60]
            if r["finish"] == "length" and not rec["ok"]:
                rec["trunc"] = True  # 达到输出上限且答错: 通常是思考未结束
            if not rec["ok"]:
                rec["tail"] = content[-240:] if content else ("（无正文，思考 %d 字）" % r["reasoning_chars"])
            return rec

        ex = ThreadPoolExecutor(max_workers=conc)
        futures = {ex.submit(worker, x) for x in pending}
        since_save = 0
        try:
            while futures:
                finished, futures = wait(futures, timeout=1.0, return_when=FIRST_COMPLETED)
                for f in finished:
                    rec = f.result()
                    if rec is None:
                        continue
                    result["items"].append(rec)
                    consecutive_err[0] = consecutive_err[0] + 1 if rec.get("err") else 0
                    since_save += 1
                    counter[0] += 1
                    if counter[0] % 20 == 0 or counter[0] == total_all:
                        plog("  进度 %d/%d" % (counter[0], total_all))
                if since_save >= 20:
                    save()
                    since_save = 0
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                if consecutive_err[0] >= MAX_CONSECUTIVE_ERRORS:
                    last = next(r["err"] for r in reversed(result["items"]) if r.get("err"))
                    raise RuntimeError("连续 %d 题请求失败，已中止（最近错误：%s）。修复端点后可续跑" % (consecutive_err[0], last[:160]))
        finally:
            for f in futures:
                f.cancel()  # 撤销尚未开始的题; 进行中的请求结果不再写入
            ex.shutdown(wait=False)
        recs = [r for r in result["items"] if r["sid"] == sub["id"]]
        correct = sum(1 for r in recs if r["ok"])
        n_err = sum(1 for r in recs if r.get("err"))
        n_trunc = sum(1 for r in recs if r.get("trunc"))
        n = len(recs)
        lo, hi = wilson(correct, n)
        result["subjects"].append({"id": sub["id"], "name": sub["name"], "type": stype,
                                   "n": n, "correct": correct, "acc": round(correct / n * 100, 1) if n else 0,
                                   "ci_lo": round(lo * 100, 1), "ci_hi": round(hi * 100, 1),
                                   "in_tokens": sum(r.get("in", 0) for r in recs),
                                   "out_tokens": sum(r.get("out", 0) for r in recs),
                                   "truncated": n_trunc, "errors": n_err})
        plog("  [%s] %d/%d = %.1f%% (CI %.1f-%.1f)%s%s" %
             (sub["id"], correct, n, result["subjects"][-1]["acc"], lo * 100, hi * 100,
              ("  截断%d" % n_trunc) if n_trunc else "", ("  请求失败%d" % n_err) if n_err else ""))
        save()
