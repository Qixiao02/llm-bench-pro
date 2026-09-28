# -*- coding: utf-8 -*-
"""LLM Bench Pro。python run.py 与 python -m llm_bench_pro.<模块> 都会先执行这里。"""
import sys

# 输出被重定向到文件或管道时, Windows 上 print 用系统代码页编码 (中文系统 GBK, 英文系统 cp1252),
# 日志里的 ⚠ ↻ 等符号 (英文系统上连中文) 编不了码, print 会直接抛错, 让正在跑的测试任务中断;
# 改为把编不了的字符换成 "?", 其余照常输出。Windows 默认的 surrogateescape 也会抛错, 一并处理
try:
    if sys.stdout is not None and sys.stdout.errors in ("strict", "surrogateescape"):
        sys.stdout.reconfigure(errors="replace")
except (AttributeError, ValueError):  # 被换成了不支持 reconfigure 的对象 (如 StringIO)
    pass
