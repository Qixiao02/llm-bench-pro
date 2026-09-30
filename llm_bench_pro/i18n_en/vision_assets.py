# -*- coding: utf-8 -*-
"""vision_assets.py 的英文词条: 中文原文 → English。规则见 CONTRIBUTING.md「服务端消息与翻译」。
带数量的 (tn) 词条写成 (单数, 复数); 占位符 {名字} 中英文必须一致; 字面的花括号写成 {{ }}; 英文里不能有汉字。
这里的文字是图片检查说明 (check_image 的 msg): 会显示在任务集 / 图片包上传的检查报告里, 有的也被别的模块接在文件名后面。
所以写成首字母大写的短语 (单独放在表格里、接在「文件名: 」后面都通顺)。
收下但提示的几条 (level=warn) 是各自独立的句子, 中文用「；」连接, 英文用句号连接 (词条 "图片检查|；"), 不写成 "…; The …"。"""
ENTRIES = {
    # ---- 文件头解析: 损坏 / 不完整 (ImageError 的说明, code=broken)
    "文件不完整（{fmt} 没有正常结束，可能下载或拷贝时被截断了）":
        "Incomplete file ({fmt} data does not end properly; it may have been truncated during download or copying)",
    "文件已损坏（PNG 数据校验不通过）": "Corrupted file (PNG checksum failed)",
    "文件已损坏（PNG 缺少文件头）": "Corrupted file (PNG header is missing)",
    "文件已损坏（PNG 里没有图像数据）": "Corrupted file (the PNG contains no image data)",
    "文件已损坏（JPEG 里读不出宽高）": "Corrupted file (cannot read the width and height from the JPEG)",
    "文件已损坏（WebP 里读不出宽高）": "Corrupted file (cannot read the width and height from the WebP)",
    # ---- 认不出 / 不支持 (code=empty / unsupported)
    "文件是空的": "The file is empty",
    "是 {kind} 格式，暂不支持，请转成 JPG 或 PNG 再用": "{kind} format is not supported yet; convert it to JPG or PNG first",
    "不是能识别的图片（只支持 JPG / PNG / WebP / GIF）": "Not a recognizable image (only JPG / PNG / WebP / GIF are supported)",
    # ---- 逐张检查: 不收的 (code=too_big / too_small / too_large)
    "有 {size}，超过单张 20 MB 的上限": "{size} exceeds the 20 MB limit per image",
    "只有 {w}×{h} 像素，太小，看图模型会直接拒绝（每边至少 {min_side} 像素）":
        "Only {w}×{h} pixels, too small; vision models will reject it (each side must be at least {min_side} pixels)",
    "尺寸 {w}×{h}，边长超过 {max_side} 像素，请缩小后再用":
        "Size {w}×{h} is too large (a side is longer than {max_side} pixels); downscale it first",
    # ---- 逐张检查: 收下但提示 (level=warn)
    "尺寸 {w}×{h} 偏小，可能影响回答效果（推荐 {rec}×{rec} 以上）":
        "Size {w}×{h} is on the small side and may affect answer quality (recommended: {rec}×{rec} or larger)",
    "扩展名是 {ext}，实际是 {actual} 图片，已按 {actual} 处理":
        "The extension is {ext}, but the file is actually a {actual} image; it was handled as {actual}",
    "图片检查|；": ". ",
}
