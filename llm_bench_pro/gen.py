#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen.py — 真实生成效果测试引擎
四档题库(普通/困难/地狱/实战 33 题) -> 模型生成完整 HTML -> 特征自动检查 + 人工星级。
作品落盘 works/, 元数据落 results/gen_*.json。
"""
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

GEN_VERSION = "1.1.0"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根(包上一级)
WORKS = os.path.join(ROOT, "works")

GEN_TASKS = [
    # ---- 普通: 视觉动画 ----
    {"id": "pelican", "name": "鹈鹕骑自行车动画", "tags": ["普通", "动画"],
     "prompt": "用单个 HTML 文件（内联 CSS 和 JS）实现：一只鹈鹕骑自行车的 2D 动画，车轮旋转、腿部踩踏、地面背景滚动。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"<svg|<canvas", r"animation|requestAnimationFrame|@keyframes|setInterval"]},
    {"id": "earth", "name": "可拖拽 3D 地球", "tags": ["普通", "3D"],
     "prompt": "用单个 HTML 文件实现 3D 旋转地球：大陆轮廓、渐变海洋、星空背景、大气光晕，鼠标拖拽改变视角，滚轮缩放。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"<canvas|transform.*3d|rotate", r"mousemove|mousedown|pointer|drag"]},
    {"id": "blackhole", "name": "黑洞吸积盘", "tags": ["普通", "特效"],
     "prompt": "用单个 HTML 文件实现黑洞可视化：事件视界、发光吸积盘旋转、引力透镜弯曲背景星光、粒子被吸入。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"<canvas|<svg", r"requestAnimationFrame|@keyframes"]},
    {"id": "matrix", "name": "矩阵字符雨", "tags": ["普通", "特效"],
     "prompt": "用单个 HTML 文件实现黑客帝国矩阵字符雨：绿色字符瀑布、多层速度视差、随机高亮、鼠标处字符加速。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"<canvas", r"requestAnimationFrame|setInterval"]},
    {"id": "koi", "name": "锦鲤池塘", "tags": ["普通", "动画"],
     "prompt": "用单个 HTML 文件实现锦鲤池塘：多条锦鲤自主游动与转向、鱼尾摆动、水面涟漪、荷叶，点击水面产生涟漪惊散鱼群。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"<canvas|<svg", r"click|mousemove", r"requestAnimationFrame|animation"]},
    {"id": "fireworks", "name": "点击烟花", "tags": ["普通", "交互"],
     "prompt": "用单个 HTML 文件实现点击放烟花：鼠标点击处烟花爆炸、粒子有重力/空气阻力/拖尾、不同花型随机、夜空星星背景。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"<canvas", r"click|mousedown", r"gravity|9.8|velocity|particle"]},
    {"id": "solar", "name": "太阳系模拟", "tags": ["普通", "模拟"],
     "prompt": "用单个 HTML 文件实现太阳系：八大行星真实相对轨道周期与距离（对数缩放）、发光太阳、轨道线、行星名与信息悬浮卡、时间加速减速暂停控制。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"<canvas|<svg", r"button|input.*range", r"requestAnimationFrame|animation"]},
    {"id": "landing", "name": "产品落地页", "tags": ["普通", "UI"],
     "prompt": "用单个 HTML 文件实现 AI 产品落地页：粘性导航、英雄区渐变与粒子背景、三特性卡、带悬停动效的价格表、常见问题手风琴、页脚，完全响应式。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"nav|header", r"grid|flex", r"@media", r"hover|transition"]},
    {"id": "dashboard", "name": "数据看板", "tags": ["普通", "图表"],
     "prompt": "用单个 HTML 文件实现暗色数据看板：侧边栏路由切换、4 个动效指标卡、纯 Canvas 折线图（带悬浮提示）与环形图、实时数据刷新模拟、响应式。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"sidebar|nav", r"canvas|svg", r"card|grid", r"setInterval|刷新"]},
    # ---- 困难: 完整游戏机制 ----
    {"id": "flappy", "name": "Flappy Bird", "tags": ["困难", "游戏"],
     "prompt": "用单个 HTML 文件实现完整 Flappy Bird：重力下落、点击/空格跳跃、随机管道间隙、碰撞死亡、计分、最佳分记录、死亡重开。像素风格。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"<canvas", r"click|keydown|space", r"gravity|velocity|jump", r"score|best"]},
    {"id": "tetris", "name": "俄罗斯方块", "tags": ["困难", "游戏"],
     "prompt": "用单个 HTML 文件实现完整俄罗斯方块：全部 7 种标准方块、旋转踢墙、软降硬降、消行计分与等级加速、下一个方块预览、暂停、游戏结束重开、方向键操作。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"<canvas|grid", r"keydown", r"rotate|旋转", r"score|line|消", r"next|预览"]},
    {"id": "breakout", "name": "打砖块 Breakout", "tags": ["困难", "游戏"],
     "prompt": "用单个 HTML 文件实现完整打砖块：鼠标/键盘控制挡板、球与砖块碰撞反弹、多排彩色砖块不同分值、道具掉落（加长挡板/多球）、多条命、关卡递进、胜负判定。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"<canvas", r"mousemove|keydown", r"collid|碰撞|bounce", r"score|lives|level"]},
    {"id": "ninja", "name": "切水果忍者", "tags": ["困难", "游戏"],
     "prompt": "用单个 HTML 文件实现切水果游戏：水果抛物线抛出、鼠标划过切割（刀光轨迹）、切开两半带果汁粒子、炸弹切割扣命、连击计分、限时模式。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"<canvas", r"mousemove|touch", r"gravity|velocity", r"score|combo|连击"]},
    {"id": "platformer", "name": "2D 平台跳跃", "tags": ["困难", "游戏"],
     "prompt": "用单个 HTML 文件实现 2D 平台跳跃游戏：角色重力跳跃（土狼时间+跳跃缓冲）、平台碰撞、移动敌人、金币收集、尖刺死亡、旗杆过关、多关卡、生命与重生。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"<canvas", r"keydown", r"gravity|jump", r"level|coin|生命"]},
    {"id": "snake", "name": "贪吃蛇", "tags": ["困难", "游戏"],
     "prompt": "用单个 HTML 文件实现贪吃蛇：网格移动、方向键且禁止反向、吃食物变长加速、撞墙/撞己死亡、分数与最高分、开始/暂停/重开。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"<canvas|grid", r"keydown", r"score"]},
    # ---- 地狱: 引擎级 ----
    {"id": "fps", "name": "3D 第一人称迷宫", "tags": ["地狱", "引擎"],
     "prompt": "用单个 HTML 文件（无外部库）实现 3D 第一人称迷宫：raycasting 体素渲染、WASD 移动+鼠标转向、墙壁碰撞、地面天花板渐变、地图迷宫、到达出口胜利计时。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"<canvas", r"raycast|ray|fov|projection|3d", r"keydown|wasd", r"map|maze"]},
    {"id": "cube3d", "name": "可拧 3D 魔方", "tags": ["地狱", "引擎"],
     "prompt": "用单个 HTML 文件实现可交互 3D 魔方：27 个小方块组成、整体旋转视角、点击拖动某一层旋转 90 度（分层拧动动画）、打乱按钮、还原检测、计时步数。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"<canvas|3d|rotateX", r"mousedown|pointer", r"rotate|拧|turn", r"scramble|打乱"]},
    {"id": "pinball", "name": "物理弹珠台", "tags": ["地狱", "引擎"],
     "prompt": "用单个 HTML 文件实现 2D 物理弹珠台：自实现刚体物理（重力、圆与线段碰撞反弹、动量衰减）、挡板空格弹射、弹射器发球、钉板/缓冲器加分、防止掉落、计分与球数。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"<canvas", r"space|keydown", r"collid|碰撞|bounce|物理", r"score|ball"]},
    {"id": "fluid", "name": "实时流体模拟", "tags": ["地狱", "引擎"],
     "prompt": "用单个 HTML 文件实现实时流体模拟：稳定流体解算（速度场+密度场扩散与平流）、鼠标拖动注入流体、彩色染料、矢量场可视化可切换。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"<canvas", r"velocity|density|advect|扩散|流体", r"mousemove"]},
    {"id": "eco", "name": "生态进化模拟", "tags": ["地狱", "模拟"],
     "prompt": "用单个 HTML 文件实现生态模拟：草-食草动物-捕食者三层智能体、能量/繁殖/饥饿/自然死亡、遗传变异速度视野、实时种群曲线图、点击投放、可调参数滑块。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"<canvas", r"reproduce|energy|能量|繁殖", r"chart|曲线|graph", r"input.*range|slider|滑块"]},
    {"id": "piano", "name": "可弹奏钢琴", "tags": ["地狱", "引擎"],
     "prompt": "用单个 HTML 文件实现 Web Audio 钢琴：合成琴音（包络+泛音）、两排琴键键盘映射可弹奏、按住延音、录音与回放、简单内置示例曲自动播放、视觉琴键按下反馈。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"AudioContext|oscillator", r"keydown", r"record|录音|playback|回放", r"key|琴键"]},
    {"id": "sortviz", "name": "排序算法可视化", "tags": ["地狱", "可视化"],
     "prompt": "用单个 HTML 文件实现排序可视化：至少 6 种算法（冒泡/选择/插入/归并/快排/堆排）并排或切换对比、柱状图实时交换高亮、复杂度与耗时统计、自定义数组大小与随机种子、播放速度控制。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"<canvas|div.*bar|柱", r"bubble|quick|merge|sort", r"speed|速度", r"time|耗时|complexity|复杂度"]},
    {"id": "win95", "name": "Win95 桌面模拟", "tags": ["地狱", "模拟"],
     "prompt": "用单个 HTML 文件模拟 Win95 桌面：可拖拽窗口（标题栏+关闭/最小化）、层叠 z-order、开始菜单级联、任务栏与时钟、图标双击打开记事本（可输入保存到 localStorage）和画板（可画图）、右键菜单。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"drag|拖", r"z-?index", r"start|开始菜单", r"contextmenu|右键", r"localStorage|notepad|画"]},
    # ---- 实战: 真实开发 · 美观与细节 ----
    {"id": "applecard", "name": "Apple 产品卡复刻", "tags": ["实战", "美观"],
     "prompt": "用单个 HTML 文件复刻 Apple 官网风格的产品介绍页：大标题渐变文字、居中产品渲染感、毛玻璃导航栏(backdrop-filter)、滚动淡入动画、精确的留白与字体层级、暗色优雅配色。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"backdrop-filter|blur", r"gradient|渐变", r"scroll|IntersectionObserver", r"@media|clamp"]},
    {"id": "stripe", "name": "Stripe 英雄区复刻", "tags": ["实战", "美观"],
     "prompt": "用单个 HTML 文件复刻 Stripe 首页英雄区：斜向彩色渐变背景(canvas 绘制动态网格/波浪)、渐变大标题、按钮悬停微交互、导航栏、三列特性说明、像素级间距。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"<canvas", r"gradient", r"hover|transition", r"grid|flex"]},
    {"id": "iostodo", "name": "iOS 待办 App", "tags": ["实战", "细节"],
     "prompt": "用单个 HTML 文件实现 iOS 风格待办应用：手机壳容器、毛玻璃工具栏、圆角卡片列表、左滑删除、勾选划线动效、新增输入弹层、深浅色切换、按压缩放细节。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"backdrop-filter|blur|rgba", r"transition|animation", r"swipe|touch|滑动", r"checkbox|check|勾"]},
    {"id": "ecomdetail", "name": "电商商品详情页", "tags": ["实战", "细节"],
     "prompt": "用单个 HTML 文件实现电商详情页：图集缩略图切换淡入、价格与优惠标签、SKU 颜色/尺码选择器(选中态)、数量步进器、吸底购买栏、加入购物车飞入动画、评价卡片区。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"click|onclick", r"sku|size|color|尺码|颜色", r"transition|animation|飞", r"sticky|fixed"]},
    {"id": "ioscalc", "name": "iOS 计算器复刻", "tags": ["实战", "细节"],
     "prompt": "用单个 HTML 文件像素级复刻 iOS 计算器：网格布局、深色数字键/橙色运算键、圆形按键、按压缩放动效、顶部小字历史行、完整四则与百分比/正负/退格逻辑、安全区适配。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"grid", r"active|transform.*scale|按压", r"operator|compute|计算|\\+", r"@media"]},
    {"id": "dock", "name": "Mac Dock 栏", "tags": ["实战", "交互"],
     "prompt": "用单个 HTML 文件实现 macOS Dock：图标横向排列、鼠标接近时鱼眼放大(邻近图标按距离缩放)、悬停显示名称气泡、点击弹跳动画、反光底部、可用 emoji 或 SVG 图标。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"mousemove", r"scale|放大", r"transition", r"tooltip|气泡|title"]},
    {"id": "terminal", "name": "macOS 终端模拟", "tags": ["实战", "细节"],
     "prompt": "用单个 HTML 文件实现 macOS 风格终端：标题栏红黄绿圆点、等宽字体命令行、闪烁光标、命令历史上下键、至少支持 help/ls/date/echo/clear/whoami、输出逐字打字机效果、暗色毛玻璃背景。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"keydown|keypress", r"blink|cursor|光标", r"command|命令|history", r"monospace|Menlo|Consolas"]},
    {"id": "parallax", "name": "3D 悬停视差卡", "tags": ["实战", "动效"],
     "prompt": "用单个 HTML 文件实现 3D 悬停卡片组：鼠标移动卡片 3D 倾斜(perspective+rotateXY)、表面 glare 高光随角度流动、悬停上浮投影加深、三张卡不同主题色、内容排版精致。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"perspective|rotateX|rotateY", r"mousemove", r"glare|高光|radial-gradient", r"box-shadow"]},
    {"id": "glasslogin", "name": "玻璃拟态登录页", "tags": ["实战", "美观"],
     "prompt": "用单个 HTML 文件实现登录页：流动渐变背景、玻璃拟态登录卡(blur+透明度+细边框)、输入框聚焦浮动标签、错误抖动提示、密码可见切换、登录按钮加载态、成功勾动效。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"backdrop-filter|blur", r"label|浮动|focus", r"shake|抖动|error", r"loading|加载|spinner"]},
    {"id": "feed", "name": "社区信息流页", "tags": ["实战", "细节"],
     "prompt": "用单个 HTML 文件实现社区信息流(知乎/微博风)：顶栏、卡片流(头像/昵称/时间/正文/图)、点赞转发动效、无限滚动加载、骨架屏占位、图片九宫格、返回顶部按钮。只输出完整的 HTML 文件内容，不要解释。",
     "features": [r"skeleton|骨架|loading", r"scroll", r"like|点赞|heart", r"grid|九宫格"]},
]


_BASE_FEATURES = [r"<!doctype html|<html", r"<script|<style"]
def chat(url, payload, headers, timeout=600):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    ch = d["choices"][0]
    return (ch["message"].get("content") or "").strip(), d.get("usage") or {}, ch.get("finish_reason") or ""


def _tail_overlap_dedup(prev, nxt, limit=240):
    """续写内容与已有尾部重叠时去重。"""
    for k in range(min(limit, len(prev)), 40, -1):
        if nxt.startswith(prev[-k:]):
            return nxt[k:]
    return nxt


def gen_complete(url, model, prompt, tier_max, headers, thinking=False):
    """生成并自动续写直到闭合 </html> 或达到轮次上限。thinking=True 开启推理模式。"""
    msgs = [{"role": "user", "content": prompt}]
    total_in = total_out = 0
    parts, cont = [], 0
    while True:
        resp, usage, finish = chat(url, {"model": model, "messages": msgs,
                                         "max_tokens": tier_max, "temperature": 0.3,
                                         "chat_template_kwargs": {"enable_thinking": bool(thinking)}}, headers)
        total_in += usage.get("prompt_tokens", 0)
        total_out += usage.get("completion_tokens", 0)
        parts.append(resp)
        if finish != "length":
            break
        cont += 1
        if cont >= 3:
            plog("    ⚠ 续写 %d 轮仍未闭合" % cont)
            break
        plog("    ↻ 截断, 自动续写第 %d 轮" % cont)
        msgs = [{"role": "user", "content": prompt},
                {"role": "assistant", "content": parts[-1][-3000:]},
                {"role": "user", "content": "继续输出剩余的 HTML 直到 </html> 结束。从上次中断处直接继续，不要重复已输出的内容，不要解释。"}]
        # 预拼接给下轮去重
        parts.append(None)
        parts = [p for p in parts if p is not None]
    # 拼接(带重叠去重)
    full = parts[0]
    for p in parts[1:]:
        full += _tail_overlap_dedup(full, p)
    return full, total_in, total_out, cont


def extract_html(resp):
    m = re.search(r"```(?:html|HTML)?\s*\n(.*?)```", resp, re.S)
    if m:
        return m.group(1).strip()
    low = resp.lower()
    i = low.find("<!doctype")
    if i < 0:
        i = low.find("<html")
    if i >= 0:
        j = low.rfind("</html>")
        return resp[i:j + 7].strip() if j > i else resp[i:].strip()
    return resp.strip()

def check_features(html, features):
    return [bool(re.search(f, html, re.I)) for f in features]


_GEN_PROGRESS = None


def plog(msg):
    print(msg, flush=True)
    if _GEN_PROGRESS:
        try:
            _GEN_PROGRESS(str(msg))
        except Exception:
            pass


def run_gen(url, model, api_key="", task_ids=None, conc=4, outdir=None, tag="",
            framework=None, fw_version=None, thinking=False):
    outdir = outdir or os.path.join(ROOT, "results")
    os.makedirs(outdir, exist_ok=True)
    headers = {"Authorization": "Bearer " + api_key} if api_key else {}
    tasks = [t for t in GEN_TASKS if not task_ids or t["id"] in task_ids]

    run_id = "gen_%s_%s" % (datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
                            re.sub(r"[^A-Za-z0-9.-]", "_", model))
    work_dir = os.path.join(WORKS, run_id)
    os.makedirs(work_dir, exist_ok=True)

    result = {"kind": "gen", "gen_version": GEN_VERSION, "run_id": run_id, "tag": tag,
              "url": url, "model": model, "conc": conc,
              "framework": {"name": framework or "", "version": fw_version or ""},
              "thinking": bool(thinking),
              "started_utc": datetime.now(timezone.utc).isoformat(),
              "works_dir": "works/" + run_id, "items": []}
    path = os.path.join(outdir, run_id + ".json")
    lock_free = True

    def save():
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)

    plog("== gen v%s | %s | %d 题 | conc=%d ==" % (GEN_VERSION, model, len(tasks), conc))

    done_ct = [0]

    def worker(task):
        plog("▶ 开始: %s (%s)" % (task["name"], "/".join(task["tags"])))
        try:
            tier_max = 16000 if "地狱" in task["tags"] else (12000 if "困难" in task["tags"] else 8000)
            resp, in_tok, out_tok, cont_n = gen_complete(url, model, task["prompt"], tier_max, headers, thinking)
        except Exception as e:
            done_ct[0] += 1
            plog("  ✗ [%s] 失败: %s · 进度 %d/%d" % (task["name"], str(e)[:60], done_ct[0], len(tasks)))
            return {"id": task["id"], "name": task["name"], "error": str(e)[:120],
                    "pass": 0, "features": [], "stars": None}
        html = extract_html(resp)
        complete = "</html>" in html.lower() and html.lower().count("<script") <= html.lower().count("</script>")
        feats = _BASE_FEATURES + [r"</html>|完整闭合"] + task["features"]
        checks = check_features(html, feats)
        checks.insert(2, complete)
        fname = task["id"] + ".html"
        with open(os.path.join(work_dir, fname), "w", encoding="utf-8") as f:
            f.write(html)
        item = {"id": task["id"], "name": task["name"], "tags": task["tags"],
                "file": "works/%s/%s" % (run_id, fname), "chars": len(html),
                "lines": html.count("\n") + 1,
                "features": ["<!doctype/<html", "<script/<style", "完整闭合</html>"] + task["tags"],
                "continuations": cont_n,
                "checks": checks, "pass": sum(checks), "total": len(checks),
                "stars": None, "in_tokens": in_tok, "out_tokens": out_tok}
        done_ct[0] += 1
        plog("  ✓ [%s] 特征 %d/%d · %d 行 · 进度 %d/%d" % (task["name"], item["pass"], item["total"], item["lines"], done_ct[0], len(tasks)))
        return item

    with ThreadPoolExecutor(max_workers=conc) as ex:
        for item in ex.map(worker, tasks):
            result["items"].append(item)
            save()
    result["finished_utc"] = datetime.now(timezone.utc).isoformat()
    save()
    plog("完成 => %s" % path)
    return path
