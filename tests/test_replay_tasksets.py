# -*- coding: utf-8 -*-
"""回放用的请求文件统一放进任务集: 回放配置认任务集 id 并记下 task_set、旧的回放文件启动时并进任务集、
旧接口 (replay-upload / replay-list) 还能用、任务集的「用过几次」把按任务集回放的测试也算上。
上传目录一律换成临时目录, 跑完不会在项目里留下 data/。"""
import hashlib
import json
import os
import unittest
import uuid

from _util import MockServer, load_json, temp_dir
import bench
import server
import sinks
import store
import tasksets
from test_bench_gen import sse
from test_store import perf_doc
from test_task_sets import TaskSetCase, fid_of, line


def sha12(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


class TestReplayUsesTaskSets(TaskSetCase):
    def setUp(self):
        TaskSetCase.setUp(self)
        self._replay_dir = server.REPLAY_DIR
        server.REPLAY_DIR = temp_dir()

    def tearDown(self):
        server.REPLAY_DIR = self._replay_dir
        TaskSetCase.tearDown(self)

    def test_parse_replay_accepts_a_task_set_id(self):
        content = "\n".join(line("问题 %d %s" % (i, uuid.uuid4().hex)) for i in range(3))
        d = self.upload(content, "线上导出.jsonl")
        cfg = server._parse_replay({"replay": {"file_id": d["file_id"], "closed": {"conc": "4,8"},
                                               "open": {"rates": "2,5", "duration_s": 30}}})
        self.assertEqual(cfg["file"], tasksets.file_path(server.SCN_TASKS_DIR, d["file_id"]))
        self.assertEqual(cfg["task_set"], {"id": d["file_id"], "name": "线上导出"})
        self.assertEqual((cfg["closed"], cfg["open"]), ({"conc": [4, 8], "requests_per_worker": 4}, {"rates": [2.0, 5.0], "duration_s": 30}))
        for bad, why in (("scn-deadbeefcafe", "任务集不存在"), ("scn-xyz", "非法"), ("../etc/passwd", "非法"), ("replay-000000000000", "回放文件不存在")):
            with self.subTest(file_id=bad):
                with self.assertRaises(ValueError) as cm:
                    server._parse_replay({"replay": {"file_id": bad, "closed": {"conc": [1]}}})
                self.assertIn(why, str(cm.exception))
        with self.assertRaises(ValueError) as cm:                                       # 没给文件
            server._parse_replay({"replay": {"closed": {"conc": [1]}}})
        self.assertIn("任务集", str(cm.exception))

    def test_legacy_replay_file_id_still_accepted(self):
        content = line("旧文件 %s" % uuid.uuid4().hex)
        fid = "replay-" + sha12(content)
        with open(os.path.join(server.REPLAY_DIR, fid + ".jsonl"), "w", encoding="utf-8") as f:
            f.write(content)
        cfg = server._parse_replay({"replay": {"file_id": fid, "closed": {"conc": [1]}}})
        self.assertEqual(cfg["file"], os.path.join(server.REPLAY_DIR, fid + ".jsonl"))
        self.assertNotIn("task_set", cfg)

    def test_replay_upload_and_list_are_the_task_set_api(self):
        content = line("旧接口 %s" % uuid.uuid4().hex)
        st, _, d = self.request("POST", "/api/replay-upload", {"name": "旧接口.jsonl", "content": content})
        self.assertEqual((st, d["ok"], d["file_id"], d["name"]), (200, True, fid_of(content), "旧接口"))
        self.assertIn(d["file_id"], self.sets()[0])                                    # 任务集页面里看得到
        st, _, lst = self.request("GET", "/api/replay-list")
        self.assertEqual([(f["file_id"], f["name"]) for f in lst["files"]], [(d["file_id"], "旧接口")])
        st, _, e = self.request("POST", "/api/replay-upload", {"name": "x", "content": "根本不是 JSONL"})
        self.assertEqual((st, e["ok"]), (400, False))

    def test_migrate_replay_files_into_task_sets(self):
        a, b = line("旧回放 a %s" % uuid.uuid4().hex), line("旧回放 b %s" % uuid.uuid4().hex)
        for content in (a, b):
            with open(os.path.join(server.REPLAY_DIR, "replay-%s.jsonl" % sha12(content)), "w", encoding="utf-8") as f:
                f.write(content)
        with open(os.path.join(server.REPLAY_DIR, "notes.txt"), "w") as f:                # 不是回放文件: 不动
            f.write("x")
        self.upload(b, "已经导入过的.jsonl")                                                # b 已经是任务集: 只删旧文件, 名称不改
        notes = server.migrate_replay_files()
        self.assertEqual(notes, [("2 个回放文件已并入任务集（在「任务集」页面里看）", False)])
        self.assertEqual(sorted(os.listdir(server.REPLAY_DIR)), ["notes.txt"])
        sets, _ = self.sets()
        self.assertEqual(sets[fid_of(a)]["name"], "回放文件 " + sha12(a))
        self.assertEqual(sets[fid_of(b)]["name"], "已经导入过的")
        with open(tasksets.file_path(server.SCN_TASKS_DIR, fid_of(a)), encoding="utf-8") as f:
            self.assertEqual(f.read(), a)                                                # 内容一个字都没变
        self.assertEqual(server.migrate_replay_files(), [])                              # 再跑一遍什么都不做


class TestReplayRunsAreCountedAsTaskSetUses(TaskSetCase):
    def test_suite_records_the_task_set_in_replay_phases(self):
        content = "\n".join(line("回放 %d %s" % (i, uuid.uuid4().hex)) for i in range(4))
        d = self.upload(content, "线上导出.jsonl")
        cfg = server._parse_replay({"replay": {"file_id": d["file_id"], "closed": {"conc": [1], "requests_per_worker": 1},
                                               "open": {"rates": [5], "duration_s": 5}}})
        cfg["open"]["duration_s"] = 1                                                    # 页面上最少 5 秒, 测试里缩短
        bench._CANCEL, bench._REQ_EXTRA = None, {}
        m = MockServer(lambda *a: (200, sse(), "text/event-stream"))
        try:
            loc = bench.run_suite(m.url + "/v1/chat/completions", "m", suite="quick", outdir=temp_dir(), conc_ladder=[1],
                                  matrix_conc=1, lens=[1], warmup_shapes=False, retry_pause_s=0, replay=cfg)
        finally:
            m.close()
        doc = load_json(loc)
        ts = {"id": d["file_id"], "name": "线上导出"}
        self.assertEqual(doc["replay"]["task_set"], ts)
        by_id = {p["id"]: p for p in doc["phases"]}
        self.assertEqual((by_id["replay"]["task_set"], by_id["openloop"]["task_set"]), (ts, ts))

    def test_uses_count_replay_and_custom_once_per_run(self):
        d = self.upload(line("用过 %s" % uuid.uuid4().hex), "压测用.jsonl")
        fid = d["file_id"]
        tag = uuid.uuid4().hex[:8]

        def run(rid, when, phases):
            doc = perf_doc("run_%s_%s" % (when, tag + rid))
            doc["started_utc"] = "2026-04-0%sT00:00:00+00:00" % when[-1]
            doc["phases"].extend(phases)
            sinks.SqliteSink().save(doc)
            return doc["run_id"]
        ts = {"id": fid, "name": "压测用"}
        pts = [{"conc": 1, "total": 1, "ok": 1, "fail": 0}]
        r1 = run("a", "20260401", [{"id": "replay", "task_set": ts, "points": pts}])                           # 只按任务集闭环回放
        r2 = run("b", "20260402", [{"id": "openloop", "task_set": ts, "points": [{"rate": 1, "sent": 1}]}])    # 只开环
        r3 = run("c", "20260403", [{"id": "replay", "task_set": ts, "points": pts},
                                   {"id": "openloop", "task_set": ts, "points": [{"rate": 1, "sent": 1}]},
                                   {"id": "scn_custom", "task": {"tpl": "custom", "task_set": ts}, "points": pts}])  # 三个阶段同一个任务集: 只算一次
        run("d", "20260404", [{"id": "replay", "points": pts}])                                                 # 旧的回放 (没有记录): 不算
        run("e", "20260405", [{"id": "replay", "task_set": "不是记录", "points": pts}])                          # LIKE 筛进来但不是记录: 不算
        uses = store.task_set_uses()
        self.assertEqual([u["run_id"] for u in uses[fid]], [r3, r2, r1])
        self.assertEqual(self.sets()[0][fid]["uses"], 3)


if __name__ == "__main__":
    unittest.main()
