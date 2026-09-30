# -*- coding: utf-8 -*-
"""模型管理: 保存的模型服务(名称 / 服务地址 / API Key / 模型名称)。纯标准库。

1. 保存时的检查: 名称、地址、模型名称、Key 的规则(页面上有同样的规则, 见 app.js mdFormCheck)。
2. 同一个服务的不同写法算同一个: runs 表里的 url 可能是完整的 .../v1/chat/completions, 也可能是 base;
   保存的地址可能带 /v1。比较前一律规整成一个键(url_key)。
3. 在测试里用过几次: 一次查出所有测试的 (类型, 地址, 模型, 开始时间), 在这里按 (地址键, 模型) 分组, 不按模型逐个查库。
4. 最近用它跑过的测试: 每次测试一行摘要(速度: 最高总生成速度; 能力: 正确率; 代码生成: 完成几题、检查通过率)。
5. 测试连接失败: 按异常类型分成 timeout / refused / auth / not_found …, 页面按 code 写成大白话(app.js mdFailText)。
"""
import errno
import functools
import http.client
import json
import re
import socket
import ssl
import urllib.error
import urllib.parse

try:
    from . import bench, gen_specs, i18n  # 包内导入
except ImportError:
    import bench  # server.py 以包目录为 sys.path 顶层导入
    import gen_specs
    import i18n

t = i18n.t

ID_RE = re.compile(r"^ep_[A-Za-z0-9_]{1,60}$")
NAME_MAX = 64       # 名称最多几个字(按字数, 不按字节)
MODEL_MAX = 128     # 模型名称最多几个字
URL_MAX = 500       # 服务地址最多几个字
KEY_MAX = 8192      # API Key 最多几个字
RUNS_MAX = 50       # 「最近用它跑过的测试」最多列几次
KINDS = ("perf", "iq", "gen")
# 名称和模型名称里去掉的字符: 控制字符, 以及会打乱文字方向的不可见字符和 BOM(与任务集名称同一套)
_DROP = re.compile("[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069\ufeff]")
_URL_OK = re.compile(r"^https?://[^\s/?#@]+(?:[/?#]\S*)?$", re.IGNORECASE)
_HOST = re.compile(r"^https?://([^/?#]+)", re.IGNORECASE)


class NotModelList(ValueError):
    """/v1/models 返回的不是模型列表(不是 OpenAI 兼容接口)。"""


def bad_url():
    """服务地址写法不对时的说明 (按当前语言生成, 所以是函数, 不是模块级常量)。"""
    return t("服务地址要以 http:// 或 https:// 开头，中间不能有空格，比如 http://127.0.0.1:8000")


# ---------------------------------------------------------------- 保存时的检查

def url_ok(url):
    """地址能不能用: http:// 或 https:// 开头、有主机、端口是数字、中间没有空白(不带用户名密码)。"""
    if not isinstance(url, str) or not _URL_OK.match(url):
        return False
    try:
        u = urllib.parse.urlsplit(url)
        u.port  # 端口不是数字或超出范围时抛 ValueError
    except ValueError:
        return False
    return bool(u.hostname)


def host_of(url):
    """地址里的主机和端口(列表里只显示这一段)。"""
    m = _HOST.match(str(url or ""))
    return m.group(1) if m else str(url or "")


def mask_key(key):
    """Key 的遮住形式(与 app.js maskKey 同一套): 16 个字以上露头尾各 4 个, 8–15 个露头尾各 2 个, 更短的全遮住。"""
    key = str(key or "")
    n = len(key)
    if not n:
        return ""
    if n >= 16:
        return key[:4] + "…" + key[-4:]
    if n >= 8:
        return key[:2] + "…" + key[-2:]
    return "••••"


def default_name(model, url):
    """名称不填时用「模型 · 主机」, 超长截断。"""
    return ("%s · %s" % (model, host_of(url)))[:NAME_MAX].strip()


