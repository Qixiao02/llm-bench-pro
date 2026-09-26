# LLM Bench Pro — 大模型推理评测一体化平台

对 OpenAI 兼容端点做 **性能基准 / 智力评分 / 真实生成效果** 三维评测，
同一模型跨后端（不同推理框架/版本/量化）A/B/N 多对象对比。
纯 Python 标准库（3.8+，零第三方依赖），前端零 CDN 依赖，下载即用；
所有图表使用本地内置的 ECharts（`web/static/vendor/echarts.min.js`，约 1MB，Apache-2.0），不依赖外网。

## 快速开始

```bash
python run.py                                   # 仅本机访问: http://127.0.0.1:18080
python run.py 18090                             # 换端口
python run.py --host 0.0.0.0 --token 自定义令牌   # 局域网访问, 用 http://主机:18080/?token=自定义令牌 打开
```

在「速度测试」页点「新建速度测试」，右侧面板里填写服务地址 → 「测试连接」（拉取 /v1/models 自动回填模型与框架）→ 「开始测试」。

### 模型配置管理（免复制粘贴）

侧边栏「设置 · 模型管理」统一维护端点配置（名称 / API 地址 / API Key / 模型名，存本机数据库、含 Key 掩码显示）：

- **添加 / 编辑**：弹窗上方表单直接填写保存，名称留空自动按「模型 · 主机」命名；
- **填入表单**：一键把配置同时填入速度测试、能力测试、代码生成三个新建面板；
- 三个「新建」表单顶部各有「模型配置」下拉，选中即填当前表单（包括 Key），不用再复制粘贴。

- 默认只监听 127.0.0.1。监听其他地址且未设置令牌时启动会给出警告；令牌也可用环境变量 `LLM_BENCH_TOKEN` 设置
- 端口被占用时启动直接失败（Windows 上不再出现多个进程同时监听同一端口、请求落到旧进程的情况）
- **更新代码后需要重启服务**。页面会检测“后端代码已更新但服务未重启”以及“页面与后端版本不一致”并提示

## 页面

每个结果页都按「结论 → 关键指标 → 分章节图表」排列：顶部先用几句大白话说明结果（例如“同时 48 个请求时总速度最高”），
工具条固定在顶部，可以一键跳到各章节；每组图表下面都能展开「查看具体数字」。
页面上的专业词都换成了大白话（如 TTFT →“首字等待”、Prefill →“读入速度”、p95 →“较慢的情况”、置信区间 →“误差范围”），
鼠标放在带虚线下划线的词上可以看到原来的专业说法，左侧「名词解释」列出全部。
图表配色经色盲安全校验（亮/暗两套），不使用双纵轴（两种单位拆成两张图）。

| 页面 | 功能 |
|---|---|
| 速度测试 | Prefill 阶梯 / 提示词长度×并发矩阵(含 P50/P90/P95) / 单流解码(ITL 分位数·投机 burst) / 并发阶梯 / **任务场景(问答/代码/抽取/RAG/图片理解/自定义·按业务自由组合)** / **真实请求回放(闭环+开环泊松到达·在途时间线)** / vLLM 框架指标时间线(KV·前缀缓存)。长度阶梯与并发可自定义，A/B 叠图对比 |
| 速度对比 | 两次测试关键指标差异: “B 相对 A”变化图(往右更好、往左更差, 延迟类已按好坏方向换算; 档位不同的指标标为不可比) / 叠图 / 矩阵逐档 / 明细表 / 场景对比。支持跨后端(框架名+版本标注)对比, **可导出 A/B 离线 HTML 报告** |
| 能力测试 | 官方题集(GSM8K·MMLU 全 53 科分四层·MATH-500·ARC·HellaSwag·C-Eval·IFEval) 924 题，Wilson 95% CI(误差范围)，各科横向柱状图 + 雷达图 + 每题 token 花费，三档题量，题库版本化可切换/一键拉取更新，多对象同屏对比；**逐题查看**：每道题的题目、选项、标准答案和模型的答案，可按科目/对错筛选、搜索，对比时可只看“只有 A 答对”“只有 B 答对”的题，点开可看模型的回答原文和发给模型的原文 |
| 代码生成 | 33 题四档单文件前端生成(鹈鹕骑车/Flappy/俄罗斯方块/3D 迷宫/流体/Win95 + 实战美观题 10 道)，**无头浏览器运行检测 + 视觉模型清单评审**，按“模型自身问题 / 评测环境问题”归因，逐轮保存模型原始输出可核对框架是否改动过代码，沙箱隔离预览，人工打星，A/B 并排 |

