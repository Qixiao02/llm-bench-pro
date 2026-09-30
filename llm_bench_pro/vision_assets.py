# -*- coding: utf-8 -*-
"""看图回答场景的图片 (纯标准库)。

1. 图片检查: 从文件头读出真实格式与宽高(PNG / JPEG / WebP / GIF), 判断能不能发给看图模型。
   损坏、太小(小于 28×28, Qwen-VL 一类模型按 28 像素一格切图, 服务端会直接 HTTP 400)、
   太大(单张超过 20 MB 或边长超过 8192)的不收; 小于 224×224、扩展名和真实格式不符的收下但提示。
2. 内置示例图片: 用 zlib + struct 手写 PNG 编码, 在代码里画几张有内容的图(几何图形、柱状图、色块拼图等),
   不上传也能跑看图回答。每张图配套的提示词只问图里确实有的东西。
   输出确定: 同一套代码画出的像素完全相同, 压缩后的字节在同一个 zlib 下也完全相同。
"""
import base64
import functools
import math
import os
import struct
import zlib

try:
    from . import i18n  # 包内导入
except ImportError:
    import i18n  # server.py 以包目录为 sys.path 顶层导入

t = i18n.t

MIN_SIDE = 28                     # 每边至少 28 像素, 更小的看图模型会拒绝
GOOD_SIDE = 224                   # 小于它收下但提示: 细节太少, 可能影响回答
MAX_SIDE = 8192                   # 边长上限
MAX_BYTES = 20 * 1024 * 1024      # 单张上限 20 MB

# 真实格式 -> (MIME, 保存用的扩展名, 显示名)
FORMATS = {"png": ("image/png", ".png", "PNG"), "jpeg": ("image/jpeg", ".jpg", "JPEG"),
           "webp": ("image/webp", ".webp", "WebP"), "gif": ("image/gif", ".gif", "GIF")}
EXT_FORMAT = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp", ".gif": "gif"}


class ImageError(ValueError):
    """认不出或已损坏的图片。code: unsupported(不是支持的格式) / broken(文件损坏或不完整)。"""

    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


# ---------------------------------------------------------------- 文件头解析

def image_info(data):
    """读出 (格式, 宽, 高); 认不出或文件不完整时抛 ImageError(原因用大白话)。"""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ("png",) + _png_size(data)
    if data[:3] == b"\xff\xd8\xff":
        return ("jpeg",) + _jpeg_size(data)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ("webp",) + _webp_size(data)
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ("gif",) + _gif_size(data)
    raise ImageError("unsupported", _unknown_format(data))


def _cut(fmt):
    return ImageError("broken", t("文件不完整（{fmt} 没有正常结束，可能下载或拷贝时被截断了）", fmt=fmt))


def _png_size(d):
    """逐块走一遍: 每块校验 CRC, 必须以 IHDR 开头、含图像数据、以 IEND 结束。"""
    pos, size, has_data = 8, None, False
    while True:
        if pos + 12 > len(d):
            raise _cut("PNG")
        n, typ = struct.unpack(">I4s", d[pos:pos + 8])
        end = pos + 12 + n
        if end > len(d):
            raise _cut("PNG")
        if zlib.crc32(d[pos + 4:end - 4]) & 0xFFFFFFFF != struct.unpack(">I", d[end - 4:end])[0]:
            raise ImageError("broken", t("文件已损坏（PNG 数据校验不通过）"))
        if size is None:
            if typ != b"IHDR" or n != 13:
                raise ImageError("broken", t("文件已损坏（PNG 缺少文件头）"))
            size = struct.unpack(">II", d[pos + 8:pos + 16])
        elif typ == b"IDAT":
            has_data = True
        elif typ == b"IEND":
            if not has_data:
                raise ImageError("broken", t("文件已损坏（PNG 里没有图像数据）"))
            return size
        pos = end


