# -*- coding: utf-8 -*-
"""模拟真实业务的素材: 图片检查(PNG/JPEG/WebP/GIF 宽高)、内置示例图片、自定义任务集模板与逐行检查、
请求失败时保存服务端返回的原因。全部离线: 模型服务用本地 MockServer 代替。"""
import base64
import json
import os
import random
import re
import struct
import unittest
import urllib.error
import zlib

from _util import ROOT, MockServer, temp_dir
import bench
import cdp
import server
import vision_assets as va
from test_server import ServerCase

# 用户图片包里那张 70 字节的 1×1 PNG(与 test_server 以前的上传夹具逐字节相同)
TINY_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def png_of(w, h, rgb=(255, 255, 255)):
    return va.encode_png(w, h, [bytes(rgb) * w for _ in range(h)])


def jpeg_of(w, h, sof=0xC0, app=b"", tail=b"\xff\xd9"):
    """最小 JPEG 结构: SOI + (APP 段) + SOF(宽高) + 结束标记 EOI。"""
    sof_seg = b"\xff" + bytes([sof]) + struct.pack(">HBHHB", 17, 8, h, w, 3) + bytes(9)
    return b"\xff\xd8" + app + sof_seg + b"\xff\xda\x00\x08" + bytes(6) + b"\x12\x34" + tail


def riff(chunk):
    body = b"WEBP" + chunk
    return b"RIFF" + struct.pack("<I", len(body)) + body


def app_template():
    """读出 app.js 里的任务集模板(TASK-TEMPLATE-BEGIN/END 之间是严格 JSON)。"""
    with open(os.path.join(ROOT, "web", "static", "app.js"), encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"/\*TASK-TEMPLATE-BEGIN\*/(.*?)/\*TASK-TEMPLATE-END\*/", src, re.S)
    return json.loads(m.group(1))


