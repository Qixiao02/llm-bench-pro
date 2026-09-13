# LLM Bench Pro — 大模型推理评测一体化平台

对 OpenAI 兼容端点做 **性能基准 / 智力评分 / 真实生成效果** 三维评测，
同一模型跨后端（不同推理框架/版本/量化）A/B/N 多对象对比。
纯 Python 标准库（3.8+，零第三方依赖），前端零 CDN 依赖，下载即用。

## 快速开始

```bash
python run.py            # 打开 http://127.0.0.1:18080
```

在"性能测试"页填 API 端点 → 点「检测模型」（拉 /v1/models 自动回填）→ 开始测试。

## 四个页面

| 页面 | 功能 |
|---|---|
| 📊 性能测试 | Prefill 阶梯 / 提示词长度×并发矩阵(含 P50/P90/P95) / 单流解码(ITL 分位数·投机 burst) / 并发阶梯 / vLLM 框架指标时间线(KV·前缀缓存)。长度阶梯与并发可自定义，A/B 叠图对比 |
| ⚖️ 数据对比 | 两次运行全维度差异: 红绿 Δ 卡片(方向感知) / 叠图 / 矩阵逐档 Δ / 明细表。支持跨后端(框架名+版本标注)对比 |
| 🧠 智力测试 | 官方题集(GSM8K·MMLU 全 53 科分四层·MATH-500·ARC·HellaSwag·C-Eval·IFEval) 924 题，Wilson 95% CI，雷达图，三档题量，题库版本化可切换/一键拉取更新，多对象同屏对比 |
| 🎨 生成测试 | 33 题四档病毒级生成(鹈鹕骑车/Flappy/俄罗斯方块/3D 迷宫/流体/Win95 + 实战美观题 10 道)，自由勾选，**沙箱隔离预览**(opaque origin，生成代码无法触碰本页)，人工打星，A/B 并排 |

## 项目结构

```
llm-bench-pro/
├── run.py                  # 启动入口: python run.py [port]
├── llm_bench_pro/          # 核心包
│   ├── server.py           # HTTP 服务 + 全部 API(多线程)
│   ├── bench.py            # 性能基准引擎(流式 TTFT/ITL/并发屏障同步)
│   ├── iq.py               # 智力测试引擎(官方判分口径 + Wilson CI)
│   ├── gen.py              # 生成测试引擎(33 题四档 + 特征检查)
│   └── bankman.py          # 题库管理(多镜像拉取/版本化/限速退避)
├── web/
│   └── index.html          # 单文件前端(暗色主题, 原生 canvas, 零依赖)
├── banks/                  # 题库版本资产(iq-<日期>-<hash>.json, 多版本共存)
├── results/                # 运行结果(gitignore)
└── works/                  # 生成作品 HTML(gitignore)
```

## API 一览

`GET /api/results|iq-results|gen-results|banks|status|iq-status|gen-status`
`POST /api/probe|start|iq-start|gen-start|bank-update|gen-rate`
`GET /works/<run>/<task>.html` — 生成作品(供沙箱 iframe)

## CLI(生产服务器直跑)

```bash
python -m llm_bench_pro.bench --url http://host:8011 --model NAME --suite standard \
    --metrics-url http://host:8011/metrics --lens 1,2,4,8,16 --conc-ladder 1,2,4,8 \
    --framework 1Cat-vLLM --fw-version 1.6.5 --tag baseline
```

## 测量口径

- TTFT = SSE 首个 content delta; 解码吞吐 = (completion_tokens-1)/流内解码跨度(usage 精确计数)
- 每次测量带唯一批次号, 防前缀缓存命中虚高; 聚合吞吐 = 轮总 token ÷ 轮墙钟(屏障同步)
- 智力判分对齐发布方: MMLU 选项匹配 / GSM8K `####` / MATH-500 boxed 规范化 / IFEval 规则校验
- 全部报告 Wilson 95% 置信区间; 题集版本不一致的对比自动警告

## License

MIT
