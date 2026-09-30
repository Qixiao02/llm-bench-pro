#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bankman.py — 能力评测题库管理器

分两步, 第二步完全不需要网络:
  1. download(): 把各题集的原始数据下载到本地 data/datasets/(已下载的跳过)。
     默认用魔搭(ModelScope)加载脚本里的数据地址(阿里云 OSS, 国内直连); 不通时依次回退到
     GitHub(国内镜像同时测速, 用最快的)、hf-mirror、HuggingFace。大压缩包只取需要的文件
     (按 zip 目录 / tar 文件头分段下载), 不整包下载。
  2. build(): 只读本地数据, 固定抽样生成版本化题库 banks/iq-<内容哈希>.json。

离线使用: 本地数据齐全时 build() 不访问网络; 没有网的机器, 把能联网机器上的 data/datasets/ 拷过去即可。
同一份上游数据无论从哪个源下载, 本地保存的格式一样, 抽出来的题完全相同(同内容同 id)。
"""
import csv
import hashlib
import io
import json
import os
import random
import re
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

try:
    from . import i18n  # 包内导入
except ImportError:
    import i18n  # server.py 以包目录为 sys.path 顶层导入

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根(包上一级)
BANKS = os.path.join(ROOT, "banks")
DATASETS = os.path.join(ROOT, "data", "datasets")  # 下载到本地的原始数据(不入库)
UA = "llm-bench-pro/1.0"

# ---- 下载源 ----
# 魔搭加载脚本(modelscope/<数据集>/<数据集>.py)里写的数据地址: 阿里云 OSS, 国内直连快
MS_OSS = "https://modelscope.oss-cn-beijing.aliyuncs.com/open_data/"
MS_OSS_HZ = "https://sail-moe.oss-cn-hangzhou.aliyuncs.com/open_data/"
MS_FILE = "https://www.modelscope.cn/api/v1/datasets/{repo}/repo?Revision=master&FilePath={path}"
HF_MIRROR_FILE = "https://hf-mirror.com/datasets/{repo}/resolve/main/{path}"
HF_ROWS = "https://datasets-server.huggingface.co/rows?dataset={ds}&config={cfg}&split={split}&offset={off}&length={n}"
GH_RAW = "https://raw.githubusercontent.com/{repo}/{branch}/{path}"
# GitHub 国内镜像(按常见可用度排列, 实际按测速结果用最快的); 直连 GitHub 放最后
GH_MIRRORS = ["https://gh-proxy.com/{raw}", "https://ghproxy.net/{raw}", "https://ghfast.top/{raw}",
              "https://cdn.jsdelivr.net/gh/{repo}@{branch}/{path}", "https://fastly.jsdelivr.net/gh/{repo}@{branch}/{path}"]
SOURCE_MODES = {"modelscope": "魔搭（国内）", "global": "GitHub / HuggingFace（海外）"}
SMALL_FILE = 8 << 20  # 比这小的压缩包整个下载; 更大的按目录 / 文件头分段只取需要的部分

# 每个题集抽样时用前多少行: 与最初(HuggingFace 按页取)的取法一致, 题库内容才能和以前完全相同
TAKE = {"mmlu": 100, "arc": 300, "hellaswag": 400, "ceval": 100}

MMLU_ALL = ["abstract_algebra", "anatomy", "astronomy", "business_ethics", "clinical_knowledge", "college_biology",
            "college_chemistry", "college_computer_science", "college_mathematics", "college_medicine", "college_physics",
            "computer_security", "conceptual_physics", "econometrics", "electrical_engineering", "elementary_mathematics",
            "formal_logic", "global_facts", "high_school_biology", "high_school_chemistry", "high_school_computer_science",
            "high_school_european_history", "high_school_geography", "high_school_government_and_politics",
            "high_school_macroeconomics", "high_school_mathematics", "high_school_microeconomics", "high_school_physics",
            "high_school_psychology", "high_school_statistics", "high_school_us_history", "high_school_world_history",
            "human_aging", "human_sexuality", "international_law", "jurisprudence", "logical_fallacies", "machine_learning",
            "management", "marketing", "medical_genetics", "miscellaneous", "moral_disputes", "moral_scenarios", "nutrition",
            "philosophy", "prehistory", "professional_accounting", "professional_law", "professional_medicine",
            "professional_psychology", "public_relations", "security_studies", "sociology", "us_foreign_policy", "virology",
            "world_religions"]
# C-Eval 没有叫 medicine 的科目(医学类是 basic_medicine / clinical_medicine / physician); 以前写错,
# 导致「更新题集」每次都在 C-Eval 这一步失败
CEVAL_SUBS = ["high_school_physics", "high_school_mathematics", "high_school_chemistry",
              "high_school_biology", "high_school_history", "high_school_politics",
              "logic", "law", "basic_medicine", "computer_network"]

# 题集: id → (显示名, 来源说明)。README 与 banks/README.md 里有各数据集的许可
DATASET_NAMES = {"gsm8k": "GSM8K", "mmlu": "MMLU", "math500": "MATH-500", "arc": "ARC-Challenge",
                 "hellaswag": "HellaSwag", "ceval": "C-Eval"}


class Cancelled(Exception):
    """用户停止了题集更新。"""


class Ctx:
    """一次下载 / 生成的上下文: 代理、下载源偏好、进度输出、停止信号、流量统计。"""

    def __init__(self, proxy=None, mode="modelscope", log=None, cancel=None):
        self.proxy = proxy or None
        self.mode = mode if mode in SOURCE_MODES else "modelscope"
        self._log, self.cancel = log, cancel
        self.bytes = 0
        handlers = [urllib.request.ProxyHandler({"http": self.proxy, "https": self.proxy})] if self.proxy else []
        self.opener = urllib.request.build_opener(*handlers)

    def log(self, msg):
        if self._log:
            self._log(msg)

    def check(self):
        if self.cancel is not None and self.cancel.is_set():
            raise Cancelled("已停止")

    def open(self, url, rng=None, timeout=30):
        headers = {"User-Agent": UA}
        if rng:
            headers["Range"] = "bytes=%d-%d" % rng
        return self.opener.open(urllib.request.Request(url, headers=headers), timeout=timeout)

    def get(self, url, rng=None, timeout=60):
        """GET 整个文件或一段(rng=(起, 止) 含止)。服务器不支持分段时只在需要的范围很靠前时接受整读。"""
        self.check()
        with self.open(url, rng, timeout) as r:
            if rng and r.status != 206:
                if rng[0] > (8 << 20):
                    raise RuntimeError("服务器不支持分段下载")
                data = r.read(rng[1] + 1)[rng[0]:]
            else:
                out = []
                while True:
                    self.check()
                    b = r.read(1 << 20)
                    if not b:
                        break
                    out.append(b)
                data = b"".join(out)
        self.bytes += len(data)
        return data

    def size(self, url):
        """远程文件大小(用 Range: bytes=0-0 的 Content-Range 取得)。"""
        with self.open(url, (0, 0), 20) as r:
            m = re.search(r"/(\d+)$", r.headers.get("Content-Range") or "")
            if r.status == 206 and m:
                return int(m.group(1))
            raise RuntimeError("服务器不支持分段下载")


class RangeFile(io.RawIOBase):
    """只读、可 seek 的远程文件: 按块用 HTTP Range 读取(带缓存), 交给 zipfile 只下载目录和需要的成员。"""

    def __init__(self, ctx, url, size=None, block=256 * 1024):
        self.ctx, self.url, self.block = ctx, url, block
        self.length = size if size is not None else ctx.size(url)
        self.pos, self.cache = 0, {}

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = {0: off, 1: self.pos + off, 2: self.length + off}[whence]
        return self.pos

    def _block(self, i):
        if i not in self.cache:
            a = i * self.block
            self.cache[i] = self.ctx.get(self.url, (a, min(self.length, a + self.block) - 1))
        return self.cache[i]

    def readinto(self, b):
        n = min(len(b), max(0, self.length - self.pos))
        got = 0
        while got < n:
            i, o = divmod(self.pos + got, self.block)
            chunk = self._block(i)[o:o + n - got]
            if not chunk:
                break
            b[got:got + len(chunk)] = chunk
            got += len(chunk)
        self.pos += got
        return got


def zip_members(ctx, url, want):
    """从远程 zip 里只取出 want(name) 为真的成员 → {成员名: bytes}(小文件整包下载, 大文件按目录分段取)。"""
    size = ctx.size(url)
    fp = io.BytesIO(ctx.get(url)) if size <= SMALL_FILE else RangeFile(ctx, url, size)
    with zipfile.ZipFile(fp) as z:
        out = {}
        for info in z.infolist():
            ctx.check()
            if not info.is_dir() and want(info.filename):
                out[info.filename] = z.read(info)
        return out


def tar_members(ctx, url, want, done=None):
    """按 tar 文件头逐个跳读远程 tar: 需要的文件连续成片读取, 用不上的大文件直接跳过(不下载)。
    want(name) 决定要不要; done(已取出的 dict) 为真就提前结束。返回 {成员名: bytes}。"""
    size = ctx.size(url)
    buf_off, buf, window, off, out = 0, b"", 256 * 1024, 0, {}
    long_name = None

    def read(a, n):
        nonlocal buf_off, buf
        if buf_off <= a and a + n <= buf_off + len(buf):
            return buf[a - buf_off:a - buf_off + n]
        buf, buf_off = ctx.get(url, (a, min(size, a + max(n, window)) - 1)), a
        return buf[:n]

    while off + 512 <= size:
        ctx.check()
        hd = read(off, 512)
        if len(hd) < 512 or not hd.strip(b"\0"):
            break  # 结束块
        name = hd[:100].split(b"\0", 1)[0].decode("utf-8", "replace")
        prefix = hd[345:500].split(b"\0", 1)[0].decode("utf-8", "replace") if hd[257:262] == b"ustar" else ""
        name = long_name or (prefix + "/" + name if prefix else name)
        long_name = None
        sz = int(hd[124:136].split(b"\0", 1)[0].strip() or b"0", 8)
        typ, data_off = hd[156:157], off + 512
        if typ == b"L":  # GNU 长文件名: 内容是下一个成员的名字
            long_name = read(data_off, sz).split(b"\0", 1)[0].decode("utf-8", "replace")
        elif typ in (b"0", b"\0") and want(name):
            out[name] = read(data_off, sz)
            window = min(window * 2, 8 << 20)  # 连着要的小文件: 每次多读一些
            if done and done(out):
                break
        elif sz > window:
            window = 64 * 1024  # 跳过了大文件: 下一次只读文件头附近
        off = data_off + (sz + 511) // 512 * 512
    return out


def jsonl(text):
    return [json.loads(x) for x in text.splitlines() if x.strip()]


def csv_rows(text, header=True):
    rd = csv.reader(io.StringIO(text))
    rows = list(rd)
    if header and rows:
        head = rows[0]
        return [dict(zip(head, r)) for r in rows[1:]]
    return rows


# ---- 各途径 ----
def gh_text(ctx, repo, branch, path):
    """GitHub 文件: 国内镜像和直连同时测速(各取前 1KB), 用最快的下载全文; 失败换下一个。"""
    raw = GH_RAW.format(repo=repo, branch=branch, path=path)
    cands = [m.format(raw=raw, repo=repo, branch=branch, path=path) for m in GH_MIRRORS] + [raw]
    if ctx.mode == "global":
        cands = [raw] + cands[:-1]

    def probe(u):
        t = time.time()
        try:
            data = ctx.get(u, (0, 1023), timeout=8)
            return (time.time() - t, u) if data.strip() else None
        except Exception:
            return None
    ctx.check()
    with i18n.executor(len(cands)) as ex:
        ranked = sorted(r for r in ex.map(probe, cands) if r)
    if not ranked:
        raise RuntimeError("GitHub 和它的镜像都连不上")
    last = None
    for _, u in ranked:
        try:
            text = ctx.get(u, timeout=90).decode("utf-8")
            host = urllib.parse.urlsplit(u).netloc
            ctx.log("      用的是 %s" % host)
            return text
        except Cancelled:
            raise
        except Exception as e:
            last = e
    raise RuntimeError("GitHub 镜像下载失败：%s" % last)


_LAST_HF = [0.0]


def hf_rows(ctx, ds, cfg, split, offsets, length=100):
    """HuggingFace datasets-server 按页取行(JSON)。它限流: 请求间隔 2.2 秒, 429/5xx 退避重试。"""
    rows = []
    for off in offsets:
        url = HF_ROWS.format(ds=ds.replace("/", "%2F"), cfg=cfg, split=split, off=off, n=length)
        for attempt in range(5):
            ctx.check()
            wait = _LAST_HF[0] + 2.2 - time.time()
            if wait > 0:
                time.sleep(wait)
            _LAST_HF[0] = time.time()
            try:
                page = json.loads(ctx.get(url, timeout=60)).get("rows", [])
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                    time.sleep(8.0 * (attempt + 1))
                    continue
                raise
        rows += [x.get("row", {}) for x in page]
        if len(page) < length:
            break
    return rows


def _pick(rows, keys):
    return [{k: r.get(k) for k in keys} for r in rows]


def routes_for(ctx, name):
    """(途径名, 取数函数) 列表, 按下载源偏好排序。取数函数返回本地保存用的行(与 HuggingFace 的行同形)。"""
    ms, gl = [], []  # 魔搭(国内) / 海外
    if name == "gsm8k":
        ms.append(("魔搭 OSS", lambda: _pick(jsonl(ctx.get(MS_OSS_HZ + "gsm8k/test.jsonl").decode("utf-8")), ("question", "answer"))))
        gl.append(("GitHub", lambda: _pick(jsonl(gh_text(ctx, "openai/grade-school-math", "master",
                                                          "grade_school_math/data/test.jsonl")), ("question", "answer"))))
        gl.append(("HuggingFace", lambda: _pick(hf_rows(ctx, "openai/gsm8k", "main", "test", range(0, 1400, 100)), ("question", "answer"))))
    elif name == "math500":
        keys = ("problem", "answer", "subject", "level", "unique_id")
        ms.append(("魔搭", lambda: _pick(jsonl(ctx.get(MS_FILE.format(repo="AI-ModelScope/MATH-500", path="test.jsonl")).decode("utf-8")), keys)))
        gl.append(("hf-mirror", lambda: _pick(jsonl(ctx.get(HF_MIRROR_FILE.format(repo="HuggingFaceH4/MATH-500", path="test.jsonl")).decode("utf-8")), keys)))
        gl.append(("HuggingFace", lambda: _pick(hf_rows(ctx, "HuggingFaceH4/MATH-500", "default", "test", range(0, 500, 100)), keys)))
    elif name == "mmlu":
        def from_tar(url):
            def run():
                want = {"data/test/%s_test.csv" % s: s for s in MMLU_ALL}
                got = tar_members(ctx, url, lambda n: n in want, done=lambda d: len(d) == len(want))
                missing = [s for n, s in want.items() if n not in got]
                if missing:
                    raise RuntimeError("压缩包里缺少科目: %s" % ", ".join(missing[:5]))
                out = {}
                for n, s in want.items():
                    rows = csv_rows(got[n].decode("utf-8"), header=False)
                    out[s] = [{"question": r[0], "choices": r[1:5], "answer": "ABCD".index(r[5].strip())}
                              for r in rows if len(r) >= 6 and r[5].strip() in ("A", "B", "C", "D")]
                return out
            return run
        ms.append(("魔搭 OSS", from_tar(MS_OSS + "mmlu/data.tar")))
        ms.append(("魔搭 OSS（杭州）", from_tar(MS_OSS_HZ + "mmlu/data.tar")))
        gl.append(("hf-mirror", from_tar(HF_MIRROR_FILE.format(repo="cais/mmlu", path="data.tar"))))
        gl.append(("HuggingFace", lambda: {s: [{"question": r.get("question"), "choices": r.get("choices"), "answer": r.get("answer")}
                                               for r in hf_rows(ctx, "cais/mmlu", s, "test", [0], TAKE["mmlu"])] for s in MMLU_ALL}))
    elif name == "arc":
        def from_zip():
            got = zip_members(ctx, MS_OSS + "arc/ARC-V1-Feb2018.zip", lambda n: n.endswith("ARC-Challenge/ARC-Challenge-Test.jsonl"))
            if not got:
                raise RuntimeError("压缩包里没有 ARC-Challenge-Test.jsonl")
            return [{"question": d["question"]["stem"],
                     "choices": {"text": [c["text"] for c in d["question"]["choices"]], "label": [c["label"] for c in d["question"]["choices"]]},
                     "answerKey": d.get("answerKey")} for d in jsonl(next(iter(got.values())).decode("utf-8"))]
        ms.append(("魔搭 OSS", from_zip))
        gl.append(("HuggingFace", lambda: _pick(hf_rows(ctx, "allenai/ai2_arc", "ARC-Challenge", "test", range(0, TAKE["arc"], 100)),
                                                ("question", "choices", "answerKey"))))
    elif name == "hellaswag":
        keys = ("ctx", "endings", "label", "activity_label")
        ms.append(("魔搭 OSS", lambda: _pick(jsonl(ctx.get(MS_OSS + "hellaswag/hellaswag_val.jsonl").decode("utf-8")), keys)))
        gl.append(("HuggingFace", lambda: _pick(hf_rows(ctx, "Rowan/hellaswag", "default", "validation", range(0, TAKE["hellaswag"], 100)), keys)))
    elif name == "ceval":
        keys = ("question", "A", "B", "C", "D", "answer")

        def from_zip():
            got = zip_members(ctx, MS_OSS + "c-eval/ceval-exam.zip", lambda n: re.search(r"(^|/)val/[^/]+_val\.csv$", n) is not None)
            out = {}
            for n, data in got.items():
                sub = re.search(r"([^/]+)_val\.csv$", n).group(1)
                out[sub] = _pick(csv_rows(data.decode("utf-8")), keys)
            missing = [s for s in CEVAL_SUBS if s not in out]
            if missing:
                raise RuntimeError("压缩包里缺少科目: %s" % ", ".join(missing))
            return out
        ms.append(("魔搭 OSS", from_zip))
        gl.append(("HuggingFace", lambda: {s: _pick(hf_rows(ctx, "ceval/ceval-exam", s, "val", [0], TAKE["ceval"]), keys) for s in CEVAL_SUBS}))
    return ms + gl if ctx.mode == "modelscope" else gl + ms


def first_ok(ctx, name, routes):
    """按顺序试每个途径, 第一个成功的就用; 都失败时报出每个途径的原因。"""
    errs = []
    for label, fn in routes:
        ctx.check()
        t, b0 = time.time(), ctx.bytes
        try:
            data = fn()
            ctx.log("      %s：从%s下载完成，%.1f MB，%.1f 秒" % (DATASET_NAMES[name], label, (ctx.bytes - b0) / 1048576, time.time() - t))
            return label, data
        except Cancelled:
            raise
        except Exception as e:
            msg = str(e).strip()[:120] or type(e).__name__
            errs.append("%s（%s）" % (label, msg))
            ctx.log("      %s：%s不可用（%s），换下一个" % (DATASET_NAMES[name], label, msg))
    raise RuntimeError("%s 所有下载途径都失败：%s" % (DATASET_NAMES[name], "；".join(errs)))


# ---- 本地数据 ----
def _local_path(name):
    return os.path.join(DATASETS, name + ".json")


def load_local(name):
    """本地保存的题集数据: {"rows": [...] 或 {科目: [...]}, "source", "url", "downloaded_utc"}; 没有返回 None。"""
    try:
        with open(_local_path(name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _enough(name, doc):
    """本地数据够不够生成题库(科目齐全、行数够)。"""
    if not doc or not doc.get("rows"):
        return False
    rows = doc["rows"]
    if name == "mmlu":
        return all(rows.get(s) for s in MMLU_ALL)
    if name == "ceval":
        return all(rows.get(s) for s in CEVAL_SUBS)
    return len(rows) >= {"arc": TAKE["arc"], "hellaswag": TAKE["hellaswag"]}.get(name, 1)


def local_status():
    """每个题集本地数据的情况, 给页面显示「可以离线生成」。"""
    out = []
    for name in DATASET_NAMES:
        doc = load_local(name)
        rows = (doc or {}).get("rows")
        n = sum(len(v) for v in rows.values()) if isinstance(rows, dict) else len(rows or [])
        out.append({"id": name, "name": DATASET_NAMES[name], "ready": _enough(name, doc), "rows": n,
                    "source": (doc or {}).get("source"), "downloaded_utc": (doc or {}).get("downloaded_utc")})
    return {"dir": DATASETS, "datasets": out, "ready": all(x["ready"] for x in out)}


def download(ctx=None, force=False, only=None):
    """把缺少的题集数据下载到本地(force=True 时全部重新下载)。返回下载了哪些。"""
    ctx = ctx or Ctx()
    os.makedirs(DATASETS, exist_ok=True)
    names = [n for n in DATASET_NAMES if not only or n in only]
    done = []
    for i, name in enumerate(names, 1):
        ctx.check()
        ctx.log("进度 %d / %d · %s" % (i - 1, len(names), DATASET_NAMES[name]))
        if not force and _enough(name, load_local(name)):
            ctx.log("  [%d/%d] %s：本地已有，跳过下载" % (i, len(names), DATASET_NAMES[name]))
            continue
        ctx.log("  [%d/%d] %s：开始下载（%s优先）" % (i, len(names), DATASET_NAMES[name], SOURCE_MODES[ctx.mode]))
        label, rows = first_ok(ctx, name, routes_for(ctx, name))
        doc = {"id": name, "source": label, "downloaded_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "rows": rows}
        tmp = _local_path(name) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, _local_path(name))
        done.append(name)
    ctx.log("进度 %d / %d · 数据已在本地" % (len(names), len(names)))
    return done


# ---- 抽样(只用本地数据) ----
def parse_gsm8k(rows, n, rng):
    """rows: [{"question", "answer"}] 或 jsonl 文本(兼容旧调用)。"""
    if isinstance(rows, str):
        rows = jsonl(rows)
    items = []
    for d in rows:
        m = re.search(r"####\s*([\d,.\-]+)", d.get("answer") or "")
        if not m:
            continue
        items.append({"q": d["question"].strip(), "answer": m.group(1).replace(",", "").rstrip(".")})
    rng.shuffle(items)
    return items[:n]


def sample_mmlu(rows_by_sub, per_subject, rng):
    """每科前 TAKE 行里抽 per_subject 题, 分四组(中学 / 大学 / 专业 / 通识)。"""
    buckets = {"mmlu_school": [], "mmlu_college": [], "mmlu_pro": [], "mmlu_misc": []}
    for sub in MMLU_ALL:
        rows = [x for x in (rows_by_sub.get(sub) or [])[:TAKE["mmlu"]]
                if x.get("choices") and len(x["choices"]) == 4 and str(x.get("answer")) in ("0", "1", "2", "3")]
        if len(rows) < per_subject:
            raise RuntimeError("MMLU 科目 %s 有效题目不足 %d 道" % (sub, per_subject))
        rng.shuffle(rows)
        key = ("mmlu_school" if sub.startswith(("elementary", "high_school", "middle")) else
               "mmlu_college" if sub.startswith("college") else "mmlu_pro" if sub.startswith("professional") else "mmlu_misc")
        buckets[key] += [{"q": x["question"].strip(), "choices": [str(c) for c in x["choices"]],
                          "answer": "ABCD"[int(x["answer"])], "sub": sub} for x in rows[:per_subject]]
    return buckets


def sample_arc(rows, n, rng):
    items = []
    for x in rows[:TAKE["arc"]]:
        ch, key = (x.get("choices") or {}).get("text"), x.get("answerKey", "")
        if not ch or len(ch) != 4:
            continue
        if key in ("1", "2", "3", "4"):
            key = "ABCD"[int(key) - 1]
        if key not in ("A", "B", "C", "D"):
            continue
        items.append({"q": x["question"].strip(), "choices": [str(c) for c in ch], "answer": key})
    rng.shuffle(items)
    return items[:n]


def sample_hellaswag(rows, n, rng):
    items = []
    for x in rows[:TAKE["hellaswag"]]:
        ctx_, endings, label = (x.get("ctx") or "").strip(), x.get("endings") or [], x.get("label")
        if not ctx_ or len(endings) != 4 or str(label) not in ("0", "1", "2", "3"):
            continue
        items.append({"q": ctx_ + chr(10) + "（选出最合理的后续）", "choices": [str(e) for e in endings], "answer": "ABCD"[int(label)]})
    rng.shuffle(items)
    return items[:n]


def sample_math500(rows, n, rng):
    items = [{"q": (x.get("problem") or "").strip(), "answer": (x.get("answer") or "").strip()} for x in rows]
    items = [x for x in items if x["q"] and x["answer"]]
    rng.shuffle(items)
    return items[:n]


def sample_ceval(rows_by_sub, n_per, rng, subjects):
    """每科取 n_per 题(科目内打乱后抽取)。"""
    items_all = []
    for sub in subjects:
        rows = [x for x in (rows_by_sub.get(sub) or [])[:TAKE["ceval"]]
                if all(x.get(k) for k in "ABCD") and x.get("answer") in ("A", "B", "C", "D")]
        if len(rows) < n_per:
            raise RuntimeError("C-Eval 科目 %s 有效题目不足 %d 道" % (sub, n_per))
        rng.shuffle(rows)
        items_all += [{"q": x["question"].strip(), "choices": [x["A"], x["B"], x["C"], x["D"]],
                       "answer": x["answer"], "sub": sub} for x in rows[:n_per]]
    return items_all


def ifeval_zh_items():
    """指令遵循(IFEval 风格, 中文): 每题挂可程序化校验的约束。本项目自编, 随代码以 MIT 许可发布。"""
    return [
        {"q": "用不超过50个字介绍量子计算。", "checks": [{"t": "max_chars", "v": 50}]},
        {"q": "用恰好3个要点说明喝水的好处，每个要点一行，以'1.'、'2.'、'3.'开头。", "checks": [{"t": "regex", "v": r"^\s*[*_]*1\.[^\n]+\n+\s*[*_]*2\.[^\n]+\n+\s*[*_]*3\.[^\n]+$"}, {"t": "min_chars", "v": 20}]},
        {"q": "输出一个合法的JSON对象，包含键 name 和 age，不要输出其他任何内容。", "checks": [{"t": "json_keys", "v": ["name", "age"]}]},
        {"q": "写一句关于秋天的话，要求整句不超过20个字，且必须包含'落叶'这个词。", "checks": [{"t": "max_chars", "v": 20}, {"t": "contains", "v": "落叶"}]},
        {"q": "把'今天天气很好'翻译成英文，只输出译文。", "checks": [{"t": "regex", "v": r"^[A-Za-z ,.'’!?]+$"}, {"t": "max_chars", "v": 60}]},
        {"q": "列出5种颜色，用逗号分隔，不要换行，不要编号。", "checks": [{"t": "line_count", "v": 1}, {"t": "regex", "v": r"^[^,，、\n]+(?:\s*[,，、]\s*[^,，、\n]+){4}$"}]},
        {"q": "写一个python函数签名 def add(a, b): 不需要函数体，只输出这一行。", "checks": [{"t": "regex", "v": r"def add\(a,\s*b\):?"}]},
        {"q": "用英文写一句不超过15个单词的问候语。", "checks": [{"t": "regex", "v": r"^[A-Za-z ,.'’!?]+$"}, {"t": "max_words", "v": 15}]},
        {"q": "回答：中国的首都是哪里？答案只写城市名，两个字。", "checks": [{"t": "contains", "v": "北京"}, {"t": "max_chars", "v": 6}]},
        {"q": "将数字 3.14159 四舍五入到两位小数，只输出数字本身。", "checks": [{"t": "regex", "v": r"^3\.14$"}]},
        {"q": "写一个句子同时包含'因为'和'所以'，不超过30字。", "checks": [{"t": "contains", "v": "因为"}, {"t": "contains", "v": "所以"}, {"t": "max_chars", "v": 30}]},
        {"q": "按JSON数组格式输出 [1, 2, 3]，不要多余内容。", "checks": [{"t": "regex", "v": r"^\s*\[\s*1\s*,\s*2\s*,\s*3\s*\]\s*$"}]},
        {"q": "用不超过40字解释什么是缓存。", "checks": [{"t": "max_chars", "v": 40}, {"t": "min_chars", "v": 10}]},
        {"q": "输出今天的英文单词 Wednesday，全大写，不要其他字符。", "checks": [{"t": "regex", "v": r"^WEDNESDAY$"}]},
        {"q": "用中文写一个疑问句，以'吗？'结尾，不超过15字。", "checks": [{"t": "ends_with", "v": "吗？"}, {"t": "max_chars", "v": 15}]},
        {"q": "列出 A、B、C 三个字母，每个一行，不要其他内容。", "checks": [{"t": "regex", "v": r"^A\nB\nC$"}]},
        {"q": "写一个不超过25字的句子，其中不能出现'的'字。", "checks": [{"t": "not_contains", "v": "的"}, {"t": "min_chars", "v": 8}, {"t": "max_chars", "v": 25}]},
        {"q": "把这句话原样输出：人工智能改变世界。不要加任何标点或解释。", "checks": [{"t": "regex", "v": r"^人工智能改变世界。?$"}]},
        {"q": "用恰好两句话介绍太阳系，两句之间用句号分隔。", "checks": [{"t": "regex", "v": r"^[^。！？!?\n]+。[^。！？!?\n]+。?$"}]},
        {"q": "输出一个合法的邮箱格式字符串，包含@符号，不超过25字符。", "checks": [{"t": "regex", "v": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"}, {"t": "max_chars", "v": 25}]},
        {"q": "从1数到5，数字之间用空格分隔，只输出这一行。", "checks": [{"t": "regex", "v": r"^1 2 3 4 5$"}]},
        {"q": "写一句不超过20字的句子描述春天，必须以'春天'开头。", "checks": [{"t": "starts_with", "v": "春天"}, {"t": "max_chars", "v": 20}]},
        {"q": "用JSON输出 {\"ok\": true}，不要输出任何其他内容。", "checks": [{"t": "json_equals", "v": {"ok": True}}]},
        {"q": "解释什么是API，要求恰好40字以上60字以下。", "checks": [{"t": "min_chars", "v": 40}, {"t": "max_chars", "v": 60}]},
        {"q": "只输出一个字：好。不要任何其他内容。", "checks": [{"t": "regex", "v": r"^好。?$"}]},
        {"q": "写三个英文单词，每个单词首字母大写，用空格分隔。", "checks": [{"t": "regex", "v": r"^[A-Z][A-Za-z]* [A-Z][A-Za-z]* [A-Z][A-Za-z]*[.!]?$"}]},
        {"q": "回答 9 乘 9 等于多少，只输出阿拉伯数字。", "checks": [{"t": "regex", "v": r"^81$"}]},
        {"q": "用不超过15个字回答：光速大约是多少万公里每秒？只输出数字。", "checks": [{"t": "regex", "v": r"^\D{0,6}30(?:\.0+)?\D{0,8}$"}, {"t": "max_chars", "v": 15}]},
        {"q": "列出周一到周日的英文缩写，逗号分隔，全部大写，一行输出。", "checks": [{"t": "regex", "v": r"^MON,\s*TUE,\s*WED,\s*THU,\s*FRI,\s*SAT,\s*SUN$"}]},
        {"q": "写一句10字以上、包含'数据'一词的陈述句。", "checks": [{"t": "contains", "v": "数据"}, {"t": "min_chars", "v": 10}, {"t": "not_contains", "v": "？"}, {"t": "not_contains", "v": "?"}]},
    ]


def build(gsm8k_n=150, mmlu_per=8, arc_n=80, hellaswag_n=80, math500_n=80,
          ceval_per=4, ifeval_n=30, seed=42, proxy=None, mode="modelscope", log=None, cancel=None, offline=False,
          out_dir=None):
    """生成题库: 先把缺少的数据下载到本地(offline=True 时不联网, 缺数据直接报错), 再只用本地数据抽样。
    MMLU 57 科(分四组) + GSM8K + MATH-500 + ARC-Challenge + HellaSwag + C-Eval + 中文指令遵循;
    每个数据源使用独立随机种子; 任一数据源缺失直接报错, 不生成残缺题库。"""
    ctx = Ctx(proxy=proxy, mode=mode, log=log, cancel=cancel)
    t0 = time.time()
    missing = [n for n in DATASET_NAMES if not _enough(n, load_local(n))]
    if missing and offline:
        raise RuntimeError("离线模式下本地缺少这些题集的数据：%s。请在能联网的机器上先更新一次题集，"
                           "再把 %s 拷贝过来" % ("、".join(DATASET_NAMES[n] for n in missing), DATASETS))
    if missing:
        ctx.log("下载源：%s；本地缺少 %d 个题集的数据，先下载到 %s" % (SOURCE_MODES[ctx.mode], len(missing), DATASETS))
        download(ctx, only=missing)
    else:
        ctx.log("全部题集的数据都已在本地（%s），不需要联网" % DATASETS)
    ctx.check()
    ctx.log("从本地数据生成题库…")
    rng = lambda name: random.Random("%s:%s" % (seed, name))  # noqa: E731
    rows = {n: load_local(n)["rows"] for n in DATASET_NAMES}
    subjects = [{"id": "gsm8k", "name": "GSM8K 数学", "type": "math", "items": parse_gsm8k(rows["gsm8k"], gsm8k_n, rng("gsm8k"))}]
    buckets = sample_mmlu(rows["mmlu"], mmlu_per, rng("mmlu"))
    bname = {"mmlu_school": "MMLU 中学", "mmlu_college": "MMLU 大学", "mmlu_pro": "MMLU 专业", "mmlu_misc": "MMLU 通识"}
    for bid in ("mmlu_school", "mmlu_college", "mmlu_pro", "mmlu_misc"):
        subjects.append({"id": bid, "name": bname[bid], "type": "mcq", "items": buckets[bid]})
    subjects.append({"id": "math500", "name": "MATH-500 竞赛数学", "type": "math500", "items": sample_math500(rows["math500"], math500_n, rng("math500"))})
    subjects.append({"id": "arc", "name": "ARC-Challenge 科学推理", "type": "mcq", "items": sample_arc(rows["arc"], arc_n, rng("arc"))})
    subjects.append({"id": "hellaswag", "name": "HellaSwag 常识", "type": "mcq", "items": sample_hellaswag(rows["hellaswag"], hellaswag_n, rng("hellaswag"))})
    subjects.append({"id": "ceval", "name": "C-Eval 中文知识", "type": "mcq", "items": sample_ceval(rows["ceval"], ceval_per, rng("ceval"), CEVAL_SUBS)})
    subjects.append({"id": "ifeval_zh", "name": "指令遵循（中文）", "type": "instruct", "items": ifeval_zh_items()[:ifeval_n]})
    for sub in subjects:
        if not sub["items"]:
            raise RuntimeError("题集 %s 为空，题库未生成" % sub["id"])

    manifest = "gsm8k:%d|mmlu:%dx%d|math500:%d|arc:%d|hellaswag:%d|ceval:%dx%d|ifeval:%d|seed:%d" % (
        gsm8k_n, len(MMLU_ALL), mmlu_per, math500_n, arc_n, hellaswag_n, len(CEVAL_SUBS), ceval_per, ifeval_n, seed)
    # 版本号只取内容哈希: 同内容同 id(与构建日期、下载源无关), 上游数据变动则 id 必变, 不会覆盖旧版本
    content = json.dumps(subjects, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    h = hashlib.sha256((manifest + "\n" + content).encode()).hexdigest()[:12]
    bank = {"bank_id": "iq-%s" % h, "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "manifest": manifest, "seed": seed, "total": sum(len(s["items"]) for s in subjects), "subjects": subjects}
    out_dir = out_dir or BANKS
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, bank["bank_id"] + ".json")
    if os.path.isfile(path):
        ctx.log("题库和已有的 %s 完全相同（内容一样，id 一样），不用新增" % bank["bank_id"])
    else:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(bank, f, ensure_ascii=False, separators=(",", ":"))
        ctx.log("已生成新题库 %s" % bank["bank_id"])
    ctx.log("完成：%s，共 %d 题；本次下载 %.1f MB，用时 %.0f 秒" % (bank["bank_id"], bank["total"], ctx.bytes / 1048576, time.time() - t0))
    return bank, path


def list_banks():
    os.makedirs(BANKS, exist_ok=True)
    out = []
    for fn in os.listdir(BANKS):
        if not (fn.startswith("iq-") and fn.endswith(".json")):
            continue
        try:
            with open(os.path.join(BANKS, fn), encoding="utf-8") as f:
                b = json.load(f)
            out.append({"bank_id": b["bank_id"], "created_utc": b.get("created_utc"),
                        "total": b.get("total"), "manifest": b.get("manifest"),
                        "subjects": [{"id": s["id"], "name": s["name"], "n": len(s["items"])} for s in b["subjects"]]})
        except Exception:
            pass
    out.sort(key=lambda b: b.get("created_utc", ""), reverse=True)
    return out


def load_bank(bank_id):
    path = os.path.join(BANKS, bank_id + ".json")
    if not os.path.isfile(path):
        raise FileNotFoundError("题库不存在: " + bank_id)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv=None):
    import argparse
    i18n.preparse_lang(argv)  # 要在创建 argparse 之前: --help 的文字也是 --lang 指定的语言
    ap = argparse.ArgumentParser(description="能力评测题库: 下载数据到本地 / 从本地数据生成题库")
    ap.add_argument("cmd", nargs="?", default="build", choices=["build", "download", "status"],
                    help="build=缺什么下载什么再生成(默认); download=只下载数据; status=看本地数据")
    ap.add_argument("--source", default="modelscope", choices=list(SOURCE_MODES), help="下载源偏好(默认魔搭, 国内)")
    ap.add_argument("--proxy", default=None, help="下载用的 HTTP 代理, 如 http://127.0.0.1:7890")
    ap.add_argument("--offline", action="store_true", help="不联网, 只用本地数据生成")
    ap.add_argument("--force", action="store_true", help="download 时重新下载全部数据")
    i18n.add_lang_arg(ap)
    a = ap.parse_args(argv)
    log = lambda m: print(m, flush=True)  # noqa: E731
    if a.cmd == "status":
        s = local_status()
        for d in s["datasets"]:
            print("%-14s %s  %6d 行  %s" % (d["name"], "已下载" if d["ready"] else "缺少  ", d["rows"], d["source"] or ""))
        print("本地数据目录:", s["dir"], "| 可以离线生成:", "是" if s["ready"] else "否")
        return
    try:
        if a.cmd == "download":
            download(Ctx(proxy=a.proxy, mode=a.source, log=log), force=a.force)
            return
        b, p = build(proxy=a.proxy, mode=a.source, log=log, offline=a.offline)
        print("built:", b["bank_id"], "| total:", b["total"], "=>", p)
    except (RuntimeError, OSError) as e:
        print("失败：%s" % e, flush=True)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("已停止：已经下载好的数据留在本地", flush=True)
        raise SystemExit(130)


if __name__ == "__main__":
    main()
