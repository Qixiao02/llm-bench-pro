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
- 界面改动请附亮色和暗色的截图，并在 1440 / 1024 / 390 三种宽度下看一遍。
- 不要提交 `data/` 下的任何内容（数据库、测试结果、作品、下载的题集数据）、API Key 和内网地址。

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

优先级从高到低：`i18n.set_lang()`（当前线程 / 上下文）→ 命令行 `--lang` → 环境变量 `LLM_BENCH_LANG`（`zh` / `en`）→ 系统区域（`LANGUAGE` / `LC_ALL` / `LC_MESSAGES` / `LANG`，以 `zh` 开头用中文，否则英文；都没有时 Windows 看用户界面语言）→ 中文。

- **服务端每个请求**按请求头 `X-Lang: zh|en` 设自己的语言，没有就看 `Accept-Language`，再没有用默认。
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