class TestImageCheck(unittest.TestCase):
    def test_png_size_and_min_side(self):
        self.assertEqual(va.image_info(png_of(300, 200)), ("png", 300, 200))
        c = va.check_image(TINY_PNG, "00.png")                      # 用户那张图: 1×1, 不收
        self.assertEqual((c["ok"], c["code"], c["width"], c["height"]), (False, "too_small", 1, 1))
        self.assertIn("1×1", c["msg"])
        self.assertIn("28", c["msg"])
        self.assertEqual(va.check_image(png_of(27, 400))["code"], "too_small")
        c = va.check_image(png_of(28, 28))                           # 刚好够: 收下, 提示偏小
        self.assertEqual((c["ok"], c["level"]), (True, "warn"))
        self.assertIn("224×224", c["msg"])
        c = va.check_image(png_of(224, 300))
        self.assertEqual((c["ok"], c["level"], c["msg"]), (True, "ok", ""))
        self.assertEqual(va.check_image(png_of(8193, 30))["code"], "too_large")

    def test_png_damaged_or_truncated(self):
        good = png_of(64, 64, (10, 20, 30))
        broken = bytearray(good)
        broken[40] ^= 0xFF                                           # 改坏图像数据: 校验不通过
        c = va.check_image(bytes(broken))
        self.assertEqual((c["ok"], c["code"]), (False, "broken"))
        self.assertIn("校验", c["msg"])
        c = va.check_image(good[:-12])                               # 缺了结尾: 被截断
        self.assertEqual(c["code"], "broken")
        self.assertIn("不完整", c["msg"])
        self.assertEqual(va.check_image(b"\x89PNG\r\n\x1a\n\n")["code"], "broken")

    def test_jpeg_size(self):
        app0 = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        self.assertEqual(va.image_info(jpeg_of(640, 480, app=app0)), ("jpeg", 640, 480))
        self.assertEqual(va.image_info(jpeg_of(1024, 768, sof=0xC2)), ("jpeg", 1024, 768))  # 渐进式
        filled = jpeg_of(300, 200).replace(b"\xff\xc0", b"\xff\xff\xff\xc0", 1)            # 标记前的填充字节
        self.assertEqual(va.image_info(filled)[1:], (300, 200))
        self.assertEqual(va.check_image(jpeg_of(640, 480, tail=b""))["code"], "broken")     # 没有结束标记
        # 缩略图自带的结束标记在主图帧头之前, 主图本身被截断: 仍判为不完整
        thumb = b"\xff\xe1\x00\x06" + b"\xff\xd8\xff\xd9"
        self.assertEqual(va.check_image(jpeg_of(640, 480, app=thumb, tail=b""))["code"], "broken")
        self.assertEqual(va.check_image(jpeg_of(16, 16))["code"], "too_small")
        self.assertEqual(va.check_image(b"\xff\xd8\xff\xe0\x00\x10JFIF")["code"], "broken")

    def test_webp_and_gif_size(self):
        vp8 = b"VP8 " + struct.pack("<I", 10) + b"\x00\x00\x00\x9d\x01\x2a" + struct.pack("<HH", 400, 300)
        self.assertEqual(va.image_info(riff(vp8)), ("webp", 400, 300))
        bits = (500 - 1) | ((250 - 1) << 14)
        vp8l = b"VP8L" + struct.pack("<I", 5) + b"\x2f" + bits.to_bytes(4, "little")
        self.assertEqual(va.image_info(riff(vp8l)), ("webp", 500, 250))
        vp8x = b"VP8X" + struct.pack("<I", 10) + b"\x10\x00\x00\x00" + (800 - 1).to_bytes(3, "little") + (600 - 1).to_bytes(3, "little")
        self.assertEqual(va.image_info(riff(vp8x)), ("webp", 800, 600))
        self.assertEqual(va.check_image(riff(vp8)[:-4])["code"], "broken")              # RIFF 长度对不上: 截断
        gif = b"GIF89a" + struct.pack("<HH", 320, 240) + b"\x00\x00\x00" + b"\x2c" + bytes(9) + b"\x3b"
        self.assertEqual(va.image_info(gif), ("gif", 320, 240))
        self.assertEqual(va.check_image(gif[:-1])["code"], "broken")

    def test_unknown_formats_and_extension_mismatch(self):
        self.assertIn("BMP", va.check_image(b"BM" + bytes(60))["msg"])
        self.assertIn("HEIC", va.check_image(b"\x00\x00\x00\x18ftypheic" + bytes(20))["msg"])
        self.assertEqual(va.check_image(b"hello world")["code"], "unsupported")
        self.assertEqual(va.check_image(b"")["code"], "empty")
        c = va.check_image(png_of(300, 300), "photo.jpg")            # 扩展名写错: 收下, 按真实格式处理
        self.assertEqual((c["ok"], c["level"], c["ext"]), (True, "warn", ".png"))
        self.assertIn("实际是 PNG", c["msg"])
        old = va.MAX_BYTES
        va.MAX_BYTES = 100
        try:
            self.assertEqual(va.check_image(png_of(300, 300))["code"], "too_big")
        finally:
            va.MAX_BYTES = old

    def test_scan_dir(self):
        d = temp_dir()
        for name, data in (("a.png", png_of(300, 300)), ("b.png", TINY_PNG), ("c.txt", b"x"), ("d.gif", b"GIF89a")):
            with open(os.path.join(d, name), "wb") as f:
                f.write(data)
        good, checks = va.scan_dir(d)
        self.assertEqual([c["name"] for c in checks], ["a.png", "b.png", "d.gif"])  # 只看图片扩展名
        self.assertEqual([n for n, _, _ in good], ["a.png"])
        self.assertIsNotNone(good[0][1])
        self.assertIsNone(va.scan_dir(d, keep_data=False)[0][0][1])


