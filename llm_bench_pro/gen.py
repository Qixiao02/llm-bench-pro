#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen.py — 真实生成效果测试引擎
四档题库(普通/困难/地狱/实战 33 题) -> 模型生成完整 HTML -> 运行检测 + 视觉评审(geneval) + 人工星级。
作品与截图落盘 works/<run_id>/, 元数据经 sink 写库或 JSON。
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone
from concurrent.futures import FIRST_COMPLETED, wait

try:
    from . import geneval, i18n, iq, sinks, store  # 包内导入: python -m llm_bench_pro.gen
except ImportError:
    import geneval  # server.py 以包目录为 sys.path 顶层导入
    import i18n
    import iq
    import sinks
    import store

# 2.0: 源码正则特征 -> 无头浏览器运行检测(逐题交互脚本/功能断言) + 可选视觉模型清单评审, 与 1.x 结果不可直接比较
# 2.1: 流式生成(思考模式不再整体超时)、续写携带完整已生成内容并按行去重、HTML 提取修正、取消即停
# 2.2: 续写保留换行且不在单词中间去重; 已落盘的作品取消后仍入库; 题目 id 精确匹配
# 2.3: 采样改为官方推荐(旧版 T0.3 易陷入重复)、流式检测逐字重复并立即停止、逐轮保存模型原始输出(works/<run>/<题>.gen.json)
GEN_VERSION = "2.3.0"
STREAM_IDLE_TIMEOUT = 300  # 流式响应两次数据之间的最长等待(秒)
_STREAM_OPTIONAL = ("stream_options", "continue_final_message", "add_generation_prompt")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根(包上一级)
WORKS = os.path.join(ROOT, "data", "works")  # 作品落盘目录; 条目里记逻辑路径 works/<run>/<文件>(即页面地址 /works/…)


def work_path(rel):
    """作品条目里的逻辑路径 works/<run>/<文件> → 磁盘路径。"""
    parts = (rel or "").replace("\\", "/").split("/")
    return os.path.join(WORKS, *parts[1:]) if parts[0] == "works" else os.path.join(ROOT, *parts)

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


class Cancelled(Exception):
    """用户取消。"""


# ---------------------------------------------------------------- 采样参数

# 默认按 Qwen 系列官方推荐: 思考 T0.6/top_p0.95/top_k20, 非思考 T0.7/top_p0.8/top_k20; 固定 seed 便于复现。
# 2.2 及之前统一用 T0.3: 接近贪心解码, 小模型写长文件时容易陷入逐字重复(同一段内容无限循环到输出上限)。
GEN_SAMPLING = {
    "think": {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "seed": 42},
    "plain": {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "seed": 42},
}
_SAMPLING_KEYS = (("temperature", float, 0.0, 2.0), ("top_p", float, 0.01, 1.0), ("top_k", int, -1, 1000),
                  ("presence_penalty", float, -2.0, 2.0), ("seed", int, 0, 2 ** 31 - 1))


def resolve_sampling(thinking, sampling=None):
    """返回本轮请求的采样参数。sampling: None/"official"(官方推荐, 按是否思考区分) | "legacy"(旧版 T0.3) | dict(自定义)。"""
    base = GEN_SAMPLING["think" if thinking else "plain"]
    if sampling in (None, "", "official"):
        return dict(base)
    if sampling == "legacy":
        return {"temperature": 0.3}
    if isinstance(sampling, dict):
        out = {}
        for key, cast, lo, hi in _SAMPLING_KEYS:
            v = sampling.get(key)
            if v is None or (isinstance(v, str) and not v.strip()):
                continue
            try:
                v = cast(v)
            except (TypeError, ValueError):
                raise ValueError("采样参数 %s 无效: %r" % (key, sampling.get(key)))
            if not lo <= v <= hi:
                raise ValueError("采样参数 %s 应在 %s 到 %s 之间: %s" % (key, lo, hi, v))
            out[key] = v
        out.setdefault("temperature", base["temperature"])
        out.setdefault("seed", 42)
        return out
    raise ValueError("未知的采样方式: %r" % (sampling,))


def sampling_record(sampling):
    """写进运行记录的采样口径: 首轮(可能思考) / 续写轮(不思考) 各自的参数。"""
    mode = "official" if sampling in (None, "", "official") else ("legacy" if sampling == "legacy" else "custom")
    return {"mode": mode, "think": resolve_sampling(True, sampling), "plain": resolve_sampling(False, sampling)}


# ---------------------------------------------------------------- 重复输出检测

