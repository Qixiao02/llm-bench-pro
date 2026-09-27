#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llm-bench-pro 服务: UI 页面 + 模型探测 + 在线起测 + 结果接口 (纯标准库)。
启动: python run.py [端口] [--host 127.0.0.1] [--token 访问令牌]
"""
import argparse
import base64
import glob
import hashlib
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
import export_html  # noqa: E402
import gen  # noqa: E402
import geneval  # noqa: E402
import iq  # noqa: E402
import report  # noqa: E402
import sinks  # noqa: E402
import store  # noqa: E402
from version import APP_VERSION  # noqa: E402

DATA = os.path.join(ROOT, "data")        # 运行数据(不入库): 数据库 / 结果 JSON / 生成作品 / 回放与场景文件
RESULTS = os.path.join(DATA, "results")  # 命令行跑出的或从别的机器拷回的 JSON 结果: 启动时自动导入库(仅新增)
WORKS = os.path.join(DATA, "works")      # 生成作品, 页面地址 /works/…

# 预览与评测共用 geneval.STORAGE_SHIM_JS。垫片必须出现在作品自己的第一个 <script> 之前,
# 否则脚本在垫片安装前读 localStorage, 沙箱里会直接抛 SecurityError。
_WORKS_SHIM = ("<script>/*llm-bench-pro storage shim*/" + geneval.STORAGE_SHIM_JS + "</script>").encode("utf-8")


def _inject_works_shim(data):
    """doctype 保持在首行。垫片插到其后、第一个 script 之前; 没有 script 时放在 head/html 开标签后。"""
    doctype = re.search(br"<\!doctype[^>]*>", data, re.IGNORECASE)
    start = doctype.end() if doctype else 0
    script = re.search(br"<script\b", data[start:], re.IGNORECASE)
    if script:
        pos = start + script.start()
    else:
        m = re.search(br"<head(?:\s[^>]*)?>", data[start:], re.IGNORECASE) or re.search(
            br"<html(?:\s[^>]*)?>", data[start:], re.IGNORECASE)
        pos = start + m.end() if m else start
    return data[:pos] + _WORKS_SHIM + data[pos:]

# 与评测时 Network.setBlockedURLs 对齐: 不给远程脚本/接口/图片, 仍允许内联脚本、eval、data/blob。
# sandbox 让新标签打开也是不透明源, 读不到 /api/endpoints。
_WORKS_CSP = (
    "sandbox allow-scripts allow-pointer-lock allow-forms allow-modals; "
    "base-uri 'none'; object-src 'none'; "
    "script-src 'unsafe-inline' 'unsafe-eval' blob: data:; script-src-attr 'unsafe-inline'; "
    "style-src 'unsafe-inline' blob: data:; "
    "img-src data: blob:; font-src data: blob:; media-src data: blob: mediastream:; "
    "connect-src data: blob:; worker-src blob:; child-src blob: data:"
)
_WORKS_CSP_OPEN = "sandbox allow-scripts allow-pointer-lock allow-forms allow-modals"
# 离线报告里的预览没有响应头: 用 <meta> 声明同样的资源限制(meta 不支持 sandbox, 由 iframe 的 sandbox 属性负责)
WORKS_CSP_META = "; ".join(x for x in _WORKS_CSP.split("; ") if not x.startswith("sandbox"))
WEB = os.path.join(ROOT, "web")
UI = os.path.join(WEB, "index.html")
REPLAY_DIR = os.path.join(DATA, "replay")      # 真实请求回放池(内容寻址 replay-<sha12>.jsonl)
SCN_TASKS_DIR = os.path.join(DATA, "scenario", "tasks")    # 自定义任务集(内容寻址 scn-<sha12>.jsonl)
SCN_IMAGES_DIR = os.path.join(DATA, "scenario", "images")  # 图片理解场景的图片包(img-<sha12>/<n>.<ext>)
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
                     "out": it.get("out"), "tail": it.get("tail") or (it.get("resp") or "")[-240:], "sub": q.get("sub")})
    return {"ok": True, "run_id": run_id, "sid": sid, "iq_version": doc.get("iq_version"),
            "bank_found": bool(sub_items), "rows": rows}


def _valid_iq_id(x):
    return isinstance(x, str) and x.startswith("iq_") and bool(_RUN_ID_RE.match(x))


def _bank_subjects(bank_id):
    """题集各科目 {sid: subject}; 题集文件缺失或损坏时为空。"""
    if not re.match(r"^[A-Za-z0-9._-]+$", bank_id or ""):
        return {}
    try:
        return {s["id"]: s for s in bankman.load_bank(bank_id)["subjects"]}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def _rec_summary(it):
    """逐题列表里的作答摘要; 回答原文不在列表里, 由 /api/iq-answer 按需加载。"""
    r = {"ok": bool(it.get("ok"))}
    for k in ("pred", "trunc", "err", "finish", "out", "rc", "mt"):
        if it.get(k) not in (None, "", False):
            r[k] = it[k]
    if "err" in r:
        r["err"] = str(r["err"])[:200]
    tail = str(it.get("tail") or "")
    if it.get("resp"):
        r["has"] = "resp"
    elif "resp" in it or tail.startswith("（无正文"):
        r["has"] = "empty"  # 模型没有给出正式回答(只有思考或空内容)
    elif tail:
        r["has"] = "tail"  # 旧版: 只有答错的题存了回答最后 240 字
    return r


def iq_items(run_id, cmp_ids=""):
    """逐题查看: 主运行答过的每道题(题干/选项/标准答案/检查规则) + 主运行与对比运行每题的作答摘要。
    对比运行的题集不同时不逐题对照(same_bank=False, 不返回记录)。"""
    if not _valid_iq_id(run_id):
        return {"ok": False, "error": "非法 run_id"}
    ids = list(dict.fromkeys(x for x in (cmp_ids or "").split(",") if x and x != run_id))[:5]
    if not all(_valid_iq_id(x) for x in ids):
        return {"ok": False, "error": "非法对比 run_id"}
    doc = store.get_run(run_id)
    if not doc:
        return {"ok": False, "error": "run 不存在"}
    bank_id = doc.get("bank_id") or ""
    subs = _bank_subjects(bank_id)
    order = {sid: i for i, sid in enumerate(subs)}
    mine = [it for it in doc.get("items", []) if isinstance(it.get("idx"), int)]
    keys = sorted({(it.get("sid"), it["idx"]) for it in mine}, key=lambda k: (order.get(k[0], len(order)), str(k[0]), k[1]))
    questions = []
    for sid, idx in keys:
        sub = subs.get(sid) or {}
        items = sub.get("items") or []
        q = items[idx] if 0 <= idx < len(items) else None
        row = {"sid": sid, "idx": idx}
        if q:
            row["q"] = q.get("q") or ""
            for k in ("choices", "answer", "sub"):
                if q.get(k) is not None:
                    row[k] = q[k]
            if sub.get("type") == "instruct":
                row["rules"] = [iq.rule_info(ck) for ck in iq.instruct_rules(q)]
        questions.append(row)
    summ = {s.get("id"): s for s in doc.get("subjects") or []}
    subjects = []
    for sid in dict.fromkeys(k[0] for k in keys):
        b, s = subs.get(sid) or {}, summ.get(sid) or {}
        subjects.append({"id": sid, "name": b.get("name") or s.get("name") or sid, "type": b.get("type") or s.get("type")})

    def recs(d):
        return {"%s|%s" % (it.get("sid"), it["idx"]): _rec_summary(it) for it in d.get("items", []) if isinstance(it.get("idx"), int)}
    runs = {run_id: {"same_bank": True, "recs": recs({"items": mine})}}
    for rid in ids:
        d = store.get_run(rid)
        if not d:
            runs[rid] = {"missing": True, "same_bank": False, "recs": {}}
            continue
        same = d.get("bank_id") == bank_id
        runs[rid] = {"same_bank": same, "recs": recs(d) if same else {}}
    return {"ok": True, "run_id": run_id, "bank_id": bank_id, "bank_found": bool(subs), "iq_version": doc.get("iq_version"),
            "subjects": subjects, "questions": questions, "runs": runs}


def iq_answer(ids, sid, idx):
    """某道题在各次运行里的回答原文(按需加载) + 发给模型的原文(仅当前评测版本) + 按要求作答题的逐条检查结果。"""
    ids = list(dict.fromkeys(x for x in (ids or "").split(",") if x))[:6]
    if not ids or not all(_valid_iq_id(x) for x in ids):
        return {"ok": False, "error": "非法 run_id"}
    try:
        idx = int(idx)
    except (TypeError, ValueError):
        return {"ok": False, "error": "非法题号"}
    head = store.get_run(ids[0], items=False)
    if not head:
        return {"ok": False, "error": "run 不存在"}
    sub = _bank_subjects(head.get("bank_id")).get(sid) or {}
    items = sub.get("items") or []
    q = items[idx] if 0 <= idx < len(items) else None
    stype = sub.get("type")
    prompt = iq.PROMPTS[stype](q)[0] if q and stype in iq.PROMPTS and head.get("iq_version") == iq.IQ_VERSION else None
    answers = {}
    for rid in ids:
        recs = store.get_iq_records(rid, sid, idx)
        if recs:
            answers[rid] = _answer_of(recs[-1], q, stype)
    return {"ok": True, "sid": sid, "idx": idx, "type": stype, "prompt": prompt, "answers": answers}


def _answer_of(it, q, stype):
    """一条作答记录 → 「看回答」要用的字段(同一题有多条记录时传最后一条)。"""
    a = {"ok": bool(it.get("ok")), "rc": it.get("rc") or 0}
    for k in ("finish", "out", "err", "pred", "trunc", "rtail"):
        if it.get(k) not in (None, "", False):
            a[k] = it[k]
    tail = str(it.get("tail") or "")
    if "resp" in it:
        a["text"], a["full"] = it["resp"] or "", True  # 新版每题留档; 空串 = 没有正式回答
    elif tail.startswith("（无正文"):
        a["text"], a["full"] = "", True
    elif tail:
        a["text"], a["full"] = tail, len(tail) < 240  # 旧版只存结尾 240 字, 不足 240 字即为全文
    elif not it.get("err"):
        a["kept"] = False  # 旧版没有保存这题的回答
    if q and stype == "instruct" and a.get("full") and a.get("text"):
        a["rules"] = iq.instruct_detail(a["text"], q)
    return a


def iq_answers_all(ids):
    """离线报告用: 一次取出这些运行(与第一个同题集)每道题的回答和发给模型的原文, 键为 "sid|idx";
    每项与 iq_answer 返回的 type / prompt / answers 一致。"""
    ids = [x for x in dict.fromkeys(ids or []) if _valid_iq_id(x)]
    head = store.get_run(ids[0], items=False) if ids else None
    if not head:
        return {}
    subjects = _bank_subjects(head.get("bank_id"))
    cur = head.get("iq_version") == iq.IQ_VERSION
    out, qs = {}, {}
    for rid in ids:
        doc = store.get_run(rid)
        if not doc or doc.get("bank_id") != head.get("bank_id"):
            continue
        last = {}
        for it in doc.get("items") or []:
            last[(it.get("sid"), it.get("idx"))] = it  # 按写入顺序, 同一题以最后一条为准(与 iq_answer 相同)
        for (sid, idx), it in last.items():
            key = "%s|%s" % (sid, idx)
            if key not in out:
                sub = subjects.get(sid) or {}
                items = sub.get("items") or []
                q = items[idx] if isinstance(idx, int) and 0 <= idx < len(items) else None
                stype = sub.get("type")
                prompt = iq.PROMPTS[stype](q)[0] if q and cur and stype in iq.PROMPTS else None
                out[key], qs[key] = {"type": stype, "prompt": prompt, "answers": {}}, q
            out[key]["answers"][rid] = _answer_of(it, qs[key], out[key]["type"])
    return out


def iq_compare(a_id, b_id):
    if not (a_id.startswith("iq_") and b_id.startswith("iq_") and _RUN_ID_RE.match(a_id) and _RUN_ID_RE.match(b_id)):
        return {"ok": False, "error": "非法 run_id"}
    a, b = store.get_run(a_id), store.get_run(b_id)
    if not a or not b:
        return {"ok": False, "error": "run 不存在"}
    return dict(iq.compare_runs(a, b), ok=True, a=a_id, b=b_id)


EXPORT_PAGES = {"dash": "perf", "cmp": "perf", "iq": "iq", "gen": "gen"}
_KIND_PREFIX = {"perf": "run_", "iq": "iq_", "gen": "gen_"}


def _work_file(rel):
    """作品相关文件的逻辑路径(works/…) → 磁盘路径; 越界或不存在返回 None。"""
    rel = str(rel or "")
    if not rel.startswith("works/"):
        return None
    full = safe_join(WORKS, rel[len("works/"):])
    return full if full and os.path.isfile(full) else None


def _pack_work(it, files):
    """一件作品要带进离线报告的文件: 网页(带存储垫片)、检查截图(data: 地址)、生成过程记录(JSON)。"""
    rel = it.get("file")
    full = _work_file(rel)
    if full:
        with open(full, "rb") as f:
            files[rel] = _inject_works_shim(f.read()).decode("utf-8", "replace")
    e = it.get("eval") or {}
    if rel and e.get("shots_dir"):
        base = rel.rsplit("/", 1)[0] + "/" + e["shots_dir"] + "/"
        for sh in e.get("shots") or []:
            p = base + str(sh.get("file") or "")
            full = _work_file(p)
            if full and p.lower().endswith((".jpg", ".jpeg")):
                with open(full, "rb") as f:
                    files[p] = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode("ascii")
    tr = it.get("trace")
    full = _work_file(tr)
    if full and tr.endswith(".gen.json"):
        try:
            with open(full, encoding="utf-8") as f:
                files[tr] = json.load(f)
        except (OSError, ValueError):
            pass


def offline_bundle(page, a_id, cmp_ids):
    """离线报告要带的数据, 与页面请求的接口同形(前端 offlineApi 按接口路径取用)。
    返回 {"api": ..., "files": ..., "sel": ...}; 参数不对或测试不存在抛 ValueError。"""
    kind = EXPORT_PAGES.get(page)
    if not kind:
        raise ValueError("不支持导出这个页面")
    ids = list(dict.fromkeys([a_id] + [x for x in cmp_ids if x]))
    if len(ids) > 7:
        raise ValueError("一次最多导出 7 次测试")
    for x in ids:
        if not (_RUN_ID_RE.match(x or "") and x.startswith(_KIND_PREFIX[kind])):
            raise ValueError("非法 run_id: %s" % x)
    api, files = {}, {}
    if kind == "perf":
        runs = {x: store.get_run(x) for x in ids}
        miss = [x for x, d in runs.items() if d is None]
        if miss:
            raise ValueError("测试不存在: %s" % ", ".join(miss))
        summary = {r["run_id"]: r for r in store.list_runs("perf", summary=True)}
        api["perfList"] = [summary[x] for x in ids if x in summary]
        api["perfRuns"] = runs
    elif kind == "iq":
        lst = {r["run_id"]: r for r in store.list_runs("iq", items=False)}
        miss = [x for x in ids if x not in lst]
        if miss:
            raise ValueError("测试不存在: %s" % ", ".join(miss))
        api["iqList"] = [lst[x] for x in ids]
        api["iqItems"] = iq_items(a_id, ",".join(ids[1:]))
        # 各次测试两两之间的「差异是否可信」: 在报告里换主测试也能看
        api["iqCompare"] = {"%s|%s" % (x, y): iq_compare(x, y) for x in ids for y in ids if x != y}
        same = [x for x in ids if ((api["iqItems"].get("runs") or {}).get(x) or {}).get("same_bank")] or [a_id]
        api["iqAnswers"] = iq_answers_all([a_id] + [x for x in same if x != a_id])
    else:
        lst = {r["run_id"]: r for r in store.list_runs("gen")}
        miss = [x for x in ids if x not in lst]
        if miss:
            raise ValueError("测试不存在: %s" % ", ".join(miss))
        api["genList"] = [lst[x] for x in ids]
        for r in api["genList"]:
            for it in r.get("items") or []:
                _pack_work(it, files)
    return {"api": api, "files": files, "sel": {"a": a_id, "cmp": ids[1:]}, "worksCsp": WORKS_CSP_META}


# 离线报告只带显示偏好(主题、视图、表格排序与列、标签页、每页条数、密度、侧栏), 不带表单里填过的地址和 Key
EXPORT_LS_KEYS = ("llm-bench-pro-theme", "llm-bench-pro-viewmode", "llm-bench-pro-dt", "llm-bench-pro-ctab",
                  "llm-bench-pro-qb", "llm-bench-pro-density", "llm-bench-pro-rail")


def _export_state(raw):
    raw = raw if isinstance(raw, dict) else {}
    theme = raw.get("theme") if raw.get("theme") in ("light", "dark") else "dark"
    ls = raw.get("ls") if isinstance(raw.get("ls"), dict) else {}
    ls = {k: v for k, v in ls.items() if k in EXPORT_LS_KEYS and isinstance(v, str) and len(v) <= 65536}
    ls["llm-bench-pro-theme"] = theme
    return {"theme": theme, "ls": ls}


def _export_ui(raw):
    """导出那一刻的界面状态(单独切换过的面板、逐题筛选、作品筛选与排序), 只收认识的字段。"""
    raw = raw if isinstance(raw, dict) else {}
    ui = {}
    panels = raw.get("panels")
    if isinstance(panels, list):
        ui["panels"] = [[str(k)[:80], v] for k, v in (p for p in panels[:200] if isinstance(p, list) and len(p) == 2)
                        if v in ("chart", "table")]
    qb = raw.get("qb")
    if isinstance(qb, dict):
        ui["qb"] = {k: str(qb.get(k) or "")[:200] for k in ("subj", "filter", "q", "vs")}
    for k in ("genFilter", "genSort"):
        if isinstance(raw.get(k), str):
            ui[k] = raw[k][:40]
    return ui


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


def _ints(raw, name, lo, hi):
    """整数列表: 接受 [1,2] 或 "1,2"; 越界/非法抛 ValueError。"""
    if isinstance(raw, str):
        raw = [x for x in raw.split(",") if x.strip()]
    if not isinstance(raw, list) or not raw:
        raise ValueError("%s 应为逗号分隔整数列表" % name)
    try:
        out = sorted({int(x) for x in raw})
    except (TypeError, ValueError):
        raise ValueError("%s 应为整数列表" % name)
    if not (lo <= min(out) and max(out) <= hi):
        raise ValueError("%s 超出范围 %d-%d" % (name, lo, hi))
    return out


def _parse_scenarios(body):
    """任务场景配置: scenarios.tasks(模板多选) + 共用参数 + 各模板专属参数。
    返回可直接传给 bench.run_suite 的 dict(无任务时返回 None); 非法抛 ValueError。"""
    scen = body.get("scenarios")
    if scen is None:
        return None
    if not isinstance(scen, dict):
        raise ValueError("scenarios 应为对象")
    tasks = scen.get("tasks") or []
    if isinstance(tasks, str):
        tasks = [t.strip() for t in tasks.split(",") if t.strip()]
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("tasks 应为任务类型列表")
    for t in tasks:
        if t not in bench.SCN_TEMPLATES:
            raise ValueError("未知任务类型 %s (可选: %s)" % (t, "/".join(bench.SCN_TEMPLATES)))
    out = {"tasks": tasks}
    if len(set(tasks)) != len(tasks):
        raise ValueError("tasks 里有重复的任务类型")
    try:
        out["conc"] = _ints(scen.get("conc") or [4, 8], "scenarios.conc", 1, 128)
        out["requests_per_worker"] = max(1, min(50, int(scen.get("requests_per_worker") or 3)))
        out["max_tokens"] = max(64, min(8192, int(scen.get("max_tokens") or 512)))
    except (TypeError, ValueError):
        raise ValueError("requests_per_worker / max_tokens 应为整数")
    if "rag" in tasks:
        out["rag_ctx"] = _ints(scen.get("rag_ctx") or [4000], "scenarios.rag_ctx", 512, 65536)
    if "vision" in tasks:
        src = scen.get("vision_src") or {}
        if not isinstance(src, dict):
            raise ValueError("vision_src 应为对象")
        img_dir = ""
        if src.get("image_id"):
            iid = str(src["image_id"]).strip()
            if not re.match(r"^img-[0-9a-f]{12}$", iid):
                raise ValueError("非法 image_id")
            img_dir = os.path.join(SCN_IMAGES_DIR, iid)
        elif (src.get("dir") or "").strip():
            img_dir = (src["dir"] or "").strip()
        if not img_dir or not os.path.isdir(img_dir):
            raise ValueError("图片理解场景需要已上传的图片包或存在的服务器图片目录")
        if not any(os.path.splitext(n)[1].lower() in (".jpg", ".jpeg", ".png", ".webp")
                   for n in os.listdir(img_dir)):
            raise ValueError("图片目录中没有可用图片(jpg/png/webp): %s" % img_dir)
        out["vision_dir"] = img_dir
        try:
            out["vision_images"] = max(1, min(4, int(src.get("images") or 1)))
        except (TypeError, ValueError):
            raise ValueError("vision_src.images 应为 1-4 的整数")
    if "custom" in tasks:
        fid = (scen.get("custom_file_id") or "").strip()
        if fid:
            if not re.match(r"^scn-[0-9a-f]{12}$", fid):
                raise ValueError("非法 custom_file_id")
            full = os.path.join(SCN_TASKS_DIR, fid + ".jsonl")
            if not os.path.isfile(full):
                raise ValueError("任务集不存在: %s (可能已被删除, 请重新上传)" % fid)
            out["custom_file"] = full
        elif (scen.get("custom_file") or "").strip():
            out["custom_file"] = scen["custom_file"].strip()
            if not os.path.isfile(out["custom_file"]):
                raise ValueError("任务集文件不存在: %s" % out["custom_file"])
        else:
            raise ValueError("自定义任务集需要选择已上传的任务集或填写服务器文件路径")
    return out


def _parse_replay(body):
    """真实请求回放配置: file/file_id + closed/open; 返回传给 run_suite 的 dict 或 None。"""
    rp = body.get("scenarios", {}).get("replay") if isinstance(body.get("scenarios"), dict) else None
    if body.get("replay"):
        rp = body["replay"]
    if not rp:
        return None
    if not isinstance(rp, dict):
        raise ValueError("replay 应为对象")
    fid = (rp.get("file_id") or "").strip()
    if fid:
        if not re.match(r"^replay-[0-9a-f]{12}$", fid):
            raise ValueError("非法 file_id")
        full = os.path.join(REPLAY_DIR, fid + ".jsonl")
        if not os.path.isfile(full):
            raise ValueError("回放文件不存在: %s (可能已被删除, 请重新上传)" % fid)
        rp = dict(rp, file=full)
    elif not (rp.get("file") or "").strip():
        raise ValueError("replay 需要 file_id(上传的文件)或 file(服务器路径)")
    replay = dict(rp)
    closed = replay.get("closed")
    if closed:
        if not isinstance(closed, dict):
            raise ValueError("replay.closed 应为对象")
        try:
            rpw = max(1, min(100, int(closed.get("requests_per_worker") or 4)))
        except (TypeError, ValueError):
            raise ValueError("replay.closed.requests_per_worker 应为整数")
        replay["closed"] = {"conc": _ints(closed.get("conc") or [8], "replay.closed.conc", 1, 128),
                            "requests_per_worker": rpw}
    o = replay.get("open")
    if o:
        if not isinstance(o, dict):
            raise ValueError("replay.open 应为对象")
        try:
            rates = [float(x) for x in (o.get("rates") if isinstance(o.get("rates"), list) else
                                        str(o.get("rates") or "").split(",")) if str(x).strip()]
        except (TypeError, ValueError):
            raise ValueError("replay.open.rates 应为数字列表")
        rates = sorted({round(r, 3) for r in rates if 0.05 <= r <= 1000})
        if not rates:
            raise ValueError("replay.open.rates 需要至少一个 0.05-1000 的速率")
        replay["open"] = {"rates": rates,
                          "duration_s": max(5, min(3600, int(o.get("duration_s") or 60)))}
    return replay


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
            ext = os.path.splitext(full or "")[1].lower()
            ctype = {".html": "text/html; charset=utf-8", ".jpg": "image/jpeg"}.get(ext)
            if full and full.endswith(".gen.json"):  # 模型原始输出留档(纯数据, 不执行)
                ctype = "application/json; charset=utf-8"
            if full and ctype and os.path.isfile(full):
                if ext == ".html":
                    with open(full, "rb") as f:
                        csp = _WORKS_CSP_OPEN if q("open") == "1" else _WORKS_CSP
                        return self._body(_inject_works_shim(f.read()), ctype, headers={"Content-Security-Policy": csp})
                return self._serve_file(full, ctype)
            return self._json({"error": "not found"}, 404)

        routes = {
            "/api/version": lambda: self._json(self.version_info()),
            "/api/results": lambda: self._json(store.list_runs("perf", summary=q("summary") == "1")),
            # 逐题 items 前端列表不读, 默认省略; ?full=1 返回完整文档
            "/api/iq-results": lambda: self._json(store.list_runs("iq", items=q("full") == "1")),
            "/api/gen-results": lambda: self._json(store.list_runs("gen")),
            "/api/iq-wrong": lambda: self._json(iq_wrong(q("id"), q("sid"))),
            "/api/iq-items": lambda: self._json(iq_items(q("id"), q("cmp"))),
            "/api/iq-answer": lambda: self._json(iq_answer(q("ids"), q("sid"), q("idx"))),
            "/api/iq-compare": lambda: self._json(iq_compare(q("a"), q("b"))),
            "/api/banks": lambda: self._json(bankman.list_banks()),
            "/api/status": lambda: self._json(JOBS["perf"].snapshot()),
            "/api/iq-status": lambda: self._json(JOBS["iq"].snapshot()),
            "/api/gen-status": lambda: self._json(JOBS["gen"].snapshot()),
            "/api/replay-list": lambda: self._json(self.replay_list()),
            "/api/scenario-list": lambda: self._json(self.scenario_list()),
            "/api/endpoints": lambda: self._json(store.list_endpoints()),
        }
        if path in routes:
            return routes[path]()
        if path == "/api/report":
            return self.report_html(q("id"), q("cmp"))
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
            "/api/endpoints": self.api_endpoint_save, "/api/endpoint-use": self.api_endpoint_use,
            "/api/endpoint-delete": self.api_endpoint_delete,
            "/api/replay-upload": self.api_replay_upload,
            "/api/export-html": self.api_export_html,
            "/api/scenario-upload": self.api_scenario_upload,
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

    def api_endpoint_save(self, body):
        """模型端点配置: 命名保存 地址/Key/模型, 三页启动器一键填入, 免去复制粘贴。"""
        try:
            ep = store.save_endpoint({"id": body.get("id"), "name": body.get("name"),
                                      "url": body.get("url"), "api_key": body.get("api_key"),
                                      "model": body.get("model")})
        except ValueError as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        return self._json({"ok": True, "endpoint": ep, "endpoints": store.list_endpoints()})

    def api_endpoint_use(self, body):
        return self._json({"ok": bool(store.touch_endpoint(body.get("id") or ""))})

    def api_endpoint_delete(self, body):
        ok = store.delete_endpoint(body.get("id") or "")
        return self._json({"ok": True} if ok else {"ok": False, "error": "配置不存在"}, 200 if ok else 404)

    # ---- 任务场景: 自定义任务集 / 图片包
    _IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

    def scenario_list(self):
        tasks = []
        if os.path.isdir(SCN_TASKS_DIR):
            for fn in sorted(os.listdir(SCN_TASKS_DIR)):
                if re.match(r"^scn-[0-9a-f]{12}\.jsonl$", fn):
                    p = os.path.join(SCN_TASKS_DIR, fn)
                    tasks.append({"file_id": fn[:-6], "size": os.path.getsize(p),
                                  "mtime": datetime.fromtimestamp(os.path.getmtime(p), timezone.utc).isoformat()[:19]})
        images = []
        if os.path.isdir(SCN_IMAGES_DIR):
            for dn in sorted(os.listdir(SCN_IMAGES_DIR)):
                d = os.path.join(SCN_IMAGES_DIR, dn)
                if re.match(r"^img-[0-9a-f]{12}$", dn) and os.path.isdir(d):
                    files = [n for n in os.listdir(d) if os.path.splitext(n)[1].lower() in self._IMG_EXTS]
                    if files:
                        images.append({"image_id": dn, "count": len(files),
                                       "size": sum(os.path.getsize(os.path.join(d, n)) for n in files)})
        return {"ok": True, "tasks": tasks, "images": images}

    def api_scenario_upload(self, body):
        """上传任务场景资产: kind=tasks 任务集 JSONL {name, content}; kind=images 图片包 {files:[{name, data}]}。
        均内容寻址幂等; 总量受 16MB 请求体上限约束。"""
        kind = body.get("kind")
        if kind == "tasks":
            content = body.get("content")
            if not isinstance(content, str) or not content.strip():
                return self._json({"ok": False, "error": "缺少文件内容 (content 应为 JSONL 文本)"}, 400)
            lines, bad = 0, 0
            for ln in content.splitlines():
                if not ln.strip():
                    continue
                try:
                    r = json.loads(ln)
                    lines += 1 if isinstance(r.get("messages"), list) else 0
                    bad += 0 if isinstance(r.get("messages"), list) else 1
                except Exception:
                    bad += 1
            if not lines:
                return self._json({"ok": False, "error": "没有可用行: 每行应为 {\"messages\": [...], \"params\": {...}}"}, 400)
            data = content.encode("utf-8")
            fid = "scn-" + hashlib.sha256(data).hexdigest()[:12]
            os.makedirs(SCN_TASKS_DIR, exist_ok=True)
            path = os.path.join(SCN_TASKS_DIR, fid + ".jsonl")
            if not os.path.isfile(path):
                tmp = path + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, path)
            return self._json({"ok": True, "file_id": fid, "name": (body.get("name") or "")[:80],
                               "lines": lines, "bad_lines": bad})
        if kind == "images":
            files = body.get("files")
            if not isinstance(files, list) or not files:
                return self._json({"ok": False, "error": "缺少 files: [{name, data(base64)}]"}, 400)
            decoded = []
            total = 0
            for f in files[:64]:
                name = str((f or {}).get("name") or "")
                ext = os.path.splitext(name)[1].lower()
                if ext not in self._IMG_EXTS:
                    return self._json({"ok": False, "error": "不支持的图片类型 %r (仅 jpg/png/webp)" % name}, 400)
                try:
                    raw = base64.b64decode((f.get("data") or ""), validate=False)
                except Exception:
                    return self._json({"ok": False, "error": "%s 的 data 不是合法 base64" % name}, 400)
                if not raw.startswith((b"\xff\xd8", b"\x89PNG", b"RIFF")):  # jpg/png/webp 魔数
                    return self._json({"ok": False, "error": "%s 不是有效的图片文件" % name}, 400)
                decoded.append((ext, raw))
                total += len(raw)
            digest = hashlib.sha256()
            for _, raw in decoded:
                digest.update(raw)
            iid = "img-" + digest.hexdigest()[:12]
            d = os.path.join(SCN_IMAGES_DIR, iid)
            os.makedirs(d, exist_ok=True)
            if not os.listdir(d):  # 内容寻址幂等
                for i, (ext, raw) in enumerate(decoded):
                    with open(os.path.join(d, "%02d%s" % (i, ext)), "wb") as f:
                        f.write(raw)
            return self._json({"ok": True, "image_id": iid, "count": len(decoded), "size": total})
        return self._json({"ok": False, "error": "kind 应为 tasks 或 images"}, 400)

    # ---- 真实请求回放池
    def replay_list(self):
        files = []
        if os.path.isdir(REPLAY_DIR):
            for fn in sorted(os.listdir(REPLAY_DIR)):
                if re.match(r"^replay-[0-9a-f]{12}\.jsonl$", fn):
                    p = os.path.join(REPLAY_DIR, fn)
                    files.append({"file_id": fn[:-6], "size": os.path.getsize(p),
                                  "mtime": datetime.fromtimestamp(os.path.getmtime(p), timezone.utc).isoformat()[:19]})
        return {"ok": True, "files": files}

    def api_replay_upload(self, body):
        """上传回放文件: {name, content}; 内容寻址存 data/replay/replay-<sha12>.jsonl, 幂等。"""
        name = (body.get("name") or "").strip()
        content = body.get("content")
        if not isinstance(content, str) or not content.strip():
            return self._json({"ok": False, "error": "缺少文件内容 (content 应为 JSONL 文本)"}, 400)
        if len(content.encode("utf-8", "ignore")) > 15 * 1024 * 1024:
            return self._json({"ok": False, "error": "文件超过 15MB 上限; 大文件请放到服务器后用路径引用"}, 400)
        lines, bad = 0, 0
        for ln in content.splitlines():
            if not ln.strip():
                continue
            try:
                r = json.loads(ln)
                lines += 1 if isinstance(r.get("messages"), list) else 0
                bad += 0 if isinstance(r.get("messages"), list) else 1
            except Exception:
                bad += 1
        if not lines:
            return self._json({"ok": False, "error": "没有可用行: 每行应为 {\"messages\": [...], \"params\": {...}}"}, 400)
        data = content.encode("utf-8")
        fid = "replay-" + hashlib.sha256(data).hexdigest()[:12]
        os.makedirs(REPLAY_DIR, exist_ok=True)
        path = os.path.join(REPLAY_DIR, fid + ".jsonl")
        if not os.path.isfile(path):  # 内容寻址: 同内容幂等
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        return self._json({"ok": True, "file_id": fid, "name": name[:80], "lines": lines, "bad_lines": bad})

    def report_html(self, run_id, cmp_id=None):
        """离线自包含 HTML 报告 (?id=run_a&cmp=run_b 做 A/B); 浏览器直接打开, 无需服务。"""
        if not _RUN_ID_RE.match(run_id or ""):
            return self._json({"ok": False, "error": "非法 run_id"}, 400)
        a = store.get_run(run_id)
        if a is None:
            return self._json({"ok": False, "error": "run 不存在"}, 404)
        b = None
        if cmp_id:
            if not _RUN_ID_RE.match(cmp_id):
                return self._json({"ok": False, "error": "非法 cmp run_id"}, 400)
            b = store.get_run(cmp_id)
            if b is None:
                return self._json({"ok": False, "error": "cmp run 不存在"}, 404)
        try:
            html_text = report.render(a, b)
        except ValueError as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        fn = "%s_report%s.html" % (run_id, "_ab" if b else "")
        return self._body(html_text.encode("utf-8"), "text/html; charset=utf-8",
                          headers={"Content-Disposition": 'attachment; filename="%s"' % fn})

    def api_export_html(self, body):
        """离线报告: 当前页面(同一套界面) + 这几次测试的数据 → 一个 HTML 文件(浏览器直接打开, 不需要服务)。"""
        page = body.get("page")
        cmp = body.get("cmp") or []
        if isinstance(cmp, str):
            cmp = [x for x in cmp.split(",") if x]
        if not isinstance(cmp, list):
            return self._json({"ok": False, "error": "cmp 格式错误"}, 400)
        try:
            bundle = offline_bundle(page, str(body.get("id") or ""), [str(x) for x in cmp])
        except ValueError as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        info = self.version_info()
        bundle["api"]["version"] = {k: info[k] for k in ("version", "iq_version", "bench_version", "gen_version")}
        bundle["api"]["version"]["offline"] = True
        bundle["ui"] = _export_ui(body.get("ui"))
        bundle["exported_at"] = datetime.now(timezone.utc).isoformat()
        title = re.sub(r"[\x00-\x1f]", " ", str(body.get("title") or ""))[:160] or "LLM Bench Pro 离线报告"
        text = export_html.compose(page, bundle, _export_state(body.get("state")), title)
        return self._body(text.encode("utf-8"), "text/html; charset=utf-8")

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
        try:
            scen_cfg = _parse_scenarios(body)
            replay_cfg = _parse_replay(body)
        except ValueError as e:
            return self._json({"ok": False, "error": "场景配置错误：%s" % e}, 400)
        warmup_shapes = body.get("warmup_shapes", True) is not False
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
                            fixed_output=fixed_output, cancel=j.cancel, notes=notes,
                            scenarios=scen_cfg, replay=replay_cfg, warmup_shapes=warmup_shapes)
            j.set(run_id=sink.run_id)
        job.run(target, "_PROGRESS_CB", bench)
        return self._json({"ok": True, "url": url, "metrics_url": metrics_url, "conc_ladder": ladder,
                           "matrix_conc": matrix_conc, "lens": lens, "fixed_output": fixed_output,
                           "scenarios": (scen_cfg or {}).get("tasks") or [], "replay": bool(replay_cfg),
                           "warmup_shapes": warmup_shapes})

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
            buds = iq.normalize_budgets(body.get("budgets")) if isinstance(body.get("budgets"), dict) else None
            iq.run_iq(url, model, body.get("api_key", ""), bank, conc, RESULTS, (body.get("tag") or "").strip(),
                      (body.get("framework") or "").strip() or None, (body.get("fw_version") or "").strip() or None,
                      subject_ids, limit, thinking, sink=sink, sampling=sampling, budgets=buds, cancel=j.cancel)
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
        raw_tasks = body.get("tasks")
        sampling = body.get("sampling") or None
        try:
            task_ids = None if raw_tasks in (None, "") else gen.normalize_task_ids(raw_tasks)
            gen.sampling_record(sampling)
        except ValueError as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        if self._busy_or_conflict("gen", base, body):
            return
        job = JOBS["gen"]
        if not job.try_start(base, model):
            return self._json({"ok": False, "error": "已有代码生成任务或重新评测在运行"}, 409)
        judge = _judge_cfg(body)

        def target(j):
            sink = sinks.SqliteSink()
            gen.run_gen(url, model, body.get("api_key", ""), task_ids, conc, RESULTS, (body.get("tag") or "").strip(),
                        (body.get("framework") or "").strip() or None, (body.get("fw_version") or "").strip() or None,
                        _truthy(body.get("thinking")), sink=sink, judge=judge, cancel=j.cancel, sampling=sampling)
            j.set(run_id=sink.run_id)
        job.run(target, "_GEN_PROGRESS", gen)
        return self._json({"ok": True, "url": url, "tasks": len(task_ids) if task_ids is not None else len(gen.GEN_TASKS),
                           "thinking": bool(body.get("thinking")), "eval": geneval.Evaluator(judge).meta()})

    def api_gen_eval(self, body):
        """对已有生成运行重新评测 (运行检测 + 可选视觉评审)。与代码生成共用任务状态/日志。"""
        run_id = body.get("run_id") or ""
        if not isinstance(run_id, str) or not run_id.startswith("gen_") or not _RUN_ID_RE.match(run_id):
            return self._json({"ok": False, "error": "非法 run_id"}, 400)
        if store.get_run(run_id, items=False) is None:
            return self._json({"ok": False, "error": "run 不存在"}, 404)
        raw_tasks = body.get("tasks")
        try:
            only = None if not raw_tasks else set(gen.normalize_task_ids(raw_tasks))
        except ValueError as e:
            return self._json({"ok": False, "error": str(e)}, 400)
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
            if not store.rate_gen_item(run_id, item_id, stars):
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


def migrate_legacy_dirs(root=ROOT, data=DATA):
    """2.9 之前 results/、works/ 放在项目根, 现统一放 data/ 下。启动时搬过去: 目标不存在则整体改名;
    两边都有则逐项搬, 重名的不覆盖、留在原处。返回 [(说明, 是否需要人工处理)]。"""
    notes = []
    for name in ("results", "works"):
        old, new = os.path.join(root, name), os.path.join(data, name)
        if not os.path.isdir(old):
            continue
        try:
            if not os.path.exists(new):
                os.makedirs(data, exist_ok=True)
                os.rename(old, new)
                notes.append(("%s/ 已搬到 data/%s/" % (name, name), False))
                continue
            left = [e for e in os.listdir(old) if os.path.exists(os.path.join(new, e))]
            for e in os.listdir(old):
                if e not in left:
                    shutil.move(os.path.join(old, e), os.path.join(new, e))
            if left:
                notes.append(("%s/ 里有 %d 项和 data/%s/ 重名，没有搬动，请手动核对后删除旧目录" % (name, len(left), name), True))
            else:
                os.rmdir(old)
                notes.append(("%s/ 已并入 data/%s/" % (name, name), False))
        except OSError as e:
            notes.append(("%s/ 搬到 data/ 失败（%s）。请关掉占用这些文件的程序后重启服务，或手动搬到 data/%s/" % (name, e, name), True))
    return notes


def main(argv=None):
    args = parse_args(argv)
    CONFIG.update(host=args.host, port=args.port, token=args.token)
    try:
        server = BenchServer((args.host, args.port), Handler)
    except OSError as e:
        print("✗ 无法监听 %s:%d（%s）\n  端口可能已被占用，常见原因是已有 LLM Bench Pro 在运行。"
              "\n  请先关闭旧进程，或换一个端口：python run.py %d" % (args.host, args.port, e, args.port + 1))
        sys.exit(1)
    moved = migrate_legacy_dirs()
    db = store.default_db()
    store.init(db)
    imported = store.import_dir(RESULTS, only_new=True)
    stale = store.mark_stale_runs()
    shown = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    print("LLM Bench Pro %s => http://%s:%d%s  (db: %s)" % (APP_VERSION, shown, args.port,
                                                            "/?token=***" if args.token else "", db))
    for text, attention in moved:
        print("  %s 目录调整：%s" % ("⚠" if attention else "·", text))
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
