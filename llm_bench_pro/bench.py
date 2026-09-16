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
import copy
import json
import os
import re
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

try:
    from . import sinks  # 包内导入: python -m llm_bench_pro.bench
except ImportError:
    import sinks  # server.py 以包目录为 sys.path 顶层导入

# 1.1: 默认固定输出长度(ignore_eos, 端点不支持时自动关闭并记录), 可取消
BENCH_VERSION = "1.1.0"
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


# ---------------------------------------------------------------- HTTP 基础

def http_json(url, payload, headers, timeout=900):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def stream_call(url, payload, headers, timeout=900):
    """流式调用, 返回精确的时间戳序列 (SSE 逐 chunk 解析)。"""
    check_cancel()
    payload = {**_REQ_EXTRA, **payload, "stream": True, "stream_options": {"include_usage": True}}
    if url in _NO_IGNORE_EOS:
        payload.pop("ignore_eos", None)
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **headers})
    t0 = time.perf_counter()
    ttft, stamps, usage, chunks = None, [], {}, 0
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500] if e.fp else ""
        if e.code in (400, 422) and "ignore_eos" in payload and "ignore_eos" in detail:
            _NO_IGNORE_EOS.add(url)  # 端点不支持固定输出长度: 关闭后重试, 结果中会记录
            plog("  端点不支持 ignore_eos, 已关闭固定输出长度")
            return stream_call(url, {k: v for k, v in payload.items() if k not in ("stream", "stream_options")}, headers, timeout)
        raise
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
                    # 推理模型的思考 token 走 reasoning_content, 同样计入首 token 与解码时间戳
                    if delta.get("content") or delta.get("reasoning_content") or delta.get("reasoning"):
                        now = time.perf_counter()
                        chunks += 1
                        if ttft is None:
                            ttft = now - t0
                        stamps.append(now)
    if not stamps:
        raise RuntimeError("empty stream (no content/reasoning deltas)")
    return {"ttft": ttft, "stamps": stamps, "wall": time.perf_counter() - t0,
            "usage": usage, "chunks": chunks}


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


# ---------------------------------------------------------------- 测试阶段

def phase_prefill(url, headers, model, ladder, out_tok, rep):
    """上下文阶梯: 每档重复 rep 次取中位数; 唯一批次号避免前缀缓存命中虚高。"""
    points = []
    session_nonce = int(time.time() * 1000) % 1000000
    for label, reps in ladder:
        check_cancel()
        runs = []
        for seq in range(rep):
            prompt = ("以下是一段技术文本（批次 %d-%d），请仔细阅读后用一句话总结主题：\n"
                      % (session_nonce, seq)) + (ZH_UNIT * reps)
            s = stream_call(url, {"model": model, "messages": [{"role": "user", "content": prompt}],
                                  "max_tokens": out_tok, "temperature": 0}, headers)
            runs.append(derive(s))
        ttfts = [r["ttft_s"] for r in runs if r["ttft_s"]]
        tps = [r["prefill_tps"] for r in runs if r["prefill_tps"]]
        points.append({
            "label": label, "in_tokens": runs[0]["in_tokens"],
            "ttft_med_s": round(statistics.median(ttfts), 3) if ttfts else None,
            "prefill_tps_med": round(statistics.median(tps), 1) if tps else None,
            "runs": runs,
        })
        plog("  %-6s in=%-7d ttft=%6.2fs  prefill=%8.0f t/s" %
              (label, points[-1]["in_tokens"], points[-1]["ttft_med_s"] or 0, points[-1]["prefill_tps_med"] or 0))
    return {"id": "prefill", "name": "Prefill 阶梯", "points": points}


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
                        results.append({"error": str(e)[:120]})

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


