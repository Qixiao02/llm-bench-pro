#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llm-bench-pro — 离线压测报告生成 (自包含 HTML, 内联 SVG, 无 JS/外链, 打印友好)。
render(a, b=None) -> HTML 字符串; a/b 为性能测试 run 文档, 传 b 时做 A/B 对比。
结构"结论先行": KPI → 结论要点 → 图表 → 明细表 → 方法论 → 失败/重跑披露。
所有来自结果的字符串都经 esc() 转义; 报告不含脚本, 可直接发给他人离线打开。
"""
import html as _html
import math
import re
from datetime import datetime, timezone

try:
    from . import bench  # 报告引用引擎版本号
    from .version import APP_VERSION
except ImportError:
    import bench
    from version import APP_VERSION

REPORT_VERSION = "1.0.0"

# 与 web/static/app.css 亮色主题同源的设计常量
CA, CB = "#6950E8", "#0E9AB0"          # A/B 系列色 (--series-1/2)
CSERIES = ["#6950E8", "#0E9AB0", "#D97F06", "#D6408E", "#2F7FE0", "#5E9E12"]
INK, MUTED, BORDER, GRID = "#111827", "#6B7280", "#E5E7EB", "rgba(17,24,39,.10)"
GOOD, BAD, WARN = "#0C8A70", "#D6174A", "#A85611"


def esc(v):
    return _html.escape(str(v if v is not None else "—"), quote=True)


def fmt(v, d=1):
    if v is None:
        return "—"
    if isinstance(v, float):
        return ("%.*f" % (d, v))
    return str(v)


def _ph(doc, pid):
    for p in (doc.get("phases") or []):
        if p.get("id") == pid:
            return p
    return None


def _points(doc, pid, key_field, key_value):
    p = _ph(doc, pid)
    if not p:
        return []
    return [x for x in (p.get("points") or []) if x.get(key_field) == key_value]


# ---------------------------------------------------------------- SVG 图表

def _nice(v):
    if v <= 0:
        return 1.0
    e = math.floor(math.log10(v))
    for m in (1, 2, 5, 10):
        n = m * 10 ** e
        if n >= v:
            return float(n)
    return float(v)


def _tick(v):
    if v >= 100:
        return "%d" % round(v)
    if v >= 10:
        return "%.0f" % v
    return "%.1f" % v


def svg_chart(x_labels, series, w=780, h=230, right=None):
    """折线图: series=[(name, color, [float|None]), ...]; right 同构(右轴)。
    x_labels 与各系列点一一对应; None 点断线。"""
    pad_l, pad_r, pad_t, pad_b = 54, 54, 12, 26
    iw, ih = w - pad_l - pad_r, h - pad_t - pad_b
    vals = [v for _, _, pts in series for v in pts if v is not None] or [1.0]
    ymax = _nice(max(vals) * 1.05)
    y2max = None
    if right:
        v2 = [v for _, _, pts in right for v in pts if v is not None]
        if v2:
            y2max = _nice(max(v2) * 1.05)
    n = max(len(x_labels), 2)
    X = lambda i: pad_l + iw * i / (n - 1)  # noqa: E731
    Y = lambda v: pad_t + ih * (1 - (v or 0) / ymax)  # noqa: E731
    Y2 = lambda v: pad_t + ih * (1 - (v or 0) / y2max) if y2max else pad_t  # noqa: E731
    out = ['<svg viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" role="img">' % (w, h)]
    for k in range(5):
        vv, y = ymax * k / 4, Y(ymax * k / 4)
        out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" stroke-width="1"/>'
                   % (pad_l, y, w - pad_r, y, GRID))
        out.append('<text x="%d" y="%.1f" text-anchor="end" font-size="10" fill="%s">%s</text>'
                   % (pad_l - 6, y + 3.5, MUTED, _tick(vv)))
    stride = max(1, math.ceil(n / 10))
    for i, lab in enumerate(x_labels):
        if i % stride == 0 or i == n - 1:
            out.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="10" fill="%s">%s</text>'
                       % (X(i), h - 8, MUTED, esc(lab)))
    if y2max:
        for k in range(5):
            y = Y2(y2max * k / 4)
            out.append('<text x="%d" y="%.1f" text-anchor="start" font-size="10" fill="%s">%s</text>'
                       % (w - pad_r + 6, y + 3.5, MUTED, _tick(y2max * k / 4)))

    def draw(seqs, yfn, dash):
        for name, color, pts in seqs:
            seg, cur = [], None
            for i, v in enumerate(pts):
                if v is None:
                    cur = None
                    continue
                xy = "%.1f,%.1f" % (X(i), yfn(v))
                seg.append(("M" if cur is None else "L") + xy)
                cur = xy
                out.append('<circle cx="%.1f" cy="%.1f" r="2.6" fill="%s"/>'
                           % (X(i), yfn(v), color))
            if seg:
                out.append('<path d="%s" fill="none" stroke="%s" stroke-width="1.8"%s/>'
                           % (" ".join(seg), color, ' stroke-dasharray="5 4"' if dash else ""))

    draw(series, Y, False)
    if right:
        draw(right, Y2, True)
    out.append("</svg>")
    return "".join(out)


def svg_area(x_labels, values, note=None, color=CA, w=780, h=150):
    """面积图(开环在途时间线): 值下的面积 + 峰值参考线。"""
    if not values:
        return '<p class="muted">无在途采样数据</p>'
    pad_l, pad_r, pad_t, pad_b = 54, 12, 10, 22
    iw, ih = w - pad_l - pad_r, h - pad_t - pad_b
    vmax = _nice(max(values) * 1.15)
    n = max(len(values), 2)
    X = lambda i: pad_l + iw * i / (n - 1)  # noqa: E731
    Y = lambda v: pad_t + ih * (1 - v / vmax)  # noqa: E731
    out = ['<svg viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" role="img">' % (w, h)]
    for k in range(3):
        y = Y(vmax * k / 2)
        out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s"/>'
                   % (pad_l, y, w - pad_r, y, GRID))
        out.append('<text x="%d" y="%.1f" text-anchor="end" font-size="10" fill="%s">%s</text>'
                   % (pad_l - 6, y + 3.5, MUTED, _tick(vmax * k / 2)))
    peak = max(values)
    out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" stroke-dasharray="4 4"/>'
               % (pad_l, Y(peak), w - pad_r, Y(peak), WARN))
    path = "M%.1f,%.1f " % (X(0), Y(values[0])) + " ".join("L%.1f,%.1f" % (X(i), Y(v)) for i, v in enumerate(values))
    out.append('<path d="%s L%.1f,%d L%.1f,%d Z" fill="%s" opacity="0.12"/>' % (path, X(n - 1), h - pad_b, X(0), h - pad_b, color))
    out.append('<path d="%s" fill="none" stroke="%s" stroke-width="1.8"/>' % (path, color))
    for i in range(0, n, max(1, n // 8)):
        out.append('<circle cx="%.1f" cy="%.1f" r="2.2" fill="%s"/>' % (X(i), Y(values[i]), color))
    out.append('<text x="%d" y="%d" text-anchor="middle" font-size="10" fill="%s">时间 (s)</text>'
               % (pad_l + iw // 2, h - 2, MUTED))
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------- HTML 片段

def _tbl(headers, rows):
    head = "".join("<th>%s</th>" % h for h in headers)
    body = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in r) for r in rows) or \
        '<tr><td colspan="%d" class="muted">无数据</td></tr>' % len(headers)
    return '<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>' % (head, body)


def _delta(a, b, digits=1, lower_better=False):
    """A/B 两值同格展示: "12.3 / 14.1" + 相对差着色。"""
    if a is None and b is None:
        return "—"
    if a is None or b is None or b == 0:
        return "%s / %s" % (fmt(a, digits), fmt(b, digits))
    d = (a - b) / abs(b) * 100
    cls = "pos" if (d > 0) != lower_better else "neg"
    if abs(d) < 0.05:
        cls, d = "muted", 0.0
    return '%s / %s <span class="%s">(%+.1f%%)</span>' % (fmt(a, digits), fmt(b, digits), cls, d)


def _legend(docs):
    if len(docs) == 1:
        return '<span class="chip" style="background:%s"></span>%s' % (CA, esc(docs[0]["model"]))
    return '<span class="chip" style="background:%s"></span>A: %s &nbsp; <span class="chip" style="background:%s"></span>B: %s' \
        % (CA, esc(docs[0]["model"]), CB, esc(docs[1]["model"]))


def _kpi_cards(docs):
    def best(doc):
        conc = _ph(doc, "concurrency")
        pts = (conc or {}).get("points") or []
        dec = _ph(doc, "decode")
        dpts = (dec or {}).get("cases") or []
        pre = _ph(doc, "prefill")
        ppts = (pre or {}).get("points") or []
        return [
            (pts[-1] or {}).get("agg_tps") if pts else None,
            max((c.get("decode_tps_med") or 0) for c in dpts) if dpts else None,
            (pts[-1] or {}).get("ttft_p95_s") if pts else None,
            max((p.get("prefill_tps_med") or 0) for p in ppts) if ppts else None,
        ]
    vals = [best(d) for d in docs]
    cards = []
    for label, unit, i, lb in (("最高并发聚合吞吐", "tok/s", 0, False), ("单流解码吞吐", "tok/s", 1, False),
                               ("最高并发 TTFT p95", "s", 2, True), ("Prefill 吞吐(峰值中位)", "tok/s", 3, False)):
        a = vals[0][i]
        b = vals[1][i] if len(vals) > 1 else None
        body = _delta(a, b, 1, lb) if b is not None else fmt(a, 1)
        cards.append('<div class="kpi"><div class="kpi-l">%s</div><div class="kpi-v">%s</div>'
                     '<div class="kpi-u">%s</div></div>' % (label, body, unit))
    return '<div class="kpis">%s</div>' % "".join(cards)


def _findings(docs):
    f = []
    a = docs[0]

    def conc_series(doc):
        pts = (_ph(doc, "concurrency") or {}).get("points") or []
        return [(p["conc"], p.get("agg_tps"), p.get("ttft_p95_s")) for p in pts]

    sa, retries, fails = conc_series(a), 0, 0
    for p in a.get("phases") or []:
        for pt in p.get("points") or []:
            if pt.get("attempts", 1) > 1:
                retries += 1
            fails += pt.get("fail") or 0
    if len(docs) == 2:
        sb = conc_series(docs[1])
        common = [c for c, _, _ in sa if c in {x for x, _, _ in sb}]
        if common:
            ea = next((x for x in sa if x[0] == common[-1]), None)
            eb = next((x for x in sb if x[0] == common[-1]), None)
            if ea and eb and ea[1] and eb[1]:
                d = (ea[1] - eb[1]) / eb[1] * 100
                who = "A (%s)" % docs[0]["model"] if d >= 0 else "B (%s)" % docs[1]["model"]
                f.append("并发 %d 下聚合吞吐: %s 更高 %.1f%%（%s vs %s tok/s）"
                         % (common[-1], who, abs(d), fmt(ea[1]), fmt(eb[1])))
            if ea and eb and ea[2] and eb[2]:
                d = (ea[2] - eb[2]) / eb[2] * 100
                who = "A (%s)" % docs[0]["model"] if d < 0 else "B (%s)" % docs[1]["model"]
                f.append("并发 %d 下 TTFT p95: %s 更低 %.1f%%（%s vs %s s）"
                         % (common[-1], who, abs(d), fmt(ea[2]), fmt(eb[2])))
        if (a.get("overrides") or {}).get("fixed_output") != (docs[1].get("overrides") or {}).get("fixed_output"):
            f.append("⚠ 两次运行的固定输出长度(ignore_eos)设置不一致, 吞吐不可直接比较")
    ov = a.get("overrides") or {}
    if ov.get("fixed_output") is False:
        f.append("⚠ 本次运行未固定输出长度(端点不支持 ignore_eos), 模型提前结束时吞吐会偏低, 跨后端对比需注意口径")
    for doc in docs[1:]:
        for p in doc.get("phases") or []:
            for pt in p.get("points") or []:
                if pt.get("attempts", 1) > 1:
                    retries += 1
                fails += pt.get("fail") or 0
    if retries:
        f.append("%d 个格子失败后整格重跑(明细见「失败与重跑」)" % retries)
    if fails:
        f.append("共 %d 个请求失败(已计入失败率, 未从结果中剔除)" % fails)
    for p in a.get("phases") or []:
        if not (p.get("id") or "").startswith("scn_"):
            continue
        label = (p.get("task") or {}).get("label") or p["id"][4:]
        worst = min(((pt.get("json_rate") if pt.get("json_rate") is not None else 1.0, pt.get("conc"))
                     for pt in p.get("points") or []), default=(1.0, None))
        if worst[0] < 0.95:
            f.append("⚠ 场景「%s」JSON 合法率最低 %.0f%% (并发 %s): 结构化输出稳定性需关注" % (label, worst[0] * 100, worst[1]))
    ol = _ph(a, "openloop")
    if ol:
        for pt in ol.get("points") or []:
            rate, done = pt.get("rate"), pt.get("completed_rps") or 0
            if done < rate * 0.9:
                f.append("⚠ 开环速率 %g req/s 下只完成 %g req/s (最大在途 %d): 到达速率已超过服务能力, 请求越排越长"
                         % (rate, done, pt.get("max_inflight") or 0))
            if pt.get("shed"):
                f.append("⚠ 开环速率 %g 有 %d 个请求因在途超限(%d)被丢弃计数" % (rate, pt["shed"], bench.MAX_OPEN_INFLIGHT))
    rp = a.get("replay") or (docs[1].get("replay") if len(docs) > 1 else None)
    if isinstance(rp, dict) and rp.get("wrapped"):
        f.append("回放池已回绕: 部分请求被重复发送, 若端点前缀缓存跨格生效, 后段吞吐可能偏高")
    if not f:
        f.append("未发现需要关注的异常; 各阶段请求全部成功")
    return '<ul class="findings">%s</ul>' % "".join("<li>%s</li>" % x for x in f)


# ---------------------------------------------------------------- 各阶段区块

def _sec(title, body, note=None):
    return '<section><h2>%s</h2>%s%s</section>' % (title, ('<p class="muted">%s</p>' % note) if note else "", body)


def _len_label(pt):
    """输入长度的标签: 1.5 之前按旧估算拼长输入, 实际长度只有标称的 45% 左右; 标签和实际差 10% 以上时按实际长度显示。"""
    lab, tok = pt.get("label"), pt.get("in_tokens")
    m = re.match(r"^(\d+(?:\.\d+)?)K$", str(lab or ""))
    if not (m and tok) or abs(tok / (float(m.group(1)) * 1000) - 1) <= 0.1:
        return lab
    k = tok / 1000.0
    return "%sK（原标 %s）" % (("%.1f" % k).rstrip("0").rstrip(".") if k < 100 else "%d" % round(k), lab)


def _same_len(a, b):
    """两次测试的同一档实际长度是否接近(相差不到 10%); 没有实际长度时按档位对齐。"""
    ta, tb = (a or {}).get("in_tokens"), (b or {}).get("in_tokens")
    return not (ta and tb) or abs(ta / float(tb) - 1) <= 0.1


def _prefill_sec(docs):
    any_p = any(_ph(d, "prefill") for d in docs)
    if not any_p:
        return ""
    labels, s1, s2, rows = [], [], [], []
    pa = (_ph(docs[0], "prefill") or {}).get("points") or []
    pb = ((_ph(docs[1], "prefill") or {}).get("points") or []) if len(docs) > 1 else []
    labels = [_len_label(p) for p in pa]
    s1 = [p.get("prefill_tps_med") for p in pa]
    # B 按档位对齐, 但实际长度差得多(新旧算法的测试放在一起)时不比
    s2 = [(pb[i].get("prefill_tps_med") if _same_len(pa[i], pb[i]) else None) if i < len(pb) else None
          for i in range(len(pa))] if pb else []
    chart = svg_chart(labels, [("Prefill 吞吐 A", CA, s1)] + ([("B", CB, s2)] if s2 else []))
    rows = []
    for i, lab in enumerate(labels):
        rows.append([esc(lab),
                     _delta(s1[i] if i < len(s1) else None,
                            s2[i] if (s2 and i < len(s2)) else None, 1)])
    return _sec("Prefill 阶梯", chart + _tbl(["输入长度", "Prefill 吞吐 tok/s" + (" (A / B)" if s2 else "")], rows),
                note="单并发, 每档重复取中位; 唯一批次号避免前缀缓存命中虚高")


def _matrix_sec(docs):
    d0 = docs[0]
    p = _ph(d0, "prefill_conc")
    if not p:
        return ""
    pts = p.get("points") or []

    def row(pt):
        return [esc(_len_label(pt)), fmt(pt.get("in_tokens"), 0), "%d/%d" % (pt.get("ok", 0), pt.get("ok", 0) + pt.get("fail", 0)),
                fmt(pt.get("ttft_avg_ms")), fmt(pt.get("itl_avg_ms")), fmt(pt.get("prefill_tps_agg"), 0),
                fmt(pt.get("decode_tps_agg")), ('<span class="tag warn">重跑×%d</span>' % pt["attempts"]) if pt.get("attempts", 1) > 1 else ""]

    return _sec("提示词长度 × 并发矩阵 (并发 %s)" % esc(p.get("conc")), _tbl(
        ["档位", "in tokens", "ok/total", "TTFT 均值 ms", "ITL p50 均值 ms", "Prefill 聚合 tok/s", "Decode 聚合 tok/s", ""],
        [row(x) for x in pts]), note="屏障同步起跑; 聚合吞吐 = 该档全部成功请求的 token ÷ 最大单请求耗时")


def _conc_sec(docs):
    if not any(_ph(d, "concurrency") for d in docs):
        return ""
    labels, l1, r1, l2, r2 = [], [], [], [], []
    for k, d in enumerate(docs):
        pts = (_ph(d, "concurrency") or {}).get("points") or []
        if k == 0:
            labels = [str(x.get("conc")) for x in pts]
            l1 = [x.get("agg_tps") for x in pts]
            r1 = [x.get("ttft_p95_s") for x in pts]
        else:
            l2 = [x.get("agg_tps") for x in pts]
            r2 = [x.get("ttft_p95_s") for x in pts]
    left = [("聚合吞吐 A", CA, l1)] + ([("B", CB, l2)] if l2 else [])
    right = [("TTFT p95 A", "#D97F06", r1)] + ([("B", "#D6408E", r2)] if r2 else [])
    chart = svg_chart(labels, left, right=right)
    pa, pb = (_ph(docs[0], "concurrency") or {}).get("points") or [], \
             ((_ph(docs[1], "concurrency") or {}).get("points") or []) if len(docs) > 1 else []
    rows = []
    for i, pt in enumerate(pa):
        q = next((x for x in pb if x.get("conc") == pt.get("conc")), None)
        rows.append([pt.get("conc"), "%d/%d" % (pt.get("ok", 0), pt.get("fail", 0)),
                     _delta(pt.get("agg_tps"), q.get("agg_tps") if q else None),
                     _delta(pt.get("per_stream_tps_med"), q.get("per_stream_tps_med") if q else None),
                     _delta(pt.get("ttft_p95_s"), q.get("ttft_p95_s") if q else None, 3, True)])
    return _sec("并发阶梯", chart + _tbl(
        ["并发", "ok/fail", "聚合吞吐 tok/s", "单流吞吐 tok/s", "TTFT p95 s"], rows),
        note="实线=聚合吞吐(左轴), 虚线=TTFT p95(右轴); 固定输出长度(ignore_eos)保证跨后端可比" if
        (docs[0].get("overrides") or {}).get("fixed_output") else
        "实线=聚合吞吐(左轴), 虚线=TTFT p95(右轴); 本次未固定输出长度")


def _decode_sec(docs):
    cases = (_ph(docs[0], "decode") or {}).get("cases") or []
    if not cases:
        return ""
    rows = [[{"zh": "中文", "en": "英文"}.get(c.get("lang"), c.get("lang")), fmt(c.get("out_tokens"), 0),
             fmt(c.get("decode_tps_med")), fmt(c.get("decode_tps_best")), fmt(c.get("itl_p50_ms_med"), 2),
             fmt(c.get("itl_p95_ms")), fmt(c.get("spec_burst_med"), 2)] for c in cases]
    return _sec("单流解码", _tbl(
        ["语言", "输出 tokens", "吞吐 tok/s", "最佳 tok/s", "ITL p50 ms", "ITL p95 ms", "投机 burst tok/chunk"], rows),
        note="spec_burst > 1 提示投机采样生效(每 chunk 平均 token 数)")


def _scn_row(pt, q, has_json):
    jr = ("%s (%.0f%%)" % (fmt(pt.get("json_ok"), 0), (pt.get("json_rate") or 0) * 100)) if pt.get("json_total") else "—"
    badge = ' <span class="tag warn">重跑×%d</span>' % pt["attempts"] if pt.get("attempts", 1) > 1 else ""
    return [fmt(pt.get("ctx_tokens"), 0) if pt.get("ctx_tokens") else pt.get("conc"),
            "%d/%d" % (pt.get("ok", 0), pt.get("total", 0)),
            _delta(pt.get("req_s"), q.get("req_s") if q else None, 2),
            _delta(pt.get("ttft_p95_s"), q.get("ttft_p95_s") if q else None, 3, True),
            _delta(pt.get("e2e_p95_s"), q.get("e2e_p95_s") if q else None, 3, True),
            fmt(pt.get("out_tokens_avg")) + ("–" + fmt(pt.get("out_tokens_p90")) if pt.get("out_tokens_p90") else ""),
            fmt(pt.get("max_inflight")) if pt.get("max_inflight") is not None else "—",
            ((jr + badge) if has_json else (badge or "—"))]


def _scenarios_sec(docs):
    secs = []
    for p in docs[0].get("phases") or []:
        pid = p.get("id") or ""
        if not pid.startswith("scn_"):
            continue
        tpl = (p.get("task") or {}).get("tpl", pid[4:])
        label = (p.get("task") or {}).get("label") or tpl
        pb = None
        if len(docs) > 1:
            pb = _ph(docs[1], pid)
        has_json = any(pt.get("json_total") for pt in p.get("points") or [])
        is_rag = tpl == "rag"
        key_field = "ctx_tokens" if is_rag else "conc"
        rows = []
        for pt in p.get("points") or []:
            q = next((x for x in (pb or {}).get("points") or [] if x.get(key_field) == pt.get(key_field)), None)
            rows.append(_scn_row(pt, q, has_json))
        headers = (["上下文 tokens" if is_rag else "并发", "ok/total", "请求/秒", "TTFT p95 s", "端到端 p95 s",
                    "输出 tokens 均值" + ("–p90" if any(x.get("out_tokens_p90") for x in p.get("points") or []) else ""),
                    "最大在途"] + (["JSON 合法"] if has_json else []))
        task = p.get("task") or {}
        note = "任务模板: %s · max_tokens %s · 每并发 %s 请求 · 不发送 ignore_eos, 测真实任务行为%s%s" % (
            esc(label), esc(task.get("max_tokens")), esc(task.get("requests_per_worker")),
            (" · 图片 %s 张/请求" % esc(task.get("images_per_request"))) if tpl == "vision" else "",
            (" · 任务集 %s 条" % esc(task.get("pool_size"))) if tpl == "custom" else "")
        if tpl == "vision":
            note += "; 图片池 %s 张%s" % (esc(task.get("images")),
                                         "(内置示例图片)" if task.get("image_source") == "builtin" else "")
            if task.get("images_skipped"):
                note += ", 另有 %s 张不能用已跳过" % esc(task.get("images_skipped"))
        cols = len(headers)
        fixed_rows = [r[:6] + [r[6]] + ([r[7]] if has_json else []) for r in rows]
        secs.append(_sec("场景 · " + label, _tbl(headers, fixed_rows), note=note))
    return "".join(secs)


def _replay_sec(docs):
    p = _ph(docs[0], "replay")
    if not p:
        return ""
    pb = _ph(docs[1], "replay") if len(docs) > 1 else None
    rows = []
    for pt in p.get("points") or []:
        q = next((x for x in (pb or {}).get("points") or [] if x.get("conc") == pt.get("conc")), None)
        rows.append([pt.get("conc"), "%d/%d" % (pt.get("ok", 0), pt.get("total", 0)),
                     _delta(pt.get("req_s"), q.get("req_s") if q else None, 2),
                     _delta(pt.get("ttft_p95_s"), q.get("ttft_p95_s") if q else None, 3, True),
                     _delta(pt.get("e2e_p95_s"), q.get("e2e_p95_s") if q else None, 3, True),
                     fmt(pt.get("prompt_tokens_avg"), 0), fmt(pt.get("out_tokens_avg"), 0),
                     pt.get("max_inflight"), "是" if pt.get("pool_wrapped") else ""])
    info = p.get("pool") or {}
    return _sec("真实请求回放 · 闭环", _tbl(
        ["并发", "ok/total", "请求/秒", "TTFT p95 s", "端到端 p95 s", "入 tokens 均值", "出 tokens 均值", "最大在途", "池回绕"], rows),
        note="回放池 %s 条(跳过 %s, 坏行 %s); cursor 跨格推进避免重复请求命中前缀缓存"
             % (esc(info.get("size")), esc(info.get("skipped")), esc(info.get("bad"))))


def _openloop_sec(docs):
    p = _ph(docs[0], "openloop")
    if not p:
        return ""
    pb = _ph(docs[1], "openloop") if len(docs) > 1 else None
    rows, charts = [], []
    for pt in p.get("points") or []:
        q = next((x for x in (pb or {}).get("points") or [] if x.get("rate") == pt.get("rate")), None)
        done = "%s / 目标 %g" % (fmt(pt.get("completed_rps"), 2), pt.get("rate") or 0)
        rows.append([pt.get("rate"), pt.get("sent"), pt.get("shed") or 0, "%d/%d" % (pt.get("ok", 0), pt.get("total", 0)),
                     _delta(pt.get("ttft_p95_s"), q.get("ttft_p95_s") if q else None, 3, True),
                     _delta(pt.get("e2e_p95_s"), q.get("e2e_p95_s") if q else None, 3, True),
                     done, pt.get("max_inflight")])
        ts = pt.get("inflight_ts") or []
        if ts:
            charts.append('<h3>在途请求时间线 · %g req/s <span class="muted">(峰值 %d, 曲线持续抬升 = 排队堆积)</span></h3>%s'
                          % (pt.get("rate"), pt.get("max_inflight") or 0,
                             svg_area([("%.0f" % t) for t, _ in ts], [v for _, v in ts])))
    return _sec("真实请求回放 · 开环 (泊松到达)", _tbl(
        ["速率 req/s", "发送", "丢弃", "ok/total", "TTFT p95 s", "端到端 p95 s", "完成 req/s", "最大在途"], rows)
        + "".join(charts),
        note="泊松到达持续 %s 秒(固定种子, 两次运行到达时间轴相同); 在途上限 %d, 超限丢弃并计数"
             % (esc(p.get("duration_s")), bench.MAX_OPEN_INFLIGHT))


def _retry_sec(docs):
    rows = []
    for k, d in enumerate(docs):
        tag = ("A", "B")[k] if len(docs) > 1 else ""
        for p in d.get("phases") or []:
            for i, pt in enumerate(p.get("points") or []):
                if (pt.get("attempts") or 1) > 1 or (pt.get("fail") or 0) > 0:
                    key = pt.get("conc", pt.get("rate", pt.get("label", i)))
                    for fa in pt.get("failed_attempts") or []:
                        rows.append(["%s%s" % (tag, p.get("id")), esc(key), fa.get("attempt"),
                                     "%s/%s" % (fa.get("ok"), (fa.get("ok") or 0) + (fa.get("fail") or 0)),
                                     esc((fa.get("errors") or [""])[0])[:120]])
                    if (pt.get("fail") or 0) > 0:
                        rows.append(["%s%s" % (tag, p.get("id")), esc(key), esc(pt.get("attempts", 1)),
                                     "%s/%s" % (pt.get("ok", 0), pt.get("total", pt.get("ok", 0) + pt.get("fail", 0))),
                                     esc((pt.get("errors") or [""])[0])[:120]])
    if not rows:
        return ""
    return _sec("失败与重跑披露", _tbl(["运行", "阶段", "尝试", "ok/total", "错误样本"], rows),
                note="整格重跑: 有失败的格子等 30s 后重跑(最多 3 次), 这里列出每轮失败; 最终结果以最后一轮为准")


def _meta_sec(docs):
    d = docs[0]
    badges = []
    for label, v in (("套件", d.get("suite")), ("框架", (d.get("framework") or {}).get("name")),
                     ("框架版本", (d.get("framework") or {}).get("version")), ("标签", d.get("tag")),
                     ("bench", d.get("bench_version")), ("run", d.get("run_id"))):
        if v:
            badges.append('<span class="badge">%s: %s</span>' % (label, esc(v)))
    rows = [["A", esc(docs[0].get("model")), esc((docs[0].get("started_utc") or "")[:19].replace("T", " "))]]
    if len(docs) > 1:
        rows.append(["B", esc(docs[1].get("model")), esc((docs[1].get("started_utc") or "")[:19].replace("T", " "))])
    return "<p>%s</p>%s" % (" ".join(badges), _tbl(["运行", "模型", "开始时间 (UTC)"], rows))


CSS = """
:root{color-scheme:light}
*{box-sizing:border-box} body{font:14px/1.65 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
color:#111827;background:#F6F7F8;margin:0;padding:0 0 64px}
main{max-width:980px;margin:0 auto;padding:0 24px}
h1{font-size:22px;margin:28px 0 6px} h2{font-size:17px;margin:34px 0 10px;padding-bottom:6px;border-bottom:1px solid #E5E7EB}
h3{font-size:13px;margin:18px 0 6px;color:#4B5563}
p{margin:8px 0} .muted{color:#6B7280} .sub{color:#6B7280;font-size:12.5px;margin-bottom:18px}
.badge{display:inline-block;background:#F1EEFD;color:#592BE7;border-radius:99px;padding:2px 10px;font-size:12px;margin:2px 6px 2px 0}
.chip{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:16px 0}
.kpi{background:#fff;border:1px solid #E5E7EB;border-radius:10px;padding:12px 14px}
.kpi-l{font-size:12px;color:#6B7280}.kpi-v{font-size:22px;font-weight:650;margin:2px 0;font-variant-numeric:tabular-nums}
.kpi-u{font-size:11px;color:#9CA3AF}
.pos{color:#0C8A70;font-size:12px}.neg{color:#D6174A;font-size:12px}
.findings{background:#fff;border:1px solid #E5E7EB;border-left:3px solid #6950E8;border-radius:8px;
padding:14px 14px 14px 32px;margin:14px 0}.findings li{margin:5px 0}
section{background:transparent} svg{width:100%;height:auto;background:#fff;border:1px solid #E5E7EB;border-radius:8px}
table{border-collapse:collapse;width:100%;background:#fff;border:1px solid #E5E7EB;border-radius:8px;overflow:hidden;font-size:13px;margin:10px 0}
th{background:#F3F4F6;text-align:right;padding:7px 10px;font-weight:600;color:#4B5563;white-space:nowrap}
td{padding:6px 10px;text-align:right;border-top:1px solid #F3F4F6;font-variant-numeric:tabular-nums}
th:first-child,td:first-child{text-align:left}
.tag{font-size:11px;border-radius:4px;padding:1px 6px}.tag.warn{background:#FFF8E6;color:#A85611}
footer{margin-top:40px;color:#9CA3AF;font-size:12px;border-top:1px solid #E5E7EB;padding-top:12px}
@media print{body{background:#fff;padding:0}svg,table{break-inside:avoid}}
"""

METHOD = """<section><h2>测量口径</h2><ul class="findings" style="border-left-color:#0E9AB0">
<li>TTFT = SSE 首个 content/reasoning 增量; 解码吞吐 = (completion_tokens−1)/流内解码跨度(usage 精确计数)</li>
<li>主流程默认固定输出长度(ignore_eos)保证不同后端吞吐可比; 业务/回放场景<b>不</b>发送 ignore_eos, 测真实任务行为</li>
<li>每次测量带唯一批次号防前缀缓存命中虚高; 并发轮屏障同步起跑; 聚合吞吐 = 轮总 token ÷ 轮墙钟</li>
<li>TTFT/TPOT/端到端分位均"先逐请求计算、再排序取分位", 非聚合比值</li>
<li>开环回放为泊松到达、绝对时间调度(无累计漂移), 到达时间轴按固定种子生成 — 两次运行的对比收到相同到达序列</li>
<li>失败请求计为失败并保留错误样本; 基础设施型失败的格子整格重跑(最多 3 次)并全量披露</li>
</ul></section>"""


def render(a, b=None):
    """生成自包含 HTML 报告; a/b 为性能测试 run 文档。非 perf 文档抛 ValueError。"""
    if not isinstance(a, dict) or not a.get("run_id", "").startswith("run_") or not isinstance(a.get("phases"), list):
        raise ValueError("仅支持性能测试运行 (run_*) 的报告")
    docs = [a] + ([b] if b else [])
    title = "%s 压测报告" % a.get("model", "")
    if b:
        title += " · A/B 对比"
    if a.get("tag"):
        title += " · %s" % a["tag"]
    sections = [
        _meta_sec(docs), _kpi_cards(docs),
        '<h2>结论要点</h2><p class="sub">%s</p>%s' % (_legend(docs), _findings(docs)),
        _conc_sec(docs), _prefill_sec(docs), _matrix_sec(docs), _decode_sec(docs),
        _scenarios_sec(docs), _replay_sec(docs), _openloop_sec(docs), _retry_sec(docs),
        METHOD,
    ]
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s</title><style>%s</style></head><body><main>
<h1>%s</h1>
%s
<footer>LLM Bench Pro v%s · 报告生成 v%s · 引擎 v%s · 生成于 %s (UTC) · 数据与口径详见各节说明; 本文件自包含, 可离线打开与打印</footer>
</main></body></html>""" % (esc(title), CSS, esc(title), "".join(x for x in sections if x),
                           esc(APP_VERSION), REPORT_VERSION, esc(a.get("bench_version")),
                           datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))
