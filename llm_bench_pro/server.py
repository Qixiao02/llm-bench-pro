#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llm-bench-pro 服务: UI 页面 + 模型探测 + 在线起测 + 结果接口 (纯标准库)。
启动: python run.py [端口] [--host 127.0.0.1] [--token 访问令牌]
"""
import argparse
import glob
import hmac
import http.cookies
import json
import os
import re
import shutil
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_PKG_DIR)  # 项目根
if _PKG_DIR not in sys.path:
    sys.path.insert(0, _PKG_DIR)

import bankman  # noqa: E402
import bench  # noqa: E402
import gen  # noqa: E402
import geneval  # noqa: E402
import iq  # noqa: E402
import sinks  # noqa: E402
import store  # noqa: E402
from version import APP_VERSION  # noqa: E402

RESULTS = os.path.join(ROOT, "results")  # 旧版 JSON 结果: 启动时自动导入库(仅新增)
WORKS = os.path.join(ROOT, "works")
WEB = os.path.join(ROOT, "web")
UI = os.path.join(WEB, "index.html")
_RUN_ID_RE = re.compile(r"^(run|iq|gen)_[A-Za-z0-9_.-]+$")
_STATIC_TYPES = {".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8",
                 ".svg": "image/svg+xml", ".woff2": "font/woff2", ".png": "image/png"}

STARTED_AT = time.time()
CONFIG = {"host": "127.0.0.1", "port": 18080, "token": ""}


def safe_join(base, rel):
    """把 rel 解析到 base 之下; 越界(../、绝对路径、盘符)返回 None。"""
    base = os.path.realpath(base)
    full = os.path.realpath(os.path.join(base, rel))
    try:
        if os.path.commonpath([base, full]) != base:
            return None
    except ValueError:  # Windows 跨盘符
        return None
    return full


def _code_mtime():
    files = glob.glob(os.path.join(_PKG_DIR, "*.py"))
    return max((os.path.getmtime(f) for f in files), default=0.0)


def _git_head():
    """读取当前提交(不依赖 git 命令)。"""
    try:
        gdir = os.path.join(ROOT, ".git")
        with open(os.path.join(gdir, "HEAD"), encoding="utf-8") as f:
            head = f.read().strip()
        if not head.startswith("ref:"):
            return head[:12]
        ref = head[4:].strip()
        p = os.path.join(gdir, *ref.split("/"))
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                return f.read().strip()[:12]
        with open(os.path.join(gdir, "packed-refs"), encoding="utf-8") as f:
            for line in f:
                if line.strip().endswith(ref):
                    return line.split()[0][:12]
    except OSError:
        pass
    return None


CODE_MTIME = _code_mtime()
COMMIT_AT_START = _git_head()


# ---------------------------------------------------------------- 后台任务

JOB_NAMES = {"perf": "性能测试", "iq": "能力评测", "gen": "代码生成"}


class Job:
    """一类后台任务(同类同一时刻只运行一个): 状态、日志、取消信号、访问的模型端点。"""

    def __init__(self, kind, log_limit=500):
        self.kind, self.log_limit = kind, log_limit
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.state = {"running": False, "log": [], "error": None, "run_id": None, "started_at": None,
                      "base": None, "title": None, "cancelling": False}

    def line(self, msg):
        with self.lock:
            self.state["log"].append({"t": round(time.time(), 1), "msg": str(msg)})
            self.state["log"] = self.state["log"][-self.log_limit:]

    def snapshot(self):
        with self.lock:
            return dict(self.state, log=list(self.state["log"]))

    def try_start(self, base, title, run_id=None):
        with self.lock:
            if self.state["running"]:
                return False
            self.cancel.clear()
            self.state.update({"running": True, "log": [], "error": None, "run_id": run_id, "base": base,
                               "title": title, "cancelling": False,
                               "started_at": datetime.now(timezone.utc).isoformat()})
            return True

    def set(self, **kw):
        with self.lock:
            self.state.update(kw)

    def run(self, target, progress_attr=None, module=None):
        """在后台线程中执行 target(job); 统一记录异常与结束状态。"""
        def body():
            if module is not None:
                setattr(module, progress_attr, self.line)
            try:
                target(self)
            except Exception as e:
                err = "%s: %s" % (type(e).__name__, str(e)[:300])
                self.set(error=err)
                self.line("FAILED: %s" % err)
            finally:
                if module is not None:
                    setattr(module, progress_attr, None)
                self.set(running=False, cancelling=False)
        threading.Thread(target=body, daemon=True, name="job-" + self.kind).start()


JOBS = {k: Job(k) for k in JOB_NAMES}
_bank_building = threading.Lock()


def endpoint_key(base):
    u = urllib.parse.urlsplit(bench.normalize_base(base or "").lower())
    host = u.hostname or ""
    if host in ("localhost", "::1"):
        host = "127.0.0.1"
    return "%s:%s" % (host, u.port or (443 if u.scheme == "https" else 80))


def endpoint_conflict(kind, base):
    """性能测试与其他测试同时访问同一模型端点时, 吞吐/延迟数据会被污染。返回冲突任务名或 None。"""
    key = endpoint_key(base)
    for k, job in JOBS.items():
        if k == kind:
            continue
        st = job.snapshot()
        if st["running"] and st["base"] and endpoint_key(st["base"]) == key and "perf" in (k, kind):
            return JOB_NAMES[k]
    return None


def running_run_ids():
    return {j.snapshot()["run_id"] for j in JOBS.values() if j.snapshot()["running"]} - {None}


def iq_wrong(run_id, sid, limit=300):
    """某次能力评测某科目的未答对题目: 题干/选项/标准答案 + 模型答案/截断/错误/正文尾部。"""
    if not run_id.startswith("iq_") or not _RUN_ID_RE.match(run_id):
        return {"ok": False, "error": "非法 run_id"}
    doc = store.get_run(run_id)
    if not doc:
        return {"ok": False, "error": "run 不存在"}
    try:
        bank = bankman.load_bank(doc.get("bank_id") or "")
        sub_items = next((s["items"] for s in bank["subjects"] if s["id"] == sid), [])
    except FileNotFoundError:
        sub_items = []
    wrong = sorted((it for it in doc.get("items", []) if it.get("sid") == sid and not it.get("ok")),
                   key=lambda it: it["idx"] if isinstance(it.get("idx"), int) else 0)[:limit]
    rows = []
    for it in wrong:
        q = sub_items[it["idx"]] if isinstance(it.get("idx"), int) and it["idx"] < len(sub_items) else {}
        rows.append({"idx": it.get("idx"), "q": (q.get("q") or "")[:600], "choices": q.get("choices"),
                     "answer": q.get("answer"), "checks": q.get("checks"), "pred": it.get("pred"),
                     "trunc": bool(it.get("trunc")), "err": it.get("err"), "finish": it.get("finish"),
                     "out": it.get("out"), "tail": it.get("tail"), "sub": q.get("sub")})
    return {"ok": True, "run_id": run_id, "sid": sid, "iq_version": doc.get("iq_version"),
            "bank_found": bool(sub_items), "rows": rows}


def iq_compare(a_id, b_id):
    if not (a_id.startswith("iq_") and b_id.startswith("iq_") and _RUN_ID_RE.match(a_id) and _RUN_ID_RE.match(b_id)):
        return {"ok": False, "error": "非法 run_id"}
    a, b = store.get_run(a_id), store.get_run(b_id)
    if not a or not b:
        return {"ok": False, "error": "run 不存在"}
    return dict(iq.compare_runs(a, b), ok=True, a=a_id, b=b_id)


def _judge_cfg(body):
    """请求体中的视觉评审配置 (judge_base/judge_model/judge_key); 未填返回 None。"""
    base, model = (body.get("judge_base") or "").strip(), (body.get("judge_model") or "").strip()
    if not base or not model:
        return None
    return {"base": base, "model": model, "api_key": body.get("judge_key") or ""}


def _truthy(v):
    return v is True or (isinstance(v, (int, float)) and v == 1) or str(v).strip().lower() in ("1", "true", "yes", "on")


def _parse_sampling(raw):
    """sampling: "official" | "greedy" | {temperature, top_p, top_k}; 非法抛 ValueError。"""
    if raw in (None, "", "official", "greedy"):
        return raw or "official"
    if not isinstance(raw, dict):
        raise ValueError("sampling 格式错误")
    out = {}
    for k, lo, hi in (("temperature", 0.0, 2.0), ("top_p", 0.0, 1.0), ("top_k", -1, 1000)):
        v = raw.get(k)
        if v in (None, ""):
            continue
        v = int(v) if k == "top_k" else float(v)
        if not lo <= v <= hi:
            raise ValueError("%s 超出范围 %s–%s" % (k, lo, hi))
        out[k] = v
    return out


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    # ---- 鉴权
    def _token_from_request(self):
        tok = self.headers.get("X-Bench-Token") or ""
        if not tok:
            cookie = http.cookies.SimpleCookie(self.headers.get("Cookie") or "")
            if "bench_token" in cookie:
                tok = cookie["bench_token"].value
        return tok

    def _authorized(self, path, query):
        token = CONFIG["token"]
        if not token:
            return True
        if path.startswith("/works/"):
            return True  # 沙箱 iframe(无同源凭据)需要直接加载作品; 作品为模型生成的静态页面
        if hmac.compare_digest(self._token_from_request(), token):
            return True
        return False

    def do_GET(self):
        parts = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parts.path)
        query = urllib.parse.parse_qs(parts.query)
        q = lambda k: (query.get(k) or [""])[0]  # noqa: E731
        token = CONFIG["token"]
        if token and path in ("/", "/index.html") and q("token"):
            if hmac.compare_digest(q("token"), token):  # 带令牌打开页面: 写入 Cookie 后去掉地址栏中的令牌
                return self._redirect("/", {"Set-Cookie": "bench_token=%s; Path=/; HttpOnly; SameSite=Strict" % token})
        if not self._authorized(path, query):
            if path.startswith("/api/"):
                return self._json({"ok": False, "error": "需要访问令牌"}, 401)
            return self._body(("<!doctype html><meta charset=utf-8><title>LLM Bench Pro</title>"
                               "<p style='font:14px system-ui;margin:40px'>该服务启用了访问令牌，请使用 "
                               "<code>http://主机:端口/?token=令牌</code> 打开。</p>").encode(), "text/html; charset=utf-8", 401)

        if path in ("/", "/index.html"):
            return self._serve_file(UI, "text/html; charset=utf-8")
        if path.startswith("/static/"):
            full = safe_join(os.path.join(WEB, "static"), path[len("/static/"):])
            ctype = _STATIC_TYPES.get(os.path.splitext(full or "")[1].lower())
            if full and ctype and os.path.isfile(full):
                return self._serve_file(full, ctype)
            return self._json({"error": "not found"}, 404)
        if path.startswith("/works/"):
            full = safe_join(WORKS, path[len("/works/"):])
            ctype = {".html": "text/html; charset=utf-8", ".jpg": "image/jpeg"}.get(os.path.splitext(full or "")[1].lower())
            if full and ctype and os.path.isfile(full):
                return self._serve_file(full, ctype)
            return self._json({"error": "not found"}, 404)

        routes = {
            "/api/version": lambda: self._json(self.version_info()),
            "/api/results": lambda: self._json(store.list_runs("perf", summary=q("summary") == "1")),
            # 逐题 items 前端列表不读, 默认省略; ?full=1 返回完整文档
            "/api/iq-results": lambda: self._json(store.list_runs("iq", items=q("full") == "1")),
            "/api/gen-results": lambda: self._json(store.list_runs("gen")),
            "/api/iq-wrong": lambda: self._json(iq_wrong(q("id"), q("sid"))),
            "/api/iq-compare": lambda: self._json(iq_compare(q("a"), q("b"))),
            "/api/banks": lambda: self._json(bankman.list_banks()),
            "/api/status": lambda: self._json(JOBS["perf"].snapshot()),
            "/api/iq-status": lambda: self._json(JOBS["iq"].snapshot()),
            "/api/gen-status": lambda: self._json(JOBS["gen"].snapshot()),
        }
        if path in routes:
            return routes[path]()
        if path in ("/api/run", "/api/export"):
            run_id = q("id")
            doc = store.get_run(run_id) if _RUN_ID_RE.match(run_id) else None
            if doc is None:
                return self._json({"error": "run 不存在"}, 404)
            data = json.dumps(doc, ensure_ascii=False, indent=1 if path == "/api/export" else None).encode()
            extra = {"Content-Disposition": 'attachment; filename="%s.json"' % run_id} if path == "/api/export" else None
            return self._body(data, "application/json", headers=extra)
        self._json({"error": "not found"}, 404)

    def version_info(self):
        commit_now = _git_head()
        code_changed = _code_mtime() > CODE_MTIME + 1 or (commit_now is not None and commit_now != COMMIT_AT_START)
        return {"version": APP_VERSION, "pid": os.getpid(),
                "started_at": datetime.fromtimestamp(STARTED_AT, timezone.utc).isoformat(),
                "uptime_s": round(time.time() - STARTED_AT), "commit": COMMIT_AT_START, "commit_now": commit_now,
                "code_changed": code_changed, "db": store.default_db(), "host": CONFIG["host"], "port": CONFIG["port"],
                "auth": bool(CONFIG["token"]), "iq_version": iq.IQ_VERSION, "bench_version": bench.BENCH_VERSION,
                "gen_version": gen.GEN_VERSION}

    def do_POST(self):
        parts = urllib.parse.urlsplit(self.path)
        try:  # 先读完请求体: 提前返回错误而不读取时, Windows 上客户端可能收到连接重置而非错误响应
            length = min(int(self.headers.get("Content-Length", 0)), 16 * 1024 * 1024)
            raw = self.rfile.read(length) if length > 0 else b""
        except (ValueError, OSError):
            return self._json({"ok": False, "error": "bad request"}, 400)
        if not self._authorized(parts.path, {}):
            return self._json({"ok": False, "error": "需要访问令牌"}, 401)
        # 跨站/沙箱 iframe(Origin: null)中的作品页面不能调用接口: 要求同源, 且必须是 JSON 请求(跨站时会触发预检)
        origin = self.headers.get("Origin")
        if origin is not None and urllib.parse.urlsplit(origin).netloc != (self.headers.get("Host") or ""):
            return self._json({"ok": False, "error": "拒绝跨源请求"}, 403)
        if not (self.headers.get("Content-Type") or "").lower().startswith("application/json"):
            return self._json({"ok": False, "error": "Content-Type 必须为 application/json"}, 415)
        try:
            body = json.loads(raw or b"{}")
        except Exception:
            return self._json({"ok": False, "error": "bad json"}, 400)
        if not isinstance(body, dict):
            return self._json({"ok": False, "error": "bad json"}, 400)
        handler = {
            "/api/probe": self.api_probe, "/api/start": self.api_start, "/api/bank-update": self.api_bank_update,
            "/api/iq-start": self.api_iq_start, "/api/iq-resume": self.api_iq_resume,
            "/api/gen-start": self.api_gen_start, "/api/gen-rate": self.api_gen_rate, "/api/gen-eval": self.api_gen_eval,
            "/api/cancel": self.api_cancel, "/api/run-delete": self.api_run_delete,
        }.get(parts.path)
        if handler is None:
            return self._json({"ok": False, "error": "not found"}, 404)
        return handler(body)

    # ---- 通用
    def _busy_or_conflict(self, kind, base, body):
        """同类任务运行中 -> 409; 与性能测试共用同一端点 -> 409(code=endpoint_busy, 可带 force 确认后继续)。
        已写出拒绝响应时返回 True, 调用方必须立即返回。"""
        if JOBS[kind].snapshot()["running"]:
            self._json({"ok": False, "error": "已有%s在运行" % JOB_NAMES[kind]}, 409)
            return True
        other = endpoint_conflict(kind, base)
        if other and not body.get("force"):
            self._json({"ok": False, "code": "endpoint_busy", "conflict": other,
                        "error": "%s正在使用同一模型端点。同时运行会使性能测试的吞吐和延迟数据失真。" % other}, 409)
            return True
        return False

    def api_probe(self, body):
        """探测端点: /v1/models 拉取模型清单 + 延迟。"""
        base = bench.normalize_base(body.get("base", ""))
        if not re.match(r"^https?://", base):
            return self._json({"ok": False, "base": base, "error": "API 地址需以 http:// 或 https:// 开头"})
        api_key = body.get("api_key", "")
        headers = {"Authorization": "Bearer " + api_key} if api_key else {}
        t0 = time.perf_counter()
        try:
            req = urllib.request.Request(base + "/v1/models", headers=headers)
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            latency = round((time.perf_counter() - t0) * 1000)
            models = [{"id": m.get("id"), "max_model_len": m.get("max_model_len")} for m in data.get("data", [])]
            fw = bench.detect_framework(base, {})
            return self._json({"ok": True, "base": base, "latency_ms": latency,
                               "count": len(models), "models": models,
                               "framework": fw.get("name") or None, "fw_version": fw.get("version") or None})
        except Exception as e:
            return self._json({"ok": False, "base": base, "error": "%s: %s" % (type(e).__name__, str(e)[:200])})

    def api_cancel(self, body):
        kind = body.get("job")
        if kind not in JOBS:
            return self._json({"ok": False, "error": "job 应为 perf / iq / gen"}, 400)
        job = JOBS[kind]
        if not job.snapshot()["running"]:
            return self._json({"ok": False, "error": "没有运行中的%s" % JOB_NAMES[kind]}, 409)
        job.cancel.set()
        job.set(cancelling=True)
        job.line("收到停止请求：不再开始新的请求，已完成的结果会保留")
        return self._json({"ok": True})

    def api_run_delete(self, body):
        run_id = body.get("run_id") or ""
        if not isinstance(run_id, str) or not _RUN_ID_RE.match(run_id):
            return self._json({"ok": False, "error": "非法 run_id"}, 400)
        if run_id in running_run_ids():
            return self._json({"ok": False, "error": "该运行尚未结束，请先停止"}, 409)
        try:
            kind = store.delete_run(run_id)
        except ValueError as e:
            return self._json({"ok": False, "error": str(e)}, 409)
        if kind is None:
            return self._json({"ok": False, "error": "run 不存在"}, 404)
        if kind == "gen" and body.get("remove_works", True):
            d = safe_join(WORKS, run_id)
            if d and d != os.path.realpath(WORKS) and os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
        return self._json({"ok": True, "kind": kind})

    # ---- 性能测试
    def api_start(self, body):
        base = bench.normalize_base(body.get("base", ""))
        url = base + "/v1/chat/completions"
        model = (body.get("model") or "").strip()
        suite = body.get("suite", "standard")
        if not base or not model:
            return self._json({"ok": False, "error": "缺少 base/model"}, 400)
        if suite not in bench.SUITES:
            return self._json({"ok": False, "error": "未知测试套件"}, 400)
        ladder = None
        raw_ladder = (body.get("conc_ladder") or "").strip().strip(",")
        if raw_ladder:
            try:
                ladder = sorted({int(x) for x in raw_ladder.split(",") if x.strip()})
                if not (1 <= min(ladder) and max(ladder) <= 128):
                    raise ValueError("range")
            except (ValueError, TypeError):
                return self._json({"ok": False, "error": "并发梯度格式错误：应为 1-128 的逗号分隔整数，如 1,2,4,8"}, 400)
        matrix_conc = None
        raw_mc = str(body.get("matrix_conc") or "").strip()
        if raw_mc:
            try:
                matrix_conc = int(raw_mc)
                if not (1 <= matrix_conc <= 32):
                    raise ValueError("range")
            except ValueError:
                return self._json({"ok": False, "error": "矩阵并发数应为 1-32 的整数"}, 400)
        lens = None
        raw_lens = (body.get("lens") or "").strip().strip(",")
        if raw_lens:
            try:
                lens = sorted({int(x) for x in raw_lens.split(",") if x.strip()})
                if not (1 <= min(lens) and max(lens) <= 256):
                    raise ValueError("range")
            except (ValueError, TypeError):
                return self._json({"ok": False, "error": "输入长度梯度格式错误：应为 1-256 的逗号分隔整数（K），如 1,2,4,8,16"}, 400)
        if self._busy_or_conflict("perf", base, body):
            return
        job = JOBS["perf"]
        if not job.try_start(base, model):
            return self._json({"ok": False, "error": "已有性能测试在运行"}, 409)
        framework = (body.get("framework") or "").strip()[:60]
        fw_version = (body.get("fw_version") or "").strip()[:60]
        metrics_url = base + "/metrics" if body.get("metrics", True) else None
        tag = (body.get("tag") or "").strip()
        fixed_output = body.get("fixed_output", True) is not False
        notes = ["启动时%s正在使用同一端点，数据可能受干扰" % body.get("conflict_with", "其他测试")] if body.get("force") else None

        def target(j):
            sink = sinks.SqliteSink()
            bench.run_suite(url, model, body.get("api_key", ""), suite, metrics_url, tag, RESULTS,
                            conc_ladder=ladder, matrix_conc=matrix_conc, lens=lens,
                            framework=framework, fw_version=fw_version, sink=sink,
                            fixed_output=fixed_output, cancel=j.cancel, notes=notes)
            j.set(run_id=sink.run_id)
        job.run(target, "_PROGRESS_CB", bench)
        return self._json({"ok": True, "url": url, "metrics_url": metrics_url, "conc_ladder": ladder,
                           "matrix_conc": matrix_conc, "lens": lens, "fixed_output": fixed_output})

    # ---- 能力评测
    def api_bank_update(self, body):
        if not _bank_building.acquire(blocking=False):
            return self._json({"ok": False, "error": "题集正在更新中"}, 409)
        proxy = (body.get("proxy") or "").strip() or None
        try:
            bank, path = bankman.build(proxy=proxy)
            return self._json({"ok": True, "bank_id": bank["bank_id"], "total": bank["total"],
                               "subjects": [{"id": s["id"], "name": s["name"], "n": len(s["items"])} for s in bank["subjects"]]})
        except Exception as e:
            return self._json({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:200]),
                               "hint": "题源需可达 datasets-server.huggingface.co 与 raw.githubusercontent.com；网络不通时在“HTTP 代理”中填写 http://127.0.0.1:端口 后重试"})
        finally:
            _bank_building.release()

    def api_iq_start(self, body):
        base = bench.normalize_base(body.get("base", ""))
        url = base + "/v1/chat/completions"
        model = (body.get("model") or "").strip()
        bank_id = (body.get("bank_id") or "").strip()
        if not base or not model or not bank_id:
            return self._json({"ok": False, "error": "缺少 base/model/bank_id"}, 400)
        try:
            conc = max(1, min(32, int(body.get("conc") or 8)))
            limit = max(1, min(200, int(body["limit"]))) if body.get("limit") else None
            sampling = _parse_sampling(body.get("sampling"))
        except (TypeError, ValueError) as e:
            return self._json({"ok": False, "error": "参数错误：%s" % e}, 400)
        try:
            bank = bankman.load_bank(bank_id)
        except FileNotFoundError as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        if self._busy_or_conflict("iq", base, body):
            return
        job = JOBS["iq"]
        if not job.try_start(base, model):
            return self._json({"ok": False, "error": "已有能力评测在运行"}, 409)
        subject_ids = body.get("subjects") or None
        if subject_ids is not None and not (isinstance(subject_ids, list) and all(isinstance(x, str) for x in subject_ids)):
            job.set(running=False)
            return self._json({"ok": False, "error": "subjects 应为科目 id 列表"}, 400)
        thinking = _truthy(body.get("thinking"))

        def target(j):
            sink = sinks.SqliteSink()
            iq.run_iq(url, model, body.get("api_key", ""), bank, conc, RESULTS, (body.get("tag") or "").strip(),
                      (body.get("framework") or "").strip() or None, (body.get("fw_version") or "").strip() or None,
                      subject_ids, limit, thinking, sink=sink, sampling=sampling, cancel=j.cancel)
            j.set(run_id=sink.run_id)
        job.run(target, "_IQ_PROGRESS", iq)
        return self._json({"ok": True, "url": url, "bank_id": bank_id, "conc": conc,
                           "sampling": iq.resolve_sampling(thinking, sampling)})

    def api_iq_resume(self, body):
        run_id = body.get("run_id") or ""
        if not isinstance(run_id, str) or not run_id.startswith("iq_") or not _RUN_ID_RE.match(run_id):
            return self._json({"ok": False, "error": "非法 run_id"}, 400)
        doc = store.get_run(run_id)
        if not doc:
            return self._json({"ok": False, "error": "run 不存在"}, 404)
        retry_errors = doc.get("status") == "done" and (doc.get("overall") or {}).get("errors")
        if doc.get("status") not in ("cancelled", "interrupted", "failed") and not retry_errors:
            return self._json({"ok": False, "error": "只有已停止、中断、失败或含请求失败题目的运行可以续跑"}, 409)
        if doc.get("iq_version") != iq.IQ_VERSION:
            return self._json({"ok": False, "error": "该运行由评测程序 %s 生成，当前为 %s，判分口径不同，不能续跑，请重新运行"
                               % (doc.get("iq_version"), iq.IQ_VERSION)}, 409)
        try:
            bank = bankman.load_bank(doc.get("bank_id") or "")
        except FileNotFoundError as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        base = bench.normalize_base(doc.get("url") or "")
        if self._busy_or_conflict("iq", base, body):
            return
        job = JOBS["iq"]
        if not job.try_start(base, doc.get("model"), run_id=run_id):
            return self._json({"ok": False, "error": "已有能力评测在运行"}, 409)

        def target(j):
            iq.run_iq(doc["url"], doc["model"], body.get("api_key", ""), bank, sink=sinks.SqliteSink(),
                      cancel=j.cancel, resume=doc)
        job.run(target, "_IQ_PROGRESS", iq)
        return self._json({"ok": True, "run_id": run_id, "done_items": len(doc.get("items", []))})

    # ---- 代码生成
    def api_gen_start(self, body):
        base = bench.normalize_base(body.get("base", ""))
        url = base + "/v1/chat/completions"
        model = (body.get("model") or "").strip()
        if not base or not model:
            return self._json({"ok": False, "error": "缺少 base/model"}, 400)
        try:
            conc = max(1, min(8, int(body.get("conc") or 4)))
        except (TypeError, ValueError):
            return self._json({"ok": False, "error": "并发应为整数"}, 400)
        if self._busy_or_conflict("gen", base, body):
            return
        job = JOBS["gen"]
        if not job.try_start(base, model):
            return self._json({"ok": False, "error": "已有代码生成任务或重新评测在运行"}, 409)
        task_ids = body.get("tasks") or None
        judge = _judge_cfg(body)

        def target(j):
            sink = sinks.SqliteSink()
            gen.run_gen(url, model, body.get("api_key", ""), task_ids, conc, RESULTS, (body.get("tag") or "").strip(),
                        (body.get("framework") or "").strip() or None, (body.get("fw_version") or "").strip() or None,
                        _truthy(body.get("thinking")), sink=sink, judge=judge, cancel=j.cancel)
            j.set(run_id=sink.run_id)
        job.run(target, "_GEN_PROGRESS", gen)
        return self._json({"ok": True, "url": url, "tasks": len(task_ids) if task_ids else len(gen.GEN_TASKS),
                           "thinking": bool(body.get("thinking")), "eval": geneval.Evaluator(judge).meta()})

    def api_gen_eval(self, body):
        """对已有生成运行重新评测 (运行检测 + 可选视觉评审)。与代码生成共用任务状态/日志。"""
        run_id = body.get("run_id") or ""
        if not isinstance(run_id, str) or not run_id.startswith("gen_") or not _RUN_ID_RE.match(run_id):
            return self._json({"ok": False, "error": "非法 run_id"}, 400)
        if store.get_run(run_id, items=False) is None:
            return self._json({"ok": False, "error": "run 不存在"}, 404)
        only = set(body.get("tasks") or []) or None
        judge = _judge_cfg(body)
        job = JOBS["gen"]
        if not job.try_start(None, "重新评测", run_id=run_id):
            return self._json({"ok": False, "error": "已有代码生成任务或重新评测在运行"}, 409)
        job.run(lambda j: gen.reevaluate(run_id, judge, only=only, log=j.line, cancel=j.cancel), "_GEN_PROGRESS", gen)
        return self._json({"ok": True, "run_id": run_id, "eval": geneval.Evaluator(judge).meta()})

    def api_gen_rate(self, body):
        run_id, item_id = body.get("run_id") or "", body.get("item_id")
        stars = body.get("stars")
        if not isinstance(run_id, str) or not _RUN_ID_RE.match(run_id):
            return self._json({"ok": False, "error": "非法 run_id"}, 400)
        if stars is not None and not (isinstance(stars, int) and not isinstance(stars, bool) and 0 <= stars <= 5):
            return self._json({"ok": False, "error": "stars 应为 0-5 整数或 null"}, 400)
        try:
            # 单行 UPDATE: 运行中的生成测试也可打星, 后台增量写入从不触碰 stars
            if not store.rate_gen_item(run_id, item_id, stars or None):
                return self._json({"ok": False, "error": "run 或作品不存在"}, 404)
            return self._json({"ok": True})
        except Exception as e:
            return self._json({"ok": False, "error": str(e)[:200]}, 500)

    # ---- 输出
    def _json(self, obj, code=200):
        self._body(json.dumps(obj, ensure_ascii=False).encode(), "application/json", code)

    def _serve_file(self, path, ctype):
        with open(path, "rb") as f:
            self._body(f.read(), ctype)

    def _redirect(self, location, headers=None):
        self.send_response(302)
        self.send_header("Location", location)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _body(self, data, ctype, code=200, headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class BenchServer(ThreadingHTTPServer):
    """Windows 上默认的 SO_REUSEADDR 允许多个进程同时监听同一端口, 请求会随机落到旧进程。
    这里改用独占绑定: 端口已被占用时启动直接失败。"""
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.allow_reuse_address = False
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="LLM Bench Pro 服务")
    ap.add_argument("port", nargs="?", type=int, default=18080, help="监听端口 (默认 18080)")
    ap.add_argument("--host", default=os.environ.get("LLM_BENCH_HOST", "127.0.0.1"),
                    help="监听地址 (默认 127.0.0.1 仅本机; 局域网访问用 0.0.0.0, 建议同时设置 --token)")
    ap.add_argument("--token", default=os.environ.get("LLM_BENCH_TOKEN", ""),
                    help="访问令牌; 设置后需用 http://主机:端口/?token=令牌 打开页面")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    CONFIG.update(host=args.host, port=args.port, token=args.token)
    try:
        server = BenchServer((args.host, args.port), Handler)
    except OSError as e:
        print("✗ 无法监听 %s:%d（%s）\n  端口可能已被占用，常见原因是已有 LLM Bench Pro 在运行。"
              "\n  请先关闭旧进程，或换一个端口：python run.py %d" % (args.host, args.port, e, args.port + 1))
        sys.exit(1)
    db = store.default_db()
    store.init(db)
    imported = store.import_dir(RESULTS, only_new=True)
    stale = store.mark_stale_runs()
    shown = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    print("LLM Bench Pro %s => http://%s:%d%s  (db: %s)" % (APP_VERSION, shown, args.port,
                                                            "/?token=***" if args.token else "", db))
    if args.host not in ("127.0.0.1", "localhost", "::1") and not args.token:
        print("  ⚠ 正在监听 %s 且未设置访问令牌：局域网内任何人都可以发起测试、查看结果。建议加 --token" % args.host)
    if imported["inserted"] or imported["errors"] or stale:
        print("  导入旧 JSON %d 个, 失败 %d 个, 标记中断 %d 个" % (imported["inserted"], len(imported["errors"]), stale))
        for e in imported["errors"]:
            print("  ✗", e)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
