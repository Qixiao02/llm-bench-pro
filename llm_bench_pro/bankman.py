#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bankman.py — 能力评测题库管理器
职责: 从公开数据源拉取题集 -> 固定抽样 -> 生成本地版本化题库 banks/iq-<内容哈希>.json
特性: 多镜像回退、每个数据源独立随机种子(一个源变化不影响其他源的抽样)、拉取失败直接报错不静默降级、
      同内容同 id、多版本共存可切换。
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
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根(包上一级)
BANKS = os.path.join(ROOT, "banks")

# 官方源定义(GitHub raw + 两个国内可达镜像前缀)
MIRRORS = [
    "https://raw.githubusercontent.com/{repo}/{branch}/{path}",
    "https://mirror.ghproxy.com/https://raw.githubusercontent.com/{repo}/{branch}/{path}",
    "https://fastly.jsdelivr.net/gh/{repo}@{branch}/{path}",
]
GSM8K_REPO_PATH = ("openai/grade-school-math", "grade_school_math/data/test.jsonl")




_LAST_REQ = [0.0]
_PROXY = [None]


def _throttle(gap=2.2):
    import time as _t
    wait = _LAST_REQ[0] + gap - _t.time()
    if wait > 0:
        _t.sleep(wait)
    _LAST_REQ[0] = _t.time()


def _opener():
    """按 _PROXY 构建 opener; 未设代理时沿用系统环境代理。"""
    if _PROXY[0]:
        return urllib.request.build_opener(urllib.request.ProxyHandler({"http": _PROXY[0], "https": _PROXY[0]}))
    return urllib.request.build_opener()


def _get(url, timeout=90):
    """限速 GET(间隔2.2s), 429/5xx 长退避重试, 可选走代理。"""
    import time as _t
    opener = _opener()
    for attempt in range(5):
        _throttle()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "llm-bench-pro/1.0"})
            with opener.open(req, timeout=timeout) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                _t.sleep(10.0 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, OSError):  # 连接失败/超时同样退避重试
            if attempt < 4:
                _t.sleep(5.0 * (attempt + 1))
                continue
            raise
    raise RuntimeError("请求重试耗尽: %s" % url)



def fetch(repo, path, branch="master"):
    """多镜像回退拉取文本, 全部失败抛异常。"""
    last = None
    opener = _opener()
    for tpl in MIRRORS:
        url = tpl.format(repo=repo, path=path, branch=branch)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "llm-bench-pro/1.0"})
            with opener.open(req, timeout=60) as r:
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
            if key in ("1", "2", "3", "4"):
                key = "ABCD"[int(key) - 1]
            if key not in ("A", "B", "C", "D"):
                continue
            items.append({"q": x["question"].strip(), "choices": [str(c) for c in ch], "answer": key})
    rng.shuffle(items)
    return items[:n]


def fetch_hellaswag(n, rng):
    items = []
    for off in (0, 100, 200, 300):
        for x in ds_rows("Rowan/hellaswag", "default", "validation", 100, off):
            ctx, endings, label = (x.get("ctx") or "").strip(), x.get("endings") or [], x.get("label")
            if not ctx or len(endings) != 4 or str(label) not in ("0", "1", "2", "3"):
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
    """每科取 n_per 题(科目内打乱后抽取), 拉取失败直接报错。"""
    items_all = []
    for sub in subjects:
        rows = [x for x in ds_rows("ceval/ceval-exam", sub, "val", 100)
                if all(x.get(k) for k in "ABCD") and x.get("answer") in ("A", "B", "C", "D")]
        if len(rows) < n_per:
            raise RuntimeError("C-Eval 科目 %s 有效题目不足 %d 道" % (sub, n_per))
        rng.shuffle(rows)
        items_all += [{"q": x["question"].strip(), "choices": [x["A"], x["B"], x["C"], x["D"]],
                       "answer": x["answer"], "sub": sub} for x in rows[:n_per]]
    return items_all


