# -*- coding: utf-8 -*-
"""好几个模块都用到的英文词条: 中文原文 → English。规则见 CONTRIBUTING.md「服务端消息与翻译」。
同一句中文只要在两个以上的模块里用到, 就放在这里 (别的词典文件里不能再有同一个键)。
带数量的 (tn) 词条写成 (单数, 复数); 占位符 {名字} 中英文必须一致; 字面的花括号写成 {{ }}; 英文里不能有汉字。"""
ENTRIES = {
    # i18n.py 的 --lang 说明 (所有命令行入口共用)
    "界面和日志的语言：zh 中文，en 英文（默认按环境变量 LLM_BENCH_LANG，再按系统语言）":
        "Language of the interface and logs: zh = Chinese, en = English (default: the LLM_BENCH_LANG environment "
        "variable, then the system language)",
    # bench.py / gen.py / iq.py: 用户点了停止
    "用户取消": "Cancelled by user",
    # endpoints.py / server.py
    "API Key 中间不能有换行或其他控制字符": "The API key cannot contain line breaks or other control characters",
    # export_html.py / server.py
    "LLM Bench Pro 离线报告": "LLM Bench Pro offline report",
    # 列表里几项之间的分隔 (中文用全角分号, 英文用分号加空格): t("；").join(...)
    "；": "; ",
    # geneval.py (i18n-py-geneval): 列表里几项之间的分隔 (中文用全角逗号 / 顿号, 英文都是逗号加空格): t("，").join(...) / t("、").join(...)
    "，": ", ",
    "、": ", ",
}
