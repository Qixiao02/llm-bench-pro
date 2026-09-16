#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
iq.py — 智力测试引擎: 官方题集跑题 + 确定性判分 + Wilson 置信区间
对齐发布方口径: GSM8K(0-shot, #### 精确匹配) / MMLU(选项字母匹配) / IFEval(规则校验)
"""
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone

try:
    from . import sinks  # 包内导入
except ImportError:
    import sinks  # server.py 以包目录为 sys.path 顶层导入

# 1.1: 修正 MATH-500 boxed 判分(1.0 的 math500 分数无效)
# 1.2: 思考模式输出预算 32K(超上下文自动减半)、截断(finish_reason=length)单独标记、选择题答案提取加固、
#      记录模型答案与错题尾部; 1.x 思考模式选择题仅 8+8192 token, 长思考会被截断计错
# 1.3: 数学题基础输出预算提高(GSM8K 2048 / MATH-500 4096); 采样参数可配置(思考默认官方推荐 0.6/0.95/20);
#      逐题增量保存、可取消、可续跑; 总体增加科目宏平均; 运行间配对 McNemar 显著性
IQ_VERSION = "1.3.0"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根(包上一级)
THINK_MAX_TOKENS = 32768   # 思考模式 max_tokens 上限(思考与正文共享); 端点上下文不足时自动减半
THINK_TIMEOUT = 1800
PLAIN_TIMEOUT = 300

_NO_TEMPLATE_KWARGS = set()  # 兼容旧引用: 明确拒绝 chat_template_kwargs 的端点
_OPTIONAL_KEYS = ("chat_template_kwargs", "top_k", "seed", "ignore_eos")  # 非 OpenAI 标准字段, 端点不认时剔除
_DROPPED = {}  # url -> 已确认不支持的可选字段集合
_GENERIC_REJECT = re.compile(r"extra_forbidden|extra inputs are not permitted|unrecognized request argument|unexpected keyword", re.I)
_CONTEXT_REJECT = re.compile(r"max_tokens|max_completion_tokens|context length|context_length|maximum context|too long|exceed", re.I)


def dropped_params(url):
    return sorted(_DROPPED.get(url, ()))


def post_chat(url, payload, headers, timeout):
    """POST chat/completions。可选字段(chat_template_kwargs/top_k/seed/ignore_eos)仅在错误信息明确指向该字段
    (或明确为“不允许额外字段”)时剔除重试并按端点记住; 其他 4xx(如超上下文)原样抛出, 错误正文挂在 detail 属性上。"""
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
            e.detail = e.read().decode("utf-8", "replace")[:500]
        except Exception:
            e.detail = ""
        if e.code in (400, 422):
            present = [k for k in _OPTIONAL_KEYS if k in payload]
            named = [k for k in present if k in e.detail]
            if not named and _GENERIC_REJECT.search(e.detail):
                named = present
            if named:
                _DROPPED.setdefault(url, set()).update(named)
                if "chat_template_kwargs" in named:
                    _NO_TEMPLATE_KWARGS.add(url)
                return post_chat(url, payload, headers, timeout)
        raise


def strip_think(text):
    """剥离思考内容: 成对 <think>…</think> 删除; 仅有 </think>(模板预置开标签)时丢弃其前全部内容;
    有 <think> 却未闭合(思考被截断)时视为没有正文。"""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
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


def ask(url, model, prompt, max_tokens, thinking, headers, sampling=None):
    """单题请求。返回 {content, finish, usage, reasoning_chars, max_tokens}。
    思考模式把 max_tokens 提到 THINK_MAX_TOKENS, 若端点因上下文不足拒绝则逐次减半直至题目基础预算。"""
    mt = max(max_tokens, THINK_MAX_TOKENS) if thinking else max_tokens
    params = resolve_sampling(thinking, sampling)
    while True:
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": mt,
                   "chat_template_kwargs": {"enable_thinking": bool(thinking)}}
        payload.update(params)
        try:
            d = post_chat(url, payload, headers, THINK_TIMEOUT if thinking else PLAIN_TIMEOUT)
        except urllib.error.HTTPError as e:
            if e.code in (400, 413, 422) and mt // 2 >= max_tokens and _CONTEXT_REJECT.search(getattr(e, "detail", "")):
                mt //= 2
                continue
            raise
        ch = d["choices"][0]
        msg = ch.get("message") or {}
        raw = msg.get("content") or ""
        reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
        return {"content": strip_think(raw), "finish": ch.get("finish_reason") or "", "usage": d.get("usage") or {},
                "reasoning_chars": len(reasoning) + (len(raw) - len(strip_think(raw))), "max_tokens": mt}


def chat(url, payload, headers, timeout=PLAIN_TIMEOUT):
    d = post_chat(url, payload, headers, timeout)
    msg = d["choices"][0]["message"]
    return strip_think(msg.get("content") or ""), d.get("usage") or {}


# ---------------------------------------------------------------- 提示模板

def prompt_mcq(item):
    lines = [item["q"], ""]
    for letter, c in zip("ABCD", item["choices"]):
        lines.append(f"{letter}. {c}")
    lines.append("")
    lines.append("只输出正确选项的字母（A、B、C 或 D），不要输出任何解释。")
    return "\n".join(lines), 8


def prompt_math(item):
    return (item["q"] + "\n\n请一步步推理，最后单独一行以 \"#### <最终数字答案>\" 的格式给出答案。"), 2048


def prompt_math500(item):
    tail = "\n\n请推理后给出最终答案，并把答案单独放在最后一行，格式：\\boxed{答案}"
    return item["q"] + tail, 4096


def last_boxed(resp):
    """取最后一个 \\boxed{...} 的内容, 支持嵌套花括号; 无则返回 None。"""
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


def _strip_cmd_arg(s, cmd):
    """\\text{abc} -> abc (保留参数去掉命令)。"""
    return re.sub(r"\\" + cmd + r"\{([^{}]*)\}", r"\1", s)


def _norm_ans(s):
    """答案规范化, 对齐 MATH 官方评测 strip_string: 去单位/美元/度/百分号/间距命令, 统一分数与根号写法。"""
    s = str(s).strip().replace("\n", "")
    s = s.replace("\\!", "").replace("\\,", "").replace("\\;", "").replace("\\ ", " ")
    s = re.sub(r"\\[dt]frac", r"\\frac", s)
    s = s.replace("\\left", "").replace("\\right", "")
    s = s.replace("^{\\circ}", "").replace("^\\circ", "")
    s = s.replace("\\$", "").replace("$", "")
    s = re.sub(r"\\(?:text|mbox|mathrm)\{\s+[^{}]*\}\s*$", "", s)  # 末尾单位: 5.4 \text{ cents}
    for cmd in ("text", "textbf", "mathrm", "mbox"):
        s = _strip_cmd_arg(s, cmd)
    s = s.replace("\\%", "").replace("%", "")
    s = s.replace(" .", " 0.").replace("{.", "{0.")
    if s.startswith("."):
        s = "0" + s
    parts = s.split("=")
    if len(parts) == 2 and len(parts[0].strip()) <= 2:  # "x = 5" -> "5"
        s = parts[1]
    s = re.sub(r"\\sqrt(\w)", r"\\sqrt{\1}", s)
    s = s.replace(" ", "")
    s = re.sub(r"\\frac(\d)(\d)", r"\\frac{\1}{\2}", s)
    s = re.sub(r"\\frac(\d)\{", r"\\frac{\1}{", s)
    s = re.sub(r"\\frac\{([^{}]+)\}(\d)", r"\\frac{\1}{\2}", s)
    m = re.fullmatch(r"(-?\d+)/(\d+)", s)
    if m:
        s = "\\frac{%s}{%s}" % m.groups()
    if re.fullmatch(r"-?[\d,]+(\.\d+)?", s):
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


def judge_math500(resp, item):
    cand = last_boxed(resp)
    if cand is None:
        last = [l for l in resp.strip().splitlines() if l.strip()]
        cand = last[-1] if last else ""
        cand = re.split(r"[:：=]", cand)[-1]  # "答案：3" -> "3"
    a, b = _norm_ans(cand), _norm_ans(item["answer"])
    if a == b:
        return True
    try:
        return abs(_to_float(a) - _to_float(b)) < 1e-9
    except (ValueError, ZeroDivisionError):
        return False

def prompt_instruct(item):
    return item["q"] + "\n\n严格按指令要求输出，不要额外解释或客套。", 320


PROMPTS = {"mcq": prompt_mcq, "math": prompt_math, "math500": prompt_math500, "instruct": prompt_instruct}


# ---------------------------------------------------------------- 判分

def judge_mcq(resp, item):
    return extract_mcq(resp) == item["answer"]


_MCQ_EXPLICIT = [
    r"(?:最终答案|正确答案|答案|正确选项|应选|选择|选)\s*(?:是|为|应为|应该是|选)?\s*[:：]?\s*[*_【\[(（]*\s*([A-D])(?![A-Za-z])",
    r"(?i)(?:final\s+)?answer\s*(?:is|:)?\s*[*_\[(]*\s*([A-D])(?![A-Za-z])",
    r"\\boxed\{\s*\(?([A-D])\)?\s*\}",
]


def extract_mcq(resp):
    """选择题答案提取: 整段仅一个字母 > 明确的“答案是X / answer is X / \\boxed{X}”(取最后一处) >
    首行以字母加分隔符开头(如 “B. …” “(C)”)。英文句首冠词 “A careful …” 不会被误判。无法确定返回 None。"""
    text = (resp or "").strip()
    if not text:
        return None
    m = re.match(r"^[\s*_`'\"(（\[【]*([A-D])[\s*_`'\")）\]】.。:：、]*$", text)
    if m:
        return m.group(1)
    for p in _MCQ_EXPLICIT:
        found = re.findall(p, text)
        if found:
            return found[-1]
    first = text.splitlines()[0].strip()
    m = re.match(r"^[*_`(（\[【]*([A-D])(?:[*_`)）\]】]*[.。:：、)]|[*_`)）\]】]+(?:\s|$))", first)
    return m.group(1) if m else None


def extract_math(resp):
    m = re.search(r"####\s*(-?[\d,]+\.?\d*)", resp or "")
    if m:
        return m.group(1).replace(",", "").rstrip(".")
    nums = _nums(resp or "")
    return nums[-1].replace(",", "").rstrip(".") if nums else None


def extract_math500(resp):
    cand = last_boxed(resp or "")
    if cand is None:
        last = [l for l in (resp or "").strip().splitlines() if l.strip()]
        cand = re.split(r"[:：=]", last[-1])[-1] if last else None
    return cand.strip() if cand else None


EXTRACTORS = {"mcq": extract_mcq, "math": extract_math, "math500": extract_math500, "instruct": lambda r: None}


def _nums(s):
    return re.findall(r"-?\d[\d,]*\.?\d*", s)


def judge_math(resp, item):
    gold = str(item["answer"]).replace(",", "").rstrip(".")
    m = re.search(r"####\s*(-?[\d,]+\.?\d*)", resp)
    cand = m.group(1).replace(",", "").rstrip(".") if m else None
    if cand is None and _nums(resp):
        cand = _nums(resp)[-1].replace(",", "").rstrip(".")
    if cand is None:
        return False
    try:
        return abs(float(cand) - float(gold)) < 1e-6
    except ValueError:
        return cand == gold


def judge_instruct(resp, item):
    text = resp.strip()
    for ck in item.get("checks", []):
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
            if t == "json_keys":
                raw = re.sub(r"^```[a-z]*\s*|\s*```$", "", text.strip()).strip()
                obj = json.loads(raw)
                if not all(k in obj for k in v):
                    return False
        except Exception:
            return False
    return True


JUDGES = {"mcq": judge_mcq, "math": judge_math, "math500": judge_math500, "instruct": judge_instruct}


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
    """配对 McNemar 检验双侧 p 值。b = A 对 B 错, c = A 错 B 对。n≤400 用精确二项, 否则连续性校正卡方。"""
    n = b + c
    if n == 0:
        return 1.0
    if n <= 400:
        k = min(b, c)
        return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)
    chi2 = (abs(b - c) - 1) ** 2 / n
    return min(1.0, math.erfc(math.sqrt(chi2 / 2)))


def compare_runs(a, b):
    """两次运行按 (科目, 题号) 配对比较, 只统计双方都有结果的题。返回总体与分科的一致/分歧计数、p 值与准确率差。"""
    def index(doc):
        return {(it["sid"], it["idx"]): bool(it.get("ok")) for it in doc.get("items", [])}
    ia, ib = index(a), index(b)
    keys = sorted(set(ia) & set(ib), key=lambda k: (str(k[0]), k[1]))

    def stats(ks):
        n = len(ks)
        both = sum(1 for k in ks if ia[k] and ib[k])
        a_only = sum(1 for k in ks if ia[k] and not ib[k])
        b_only = sum(1 for k in ks if not ia[k] and ib[k])
        p = mcnemar(a_only, b_only)
        return {"n": n, "a_only": a_only, "b_only": b_only,
                "acc_a": round(100.0 * (both + a_only) / n, 1) if n else None,
                "acc_b": round(100.0 * (both + b_only) / n, 1) if n else None,
                "diff": round(100.0 * (b_only - a_only) / n, 1) if n else None,
                "p": round(p, 4), "significant": bool(n) and p < 0.05}
    subjects = {sid: stats([k for k in keys if k[0] == sid]) for sid in sorted({k[0] for k in keys})}
    return {"same_bank": a.get("bank_id") == b.get("bank_id"), "overall": stats(keys), "subjects": subjects}


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


def run_iq(url, model, api_key="", bank=None, conc=8, outdir=None, tag="",
           framework=None, fw_version=None, subject_ids=None, limit_per_subject=None, thinking=False, sink=None,
           sampling=None, cancel=None, resume=None):
    """跑能力评测。逐题增量保存; cancel(threading.Event)置位后停止派发新题并以 cancelled 状态收尾;
    resume 传入同版本未完成运行的文档时, 跳过已有结果的题目继续。sink 默认写 outdir/<run_id>.json; 返回落地位置。"""
    outdir = outdir or os.path.join(ROOT, "results")
    headers = {"Authorization": "Bearer " + api_key} if api_key else {}
    if resume:
        if resume.get("iq_version") != IQ_VERSION:
            raise ValueError("该运行由评测程序 %s 生成，当前为 %s，判分口径不同，不能续跑，请重新运行"
                             % (resume.get("iq_version"), IQ_VERSION))
        result = resume
        params = result.get("params") or {}
        subject_ids, limit_per_subject = params.get("subject_ids"), params.get("limit_per_subject")
        thinking, conc = bool(result.get("thinking")), result.get("conc") or conc
        sampling = result.get("sampling")
        result["resumed_utc"] = datetime.now(timezone.utc).isoformat()
        for k in ("error", "finished_utc", "overall"):
            result.pop(k, None)
    else:
        run_id = "iq_%s_%s" % (datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"), re.sub(r"[^A-Za-z0-9.-]", "_", model))
        sampling = resolve_sampling(thinking, sampling)
        result = {"kind": "iq", "iq_version": IQ_VERSION, "run_id": run_id, "tag": tag,
                  "url": url, "model": model, "conc": conc,
                  "bank_id": bank["bank_id"], "bank_manifest": bank.get("manifest"),
                  "framework": {"name": framework or "", "version": fw_version or ""},
                  "thinking": bool(thinking), "sampling": sampling,
                  "params": {"subject_ids": subject_ids or None, "limit_per_subject": limit_per_subject or None},
                  "max_tokens_policy": ("思考模式: 上限 %d(超上下文自动减半)" % THINK_MAX_TOKENS) if thinking else "非思考: 按题型基础预算",
                  "started_utc": datetime.now(timezone.utc).isoformat(),
                  "subjects": [], "items": []}
    subjects = bank["subjects"]
    if subject_ids:
        subjects = [s for s in subjects if s["id"] in subject_ids]
    sink = sink or sinks.JsonFileSink(outdir)

    def save():
        dp = dropped_params(url)
        if dp:
            result["ignored_params"] = dp
        sink.save(result)

    total_all = sum(min(len(s["items"]), limit_per_subject or 10**9) for s in subjects)
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
                         "macro_acc": round(sum(s["acc"] for s in subs) / len(subs), 1) if subs else 0,
                         "ci_lo": round(lo * 100, 1), "ci_hi": round(hi * 100, 1),
                         "in_tokens": sum(s["in_tokens"] for s in subs),
                         "out_tokens": sum(s["out_tokens"] for s in subs),
                         "truncated": sum(s.get("truncated", 0) for s in subs),
                         "errors": sum(s.get("errors", 0) for s in subs)}
    result["finished_utc"] = datetime.now(timezone.utc).isoformat()
    result["status"] = "done"
    save()
    plog("总体: %d/%d = %.1f%% (CI %.1f-%.1f, 科目宏平均 %.1f%%) => %s" % (
        tot_c, tot_n, result["overall"]["acc"], lo * 100, hi * 100, result["overall"]["macro_acc"], sink.location))
    return sink.location


def _run_subjects(url, model, headers, subjects, limit_per_subject, conc, thinking, sampling, total_all, result, save, cancel):
    """逐科目跑题: 已有结果的题跳过(续跑); 完成的题实时追加到 result['items'], 每 20 题保存一次;
    科目完成后写入汇总。cancel 置位时撤销未开始的题并抛出 Cancelled(进行中的请求不再等待)。"""
    done = {(r["sid"], r["idx"]) for r in result["items"]}
    finished_subjects = {s["id"] for s in result["subjects"]}
    counter = [len(result["items"])]

    for sub in subjects:
        if sub["id"] in finished_subjects:
            continue
        items = sub["items"][:limit_per_subject] if limit_per_subject else sub["items"]
        stype = sub["type"]
        pending = [(idx, item) for idx, item in enumerate(items) if (sub["id"], idx) not in done]

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
                rec["err"] = ("%s: %s%s" % (type(e).__name__, str(e), (" | " + detail) if detail else ""))[:200]
            else:
                content, usage = r["content"], r["usage"]
                rec.update({"ok": bool(judge(content, item)), "in": usage.get("prompt_tokens", 0),
                            "out": usage.get("completion_tokens", 0), "finish": r["finish"]})
                pred = extract(content)
                if pred is not None:
                    rec["pred"] = str(pred)[:60]
                if r["finish"] == "length":
                    rec["trunc"] = True  # 达到输出上限: 通常是思考未结束, 计为错误但单独标记
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
                    since_save += 1
                    counter[0] += 1
                    if counter[0] % 20 == 0 or counter[0] == total_all:
                        plog("  进度 %d/%d" % (counter[0], total_all))
                if since_save >= 20:
                    save()
                    since_save = 0
                if cancel is not None and cancel.is_set():
                    for f in futures:
                        f.cancel()
                    raise Cancelled()
        finally:
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
