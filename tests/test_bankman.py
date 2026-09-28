# -*- coding: utf-8 -*-
"""题集下载与离线生成: 本地模拟服务器(支持 Range), 不访问外网。"""
import io
import json
import os
import re
import tarfile
import threading
import unittest
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from _util import temp_dir
import bankman


class FileServer:
    """按路径提供内存里的文件, 支持 Range(206)、404; 记录每个路径实际发出的字节数。"""

    def __init__(self, files):
        self.files, self.sent, self.hits = dict(files), {}, []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                outer.hits.append(self.path)
                data = outer.files.get(path)
                if callable(data):
                    data = data(self.path)
                if data is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                m = re.match(r"bytes=(\d+)-(\d+)", self.headers.get("Range") or "")
                if m:
                    a, b = int(m.group(1)), min(int(m.group(2)), len(data) - 1)
                    body = data[a:b + 1]
                    self.send_response(206)
                    self.send_header("Content-Range", "bytes %d-%d/%d" % (a, b, len(data)))
                else:
                    body = data
                    self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                outer.sent[path] = outer.sent.get(path, 0) + len(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def junk(n):
    return os.urandom(n)  # 随机内容, 压缩不了: 用来当「用不上的大文件」


def make_tar(members):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as t:
        for name, data in members:
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            t.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def make_zip(members, stored_big=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members:
            z.writestr(name, data, compress_type=zipfile.ZIP_STORED if name == stored_big else zipfile.ZIP_DEFLATED)
    return buf.getvalue()


SUBS_MMLU = ["anatomy", "college_physics", "high_school_biology", "professional_law"]  # 四个分组各一科
SUBS_CEVAL = ["logic", "law"]


def fixtures():
    """一套很小的「上游数据」: 与真实文件同格式(jsonl / tar 里的 csv / zip 里的 jsonl 和 csv)。"""
    gsm = "".join(json.dumps({"question": "Q%d ?" % i, "answer": "step\n#### %d" % (i * 7)}) + "\n" for i in range(12))
    math = "".join(json.dumps({"problem": "P%d" % i, "solution": "s", "answer": str(i), "subject": "Algebra", "level": 1 + i % 5,
                               "unique_id": "u%d" % i}) + "\n" for i in range(10))
    mmlu_csv = {s: "".join('"%s q%d, with comma",a%d,b%d,c%d,d%d,%s\n' % (s, i, i, i, i, i, "ABCD"[i % 4]) for i in range(9)) for s in SUBS_MMLU}
    tar = make_tar([("data/README.txt", b"x")] + [("data/val/%s_val.csv" % s, b"v,1,2,3,4,A\n") for s in SUBS_MMLU] +
                   [("data/auxiliary_train/big.csv", junk(3 << 20))] +
                   [("data/test/%s_test.csv" % s, mmlu_csv[s].encode()) for s in SUBS_MMLU] +
                   [("data/dev/%s_dev.csv" % s, b"d,1,2,3,4,B\n") for s in SUBS_MMLU])
    arc = "".join(json.dumps({"id": "a%d" % i, "question": {"stem": "Why %d?" % i, "choices": [{"text": "t%d%s" % (i, L), "label": L} for L in "ABCD"]},
                              "answerKey": "ABCD"[i % 4]}) + "\n" for i in range(8))
    arc_zip = make_zip([("ARC-V1-Feb2018-2/ARC_Corpus.txt", junk(2 << 20)),
                        ("ARC-V1-Feb2018-2/ARC-Challenge/ARC-Challenge-Test.jsonl", arc.encode())], stored_big="ARC-V1-Feb2018-2/ARC_Corpus.txt")
    hs = "".join(json.dumps({"ind": i, "activity_label": "act", "ctx": "ctx %d" % i, "endings": ["e1", "e2", "e3", "e4"], "label": i % 4}) + "\n"
                 for i in range(8))
    ceval_zip = make_zip([("val/%s_val.csv" % s, ("id,question,A,B,C,D,answer,explanation\n" +
                                                   "".join("%d,%s 题 %d,甲,乙,丙,丁,%s,\n" % (i, s, i, "ABCD"[i % 4]) for i in range(6))).encode())
                          for s in SUBS_CEVAL + ["physician"]])
    return {"gsm": gsm, "math": math, "tar": tar, "arc_zip": arc_zip, "hs": hs, "ceval_zip": ceval_zip,
            "mmlu_csv": mmlu_csv, "arc": arc}


class BankmanCase(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures()
        fx = self.fx
        self.srv = FileServer({
            "/sail/open_data/gsm8k/test.jsonl": fx["gsm"].encode(),
            "/ms/api/v1/datasets/AI-ModelScope/MATH-500/repo": fx["math"].encode(),
            "/bj/open_data/mmlu/data.tar": fx["tar"],
            "/bj/open_data/arc/ARC-V1-Feb2018.zip": fx["arc_zip"],
            "/bj/open_data/hellaswag/hellaswag_val.jsonl": fx["hs"].encode(),
            "/bj/open_data/c-eval/ceval-exam.zip": fx["ceval_zip"],
        })
        u = self.srv.url
        self.saved = {k: getattr(bankman, k) for k in ("MS_OSS", "MS_OSS_HZ", "MS_FILE", "HF_MIRROR_FILE", "HF_ROWS", "GH_RAW",
                                                        "GH_MIRRORS", "MMLU_ALL", "CEVAL_SUBS", "DATASETS", "BANKS")}
        self.saved_take, self.saved_small = dict(bankman.TAKE), bankman.SMALL_FILE
        bankman.SMALL_FILE = 256 * 1024
        bankman.MS_OSS, bankman.MS_OSS_HZ = u + "/bj/open_data/", u + "/sail/open_data/"
        bankman.MS_FILE = u + "/ms/api/v1/datasets/{repo}/repo?Revision=master&FilePath={path}"
        bankman.HF_MIRROR_FILE = u + "/hfm/{repo}/{path}"
        bankman.HF_ROWS = u + "/rows?dataset={ds}&config={cfg}&split={split}&offset={off}&length={n}"
        bankman.GH_RAW = u + "/gh/{repo}/{branch}/{path}"
        bankman.GH_MIRRORS = [u + "/mirror1/{raw}", u + "/mirror2/{raw}"]
        bankman.MMLU_ALL, bankman.CEVAL_SUBS = list(SUBS_MMLU), list(SUBS_CEVAL)
        bankman.TAKE.update({"mmlu": 8, "arc": 6, "hellaswag": 6, "ceval": 5})
        d = temp_dir()
        bankman.DATASETS, bankman.BANKS = os.path.join(d, "datasets"), os.path.join(d, "banks")
        self.kw = dict(gsm8k_n=5, mmlu_per=2, arc_n=3, hellaswag_n=3, math500_n=4, ceval_per=2, ifeval_n=5)

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(bankman, k, v)
        bankman.TAKE.clear()
        bankman.TAKE.update(self.saved_take)
        bankman.SMALL_FILE = self.saved_small
        self.srv.close()

    def test_zip_and_tar_only_fetch_needed_parts(self):
        """压缩包只取需要的文件: zip 按目录分段读, tar 跳过用不上的大文件, 都不整包下载。"""
        ctx = bankman.Ctx()
        got = bankman.zip_members(ctx, self.srv.url + "/bj/open_data/arc/ARC-V1-Feb2018.zip", lambda n: n.endswith("ARC-Challenge-Test.jsonl"))
        self.assertEqual(list(got.values())[0].decode(), self.fx["arc"])
        self.assertLess(self.srv.sent["/bj/open_data/arc/ARC-V1-Feb2018.zip"], 600 * 1024)   # 压缩包 2 MB+
        want = {"data/test/%s_test.csv" % s for s in SUBS_MMLU}
        got = bankman.tar_members(ctx, self.srv.url + "/bj/open_data/mmlu/data.tar", lambda n: n in want, done=lambda d: len(d) == len(want))
        self.assertEqual(set(got), want)
        self.assertEqual(got["data/test/anatomy_test.csv"].decode(), self.fx["mmlu_csv"]["anatomy"])
        self.assertLess(self.srv.sent["/bj/open_data/mmlu/data.tar"], 1 << 20)                 # 跳过了 3 MB 的大文件

    def test_download_then_build_offline_without_network(self):
        """先下载到本地, 之后断网也能生成同一个题库; 本地数据齐全时 build() 根本不联网。"""
        logs = []
        bank, path = bankman.build(log=logs.append, **self.kw)
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(bankman.local_status()["ready"])
        self.assertTrue(any("从魔搭 OSS下载完成" in x for x in logs))
        self.assertEqual({s["id"]: len(s["items"]) for s in bank["subjects"]},
                         {"gsm8k": 5, "mmlu_school": 2, "mmlu_college": 2, "mmlu_pro": 2, "mmlu_misc": 2, "math500": 4, "arc": 3,
                          "hellaswag": 3, "ceval": 4, "ifeval_zh": 5})
        self.assertEqual(sorted({it["sub"] for s in bank["subjects"] if s["id"] == "ceval" for it in s["items"]}), sorted(SUBS_CEVAL))

        def no_net(*a, **k):
            raise AssertionError("不应该联网")
        orig = urllib.request.OpenerDirector.open
        urllib.request.OpenerDirector.open = no_net
        try:
            logs2 = []
            again, _ = bankman.build(log=logs2.append, **self.kw)                # 数据齐全: 不联网
            offline, _ = bankman.build(offline=True, **self.kw)                  # 明确离线
        finally:
            urllib.request.OpenerDirector.open = orig
        self.assertEqual(again["bank_id"], bank["bank_id"])
        self.assertEqual(offline["bank_id"], bank["bank_id"])
        self.assertTrue(any("不需要联网" in x for x in logs2))
        self.assertTrue(any("完全相同" in x for x in logs2))

    def test_offline_with_missing_data_says_what_to_do(self):
        with self.assertRaises(RuntimeError) as cm:
            bankman.build(offline=True, **self.kw)
        self.assertIn("GSM8K", str(cm.exception))
        self.assertIn(bankman.DATASETS, str(cm.exception))

    def test_falls_back_to_next_source(self):
        """魔搭的 GSM8K 不通 → 换 GitHub: 镜像测速, 不通的镜像跳过, 用能用的。"""
        del self.srv.files["/sail/open_data/gsm8k/test.jsonl"]
        raw = "/gh/openai/grade-school-math/master/grade_school_math/data/test.jsonl"
        self.srv.files["/mirror2/" + self.srv.url + raw] = self.fx["gsm"].encode()   # 只有镜像 2 可用
        logs = []
        bankman.download(bankman.Ctx(log=logs.append), only=["gsm8k"])
        self.assertEqual(bankman.load_local("gsm8k")["source"], "GitHub")
        self.assertEqual(len(bankman.load_local("gsm8k")["rows"]), 12)
        self.assertTrue(any("魔搭 OSS不可用" in x and "换下一个" in x for x in logs))

    def test_all_sources_fail_reports_each(self):
        del self.srv.files["/bj/open_data/hellaswag/hellaswag_val.jsonl"]
        with self.assertRaises(RuntimeError) as cm:
            bankman.download(bankman.Ctx(), only=["hellaswag"])
        self.assertIn("魔搭 OSS", str(cm.exception))
        self.assertIn("HuggingFace", str(cm.exception))

    def test_cancel(self):
        ev = threading.Event()
        ev.set()
        with self.assertRaises(bankman.Cancelled):
            bankman.build(cancel=ev, **self.kw)
        self.assertFalse(os.path.isdir(bankman.BANKS) and os.listdir(bankman.BANKS))

    def test_same_items_from_huggingface_rows(self):
        """同一份数据从 HuggingFace 按页取(JSON 行)和从魔搭文件取, 生成的题库完全相同。"""
        a, _ = bankman.build(**self.kw)
        fx = self.fx

        def rows(path):
            q = dict(x.split("=", 1) for x in path.split("?", 1)[1].split("&"))
            ds, cfg, off, n = q["dataset"].replace("%2F", "/"), q["config"], int(q["offset"]), int(q["length"])
            if ds == "openai/gsm8k":
                src = [json.loads(x) for x in fx["gsm"].splitlines()]
            elif ds == "HuggingFaceH4/MATH-500":
                src = [json.loads(x) for x in fx["math"].splitlines()]
            elif ds == "cais/mmlu":
                src = [{"question": r[0], "choices": r[1:5], "answer": "ABCD".index(r[5])} for r in bankman.csv_rows(fx["mmlu_csv"][cfg], header=False)]
            elif ds == "allenai/ai2_arc":
                src = [{"question": d["question"]["stem"], "choices": {"text": [c["text"] for c in d["question"]["choices"]],
                        "label": [c["label"] for c in d["question"]["choices"]]}, "answerKey": d["answerKey"]} for d in map(json.loads, fx["arc"].splitlines())]
            elif ds == "Rowan/hellaswag":
                src = [dict(json.loads(x), label=str(json.loads(x)["label"])) for x in fx["hs"].splitlines()]
            elif ds == "ceval/ceval-exam":
                src = bankman.csv_rows(zipfile.ZipFile(io.BytesIO(fx["ceval_zip"])).read("val/%s_val.csv" % cfg).decode())
            else:
                return None
            return json.dumps({"rows": [{"row": r} for r in src[off:off + n]]}).encode()
        self.srv.files["/rows"] = rows
        for k in list(self.srv.files):
            if k.startswith(("/bj/", "/sail/", "/ms/")):
                del self.srv.files[k]
        bankman.DATASETS = os.path.join(temp_dir(), "datasets")
        bankman._LAST_HF[0] = 0.0
        orig_sleep = bankman.time.sleep
        bankman.time.sleep = lambda s: None                     # 测试里不等 HuggingFace 的限流间隔
        try:
            b, _ = bankman.build(mode="global", **self.kw)
        finally:
            bankman.time.sleep = orig_sleep
        self.assertEqual(b["bank_id"], a["bank_id"])
        self.assertEqual({bankman.load_local(n)["source"] for n in bankman.DATASET_NAMES} - {"GitHub", "hf-mirror"}, {"HuggingFace"})


class ModuleCase(unittest.TestCase):
    def test_ceval_subjects_exist(self):
        """C-Eval 的科目名必须是真实存在的配置(以前写成了不存在的 medicine, 更新题集每次失败)。"""
        real = {"computer_network", "operating_system", "computer_architecture", "college_programming", "college_physics",
                "college_chemistry", "advanced_mathematics", "probability_and_statistics", "discrete_mathematics", "electrical_engineer",
                "metrology_engineer", "high_school_mathematics", "high_school_physics", "high_school_chemistry", "high_school_biology",
                "middle_school_mathematics", "middle_school_biology", "middle_school_physics", "middle_school_chemistry",
                "veterinary_medicine", "college_economics", "business_administration", "marxism", "mao_zedong_thought",
                "education_science", "teacher_qualification", "high_school_politics", "high_school_geography", "middle_school_politics",
                "middle_school_geography", "modern_chinese_history", "ideological_and_moral_cultivation", "logic", "law",
                "chinese_language_and_literature", "art_studies", "professional_tour_guide", "legal_professional", "high_school_chinese",
                "high_school_history", "middle_school_history", "civil_servant", "sports_science", "plant_protection", "basic_medicine",
                "clinical_medicine", "urban_and_rural_planner", "accountant", "fire_engineer", "environmental_impact_assessment_engineer",
                "tax_accountant", "physician"}
        self.assertEqual(set(bankman.CEVAL_SUBS) - real, set())
        self.assertEqual(len(bankman.MMLU_ALL), 57)

    def test_default_source_is_modelscope(self):
        ctx = bankman.Ctx()
        self.assertEqual(ctx.mode, "modelscope")
        for name in bankman.DATASET_NAMES:
            self.assertTrue(bankman.routes_for(ctx, name)[0][0].startswith("魔搭"), name)
        self.assertTrue(bankman.routes_for(bankman.Ctx(mode="global"), "gsm8k")[0][0] == "GitHub")


if __name__ == "__main__":
    unittest.main()