通用操作：
- **任务场景**（按你的业务形态自由组合，默认不启用）：场景 = 任务模板 × 语料 × 负载。六类内置模板——**对话问答**（短答/长文混合）、**代码生成**（函数/类/脚本/修 bug）、**结构化抽取**（商品→标准 JSON，报合法率）、**RAG 问答**（1.5K/4K/16K 档长上下文 + 引用式回答）、**图片理解**（多模态 content 数组，图片来自上传图片包或服务器目录，每请求 1-4 张）、**自定义任务集**（上传你自己的 JSONL，完全用你的请求）。语料固定种子生成——A/B 两次运行收到相同请求序列；指标诚实：只有声明输出契约的模板（结构化抽取/带 response_format 的自定义行）报 JSON 合法率，其余报输出长度分布
- **真实请求回放**（可选，上传线上导出的 JSONL）：**闭环**（C 个 worker 各连发 N 条）回答"C 路并发扛不扛得住"；**开环**（泊松到达按速率施压，含在途时间线与最大在途）回答"线上到达速率下会不会越排越长"。两次运行到达时间轴相同，A/B 差异全部来自服务端；回放池 cursor 跨格推进防前缀缓存
- 正式测量前按"实际会跑的 (输入长度, 并发) 组合"预热一轮（结果丢弃），避免引擎按 batch shape 的编译/冷启动拖慢首格；场景/矩阵格遇基础设施型失败（如实例卡死）会等服务恢复后**整格重跑**（最多 3 次），每轮失败在结果与报告中全量披露
- 新建测试在右侧面板里填写，运行日志也在面板里；关掉面板后，侧栏和页头会显示“进行中”，点一下重新打开
- 运行中的任务可在日志栏点「停止」：不再开始新请求，已完成的结果保留；能力评测停止或中断后可「续跑」，只补做未完成的题
- 工具条右侧可删除所选运行（代码生成会一并删除作品文件）；删除后 `results/` 中的同名 JSON 不会在重启时被重新导入
- 性能测试与其他测试同时访问同一模型端点时，启动前会要求确认（同时运行会污染吞吐与延迟数据）
- 性能页自动给出数据提示，如并发增加时聚合吞吐下降、投机解码只在单并发生效、请求失败等
- 暗色为默认主题，侧栏底部可切换亮色；时间按浏览器本地时区显示；运行中的任务在刷新页面后会自动恢复日志跟踪

## 项目结构

