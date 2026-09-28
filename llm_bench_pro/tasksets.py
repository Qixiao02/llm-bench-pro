# -*- coding: utf-8 -*-
"""任务集: 速度测试「自定义任务集」用的 JSONL 请求文件(每行一个请求)。纯标准库。

1. 名称与导入时间: 文件按内容命名(data/scenario/tasks/scn-<sha12>.jsonl, 写入后不再改),
   名称和导入时间存在旁边的 scn-<sha12>.meta.json(原子写入)。没有元数据的旧文件: 名称用 id, 导入时间用文件修改时间。
2. 逐行索引与统计: 每行的状态、原因、提醒一律来自 bench.check_task_line, 页面上看到的「可用 / 有问题」
   与测试时实际发送的判断完全一致; 行号与上传时的检查报告相同(空行也占行号)。
3. 逐行查看: 按页读出几行, 长文字截断(带 cut 标记), 图片只给格式和宽高, 不把 base64 放进列表数据。
"""
import base64
import bisect
import functools
import json
import os
import re
import threading
from datetime import datetime, timezone

try:
    from . import bench, vision_assets  # 包内导入
except ImportError:
    import bench  # server.py 以包目录为 sys.path 顶层导入
    import vision_assets

ID_RE = re.compile(r"^scn-[0-9a-f]{12}$")
NAME_MAX = 80        # 名称最多几个字
TEXT_MAX = 3000      # 逐行查看时每段文字最多给几个字, 超出的「展开全文」时按行号再取
URL_MAX = 2000       # 网址形式的图片最多显示几个字
PAGE_MAX = 100       # 一页最多几行
FILTERS = ("all", "ok", "bad", "image", "json")
EXTS = (".jsonl", ".json", ".txt", ".ndjson")
# 名称里去掉的字符: 控制字符, 以及会打乱文字方向的不可见字符和 BOM(页面与服务端用同一套规则, 见 app.js tsNameCheck)
_NAME_DROP = re.compile("[\x00-\x1f\x7f-\x9f‪-‮⁦-⁩﻿]")
_META_LOCK = threading.Lock()


# ---------------------------------------------------------------- 名称与元数据

def clean_name(raw):
    """名称: 去掉控制字符和首尾空白。返回 (名称, 错误说明); 没问题时错误说明为空。"""
    name = _NAME_DROP.sub("", str(raw if raw is not None else "")).strip()
    if not name:
        return name, "名称不能为空"
    if len(name) > NAME_MAX:
        return name, "名称最多 %d 个字（现在 %d 个）" % (NAME_MAX, len(name))
    return name, ""


def default_name(filename, fid):
    """导入时的默认名称: 文件名去掉路径和扩展名(.jsonl / .json / .txt), 超长截断, 什么都不剩时用 id。"""
    base = os.path.basename(str(filename or "").replace("\\", "/"))
    root, ext = os.path.splitext(base)
    if ext.lower() in EXTS:
        base = root
    elif base.lower() in EXTS:  # 文件名只有扩展名, 比如 ".jsonl"
        base = ""
    name, _ = clean_name(base)
    return name[:NAME_MAX].strip() or fid


def file_path(d, fid):
    return os.path.join(d, fid + ".jsonl")


def meta_path(d, fid):
    return os.path.join(d, fid + ".meta.json")


def now_iso():
    return datetime.now(timezone.utc).isoformat()[:19]


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()[:19]


def _load_meta(d, fid):
    try:
        with open(meta_path(d, fid), encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError):
        return {}
    return m if isinstance(m, dict) else {}


def read_meta(d, fid):
    """{name, imported_utc, named}: named=False 表示没有保存过名称(旧文件), 名称暂用 id。"""
    with _META_LOCK:
        m = _load_meta(d, fid)
    out = {"name": fid, "imported_utc": None, "named": False}
    name, _ = clean_name(m.get("name"))
    if name:
        out.update(name=name[:NAME_MAX], named=True)
    if isinstance(m.get("imported_utc"), str) and m["imported_utc"]:
        out["imported_utc"] = m["imported_utc"][:40]
    else:
        try:
            out["imported_utc"] = _iso(os.path.getmtime(file_path(d, fid)))
        except OSError:
            pass
    return out


