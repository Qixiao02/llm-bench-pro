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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

try:
    from . import sinks  # 包内导入
except ImportError:
    import sinks  # server.py 以包目录为 sys.path 顶层导入

# 1.1: 修正 MATH-500 boxed 判分(1.0 的 math500 分数无效)
# 1.2: 思考模式输出预算 32K(超上下文自动减半)、截断(finish_reason=length)单独标记、选择题答案提取加固、
#      记录模型答案与错题尾部; 1.x 思考模式选择题仅 8+8192 token, 长思考会被截断计错
IQ_VERSION = "1.2.0"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根(包上一级)
THINK_MAX_TOKENS = 32768   # 思考模式 max_tokens 上限(思考与正文共享); 端点上下文不足时自动减半
THINK_TIMEOUT = 1800
PLAIN_TIMEOUT = 300

_NO_TEMPLATE_KWARGS = set()  # 明确拒绝 chat_template_kwargs 的端点
_KWARGS_REJECT = re.compile(r"chat_template_kwargs|extra_forbidden|extra inputs|unrecognized request argument|unexpected keyword", re.I)
_CONTEXT_REJECT = re.compile(r"max_tokens|max_completion_tokens|context length|context_length|maximum context|too long|exceed", re.I)


def post_chat(url, payload, headers, timeout):
    """POST chat/completions。仅当错误信息明确指向 chat_template_kwargs 时才剔除该字段重试并记住;
    其他 4xx(如超上下文)原样抛出, 错误正文挂在异常的 detail 属性上。"""
    if url in _NO_TEMPLATE_KWARGS:
        payload = {k: v for k, v in payload.items() if k != "chat_template_kwargs"}
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
        if e.code in (400, 422) and "chat_template_kwargs" in payload and _KWARGS_REJECT.search(e.detail):
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


def ask(url, model, prompt, max_tokens, thinking, headers):
    """单题请求。返回 {content, finish, usage, reasoning_chars, max_tokens}。
    思考模式把 max_tokens 提到 THINK_MAX_TOKENS, 若端点因上下文不足拒绝则逐次减半直至题目基础预算。"""
    mt = max(max_tokens, THINK_MAX_TOKENS) if thinking else max_tokens
    while True:
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": mt,
                   "temperature": 0, "chat_template_kwargs": {"enable_thinking": bool(thinking)}}
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
    return (item["q"] + "\n\n请一步步推理，最后单独一行以 \"#### <最终数字答案>\" 的格式给出答案。"), 1280


def prompt_math500(item):
    tail = "\n\n请推理后给出最终答案，并把答案单独放在最后一行，格式：\\boxed{答案}"
    return item["q"] + tail, 900


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


_IQ_PROGRESS = None


def plog(msg):
    print(msg, flush=True)
    if _IQ_PROGRESS:
        try:
            _IQ_PROGRESS(str(msg))
        except Exception:
            pass