# 带宽高的帧头(SOF): C0-CF 中除去 C4(DHT) / C8(保留) / CC(DAC)
_JPEG_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def _jpeg_size(d):
    """按段跳读找到帧头(SOF)取宽高; SOF 之后必须还有结束标记(EOI), 否则是被截断的文件。"""
    pos, n = 2, len(d)
    while pos < n:
        if d[pos] != 0xFF:
            break
        while pos < n and d[pos] == 0xFF:  # 标记前可以有若干填充的 0xFF
            pos += 1
        if pos >= n:
            break
        mark = d[pos]
        pos += 1
        if mark == 0xD8 or mark == 0x01 or 0xD0 <= mark <= 0xD7:  # 没有长度字段的标记
            continue
        if mark in (0xD9, 0xDA):  # 还没见到帧头就到了图像数据或文件结尾
            break
        if pos + 2 > n:
            raise _cut("JPEG")
        seg = struct.unpack(">H", d[pos:pos + 2])[0]
        if seg < 2 or pos + seg > n:
            raise _cut("JPEG")
        if mark in _JPEG_SOF:
            if seg < 7:
                break
            h, w = struct.unpack(">HH", d[pos + 3:pos + 7])
            if d.rfind(b"\xff\xd9") < pos + seg:
                raise _cut("JPEG")
            if not w or not h:
                break
            return w, h
        pos += seg
    raise ImageError("broken", t("文件已损坏（JPEG 里读不出宽高）"))