def fetch_mmlu(per_subject, rng):
    """按科目逐个拉取 cais/mmlu 的 test split, 每科抽 per_subject 题, 分四组。
    (旧实现只取 all 配置的前几页, 该配置按科目字母序拼接, 实际只覆盖前几个科目。)"""
    buckets = {"mmlu_school": [], "mmlu_college": [], "mmlu_pro": [], "mmlu_misc": []}
    for sub in MMLU_ALL:
        rows = [x for x in ds_rows("cais/mmlu", sub, "test", 100)
                if x.get("choices") and len(x["choices"]) == 4 and str(x.get("answer")) in ("0", "1", "2", "3")]
        if len(rows) < per_subject:
            raise RuntimeError("MMLU 科目 %s 有效题目不足 %d 道" % (sub, per_subject))
        rng.shuffle(rows)
        if sub.startswith(("elementary", "high_school", "middle")):
            key = "mmlu_school"
        elif sub.startswith("college"):
            key = "mmlu_college"
        elif sub.startswith("professional"):
            key = "mmlu_pro"
        else:
            key = "mmlu_misc"
        buckets[key] += [{"q": x["question"].strip(), "choices": [str(c) for c in x["choices"]],
                          "answer": "ABCD"[int(x["answer"])], "sub": sub} for x in rows[:per_subject]]
    return buckets


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
          ceval_per=4, ifeval_n=30, seed=42, proxy=None):
    """构建题库: MMLU 57 科(分四组) + GSM8K + MATH-500 + ARC-Challenge + HellaSwag + C-Eval + 中文指令遵循。
    每个数据源使用独立随机种子; 任一数据源拉取失败直接抛错, 不生成残缺题库。"""
    _PROXY[0] = (proxy or None)
    os.makedirs(BANKS, exist_ok=True)
    rng = lambda name: random.Random("%s:%s" % (seed, name))  # noqa: E731
    subjects = []

    raw = fetch(*GSM8K_REPO_PATH)
    subjects.append({"id": "gsm8k", "name": "GSM8K 数学", "type": "math", "items": parse_gsm8k(raw, gsm8k_n, rng("gsm8k"))})

    buckets = fetch_mmlu(mmlu_per, rng("mmlu"))
    bname = {"mmlu_school": "MMLU 中学", "mmlu_college": "MMLU 大学", "mmlu_pro": "MMLU 专业", "mmlu_misc": "MMLU 通识"}
    for bid in ("mmlu_school", "mmlu_college", "mmlu_pro", "mmlu_misc"):
        subjects.append({"id": bid, "name": bname[bid], "type": "mcq", "items": buckets[bid]})

    subjects.append({"id": "math500", "name": "MATH-500 竞赛数学", "type": "math500",
                     "items": fetch_math500(math500_n, rng("math500"))})
    subjects.append({"id": "arc", "name": "ARC-Challenge 科学推理", "type": "mcq", "items": fetch_arc(arc_n, rng("arc"))})
    subjects.append({"id": "hellaswag", "name": "HellaSwag 常识", "type": "mcq",
                     "items": fetch_hellaswag(hellaswag_n, rng("hellaswag"))})
    subjects.append({"id": "ceval", "name": "C-Eval 中文知识", "type": "mcq",
                     "items": fetch_ceval(ceval_per, rng("ceval"), CEVAL_SUBS)})
    subjects.append({"id": "ifeval_zh", "name": "指令遵循（中文）", "type": "instruct", "items": ifeval_zh_items()[:ifeval_n]})
    for sub in subjects:
        if not sub["items"]:
            raise RuntimeError("题集 %s 为空，题库未生成" % sub["id"])

    manifest = "gsm8k:%d|mmlu:%dx%d|math500:%d|arc:%d|hellaswag:%d|ceval:%dx%d|ifeval:%d|seed:%d" % (
        gsm8k_n, len(MMLU_ALL), mmlu_per, math500_n, arc_n, hellaswag_n, len(CEVAL_SUBS), ceval_per, ifeval_n, seed)
    # 版本号只取内容哈希: 同内容同 id(与构建日期无关), 上游数据变动则 id 必变, 不会覆盖旧版本
    content = json.dumps(subjects, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    h = hashlib.sha256((manifest + "\n" + content).encode()).hexdigest()[:12]
    bank = {
        "bank_id": "iq-%s" % h,
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