REPEAT_SPAN = 6000          # 严格循环: 末尾至少这么多字符按同一周期逐字重复
REPEAT_SPAN_TINY = 8000     # 周期 ≤4 个字符(一长串 0 / 点号)时要求更长, 避免误伤正常的数组字面量
REPEAT_MAX_PERIOD = 2000
REPEAT_WINDOW = 8000        # 高度雷同: 最近 8000 字符的压缩率
REPEAT_RATIO = 0.13         # 实测正常作品任意 8000 字符窗口压缩率 ≥ 0.19; 循环/机械计数输出持续低于 0.12
REPEAT_LOW_CHECKS = 3       # 连续 3 次检查都低于阈值才判定(输出又增长了约 4000 字符, 排除偶发的整齐数据块)
REPEAT_CHECK_EVERY = 2000   # 流式输出每增长这么多字符检查一次


def _min_period(unit):
    """字符串的最小周期(unit 由某个更短片段整数次重复而成时返回该片段长度)。"""
    n = len(unit)
    for d in range(1, n):
        if n % d == 0 and unit[:d] * (n // d) == unit:
            return d
    return n


def detect_repetition(text):
    """严格循环: 输出末尾 L 个字符与其前移 p 个字符完全相同(L ≥ max(6000, 4p); 周期 ≤4 时整段循环 ≥ 8000)。
    正常代码不会出现这么长的逐字循环。返回 {"kind": "loop", "period", "repeats", "start", "sample"} 或 None。"""
    n = len(text)
    if n <= REPEAT_SPAN:
        return None
    probe = 48
    for p in range(1, min(REPEAT_MAX_PERIOD, n // 4) + 1):
        need = max(REPEAT_SPAN, 4 * p)
        if need + p > n:
            break
        if text[n - probe:] != text[n - probe - p:n - p]:  # 先比最后几十个字符, 快速排除
            continue
        if text[n - need:] != text[n - need - p:n - p]:
            continue
        start = n - need - p
        lo = max(0, start - 500000)
        while start > lo and text[start - 1] == text[start - 1 + p]:
            start -= 1
        period = _min_period(text[n - p:])
        if period <= 4 and n - start < REPEAT_SPAN_TINY:
            return None
        return {"kind": "loop", "period": period, "repeats": (n - start) // period, "start": start,
                "sample": text[n - max(period, 40):][:160]}
    return None


class RepetitionWatch:
    """流式输出的重复检测: 逐字循环立即判定; 内容高度雷同(机械计数、同一句式反复)连续多次低于压缩率阈值时判定。"""

    def __init__(self):
        self.low = 0

    def check(self, text):
        hit = detect_repetition(text)
        if hit:
            return hit
        if len(text) < REPEAT_WINDOW:
            return None
        w = text[-REPEAT_WINDOW:].encode("utf-8")
        ratio = len(zlib.compress(w, 6)) / len(w)
        self.low = self.low + 1 if ratio < REPEAT_RATIO else 0
        if self.low >= REPEAT_LOW_CHECKS:
            return {"kind": "similar", "ratio": round(ratio, 3), "period": None, "repeats": None,
                    "sample": text[-160:]}
        return None


def repetition_text(rep):
    """重复输出的大白话描述。"""
    if rep.get("kind") == "loop":
        return "每 %d 个字符循环一次，已重复 %d 次" % (rep["period"], rep["repeats"])
    return "最近几千字内容高度雷同（压缩率 %.2f，正常代码约 0.2 以上）" % (rep.get("ratio") or 0)


def scan_repetition(text):
    """按流式检查的节奏扫描一段完整输出(非流式响应或事后核查用), 返回首次命中或 None。"""
    watch = RepetitionWatch()
    for end in range(REPEAT_CHECK_EVERY, len(text) + REPEAT_CHECK_EVERY, REPEAT_CHECK_EVERY):
        hit = watch.check(text[:min(end, len(text))])
        if hit:
            return hit
    return None


# ---------------------------------------------------------------- 流式请求

def chat(url, payload, headers, cancel=None, idle_timeout=STREAM_IDLE_TIMEOUT, info=None):
    """流式请求 chat/completions, 返回 (content, usage, finish_reason, reasoning)。
    按数据间隔而非总时长计超时, 长思考不会整体超时; cancel 置位时中断连接并抛出 Cancelled。
    正文或思考陷入逐字重复时立即断开(finish_reason="repetition", 详情写入 info["repetition"]),
    不再等模型把输出上限耗完。端点不支持流式而直接返回 JSON 时照常解析;
    明确拒绝的可选字段剔除后重试(按端点记住)。"""
    drop = iq._DROPPED.get(url, set())
    body = dict(payload, stream=True, stream_options={"include_usage": True})
    body = {k: v for k, v in body.items() if k not in drop}
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Accept": "text/event-stream", **headers})
    try:
        r = urllib.request.urlopen(req, timeout=idle_timeout)
    except urllib.error.HTTPError as e:
        try:
            e.detail = e.read().decode("utf-8", "replace")[:2000]
        except Exception:
            e.detail = ""
        if e.code in (400, 422):
            present = [k for k in iq._OPTIONAL_KEYS + _STREAM_OPTIONAL if k in body]
            named = iq._rejected_keys(e.detail, present)
            if named:
                iq._DROPPED.setdefault(url, set()).update(named)
                return chat(url, payload, headers, cancel, idle_timeout, info)
        raise

    watches = {"content": RepetitionWatch(), "reasoning": RepetitionWatch()}

    def repetition(parts, where, full_scan=False):
        text = "".join(parts)
        hit = (scan_repetition(text) if full_scan else watches[where].check(text)) if text else None
        if hit:
            hit["where"] = where
            if info is not None:
                info["repetition"] = hit
        return hit

    content, reasoning, finish, usage = [], [], "", {}
    size, next_check = 0, REPEAT_CHECK_EVERY
    with r:
        if "text/event-stream" not in (r.headers.get("Content-Type") or ""):
            d = json.loads(r.read())
            ch = d["choices"][0]
            msg = ch.get("message") or {}
            text = msg.get("content") or ""
            reason = (msg.get("reasoning_content") or msg.get("reasoning") or "").strip()
            finish = ch.get("finish_reason") or ""
            if finish == "length" and (repetition([text], "content", True) or repetition([reason], "reasoning", True)):
                finish = "repetition"
            return text, d.get("usage") or {}, finish, reason
        stopped = False
        for raw in r:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                d = json.loads(data)
            except ValueError:
                continue
            if d.get("usage"):
                usage = d["usage"]
            for ch in d.get("choices") or []:
                delta = ch.get("delta") or {}
                if delta.get("content"):
                    content.append(delta["content"])
                    size += len(delta["content"])
                r_part = delta.get("reasoning_content") or delta.get("reasoning")
                if r_part:
                    reasoning.append(r_part)
                    size += len(r_part)
                if ch.get("finish_reason"):
                    finish = ch["finish_reason"]
            if size >= next_check:
                next_check = size + REPEAT_CHECK_EVERY
                if repetition(content, "content") or repetition(reasoning, "reasoning"):
                    stopped = True
                    break  # 断开连接, 服务端随之中止生成
        text, reason = "".join(content), "".join(reasoning).strip()
        if stopped:
            finish = "repetition"
            if not usage:  # 提前断开拿不到服务端统计, 按字符数估算(约 3 字符 / token)
                usage = {"completion_tokens": (len(text) + len(reason)) // 3, "estimated": True}
        elif finish == "length" and not (info or {}).get("repetition") and (
                repetition([text], "content", True) or repetition([reason], "reasoning", True)):
            finish = "repetition"
    return text, usage, finish, reason


# ---------------------------------------------------------------- 续写拼接

_CONTINUE_HINT = "输出在上面中断了。请从中断处继续输出剩余代码直到 </html>，不要重复已输出的内容，不要解释。"
_FENCE_LINE = re.compile(r"^\s*```[\w-]*\s*$")


def _word_char(ch):
    return bool(ch) and (ch.isalnum() or ch == "_")


# 续写从这些词开头, 且上文没有换行时, 补上被截断吃掉的换行。不用于标识符中间(simYe+ars)。
_STMT_START = re.compile(
    r"^(?:let|const|var|function|class|import|export|return|if|else|for|while|do|switch|"
    r"case|break|continue|try|catch|finally|throw|async|await|yield|debugger)\b"
)


def _join_parts(prev, nxt):
    """最后一步拼接。两边都没带换行、续写却是新语句时补一个换行, 避免 let x = 1let y = 2。"""
    if not prev or not nxt or prev.endswith("\n") or nxt[0] in "\n \t":
        return prev + nxt
    if _STMT_START.match(nxt):
        return prev + "\n" + nxt
    return prev + nxt


def _stitch_info(prev, nxt):
    """把续写内容接到已有内容后, 返回 (拼接结果, 处理说明)。
    处理说明 {fence: 去掉了续写开头的代码块标记, overlap: 去掉的与上文重复的字符数,
             line_restart: 模型从被截断那一行的行首重新输出, newline: 补了一个换行}。

    续写以换行开头时保留该换行(截断点常在行尾)。重叠不能从单词中间切开,
    例如已有内容以 myfunction 结尾、续写以 function 开头时不能删掉 function。
    """
    info = {"fence": False, "overlap": 0, "line_restart": False, "newline": False}
    lines = nxt.split("\n")
    while lines and _FENCE_LINE.match(lines[0]):
        lines.pop(0)
        info["fence"] = True
    if info["fence"] and lines and lines[0] == "":
        lines.pop(0)  # 围栏后习惯性空行, 不是截断点的换行
    nxt = "\n".join(lines)
    if not nxt:
        return prev, info
    limit = min(2000, len(prev), len(nxt))
    for k in range(limit, 7, -1):
        if not prev.endswith(nxt[:k]):
            continue
        before = prev[-k - 1] if len(prev) > k else ""
        if _word_char(before) and _word_char(nxt[0]):
            continue
        info["overlap"] = k
        return prev + nxt[k:], info
    last_nl = prev.rfind("\n")
    partial = prev[last_nl + 1:]
    first = nxt.split("\n", 1)[0]
    ps, fs = partial.strip(), first.strip()
    if ps and fs.startswith(ps):
        rest = fs[len(ps):]
        mid_token = bool(rest) and _word_char(ps[-1]) and _word_char(rest[0])
        if not (mid_token and len(ps) < 4):
            info["line_restart"], info["overlap"] = True, len(partial)
            return prev[:last_nl + 1] + nxt, info
    joined = _join_parts(prev, nxt)
    info["newline"] = len(joined) == len(prev) + len(nxt) + 1
    return joined, info


def _stitch(prev, nxt):
    return _stitch_info(prev, nxt)[0]


def gen_complete(url, model, prompt, tier_max, headers, thinking=False, cancel=None, sampling=None, trace=None):
    """生成并自动续写直到正常结束或达到轮次上限。thinking=True 开启推理模式(仅首轮)。
    续写时把完整已生成内容作为 assistant 前缀, 支持 continue_final_message 的端点(vLLM/SGLang)直接接着写;
    不支持时退回"继续输出"指令, 同样携带完整内容, 模型能看到前文声明的变量。
    模型陷入逐字重复时立即停止且不再续写(继续只会放大重复)。
    trace(dict): 逐轮记录原始输出、结束原因、token 与拼接方式, 用于核对框架是否改动了模型输出。"""
    trace = trace if trace is not None else {}
    rounds = trace.setdefault("rounds", [])
    total_in = total_out = 0
    full, cont, total_reason = "", 0, 0
    msgs = [{"role": "user", "content": prompt}]
    extra, mt, mode = {}, tier_max, "first"
    while True:
        think_now = bool(thinking and cont == 0)
        payload = {"model": model, "messages": msgs, "max_tokens": mt,
                   "chat_template_kwargs": {"enable_thinking": think_now}}
        payload.update(resolve_sampling(think_now, sampling))
        payload.update(extra)
        info, t0 = {}, time.time()
        try:
            resp, usage, finish, reasoning = chat(url, payload, headers, cancel, info=info)
        except Cancelled:
            raise
        except Exception as e:
            if cont == 0:
                raise
            # 续写携带完整前文可能超出上下文: 按报错收缩输出上限重试一次, 仍失败则保留已生成部分
            _, fit = iq._context_fit(getattr(e, "detail", ""), len(json.dumps(msgs)) // 3)
            if fit and 512 <= fit < mt:
                mt = fit
                continue
            plog("    ⚠ 续写失败, 保留已生成部分: %s" % str(e)[:80])
            rounds.append({"n": len(rounds) + 1, "mode": mode, "error": str(e)[:240]})
            break
        if extra and "continue_final_message" in iq._DROPPED.get(url, ()):
            # 端点不支持前缀续写(本轮已按普通对话生成, 结果不可用): 改为指令式续写重做本轮
            msgs = msgs + [{"role": "user", "content": _CONTINUE_HINT}]
            extra, mode = {}, "instruct"
            continue
        total_in += usage.get("prompt_tokens", 0)
        total_out += usage.get("completion_tokens", 0)
        total_reason += len(reasoning)
        rec = {"n": len(rounds) + 1, "mode": mode, "thinking": think_now, "max_tokens": mt, "finish": finish,
               "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
               "tokens_estimated": bool(usage.get("estimated")), "seconds": round(time.time() - t0, 1),
               "content_chars": len(resp), "reasoning_chars": len(reasoning),
               "reasoning_head": reasoning[:1500], "reasoning_tail": reasoning[-1500:] if len(reasoning) > 3000 else "",
               "content": resp}
        rep = info.get("repetition")
        if rep:
            rec["repetition"] = rep
        if cont == 0 or mode == "restart":
            full = resp
        elif re.match(r"\s*(```[\w-]*\s*)?<!doctype|\s*(```[\w-]*\s*)?<html", resp, re.I) and "<html" in full.lower():
            plog("    ↻ 续写从头重新输出了整个文件, 改用新内容")
            full = resp
            rec["join"] = {"replaced": True}
        else:
            full, rec["join"] = _stitch_info(full, resp)
        rounds.append(rec)
        if rep and rep["where"] == "content":
            trace["degenerate"] = {k: rep.get(k) for k in ("kind", "period", "repeats", "ratio", "sample")}
            trace["degenerate"]["round"] = rec["n"]
            plog("    ⚠ 模型陷入重复输出(%s), 停止生成、不再续写" % repetition_text(rep))
            break
        if rep:  # 思考过程陷入重复: 与思考用完输出长度同样处理(正文为空时改为不思考重新生成)
            trace["degenerate_reasoning"] = {k: rep.get(k) for k in ("kind", "period", "repeats", "ratio", "sample")}
            trace["degenerate_reasoning"]["round"] = rec["n"]
            plog("    ⚠ 思考过程陷入重复输出, 停止思考")
            finish = "length"
        if finish != "length":
            break
        cont += 1
        if cont >= 4:
            plog("    ⚠ 续写 %d 轮仍未闭合" % cont)
            trace["unfinished"] = True
            break
        plog("    ↻ 截断, 续写第 %d 轮(关闭思考直出代码)" % cont)
        visible = iq.strip_think(full) if "<think>" in full or "</think>" in full else full
        if not visible.strip():
            msgs = [{"role": "user", "content": prompt + "\n\n（直接输出完整 HTML 代码，不要思考过程。）"}]
            full, extra, mode = "", {}, "restart"
            trace["rescued"] = "思考过程%s，没写出代码；改为不思考、直接重新生成" % ("陷入重复" if rep else "用完了输出长度")
        elif url not in iq._DROPPED or "continue_final_message" not in iq._DROPPED[url]:
            msgs = [{"role": "user", "content": prompt}, {"role": "assistant", "content": visible}]
            extra, full, mode = {"continue_final_message": True, "add_generation_prompt": False}, visible, "prefix"
        else:
            msgs = [{"role": "user", "content": prompt}, {"role": "assistant", "content": visible},
                    {"role": "user", "content": _CONTINUE_HINT}]
            extra, full, mode = {}, visible, "instruct"
    return full, total_in, total_out, cont, total_reason


def describe_changes(raw, html, trace=None):
    """用大白话列出框架对模型原始输出做过的全部处理。除列出的处理外, 保存的作品与模型输出逐字一致,
    用于回答"作品是不是被框架弄坏了"。没有任何处理时返回 ["原样保存…"]。"""
    trace = trace or {}
    out = []
    if trace.get("rescued"):
        out.append(trace["rescued"])
    for r in (trace.get("rounds") or [])[1:]:
        if r.get("mode") == "restart" or r.get("error"):
            continue
        j = r.get("join") or {}
        if j.get("replaced"):
            out.append("第 %d 轮续写时模型从头重写了整个文件，采用了重写后的版本" % r["n"])
            continue
        bits = []
        if j.get("line_restart"):
            bits.append("模型从被截断的那一行重新写，去掉了重复的半行（%d 个字符）" % j.get("overlap", 0))
        elif j.get("overlap"):
            bits.append("去掉了与上文重复的 %d 个字符" % j["overlap"])
        if j.get("fence"):
            bits.append("去掉了开头的代码块标记")
        if j.get("newline"):
            bits.append("补了 1 个换行")
        out.append("接上第 %d 轮续写（%s）" % (r["n"], "，".join(bits) if bits else "直接拼接"))
    no_think = iq.strip_think(raw)
    cut = len(raw.strip()) - len(no_think)
    if cut > 0:
        out.append("去掉了混在正文里的思考过程（%d 个字符）" % cut)
    pos = no_think.find(html) if html else -1
    if pos >= 0:
        for where, text in (("前面", no_think[:pos]), ("后面", no_think[pos + len(html):])):
            prose = re.sub(r"```[\w-]*", "", text).strip()
            if prose:
                out.append("去掉了代码%s的说明文字（%d 个字符）%s：「%s」" % (
                    where, len(prose), "和代码块标记" if "```" in text else "",
                    prose[:40].replace("\n", " ") + ("…" if len(prose) > 40 else "")))
            elif "```" in text:
                out.append("去掉了代码%s的 Markdown 代码块标记" % where)
    elif html:
        out.append("删除了续写接缝处多余的代码块标记")
    return out or ["原样保存了模型输出，没有做任何修改"]


def _drop_seam_fences(text):
    """代码块内部再次出现带语言标记的开围栏(续写时模型重新输出 ```html)是接缝, 删除该行。"""
    out, open_ = [], False
    for line in text.split("\n"):
        m = re.match(r"^[ \t]*```([\w-]*)[ \t]*$", line)
        if m:
            if m.group(1) and open_:
                continue
            open_ = bool(m.group(1)) or not open_
        out.append(line)
    return "\n".join(out)


def extract_html(resp):
    """从模型输出中取出 HTML: 删除续写接缝处的代码围栏行后, 优先取包含 <html/<!doctype 的最长代码块, 否则按文档标记截取。"""
    resp = _drop_seam_fences(iq.strip_think(resp))
    blocks = [m.group(1) for m in re.finditer(r"(?m)^[ \t]*```[\w-]*[ \t]*\n(.*?)(?:^[ \t]*```[ \t]*$|\Z)", resp, re.S)]
    docs = [b for b in blocks if re.search(r"<!doctype|<html", b, re.I)]
    if docs:
        return max(docs, key=len).strip()
    low = resp.lower()
    i = low.find("<!doctype")
    if i < 0:
        i = low.find("<html")
    if i >= 0:
        j = low.rfind("</html>")
        out = resp[i:j + 7] if j > i else resp[i:]
        return re.sub(r"(?m)^[ \t]*```[\w-]*[ \t]*\n?", "", out).strip()
    if blocks:
        return max(blocks, key=len).strip()
    return resp.strip()


def normalize_task_ids(raw):
    """None 表示全部题目。字符串按逗号拆开。空列表和未知 id 报错。返回 id 列表。"""
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = [x.strip() for x in raw.split(",") if x.strip()]
    if not isinstance(raw, (list, tuple)):
        raise ValueError("tasks 应为题目 id 数组")
    ids = []
    for x in raw:
        if not isinstance(x, str) or not x.strip():
            raise ValueError("tasks 应为题目 id 数组")
        ids.append(x.strip())
    if not ids:
        raise ValueError("请至少选择 1 道题目")
    known = {t["id"] for t in GEN_TASKS}
    bad = [x for x in ids if x not in known]
    if bad:
        raise ValueError("未知题目：" + "、".join(bad[:8]))
    return ids


_GEN_PROGRESS = None


def plog(msg):
    print(msg, flush=True)
    if _GEN_PROGRESS:
        try:
            _GEN_PROGRESS(str(msg))
        except Exception:
            pass


def run_gen(url, model, api_key="", task_ids=None, conc=4, outdir=None, tag="",
            framework=None, fw_version=None, thinking=False, sink=None, judge=None, browsers=2, cancel=None,
            sampling=None):
    """跑生成测试。作品落 data/works/<run_id>/; 每件作品生成后即做运行检测(+可选视觉评审);
    元数据经 sink (默认 outdir/<run_id>.json); 返回落地位置。judge: {base, model, api_key}
    cancel: threading.Event, 置位后不再开始新题, 已完成作品保留, 状态记为 cancelled。
    sampling: None/"official" | "legacy" | dict, 见 resolve_sampling。每题的原始输出逐轮保存在 data/works/<run_id>/<题>.gen.json。"""
    sampling_record(sampling)  # 参数有误时在开始前报错
    outdir = outdir or os.path.join(ROOT, "data", "results")
    headers = {"Authorization": "Bearer " + api_key} if api_key else {}
    if task_ids is not None:
        task_ids = set(normalize_task_ids(task_ids))
    tasks = [t for t in GEN_TASKS if task_ids is None or t["id"] in task_ids]

    run_id = "gen_%s_%s" % (datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
                            re.sub(r"[^A-Za-z0-9.-]", "_", model))
    work_dir = os.path.join(WORKS, run_id)
    os.makedirs(work_dir, exist_ok=True)

    result = {"kind": "gen", "gen_version": GEN_VERSION, "run_id": run_id, "tag": tag,
              "url": url, "model": model, "conc": conc,
              "framework": {"name": framework or "", "version": fw_version or ""},
              "thinking": bool(thinking), "planned": len(tasks), "sampling": sampling_record(sampling),
              "started_utc": datetime.now(timezone.utc).isoformat(),
              "works_dir": "works/" + run_id, "items": []}
    sink = sink or sinks.JsonFileSink(outdir)
    evaluator = geneval.Evaluator(judge, browsers=browsers, log=plog)
    evaluator.reap()
    result["eval"] = evaluator.meta()

    def save():
        sink.save(result)

    first = resolve_sampling(thinking, sampling)
    plog("== gen v%s | %s | %d 题 | conc=%d | 采样 %s | 评测: %s%s ==" % (
        GEN_VERSION, model, len(tasks), conc, json.dumps(first, ensure_ascii=False),
        "无头浏览器运行检测" if evaluator.method == "browser" else "源码检查(未找到浏览器)",
        " + 视觉评审 " + judge["model"] if evaluator.judge_cfg else ""))

    def keep_trace(task, trace, raw, html):
        """逐题留档: 模型每一轮的原始输出 + 框架做过的处理; 返回写进作品条目的摘要字段。"""
        if not trace.get("rounds"):
            return {}
        changes = describe_changes(raw, html, trace) if raw is not None else []
        doc = {"gen_version": GEN_VERSION, "task": task["id"], "prompt": task["prompt"], "thinking": bool(thinking),
               "sampling": result["sampling"], "raw_chars": len(raw or ""), "html_chars": len(html or ""),
               "changes": changes}
        doc.update(trace)
        rel = "works/%s/%s.gen.json" % (run_id, task["id"])
        path = work_path(rel)
        try:
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False)
            os.replace(path + ".tmp", path)
        except OSError as e:
            plog("  ⚠ [%s] 原始输出留档失败: %s" % (task["name"], e))
            rel = None
        brief = {"rounds": [{k: r.get(k) for k in ("n", "mode", "thinking", "finish", "completion_tokens", "tokens_estimated",
                                                   "content_chars", "reasoning_chars", "seconds", "error")}
                            for r in trace["rounds"]],
                 "changes": changes}
        if rel:
            brief["trace"] = rel
        for k in ("degenerate", "degenerate_reasoning", "rescued", "unfinished"):
            if trace.get(k):
                brief[k] = trace[k]
        return brief

    done_ct = [0]

    def failed(task, err):
        return {"id": task["id"], "name": task["name"], "tags": task["tags"], "error": err,
                "checks": [], "pass": 0, "total": 0, "features": [], "stars": None, "lines": 0, "chars": 0}

    def worker(task):
        if cancel is not None and cancel.is_set():
            return None
        plog("▶ 开始: %s (%s)" % (task["name"], "/".join(task["tags"])))
        trace = {}
        try:
            base_max = 16000 if "地狱" in task["tags"] else (12000 if "困难" in task["tags"] else 8000)
            tier_max = int(base_max * 2.5) if thinking else base_max  # 思考 token 与正文共享输出预算
            resp, in_tok, out_tok, cont_n, reason_len = gen_complete(url, model, task["prompt"], tier_max, headers,
                                                                     thinking, cancel, sampling, trace)
        except Cancelled:
            return None
        except Exception as e:
            done_ct[0] += 1
            detail = getattr(e, "detail", "")
            plog("  ✗ [%s] 失败: %s · 进度 %d/%d" % (task["name"], str(e)[:60], done_ct[0], len(tasks)))
            item = failed(task, (str(e) + ((" " + detail[:120]) if detail else ""))[:240])
            item.update(keep_trace(task, trace, None, None))
            return item
        html = extract_html(resp)
        if len(html) < 200 or "<" not in html:
            done_ct[0] += 1
            why = ("思考耗尽未产出正文(思考%d字)" % reason_len) if thinking and reason_len and not iq.strip_think(resp).strip() \
                else "输出中没有有效的 HTML(提取到 %d 字)" % len(html)
            if trace.get("degenerate"):
                why = "模型陷入重复输出，没有写出有效的 HTML"
            plog("  ✗ [%s] %s · 进度 %d/%d" % (task["name"], why, done_ct[0], len(tasks)))
            item = failed(task, why)
            item.update(keep_trace(task, trace, resp, html))
            return item
        fname = task["id"] + ".html"
        fpath = os.path.join(work_dir, fname)
        try:
            with open(fpath + ".tmp", "w", encoding="utf-8") as f:
                f.write(html)
            os.replace(fpath + ".tmp", fpath)
            item = {"id": task["id"], "name": task["name"], "tags": task["tags"],
                    "file": "works/%s/%s" % (run_id, fname), "chars": len(html),
                    "lines": html.count("\n") + 1,
                    "continuations": cont_n, "reason_chars": reason_len,
                    "stars": None, "in_tokens": in_tok, "out_tokens": out_tok}
            item.update(keep_trace(task, trace, resp, html))
            if cancel is None or not cancel.is_set():
                report = evaluator.evaluate(task, fpath, html, cancel)
                geneval.apply_eval(item, report)
            else:
                plog("  · [%s] 已生成，取消于评测前" % task["name"])
        except Cancelled:
            return None
        except Exception as e:
            done_ct[0] += 1
            plog("  ✗ [%s] 失败: %s · 进度 %d/%d" % (task["name"], str(e)[:60], done_ct[0], len(tasks)))
            return failed(task, str(e)[:240])
        done_ct[0] += 1
        plog("  ✓ [%s] %s · 进度 %d/%d" % (task["name"], _eval_brief(item) if item.get("eval") else "已生成、未评测", done_ct[0], len(tasks)))
        return item

    result["status"] = "running"
    save()
    futures, flushed = [], [0]

    def flush(final=False):
        """按题目顺序把已完成的作品追加并保存; final 时跳过被取消/未开始的题。"""
        changed = False
        while flushed[0] < len(futures):
            f = futures[flushed[0]]
            if not f.done():
                if not final:
                    break
            elif not f.cancelled() and f.exception() is None and f.result() is not None:
                result["items"].append(f.result())
                changed = True
            flushed[0] += 1
        if changed:
            save()

    try:
        ex = i18n.executor(max_workers=conc)
        futures.extend(ex.submit(worker, t) for t in tasks)
        try:
            pending = set(futures)
            while pending:
                finished, pending = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)
                flush()
                if cancel is not None and cancel.is_set():
                    for f in pending:
                        f.cancel()
                    evaluator.close()  # 结束进行中的浏览器检测; 生成中的请求在下一个数据块时中断
                    break
        finally:
            ex.shutdown(wait=True)  # 等进行中的题收尾, 避免返回后仍有线程写作品/启动浏览器
        flush(final=True)
        if cancel is not None and cancel.is_set():
            result["status"], result["error"] = "cancelled", "用户取消"
            plog("已取消: 保留已完成的 %d 件作品" % len(result["items"]))
        else:
            result["status"] = "done"
    except BaseException as e:
        try:
            flush(final=True)  # 中断时也把已经跑完的题按顺序入库
        except Exception:
            pass
        result["status"] = "interrupted" if isinstance(e, KeyboardInterrupt) else "failed"
        result["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
        raise
    finally:
        evaluator.close()
        result["eval"] = evaluator.meta()
        mode = geneval.eval_method(result["items"])
        if mode:
            result["eval"]["method"] = mode
        if thinking and "chat_template_kwargs" in iq._DROPPED.get(url, ()):
            result["thinking_dropped"] = True
        result["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save()
    plog("完成 => %s" % sink.location)
    return sink.location


def _eval_brief(item):
    ev = item.get("eval") or {}
    s = "运行检测 %d/%d" % (item["pass"], item["total"])
    fails = [c["label"] for c in ev.get("checks", []) if not c["pass"]]
    if fails:
        s += "（未通过：%s）" % "、".join(fails[:3])
    j = ev.get("judge") or {}
    if j.get("score") is not None:
        s += " · 评审 %.0f 分" % j["score"]
    elif j.get("error"):
        s += " · 评审失败"
    return s + " · %d 行" % item["lines"]


def reevaluate(run_id, judge=None, only=None, db_path=None, browsers=2, log=None, cancel=None):
    """对库中已有生成运行重新评测(运行检测 + 可选视觉评审), 就地更新作品条目, 保留人工星级。
    未配置评审模型时保留原有评审结果(标记为基于旧截图); cancel 置位后不再开始新作品。"""
    log = log or plog
    doc = store.get_run(run_id, db_path=db_path)
    if not doc or doc.get("kind") != "gen":
        raise KeyError("生成运行不存在: %s" % run_id)
    tasks = {t["id"]: t for t in GEN_TASKS}
    evaluator = geneval.Evaluator(judge, browsers=browsers, log=log)
    evaluator.reap()
    targets = [it for it in doc.get("items", []) if not it.get("error") and it.get("id") in tasks
               and (not only or it["id"] in only)]
    log("== 重新评测 %s | %d 件作品 | %s%s ==" % (run_id, len(targets), evaluator.method,
                                              " + 视觉评审 " + judge["model"] if evaluator.judge_cfg else ""))
    done = [0]

    def one(it):
        if cancel is not None and cancel.is_set():
            return
        path = work_path(it["file"])
        if not os.path.isfile(path):
            log("  ✗ [%s] 作品文件缺失: %s" % (it["name"], it["file"]))
            return
        with open(path, encoding="utf-8", errors="replace") as f:
            html = f.read()
        old_eval = it.get("eval") or {}
        old_judge = old_eval.get("judge") if isinstance(old_eval.get("judge"), dict) else None
        report = evaluator.evaluate(tasks[it["id"]], path, html, cancel)
        if report.get("method") != "browser" and old_eval.get("method") == "browser":
            log("  · [%s] 浏览器检测失败，保留上次的运行检测和评审" % it["name"])
            return
        j = report.get("judge") or {}
        if j.get("score") is None and old_judge and old_judge.get("score") is not None:
            kept = dict(old_judge, stale=True)
            if j.get("error"):
                kept["kept_because"] = str(j["error"])[:160]
            report["judge"] = kept
        elif not evaluator.judge_cfg and old_judge:
            report["judge"] = dict(old_judge, stale=True) if old_judge.get("score") is not None else old_judge
        geneval.apply_eval(it, report)
        store.update_gen_item(run_id, it, db_path=db_path)
        done[0] += 1
        log("  ✓ [%s] %s · 进度 %d/%d" % (it["name"], _eval_brief(it), done[0], len(targets)))

    try:
        with i18n.executor(max_workers=max(1, browsers)) as ex:
            pending = {ex.submit(one, it) for it in targets}
            while pending:
                finished, pending = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)
                for f in finished:
                    f.result()
                if cancel is not None and cancel.is_set():
                    for f in pending:
                        f.cancel()
                    evaluator.close()
    finally:
        evaluator.close()
        meta = evaluator.meta()
        if not evaluator.judge_cfg:  # 未配置评审时保留了原评审结果, 评审模型沿用原记录
            meta["judge_model"] = (doc.get("eval") or {}).get("judge_model")
        mode = geneval.eval_method(doc.get("items") or [])
        if mode:
            meta["method"] = mode  # 以作品上的实际检测方式为准, 不因本机有 Chrome 就写成浏览器
        if done[0]:
            store.update_run_meta(run_id, {"eval": meta}, db_path=db_path)  # 一件都没更新时不改运行口径
    log("重新评测已取消" if cancel is not None and cancel.is_set() else "重新评测完成")
