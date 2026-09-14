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

IQ_VERSION = "1.1.0"  # 1.1: 修正 MATH-500 boxed 判分, 1.0 的 math500 分数无效
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根(包上一级)


_NO_TEMPLATE_KWARGS = set()  # 拒绝 chat_template_kwargs 的端点(400 后自动剔除重试)


def post_chat(url, payload, headers, timeout):
    """POST chat/completions; 端点不认 chat_template_kwargs(400) 时剔除该字段重试并记住。"""
    if url in _NO_TEMPLATE_KWARGS:
        payload = {k: v for k, v in payload.items() if k != "chat_template_kwargs"}
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code in (400, 422) and "chat_template_kwargs" in payload:
            _NO_TEMPLATE_KWARGS.add(url)
            return post_chat(url, payload, headers, timeout)
        raise


def strip_think(text):
    """剥离 <think>…</think>; 仅有 </think>(模板已预置开标签)时丢弃其前全部内容。"""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    i = text.rfind("</think>")
    return (text[i + len("</think>"):] if i >= 0 else text).strip()


def chat(url, payload, headers, timeout=300):
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
    s = str(s).strip()
    for cmd in ("text", "textbf", "mathrm", "mbox"):
        s = _strip_cmd_arg(s, cmd)
    s = re.sub(r"\\[dt]frac", r"\\frac", s)
    s = re.sub(r"\\frac(\d)(\d)", r"\\frac{\1}{\2}", s)
    for tok in ("\\left", "\\right", "\\!", "\\,", "\\;", "\\ ", "$", "^\\circ", "^{\\circ}", "\\%", "%"):
        s = s.replace(tok, "")
    s = s.replace(" ", "").replace(",", "") if re.fullmatch(r"[\d,\s.\-]+", s) else s.replace(" ", "")
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
    m = re.search(r"\b([A-D])\b", resp[:40])
    return bool(m) and m.group(1) == item["answer"]


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
    plog("== iq v%s | %s | bank=%s | %d 题 | conc=%d ==" % (IQ_VERSION, model, bank["bank_id"], total_all, conc))
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
                         "out_tokens": sum(s["out_tokens"] for s in result["subjects"])}
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
        prompter = PROMPTS[stype]
        correct = 0
        in_tok = out_tok = 0

        def worker(idx_item):
            idx, item = idx_item
            prompt, mt = prompter(item)
            if thinking:
                mt += 8192  # 思考 token 与正文共享 max_tokens 预算
            try:
                resp, usage = chat(url, {"model": model, "messages": [{"role": "user", "content": prompt}],
                                          "max_tokens": mt, "temperature": 0,
                                          "chat_template_kwargs": {"enable_thinking": bool(thinking)}}, headers)
                ok = judge(resp, item)
            except Exception as e:
                usage, ok, err = {}, False, str(e)[:100]
            else:
                err = None
            with lock:
                done_count[0] += 1
                if done_count[0] % 20 == 0 or done_count[0] == total_all:
                    plog("  进度 %d/%d" % (done_count[0], total_all))
            if err:
                return {"sid": sub["id"], "idx": idx, "ok": False, "err": err}
            return {"sid": sub["id"], "idx": idx, "ok": ok,
                    "in": usage.get("prompt_tokens", 0), "out": usage.get("completion_tokens", 0)}

        with ThreadPoolExecutor(max_workers=conc) as ex:
            results = list(ex.map(worker, enumerate(items)))
        result["items"].extend(results)
        good = [r for r in results if r["ok"]]
        errors = [r for r in results if r.get("err")]
        correct = len(good)
        in_tok = sum(r.get("in", 0) for r in results)
        out_tok = sum(r.get("out", 0) for r in results)
        n = len(results)
        lo, hi = wilson(correct, n)
        result["subjects"].append({"id": sub["id"], "name": sub["name"], "type": stype,
                                   "n": n, "correct": correct, "acc": round(correct / n * 100, 1) if n else 0,
                                   "ci_lo": round(lo * 100, 1), "ci_hi": round(hi * 100, 1),
                                   "in_tokens": in_tok, "out_tokens": out_tok})
        plog("  [%s] %d/%d = %.1f%% (CI %.1f-%.1f)%s" %
             (sub["id"], correct, n, result["subjects"][-1]["acc"], lo * 100, hi * 100,
              ("  错误%d" % len(errors)) if errors else ""))
        save()