def phase_prefill_conc(url, headers, model, ladder, conc, out_tok):
    """提示词长度阶梯 × 并发矩阵: 每档并发起跑, 记录 TTFT/ITL/聚合吞吐/成功率, 并汇总分位数。"""
    points = []
    session_nonce = int(time.time() * 1000) % 1000000
    for label, reps in ladder:
        check_cancel()
        barrier = threading.Barrier(conc)
        lock, results = threading.Lock(), []

        def worker(i):
            try:
                barrier.wait(timeout=60)
            except threading.BrokenBarrierError:
                return
            prompt = ("以下是技术参考资料（批次 %d-%d），请阅读后用两句话总结要点：" % (session_nonce, i)) + chr(10) + (ZH_UNIT * reps)
            try:
                s = stream_call(url, {"model": model, "messages": [{"role": "user", "content": prompt}],
                                      "max_tokens": out_tok, "temperature": 0}, headers)
                with lock:
                    results.append(derive(s))
            except Exception as e:
                with lock:
                    results.append({"error": str(e)[:120]})

        with ThreadPoolExecutor(max_workers=conc) as ex:
            list(ex.map(worker, range(conc)))
        good = [r for r in results if "error" not in r]
        bad = len(results) - len(good)
        if good and any(r["ttft_s"] for r in good):
            in_tot = sum(r["in_tokens"] for r in good)
            out_tot = sum(r["out_tokens"] for r in good)
            ttfts = [r["ttft_s"] for r in good if r["ttft_s"]]
            max_ttft = max(ttfts)
            max_dspan = max(r["decode_span_s"] for r in good)
            itls = [r["itl_p50_ms"] for r in good if r["itl_p50_ms"] is not None]
            points.append({
                "label": label, "in_tokens": good[0]["in_tokens"], "ok": len(good), "fail": bad,
                "ttft_avg_ms": round(1000 * sum(ttfts) / len(ttfts), 1),
                "ttft_max_ms": round(1000 * max_ttft, 1),
                "itl_avg_ms": round(sum(itls) / len(itls), 2) if itls else None,
                "prefill_tps_agg": round(in_tot / max(max_ttft, 1e-6), 1),
                "decode_tps_agg": round(out_tot / max(max_dspan, 1e-6), 1) if out_tot > 1 else None,
                "stream_prefill_tps": [round(r["in_tokens"] / r["ttft_s"], 1) for r in good if r["ttft_s"]],
                "stream_decode_tps": [r["decode_tps"] for r in good if r["decode_tps"]],
            })
            plog("  %-5s in=%-6d ttft_avg=%7.1fms  prefill_agg=%8.0f t/s  decode_agg=%7.1f t/s  ok=%d/%d" %
                 (label, points[-1]["in_tokens"], points[-1]["ttft_avg_ms"], points[-1]["prefill_tps_agg"],
                  points[-1]["decode_tps_agg"] or 0, len(good), len(good) + bad))
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
    return {"id": "prefill_conc", "name": "提示词阶梯×并发", "conc": conc, "points": points, "summary": summary}


