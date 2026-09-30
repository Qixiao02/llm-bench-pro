# -*- coding: utf-8 -*-
"""翻译第二阶段 (服务端接口和任务集): server.py、tasksets.py 的中文 / 英文消息测试。约定见 CONTRIBUTING.md「服务端消息与翻译」。

每条消息中文和英文各断言一次: 中文和转换前逐字一致, 英文和词典里的写法一致且没有汉字。覆盖:
  1. 转换完成: 两个文件违规数为 0, 基线为 0, 允许清单里只有旧数据的标记
  2. 各接口的错误提示: run_id / 测试不存在, 导出离线报告, 启动速度测试的参数检查, 场景和回放配置,
     上传任务集 / 图片包 / 回放文件, 能力评测续跑, 代码生成, 打星
  3. 带数量的句子 (tn): 测试不存在 (1 个 / 多个), 这一行没有第 N 张图 (0 / 1 / 多张)
  4. 存进结果和任务日志里的文字: 题集更新的标题和日志, 强制启动时记进结果的 notes
  5. 旧版报告接口 /api/report 的语言: ?lang= 优先于请求头 X-Lang
  6. 中英文的缓存互不串: 任务集逐行索引 (tasksets.scan)、图片包检查 (server._image_pack_check)
  7. 直接调用的函数: server 里的检查函数, tasksets 里的名称 / 图片 / 长文字函数
  8. 旧数据里的中文标记 (「（无正文」) 仍能识别

被测消息里来自别的模块的说明 (bench.check_task_line 的原因、vision_assets 的图片检查说明、report.render 的报错等) 不在这里
断言, 用假的替身代替: 那些由各自的模块负责翻译和测试。
"""
import base64
import contextlib
import json
import os
import time
import unittest
from unittest import mock

from _util import temp_dir  # 先设 LLM_BENCH_LANG=zh, 再导入包内模块
import bankman
import bench
import i18n
import i18n_lint_py as lint
import iq
import report
import server
import sinks
import store
import tasksets
import vision_assets
import test_i18n_py as base
from test_i18n_py import assert_english, english_flow
from test_store import gen_doc, iq_doc, perf_doc

PERF, IQ_DONE, IQ_OLD, GEN = "run_i18nsrv_perf", "iq_i18nsrv_done", "iq_i18nsrv_old", "gen_i18nsrv_a"
BASE = "http://127.0.0.1:1"      # 连不上的地址: 这些用例都在启动前就被拒绝, 不会真的去连


def setUpModule():
    old = iq_doc(IQ_OLD)
    old.update(status="cancelled", iq_version="0.9.0")            # 旧版评测程序生成的、停止过的运行: 版本对不上, 不能续跑
    for doc in (perf_doc(PERF), iq_doc(IQ_DONE), old, gen_doc(GEN)):
        sinks.SqliteSink().save(doc)


def tearDownModule():
    i18n.set_lang(None)
    for rid in (PERF, IQ_DONE, IQ_OLD, GEN):
        store.delete_run(rid)                                     # 用完就删, 不留在共用的临时库里


def png_of(w, h):
    return vision_assets.encode_png(w, h, [b"\xff\xff\xff" * w for _ in range(h)])


def b64(raw):
    return base64.b64encode(raw).decode("ascii")


@contextlib.contextmanager
def running(kind, base_url=None, **kw):
    """把某类任务置为「运行中」 (不真的跑), 出来后恢复。"""
    job = server.JOBS[kind]
    assert job.try_start(base_url, "m", **kw)
    try:
        yield job
    finally:
        job.set(running=False, run_id=None, files=[])


