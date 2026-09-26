# -*- coding: utf-8 -*-
"""自研行覆盖率统计 (纯标准库, 不引入 coverage.py):
    python tests/run_coverage.py

原理:
- 分子: sys.settrace 采集主线程 + 包装 threading.Thread.run 采集子线程的已执行行;
- 分母: ast 遍历每个模块的可执行语句行 (排除空行/注释/docstring/pass);
- 只统计 llm_bench_pro/*.py, 结果按覆盖率升序输出并写入 coverage.txt。

注意: settrace 有 2-3 倍减速, 且不与 unittest discover 混跑 (名字不以 test 开头即不会被收集)。
"""
import ast
import os
import sys
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "llm_bench_pro")
if PKG not in sys.path:
    sys.path.insert(0, PKG)

TARGETS = [os.path.join(PKG, n) for n in sorted(os.listdir(PKG)) if n.endswith(".py")]
WATCH = {os.path.normcase(p): p for p in TARGETS}
HITS = {p: set() for p in TARGETS}


def _tracer(frame, event, arg):
    fn = os.path.normcase(frame.f_code.co_filename)
    if event == "call":
        return _tracer if fn in WATCH else None
    if event == "line" and fn in WATCH:
        HITS[WATCH[fn]].add(frame.f_lineno)
    return _tracer


_orig_thread_run = threading.Thread.run


def _traced_run(self):  # 子线程(压测 worker/MockServer)也要计入
    sys.settrace(_tracer)
    try:
        _orig_thread_run(self)
    finally:
        sys.settrace(None)


def _executable_lines(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    lines = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and not isinstance(node, ast.Pass):
            lines.add(node.lineno)
    for node in ast.walk(tree):  # 剔除 docstring
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            b = node.body
            if (b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant)
                    and isinstance(b[0].value.value, str)):
                lines.discard(b[0].lineno)
    return lines


def main():
    threading.Thread.run = _traced_run
    os.chdir(HERE)  # 与 python -m unittest discover -s tests 同一工作目录约定
    loader = unittest.TestLoader()
    suite = loader.discover(HERE, pattern="test*.py")
    sys.settrace(_tracer)
    try:
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    finally:
        sys.settrace(None)
        threading.Thread.run = _orig_thread_run

    rows, total_s, total_h = [], 0, 0
    for p in TARGETS:
        denom = _executable_lines(p)
        hit = len(HITS[p] & denom)
        rows.append((os.path.relpath(p, ROOT), len(denom), hit))
        total_s += len(denom)
        total_h += hit
    rows.sort(key=lambda r: (r[2] / r[1] if r[1] else 1.0, r[0]))  # 最差的排前面

    W = max(len(r[0]) for r in rows) + 2
    out = ["%-*s %6s %6s %7s" % (W, "模块", "语句", "覆盖", "%"), "-" * (W + 24)]
    for name, d, h in rows:
        out.append("%-*s %6d %6d %6.1f%%" % (W, name, d, h, (h * 100.0 / d) if d else 100.0))
    out.append("-" * (W + 24))
    out.append("%-*s %6d %6d %6.1f%%" % (W, "整体", total_s, total_h, total_h * 100.0 / total_s))
    text = "\n".join(out)
    print("\n" + text)
    with open(os.path.join(ROOT, "coverage.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text + "\n")
    print("\n已写入 coverage.txt; 测试结果: %s" % ("OK" if result.wasSuccessful() else "FAILED"))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
