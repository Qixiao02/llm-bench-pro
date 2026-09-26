#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM Bench Pro 启动入口: python run.py [端口]  (默认 18080)"""
import sys

sys.dont_write_bytecode = True  # 不在项目目录里生成 __pycache__

from llm_bench_pro.server import main  # noqa: E402

if __name__ == "__main__":
    main()
