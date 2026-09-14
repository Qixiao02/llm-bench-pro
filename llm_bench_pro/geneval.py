#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
geneval.py — 生成作品评测 (对齐 ArtifactsBench 口径: 真实渲染 + 交互截图 + 清单式多模态评审)

1) 运行检测 (有 Chrome/Edge 时, 确定性、可复现):
   无头浏览器加载作品 (断网, Math.random 固定种子, 弹窗置空) ->
   加载/卡死、未捕获异常、首屏非空白、空闲期是否在动、逐题脚本化交互是否生效 (断言或超出空闲基线的画面/DOM 变化)、
   移动视口横向溢出、外部依赖 -> 多帧截图
2) 源码检查 (无浏览器时降级): 去注释后按事件绑定/特征正则检查, 结果标注 method=static
3) 视觉评审 (配置评审模型时): 题目 + 运行检测报告 + 截图序列 + 代码 -> 逐项 0-10 分, 汇总为 0-100
CLI: python -m llm_bench_pro.geneval --run gen_xxx [--judge-base URL --judge-model NAME --judge-key KEY]
"""
import argparse
import base64
import json
import os
import pathlib
import re
import threading
import time

try:
    from . import cdp, gen_specs, iq
except ImportError:
    import cdp
    import gen_specs
    import iq

EVAL_VERSION = "1.0.0"
VIEW_W, VIEW_H = 1280, 800
ANALYZE_SCALE = 0.25   # 像素分析用小图 320x200
SHOT_SCALE = 0.6       # 评审/展示用截图 768x480
MOBILE_W, MOBILE_H = 390, 844

# 注入脚本: 在作品任何代码之前执行
INSTRUMENT_JS = r"""
(() => {
  const S = window.__probe = {listeners: {}, calls: {}, raf: 0, draws: 0, mutations: 0, dialogs: 0};
  let seed = 42;
  Math.random = function () {  // mulberry32 固定种子, 截图可复现
    seed |= 0; seed = seed + 0x6D2B79F5 | 0;
    let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
  window.alert = function () { S.dialogs++; };
  window.confirm = function () { S.dialogs++; return true; };
  window.prompt = function (m, d) { S.dialogs++; return d || ""; };
  const add = EventTarget.prototype.addEventListener, rem = EventTarget.prototype.removeEventListener;
  const wrapped = new WeakMap();
  EventTarget.prototype.addEventListener = function (type, fn, opt) {
    if (!fn || (typeof fn !== "function" && typeof fn.handleEvent !== "function")) return add.call(this, type, fn, opt);
    S.listeners[type] = (S.listeners[type] || 0) + 1;
    let w = wrapped.get(fn);
    if (!w) {
      w = function (e) {
        S.calls[e.type] = (S.calls[e.type] || 0) + 1;
        return typeof fn === "function" ? fn.apply(this, arguments) : fn.handleEvent(e);
      };
      wrapped.set(fn, w);
    }
    return add.call(this, type, w, opt);
  };
  EventTarget.prototype.removeEventListener = function (type, fn, opt) {
    return rem.call(this, type, (fn && wrapped.get(fn)) || fn, opt);
  };
  const INPUT = ["keydown","keyup","keypress","mousedown","mouseup","mousemove","click","dblclick","contextmenu",
                 "pointerdown","pointerup","pointermove","wheel","touchstart","touchmove","input","change"];
  INPUT.forEach(t => add.call(window, t, e => {  // on* 属性/内联处理器
    for (const n of e.composedPath ? e.composedPath() : []) {
      if (n && typeof n["on" + t] === "function") { S.calls["on" + t] = (S.calls["on" + t] || 0) + 1; break; }
    }
  }, true));
  const raf = window.requestAnimationFrame;
  window.requestAnimationFrame = function (cb) { S.raf++; return raf.call(window, cb); };
  const count = (proto, names) => proto && names.forEach(n => {
    const f = proto[n]; if (typeof f !== "function") return;
    proto[n] = function () { S.draws++; return f.apply(this, arguments); };
  });
  count(window.CanvasRenderingContext2D && CanvasRenderingContext2D.prototype,
        ["fillRect","strokeRect","fill","stroke","drawImage","fillText","strokeText","putImageData"]);
  count(window.WebGLRenderingContext && WebGLRenderingContext.prototype, ["drawArrays","drawElements"]);
  count(window.WebGL2RenderingContext && WebGL2RenderingContext.prototype, ["drawArrays","drawElements"]);
  const gc = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function (type, attrs) {  // WebGL 保留绘制缓冲, 截图不黑屏
    if (/webgl/i.test(type)) attrs = Object.assign({}, attrs, {preserveDrawingBuffer: true});
    return gc.call(this, type, attrs);
  };
  const startMO = () => new MutationObserver(l => { S.mutations += l.length; })
    .observe(document.documentElement, {subtree: true, childList: true, attributes: true, characterData: true});
  if (document.documentElement) startMO(); else add.call(document, "DOMContentLoaded", startMO);
})();
"""

FIND_JS = r"""
((re, css) => {
  const rx = re ? new RegExp(re, "i") : null;
  const sel = css || "button,a,[role=button],input[type=button],input[type=submit],summary,label,li,span,div,p,td,dt,h3,h4,[onclick]";
  let best = null;
  for (const e of document.querySelectorAll(sel)) {
    const r = e.getBoundingClientRect();
    if (r.width < 4 || r.height < 4 || r.bottom <= 0 || r.right <= 0 || r.top >= innerHeight || r.left >= innerWidth) continue;
    const st = getComputedStyle(e);
    if (st.visibility === "hidden" || st.display === "none" || +st.opacity === 0 || st.pointerEvents === "none") continue;
    if (rx) {
      const t = (e.innerText || e.value || e.getAttribute("aria-label") || e.title || "").trim();
      if (!t || t.length > 40 || !rx.test(t)) continue;
    }
    const a = r.width * r.height;
    if (!best || a < best.a) best = {x: r.left + r.width / 2, y: r.top + r.height / 2, a, text: (e.innerText || e.value || e.tagName).trim().slice(0, 24)};
  }
  return best;
})
"""

_KEYS = {"ArrowLeft": 37, "ArrowUp": 38, "ArrowRight": 39, "ArrowDown": 40, "Enter": 13, "Escape": 27,
         "Backspace": 8, "Tab": 9, " ": 32, "Shift": 16}
_CODES = {" ": "Space", "Enter": "Enter", "Escape": "Escape", "Backspace": "Backspace", "Tab": "Tab", "/": "Slash"}


def _key_params(key):
    if key in _KEYS:
        vk, code, text = _KEYS[key], _CODES.get(key, key), {" ": " ", "Enter": "\r"}.get(key)
    elif len(key) == 1:
        vk = ord(key.upper()) if key.isalnum() else ord(key)
        code = ("Key" + key.upper()) if key.isalpha() else (("Digit" + key) if key.isdigit() else _CODES.get(key, ""))
        text = key
    else:
        vk, code, text = 0, key, None
    p = {"key": key, "code": code, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
    return p, text


class Prober:
    """在一个标签页里对单个作品执行运行检测。"""

    def __init__(self, page, spec, shots_dir):
        self.pg, self.spec, self.shots_dir = page, spec, shots_dir
        self.checks, self.shots, self.notes = [], [], []
        self._w, self._h = VIEW_W, VIEW_H

    # ---- 基础
    def check(self, cid, label, ok, detail=""):
        self.checks.append({"id": cid, "label": label, "pass": bool(ok), "detail": detail})

    def small(self):
        return self.pg.screenshot("png", ANALYZE_SCALE, width=self._w, height=self._h)

    def shot(self, name, caption):
        data = self.pg.screenshot("jpeg", SHOT_SCALE, quality=72, width=self._w, height=self._h)
        fn = name + ".jpg"
        with open(os.path.join(self.shots_dir, fn), "wb") as f:
            f.write(data)
        self.shots.append({"name": name, "file": fn, "caption": caption})
        return data

    def probe_state(self):
        try:
            return json.loads(self.pg.evaluate("JSON.stringify(window.__probe||{})", timeout=5))
        except (cdp.CDPError, TypeError, ValueError):
            return {}

    def exceptions(self, since):
        out = []
        for t, m, p in list(self.pg.events):
            if t < since:
                continue
            if m == "Runtime.exceptionThrown":
                d = p.get("exceptionDetails") or {}
                ex = d.get("exception") or {}
                out.append((ex.get("description") or d.get("text") or "exception").split("\n")[0][:160])
            elif m == "Runtime.consoleAPICalled" and p.get("type") == "error":
                args = p.get("args") or []
                out.append("console.error: " + " ".join(str(a.get("value", a.get("description", ""))) for a in args)[:160])
        return out

    # ---- 输入
    def xy(self, pt):
        return pt[0] * self._w, pt[1] * self._h

    def mouse(self, typ, x, y, button="left", clicks=1):
        p = {"type": typ, "x": x, "y": y, "button": button if typ != "mouseMoved" else "none", "clickCount": clicks}
        if typ != "mouseMoved":
            p["buttons"] = 1 if button == "left" else 2
        self.pg.send("Input.dispatchMouseEvent", p)

    def click_at(self, x, y, button="left", clicks=1):
        self.mouse("mouseMoved", x, y)
        for c in range(1, clicks + 1):
            self.mouse("mousePressed", x, y, button, c)
            self.mouse("mouseReleased", x, y, button, c)

    def key(self, key, hold=0.0):
        p, text = _key_params(key)
        down = dict(p, type="keyDown")
        if text:
            down["text"] = text
        self.pg.send("Input.dispatchKeyEvent", down)
        if hold:
            end = time.monotonic() + hold
            while time.monotonic() < end:  # 长按: 模拟系统自动重复
                time.sleep(0.05)
                self.pg.send("Input.dispatchKeyEvent", dict(down, autoRepeat=True))
        self.pg.send("Input.dispatchKeyEvent", dict(p, type="keyUp"))

    def run_action(self, a):
        """执行单个动作; 返回 (ok, 说明)。"""
        if "wait" in a:
            time.sleep(a["wait"])
        elif "key" in a:
            for _ in range(a.get("repeat", 1)):
                self.key(a["key"], a.get("hold", 0))
                time.sleep(0.06)
        elif "type" in a:
            for ch in a["type"]:
                self.key("Enter" if ch == "\n" else ch)
                time.sleep(0.02)
        elif "click" in a or "dblclick" in a or "rclick" in a:
            pt = a.get("click") or a.get("dblclick") or a.get("rclick")
            x, y = self.xy(pt)
            if "rclick" in a:
                self.click_at(x, y, "right")
            else:
                self.click_at(x, y, clicks=2 if "dblclick" in a else 1)
        elif "drag" in a:
            (x1, y1), (x2, y2) = self.xy(a["drag"][0]), self.xy(a["drag"][1])
            n = a.get("steps", 12)
            self.mouse("mouseMoved", x1, y1)
            self.mouse("mousePressed", x1, y1)
            for i in range(1, n + 1):
                self.pg.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x1 + (x2 - x1) * i / n,
                                                         "y": y1 + (y2 - y1) * i / n, "button": "left", "buttons": 1})
                time.sleep(0.016)
            self.mouse("mouseReleased", x2, y2)
        elif "move" in a:
            pts = [self.xy(p) for p in a["move"]]
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                for i in range(1, 9):
                    self.mouse("mouseMoved", x1 + (x2 - x1) * i / 8, y1 + (y2 - y1) * i / 8)
                    time.sleep(0.016)
        elif "wheel" in a:
            x, y = self.xy(a.get("at", [0.5, 0.5]))
            self.pg.send("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x, "y": y, "deltaX": 0, "deltaY": a["wheel"]})
        elif "find" in a or "css" in a:
            target = self.pg.evaluate("%s(%s, %s)" % (FIND_JS, json.dumps(a.get("find") or ""), json.dumps(a.get("css") or "")))
            if not target:
                return bool(a.get("optional")), "未找到元素 %s" % (a.get("find") or a.get("css"))
            do = a.get("do", "click")
            if do == "hover":
                self.mouse("mouseMoved", target["x"], target["y"])
            else:
                self.click_at(target["x"], target["y"], clicks=2 if do == "dblclick" else 1)
            return True, "命中「%s」" % target["text"]
        return True, ""

    # ---- 流程
    def load(self, url, mobile=False):
        self._w, self._h = (MOBILE_W, MOBILE_H) if mobile else (VIEW_W, VIEW_H)
        self.pg.send("Emulation.setDeviceMetricsOverride", {"width": self._w, "height": self._h,
                                                           "deviceScaleFactor": 1, "mobile": mobile})
        t = time.monotonic()
        self.pg.send("Page.navigate", {"url": url})
        return self.pg.wait_event("Page.loadEventFired", 15, since=t) is not None

    def run(self, url):
        spec = self.spec
        t_start = time.monotonic()
        loaded = self.load(url)
        time.sleep(1.2)
        try:
            self.pg.evaluate("1", timeout=5)
            alive = True
        except cdp.CDPError:
            alive = False
        self.check("load", "页面加载完成且未卡死", loaded and alive,
                   "" if loaded and alive else ("加载超时" if not loaded else "主线程无响应(疑似死循环)"))
        if not alive:
            self.check("no_error", "运行无未捕获异常", False, "页面卡死, 无法继续检测")
            return

        a = self.small()
        st = cdp.image_stats(a)
        nonblank = st["dominant_ratio"] < 0.998 and st["colors"] > 4  # 大面积纯色桌面/背景仍算有内容
        self.shot("01_initial", "首屏（加载后约 1.2 秒）")
        self.check("nonblank", "首屏有实际渲染内容（非白屏/纯色）", nonblank,
                   "主色占比 %.1f%%，颜色数 %d" % (st["dominant_ratio"] * 100, st["colors"]))

        ps0 = self.probe_state()
        time.sleep(spec["idle"])
        b = self.small()
        ps1 = self.probe_state()
        idle_diff = cdp.image_diff(a, b)
        idle_mut = ps1.get("mutations", 0) - ps0.get("mutations", 0)
        self.shot("02_idle", "空闲 %.1f 秒后" % spec["idle"])
        if spec["animated"]:
            self.check("animated", "空闲时持续动画/渲染", idle_diff > 0.0005,
                       "画面变化 %.2f%%，rAF %d 次，绘制调用 %d 次" % (idle_diff * 100, ps1.get("raf", 0) - ps0.get("raf", 0),
                                                            ps1.get("draws", 0) - ps0.get("draws", 0)))

        for act in spec["setup"]:
            try:
                self.run_action(act)
            except cdp.CDPError as e:
                self.notes.append("预热动作失败: %s" % e)
            time.sleep(0.15)
        if spec["setup"]:
            time.sleep(0.5)

        for i, stp in enumerate(spec["steps"]):
            self.run_step(i, stp)

        errs = self.exceptions(t_start)
        self.check("no_error", "运行无未捕获异常/控制台错误", not errs,
                   ("%d 条：%s" % (len(errs), "；".join(dict.fromkeys(errs))))[:300] if errs else "")

        if spec["responsive"]:
            self.run_mobile(url)

    def run_step(self, i, stp):
        label, settle = stp["label"], stp.get("settle", 0.6)
        cid = "step%d" % (i + 1)
        try:
            pre1 = self.small()
            ps_a = self.probe_state()
            time.sleep(settle)
            pre2 = self.small()
            ps_b = self.probe_state()
            base_diff = cdp.image_diff(pre1, pre2)
            base_mut = ps_b.get("mutations", 0) - ps_a.get("mutations", 0)
            t0 = time.monotonic()
            notes = []
            ok_actions = True
            for act in stp["actions"]:
                ok, note = self.run_action(act)
                if note:
                    notes.append(note)
                if not ok:
                    ok_actions = False
                    break
                time.sleep(0.08)
            time.sleep(settle)
            post = self.small()
            ps_c = self.probe_state()
            diff = cdp.image_diff(pre2, post)
            mut = ps_c.get("mutations", 0) - ps_b.get("mutations", 0)
            handled = sum(ps_c.get("calls", {}).values()) - sum(ps_b.get("calls", {}).values())
            errs = self.exceptions(t0)
            if len(self.shots) < 7:
                self.shot("%02d_step%d" % (i + 3, i + 1), "交互「%s」之后" % label)
            if not ok_actions:
                passed, why = False, "；".join(notes)
            elif errs:
                passed, why = False, "交互触发异常：%s" % errs[0]
            elif stp.get("assert"):
                val = self.pg.evaluate("!!(%s)" % stp["assert"])
                passed, why = bool(val), "功能断言%s" % ("通过" if val else "未通过")
            else:
                # 证据任一成立即判定生效: 画面变化显著超出空闲基线 / DOM 变更超出基线 /
                # 作品自身事件处理器被调用, 且画面变化略超基线(如方块旋转)或动画节奏明显改变(如暂停)。
                # 仅"处理器被调用 + 背景照常动画"不算生效, 避免开始界面未进入游戏时误判。
                visual = diff > max(base_diff * 1.5 + 0.001, 0.002)
                dom = mut > base_mut * 1.5 + 2
                rhythm = abs(diff - base_diff) > max(0.003, base_diff * 0.5)
                passed = visual or dom or (handled > 0 and (diff > base_diff * 1.15 + 0.0005 or rhythm))
                why = "画面变化 %.2f%%（空闲基线 %.2f%%），DOM 变更 %d（基线 %d），事件处理 %d 次" % (
                    diff * 100, base_diff * 100, mut, base_mut, handled)
            if notes and ok_actions:
                why = "；".join(notes) + "；" + why
            self.check(cid, "交互：" + label, passed, why)
        except cdp.CDPError as e:
            self.check(cid, "交互：" + label, False, "页面无响应：%s" % e)

    def run_mobile(self, url):
        try:
            self.load(url, mobile=True)
            time.sleep(1.0)
            m = self.pg.evaluate("JSON.stringify({sw: document.documentElement.scrollWidth, w: innerWidth})")
            m = json.loads(m)
            self.shot("09_mobile", "移动端 390px 视口")
            self.check("responsive", "移动端 390px 无横向溢出", m["sw"] <= m["w"] + 4,
                       "内容宽 %dpx / 视口 %dpx" % (m["sw"], m["w"]))
        except cdp.CDPError as e:
            self.check("responsive", "移动端 390px 无横向溢出", False, str(e))


def external_requests(page):
    out = []
    for _, m, p in list(page.events):
        if m == "Network.requestWillBeSent":
            u = (p.get("request") or {}).get("url", "")
            if re.match(r"^(https?|wss?):", u):
                out.append({"url": u[:160], "type": p.get("type") or ""})
    return out


def source_complete(html):
    low = html.lower()
    return "</html>" in low and low.count("<script") <= low.count("</script>")


def probe_work(browser, html_path, task_id, shots_dir):
    spec = gen_specs.get(task_id)
    os.makedirs(shots_dir, exist_ok=True)
    page = browser.new_page()
    prober = Prober(page, spec, shots_dir)
    with open(html_path, encoding="utf-8", errors="replace") as f:
        prober.check("complete", "代码完整输出（</html> 闭合、script 配对）", source_complete(f.read()),
                     "")
    try:
        page.send("Page.enable")
        page.send("Runtime.enable")
        page.send("Network.enable")
        page.send("Network.setBlockedURLs", {"urls": ["http://*", "https://*", "ws://*", "wss://*"]})
        page.send("Emulation.setFocusEmulationEnabled", {"enabled": True})
        page.send("Page.addScriptToEvaluateOnNewDocument", {"source": INSTRUMENT_JS})
        prober.run(pathlib.Path(html_path).resolve().as_uri())
    except cdp.CDPError as e:
        prober.notes.append("检测中断: %s" % e)
        if not any(c["id"] == "load" for c in prober.checks):
            prober.check("load", "页面加载完成且未卡死", False, str(e))
    finally:
        ext = external_requests(page)
        try:
            page.close()
        except Exception:
            pass
    # 网络字体(含 Google Fonts 样式表)被拦截只影响字形, 不影响功能, 不判失败
    soft = re.compile(r"^https?://(fonts\.(googleapis|gstatic)\.com|fonts\.loli\.net|use\.typekit\.net)/", re.I)
    hard = [e for e in ext if e["type"] in ("Script", "Stylesheet", "Fetch", "XHR", "WebSocket") and not soft.match(e["url"])]
    prober.check("self_contained", "单文件自包含（无外部脚本/样式/接口依赖）", not hard,
                 ("外部依赖被拦截：" + "，".join(e["url"] for e in hard[:3])) if hard else
                 ("仅网络字体/图片等外链 %d 个（已拦截，不影响功能）" % len(ext) if ext else ""))
    return {"method": "browser", "browser": browser.version, "checks": prober.checks,
            "shots": prober.shots, "notes": prober.notes, "external": ext[:20]}


# ---------------------------------------------------------------- 源码检查 (降级)

def strip_comments(html):
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    html = re.sub(r"/\*.*?\*/", "", html, flags=re.S)
    return re.sub(r"(?m)(^|[^:\"'\\])//[^\n]*", r"\1", html)


def static_checks(html, task):
    code = strip_comments(html)
    low = code.lower()
    checks = [
        {"id": "doctype", "label": "HTML 文档结构", "pass": bool(re.search(r"<!doctype html|<html", low)), "detail": ""},
        {"id": "complete", "label": "代码完整输出（</html> 闭合、script 配对）", "pass": source_complete(html), "detail": ""},
        {"id": "self_contained", "label": "无外部脚本/样式依赖",
         "pass": not re.search(r"<script[^>]+src=[\"']https?:|<link[^>]+href=[\"']https?:[^>]+stylesheet", low), "detail": ""},
    ]
    for i, f in enumerate(task.get("features") or []):
        checks.append({"id": "f%d" % (i + 1), "label": "源码特征 /%s/" % f, "pass": bool(re.search(f, code, re.I)),
                       "detail": "已去除注释后匹配"})
    return {"method": "static", "browser": None, "checks": checks, "shots": [], "notes": ["未找到无头浏览器，降级为源码检查"],
            "external": []}


# ---------------------------------------------------------------- 视觉评审

JUDGE_SYSTEM = ("你是严格、客观的前端作品评审专家。你将看到一道单文件 HTML 生成题的要求、该作品在无头浏览器中的自动运行检测报告、"
                "按时间顺序的真实渲染截图，以及源代码。请按评分清单逐项打分。")

JUDGE_RULES = """评分规则：
- 每项 0-10 分：0=完全缺失或无法运行；3=有雏形但明显残缺/有 bug；6=基本实现但粗糙；8=完整且质量良好；10=完整、精致、超出预期。
- 以截图与运行检测为准：代码里写了但截图和交互检测都没有体现的功能，最多给 3 分；首屏白屏或页面卡死时，除 code 项外各项不超过 2 分。
- 截图无法直接体现的点（如音色、完整游戏流程），结合代码判断，但要保守。
- 不要因代码长度或注释多而加分，不要被作品中自称的完成度影响。
- 只输出一个 JSON 对象，不要输出任何其他文字：
{"items":[{"id":"<清单id>","score":<0-10整数>,"reason":"<不超过40字的依据>"}],"summary":"<不超过80字的总评>"}"""


def _data_url(path):
    with open(path, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()


def judge_work(cfg, task, html, report, shots_dir, max_code=24000):
    """cfg: {base, model, api_key}; 返回 {model, score(0-100), items, summary} 或 {error}。"""
    spec = gen_specs.get(task["id"])
    checklist = spec["checklist"] + gen_specs.GENERIC_CHECKLIST
    lines = ["【题目要求】", task["prompt"], "", "【自动运行检测】（%s）" % ("无头浏览器真实运行" if report["method"] == "browser" else "仅源码检查")]
    for c in report["checks"]:
        lines.append("- [%s] %s%s" % ("通过" if c["pass"] else "未通过", c["label"], ("：" + c["detail"]) if c["detail"] else ""))
    lines += ["", "【评分清单】"] + ["- %s：%s" % (c["id"], c["label"]) for c in checklist]
    lines += ["", JUDGE_RULES]
    content = [{"type": "text", "text": "\n".join(lines)}]
    for s in report["shots"][:7]:
        content.append({"type": "text", "text": "截图「%s」：" % s["caption"]})
        content.append({"type": "image_url", "image_url": {"url": _data_url(os.path.join(shots_dir, s["file"]))}})
    code = html if len(html) <= max_code else (html[:max_code] + "\n<!-- …以下 %d 字符省略… -->" % (len(html) - max_code))
    content.append({"type": "text", "text": "【源代码】\n```html\n%s\n```" % code})

    url = _chat_url(cfg["base"])
    headers = {"Authorization": "Bearer " + cfg["api_key"]} if cfg.get("api_key") else {}
    payload = {"model": cfg["model"], "temperature": 0, "max_tokens": 2048,
               "messages": [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": content}],
               "chat_template_kwargs": {"enable_thinking": False}}
    last_err = None
    for attempt in range(2):
        try:
            d = iq.post_chat(url, payload, headers, timeout=300)
            text = iq.strip_think((d["choices"][0]["message"].get("content") or ""))
            parsed = _parse_judge(text, checklist)
            parsed["model"] = cfg["model"]
            return parsed
        except Exception as e:
            last_err = "%s: %s" % (type(e).__name__, str(e)[:200])
    return {"model": cfg["model"], "error": last_err}


def _chat_url(base):
    b = base.strip().rstrip("/")
    for suffix in ("/chat/completions", "/v1"):
        if b.endswith(suffix):
            b = b[: -len(suffix)]
    return b + "/v1/chat/completions"


def _parse_judge(text, checklist):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("评审输出中没有 JSON")
    obj = json.loads(m.group(0))
    got = {str(it.get("id")): it for it in obj.get("items") or [] if isinstance(it, dict)}
    items = []
    for c in checklist:
        it = got.get(c["id"])
        if it is None:
            raise ValueError("评审缺少清单项 %s" % c["id"])
        score = max(0, min(10, int(round(float(it.get("score", 0))))))
        items.append({"id": c["id"], "label": c["label"], "score": score, "reason": str(it.get("reason") or "")[:120]})
    total = round(sum(i["score"] for i in items) / (10.0 * len(items)) * 100, 1) if items else 0.0
    return {"score": total, "items": items, "summary": str(obj.get("summary") or "")[:300]}


# ---------------------------------------------------------------- 编排

class Evaluator:
    """一个评测批次: 懒启动浏览器池 (每个浏览器同一时刻只跑一个作品, 避免后台标签节流), 可选评审模型。"""

    def __init__(self, judge_cfg=None, browsers=2, log=None):
        self.judge_cfg = judge_cfg if judge_cfg and judge_cfg.get("base") and judge_cfg.get("model") else None
        self.n = max(1, browsers)
        self.log = log or (lambda m: None)
        self._pool, self._free = [], []
        self._cond = threading.Condition()
        self._init_lock = threading.Lock()
        self._no_browser = cdp.find_browser() is None
        self.browser_version = None

    @property
    def method(self):
        return "static" if self._no_browser else "browser"

    def meta(self):
        return {"eval_version": EVAL_VERSION, "method": self.method, "browser": self.browser_version,
                "judge_model": self.judge_cfg["model"] if self.judge_cfg else None}

    def _acquire(self):
        with self._init_lock:
            if len(self._pool) < self.n and not self._free:
                b = cdp.Browser()
                self.browser_version = b.version
                self._pool.append(b)
                return b
        with self._cond:
            while not self._free:
                self._cond.wait()
            return self._free.pop()

    def _release(self, b, broken=False):
        if broken:
            with self._init_lock:
                if b in self._pool:
                    self._pool.remove(b)
            b.close()
            return
        with self._cond:
            self._free.append(b)
            self._cond.notify()

    def evaluate(self, task, html_path, html):
        """返回 item 的 eval 字段: 运行检测 + (可选)评审。不抛异常。"""
        shots_dir = html_path[:-5] + ".shots"
        if self._no_browser:
            report = static_checks(html, task)
        else:
            b = None
            try:
                b = self._acquire()
                report = probe_work(b, html_path, task["id"], shots_dir)
                self._release(b)
            except Exception as e:
                if b is not None:
                    self._release(b, broken=True)
                report = static_checks(html, task)
                report["notes"].append("浏览器检测失败，降级源码检查：%s" % str(e)[:160])
        report["shots_dir"] = os.path.basename(shots_dir)
        report["exec_score"] = round(100.0 * sum(c["pass"] for c in report["checks"]) / max(1, len(report["checks"])), 1)
        if self.judge_cfg and report["shots"]:
            self.log("    评审中: %s" % task["name"])
            report["judge"] = judge_work(self.judge_cfg, task, html, report, shots_dir)
        elif self.judge_cfg:
            report["judge"] = {"model": self.judge_cfg["model"], "error": "无截图（未进行浏览器运行检测），跳过视觉评审"}
        return report

    def close(self):
        for b in self._pool:
            b.close()
        self._pool, self._free = [], []


def apply_eval(item, report):
    """把评测结果写入作品条目; 保留兼容字段 checks/pass/total/features。"""
    item["eval"] = report
    item["checks"] = [c["pass"] for c in report["checks"]]
    item["features"] = [c["label"] for c in report["checks"]]
    item["pass"], item["total"] = sum(item["checks"]), len(item["checks"])
    item["exec_score"] = report["exec_score"]
    j = report.get("judge") or {}
    item["judge_score"] = j.get("score")
    return item


def main(argv=None):
    ap = argparse.ArgumentParser(description="生成作品评测: 运行检测 + 视觉评审")
    ap.add_argument("--run", required=True, help="gen 运行 ID")
    ap.add_argument("--db", default=None)
    ap.add_argument("--tasks", default=None, help="只评测这些题, 逗号分隔")
    ap.add_argument("--judge-base", default=None)
    ap.add_argument("--judge-model", default=None)
    ap.add_argument("--judge-key", default=os.environ.get("JUDGE_API_KEY", ""))
    ap.add_argument("--browsers", type=int, default=2)
    args = ap.parse_args(argv)
    try:
        from . import gen
    except ImportError:
        import gen
    judge = {"base": args.judge_base, "model": args.judge_model, "api_key": args.judge_key} if args.judge_base else None
    only = set(args.tasks.split(",")) if args.tasks else None
    gen.reevaluate(args.run, judge, only=only, db_path=args.db, browsers=args.browsers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