def write_meta(d, fid, **fields):
    """合并写入元数据(先写临时文件再改名, 写到一半不会留下坏文件)。值为 None 的字段不改。"""
    path = meta_path(d, fid)
    with _META_LOCK:
        cur = _load_meta(d, fid)
        cur.update({k: v for k, v in fields.items() if v is not None})
        tmp = "%s.%d.tmp" % (path, threading.get_ident())
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False)
        os.replace(tmp, path)
        return dict(cur)


def on_import(d, fid, filename, existed):
    """导入后的元数据: 新文件记下名称(默认用文件名)和导入时间; 内容相同的旧文件已经有名称就不动, 没有就补上。"""
    if not existed:
        write_meta(d, fid, name=default_name(filename, fid), imported_utc=now_iso())
    else:
        m = read_meta(d, fid)
        if not m["named"]:
            write_meta(d, fid, name=default_name(filename, fid), imported_utc=m["imported_utc"])
    return read_meta(d, fid)


def remove(d, fid):
    """删除任务集文件和它的元数据; 返回是否删掉了任务集文件。"""
    gone = False
    with _META_LOCK:
        for p in (file_path(d, fid), meta_path(d, fid)):
            try:
                os.remove(p)
                gone = gone or p.endswith(".jsonl")
            except FileNotFoundError:
                pass
    return gone


def list_ids(d):
    """目录里的任务集 id(按文件名排序)。"""
    if not os.path.isdir(d):
        return []
    return sorted(fn[:-6] for fn in os.listdir(d) if fn.endswith(".jsonl") and ID_RE.match(fn[:-6]))


_FS_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]+')


def download_name(name, fid):
    """下载时的文件名: 任务集名称 + .jsonl; 文件名里不能用的字符换成下划线。"""
    base = _FS_BAD.sub("_", str(name or "")).strip(" .")[:NAME_MAX] or fid
    return base + ".jsonl"


# ---------------------------------------------------------------- 逐行索引

_SEP = re.compile(rb"\r\n|\r|\n")
_BOM = b"\xef\xbb\xbf"


def iter_lines(data):
    """文件字节 -> [(行号, 起, 止)]: 与 bench.check_task_text 的行号一致(开头的 BOM 去掉, 空行也占一个行号)。"""
    pos = 0
    while data.startswith(_BOM, pos):
        pos += 3
    out, no = [], 0
    for m in _SEP.finditer(data, pos):
        no += 1
        out.append((no, pos, m.start()))
        pos = m.end()
    out.append((no + 1, pos, len(data)))
    return out


def messages_of(obj):
    msgs = obj.get("messages") if isinstance(obj, dict) else None
    return msgs if isinstance(msgs, list) else []


def image_urls(obj):
    """这一行的图片地址, 按消息顺序(与 check_task_line 数「第几张图」的顺序相同); 没写地址的记为 None。"""
    out = []
    for m in messages_of(obj):
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    iu = part.get("image_url")
                    url = iu.get("url") if isinstance(iu, dict) else None
                    out.append(url if isinstance(url, str) and url else None)
    return out


def wants_json(obj):
    """这一行要求输出 JSON(params.response_format 是 json_object / json_schema)。"""
    params = obj.get("params") if isinstance(obj, dict) else None
    rf = params.get("response_format") if isinstance(params, dict) else None
    return isinstance(rf, dict) and rf.get("type") in ("json_object", "json_schema")


def input_chars(obj):
    """发给模型的文字有多长(字符数): 各条消息的文字相加, 图片不算。"""
    n = 0
    for m in messages_of(obj):
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, str):
            n += len(content)
        elif isinstance(content, list):
            n += sum(len(p["text"]) for p in content
                     if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str))
    return n


