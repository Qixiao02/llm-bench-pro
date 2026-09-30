# 英文模式验收

翻完一个区域（或改了界面文字）之后，在**英文模式**下把页面过一遍，确认：

1. 可见文字里没有漏翻的中文（数据内容——模型名、题库名、作品名等——除外，见「数据内容」）；
2. 中文模式下界面一个字都没变；
3. 在页面上点语言按钮切换后，页面确实重画成了新语言（和「直接用这个语言打开」看到的一样）。

静态检查（`python tests/i18n_lint.py --report`）只管代码里写死的字符串；运行时才拼出来的文字、数据里的中文名、服务端返回的提示要靠这一步。

## 1. 准备

- 用**数据库副本**和**自己的端口**启动开发服务，不要用真实数据库和正在用的端口：

  ```bash
  cp data/llm_bench.db /tmp/dev-i18n.db                    # 副本 (PowerShell: Copy-Item)
  LLM_BENCH_DB=/tmp/dev-i18n.db python run.py 18100        # PowerShell: $env:LLM_BENCH_DB='...'; python run.py 18100
  ```
- 改前端文件不用重启（静态文件每次请求都重新读）；改了 Python 要重启。
- 不要连真实的模型服务；要看「进行中」的日志，用本地的模拟服务。

## 2. 切到英文

三选一：点侧栏底部的语言按钮（显示 `中` / `EN`）；页面「更多」菜单里的「语言 / Language」；或在浏览器控制台运行 `setLang("en")`。想从头用英文打开：先在控制台运行 `localStorage.setItem("llm-bench-pro-lang", "en")` 再刷新（没有本地偏好时按浏览器语言选：`zh` 开头用中文，否则英文）。

## 3. 要过一遍的页面和状态

- 速度测试、速度对比、能力测试、代码生成：**图表视图和表格视图**都要看；选了对比对象 B 的样子、只有一个测试的样子、没有任何测试的空状态、加载失败的样子；
- 能力测试：逐题查看（筛选、搜索、展开）、加入对比；代码生成：作品卡、检查详情、生成过程、人工评分；
- 任务集：列表、详情（概况、逐行）、导入后的检查报告、导入失败、删除确认；
- 模型管理：列表、详情、添加 / 编辑弹窗、测试连接的各种结果（成功、超时、401、404……）、删除确认；
- 名词解释（弹窗）、三个新建面板（抽屉）和它们底部的摘要、每个页面的「更多」菜单；
- 各种 toast、确认弹窗、运行日志（开始 / 停止 / 完成 / 失败）、页头「测试进行中」；
- **手机宽度 390**（底部标签栏、页头）和**离线报告**（导出后用浏览器打开）。

## 4. 列出还含汉字的文字

在每个状态下，把下面的脚本粘进浏览器控制台运行；它列出所有**可见**的、还含汉字（含中文标点）的文本节点和属性（`title` / `placeholder` / `aria-label` / `alt`，`<option>` 文字不管是否展开都列），并列出运行时记下的缺词：

```js
(() => {
  const CJK = /[\u3400-\u4dbf\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]/;
  const found = new Map();
  const vis = el => { try { return el.checkVisibility({checkVisibilityCSS: true}); } catch (e) { return el.getClientRects().length > 0; } };
  const where = el => { const p = []; for (let n = el, i = 0; n && n !== document.body && i < 4; n = n.parentElement, i++) { p.unshift(n.tagName.toLowerCase() + (n.id ? "#" + n.id : "")); if (n.id) break; } return p.join(" > "); };
  const add = (kind, text, el) => { const k = kind + " | " + text; if (!found.has(k)) found.set(k, where(el)); };
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
  for (let n; (n = w.nextNode());) {
    if (n.nodeType === 1) {
      if (["SCRIPT", "STYLE", "SVG"].includes(n.tagName.toUpperCase()) || n.closest("svg") || (n.tagName !== "OPTION" && !vis(n))) continue;
      for (const a of ["title", "placeholder", "aria-label", "alt"]) { const v = n.getAttribute(a); if (v && CJK.test(v)) add(a, v.trim(), n); }
    } else if (CJK.test(n.nodeValue) && n.parentElement && !n.parentElement.closest("script,style,svg") && (n.parentElement.tagName === "OPTION" || vis(n.parentElement))) {
      add("text", n.nodeValue.trim(), n.parentElement);
    }
  }
  console.table([...found].map(([k, v]) => ({文字: k, 位置: v})));
  console.log("I18N.missing (t / tn 查不到英文词条):", I18N.missing);
  console.log("I18N.missingServer (tm 没有匹配的服务端提示):", I18N.missingServer);
  console.log("I18N.missingData (td 查不到的数据名):", I18N.missingData);
})();
```

图表里的文字（坐标轴名、图例、系列名、浮层）不在 DOM 里，脚本看不到：ECharts 的配置在 `CHARTS`（`Map`，键是图表容器的 id），可以用 `JSON.stringify([...CHARTS.values()].map(c => c.getOption())).match(/"[^"]*[\u4e00-\u9fff][^"]*"/g)` 列出配置里的中文，再把鼠标放到图上看浮层。

## 5. 数据内容

数据里的中文（模型名、任务集名、题库和科目名、作品名、场景名等）不是界面文字，脚本会把它们列出来，人工判断：

- 用户自己起的名字（模型名、任务集名、标签）：不翻译；
- 程序内置的数据名（题库科目、代码生成的题目和检查项、场景名、指标名）：用 `td()` 翻译，英文写进对应区域词典的 `I18N.add("enData", {…})`；
- 服务端返回的提示：用 `tm()` 翻译，正则模式写进 `i18n.en.server.js`。

## 6. 切换后有没有重画

- 在中文页面点语言按钮切到英文，再和「直接用英文打开」同一个页面比：看得见的文字应该完全一样。不一样的地方，就是「只生成一次就存进 DOM」的文字，要用 `I18N.onChange(…)` 登记重画；
- 打开着的「更多」菜单、抽屉、名词解释在切换后也要是新语言（弹窗、toast 是一次性的，不要求重画）；
- 切回中文后，界面应该和改动前一模一样。

## 7. 收尾

- `python tests/i18n_lint.py --report --area 区域名` 显示 0 个违规后，运行 `python tests/i18n_lint.py --update-baseline` 把这个区域的基线降成 0；
- `python tests/i18n_lint.py --missing` 没有输出；
- `python -m unittest discover -s tests` 全部通过；
- 浏览器控制台没有报错、页面没有横向溢出（1440 / 1024 / 390 三种宽度各看一遍）。