class TestBuiltinSamples(unittest.TestCase):
    def test_generation_is_stable_valid_png(self):
        first = va.sample_images()
        va.sample_images.cache_clear()
        again = va.sample_images()
        self.assertEqual([x[2] for x in first], [x[2] for x in again])       # 同样的输入得到同样的字节
        self.assertGreaterEqual(len(first), 5)
        for fn, label, png, prompts in first:
            with self.subTest(sample=label):
                self.assertEqual(va.image_info(png), ("png", va.SAMPLE_SIZE, va.SAMPLE_SIZE))
                self.assertEqual(va.check_image(png, fn)["level"], "ok")
                w, h, ch, _ = cdp.decode_png(png)                             # 自己的解码器读回
                self.assertEqual((w, h, ch), (va.SAMPLE_SIZE, va.SAMPLE_SIZE, 3))
                self.assertGreaterEqual(len(prompts), 2)
                self.assertFalse(any("文字" in p for p in prompts))           # 图里没有文字, 不问文字
                self.assertLess(len(png), 20000)
        self.assertEqual(va.sample_summary()["count"], len(first))

    def test_pixels_match_prompts(self):
        """提示词问到的内容图里确实有: 抽查关键位置的颜色。"""
        imgs = {label: png for _, label, png, _ in va.sample_images()}

        def at(label, x, y):
            w, _, _, px = cdp.decode_png(imgs[label])
            return tuple(px[(y * w + x) * 3:(y * w + x) * 3 + 3])
        self.assertEqual([at("几何图形", 112, 224), at("几何图形", 266, 224), at("几何图形", 388, 250)],
                         [va.RED, va.BLUE, va.GREEN])
        self.assertEqual(at("几何图形", 5, 5), (255, 255, 255))
        # 柱状图: 只有第 4 根(紫色)高到 y=60, 第 1 根(蓝色)是最矮的
        self.assertEqual(at("柱状图", 316, 60), va.PURPLE)
        self.assertNotIn(at("柱状图", 100, 60), va.BAR_COLORS)
        self.assertEqual(at("柱状图", 100, 300), va.BLUE)
        self.assertEqual(va.BAR_VALUES.index(max(va.BAR_VALUES)), 3)
        self.assertEqual([at("色块拼图", 80, 80), at("色块拼图", 224, 224), at("色块拼图", 368, 368), at("色块拼图", 224, 80)],
                         [va.RED, va.RED, va.RED, va.BLUE])
        self.assertEqual([at("饼图", 324, 224), at("饼图", 150, 300), at("饼图", 117, 170), at("饼图", 187, 110)],
                         [va.BLUE, va.ORANGE, va.GREEN, va.GRAY])
        self.assertTrue(all(at("数一数", x, y) == va.BLUE for x, y in va.COUNT_CIRCLES))
        self.assertTrue(all(at("数一数", x, y) == va.RED for x, y in va.COUNT_SQUARES))
        self.assertEqual((len(va.COUNT_CIRCLES), len(va.COUNT_SQUARES)), (5, 3))

    def test_vision_body_pairs_prompt_with_image(self):
        samples = va.sample_images()
        urls = [va.data_url(png) for _, _, png, _ in samples]
        prompts = [p for _, _, _, p in samples]
        for seed in range(20):
            body = bench._scn_vision_body("m", random.Random(seed), 256, "s%d" % seed, urls, 1, prompts)
            text, img = body["messages"][0]["content"]
            k = urls.index(img["image_url"]["url"])
            self.assertIn(text["text"].split("] ", 1)[1], prompts[k])       # 问的正是这张图里的东西
        body = bench._scn_vision_body("m", random.Random(1), 256, "s", urls, 2, prompts)
        self.assertIn(body["messages"][0]["content"][0]["text"].split("] ", 1)[1], va.SAMPLE_MULTI_PROMPTS)
        body = bench._scn_vision_body("m", random.Random(1), 256, "s", urls, 1)  # 上传的图: 通用提示词
        self.assertIn(body["messages"][0]["content"][0]["text"].split("] ", 1)[1], bench.VISION_PROMPTS)