def clean_fields(body):
    """保存一个模型时的字段: 返回 (字段, 错误说明); 有错时字段为 None。
    - 服务地址: 必填, 去掉首尾空白; 要以 http:// 或 https:// 开头、有主机、中间不能有空白;
      末尾的 /v1 或 /v1/chat/completions 去掉(测试时会自动加上)
    - 模型名称: 必填, 去掉控制字符和首尾空白, 最多 128 个字
    - 名称: 可以不填(用「模型 · 主机」), 去掉控制字符和首尾空白, 最多 64 个字
    - API Key: 可以不填, 去掉首尾空白(复制时常带上换行); 中间不能有换行等控制字符(放不进请求头)"""
    for k in ("name", "url", "api_key", "model"):
        v = body.get(k)
        if v is not None and not isinstance(v, str):
            return None, t("{field} 应为文字", field=k)
    url = (body.get("url") or "").strip()
    if not url:
        return None, t("服务地址不能为空")
    if len(url) > URL_MAX:
        return None, t("服务地址最多 {limit} 个字（现在 {n} 个）", limit=URL_MAX, n=len(url))
    if not url_ok(url):
        return None, bad_url()
    url = bench.normalize_base(url)
    model = _DROP.sub("", body.get("model") or "").strip()
    if not model:
        return None, t("模型名称不能为空")
    if len(model) > MODEL_MAX:
        return None, t("模型名称最多 {limit} 个字（现在 {n} 个）", limit=MODEL_MAX, n=len(model))
    name = _DROP.sub("", body.get("name") or "").strip()
    if len(name) > NAME_MAX:
        return None, t("名称最多 {limit} 个字（现在 {n} 个）", limit=NAME_MAX, n=len(name))
    key = (body.get("api_key") or "").strip()
    if len(key) > KEY_MAX:
        return None, t("API Key 最多 {limit} 个字", limit=KEY_MAX)
    if re.search(r"[\x00-\x1f\x7f]", key):
        return None, t("API Key 中间不能有换行或其他控制字符")
    return {"name": name or default_name(model, url), "url": url, "api_key": key, "model": model}, ""


# ---------------------------------------------------------------- 在测试里用过几次

@functools.lru_cache(maxsize=2048)
def url_key(url):
    """地址 → 比较用的键: 先用 bench.normalize_base 去掉末尾的 /v1、/v1/chat/completions 和 /,
    协议和主机不分大小写, localhost 和 ::1 当作 127.0.0.1, 没写端口时补上默认端口(http 80 / https 443)。"""
    b = bench.normalize_base(str(url or ""))
    try:
        u = urllib.parse.urlsplit(b)
        host, port = (u.hostname or "").lower(), u.port
    except ValueError:  # 端口不是数字之类, 解析不了: 按原文比较
        return b.lower()
    scheme = u.scheme.lower()
    if not scheme or not host:
        return b.lower()
    if host in ("localhost", "::1"):
        host = "127.0.0.1"
    return "%s://%s:%d%s" % (scheme, host, port or {"https": 443}.get(scheme, 80), u.path.rstrip("/"))


def target_key(url, model):
    return url_key(str(url or "")), str(model or "").strip()


def usage(targets):
    """targets: [(run_id, 类型, 地址, 模型, 开始时间), ...](store.run_targets, 一次查出)
    → {(地址键, 模型): {"perf": 次数, "iq": 次数, "gen": 次数, "last_utc": 最近一次的开始时间}}。"""
    out = {}
    for _, kind, url, model, started in targets:
        if kind not in KINDS:
            continue
        g = out.setdefault(target_key(url, model), {"perf": 0, "iq": 0, "gen": 0, "last_utc": None})
        g[kind] += 1
        if started and (not g["last_utc"] or started > g["last_utc"]):
            g["last_utc"] = started
    return out


def uses_of(ep, groups):
    """某个保存的模型在测试里用过几次: {perf, iq, gen, total, last_utc}。"""
    g = groups.get(target_key(ep.get("url"), ep.get("model"))) or {}
    out = {k: g.get(k, 0) for k in KINDS}
    out.update(total=sum(out.values()), last_utc=g.get("last_utc"))
    return out


def matching_runs(targets, ep, kind="all"):
    """用这个模型(地址和模型名称都对上)跑过的测试 id, 新的在前; kind 为 perf / iq / gen 时只要这一类。
    返回 (全部对上的 [(run_id, 类型)], 各类次数)。"""
    key = target_key(ep.get("url"), ep.get("model"))
    hit = sorted(((started or "", rid, k) for rid, k, url, model, started in targets
                  if k in KINDS and target_key(url, model) == key), reverse=True)
    counts = {k: 0 for k in KINDS}
    for _, _, k in hit:
        counts[k] += 1
    return [(rid, k) for _, rid, k in hit if kind in ("all", k)], counts


# ---------------------------------------------------------------- 用过的测试: 每次一行摘要

