# -*- coding: utf-8 -*-
"""离线报告: 用系统里同一套页面(index.html + app.css + app.js + ECharts)和这次测试的数据合成一个 HTML 文件。
双击就能打开, 看到的和系统里一模一样; 只读(不能新建测试、删除、重新检查), 数据是导出那一刻的样子。

数据放在 <script type="application/json" id="llmb-offline"> 里, 页面脚本发现 window.LLMB_OFFLINE 后
从这里取「接口」数据, 不再连后端(见 app.js 的 offlineApi)。"""
import html as _html
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")

# index.html 里要换成内联内容的位置; 结构变了就明确报错, 不生成半截报告
M_TITLE = "<title>LLM Bench Pro</title>"
M_CHARSET = '<meta charset="UTF-8">'
M_CSS = '<link rel="stylesheet" href="/static/app.css">'
M_ECHARTS = '<script src="/static/vendor/echarts.min.js"></script>'
M_APP = '<script src="/static/app.js"></script>'


def _read(*parts):
    with open(os.path.join(WEB, *parts), encoding="utf-8") as f:
        return f.read()


def json_for_script(obj):
    """放进 <script> 的 JSON: 去掉所有 "<", 页面解析器不会提前结束脚本或进入注释状态。"""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def script_safe(js):
    """内联脚本里不能出现 </script 和 <!-- ; 两种写法在字符串、模板字符串、正则里含义不变。"""
    return js.replace("</script", "<\\/script").replace("<!--", "<\\x21--")


def compose(page, bundle, head_state, title):
    """bundle: 页面数据(api / files / sel / ui ...); head_state: 首帧前要用的主题和本地偏好。返回完整 HTML 文本。"""
    idx = _read("index.html")
    parts = {
        M_TITLE: "<title>%s</title>" % _html.escape(title or "LLM Bench Pro 离线报告"),
        M_CHARSET: '%s\n<meta name="generator" content="LLM Bench Pro 离线报告">\n<script>window.LLMB_OFF_STATE=%s</script>'
                   % (M_CHARSET, json_for_script(head_state)),
        M_CSS: "<style>\n%s\n</style>" % _read("static", "app.css").replace("</style", "<\\/style"),
        M_ECHARTS: '<script type="application/json" id="llmb-offline">%s</script>\n'
                   '<script>window.LLMB_OFFLINE=JSON.parse(document.getElementById("llmb-offline").textContent)</script>\n'
                   "<script>%s</script>" % (json_for_script(dict(bundle, page=page)),
                                            script_safe(_read("static", "vendor", "echarts.min.js"))),
        M_APP: "<script>%s</script>" % script_safe(_read("static", "app.js")),
    }
    # 按原文位置切开再拼接: 插进去的内容里即使出现别的标记也不会被二次替换
    spots = []
    for mark in parts:
        n = idx.count(mark)
        if n != 1:
            raise RuntimeError("web/index.html 结构变了, 找到 %d 处 %s" % (n, mark))
        spots.append((idx.index(mark), mark))
    out, pos = [], 0
    for at, mark in sorted(spots):
        out.append(idx[pos:at])
        out.append(parts[mark])
        pos = at + len(mark)
    out.append(idx[pos:])
    return "".join(out)