class TestTaskCheck(unittest.TestCase):
    def test_template_lines_accepted(self):
        tpl = app_template()
        self.assertGreaterEqual(len(tpl), 6)
        for i, obj in enumerate(tpl, 1):
            with self.subTest(line=i):
                c = bench.check_task_line(json.dumps(obj, ensure_ascii=False))
                self.assertEqual((c["status"], c["reason"], c["warns"]), ("ok", "", []))
        text = "\n".join(json.dumps(x, ensure_ascii=False) for x in tpl) + "\n"
        rep = bench.check_task_text(text)
        self.assertEqual((rep["total"], rep["valid"], rep["problems"], rep["warnings"]), (len(tpl), len(tpl), [], []))
        self.assertGreaterEqual(rep["json"], 2)
        self.assertGreaterEqual(rep["image"], 1)
        p = os.path.join(temp_dir(), "tpl.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        pool = bench.ReplayPool(p)                                           # 测试时实际读取也全部接受
        self.assertEqual((len(pool), pool.skipped, pool.bad), (len(tpl), 0, 0))
        # 带图那一行问「有哪些形状、什么颜色」: 示例图左边红色圆形、右边蓝色正方形
        url = next(part["image_url"]["url"] for x in tpl for m in x["messages"] if isinstance(m["content"], list)
                   for part in m["content"] if part["type"] == "image_url")
        png = base64.b64decode(url.split(",", 1)[1])
        w, h, _, px = cdp.decode_png(png)
        self.assertEqual((w, h), (224, 224))
        self.assertEqual([tuple(px[(y * w + x) * 3:(y * w + x) * 3 + 3]) for x, y in ((72, 112), (164, 112))],
                         [va.RED, va.BLUE])

    def test_bad_lines_have_numbers_and_reasons(self):
        img = "data:image/png;base64," + base64.b64encode(TINY_PNG).decode()
        lines = [
            '{"messages":[{"role":"user","content":"ok"}],"params":{"response_format":{"type":"json_object"}}}',  # 1 可用 + JSON
            "",                                                                                                  # 2 空行
            '{"messages":[{"role":"user","content":"x"},]}',                                                    # 3 多余逗号
            '["不是对象"]',                                                                                       # 4
            '{"messages":[{"role":"usr","content":"x"}]}',                                                      # 5 role 写错
            json.dumps({"messages": [{"role": "user", "content": [{"type": "text", "text": "看图"},
                                                                  {"type": "image_url", "image_url": {"url": img}}]}]}),  # 6 1×1
            '{"messages":[{"role":"user","content":"x"}],"params":{"response_format":{"type":"json_schema"}}}',  # 7
            '{"messages":[{"role":"user","content":"x"}],"params":{"max_tokens":"abc"}}',                       # 8 可用, 提醒
            '{"no":"messages"}',                                                                                 # 9 跳过
            '{"messages":[{"role":"user","content":"x"}],"params":{"temperature":-1}}',                         # 10
            '{"messages":[{"role":"user","content":"x"}],"meta":{"prompt_tokens":99999}}',                      # 11 超长跳过
        ]
        rep = bench.check_task_text("\ufeff" + "\r\n".join(lines))
        self.assertEqual((rep["total"], rep["valid"], rep["bad"], rep["skipped"], rep["json"]), (10, 2, 6, 2, 1))
        got = {p["line"]: p["reason"] for p in rep["problems"]}
        self.assertEqual(sorted(got), [3, 4, 5, 6, 7, 9, 10, 11])
        self.assertIn("不是合法的 JSON", got[3])
        self.assertIn("逗号", got[3])
        self.assertIn("JSON 对象", got[4])
        self.assertIn("usr", got[5])
        self.assertIn("1×1", got[6])
        self.assertIn("json_schema", got[7])
        self.assertIn("messages", got[9])
        self.assertIn("temperature", got[10])
        self.assertIn("60000", got[11])
        self.assertEqual([(w["line"], "max_tokens" in w["reason"]) for w in rep["warnings"]], [(8, True)])
        many = "\n".join("坏行 %d" % i for i in range(25))                  # 只列前 10 条
        rep = bench.check_task_text(many)
        self.assertEqual((rep["total"], rep["bad"], len(rep["problems"])), (25, 25, 10))
        arr = json.dumps([{"messages": [{"role": "user", "content": "a"}]}] * 2, indent=2)
        self.assertIn("JSON 数组", bench.check_task_text(arr)["hint"])     # 常见错误: 整份是 JSON 数组

    def test_replay_pool_uses_same_rules(self):
        p = os.path.join(temp_dir(), "t.jsonl")
        img = "data:image/png;base64," + base64.b64encode(TINY_PNG).decode()
        with open(p, "w", encoding="utf-8-sig") as f:                        # 带 BOM 也能读
            f.write('{"messages":[{"role":"user","content":"ok"}]}\n')
            f.write('{"messages":[{"role":"usr","content":"x"}]}\n')
            f.write(json.dumps({"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": img}}]}]}) + "\n")
            f.write('{"no":"messages"}\n[1, 2]\n')
        pool = bench.ReplayPool(p)
        self.assertEqual((len(pool), pool.bad, pool.skipped), (1, 3, 1))
        with open(p, encoding="utf-8-sig") as f:
            rep = bench.check_task_text(f.read())
        self.assertEqual((rep["valid"], rep["bad"], rep["skipped"]), (1, 3, 1))  # 上传检查与实际发送一致


