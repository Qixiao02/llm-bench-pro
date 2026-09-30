# -*- coding: utf-8 -*-
"""tasksets.py 的英文词条: 中文原文 → English。规则见 CONTRIBUTING.md「服务端消息与翻译」。
带数量的 (tn) 词条写成 (单数, 复数); 占位符 {名字} 中英文必须一致; 字面的花括号写成 {{ }}; 英文里不能有汉字。"""
ENTRIES = {
    # ---- 任务集名称 (clean_name)
    "名称不能为空": "The name cannot be empty",
    "名称最多 {max} 个字（现在 {n} 个）": "The name can be at most {max} characters (currently {n})",
    # ---- 逐行查看: 图片概况 (image_info) 和取图片 (image_bytes)
    "缺少图片地址": "The image URL is missing",
    "不是 base64 格式的 data URL": "Not a base64 data URL",
    "base64 数据已损坏": "The base64 data is corrupted",
    "地址应为 data:image/…;base64,… 或 http(s) 网址": "The URL must be data:image/…;base64,… or an http(s) URL",
    "这一行不是合法的 JSON": "This line is not valid JSON",
    "这一行没有第 {no} 张图（一共 {n} 张）": (
        "This line has no image {no} (it has {n} image in total)",
        "This line has no image {no} (it has {n} images in total)"),
    "这张图没有地址": "This image has no URL",
    "这张图是网址形式，只显示网址，不在这里下载": "This image is a URL; only the URL is shown and it is not downloaded here",
    # ---- 逐行查看: params / meta 太长时的占位说明 (_small) 和「看原始 JSON」里被省略的图片数据 (pretty)
    "（{type}，太长没有显示）": "({type}, too long to display)",
    "{head}…（共 {n} 个字符，这里省略）": "{head}… ({n} characters in total, omitted here)",
}