```
llm-bench-pro/
├── run.py                  # 启动入口: python run.py [port] [--host] [--token]
├── llm_bench_pro/          # 核心包
│   ├── server.py           # HTTP 服务 + 全部 API(多线程, 任务取消/续跑/端点冲突保护/访问令牌)
│   ├── version.py          # 应用版本号(与 web/static/app.js 的 UI_VERSION 一致)
│   ├── bench.py            # 性能基准引擎(流式 TTFT/ITL/并发屏障同步 + 任务场景/回放场景)
│   ├── iq.py               # 智力测试引擎(官方判分口径 + Wilson CI)
│   ├── gen.py              # 生成测试引擎(33 题四档, 生成 + 续写 + 重新评测)
│   ├── geneval.py          # 生成作品评测: 运行检测 / 源码检查降级 / 视觉评审
│   ├── gen_specs.py        # 逐题评测规格: 交互脚本 / 功能断言 / 评审清单
│   ├── cdp.py              # 纯标准库 Chrome DevTools 协议客户端(无头 Chrome/Edge)
│   ├── bankman.py          # 题库管理(多镜像拉取/版本化/限速退避)
│   ├── store.py            # SQLite 结果库(建表/增量写/读/导入导出)
│   ├── report.py           # 离线 HTML 报告生成(自包含·内联 SVG·A/B 对比·失败重跑披露)
│   └── sinks.py            # 结果落地抽象: JSON 文件 / SQLite / 组合
├── web/
│   ├── index.html          # 页面结构与图标
│   └── static/             # app.css(设计 token/组件) · app.js(逻辑与 ECharts 图表) · vendor/echarts.min.js
├── tests/                  # 标准库 unittest: 判分/统计/存储/服务/性能引擎/生成评测
├── banks/                  # 题库版本资产(iq-<日期>-<hash>.json, 多版本共存)
├── data/llm_bench.db       # 运行结果库(gitignore, 可用 $LLM_BENCH_DB 改路径)
├── results/                # 旧版/CLI 产出的 JSON 结果(gitignore, 服务启动时自动导入库)
└── works/                  # 生成作品 HTML 与检测截图(gitignore)
```

## 生成测试评测口径

参照 ArtifactsBench（真实渲染 + 交互截图 + 清单式多模态评审），分两层，结果分别报告、不做加权混合：

1. **运行检测**（确定性、可复现，需本机安装 Chrome / Edge / Chromium，可用 `LLM_BENCH_BROWSER` 指定路径）
   - 断网加载（外部脚本/样式被拦截即判“非自包含”，网络字体除外），`Math.random` 固定种子，`alert/confirm` 置空
   - 检查项：代码完整输出、加载无卡死、无未捕获异常/控制台错误、首屏非白屏、应有动画的题空闲时持续渲染、移动端 390px 无横向溢出
   - 逐题交互脚本（`gen_specs.py`）：真实按键/点击/拖拽/滚轮；计算器、终端、待办等题用**功能断言**判定（如 7+8 必须显示 15），其余以画面/DOM 变化是否超出空闲基线、作品事件处理器是否被调用判定
   - 作品报错时，会在**不注入任何检测脚本**的干净页面里按同样步骤再跑一遍（对照运行）：同样报错即作品自身的 bug，否则提示“可能是检测环境引起”
   - 未找到浏览器或浏览器启动失败时降级为源码检查（去注释后匹配），页面醒目标注“没有实际运行”并给出原因，修复后可一键重新检查
   - 以管理员身份运行服务时，Chrome 会以普通权限重启自身；评测会接管重启出的浏览器（并传 `--do-not-de-elevate`），临时目录记录所属进程，所属进程退出后遗留的后台浏览器会被自动回收。旧版本遗留的后台浏览器可在没有评测运行时手动清理：`python -m llm_bench_pro.cdp --reap-all`
2. **视觉评审**（可选，需一个支持图片输入的 OpenAI 兼容模型）：题目要求 + 运行检测报告 + 截图序列 + 源代码 → 逐题清单与通用项（视觉/完成度/代码）逐项 0–10 分，汇总为 0–100；代码中声称但截图与检测均未体现的功能最多 3 分

生成过程本身也可核对（2.3 起）：

- **采样**：默认按官方推荐（思考 temperature 0.6 / top_p 0.95，不思考 0.7 / 0.8，top_k 20，seed 42）；旧版统一 0.3，接近贪心，小模型写长文件容易陷入无限重复。新建面板可改为旧版口径或自定义
- **重复输出检测**：流式生成时检测逐字循环（严格周期）和内容高度雷同（8000 字符窗口压缩率连续 3 次低于 0.13；正常作品实测不低于 0.19），命中立即停止且不再续写，作品标注“陷入重复输出”
- **原始输出留档**：每题逐轮保存模型原始输出、思考长度、结束原因、token 和拼接方式到 `works/<run>/<题>.gen.json`；作品卡片「生成过程」里可查看每一轮原文（重复部分标红），并用大白话列出框架做过的全部处理（去掉说明文字/代码块标记、拼接续写等）。除列出的处理外，保存的作品与模型输出逐字一致

