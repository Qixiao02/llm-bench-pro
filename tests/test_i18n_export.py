# -*- coding: utf-8 -*-
"""离线报告里的界面语言: 导出时带上语言偏好、翻译脚本内联进报告、在报告里切换语言有效 (只在这次打开有效, 不写浏览器)。

「在报告里切换语言」用 Node 跑: 把导出的 HTML 里内联的脚本 (i18n.js、各词典、app.js) 连同报告数据放进和 tests/js/harness.js
一样的 DOM 桩里, 走完 offlineInit, 再断言语言、侧栏文字和本地偏好。无 Node 这一项自动跳过。
"""
import json
import os
import re
import shutil
import subprocess
import unittest

from _util import ROOT
import server
import sinks
from test_server import ServerCase
from test_store import perf_doc

NODE = shutil.which("node")
JS_DIR = os.path.join(ROOT, "tests", "js")


def i18n_files():
    with open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8") as f:
        return re.findall(r'<script src="/static/(i18n(?:\.en\.[A-Za-z0-9_-]+)?\.js)"></script>', f.read())


class TestExportState(unittest.TestCase):
    def test_language_key_is_exported_and_only_zh_or_en_survives(self):
        self.assertIn("llm-bench-pro-lang", server.EXPORT_LS_KEYS)
        for lang in ("zh", "en"):
            st = server._export_state({"theme": "light", "ls": {"llm-bench-pro-lang": lang, "llm-bench-pro-iq-form": "x"}})
            self.assertEqual(st["ls"]["llm-bench-pro-lang"], lang)
            self.assertNotIn("llm-bench-pro-iq-form", st["ls"])                       # 表单里填过的东西照旧不带
        for bad in ("fr", "", "EN", None, 1, ["en"]):
            with self.subTest(bad=bad):
                st = server._export_state({"theme": "dark", "ls": {"llm-bench-pro-lang": bad}})
                self.assertNotIn("llm-bench-pro-lang", st["ls"])
        self.assertNotIn("llm-bench-pro-lang", server._export_state({"theme": "dark"})["ls"])
        self.assertNotIn("llm-bench-pro-lang", server._export_state(None)["ls"])