class TestHttpErrorReason(unittest.TestCase):
    def setUp(self):
        bench._NO_IGNORE_EOS.clear()
        bench._REQ_EXTRA = {}
        bench._CANCEL = None

    def test_scenario_400_keeps_server_reason(self):
        key = "sk-test-SECRET-1234567890"

        def h(method, path, body):
            return 400, {"error": {"message": "Image size too small\n(received key %s)" % key,
                                   "type": "BadRequestError", "code": 400}}, None
        m = MockServer(h)
        try:
            ph = bench.phase_scenario(m.url + "/v1/chat/completions", {"Authorization": "Bearer " + key}, "m", "vision",
                                      {"conc": [2], "requests_per_worker": 1, "max_attempts": 1, "retry_pause_s": 0})
        finally:
            m.close()
        self.assertEqual(ph["task"]["image_source"], "builtin")
        pt = ph["points"][0]
        self.assertEqual((pt["ok"], pt["fail"]), (0, 2))
        err = pt["errors"][0]
        self.assertTrue(err.startswith('HTTP 400: {"error": {"message": "Image size too small'), err)
        self.assertNotIn("\n", err)
        self.assertNotIn("SECRET", err)                                      # 回显的 API Key 被隐去
        self.assertLessEqual(len(err), bench.ERR_MAX)
        url = m.calls[0][2]["messages"][0]["content"][1]["image_url"]["url"]  # 默认发的是内置示例图片
        self.assertEqual(va.check_image(base64.b64decode(url.split(",", 1)[1]))["level"], "ok")

    def test_stream_call_error_text(self):
        def h(method, path, body):
            if path.startswith("/html"):
                return 502, b"<html>\n<head><title>502</title><style>p{}</style></head>\r\n<body><h1>Bad Gateway</h1></body></html>", "text/html"
            if path.startswith("/empty"):
                return 400, b"", "text/plain"
            return 422, {"detail": "x" * 1000}, None
        m = MockServer(h)
        try:
            with self.assertRaises(urllib.error.HTTPError) as cm:                # 仍是 HTTPError, 原有处理不变
                bench.stream_call(m.url + "/html", {"model": "m", "messages": []}, {})
            self.assertEqual(cm.exception.code, 502)
            self.assertEqual(str(cm.exception), "HTTP 502: 502 Bad Gateway")
            with self.assertRaises(bench.HTTPStatusError) as cm:
                bench.stream_call(m.url + "/empty", {"model": "m", "messages": []}, {})
            self.assertEqual(str(cm.exception), "HTTP 400: Bad Request")
            with self.assertRaises(bench.HTTPStatusError) as cm:
                bench.stream_call(m.url + "/long", {"model": "m", "messages": []}, {})
            self.assertEqual(len(cm.exception.detail), 300)                   # 原因截取前 300 字
        finally:
            m.close()


