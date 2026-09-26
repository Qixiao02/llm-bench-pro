# -*- coding: utf-8 -*-
import json
import os
import time
import unittest

from _util import load_json, temp_dir
import sinks
import store


def perf_doc(run_id="run_20260101_000000_m"):
    return {"bench_version": "1.1.0", "run_id": run_id, "tag": "t", "suite": "quick",
            "started_utc": "2026-01-01T00:00:00+00:00", "url": "http://x/v1/chat/completions", "model": "m",
            "env": {"gateway": "g"}, "phases": [{"id": "prefill", "points": [{"label": "1K", "prefill_tps_med": 100}]}],
            "overrides": {"fixed_output": True}, "framework": {"name": "vLLM", "version": "1"},
            "metrics_samples": [{"t": 1, "gpu_cache_usage": 0.5}], "status": "done", "finished_utc": "2026-01-01T00:01:00+00:00"}


def iq_doc(run_id="iq_20260101_000000_m"):
    return {"kind": "iq", "iq_version": "1.3.0", "run_id": run_id, "model": "m", "bank_id": "b", "thinking": True,
            "sampling": {"temperature": 0.6}, "started_utc": "2026-01-01T00:00:00+00:00", "status": "done",
            "subjects": [{"id": "s", "name": "S", "type": "mcq", "n": 2, "correct": 1, "acc": 50.0, "ci_lo": 1, "ci_hi": 99,
                          "in_tokens": 1, "out_tokens": 2, "truncated": 1, "errors": 0}],
            "items": [{"sid": "s", "idx": 0, "ok": True, "in": 1, "out": 1, "finish": "stop", "pred": "B"},
                      {"sid": "s", "idx": 1, "ok": False, "in": 0, "out": 1, "finish": "length", "trunc": True, "tail": "…"},
                      {"sid": "s", "idx": 2, "ok": False, "err": "timeout"}],
            "overall": {"acc": 50.0, "n": 2, "correct": 1, "macro_acc": 50.0}}


def gen_doc(run_id="gen_20260101_000000_m"):
    return {"kind": "gen", "gen_version": "2.0.0", "run_id": run_id, "model": "m", "started_utc": "2026-01-01T00:00:00+00:00",
            "status": "done", "items": [{"id": "snake", "name": "贪吃蛇", "pass": 3, "total": 4, "stars": None,
                                         "eval": {"checks": [{"id": "load", "pass": True}]}}]}