def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def perf_summary(phases):
    """速度测试: 最高总生成速度(同时几个请求时)、单个请求的生成速度(中文优先)、模拟业务几类。
    phases: [(阶段 id, 数据或 None)], 只有 concurrency / decode 两个阶段带数据。"""
    s = {"phases": len(phases), "scn": sum(1 for pid, _ in phases if str(pid or "").startswith("scn_"))}
    for pid, d in phases:
        d = d if isinstance(d, dict) else {}
        if pid == "concurrency":
            pts = [p for p in d.get("points") or [] if isinstance(p, dict) and _num(p.get("agg_tps"))]
            if pts:
                best = max(pts, key=lambda p: p["agg_tps"])
                s.update(peak_tps=round(best["agg_tps"], 1), peak_conc=best.get("conc"))
        elif pid == "decode":
            cases = [c for c in d.get("cases") or [] if isinstance(c, dict) and _num(c.get("decode_tps_med"))]
            one = next((c for c in cases if c.get("lang") == "zh"), cases[0] if cases else None)
            if one:
                s["decode_tps"] = round(one["decode_tps_med"], 1)
    return s


def _usable_score(it):
    """作品按「能不能用」得的分(0-100): 只算 能打开 / 不白屏 / 不报错 / 核心操作有反应; 没有实际运行返回 None。
    旧任务的记录里没有 scored 标记, 按检查项现算(规则见 gen_specs.score_checks, 与代码生成页相同)。"""
    e = it.get("eval")
    if not isinstance(e, dict) or e.get("method") != "browser":
        return None
    if isinstance(e.get("checks"), list) and e["checks"]:
        return gen_specs.score_checks(e["checks"], "browser", e.get("control"))["score"]
    return it["exec_score"] if _num(it.get("exec_score")) else None


def gen_summary(items, planned=None):
    """代码生成: 完成几题 / 计划几题、检查通过率(每件作品「能不能用」的得分再求平均, 与代码生成页相同; 没有实际运行的不算)、
    有没有只看了代码(没在浏览器里实际运行)、AI 看图打分的平均分。"""
    done = [it for it in items if isinstance(it, dict) and not it.get("error")]
    execs = [s for s in (_usable_score(it) for it in done) if s is not None]
    judges = [it["judge_score"] for it in done if _num(it.get("judge_score"))]
    methods = {(it.get("eval") or {}).get("method") for it in done if isinstance(it.get("eval"), dict)}
    s = {"done": len(done), "planned": planned if isinstance(planned, int) and planned > 0 else len(items)}
    if execs:
        s["exec"] = round(sum(execs) / len(execs), 1)
    if judges:
        s["judge"] = round(sum(judges) / len(judges), 1)
    if methods:
        s["method"] = "static" if methods == {"static"} else "mixed" if "static" in methods else "browser"
    return s


# ---------------------------------------------------------------- 测试连接失败的原因

_UNREACHABLE = {errno.ENETUNREACH, errno.EHOSTUNREACH, 10051, 10065}  # 后两个是 Windows 的 WSAENETUNREACH / WSAEHOSTUNREACH


def models_of(data):
    """/v1/models 的返回 → [{id, max_model_len}]; 不是 {"data": [...]} 的样子时抛 NotModelList。"""
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise NotModelList(t("返回的不是模型列表（没有 data 数组）"))
    out = []
    for m in items:
        if isinstance(m, dict) and isinstance(m.get("id"), str):
            n = m.get("max_model_len")
            out.append({"id": m["id"], "max_model_len": n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else None})
    return out


def probe_fail(e):
    """测试连接失败 → (code, HTTP 状态码或 None, 原文说明)。
    code: auth(401/403) / not_found(404) / server(5xx) / http(其他状态码) / timeout / refused / dns /
          unreachable / reset / tls / bad_json(返回的不是模型列表) / bad_url / other"""
    if isinstance(e, urllib.error.HTTPError):
        body = ""
        try:
            body = e.read(400).decode("utf-8", "replace").strip()
        except Exception:
            pass
        st = e.code
        code = "auth" if st in (401, 403) else "not_found" if st == 404 else "server" if st >= 500 else "http"
        return code, st, "HTTP %d%s" % (st, (": " + body[:200]) if body else "")
    reason = e.reason if isinstance(e, urllib.error.URLError) else e
    text = "%s: %s" % (type(reason).__name__, str(reason)[:200])
    if isinstance(reason, (socket.timeout, TimeoutError)) or str(reason) == "timed out":
        return "timeout", None, text
    if isinstance(reason, ConnectionRefusedError):
        return "refused", None, text
    if isinstance(reason, socket.gaierror):
        return "dns", None, text
    if isinstance(reason, (ssl.SSLError, ssl.CertificateError)):
        return "tls", None, text
    if isinstance(reason, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
        return "reset", None, text
    if isinstance(reason, OSError) and (reason.errno in _UNREACHABLE or getattr(reason, "winerror", None) in _UNREACHABLE):
        return "unreachable", None, text
    if isinstance(e, (NotModelList, json.JSONDecodeError, UnicodeDecodeError)):
        return "bad_json", None, text
    if isinstance(e, http.client.InvalidURL):
        return "bad_url", None, text
    return "other", None, text
