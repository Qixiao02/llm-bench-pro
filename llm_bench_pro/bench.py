#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llm-bench-pro — LLM 推理专业基准测试引擎
纯标准库实现，可直接在生产服务器运行，测量 OpenAI 兼容端点。

测试维度:
  1. Prefill 阶梯    TTFT / prefill 吞吐 随上下文长度 (1K→128K) 的曲线
  2. 单流解码        中/英内容 TPOT、ITL 分位数 (p50/p95/p99)、抖动、乱序检查
  3. 并发阶梯        聚合吞吐、单流吞吐、TTFT 分位数、成功率 (1→64)
  4. 长上下文驻留    32K/64K 上下文内解码稳定性 (可选)
  5. 框架指标        抓取 vLLM /metrics: KV 占用、前缀缓存命中、运行/排队数
输出: results/run_<时间戳>_<模型>.json (增量保存, 崩溃安全)
"""
import argparse
import base64
import copy
import functools
import io
import json
import os
import random
import re
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

try:
    from . import sinks, vision_assets  # 包内导入: python -m llm_bench_pro.bench
except ImportError:
    import sinks  # server.py 以包目录为 sys.path 顶层导入
    import vision_assets

# 1.3: 业务场景改为可插拔任务模板(对话问答/代码/结构化抽取/RAG/图片理解/自定义任务集); 1.2 的回放机制不变
# 1.4: 图片理解默认用内置示例图片(每张图配只问图里内容的提示词), 发送前检查图片(太小/损坏的不发);
#      自定义任务集与回放逐行检查格式; HTTP 错误记下服务端返回的原因
# 1.5: 长输入按被测模型的实际 token 数拼。1.4 及以前按「每句 77.5 token」估算, 新一代分词器(如 Qwen3)上每句只有
#      35 token 左右, 各档实际长度只有标称的 45%; 现在每次测试开始时实测一次再拼(长度阶梯 / 长输入并发 / 超长输入 /
#      预热 / 看资料回答), 结果里记下校准值和每档的目标长度
BENCH_VERSION = "1.5.0"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根(包上一级)

_PROGRESS_CB = None
_REQ_EXTRA = {}          # 本次运行附加到每个请求的字段(如 ignore_eos); 同一时刻只有一个性能测试
_CANCEL = None           # threading.Event; 置位后在下一个检查点停止
_NO_IGNORE_EOS = set()   # 明确不支持 ignore_eos 的端点


class Cancelled(Exception):
    """用户取消运行。"""


def check_cancel():
    if _CANCEL is not None and _CANCEL.is_set():
        raise Cancelled()


def _sleep_cancel(seconds):
    """可中断睡眠: 每 0.2s 检查一次取消, 取消立即抛出。"""
    end = time.perf_counter() + seconds
    while True:
        left = end - time.perf_counter()
        if left <= 0:
            return
        check_cancel()
        time.sleep(min(0.2, left))


def plog(msg):
    print(msg)
    if _PROGRESS_CB:
        try:
            _PROGRESS_CB(str(msg))
        except Exception:
            pass



ZH_UNIT = "人工智能与大语言模型技术综述。深度学习架构、注意力机制、模型量化与推理优化、 speculative decoding 投机采样、KV cache 缓存与显存管理。 "
EN_PROMPT = ("Write a production-quality Python quicksort implementation with type hints, "
             "detailed docstrings, and 3 pytest unit tests covering edge cases.")
PREFILL_HEAD = "以下是一段技术文本（批次 %d-%d），请仔细阅读后用一句话总结主题：\n"
UNIT_GUESS = 77.5        # ZH_UNIT 每句 token 数的旧估算(老一代分词器约一字一 token); 只在校准不成时用
CAL_REPS = (8, 40)       # 校准用的两个句数
_LEN_LABEL = re.compile(r"^(\d+(?:\.\d+)?)K$")


def label_tokens(label):
    """长度档位标签 -> 目标 token 数: "32K" -> 32000; 不是这种写法的返回 None。"""
    m = _LEN_LABEL.match(str(label or ""))
    return int(round(float(m.group(1)) * 1000)) if m else None


# ---------------------------------------------------------------- HTTP 基础

def http_json(url, payload, headers, timeout=900):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


class HTTPStatusError(urllib.error.HTTPError):
    """HTTP 错误 + 服务端返回的原因。str() 形如 'HTTP 400: {"error": {"message": "..."}}',
    失败记录里能直接看出是模型不支持、参数不对还是图片有问题; 仍是 HTTPError 子类, 原有的异常处理不变。"""

    def __init__(self, url, code, msg, hdrs, detail):
        # 给一个内存里的 fp: Python 3.8 在 fp 为 None 时不初始化响应对象部分, 之后读属性会出错
        super().__init__(url, code, msg, hdrs, io.BytesIO(detail.encode("utf-8")))
        self.detail = detail

    def __str__(self):
        return "HTTP %s: %s" % (self.code, self.detail or self.msg or "")


ERR_MAX = 320  # 失败记录里每条错误最多保留的字数: 状态码 + 服务端原因(300 字)


def _error_brief(text, headers=None, limit=300):
    """服务端错误正文 -> 一行摘要: 去掉 HTML 标签和换行, 隐去请求里的密钥(有的网关会原样回显), 截取前 limit 字。"""
    t = text or ""
    if t.lstrip()[:1] == "<":
        t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", t)
        t = re.sub(r"<[^>]+>", " ", t)
    t = " ".join(t.split())
    for v in (headers or {}).values():
        v = str(v)
        secret = v.split(None, 1)[-1] if v[:7].lower() == "bearer " else v
        if len(secret) >= 8:
            t = t.replace(secret, "***")
    t = re.sub(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}", "Bearer ***", t)
    t = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}", "sk-***", t)
    return t[:limit]


def stream_call(url, payload, headers, timeout=900, apply_req_extra=True):
    """流式调用, 返回精确的时间戳序列 (SSE 逐 chunk 解析)。
    apply_req_extra=False: 不注入 ignore_eos 等基准附加字段(业务/回放场景需要真实生成行为)。"""
    check_cancel()
    extra = _REQ_EXTRA if apply_req_extra else {}
    payload = {**extra, **payload, "stream": True, "stream_options": {"include_usage": True}}
    if url in _NO_IGNORE_EOS:
        payload.pop("ignore_eos", None)
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **headers})
    t0 = time.perf_counter()
    ttft, stamps, usage, chunks = None, [], {}, 0
    texts = []
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", "replace")[:4000] if e.fp else ""
        except Exception:  # 读正文时连接断开: 只记状态码
            detail = ""
        if e.code in (400, 422) and "ignore_eos" in payload and "ignore_eos" in detail:
            _NO_IGNORE_EOS.add(url)  # 端点不支持固定输出长度: 关闭后重试, 结果中会记录
            plog("  端点不支持 ignore_eos, 已关闭固定输出长度")
            return stream_call(url, {k: v for k, v in payload.items() if k not in ("stream", "stream_options")},
                               headers, timeout, apply_req_extra)
        raise HTTPStatusError(url, e.code, e.msg, e.hdrs, _error_brief(detail, headers)) from None
    with resp as r:
        buf = b""
        for raw in r:
            buf += raw
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line.startswith(b"data: "):
                    continue
                data = line[6:]
                if data == b"[DONE]":
                    continue
                try:
                    d = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if d.get("usage"):
                    usage = d["usage"]
                ch = d.get("choices") or []
                if ch:
                    delta = ch[0].get("delta") or {}
                    piece = delta.get("content")
                    # 推理模型的思考 token 走 reasoning_content, 同样计入首 token 与解码时间戳
                    if piece or delta.get("reasoning_content") or delta.get("reasoning") or delta.get("tool_calls"):
                        now = time.perf_counter()
                        chunks += 1
                        if ttft is None:
                            ttft = now - t0
                        stamps.append(now)
                    if piece:
                        texts.append(piece)
    if not stamps:
        raise RuntimeError("empty stream (no content/reasoning deltas)")
    return {"ttft": ttft, "stamps": stamps, "wall": time.perf_counter() - t0,
            "usage": usage, "chunks": chunks, "text": "".join(texts)}


def pct(values, p):
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def derive(sample):
    """从一次流式采样派生全部单流指标。"""
    u = sample["usage"]
    out_tok = u.get("completion_tokens") or 0
    in_tok = u.get("prompt_tokens") or 0
    stamps = sample["stamps"]
    decode_span = max(stamps[-1] - stamps[0], 1e-6) if len(stamps) > 1 else 1e-6  # 全部 chunk 同时到达时避免除零
    itls = [stamps[i] - stamps[i - 1] for i in range(1, len(stamps))]
    return {
        "in_tokens": in_tok, "out_tokens": out_tok,
        "ttft_s": round(sample["ttft"], 4) if sample["ttft"] else None,
        "wall_s": round(sample["wall"], 3),
        "decode_span_s": round(decode_span, 3),
        "prefill_tps": round(in_tok / max(sample["ttft"], 1e-6), 1) if sample["ttft"] else None,
        "decode_tps": round((out_tok - 1) / decode_span, 2) if out_tok > 1 else None,
        "tpot_ms": round(decode_span / max(out_tok - 1, 1) * 1000, 2) if out_tok > 1 else None,
        "itl_p50_ms": round(pct(itls, 50) * 1000, 2) if itls else None,
        "itl_p95_ms": round(pct(itls, 95) * 1000, 2) if itls else None,
        "itl_p99_ms": round(pct(itls, 99) * 1000, 2) if itls else None,
        "itl_jitter_ms": round(statistics.pstdev(itls) * 1000, 2) if len(itls) > 2 else None,
        "spec_burst": round(out_tok / max(len(stamps), 1), 2),  # 每 chunk 平均 token 数, >1 提示投机采样生效
    }


# ---------------------------------------------------------------- 框架指标抓取

METRIC_KEYS = {
    "gpu_cache_usage": ("vllm:kv_cache_usage_perc", "vllm:gpu_cache_usage_percent"),
    "requests_running": ("vllm:num_requests_running",),
    "requests_waiting": ("vllm:num_requests_waiting",),
    "prefix_hits": ("vllm:prefix_cache_hits_total",),
    "prefix_queries": ("vllm:prefix_cache_queries_total",),
}


def scrape_metrics(metrics_url, headers):
    """解析 Prometheus 文本格式(含 {label} 行), 提取关键框架指标原始值。"""
    out = {"t": round(time.time(), 1)}
    try:
        req = urllib.request.Request(metrics_url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as r:
            text = r.read().decode()
    except Exception:
        return out
    for name, keys in METRIC_KEYS.items():
        for key in keys:
            m = re.search(re.escape(key) + r'(?:[{][^}]*[}])?\s+([0-9.eE+-]+)', text)
            if m:
                out[name] = float(m.group(1))
                break
    return out


class MetricsRecorder:
    def __init__(self, url, headers, enabled):
        self.url, self.headers, self.enabled = url, headers, enabled
        self.samples = []
        if enabled:
            self._stop = threading.Event()
            self._th = threading.Thread(target=self._loop, daemon=True)
            self._th.start()

    def _loop(self):
        while not self._stop.wait(1.0):
            self.samples.append(scrape_metrics(self.url, self.headers))

    def close(self):
        if self.enabled:
            self._stop.set()
            self._th.join(timeout=3)
        # prefix 命中率: counter 差值 -> 窗口内命中率(%)
        base = next((s for s in self.samples if s.get("prefix_queries") is not None), None)
        if base:
            h0, q0 = base.get("prefix_hits") or 0.0, base["prefix_queries"]
            for s in self.samples:
                h, q = s.get("prefix_hits"), s.get("prefix_queries")
                s["prefix_cache_hit"] = round((h - h0) / (q - q0) * 100, 2) if (h is not None and q and q > q0) else None
        return self.samples


# ---------------------------------------------------------------- 长输入的长度校准

def _guess(reason, samples=None):
    out = {"method": "guess", "unit_tokens": UNIT_GUESS, "overhead_tokens": 0, "error": reason}
    if samples:
        out["samples"] = samples
    return out


def _fit(samples):
    """两点 (句数或段数, 实际输入 token) -> (每单位 token, 其余部分 token)。"""
    (n1, t1), (n2, t2) = samples
    unit = (t2 - t1) / float(n2 - n1)
    return unit, t1 - unit * n1


def calibrate_prompt(url, headers, model):
    """实测 ZH_UNIT 在被测模型上的 token 数: 发两个只生成 1 个 token 的请求(ZH_UNIT 分别重复 8 次和 40 次),
    按服务返回的实际输入 token 数算出每句多少 token, 以及说明文字 + 对话模板多少 token。
    服务没返回用量、或结果明显不合理时, 退回旧估算(每句 77.5)并在结果里注明原因。"""
    nonce = int(time.time() * 1000) % 1000000
    samples = []
    try:
        for reps in CAL_REPS:
            s = stream_call(url, {"model": model, "max_tokens": 1, "temperature": 0,
                                  "messages": [{"role": "user", "content": PREFILL_HEAD % (nonce, reps) + ZH_UNIT * reps}]},
                            headers, timeout=120)
            samples.append([reps, derive(s)["in_tokens"]])
    except Cancelled:
        raise
    except Exception as e:
        return _guess("校准请求失败：%s" % str(e)[:200], samples)
    unit, overhead = _fit(samples)
    if not (2 <= unit <= 400) or not (-50 <= overhead <= 4000):
        return _guess("服务返回的输入 token 数不随长度变化（可能没有返回真实用量）", samples)
    return {"method": "usage", "unit_tokens": round(unit, 3), "overhead_tokens": max(0, int(round(overhead))),
            "samples": samples}


# 服务以「上下文超长」拒绝请求时的说法(vLLM / SGLang / llama.cpp / TGI / OpenAI 等)
_CTX_ERR = re.compile(r"maximum context|context (length|size|window)|max_model_len|max_position|too long|"
                      r"exceeds? the (model|available)|must be <=|prompt is too long", re.I)


class ContextOverflow(Exception):
    """这一档超过了模型的最大上下文。"""


def ctx_overflow(e):
    """HTTP 400 / 413 / 422 且服务说的是上下文超长 -> 大白话原因; 其他错误返回 None。"""
    if isinstance(e, urllib.error.HTTPError) and e.code in (400, 413, 422) and _CTX_ERR.search(str(e)):
        return "超过模型的最大上下文（服务返回：%s）" % str(e)[:160]
    return None


def fit_context(ladder, max_len, out_tok, phase_id):
    """去掉放不下的档位(目标长度 + 输出 > 最大上下文): 返回 (保留的档位, 跳过记录)。"""
    keep, skipped = [], []
    for item in ladder:
        label, _, target = item
        if max_len and target and target + out_tok > max_len:
            skipped.append({"phase": phase_id, "label": label,
                            "reason": "超过模型的最大上下文（%d token）" % max_len})
        else:
            keep.append(item)
    return keep, skipped


def reps_for(tokens, cal):
    """目标 token 数 -> ZH_UNIT 重复几句。"""
    return max(1, int(round((tokens - cal["overhead_tokens"]) / cal["unit_tokens"])))


def resolve_ladder(ladder, cal):
    """长度档位 -> [(标签, 句数, 目标 token)]。档位写成 "32K" 这类标签时按校准结果算句数;
    旧的自定义套件文件里的 [标签, 句数] 同样按标签重算(原句数是按旧估算写的); 认不出长度的标签保留原句数。"""
    out = []
    for item in ladder:
        label, reps = (item, None) if isinstance(item, str) else (item[0], item[1] if len(item) > 1 else None)
        target = label_tokens(label)
        out.append((label, reps_for(target, cal), target) if target else (label, max(1, int(reps or 1)), None))
    return out


def _cal_text(cal):
    if cal["method"] == "usage":
        return "每句 %.1f token，说明文字和对话模板 %d token（实测）" % (cal["unit_tokens"], cal["overhead_tokens"])
    return "没能校准，按旧估算每句 %.1f token（%s）" % (cal["unit_tokens"], cal.get("error") or "")


# ---------------------------------------------------------------- 测试阶段

def phase_prefill(url, headers, model, ladder, out_tok, rep):
    """上下文阶梯: 每档重复 rep 次取中位数; 唯一批次号避免前缀缓存命中虚高。
    ladder: resolve_ladder 的结果 [(标签, 句数, 目标 token)]。"""
    points, skipped = [], []
    session_nonce = int(time.time() * 1000) % 1000000
    for i, (label, reps, target) in enumerate(ladder):
        check_cancel()
        runs = []
        try:
            for seq in range(rep):
                prompt = PREFILL_HEAD % (session_nonce, seq) + (ZH_UNIT * reps)
                s = stream_call(url, {"model": model, "messages": [{"role": "user", "content": prompt}],
                                      "max_tokens": out_tok, "temperature": 0}, headers)
                runs.append(derive(s))
        except urllib.error.HTTPError as e:
            why = ctx_overflow(e)
            if not why:
                raise
            skipped += [{"phase": "prefill", "label": x[0], "reason": why} for x in ladder[i:]]  # 更长的也放不下
            plog("  %s 及更长的档位跳过: %s" % (label, why))
            break
        ttfts = [r["ttft_s"] for r in runs if r["ttft_s"]]
        tps = [r["prefill_tps"] for r in runs if r["prefill_tps"]]
        points.append({
            "label": label, "target_tokens": target, "in_tokens": runs[0]["in_tokens"],
            "ttft_med_s": round(statistics.median(ttfts), 3) if ttfts else None,
            "prefill_tps_med": round(statistics.median(tps), 1) if tps else None,
            "runs": runs,
        })
        plog("  %-6s in=%-7d ttft=%6.2fs  prefill=%8.0f t/s" %
              (label, points[-1]["in_tokens"], points[-1]["ttft_med_s"] or 0, points[-1]["prefill_tps_med"] or 0))
    out = {"id": "prefill", "name": "Prefill 阶梯", "points": points}
    if skipped:
        out["skipped"] = skipped
    return out


def phase_decode(url, headers, model, out_tok, rep):
    """单流解码: 中文(内容不敏感验证) + 英文代码。"""
    cases = []
    for lang, prompt in (("zh", "请详细介绍大语言模型推理优化的主要技术方向，覆盖量化、投机采样、KV cache 管理与并行策略。"),
                         ("en", EN_PROMPT)):
        runs, texts = [], []
        for _ in range(rep):
            s = stream_call(url, {"model": model, "messages": [{"role": "user", "content": prompt}],
                                  "max_tokens": out_tok, "temperature": 0}, headers)
            runs.append(derive(s))
        tps = [r["decode_tps"] for r in runs if r["decode_tps"]]
        itl50 = [r["itl_p50_ms"] for r in runs if r["itl_p50_ms"] is not None]
        burst = [r["spec_burst"] for r in runs]
        cases.append({
            "lang": lang, "out_tokens": runs[0]["out_tokens"],
            "decode_tps_med": round(statistics.median(tps), 1) if tps else None,
            "decode_tps_best": round(max(tps), 1) if tps else None,
            "itl_p50_ms_med": round(statistics.median(itl50), 2) if itl50 else None,
            "spec_burst_med": round(statistics.median(burst), 2),
            "runs": runs,
        })
        plog("  %s  decode=%7.1f t/s  itl_p50=%6.1fms  burst=%.2f tok/chunk" %
              (lang, cases[-1]["decode_tps_med"] or 0, cases[-1]["itl_p50_ms_med"] or 0, cases[-1]["spec_burst_med"]))
    return {"id": "decode", "name": "单流解码", "cases": cases}


def phase_concurrency(url, headers, model, conc_list, out_tok, per_conc):
    """并发阶梯: 屏障同步起跑, 每档 per_conc 轮; 聚合吞吐 = 总 token / 轮墙钟。"""
    points = []
    for conc in conc_list:
        check_cancel()
        all_runs, ok, fail, agg_list = [], 0, 0, []
        for _ in range(per_conc):
            barrier = threading.Barrier(conc)
            lock, results = threading.Lock(), []

            def worker(i):
                try:
                    barrier.wait(timeout=60)
                except threading.BrokenBarrierError:
                    return
                prompt = "请编写一个实用的 Python 工具函数（编号 %d），包含文档字符串、类型标注和测试用例。" % i
                try:
                    s = stream_call(url, {"model": model, "messages": [{"role": "user", "content": prompt}],
                                          "max_tokens": out_tok, "temperature": 0}, headers)
                    with lock:
                        results.append(derive(s))
                except Exception as e:
                    with lock:
                        results.append({"error": str(e)[:ERR_MAX]})

            round_t0 = time.perf_counter()
            with ThreadPoolExecutor(max_workers=conc) as ex:
                list(ex.map(worker, range(conc)))
            round_wall = time.perf_counter() - round_t0
            good = [r for r in results if "error" not in r]
            ok += len(good)
            fail += len([r for r in results if "error" in r])
            all_runs.extend(good)
            round_tokens = sum(r["out_tokens"] for r in good)
            agg_list.append(round_tokens / round_wall if round_wall > 0 else 0.0)
        ttfts = [r["ttft_s"] for r in all_runs if r["ttft_s"]]
        tps = [r["decode_tps"] for r in all_runs if r["decode_tps"]]
        points.append({
            "conc": conc, "ok": ok, "fail": fail,
            "agg_tps": round(statistics.median(agg_list), 1) if agg_list else 0,
            "per_stream_tps_med": round(statistics.median(tps), 1) if tps else None,
            "ttft_p50_s": round(pct(ttfts, 50), 3) if ttfts else None,
            "ttft_p95_s": round(pct(ttfts, 95), 3) if ttfts else None,
        })
        plog("  conc=%-3d ok/fail=%d/%d  agg=%8.1f t/s  per_stream=%7.1f  ttft_p95=%6.2fs" %
              (conc, ok, fail, points[-1]["agg_tps"], points[-1]["per_stream_tps_med"] or 0,
               points[-1]["ttft_p95_s"] or 0))
    return {"id": "concurrency", "name": "并发阶梯", "points": points}


def phase_prefill_conc(url, headers, model, ladder, conc, out_tok, max_attempts=3, retry_pause_s=30.0):
    """提示词长度阶梯 × 并发矩阵: 每档并发起跑, 记录 TTFT/ITL/聚合吞吐/成功率, 并汇总分位数。
    有失败时整格重跑(基础设施型失败), 留痕 failed_attempts。"""
    points = []

    def run_label(reps):
        nonce = int(time.time() * 1000) % 1000000  # 每次尝试新批次号: 重跑不得命中前缀缓存
        barrier = threading.Barrier(conc)
        lock, results = threading.Lock(), []

        def worker(i):
            try:
                barrier.wait(timeout=60)
            except threading.BrokenBarrierError:
                return
            prompt = ("以下是技术参考资料（批次 %d-%d），请阅读后用两句话总结要点：" % (nonce, i)) + chr(10) + (ZH_UNIT * reps)
            try:
                s = stream_call(url, {"model": model, "messages": [{"role": "user", "content": prompt}],
                                      "max_tokens": out_tok, "temperature": 0}, headers)
                with lock:
                    results.append(derive(s))
            except Exception as e:
                with lock:
                    results.append({"error": str(e)[:ERR_MAX], "ctx": ctx_overflow(e)})

        with ThreadPoolExecutor(max_workers=conc) as ex:
            list(ex.map(worker, range(conc)))
        good = [r for r in results if "error" not in r]
        ctx = next((r["ctx"] for r in results if r.get("ctx")), None)
        if ctx and not good:
            raise ContextOverflow(ctx)  # 放不下不是临时故障, 不整格重跑
        bad = len(results) - len(good)
        point = None
        if good and any(r["ttft_s"] for r in good):
            in_tot = sum(r["in_tokens"] for r in good)
            out_tot = sum(r["out_tokens"] for r in good)
            ttfts = [r["ttft_s"] for r in good if r["ttft_s"]]
            max_ttft = max(ttfts)
            max_dspan = max(r["decode_span_s"] for r in good)
            itls = [r["itl_p50_ms"] for r in good if r["itl_p50_ms"] is not None]
            point = {
                "label": "", "in_tokens": good[0]["in_tokens"], "ok": len(good), "fail": bad,
                "ttft_avg_ms": round(1000 * sum(ttfts) / len(ttfts), 1),
                "ttft_max_ms": round(1000 * max_ttft, 1),
                "itl_avg_ms": round(sum(itls) / len(itls), 2) if itls else None,
                "prefill_tps_agg": round(in_tot / max(max_ttft, 1e-6), 1),
                "decode_tps_agg": round(out_tot / max(max_dspan, 1e-6), 1) if out_tot > 1 else None,
                "stream_prefill_tps": [round(r["in_tokens"] / r["ttft_s"], 1) for r in good if r["ttft_s"]],
                "stream_decode_tps": [r["decode_tps"] for r in good if r["decode_tps"]],
            }
        return {"point": point, "ok": len(good), "fail": bad, "total": conc,
                "errors": [r["error"] for r in results if "error" in r][:3]}

    skipped = []
    for i, (label, reps, target) in enumerate(ladder):
        check_cancel()
        try:
            rec = _retry_cell(lambda r=reps: run_label(r), "矩阵 %s" % label, max_attempts, retry_pause_s)
        except ContextOverflow as e:
            skipped += [{"phase": "prefill_conc", "label": x[0], "reason": str(e)} for x in ladder[i:]]
            plog("  %s 及更长的档位跳过: %s" % (label, e))
            break
        if rec["point"]:
            rec["point"]["label"] = label
            rec["point"]["target_tokens"] = target
            points.append(rec["point"])
            plog("  %-5s in=%-6d ttft_avg=%7.1fms  prefill_agg=%8.0f t/s  decode_agg=%7.1f t/s  ok=%d/%d" %
                 (label, points[-1]["in_tokens"], points[-1]["ttft_avg_ms"], points[-1]["prefill_tps_agg"],
                  points[-1]["decode_tps_agg"] or 0, points[-1]["ok"], points[-1]["ok"] + points[-1]["fail"]))
    agg_pre = [p["prefill_tps_agg"] for p in points]
    agg_dec = [p["decode_tps_agg"] for p in points if p["decode_tps_agg"]]
    all_pre = [x for p in points for x in p["stream_prefill_tps"]]
    all_dec = [x for p in points for x in p["stream_decode_tps"]]
    summary = {
        "prefill_min": round(min(agg_pre), 1) if agg_pre else None,
        "prefill_max": round(max(agg_pre), 1) if agg_pre else None,
        "prefill_avg": round(statistics.mean(agg_pre), 1) if agg_pre else None,
        "decode_min": round(min(agg_dec), 1) if agg_dec else None,
        "decode_max": round(max(agg_dec), 1) if agg_dec else None,
        "decode_avg": round(statistics.mean(agg_dec), 1) if agg_dec else None,
        "per_stream_prefill_p50": round(pct(all_pre, 50), 1) if all_pre else None,
        "per_stream_prefill_p90": round(pct(all_pre, 90), 1) if all_pre else None,
        "per_stream_prefill_p95": round(pct(all_pre, 95), 1) if all_pre else None,
        "per_stream_decode_p50": round(pct(all_dec, 50), 1) if all_dec else None,
        "per_stream_decode_p90": round(pct(all_dec, 90), 1) if all_dec else None,
        "per_stream_decode_p95": round(pct(all_dec, 95), 1) if all_dec else None,
    }
    out = {"id": "prefill_conc", "name": "提示词阶梯×并发", "conc": conc, "points": points, "summary": summary}
    if skipped:
        out["skipped"] = skipped
    return out


def phase_longctx(url, headers, model, ctx_tokens, out_tok, cal=None):
    """长上下文驻留: 大上下文注入后解码。句数按校准结果算(cal 为空时用旧估算)。"""
    reps = reps_for(ctx_tokens, cal or _guess(""))
    prompt = "以下是技术文档，请基于内容回答：\n" + (ZH_UNIT * reps) + "\n\n用三句话概括核心内容。"
    label = "%dK" % (ctx_tokens // 1024)
    try:
        s = stream_call(url, {"model": model, "messages": [{"role": "user", "content": prompt}],
                              "max_tokens": out_tok, "temperature": 0}, headers)
    except urllib.error.HTTPError as e:
        why = ctx_overflow(e)
        if not why:
            raise
        plog("  超长输入 %s 跳过: %s" % (label, why))
        return {"id": "longctx", "name": "长上下文驻留", "points": [],
                "skipped": [{"phase": "longctx", "label": label, "reason": why}]}
    d = derive(s)
    d.update(label=label, target_tokens=ctx_tokens)
    plog("  ctx=%-7d in=%d  ttft=%6.2fs  prefill=%7.0f t/s  decode=%6.1f t/s" %
         (ctx_tokens, d["in_tokens"], d["ttft_s"] or 0, d["prefill_tps"] or 0, d["decode_tps"] or 0))
    return {"id": "longctx", "name": "长上下文驻留", "points": [d]}


# ---------------------------------------------------------------- 场景阶段: 任务模板 / 真实请求回放
# 业务场景 = 任务模板(形状) × 语料(内容) × 负载模式(闭环/开环)。
# 内置模板语料 seeded 生成(A/B 两次运行收到同序列, 盐除外), 请求不注入 ignore_eos, 测真实任务行为;
# 自定义任务集/真实请求回放则完全使用用户自己的请求。
# 指标诚实化: 只有声明输出契约的模板(json / custom 行内 response_format)报 JSON 合法率。

BIZ_RULES = [
    "你是跨境电商商品信息结构化助手，负责把卖家提供的原始商品描述整理为平台上架所需的标准字段。",
    "只输出一个 JSON 对象，不要输出解释、不要输出 Markdown 代码块、不要输出多余的空白行。",
    "title 字段为英文标题，长度 60 到 120 个字符，首字母大写，包含核心品类词、关键材质和主要规格，不得出现品牌侵权词、极限词和联系方式。",
    "category 字段从以下一级类目中选择最贴切的一个：家居厨房、户外运动、服饰配件、母婴用品、宠物用品、汽车配件、数码配件、美妆个护、办公文具、工具五金。",
    "material 字段填写主体材质，多种材质时按占比从高到低用逗号分隔，最多三种；无法判断时填写 unknown。",
    "price_usd 字段为数字，按卖家给出的人民币价格除以 7.1 后保留两位小数；卖家未给价格时填写 0。",
    "weight_g 字段为整数，单位克；卖家给出千克、磅或盎司时换算为克，四舍五入；未给出时填写 0。",
    "size_cm 字段为字符串，格式为 长x宽x高，单位厘米，保留一位小数；卖家给出英寸时乘以 2.54 换算。",
    "tags 字段为 3 到 6 个英文关键词组成的数组，每个关键词不超过 3 个单词，按搜索热度从高到低排列，不得重复。",
    "risk 字段为数组，列出可能涉及的合规风险：带电、液体、粉末、磁性、刀具、食品接触、儿童用品、仿牌；没有风险时为空数组。",
    "summary 字段为中文，一句话概括商品卖点，不超过 40 个汉字。",
    "所有字段必须出现；数字字段不得带单位；字符串字段不得包含换行符；遇到卖家描述前后矛盾时以规格参数表为准。",
    "卖家描述中的营销夸张用语（例如第一、最好、全网最低）不得出现在任何字段中。",
    "若卖家描述包含多个颜色或尺码，只按默认款整理，并在 summary 中注明提供多款可选。",
]
BIZ_SYSTEM = "\n".join("%d. %s" % (k + 1, r) for k, r in enumerate(BIZ_RULES * 2))
BIZ_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"}, "category": {"type": "string"},
        "material": {"type": "string"}, "price_usd": {"type": "number"},
        "weight_g": {"type": "integer"}, "size_cm": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "risk": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": ["title", "category", "material", "price_usd", "weight_g", "size_cm",
                 "tags", "risk", "summary"],
}
BIZ_ITEMS = ["不锈钢真空保温杯", "硅胶折叠收纳盒", "户外折叠露营椅", "宠物自动喂食器", "车载手机支架",
             "儿童防摔餐盘", "竹纤维毛巾套装", "磁吸无线充电器", "陶瓷不粘煎锅", "防水运动腰包"]
BIZ_SENTENCES = [
    "采用{m}材质，做工细致，边缘经过打磨处理，手感顺滑不刮手。",
    "规格参数：长{a}厘米，宽{b}厘米，高{c}厘米，净重约{w}克。",
    "适合家庭日常、办公室、户外出行等多种场景使用，收纳方便不占空间。",
    "提供{n}种颜色可选，默认款为{col}，包装为独立彩盒，适合作为礼品赠送。",
    "卖家建议零售价{p}元，支持批量采购，量大可议价，起订量{q}件。",
    "产品已通过相关质量检测，表面无异味，清洗时建议使用温水和中性清洁剂。",
    "注意：请勿放入微波炉或烤箱加热，避免长时间暴晒，儿童需在成人看护下使用。",
    "细节设计考虑到用户习惯，防滑底座和圆角结构提升了使用的安全性和稳定性。",
]

MAX_OPEN_INFLIGHT = 128  # 开环在途硬上限: 超限丢弃并计数, 防客户端线程爆炸

# ---- 对话问答语料: 短答/中任务/长文混合, 覆盖常见问答形态
CHAT_POOL = [
    "用两三句话解释什么是 KV cache，为什么它对推理速度至关重要。",
    "temperature 和 top_p 分别控制什么？调参时应该先动哪个？",
    "列出三种常见的模型量化方法，各用一句话说明优缺点。",
    "为什么推理时批量越大吞吐越高，但单个请求的延迟也越高？",
    "用通俗的语言解释 Transformer 的注意力机制在做什么。",
    "大模型'幻觉'的主要成因是什么？用三句话概括。",
    "把这段话翻译成英文：大模型的推理瓶颈通常在显存带宽而不是算力，量化通过降低权重精度来缓解这一约束。",
    "把下面这段口语化描述改写为正式的技术文档语气：这个缓存吧，一满就把最老的那些东西扔了，新来的接着用。",
    "为下面这段内容写一句摘要：前缀缓存通过复用相同前缀的 KV 计算结果，让重复系统提示词的请求跳过大部分 prefill，显著降低首 token 延迟。",
    "我们要给一个内部评测平台起一个中文名，要求体现'快'与'可信'，给出三个候选并各配一句理由。",
    "写一篇 600 字左右的短文，主题：边缘设备上部署大语言模型的机会与挑战。",
    "为技术团队写一份 500 字左右的决策备忘录：是否引入 AI 代码助手，需覆盖收益、风险与试点方案。",
    "对比 vLLM 与 SGLang 的核心设计差异，写一篇 600 字左右的技术综述。",
    "写一份面向新同学的'如何看懂推理服务指标'入门指南，600 字左右，覆盖 TTFT、吞吐、队列深度。",
    "用比喻的方式向产品经理解释什么是投机解码，为什么它能加速生成，300 字左右。",
    "总结构建高并发推理网关的五个关键设计点，每个点两三句话展开，500 字左右。",
    "分析这个论断是否成立并说明理由：'模型量化到 4bit 后，输出质量一定显著下降。'400 字左右。",
    "把以下需求拆解成结构化任务清单（用户故事格式）：用户希望上传文档后自动生成摘要并可追问。",
]

# ---- 代码生成语料: (任务描述, 语言)
CODE_TASKS = [
    ("实现一个 LRU 缓存类，支持 get/put 与容量上限，说明时间复杂度。", "Python"),
    ("编写函数 merge_intervals(intervals)，合并所有重叠区间，附带单元测试。", "Python"),
    ("实现一个线程安全的有界阻塞队列，供生产者-消费者场景使用。", "Python"),
    ("写一个命令行脚本：统计指定目录下各扩展名文件的累计大小，按大小排序输出。", "Python"),
    ("在不使用内置解码器的前提下实现 is_valid_utf8(data: bytes) -> bool。", "Python"),
    ("实现一个简化版布隆过滤器，支持指定误判率，并推导位数组大小。", "Python"),
    ("实现带过期时间的内存缓存模块，导出 get/set/delete 接口。", "TypeScript"),
    ("实现一个遵循速率限制的重试装饰器：指数退避、最多重试三次、可配置限速。", "Python"),
    ("实现令牌桶限流器类，支持突发容量与匀速补充，附并发测试。", "Python"),
    ("实现二叉树的序列化与反序列化（不用库函数），并写两个测试。", "Python"),
    ("写一个把 CSV 文件转换为 JSON 数组的脚本，处理引号转义与缺列。", "Python"),
    ("实现固定容量的环形缓冲区，支持并发读写一写一读无锁。", "C++"),
    ("实现函数 top_k_frequent(words, k)：返回出现频率最高的 k 个单词，同频按字典序。", "Python"),
    ("排查并修复这段代码的描述场景：一个长期运行的服务把每个请求的响应体都存进全局 list 用于'调试'，内存持续增长。给出修复代码与原因说明。", "Python"),
]

# ---- RAG 语料: 通用技术段落(编号引用) + 与内容无关也成立的引用式问题
RAG_TOKENS_PER_PASSAGE = 110  # 每段正文约 100-115 汉字(≈1 token/字), 另加段落编号
RAG_PASSAGES = [
    "权重量化把模型参数从 16bit 压缩到 8bit 或 4bit，直接减少显存占用与访存量。量化误差会轻微影响输出质量，但配合逐层校准通常可以把质量损失控制在很小的范围内，是单卡部署大模型最常用的手段。",
    "连续批处理让推理引擎在每一步解码时动态合并正在运行的请求，新请求不必等待整批完成。相比静态批处理，它显著提高了 GPU 利用率与吞吐，是 vLLM 等现代引擎的标志性设计。",
    "KV 缓存保存注意力计算中间结果，使解码阶段每步只需计算新 token。它随上下文长度线性增长，是显存的主要消耗者之一；页式注意力(PagedAttention)通过分页管理减少了碎片浪费。",
    "投机解码用一个小的草稿模型快速生成若干候选 token，再由主模型并行验证，被接受的部分等价于主模型逐个生成。它在保持输出分布不变的前提下，可以成倍降低解码延迟。",
    "张量并行把每一层的权重切分到多张 GPU 上，各卡计算部分结果后通信归约。它对通信带宽敏感，通常通过 NVLink 等高速互联才能发挥效果，是大模型多卡部署的基础并行方式。",
    "前缀缓存复用相同前缀的 KV 计算结果。对系统提示词很长的服务，命中前缀缓存可以把首 token 延迟降低一个数量级；评测时应使用唯一前缀避免命中导致数据虚高。",
    "推理请求调度需要在吞吐与延迟之间权衡：batch 越大吞吐越高，但排队延迟也随之上升。常见的策略是设置等待队列上限与批大小上限，超过后新请求快速失败或降级。",
    "评测推理性能时，固定输出长度(忽略停止条件)可以避免模型提前结束造成的吞吐偏差；同时报告 TTFT 与每 token 延迟的分位数，比只报平均值更能反映用户体验。",
    "显存占用由权重、KV 缓存与激活三部分构成。部署时通常预留一部分显存给 KV 缓存池，池越大可并发请求越多；当并发超过容量时，引擎会抢占或排队，表现为延迟陡增。",
    "模型服务的长尾延迟往往来自个别的慢请求与偶发的批重组。压测时除了平均延迟，更应关注 P95/P99 与最大在途请求数，开环(固定到达速率)测试比闭环并发更能暴露排队堆积。",
]
RAG_QUESTIONS = [
    "根据资料，总结其中提到的三个最重要的观点，并标注各自的段落号。",
    "资料中提到了哪些技术手段？分别用来解决什么问题？请逐条标注来源段落。",
    "仅根据资料回答：如果显存不足，有哪几种可行的应对办法？标注依据段落。",
    "资料作者对'吞吐与延迟的关系'持什么观点？请引用具体段落说明。",
    "基于资料，说明为什么评测推理系统时不能只看平均延迟，需引用段落支持你的回答。",
    "资料未提及但与主题相关的'模型蒸馏'，资料里有没有任何间接信息？若没有请明确说明，并总结资料实际覆盖的主题。",
]

# ---- 图片理解语料: 上传的图片内容未知, 用与具体图片无关也成立的分析型 prompt;
#      内置示例图片每张自带只问图里内容的提示词(vision_assets.SAMPLES)
VISION_PROMPTS = [
    "详细描述这张图片的内容，指出其中最值得注意的三点。",
    "如果这是数据图表，请读出关键数值并给出三条分析结论；若不是图表，请做内容分析。",
    "如果图片里有文字，请提取出来并尽量保持原始排版结构；没有文字就说明没有，再简单描述图片。",
    "为这张图片写一段 100 字左右的替代文本(alt text)，再写一段内容分析。",
    "评估这张图片的构图、清晰度与信息密度，并说明它适合用在什么场合。",
    "假设这张图片来自一份报告，请推断它想支持什么结论，并指出图中可能存在的误导之处。",
]

SCN_TEMPLATES = {
    "chat":   {"label": "对话问答", "validator": None},
    "code":   {"label": "代码生成", "validator": None},
    "json":   {"label": "结构化抽取", "validator": "json"},
    "rag":    {"label": "RAG 问答", "validator": None},
    "vision": {"label": "图片理解", "validator": None},
    "custom": {"label": "自定义任务集", "validator": None},  # 合法率按行内 response_format 决定
}


def _json_text_ok(text, required=None):
    """输出能否解析为 JSON(容忍 ``` 围栏); required 非空时要求键齐全。"""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    try:
        obj = json.loads(t)
    except Exception:
        return False
    return isinstance(obj, dict) and (not required or set(required) <= set(obj))


def _retry_cell(run_once, label, max_attempts=3, pause_s=30.0):
    """整格重跑: 有失败且未达上限时隔 pause_s 秒重跑整格, 每轮失败留痕, 记录以最后一轮为准。
    只用于"基础设施型失败"的场景格(业务/回放/矩阵); 并发阶梯的过载失败是测量对象, 不重跑。"""
    attempts, failed = 0, []
    while True:
        attempts += 1
        rec = run_once()
        if rec.get("ok") == rec.get("total") or attempts >= max_attempts:
            if attempts > 1:
                rec["attempts"] = attempts
                rec["failed_attempts"] = failed
            return rec
        failed.append({"attempt": attempts, "ok": rec["ok"], "fail": rec["fail"],
                       "errors": rec.get("errors") or []})
        plog("  %s: %d/%d 失败, %.0fs 后重跑 (尝试 %d/%d)" %
             (label, rec["fail"], rec["total"], pause_s, attempts + 1, max_attempts))
        _sleep_cancel(pause_s)


def _cell_metrics(recs, wall):
    """场景格通用汇总: 先逐请求记录, 再对每请求指标取分位。"""
    ok = [r for r in recs if not r["err"] and r["ntok"] > 0]
    tt = sorted(r["ttft"] for r in ok if r["ttft"] is not None)
    e2e = sorted(r["dt"] for r in ok)
    m = {
        "wall_s": round(wall, 2), "ok": len(ok), "fail": len(recs) - len(ok), "total": len(recs),
        "req_s": round(len(ok) / wall, 3) if ok and wall > 0 else 0,
        "agg_tps": round(sum(r["ntok"] for r in ok) / wall, 1) if ok and wall > 0 else 0,
        "ttft_p50_s": round(pct(tt, 50), 3) if tt else None,
        "ttft_p95_s": round(pct(tt, 95), 3) if tt else None,
        "e2e_p50_s": round(pct(e2e, 50), 3) if e2e else None,
        "e2e_p95_s": round(pct(e2e, 95), 3) if e2e else None,
        "prompt_tokens_avg": round(statistics.mean(r["ptok"] for r in ok if r["ptok"]), 1)
            if ok and any(r["ptok"] for r in ok) else None,
        "out_tokens_avg": round(statistics.mean(r["ntok"] for r in ok), 1) if ok else None,
        "errors": [r["err"] for r in recs if r["err"]][:3],
    }
    jr = [r for r in ok if r.get("json_req")]
    if jr:
        m["json_total"] = len(jr)
        m["json_ok"] = sum(1 for r in jr if r["json_ok"])
    return m


def _scenario_request(url, headers, body, res, lock, inflight=None):
    """单次场景请求(流式): 记录 ttft/e2e/token 数/JSON 合法性; 异常降级为错误记录。"""
    json_req = (body.get("response_format") or {}).get("type") in ("json_schema", "json_object")
    rec = {"ttft": None, "dt": None, "ntok": 0, "ptok": 0, "err": None,
           "json_req": json_req, "json_ok": False}
    if inflight is not None:
        with lock:
            inflight[0] += 1
            inflight[1] = max(inflight[1], inflight[0])
    try:
        s = stream_call(url, body, headers, apply_req_extra=False)
        rec.update(ttft=s["ttft"], dt=s["wall"],
                   ntok=(s["usage"].get("completion_tokens") or 0) or s["chunks"],
                   ptok=s["usage"].get("prompt_tokens") or 0)
        if json_req:
            rec["json_ok"] = _json_text_ok(s["text"])
    except Exception as e:
        rec["err"] = str(e)[:ERR_MAX]
    finally:
        if inflight is not None:
            with lock:
                inflight[0] -= 1
        with lock:
            res.append(rec)


def _scn_json_body(model, rng, max_tokens, disable_thinking):
    item = rng.choice(BIZ_ITEMS)
    fill = dict(m=rng.choice(["304不锈钢", "食品级硅胶", "铝合金", "ABS塑料", "竹纤维", "陶瓷"]),
                a=rng.randint(5, 60), b=rng.randint(5, 40), c=rng.randint(2, 30), w=rng.randint(80, 3000),
                n=rng.randint(2, 6), col=rng.choice(["黑色", "白色", "灰色", "蓝色", "粉色"]),
                p=rng.randint(15, 400), q=rng.randint(10, 200))
    body_text = "".join(rng.choice(BIZ_SENTENCES).format(**fill) for _ in range(22))
    user = "[编号%s] 商品：%s\n卖家原始描述：%s\n请按规则整理为 JSON。" % (uuid.uuid4().hex[:8], item, body_text)
    body = {"model": model,
            "messages": [{"role": "system", "content": BIZ_SYSTEM}, {"role": "user", "content": user}],
            "max_tokens": max_tokens, "temperature": 0.3,
            "response_format": {"type": "json_schema", "json_schema": {"name": "listing", "schema": BIZ_SCHEMA}}}
    if disable_thinking:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    return body


def _scn_chat_body(model, rng, max_tokens, salt):
    return {"model": model, "max_tokens": max_tokens, "temperature": 0.3,
            "messages": [{"role": "user", "content": "[%s] %s" % (salt, rng.choice(CHAT_POOL))}]}


def _scn_code_body(model, rng, max_tokens, salt):
    task, lang = rng.choice(CODE_TASKS)
    return {"model": model, "max_tokens": max_tokens, "temperature": 0.2,
            "messages": [{"role": "system",
                          "content": "你是资深软件工程师。给出完整、可直接运行的代码，附简要说明与两个测试用例。"},
                         {"role": "user", "content": "[%s] 编程语言: %s。任务: %s" % (salt, lang, task)}]}


def _scn_rag_body(model, rng, max_tokens, salt, ctx_tokens, cal=None, n=None):
    """资料段数按目标长度算: cal 是 calibrate_rag 的结果(每段资料多少 token、其余部分多少 token), 为空时用旧估算;
    n 直接指定段数(校准时用)。"""
    if n is None:
        per, rest = (cal["unit_tokens"], cal["overhead_tokens"]) if cal else (RAG_TOKENS_PER_PASSAGE, 0)
        n = max(3, int(round((ctx_tokens - rest) / per)))
    start = rng.randrange(len(RAG_PASSAGES))
    parts = ["[段落 %d] %s" % (i + 1, RAG_PASSAGES[(start + i) % len(RAG_PASSAGES)]) for i in range(n)]
    user = "[%s]\n以下是检索到的资料：\n\n%s\n\n问题: %s" % (salt, "\n\n".join(parts), rng.choice(RAG_QUESTIONS))
    return {"model": model, "max_tokens": max_tokens, "temperature": 0.2,
            "messages": [{"role": "system",
                          "content": "仅基于用户提供的资料回答，需标注依据的段落号；资料未涉及的内容明确说明不知道，不得编造。"},
                         {"role": "user", "content": user}]}


def calibrate_rag(url, headers, model):
    """实测「看资料回答」每段资料的 token 数: 同一个问题分别带 10 段和 30 段资料, 各发一个只生成 1 个 token 的请求。
    不成时退回旧估算(每段 110)。"""
    k = len(RAG_PASSAGES)
    samples = []
    try:
        for n in (k, 3 * k):
            body = _scn_rag_body(model, random.Random(0), 1, "cal", 0, n=n)  # 同一个随机种子: 只有段数不同
            s = stream_call(url, body, headers, timeout=120, apply_req_extra=False)  # 和场景请求一样不带 ignore_eos
            samples.append([n, derive(s)["in_tokens"]])
    except Cancelled:
        raise
    except Exception as e:
        out = _guess("校准请求失败：%s" % str(e)[:200], samples)
        out["unit_tokens"] = RAG_TOKENS_PER_PASSAGE
        return out
    unit, overhead = _fit(samples)
    if not (5 <= unit <= 2000) or not (-50 <= overhead <= 4000):
        out = _guess("服务返回的输入 token 数不随资料长度变化（可能没有返回真实用量）", samples)
        out["unit_tokens"] = RAG_TOKENS_PER_PASSAGE
        return out
    return {"method": "usage", "unit_tokens": round(unit, 3), "overhead_tokens": max(0, int(round(overhead))),
            "samples": samples}


def _scn_vision_body(model, rng, max_tokens, salt, images, n_img, prompts=None):
    """images: data URL 列表; prompts: 与 images 一一对应的提示词列表(内置示例图片),
    为空时用通用的 VISION_PROMPTS(上传的图片内容未知)。一次带多张内置图时用对每张都成立的提示词。"""
    start = rng.randrange(len(images))
    if not prompts:
        pool = VISION_PROMPTS
    else:
        pool = prompts[start] if n_img == 1 else vision_assets.SAMPLE_MULTI_PROMPTS
    parts = [{"type": "text", "text": "[%s] %s" % (salt, rng.choice(pool))}]
    parts += [{"type": "image_url", "image_url": {"url": images[(start + k) % len(images)]}}
              for k in range(n_img)]
    return {"model": model, "max_tokens": max_tokens, "temperature": 0.2,
            "messages": [{"role": "user", "content": parts}]}


def _load_vision_images(d, skipped=None):
    """读取图片目录 -> data URL 列表。逐张检查: 太小、损坏、太大的跳过(发出去服务端也会拒绝),
    跳过的检查结果追加到 skipped; 无目录或没有能用的图片时抛错(场景无法运行, 快速失败)。"""
    if not d or not os.path.isdir(d):
        raise RuntimeError("图片目录不存在: %s (图片理解场景需要已上传的图片包或服务器图片目录)" % d)
    good, checks = vision_assets.scan_dir(d)
    if not checks:
        raise RuntimeError("图片目录中没有图片(jpg/png/webp/gif): %s" % d)
    bad = [c for c in checks if not c["ok"]]
    for c in bad[:5]:
        plog("  跳过图片 %s: %s" % (c["name"], c["msg"]))
    if len(bad) > 5:
        plog("  另外还跳过 %d 张不能用的图片" % (len(bad) - 5))
    if skipped is not None:
        skipped.extend(bad)
    if not good:
        raise RuntimeError("图片目录里没有能用的图片: %s (%s)" % (d, "；".join("%s %s" % (c["name"], c["msg"]) for c in bad[:3])))
    return [vision_assets.data_url(data, c["format"]) for _, data, c in good]


def phase_scenario(url, headers, model, tpl_id, cfg):
    """任务场景: 按 SCENARIO_TEMPLATES 的模板构造请求, C 个 worker 各连发 N 条。
    语料 seeded 生成(同 seed 同正文, 盐除外) → A/B 两次运行收到相同请求序列;
    custom 模板的请求来自任务集文件(cursor 跨格推进防前缀缓存)。"""
    tpl = SCN_TEMPLATES[tpl_id]
    conc_list = [int(c) for c in (cfg.get("conc") or [4, 8])]
    rpw = int(cfg.get("requests_per_worker") or 3)
    mt = int(cfg.get("max_tokens") or 512)
    max_attempts = int(cfg.get("max_attempts") or 3)
    pause = cfg.get("retry_pause_s")
    pause = 30.0 if pause is None else float(pause)
    images = pool = prompts = None
    n_img = int(cfg.get("vision_images") or 1)
    img_skipped = []
    if tpl_id == "vision":
        if cfg.get("vision_dir"):  # 上传的图片包或服务器上的文件夹
            images = _load_vision_images(cfg["vision_dir"], img_skipped)
        else:  # 默认: 内置示例图片, 每张图配只问图里内容的提示词
            samples = vision_assets.sample_images()
            images = [vision_assets.data_url(png, "png") for _, _, png, _ in samples]
            prompts = [p for _, _, _, p in samples]
        plog("  图片池 %d 张%s, 每请求 %d 张" % (len(images), "(内置示例图片)" if prompts else "", n_img))
    if tpl_id == "custom":
        pool = ReplayPool(cfg.get("custom_file") or "")
        plog("  任务集 %d 条" % len(pool))
    ctx_list = [int(x) for x in (cfg.get("rag_ctx") or [4000])] if tpl_id == "rag" else [None]
    rag_cal = None
    if tpl_id == "rag":
        rag_cal = calibrate_rag(url, headers, model)
        plog("  资料长度校准: " + (("每段 %.1f token，问题和说明 %d token（实测）" % (rag_cal["unit_tokens"], rag_cal["overhead_tokens"]))
                                   if rag_cal["method"] == "usage" else "没能校准，按旧估算每段 %d token（%s）"
                                   % (rag_cal["unit_tokens"], rag_cal.get("error") or "")))

    def build(rng, salt, ctx):
        if tpl_id == "chat":
            return _scn_chat_body(model, rng, mt, salt)
        if tpl_id == "code":
            return _scn_code_body(model, rng, mt, salt)
        if tpl_id == "json":
            return _scn_json_body(model, rng, mt, bool(cfg.get("disable_thinking")))
        if tpl_id == "rag":
            return _scn_rag_body(model, rng, mt, salt, ctx, rag_cal)
        return _scn_vision_body(model, rng, mt, salt, images, n_img, prompts)

    points = []
    for conc in conc_list:
        for ctx in ctx_list:
            check_cancel()

            def once(conc=conc, ctx=ctx):
                res, lock, inflight = [], threading.Lock(), [0, 0]
                start = pool.reserve(conc * rpw) if pool is not None else 0

                def worker(w):
                    rng = random.Random("%s-%s-%d-%d" % (tpl_id, ctx or "x", conc, w))
                    for j in range(rpw):
                        check_cancel()
                        if pool is not None:  # custom: 请求来自任务集, 保留行内 params
                            body = _replay_body(model, pool.get(start + w * rpw + j), pool)
                        else:
                            body = build(rng, uuid.uuid4().hex[:8], ctx)
                        _scenario_request(url, headers, body, res, lock, inflight)

                t0 = time.perf_counter()
                with ThreadPoolExecutor(max_workers=conc) as ex:
                    list(ex.map(worker, range(conc)))
                m = _cell_metrics(res, time.perf_counter() - t0)
                m.update(conc=conc, requests_per_worker=rpw)
                if ctx is not None:
                    m["ctx_tokens"] = ctx
                if pool is not None:
                    m.update(pool_size=len(pool), pool_wrapped=pool.wrapped)
                if m["ok"] and tpl_id == "json":
                    m["json_rate"] = round(m["json_ok"] / m["ok"], 3)
                return m

            rec = _retry_cell(once, "%s C=%d%s" % (tpl_id, conc, (" ctx=%d" % ctx) if ctx else ""),
                              max_attempts, pause)
            points.append(rec)
            plog("  C=%-3d%s ok=%d/%d  req/s=%7.2f  ttft_p95=%6.2fs  e2e_p95=%6.2fs%s" %
                 (conc, ("ctx=%-6d" % ctx) if ctx else "      ", rec["ok"], rec["total"], rec["req_s"],
                  rec["ttft_p95_s"] or 0, rec["e2e_p95_s"] or 0,
                  ("  json=%d/%d" % (rec["json_ok"], rec["json_total"])) if rec.get("json_total") else ""))
    task = {"tpl": tpl_id, "label": tpl["label"], "validator": tpl["validator"],
            "max_tokens": mt, "requests_per_worker": rpw}
    if tpl_id == "rag":
        task["rag_ctx"] = ctx_list
        task["rag_calibration"] = rag_cal
    if tpl_id == "vision":
        task["images"] = len(images)
        task["images_per_request"] = n_img
        task["image_source"] = "builtin" if prompts else "files"
        if img_skipped:
            task["images_skipped"] = len(img_skipped)
    if tpl_id == "custom":
        task["pool_size"] = len(pool)
        ts = cfg.get("task_set")  # 用的是页面上导入的哪个任务集(任务集页面按它统计「用过几次」)
        if isinstance(ts, dict) and ts.get("id"):
            task["task_set"] = {"id": str(ts["id"]), "name": str(ts.get("name") or ts["id"])}
    return {"id": "scn_" + tpl_id, "name": "场景 · " + tpl["label"], "points": points, "task": task}


# ---- 自定义任务集 / 回放文件的逐行检查: 测试时实际发送(ReplayPool)与上传时的检查报告共用同一个判断
TASK_MAX_PROMPT_TOKENS = 60000   # meta.prompt_tokens 超过它的行跳过(避免超长请求拖垮整格)
TASK_MT_DEFAULT = 4096           # 行内没写 max_tokens 时的默认值
TASK_MT_CAP = 8192               # 行内 max_tokens 的上限
TASK_ROLES = ("system", "user", "assistant", "tool", "developer", "function")
_JSON_ERR_ZH = [("Expecting ',' delimiter", "缺少逗号，或者括号没有配对"), ("Expecting ':' delimiter", "缺少冒号"),
                ("Expecting property name enclosed in double quotes", "键名要用英文双引号括起来，最后一项后面不能有逗号"),
                ("Illegal trailing comma", "最后一项后面不能有逗号"),
                ("Unterminated string", "字符串没有结束（缺少英文双引号）"), ("Invalid control character", "字符串里不能直接换行（要写成 \\n）"),
                ("Extra data", "一行里只能放一个 JSON 对象"), ("Expecting value", "这里缺少值（可能多了逗号，或用了中文引号、单引号）"),
                ("Unexpected UTF-8 BOM", "文件开头有 BOM，请存为不带 BOM 的 UTF-8")]


def task_max_tokens(params, default=TASK_MT_DEFAULT, cap=TASK_MT_CAP):
    """任务集 / 回放一行实际发送的 max_tokens: 行内 max_tokens 优先, 其次 max_completion_tokens;
    没写或不是正整数时按默认值(check_task_line 的提醒也是这么说的), 超过上限按上限。"""
    params = params if isinstance(params, dict) else {}
    v = params.get("max_tokens") or params.get("max_completion_tokens")
    try:
        n = int(v) if v is not None else 0
    except (TypeError, ValueError):
        n = 0
    return min(n if n > 0 else int(default), int(cap))


def _json_err_text(e):
    msg = getattr(e, "msg", str(e))
    zh = next((z for en, z in _JSON_ERR_ZH if msg.startswith(en)), msg)
    return "第 %d 个字符附近%s" % (getattr(e, "colno", 0), "：" + zh if zh else "")


def _check_image_url(url):
    """任务集里的一张图: data URL 解码后按看图模型的要求检查; 网址没法离线检查, 只提醒。返回 (问题, 提醒)。"""
    if url.startswith("data:"):
        head, _, payload = url.partition(",")
        if ";base64" not in head or not payload:
            return "不是 base64 格式的 data URL（应为 data:image/png;base64,…）", None
        try:
            data = base64.b64decode(payload)
        except (ValueError, TypeError):
            return "的 base64 数据已损坏", None
        c = vision_assets.check_image(data)
        if not c["ok"]:
            return c["msg"], None
        return None, (c["msg"] or None)
    if url.startswith(("http://", "https://")):
        return None, "是网址，模型服务需要能访问到它"
    return "的地址应为 data:image/…;base64,… 或 http(s) 网址", None


def check_task_line(line, max_prompt_tokens=TASK_MAX_PROMPT_TOKENS):
    """检查任务集 / 回放文件的一行。返回 {status, reason, warns, rec, json, images}:
    status = ok(可以发) / skip(没有消息或超长, 跳过) / bad(格式不对, 发出去服务端也会拒绝);
    json = 带 JSON 输出要求(response_format, 会统计 JSON 合法率); images = 带几张图。"""
    out = {"status": "bad", "reason": "", "warns": [], "rec": None, "json": False, "images": 0}

    def bad(reason):
        out["reason"] = reason
        return out
    try:
        r = json.loads(line)
    except ValueError as e:
        return bad("不是合法的 JSON（%s）" % _json_err_text(e))
    if not isinstance(r, dict):
        return bad("每行应是一个 JSON 对象，形如 {\"messages\": [...]}")
    msgs = r.get("messages")
    if not isinstance(msgs, list) or not msgs:
        out["status"] = "skip"
        return bad("缺少 messages（消息列表）" if not isinstance(msgs, list) else "messages 是空的")
    for k, m in enumerate(msgs, 1):
        where = "messages 第 %d 条" % k
        if not isinstance(m, dict):
            return bad(where + "不是对象，应为 {\"role\": ..., \"content\": ...}")
        role = m.get("role")
        if not isinstance(role, str) or not role:
            return bad(where + "缺少 role")
        if role not in TASK_ROLES:
            return bad("%s的 role「%s」不认识（应为 system / user / assistant / tool）" % (where, role))
        content = m.get("content")
        if content is None:
            if role != "assistant":  # 只有带 tool_calls 的助手消息可以没有 content
                return bad(where + "缺少 content")
        elif isinstance(content, list):
            for j, part in enumerate(content, 1):
                if not isinstance(part, dict) or not isinstance(part.get("type"), str):
                    return bad("%s的 content 第 %d 项应为 {\"type\": ...}" % (where, j))
                if part["type"] == "text" and not isinstance(part.get("text"), str):
                    return bad("%s的 content 第 %d 项缺少 text" % (where, j))
                if part["type"] == "image_url":
                    iu = part.get("image_url")
                    url = iu.get("url") if isinstance(iu, dict) else None
                    if not isinstance(url, str) or not url:
                        return bad("%s的图片应写成 {\"type\": \"image_url\", \"image_url\": {\"url\": \"...\"}}" % where)
                    out["images"] += 1
                    problem, warn = _check_image_url(url)
                    if problem:
                        return bad("%s的第 %d 张图%s" % (where, out["images"], problem))
                    if warn:
                        out["warns"].append("第 %d 张图%s" % (out["images"], warn))
        elif not isinstance(content, str):
            return bad(where + "的 content 应为文字，或文字和图片组成的列表")
    params = r.get("params")
    if params is not None and not isinstance(params, dict):
        return bad("params 应为对象，如 {\"max_tokens\": 512}")
    params = params or {}
    rf = params.get("response_format")
    if rf is not None:
        if not isinstance(rf, dict) or rf.get("type") not in ("text", "json_object", "json_schema"):
            return bad("response_format 应为 {\"type\": \"json_object\"} 或 {\"type\": \"json_schema\", \"json_schema\": {...}}")
        js = rf.get("json_schema")
        if rf["type"] == "json_schema" and not (isinstance(js, dict) and isinstance(js.get("name"), str) and js["name"]
                                               and isinstance(js.get("schema", {}), dict)):
            return bad("json_schema 应写成 {\"name\": \"名字\", \"schema\": {JSON Schema}}")
        out["json"] = rf["type"] != "text"
    for key in ("max_tokens", "max_completion_tokens"):
        v = params.get(key)
        if v is None:
            continue
        try:
            n = int(v)
        except (TypeError, ValueError):
            n = 0
        if n <= 0:
            out["warns"].append("%s 不是正整数，会按默认 %d" % (key, TASK_MT_DEFAULT))
        elif n > TASK_MT_CAP:
            out["warns"].append("%s 是 %d，超过上限，会按 %d" % (key, n, TASK_MT_CAP))
    t = params.get("temperature")
    if t is not None and (isinstance(t, bool) or not isinstance(t, (int, float)) or t < 0):
        return bad("temperature 应为不小于 0 的数字")
    meta = r.get("meta")
    pt = meta.get("prompt_tokens") if isinstance(meta, dict) else None
    if isinstance(pt, int) and pt > max_prompt_tokens:
        out["status"] = "skip"
        return bad("输入约 %d token，超过 %d 的上限，跳过" % (pt, max_prompt_tokens))
    out.update(status="ok", rec=r)
    return out


def check_task_text(text, max_prompt_tokens=TASK_MAX_PROMPT_TOKENS, limit=10):
    """检查整个任务集文件(上传时用): 共几行、可用几行、带 JSON 输出要求 / 带图片的各几条,
    有问题的行给出行号和原因(前 limit 条)。行的判断与测试时实际发送完全一致。"""
    rep = {"total": 0, "valid": 0, "skipped": 0, "bad": 0, "json": 0, "image": 0,
           "problems": [], "warnings": [], "warning_count": 0, "hint": ""}
    text = (text or "").lstrip("\ufeff")
    for no, ln in enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"), 1):
        if not ln.strip():
            continue
        rep["total"] += 1
        c = check_task_line(ln, max_prompt_tokens)
        if c["status"] == "ok":
            rep["valid"] += 1
            rep["json"] += c["json"]
            rep["image"] += c["images"] > 0
        else:
            rep["skipped" if c["status"] == "skip" else "bad"] += 1
            if len(rep["problems"]) < limit:
                rep["problems"].append({"line": no, "reason": c["reason"]})
        for w in c["warns"]:
            rep["warning_count"] += 1
            if len(rep["warnings"]) < limit:
                rep["warnings"].append({"line": no, "reason": w})
    if rep["total"] > 1 and not rep["valid"] and text.lstrip()[:1] in ("[", "{"):
        try:  # 常见错误: 整份文件是一个 JSON 数组, 或一个对象排版成了多行
            whole = json.loads(text)
        except ValueError:
            whole = None
        if isinstance(whole, list):
            rep["hint"] = "整个文件是一个 JSON 数组；任务集要求每行一个 JSON 对象（JSONL），可以参考「下载模板」"
        elif isinstance(whole, dict):
            rep["hint"] = "一个请求被排版成了多行；任务集要求每个请求写在一行里（JSONL），可以参考「下载模板」"
    return rep


class ReplayPool:
    """真实请求池: JSONL 逐行 {"messages": [...], "params": {...}}; 固定种子洗牌,
    cursor 跨格推进尽量不重发同一请求(重复请求会命中前缀缓存, 吞吐虚高)。
    每行按 check_task_line 判断: 没有消息或超长的跳过(skipped), 格式不对的算坏行(bad)。"""

    def __init__(self, path, max_prompt_tokens=TASK_MAX_PROMPT_TOKENS, seed=1,
                 mt_default=TASK_MT_DEFAULT, mt_cap=TASK_MT_CAP):
        pool, skipped, bad = [], 0, 0
        with open(path, encoding="utf-8-sig") as f:
            for ln in f:
                if not ln.strip():
                    continue
                c = check_task_line(ln, max_prompt_tokens)
                if c["status"] == "ok":
                    pool.append(c["rec"])
                elif c["status"] == "skip":
                    skipped += 1
                else:
                    bad += 1
        if not pool:
            raise RuntimeError("文件里没有可用请求: %s (没有消息或超长跳过 %d 行, 格式不对 %d 行)" % (path, skipped, bad))
        random.Random(seed).shuffle(pool)
        self.pool, self.skipped, self.bad, self.path = pool, skipped, bad, path
        self.mt_default, self.mt_cap, self.cursor = int(mt_default), int(mt_cap), 0

    def reserve(self, n):
        """预占 n 个请求(返回起始下标); 耗尽后回绕并置 wrapped。"""
        start = self.cursor
        self.cursor += n
        return start

    def get(self, i):
        return self.pool[i % len(self.pool)]

    @property
    def wrapped(self):
        return self.cursor > len(self.pool)

    def __len__(self):
        return len(self.pool)


def _replay_body(model, rec, rp):
    params = rec.get("params") or {}
    body = {k: v for k, v in params.items() if k not in ("model", "stream", "stream_options", "n")}
    body.pop("max_completion_tokens", None)
    body["max_tokens"] = task_max_tokens(params, rp.mt_default, rp.mt_cap)
    if "enable_thinking" in body:  # 网关把顶层开关映射进 chat template
        body.setdefault("chat_template_kwargs", {}).setdefault("enable_thinking", bool(body.pop("enable_thinking")))
    body.update(model=model, messages=rec["messages"])
    return body


def phase_replay_closed(url, headers, model, cfg, rp):
    """回放·闭环: C 个 worker 各连发 N 条真实请求 — 回答"C 路并发扛不扛得住"。"""
    conc_list = [int(c) for c in (cfg.get("conc") or [4, 8])]
    rpw = int(cfg.get("requests_per_worker") or 4)
    max_attempts = int(cfg.get("max_attempts") or 3)
    pause = cfg.get("retry_pause_s")
    pause = 30.0 if pause is None else float(pause)
    points = []
    for conc in conc_list:
        check_cancel()

        def once(c=conc):
            start = rp.reserve(c * rpw)
            res, lock, inflight = [], threading.Lock(), [0, 0]

            def worker(w):
                for j in range(rpw):
                    check_cancel()
                    _scenario_request(url, headers, _replay_body(model, rp.get(start + w * rpw + j), rp),
                                      res, lock, inflight)

            t0 = time.perf_counter()
            with ThreadPoolExecutor(max_workers=c) as ex:
                list(ex.map(worker, range(c)))
            m = _cell_metrics(res, time.perf_counter() - t0)
            m.update(conc=c, requests_per_worker=rpw, max_inflight=inflight[1],
                     pool_size=len(rp), pool_wrapped=rp.wrapped)
            return m

        rec = _retry_cell(once, "replay C=%d" % conc, max_attempts, pause)
        points.append(rec)
        plog("  C=%-3d ok=%d/%d  req/s=%7.2f  ttft_p95=%6.2fs  e2e_p95=%6.2fs  in-flight_max=%d" %
             (conc, rec["ok"], rec["total"], rec["req_s"], rec["ttft_p95_s"] or 0,
              rec["e2e_p95_s"] or 0, rec["max_inflight"]))
    return {"id": "replay", "name": "回放·闭环", "points": points,
            "pool": {"size": len(rp), "skipped": rp.skipped, "bad": rp.bad, "wrapped": rp.wrapped}}


def _inflight_sampler(out, stop, inflight, lock):
    t0 = time.perf_counter()
    while not stop.wait(1.0):
        with lock:
            out.append([round(time.perf_counter() - t0, 1), inflight[0]])


def _open_rate_cell(url, headers, model, rate, duration, rp):
    """开波单速率格: 泊松到达(种子固定, A/B 两次运行到达时间轴相同), 发送期+排空期全程计时。"""
    rng = random.Random("openloop-rate-%g" % rate)
    res, lock, inflight = [], threading.Lock(), [0, 0]
    samples, stop = [], threading.Event()
    threads, shed, k = [], 0, 0
    start = rp.cursor
    sampler = threading.Thread(target=_inflight_sampler, args=(samples, stop, inflight, lock), daemon=True)
    t0 = time.perf_counter()
    sampler.start()
    try:
        nxt = 0.0
        while nxt < duration:
            _sleep_cancel(max(0.0, t0 + nxt - time.perf_counter()))
            check_cancel()
            if inflight[0] >= MAX_OPEN_INFLIGHT:  # 在途超限: 丢弃并计数(到达时间轴不变)
                shed += 1
            else:
                t = threading.Thread(target=_scenario_request,
                                     args=(url, headers, _replay_body(model, rp.get(start + k), rp),
                                           res, lock, inflight), daemon=True)
                t.start()
                threads.append(t)
            k += 1
            nxt += rng.expovariate(rate)
        for t in threads:
            t.join()
    finally:
        stop.set()
        sampler.join(timeout=2)
        rp.cursor = start + k
    wall = time.perf_counter() - t0
    m = _cell_metrics(res, wall)
    m.update(rate=rate, duration_s=duration, sent=k, shed=shed,
             completed_rps=round(m["ok"] / wall, 3) if wall > 0 else 0,
             max_inflight=inflight[1], inflight_ts=samples,
             pool_size=len(rp), pool_wrapped=rp.wrapped)
    return m


def phase_replay_open(url, headers, model, cfg, rp):
    """回放·开环: 按设定速率(泊松到达)持续施压 — 回答"线上到达速率下会不会越排越长"。
    inflight_ts 时间线 + max_inflight 直接暴露排队堆积。"""
    rates = [float(r) for r in (cfg.get("rates") or [])]
    duration = float(cfg.get("duration_s") or 60)
    max_attempts = int(cfg.get("max_attempts") or 3)
    pause = cfg.get("retry_pause_s")
    pause = 30.0 if pause is None else float(pause)
    points = []
    for rate in rates:
        check_cancel()
        rec = _retry_cell(lambda r=rate: _open_rate_cell(url, headers, model, r, duration, rp),
                          "openloop rate=%g" % rate, max_attempts, pause)
        points.append(rec)
        plog("  rate=%-6g sent=%d shed=%d ok=%d/%d  完成=%6.2f rps  ttft_p95=%6.2fs  in-flight_max=%d" %
             (rate, rec["sent"], rec["shed"], rec["ok"], rec["total"], rec["completed_rps"],
              rec["ttft_p95_s"] or 0, rec["max_inflight"]))
    return {"id": "openloop", "name": "回放·开环 (泊松到达)", "points": points, "duration_s": duration}


# ---------------------------------------------------------------- 主流程

# 长度档位只写目标长度("8K" = 8000 token), 拼几句在测试开始校准后再算(resolve_ladder);
# 自定义套件文件里旧的 [标签, 句数] 写法也兼容, 按标签重算
SUITES = {
    "quick":     {"prefill": ["2K", "8K"], "prefill_rep": 1,
                  "prefill_conc": {"ladder": ["1K", "4K", "8K"], "conc": 4}, "decode_tok": 256, "decode_rep": 1,
                  "conc": [1, 4, 8], "conc_rounds": 1, "longctx": []},
    "standard":  {"prefill": ["1K", "2K", "4K", "8K", "16K"], "prefill_rep": 2,
                  "prefill_conc": {"ladder": ["1K", "2K", "3K", "4K", "5K", "6K", "7K", "8K"], "conc": 4},
                  "decode_tok": 384, "decode_rep": 2, "conc": [1, 2, 4, 8, 16], "conc_rounds": 2, "longctx": []},
    "full":      {"prefill": ["1K", "2K", "4K", "8K", "16K", "32K", "64K", "128K"],
                  "prefill_rep": 2, "decode_tok": 512, "decode_rep": 3, "conc": [1, 2, 4, 8, 16, 32, 48, 64],
                  "conc_rounds": 2, "longctx": [32768, 65536],
                  "prefill_conc": {"ladder": ["1K", "2K", "4K", "6K", "8K", "10K", "12K", "16K"], "conc": 4}}
}


def probe_env(base_url, headers, model=None):
    """服务上的模型列表, 以及被测模型的最大上下文(vLLM / SGLang 的 /v1/models 会给 max_model_len)。"""
    env = {"gateway": base_url}
    try:
        req = urllib.request.Request(base_url.rstrip("/") + "/v1/models", headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            models = json.loads(r.read()).get("data") or []
        env["models_visible"] = [m.get("id") for m in models]
        mine = next((m for m in models if m.get("id") == model), None)
        if mine and isinstance(mine.get("max_model_len"), int) and mine["max_model_len"] > 0:
            env["max_model_len"] = mine["max_model_len"]
    except Exception as e:
        env["models_visible"] = "unavailable: %s" % str(e)[:80]
    return env


def normalize_base(base):
    """统一规整为不带 /v1 的 base: 支持 .../v1/chat/completions、.../v1、裸 base。"""
    b = base.strip().rstrip("/")
    for suffix in ("/chat/completions", "/v1"):
        if b.endswith(suffix):
            b = b[: -len(suffix)]
    return b


def lens_to_ladder(lens_k):
    """K 列表 -> 长度档位标签, 如 [1, 8] -> ["1K", "8K"]; 拼几句在测试开始校准后再算。"""
    return ["%dK" % k for k in lens_k]


def detect_framework(base_url, headers):
    """尝试从引擎 /version 与 /metrics 探测框架名与版本, 失败返回空。"""
    name, ver = "", ""
    try:
        req = urllib.request.Request(base_url.rstrip("/") + "/version", headers=headers)
        with urllib.request.urlopen(req, timeout=4) as r:
            d = json.loads(r.read())
            ver = str(d.get("version", "")).strip()
    except Exception:
        pass
    if not ver:
        try:
            req = urllib.request.Request(base_url.rstrip("/") + "/metrics", headers=headers)
            with urllib.request.urlopen(req, timeout=4) as r:
                for line in r.read().decode().splitlines():
                    if line.startswith("vllm:version{") or line.startswith("vllm:version "):
                        ver = line.rsplit(" ", 1)[-1].strip().strip('"')
                        break
        except Exception:
            pass
    return {"name": name or ("vLLM" if ver else ""), "version": ver}


def _warm_one(url, headers, model, prompt):
    try:
        stream_call(url, {"model": model, "messages": [{"role": "user", "content": prompt}],
                          "max_tokens": 32, "temperature": 0}, headers, timeout=120)
    except RuntimeError as e:  # 空流不致命(如被截断); 连接类错误与取消照常抛出
        plog("warmup warning: %s" % e)
    except urllib.error.HTTPError as e:  # 超过最大上下文的形状不预热(正式测量时这一档会跳过); 其他 HTTP 错误照常抛出
        if not ctx_overflow(e):
            raise
        plog("warmup skip: %s" % ctx_overflow(e))


def _warmup(url, headers, model, cfg, warmup_shapes):
    """按"实际会跑的 (输入长度, 并发) 组合"各预热一发(out=32, 结果丢弃), 覆盖引擎按 batch shape 的
    编译/cudagraph/缓存冷启动, 避免首个格子吃到冷启动开销。cfg 里的档位已按校准结果算好句数(resolve_ladder)。
    (最开始那一发单独的热身在校准之前, 见 run_suite)"""
    if not warmup_shapes:
        return
    one = functools.partial(_warm_one, url, headers, model)
    shapes = [(reps, 1) for _, reps, _ in (cfg.get("prefill") or [])]
    pc = cfg.get("prefill_conc")
    if pc:
        shapes += [(reps, int(pc.get("conc") or 4)) for _, reps, _ in (pc.get("ladder") or [])]
    shapes += [(1, c) for c in (1, 4, 8) if c in (cfg.get("conc") or [])]
    seen, uniq = set(), []
    for s in shapes:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    for reps, conc in uniq[:16]:
        check_cancel()
        prompt = "（预热 %d）请阅读后用一句话概括：" % (int(time.time() * 1000) % 1000000) + (ZH_UNIT * reps)
        with ThreadPoolExecutor(max_workers=conc) as ex:
            list(ex.map(lambda _: one(prompt), range(conc)))
        plog("  warmup shape: 输入x%d句 × 并发%d" % (reps, conc))


def run_suite(url, model, api_key="", suite="standard", metrics_url=None, tag="",
              outdir=None, custom=None, conc_ladder=None, matrix_conc=None, lens=None,
              framework=None, fw_version=None, sink=None, fixed_output=True, cancel=None, notes=None,
              scenarios=None, replay=None, warmup_shapes=True, retry_max_attempts=3, retry_pause_s=30):
    """可编程入口: server.py 与 CLI 共用。sink 默认写 outdir/<run_id>.json; 返回落地位置; 失败抛异常。
    fixed_output: 请求带 ignore_eos, 每次输出都跑满 max_tokens, 使不同后端/模型的吞吐可比(任务场景/回放除外)。
    cancel: threading.Event, 置位后在下一个请求前停止, 已完成阶段保留, 状态记为 cancelled。
    scenarios: 任务场景配置 {"tasks": ["chat","code","json","rag","vision","custom"], "conc": [...],
              "requests_per_worker": n, "max_tokens": n, "rag_ctx": [...], "vision_dir": 路径(不给则用内置示例图片), "vision_images": n,
              "custom_file": 路径, "task_set": {"id", "name"}(可选: 页面上导入的任务集, 记进结果)}; 默认不启用任何场景。
    replay: 真实请求回放配置 dict({"file": 路径, "closed": {...}, "open": {"rates": [...], "duration_s": n}, ...})。
    warmup_shapes: 按 batch shape 预热; retry_*: 场景/矩阵格失败整格重跑(留痕)。"""
    global _REQ_EXTRA, _CANCEL
    _REQ_EXTRA = {"ignore_eos": True} if fixed_output else {}
    _CANCEL = cancel
    outdir = outdir or os.path.join(ROOT, "data", "results")
    headers = {"Authorization": "Bearer " + api_key} if api_key else {}
    if suite != "custom":
        cfg = copy.deepcopy(SUITES[suite])  # 深拷贝: 下方覆盖项不得污染常驻进程里的全局套件
    else:
        with open(custom, encoding="utf-8") as f:
            cfg = json.load(f)
    if conc_ladder:
        cfg["conc"] = list(conc_ladder)
    if matrix_conc and cfg.get("prefill_conc"):
        cfg["prefill_conc"]["conc"] = int(matrix_conc)
    if lens:
        cfg["prefill"] = lens_to_ladder(lens)
        if cfg.get("prefill_conc"):
            cfg["prefill_conc"]["ladder"] = lens_to_ladder(lens)
    if scenarios and scenarios.get("tasks"):
        for t in scenarios["tasks"]:
            if t not in SCN_TEMPLATES:
                raise RuntimeError("未知任务类型: %s (可选: %s)" % (t, "/".join(SCN_TEMPLATES)))
    rp_pool = None
    if replay:
        rfile = replay.get("file") or replay.get("path") or ""
        if not rfile or not os.path.isfile(rfile):
            raise RuntimeError("回放文件不存在: %s" % rfile)
        rp_pool = ReplayPool(rfile,
                             max_prompt_tokens=int(replay.get("max_prompt_tokens") or 60000),
                             seed=int(replay.get("seed") or 1),
                             mt_default=int(replay.get("max_tokens_default") or 4096),
                             mt_cap=int(replay.get("max_tokens_cap") or 8192))

    base_url = normalize_base(url)
    fw = detect_framework(base_url, headers)
    if framework:
        fw["name"] = framework
    if fw_version:
        fw["version"] = fw_version
    run_id = "run_%s_%s" % (datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"), re.sub(r"[^A-Za-z0-9.-]", "_", model))
    result = {"bench_version": BENCH_VERSION, "run_id": run_id, "tag": tag, "suite": suite,
              "started_utc": datetime.now(timezone.utc).isoformat(), "url": url, "model": model,
              "env": probe_env(base_url, headers, model), "phases": [],
              "overrides": {"conc_ladder": conc_ladder or None, "matrix_conc": matrix_conc or None, "lens": lens or None,
                            "fixed_output": bool(fixed_output), "warmup_shapes": bool(warmup_shapes)},
              "framework": fw}
    if notes:
        result["notes"] = list(notes)
    if replay and rp_pool is not None:
        result["replay"] = {"file": os.path.basename(rp_pool.path), "pool_size": len(rp_pool),
                            "skipped": rp_pool.skipped, "bad": rp_pool.bad}
    sink = sink or sinks.JsonFileSink(outdir)

    def save():
        sink.save(result)

    plog("== llm-bench-pro v%s | %s | suite=%s ==" % (BENCH_VERSION, model, suite))
    rec = MetricsRecorder(metrics_url, headers, bool(metrics_url))
    skips = []  # 超过模型最大上下文而没测的档位
    result["status"] = "running"
    try:
        save()
        plog("warmup...")
        _warm_one(url, headers, model, "回复 OK")
        cal = calibrate_prompt(url, headers, model)
        result["prompt_calibration"] = cal
        plog("  长度校准: " + _cal_text(cal))
        cfg["prefill"] = resolve_ladder(cfg.get("prefill") or [], cal)
        if cfg.get("prefill_conc"):
            cfg["prefill_conc"]["ladder"] = resolve_ladder(cfg["prefill_conc"].get("ladder") or [], cal)
        max_len = result["env"].get("max_model_len")
        if max_len:  # 放不下的档位开测前就去掉(不知道最大上下文时, 由各阶段在服务拒绝时跳过)
            cfg["prefill"], sk = fit_context(cfg["prefill"], max_len, 96, "prefill")
            skips.extend(sk)
            if cfg.get("prefill_conc"):
                cfg["prefill_conc"]["ladder"], sk = fit_context(cfg["prefill_conc"]["ladder"], max_len, 128, "prefill_conc")
                skips.extend(sk)
            for ctx in cfg.get("longctx", []):
                if ctx + 256 > max_len:
                    skips.append({"phase": "longctx", "label": "%dK" % (ctx // 1024),
                                  "reason": "超过模型的最大上下文（%d token）" % max_len})
            cfg["longctx"] = [c for c in cfg.get("longctx", []) if c + 256 <= max_len]
            for s in skips:
                plog("  %s 跳过: %s" % (s["label"], s["reason"]))
        _warmup(url, headers, model, cfg, warmup_shapes)
        plog("[phase] prefill")
        result["phases"].append(phase_prefill(url, headers, model, cfg["prefill"], 96, cfg["prefill_rep"])); save()
        pc = cfg.get("prefill_conc")
        if pc:
            plog("[phase] prefill-conc (x%d)" % pc["conc"])
            result["phases"].append(phase_prefill_conc(url, headers, model, pc["ladder"], pc["conc"], 128,
                                                       retry_max_attempts, retry_pause_s)); save()
        plog("[phase] decode")
        result["phases"].append(phase_decode(url, headers, model, cfg["decode_tok"], cfg["decode_rep"])); save()
        plog("[phase] concurrency")
        result["phases"].append(phase_concurrency(url, headers, model, cfg["conc"], cfg["decode_tok"], cfg["conc_rounds"])); save()
        for tpl_id in (scenarios or {}).get("tasks") or []:
            plog("[phase] scenario:%s (%s)" % (tpl_id, SCN_TEMPLATES[tpl_id]["label"]))
            result["phases"].append(phase_scenario(url, headers, model, tpl_id, scenarios)); save()
        if rp_pool is not None:
            rcfg = replay.get("closed") or {}
            if rcfg.get("conc"):
                plog("[phase] replay 闭环")
                result["phases"].append(phase_replay_closed(url, headers, model, rcfg, rp_pool)); save()
            ocfg = replay.get("open") or {}
            if ocfg.get("rates"):
                plog("[phase] replay 开环 (泊松到达)")
                result["phases"].append(phase_replay_open(url, headers, model, ocfg, rp_pool)); save()
            result["replay"]["wrapped"] = rp_pool.wrapped
        for ctx in cfg.get("longctx", []):
            plog("[phase] longctx %dK" % (ctx // 1024))
            result["phases"].append(phase_longctx(url, headers, model, ctx, 256, cal)); save()
        result["status"] = "done"
    except Cancelled:
        result["status"] = "cancelled"
        result["error"] = "用户取消"
        plog("已取消: 已完成的阶段已保存")
    except KeyboardInterrupt:
        result["status"] = "interrupted"
        plog("interrupted - partial results kept")
    except BaseException as e:
        result["status"] = "failed"
        result["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
        raise
    finally:
        skips.extend(s for ph in result["phases"] for s in ph.get("skipped") or [])
        if skips:
            result["length_skips"] = skips
        result["metrics_samples"] = rec.close()
        result["finished_utc"] = datetime.now(timezone.utc).isoformat()
        if fixed_output and url in _NO_IGNORE_EOS:
            result["overrides"]["fixed_output"] = False
            result["overrides"]["fixed_output_note"] = "端点不支持 ignore_eos, 输出长度未固定"
        _CANCEL = None
        save()
    plog("done => %s" % sink.location)
    return sink.location


def main():
    ap = argparse.ArgumentParser(description="llm-bench-pro 推理基准引擎")
    ap.add_argument("--url", required=True, help="完整 chat completions URL (或 base URL, 自动规整)")
    ap.add_argument("--model", required=True)
    ap.add_argument("--api-key", default=os.environ.get("BENCH_API_KEY", ""))
    ap.add_argument("--suite", choices=list(SUITES) + ["custom"], default="standard")
    ap.add_argument("--metrics-url", default=None, help="vLLM /metrics 地址 (框架指标抓取)")
    ap.add_argument("--tag", default="", help="运行标签, 如 '1.6.5 vs 1.6.3'")
    ap.add_argument("--outdir", default=os.path.join(ROOT, "data", "results"), help="结果目录 (默认 data/results/, 页面服务启动时自动导入)")
    ap.add_argument("--custom", default=None, help="自定义套件 JSON 文件 (suite=custom 时)")
    ap.add_argument("--conc-ladder", default=None, help="自定义并发阶梯, 逗号分隔, 如 1,2,4,8")
    ap.add_argument("--matrix-conc", type=int, default=None, help="提示词阶梯x并发的并发路数 (默认 4)")
    ap.add_argument("--lens", default=None, help="自定义长度阶梯(K), 逗号分隔, 如 1,2,4,8,16")
    ap.add_argument("--framework", default=None, help="后端框架名称, 如 1Cat-vLLM / vLLM / SGLang")
    ap.add_argument("--fw-version", default=None, help="框架版本号, 如 1.6.5-sm70main")
    ap.add_argument("--no-fixed-output", action="store_true", help="不发送 ignore_eos(允许模型提前结束输出)")
    ap.add_argument("--scn", default=None,
                    help="任务场景, 逗号分隔: chat/code/json/rag/vision/custom (默认不启用任何场景)")
    ap.add_argument("--scn-conc", default=None, help="任务场景并发列表, 逗号分隔, 如 4,8 (默认 4,8)")
    ap.add_argument("--scn-rpw", type=int, default=3, help="任务场景每并发请求数 (默认 3)")
    ap.add_argument("--rag-ctx", default=None, help="RAG 场景上下文档位(token), 逗号分隔, 如 1500,4000,16000")
    ap.add_argument("--vision-dir", default=None, help="图片理解场景的图片目录(服务器路径); 不填用内置示例图片")
    ap.add_argument("--vision-img", type=int, default=1, help="图片理解每请求图片数 1-4 (默认 1)")
    ap.add_argument("--custom-file", default=None, help="自定义任务集 JSONL (每行 {messages, params})")
    ap.add_argument("--replay-file", default=None, help="真实请求回放 JSONL 文件 (每行 {messages, params})")
    ap.add_argument("--replay-conc", default=None, help="回放闭环并发列表, 逗号分隔, 如 8,16")
    ap.add_argument("--replay-rates", default=None, help="回放开环速率列表(req/s), 逗号分隔, 如 2,5; 传了才跑开环")
    ap.add_argument("--rate-duration", type=int, default=60, help="开环每档速率持续秒数 (默认 60)")
    ap.add_argument("--no-shape-warmup", action="store_true", help="关闭按 batch shape 的预热")
    ap.add_argument("--sink", choices=["json", "db", "both"], default="json",
                    help="结果落地: json=outdir 文件(默认) / db=SQLite 库 / both")
    ap.add_argument("--db", default=None, help="SQLite 库路径 (默认 data/llm_bench.db 或 $LLM_BENCH_DB)")
    args = ap.parse_args()
    url = args.url if args.url.endswith("/chat/completions") else normalize_base(args.url) + "/v1/chat/completions"
    ladder = None
    if args.conc_ladder:
        try:
            ladder = sorted({int(x) for x in args.conc_ladder.split(",") if x.strip()})
        except ValueError:
            plog("--conc-ladder 格式错误, 应为逗号分隔整数"); sys.exit(2)
    lens_list = None
    if args.lens:
        try:
            lens_list = sorted({int(x) for x in args.lens.split(",") if x.strip()})
            if not (1 <= min(lens_list) and max(lens_list) <= 256):
                raise ValueError("range")
        except ValueError:
            plog("--lens 格式错误: 应为 1-256 的逗号分隔整数(K)"); sys.exit(2)

    def _int_list(text, flag):
        try:
            return [int(x) for x in text.split(",") if x.strip()]
        except ValueError:
            plog("%s 格式错误, 应为逗号分隔整数" % flag); sys.exit(2)

    scen_cfg = None
    if args.scn:
        scen_cfg = {"tasks": [t.strip() for t in args.scn.split(",") if t.strip()]}
        if args.scn_conc:
            scen_cfg["conc"] = _int_list(args.scn_conc, "--scn-conc")
        scen_cfg["requests_per_worker"] = args.scn_rpw
        if args.rag_ctx:
            scen_cfg["rag_ctx"] = _int_list(args.rag_ctx, "--rag-ctx")
        if args.vision_dir:
            scen_cfg["vision_dir"] = args.vision_dir
        scen_cfg["vision_images"] = max(1, min(4, args.vision_img))
        if args.custom_file:
            scen_cfg["custom_file"] = args.custom_file
    replay_cfg = None
    if args.replay_file:
        replay_cfg = {"file": args.replay_file}
        if args.replay_conc:
            replay_cfg["closed"] = {"conc": _int_list(args.replay_conc, "--replay-conc")}
        if args.replay_rates:
            try:
                replay_cfg["open"] = {"rates": [float(x) for x in args.replay_rates.split(",") if x.strip()],
                                      "duration_s": args.rate_duration}
            except ValueError:
                plog("--replay-rates 格式错误, 应为逗号分隔数字"); sys.exit(2)
    try:
        run_suite(url, args.model, args.api_key, args.suite, args.metrics_url, args.tag, args.outdir, args.custom,
                  conc_ladder=ladder, matrix_conc=args.matrix_conc, lens=lens_list,
                  framework=args.framework, fw_version=args.fw_version,
                  sink=sinks.from_cli(args.sink, args.outdir, args.db), fixed_output=not args.no_fixed_output,
                  scenarios=scen_cfg, replay=replay_cfg, warmup_shapes=not args.no_shape_warmup)
    except SystemExit:
        raise
    except Exception as e:
        plog("BENCH FAILED: %s" % e)
        sys.exit(2)


if __name__ == "__main__":
    main()