class TestStore(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(temp_dir(), "s.db")

    def test_sink_roundtrip_all_kinds(self):
        for doc in (perf_doc(), iq_doc(), gen_doc()):
            with self.subTest(kind=store.doc_kind(doc)):
                sink = sinks.SqliteSink(self.db)
                sink.save(doc)
                got = store.get_run(doc["run_id"], db_path=self.db)
                self.assertEqual(got, doc)

    def test_scenario_phases_roundtrip(self):
        """任务场景 phase(scn_* 任意模板 id) 与顶层 replay 元数据按 phase_id 自由透传, 无需改表。"""
        doc = perf_doc()
        doc["replay"] = {"file": "x.jsonl", "pool_size": 5, "skipped": 1, "bad": 0, "wrapped": True}
        doc["phases"] += [
            {"id": "scn_json", "task": {"tpl": "json", "label": "结构化抽取", "validator": "json", "max_tokens": 256},
             "points": [{"conc": 4, "total": 12, "ok": 12, "fail": 0,
                         "req_s": 1.8, "json_total": 12, "json_ok": 11, "json_rate": 0.917, "attempts": 2,
                         "failed_attempts": [{"attempt": 1, "ok": 10, "fail": 2, "errors": ["x"]}]}]},
            {"id": "scn_vision", "task": {"tpl": "vision", "label": "图片理解", "validator": None,
                                          "images": 6, "images_per_request": 2},
             "points": [{"conc": 2, "total": 6, "ok": 6, "fail": 0, "req_s": 0.8, "out_tokens_avg": 260.0}]},
            {"id": "scn_rag", "task": {"tpl": "rag", "label": "RAG 问答", "validator": None, "rag_ctx": [4000, 16000]},
             "points": [{"conc": 4, "ctx_tokens": 16000, "total": 12, "ok": 11, "fail": 1, "req_s": 0.9}]},
            {"id": "replay", "pool": {"size": 5, "skipped": 1, "bad": 0, "wrapped": True},
             "points": [{"conc": 8, "total": 16, "ok": 15, "fail": 1, "max_inflight": 8, "pool_wrapped": False}]},
            {"id": "openloop", "duration_s": 60, "points": [{"rate": 2.0, "duration_s": 60, "sent": 121, "shed": 3,
                          "total": 118, "ok": 115, "fail": 3, "completed_rps": 1.7, "max_inflight": 24,
                          "inflight_ts": [[0.5, 0], [1.5, 4], [2.5, 9]]}]},
        ]
        sinks.SqliteSink(self.db).save(doc)
        self.assertEqual(store.get_run(doc["run_id"], db_path=self.db), doc)

    def test_incremental_items_and_stars_preserved(self):
        doc = gen_doc()
        doc["status"] = "running"
        items = doc["items"]
        doc["items"] = []
        sink = sinks.SqliteSink(self.db)
        sink.save(doc)
        doc["items"] = items
        sink.save(doc)
        self.assertTrue(store.rate_gen_item(doc["run_id"], "snake", 4, db_path=self.db))
        doc["status"] = "done"
        sink.save(doc)  # 后续增量写不能覆盖人工评分
        self.assertEqual(store.get_run(doc["run_id"], db_path=self.db)["items"][0]["stars"], 4)

    def test_summary_list_excludes_children(self):
        sinks.SqliteSink(self.db).save(perf_doc())
        rows = store.list_runs("perf", db_path=self.db, summary=True)
        self.assertEqual(len(rows), 1)
        self.assertNotIn("phases", rows[0])
        self.assertNotIn("metrics_samples", rows[0])
        self.assertEqual(rows[0]["model"], "m")

    def test_delete_tombstone_blocks_reimport(self):
        results = temp_dir()
        doc = iq_doc()
        with open(os.path.join(results, doc["run_id"] + ".json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        self.assertEqual(store.import_dir(results, db_path=self.db)["inserted"], 1)
        self.assertEqual(store.import_dir(results, db_path=self.db)["inserted"], 0)  # 幂等
        self.assertEqual(store.delete_run(doc["run_id"], db_path=self.db), "iq")
        self.assertIsNone(store.get_run(doc["run_id"], db_path=self.db))
        summary = store.import_dir(results, only_new=True, db_path=self.db)
        self.assertEqual(summary["inserted"], 0)
        self.assertIsNone(store.get_run(doc["run_id"], db_path=self.db))

    def test_delete_refuses_running(self):
        doc = iq_doc()
        doc["status"] = "running"
        sinks.SqliteSink(self.db).save(doc)
        with self.assertRaises(ValueError):
            store.delete_run(doc["run_id"], db_path=self.db)

    def test_stale_running_marked_interrupted(self):
        doc = perf_doc()
        doc["status"] = "running"
        with store.session(self.db) as c, store.write_tx(c):
            store.upsert_header(c, doc)
            c.execute("UPDATE runs SET heartbeat_ts=? WHERE run_id=?", (time.time() - 3600, doc["run_id"]))
        self.assertEqual(store.get_run(doc["run_id"], db_path=self.db)["status"], "interrupted")
        self.assertEqual(store.mark_stale_runs(db_path=self.db), 1)

    def test_export_matches(self):
        sinks.SqliteSink(self.db).save(iq_doc())
        out = temp_dir()
        path = store.export_run(iq_doc()["run_id"], out, db_path=self.db)
        self.assertEqual(load_json(path), iq_doc())


if __name__ == "__main__":
    unittest.main()