def _webp_size(d):
    if len(d) < 8 + struct.unpack("<I", d[4:8])[0]:
        raise _cut("WebP")
    kind = d[12:16]
    if kind == b"VP8 " and len(d) >= 30 and d[23:26] == b"\x9d\x01\x2a":  # 有损
        w, h = struct.unpack("<HH", d[26:30])
        return w & 0x3FFF, h & 0x3FFF
    if kind == b"VP8L" and len(d) >= 25 and d[20] == 0x2F:  # 无损
        b = int.from_bytes(d[21:25], "little")
        return (b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1
    if kind == b"VP8X" and len(d) >= 30:  # 扩展格式(带透明/动画)
        return int.from_bytes(d[24:27], "little") + 1, int.from_bytes(d[27:30], "little") + 1
    raise ImageError("broken", t("文件已损坏（WebP 里读不出宽高）"))


def _gif_size(d):
    if len(d) < 13:
        raise _cut("GIF")
    w, h = struct.unpack("<HH", d[6:10])
    if not d.rstrip(b"\x00").endswith(b"\x3b"):  # GIF 以 0x3B 结尾
        raise _cut("GIF")
    return w, h


def _unknown_format(d):
    if not d:
        return t("文件是空的")
    head = d[:64].lstrip().lower()
    kind = None
    if d[:2] == b"BM":
        kind = "BMP"
    elif d[:4] in (b"II*\x00", b"MM\x00*"):
        kind = "TIFF"
    elif d[4:8] == b"ftyp" and d[8:12] in (b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1"):
        kind = "HEIC"
    elif d[4:8] == b"ftyp" and d[8:12] in (b"avif", b"avis"):
        kind = "AVIF"
    elif head.startswith((b"<svg", b"<?xml")):
        kind = "SVG"
    if kind:
        return t("是 {kind} 格式，暂不支持，请转成 JPG 或 PNG 再用", kind=kind)
    return t("不是能识别的图片（只支持 JPG / PNG / WebP / GIF）")


# ---------------------------------------------------------------- 逐张检查

def _mb(n):
    return "%.1f MB" % (n / 1048576.0)


def check_image(data, name=None):
    """检查一张图片能不能发给看图模型。返回
    {name, bytes, format, width, height, ext(按真实格式保存用的扩展名), ok, level(ok|warn|bad), code, msg}。
    ok=False 的不收进图片包、也不发给模型; code 说明原因: empty / broken / unsupported / too_big / too_small / too_large。"""
    out = {"name": name or "", "bytes": len(data), "format": None, "width": None, "height": None, "ext": None,
           "ok": False, "level": "bad", "code": "", "msg": ""}
    if not data:
        out.update(code="empty", msg=t("文件是空的"))
        return out
    try:
        fmt, w, h = image_info(data)
    except ImageError as e:
        out.update(code=e.code, msg=str(e))
        return out
    out.update(format=fmt, width=w, height=h, ext=FORMATS[fmt][1])
    if len(data) > MAX_BYTES:
        out.update(code="too_big", msg=t("有 {size}，超过单张 20 MB 的上限", size=_mb(len(data))))
    elif w < MIN_SIDE or h < MIN_SIDE:
        out.update(code="too_small", msg=t("只有 {w}×{h} 像素，太小，看图模型会直接拒绝（每边至少 {min_side} 像素）",
                                            w=w, h=h, min_side=MIN_SIDE))
    elif max(w, h) > MAX_SIDE:
        out.update(code="too_large", msg=t("尺寸 {w}×{h}，边长超过 {max_side} 像素，请缩小后再用", w=w, h=h, max_side=MAX_SIDE))
    else:
        notes = []
        if min(w, h) < GOOD_SIDE:
            notes.append(t("尺寸 {w}×{h} 偏小，可能影响回答效果（推荐 {rec}×{rec} 以上）", w=w, h=h, rec=GOOD_SIDE))
        ext = os.path.splitext(name or "")[1].lower()
        if ext in EXT_FORMAT and EXT_FORMAT[ext] != fmt:
            notes.append(t("扩展名是 {ext}，实际是 {actual} 图片，已按 {actual} 处理", ext=ext, actual=FORMATS[fmt][2]))
        out.update(ok=True, level="warn" if notes else "ok", msg=t("；", ctx="图片检查").join(notes))
    return out


def check_line(c):
    """一张图片的检查结果拼成一句「名称 说明」: 上传汇总、素材列表、启动检查的报错里用。中文用空格连接 (和以前一样);
    英文的说明是首字母大写的短语, 用冒号接在名称后面。(连接符不走词典: 词典的键必须含汉字, 而这里中文那一边只是一个空格。)"""
    return "%s%s%s" % (c["name"], ": " if i18n.current_lang() == "en" else " ", c["msg"])


def scan_dir(d, keep_data=True):
    """检查文件夹里的图片(只看支持的扩展名, 按文件名排序)。
    返回 (能用的 [(文件名, 字节或 None, 检查结果)], 全部检查结果)。"""
    good, checks = [], []
    for n in sorted(os.listdir(d)):
        p = os.path.join(d, n)
        if os.path.splitext(n)[1].lower() not in EXT_FORMAT or not os.path.isfile(p):
            continue
        size = os.path.getsize(p)
        data = None
        if size > MAX_BYTES:  # 太大的不读进内存
            c = {"name": n, "bytes": size, "format": None, "width": None, "height": None, "ext": None,
                 "ok": False, "level": "bad", "code": "too_big", "msg": t("有 {size}，超过单张 20 MB 的上限", size=_mb(size))}
        else:
            with open(p, "rb") as f:
                data = f.read()
            c = check_image(data, name=n)
        checks.append(c)
        if c["ok"]:
            good.append((n, data if keep_data else None, c))
    return good, checks


def data_url(data, fmt=None):
    """图片字节 -> data URL(看图请求里 image_url 的写法)。"""
    fmt = fmt or image_info(data)[0]
    return "data:%s;base64,%s" % (FORMATS[fmt][0], base64.b64encode(data).decode("ascii"))


# ---------------------------------------------------------------- PNG 编码与画布

def encode_png(width, height, rows):
    """RGB 8 位 PNG: 每行过滤类型 0(不过滤), zlib 级别 9 压缩。"""
    raw = b"".join(b"\x00" + bytes(r) for r in rows)

    def chunk(typ, body):
        return struct.pack(">I", len(body)) + typ + body + struct.pack(">I", zlib.crc32(typ + body) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


class Canvas:
    """极简 RGB 画布: 按像素中心采样填充(不做抗锯齿), 结果只取决于坐标, 不依赖字体或系统。"""

    def __init__(self, width, height, bg=(255, 255, 255)):
        self.w, self.h = width, height
        self.rows = [bytearray(bytes(bg) * width) for _ in range(height)]

    def span(self, y, x0, x1, color):
        """第 y 行: 像素中心落在 [x0, x1) 的像素填色。"""
        if 0 <= y < self.h:
            a, b = max(0, math.ceil(x0 - 0.5)), min(self.w, math.ceil(x1 - 0.5))
            if b > a:
                self.rows[y][3 * a:3 * b] = bytes(color) * (b - a)

    def rect(self, x0, y0, x1, y1, color):
        for y in range(max(0, math.ceil(y0 - 0.5)), min(self.h, math.ceil(y1 - 0.5))):
            self.span(y, x0, x1, color)

    def circle(self, cx, cy, r, color):
        for y in range(max(0, math.floor(cy - r)), min(self.h, math.ceil(cy + r) + 1)):
            dy = y + 0.5 - cy
            if abs(dy) < r:
                half = math.sqrt(r * r - dy * dy)
                self.span(y, cx - half, cx + half, color)

    def polygon(self, pts, color):
        """扫描线填充(奇偶规则)。"""
        ys = [p[1] for p in pts]
        edges = list(zip(pts, pts[1:] + pts[:1]))
        for y in range(max(0, math.floor(min(ys))), min(self.h, math.ceil(max(ys)) + 1)):
            yc = y + 0.5
            xs = sorted(x1 + (yc - y1) * (x2 - x1) / (y2 - y1)
                        for (x1, y1), (x2, y2) in edges if (y1 <= yc < y2) or (y2 <= yc < y1))
            for a, b in zip(xs[0::2], xs[1::2]):
                self.span(y, a, b, color)

    def line(self, x1, y1, x2, y2, width, color):
        """粗线段: 四边形 + 两端圆头。"""
        length = math.hypot(x2 - x1, y2 - y1) or 1.0
        nx, ny = -(y2 - y1) / length * width / 2, (x2 - x1) / length * width / 2
        self.polygon([(x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)], color)
        self.circle(x1, y1, width / 2, color)
        self.circle(x2, y2, width / 2, color)

    def pixel(self, x, y):
        return tuple(self.rows[y][3 * x:3 * x + 3])

    def png(self):
        return encode_png(self.w, self.h, self.rows)


# ---------------------------------------------------------------- 内置示例图片

SAMPLE_SIZE = 448
RED, BLUE, GREEN = (220, 38, 38), (37, 99, 235), (22, 163, 74)
YELLOW, ORANGE, PURPLE, GRAY = (234, 179, 8), (249, 115, 22), (147, 51, 234), (156, 163, 175)
AXIS, GRID = (55, 65, 81), (226, 229, 234)
_PLOT = (64, 48, 424, 400)  # 图表的绘图区: 左、上、右、下(横轴在下边)


def _draw_shapes():
    """三个图形, 从左到右越来越小: 红色圆形 > 蓝色正方形 > 绿色三角形。"""
    c = Canvas(SAMPLE_SIZE, SAMPLE_SIZE)
    c.circle(112, 224, 84, RED)
    c.rect(206, 164, 326, 284, BLUE)
    c.polygon([(344, 276), (432, 276), (388, 184)], GREEN)
    return c


def _axes(c, unit):
    x0, y0, x1, y1 = _PLOT
    for k in (2, 4, 6, 8):  # 浅灰横向网格线
        c.rect(x0, y1 - k * unit - 1, x1, y1 - k * unit + 1, GRID)


def _axis_lines(c):
    x0, y0, x1, y1 = _PLOT
    c.rect(x0 - 3, y0 - 8, x0, y1 + 3, AXIS)  # 纵轴
    c.rect(x0 - 3, y1, x1 + 8, y1 + 3, AXIS)  # 横轴


BAR_VALUES = [3, 6, 4, 8, 5]
BAR_COLORS = [BLUE, ORANGE, GREEN, PURPLE, GRAY]


def _draw_bars():
    """柱状图: 5 根不同颜色的柱子, 最高的是从左数第 4 根(紫色), 最矮的是第 1 根(蓝色)。"""
    c = Canvas(SAMPLE_SIZE, SAMPLE_SIZE)
    x0, y0, x1, y1 = _PLOT
    unit = (y1 - y0) / 8.0
    _axes(c, unit)
    slot = (x1 - x0) / float(len(BAR_VALUES))
    for i, (v, col) in enumerate(zip(BAR_VALUES, BAR_COLORS)):
        bx = x0 + slot * i + 14
        c.rect(bx, y1 - v * unit, bx + slot - 28, y1, col)
    _axis_lines(c)
    return c


GRID_LAYOUT = [[RED, BLUE, GREEN], [YELLOW, RED, BLUE], [GREEN, YELLOW, RED]]


def _draw_grid():
    """3×3 色块拼图: 红色沿左上到右下的对角线(3 块), 蓝、绿、黄各 2 块。"""
    c = Canvas(SAMPLE_SIZE, SAMPLE_SIZE)
    cell, gap, margin = 128, 16, 16
    for r, row in enumerate(GRID_LAYOUT):
        for k, col in enumerate(row):
            x, y = margin + k * (cell + gap), margin + r * (cell + gap)
            c.rect(x, y, x + cell, y + cell, col)
    return c


PIE_PARTS = [(0.50, BLUE), (0.25, ORANGE), (0.15, GREEN), (0.10, GRAY)]  # 从 12 点钟方向顺时针


def _draw_pie():
    """饼图: 蓝 50%、橙 25%、绿 15%、灰 10%, 扇区之间留白线。"""
    c = Canvas(SAMPLE_SIZE, SAMPLE_SIZE)
    cx, cy, r = 224, 224, 176
    bounds, acc = [], 0.0
    for frac, col in PIE_PARTS:
        acc += frac
        bounds.append((acc, bytes(col)))
    for y in range(cy - r, cy + r):
        dy = y + 0.5 - cy
        half = math.sqrt(r * r - dy * dy)
        row = c.rows[y]
        for x in range(math.ceil(cx - half - 0.5), math.ceil(cx + half - 0.5)):
            t = (math.atan2(x + 0.5 - cx, -dy) / (2 * math.pi)) % 1.0  # 12 点钟为 0, 顺时针增加
            row[3 * x:3 * x + 3] = next((col for b, col in bounds if t < b), bounds[-1][1])
    acc = 0.0
    for frac, _ in PIE_PARTS:
        a = acc * 2 * math.pi
        c.line(cx, cy, cx + r * math.sin(a), cy - r * math.cos(a), 4, (255, 255, 255))
        acc += frac
    return c


COUNT_CIRCLES = [(80, 72), (366, 86), (224, 224), (86, 370), (362, 366)]
COUNT_SQUARES = [(224, 76), (78, 224), (370, 226)]


def _draw_count():
    """数一数: 5 个蓝色圆形、3 个红色正方形, 互不重叠。"""
    c = Canvas(SAMPLE_SIZE, SAMPLE_SIZE)
    for x, y in COUNT_CIRCLES:
        c.circle(x, y, 38, BLUE)
    for x, y in COUNT_SQUARES:
        c.rect(x - 34, y - 34, x + 34, y + 34, RED)
    return c


LINE_VALUES = [2, 3.5, 3, 5.5, 7, 6]


def _draw_line():
    """折线图: 6 个点整体上升, 最高点是第 5 个; 第 2→3、第 5→6 两段下降。"""
    c = Canvas(SAMPLE_SIZE, SAMPLE_SIZE)
    x0, y0, x1, y1 = _PLOT
    unit = (y1 - y0) / 8.0
    _axes(c, unit)
    step = (x1 - x0 - 40) / float(len(LINE_VALUES) - 1)
    pts = [(x0 + 20 + step * i, y1 - v * unit) for i, v in enumerate(LINE_VALUES)]
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        c.line(ax, ay, bx, by, 5, BLUE)
    for x, y in pts:
        c.circle(x, y, 9, BLUE)
    _axis_lines(c)
    return c


# (文件名, 显示名, 画法, 只问图里有的东西的提示词)
SAMPLES = [
    ("01-shapes.png", "几何图形", _draw_shapes, [
        "图里有哪几种形状？分别是什么颜色？",
        "从左到右依次说出图中的图形和颜色，并指出面积最大的是哪一个。",
        "图里一共有几个图形？其中三角形是什么颜色？"]),
    ("02-bars.png", "柱状图", _draw_bars, [
        "这是一张柱状图。哪根柱子最高？它是从左往右数第几根、什么颜色？",
        "图里一共有几根柱子？请按从高到低的顺序说出它们的颜色。",
        "最矮的柱子是什么颜色？它的高度大约是最高那根的几分之几？"]),
    ("03-grid.png", "色块拼图", _draw_grid, [
        "这是一张 3×3 的色块拼图。左上角、正中间和右下角的方块分别是什么颜色？",
        "红色的方块有几个？它们排成了什么形状？",
        "按从上到下、从左到右的顺序，说出九个方块的颜色。"]),
    ("04-pie.png", "饼图", _draw_pie, [
        "这是一张饼图。哪一块最大？它大约占整个圆的多少？",
        "饼图分成了几块？请按从大到小的顺序说出每一块的颜色。"]),
    ("05-count.png", "数一数", _draw_count, [
        "图里有几个蓝色圆形、几个红色正方形？",
        "图里一共有多少个图形？哪种颜色的图形最多？"]),
    ("06-line.png", "折线图", _draw_line, [
        "这是一张折线图。整体趋势是上升还是下降？最高点是从左往右数第几个点？",
        "折线一共有几个点？哪几段是往下降的？"]),
]
# 一次请求带多张内置图时的提示词(对每张图都成立)
SAMPLE_MULTI_PROMPTS = [
    "这里有几张图。请依次说说每张图里有什么：是什么类型的图，有哪些形状和颜色。",
    "逐张看这些图：如果是图表，指出最高或最大的那一项；如果是图形或色块，说出各有几个、分别是什么颜色。",
]


@functools.lru_cache(maxsize=1)
def sample_images():
    """内置示例图片: ((文件名, 显示名, PNG 字节, 提示词元组), ...); 进程内只画一次。"""
    return tuple((fn, label, draw().png(), tuple(prompts)) for fn, label, draw, prompts in SAMPLES)


def sample_summary():
    """给页面列表用: 张数、尺寸、每张的名字(不需要真的画图)。"""
    return {"image_id": "builtin", "count": len(SAMPLES), "width": SAMPLE_SIZE, "height": SAMPLE_SIZE,
            "names": [label for _, label, _, _ in SAMPLES]}
