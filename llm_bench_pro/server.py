#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""llm-bench-pro 服务: UI 页面 + 模型探测 + 在线起测 + 结果接口 (纯标准库)。"""
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

import os as _os
import sys as _sys
_PKG_DIR = _os.path.dirname(_os.path.abspath(__file__))
ROOT = _os.path.dirname(_PKG_DIR)  # 项目根
if _PKG_DIR not in _sys.path:
    _sys.path.insert(0, _PKG_DIR)

import bankman
import bench
import gen
import iq

RESULTS = os.path.join(ROOT, "results")
WORKS = os.path.join(ROOT, "works")
UI = os.path.join(ROOT, "web", "index.html")
_RUN_ID_RE = re.compile(r"^gen_[A-Za-z0-9_.-]+$")


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

_state_lock = threading.Lock()
_state = {"running": False, "log": [], "error": None, "run_id": None, "started_at": None}

_gen_lock = threading.Lock()
_gen_state = {"running": False, "log": [], "error": None, "run_id": None, "started_at": None}
_rate_lock = threading.Lock()


def gen_status_line(msg):
    with _gen_lock:
        _gen_state["log"].append({"t": round(time.time(), 1), "msg": msg})
        _gen_state["log"] = _gen_state["log"][-400:]


def run_gen_benchmark(url, model, api_key, task_ids, conc, tag, framework, fw_version, thinking=False):
    gen._GEN_PROGRESS = gen_status_line
    try:
        with _gen_lock:
            _gen_state["error"] = None
        path = gen.run_gen(url, model, api_key, task_ids, conc, RESULTS, tag, framework, fw_version, thinking)
        with _gen_lock:
            _gen_state["run_id"] = os.path.basename(path).rsplit(".", 1)[0]
    except Exception as e:
        with _gen_lock:
            _gen_state["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
        gen_status_line("FAILED: %s" % _gen_state["error"])
    finally:
        gen._GEN_PROGRESS = None
        with _gen_lock:
            _gen_state["running"] = False


_iq_lock = threading.Lock()
_iq_state = {"running": False, "log": [], "error": None, "run_id": None, "started_at": None, "bank_building": False}


def iq_status_line(msg):
    with _iq_lock:
        _iq_state["log"].append({"t": round(time.time(), 1), "msg": msg})
        _iq_state["log"] = _iq_state["log"][-500:]


def run_iq_benchmark(url, model, api_key, bank_id, conc, tag, framework, fw_version, subject_ids, limit, thinking=False):
    iq._IQ_PROGRESS = iq_status_line
    try:
        with _iq_lock:
            _iq_state["error"] = None
        bank = bankman.load_bank(bank_id)
        path = iq.run_iq(url, model, api_key, bank, conc, RESULTS, tag,
                         framework, fw_version, subject_ids, limit, thinking)
        with _iq_lock:
            _iq_state["run_id"] = os.path.basename(path).rsplit(".", 1)[0]
    except Exception as e:
        with _iq_lock:
            _iq_state["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
        iq_status_line("FAILED: %s" % _iq_state["error"])
    finally:
        iq._IQ_PROGRESS = None
        with _iq_lock:
            _iq_state["running"] = False


def status_line(msg):
    with _state_lock:
        _state["log"].append({"t": round(time.time(), 1), "msg": msg})
        _state["log"] = _state["log"][-400:]


def run_benchmark(url, model, api_key, suite, tag, metrics_url, conc_ladder=None, matrix_conc=None, lens=None,
                  framework=None, fw_version=None):
    bench._PROGRESS_CB = status_line
    try:
        with _state_lock:
            _state["error"] = None
        path = bench.run_suite(url, model, api_key, suite, metrics_url, tag, RESULTS,
                               conc_ladder=conc_ladder, matrix_conc=matrix_conc, lens=lens,
                               framework=framework, fw_version=fw_version)
        with _state_lock:
            _state["run_id"] = os.path.basename(path).rsplit(".", 1)[0]
    except Exception as e:
        with _state_lock:
            _state["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
        status_line("FAILED: %s" % _state["error"])
    finally:
        bench._PROGRESS_CB = None
        with _state_lock:
            _state["running"] = False


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if path in ("/", "/index.html"):
            self._serve_file(UI, "text/html; charset=utf-8")
        elif path == "/api/results":
            runs = []
            if os.path.isdir(RESULTS):
                for fn in sorted(os.listdir(RESULTS)):
                    if not fn.endswith(".json"):
                        continue
                    try:
                        with open(os.path.join(RESULTS, fn), encoding="utf-8") as f:
                            obj = json.load(f)
                        if obj.get("kind") not in ("iq", "gen"):  # 性能结果无 kind 字段
                            runs.append(obj)
                    except Exception:
                        pass
            runs.sort(key=lambda r: r.get("started_utc", ""), reverse=True)
            self._body(json.dumps(runs, ensure_ascii=False).encode(), "application/json")
        elif path == "/api/status":
            with _state_lock:
                payload = dict(_state)
            self._body(json.dumps(payload, ensure_ascii=False).encode(), "application/json")
        elif path == "/api/iq-status":
            with _iq_lock:
                payload = dict(_iq_state)
            self._body(json.dumps(payload, ensure_ascii=False).encode(), "application/json")
        elif path == "/api/gen-status":
            with _gen_lock:
                payload = dict(_gen_state)
            self._body(json.dumps(payload, ensure_ascii=False).encode(), "application/json")
        elif path == "/api/gen-results":
            runs = []
            if os.path.isdir(RESULTS):
                for fn in sorted(os.listdir(RESULTS)):
                    if not (fn.startswith("gen_") and fn.endswith(".json")):
                        continue
                    try:
                        with open(os.path.join(RESULTS, fn), encoding="utf-8") as f:
                            runs.append(json.load(f))
                    except Exception:
                        pass
            runs.sort(key=lambda r: r.get("started_utc", ""), reverse=True)
            self._body(json.dumps(runs, ensure_ascii=False).encode(), "application/json")
        elif path.startswith("/works/"):
            full = safe_join(WORKS, path[len("/works/"):])
            if full and full.lower().endswith(".html") and os.path.isfile(full):
                self._serve_file(full, "text/html; charset=utf-8")
            else:
                self._json({"error": "not found"}, 404)
        elif path == "/api/banks":
            self._body(json.dumps(bankman.list_banks(), ensure_ascii=False).encode(), "application/json")
        elif path == "/api/iq-results":
            runs = []
            if os.path.isdir(RESULTS):
                for fn in sorted(os.listdir(RESULTS)):
                    if not (fn.startswith("iq_") and fn.endswith(".json")):
                        continue
                    try:
                        with open(os.path.join(RESULTS, fn), encoding="utf-8") as f:
                            runs.append(json.load(f))
                    except Exception:
                        pass
            runs.sort(key=lambda r: r.get("started_utc", ""), reverse=True)
            self._body(json.dumps(runs, ensure_ascii=False).encode(), "application/json")
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._json({"ok": False, "error": "bad json"}, 400)
        if not isinstance(body, dict):
            return self._json({"ok": False, "error": "bad json"}, 400)

        path = urllib.parse.urlsplit(self.path).path
        if path == "/api/probe":
            return self.api_probe(body)
        if path == "/api/start":
            return self.api_start(body)
        if path == "/api/bank-update":
            return self.api_bank_update(body)
        if path == "/api/iq-start":
            return self.api_iq_start(body)
        if path == "/api/gen-start":
            return self.api_gen_start(body)
        if path == "/api/gen-rate":
            return self.api_gen_rate(body)
        self._json({"ok": False, "error": "not found"}, 404)

    def api_probe(self, body):
        """探测端点: /v1/models 拉取模型清单 + 延迟。"""
        base = bench.normalize_base(body.get("base", ""))
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

    def api_start(self, body):
        base = bench.normalize_base(body.get("base", ""))
        url = base + "/v1/chat/completions"
        model = (body.get("model") or "").strip()
        suite = body.get("suite", "standard")
        if not base or not model:
            return self._json({"ok": False, "error": "缺少 base/model"}, 400)
        ladder = None
        raw_ladder = (body.get("conc_ladder") or "").strip().strip(",")
        if raw_ladder:
            try:
                ladder = sorted({int(x) for x in raw_ladder.split(",") if x.strip()})
                if not (1 <= min(ladder) and max(ladder) <= 128):
                    raise ValueError("range")
            except (ValueError, TypeError):
                return self._json({"ok": False, "error": "并发阶梯格式错误：应为 1-128 的逗号分隔整数，如 1,2,4,8"}, 400)
        matrix_conc = None
        raw_mc = str(body.get("matrix_conc") or "").strip()
        if raw_mc:
            try:
                matrix_conc = int(raw_mc)
                if not (1 <= matrix_conc <= 32):
                    raise ValueError("range")
            except ValueError:
                return self._json({"ok": False, "error": "阶梯×并发路数应为 1-32 的整数"}, 400)
        lens = None
        raw_lens = (body.get("lens") or "").strip().strip(",")
        if raw_lens:
            try:
                lens = sorted({int(x) for x in raw_lens.split(",") if x.strip()})
                if not (1 <= min(lens) and max(lens) <= 256):
                    raise ValueError("range")
            except (ValueError, TypeError):
                return self._json({"ok": False, "error": "长度阶梯格式错误：应为 1-256 的逗号分隔整数（K 单位），如 1,2,4,8,16"}, 400)
        framework = (body.get("framework") or "").strip()[:60]
        fw_version = (body.get("fw_version") or "").strip()[:60]
        with _state_lock:
            if _state["running"]:
                return self._json({"ok": False, "error": "已有测试在运行"}, 409)
            _state.update({"running": True, "log": [], "error": None, "run_id": None,
                           "started_at": time.strftime("%Y-%m-%d %H:%M:%S")})
        metrics_url = base + "/metrics" if body.get("metrics", True) else None
        tag = (body.get("tag") or "").strip()
        th = threading.Thread(target=run_benchmark,
                              args=(url, model, body.get("api_key", ""), suite, tag, metrics_url, ladder, matrix_conc, lens,
                                    framework, fw_version),
                              daemon=True)
        th.start()
        return self._json({"ok": True, "url": url, "metrics_url": metrics_url, "conc_ladder": ladder,
                           "matrix_conc": matrix_conc, "lens": lens})

    def api_bank_update(self, body):
        with _iq_lock:
            if _iq_state["bank_building"]:
                return self._json({"ok": False, "error": "题库正在更新中"}, 409)
            _iq_state["bank_building"] = True
        proxy = (body.get("proxy") or "").strip() or None
        try:
            bank, path = bankman.build(proxy=proxy)
            return self._json({"ok": True, "bank_id": bank["bank_id"], "total": bank["total"],
                               "subjects": [{"id": s["id"], "name": s["name"], "n": len(s["items"])} for s in bank["subjects"]]})
        except Exception as e:
            return self._json({"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:200]),
                               "hint": "官方题源需可达 datasets-server.huggingface.co 与 raw.githubusercontent.com（GSM8K 已自动走国内镜像）；网络不通时在下方『代理』填 http://127.0.0.1:端口 后重试"})
        finally:
            with _iq_lock:
                _iq_state["bank_building"] = False

    def api_iq_start(self, body):
        base = bench.normalize_base(body.get("base", ""))
        url = base + "/v1/chat/completions"
        model = (body.get("model") or "").strip()
        bank_id = (body.get("bank_id") or "").strip()
        if not base or not model or not bank_id:
            return self._json({"ok": False, "error": "缺少 base/model/bank_id"}, 400)
        try:
            conc = max(1, min(32, int(body.get("conc") or 8)))
        except (TypeError, ValueError):
            return self._json({"ok": False, "error": "并发应为整数"}, 400)
        subject_ids = body.get("subjects") or None
        limit = body.get("limit") or None
        if limit:
            try:
                limit = max(1, min(200, int(limit)))
            except (TypeError, ValueError):
                return self._json({"ok": False, "error": "limit 应为整数"}, 400)
        try:
            bankman.load_bank(bank_id)
        except FileNotFoundError as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        with _iq_lock:
            if _iq_state["running"]:
                return self._json({"ok": False, "error": "已有智力测试在运行"}, 409)
            _iq_state.update({"running": True, "log": [], "error": None, "run_id": None,
                              "started_at": time.strftime("%Y-%m-%d %H:%M:%S")})
        th = threading.Thread(target=run_iq_benchmark,
                              args=(url, model, body.get("api_key", ""), bank_id, conc,
                                    (body.get("tag") or "").strip(),
                                    (body.get("framework") or "").strip() or None,
                                    (body.get("fw_version") or "").strip() or None,
                                    subject_ids, limit, bool(body.get("thinking"))),
                              daemon=True)
        th.start()
        return self._json({"ok": True, "url": url, "bank_id": bank_id, "conc": conc})

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
        task_ids = body.get("tasks") or None
        with _gen_lock:
            if _gen_state["running"]:
                return self._json({"ok": False, "error": "已有生成测试在运行"}, 409)
            _gen_state.update({"running": True, "log": [], "error": None, "run_id": None,
                               "started_at": time.strftime("%Y-%m-%d %H:%M:%S")})
        th = threading.Thread(target=run_gen_benchmark,
                              args=(url, model, body.get("api_key", ""), task_ids, conc,
                                    (body.get("tag") or "").strip(),
                                    (body.get("framework") or "").strip() or None,
                                    (body.get("fw_version") or "").strip() or None,
                                    bool(body.get("thinking"))),
                              daemon=True)
        th.start()
        return self._json({"ok": True, "url": url, "tasks": len(task_ids) if task_ids else len(gen.GEN_TASKS),
                           "thinking": bool(body.get("thinking"))})

    def api_gen_rate(self, body):
        run_id, item_id = body.get("run_id") or "", body.get("item_id")
        stars = body.get("stars")
        if not isinstance(run_id, str) or not _RUN_ID_RE.match(run_id) or ".." in run_id:
            return self._json({"ok": False, "error": "非法 run_id"}, 400)
        if stars is not None and not (isinstance(stars, int) and 0 <= stars <= 5):
            return self._json({"ok": False, "error": "stars 应为 0-5 整数或 null"}, 400)
        path = os.path.join(RESULTS, run_id + ".json")
        if not os.path.isfile(path):
            return self._json({"ok": False, "error": "run 不存在"}, 404)
        try:
            with _rate_lock:  # 连续打星的并发读改写互斥; 运行中的 run 会被 gen 增量保存覆盖, 故拒绝
                with open(path, encoding="utf-8") as f:
                    r = json.load(f)
                if "finished_utc" not in r and _gen_state["running"]:
                    return self._json({"ok": False, "error": "该生成测试仍在运行，完成后再打星"}, 409)
                for it in r.get("items", []):
                    if it.get("id") == item_id:
                        it["stars"] = stars
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(r, f, ensure_ascii=False, indent=1)
            return self._json({"ok": True})
        except Exception as e:
            return self._json({"ok": False, "error": str(e)[:200]}, 500)

    def _json(self, obj, code=200):
        self._body(json.dumps(obj, ensure_ascii=False).encode(), "application/json", code)

    def _serve_file(self, path, ctype):
        with open(path, "rb") as f:
            self._body(f.read(), ctype)

    def _body(self, data, ctype, code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass




def main():
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18080
    os.makedirs(RESULTS, exist_ok=True)
    print("llm-bench-pro UI => http://127.0.0.1:%d  (results: %s)" % (port, RESULTS))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