def _texts(obj):
    """消息里的文字和 meta.note(搜索用)。"""
    out = []
    for m in messages_of(obj):
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, str):
            out.append(content)
        elif isinstance(content, list):
            out.extend(p["text"] for p in content
                       if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str))
    meta = obj.get("meta") if isinstance(obj, dict) else None
    if isinstance(meta, dict) and isinstance(meta.get("note"), str):
        out.append(meta["note"])
    return out


# 每行一条: (行号, 起, 止, 状态 ok/skip/bad, 原因, 提醒, 要求 JSON, 图片张数, 输入字符数, 实际 max_tokens, 搜索用的小写文字)
NO, START, END, ST, REASON, WARNS, JSON_, NIMG, CHARS, MT, HAY = range(11)


def scan_file(path):
    """读一遍任务集文件: 每行的判断(与测试时实际发送相同) + 汇总统计。"""
    with open(path, "rb") as f:
        data = f.read()
    rows, mt_unset = [], 0
    for no, a, b in iter_lines(data):
        text = data[a:b].decode("utf-8", "replace")
        if not text.strip():
            continue
        c = bench.check_task_line(text)
        obj = c["rec"]
        if obj is None:
            try:
                obj = json.loads(text)
            except ValueError:
                obj = None
        ok = c["status"] == "ok"
        params = obj.get("params") if isinstance(obj, dict) else None
        if ok and not (isinstance(params, dict) and (params.get("max_tokens") is not None
                                                     or params.get("max_completion_tokens") is not None)):
            mt_unset += 1
        hay = "\n".join(_texts(obj)) if isinstance(obj, dict) else text
        rows.append((no, a, b, c["status"], c["reason"], tuple(c["warns"]), wants_json(obj), len(image_urls(obj)),
                     input_chars(obj) if ok else None, bench.task_max_tokens(params) if ok else None, hay.lower()))
    summary = _summarize(rows)
    summary["mt_unset"] = mt_unset  # 可用的行里有几行没写 max_tokens(按默认值发送)
    return {"rows": rows, "nos": [r[NO] for r in rows], "summary": summary}