def run_iq(url, model, api_key="", bank=None, conc=8, outdir=None, tag="",
           framework=None, fw_version=None, subject_ids=None, limit_per_subject=None, thinking=False, sink=None):
    """跑完整智力测试。sink 默认写 outdir/<run_id>.json; 返回落地位置。"""
    outdir = outdir or os.path.join(ROOT, "results")
    headers = {"Authorization": "Bearer " + api_key} if api_key else {}
    subjects = bank["subjects"]
    if subject_ids:
        subjects = [s for s in subjects if s["id"] in subject_ids]

    run_id = "iq_%s_%s" % (datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
                           re.sub(r"[^A-Za-z0-9.-]", "_", model))
    result = {"kind": "iq", "iq_version": IQ_VERSION, "run_id": run_id, "tag": tag,
              "url": url, "model": model, "conc": conc,
              "bank_id": bank["bank_id"], "bank_manifest": bank.get("manifest"),
              "framework": {"name": framework or "", "version": fw_version or ""},
              "thinking": bool(thinking),
              "started_utc": datetime.now(timezone.utc).isoformat(),
              "subjects": [], "items": []}
    sink = sink or sinks.JsonFileSink(outdir)

    def save():
        sink.save(result)

    total_all = sum(min(len(s["items"]), limit_per_subject or 10**9) for s in subjects)
    result["max_tokens_policy"] = ("思考模式: 上限 %d(超上下文自动减半)" % THINK_MAX_TOKENS) if thinking else "非思考: 按题型基础预算"
    plog("== iq v%s | %s | bank=%s | %d 题 | conc=%d | %s ==" % (IQ_VERSION, model, bank["bank_id"], total_all, conc,
                                                            "思考模式(max_tokens≤%d)" % THINK_MAX_TOKENS if thinking else "非思考"))
    result["status"] = "running"
    save()
    try:
        _run_subjects(url, model, headers, subjects, limit_per_subject, conc, thinking, total_all, result, save)
    except BaseException as e:
        result["status"] = "interrupted" if isinstance(e, KeyboardInterrupt) else "failed"
        result["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
        result["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save()
        raise
    tot_c = sum(s["correct"] for s in result["subjects"])
    tot_n = sum(s["n"] for s in result["subjects"])
    lo, hi = wilson(tot_c, tot_n)
    result["overall"] = {"correct": tot_c, "n": tot_n,
                         "acc": round(tot_c / tot_n * 100, 1) if tot_n else 0,
                         "ci_lo": round(lo * 100, 1), "ci_hi": round(hi * 100, 1),
                         "in_tokens": sum(s["in_tokens"] for s in result["subjects"]),
                         "out_tokens": sum(s["out_tokens"] for s in result["subjects"]),
                         "truncated": sum(s.get("truncated", 0) for s in result["subjects"]),
                         "errors": sum(s.get("errors", 0) for s in result["subjects"])}
    result["finished_utc"] = datetime.now(timezone.utc).isoformat()
    result["status"] = "done"
    save()
    plog("总体: %d/%d = %.1f%% (CI %.1f-%.1f) => %s" % (tot_c, tot_n, result["overall"]["acc"],
                                                        lo * 100, hi * 100, sink.location))
    return sink.location


def _run_subjects(url, model, headers, subjects, limit_per_subject, conc, thinking, total_all, result, save):
    """逐科目跑题并判分, 每科结束写入 result 并 save()。"""
    done_count = [0]
    lock = threading.Lock()

    for sub in subjects:
        items = sub["items"][:limit_per_subject] if limit_per_subject else sub["items"]
        stype = sub["type"]
        judge = JUDGES[stype]
        extract = EXTRACTORS[stype]
        prompter = PROMPTS[stype]

        def worker(idx_item):
            idx, item = idx_item
            prompt, mt = prompter(item)
            rec = {"sid": sub["id"], "idx": idx, "ok": False}
            try:
                r = ask(url, model, prompt, mt, thinking, headers)
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
            with lock:
                done_count[0] += 1
                if done_count[0] % 20 == 0 or done_count[0] == total_all:
                    plog("  进度 %d/%d" % (done_count[0], total_all))
            return rec

        with ThreadPoolExecutor(max_workers=conc) as ex:
            results = list(ex.map(worker, enumerate(items)))
        result["items"].extend(results)
        correct = sum(1 for r in results if r["ok"])
        n_err = sum(1 for r in results if r.get("err"))
        n_trunc = sum(1 for r in results if r.get("trunc"))
        n = len(results)
        lo, hi = wilson(correct, n)
        result["subjects"].append({"id": sub["id"], "name": sub["name"], "type": stype,
                                   "n": n, "correct": correct, "acc": round(correct / n * 100, 1) if n else 0,
                                   "ci_lo": round(lo * 100, 1), "ci_hi": round(hi * 100, 1),
                                   "in_tokens": sum(r.get("in", 0) for r in results),
                                   "out_tokens": sum(r.get("out", 0) for r in results),
                                   "truncated": n_trunc, "errors": n_err})
        plog("  [%s] %d/%d = %.1f%% (CI %.1f-%.1f)%s%s" %
             (sub["id"], correct, n, result["subjects"][-1]["acc"], lo * 100, hi * 100,
              ("  截断%d" % n_trunc) if n_trunc else "", ("  请求失败%d" % n_err) if n_err else ""))
        save()
