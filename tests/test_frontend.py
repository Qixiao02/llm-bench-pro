# -*- coding: utf-8 -*-
"""前端 app.js 的自动化单测: 无 Node 则整组跳过, 不破坏"零第三方依赖"承诺。

两个层次:
1. test_syntax  — node --check 语法门: 1900+ 行经典脚本的拼写错误在 CI 阶段就拦下;
2. test_logic   — 拼接 harness(DOM 桩) + app.js 全文 + checks(断言) 成一个脚本交 Node 执行,
                  覆盖纯逻辑层: esc/fmt 家族/niceMax/median/时间函数/withAlpha/areaFill 淡色守卫/名词解释/归因规则。
   ECharts 渲染与交互仍以浏览器验证为准(README 有说明), 这里守住的是逻辑与回归锚点。
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "js")


def i18n_scripts():
    """index.html 里加载的翻译脚本 (i18n.js 和各区域的英文词典), 按页面里的顺序; app.js 之前拼进测试脚本。"""
    with open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8") as f:
        names = re.findall(r'<script src="/static/(i18n(?:\.en\.[A-Za-z0-9_-]+)?\.js)"></script>', f.read())
    return [os.path.join(ROOT, "web", "static", n) for n in names]


def _run(cmd, timeout=90):
    p = subprocess.run(cmd, capture_output=True, timeout=timeout, env=dict(os.environ, LLMB_ROOT=ROOT))   # checks.js 要读 web/index.html
    return p.returncode, (p.stdout or b"").decode("utf-8", "replace"), (p.stderr or b"").decode("utf-8", "replace")


class TestFrontendJS(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if not cls.node:
            raise unittest.SkipTest("node 不可用, 跳过前端 JS 单测 (安装 Node.js 后自动启用)")

    def test_syntax(self):
        for path in [os.path.join(ROOT, "web", "static", "app.js")] + i18n_scripts():
            rc, _, err = _run([self.node, "--check", path])
            self.assertEqual(rc, 0, "%s 语法错误:\n%s" % (os.path.basename(path), err))

    def test_logic(self):
        parts = []
        for path in ([os.path.join(JS_DIR, "harness.js")] + i18n_scripts() +
                     [os.path.join(ROOT, "web", "static", "app.js"), os.path.join(JS_DIR, "checks.js")]):
            with open(path, encoding="utf-8") as f:
                parts.append(f.read())
        fd, path = tempfile.mkstemp(suffix=".js", prefix="llmbench-frontend-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write("\n;\n".join(parts))
            rc, out, err = _run([self.node, path])
        finally:
            os.unlink(path)
        self.assertEqual(rc, 0, "前端逻辑断言失败:\n" + (out + err))
        self.assertIn("FRONTEND-OK", out)
        self.assertRegex(out, r"FRONTEND-OK (\d+)$")   # 至少跑完了全部用例


if __name__ == "__main__":
    unittest.main()