def _summarize(rows):
    valid = [r for r in rows if r[ST] == "ok"]
    chars = sorted(r[CHARS] for r in valid)
    mts = {}
    for r in valid:
        mts[r[MT]] = mts.get(r[MT], 0) + 1
    out = {"total": len(rows), "valid": len(valid), "skipped": sum(1 for r in rows if r[ST] == "skip"),
           "bad": sum(1 for r in rows if r[ST] == "bad"), "json": sum(1 for r in valid if r[JSON_]),
           "image": sum(1 for r in valid if r[NIMG]), "warning_count": sum(len(r[WARNS]) for r in rows),
           "chars_avg": round(sum(chars) / len(chars), 1) if chars else None,
           "chars_min": chars[0] if chars else None, "chars_max": chars[-1] if chars else None,
           "chars_med": (chars[(len(chars) - 1) // 2] + chars[len(chars) // 2]) / 2.0 if chars else None,
           # 每行实际发送的 max_tokens: 各个值有几行(多的在前)
           "mt_dist": sorted(([v, n] for v, n in mts.items()), key=lambda x: (-x[1], x[0]))}
    return out


@functools.lru_cache(maxsize=2)
def scan(path, size, mtime_ns):
    """逐行索引(含搜索用的文字): 按 (路径, 大小, 修改时间) 缓存最近看过的两个文件, 翻页、筛选、看图不用每次重读。"""
    return scan_file(path)


def stat_key(path):
    st = os.stat(path)
    return path, st.st_size, st.st_mtime_ns


# ---------------------------------------------------------------- 筛选与分页

def _pick(filt):
    return {"all": lambda r: True, "ok": lambda r: r[ST] == "ok", "bad": lambda r: r[ST] != "ok",
            "image": lambda r: r[NIMG] > 0, "json": lambda r: r[JSON_]}[filt]


def query(s, status="all", q="", offset=0, limit=12):
    """按关键词(消息文字和备注, 不分大小写)和筛选条件取一页。返回 (各筛选条件的行数, 符合条件的行数, 这一页的行)。
    各筛选条件的行数按关键词过滤之后算, 与页面上筛选标签里的数字一致。"""
    q = (q or "").strip().lower()
    scope = [r for r in s["rows"] if q in r[HAY]] if q else s["rows"]
    counts = {f: sum(1 for r in scope if _pick(f)(r)) for f in FILTERS}
    sel = [r for r in scope if _pick(status)(r)]
    return counts, len(sel), sel[offset:offset + limit]


def find(s, no):
    """按行号找到这一行的索引记录; 没有这一行(或是空行)返回 None。"""
    i = bisect.bisect_left(s["nos"], no)
    return s["rows"][i] if i < len(s["nos"]) and s["nos"][i] == no else None


def read_texts(path, rows):
    """按索引记录读出这几行的原文(只读这几行, 不读整个文件)。"""
    out = []
    with open(path, "rb") as f:
        for r in rows:
            f.seek(r[START])
            out.append(f.read(r[END] - r[START]).decode("utf-8", "replace"))
    return out


# ---------------------------------------------------------------- 逐行查看

def _text_part(text, full):
    part = {"t": "text", "text": text}
    if not full and len(text) > TEXT_MAX:
        part.update(text=text[:TEXT_MAX], cut=True, len=len(text))
    return part


def image_info(url):
    """一张图的概况(不带图片数据): data URL 解码后给出格式、宽高、大小和检查结果; 网址只给地址。"""
    if not isinstance(url, str) or not url:
        return {"kind": "bad", "msg": "缺少图片地址"}
    if url.startswith("data:"):
        head, _, payload = url.partition(",")
        if ";base64" not in head or not payload:
            return {"kind": "bad", "msg": "不是 base64 格式的 data URL"}
        try:
            data = base64.b64decode(payload)
        except (ValueError, TypeError):
            return {"kind": "bad", "msg": "base64 数据已损坏"}
        c = vision_assets.check_image(data)
        fmt = c["format"]
        return {"kind": "data", "format": vision_assets.FORMATS[fmt][2] if fmt else None, "width": c["width"],
                "height": c["height"], "bytes": c["bytes"], "ok": c["ok"], "level": c["level"], "msg": c["msg"]}
    if url.startswith(("http://", "https://")):
        return {"kind": "url", "url": url[:URL_MAX], "cut": len(url) > URL_MAX}
    return {"kind": "bad", "msg": "地址应为 data:image/…;base64,… 或 http(s) 网址"}


def _call_name(call):
    """工具调用的函数名(写得不对时是 ?)。"""
    fn = call.get("function") if isinstance(call, dict) else None
    name = fn.get("name") if isinstance(fn, dict) else None
    return str(name or "?")[:60]


def _message_view(m, images, full):
    if not isinstance(m, dict):
        return {"role": None, "parts": [_text_part(json.dumps(m, ensure_ascii=False), full)], "raw": True}
    role = m.get("role") if isinstance(m.get("role"), str) else None
    content, parts = m.get("content"), []
    if isinstance(content, str):
        parts.append(_text_part(content, full))
    elif isinstance(content, list):
        for p in content:
            kind = p.get("type") if isinstance(p, dict) else None
            if kind == "text":
                parts.append(_text_part(p.get("text") if isinstance(p.get("text"), str) else "", full))
            elif kind == "image_url":
                iu = p.get("image_url")
                images.append(image_info(iu.get("url") if isinstance(iu, dict) else None))
                parts.append({"t": "img", "i": len(images) - 1})
            else:
                parts.append({"t": "other", "type": str(kind)[:40] if kind is not None else type(p).__name__})
    elif content is not None:
        parts.append(_text_part(json.dumps(content, ensure_ascii=False), full))
    view = {"role": role, "parts": parts}
    calls = m.get("tool_calls")
    if isinstance(calls, list) and calls:
        view["tool_calls"] = [_call_name(c) for c in calls[:8]]
        view["tool_calls_n"] = len(calls)
    for k in ("name", "tool_call_id"):
        if isinstance(m.get(k), str) and m[k]:
            view[k] = m[k][:80]
    return view


def _small(obj, limit=20000):
    """params / meta 原样给页面; 特别长时(比如很大的 JSON Schema)只留键名和值的类型, 完整内容在「看原始 JSON」里。"""
    try:
        if len(json.dumps(obj, ensure_ascii=False)) <= limit:
            return obj
    except (TypeError, ValueError):
        pass
    return {k: "（%s，太长没有显示）" % type(v).__name__ for k, v in obj.items()}


def line_view(row, text, full=False):
    """页面上一行要显示的内容: 状态、原因、提醒、消息(文字截断, 图片只给概况)、params、meta。"""
    out = {"no": row[NO], "status": row[ST], "reason": row[REASON], "warns": list(row[WARNS]), "json": row[JSON_],
           "chars": row[CHARS], "mt": row[MT], "images": [], "messages": None, "params": None, "meta": None}
    try:
        obj = json.loads(text)
    except ValueError:
        obj = None
    if not isinstance(obj, dict) or not isinstance(obj.get("messages"), list):
        out["raw"] = _text_part(text, full)  # 不是能按消息显示的格式: 给原文
    if isinstance(obj, dict):
        if isinstance(obj.get("messages"), list):
            out["messages"] = [_message_view(m, out["images"], full) for m in obj["messages"]]
        if isinstance(obj.get("params"), dict):
            out["params"] = _small(obj["params"])
        if isinstance(obj.get("meta"), dict):
            out["meta"] = _small(obj["meta"], 4000)
    return out


def pretty(text):
    """「看原始 JSON」: 缩进排好; 很长的 data URL(图片)只留开头。不是合法 JSON 时返回 None。"""
    try:
        obj = json.loads(text)
    except ValueError:
        return None

    def walk(x):
        if isinstance(x, str) and x.startswith("data:") and len(x) > 200:
            return "%s…（共 %d 个字符，这里省略）" % (x[:64], len(x))
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        return x
    return json.dumps(walk(obj), ensure_ascii=False, indent=2)


class RemoteImage(ValueError):
    """网址形式的图片: 页面只显示网址, 服务端不去下载。"""


def image_bytes(text, idx):
    """这一行第 idx 张图(从 0 数)的 (字节, MIME)。只取 data URL 里的图片:
    没有这张图抛 LookupError; 网址形式抛 RemoteImage; 数据坏了或不是能识别的图片抛 ValueError(附原因)。"""
    try:
        obj = json.loads(text)
    except ValueError:
        raise ValueError("这一行不是合法的 JSON")
    urls = image_urls(obj)
    if not 0 <= idx < len(urls):
        raise LookupError("这一行没有第 %d 张图（一共 %d 张）" % (idx + 1, len(urls)))
    url = urls[idx]
    if not url:
        raise ValueError("这张图没有地址")
    if not url.startswith("data:"):
        raise RemoteImage("这张图是网址形式，只显示网址，不在这里下载")
    head, _, payload = url.partition(",")
    if ";base64" not in head or not payload:
        raise ValueError("不是 base64 格式的 data URL")
    try:
        data = base64.b64decode(payload)
    except (ValueError, TypeError):
        raise ValueError("base64 数据已损坏")
    try:
        fmt = vision_assets.image_info(data)[0]
    except vision_assets.ImageError as e:
        raise ValueError(str(e))
    return data, vision_assets.FORMATS[fmt][0]