class TestExportLanguage(ServerCase):
    @classmethod
    def setUpClass(cls):
        super(TestExportLanguage, cls).setUpClass()
        cls.doc = perf_doc("run_20260105_000000_i18nx")
        sinks.SqliteSink().save(cls.doc)

    def export(self, lang="en", **extra):
        ls = {"llm-bench-pro-dt": "{}"}
        if lang is not None:
            ls["llm-bench-pro-lang"] = lang
        body = dict({"page": "dash", "id": self.doc["run_id"], "title": "速度测试 · m", "state": {"theme": "dark", "ls": ls}}, **extra)
        st, _h, raw = self.request("POST", "/api/export-html", body)
        self.assertEqual(st, 200)
        return raw

    def test_report_carries_the_language_preference(self):
        for lang in ("en", "zh"):
            html = self.export(lang)
            state = json.loads(re.search(rb"window\.LLMB_OFF_STATE=(\{.*?\})</script>", html).group(1).decode("utf-8"))
            self.assertEqual(state["ls"]["llm-bench-pro-lang"], lang)
        html = self.export(None)                                                     # 没有偏好: 报告里也没有, 打开时按浏览器语言选
        state = json.loads(re.search(rb"window\.LLMB_OFF_STATE=(\{.*?\})</script>", html).group(1).decode("utf-8"))
        self.assertNotIn("llm-bench-pro-lang", state["ls"])

    def test_report_inlines_every_i18n_script_in_page_order(self):
        html = self.export("en")
        self.assertNotIn(b'src="/static', html)
        self.assertEqual(html.count(b"<script"), html.count(b"</script>"))
        names = i18n_files()
        self.assertEqual(names[0], "i18n.js")
        self.assertGreaterEqual(len(names), 10)
        at = -1
        for name in names + ["app.js"]:
            with open(os.path.join(ROOT, "web", "static", name), encoding="utf-8") as f:
                text = f.read().replace("\r\n", "\n")
            # 每个文件里挑一行最长的 (不含 </script 和 <!-- : 内联时会被转义), 它在报告里出现的位置要按页面里的顺序递增
            lines = [ln for ln in text.split("\n") if "</script" not in ln and "<!--" not in ln]
            first = max(lines, key=len)
            pos = html.replace(b"\r\n", b"\n").find(first.encode("utf-8"), at + 1)
            self.assertGreater(pos, at, "报告里没有按页面里的顺序内联 %s" % name)
            at = pos
        self.assertIn(b"I18N.add(", html)                                            # 词典也在
        self.assertIn("Offline report".encode(), html)                               # 试点转换的英文词条

    @unittest.skipUnless(NODE, "node 不可用, 跳过在报告里切换语言的检查")
    def test_switching_language_inside_the_report(self):
        for lang in ("en", "zh"):
            with self.subTest(exported_language=lang):
                self.run_report_in_node(self.export(lang), lang)

    def run_report_in_node(self, html, lang):
        blocks = [b.decode("utf-8") for b in re.findall(rb"<script>([\s\S]*?)</script>", html)]
        state = next(b for b in blocks if b.startswith("window.LLMB_OFF_STATE="))[len("window.LLMB_OFF_STATE="):]
        offline = re.search(rb'<script type="application/json" id="llmb-offline">(.*?)</script>', html, re.S).group(1).decode("utf-8")
        i18n = [b for b in blocks if "const I18N=" in b or b.lstrip().startswith("/* 英文词条")]
        app = [b for b in blocks if "const UI_VERSION=" in b]
        self.assertEqual(len(app), 1)
        self.assertEqual(len(i18n), len(i18n_files()))
        now_text, then_text = ("离线报告", "Offline report") if lang == "zh" else ("Offline report", "离线报告")  # 侧栏连接状态: 现在的语言 / 切换之后的语言
        check = r'''
;(function () {
  const assert = require("node:assert");
  const conn = document.getElementById("connText");
  assert.equal(I18N.lang, %(lang)s, "报告里的语言偏好没有生效");
  assert.equal(document.documentElement.lang, %(lang)s === "en" ? "en" : "zh-CN");
  assert.ok(OFF, "应该是离线报告");
  assert.equal(conn.textContent, %(now)s);
  let writes = 0;
  globalThis.localStorage = { getItem() { return null; }, setItem() { writes++; }, removeItem() {} };
  const seen = [];
  I18N.onChange(l => seen.push(l));
  const other = %(lang)s === "en" ? "zh" : "en";
  setLang(other);                                                                      /* 在报告里切换语言 */
  assert.equal(I18N.lang, other);
  assert.equal(conn.textContent, %(then)s);
  assert.equal(document.documentElement.lang, other === "en" ? "en" : "zh-CN");
  assert.deepEqual(seen, [other]);
  assert.equal(writes, 0, "离线报告里的偏好只在这次打开有效, 不能写进看报告的人的浏览器");
  setLang(%(lang)s);
  assert.equal(conn.textContent, %(now)s);
  assert.equal(apiHeaders()["X-Lang"], %(lang)s);
  console.log("REPORT-LANG-OK");
})();
''' % {"lang": json.dumps(lang), "now": json.dumps(now_text), "then": json.dumps(then_text)}
        with open(os.path.join(JS_DIR, "harness.js"), encoding="utf-8") as f:
            harness = f.read()
        script = "\n;\n".join(['process.on("unhandledRejection", () => {});', harness,
                               "globalThis.LLMB_OFF_STATE=%s;globalThis.LLMB_OFFLINE=%s;" % (state, offline)] + i18n + app + [check])
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".js", prefix="llmbench-report-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(script)
            p = subprocess.run([NODE, path], capture_output=True, timeout=90)
        finally:
            os.unlink(path)
        out = p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace")
        self.assertEqual(p.returncode, 0, out[-3000:])
        self.assertIn("REPORT-LANG-OK", out)


if __name__ == "__main__":
    unittest.main()
