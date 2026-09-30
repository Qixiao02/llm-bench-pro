# 参与贡献

感谢你愿意改进 LLM Bench Pro！提 Issue 和 Pull Request 都欢迎。

## 提 Issue

- **问题反馈**：写清楚怎么复现（点了哪里、填了什么）、看到了什么、期望是什么；附上运行日志（新建面板里的「复制日志」）和浏览器控制台的报错。
- **功能建议**：说明使用场景，为什么现有功能不够用。
- 请不要在 Issue 里贴 API Key、内网地址或不能公开的测试结果。

## 提交 Pull Request

`main` 分支受保护：**不能直接推送，所有改动都要通过 Pull Request 合并**，并且需要：

1. 维护者（[@Qixiao02](https://github.com/Qixiao02)）审核通过；
2. 自动测试（GitHub Actions）全部通过；
3. PR 里的讨论都已解决。

流程：

```bash
# 1. 在 GitHub 上 Fork 本仓库, 然后克隆你自己的 Fork
git clone https://github.com/<你的用户名>/llm-bench-pro.git
cd llm-bench-pro

# 2. 从 main 新建一个分支
git checkout -b fix/xxx          # 或 feat/xxx、docs/xxx

# 3. 修改、跑测试、提交
python -m unittest discover -s tests
git commit -m "fix(iq): 修正 xxx"

# 4. 推到你的 Fork, 在 GitHub 上向本仓库的 main 发起 Pull Request
git push origin fix/xxx
```

提交信息建议写成 `类型(范围): 说明`，类型用 `feat`（新功能）、`fix`（修问题）、`docs`（文档）、`refactor`、`test`、`chore`；范围如 `perf`、`iq`、`gen`、`ui`、`server`、`bank`。

## 开发环境

- Python 3.8+，**只用标准库，不要引入第三方依赖**；
- Node.js（可选）：装了才会跑前端逻辑测试 `tests/test_frontend.py`；
- 启动：`python run.py 18080`，浏览器打开 <http://127.0.0.1:18080>；
- 测试：`python -m unittest discover -s tests`（测试都用临时数据库和本地模拟服务，不会碰 `data/`，也不联网）。

## 代码约定

- **离线可用**：页面、图表库、字体都在本地，不要加 CDN 或其他外网资源；新增的页面接口要在离线报告里（`app.js` 的 `offlineApi`）有对应处理，否则导出的报告会缺数据。
- **界面默认用大白话，可以一键切成专业词**：默认显示大白话（专业说法在悬停提示和「名词解释」里）；侧栏底部的按钮和各页「更多」菜单里的「切换术语：大白话 / 专业」可以把标签换成 Prefill、TTFT、P95 这样的专业写法。所以新增的名词（指标名、表头、图表标题、坐标轴、图例、结论句里的词）要走统一函数：先在 `app.js` 的 `TERMS` 里加一条（大白话 `name`、专业写法 `pro`、完整说法 `tech`、解释 `desc`），页面上用 `term(key)`，或在文字里写 `{key}` 再交给 `termHtml(...)`（HTML）/ `termText(...)`（图表、CSV、title 等纯文本），不要在调用处手写大白话或专业词。对比统一写成「A 比 B」（A 是正在看的测试，B 是拿来比的）。
- **图表**：统一用 ECharts，不画双纵轴；每张图都能切换成表格查看。
- **界面文字要能翻译**：界面有中文 / English 两种语言，新增的界面文字用 `t()` / `tn()` 等写，并同时在对应区域的词典里加英文（写法、词典文件和检查工具见下面的「界面文字与翻译」）。
- 界面改动请附亮色和暗色的截图，并在 1440 / 1024 / 390 三种宽度下看一遍。
- 不要提交 `data/` 下的任何内容（数据库、测试结果、作品、下载的题集数据）、API Key 和内网地址。

## 界面文字与翻译

界面有 **中文 / English** 两种语言：左侧栏底部的语言按钮（显示当前语言的缩写，点一下切换），或每个页面「更多」菜单里的「语言 / Language」；离线报告里也能切换（只在这次打开有效）。选过的语言记在本机。**翻译全部完成之前，这个功能对用户是关着的**：`I18N.AUTO_DETECT` 是 `false`（不按浏览器语言自动选，一律中文），`I18N.READY` 是 `false`（语言按钮默认隐藏，已经在英文模式时照常显示，好切回来）；要试英文，网址后面加 `?lang=en`（会记住），`?lang=zh` 切回中文。全部翻完后把这两个开关一起改成 `true`（打开后 `zh` 开头的浏览器语言用中文，其余用英文），`index.html` 页头脚本里的自动识别写法也要一起改，测试会检查两处一致。

**做法：以中文原文为键（gettext 风格）。中文原文继续写在代码里，英文放在词典里。** 中文模式下 `t()` 原样返回原文，所以中文界面不会因为翻译框架而变样。

### 怎么写

| 写法 | 用在哪 | 例子 |
|---|---|---|
| `t("中文 {名字}", {名字: 值}, 语境?)` | 普通句子、按钮、标题、提示 | `t("已导出「{title}」（{size} MB）", {title, size})` |
| `tn("{n} 行", n, 其他占位符?)` | 带数量的句子（英文有单复数） | `tn("{n} 分钟前", m)` |
| `td("鹈鹕骑自行车动画")` | **数据里的**中文名：作品名、题库科目名、场景名等 | `td(item.name)` |
| `tm(服务端返回的消息)` | 服务端接口返回的错误 / 状态提示 | `toast(tm(d.error), "error")` |
| `tk("可用")` | 只做标记、原样返回：常量表里的中文（见下） | `{ok: tk("可用")}`，用的时候 `t(x.ok)` |

- **占位符**用单花括号 `{名字}`（名字可以是中文；避免和模板字符串的 `${}` 混淆）。没传的名字原样留着，一眼看得出写错了；`{{` `}}` 表示字面的花括号（只在传了参数时生效）。
- **`t` 不转义**：往 HTML 里插值时调用处自己 `esc()`，往纯文本（toast、`title`、ECharts）里放就传原值，和以前的做法一样。文字里可以带 HTML 标签，如 `t("同时 <b>{n}</b> 个请求", {n})`。
- **英文词条里的占位符和 HTML 标签必须和中文一致**（测试会检查），英文里不能有汉字。
- **整句翻译，不要拼句子**：中英文语序不同，不要把一句话拆成几段用 `+` 拼；变化的部分用占位符。`t()` 的第一个参数必须是一个写死的字符串或不带 `${}` 的模板字符串（检查工具要靠它认出词典的键）。
- **分隔符也是文字**：`、` `，` `；` `（）` `：` 在英文里是 `, ` `; ` `(`…，写成 `list.join(t("、"))`。
- **同一句中文在不同地方要译成不同的英文**：加语境参数 `t("图表", null, "切换按钮")`，词典里的键写成 `"切换按钮|图表"`。
- **数量**：`tn` 的英文词条是 `["{n} minute", "{n} minutes"]`（`n === 1` 用单数）；`{n}` 默认就是数量，要千分位等格式传 `{n: fmtInt(n)}`。
- **数字**：`toLocaleString(I18N.locale())`（中文 `zh-CN`，英文 `en-US`），不要写死语言。
- **常量表里的中文不能在定义时翻译**（会固定成加载时的语言）。三种办法：① 对象用 getter（`{get ok(){return t("可用")}}`，用到的地方不用改，例子见 `STATUS_NAME`）；② 改成函数；③ `tk("可用")` 标记，用的时候 `t(x)`。
- **变量名不要叫 `t` `tn` `td` `tm` `tk`**：会遮住翻译函数。检查工具会指出具体位置，把变量改名即可。
- **CSS 里 `content: "中文"` 生成的文字**：用 `html:lang(en) 原来的选择器 {content: "English"}` 覆盖（JS 切换语言时会改 `<html lang>`）。
- 接口请求（`getJSON` / `postJSON` / `tsApi` / 导出报告）都带请求头 `X-Lang: zh|en`，服务端据此决定接口错误提示和后台任务日志的语言；新增直接调用 `fetch("/api/…")` 的地方用 `apiHeaders()`。

常见写法：

- 句子里夹着 `term(…)`、`fmt(…)`、`esc(…)` 这类调用：整句翻译，把它们的结果当占位符值传进去，别把句子拆开，如 `t("同时 <b>{n}</b> 个请求时{term}最高", {n, term: term("agg", t("总速度"))})`。
- `emptyState(t("标题"), t("说明"))`、`alertBox("warn", t("…"))`、`toast(t("…"))`、`msg(el, "error", t("…"))`：文字在调用处翻译（这些函数自己会转义）。
- 表格的列名、图表的系列名和坐标轴名：在生成它们的函数里 `t()`，不要放进模块级常量。
- 转换是机械的：中文模式下 `t("…")` 必须和原来的字符串逐字相同（空格、标点也一样），不要顺手改中文文案。

### 静态 HTML（`web/index.html`）

直接写中文，**不用改标签**：`applyStaticI18n` 会在页面打开和切换语言时翻译文本节点和 `title` / `placeholder` / `aria-label` / `alt` 属性（原文记着，切回中文还原）。键是去掉首尾空白、中间的空白（含换行缩进）合成一个空格的中文原文，英文词条写进 `web/static/i18n.en.html.js`。

- 句子中间夹着 `<code>` `<b>` `<a>` 的元素，拆成文本节点没法翻：给元素加 `data-i18n-html`，键就是它的 `innerHTML`（空白合并），英文值里的标签要和中文一致。
- 不该翻译的（数据、代码）加 `translate="no"`。
- 只处理页面刚打开时就有的节点；之后 JS 动态插入的文字走 `t()`。

### 换语言时要重画

页面上动态生成的文字都是「画的时候翻译的」，换语言后要重画。当前页面（图表、表格、结论）、侧栏、打开着的抽屉和名词解释已经会自动重画；**只生成一次就存进 DOM 的文字**（元素的 `title`、下拉的选项、缓存好的 HTML 等）要在自己的代码旁边登记：

```js
I18N.onChange(() => { if (RUNS_LOADED) fillRunSelects(); });   // 例子: 页头的测试下拉
```

`app.js` 里的 `setLang(x)` 写本地偏好（离线报告里只写内存）→ `I18N.set(x)` 改 `<html lang>`、标题和静态文字 → 依次调用登记的函数。已经弹出来的 toast 不会重新翻译。

### 词典文件

`web/static/i18n.js` 是框架，每个区域一个词典文件 `web/static/i18n.en.<区域>.js`，加载顺序 `i18n.js` → 各词典 → `app.js`（`index.html`、离线报告、`tests/test_frontend.py` 里都是这个顺序）。词典文件里只能写 `I18N.add("en", {…});`、`I18N.add("enData", {…});` 和 `I18N.addPattern([/正则/, "英文或函数"], …);`。

| 文件 | 放什么 | app.js 里对应的区域 |
|---|---|---|
| `common` | 导航、按钮、通用提示，两边（HTML 和 JS）都用到的句子 | 基础工具 · 主题 · 界面语言 · 导航 / 抽屉 / 弹窗 · 自定义下拉 · 运行日志 · 图表层 · 页面积木 · 多表格系统 · 删除 · 样式自检 · 导出报告 · 启动 |
| `html` | `index.html` 的静态文字 | — |
| `perf` | 速度测试 | 速度测试: 新建 / 列表 / 指标 · 速度测试: 结果页 |
| `cmp` | 速度对比 | 速度对比 |
| `iq` | 能力测试 | 能力测试 |
| `gen` | 代码生成 | 代码生成 |
| `tasks` | 任务集 | 任务集 |
| `models` | 模型管理 | 模型管理 |
| `glossary` | 名词解释 | 名词解释 |
| `server` | 服务端返回给界面的提示（含正则模式） | — |

服务端提示带变化部分的用正则模式：`I18N.addPattern([/^任务集不存在: (\S+)$/, "Task set not found: $1"])`，第二项也可以是函数 `(m, a) => …`（里面可以再 `tm(a)`）；查不到的记进 `I18N.missingServer`。查不到英文词条的 `t()` / `tn()` 回退成中文并记进 `I18N.missing`（控制台只警告一次）；`td()` 查不到回退原文并记进 `I18N.missingData`。

### 检查工具与基线

```bash
python tests/i18n_lint.py --report                # 汇总（按区域）和全部明细
python tests/i18n_lint.py --report --area 任务集   # 只看名称含「任务集」的区域
python tests/i18n_lint.py --missing               # 已转成 t() 但词典里还没有英文的键
python tests/i18n_lint.py --update-baseline       # 翻完一个区域后，把基线降下来
```

`tests/i18n_lint.py` 用一个只认「字符串、模板字符串、注释、正则字面量」的 JS 词法扫描器，规则：**字符串 / 模板字符串的静态文字里出现汉字（含中文标点），除非它就是 `t(` `tn(` `td(` `tm(` `tk(` 调用的第一个参数（词典的键），就算「违规」**（注释里的汉字不算）。模板字符串里夹着 HTML 的，把每段要翻译的文字拆成 `${t("…")}`。`index.html` 里中文原文在词典里没有英文、`app.css` 里没有 `:lang(en)` 覆盖的中文 `content`，也算违规。

- **基线棘轮** `tests/i18n_baseline.json` 记录每个区域当前允许的违规数：违规数不能比基线多，比基线少了也要运行 `--update-baseline` 把基线降下来（`--update-baseline` 只允许降低，要升要加 `--allow-increase`，一般不该用）。翻完一个区域，基线就是 0。
- **只对基线为 0 的区域强制**：这些区域里 `t()` / `tn()` 用到的键必须都有英文；转换到一半的区域缺英文只在 `--missing` 里列出。
- **允许清单** `tests/i18n_allow.txt`：按「文件: 内容片段」登记不算违规的例外（两种语言下写法一样的双语标签、必须保持中文的数据键），片段是违规文字所在那一行源码里的一段，不要写行号；用不上的条目测试会提醒删掉。
- `python -m unittest discover -s tests` 里的 `test_i18n.py`（扫描器本身、基线、词典、`t()` 传的占位符参数和键里的 `{名字}` 一一对上、`index.html` / `app.css`）、`test_i18n_export.py`（离线报告带语言偏好、内联翻译脚本、在报告里切换语言）、`test_frontend.py`（`t` / `tn` / `td` / `tm` / `applyStaticI18n`、请求头）会守住这些规矩。

### 新增文字的清单

1. 写 `t()` / `tn()` / …（不要把中文直接留在字符串里）；
2. 在对应区域的词典里加英文（同一句两边都用的放 `common`）；
3. 运行 `python -m unittest discover -s tests`；
4. 英文模式下打开页面看一遍（做法见 [tests/i18n_probe.md](tests/i18n_probe.md)）。

## 服务端消息与翻译

后端（`llm_bench_pro/*.py`）的日志、接口错误提示、存进结果里的说明、命令行帮助和旧版 HTML 报告都有中文 / 英文两种。做法是 gettext 风格：**中文原文继续写在代码里、当作键，英文放在词典里**。新增或修改任何「给人看的文字」，都要按这一节写。

### 怎么写

```python
try:
    from . import i18n          # 包内导入 (python -m llm_bench_pro.xxx); 另一种写法见 endpoints.py 开头
except ImportError:
    import i18n                 # server.py 以包目录为 sys.path 顶层导入
t, tn = i18n.t, i18n.tn

return None, t("服务地址最多 {limit} 个字（现在 {n} 个）", limit=URL_MAX, n=len(url))   # 带参数的错误提示
plog(tn("  另外还跳过 {n} 张不能用的图片", extra))                                        # 带数量: 词典里写 (单数, 复数)
name = t("代码生成", ctx="任务名")                                                       # 同一个中文、不同场合译法不同: 词典键 "任务名|代码生成"
```

- **键必须是字符串常量**（相邻的字符串字面量会自动合并，可以拆行写），不能是变量、f-string、`+` 拼接、`%` 格式化，也不能用 `*` / `**` 展开参数——否则检查工具看不到它。旧的 `%s` / `%d` 写法改成 `{名字}`：`"%d/%d 失败" % (a, b)` → `t("{fail}/{total} 失败", fail=a, total=b)`。数字格式照 `str.format`：`{x:.1f}`、`{label:<6}`。文字里要出现字面的花括号（比如 JSON 示例）写成 `{{` `}}`。
- **整句翻译，不要拼碎片**：英文语序和中文不一样。一句话里有可选的后缀，就写成两个整句（见 `bench.py` 的 `phase_scenario`）；列表里几项之间的分隔用 `t("；").join(...)`（词典在 `common.py`）。
- **带数量用 `tn(键, n, ...)`**：中文只有一种写法，英文词条是 `(单数, 复数)` 二元组，`n == 1` 用单数，`{n}` 默认就是 `n`（要千分位就自己传 `n="3,000"`）。能改写成不分单复数的说法（`{inserted} 个 → {inserted} imported`）就用 `t`。
- **在函数里调用，不要在模块级或类体里调用**：import 时语言还没定，会固定成加载时的语言。模块级常量里要显示的文字改成函数，例如 `endpoints.bad_url()`、`server.job_name(kind)`。
- **别把局部变量叫 `t` / `tn`**（会遮住翻译函数，报错发生在很少走到的错误分支里）。检查工具会抓；实在要保留，这个函数里改用 `i18n.t(...)`。
- **线程一律用 `i18n.spawn(...)`，线程池一律用 `i18n.executor(...)`**（用法同 `threading.Thread` / `ThreadPoolExecutor`），不要直接用标准库的：语言存在 `contextvars` 里，标准库创建的线程不会继承它，线程里的日志和生成的说明文字就会变回默认语言。
- **存进结果里的说明**（`notes`、`error`、警告、`length_skips` 的 `reason` 等）按任务语言生成、原样存储；已有的旧数据里的中文不用管（前端另有处理）。
- 操作系统和第三方库返回的错误原文（如 `ConnectionRefusedError: [WinError 10061] …`）是系统语言，翻不了，原样带上。

### 不翻译的

函数 / 模块的 docstring 和注释（开发者文档，保留中文）；发给模型的提示词、测试题目、语料、作品名、检查项名称、题库数据、从模型回答里提取答案的正则等**测试内容**（`gen.py` 的题目表、`gen_specs.py` 的检查清单、题库等，由前端按需显示英文名）；`data/` 里已有的数据。这些登记在 `tests/i18n_py_allow.txt`（见下）。

### 词典

`llm_bench_pro/i18n_en/<模块名>.py`，每个模块一个文件，内容是 `ENTRIES = {"中文原文": "English", ...}`（只能是字面量）：

- 好几个模块都用的句子放 `common.py`；**每个键只能出现在一个文件里**，也只能出现在用到它的模块的文件（或 `common.py`）里。
- 中文和英文的 `{占位符}` 要一致，调用处要把它们都传进去；英文里不能有汉字和中文标点；带数量的（`tn`）写成 `(单数, 复数)`。
- 中文模式不加载词典；英文模式第一次需要时才加载。查不到英文时回退成中文，并把键记进 `i18n.MISSING`（集合，不刷屏）。

### 语言怎么定

优先级从高到低：`i18n.set_lang()`（当前线程 / 上下文）→ 命令行 `--lang` → 环境变量 `LLM_BENCH_LANG`（`zh` / `en`）→ 系统区域（`LANGUAGE` / `LC_ALL` / `LC_MESSAGES` / `LANG`，以 `zh` 开头用中文，否则英文；`C` / `POSIX` 当作没设；都没有时 Windows 看用户界面语言）→ 中文。**系统区域和 `Accept-Language` 只在 `i18n.AUTO_DETECT` 为 `True` 时才看；翻译全部完成之前它是 `False`，没有明确指定语言（请求头 / `--lang` / 环境变量）就一律中文**，全部翻完后和界面那边的 `I18N.AUTO_DETECT` 一起改成 `True`。

- **服务端每个请求**按请求头 `X-Lang: zh|en` 设自己的语言，没有就看 `Accept-Language`（同样要 `AUTO_DETECT` 打开才看），再没有用默认。
- **页面启动的测试任务**（速度 / 能力 / 代码生成 / 题集更新）在启动时记下请求的语言，任务线程和任务里的工作线程都沿用它，不受之后别的请求的语言影响（`Job.lang`）。
- **命令行**：所有入口（`run.py`、`bench`、`geneval`、`store`、`bankman`、`cdp`）都有 `--lang zh|en`。新写命令行入口时，创建 argparse **之前**调用 `i18n.preparse_lang(argv)`（这样 `--help` 的文字也是对应语言），创建后调用 `i18n.add_lang_arg(ap)`（带子命令的，如 `store`，每个子命令解析器还要 `i18n.add_lang_arg(p, sub=True)`，这样 `--lang` 写在子命令后面也行）。

### 检查

```bash
python tests/i18n_lint_py.py                       # 违规数不超过基线、允许清单没有过期条目、词典没问题 (测试里也会跑)
python tests/i18n_lint_py.py --report -f bench.py  # 某个文件的全部明细 (哪一行、哪个函数、什么文字); 不带 -f 是全部文件
python tests/i18n_lint_py.py --scopes -f server.py # 按函数 / 常量汇总, 带行号范围: 拆分大文件时用
python tests/i18n_lint_py.py --missing             # 用到了、词典里还没有英文的键
python tests/i18n_lint_py.py --update-baseline     # 转换完一个文件后把基线降下来
```

- **规则**（`tests/i18n_lint_py.py` 开头有完整说明）：任何含汉字（或中文标点）的字符串常量 / f-string 静态部分，除非是 `t()` / `tn()` 的第一个参数、`ctx=` 参数、docstring，或登记在允许清单里，就是违规；另外检查 `t()` 的写法（键要是常量、占位符格式对、不在模块级调用、没被变量名遮住、已导入）和线程是否用了 `i18n.spawn` / `i18n.executor`。
- **基线棘轮**：`tests/i18n_py_baseline.json` 记录每个文件现在允许的违规数。违规数不能比基线多，转换之后也要把基线降下来（`--update-baseline` 只降不升；新文件要么一开始就是 0，要么明确加 `--allow-increase`）。`t()` 写法、线程这几条不靠基线，任何文件都必须是 0。
- **允许清单** `tests/i18n_py_allow.txt`：每行 `文件名:范围` 或 `文件名:范围:文字片段`（范围是函数名 / 模块级变量名 / 类名 / `类名.方法名`，后一种用来在同一个函数里区分「测试内容」和「对外提示」）。只登记确定不是给人看的输出；登记的东西改了、删了，对应的行会过期，测试会提醒删掉。
- **英文输出扫描**：`tests/test_i18n_py.py` 里的 `english_flow()`（收集英文模式下 `plog` 的全部输出，含线程里的，还记下查不到英文的键）、`flow.assert_clean(...)`、`assert_english(self, 对象, keys=...)`（断言没有汉字；`keys=STORED_TEXT_KEYS` 只查存进结果里的说明类字段）。转换完一个模块，写一个在英文下跑它的测试：

  ```python
  from test_i18n_py import english_flow, assert_english, STORED_TEXT_KEYS

  with english_flow() as flow:
      result = bench.calibrate_prompt(url, {}, "m")      # 任何会打日志、会生成说明文字的流程
  flow.assert_clean(self, result, keys=STORED_TEXT_KEYS)  # 日志和标准输出没有汉字、词典没有缺键, 存进结果里的说明也没有汉字
  ```

  接口用请求头 `X-Lang: en` 请求，再对返回的 `error` 调用 `assert_english`（见 `TestApiErrorsFollowXLang`）；后台任务见 `TestJobsRunInTheLanguageOfTheRequestThatStartedThem`。中文模式的输出要和转换前逐字一致：现有测试断言的中文提示就是证明，新写的英文测试旁边再配一个中文的断言。写英文扫描的测试时别去触发真实的操作系统错误（连接被拒绝等，中文系统上原文是中文），用 `MockServer` 返回 HTTP 错误就行。

### 转换一个模块的步骤

1. `python tests/i18n_lint_py.py --report -f 文件名`（大文件先 `--scopes` 看分布）列出还没转的字符串；分清哪些是对外的文字（改成 `t()` / `tn()`）、哪些是测试内容（登记到允许清单）。
2. 逐个改成 `t()` / `tn()`，中文原文逐字不变，保证中文模式的输出和以前一样；在 `i18n_en/<模块名>.py` 里写英文词条。
3. 跑 `python -m unittest discover -s tests`（`python tests/i18n_lint_py.py --missing` 能看到漏写的词条），写英文输出扫描的测试。
4. `python tests/i18n_lint_py.py --update-baseline` 把基线降下来。

## 许可

提交到本仓库的代码以 [MIT 许可](LICENSE) 发布。题库数据的来源与许可见 [banks/README.md](banks/README.md)。
