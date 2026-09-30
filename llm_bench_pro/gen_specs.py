#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_specs.py — 生成测试逐题评测规格 (与 gen.GEN_TASKS 的 id 一一对应)

每题:
  animated    首屏空闲期是否应持续有画面变化
  idle        空闲观察窗口秒数 (默认 1.0; 慢刷新题调大)
  responsive  是否检查 390px 移动视口无横向溢出
  setup       交互前的预热动作 (如点击开始), 不计分
  steps       交互步骤, 每步独立判定:
                assert  JS 表达式, 操作前不成立且操作后成立才通过(慢输出最多再等 3 秒)
                count   JS 数值表达式, 操作后比操作前至少增加 gain(默认 1)
                否则    画面/DOM 变化超出等长空闲基线, 且作品自身处理器响应了该输入;
                        native=True 的步骤(页面滚动、CSS 悬停样式、原生复选框等)不要求处理器响应
  checklist   视觉评审模型逐项打分清单 (0-10), 须能从截图+运行检测中核实

动作语法 (坐标为视口比例 0-1, 视口 1280x800):
  {"key": "ArrowLeft", "hold": 0.3, "repeat": 2}   按键 (hold 秒, repeat 次)
  {"type": "help\\n"}                                逐字键入, \\n 为回车
  {"click": [x, y]} / {"dblclick": [x, y]} / {"rclick": [x, y]}
  {"drag": [[x1, y1], [x2, y2]], "steps": 12}
  {"move": [[x, y], ...]}                           鼠标悬停轨迹
  {"wheel": 800, "at": [x, y]}
  {"find": "正则", "css": "选择器", "do": "click|dblclick|hover", "optional": true}
      按可见文本(正则, 不区分大小写)或 CSS 定位可见元素(可点击元素优先, 其次面积最小)并操作;
      找不到时: 有 "else": [动作...] 则改做这些动作, optional 则跳过, 否则该步失败
  {"wait": 0.5}