def phase_longctx(url, headers, model, ctx_tokens, out_tok):
    """长上下文驻留: 大上下文注入后解码。"""
    reps = max(1, ctx_tokens // 78)  # ZH_UNIT ~78 token/句
    prompt = "以下是技术文档，请基于内容回答：\n" + (ZH_UNIT * reps) + "\n\n用三句话概括核心内容。"
    s = stream_call(url, {"model": model, "messages": [{"role": "user", "content": prompt}],
                          "max_tokens": out_tok, "temperature": 0}, headers)
    d = derive(s)
    plog("  ctx=%-7d in=%d  ttft=%6.2fs  prefill=%7.0f t/s  decode=%6.1f t/s" %
          (ctx_tokens, d["in_tokens"], d["ttft_s"] or 0, d["prefill_tps"] or 0, d["decode_tps"] or 0))
    return {"id": "longctx", "name": "长上下文驻留", "points": [d]}


# ---------------------------------------------------------------- 主流程

SUITES = {
    "quick":     {"prefill": [("2K", 26), ("8K", 103)], "prefill_rep": 1,
                  "prefill_conc": {"ladder": [("1K", 13), ("4K", 52), ("8K", 103)], "conc": 4}, "decode_tok": 256, "decode_rep": 1,
                  "conc": [1, 4, 8], "conc_rounds": 1, "longctx": []},
    "standard":  {"prefill": [("1K", 13), ("2K", 26), ("4K", 52), ("8K", 103), ("16K", 206)], "prefill_rep": 2,
                  "prefill_conc": {"ladder": [("1K", 13), ("2K", 26), ("3K", 39), ("4K", 52), ("5K", 65), ("6K", 78), ("7K", 91), ("8K", 103)], "conc": 4},
                  "decode_tok": 384, "decode_rep": 2, "conc": [1, 2, 4, 8, 16], "conc_rounds": 2, "longctx": []},
    "full":      {"prefill": [("1K", 13), ("2K", 26), ("4K", 52), ("8K", 103), ("16K", 206), ("32K", 413), ("64K", 826), ("128K", 1652)],
                  "prefill_rep": 2, "decode_tok": 512, "decode_rep": 3, "conc": [1, 2, 4, 8, 16, 32, 48, 64],
                  "conc_rounds": 2, "longctx": [32768, 65536],
                  "prefill_conc": {"ladder": [("1K", 13), ("2K", 26), ("4K", 52), ("6K", 78), ("8K", 103), ("10K", 129), ("12K", 155), ("16K", 206)], "conc": 4}}
}


def probe_env(base_url, headers):
    env = {"gateway": base_url}
    try:
        data = http_json(base_url.rstrip("/") + "/models", {}, dict(headers, **{"Content-Type": "application/json"}), 15)
        env["models_visible"] = [m.get("id") for m in data.get("data", [])]
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
    """K 列表 -> [(label, 句数)]; ZH_UNIT 实测约 77.5 token/句。"""
    return [("%dK" % k, max(1, round(k * 1000 / 77.5))) for k in lens_k]


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


def run_suite(url, model, api_key="", suite="standard", metrics_url=None, tag="",
              outdir=None, custom=None, conc_ladder=None, matrix_conc=None, lens=None,
              framework=None, fw_version=None, sink=None, fixed_output=True, cancel=None, notes=None):
    """可编程入口: server.py 与 CLI 共用。sink 默认写 outdir/<run_id>.json; 返回落地位置; 失败抛异常。
    fixed_output: 请求带 ignore_eos, 每次输出都跑满 max_tokens, 使不同后端/模型的吞吐可比。
    cancel: threading.Event, 置位后在下一个请求前停止, 已完成阶段保留, 状态记为 cancelled。"""
    global _REQ_EXTRA, _CANCEL
    _REQ_EXTRA = {"ignore_eos": True} if fixed_output else {}
    _CANCEL = cancel
    outdir = outdir or os.path.join(ROOT, "results")
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

    base_url = normalize_base(url)
    fw = detect_framework(base_url, headers)
    if framework:
        fw["name"] = framework
    if fw_version:
        fw["version"] = fw_version
    run_id = "run_%s_%s" % (datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"), re.sub(r"[^A-Za-z0-9.-]", "_", model))
    result = {"bench_version": BENCH_VERSION, "run_id": run_id, "tag": tag, "suite": suite,
              "started_utc": datetime.now(timezone.utc).isoformat(), "url": url, "model": model,
              "env": probe_env(base_url, headers), "phases": [],
              "overrides": {"conc_ladder": conc_ladder or None, "matrix_conc": matrix_conc or None, "lens": lens or None,
                            "fixed_output": bool(fixed_output)},
              "framework": fw}
    if notes:
        result["notes"] = list(notes)
    sink = sink or sinks.JsonFileSink(outdir)

    def save():
        sink.save(result)

    plog("== llm-bench-pro v%s | %s | suite=%s ==" % (BENCH_VERSION, model, suite))
    rec = MetricsRecorder(metrics_url, headers, bool(metrics_url))
    result["status"] = "running"
    try:
        save()
        plog("warmup...")
        try:
            stream_call(url, {"model": model, "messages": [{"role": "user", "content": "回复 OK"}],
                              "max_tokens": 16, "temperature": 0}, headers, timeout=120)
        except RuntimeError as e:  # 空流不致命(如被截断); 连接类错误与取消照常抛出
            plog("warmup warning: %s" % e)
        plog("[phase] prefill")
        result["phases"].append(phase_prefill(url, headers, model, cfg["prefill"], 96, cfg["prefill_rep"])); save()
        pc = cfg.get("prefill_conc")
        if pc:
            plog("[phase] prefill-conc (x%d)" % pc["conc"])
            result["phases"].append(phase_prefill_conc(url, headers, model, pc["ladder"], pc["conc"], 128)); save()
        plog("[phase] decode")
        result["phases"].append(phase_decode(url, headers, model, cfg["decode_tok"], cfg["decode_rep"])); save()
        plog("[phase] concurrency")
        result["phases"].append(phase_concurrency(url, headers, model, cfg["conc"], cfg["decode_tok"], cfg["conc_rounds"])); save()
        for ctx in cfg.get("longctx", []):
            plog("[phase] longctx %dK" % (ctx // 1024))
            result["phases"].append(phase_longctx(url, headers, model, ctx, 256)); save()
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
    ap.add_argument("--outdir", default=os.path.join(ROOT, "results"), help="结果目录 (默认项目根 results/, 与 UI 一致)")
    ap.add_argument("--custom", default=None, help="自定义套件 JSON 文件 (suite=custom 时)")
    ap.add_argument("--conc-ladder", default=None, help="自定义并发阶梯, 逗号分隔, 如 1,2,4,8")
    ap.add_argument("--matrix-conc", type=int, default=None, help="提示词阶梯x并发的并发路数 (默认 4)")
    ap.add_argument("--lens", default=None, help="自定义长度阶梯(K), 逗号分隔, 如 1,2,4,8,16")
    ap.add_argument("--framework", default=None, help="后端框架名称, 如 1Cat-vLLM / vLLM / SGLang")
    ap.add_argument("--fw-version", default=None, help="框架版本号, 如 1.6.5-sm70main")
    ap.add_argument("--no-fixed-output", action="store_true", help="不发送 ignore_eos(允许模型提前结束输出)")
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
    try:
        run_suite(url, args.model, args.api_key, args.suite, args.metrics_url, args.tag, args.outdir, args.custom,
                  conc_ladder=ladder, matrix_conc=args.matrix_conc, lens=lens_list,
                  framework=args.framework, fw_version=args.fw_version,
                  sink=sinks.from_cli(args.sink, args.outdir, args.db), fixed_output=not args.no_fixed_output)
    except SystemExit:
        raise
    except Exception as e:
        plog("BENCH FAILED: %s" % e)
        sys.exit(2)


if __name__ == "__main__":
    main()
