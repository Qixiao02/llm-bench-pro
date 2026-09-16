#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sinks.py — 运行结果落地抽象。引擎每个检查点调用 sink.save(result) (result 为完整文档)。
  JsonFileSink  results/<run_id>.json 原子整写 (CLI 默认, 便于从生产机拷回)
  SqliteSink    增量写入 SQLite: 只追加新增子行, 从不改 stars; 运行期间后台心跳
  MultiSink     组合
"""
import json
import os
import threading

try:
    from . import store  # 包内导入
except ImportError:
    import store  # server.py 以包目录为 sys.path 顶层导入


class JsonFileSink:
    def __init__(self, outdir):
        self.outdir = outdir
        self.run_id = None

    @property
    def path(self):
        return os.path.join(self.outdir, "%s.json" % self.run_id)

    @property
    def location(self):
        return self.path

    def save(self, result):
        self.run_id = result["run_id"]
        os.makedirs(self.outdir, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)  # 原子替换: 崩溃不留半截文件


class SqliteSink:
    HEARTBEAT_S = 30

    def __init__(self, db_path=None):
        self.db_path = db_path or store.default_db()
        self.run_id = None
        self._cursor = {}
        self._hb_stop = None

    @property
    def location(self):
        return "sqlite:%s#%s" % (self.db_path, self.run_id)

    def save(self, result):
        self.run_id = result["run_id"]
        with store.session(self.db_path) as conn, store.write_tx(conn):
            kind = store.upsert_header(conn, result)
            self._cursor = store.insert_children(conn, result, kind, self._cursor)
        running = (result.get("status") or "running") == "running"
        if running and self._hb_stop is None:
            self._start_heartbeat()
        elif not running and self._hb_stop is not None:
            self._hb_stop.set()

    def reset(self, result):
        """续跑前整体重写子表(已删除请求失败的条目), 并同步写入游标。"""
        self.run_id = result["run_id"]
        self._cursor = store.rewrite_children(result, self.db_path)

    def _start_heartbeat(self):
        """独立心跳: 单个 phase 可能持续十几分钟; 调用线程退出(未正常收尾)时自动停止, 交由 stale 判定。"""
        self._hb_stop = stop = threading.Event()
        owner, run_id, db = threading.current_thread(), self.run_id, self.db_path

        def loop():
            while not stop.wait(self.HEARTBEAT_S) and owner.is_alive():
                try:
                    store.heartbeat(run_id, db)
                except Exception:
                    pass

        threading.Thread(target=loop, name="hb-" + run_id, daemon=True).start()


class MultiSink:
    def __init__(self, *sinks):
        self.sinks = sinks

    @property
    def run_id(self):
        return self.sinks[0].run_id

    @property
    def location(self):
        return " + ".join(s.location for s in self.sinks)

    def save(self, result):
        for s in self.sinks:
            s.save(result)


def from_cli(kind, outdir, db_path=None):
    """CLI --sink json|db|both。"""
    json_sink = JsonFileSink(outdir)
    if kind == "json":
        return json_sink
    if kind == "db":
        return SqliteSink(db_path)
    return MultiSink(json_sink, SqliteSink(db_path))