"""
import re

C = [0.5, 0.5]
# 页面文本中独立出现某个数的次数(排除 10:15 这类时间与更长数字的一部分)
_NUM_COUNT = r"(document.body.innerText.match(/(^|[^\d.:])%s(?![\d.:])/g) || []).length"

# 通用评审项 (追加在每题清单之后)
GENERIC_CHECKLIST = [
    {"id": "visual", "label": "视觉设计：配色、排版层级、留白与整体美观度"},
    {"id": "polish", "label": "完成度：动效流畅、细节打磨、无明显错位/穿模/闪烁等瑕疵"},
    {"id": "code", "label": "代码质量：结构清晰、逻辑正确、无明显错误或隐患"},
]


def step(label, actions, assert_js=None, settle=0.6, native=False, count=None, gain=1):
    s = {"label": label, "actions": actions, "settle": settle}
    if assert_js:
        s["assert"] = assert_js
    if count:
        s["count"], s["gain"] = count, gain
    if native:
        s["native"] = True
    return s


def ck(*labels):
    return [{"id": "t%d" % (i + 1), "label": t} for i, t in enumerate(labels)]


# 注意: JS 正则的 \b 对中文无效, 中文按钮文本不要用 \b
_START_RE = r"^\s*[▶►🎮]?\s*(开始游戏|开始挑战|开始冒险|点击开始|进入游戏|进入迷宫|开始|进入|新游戏|start|start game|play|new game)\s*[!！]?\s*$"


def start(*fallback):
    """点击开始按钮; 没有开始按钮时才执行 fallback 动作(如按空格开始), 避免开始后再按一次反而暂停。"""
    act = {"find": _START_RE, "do": "click", "optional": True}
    if fallback:
        act["else"] = list(fallback)
    return [act, {"wait": 0.3}]


START = start()

SPECS = {
    # ---------------- 普通
    "pelican": {"animated": True, "steps": [],
                "checklist": ck("鹈鹕形象可辨识（长喙/喉囊等特征）", "自行车结构完整（车架、双轮、踏板）",
                                "车轮旋转与腿部踩踏动作协调", "地面/背景滚动营造前进感")},
    "earth": {"animated": True,
              "steps": [step("拖拽改变视角", [{"drag": [[0.5, 0.5], [0.72, 0.42]], "steps": 14}]),
                        step("滚轮缩放", [{"wheel": -600, "at": C}])],
              "checklist": ck("球体与大陆轮廓清晰可辨", "海洋渐变、星空背景与大气光晕", "鼠标拖拽可旋转视角", "滚轮缩放有效")},
    "blackhole": {"animated": True, "steps": [],
                  "checklist": ck("事件视界黑色核心清晰", "吸积盘发光并旋转", "引力透镜弯曲背景星光的效果", "粒子被吸入的动态")},
    "matrix": {"animated": True,
               "steps": [step("鼠标处字符加速", [{"move": [[0.3, 0.5], [0.5, 0.5], [0.7, 0.5]]}])],
               "checklist": ck("绿色字符瀑布下落", "多层速度视差", "随机高亮字符", "鼠标附近字符加速")},
    "koi": {"animated": True,
            "steps": [step("点击水面产生涟漪", [{"click": [0.42, 0.55]}])],
            "checklist": ck("多条锦鲤自主游动与转向", "鱼尾摆动自然", "水面涟漪与荷叶", "点击产生涟漪并惊散鱼群")},
    "fireworks": {"animated": False,
                  "steps": [step("点击放烟花", [{"click": [0.5, 0.4]}], settle=0.5),
                            step("连续点击不同位置", [{"click": [0.25, 0.35]}, {"click": [0.75, 0.3]}], settle=0.5)],
                  "checklist": ck("点击处烟花爆炸", "粒子受重力/空气阻力并有拖尾", "花型多样随机", "夜空星星背景")},
    "solar": {"animated": True,
              "steps": [step("悬浮行星信息卡", [{"move": [[0.55, 0.5], [0.6, 0.45], [0.65, 0.5], [0.58, 0.58]]}]),
                        step("时间控制(暂停/加速)", [{"find": r"暂停|pause|加速|faster|speed|⏸|▶", "do": "click"}])],
              "checklist": ck("八大行星与轨道齐全", "周期与距离比例合理（对数缩放）", "发光太阳与轨道线",
                              "悬浮显示行星名与信息卡", "时间加速/减速/暂停控件可用")},
    "landing": {"animated": False, "responsive": True,
                "steps": [step("滚动页面", [{"wheel": 900, "at": C}], settle=0.8, native=True),
                          step("常见问题手风琴展开", [{"find": r"\?|？|常见问题|FAQ", "css": "summary,button,[class*=faq] *,[class*=accordion] *,dt,h3,h4", "do": "click"}], native=True)],
                "checklist": ck("粘性导航栏", "英雄区渐变与粒子背景", "三特性卡片", "价格表及悬停动效",
                                "常见问题手风琴与页脚", "移动端响应式布局")},
    "dashboard": {"animated": True, "idle": 3.0, "responsive": True,
                  "steps": [step("图表悬浮提示", [{"move": [[0.45, 0.55], [0.55, 0.55], [0.6, 0.5]]}]),
                            step("侧边栏路由切换", [{"find": r"分析|报表|用户|设置|订单|analytics|reports|users|settings", "css": "nav *,aside *,[class*=side] *", "do": "click"}])],
                  "checklist": ck("侧边栏与路由切换", "4 个指标卡带动效", "纯 Canvas 折线图带悬浮提示", "环形图", "实时数据刷新")},
    # ---------------- 困难
    "flappy": {"animated": False, "setup": START,
               "steps": [step("空格跳跃", [{"key": " ", "repeat": 3}], settle=0.4),
                         step("点击跳跃", [{"click": C}, {"click": C}], settle=0.4)],
               "checklist": ck("像素风小鸟与管道", "重力下落与跳跃手感", "随机管道间隙与碰撞死亡", "计分与最佳分记录", "死亡后可重开")},
    "tetris": {"animated": False, "setup": start({"key": "Enter"}),
               "steps": [step("方向键左移", [{"key": "ArrowLeft", "repeat": 3}], settle=0.3),
                         step("旋转", [{"key": "ArrowUp", "repeat": 2}], settle=0.3),
                         step("硬降", [{"key": " "}], settle=0.4)],
               "checklist": ck("7 种标准方块", "旋转与踢墙", "软降/硬降", "消行计分与等级加速", "下一个方块预览", "暂停与结束重开")},
    "breakout": {"animated": False, "setup": start({"key": " "}),
                 "steps": [step("鼠标控制挡板", [{"move": [[0.3, 0.85], [0.5, 0.85], [0.75, 0.85]]}], settle=0.4),
                           step("键盘控制挡板", [{"key": "ArrowLeft", "hold": 0.6}], settle=0.3)],
                 "checklist": ck("挡板/球/多排彩色砖块", "碰撞反弹正确", "道具掉落（加长/多球）", "生命数与关卡递进", "胜负判定")},
    "ninja": {"animated": True, "setup": START,
              "steps": [step("鼠标划动切割", [{"drag": [[0.2, 0.6], [0.8, 0.35]], "steps": 16}], settle=0.4)],
              "checklist": ck("水果抛物线抛出", "划动刀光轨迹", "切开两半与果汁粒子", "炸弹扣命", "连击计分与限时模式")},
    "platformer": {"animated": False, "setup": START,
                   "steps": [step("右移", [{"key": "ArrowRight", "hold": 0.7}], settle=0.3),
                             step("跳跃", [{"key": " "}, {"key": "ArrowUp"}], settle=0.4)],
                   "checklist": ck("角色重力与跳跃手感", "平台碰撞", "移动敌人与尖刺", "金币收集与旗杆过关", "多关卡与生命重生")},
    # 开始后蛇立即移动, 预热开始会在基线观察期间撞墙; 开始与转向放在同一步(基线为开始界面)
    "snake": {"animated": False,
              "steps": [step("开始并用方向键转向", start({"key": " "}) + [{"key": "ArrowUp"}, {"wait": 0.3}, {"key": "ArrowLeft"}], settle=0.4)],
              "checklist": ck("网格移动与方向控制（禁止反向）", "吃食物变长并加速", "撞墙/撞自己死亡", "分数与最高分", "开始/暂停/重开")},
    # ---------------- 地狱
    "fps": {"animated": False, "setup": start({"click": C}),
            "steps": [step("W 前进", [{"key": "w", "hold": 0.8}], settle=0.3),
                      step("A/D 或鼠标转向", [{"key": "d", "hold": 0.6}, {"key": "ArrowRight", "hold": 0.4}], settle=0.3)],
            "checklist": ck("raycasting 伪 3D 墙面透视正确", "WASD 移动与转向", "墙壁碰撞", "地面天花板渐变", "迷宫地图/出口/计时")},
    "cube3d": {"animated": False,
               "steps": [step("拖动旋转视角或拧层", [{"drag": [[0.5, 0.5], [0.66, 0.44]], "steps": 14}], settle=0.8),
                         step("打乱", [{"find": r"打乱|scramble|shuffle|随机", "do": "click"}], settle=1.2)],
               "checklist": ck("27 个小方块组成的 3D 魔方", "整体旋转视角", "分层拧动 90° 动画", "打乱按钮", "还原检测与计时步数")},
    "pinball": {"animated": False, "setup": [{"click": C}],
                "steps": [step("空格挡板/弹射", [{"key": " ", "hold": 0.8}], settle=0.6),
                          step("方向键挡板", [{"key": "ArrowLeft"}, {"key": "ArrowRight"}, {"key": "z"}, {"key": "/"}], settle=0.5)],
                "checklist": ck("弹珠台结构（挡板/弹射器/钉板缓冲器）", "重力与碰撞反弹物理", "空格控制挡板/发球", "计分与剩余球数")},
    "fluid": {"animated": False,
              "steps": [step("拖动注入流体", [{"drag": [[0.3, 0.5], [0.7, 0.45]], "steps": 20}], settle=0.6),
                        step("切换矢量场", [{"find": r"矢量|向量|速度场|vector|velocity|field", "do": "click", "optional": True}, {"key": "v"}], settle=0.6)],
               "checklist": ck("稳定流体解算（扩散与平流）", "鼠标拖动注入流体", "彩色染料效果", "矢量场可视化可切换")},
    "eco": {"animated": True,
            "steps": [step("点击投放", [{"click": [0.4, 0.45]}], settle=0.6)],
            "checklist": ck("草-食草动物-捕食者三层智能体", "能量/繁殖/饥饿/死亡机制", "实时种群曲线图", "点击投放", "参数滑块可调")},
    "piano": {"animated": False, "setup": [{"click": [0.5, 0.2]}],
              "steps": [step("键盘弹奏", [{"key": "a", "hold": 0.25}, {"key": "s", "hold": 0.25}, {"key": "d", "hold": 0.25}], settle=0.2),
                        step("点击琴键", [{"click": [0.5, 0.8]}], settle=0.3),
                        step("示例曲自动播放", [{"find": r"示例|演示|播放|play|demo", "do": "click"}], settle=1.0)],
              "checklist": ck("两排琴键外观与键盘映射提示", "按下琴键有视觉反馈", "合成琴音（包络+泛音，代码核实）", "录音与回放", "示例曲自动播放")},
    "sortviz": {"animated": False,
                "steps": [step("开始排序", [{"find": r"^(开始|开始排序|运行|start|run|play|排序|▶)", "do": "click"}], settle=1.2)],
                "checklist": ck("至少 6 种排序算法可切换/并排", "柱状图实时交换高亮", "复杂度与耗时统计", "数组大小与随机种子可设", "播放速度控制")},
    "win95": {"animated": False,
              "steps": [step("开始菜单", [{"find": r"^开始$|^start$", "do": "click"}], settle=0.5),
                        step("双击图标打开记事本", [{"key": "Escape"}, {"find": r"记事本|notepad", "do": "dblclick"}], settle=0.6),
                        step("右键菜单", [{"rclick": [0.6, 0.4]}], settle=0.5)],
              "checklist": ck("Win95 视觉风格（灰色立体边框/任务栏）", "窗口可拖拽、关闭/最小化、层叠 z-order", "开始菜单级联",
                              "任务栏与时钟", "记事本（可保存）与画板", "右键菜单")},
    # ---------------- 实战
    "applecard": {"animated": False, "responsive": True,
                  "steps": [step("滚动淡入", [{"wheel": 900, "at": C}], settle=1.0, native=True)],
                  "checklist": ck("大标题渐变文字", "毛玻璃导航栏", "滚动淡入动画", "精确留白与字体层级", "暗色优雅配色与 Apple 质感")},
    "stripe": {"animated": True, "responsive": True,
               "steps": [step("按钮悬停微交互", [{"find": r"开始|免费|注册|联系|start|get|sign|contact", "css": "a,button", "do": "hover"}], settle=0.5, native=True)],
               "checklist": ck("斜向彩色渐变动态背景（Canvas）", "渐变大标题", "按钮悬停微交互", "导航栏", "三列特性说明与像素级间距")},
    "iostodo": {"animated": False,
                "steps": [step("新增待办", [{"find": r"^(\+|＋|新增|添加|新建|add|new)", "do": "click", "optional": True},
                                          {"css": "input[type=text],input:not([type]),textarea", "find": "", "do": "click", "optional": True},
                                          {"type": "测试待办ABC\n"},
                                          {"find": r"^(添加|确定|完成|保存|add|save|done|ok)$", "do": "click", "optional": True}],
                           assert_js="document.body.innerText.includes('测试待办ABC')", settle=0.6),
                          step("勾选完成", [{"css": "input[type=checkbox],[class*=check],[role=checkbox]", "find": "", "do": "click"}], settle=0.6, native=True),
                          step("深浅色切换", [{"find": r"深色|浅色|暗|亮|dark|light|theme|🌙|☀", "do": "click"}], settle=0.6)],
                "checklist": ck("手机壳容器与 iOS 风格", "毛玻璃工具栏与圆角卡片", "新增输入弹层", "勾选划线动效与左滑删除", "深浅色切换与按压缩放细节")},
    "ecomdetail": {"animated": False, "responsive": True,
                   "steps": [step("SKU 选择", [{"find": r"^(XS|S|M|L|XL|XXL|3[5-9]|4[0-5]|黑色|白色|红色|蓝色|灰色)$", "do": "click"}], settle=0.5),
                             step("加入购物车", [{"find": r"加入购物车|add to cart", "do": "click"}], settle=0.8)],
                   "checklist": ck("图集缩略图切换", "价格与优惠标签", "SKU 颜色/尺码选择器选中态", "数量步进器与吸底购买栏",
                                   "加入购物车飞入动画", "评价卡片区")},
    "ioscalc": {"animated": False,
                "steps": [step("7 + 8 = 15", [{"find": r"^7$", "do": "click"}, {"find": r"^[+＋]$", "do": "click"},
                                             {"find": r"^8$", "do": "click"}, {"find": r"^[=＝]$", "do": "click"}],
                           count=_NUM_COUNT % "15", settle=0.5),
                          step("清除后 9 × 6 = 54", [{"find": r"^(AC|C)$", "do": "click", "optional": True},
                                                  {"find": r"^9$", "do": "click"}, {"find": r"^[×x*✕]$", "do": "click"},
                                                  {"find": r"^6$", "do": "click"}, {"find": r"^[=＝]$", "do": "click"}],
                           count=_NUM_COUNT % "54", settle=0.5)],
                "checklist": ck("网格布局与圆形按键", "深色数字键/橙色运算键配色", "按压缩放动效", "顶部历史行", "四则/百分比/正负/退格逻辑正确")},
    "dock": {"animated": False,
             "steps": [step("鱼眼放大", [{"move": [[0.35, 0.93], [0.45, 0.93], [0.52, 0.93]]}], settle=0.4),
                       step("点击弹跳", [{"click": [0.5, 0.93]}], settle=0.4)],
             "checklist": ck("图标横向排列与反光底座", "鼠标接近时按距离鱼眼放大", "悬停名称气泡", "点击弹跳动画")},
    "terminal": {"animated": False, "setup": [{"click": C}],
                 "steps": [step("help 命令", [{"type": "help\n"}], count="(document.body.innerText.match(/whoami/gi) || []).length", settle=1.2),
                           step("echo 命令", [{"type": "echo hello9527\n"}],
                                count="document.body.innerText.split('hello9527').length - 1", gain=2, settle=1.2),
                           step("上键历史", [{"key": "ArrowUp"}], assert_js=None, settle=0.4)],
                 "checklist": ck("macOS 标题栏红黄绿圆点", "等宽字体与闪烁光标", "help/ls/date/echo/clear/whoami 命令", "上下键命令历史", "打字机输出效果与毛玻璃暗色背景")},
    "parallax": {"animated": False,
                 "steps": [step("悬停 3D 倾斜", [{"move": [[0.2, 0.45], [0.26, 0.5], [0.3, 0.42]]}], settle=0.4)],
                 "checklist": ck("三张不同主题色卡片", "鼠标移动 3D 倾斜（perspective）", "表面高光随角度流动", "悬停上浮与投影加深", "卡片内容排版精致")},
    "glasslogin": {"animated": True,
                   "steps": [step("空提交错误提示", [{"find": r"^(登录|登 录|login|sign in|log in)$", "css": "button,input[type=submit],a", "do": "click"}], settle=0.6),
                             step("输入并登录", [{"css": "input[type=text],input[type=email],input:not([type])", "find": "", "do": "click"},
                                               {"type": "demo@test.com"},
                                               {"css": "input[type=password]", "find": "", "do": "click"},
                                               {"type": "Passw0rd!"},
                                               {"find": r"^(登录|登 录|login|sign in|log in)$", "css": "button,input[type=submit],a", "do": "click"}], settle=1.5)],
                   "checklist": ck("流动渐变背景", "玻璃拟态登录卡", "输入框聚焦浮动标签", "错误抖动提示与密码可见切换", "登录加载态与成功动效")},
    "feed": {"animated": False, "responsive": True,
             "steps": [step("点赞动效", [{"find": r"赞|like|♥|❤|👍", "do": "click"}], settle=0.6),
                       step("滚动加载", [{"wheel": 2500, "at": C}, {"wait": 0.8}, {"wheel": 2500, "at": C}], settle=1.2, native=True)],
             "checklist": ck("顶栏与卡片流（头像/昵称/时间/正文/图）", "点赞转发动效", "无限滚动加载与骨架屏", "图片九宫格", "返回顶部按钮")},
}


def get(task_id):
    spec = dict(SPECS.get(task_id) or {"animated": False, "steps": [], "checklist": []})
    spec.setdefault("idle", 1.0)
    spec.setdefault("responsive", False)
    spec.setdefault("setup", [])
    return spec


# ---------------------------------------------------------------- 评分标准: 以「能不能用」为准
#
# 算分的只有四类(每道题 1~3 条核心断言): 能打开(load)、不白屏(nonblank)、不报错(no_error)、
# 题目要求的核心操作有反应(step1…)。动画、手机适配、外部网络依赖、代码写完整、HTML 文档结构、代码关键词
# 都只作提示, 不算分; AI 看图打分和人工星级另外列出, 不混进这个分数。
# 纯动画题(没有操作步骤)的核心断言就是「画面在动」, 这时 animated 也算分, 保证每道题至少有一条核心断言。
# 没有在浏览器里实际运行(只看了代码)看不出能不能用, 不打分。
# 前端 web/static/app.js 的 genChecks 用同一套规则; tests/js/gen_score_cases.json 是两边共用的用例。

CORE_FIXED = ("load", "nonblank", "no_error")
_STEP = re.compile(r"^step\d+$")


def is_core(cid, ids):
    """这一项检查算不算分。ids: 这件作品做过的全部检查 id(有没有操作步骤决定动画算不算分)。"""
    cid = str(cid)
    if cid in CORE_FIXED or _STEP.match(cid):
        return True
    return cid == "animated" and not any(_STEP.match(str(i)) for i in ids)


def score_checks(checks, method="browser", control=None):
    """按「能不能用」给一件作品的检查记录算分。
    返回 {"core": 算分的检查 id, "env": 不算分的「可能是检测引起的报错」的检查 id, "pass": 通过几项, "total": 算分几项,
    "score": 0-100 或 None}。没有在浏览器里实际运行(method 不是 browser)或者没有算分项: score 是 None。
    no_error 没通过、但在不注入检测脚本的干净页面里没有复现(control.reproduced 是 False): 可能是检测引起的,
    不算在作品头上, 不算分, 归入 env。"""
    checks = [c for c in checks or [] if isinstance(c, dict) and c.get("id") is not None]
    out = {"core": [], "env": [], "pass": 0, "total": 0, "score": None}
    if method != "browser":
        return out
    ids = [str(c["id"]) for c in checks]
    not_reproduced = isinstance(control, dict) and control.get("reproduced") is False
    for c in checks:
        cid = str(c["id"])
        if not is_core(cid, ids):
            continue
        if cid == "no_error" and not c.get("pass") and not_reproduced:
            out["env"].append(cid)
            continue
        out["core"].append(cid)
        if c.get("pass"):
            out["pass"] += 1
    out["total"] = len(out["core"])
    if out["total"]:
        out["score"] = round(100.0 * out["pass"] / out["total"], 1)
    return out