class TestScenarioUploadAPI(ServerCase):
    def setUp(self):
        self._saved = (server.SCN_TASKS_DIR, server.SCN_IMAGES_DIR)
        server.SCN_TASKS_DIR, server.SCN_IMAGES_DIR = temp_dir(), temp_dir()

    def tearDown(self):
        server.SCN_TASKS_DIR, server.SCN_IMAGES_DIR = self._saved

    def upload_images(self, files):
        return self.request("POST", "/api/scenario-upload", {"kind": "images", "files": [
            {"name": n, "data": base64.b64encode(d).decode()} for n, d in files]})

    def test_task_upload_reports_bad_lines(self):
        content = "\n".join(['{"messages":[{"role":"user","content":"a"}],"params":{"response_format":{"type":"json_object"}}}',
                             '{"messages":[{"role":"user","content":"b"}] ',
                             '{"messages":[{"role":"user","content":"c"}]}'])
        st, _, d = self.request("POST", "/api/scenario-upload", {"kind": "tasks", "name": "t.jsonl", "content": content})
        self.assertEqual((st, d["ok"], d["lines"], d["bad_lines"]), (200, True, 2, 1))
        self.assertEqual((d["check"]["json"], d["check"]["problems"][0]["line"]), (1, 2))
        st, _, lst = self.request("GET", "/api/scenario-list")
        self.assertEqual([(t["file_id"], t["lines"], t["total"]) for t in lst["tasks"]], [(d["file_id"], 2, 3)])
        st, _, d = self.request("POST", "/api/scenario-upload", {"kind": "tasks", "name": "bad.jsonl",
                                                                 "content": '{"messages": 1}\n{"messages":[{"role":"x","content":"a"}]}'})
        self.assertEqual((st, d["ok"], d["check"]["valid"]), (400, False, 0))
        self.assertIn("第 1 行", d["error"])
        self.assertEqual(len(os.listdir(server.SCN_TASKS_DIR)), 1)           # 一行都不能用的不保存

    def test_image_upload_checks_each_file(self):
        good = va.sample_images()[1][2]
        st, _, d = self.upload_images([("good.png", good), ("tiny.png", TINY_PNG), ("cut.png", good[:-20]),
                                       ("really-png.jpg", png_of(300, 300)), ("pic.bmp", good)])
        self.assertEqual((st, d["ok"], d["count"], d["rejected"]), (200, True, 2, 3))
        codes = {f["name"]: (f["ok"], f["code"] or f["level"]) for f in d["files"]}
        self.assertEqual(codes, {"good.png": (True, "ok"), "tiny.png": (False, "too_small"), "cut.png": (False, "broken"),
                                 "really-png.jpg": (True, "warn"), "pic.bmp": (False, "unsupported")})
        pack = os.path.join(server.SCN_IMAGES_DIR, d["image_id"])
        self.assertEqual(sorted(os.listdir(pack)), ["00.png", "01.png"])     # 扩展名写错的按真实格式保存
        st, _, lst = self.request("GET", "/api/scenario-list")
        item = lst["images"][0]
        self.assertEqual((item["count"], item["usable"], item["too_small"], item["dims"]), (2, 2, 0, "300×300 – 448×448"))
        self.assertEqual((lst["builtin_images"]["count"], lst["builtin_images"]["width"]), (len(va.SAMPLES), 448))
        st, _, d = self.upload_images([("tiny.png", TINY_PNG)])              # 全都不能用: 不建图片包
        self.assertEqual((st, d["ok"]), (400, False))
        self.assertIn("1×1", d["error"])
        self.assertEqual(len(os.listdir(server.SCN_IMAGES_DIR)), 1)

    def test_old_pack_with_tiny_image_is_flagged_and_refused(self):
        """用户以前的图片包只有一张 1×1 的图: 列表里标出太小, 开始测试前就拒绝(不再发 36 个注定失败的请求)。"""
        pack = os.path.join(server.SCN_IMAGES_DIR, "img-c414cd0e204d")
        os.makedirs(pack)
        with open(os.path.join(pack, "00.png"), "wb") as f:
            f.write(TINY_PNG)
        st, _, lst = self.request("GET", "/api/scenario-list")
        item = lst["images"][0]
        self.assertEqual((item["image_id"], item["count"], item["usable"], item["too_small"], item["dims"]),
                         ("img-c414cd0e204d", 1, 0, 1, "1×1"))
        self.assertIn("太小", item["problems"][0])
        with self.assertRaises(ValueError) as cm:
            server._parse_scenarios({"scenarios": {"tasks": ["vision"], "vision_src": {"image_id": "img-c414cd0e204d"}}})
        self.assertIn("没有能用的图片", str(cm.exception))
        self.assertIn("1×1", str(cm.exception))

    def test_list_caches_checks_but_sees_changed_files(self):
        """素材列表的检查结果按文件的大小和修改时间缓存: 没变时不重读; 文件被手动改过时重新检查。"""
        line = '{"messages":[{"role":"user","content":"a"}]}'
        st, _, d = self.request("POST", "/api/scenario-upload", {"kind": "tasks", "name": "t.jsonl", "content": line})
        path = os.path.join(server.SCN_TASKS_DIR, d["file_id"] + ".jsonl")
        pack = os.path.join(server.SCN_IMAGES_DIR, "img-0123456789ab")
        os.makedirs(pack)
        with open(os.path.join(pack, "00.png"), "wb") as f:
            f.write(TINY_PNG)
        lst = self.request("GET", "/api/scenario-list")[2]
        self.assertEqual((lst["tasks"][0]["lines"], lst["images"][0]["usable"]), (1, 0))
        hits = lambda: (server._task_file_check.cache_info().hits, server._image_pack_check.cache_info().hits)
        before = hits()
        self.request("GET", "/api/scenario-list")
        self.assertEqual(hits(), (before[0] + 1, before[1] + 1))                # 第二次直接用缓存
        with open(path, "a", encoding="utf-8") as f:                             # 手动改过: 大小和修改时间都变了
            f.write("\n" + line.replace('"a"', '"b"'))
        with open(os.path.join(pack, "01.png"), "wb") as f:
            f.write(png_of(300, 300))
        lst = self.request("GET", "/api/scenario-list")[2]
        self.assertEqual((lst["tasks"][0]["lines"], lst["images"][0]["count"], lst["images"][0]["usable"]), (2, 2, 1))

    def test_vision_source_defaults_to_builtin(self):
        for src in (None, {}, {"builtin": True, "dir": "/nope"}, {"image_id": "builtin"}):
            with self.subTest(src=src):
                scen = {"tasks": ["vision"]}
                if src is not None:
                    scen["vision_src"] = src
                cfg = server._parse_scenarios({"scenarios": scen})
                self.assertNotIn("vision_dir", cfg)                          # 不给 vision_dir = 内置示例图片
        d = temp_dir()
        with open(os.path.join(d, "a.png"), "wb") as f:
            f.write(png_of(300, 300))
        with open(os.path.join(d, "b.png"), "wb") as f:
            f.write(TINY_PNG)
        cfg = server._parse_scenarios({"scenarios": {"tasks": ["vision"], "vision_src": {"dir": d, "images": 2}}})
        self.assertEqual((cfg["vision_dir"], cfg["vision_images"]), (d, 2))
        with self.assertRaises(ValueError):
            server._parse_scenarios({"scenarios": {"tasks": ["vision"], "vision_src": {"dir": os.path.join(d, "nope")}}})
        skipped = []
        self.assertEqual(len(bench._load_vision_images(d, skipped)), 1)       # 运行时同样跳过太小的那张
        self.assertEqual(skipped[0]["code"], "too_small")


if __name__ == "__main__":
    unittest.main()
