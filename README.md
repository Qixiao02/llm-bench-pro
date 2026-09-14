# LLM Bench Pro — 大模型推理评测一体化平台

对 OpenAI 兼容端点做 **性能基准 / 智力评分 / 真实生成效果** 三维评测，
同一模型跨后端（不同推理框架/版本/量化）A/B/N 多对象对比。
纯 Python 标准库（3.8+，零第三方依赖），前端零 CDN 依赖，下载即用。

## 快速开始

```bash
python run.py            # 打开 http://127.0.0.1:18080
```

在「性能基准」页点「新建测试」，填写 API 地址 → 「测试连接」（拉取 /v1/models 自动回填模型与框架）→ 「开始运行」。

## 四个页面

| 页面 | 功能 |
|---|---|
| 性能基准 | Prefill 阶梯 / 提示词长度×并发矩阵(含 P50/P90/P95) / 单流解码(ITL 分位数·投机 burst) / 并发阶梯 / vLLM 框架指标时间线(KV·前缀缓存)。长度阶梯与并发可自定义，A/B 叠图对比 |
| 运行对比 | 两次运行关键指标差异: 涨跌标注(延迟类越低越好) / 叠图 / 矩阵逐档 Δ / 明细表。支持跨后端(框架名+版本标注)对比 |
| 能力评测 | 官方题集(GSM8K·MMLU 全 53 科分四层·MATH-500·ARC·HellaSwag·C-Eval·IFEval) 924 题，Wilson 95% CI，雷达图，三档题量，题库版本化可切换/一键拉取更新，多对象同屏对比 |
| 代码生成 | 33 题四档单文件前端生成(鹈鹕骑车/Flappy/俄罗斯方块/3D 迷宫/流体/Win95 + 实战美观题 10 道)，**无头浏览器运行检测 + 视觉模型清单评审**，沙箱隔离预览，人工打星，A/B 并排 |

界面：暗色为默认主题，侧栏底部可切换亮色（跟随系统偏好，选择会被记住）；运行中的任务在刷新页面后会自动恢复日志跟踪。

## 项目结构

```
llm-bench-pro/
├── run.py                  # 启动入口: python run.py [port]
├── llm_bench_pro/          # 核心包
│   ├── server.py           # HTTP 服务 + 全部 API(多线程)
│   ├── bench.py            # 性能基准引擎(流式 TTFT/ITL/并发屏障同步)
│   ├── iq.py               # 智力测试引擎(官方判分口径 + Wilson CI)
│   ├── gen.py              # 生成测试引擎(33 题四档, 生成 + 续写 + 重新评测)
│   ├── geneval.py          # 生成作品评测: 运行检测 / 源码检查降级 / 视觉评审
│   ├── gen_specs.py        # 逐题评测规格: 交互脚本 / 功能断言 / 评审清单
│   ├── cdp.py              # 纯标准库 Chrome DevTools 协议客户端(无头 Chrome/Edge)
│   ├── bankman.py          # 题库管理(多镜像拉取/版本化/限速退避)
│   ├── store.py            # SQLite 结果库(建表/增量写/读/导入导出)
│   └── sinks.py            # 结果落地抽象: JSON 文件 / SQLite / 组合
├── web/
│   └── index.html          # 单文件前端(暗/亮双主题, 设计 token + 原生 canvas 图表, 零依赖)
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
   - 未找到浏览器时降级为源码检查（去注释后匹配），结果标注“源码检查”
2. **视觉评审**（可选，需一个支持图片输入的 OpenAI 兼容模型）：题目要求 + 运行检测报告 + 截图序列 + 源代码 → 逐题清单与通用项（视觉/完成度/代码）逐项 0–10 分，汇总为 0–100；代码中声称但截图与检测均未体现的功能最多 3 分

已有运行可在页面点「重新评测」，或命令行：

```bash
python -m llm_bench_pro.geneval --run gen_20260914_xxx --judge-base http://host:8000 --judge-model Qwen2.5-VL-72B
```

## 结果存储

- 服务端所有运行写入 SQLite(`data/llm_bench.db`, WAL 模式): 每个 phase / 科目 / 作品增量提交, 崩溃不丢已完成部分
- 运行状态 `status`: running / done / failed / interrupted; 进程被杀的运行按心跳超时(5 分钟)自动判为 interrupted
- 人工打星为单行更新, 生成测试运行中也可打星
- 服务启动时自动导入 `results/` 中库里还没有的 JSON(旧数据零迁移成本)

```bash
python -m llm_bench_pro.store import            # 导入 results/*.json (幂等, --force 覆盖内容变化者)
python -m llm_bench_pro.store check             # 校验库与 results/*.json 往返等价
python -m llm_bench_pro.store export --out dir  # 导出为 JSON (--kind perf|iq|gen / --run RUN_ID)
python -m llm_bench_pro.store stale             # 手动标记心跳超时的运行为 interrupted
```

## API 一览

`GET /api/results|iq-results|gen-results|banks|status|iq-status|gen-status`
`GET /api/run?id=<run_id>` 单个运行完整文档 · `GET /api/export?id=<run_id>` 下载 JSON · `/api/iq-results?full=1` 含逐题结果
`POST /api/probe|start|iq-start|gen-start|bank-update|gen-rate`
`GET /works/<run>/<task>.html` — 生成作品(供沙箱 iframe)

## CLI(生产服务器直跑)

```bash
python -m llm_bench_pro.bench --url http://host:8011 --model NAME --suite standard \
    --metrics-url http://host:8011/metrics --lens 1,2,4,8,16 --conc-ladder 1,2,4,8 \
    --framework 1Cat-vLLM --fw-version 1.6.5 --tag baseline
```

默认输出 `results/<run_id>.json`(拷回本机 `results/` 后服务启动即自动入库); `--sink db` 直接写库, `--sink both` 两者都写, `--db PATH` 指定库。

## 测量口径

- TTFT = SSE 首个 content delta; 解码吞吐 = (completion_tokens-1)/流内解码跨度(usage 精确计数)
- 每次测量带唯一批次号, 防前缀缓存命中虚高; 聚合吞吐 = 轮总 token ÷ 轮墙钟(屏障同步)
- 智力判分对齐发布方: MMLU 选项匹配 / GSM8K `####` / MATH-500 boxed 规范化 / IFEval 规则校验
- 全部报告 Wilson 95% 置信区间; 题集版本不一致的对比自动警告

## License

MIT
