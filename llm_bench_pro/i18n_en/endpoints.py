# -*- coding: utf-8 -*-
"""endpoints.py 的英文词条: 中文原文 → English。规则见 CONTRIBUTING.md「服务端消息与翻译」。
带数量的 (tn) 词条写成 (单数, 复数); 占位符 {名字} 中英文必须一致; 字面的花括号写成 {{ }}; 英文里不能有汉字。"""
ENTRIES = {
    "服务地址要以 http:// 或 https:// 开头，中间不能有空格，比如 http://127.0.0.1:8000":
        "The service URL must start with http:// or https:// and contain no spaces, e.g. http://127.0.0.1:8000",
    "{field} 应为文字": "{field} must be a string",
    "服务地址不能为空": "The service URL cannot be empty",
    "服务地址最多 {limit} 个字（现在 {n} 个）": "The service URL can be at most {limit} characters (currently {n})",
    "模型名称不能为空": "The model name cannot be empty",
    "模型名称最多 {limit} 个字（现在 {n} 个）": "The model name can be at most {limit} characters (currently {n})",
    "名称最多 {limit} 个字（现在 {n} 个）": "The name can be at most {limit} characters (currently {n})",
    "API Key 最多 {limit} 个字": "The API key can be at most {limit} characters",
    "返回的不是模型列表（没有 data 数组）": "The response is not a model list (no data array)",
}
