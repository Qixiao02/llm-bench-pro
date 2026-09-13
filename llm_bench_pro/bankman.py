#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bankman.py — 智力测试题库管理器
职责: 从官方源拉取题集 -> 固定抽样 -> 生成本地版本化题库 banks/iq-<date>-<hash>.json
特性: 多镜像回退(ghproxy/jsdelivr)、版本标记、同版本永不变、多版本共存可切换。
"""
import csv
import hashlib
import io
import json
import os
import random
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根(包上一级)
BANKS = os.path.join(ROOT, "banks")

# 官方源定义(GitHub raw + 两个国内可达镜像前缀)
MIRRORS = [
    "https://raw.githubusercontent.com/{repo}/{branch}/{path}",
    "https://mirror.ghproxy.com/https://raw.githubusercontent.com/{repo}/{branch}/{path}",
    "https://fastly.jsdelivr.net/gh/{repo}@{branch}/{path}",
]
MMLU_SUBJECTS = [
    ("abstract_algebra", "抽象代数"),
    ("college_physics", "大学物理"),
    ("high_school_world_history", "世界历史"),
    ("professional_law", "职业法律"),
    ("econometrics", "计量经济"),
    ("machine_learning", "机器学习"),
]
GSM8K_REPO_PATH = ("openai/grade-school-math", "grade_school_math/data/test.jsonl")
MMLU_REPO = "hendrycks/test"



_LAST_REQ = [0.0]
_PROXY = [None]


def _throttle(gap=2.2):
    import time as _t
    wait = _LAST_REQ[0] + gap - _t.time()
    if wait > 0:
        _t.sleep(wait)
    _LAST_REQ[0] = _t.time()


def _get(url, timeout=90):
    """限速 GET(间隔2.2s), 429/5xx 长退避重试, 可选走代理。"""
    import time as _t
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(
        {"http": _PROXY[0], "https": _PROXY[0]})) if _PROXY[0] else urllib.request.build_opener()
    for attempt in range(5):
        _throttle()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "llm-bench-pro/1.0"})
            with opener.open(req, timeout=timeout) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 4:
                _t.sleep(10.0 * (attempt + 1))
                continue
            raise
    raise RuntimeError("多镜像均失败(限速重试耗尽)")
def fetch(repo, path, branch="master"):
    """多镜像回退拉取文本, 全部失败抛异常。"""
    last = None
    for tpl in MIRRORS:
        url = tpl.format(repo=repo, path=path, branch=branch)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "llm-bench-pro/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read().decode("utf-8")
            if len(data) > 200 and ("404" not in data[:60]):
                return data
            last = "empty body from " + url
        except Exception as e:
            last = "%s: %s" % (url, str(e)[:100])
    raise RuntimeError("all mirrors failed: %s" % last)


def parse_gsm8k(text, n, rng):
    items = []
    for line in text.splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        m = re.search(r"####\s*([\d,.\-]+)", d.get("answer", ""))
        if not m:
            continue
        ans = m.group(1).replace(",", "").rstrip(".")
        items.append({"q": d["question"].strip(), "answer": ans})
    rng.shuffle(items)
    return items[:n]


def fetch_mmlu_api(subject, n, rng):
    """MMLU 官方数据(HF cais/mmlu)经 datasets-server JSON API 拉取, 纯标准库。"""
    url = (f"https://datasets-server.huggingface.co/rows?dataset=cais%2Fmmlu"
           f"&config={subject}&split=test&offset=0&length={max(n * 2, 80)}")
    d = json.loads(_get(url))
    letters = "ABCD"
    items = []
    for row in d.get("rows", []):
        x = row.get("row", {})
        ch, ans = x.get("choices"), x.get("answer")
        if not ch or len(ch) != 4 or ans is None:
            continue
        items.append({"q": x["question"].strip(), "choices": [str(c) for c in ch],
                      "answer": letters[int(ans)]})
    rng.shuffle(items)
    return items[:n]



def ds_rows(dataset, config, split, length=100, offset=0):
    """通用 HF datasets-server JSON API 拉取(限速+重试), 纯标准库。"""
    url = (f"https://datasets-server.huggingface.co/rows?dataset={dataset.replace('/', '%2F')}"
           f"&config={config}&split={split}&offset={offset}&length={length}")
    return [x.get("row", {}) for x in json.loads(_get(url)).get("rows", [])]


def fetch_arc(n, rng):
    items = []
    for off in (0, 100, 200):
        for x in ds_rows("allenai/ai2_arc", "ARC-Challenge", "test", 100, off):
            ch, key = x.get("choices", {}).get("text"), x.get("answerKey", "")
            if not ch or len(ch) != 4:
                continue
            if key in "1234":
                key = "ABCD"[int(key) - 1]
            if key not in "ABCD":
                continue
            items.append({"q": x["question"].strip(), "choices": [str(c) for c in ch], "answer": key})
    rng.shuffle(items)
    return items[:n]


def fetch_hellaswag(n, rng):
    items = []
    for off in (0, 100, 200, 300):
        for x in ds_rows("Rowan/hellaswag", "default", "validation", 100, off):
            ctx, endings, label = (x.get("ctx") or "").strip(), x.get("endings") or [], x.get("label")
            if not ctx or len(endings) != 4 or label in (None, ""):
                continue
            items.append({"q": ctx + chr(10) + "（选出最合理的后续）",
                          "choices": [str(e) for e in endings], "answer": "ABCD"[int(label)]})
    rng.shuffle(items)
    return items[:n]


def fetch_math500(n, rng):
    items = []
    for off in (0, 100, 200, 300, 400):
        for x in ds_rows("HuggingFaceH4/MATH-500", "default", "test", 100, off):
            q, ans = (x.get("problem") or "").strip(), (x.get("answer") or "").strip()
            if q and ans:
                items.append({"q": q, "answer": ans})
    rng.shuffle(items)
    return items[:n]


def fetch_ceval(n_per, rng, subjects):
    items_all = []
    for sub in subjects:
        try:
            for x in ds_rows("ceval/ceval-exam", sub, "val", 25):
                if not all(x.get(k) for k in "ABCD") or x.get("answer", "") not in "ABCD":
                    continue
                items_all.append({"q": x["question"].strip(),
                                  "choices": [x["A"], x["B"], x["C"], x["D"]], "answer": x["answer"]})
        except Exception:
            continue
    rng.shuffle(items_all)
    return items_all[:n_per * len(subjects)]


MMLU_ALL = ["abstract_algebra","anatomy","astronomy","business_ethics","clinical_knowledge","college_biology",
    "college_chemistry","college_computer_science","college_mathematics","college_medicine","college_physics",
    "computer_security","conceptual_physics","econometrics","electrical_engineering","elementary_mathematics",
    "formal_logic","global_facts","high_school_biology","high_school_chemistry","high_school_computer_science",
    "high_school_european_history","high_school_geography","high_school_government_and_politics",
    "high_school_macroeconomics","high_school_mathematics","high_school_microeconomics","high_school_physics",
    "high_school_psychology","high_school_statistics","high_school_us_history","high_school_world_history",
    "human_aging","human_sexuality","international_law","jurisprudence","logical_fallacies","machine_learning",
    "management","marketing","medical_genetics","miscellaneous","moral_disputes","moral_scenarios","nutrition",
    "philosophy","prehistory","professional_accounting","professional_law","professional_medicine",
    "professional_psychology","public_relations","security_studies","sociology","us_foreign_policy","virology","world_religions"]
CEVAL_SUBS = ["high_school_physics","high_school_mathematics","high_school_chemistry",
    "high_school_biology","high_school_history","high_school_politics",
    "logic","law","medicine","computer_network"]


def ifeval_zh_items():
    """指令遵循(IFEval 风格, 中文): 每题挂可程序化校验的约束。"""
    return [
        {"q": "用不超过50个字介绍量子计算。", "checks": [{"t": "max_chars", "v": 50}]},
        {"q": "用恰好3个要点说明喝水的好处，每个要点一行，以'1.'、'2.'、'3.'开头。", "checks": [{"t": "regex", "v": r"1\..+\n2\..+\n3\."}, {"t": "min_chars", "v": 20}]},
        {"q": "输出一个合法的JSON对象，包含键 name 和 age，不要输出其他任何内容。", "checks": [{"t": "json_keys", "v": ["name", "age"]}]},
        {"q": "写一句关于秋天的话，要求整句不超过20个字，且必须包含'落叶'这个词。", "checks": [{"t": "max_chars", "v": 20}, {"t": "contains", "v": "落叶"}]},
        {"q": "把'今天天气很好'翻译成英文，只输出译文。", "checks": [{"t": "regex", "v": r"^[A-Za-z ,.'!?]+$"}, {"t": "max_chars", "v": 60}]},
        {"q": "列出5种颜色，用逗号分隔，不要换行，不要编号。", "checks": [{"t": "line_count", "v": 1}, {"t": "regex", "v": r"^[^,]+,[^,]+,[^,]+,[^,]+,[^,]+$"}]},
        {"q": "写一个python函数签名 def add(a, b): 不需要函数体，只输出这一行。", "checks": [{"t": "regex", "v": r"def add\(a,\s*b\):?"}]},
        {"q": "用英文写一句不超过15个单词的问候语。", "checks": [{"t": "regex", "v": r"^[A-Za-z ,.'!?]+$"}, {"t": "max_words", "v": 15}]},
        {"q": "回答：中国的首都是哪里？答案只写城市名，两个字。", "checks": [{"t": "contains", "v": "北京"}, {"t": "max_chars", "v": 6}]},
        {"q": "将数字 3.14159 四舍五入到两位小数，只输出数字本身。", "checks": [{"t": "regex", "v": r"^3\.14$"}]},
        {"q": "写一个句子同时包含'因为'和'所以'，不超过30字。", "checks": [{"t": "contains", "v": "因为"}, {"t": "contains", "v": "所以"}, {"t": "max_chars", "v": 30}]},
        {"q": "按JSON数组格式输出 [1, 2, 3]，不要多余内容。", "checks": [{"t": "regex", "v": r"^\s*\[\s*1\s*,\s*2\s*,\s*3\s*\]\s*$"}]},
        {"q": "用不超过40字解释什么是缓存。", "checks": [{"t": "max_chars", "v": 40}, {"t": "min_chars", "v": 10}]},
        {"q": "输出今天的英文单词 Wednesday，全大写，不要其他字符。", "checks": [{"t": "regex", "v": r"^WEDNESDAY$"}]},
        {"q": "用中文写一个疑问句，以'吗？'结尾，不超过15字。", "checks": [{"t": "ends_with", "v": "吗？"}, {"t": "max_chars", "v": 15}]},
        {"q": "列出 A、B、C 三个字母，每个一行，不要其他内容。", "checks": [{"t": "regex", "v": r"^A\nB\nC$"}]},
        {"q": "写一个不超过25字的句子，其中不能出现'的'字。", "checks": [{"t": "not_contains", "v": "的"}, {"t": "min_chars", "v": 8}]},
        {"q": "把这句话原样输出：人工智能改变世界。不要加任何标点或解释。", "checks": [{"t": "contains", "v": "人工智能改变世界"}]},
        {"q": "用恰好两句话介绍太阳系，两句之间用句号分隔。", "checks": [{"t": "regex", "v": r"^[^。]+。[^。]+。?$"}]},
        {"q": "输出一个合法的邮箱格式字符串，包含@符号，不超过25字符。", "checks": [{"t": "regex", "v": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"}, {"t": "max_chars", "v": 25}]},
        {"q": "从1数到5，数字之间用空格分隔，只输出这一行。", "checks": [{"t": "regex", "v": r"^1 2 3 4 5$"}]},
        {"q": "写一句不超过20字的句子描述春天，必须以'春天'开头。", "checks": [{"t": "starts_with", "v": "春天"}, {"t": "max_chars", "v": 20}]},
        {"q": "用JSON输出 {\"ok\": true}，不要输出任何其他内容。", "checks": [{"t": "json_keys", "v": ["ok"]}]},
        {"q": "解释什么是API，要求恰好40字以上60字以下。", "checks": [{"t": "min_chars", "v": 40}, {"t": "max_chars", "v": 60}]},
        {"q": "只输出一个字：好。不要任何其他内容。", "checks": [{"t": "regex", "v": r"^好。?$"}]},
        {"q": "写三个英文单词，每个单词首字母大写，用空格分隔。", "checks": [{"t": "regex", "v": r"^[A-Z][a-z]+ [A-Z][a-z]+ [A-Z][a-z]+$"}]},
        {"q": "回答 9 乘 9 等于多少，只输出阿拉伯数字。", "checks": [{"t": "regex", "v": r"^81$"}]},
        {"q": "用不超过15个字回答：光速大约是多少万公里每秒？只输出数字。", "checks": [{"t": "contains", "v": "30"}]},
        {"q": "列出周一到周日的英文缩写，逗号分隔，全部大写，一行输出。", "checks": [{"t": "regex", "v": r"^MON,\s*TUE,\s*WED,\s*THU,\s*FRI,\s*SAT,\s*SUN$"}]},
        {"q": "写一句10字以上、包含'数据'一词的陈述句。", "checks": [{"t": "contains", "v": "数据"}, {"t": "min_chars", "v": 10}]},
    ]


def build(gsm8k_n=150, mmlu_per=8, arc_n=80, hellaswag_n=80, math500_n=80,
          ceval_per=4, ifeval_n=30, seed=42, proxy=None):
    """发布级题库: MMLU全57科 + GSM8K + MATH-500 + ARC + HellaSwag + C-Eval中文 + IFEval。"""
    _PROXY[0] = (proxy or None)
    os.makedirs(BANKS, exist_ok=True)
    rng = random.Random(seed)
    subjects = []

    raw = fetch(*GSM8K_REPO_PATH)
    subjects.append({"id": "gsm8k", "name": "GSM8K 数学(官方)", "type": "math",
                     "items": parse_gsm8k(raw, gsm8k_n, rng)})

    buckets = {"mmlu_school": [], "mmlu_college": [], "mmlu_pro": [], "mmlu_misc": []}
    bname = {"mmlu_school": "MMLU 中学(官方)", "mmlu_college": "MMLU 大学(官方)",
             "mmlu_pro": "MMLU 专业(官方)", "mmlu_misc": "MMLU 通识(官方)"}
    letters = "ABCD"
    mmlu_rows = []
    pages = max(3, (mmlu_per * 57 + 99) // 100)
    for page in range(pages):
        try:
            mmlu_rows.extend(ds_rows("cais/mmlu", "all", "test", 100, page * 100))
        except Exception:
            break
    rng.shuffle(mmlu_rows)
    per_bucket = {k: mmlu_per * 14 for k in buckets}
    for x in mmlu_rows:
        ch, ans, sub = x.get("choices"), x.get("answer"), x.get("subject", "")
        if not ch or len(ch) != 4 or ans is None:
            continue
        if sub.startswith(("elementary", "high_school", "middle")):
            key = "mmlu_school"
        elif sub.startswith("college"):
            key = "mmlu_college"
        elif sub.startswith("professional"):
            key = "mmlu_pro"
        else:
            key = "mmlu_misc"
        if len(buckets[key]) >= per_bucket[key]:
            continue
        buckets[key].append({"q": x["question"].strip(), "choices": [str(c) for c in ch],
                             "answer": letters[int(ans)], "sub": sub})
    ok_subs = len({x.get("sub") for b in buckets.values() for x in b})
    for bid in ("mmlu_school", "mmlu_college", "mmlu_pro", "mmlu_misc"):
        subjects.append({"id": bid, "name": bname[bid], "type": "mcq", "items": buckets[bid]})

    subjects.append({"id": "math500", "name": "MATH-500 竞赛数学(官方)", "type": "math500",
                     "items": fetch_math500(math500_n, rng)})
    subjects.append({"id": "arc", "name": "ARC-Challenge 科学推理(官方)", "type": "mcq",
                     "items": fetch_arc(arc_n, rng)})
    subjects.append({"id": "hellaswag", "name": "HellaSwag 常识(官方)", "type": "mcq",
                     "items": fetch_hellaswag(hellaswag_n, rng)})
    subjects.append({"id": "ceval", "name": "C-Eval 中文知识(官方)", "type": "mcq",
                     "items": fetch_ceval(ceval_per, rng, CEVAL_SUBS)})
    subjects.append({"id": "ifeval_zh", "name": "指令遵循 IFEval风格(中文)", "type": "instruct",
                     "items": ifeval_zh_items()[:ifeval_n]})

    manifest = "gsm8k:%d|mmlu4:%dx%d|math500:%d|arc:%d|hellaswag:%d|ceval:%dx%d|ifeval:%d|seed:%d" % (
        gsm8k_n, ok_subs, mmlu_per, math500_n, arc_n, hellaswag_n, len(CEVAL_SUBS), ceval_per, ifeval_n, seed)
    h = hashlib.sha256(manifest.encode()).hexdigest()[:8]
    bank = {
        "bank_id": "iq-%s-%s" % (time.strftime("%Y%m%d"), h),
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "manifest": manifest, "seed": seed,
        "total": sum(len(s["items"]) for s in subjects),
        "subjects": subjects,
    }
    path = os.path.join(BANKS, bank["bank_id"] + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(bank, f, ensure_ascii=False, separators=(",", ":"))
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


if __name__ == "__main__":
    b, p = build()
    print("built:", b["bank_id"], "| total:", b["total"], "=>", p)
