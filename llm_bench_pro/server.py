#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llm-bench-pro 服务: UI 页面 + 模型探测 + 在线起测 + 结果接口 (纯标准库)。
启动: python run.py [端口] [--host 127.0.0.1] [--token 访问令牌]
"""
import argparse
import base64
import functools
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
import endpoints  # noqa: E402
import export_html  # noqa: E402
import gen  # noqa: E402
import geneval  # noqa: E402
import i18n  # noqa: E402
import iq  # noqa: E402
import report  # noqa: E402
import sinks  # noqa: E402
import store  # noqa: E402
import tasksets  # noqa: E402
import vision_assets  # noqa: E402
from version import APP_VERSION  # noqa: E402

t, tn = i18n.t, i18n.tn

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
PROBE_TIMEOUT = 10  # 测试连接: 拉 /v1/models 最多等几秒


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

JOB_KINDS = ("perf", "iq", "gen", "bank")


def job_name(kind):
    """任务的名称 (出现在提示和日志里)。按当前语言生成, 所以是函数, 不是模块级常量。
    ctx="任务名": 「代码生成」在别处 (场景名等) 的英文说法不一样, 用语境区分。"""
    return {"perf": t("性能测试", ctx="任务名"), "iq": t("能力评测", ctx="任务名"),
            "gen": t("代码生成", ctx="任务名"), "bank": t("题集更新", ctx="任务名")}[kind]


class Job:
    """一类后台任务(同类同一时刻只运行一个): 状态、日志、取消信号、访问的模型端点、正在读的素材文件。"""

    def __init__(self, kind, log_limit=500):
        self.kind, self.log_limit = kind, log_limit
        self.lang = i18n.current_lang()  # 任务启动时的语言 (try_start 里更新): 任务的日志和结果里的说明都用它
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.state = {"running": False, "log": [], "error": None, "run_id": None, "started_at": None,
                      "base": None, "title": None, "cancelling": False, "files": []}

    def line(self, msg):
        with self.lock:
            self.state["log"].append({"t": round(time.time(), 1), "msg": str(msg)})
            self.state["log"] = self.state["log"][-self.log_limit:]

    def snapshot(self):
        with self.lock:
            return dict(self.state, log=list(self.state["log"]))

    def try_start(self, base, title, run_id=None, files=None):
        """files: 这次要读的素材文件(任务集、回放文件), 运行期间不允许删除。"""
        with self.lock:
            if self.state["running"]:
                return False
            self.lang = i18n.current_lang()  # 记下发起这个任务的请求的语言, 之后别的请求的语言不影响它
            self.cancel.clear()
            self.state.update({"running": True, "log": [], "error": None, "run_id": run_id, "base": base,
                               "title": title, "cancelling": False, "files": [os.path.realpath(f) for f in files or []],
                               "started_at": datetime.now(timezone.utc).isoformat()})
            return True

    def set(self, **kw):
        with self.lock:
            self.state.update(kw)

    def run(self, target, progress_attr=None, module=None):
        """在后台线程中执行 target(job); 统一记录异常与结束状态。任务线程和它里面的工作线程都用启动时记下的语言。"""
        def body():
            i18n.set_lang(self.lang)
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
        i18n.spawn(body, name="job-" + self.kind)


JOBS = {k: Job(k) for k in JOB_KINDS}


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
            return job_name(k)
    return None


def running_run_ids():
    return {j.snapshot()["run_id"] for j in JOBS.values() if j.snapshot()["running"]} - {None}


def iq_wrong(run_id, sid, limit=300):
    """某次能力评测某科目的未答对题目: 题干/选项/标准答案 + 模型答案/截断/错误/正文尾部。"""
    if not run_id.startswith("iq_") or not _RUN_ID_RE.match(run_id):
        return {"ok": False, "error": t("非法 run_id")}
    doc = store.get_run(run_id)
    if not doc:
        return {"ok": False, "error": t("run 不存在")}
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
    elif "resp" in it or tail.startswith("（无正文"):  # 旧版数据里的标记, 只用来识别已存的旧数据 (登记在允许清单里), 不是输出
        r["has"] = "empty"  # 模型没有给出正式回答(只有思考或空内容)
    elif tail:
        r["has"] = "tail"  # 旧版: 只有答错的题存了回答最后 240 字
    return r


def iq_items(run_id, cmp_ids=""):
    """逐题查看: 主运行答过的每道题(题干/选项/标准答案/检查规则) + 主运行与对比运行每题的作答摘要。
    对比运行的题集不同时不逐题对照(same_bank=False, 不返回记录)。"""
    if not _valid_iq_id(run_id):
        return {"ok": False, "error": t("非法 run_id")}
    ids = list(dict.fromkeys(x for x in (cmp_ids or "").split(",") if x and x != run_id))[:5]
    if not all(_valid_iq_id(x) for x in ids):
        return {"ok": False, "error": t("非法对比 run_id")}
    doc = store.get_run(run_id)
    if not doc:
        return {"ok": False, "error": t("run 不存在")}
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
        return {"ok": False, "error": t("非法 run_id")}
    try:
        idx = int(idx)
    except (TypeError, ValueError):
        return {"ok": False, "error": t("非法题号")}
    head = store.get_run(ids[0], items=False)
    if not head:
        return {"ok": False, "error": t("run 不存在")}
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
    elif tail.startswith("（无正文"):  # 旧版数据里的标记 (同 _rec_summary)
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
        return {"ok": False, "error": t("非法 run_id")}
    a, b = store.get_run(a_id), store.get_run(b_id)
    if not a or not b:
        return {"ok": False, "error": t("run 不存在")}
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
        raise ValueError(t("不支持导出这个页面"))
    ids = list(dict.fromkeys([a_id] + [x for x in cmp_ids if x]))
    if len(ids) > 7:
        raise ValueError(t("一次最多导出 7 次测试"))
    for x in ids:
        if not (_RUN_ID_RE.match(x or "") and x.startswith(_KIND_PREFIX[kind])):
            raise ValueError(t("非法 run_id: {id}", id=x))
    api, files = {}, {}
    if kind == "perf":
        runs = {x: store.get_run(x) for x in ids}
        miss = [x for x, d in runs.items() if d is None]
        if miss:
            raise ValueError(tn("测试不存在: {ids}", len(miss), ids=", ".join(miss)))
        summary = {r["run_id"]: r for r in store.list_runs("perf", summary=True)}
        api["perfList"] = [summary[x] for x in ids if x in summary]
        api["perfRuns"] = runs
    elif kind == "iq":
        lst = {r["run_id"]: r for r in store.list_runs("iq", items=False)}
        miss = [x for x in ids if x not in lst]
        if miss:
            raise ValueError(tn("测试不存在: {ids}", len(miss), ids=", ".join(miss)))
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
            raise ValueError(tn("测试不存在: {ids}", len(miss), ids=", ".join(miss)))
        api["genList"] = [lst[x] for x in ids]
        for r in api["genList"]:
            for it in r.get("items") or []:
                _pack_work(it, files)
    return {"api": api, "files": files, "sel": {"a": a_id, "cmp": ids[1:]}, "worksCsp": WORKS_CSP_META}


# 离线报告只带显示偏好(主题、界面语言、术语模式、视图、表格排序与列、标签页、每页条数、作品列表的每页件数、密度、侧栏), 不带表单里填过的地址和 Key
EXPORT_LS_KEYS = ("llm-bench-pro-theme", "llm-bench-pro-lang", "llm-bench-pro-terms", "llm-bench-pro-viewmode", "llm-bench-pro-dt",
                  "llm-bench-pro-ctab", "llm-bench-pro-qb", "llm-bench-pro-gen-works", "llm-bench-pro-density", "llm-bench-pro-rail")
# 术语模式只收这两个值: plain = 大白话(默认), pro = 专业词
TERMS_MODES = ("plain", "pro")


def _export_state(raw):
    raw = raw if isinstance(raw, dict) else {}
    theme = raw.get("theme") if raw.get("theme") in ("light", "dark") else "dark"
    ls = raw.get("ls") if isinstance(raw.get("ls"), dict) else {}
    ls = {k: v for k, v in ls.items() if k in EXPORT_LS_KEYS and isinstance(v, str) and len(v) <= 65536}
    ls["llm-bench-pro-theme"] = theme
    if ls.get("llm-bench-pro-terms") not in TERMS_MODES:
        ls.pop("llm-bench-pro-terms", None)
    if ls.get("llm-bench-pro-lang") not in ("zh", "en"):  # 界面语言只收 zh / en, 别的值不带 (报告里走默认的语言选择)
        ls.pop("llm-bench-pro-lang", None)
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
    gv = raw.get("genView")  # 作品列表的难度筛选 / 名称搜索 / 第几页 / 每页几件
    if isinstance(gv, dict):
        page, size = gv.get("page"), gv.get("size")
        ui["genView"] = {"tier": str(gv.get("tier") or "all")[:20], "q": str(gv.get("q") or "")[:80],
                         "page": page if isinstance(page, int) and not isinstance(page, bool) and 0 <= page < 100000 else 0,
                         "size": size if size in (12, 24, 48) and not isinstance(size, bool) else 12}
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
        raise ValueError(t("sampling 格式错误"))
    out = {}
    for k, lo, hi in (("temperature", 0.0, 2.0), ("top_p", 0.0, 1.0), ("top_k", -1, 1000)):
        v = raw.get(k)
        if v in (None, ""):
            continue
        v = int(v) if k == "top_k" else float(v)
        if not lo <= v <= hi:
            raise ValueError(t("{name} 超出范围 {lo}–{hi}", name=k, lo=lo, hi=hi))
        out[k] = v
    return out


def _ints(raw, name, lo, hi):
    """整数列表: 接受 [1,2] 或 "1,2"; 越界/非法抛 ValueError。"""
    if isinstance(raw, str):
        raw = [x for x in raw.split(",") if x.strip()]
    if not isinstance(raw, list) or not raw:
        raise ValueError(t("{name} 应为逗号分隔整数列表", name=name))
    try:
        out = sorted({int(x) for x in raw})
    except (TypeError, ValueError):
        raise ValueError(t("{name} 应为整数列表", name=name))
    if not (lo <= min(out) and max(out) <= hi):
        raise ValueError(t("{name} 超出范围 {lo}-{hi}", name=name, lo=lo, hi=hi))
    return out


def _mtime_iso(p):
    return datetime.fromtimestamp(os.path.getmtime(p), timezone.utc).isoformat()[:19]


def _dims_text(checks):
    """图片尺寸范围: 全部一样时 "448×448", 否则 "最小 – 最大"(按像素数); 都读不出尺寸时为空。"""
    dims = sorted({(c["width"], c["height"]) for c in checks if c.get("width")}, key=lambda d: (d[0] * d[1], d))
    if not dims:
        return ""
    return "%d×%d" % dims[0] if len(dims) == 1 else "%d×%d – %d×%d" % (dims[0] + dims[-1])


def _img_reject(name, msg, code="unsupported"):
    """上传时没进到格式检查就被拒的图片, 结果字段与 vision_assets.check_image 一致。"""
    return {"name": name, "bytes": 0, "format": None, "width": None, "height": None, "ext": None,
            "ok": False, "level": "bad", "code": code, "msg": msg}


# 素材列表里的检查结果缓存: 上传的任务集和图片包按内容命名、写入后不再改, 按 (路径, 大小, 修改时间) 缓存,
# 打开素材列表时不用每次把所有文件重读、重查一遍(任务集最大 15 MB)。文件被手动改过时键会变, 自动重查
@functools.lru_cache(maxsize=256)
def _task_file_check(path, size, mtime_ns):
    """任务集的汇总: 共几行、可用几行、要求 JSON / 带图片的条数、输入长度、max_tokens 分布(与上传检查同一套判断)。
    逐行索引另有一个只留最近两个文件的缓存(tasksets.scan), 这里只留汇总, 文件再多也不占多少内存。"""
    return dict(tasksets.scan(path, size, mtime_ns)["summary"])


@functools.lru_cache(maxsize=256)
def _image_pack_check(d, stamp, lang):
    """图片包的逐张检查结果。每张的 msg 是按当前语言写的说明, 所以语言也是缓存键: 中英文界面各缓存一份, 不会互相串。"""
    return vision_assets.scan_dir(d, keep_data=False)


def _dir_stamp(d):
    """目录里各文件的 (名字, 大小, 修改时间), 作图片包检查结果的缓存键。"""
    return tuple(sorted((e.name, e.stat().st_size, e.stat().st_mtime_ns) for e in os.scandir(d) if e.is_file()))


def _parse_scenarios(body):
    """任务场景配置: scenarios.tasks(模板多选) + 共用参数 + 各模板专属参数。
    返回可直接传给 bench.run_suite 的 dict(无任务时返回 None); 非法抛 ValueError。"""
    scen = body.get("scenarios")
    if scen is None:
        return None
    if not isinstance(scen, dict):
        raise ValueError(t("scenarios 应为对象"))
    tasks = scen.get("tasks") or []
    if isinstance(tasks, str):
        tasks = [x.strip() for x in tasks.split(",") if x.strip()]
    if not isinstance(tasks, list) or not tasks:
        raise ValueError(t("tasks 应为任务类型列表"))
    for task in tasks:
        if task not in bench.SCN_TEMPLATES:
            raise ValueError(t("未知任务类型 {name} (可选: {options})", name=task, options="/".join(bench.SCN_TEMPLATES)))
    out = {"tasks": tasks}
    if len(set(tasks)) != len(tasks):
        raise ValueError(t("tasks 里有重复的任务类型"))
    try:
        out["conc"] = _ints(scen.get("conc") or [4, 8], "scenarios.conc", 1, 128)
        out["requests_per_worker"] = max(1, min(50, int(scen.get("requests_per_worker") or 3)))
        out["max_tokens"] = max(64, min(8192, int(scen.get("max_tokens") or 512)))
    except (TypeError, ValueError):
        raise ValueError(t("requests_per_worker / max_tokens 应为整数"))
    if "rag" in tasks:
        out["rag_ctx"] = _ints(scen.get("rag_ctx") or [4000], "scenarios.rag_ctx", 512, 65536)
    if "vision" in tasks:
        # 图片来源: image_id(上传的图片包) > dir(服务器上的文件夹) > 内置示例图片(默认, builtin 或什么都不给)
        src = scen.get("vision_src") or {}
        if not isinstance(src, dict):
            raise ValueError(t("vision_src 应为对象"))
        # what: 提示里用的名字 (图片包 id 或文件夹路径); is_pack: 是上传的图片包还是服务器上的文件夹。
        # 英文语序和中文不一样, 「图片包 xx」「图片文件夹 xx」不能拼成碎片, 下面每种情况各写一整句
        img_dir, what, is_pack = "", "", False
        iid = str(src.get("image_id") or "").strip()
        if iid and iid != "builtin":
            if not re.match(r"^img-[0-9a-f]{12}$", iid):
                raise ValueError(t("非法 image_id"))
            img_dir, what, is_pack = os.path.join(SCN_IMAGES_DIR, iid), iid, True
            if not os.path.isdir(img_dir):
                raise ValueError(t("图片包 {name} 不存在（可能已被删除），请重新上传或改用内置示例图片", name=what))
        elif not iid and not src.get("builtin") and str(src.get("dir") or "").strip():
            img_dir = what = str(src["dir"]).strip()
            if not os.path.isdir(img_dir):
                raise ValueError(t("服务器上没有这个图片文件夹: {dir}", dir=img_dir))
        if img_dir:  # 发送前逐张检查: 一张能用的都没有就不开始(否则要等前面几个阶段跑完才失败)
            good, checks = vision_assets.scan_dir(img_dir, keep_data=False)
            if not checks:
                if is_pack:
                    raise ValueError(t("图片包 {name} 里没有图片（支持 jpg / png / webp / gif）", name=what))
                raise ValueError(t("图片文件夹 {name} 里没有图片（支持 jpg / png / webp / gif）", name=what))
            if not good:
                detail = t("；").join("%s %s" % (c["name"], c["msg"]) for c in checks[:3])
                if is_pack:
                    raise ValueError(t("图片包 {name} 里没有能用的图片：{detail}。请重新上传，或改用内置示例图片",
                                       name=what, detail=detail))
                raise ValueError(t("图片文件夹 {name} 里没有能用的图片：{detail}。请重新上传，或改用内置示例图片",
                                   name=what, detail=detail))
            out["vision_dir"] = img_dir
        try:
            out["vision_images"] = max(1, min(4, int(src.get("images") or 1)))
        except (TypeError, ValueError):
            raise ValueError(t("vision_src.images 应为 1-4 的整数"))
    if "custom" in tasks:
        fid = (scen.get("custom_file_id") or "").strip()
        if fid:
            if not tasksets.ID_RE.match(fid):
                raise ValueError(t("非法 custom_file_id"))
            full = tasksets.file_path(SCN_TASKS_DIR, fid)
            if not os.path.isfile(full):
                raise ValueError(t("任务集不存在: {id} (可能已被删除, 请重新导入)", id=fid))
            out["custom_file"] = full
            # 记进结果: 任务集页面按它统计「用过几次」, 速度测试结果页显示「任务集：名称」
            out["task_set"] = {"id": fid, "name": tasksets.read_meta(SCN_TASKS_DIR, fid)["name"]}
        elif (scen.get("custom_file") or "").strip():
            out["custom_file"] = scen["custom_file"].strip()
            if not os.path.isfile(out["custom_file"]):
                raise ValueError(t("任务集文件不存在: {path}", path=out["custom_file"]))
        else:
            raise ValueError(t("自定义任务集需要选择已上传的任务集或填写服务器文件路径"))
    return out


def _parse_replay(body):
    """真实请求回放配置: file/file_id + closed/open; 返回传给 run_suite 的 dict 或 None。"""
    rp = body.get("scenarios", {}).get("replay") if isinstance(body.get("scenarios"), dict) else None
    if body.get("replay"):
        rp = body["replay"]
    if not rp:
        return None
    if not isinstance(rp, dict):
        raise ValueError(t("replay 应为对象"))
    fid = (rp.get("file_id") or "").strip()
    if fid:
        if not re.match(r"^replay-[0-9a-f]{12}$", fid):
            raise ValueError(t("非法 file_id"))
        full = os.path.join(REPLAY_DIR, fid + ".jsonl")
        if not os.path.isfile(full):
            raise ValueError(t("回放文件不存在: {id} (可能已被删除, 请重新上传)", id=fid))
        rp = dict(rp, file=full)
    elif not (rp.get("file") or "").strip():
        raise ValueError(t("replay 需要 file_id(上传的文件)或 file(服务器路径)"))
    replay = dict(rp)
    closed = replay.get("closed")
    if closed:
        if not isinstance(closed, dict):
            raise ValueError(t("replay.closed 应为对象"))
        try:
            rpw = max(1, min(100, int(closed.get("requests_per_worker") or 4)))
        except (TypeError, ValueError):
            raise ValueError(t("replay.closed.requests_per_worker 应为整数"))
        replay["closed"] = {"conc": _ints(closed.get("conc") or [8], "replay.closed.conc", 1, 128),
                            "requests_per_worker": rpw}
    o = replay.get("open")
    if o:
        if not isinstance(o, dict):
            raise ValueError(t("replay.open 应为对象"))
        try:
            rates = [float(x) for x in (o.get("rates") if isinstance(o.get("rates"), list) else
                                        str(o.get("rates") or "").split(",")) if str(x).strip()]
        except (TypeError, ValueError):
            raise ValueError(t("replay.open.rates 应为数字列表"))
        rates = sorted({round(r, 3) for r in rates if 0.05 <= r <= 1000})
        if not rates:
            raise ValueError(t("replay.open.rates 需要至少一个 0.05-1000 的速率"))
        replay["open"] = {"rates": rates,
                          "duration_s": max(5, min(3600, int(o.get("duration_s") or 60)))}
    return replay


# ---------------------------------------------------------------- 任务集页面
# 列表 / 详情(逐行分页、筛选、搜索) / 某行全文 / 图片 / 改名 / 删除 / 下载。函数返回 (状态码, 数据), 由 Handler 输出

def _busy_task_files():
    """正在跑的速度测试要读的文件(真实路径): 这些任务集不能删。"""
    st = JOBS["perf"].snapshot()
    return set(st.get("files") or []) if st["running"] else set()


def _task_set_path(fid):
    """(路径, 状态码, 错误说明): id 必须是 scn- 加 12 位十六进制数字, 文件要存在。"""
    if not isinstance(fid, str) or not tasksets.ID_RE.match(fid):
        return None, 400, t("任务集 id 不对（应为 scn- 加 12 位十六进制数字）")
    path = tasksets.file_path(SCN_TASKS_DIR, fid)
    if not os.path.isfile(path):
        return None, 404, t("任务集不存在（可能已被删除）")
    return path, 200, ""


def _task_set_item(fid, uses, busy):
    path = tasksets.file_path(SCN_TASKS_DIR, fid)
    st = os.stat(path)
    s = _task_file_check(path, st.st_size, st.st_mtime_ns)
    meta = tasksets.read_meta(SCN_TASKS_DIR, fid)
    used = uses.get(fid) or []
    return {"id": fid, "name": meta["name"], "named": meta["named"], "imported_utc": meta["imported_utc"],
            "size": st.st_size, "total": s["total"], "valid": s["valid"], "bad": s["bad"], "skipped": s["skipped"],
            "json": s["json"], "image": s["image"], "warnings": s["warning_count"], "chars_avg": s["chars_avg"],
            "chars_max": s["chars_max"], "mt_top": s["mt_dist"][0] if s["mt_dist"] else None, "mt_unset": s["mt_unset"],
            "uses": len(used), "last_used": used[0]["started_utc"] if used else None,
            "busy": os.path.realpath(path) in busy}


def task_set_list():
    """每个任务集的名称、行数统计、输入长度、大小、导入时间、用过几次; 新导入的在前。"""
    uses, busy, sets = store.task_set_uses(), _busy_task_files(), []
    for fid in tasksets.list_ids(SCN_TASKS_DIR):
        try:
            sets.append(_task_set_item(fid, uses, busy))
        except OSError:  # 列目录之后刚被删掉
            continue
    sets.sort(key=lambda x: (x["imported_utc"] or "", x["id"]), reverse=True)
    return 200, {"ok": True, "sets": sets}


def task_set_detail(fid, offset="", limit="", status="", q="", head=True):
    """一个任务集: 概况(head=True 时带上; 翻页、筛选时不用再传) + 按筛选条件和关键词取的一页逐行数据。"""
    path, code, err = _task_set_path(fid)
    if not path:
        return code, {"ok": False, "error": err}
    try:
        offset, limit = int(offset or 0), int(limit or 12)
    except (TypeError, ValueError):
        return 400, {"ok": False, "error": t("offset / limit 应为整数")}
    if offset < 0 or not 1 <= limit <= tasksets.PAGE_MAX:
        return 400, {"ok": False, "error": t("offset 不能小于 0，limit 应为 1–{max}", max=tasksets.PAGE_MAX)}
    status = status or "all"
    if status not in tasksets.FILTERS:
        return 400, {"ok": False, "error": t("status 应为 {options} 之一", options=" / ".join(tasksets.FILTERS))}
    q = str(q or "")[:200]
    s = tasksets.scan(*tasksets.stat_key(path))
    counts, total, page = tasksets.query(s, status, q, offset, limit)
    texts = tasksets.read_texts(path, page)
    out = {"ok": True, "id": fid, "status": status, "q": q, "offset": offset, "limit": limit, "total": total,
           "counts": counts, "lines": [tasksets.line_view(r, text) for r, text in zip(page, texts)]}
    if head:
        uses = store.task_set_uses().get(fid) or []
        item = _task_set_item(fid, {fid: uses}, _busy_task_files())
        summ = s["summary"]
        item.update(chars=[r[tasksets.CHARS] for r in s["rows"] if r[tasksets.ST] == "ok"], mt_dist=summ["mt_dist"],
                    chars_min=summ["chars_min"], chars_med=summ["chars_med"])
        out.update(set=item, uses=uses[:50])
    return 200, out


def task_set_line(fid, line, raw=False):
    """某一行的全文(「展开全文」「看原始 JSON」); raw=True 时给文件里这一行的原文(「复制这一行 JSON」)。"""
    path, code, err = _task_set_path(fid)
    if not path:
        return code, {"ok": False, "error": err}
    try:
        no = int(line)
    except (TypeError, ValueError):
        return 400, {"ok": False, "error": t("line 应为行号")}
    row = tasksets.find(tasksets.scan(*tasksets.stat_key(path)), no)
    if row is None:
        return 404, {"ok": False, "error": t("没有第 {no} 行（或者这一行是空行）", no=no)}
    text = tasksets.read_texts(path, [row])[0]
    if raw:
        return 200, {"ok": True, "no": no, "text": text}
    return 200, {"ok": True, "line": tasksets.line_view(row, text, full=True), "pretty": tasksets.pretty(text)}


def task_set_image(fid, line, idx):
    """某行第 idx 张图(从 0 数)的字节: 返回 (状态码, 字节或错误数据, MIME)。只给 data URL 里的图片, 网址不去下载。"""
    path, code, err = _task_set_path(fid)
    if not path:
        return code, {"ok": False, "error": err}, None
    try:
        no, k = int(line), int(idx)
    except (TypeError, ValueError):
        return 400, {"ok": False, "error": t("line / idx 应为整数")}, None
    row = tasksets.find(tasksets.scan(*tasksets.stat_key(path)), no)
    if row is None:
        return 404, {"ok": False, "error": t("没有第 {no} 行（或者这一行是空行）", no=no)}, None
    try:
        data, ctype = tasksets.image_bytes(tasksets.read_texts(path, [row])[0], k)
    except LookupError as e:
        return 404, {"ok": False, "error": str(e)}, None
    except tasksets.RemoteImage as e:
        return 400, {"ok": False, "error": str(e)}, None
    except ValueError as e:
        return 422, {"ok": False, "error": str(e)}, None
    return 200, data, ctype


# ---------------------------------------------------------------- 模型管理页面
# 保存的模型(名称 / 地址 / Key / 模型) + 在测试里用过几次 + 最近用它跑过的测试。函数返回 (状态码, 数据), 由 Handler 输出

def endpoint_list():
    """保存的模型, 每个带上在测试里用过几次(按地址和模型对上历史测试: 只查一次 runs 表, 在 endpoints.usage 里分组)。"""
    groups = endpoints.usage(store.run_targets())
    eps = store.list_endpoints()
    for ep in eps:
        ep["uses"] = endpoints.uses_of(ep, groups)
    return eps


def _endpoint_of(ep_id):
    """(保存的模型, 状态码, 错误说明): id 必须是 ep_ 加字母数字, 模型要存在。"""
    if not isinstance(ep_id, str) or not endpoints.ID_RE.match(ep_id):
        return None, 400, t("模型 id 不对（应为 ep_ 开头的字母、数字、下划线）")
    ep = store.get_endpoint(ep_id)
    if not ep:
        return None, 404, t("这个模型不存在（可能已被删除）")
    return ep, 200, ""


def endpoint_runs(ep_id, kind="", limit=""):
    """最近用这个模型(地址和模型名称都对上)跑过的测试, 新的在前, 最多 50 次; kind 为 perf / iq / gen 时只要这一类。
    每次带上结果摘要(速度: 最高总生成速度与单个请求速度; 能力: 正确率; 代码生成: 完成几题、检查通过率)。"""
    ep, code, err = _endpoint_of(ep_id)
    if not ep:
        return code, {"ok": False, "error": err}
    kind = kind or "all"
    if kind not in ("all",) + endpoints.KINDS:
        return 400, {"ok": False, "error": t("kind 应为 all / perf / iq / gen 之一")}
    try:
        limit = int(limit or endpoints.RUNS_MAX)
    except (TypeError, ValueError):
        return 400, {"ok": False, "error": t("limit 应为整数")}
    if not 1 <= limit <= endpoints.RUNS_MAX:
        return 400, {"ok": False, "error": t("limit 应为 1–{max}", max=endpoints.RUNS_MAX)}
    hit, counts = endpoints.matching_runs(store.run_targets(), ep, kind)
    briefs = store.run_briefs([rid for rid, _ in hit[:limit]])
    runs = []
    for rid, _ in hit[:limit]:
        b = briefs.get(rid)
        if not b:  # 查完列表之后刚被删掉
            continue
        acc = {k: b.pop(k) for k in ("acc", "correct", "n")}
        if b["kind"] == "perf":
            b["summary"] = endpoints.perf_summary(b.pop("phases"))
        elif b["kind"] == "gen":
            b["summary"] = endpoints.gen_summary(b.pop("items"), b.pop("planned"))
        else:
            b["summary"] = acc
        if b.get("error"):
            b["error"] = str(b["error"])[:200]
        runs.append(b)
    return 200, {"ok": True, "id": ep["id"], "kind": kind, "limit": limit, "counts": counts,
                 "total": sum(counts.values()), "matched": len(hit), "runs": runs}


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
        # 本请求的语言: X-Lang, 其次 Accept-Language, 都没有用默认。旧版 HTML 报告 (/api/report) 常在浏览器地址栏里直接打开,
        # 发不了请求头, 所以它另认 ?lang=zh|en (写了就优先于请求头; 不认识的值当作没写)
        url_lang = i18n.normalize_lang(q("lang")) if path == "/api/report" else None
        i18n.set_lang(url_lang or i18n.lang_from_headers(self.headers))
        token = CONFIG["token"]
        if token and path in ("/", "/index.html") and q("token"):
            if hmac.compare_digest(q("token"), token):  # 带令牌打开页面: 写入 Cookie 后去掉地址栏中的令牌
                return self._redirect("/", {"Set-Cookie": "bench_token=%s; Path=/; HttpOnly; SameSite=Strict" % token})
        if not self._authorized(path, query):
            if path.startswith("/api/"):
                return self._json({"ok": False, "error": t("需要访问令牌")}, 401)
            return self._body(("<!doctype html><meta charset=utf-8><title>LLM Bench Pro</title>"
                               "<p style='font:14px system-ui;margin:40px'>%s</p>"
                               % t("该服务启用了访问令牌，请使用 <code>http://主机:端口/?token=令牌</code> 打开。")).encode(),
                              "text/html; charset=utf-8", 401)

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
            "/api/bank-status": lambda: self._json(JOBS["bank"].snapshot()),
            "/api/datasets": lambda: self._json(bankman.local_status()),
            "/api/status": lambda: self._json(JOBS["perf"].snapshot()),
            "/api/iq-status": lambda: self._json(JOBS["iq"].snapshot()),
            "/api/gen-status": lambda: self._json(JOBS["gen"].snapshot()),
            "/api/replay-list": lambda: self._json(self.replay_list()),
            "/api/scenario-list": lambda: self._json(self.scenario_list()),
            # 模型管理页面
            "/api/endpoints": lambda: self._json(endpoint_list()),
            "/api/endpoint-runs": lambda: self._reply(endpoint_runs(q("id"), q("kind"), q("limit"))),
            # 任务集页面
            "/api/task-sets": lambda: self._reply(task_set_list()),
            "/api/task-set": lambda: self._reply(task_set_detail(q("id"), q("offset"), q("limit"), q("status"), q("q"),
                                                                 head=q("head") != "0")),
            "/api/task-set-line": lambda: self._reply(task_set_line(q("id"), q("line"), raw=q("raw") == "1")),
            "/api/task-set-image": lambda: self.task_set_image(q("id"), q("line"), q("idx")),
            "/api/task-set-download": lambda: self.task_set_download(q("id")),
        }
        if path in routes:
            return routes[path]()
        if path == "/api/report":
            return self.report_html(q("id"), q("cmp"))
        if path in ("/api/run", "/api/export"):
            run_id = q("id")
            doc = store.get_run(run_id) if _RUN_ID_RE.match(run_id) else None
            if doc is None:
                return self._json({"error": t("run 不存在")}, 404)
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
        i18n.set_lang(i18n.lang_from_headers(self.headers))  # 本请求的语言 (同 do_GET); 后台任务在启动时再记下它
        parts = urllib.parse.urlsplit(self.path)
        try:  # 先读完请求体: 提前返回错误而不读取时, Windows 上客户端可能收到连接重置而非错误响应
            length = min(int(self.headers.get("Content-Length", 0)), 16 * 1024 * 1024)
            raw = self.rfile.read(length) if length > 0 else b""
        except (ValueError, OSError):
            return self._json({"ok": False, "error": "bad request"}, 400)
        if not self._authorized(parts.path, {}):
            return self._json({"ok": False, "error": t("需要访问令牌")}, 401)
        # 跨站/沙箱 iframe(Origin: null)中的作品页面不能调用接口: 要求同源, 且必须是 JSON 请求(跨站时会触发预检)
        origin = self.headers.get("Origin")
        if origin is not None and urllib.parse.urlsplit(origin).netloc != (self.headers.get("Host") or ""):
            return self._json({"ok": False, "error": t("拒绝跨源请求")}, 403)
        if not (self.headers.get("Content-Type") or "").lower().startswith("application/json"):
            return self._json({"ok": False, "error": t("Content-Type 必须为 application/json")}, 415)
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
            "/api/task-set-rename": self.api_task_set_rename,
            "/api/task-set-delete": self.api_task_set_delete,
        }.get(parts.path)
        if handler is None:
            return self._json({"ok": False, "error": "not found"}, 404)
        return handler(body)

    # ---- 通用
    def _busy_or_conflict(self, kind, base, body):
        """同类任务运行中 -> 409; 与性能测试共用同一端点 -> 409(code=endpoint_busy, 可带 force 确认后继续)。
        已写出拒绝响应时返回 True, 调用方必须立即返回。"""
        if JOBS[kind].snapshot()["running"]:
            self._json({"ok": False, "error": t("已有{name}在运行", name=job_name(kind))}, 409)
            return True
        other = endpoint_conflict(kind, base)
        if other and not body.get("force"):
            self._json({"ok": False, "code": "endpoint_busy", "conflict": other,
                        "error": t("{name}正在使用同一模型端点。同时运行会使性能测试的吞吐和延迟数据失真。", name=other)}, 409)
            return True
        return False

    def api_probe(self, body):
        """测试连接: 拉 /v1/models 得到模型清单(含最大上下文 max_model_len)和延迟, 再从 /version、/metrics 认框架和版本
        (带上同样的 Key: 服务开了鉴权时不带就认不出来)。连不上时 code 说明原因(见 endpoints.probe_fail), 页面写成大白话。"""
        raw, api_key = body.get("base"), body.get("api_key")
        if not isinstance(raw, str) or (api_key is not None and not isinstance(api_key, str)):
            return self._json({"ok": False, "code": "bad_url", "error": t("base / api_key 应为文字")}, 400)
        base = bench.normalize_base(raw)
        if not endpoints.url_ok(base):
            return self._json({"ok": False, "code": "bad_url", "base": base, "error": endpoints.bad_url()}, 400)
        api_key = (api_key or "").strip()
        if re.search(r"[\x00-\x1f\x7f]", api_key):
            return self._json({"ok": False, "code": "bad_key", "base": base, "error": t("API Key 中间不能有换行或其他控制字符")}, 400)
        headers = {"Authorization": "Bearer " + api_key} if api_key else {}
        t0 = time.perf_counter()
        try:
            req = urllib.request.Request(base + "/v1/models", headers=headers)
            with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as r:
                data = json.loads(r.read())
            latency = round((time.perf_counter() - t0) * 1000)
            models = endpoints.models_of(data)
        except Exception as e:
            code, status, text = endpoints.probe_fail(e)
            if api_key:  # 有的服务在出错说明里原样带上收到的 Key: 页面上只给遮住的形式
                text = text.replace(api_key, endpoints.mask_key(api_key))
            return self._json({"ok": False, "base": base, "code": code, "status": status, "error": text})
        # 认框架用剩下的时间(每个请求最多 4 秒): 服务慢的时候整个测试连接也不超过 PROBE_TIMEOUT 秒
        left = PROBE_TIMEOUT - (time.perf_counter() - t0)
        fw = bench.detect_framework(base, headers, timeout=min(4, left / 2)) if left >= 1 else {}
        return self._json({"ok": True, "base": base, "latency_ms": latency, "count": len(models), "models": models,
                           "framework": fw.get("name") or None, "fw_version": fw.get("version") or None})

    def api_cancel(self, body):
        kind = body.get("job")
        if kind not in JOBS:
            return self._json({"ok": False, "error": t("job 应为 perf / iq / gen / bank")}, 400)
        job = JOBS[kind]
        if not job.snapshot()["running"]:
            return self._json({"ok": False, "error": t("没有运行中的{name}", name=job_name(kind))}, 409)
        job.cancel.set()
        job.set(cancelling=True)
        with i18n.use_lang(job.lang):  # 这行日志写进任务的日志里: 用任务启动时的语言, 不用这次停止请求的语言
            job.line(t("收到停止请求：不再开始新的请求，已完成的结果会保留"))
        return self._json({"ok": True})

    def api_run_delete(self, body):
        run_id = body.get("run_id") or ""
        if not isinstance(run_id, str) or not _RUN_ID_RE.match(run_id):
            return self._json({"ok": False, "error": t("非法 run_id")}, 400)
        if run_id in running_run_ids():
            return self._json({"ok": False, "error": t("该运行尚未结束，请先停止")}, 409)
        try:
            kind = store.delete_run(run_id)
        except ValueError as e:
            return self._json({"ok": False, "error": str(e)}, 409)
        if kind is None:
            return self._json({"ok": False, "error": t("run 不存在")}, 404)
        if kind == "gen" and body.get("remove_works", True):
            d = safe_join(WORKS, run_id)
            if d and d != os.path.realpath(WORKS) and os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
        return self._json({"ok": True, "kind": kind})

    def api_endpoint_save(self, body):
        """保存一个模型(名称 / 服务地址 / API Key / 模型名称), 三个新建面板一键填入, 免去复制粘贴。
        带 id 是修改, 不带是新增; 字段规则见 endpoints.clean_fields。返回这一个和全部(都带「用过几次」)。"""
        ep_id = body.get("id")
        if ep_id not in (None, "") and (not isinstance(ep_id, str) or not endpoints.ID_RE.match(ep_id)):
            return self._json({"ok": False, "error": t("模型 id 不对（应为 ep_ 开头的字母、数字、下划线）")}, 400)
        fields, err = endpoints.clean_fields(body)
        if err:
            return self._json({"ok": False, "error": err}, 400)
        try:
            ep = store.save_endpoint(dict(fields, id=ep_id or None))
        except KeyError:
            return self._json({"ok": False, "error": t("这个模型不存在（可能已被删除）")}, 404)
        except ValueError as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        eps = endpoint_list()
        return self._json({"ok": True, "endpoint": next((x for x in eps if x["id"] == ep["id"]), ep), "endpoints": eps})

    def api_endpoint_use(self, body):
        """记下「一键填入」的时间(列表里的「最近使用」)。"""
        ep, code, err = _endpoint_of(body.get("id"))
        if not ep:
            return self._json({"ok": False, "error": err}, code)
        return self._json({"ok": True, "id": ep["id"], "last_used_utc": store.touch_endpoint(ep["id"])})

    def api_endpoint_delete(self, body):
        """删除保存的模型。已经填到新建面板里的内容和过去的测试结果都不受影响。"""
        ep, code, err = _endpoint_of(body.get("id"))
        if not ep:
            return self._json({"ok": False, "error": err}, code)
        store.delete_endpoint(ep["id"])
        return self._json({"ok": True, "id": ep["id"]})

    # ---- 任务场景: 自定义任务集 / 图片包
    _MAX_UPLOAD_IMAGES = 64

    def scenario_list(self):
        """任务集(每个带名称和可用行数)与图片包(张数、尺寸范围、有几张不能用), 新的在前; 另给内置示例图片的概况。"""
        tasks = []
        for fid in tasksets.list_ids(SCN_TASKS_DIR):
            p = tasksets.file_path(SCN_TASKS_DIR, fid)
            try:
                st = os.stat(p)
                chk = _task_file_check(p, st.st_size, st.st_mtime_ns)
            except OSError:  # 列目录之后刚被删掉
                continue
            meta = tasksets.read_meta(SCN_TASKS_DIR, fid)
            tasks.append({"file_id": fid, "name": meta["name"], "size": st.st_size, "mtime": meta["imported_utc"] or _mtime_iso(p),
                          "lines": chk["valid"], "total": chk["total"], "json": chk["json"], "image": chk["image"]})
        images = []
        if os.path.isdir(SCN_IMAGES_DIR):
            for dn in os.listdir(SCN_IMAGES_DIR):
                d = os.path.join(SCN_IMAGES_DIR, dn)
                if not (re.match(r"^img-[0-9a-f]{12}$", dn) and os.path.isdir(d)):
                    continue
                good, checks = _image_pack_check(d, _dir_stamp(d), i18n.current_lang())
                if not checks:
                    continue
                small = sum(1 for c in checks if c["code"] == "too_small")
                images.append({"image_id": dn, "count": len(checks), "usable": len(good), "too_small": small,
                               "broken": len(checks) - len(good) - small, "size": sum(c["bytes"] for c in checks),
                               "dims": _dims_text(checks), "mtime": _mtime_iso(d),
                               "problems": ["%s %s" % (c["name"], c["msg"]) for c in checks if not c["ok"]][:3]})
        tasks.sort(key=lambda x: x["mtime"], reverse=True)
        images.sort(key=lambda x: x["mtime"], reverse=True)
        return {"ok": True, "tasks": tasks, "images": images, "builtin_images": vision_assets.sample_summary()}

    def api_scenario_upload(self, body):
        """上传任务场景资产, 均内容寻址幂等; 总量受 16MB 请求体上限约束。
        kind=tasks: 任务集 JSONL {name, content}, 逐行检查(与测试时实际发送的判断相同), 返回 check 报告;
          name(文件名, 去掉扩展名)存为任务集名称; 内容完全相同的已经导入过时不重复保存(exists=true), 旧的没有名称就补上。
        kind=images: 图片包 {files:[{name, data(base64)}]}, 逐张检查, 损坏/太小/太大的不收, 返回每张的结果 files。"""
        kind = body.get("kind")
        if kind == "tasks":
            content = body.get("content")
            if not isinstance(content, str) or not content.strip():
                return self._json({"ok": False, "error": t("缺少文件内容 (content 应为 JSONL 文本)")}, 400)
            if len(content.encode("utf-8", "ignore")) > 15 * 1024 * 1024:
                return self._json({"ok": False, "error": t("文件超过 15MB 上限; 大文件请放到服务器后用路径引用")}, 400)
            check = bench.check_task_text(content)
            if not check["valid"]:
                first = check["hint"]
                if not first and check["problems"]:
                    p0 = check["problems"][0]
                    first = t("第 {line} 行：{reason}", line=p0["line"], reason=p0["reason"])
                # 有原因时写进括号; 是两个整句, 不拼碎片
                error = t("没有一行能用（{first}）", first=first) if first else t("没有一行能用")
                return self._json({"ok": False, "error": error, "check": check}, 400)
            data = content.encode("utf-8")
            fid = "scn-" + hashlib.sha256(data).hexdigest()[:12]
            os.makedirs(SCN_TASKS_DIR, exist_ok=True)
            path = tasksets.file_path(SCN_TASKS_DIR, fid)
            existed = os.path.isfile(path)
            if not existed:
                tmp = path + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, path)
            meta = tasksets.on_import(SCN_TASKS_DIR, fid, body.get("name"), existed)
            return self._json({"ok": True, "file_id": fid, "name": meta["name"], "exists": existed,
                               "imported_utc": meta["imported_utc"], "lines": check["valid"],
                               "bad_lines": check["total"] - check["valid"], "check": check})
        if kind == "images":
            files = body.get("files")
            if not isinstance(files, list) or not files:
                return self._json({"ok": False, "error": t("缺少 files: [{{name, data(base64)}}]")}, 400)
            report, keep = [], []
            for i, f in enumerate(files):
                f = f if isinstance(f, dict) else {}
                name = os.path.basename(str(f.get("name") or t("第 {n} 张", n=i + 1)))[:120]
                if i >= self._MAX_UPLOAD_IMAGES:
                    report.append(_img_reject(name, t("一次最多上传 {max} 张，这张没有收", max=self._MAX_UPLOAD_IMAGES)))
                    continue
                if os.path.splitext(name)[1].lower() not in vision_assets.EXT_FORMAT:
                    report.append(_img_reject(name, t("不是支持的图片类型（只收 jpg / png / webp / gif）")))
                    continue
                try:
                    raw = base64.b64decode(f.get("data") or "", validate=False)
                except (ValueError, TypeError):
                    report.append(_img_reject(name, t("上传的数据不是合法的 base64"), "broken"))
                    continue
                c = vision_assets.check_image(raw, name=name)
                report.append(c)
                if c["ok"]:
                    keep.append((c, raw))
            rejected = sum(1 for c in report if not c["ok"])
            if not keep:
                detail = t("；").join("%s %s" % (c["name"], c["msg"]) for c in report[:3])
                return self._json({"ok": False, "files": report, "rejected": rejected,
                                   "error": t("没有能用的图片：{detail}", detail=detail)}, 400)
            digest = hashlib.sha256()
            for _, raw in keep:
                digest.update(raw)
            iid = "img-" + digest.hexdigest()[:12]
            d = os.path.join(SCN_IMAGES_DIR, iid)
            os.makedirs(d, exist_ok=True)
            if not os.listdir(d):  # 内容寻址幂等; 按真实格式定扩展名(扩展名写错的也能按正确类型发送)
                for i, (c, raw) in enumerate(keep):
                    with open(os.path.join(d, "%02d%s" % (i, c["ext"])), "wb") as f:
                        f.write(raw)
            return self._json({"ok": True, "image_id": iid, "count": len(keep), "size": sum(len(r) for _, r in keep),
                               "dims": _dims_text([c for c, _ in keep]), "files": report, "rejected": rejected})
        return self._json({"ok": False, "error": t("kind 应为 tasks 或 images")}, 400)

    # ---- 任务集页面: 图片 / 下载 / 改名 / 删除(列表、详情、某行全文见 task_set_* 函数)
    def task_set_image(self, fid, line, idx):
        code, data, ctype = task_set_image(fid, line, idx)
        if code != 200:
            return self._json(data, code)
        # 内容寻址的文件写入后不再改, 同一张图不用每次翻页都重新下载
        return self._body(data, ctype, cache="private, max-age=86400")

    def task_set_download(self, fid):
        """原文件; 下载的文件名用任务集名称(非 ASCII 名称按 RFC 5987 写在 filename* 里)。"""
        path, code, err = _task_set_path(fid)
        if not path:
            return self._json({"ok": False, "error": err}, code)
        name = tasksets.download_name(tasksets.read_meta(SCN_TASKS_DIR, fid)["name"], fid)
        plain = name if re.match(r"^[A-Za-z0-9 ._()\[\]-]+$", name) else fid + ".jsonl"
        with open(path, "rb") as f:
            data = f.read()
        disp = "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (plain, urllib.parse.quote(name, safe=""))
        return self._body(data, "application/x-ndjson; charset=utf-8", headers={"Content-Disposition": disp})

    def api_task_set_rename(self, body):
        path, code, err = _task_set_path(body.get("id"))
        if not path:
            return self._json({"ok": False, "error": err}, code)
        if not isinstance(body.get("name"), str):
            return self._json({"ok": False, "error": t("name 应为文字")}, 400)
        name, err = tasksets.clean_name(body["name"])
        if err:
            return self._json({"ok": False, "error": err}, 400)
        fid = body["id"]
        meta = tasksets.read_meta(SCN_TASKS_DIR, fid)
        tasksets.write_meta(SCN_TASKS_DIR, fid, name=name, imported_utc=meta["imported_utc"])
        return self._json({"ok": True, "id": fid, "name": name})

    def api_task_set_delete(self, body):
        """删除任务集(连同元数据)。已经跑完的测试结果不受影响; 有速度测试正在用它时拒绝。"""
        path, code, err = _task_set_path(body.get("id"))
        if not path:
            return self._json({"ok": False, "error": err}, code)
        if os.path.realpath(path) in _busy_task_files():
            return self._json({"ok": False, "error": t("有速度测试正在用这个任务集，等测试结束（或停止它）之后再删除")}, 409)
        fid = body["id"]
        uses = len(store.task_set_uses().get(fid) or [])
        tasksets.remove(SCN_TASKS_DIR, fid)
        return self._json({"ok": True, "id": fid, "uses": uses})

    # ---- 真实请求回放池
    def replay_list(self):
        files = []
        if os.path.isdir(REPLAY_DIR):
            for fn in sorted(os.listdir(REPLAY_DIR)):
                if re.match(r"^replay-[0-9a-f]{12}\.jsonl$", fn):
                    p = os.path.join(REPLAY_DIR, fn)
                    files.append({"file_id": fn[:-6], "size": os.path.getsize(p), "mtime": _mtime_iso(p)})
        return {"ok": True, "files": files}

    def api_replay_upload(self, body):
        """上传回放文件: {name, content}; 内容寻址存 data/replay/replay-<sha12>.jsonl, 幂等。
        逐行检查与回放时实际发送的判断相同(bench.check_task_text)。"""
        name = (body.get("name") or "").strip()
        content = body.get("content")
        if not isinstance(content, str) or not content.strip():
            return self._json({"ok": False, "error": t("缺少文件内容 (content 应为 JSONL 文本)")}, 400)
        if len(content.encode("utf-8", "ignore")) > 15 * 1024 * 1024:
            return self._json({"ok": False, "error": t("文件超过 15MB 上限; 大文件请放到服务器后用路径引用")}, 400)
        check = bench.check_task_text(content)
        if not check["valid"]:
            return self._json({"ok": False, "error": t('没有可用行: 每行应为 {{"messages": [...], "params": {{...}}}}'),
                               "check": check}, 400)
        data = content.encode("utf-8")
        fid = "replay-" + hashlib.sha256(data).hexdigest()[:12]
        os.makedirs(REPLAY_DIR, exist_ok=True)
        path = os.path.join(REPLAY_DIR, fid + ".jsonl")
        if not os.path.isfile(path):  # 内容寻址: 同内容幂等
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        return self._json({"ok": True, "file_id": fid, "name": name[:80], "lines": check["valid"],
                           "bad_lines": check["total"] - check["valid"], "check": check})

    def report_html(self, run_id, cmp_id=None):
        """离线自包含 HTML 报告 (?id=run_a&cmp=run_b 做 A/B); 浏览器直接打开, 无需服务。
        报告和错误提示的语言: ?lang=zh|en (地址栏直接打开发不了请求头, 见 do_GET) 优先, 其次 X-Lang / Accept-Language。"""
        if not _RUN_ID_RE.match(run_id or ""):
            return self._json({"ok": False, "error": t("非法 run_id")}, 400)
        a = store.get_run(run_id)
        if a is None:
            return self._json({"ok": False, "error": t("run 不存在")}, 404)
        b = None
        if cmp_id:
            if not _RUN_ID_RE.match(cmp_id):
                return self._json({"ok": False, "error": t("非法 cmp run_id")}, 400)
            b = store.get_run(cmp_id)
            if b is None:
                return self._json({"ok": False, "error": t("cmp run 不存在")}, 404)
        try:
            html_text = report.render(a, b)  # 报告的语言取当前请求的语言 (do_GET 已按 ?lang= / X-Lang 设好)
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
            return self._json({"ok": False, "error": t("cmp 格式错误")}, 400)
        try:
            bundle = offline_bundle(page, str(body.get("id") or ""), [str(x) for x in cmp])
        except ValueError as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        info = self.version_info()
        bundle["api"]["version"] = {k: info[k] for k in ("version", "iq_version", "bench_version", "gen_version")}
        bundle["api"]["version"]["offline"] = True
        bundle["ui"] = _export_ui(body.get("ui"))
        bundle["exported_at"] = datetime.now(timezone.utc).isoformat()
        title = re.sub(r"[\x00-\x1f]", " ", str(body.get("title") or ""))[:160] or t("LLM Bench Pro 离线报告")
        text = export_html.compose(page, bundle, _export_state(body.get("state")), title)
        return self._body(text.encode("utf-8"), "text/html; charset=utf-8")

    # ---- 性能测试
    def api_start(self, body):
        base = bench.normalize_base(body.get("base", ""))
        url = base + "/v1/chat/completions"
        model = (body.get("model") or "").strip()
        suite = body.get("suite", "standard")
        if not base or not model:
            return self._json({"ok": False, "error": t("缺少 base/model")}, 400)
        if suite not in bench.SUITES:
            return self._json({"ok": False, "error": t("未知测试套件")}, 400)
        ladder = None
        raw_ladder = (body.get("conc_ladder") or "").strip().strip(",")
        if raw_ladder:
            try:
                ladder = sorted({int(x) for x in raw_ladder.split(",") if x.strip()})
                if not (1 <= min(ladder) and max(ladder) <= 128):
                    raise ValueError("range")
            except (ValueError, TypeError):
                return self._json({"ok": False, "error": t("并发梯度格式错误：应为 1-128 的逗号分隔整数，如 1,2,4,8")}, 400)
        matrix_conc = None
        raw_mc = str(body.get("matrix_conc") or "").strip()
        if raw_mc:
            try:
                matrix_conc = int(raw_mc)
                if not (1 <= matrix_conc <= 32):
                    raise ValueError("range")
            except ValueError:
                return self._json({"ok": False, "error": t("矩阵并发数应为 1-32 的整数")}, 400)
        lens = None
        raw_lens = (body.get("lens") or "").strip().strip(",")
        if raw_lens:
            try:
                lens = sorted({int(x) for x in raw_lens.split(",") if x.strip()})
                if not (1 <= min(lens) and max(lens) <= 256):
                    raise ValueError("range")
            except (ValueError, TypeError):
                return self._json({"ok": False, "error": t("输入长度梯度格式错误：应为 1-256 的逗号分隔整数（K），如 1,2,4,8,16")}, 400)
        try:
            scen_cfg = _parse_scenarios(body)
            replay_cfg = _parse_replay(body)
        except ValueError as e:
            return self._json({"ok": False, "error": t("场景配置错误：{error}", error=e)}, 400)
        warmup_shapes = body.get("warmup_shapes", True) is not False
        if self._busy_or_conflict("perf", base, body):
            return
        job = JOBS["perf"]
        files = [x for x in ((scen_cfg or {}).get("custom_file"), (replay_cfg or {}).get("file")) if x]
        if not job.try_start(base, model, files=files):  # 测试期间这些文件不能删(任务集页面的删除会检查)
            return self._json({"ok": False, "error": t("已有{name}在运行", name=job_name("perf"))}, 409)
        framework = (body.get("framework") or "").strip()[:60]
        fw_version = (body.get("fw_version") or "").strip()[:60]
        metrics_url = base + "/metrics" if body.get("metrics", True) else None
        tag = (body.get("tag") or "").strip()
        fixed_output = body.get("fixed_output", True) is not False
        # 存进结果里的说明: 用发起这个测试的请求的语言生成 (任务里的其他文字也一样), 原样存储
        notes = [t("启动时{name}正在使用同一端点，数据可能受干扰", name=body.get("conflict_with", t("其他测试")))] if body.get("force") else None

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
        """更新题集(后台任务): 本地缺少的题集数据先下载到 data/datasets/(默认魔搭, 国内), 再只用本地数据生成题库。
        进度看 /api/bank-status, 可用 /api/cancel {job: bank} 停止。offline=true 时不联网。"""
        job = JOBS["bank"]
        proxy = (body.get("proxy") or "").strip() or None
        source = body.get("source") if body.get("source") in bankman.SOURCE_MODES else "modelscope"
        offline = _truthy(body.get("offline"))
        if not job.try_start(None, t("更新题集")):
            return self._json({"ok": False, "error": t("题集正在更新中")}, 409)

        def work(j):
            try:
                bank, _ = bankman.build(proxy=proxy, mode=source, log=j.line, cancel=j.cancel, offline=offline)
            except bankman.Cancelled:
                j.line(t("已停止：已经下载好的题集数据留在本地，下次不用重新下载"))
                return
            except Exception:
                j.line(t("提示：可以换一个「题集下载源」或填「下载用的代理」再试；没有网的机器，"
                         "把能联网机器上的 data/datasets/ 拷贝过来即可离线生成"))
                raise
            j.set(run_id=bank["bank_id"])
        job.run(work)
        return self._json({"ok": True, "started": True, "source": source})

    def api_iq_start(self, body):
        base = bench.normalize_base(body.get("base", ""))
        url = base + "/v1/chat/completions"
        model = (body.get("model") or "").strip()
        bank_id = (body.get("bank_id") or "").strip()
        if not base or not model or not bank_id:
            return self._json({"ok": False, "error": t("缺少 base/model/bank_id")}, 400)
        try:
            conc = max(1, min(32, int(body.get("conc") or 8)))
            limit = max(1, min(200, int(body["limit"]))) if body.get("limit") else None
            sampling = _parse_sampling(body.get("sampling"))
        except (TypeError, ValueError) as e:
            return self._json({"ok": False, "error": t("参数错误：{error}", error=e)}, 400)
        try:
            bank = bankman.load_bank(bank_id)
        except FileNotFoundError as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        if self._busy_or_conflict("iq", base, body):
            return
        job = JOBS["iq"]
        if not job.try_start(base, model):
            return self._json({"ok": False, "error": t("已有{name}在运行", name=job_name("iq"))}, 409)
        subject_ids = body.get("subjects") or None
        if subject_ids is not None and not (isinstance(subject_ids, list) and all(isinstance(x, str) for x in subject_ids)):
            job.set(running=False)
            return self._json({"ok": False, "error": t("subjects 应为科目 id 列表")}, 400)
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
            return self._json({"ok": False, "error": t("非法 run_id")}, 400)
        doc = store.get_run(run_id)
        if not doc:
            return self._json({"ok": False, "error": t("run 不存在")}, 404)
        retry_errors = doc.get("status") == "done" and (doc.get("overall") or {}).get("errors")
        if doc.get("status") not in ("cancelled", "interrupted", "failed") and not retry_errors:
            return self._json({"ok": False, "error": t("只有已停止、中断、失败或含请求失败题目的运行可以续跑")}, 409)
        if doc.get("iq_version") != iq.IQ_VERSION:
            return self._json({"ok": False, "error": t("该运行由评测程序 {old} 生成，当前为 {new}，判分口径不同，不能续跑，请重新运行",
                                                       old=doc.get("iq_version"), new=iq.IQ_VERSION)}, 409)
        try:
            bank = bankman.load_bank(doc.get("bank_id") or "")
        except FileNotFoundError as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        base = bench.normalize_base(doc.get("url") or "")
        if self._busy_or_conflict("iq", base, body):
            return
        job = JOBS["iq"]
        if not job.try_start(base, doc.get("model"), run_id=run_id):
            return self._json({"ok": False, "error": t("已有{name}在运行", name=job_name("iq"))}, 409)

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
            return self._json({"ok": False, "error": t("缺少 base/model")}, 400)
        try:
            conc = max(1, min(8, int(body.get("conc") or 4)))
        except (TypeError, ValueError):
            return self._json({"ok": False, "error": t("并发应为整数")}, 400)
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
            return self._json({"ok": False, "error": t("已有代码生成任务或重新评测在运行")}, 409)
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
            return self._json({"ok": False, "error": t("非法 run_id")}, 400)
        if store.get_run(run_id, items=False) is None:
            return self._json({"ok": False, "error": t("run 不存在")}, 404)
        raw_tasks = body.get("tasks")
        try:
            only = None if not raw_tasks else set(gen.normalize_task_ids(raw_tasks))
        except ValueError as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        judge = _judge_cfg(body)
        job = JOBS["gen"]
        if not job.try_start(None, t("重新评测"), run_id=run_id):
            return self._json({"ok": False, "error": t("已有代码生成任务或重新评测在运行")}, 409)
        job.run(lambda j: gen.reevaluate(run_id, judge, only=only, log=j.line, cancel=j.cancel), "_GEN_PROGRESS", gen)
        return self._json({"ok": True, "run_id": run_id, "eval": geneval.Evaluator(judge).meta()})

    def api_gen_rate(self, body):
        run_id, item_id = body.get("run_id") or "", body.get("item_id")
        stars = body.get("stars")
        if not isinstance(run_id, str) or not _RUN_ID_RE.match(run_id):
            return self._json({"ok": False, "error": t("非法 run_id")}, 400)
        if stars is not None and not (isinstance(stars, int) and not isinstance(stars, bool) and 0 <= stars <= 5):
            return self._json({"ok": False, "error": t("stars 应为 0-5 整数或 null")}, 400)
        try:
            # 单行 UPDATE: 运行中的生成测试也可打星, 后台增量写入从不触碰 stars
            if not store.rate_gen_item(run_id, item_id, stars):
                return self._json({"ok": False, "error": t("run 或作品不存在")}, 404)
            return self._json({"ok": True})
        except Exception as e:
            return self._json({"ok": False, "error": str(e)[:200]}, 500)

    # ---- 输出
    def _json(self, obj, code=200):
        self._body(json.dumps(obj, ensure_ascii=False).encode(), "application/json", code)

    def _reply(self, res):
        """(状态码, 数据) → JSON 响应。"""
        code, obj = res
        self._json(obj, code)

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

    def _body(self, data, ctype, code=200, headers=None, cache="no-store"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
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

    def handle_error(self, request, client_address):
        """浏览器刷新或关掉页面时会中断还在传的响应(Windows 上是 WinError 10053 / 10054, 其他系统是 Broken pipe),
        属于正常情况, 不打印堆栈; 其他异常照常打印。"""
        if isinstance(sys.exc_info()[1], (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def parse_args(argv=None):
    i18n.preparse_lang(argv)  # 要在创建 argparse 之前: --help 的文字也是 --lang 指定的语言
    ap = argparse.ArgumentParser(description=t("LLM Bench Pro 服务"))
    ap.add_argument("port", nargs="?", type=int, default=18080, help=t("监听端口 (默认 18080)"))
    ap.add_argument("--host", default=os.environ.get("LLM_BENCH_HOST", "127.0.0.1"),
                    help=t("监听地址 (默认 127.0.0.1 仅本机; 局域网访问用 0.0.0.0, 建议同时设置 --token)"))
    ap.add_argument("--token", default=os.environ.get("LLM_BENCH_TOKEN", ""),
                    help=t("访问令牌; 设置后需用 http://主机:端口/?token=令牌 打开页面"))
    i18n.add_lang_arg(ap)
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
                notes.append((t("{name}/ 已搬到 data/{name}/", name=name), False))
                continue
            left = [e for e in os.listdir(old) if os.path.exists(os.path.join(new, e))]
            for e in os.listdir(old):
                if e not in left:
                    shutil.move(os.path.join(old, e), os.path.join(new, e))
            if left:
                notes.append((tn("{name}/ 里有 {n} 项和 data/{name}/ 重名，没有搬动，请手动核对后删除旧目录", len(left), name=name), True))
            else:
                os.rmdir(old)
                notes.append((t("{name}/ 已并入 data/{name}/", name=name), False))
        except OSError as e:
            notes.append((t("{name}/ 搬到 data/ 失败（{error}）。请关掉占用这些文件的程序后重启服务，或手动搬到 data/{name}/",
                            name=name, error=e), True))
    return notes


def main(argv=None):
    args = parse_args(argv)
    CONFIG.update(host=args.host, port=args.port, token=args.token)
    try:
        server = BenchServer((args.host, args.port), Handler)
    except OSError as e:
        print(t("✗ 无法监听 {host}:{port}（{error}）\n  端口可能已被占用，常见原因是已有 LLM Bench Pro 在运行。"
                "\n  请先关闭旧进程，或换一个端口：python run.py {next_port}",
                host=args.host, port=args.port, error=e, next_port=args.port + 1))
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
        print(t("  {mark} 目录调整：{text}", mark="⚠" if attention else "·", text=text))
    if args.host not in ("127.0.0.1", "localhost", "::1") and not args.token:
        print(t("  ⚠ 正在监听 {host} 且未设置访问令牌：局域网内任何人都可以发起测试、查看结果。建议加 --token", host=args.host))
    if imported["inserted"] or imported["errors"] or stale:
        print(t("  导入旧 JSON {inserted} 个, 失败 {failed} 个, 标记中断 {stale} 个",
                inserted=imported["inserted"], failed=len(imported["errors"]), stale=stale))
        for e in imported["errors"]:
            print("  ✗", e)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
