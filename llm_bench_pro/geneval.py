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
import shutil
import threading
import time

try:
    from . import cdp, gen_specs, iq
except ImportError:
    import cdp
    import gen_specs
    import iq

# 1.1: 交互判定基线与动作窗口等长、需作品处理器响应、忽略无变化的 DOM 重写; 按键码表; 移动端溢出判定;
#      白屏/截断时不白给分; 断言前后对照; 评审输出容错
# 1.2: 卡死/中断未跑的步骤记失败; 评审缺项记 0; 截图目录成功后才替换; 有开始按钮的动画在开始后测量
EVAL_VERSION = "1.2.0"
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
        try { if (e && e.type) S.calls[e.type] = (S.calls[e.type] || 0) + 1; } catch (err) {}
        return typeof fn === "function" ? fn.apply(this, arguments) : (fn && fn.handleEvent && fn.handleEvent(e));
      };
      wrapped.set(fn, w);
    }
    return add.call(this, type, w, opt);
  };
  EventTarget.prototype.removeEventListener = function (type, fn, opt) {
    return rem.call(this, type, (fn && wrapped.get(fn)) || fn, opt);
  };
  const INPUT = ["keydown","keyup","keypress","mousedown","mouseup","mousemove","click","dblclick","contextmenu",
                 "pointerdown","pointerup","pointermove","wheel","touchstart","touchmove","input","change","submit",
                 "mouseover","mouseout","pointerover","pointerout"];
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
  const same = (a, b) => a.length === b.length && Array.prototype.every.call(a, (n, i) =>
    n.nodeType === b[i].nodeType && (n.nodeType === 3 ? n.data === b[i].data : n.isEqualNode(b[i])));
  const real = r => r.type === "characterData" ? r.target.data !== r.oldValue
    : r.type === "attributes" ? r.target.getAttribute(r.attributeName) !== r.oldValue
    : !same(r.addedNodes, r.removedNodes);
  const startMO = () => new MutationObserver(l => { for (const r of l) if (real(r)) S.mutations++; })
    .observe(document.documentElement, {subtree: true, childList: true, attributes: true, characterData: true,
                                        attributeOldValue: true, characterDataOldValue: true});
  if (document.documentElement) startMO(); else add.call(document, "DOMContentLoaded", startMO);
})();
"""

# 预览沙箱和 file:// 评测共用: 内存 localStorage/sessionStorage, 每次加载都是空的。
# 沙箱不透明源访问原生 localStorage 会抛 SecurityError, 游戏在注册按键前读最高分就会停住;
# file:// 上的原生 localStorage 则会把上一次评测的存档留到下一次。
STORAGE_SHIM_JS = r"""
(function () {
  var mk = function () {
    var s = {};
    return {
      getItem: function (k) { k = String(k); return Object.prototype.hasOwnProperty.call(s, k) ? s[k] : null; },
      setItem: function (k, v) { s[String(k)] = String(v); },
      removeItem: function (k) { delete s[String(k)]; },
      clear: function () { s = {}; },
      key: function (i) { return Object.keys(s)[i] || null; },
      get length() { return Object.keys(s).length; }
    };
  };
  var put = function (obj, name) {
    try { Object.defineProperty(obj, name, { configurable: true, value: mk() }); } catch (e) {}
  };
  put(window, "localStorage");
  put(window, "sessionStorage");
  try {
    Object.defineProperty(document, "cookie", { configurable: true, get: function () { return ""; }, set: function () {} });
  } catch (e) {}
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
    const clickable = e.matches("button,a,[role=button],input,summary,select,[onclick]") || st.cursor === "pointer" ? 0 : 1;
    const rank = [clickable, a];
    if (!best || rank[0] < best.rank[0] || (rank[0] === best.rank[0] && rank[1] < best.rank[1]))
      best = {x: r.left + r.width / 2, y: r.top + r.height / 2, a, rank, text: (e.innerText || e.value || e.tagName).trim().slice(0, 24)};
  }
  return best;
})
"""

_KEYS = {"ArrowLeft": 37, "ArrowUp": 38, "ArrowRight": 39, "ArrowDown": 40, "Enter": 13, "Escape": 27,
         "Backspace": 8, "Tab": 9, " ": 32, "Shift": 16}
_CODES = {" ": "Space", "Enter": "Enter", "Escape": "Escape", "Backspace": "Backspace", "Tab": "Tab"}
# 美式键盘 OEM 键: 字符 -> (VK, code, 是否需 Shift)
_OEM = {";": (186, "Semicolon", 0), ":": (186, "Semicolon", 1), "=": (187, "Equal", 0), "+": (187, "Equal", 1),
        ",": (188, "Comma", 0), "<": (188, "Comma", 1), "-": (189, "Minus", 0), "_": (189, "Minus", 1),
        ".": (190, "Period", 0), ">": (190, "Period", 1), "/": (191, "Slash", 0), "?": (191, "Slash", 1),
        "`": (192, "Backquote", 0), "~": (192, "Backquote", 1), "[": (219, "BracketLeft", 0), "{": (219, "BracketLeft", 1),
        "\\": (220, "Backslash", 0), "|": (220, "Backslash", 1), "]": (221, "BracketRight", 0), "}": (221, "BracketRight", 1),
        "'": (222, "Quote", 0), '"': (222, "Quote", 1)}
_SHIFT_DIGITS = ")!@#$%^&*("


def _key_params(key):
    """返回 (CDP 按键参数, 输入文本)。非 ASCII 字符(如中文)只发 text, VK 为 0。"""
    shift = False
    if key in _KEYS:
        vk, code, text = _KEYS[key], _CODES.get(key, key), {" ": " ", "Enter": "\r"}.get(key)
    elif len(key) == 1 and key.isascii() and key.isalnum():
        vk = ord(key.upper())
        code = ("Key" + key.upper()) if key.isalpha() else ("Digit" + key)
        text, shift = key, key.isupper()
    elif key in _OEM:
        vk, code, shift = _OEM[key]
        text = key
    elif len(key) == 1 and key in _SHIFT_DIGITS:
        d = str(_SHIFT_DIGITS.index(key))
        vk, code, text, shift = ord(d), "Digit" + d, key, True
    elif len(key) == 1:
        vk, code, text = 0, "", key
    else:
        vk, code, text = 0, key, None
    p = {"key": key, "code": code, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
    if shift:
        p["modifiers"] = 8
    return p, text


def _action_time(a):
    """动作大致耗时(秒), 用于让空闲基线窗口与动作窗口等长。"""
    if "wait" in a:
        return a["wait"]
    if "key" in a:
        return a.get("repeat", 1) * (a.get("hold", 0) + 0.08)
    if "type" in a:
        return len(a["type"]) * 0.04
    if "drag" in a:
        return a.get("steps", 12) * 0.02 + 0.05
    if "move" in a:
        return max(0, len(a["move"]) - 1) * 8 * 0.02
    return 0.1


# 仅因无头环境产生、真实浏览器中不会出现的错误(指针锁定、全屏、音频自动播放限制), 不计为作品异常
_HEADLESS_ONLY = re.compile(r"pointer ?lock|requestPointerLock|fullscreen|play\(\) failed because the user didn't interact", re.I)


def _nonblank(st):
    """首屏是否有内容: 少量多色元素(大面积纯色桌面/背景上的界面), 或非主色像素占比达 1%(扁平色块画面)。"""
    return (st["dominant_ratio"] < 0.998 and st["colors"] > 4) or st["dominant_ratio"] < 0.99


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
        return [m for m in out if not _HEADLESS_ONLY.search(m)]

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
                if a.get("else"):
                    for sub in a["else"]:
                        self.run_action(sub)
                        time.sleep(0.08)
                    return True, ""
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
            fill_skipped(self, spec, "页面卡死，未检测")
            return

        a = self.small()
        st = cdp.image_stats(a)
        nonblank = _nonblank(st)
        self.shot("01_initial", "首屏（加载后约 1.2 秒）")
        self.check("nonblank", "首屏有实际渲染内容（非白屏/纯色）", nonblank,
                   "主色占比 %.1f%%，颜色数 %d" % (st["dominant_ratio"] * 100, st["colors"]))

        ps0 = self.probe_state()
        time.sleep(spec["idle"])
        b = self.small()
        ps1 = self.probe_state()
        idle_diff = cdp.image_diff(a, b)
        self.shot("02_idle", "空闲 %.1f 秒后" % spec["idle"])
        self.blank = not nonblank
        if spec["animated"]:
            self._mark_animated(idle_diff, ps0, ps1)

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
        if self.blank:  # 白屏(常见于脚本被截断未执行)时"无异常"没有意义, 不计通过
            self.check("no_error", "运行无未捕获异常/控制台错误", False, "首屏白屏，无法确认脚本正常运行")
        else:
            self.check("no_error", "运行无未捕获异常/控制台错误", not errs,
                       ("%d 条：%s" % (len(errs), "；".join(dict.fromkeys(errs))))[:300] if errs else "")

        if spec["responsive"]:
            self.run_mobile(url)

    def _mark_animated(self, diff, ps0, ps1):
        active = (ps1.get("raf", 0) > ps0.get("raf", 0) or ps1.get("draws", 0) > ps0.get("draws", 0)
                  or ps1.get("mutations", 0) > ps0.get("mutations", 0))
        self.check("animated", "空闲时持续动画/渲染", diff > 0.003 or (diff > 0.0005 and active),
                   "画面变化 %.2f%%，rAF %d 次，绘制调用 %d 次" % (diff * 100, ps1.get("raf", 0) - ps0.get("raf", 0),
                                                        ps1.get("draws", 0) - ps0.get("draws", 0)))

    def _measure(self, js):
        try:
            return self.pg.evaluate("(() => { try { return %s; } catch (e) { return null; } })()" % js, timeout=5)
        except cdp.CDPError:
            return None

    def run_step(self, i, stp):
        label, settle = stp["label"], stp.get("settle", 0.6)
        cid = "step%d" % (i + 1)
        try:
            # 鼠标移出页面, 避免上一步残留的 :hover 样式在本步前后截图中产生差异
            self.mouse("mouseMoved", 1, 1)
            time.sleep(0.1)
            # 基线窗口与动作窗口等长: 每帧自然变化的页面(HUD 计时/背景动画)不会因动作耗时长而"看起来"有响应
            window = settle + sum(_action_time(a) + 0.08 for a in stp["actions"])
            pre_assert = self._measure(stp["assert"]) if stp.get("assert") else None
            pre_count = self._measure(stp["count"]) if stp.get("count") else None
            pre1 = self.small()
            ps_a = self.probe_state()
            t_base = time.monotonic()
            time.sleep(window)
            pre2 = self.small()
            ps_b = self.probe_state()
            base_dt = time.monotonic() - t_base
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
            act_dt = time.monotonic() - t0
            diff = cdp.image_diff(pre2, post)
            mut = ps_c.get("mutations", 0) - ps_b.get("mutations", 0)
            base_mut = base_mut * act_dt / max(base_dt, 0.05)  # 两窗口实际时长仍有出入时按时长折算
            handled = sum(ps_c.get("calls", {}).values()) - sum(ps_b.get("calls", {}).values())
            errs = self.exceptions(t0)
            if not ok_actions:
                passed, why = False, "；".join(notes)
            elif errs:
                passed, why = False, "交互触发异常：%s" % errs[0]
            elif stp.get("assert") or stp.get("count"):
                passed, why = self._poll_assert(stp, pre_assert, pre_count)
            else:
                # 证据任一成立即判定生效: 画面变化显著超出等长空闲基线 / DOM 实际变更超出基线 /
                # 作品自身事件处理器被调用, 且画面变化略超基线(如方块旋转)或动画节奏明显改变(如暂停)。
                # 作品没有任何处理器响应该输入时一律不算生效(纯 CSS :hover 或自走动画), 原生交互(滚动/悬停样式)除外。
                visual = diff > max(base_diff * 1.5 + 0.001, 0.002)
                dom = mut > base_mut * 1.5 + 2
                rhythm = abs(diff - base_diff) > max(0.003, base_diff * 0.5)
                passed = visual or dom or (handled > 0 and (diff > base_diff * 1.15 + 0.0005 or rhythm))
                why = "画面变化 %.2f%%（等长空闲基线 %.2f%%），DOM 变更 %d（基线 %.0f），事件处理 %d 次" % (
                    diff * 100, base_diff * 100, mut, base_mut, handled)
                if passed and handled == 0 and not stp.get("native"):
                    passed, why = False, why + "；作品没有处理该输入，变化来自自身动画或样式"
            if len(self.shots) < 7:
                self.shot("%02d_step%d" % (i + 3, i + 1), "交互「%s」之后" % label)
            if notes and ok_actions:
                why = "；".join(notes) + "；" + why
            self.check(cid, "交互：" + label, passed, why)
        except cdp.CDPError as e:
            self.check(cid, "交互：" + label, False, "页面无响应：%s" % e)

    def _poll_assert(self, stp, pre_assert, pre_count, extra=3.0):
        """功能断言: 操作前不成立、操作后成立才算通过(计数型断言要求增量达到 gain); 逐字输出等慢渲染最多再等 extra 秒。"""
        end = time.monotonic() + extra
        while True:
            if stp.get("count"):
                now = self._measure(stp["count"])
                gain = stp.get("gain", 1)
                ok = isinstance(now, (int, float)) and isinstance(pre_count, (int, float)) and now - pre_count >= gain
                why = "功能断言%s（计数 %s → %s，需增加 %d）" % ("通过" if ok else "未通过", pre_count, now, gain)
            else:
                now = self._measure(stp["assert"])
                if pre_assert:
                    return False, "功能断言在操作前已成立，无法确认由本次操作产生"
                ok = bool(now)
                why = "功能断言%s" % ("通过" if ok else "未通过")
            if ok or time.monotonic() >= end:
                return ok, why
            time.sleep(0.4)

    def run_mobile(self, url):
        label = _RESP_LABEL
        if self.blank:
            self.check("responsive", label, False, "桌面首屏白屏，不检查移动端")
            return
        try:
            t = time.monotonic()
            self.load(url, mobile=True)
            time.sleep(1.0)
            # 移动模拟下内容过宽会撑大布局视口(innerWidth 随之变大), 须与设备宽度比较
            m = json.loads(self.pg.evaluate(
                "JSON.stringify({sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth, "
                "iw: innerWidth, meta: !!document.querySelector('meta[name=viewport]')})"))
            st = cdp.image_stats(self.small())
            self.shot("09_mobile", "移动端 390px 视口")
            limit = MOBILE_W + 4
            problems = []
            if not m["meta"]:
                problems.append("缺少 viewport meta")
            if max(m["sw"], m["cw"], m["iw"]) > limit:
                problems.append("布局宽 %dpx 超出设备宽 %dpx" % (max(m["sw"], m["cw"], m["iw"]), MOBILE_W))
            if not _nonblank(st):
                problems.append("移动端白屏")
            errs = [e for e in self.exceptions(t)]
            if errs:
                self.notes.append("移动端加载异常：%s" % errs[0])
            self.check("responsive", label, not problems,
                       "；".join(problems) if problems else "内容宽 %dpx / 设备宽 %dpx" % (m["sw"], MOBILE_W))
        except cdp.CDPError as e:
            self.check("responsive", label, False, str(e))


def external_requests(page):
    out = []
    for _, m, p in list(page.events):
        if m == "Network.requestWillBeSent":
            u = (p.get("request") or {}).get("url", "")
            if re.match(r"^(https?|wss?):", u) and not any(e["url"] == u[:160] for e in out):
                out.append({"url": u[:160], "type": p.get("type") or ""})
    return out


_LITERAL = re.compile(r"<!--.*?-->|/\*.*?\*/|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`", re.S)


def _mask_literals(html):
    """去掉注释和字符串, 避免脚本里的 `<script>` 文本被当成真标签。"""
    html = _LITERAL.sub(" ", html)
    return re.sub(r"(?m)(^|[^:\"'\\])//[^\n]*", r"\1", html)


def source_complete(html):
    low = _mask_literals(html).lower()
    return "</html>" in low and len(re.findall(r"<script\b[^>]*>", low)) <= low.count("</script>")


_RESP_LABEL = "移动端 390px 适配（viewport 声明、无横向溢出）"


def fill_skipped(prober, spec, why):
    """没跑到的功能项记失败, 避免卡死或中断后这些项从通过率里消失。"""
    have = {c["id"] for c in prober.checks}
    if "nonblank" not in have:
        prober.check("nonblank", "首屏有实际渲染内容（非白屏/纯色）", False, why)
    if spec.get("animated") and "animated" not in have:
        prober.check("animated", "空闲时持续动画/渲染", False, why)
    for i, stp in enumerate(spec.get("steps") or []):
        cid = "step%d" % (i + 1)
        if cid not in have:
            prober.check(cid, "交互：" + stp["label"], False, why)
    if "no_error" not in have:
        prober.check("no_error", "运行无未捕获异常/控制台错误", False, why)
    if spec.get("responsive") and "responsive" not in have:
        prober.check("responsive", _RESP_LABEL, False, why)


def _commit_shots(tmp, shots_dir):
    """新截图写在临时目录, 成功后整目录替换, 失败时旧截图还在。"""
    if not os.path.isdir(tmp):
        return
    shutil.rmtree(shots_dir, ignore_errors=True)
    os.rename(tmp, shots_dir)


def probe_work(browser, html_path, task_id, shots_dir):
    spec = gen_specs.get(task_id)
    tmp = shots_dir + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    page = browser.new_page()
    prober = Prober(page, spec, tmp)
    prober.blank = False
    ext = []
    try:
        with open(html_path, encoding="utf-8", errors="replace") as f:
            prober.check("complete", "代码完整输出（</html> 闭合、script 配对）", source_complete(f.read()), "")
        try:
            page.send("Page.enable")
            page.send("Runtime.enable")
            page.send("Network.enable")
            page.send("Network.setBlockedURLs", {"urls": ["http://*", "https://*", "ws://*", "wss://*"]})
            page.send("Emulation.setFocusEmulationEnabled", {"enabled": True})
            page.send("Page.addScriptToEvaluateOnNewDocument", {"source": STORAGE_SHIM_JS})
            page.send("Page.addScriptToEvaluateOnNewDocument", {"source": INSTRUMENT_JS})
            prober.run(pathlib.Path(html_path).resolve().as_uri())
        except cdp.CDPError as e:
            prober.notes.append("检测中断: %s" % e)
            if not any(c["id"] == "load" for c in prober.checks):
                prober.check("load", "页面加载完成且未卡死", False, str(e))
            else:
                prober.check("probe", "运行检测完整执行", False, "检测中断（页面无响应或超时）：%s" % str(e)[:160])
            fill_skipped(prober, spec, "检测中断，未执行")
        ext = external_requests(page)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    finally:
        try:
            page.close()
        except Exception:
            pass
    _commit_shots(tmp, shots_dir)
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


def static_checks(html, task, note=None):
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
    return {"method": "static", "browser": None, "checks": checks, "shots": [],
            "notes": [note or "未找到无头浏览器，降级为源码检查"], "external": []}


# ---------------------------------------------------------------- 视觉评审

JUDGE_SYSTEM = ("你是严格、客观的前端作品评审专家。你将看到一道单文件 HTML 生成题的要求、该作品在无头浏览器中的自动运行检测报告、"
                "按时间顺序的真实渲染截图，以及源代码。请按评分清单逐项打分。")

JUDGE_RULES = """评分规则：
- 每项 0-10 分：0=完全缺失或无法运行；3=有雏形但明显残缺/有 bug；6=基本实现但粗糙；8=完整且质量良好；10=完整、精致、超出预期。
- 以截图为主要依据。运行检测是自动脚本的结果，可能误判，与截图矛盾时以截图为准。
- 截图能体现的功能（布局、配色、动画帧、交互后的画面）：截图中看不到就最多给 3 分。
- 自动脚本无法触发的功能（如道具掉落、录音回放、还原检测、多关卡、音色）：根据代码核实，实现完整且逻辑正确最多给 7 分，只有雏形或有明显 bug 不超过 3 分。
- 首屏白屏或页面卡死时，除 code 项外各项不超过 2 分。
- 不要因代码长度或注释多而加分，不要被作品中自称的完成度影响。
- 只输出一个 JSON 对象，不要输出任何其他文字：
{"items":[{"id":"<清单id>","score":<0-10整数>,"reason":"<不超过40字的依据>"}],"summary":"<不超过80字的总评>"}"""


def _data_url(path):
    with open(path, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()


def _script_ranges(html):
    """每个 <script> 的 [start, end)。字符串和注释里的 </script> 不结束脚本。"""
    low = html.lower()
    i, n = 0, len(html)
    spans = []
    while i < n:
        start = low.find("<script", i)
        if start < 0 or (start and (html[start - 1].isalnum() or html[start - 1] in "_")):
            if start < 0:
                break
            i = start + 7
            continue
        gt = html.find(">", start)
        if gt < 0:
            spans.append((start, n))
            break
        j = gt + 1
        end = n
        while j < n:
            c = html[j]
            if c in "\"'`":
                j += 1
                while j < n:
                    if html[j] == "\\":
                        j += 2
                        continue
                    if html[j] == c:
                        j += 1
                        break
                    j += 1
                continue
            if html.startswith("//", j):
                nl = html.find("\n", j)
                j = n if nl < 0 else nl + 1
                continue
            if html.startswith("/*", j):
                close = html.find("*/", j + 2)
                j = n if close < 0 else close + 2
                continue
            if low.startswith("</script>", j):
                end = j + len("</script>")
                break
            j += 1
        spans.append((start, end))
        i = end
    return spans


def _clip_ends(text, budget):
    """超长时保留头尾, 中间用一行说明代替。游戏逻辑经常在脚本后部。"""
    if len(text) <= budget:
        return text
    if budget < 48:
        return text[:max(0, budget)]
    tail = max(16, budget // 3)
    note = ""
    head = budget - tail
    while True:
        omitted = len(text) - head - tail
        note = "\n/* …省略 %d 字符… */\n" % max(0, omitted)
        if head + len(note) + tail <= budget or head <= 16:
            break
        head -= 1
    return text[:head] + note + text[-tail:]


def _code_excerpt(html, max_code):
    """代码过长时: 去掉 SVG path 数据与 base64, 仍超长则保留页头, 并带上每个脚本的头和尾。"""
    if len(html) <= max_code:
        return html
    slim = re.sub(r'(\sd=")[^"]{200,}(")', r"\1…\2", html)
    slim = re.sub(r"(data:[\w/+.-]+;base64,)[A-Za-z0-9+/=]{200,}", r"\1…", slim)
    if len(slim) <= max_code:
        return slim
    spans = _script_ranges(slim)
    scripts = [slim[a:b] for a, b in spans]
    if not scripts:
        return slim[:max_code]
    script_budget = max_code // 2
    sep = "\n<!-- …中间 HTML/CSS 省略，以下为脚本… -->\n"
    body_budget = max(0, script_budget - len(sep))
    per = max(1, body_budget // len(scripts))
    body = "\n".join(_clip_ends(s, per) for s in scripts)
    if len(body) > body_budget:
        body = _clip_ends(body, body_budget)
    head_budget = max(0, max_code - len(sep) - len(body))
    head = slim[:head_budget]
    # 页头已经完整包含的脚本不必再贴一次
    if all(b <= head_budget for _, b in spans):
        return head
    return head + sep + body


def judge_work(cfg, task, html, report, shots_dir, max_code=32000):
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
    code = _code_excerpt(html, max_code)
    content.append({"type": "text", "text": "【源代码】\n```html\n%s\n```" % code})

    url = _chat_url(cfg["base"])
    headers = {"Authorization": "Bearer " + cfg["api_key"]} if cfg.get("api_key") else {}
    payload = {"model": cfg["model"], "temperature": 0, "max_tokens": 2048,
               "messages": [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": content}],
               "chat_template_kwargs": {"enable_thinking": False}}
    last_err = None
    for attempt in range(2):
        text = None
        try:
            d = iq.post_chat(url, payload, headers, timeout=300)
            text = iq.strip_think((d["choices"][0]["message"].get("content") or ""))
            parsed = _parse_judge(text, checklist)
            parsed["model"] = cfg["model"]
            return parsed
        except Exception as e:
            last_err = "%s: %s" % (type(e).__name__, str(e)[:200])
            code = getattr(e, "code", None)
            if isinstance(code, int) and 400 <= code < 500 and code != 429:
                break  # 请求本身有误, 重试无意义
            if text is not None:  # 输出无法解析: 带上原输出要求修正
                payload = dict(payload, messages=payload["messages"] + [
                    {"role": "assistant", "content": text[:4000]},
                    {"role": "user", "content": "上面的输出无法解析（%s）。请只输出符合要求格式的 JSON 对象，包含全部清单项。" % str(e)[:100]}])
    return {"model": cfg["model"], "error": last_err}


def _chat_url(base):
    b = base.strip().rstrip("/")
    for suffix in ("/chat/completions", "/v1"):
        if b.endswith(suffix):
            b = b[: -len(suffix)]
    return b + "/v1/chat/completions"


def _find_judge_json(text):
    """从评审输出中找出含 items 列表的 JSON 对象(容忍前后说明文字、代码围栏、尾随逗号、中文标点)。"""
    dec = json.JSONDecoder()
    variants = [text, re.sub(r",\s*([}\]])", r"\1", text.replace("：", ":").replace("，", ",").replace("“", '"').replace("”", '"'))]
    for t in variants:
        for m in re.finditer(r"\{", t):
            try:
                obj, _ = dec.raw_decode(t, m.start())
            except ValueError:
                continue
            if isinstance(obj, dict) and isinstance(obj.get("items"), list):
                return obj
    raise ValueError("评审输出中没有包含 items 的 JSON")


def _score_of(v):
    m = re.search(r"-?\d+(?:\.\d+)?", str(v)) if v is not None else None
    return float(m.group(0)) if m else None


def _parse_judge(text, checklist):
    obj = _find_judge_json(text)
    got = {str(it.get("id")).strip().lower(): it for it in obj["items"] if isinstance(it, dict)}
    raw = {c["id"]: _score_of((got.get(c["id"].lower()) or {}).get("score")) for c in checklist}
    valid = [v for v in raw.values() if v is not None]
    missing = [k for k, v in raw.items() if v is None]
    if not valid or len(missing) > len(checklist) * 0.2:
        raise ValueError("评审缺少清单项 %s" % "、".join(missing))
    nonzero = [v for v in valid if v > 0]
    hundred = sum(1 for v in nonzero if v > 10) * 2 > len(nonzero)  # 多数项超过 10: 按 100 分制打分, 折算; 个别超出则截断
    items = []
    for c in checklist:
        v = raw[c["id"]]
        it = got.get(c["id"].lower()) or {}
        score = None if v is None else max(0, min(10, int(v / 10.0 + 0.5) if hundred else int(v + 0.5)))
        items.append({"id": c["id"], "label": c["label"], "score": score, "reason": str(it.get("reason") or "")[:120]})
    scored = [i["score"] for i in items if i["score"] is not None]
    total = round(sum(scored) / (10.0 * len(scored)) * 100, 1)
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
        self._starting = 0
        self.closed = False
        self._no_browser = cdp.find_browser() is None
        self.browser_version = None

    @property
    def method(self):
        return "static" if self._no_browser else "browser"

    def meta(self):
        return {"eval_version": EVAL_VERSION, "method": self.method, "browser": self.browser_version,
                "judge_model": self.judge_cfg["model"] if self.judge_cfg else None}

    def _acquire(self):
        with self._cond:
            while True:
                if self.closed:
                    raise RuntimeError("评测已结束")
                if self._free:
                    return self._free.pop()
                if len(self._pool) + self._starting < self.n:
                    self._starting += 1
                    break
                self._cond.wait()
        try:
            b = cdp.Browser()
        except BaseException:
            with self._cond:
                self._starting -= 1
                self._cond.notify_all()
            raise
        with self._cond:
            self._starting -= 1
            self.browser_version = b.version
            if self.closed:
                b.close()
                raise RuntimeError("评测已结束")
            self._pool.append(b)
            return b

    def _release(self, b, broken=False):
        with self._cond:
            if broken or self.closed:
                if b in self._pool:
                    self._pool.remove(b)
            else:
                self._free.append(b)
            self._cond.notify_all()  # 浏览器损坏时唤醒等待者去新建, 避免永久等待
        if broken or self.closed:
            b.close()

    def evaluate(self, task, html_path, html, cancel=None):
        """返回 item 的 eval 字段: 运行检测 + (可选)评审。不抛异常。cancel 置位后不再开始视觉评审。"""
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
                report = static_checks(html, task, "浏览器检测失败，降级为源码检查：%s" % str(e)[:160])
        report["shots_dir"] = os.path.basename(shots_dir)
        report["exec_score"] = round(100.0 * sum(c["pass"] for c in report["checks"]) / max(1, len(report["checks"])), 1)
        if self.closed or (cancel is not None and cancel.is_set()):
            return report
        if self.judge_cfg and report["shots"]:
            self.log("    评审中: %s" % task["name"])
            report["judge"] = judge_work(self.judge_cfg, task, html, report, shots_dir)
        elif self.judge_cfg:
            report["judge"] = {"model": self.judge_cfg["model"], "error": "无截图（未进行浏览器运行检测），跳过视觉评审"}
        return report

    def close(self):
        with self._cond:
            self.closed = True
            pool, self._pool, self._free = self._pool, [], []
            self._cond.notify_all()
        for b in pool:
            b.close()


def eval_method(items):
    """按作品上记录的检测方式汇总: browser / static / mixed。没有评测结果时返回空串。"""
    methods = set()
    for it in items or []:
        if it.get("error"):
            continue
        m = (it.get("eval") or {}).get("method")
        if m:
            methods.add(m)
    if not methods:
        return ""
    if methods == {"static"}:
        return "static"
    if "static" in methods and "browser" in methods:
        return "mixed"
    return "browser" if "browser" in methods else ""


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