已有运行可在页面点「重新检查」，或命令行：

```bash
python -m llm_bench_pro.geneval --run gen_20260914_xxx --judge-base http://host:8000 --judge-model Qwen2.5-VL-72B
```

## 能力评测口径

- 判分对齐发布方：MMLU/ARC/HellaSwag/C-Eval 选项提取、GSM8K `####`、MATH-500 `\boxed{}` + 官方 `strip_string` 规范化、IFEval 风格规则校验
- 输出预算（max_tokens）：选择题 16、GSM8K 2048、MATH-500 4096、指令遵循 320（默认值为本项目设定，对齐主流口径的做法；启动器「高级设置」可按题型覆盖，数值钳制在 8–32768，只影响"能否答完"不影响判分）；思考模式统一 32K（超出模型上下文时自动收缩）。各运行的预算明示在结果卡片上
- **Token 花销作为能力维度**：结果卡片显示入/出 token 总量与每题输出均值，分科表有各科 tok/题 列；A/B 对比时显示较 A 的增减百分比（同等正确率下花得更少更高效）
- 采样：默认「官方推荐」——思考模式 temperature 0.6 / top_p 0.95 / top_k 20（贪心解码容易陷入重复），非思考模式贪心；可改为贪心或自定义，采样时固定 seed=42。端点不支持 top_k/seed 等非标准参数时自动去掉并记录
- 达到输出上限的题标记为「截断」、请求异常标记为「失败」，均计为答错并单独统计；每题记录模型答案和回答原文（超过 6000 字时保留开头 2000 + 结尾 4000 字），答错的题另存思考过程的最后 1500 字，可在「逐题查看」里逐题排查（旧测试只保存了答错题回答的最后 240 字）
- 总体准确率按题数计，同时给出科目宏平均；多次运行对比时对共同题目做 McNemar 配对检验，标注差异是否显著（p<0.05）
- 评测程序版本记录在结果中（当前 1.4.0），旧版本结果在页面上会提示口径差异

## 结果存储

- 服务端所有运行写入 SQLite(`data/llm_bench.db`, WAL 模式): 每个 phase / 科目 / 作品增量提交, 崩溃不丢已完成部分
- 运行状态 `status`: running / done / failed / interrupted / cancelled; 进程被杀的运行按心跳超时(5 分钟)自动判为 interrupted
- 能力评测逐题增量保存(每 20 题提交一次), 性能测试按阶段提交, 代码生成按作品提交
- 性能列表接口只返回摘要, 页面按需加载单次运行详情
- 人工打星为单行更新, 生成测试运行中也可打星
- 服务启动时自动导入 `results/` 中库里还没有的 JSON(旧数据零迁移成本)

```bash
python -m llm_bench_pro.store import            # 导入 results/*.json (幂等, --force 覆盖内容变化者)
python -m llm_bench_pro.store check             # 校验库与 results/*.json 往返等价
python -m llm_bench_pro.store export --out dir  # 导出为 JSON (--kind perf|iq|gen / --run RUN_ID)
python -m llm_bench_pro.store stale             # 手动标记心跳超时的运行为 interrupted
```

## API 一览

`GET /api/version` 服务版本、启动时间、提交、是否需要重启
`GET /api/results[?summary=1]|iq-results|gen-results|banks|status|iq-status|gen-status`
`GET /api/run?id=<run_id>` 单个运行完整文档 · `GET /api/export?id=<run_id>` 下载 JSON · `/api/iq-results?full=1` 含逐题结果
`GET /api/report?id=<run_id>[&cmp=<run_id>]` 离线 HTML 报告下载(自包含, 可直接发他人打开)
`GET /api/replay-list` 已上传的回放文件 · `POST /api/replay-upload {name, content}` 上传 JSONL(内容寻址幂等, ≤15MB)
`GET /api/scenario-list` 任务集与图片包清单 · `POST /api/scenario-upload {kind: tasks|images, ...}` 上传自定义任务集/图片包
`GET /api/iq-items?id=<run_id>[&cmp=<run_id>,…]` 逐题列表(题目/标准答案/各次作答摘要) · `GET /api/iq-answer?ids=<run_id>,…&sid=&idx=` 某题回答原文 · `GET /api/iq-wrong?id=&sid=` 某科错题 · `GET /api/iq-compare?a=&b=` 配对显著性
`POST /api/probe|start|iq-start|iq-resume|gen-start|gen-eval|gen-rate|replay-upload|bank-update|cancel|run-delete`
启用令牌时，接口需带请求头 `X-Bench-Token` 或通过 `/?token=` 打开页面获得的 Cookie
`GET /works/<run>/<task>.html` — 生成作品(供沙箱 iframe)

