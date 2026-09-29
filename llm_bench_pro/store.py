#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
store.py — SQLite 结果存储 (标准库 sqlite3)
- runs 主表: 可查询字段列化, 其余顶层键整体存 meta_json (保证与原 JSON 往返等价)
- 子表: perf_phases / perf_metrics / iq_subjects / iq_items / gen_items, 支持增量写
- 兼容老 SQLite(≥3.7.11): 不用 STRICT / RETURNING / UPSERT / 生成列 / json1
- 并发: WAL + busy_timeout + BEGIN IMMEDIATE + 进程内写锁; 短连接, 不跨线程共享
CLI: python -m llm_bench_pro.store init|import|export|stale|check
"""
import argparse
import contextlib
import hashlib
import json
import os
import sqlite3
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根(包上一级)
SCHEMA_VERSION = 2  # 2: deleted_runs 墓碑表
STALE_S = 300  # 心跳超过该秒数未更新的 running 运行视为中断
KINDS = ("perf", "iq", "gen")
_CHILD_KEYS = ("phases", "metrics_samples", "subjects", "items")

_write_lock = threading.Lock()
_inited = set()


def default_db():
    return os.environ.get("LLM_BENCH_DB") or os.path.join(ROOT, "data", "llm_bench.db")


DDL = """
CREATE TABLE IF NOT EXISTS runs (
  run_id        TEXT PRIMARY KEY,
  kind          TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'running',
  model         TEXT NOT NULL DEFAULT '',
  url           TEXT,
  tag           TEXT NOT NULL DEFAULT '',
  framework     TEXT NOT NULL DEFAULT '',
  fw_version    TEXT NOT NULL DEFAULT '',
  engine_version TEXT,
  suite         TEXT,
  thinking      INTEGER,
  conc          INTEGER,
  bank_id       TEXT,
  started_utc   TEXT NOT NULL DEFAULT '',
  finished_utc  TEXT,
  heartbeat_ts  REAL,
  error         TEXT,
  acc REAL, correct INTEGER, n INTEGER, ci_lo REAL, ci_hi REAL,
  in_tokens INTEGER, out_tokens INTEGER,
  source_file   TEXT, source_sha256 TEXT, imported_utc TEXT,
  meta_json     TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_runs_kind_started ON runs(kind, started_utc);
CREATE INDEX IF NOT EXISTS ix_runs_model_fw ON runs(model, framework, fw_version);
CREATE INDEX IF NOT EXISTS ix_runs_status ON runs(status);

CREATE TABLE IF NOT EXISTS perf_phases (
  run_id    TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  seq       INTEGER NOT NULL,
  phase_id  TEXT,
  data_json TEXT NOT NULL,
  PRIMARY KEY (run_id, seq)
);

CREATE TABLE IF NOT EXISTS perf_metrics (
  run_id       TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
  samples_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS iq_subjects (
  run_id  TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  seq     INTEGER NOT NULL,
  sid     TEXT, name TEXT, type TEXT,
  n INTEGER, correct INTEGER, acc REAL, ci_lo REAL, ci_hi REAL,
  in_tokens INTEGER, out_tokens INTEGER,
  data_json TEXT NOT NULL,
  PRIMARY KEY (run_id, seq)
);

CREATE TABLE IF NOT EXISTS iq_items (
  run_id     TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  seq        INTEGER NOT NULL,
  sid        TEXT,
  idx        INTEGER,
  ok         INTEGER NOT NULL DEFAULT 0,
  in_tokens  INTEGER,
  out_tokens INTEGER,
  err        TEXT,
  extra_json TEXT,
  PRIMARY KEY (run_id, seq)
);
CREATE INDEX IF NOT EXISTS ix_iq_items_sid ON iq_items(run_id, sid, idx);

CREATE TABLE IF NOT EXISTS gen_items (
  run_id    TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  seq       INTEGER NOT NULL,
  task_id   TEXT,
  name      TEXT,
  file      TEXT,
  error     TEXT,
  pass INTEGER, total INTEGER,
  stars     INTEGER,
  rated_utc TEXT,
  data_json TEXT NOT NULL,
  PRIMARY KEY (run_id, seq)
);
CREATE INDEX IF NOT EXISTS ix_gen_items_task ON gen_items(run_id, task_id);

CREATE TABLE IF NOT EXISTS deleted_runs (
  run_id      TEXT PRIMARY KEY,
  kind        TEXT,
  deleted_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS endpoints (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  url           TEXT NOT NULL,
  api_key       TEXT,
  model         TEXT,
  created_utc   TEXT,
  last_used_utc TEXT
);
"""


# ---------------------------------------------------------------- 连接

def connect(db_path=None):
    """短连接: autocommit + 显式事务; 调用方负责 close (或用 with closing)。"""
    db_path = db_path or default_db()
    if db_path not in _inited:
        init(db_path)
    return _raw_connect(db_path)


def _raw_connect(db_path):
    conn = sqlite3.connect(db_path, timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init(db_path=None):
    db_path = db_path or default_db()
    d = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(d, exist_ok=True)
    conn = _raw_connect(db_path)
    try:
        if os.environ.get("LLM_BENCH_DB_JOURNAL", "WAL").upper() == "WAL":
            conn.execute("PRAGMA journal_mode=WAL")
        with _write_lock:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for stmt in DDL.split(";"):
                    if stmt.strip():
                        conn.execute(stmt)
                ver = conn.execute("PRAGMA user_version").fetchone()[0]
                if ver < SCHEMA_VERSION:
                    conn.execute("PRAGMA user_version=%d" % SCHEMA_VERSION)
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
    finally:
        conn.close()
    _inited.add(db_path)


@contextlib.contextmanager
def write_tx(conn):
    """进程内写锁 + BEGIN IMMEDIATE: 开事务即取写锁, 使 busy_timeout 生效。"""
    with _write_lock:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")


@contextlib.contextmanager
def session(db_path=None):
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------- 文档 -> 行

def doc_kind(doc):
    k = doc.get("kind")
    if k in ("iq", "gen"):
        return k
    if "phases" in doc or str(doc.get("run_id", "")).startswith("run_"):
        return "perf"
    return None


def _dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _infer_status(doc, kind):
    """旧 JSON 无 status 时推断; running 的 JSON 无心跳, 一律视为中断。"""
    st = doc.get("status")
    if st and st != "running":
        return st
    if kind == "perf":
        return "done" if doc.get("phases") and doc.get("finished_utc") else "interrupted"
    if kind == "iq":
        return "done" if doc.get("overall") else "interrupted"
    return "done" if doc.get("finished_utc") else "interrupted"


def _header(doc, kind, status):
    fw = doc.get("framework") or {}
    ov = doc.get("overall") or {}
    meta = {k: v for k, v in doc.items() if k not in _CHILD_KEYS}
    thinking = doc.get("thinking")
    return {
        "run_id": doc["run_id"], "kind": kind, "status": status,
        "model": doc.get("model") or "", "url": doc.get("url"), "tag": doc.get("tag") or "",
        "framework": fw.get("name") or "", "fw_version": fw.get("version") or "",
        "engine_version": doc.get("bench_version") or doc.get("iq_version") or doc.get("gen_version"),
        "suite": doc.get("suite"), "thinking": None if thinking is None else int(bool(thinking)),
        "conc": doc.get("conc"), "bank_id": doc.get("bank_id"),
        "started_utc": doc.get("started_utc") or "", "finished_utc": doc.get("finished_utc"),
        "error": doc.get("error"),
        "acc": ov.get("acc"), "correct": ov.get("correct"), "n": ov.get("n"),
        "ci_lo": ov.get("ci_lo"), "ci_hi": ov.get("ci_hi"),
        "in_tokens": ov.get("in_tokens"), "out_tokens": ov.get("out_tokens"),
        "meta_json": _dumps(meta),
    }


def upsert_header(conn, doc, status=None, heartbeat=True, source=None):
    """INSERT OR IGNORE + UPDATE (老 SQLite 无 UPSERT)。stale 标记的 status 由调用方决定是否覆盖。"""
    kind = doc_kind(doc)
    if kind is None:
        raise ValueError("无法识别运行类型: %s" % doc.get("run_id"))
    h = _header(doc, kind, status or doc.get("status") or "running")
    if heartbeat:
        h["heartbeat_ts"] = time.time()
    if source:
        h.update(source)
    cols = list(h)
    conn.execute("INSERT OR IGNORE INTO runs (%s) VALUES (%s)" % (",".join(cols), ",".join("?" * len(cols))),
                 [h[c] for c in cols])
    sets = [c for c in cols if c != "run_id"]
    conn.execute("UPDATE runs SET %s WHERE run_id=?" % ",".join("%s=?" % c for c in sets),
                 [h[c] for c in sets] + [h["run_id"]])
    return kind


def insert_children(conn, doc, kind, cursor):
    """从 cursor(各子集合已写条数) 起追加新增子行, 返回新 cursor。子行写入后不再改动(除 stars)。"""
    rid = doc["run_id"]
    cur = dict(cursor)
    if kind == "perf":
        phases = doc.get("phases") or []
        for seq in range(cur.get("phases", 0), len(phases)):
            p = phases[seq]
            conn.execute("INSERT OR IGNORE INTO perf_phases (run_id,seq,phase_id,data_json) VALUES (?,?,?,?)",
                         (rid, seq, p.get("id"), _dumps(p)))
        cur["phases"] = len(phases)
        if "metrics_samples" in doc:
            conn.execute("INSERT OR REPLACE INTO perf_metrics (run_id,samples_json) VALUES (?,?)",
                         (rid, _dumps(doc["metrics_samples"])))
    elif kind == "iq":
        subs = doc.get("subjects") or []
        for seq in range(cur.get("subjects", 0), len(subs)):
            s = subs[seq]
            conn.execute("INSERT OR IGNORE INTO iq_subjects (run_id,seq,sid,name,type,n,correct,acc,ci_lo,ci_hi,"
                         "in_tokens,out_tokens,data_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (rid, seq, s.get("id"), s.get("name"), s.get("type"), s.get("n"), s.get("correct"),
                          s.get("acc"), s.get("ci_lo"), s.get("ci_hi"), s.get("in_tokens"), s.get("out_tokens"),
                          _dumps(s)))
        cur["subjects"] = len(subs)
        items = doc.get("items") or []
        rows = []
        for seq in range(cur.get("items", 0), len(items)):
            it = items[seq]
            rows.append((rid, seq, it.get("sid"), it.get("idx"), int(bool(it.get("ok"))),
                         it.get("in"), it.get("out"), it.get("err"),
                         None if _is_std_iq_item(it) else _dumps(it)))  # 非标准形态整条留存, 保证往返等价
        conn.executemany("INSERT OR IGNORE INTO iq_items (run_id,seq,sid,idx,ok,in_tokens,out_tokens,err,extra_json)"
                         " VALUES (?,?,?,?,?,?,?,?,?)", rows)
        cur["items"] = len(items)
    elif kind == "gen":
        items = doc.get("items") or []
        for seq in range(cur.get("items", 0), len(items)):
            it = items[seq]
            data = {k: v for k, v in it.items() if k != "stars"}
            data["__has_stars"] = "stars" in it
            conn.execute("INSERT OR IGNORE INTO gen_items (run_id,seq,task_id,name,file,error,pass,total,stars,data_json)"
                         " VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (rid, seq, it.get("id"), it.get("name"), it.get("file"), it.get("error"),
                          it.get("pass"), it.get("total"), it.get("stars"), _dumps(data)))
        cur["items"] = len(items)
    return cur


def _is_std_iq_item(it):
    """标准形态(可由列完整还原): 出错项 {sid,idx,ok=False,err}; 正常项 {sid,idx,ok,in,out}。"""
    if it.get("err") is not None:
        return set(it) == {"sid", "idx", "ok", "err"} and it["ok"] is False
    return set(it) == {"sid", "idx", "ok", "in", "out"} and isinstance(it["ok"], bool)


# ---------------------------------------------------------------- 行 -> 文档

def _row_status(row, now=None):
    st = row["status"]
    if st == "running":
        hb = row["heartbeat_ts"]
        if hb is None or (now or time.time()) - hb > STALE_S:
            return "interrupted"
    return st


def _rebuild_iq_item(r):
    if r["extra_json"]:
        return json.loads(r["extra_json"])
    it = {"sid": r["sid"], "idx": r["idx"], "ok": bool(r["ok"])}
    if r["err"] is not None:
        it["err"] = r["err"]
    else:
        it["in"], it["out"] = r["in_tokens"], r["out_tokens"]
    return it


def _rebuild_gen_item(r):
    data = json.loads(r["data_json"])
    has = data.pop("__has_stars", True)
    if has:
        data["stars"] = r["stars"]
    return data


def _rebuild(row, children, items=True):
    doc = json.loads(row["meta_json"])
    doc["status"] = _row_status(row)
    if row["error"] is not None and "error" not in doc:
        doc["error"] = row["error"]
    kind = row["kind"]
    ch = children.get(row["run_id"], {})
    if kind == "perf":
        doc["phases"] = ch.get("phases", [])
        if "metrics_samples" in ch:
            doc["metrics_samples"] = ch["metrics_samples"]
    elif kind == "iq":
        doc["subjects"] = ch.get("subjects", [])
        if items:
            doc["items"] = ch.get("items", [])
    else:
        doc["items"] = ch.get("items", [])
    return doc


def _load_children(conn, kind, where, params, items=True):
    """批量拉取子行并按 run_id 分组 (避免 N+1)。where 作用于 runs 表别名 r。"""
    out = {}
    sub = "SELECT run_id FROM runs r WHERE " + where

    def add(rid, key, val):
        out.setdefault(rid, {}).setdefault(key, []).append(val)

    if kind == "perf":
        for r in conn.execute("SELECT run_id,data_json FROM perf_phases WHERE run_id IN (%s) ORDER BY run_id,seq" % sub, params):
            add(r["run_id"], "phases", json.loads(r["data_json"]))
        for r in conn.execute("SELECT run_id,samples_json FROM perf_metrics WHERE run_id IN (%s)" % sub, params):
            out.setdefault(r["run_id"], {})["metrics_samples"] = json.loads(r["samples_json"])
    elif kind == "iq":
        for r in conn.execute("SELECT run_id,data_json FROM iq_subjects WHERE run_id IN (%s) ORDER BY run_id,seq" % sub, params):
            add(r["run_id"], "subjects", json.loads(r["data_json"]))
        if items:
            for r in conn.execute("SELECT * FROM iq_items WHERE run_id IN (%s) ORDER BY run_id,seq" % sub, params):
                add(r["run_id"], "items", _rebuild_iq_item(r))
    else:
        for r in conn.execute("SELECT run_id,data_json,stars FROM gen_items WHERE run_id IN (%s) ORDER BY run_id,seq" % sub, params):
            add(r["run_id"], "items", _rebuild_gen_item(r))
    return out


def list_runs(kind, items=True, db_path=None, summary=False):
    """与旧 /api/*-results 同构: 完整文档列表, started_utc 倒序。
    summary=True 时只返回顶层元数据(不含 phases/metrics_samples/subjects/items), 供列表与下拉框使用。"""
    with session(db_path) as conn:
        rows = conn.execute("SELECT * FROM runs WHERE kind=? ORDER BY started_utc DESC", (kind,)).fetchall()
        if summary:
            out = []
            for r in rows:
                doc = json.loads(r["meta_json"])
                doc["status"] = _row_status(r)
                if r["error"] is not None and "error" not in doc:
                    doc["error"] = r["error"]
                out.append(doc)
            return out
        children = _load_children(conn, kind, "r.kind=?", (kind,), items)
    return [_rebuild(r, children, items) for r in rows]


def rewrite_children(doc, db_path=None):
    """整体重写某次运行的子表行(子表只追加, 续跑前删除请求失败的条目后需要调用)。返回新的写入游标。"""
    kind = doc_kind(doc)
    with session(db_path) as conn, write_tx(conn):
        for table in ("perf_phases", "perf_metrics", "iq_subjects", "iq_items", "gen_items"):
            conn.execute("DELETE FROM %s WHERE run_id=?" % table, (doc["run_id"],))
        upsert_header(conn, doc)
        return insert_children(conn, doc, kind, {})


def delete_run(run_id, db_path=None):
    """删除运行(子表级联)并写入墓碑, 防止 results/ 中的同名 JSON 在启动时被重新导入。返回被删运行的 kind 或 None。"""
    with session(db_path) as conn, write_tx(conn):
        row = conn.execute("SELECT kind,status,heartbeat_ts FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            return None
        if _row_status(row) == "running":
            raise ValueError("运行尚未结束，请先停止后再删除")
        conn.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
        conn.execute("INSERT OR REPLACE INTO deleted_runs (run_id,kind,deleted_utc) VALUES (?,?,?)",
                     (run_id, row["kind"], time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
        return row["kind"]


def is_deleted(conn, run_id):
    return conn.execute("SELECT 1 FROM deleted_runs WHERE run_id=?", (run_id,)).fetchone() is not None


# ---------------------------------------------------------------- 模型端点配置 (含 API Key, 仅存本地库)

def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def list_endpoints(db_path=None):
    """保存的模型: 最近用过(一键填入)的在前, 没用过的按添加时间。"""
    with session(db_path) as conn:
        rows = conn.execute("SELECT * FROM endpoints ORDER BY COALESCE(last_used_utc, created_utc) DESC, created_utc DESC").fetchall()
        return [dict(r) for r in rows]


def get_endpoint(ep_id, db_path=None):
    with session(db_path) as conn:
        row = conn.execute("SELECT * FROM endpoints WHERE id=?", (ep_id,)).fetchone()
        return dict(row) if row else None


def save_endpoint(ep, db_path=None):
    """有 id 则整体覆盖(以最后一次保存为准), 无 id 则新建。返回完整字段; id 不存在时抛 KeyError。
    last_used_utc 只记「一键填入」的时间(touch_endpoint): 新建时为空, 编辑不改。"""
    ep = dict(ep)
    if not ep.get("url") or not str(ep["url"]).startswith(("http://", "https://")):
        raise ValueError("API 地址必须以 http:// 或 https:// 开头")
    if not ep.get("model"):
        raise ValueError("模型名称不能为空")
    if not ep.get("name"):
        host = str(ep["url"]).split("//", 1)[-1].split("/")[0]
        ep["name"] = "%s · %s" % (ep["model"], host)
    now = _now()
    with session(db_path) as conn, write_tx(conn):
        if ep.get("id"):
            row = conn.execute("SELECT id FROM endpoints WHERE id=?", (ep["id"],)).fetchone()
            if not row:
                raise KeyError("配置不存在或已被删除")
            conn.execute("UPDATE endpoints SET name=?,url=?,api_key=?,model=? WHERE id=?",
                         (ep["name"][:64], ep["url"], ep.get("api_key") or "", ep["model"][:128], ep["id"]))
        else:
            ep["id"] = "ep_%d_%s" % (int(time.time()), os.urandom(4).hex())
            conn.execute("INSERT INTO endpoints (id,name,url,api_key,model,created_utc,last_used_utc) VALUES (?,?,?,?,?,?,?)",
                         (ep["id"], ep["name"][:64], ep["url"], ep.get("api_key") or "", ep["model"][:128], now, None))
        row = conn.execute("SELECT * FROM endpoints WHERE id=?", (ep["id"],)).fetchone()
        return dict(row)


def touch_endpoint(ep_id, db_path=None):
    """记下「一键填入」的时间; 返回这个时间, id 不存在时返回 None。"""
    now = _now()
    with session(db_path) as conn, write_tx(conn):
        cur = conn.execute("UPDATE endpoints SET last_used_utc=? WHERE id=?", (now, ep_id))
        return now if cur.rowcount > 0 else None


def delete_endpoint(ep_id, db_path=None):
    with session(db_path) as conn, write_tx(conn):
        cur = conn.execute("DELETE FROM endpoints WHERE id=?", (ep_id,))
        return cur.rowcount > 0


def run_targets(db_path=None):
    """所有测试的 (run_id, 类型, 地址, 模型, 开始时间): 模型管理页按地址和模型统计「在测试里用过几次」。
    只查一次 runs 表, 分组在调用方(endpoints.usage)做, 不按模型逐个查。"""
    with session(db_path) as conn:
        return [tuple(r) for r in conn.execute("SELECT run_id, kind, url, model, started_utc FROM runs")]


def run_briefs(run_ids, db_path=None):
    """几次测试的摘要原料(模型管理页「最近用它跑过的测试」): 返回 {run_id: 行}, 行里有
    kind / status / 时间 / 标签 / 框架 / 正确率等列, 速度测试另带 phases=[(阶段 id, 数据或 None)]
    (只解析 concurrency / decode 两个阶段), 代码生成另带 items(作品条目) 和 planned(计划几题)。"""
    ids = list(dict.fromkeys(run_ids))
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    out = {}
    with session(db_path) as conn:
        for r in conn.execute("SELECT run_id, kind, status, heartbeat_ts, started_utc, finished_utc, tag, framework, fw_version, "
                              "suite, thinking, bank_id, acc, correct, n, error, meta_json FROM runs WHERE run_id IN (%s)" % marks, ids):
            d = {k: r[k] for k in ("run_id", "kind", "started_utc", "finished_utc", "tag", "framework", "fw_version",
                                   "suite", "bank_id", "acc", "correct", "n", "error")}
            d["status"] = _row_status(r)
            d["thinking"] = None if r["thinking"] is None else bool(r["thinking"])
            if r["kind"] == "perf":
                d["phases"] = []
            elif r["kind"] == "gen":
                try:
                    planned = json.loads(r["meta_json"]).get("planned")
                except (ValueError, AttributeError):
                    planned = None
                d.update(items=[], planned=planned)
            out[r["run_id"]] = d
        for r in conn.execute("SELECT run_id, phase_id, CASE WHEN phase_id IN ('concurrency','decode') THEN data_json END AS data_json "
                              "FROM perf_phases WHERE run_id IN (%s) ORDER BY run_id, seq" % marks, ids):
            if r["run_id"] in out and "phases" in out[r["run_id"]]:
                try:
                    data = json.loads(r["data_json"]) if r["data_json"] else None
                except ValueError:
                    data = None
                out[r["run_id"]]["phases"].append((r["phase_id"], data))
        for r in conn.execute("SELECT run_id, data_json FROM gen_items WHERE run_id IN (%s) ORDER BY run_id, seq" % marks, ids):
            if r["run_id"] in out and "items" in out[r["run_id"]]:
                try:
                    out[r["run_id"]]["items"].append(json.loads(r["data_json"]))
                except ValueError:
                    pass
    return out


def get_run(run_id, items=True, db_path=None, conn=None):
    own = conn is None
    conn = conn or connect(db_path)
    try:
        row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            return None
        children = _load_children(conn, row["kind"], "r.run_id=?", (run_id,), items)
        return _rebuild(row, children, items)
    finally:
        if own:
            conn.close()


def task_set_uses(db_path=None):
    """速度测试用过的任务集: {任务集 id: [{run_id, model, tag, framework, fw_version, started_utc, status, name}]},
    每个 id 下新的在前。只看「自定义任务集」阶段(phase_id = scn_custom)里记了 task_set 的行: SQL 先按阶段和
    LIKE 筛, 只解析筛出来的几行, 不把整张表反序列化。3.6.0 之前的测试没有这条记录, 不计入。"""
    out = {}
    with session(db_path) as conn:
        rows = conn.execute(
            "SELECT p.run_id, p.data_json, r.model, r.tag, r.framework, r.fw_version, r.started_utc, r.status, r.heartbeat_ts "
            "FROM perf_phases p JOIN runs r ON r.run_id = p.run_id "
            "WHERE p.phase_id = 'scn_custom' AND p.data_json LIKE '%\"task_set\"%' "
            "ORDER BY r.started_utc DESC, p.run_id DESC").fetchall()
    for r in rows:
        try:
            ts = (json.loads(r["data_json"]).get("task") or {}).get("task_set")
        except (ValueError, AttributeError):
            continue
        if not isinstance(ts, dict) or not isinstance(ts.get("id"), str):
            continue
        lst = out.setdefault(ts["id"], [])
        if any(x["run_id"] == r["run_id"] for x in lst):
            continue
        lst.append({"run_id": r["run_id"], "model": r["model"], "tag": r["tag"], "framework": r["framework"],
                    "fw_version": r["fw_version"], "started_utc": r["started_utc"], "status": _row_status(r),
                    "name": str(ts.get("name") or "")[:120]})
    return out


def get_iq_records(run_id, sid, idx, db_path=None):
    """某次能力评测某道题的作答记录(按写入顺序), 走 (run_id, sid, idx) 索引, 不加载整次运行。"""
    with session(db_path) as conn:
        rows = conn.execute("SELECT * FROM iq_items WHERE run_id=? AND sid=? AND idx=? ORDER BY seq",
                            (run_id, sid, idx)).fetchall()
    return [_rebuild_iq_item(r) for r in rows]


def rate_gen_item(run_id, task_id, stars, db_path=None):
    """单行 UPDATE, 与后台增量写入无竞态 (SqliteSink 从不写 stars)。返回是否命中。"""
    with session(db_path) as conn, write_tx(conn):
        cur = conn.execute("UPDATE gen_items SET stars=?, rated_utc=? WHERE run_id=? AND task_id=?",
                           (stars, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), run_id, task_id))
        return cur.rowcount > 0


def update_gen_item(run_id, item, db_path=None):
    """重新评测后就地更新作品条目 (不改 stars)。返回是否命中。"""
    data = {k: v for k, v in item.items() if k != "stars"}
    with session(db_path) as conn, write_tx(conn):
        row = conn.execute("SELECT data_json FROM gen_items WHERE run_id=? AND task_id=?", (run_id, item.get("id"))).fetchone()
        if not row:
            return False
        data["__has_stars"] = json.loads(row["data_json"]).get("__has_stars", True)
        cur = conn.execute("UPDATE gen_items SET name=?, file=?, error=?, pass=?, total=?, data_json=? WHERE run_id=? AND task_id=?",
                           (item.get("name"), item.get("file"), item.get("error"), item.get("pass"), item.get("total"),
                            _dumps(data), run_id, item.get("id")))
        return cur.rowcount > 0


def update_run_meta(run_id, patch, db_path=None):
    """合并更新运行的顶层元数据 (meta_json), 如评测口径。"""
    with session(db_path) as conn, write_tx(conn):
        row = conn.execute("SELECT meta_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            return False
        meta = json.loads(row["meta_json"])
        meta.update(patch)
        conn.execute("UPDATE runs SET meta_json=? WHERE run_id=?", (_dumps(meta), run_id))
        return True


def heartbeat(run_id, db_path=None):
    with session(db_path) as conn, write_tx(conn):
        conn.execute("UPDATE runs SET heartbeat_ts=? WHERE run_id=? AND status='running'", (time.time(), run_id))


def mark_stale_runs(max_age_s=STALE_S, db_path=None):
    with session(db_path) as conn, write_tx(conn):
        cur = conn.execute("UPDATE runs SET status='interrupted' WHERE status='running' AND "
                           "(heartbeat_ts IS NULL OR heartbeat_ts < ?)", (time.time() - max_age_s,))
        return cur.rowcount


# ---------------------------------------------------------------- 导入 / 导出

def import_json_file(path, force=False, db_path=None, conn=None):
    """幂等导入单个结果 JSON。返回 inserted | skipped:<原因> | replaced | error:<原因>。"""
    try:
        with open(path, "rb") as f:
            raw = f.read()
        doc = json.loads(raw.decode("utf-8"))
    except Exception as e:
        return "error:%s: %s" % (type(e).__name__, str(e)[:100])
    if not isinstance(doc, dict):
        return "error:非对象 JSON"
    doc.setdefault("run_id", os.path.basename(path).rsplit(".", 1)[0])
    kind = doc_kind(doc)
    if kind is None:
        return "skipped:无法识别类型"
    sha = hashlib.sha256(raw).hexdigest()
    own = conn is None
    conn = conn or connect(db_path)
    try:
        with write_tx(conn):
            if is_deleted(conn, doc["run_id"]) and not force:
                return "skipped:已删除"
            old = conn.execute("SELECT source_file,source_sha256 FROM runs WHERE run_id=?", (doc["run_id"],)).fetchone()
            verdict = "inserted"
            if old:
                if old["source_file"] is None:
                    return "skipped:库内原生运行"
                if old["source_sha256"] == sha:
                    return "skipped:未变化"
                if not force:
                    return "skipped:内容不同(加 --force 覆盖)"
                conn.execute("DELETE FROM runs WHERE run_id=?", (doc["run_id"],))
                verdict = "replaced"
            source = {"source_file": os.path.abspath(path), "source_sha256": sha,
                      "imported_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            upsert_header(conn, doc, status=_infer_status(doc, kind), heartbeat=False, source=source)
            insert_children(conn, doc, kind, {})
        return verdict
    finally:
        if own:
            conn.close()


def import_dir(results_dir, force=False, only_new=False, db_path=None, log=None):
    """导入目录下全部 run_/iq_/gen_*.json。only_new=True 时仅导入库中不存在的 run_id(启动自动导入用)。"""
    summary = {"inserted": 0, "replaced": 0, "skipped": 0, "errors": []}
    if not os.path.isdir(results_dir):
        return summary
    with session(db_path) as conn:
        known = {r[0] for r in conn.execute("SELECT run_id FROM runs")} if only_new else set()
        for fn in sorted(os.listdir(results_dir)):
            if not fn.endswith(".json") or not fn.startswith(("run_", "iq_", "gen_")):
                continue
            if only_new and fn[:-5] in known:
                continue
            v = import_json_file(os.path.join(results_dir, fn), force=force, conn=conn)
            if v.startswith("error:"):
                summary["errors"].append("%s: %s" % (fn, v[6:]))
            else:
                key = v.split(":", 1)[0]
                summary[key] = summary.get(key, 0) + 1
            if log:
                log("  %s -> %s" % (fn, v))
    return summary


def export_run(run_id, out_dir, db_path=None):
    doc = get_run(run_id, db_path=db_path)
    if doc is None:
        raise KeyError("run 不存在: " + run_id)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, run_id + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return path


def export_all(out_dir, kind=None, db_path=None):
    with session(db_path) as conn:
        if kind:
            ids = [r[0] for r in conn.execute("SELECT run_id FROM runs WHERE kind=?", (kind,))]
        else:
            ids = [r[0] for r in conn.execute("SELECT run_id FROM runs")]
    return [export_run(i, out_dir, db_path) for i in ids]


def check_roundtrip(results_dir, db_path=None):
    """校验库中文档与原 JSON 等价(忽略 status)。返回不一致的 run_id 列表。"""
    bad = []
    for fn in sorted(os.listdir(results_dir)):
        if not fn.endswith(".json") or not fn.startswith(("run_", "iq_", "gen_")):
            continue
        try:
            with open(os.path.join(results_dir, fn), encoding="utf-8") as f:
                src = json.load(f)
        except Exception:
            continue
        got = get_run(src.get("run_id") or fn[:-5], db_path=db_path)
        if got is None:
            bad.append(fn + " (缺失)")
            continue
        src.pop("status", None)
        got.pop("status", None)
        if src.get("error") is None:
            src.pop("error", None)
            if got.get("error") is None:
                got.pop("error", None)
        if src != got:
            bad.append(fn)
    return bad


def main(argv=None):
    ap = argparse.ArgumentParser(description="llm-bench-pro SQLite 结果库")
    ap.add_argument("--db", default=None, help="库路径 (默认 data/llm_bench.db 或 $LLM_BENCH_DB)")
    sp = ap.add_subparsers(dest="cmd")
    sp.add_parser("init", help="建库建表")
    p = sp.add_parser("import", help="导入 data/results/*.json (幂等)")
    p.add_argument("--results", default=os.path.join(ROOT, "data", "results"))
    p.add_argument("--force", action="store_true", help="内容变化的已导入运行删除后重导")
    p = sp.add_parser("export", help="导出为 JSON")
    p.add_argument("--out", default=os.path.join(ROOT, "data", "export"))
    p.add_argument("--kind", choices=KINDS, default=None)
    p.add_argument("--run", default=None)
    sp.add_parser("stale", help="把心跳超时的 running 运行标记为 interrupted")
    p = sp.add_parser("check", help="校验库与 data/results/*.json 往返等价")
    p.add_argument("--results", default=os.path.join(ROOT, "data", "results"))
    args = ap.parse_args(argv)
    db = args.db or default_db()
    if args.cmd == "init":
        init(db)
        print("ok:", db)
    elif args.cmd == "import":
        s = import_dir(args.results, force=args.force, db_path=db, log=print)
        print("导入完成:", json.dumps(s, ensure_ascii=False))
        return 1 if s["errors"] else 0
    elif args.cmd == "export":
        paths = [export_run(args.run, args.out, db)] if args.run else export_all(args.out, args.kind, db)
        print("导出 %d 个 => %s" % (len(paths), args.out))
    elif args.cmd == "stale":
        print("标记中断:", mark_stale_runs(db_path=db))
    elif args.cmd == "check":
        bad = check_roundtrip(args.results, db)
        print("往返一致" if not bad else "不一致: %s" % bad)
        return 1 if bad else 0
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