class ServerCase(base.LangServerCase):
    """起一个本地服务; 任务集 / 图片包 / 回放文件的目录换成临时目录, 不碰 data/。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._saved_dirs = {n: getattr(server, n) for n in ("SCN_TASKS_DIR", "SCN_IMAGES_DIR", "REPLAY_DIR")}
        server.SCN_TASKS_DIR, server.SCN_IMAGES_DIR, server.REPLAY_DIR = temp_dir(), temp_dir(), temp_dir()

    @classmethod
    def tearDownClass(cls):
        for n, v in cls._saved_dirs.items():
            setattr(server, n, v)
        super().tearDownClass()

    def both(self, method, path, body, zh, en, status, key="error"):
        """同一个请求: 英文 (X-Lang: en) 返回 en 且没有汉字; 中文 (X-Lang: zh 和不带请求头) 与转换前逐字一致。"""
        st, d = self.request(method, path, body, lang="en")
        self.assertEqual((st, d.get(key)), (status, en), path)
        assert_english(self, d.get(key), what=path)
        self.assertEqual(self.error_of(method, path, body, lang="zh"), (status, zh), path)
        self.assertEqual(self.error_of(method, path, body), (status, zh), path)

    def wait_idle(self, kind, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            if not server.JOBS[kind].snapshot()["running"]:
                return server.JOBS[kind].snapshot()
            time.sleep(0.02)
        self.fail("任务 %s 没有在 %d 秒内结束" % (kind, timeout))


# ================================================================ 1. 转换完成

class TestConverted(unittest.TestCase):
    def test_both_files_are_fully_converted_and_baseline_is_zero(self):
        scan = lint.scan_all()
        bad, allowed, stale = lint.apply_allow(scan, lint.load_allow())
        cur, base_ = lint.counts(bad), lint.load_baseline()
        for fn in ("server.py", "tasksets.py"):
            with self.subTest(file=fn):
                self.assertEqual([(v.line, v.text) for v in bad[fn]], [])
                self.assertEqual((cur[fn], base_[fn]), (0, 0))
        self.assertEqual([e.raw for e in stale if e.file in ("server.py", "tasksets.py")], [])

    def test_allow_list_only_holds_the_legacy_data_markers(self):
        """server.py / tasksets.py 在允许清单里只登记「旧数据的标记」两处; 其他中文都走 t() / tn()。"""
        mine = [e for e in lint.load_allow() if e.file in ("server.py", "tasksets.py")]
        self.assertEqual(sorted((e.file, e.scope, e.frag) for e in mine),
                         [("server.py", "_answer_of", "（无正文"), ("server.py", "_rec_summary", "（无正文")])

    def test_dictionary_entries_of_both_modules_exist_and_are_clean(self):
        dicts, problems = lint.load_dicts()
        problems = problems + lint.check_dictionary(lint.scan_all(), dicts)
        self.assertEqual([p.text for p in problems if p.where.startswith(("server", "tasksets"))], [])
        merged = i18n.dictionary("en")               # 不管词条放在哪个文件里 (以后有的可能挪进 common.py), 合并后的词典里都要有
        for key in ("非法 run_id", "测试不存在: {ids}", "第 {n} 张", "更新题集", "名称不能为空", "这一行没有第 {no} 张图（一共 {n} 张）"):
            self.assertIn(key, merged)


# ================================================================ 2. 各接口的错误提示

class TestRunIdMessages(ServerCase):
    def test_get_endpoints(self):
        rows = [
            ("/api/iq-wrong?id=bad&sid=s", "非法 run_id", "Invalid run_id", 200),
            ("/api/iq-wrong?id=iq_nope&sid=s", "run 不存在", "The run does not exist", 200),
            ("/api/iq-items?id=bad", "非法 run_id", "Invalid run_id", 200),
            ("/api/iq-items?id=%s&cmp=bad" % IQ_DONE, "非法对比 run_id", "Invalid comparison run_id", 200),
            ("/api/iq-items?id=iq_nope", "run 不存在", "The run does not exist", 200),
            ("/api/iq-answer?ids=bad&sid=s&idx=0", "非法 run_id", "Invalid run_id", 200),
            ("/api/iq-answer?ids=%s&sid=s&idx=x" % IQ_DONE, "非法题号", "Invalid question number", 200),
            ("/api/iq-answer?ids=iq_nope&sid=s&idx=0", "run 不存在", "The run does not exist", 200),
            ("/api/iq-compare?a=bad&b=%s" % IQ_DONE, "非法 run_id", "Invalid run_id", 200),
            ("/api/iq-compare?a=%s&b=iq_nope" % IQ_DONE, "run 不存在", "The run does not exist", 200),
            ("/api/run?id=run_nope", "run 不存在", "The run does not exist", 404),
            ("/api/export?id=run_nope", "run 不存在", "The run does not exist", 404),
        ]
        for path, zh, en, status in rows:
            with self.subTest(path=path):
                self.both("GET", path, None, zh, en, status)

    def test_post_endpoints(self):
        rows = [
            ("/api/run-delete", {"run_id": "bad"}, "非法 run_id", "Invalid run_id", 400),
            ("/api/run-delete", {"run_id": 5}, "非法 run_id", "Invalid run_id", 400),
            ("/api/run-delete", {"run_id": "run_nope"}, "run 不存在", "The run does not exist", 404),
            ("/api/iq-resume", {"run_id": "bad"}, "非法 run_id", "Invalid run_id", 400),
            ("/api/iq-resume", {"run_id": "iq_nope"}, "run 不存在", "The run does not exist", 404),
            ("/api/iq-resume", {"run_id": IQ_DONE}, "只有已停止、中断、失败或含请求失败题目的运行可以续跑",
             "Only runs that were stopped, interrupted or failed, or that contain questions with failed requests, can be resumed", 409),
            ("/api/iq-resume", {"run_id": IQ_OLD},
             "该运行由评测程序 0.9.0 生成，当前为 %s，判分口径不同，不能续跑，请重新运行" % iq.IQ_VERSION,
             "This run was made with capability test version 0.9.0; the current version is %s. Scoring differs between "
             "versions, so it cannot be resumed. Run the test again instead." % iq.IQ_VERSION, 409),
            ("/api/gen-eval", {"run_id": "bad"}, "非法 run_id", "Invalid run_id", 400),
            ("/api/gen-eval", {"run_id": "run_nope"}, "非法 run_id", "Invalid run_id", 400),     # 不是 gen_ 开头
            ("/api/gen-eval", {"run_id": "gen_nope"}, "run 不存在", "The run does not exist", 404),
            ("/api/gen-rate", {"run_id": "bad", "item_id": "x", "stars": 3}, "非法 run_id", "Invalid run_id", 400),
            ("/api/gen-rate", {"run_id": GEN, "item_id": "snake", "stars": 9}, "stars 应为 0-5 整数或 null",
             "stars must be an integer from 0 to 5, or null", 400),
            ("/api/gen-rate", {"run_id": GEN, "item_id": "snake", "stars": True}, "stars 应为 0-5 整数或 null",
             "stars must be an integer from 0 to 5, or null", 400),
            ("/api/gen-rate", {"run_id": "gen_nope", "item_id": "snake", "stars": 3}, "run 或作品不存在",
             "The run or generated page does not exist", 404),
            ("/api/gen-rate", {"run_id": GEN, "item_id": "nope", "stars": 3}, "run 或作品不存在",
             "The run or generated page does not exist", 404),
        ]
        for path, body, zh, en, status in rows:
            with self.subTest(path=path, body=body):
                self.both("POST", path, body, zh, en, status)

    def test_deleting_a_running_run(self):
        with running("perf", run_id=PERF):
            self.both("POST", "/api/run-delete", {"run_id": PERF}, "该运行尚未结束，请先停止",
                      "This run is still in progress. Stop it first.", 409)

    def test_old_report_endpoint_messages(self):
        rows = [
            ("/api/report?id=bad", "非法 run_id", "Invalid run_id", 400),
            ("/api/report?id=run_nope", "run 不存在", "The run does not exist", 404),
            ("/api/report?id=%s&cmp=bad" % PERF, "非法 cmp run_id", "Invalid cmp run_id", 400),
            ("/api/report?id=%s&cmp=run_nope" % PERF, "cmp run 不存在", "The cmp run does not exist", 404),
        ]
        for path, zh, en, status in rows:
            with self.subTest(path=path):
                self.both("GET", path, None, zh, en, status)


class TestExportMessages(ServerCase):
    def test_export_html_errors(self):
        rows = [
            ({"page": "dash", "id": PERF, "cmp": 5}, "cmp 格式错误", "Invalid cmp format", 400),
            ({"page": "zzz", "id": PERF}, "不支持导出这个页面", "This page cannot be exported", 400),
            ({"page": "dash", "id": PERF, "cmp": ["run_%d" % i for i in range(7)]}, "一次最多导出 7 次测试",
             "You can export at most 7 tests at a time", 400),
            ({"page": "dash", "id": "zzz"}, "非法 run_id: zzz", "Invalid run_id: zzz", 400),
            ({"page": "iq", "id": PERF}, "非法 run_id: %s" % PERF, "Invalid run_id: %s" % PERF, 400),   # 前缀和页面对不上
        ]
        for body, zh, en, status in rows:
            with self.subTest(body=body):
                self.both("POST", "/api/export-html", body, zh, en, status)

    def test_missing_tests_singular_and_plural(self):
        """「测试不存在」是带数量的句子 (tn): 一个用单数, 多个用复数; 中文不分。三种页面各查一遍。"""
        rows = [
            ({"page": "dash", "id": "run_nope1"}, "测试不存在: run_nope1", "The test does not exist: run_nope1"),
            ({"page": "cmp", "id": PERF, "cmp": ["run_nope1", "run_nope2"]}, "测试不存在: run_nope1, run_nope2",
             "These tests do not exist: run_nope1, run_nope2"),
            ({"page": "iq", "id": "iq_nope1"}, "测试不存在: iq_nope1", "The test does not exist: iq_nope1"),
            ({"page": "iq", "id": IQ_DONE, "cmp": "iq_nope1,iq_nope2"}, "测试不存在: iq_nope1, iq_nope2",
             "These tests do not exist: iq_nope1, iq_nope2"),
            ({"page": "gen", "id": "gen_nope1"}, "测试不存在: gen_nope1", "The test does not exist: gen_nope1"),
            ({"page": "gen", "id": GEN, "cmp": ["gen_nope1", "gen_nope2"]}, "测试不存在: gen_nope1, gen_nope2",
             "These tests do not exist: gen_nope1, gen_nope2"),
        ]
        for body, zh, en in rows:
            with self.subTest(body=body):
                self.both("POST", "/api/export-html", body, zh, en, 400)

    def test_direct_calls_raise_translated_errors(self):
        for lang, want in (("zh", "测试不存在: run_x"), ("en", "The test does not exist: run_x")):
            with i18n.use_lang(lang), self.assertRaises(ValueError) as cm:
                server.offline_bundle("dash", "run_x", [])
            self.assertEqual(str(cm.exception), want)

    def test_export_still_works_and_uses_the_request_language_for_the_title(self):
        st, page = self.request("POST", "/api/export-html", {"page": "dash", "id": PERF}, lang="en")
        self.assertEqual(st, 200)
        self.assertIn("<title>LLM Bench Pro offline report</title>", page)
        st, page = self.request("POST", "/api/export-html", {"page": "dash", "id": PERF}, lang="zh")
        self.assertIn("<title>LLM Bench Pro 离线报告</title>", page)


class TestStartValidation(ServerCase):
    """启动速度测试 / 能力评测 / 代码生成前的参数检查: 全部在真正启动任务之前就被拒绝。"""

    def start(self, **extra):
        return dict({"base": BASE, "model": "m", "suite": "quick"}, **extra)

    def test_speed_test_parameters(self):
        rows = [
            ({"base": BASE}, "缺少 base/model", "base and model are required"),
            ({"model": "m"}, "缺少 base/model", "base and model are required"),
            (self.start(suite="zzz"), "未知测试套件", "Unknown test suite"),
            (self.start(conc_ladder="a,b"), "并发梯度格式错误：应为 1-128 的逗号分隔整数，如 1,2,4,8",
             "Invalid concurrency ladder: expected comma-separated integers from 1 to 128, e.g. 1,2,4,8"),
            (self.start(conc_ladder="999"), "并发梯度格式错误：应为 1-128 的逗号分隔整数，如 1,2,4,8",
             "Invalid concurrency ladder: expected comma-separated integers from 1 to 128, e.g. 1,2,4,8"),
            (self.start(matrix_conc="a"), "矩阵并发数应为 1-32 的整数", "The matrix concurrency must be an integer from 1 to 32"),
            (self.start(matrix_conc="99"), "矩阵并发数应为 1-32 的整数", "The matrix concurrency must be an integer from 1 to 32"),
            (self.start(lens="a"), "输入长度梯度格式错误：应为 1-256 的逗号分隔整数（K），如 1,2,4,8,16",
             "Invalid input length ladder: expected comma-separated integers from 1 to 256 (in K tokens), e.g. 1,2,4,8,16"),
            (self.start(lens="999"), "输入长度梯度格式错误：应为 1-256 的逗号分隔整数（K），如 1,2,4,8,16",
             "Invalid input length ladder: expected comma-separated integers from 1 to 256 (in K tokens), e.g. 1,2,4,8,16"),
        ]
        for body, zh, en in rows:
            with self.subTest(body=body):
                self.both("POST", "/api/start", body, zh, en, 400)

    def test_scenario_and_replay_settings(self):
        """场景 (scenarios) 和回放 (replay) 的每一种配置错误: 前面加「场景配置错误：」, 英文加 "Invalid scenario settings: "。"""
        empty_dir = temp_dir()
        no_dir, no_file = os.path.join(empty_dir, "no-such-dir"), os.path.join(empty_dir, "no.jsonl")
        rows = [
            ({"scenarios": 5}, "scenarios 应为对象", "scenarios must be an object"),
            ({"scenarios": {"tasks": []}}, "tasks 应为任务类型列表", "tasks must be a list of task types"),
            ({"scenarios": {"tasks": "chat,zzz"}}, "未知任务类型 zzz (可选: %s)" % "/".join(bench.SCN_TEMPLATES),
             "Unknown task type zzz (choose from: %s)" % "/".join(bench.SCN_TEMPLATES)),
            ({"scenarios": {"tasks": ["chat", "chat"]}}, "tasks 里有重复的任务类型", "tasks contains duplicate task types"),
            ({"scenarios": {"tasks": ["chat"], "requests_per_worker": "x"}}, "requests_per_worker / max_tokens 应为整数",
             "requests_per_worker and max_tokens must be integers"),
            ({"scenarios": {"tasks": ["chat"], "conc": [999]}}, "requests_per_worker / max_tokens 应为整数",
             "requests_per_worker and max_tokens must be integers"),      # conc 的错在同一个 try 里, 沿用这句 (转换前就是这样)
            ({"scenarios": {"tasks": ["rag"], "rag_ctx": [1]}}, "scenarios.rag_ctx 超出范围 512-65536",
             "scenarios.rag_ctx must be between 512 and 65536"),
            ({"scenarios": {"tasks": ["rag"], "rag_ctx": "a"}}, "scenarios.rag_ctx 应为整数列表",
             "scenarios.rag_ctx must be a list of integers"),
            ({"scenarios": {"tasks": ["rag"], "rag_ctx": 5}}, "scenarios.rag_ctx 应为逗号分隔整数列表",
             "scenarios.rag_ctx must be a comma-separated list of integers"),
            ({"scenarios": {"tasks": ["vision"], "vision_src": 5}}, "vision_src 应为对象", "vision_src must be an object"),
            ({"scenarios": {"tasks": ["vision"], "vision_src": {"image_id": "bad"}}}, "非法 image_id", "Invalid image_id"),
            ({"scenarios": {"tasks": ["vision"], "vision_src": {"image_id": "img-ffffffffffff"}}},
             "图片包 img-ffffffffffff 不存在（可能已被删除），请重新上传或改用内置示例图片",
             "Image pack img-ffffffffffff does not exist (it may have been deleted). Upload it again or use the built-in sample images."),
            ({"scenarios": {"tasks": ["vision"], "vision_src": {"dir": no_dir}}}, "服务器上没有这个图片文件夹: %s" % no_dir,
             "There is no such image folder on the server: %s" % no_dir),
            ({"scenarios": {"tasks": ["vision"], "vision_src": {"dir": empty_dir}}},
             "图片文件夹 %s 里没有图片（支持 jpg / png / webp / gif）" % empty_dir,
             "Image folder %s contains no images (supported: jpg / png / webp / gif)" % empty_dir),
            ({"scenarios": {"tasks": ["vision"], "vision_src": {"image_id": "builtin", "images": "x"}}}, "vision_src.images 应为 1-4 的整数",
             "vision_src.images must be an integer from 1 to 4"),
            ({"scenarios": {"tasks": ["custom"], "custom_file_id": "bad"}}, "非法 custom_file_id", "Invalid custom_file_id"),
            ({"scenarios": {"tasks": ["custom"], "custom_file_id": "scn-000000000000"}},
             "任务集不存在: scn-000000000000 (可能已被删除, 请重新导入)",
             "The task set does not exist: scn-000000000000 (it may have been deleted; import it again)"),
            ({"scenarios": {"tasks": ["custom"], "custom_file": no_file}}, "任务集文件不存在: %s" % no_file,
             "The task set file does not exist: %s" % no_file),
            ({"scenarios": {"tasks": ["custom"]}}, "自定义任务集需要选择已上传的任务集或填写服务器文件路径",
             "A custom task set needs an imported task set or a file path on the server"),
            ({"replay": 5}, "replay 应为对象", "replay must be an object"),
            ({"scenarios": {"tasks": ["chat"], "replay": 5}}, "replay 应为对象", "replay must be an object"),
            ({"replay": {"file_id": "bad"}}, "非法 file_id", "Invalid file_id"),
            ({"replay": {"file_id": "replay-ffffffffffff"}}, "回放文件不存在: replay-ffffffffffff (可能已被删除, 请重新上传)",
             "The replay file does not exist: replay-ffffffffffff (it may have been deleted; upload it again)"),
            ({"replay": {"closed": {}}}, "replay 需要 file_id(上传的文件)或 file(服务器路径)",
             "replay needs either file_id (an uploaded file) or file (a path on the server)"),
            ({"replay": {"file": "/x", "closed": 5}}, "replay.closed 应为对象", "replay.closed must be an object"),
            ({"replay": {"file": "/x", "closed": {"requests_per_worker": "a"}}}, "replay.closed.requests_per_worker 应为整数",
             "replay.closed.requests_per_worker must be an integer"),
            ({"replay": {"file": "/x", "closed": {"conc": [999]}}}, "replay.closed.conc 超出范围 1-128",
             "replay.closed.conc must be between 1 and 128"),
            ({"replay": {"file": "/x", "open": 5}}, "replay.open 应为对象", "replay.open must be an object"),
            ({"replay": {"file": "/x", "open": {"rates": ["a"]}}}, "replay.open.rates 应为数字列表",
             "replay.open.rates must be a list of numbers"),
            ({"replay": {"file": "/x", "open": {"rates": [0]}}}, "replay.open.rates 需要至少一个 0.05-1000 的速率",
             "replay.open.rates needs at least one rate between 0.05 and 1000"),
        ]
        for extra, zh, en in rows:
            with self.subTest(extra=extra):
                self.both("POST", "/api/start", self.start(**extra), "场景配置错误：" + zh, "Invalid scenario settings: " + en, 400)

    def test_image_source_without_a_usable_image_uses_a_whole_sentence_per_kind(self):
        """「图片包 xx」和「图片文件夹 xx」各写整句 (英文语序和中文不一样): 没有能用的图片时列出前 3 张的原因, 用 t("；") 隔开。"""
        checks = [{"name": "%d.png" % i, "msg": "m%d" % i, "ok": False} for i in range(1, 6)]
        pack = os.path.join(server.SCN_IMAGES_DIR, "img-0000000000aa")
        os.makedirs(pack, exist_ok=True)
        folder = temp_dir()
        with mock.patch.object(vision_assets, "scan_dir", lambda d, keep_data=True: ([], checks)):
            self.both("POST", "/api/start", self.start(scenarios={"tasks": ["vision"], "vision_src": {"image_id": "img-0000000000aa"}}),
                      "场景配置错误：图片包 img-0000000000aa 里没有能用的图片：1.png m1；2.png m2；3.png m3。请重新上传，或改用内置示例图片",
                      "Invalid scenario settings: Image pack img-0000000000aa has no usable images: 1.png: m1; 2.png: m2; 3.png: m3. "
                      "Upload it again or use the built-in sample images.", 400)
            self.both("POST", "/api/start", self.start(scenarios={"tasks": ["vision"], "vision_src": {"dir": folder}}),
                      "场景配置错误：图片文件夹 %s 里没有能用的图片：1.png m1；2.png m2；3.png m3。请重新上传，或改用内置示例图片" % folder,
                      "Invalid scenario settings: Image folder %s has no usable images: 1.png: m1; 2.png: m2; 3.png: m3. "
                      "Upload them again or use the built-in sample images." % folder, 400)
        with mock.patch.object(vision_assets, "scan_dir", lambda d, keep_data=True: ([], [])):
            self.both("POST", "/api/start", self.start(scenarios={"tasks": ["vision"], "vision_src": {"image_id": "img-0000000000aa"}}),
                      "场景配置错误：图片包 img-0000000000aa 里没有图片（支持 jpg / png / webp / gif）",
                      "Invalid scenario settings: Image pack img-0000000000aa contains no images (supported: jpg / png / webp / gif)", 400)

    def test_task_already_running_races(self):
        """校验都通过、但抢不到任务位置 (两个请求几乎同时启动) 的提示, 和「已有…在运行」的提示是同一句。"""
        zh_en = {"perf": ("已有性能测试在运行", "Another speed test is already running"),
                 "iq": ("已有能力评测在运行", "Another capability test is already running"),
                 "gen": ("已有代码生成任务或重新评测在运行", "Another code generation run or re-evaluation is already running")}
        bank = {"bank_id": "b", "subjects": []}
        stopped = iq_doc("iq_i18nsrv_race")                     # 续跑要一份「停止过、评测程序版本和现在一样」的运行
        stopped.update(status="cancelled", iq_version=iq.IQ_VERSION)
        sinks.SqliteSink().save(stopped)
        self.addCleanup(store.delete_run, "iq_i18nsrv_race")
        cases = [("perf", "/api/start", self.start()),
                 ("iq", "/api/iq-start", {"base": BASE, "model": "m", "bank_id": "b"}),
                 ("iq", "/api/iq-resume", {"run_id": "iq_i18nsrv_race"}),
                 ("gen", "/api/gen-start", {"base": BASE, "model": "m"}),
                 ("gen", "/api/gen-eval", {"run_id": GEN})]
        with mock.patch.object(bankman, "load_bank", lambda bank_id: bank):
            for kind, path, body in cases:
                with self.subTest(path=path), mock.patch.object(server.JOBS[kind], "try_start", lambda *a, **k: False):
                    zh, en = zh_en[kind]
                    self.both("POST", path, body, zh, en, 409)

    def test_capability_test_parameters(self):
        bank = {"bank_id": "b", "subjects": []}
        ok = {"base": BASE, "model": "m", "bank_id": "b"}
        rows = [
            ({"base": BASE}, "缺少 base/model/bank_id", "base, model and bank_id are required"),
            (dict(ok, sampling="x"), "参数错误：sampling 格式错误", "Invalid parameters: Invalid sampling format"),
            (dict(ok, sampling={"temperature": 5}), "参数错误：temperature 超出范围 0.0–2.0",
             "Invalid parameters: temperature must be between 0.0 and 2.0"),
            (dict(ok, sampling={"top_p": 2}), "参数错误：top_p 超出范围 0.0–1.0", "Invalid parameters: top_p must be between 0.0 and 1.0"),
            (dict(ok, sampling={"top_k": 5000}), "参数错误：top_k 超出范围 -1–1000", "Invalid parameters: top_k must be between -1 and 1000"),
            (dict(ok, subjects="x"), "subjects 应为科目 id 列表", "subjects must be a list of subject ids"),
            (dict(ok, subjects=[1]), "subjects 应为科目 id 列表", "subjects must be a list of subject ids"),
        ]
        with mock.patch.object(bankman, "load_bank", lambda bank_id: bank):
            for body, zh, en in rows:
                with self.subTest(body=body):
                    self.both("POST", "/api/iq-start", body, zh, en, 400)
        self.assertFalse(server.JOBS["iq"].snapshot()["running"])          # subjects 的检查在占位之后, 拒绝时要把位置放回去

    def test_code_generation_parameters(self):
        rows = [
            ({"base": BASE}, "缺少 base/model", "base and model are required"),
            ({"base": BASE, "model": "m", "conc": "abc"}, "并发应为整数", "Concurrency must be an integer"),
        ]
        for body, zh, en in rows:
            with self.subTest(body=body):
                self.both("POST", "/api/gen-start", body, zh, en, 400)

    def test_python_error_text_is_passed_on_untouched(self):
        """int() 等 Python 自己的报错原文 (英文) 原样带在后面, 中英文一样。"""
        body = {"base": BASE, "model": "m", "bank_id": "b", "conc": "abc"}
        with mock.patch.object(bankman, "load_bank", lambda bank_id: {"bank_id": bank_id, "subjects": []}):
            for lang, head in (("zh", "参数错误："), ("en", "Invalid parameters: ")):
                st, d = self.request("POST", "/api/iq-start", body, lang=lang)
                self.assertEqual((st, d["error"]), (400, head + "invalid literal for int() with base 10: 'abc'"))


# ================================================================ 2b. 上传

class TestUploadMessages(ServerCase):
    LINE = '{"messages": [{"role": "user", "content": "hi"}]}'

    def test_missing_content_and_size_limit_are_shared_by_both_upload_endpoints(self):
        need = ("缺少文件内容 (content 应为 JSONL 文本)", "Missing file content (content must be JSONL text)")
        big = ("文件超过 15MB 上限; 大文件请放到服务器后用路径引用",
               "The file exceeds the 15MB limit. For large files, put them on the server and reference them by path.")
        for path, body in (("/api/scenario-upload", {"kind": "tasks"}), ("/api/scenario-upload", {"kind": "tasks", "content": "  \n "}),
                           ("/api/replay-upload", {}), ("/api/replay-upload", {"content": 5})):
            with self.subTest(path=path, body=body):
                self.both("POST", path, body, need[0], need[1], 400)
        huge = "a" * (15 * 1024 * 1024 + 1)         # 太大的请求每次要传十几 MB: 中文 / 英文各一次, 不再试「不带请求头」
        for path, body in (("/api/scenario-upload", {"kind": "tasks", "content": huge}), ("/api/replay-upload", {"content": huge})):
            with self.subTest(path=path, size="15MB+1"):
                self.assertEqual(self.error_of("POST", path, body, lang="zh"), (400, big[0]))
                st, msg = self.error_of("POST", path, body, lang="en")
                self.assertEqual((st, msg), (400, big[1]))
                assert_english(self, msg)

    def test_no_usable_line_reports_the_first_problem_or_the_hint(self):
        """整份文件一行都不能用: 有整体提示 (hint) 就写提示, 否则写第一个有问题的行; 都没有也有一句 (整句, 不拼碎片)。"""
        check = {"total": 1, "valid": 0, "skipped": 0, "bad": 1, "json": 0, "image": 0, "warnings": [], "warning_count": 0}
        cases = [
            (dict(check, problems=[{"line": 3, "reason": "REASON"}], hint=""), "没有一行能用（第 3 行：REASON）",
             "No usable lines (Line 3: REASON)"),
            (dict(check, problems=[{"line": 3, "reason": "REASON"}], hint="HINT"), "没有一行能用（HINT）", "No usable lines (HINT)"),
            (dict(check, problems=[], hint=""), "没有一行能用", "No usable lines"),
        ]
        for fake, zh, en in cases:
            with self.subTest(zh=zh), mock.patch.object(bench, "check_task_text", lambda text, *a, **k: fake):
                self.both("POST", "/api/scenario-upload", {"kind": "tasks", "content": "x\n"}, zh, en, 400)
        json_line = '没有可用行: 每行应为 {"messages": [...], "params": {...}}'
        json_line_en = 'No usable lines: each line must be {"messages": [...], "params": {...}}'
        with mock.patch.object(bench, "check_task_text", lambda text, *a, **k: dict(check, problems=[], hint="")):
            self.both("POST", "/api/replay-upload", {"content": "x\n"}, json_line, json_line_en, 400)      # 里面的花括号是字面的

    def test_image_upload_messages(self):
        rows = [
            ({"kind": "images"}, "缺少 files: [{name, data(base64)}]", "Missing files: [{name, data(base64)}]"),
            ({"kind": "images", "files": []}, "缺少 files: [{name, data(base64)}]", "Missing files: [{name, data(base64)}]"),
            ({"kind": "zzz"}, "kind 应为 tasks 或 images", "kind must be tasks or images"),
            ({"kind": "images", "files": [{"name": "a.txt", "data": "x"}]},
             "没有能用的图片：a.txt 不是支持的图片类型（只收 jpg / png / webp / gif）",
             "No usable images: a.txt: Unsupported image type (only jpg / png / webp / gif are accepted)"),
            ({"kind": "images", "files": [{"name": "a.png", "data": "abc"}]},
             "没有能用的图片：a.png 上传的数据不是合法的 base64", "No usable images: a.png: The uploaded data is not valid base64"),
            # 没有名字的文件用「第 N 张」; 最多列前 3 张的原因, 用 t("；") 隔开
            ({"kind": "images", "files": [{"data": "x"}, 5, {"name": "c.gif.txt"}, {"name": "d.txt"}]},
             "没有能用的图片：第 1 张 不是支持的图片类型（只收 jpg / png / webp / gif）；第 2 张 不是支持的图片类型（只收 jpg / png / webp / gif）；"
             "c.gif.txt 不是支持的图片类型（只收 jpg / png / webp / gif）",
             "No usable images: Image 1: Unsupported image type (only jpg / png / webp / gif are accepted); "
             "Image 2: Unsupported image type (only jpg / png / webp / gif are accepted); "
             "c.gif.txt: Unsupported image type (only jpg / png / webp / gif are accepted)"),
        ]
        for body, zh, en in rows:
            with self.subTest(body=body):
                self.both("POST", "/api/scenario-upload", body, zh, en, 400)

    def test_per_file_messages_in_the_report(self):
        """收不下的每张图带一句原因 (files[].msg, 页面按「文件名：原因」列出); 一次最多收 64 张, 超过的每张说明没收。"""
        ok = b64(png_of(64, 64))
        limit = server.Handler._MAX_UPLOAD_IMAGES
        files = [{"name": "f%d.png" % i, "data": ok} for i in range(limit - 2)]
        files += [{"name": "bad.txt", "data": "x"}, {"name": "broken.png", "data": "abc"}]          # 前 64 张之内: 各有各的原因
        files += [{"name": "extra1.png", "data": ok}, {"name": "extra2.png", "data": ok}]           # 第 65、66 张: 超过一次的上限
        for lang, msgs in (("zh", ["不是支持的图片类型（只收 jpg / png / webp / gif）", "上传的数据不是合法的 base64",
                                   "一次最多上传 64 张，这张没有收", "一次最多上传 64 张，这张没有收"]),
                           ("en", ["Unsupported image type (only jpg / png / webp / gif are accepted)",
                                   "The uploaded data is not valid base64",
                                   "At most 64 images can be uploaded at a time; this one was not accepted",
                                   "At most 64 images can be uploaded at a time; this one was not accepted"])):
            st, d = self.request("POST", "/api/scenario-upload", {"kind": "images", "files": files}, lang=lang)
            self.assertEqual((st, d["ok"], d["count"], d["rejected"]), (200, True, limit - 2, 4), d)
            self.assertEqual([f["msg"] for f in d["files"][limit - 2:]], msgs)
            self.assertEqual([f["code"] for f in d["files"][limit - 2:]], ["unsupported", "broken", "unsupported", "unsupported"])   # 代码不随语言变
            if lang == "en":
                assert_english(self, [f["msg"] for f in d["files"][limit - 2:]])

    def test_task_upload_still_reports_everything_else_as_before(self):
        st, d = self.request("POST", "/api/scenario-upload", {"kind": "tasks", "name": "a.jsonl", "content": self.LINE + "\n"}, lang="en")
        self.assertEqual((st, d["ok"], d["lines"], d["bad_lines"], d["name"]), (200, True, 1, 0, "a"))


# ================================================================ 4. 存进结果和任务日志里的文字

class TestJobTextFollowsTheRequestLanguage(ServerCase):
    def tearDown(self):
        for kind in ("bank", "perf"):                          # 任务的日志和错误留在共用的任务状态里: 清掉, 不影响别的用例
            server.JOBS[kind].set(log=[], error=None, run_id=None, title=None, base=None)

    def test_bank_update_title_and_logs(self):
        """题集更新是页面启动的后台任务: 标题和日志 (被停止 / 失败时的提示) 用发起请求的语言。"""
        for lang, title, stopped, tip in (
                ("zh", "更新题集", "已停止：已经下载好的题集数据留在本地，下次不用重新下载",
                 "提示：可以换一个「题集下载源」或填「下载用的代理」再试；没有网的机器，把能联网机器上的 data/datasets/ 拷贝过来即可离线生成"),
                ("en", "Question set update", "Stopped: the question set data already downloaded stays on this machine, so it will not be "
                                              "downloaded again next time",
                 'Tip: try a different "Question set download source" or set a "Download proxy", then retry. On a machine without '
                 'internet access, copy data/datasets/ from a machine that is online to build the question sets offline')):
            with mock.patch.object(bankman, "build", side_effect=bankman.Cancelled()):
                self.assertEqual(self.request("POST", "/api/bank-update", {}, lang=lang)[1]["ok"], True)
                snap = self.wait_idle("bank")
            self.assertEqual((snap["title"], snap["error"], [x["msg"] for x in snap["log"]]), (title, None, [stopped]), lang)
            with mock.patch.object(bankman, "build", side_effect=RuntimeError("boom")):
                self.assertEqual(self.request("POST", "/api/bank-update", {}, lang=lang)[1]["ok"], True)
                snap = self.wait_idle("bank")
            self.assertEqual((snap["title"], snap["error"]), (title, "RuntimeError: boom"), lang)
            self.assertEqual([x["msg"] for x in snap["log"]], [tip, "FAILED: RuntimeError: boom"], lang)
            if lang == "en":
                assert_english(self, snap, what="bank job state")

    def test_bank_update_already_running(self):
        with running("bank"):
            self.both("POST", "/api/bank-update", {}, "题集正在更新中", "A question set update is already in progress", 409)

    def test_forced_start_records_the_note_in_the_request_language(self):
        """和别的任务共用端点、用户确认后强制启动: 记进结果的 notes 用发起请求的语言, 原样存储。"""
        seen = []

        def fake_run_suite(*a, **kw):
            seen.append(kw.get("notes"))
        body = {"base": BASE, "model": "m", "suite": "quick", "force": True}
        with mock.patch.object(bench, "run_suite", fake_run_suite):
            for lang, extra, want in (
                    ("zh", {}, "启动时其他测试正在使用同一端点，数据可能受干扰"),
                    ("zh", {"conflict_with": "能力评测"}, "启动时能力评测正在使用同一端点，数据可能受干扰"),
                    ("en", {}, "The other test was using the same endpoint when this run started, so the data may be affected"),
                    ("en", {"conflict_with": "capability test"},
                     "The capability test was using the same endpoint when this run started, so the data may be affected")):
                del seen[:]
                st, d = self.request("POST", "/api/start", dict(body, **extra), lang=lang)
                self.assertEqual((st, d["ok"]), (200, True), d)
                self.wait_idle("perf")
                self.assertEqual(seen, [[want]], (lang, extra))
            del seen[:]
            self.request("POST", "/api/start", {"base": BASE, "model": "m", "suite": "quick"}, lang="en")     # 没有强制: 不记
            self.wait_idle("perf")
            self.assertEqual(seen, [None])


# ================================================================ 5. 旧版报告接口的语言

class TestOldReportLanguage(ServerCase):
    def test_lang_query_beats_the_header_and_the_default(self):
        """/api/report 常在浏览器地址栏直接打开, 发不了请求头: ?lang=zh|en 优先于 X-Lang, 都没有用默认 (测试里是中文)。"""
        def fake_render(a, b=None):
            return "<html lang=%s>%s</html>" % (i18n.current_lang(), "ab" if b else "a")
        url = "/api/report?id=%s" % PERF
        cases = [(url, {}, "zh"), (url + "&lang=en", {}, "en"), (url + "&lang=zh", {}, "zh"), (url, {"X-Lang": "en"}, "en"),
                 (url + "&lang=zh", {"X-Lang": "en"}, "zh"), (url + "&lang=en", {"X-Lang": "zh"}, "en"),
                 (url + "&lang=fr", {"X-Lang": "en"}, "en"), (url + "&lang=", {"X-Lang": "en"}, "en"),
                 (url + "&lang=EN-us", {}, "en"), (url + "&cmp=%s&lang=en" % PERF, {}, "en")]
        with mock.patch.object(report, "render", fake_render):
            for path, headers, want in cases:
                with self.subTest(path=path, headers=headers):
                    st, page = self.request("GET", path, headers=headers)
                    self.assertEqual(st, 200)
                    self.assertTrue(page.startswith("<html lang=%s>" % want), page)

    def test_errors_of_the_report_endpoint_follow_the_query_too(self):
        for path, headers, want in (("/api/report?id=bad&lang=en", {}, "Invalid run_id"), ("/api/report?id=bad", {}, "非法 run_id"),
                                    ("/api/report?id=bad&lang=zh", {"X-Lang": "en"}, "非法 run_id"),
                                    ("/api/report?id=run_nope&lang=en", {}, "The run does not exist")):
            st, d = self.request("GET", path, headers=headers)
            self.assertEqual(d["error"], want, path)

    def test_render_errors_are_returned_as_they_are(self):
        """报告内容里的错误由 report.py 负责翻译: 这里原样带回去, 状态码 400。"""
        with mock.patch.object(report, "render", side_effect=ValueError("some report error")):
            st, d = self.request("GET", "/api/report?id=%s&lang=en" % PERF)
        self.assertEqual((st, d), (400, {"ok": False, "error": "some report error"}))


# ================================================================ 6. 中英文缓存互不串

class TestCachesDoNotMixLanguages(ServerCase):
    def test_task_set_line_reasons_are_scanned_once_per_language(self):
        """逐行索引 (tasksets.scan) 缓存了每行的原因: 说明是按当前语言写的, 语言是缓存键 —— 切换语言重读一遍, 不会看到另一种语言的旧说明。"""
        real = bench.check_task_line
        calls = []

        def fake(line, *a, **k):
            r = real(line, *a, **k)
            calls.append(i18n.current_lang())
            return dict(r, reason="[%s] %s" % (i18n.current_lang(), r["reason"])) if r["status"] != "ok" else r
        tasksets._scan_cached.cache_clear()
        with mock.patch.object(bench, "check_task_line", fake):
            st, up = self.request("POST", "/api/scenario-upload", {"kind": "tasks", "name": "t.jsonl",
                                                                   "content": TestUploadMessages.LINE + "\nnot json\n"}, lang="zh")
            self.assertEqual(st, 200, up)
            fid = up["file_id"]

            def reasons(lang):
                del calls[:]
                st, d = self.request("GET", "/api/task-set?id=%s&limit=100&head=0" % fid, lang=lang)
                self.assertEqual(st, 200, d)
                return [x["reason"][:4] for x in d["lines"] if x["status"] != "ok"], len(calls)
            self.assertEqual(reasons("zh"), (["[zh]"], 2))          # 第一次: 扫描 (两行)
            self.assertEqual(reasons("zh"), (["[zh]"], 0))          # 同语言: 用缓存
            self.assertEqual(reasons("en"), (["[en]"], 2))          # 换语言: 重新扫描, 说明是英文的
            self.assertEqual(reasons("en"), (["[en]"], 0))
            self.assertEqual(reasons("zh"), (["[zh]"], 0))          # 两种语言各留一份 (缓存最近 2 个)
            st, d = self.request("GET", "/api/task-set-line?id=%s&line=2" % fid, lang="en")
            self.assertTrue(d["line"]["reason"].startswith("[en]"), d)
        tasksets._scan_cached.cache_clear()

    def test_image_pack_check_is_cached_per_language(self):
        pack = os.path.join(server.SCN_IMAGES_DIR, "img-0123456789ab")
        os.makedirs(pack, exist_ok=True)
        with open(os.path.join(pack, "00.png"), "wb") as f:
            f.write(b"x")
        calls = []

        def fake_scan(d, keep_data=True):
            calls.append(i18n.current_lang())
            return [], [{"name": "x.png", "bytes": 1, "ok": False, "code": "broken", "msg": "MSG-" + i18n.current_lang()}]
        server._image_pack_check.cache_clear()
        with mock.patch.object(vision_assets, "scan_dir", fake_scan):
            for lang in ("zh", "en", "zh", "en", "en"):
                st, d = self.request("GET", "/api/scenario-list", lang=lang)
                self.assertEqual(d["images"][0]["problems"], [("x.png: MSG-" if lang == "en" else "x.png MSG-") + lang], lang)
        self.assertEqual(calls, ["zh", "en"])                 # 每种语言只检查一次
        server._image_pack_check.cache_clear()


# ================================================================ 7. 直接调用的函数

class TestServerFunctions(base.LangCase):
    def raises(self, fn, args, zh, en, exc=ValueError):
        for lang, want in (("zh", zh), ("en", en)):
            with i18n.use_lang(lang), self.assertRaises(exc) as cm:
                fn(*args)
            self.assertEqual(str(cm.exception), want, lang)
            if lang == "en":
                assert_english(self, str(cm.exception))

    def test_parse_sampling(self):
        self.raises(server._parse_sampling, ("x",), "sampling 格式错误", "Invalid sampling format")
        self.raises(server._parse_sampling, ({"temperature": 3},), "temperature 超出范围 0.0–2.0", "temperature must be between 0.0 and 2.0")
        self.raises(server._parse_sampling, ({"top_p": -1},), "top_p 超出范围 0.0–1.0", "top_p must be between 0.0 and 1.0")
        self.raises(server._parse_sampling, ({"top_k": 1001},), "top_k 超出范围 -1–1000", "top_k must be between -1 and 1000")
        self.assertEqual(server._parse_sampling({"temperature": "0.5", "top_k": 20}), {"temperature": 0.5, "top_k": 20})

    def test_ints(self):
        self.raises(server._ints, ("x", "n", 1, 9), "n 应为整数列表", "n must be a list of integers")
        self.raises(server._ints, ([], "n", 1, 9), "n 应为逗号分隔整数列表", "n must be a comma-separated list of integers")
        self.raises(server._ints, (5, "n", 1, 9), "n 应为逗号分隔整数列表", "n must be a comma-separated list of integers")
        self.raises(server._ints, ([10], "n", 1, 9), "n 超出范围 1-9", "n must be between 1 and 9")
        self.assertEqual(server._ints("3,1,3", "n", 1, 9), [1, 3])

    def test_iq_query_functions_return_translated_error_dicts(self):
        cases = [(server.iq_wrong, ("bad", "s"), "非法 run_id", "Invalid run_id"),
                 (server.iq_items, ("bad",), "非法 run_id", "Invalid run_id"),
                 (server.iq_items, ("iq_a", "bad"), "非法对比 run_id", "Invalid comparison run_id"),
                 (server.iq_answer, ("iq_a", "s", "x"), "非法题号", "Invalid question number"),
                 (server.iq_compare, ("bad", "iq_b"), "非法 run_id", "Invalid run_id"),
                 (server.iq_compare, ("iq_a", "iq_nope"), "run 不存在", "The run does not exist")]
        for fn, args, zh, en in cases:
            for lang, want in (("zh", zh), ("en", en)):
                with i18n.use_lang(lang):
                    self.assertEqual(fn(*args), {"ok": False, "error": want}, (fn.__name__, lang))

    def test_export_bundle_argument_errors(self):
        self.raises(server.offline_bundle, ("nope", "x", []), "不支持导出这个页面", "This page cannot be exported")
        self.raises(server.offline_bundle, ("dash", PERF, ["run_%d" % i for i in range(7)]), "一次最多导出 7 次测试",
                    "You can export at most 7 tests at a time")
        self.raises(server.offline_bundle, ("dash", "zzz", []), "非法 run_id: zzz", "Invalid run_id: zzz")
        self.raises(server.offline_bundle, ("iq", "iq_nope", ["iq_nope2"]), "测试不存在: iq_nope, iq_nope2",
                    "These tests do not exist: iq_nope, iq_nope2")

    def test_scenarios_and_replay_checks(self):
        self.raises(server._parse_scenarios, ({"scenarios": {"tasks": ["chat", "chat"]}},), "tasks 里有重复的任务类型",
                    "tasks contains duplicate task types")
        self.raises(server._parse_scenarios, ({"scenarios": {"tasks": ["zzz"]}},),
                    "未知任务类型 zzz (可选: %s)" % "/".join(bench.SCN_TEMPLATES),
                    "Unknown task type zzz (choose from: %s)" % "/".join(bench.SCN_TEMPLATES))
        self.raises(server._parse_replay, ({"replay": {"file": "/x", "open": {"rates": [0]}}},),
                    "replay.open.rates 需要至少一个 0.05-1000 的速率", "replay.open.rates needs at least one rate between 0.05 and 1000")
        self.assertIsNone(server._parse_scenarios({}))
        self.assertIsNone(server._parse_replay({}))

    def test_scenario_parsing_does_not_shadow_the_translation_function(self):
        """_parse_scenarios 里以前的循环变量叫 t, 会遮住 t(): 每种任务类型都走一遍, 确认能正常翻译出错误。"""
        for task in bench.SCN_TEMPLATES:
            with self.subTest(task=task):
                self.raises(server._parse_scenarios, ({"scenarios": {"tasks": [task, "zzz"]}},),
                            "未知任务类型 zzz (可选: %s)" % "/".join(bench.SCN_TEMPLATES),
                            "Unknown task type zzz (choose from: %s)" % "/".join(bench.SCN_TEMPLATES))


class TestEnglishFlows(ServerCase):
    """用 english_flow() 在英文下把常见的错误分支走一遍: 返回的文字没有汉字, 词典没有缺键 (缺了会回退成中文并记进 i18n.MISSING)。"""

    def test_english_requests_find_every_dictionary_key(self):
        empty_dir = temp_dir()
        calls = [
            ("GET", "/api/iq-wrong?id=bad&sid=s", None), ("GET", "/api/iq-items?id=iq_nope", None),
            ("GET", "/api/iq-answer?ids=%s&sid=s&idx=x" % IQ_DONE, None), ("GET", "/api/iq-compare?a=bad&b=x", None),
            ("GET", "/api/run?id=run_nope", None), ("GET", "/api/report?id=bad", None), ("GET", "/api/report?id=run_nope&lang=en", None),
            ("POST", "/api/run-delete", {"run_id": "bad"}), ("POST", "/api/run-delete", {"run_id": "run_nope"}),
            ("POST", "/api/iq-resume", {"run_id": IQ_DONE}), ("POST", "/api/iq-resume", {"run_id": IQ_OLD}),
            ("POST", "/api/gen-eval", {"run_id": "bad"}), ("POST", "/api/gen-rate", {"run_id": GEN, "item_id": "x", "stars": 9}),
            ("POST", "/api/export-html", {"page": "zzz"}), ("POST", "/api/export-html", {"page": "dash", "id": "run_nope"}),
            ("POST", "/api/export-html", {"page": "iq", "id": "iq_nope1", "cmp": ["iq_nope2"]}),
            ("POST", "/api/start", {"base": BASE}), ("POST", "/api/start", {"base": BASE, "model": "m", "suite": "zzz"}),
            ("POST", "/api/start", {"base": BASE, "model": "m", "lens": "a"}),
            ("POST", "/api/start", {"base": BASE, "model": "m", "scenarios": {"tasks": ["chat", "chat"]}}),
            ("POST", "/api/start", {"base": BASE, "model": "m", "scenarios": {"tasks": ["vision"], "vision_src": {"dir": empty_dir}}}),
            ("POST", "/api/start", {"base": BASE, "model": "m", "replay": {"file": "/x", "open": {"rates": [0]}}}),
            ("POST", "/api/iq-start", {"base": BASE}), ("POST", "/api/gen-start", {"base": BASE, "model": "m", "conc": "x"}),
            ("POST", "/api/scenario-upload", {"kind": "zzz"}), ("POST", "/api/scenario-upload", {"kind": "tasks"}),
            ("POST", "/api/scenario-upload", {"kind": "images", "files": [{"name": "a.txt", "data": "x"}]}),
            ("POST", "/api/replay-upload", {}), ("POST", "/api/task-set-rename", {"id": "scn-000000000000", "name": "x"}),
        ]
        got = []
        with english_flow() as flow:
            for method, path, body in calls:
                st, d = self.request(method, path, body, lang="en")
                self.assertIn(st, (200, 400, 404, 409), (path, st, d))
                got.append(d)
        flow.assert_clean(self, got)
        self.assertEqual(sum(1 for d in got if isinstance(d, dict) and d.get("error")), len(calls))     # 每个请求都有一条英文的说明


class TestEnglishFlowOfDirectCalls(base.LangCase):
    def test_functions_of_both_modules_in_english(self):
        texts = []

        def note(fn, *args):
            try:
                texts.append(fn(*args))
            except (ValueError, LookupError) as e:
                texts.append(str(e))
        with english_flow() as flow:
            for scen in ({"scenarios": 5}, {"scenarios": {"tasks": []}}, {"scenarios": {"tasks": ["zzz"]}},
                         {"scenarios": {"tasks": ["rag"], "rag_ctx": [1]}}, {"scenarios": {"tasks": ["vision"], "vision_src": {"dir": "/no/such"}}},
                         {"scenarios": {"tasks": ["custom"]}}, {"replay": 5}, {"replay": {"closed": {}}}):
                note(server._parse_scenarios, scen)
                note(server._parse_replay, scen)
            note(server._parse_sampling, "x")
            note(server._ints, "a", "n", 1, 9)
            note(server.offline_bundle, "dash", "run_nope1", ["run_nope2"])
            note(tasksets.clean_name, "")
            note(tasksets.image_bytes, "not json", 0)
            note(tasksets.image_bytes, "{}", 3)
            note(tasksets.image_info, "ftp://x")
            note(tasksets._small, {"a": [1] * 30}, 5)
            note(tasksets.pretty, '{"u": "data:%s"}' % ("a" * 300))
        flow.assert_clean(self, texts)
        self.assertGreater(len(texts), 20)


# ================================================================ 7b. tasksets.py

class TestTaskSetsModule(base.LangCase):
    def both(self, fn, args, zh, en):
        """同一个调用: 中文和转换前逐字一致, 英文和词典一致且没有汉字。"""
        for lang, want in (("zh", zh), ("en", en)):
            with i18n.use_lang(lang):
                self.assertEqual(fn(*args), want, lang)
        with i18n.use_lang("en"):
            assert_english(self, fn(*args))

    def raises(self, fn, args, exc, zh, en):
        for lang, want in (("zh", zh), ("en", en)):
            with i18n.use_lang(lang), self.assertRaises(exc) as cm:
                fn(*args)
            self.assertEqual(str(cm.exception), want, lang)
            if lang == "en":
                assert_english(self, str(cm.exception))

    def test_clean_name(self):
        self.both(tasksets.clean_name, ("  ",), ("", "名称不能为空"), ("", "The name cannot be empty"))
        self.both(tasksets.clean_name, (None,), ("", "名称不能为空"), ("", "The name cannot be empty"))
        long_name = "n" * (tasksets.NAME_MAX + 1)
        self.both(tasksets.clean_name, (long_name,), (long_name, "名称最多 80 个字（现在 81 个）"),
                  (long_name, "The name can be at most 80 characters (currently 81)"))
        self.both(tasksets.clean_name, (" ok ",), ("ok", ""), ("ok", ""))
        with i18n.use_lang("en"):
            self.assertEqual(tasksets.clean_name(" 好名字 "), ("好名字", ""))       # 名称本身是数据, 不翻译

    def test_image_info_messages(self):
        bad = lambda msg: {"kind": "bad", "msg": msg}      # noqa: E731
        cases = [(None, "缺少图片地址", "The image URL is missing"),
                 ("", "缺少图片地址", "The image URL is missing"),
                 ("data:image/png,xx", "不是 base64 格式的 data URL", "Not a base64 data URL"),
                 ("data:image/png;base64,", "不是 base64 格式的 data URL", "Not a base64 data URL"),
                 ("data:image/png;base64,abc", "base64 数据已损坏", "The base64 data is corrupted"),
                 ("ftp://x/a.png", "地址应为 data:image/…;base64,… 或 http(s) 网址",
                  "The URL must be data:image/…;base64,… or an http(s) URL")]
        for url, zh, en in cases:
            with self.subTest(url=url):
                self.both(tasksets.image_info, (url,), bad(zh), bad(en))
        self.both(tasksets.image_info, ("http://x/a.png",), {"kind": "url", "url": "http://x/a.png", "cut": False},
                  {"kind": "url", "url": "http://x/a.png", "cut": False})          # 网址形式: 没有说明文字, 两种语言一样
        with i18n.use_lang("en"):
            info = tasksets.image_info("data:image/png;base64," + b64(png_of(300, 200)))
        self.assertEqual((info["kind"], info["format"], info["width"], info["height"], info["ok"]), ("data", "PNG", 300, 200, True))

    def test_long_values_are_replaced_by_a_placeholder_sentence(self):
        obj = {"a": {"x": "y" * 50}, "b": [1] * 50, "c": "z" * 50}
        self.both(tasksets._small, (obj, 10), {"a": "（dict，太长没有显示）", "b": "（list，太长没有显示）", "c": "（str，太长没有显示）"},
                  {"a": "(dict, too long to display)", "b": "(list, too long to display)", "c": "(str, too long to display)"})
        self.both(tasksets._small, ({"a": 1}, 10), {"a": 1}, {"a": 1})                # 不长: 原样给

    def test_pretty_shortens_image_data_with_a_translated_note(self):
        url = "data:image/png;base64," + b64(png_of(300, 300))
        n = len(url)
        text = '{"u": "%s", "s": "short"}' % url
        zh = '{\n  "u": "%s…（共 %d 个字符，这里省略）",\n  "s": "short"\n}' % (url[:64], n)
        en = '{\n  "u": "%s… (%d characters in total, omitted here)",\n  "s": "short"\n}' % (url[:64], n)
        self.both(tasksets.pretty, (text,), zh, en)
        self.assertIsNone(tasksets.pretty("not json"))

    def test_image_bytes_errors(self):
        def line(*urls):
            parts = [{"type": "image_url", "image_url": ({"url": u} if u is not None else {})} for u in urls]
            return '{"messages": [{"role": "user", "content": %s}]}' % json.dumps(parts)
        self.raises(tasksets.image_bytes, ("not json", 0), ValueError, "这一行不是合法的 JSON", "This line is not valid JSON")
        self.raises(tasksets.image_bytes, (line(None), 0), ValueError, "这张图没有地址", "This image has no URL")
        self.raises(tasksets.image_bytes, (line("http://x/a.png"), 0), tasksets.RemoteImage,
                    "这张图是网址形式，只显示网址，不在这里下载", "This image is a URL; only the URL is shown and it is not downloaded here")
        self.raises(tasksets.image_bytes, (line("data:image/png,x"), 0), ValueError, "不是 base64 格式的 data URL", "Not a base64 data URL")
        self.raises(tasksets.image_bytes, (line("data:image/png;base64,abc"), 0), ValueError, "base64 数据已损坏",
                    "The base64 data is corrupted")
        data, ctype = tasksets.image_bytes(line("data:image/png;base64," + b64(png_of(30, 30))), 0)
        self.assertEqual((ctype, data[:4]), ("image/png", b"\x89PNG"))

    def test_missing_image_is_a_plural_sentence_about_how_many_there_are(self):
        """「这一行没有第 N 张图（一共 M 张）」是带数量的句子 (tn): 一共 0 张 / 1 张 / 多张。"""
        def line(n):
            parts = [{"type": "image_url", "image_url": {"url": "http://x/%d.png" % i}} for i in range(n)]
            return '{"messages": [{"role": "user", "content": %s}]}' % json.dumps(parts)
        cases = [(0, 0, "这一行没有第 1 张图（一共 0 张）", "This line has no image 1 (it has 0 images in total)"),
                 (1, 1, "这一行没有第 2 张图（一共 1 张）", "This line has no image 2 (it has 1 image in total)"),
                 (2, 5, "这一行没有第 6 张图（一共 2 张）", "This line has no image 6 (it has 2 images in total)"),
                 (2, -1, "这一行没有第 0 张图（一共 2 张）", "This line has no image 0 (it has 2 images in total)")]
        for n, idx, zh, en in cases:
            with self.subTest(images=n, idx=idx):
                self.raises(tasksets.image_bytes, (line(n), idx), LookupError, zh, en)

    def test_scan_cache_is_keyed_by_language(self):
        p = os.path.join(temp_dir(), "x.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            f.write("not json\n")
        tasksets._scan_cached.cache_clear()
        key = tasksets.stat_key(p)
        with i18n.use_lang("zh"):
            a = tasksets.scan(*key)
            self.assertIs(tasksets.scan(*key), a)
        with i18n.use_lang("en"):
            b = tasksets.scan(*key)
        self.assertIsNot(a, b)
        with i18n.use_lang("zh"):
            self.assertIs(tasksets.scan(*key), a)
        tasksets._scan_cached.cache_clear()


# ================================================================ 8. 旧数据里的中文标记

class TestLegacyDataMarker(unittest.TestCase):
    """旧版评测程序在模型没给出正式回答时, 把「（无正文…」存进逐题记录的 tail。现在没有代码会写它, 但库里的旧数据还有,
    server.py 要继续认得 (这是数据, 不翻译, 登记在允许清单里)。"""

    def test_rec_summary_and_answer_still_recognise_it(self):
        it = {"ok": False, "tail": "（无正文：模型只输出了思考内容）", "finish": "length"}
        self.assertEqual(server._rec_summary(it)["has"], "empty")
        a = server._answer_of(it, None, None)
        self.assertEqual((a["text"], a["full"]), ("", True))
        other = {"ok": False, "tail": "ends with this"}
        self.assertEqual(server._rec_summary(other)["has"], "tail")                     # 别的旧数据: 结尾 240 字
        self.assertEqual(server._answer_of(other, None, None)["text"], "ends with this")


if __name__ == "__main__":
    unittest.main()