## CLI(生产服务器直跑)

```bash
python -m llm_bench_pro.bench --url http://host:8011 --model NAME --suite standard \
    --metrics-url http://host:8011/metrics --lens 1,2,4,8,16 --conc-ladder 1,2,4,8 \
    --framework 1Cat-vLLM --fw-version 1.6.5 --tag baseline

# 任务场景(按业务形态组合) + 真实请求回放(闭环 + 开环)
python -m llm_bench_pro.bench --url http://host:8011 --model NAME \
    --scn chat,code,rag --scn-conc 4,8 --rag-ctx 4000,16000 \
    --vision-dir /data/images --vision-img 2 \
    --custom-file my_tasks.jsonl \
    --replay-file real.jsonl --replay-conc 8,16 --replay-rates 2,5
```

默认输出 `results/<run_id>.json`(拷回本机 `results/` 后服务启动即自动入库); `--sink db` 直接写库, `--sink both` 两者都写, `--db PATH` 指定库。
默认发送 `ignore_eos` 固定输出长度(每次生成满 max_tokens, 保证不同后端吞吐可比), `--no-fixed-output` 关闭; 端点不支持时自动关闭并在结果中注明。

## 测试

```bash
python -m unittest discover -s tests     # 全部使用临时数据库与本地模拟服务, 不访问真实模型
python tests/run_coverage.py             # 覆盖率(自研 ~100 行, 纯标准库; 结果写入 coverage.txt)
```

- 后端 Python: `test_bench_gen / test_iq / test_server / test_store / test_report` — 覆盖压测引擎、能力评测判分、HTTP 服务层(含安全门禁与版本锁)、SQLite 存储契约、离线报告的自包含性/转义/SVG 完整性等内容级断言。
- 前端 JS: `test_frontend` — 有 Node 则运行(`node --check` 语法门 + DOM 桩加载 app.js 全文跑纯逻辑断言: esc/fmt/坐标轴/淡色守卫/名词解释/问题归因/沙箱策略), 无 Node 自动跳过, 不破坏零依赖承诺; ECharts 渲染与交互以浏览器验证为准。
- 覆盖率不引第三方库: `sys.settrace`(含子线程补丁)采分子、`ast` 数语句行做分母; 浏览器池类模块(cdp/geneval/gen_specs)需真实 Chrome, 数字低是如实反映。

## 测量口径

- TTFT = SSE 首个 content/reasoning delta; 解码吞吐 = (completion_tokens-1)/流内解码跨度(usage 精确计数)
- 默认固定输出长度(ignore_eos), 避免模型提前结束导致吞吐偏高、不同后端不可比; **任务场景与回放不发送 ignore_eos**, 测真实任务行为(合法率/真实输出长度)
- 每次测量带唯一批次号, 防前缀缓存命中虚高; 聚合吞吐 = 轮总 token ÷ 轮墙钟(屏障同步)
- 场景指标均为"先逐请求计算、再排序取分位"; 开环回放为泊松到达、绝对时间调度(无累计漂移), 在途上限 128、超限丢弃并计数; 回放池 cursor 跨格推进防重复请求命中前缀缓存
- 能力评测见上文「能力评测口径」; 全部报告 Wilson 95% 置信区间, 题集版本不一致的对比自动警告

## License

MIT
