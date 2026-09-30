# -*- coding: utf-8 -*-
"""report.py 的英文词条: 中文原文 → English。规则见 CONTRIBUTING.md「服务端消息与翻译」。
带数量的 (tn) 词条写成 (单数, 复数); 占位符 {名字} 中英文必须一致; 字面的花括号写成 {{ }}; 英文里不能有汉字。

旧版 HTML 报告 (GET /api/report): 页面上的文字、表头、图表说明、结论、方法说明、页脚都在这里。
 - 键带语境的 (表头 / 表格 / 徽章 / 图例 / 场景名 / 解码语言): 都是几个字的短词, 单独一个词在别的模块里可能是另一个意思, 用语境隔开
 - 结论要点 (findings) 和测量口径每条是完整的句子, 用句号结尾; 各节下面的小字说明、表头、标签是片段, 不加句号
 - 词条里的 <b> 之类标签和中文原文里的用法一致 (只有强调的那个词用到)"""
ENTRIES = {
    # ---- 通用: 表格和图表里的短文字
    "无在途采样数据": "No in-flight samples",
    "时间 (s)": "Time (s)",
    "表格|无数据": "No data",
    "表格|是": "Yes",
    # ---- 顶部指标卡 (KPI)
    "最高并发聚合吞吐": "Aggregate throughput at max concurrency",
    "单流解码吞吐": "Single-stream decode throughput",
    "最高并发 TTFT p95": "TTFT p95 at max concurrency",
    "Prefill 吞吐(峰值中位)": "Prefill throughput (peak median)",
    # ---- 结论要点
    "章节|结论要点": "Key findings",
    "并发 {conc} 下聚合吞吐: {who} 更高 {pct:.1f}%（{a} vs {b} tok/s）":
        "Aggregate throughput at concurrency {conc}: {who} is {pct:.1f}% higher ({a} vs {b} tok/s).",
    "并发 {conc} 下 TTFT p95: {who} 更低 {pct:.1f}%（{a} vs {b} s）":
        "TTFT p95 at concurrency {conc}: {who} is {pct:.1f}% lower ({a} vs {b} s).",
    "⚠ 两次运行的固定输出长度(ignore_eos)设置不一致, 吞吐不可直接比较":
        "⚠ The two runs used different fixed-output-length (ignore_eos) settings, so their throughput cannot be "
        "compared directly.",
    "⚠ 本次运行未固定输出长度(端点不支持 ignore_eos), 模型提前结束时吞吐会偏低, 跨后端对比需注意口径":
        "⚠ This run did not fix the output length (the endpoint does not support ignore_eos). Throughput reads low "
        "when the model stops early, so be careful when comparing across backends.",
    "{n} 个格子失败后整格重跑(明细见「失败与重跑」)": (
        "{n} cell had failures, so the whole cell was rerun (see \"Failures and reruns\" for details).",
        "{n} cells had failures, so each whole cell was rerun (see \"Failures and reruns\" for details)."),
    "共 {n} 个请求失败(已计入失败率, 未从结果中剔除)": (
        "{n} request failed in total (counted in the failure rate, not removed from the results).",
        "{n} requests failed in total (counted in the failure rate, not removed from the results)."),
    "⚠ 场景「{label}」JSON 合法率最低 {pct:.0f}% (并发 {conc}): 结构化输出稳定性需关注":
        "⚠ Scenario \"{label}\" has a JSON validity rate as low as {pct:.0f}% (concurrency {conc}); "
        "structured-output stability needs attention.",
    "⚠ 开环速率 {rate:g} req/s 下只完成 {done:g} req/s (最大在途 {inflight}): 到达速率已超过服务能力, 请求越排越长":
        "⚠ At an open-loop rate of {rate:g} req/s only {done:g} req/s completed (max in-flight {inflight}): the "
        "arrival rate exceeds what the service can handle, so requests queue up longer and longer.",
    "⚠ 开环速率 {rate:g} 有 {n} 个请求因在途超限({cap})被丢弃计数": (
        "⚠ At open-loop rate {rate:g}, {n} request was dropped and counted because it exceeded the in-flight limit ({cap}).",
        "⚠ At open-loop rate {rate:g}, {n} requests were dropped and counted because they exceeded the in-flight limit ({cap})."),
    "回放池已回绕: 部分请求被重复发送, 若端点前缀缓存跨格生效, 后段吞吐可能偏高":
        "The replay pool wrapped around: some requests were sent more than once, so if the endpoint's prefix cache "
        "persists across cells, throughput in later cells may read high.",
    "未发现需要关注的异常; 各阶段请求全部成功": "No anomalies found; all requests succeeded in every phase.",
    # ---- 输入长度标签: 旧结果按旧估算拼长输入, 实际长度和标称差得多时显示实际长度
    "{size}K（原标 {label}）": "{size}K (nominal {label})",
    # ---- Prefill 阶梯
    "图例|Prefill 吞吐 A": "Prefill throughput A",
    "章节|Prefill 阶梯": "Prefill ladder",
    "表头|输入长度": "Input length",
    "表头|Prefill 吞吐 tok/s": "Prefill throughput tok/s",
    "单并发, 每档重复取中位; 唯一批次号避免前缀缓存命中虚高":
        "Concurrency 1, median of repeated runs per tier; unique batch IDs avoid inflated prefix-cache hits",
    # ---- 提示词长度 x 并发矩阵
    "重跑×{n}": "Rerun ×{n}",
    "章节|提示词长度 × 并发矩阵 (并发 {conc})": "Prompt length × concurrency matrix (concurrency {conc})",
    "表头|档位": "Tier",
    "表头|TTFT 均值 ms": "TTFT avg ms",
    "表头|ITL p50 均值 ms": "ITL p50 avg ms",
    "表头|Prefill 聚合 tok/s": "Prefill aggregate tok/s",
    "表头|Decode 聚合 tok/s": "Decode aggregate tok/s",
    "屏障同步起跑; 聚合吞吐 = 该档全部成功请求的 token ÷ 最大单请求耗时":
        "Barrier-synchronized start; aggregate throughput = tokens of all successful requests in the tier ÷ the "
        "longest single-request time",
    # ---- 并发阶梯
    "图例|聚合吞吐 A": "Aggregate throughput A",
    "章节|并发阶梯": "Concurrency ladder",
    "表头|并发": "Concurrency",
    "表头|聚合吞吐 tok/s": "Aggregate throughput tok/s",
    "表头|单流吞吐 tok/s": "Per-stream throughput tok/s",
    "实线=聚合吞吐(左轴), 虚线=TTFT p95(右轴); 固定输出长度(ignore_eos)保证跨后端可比":
        "Solid line = aggregate throughput (left axis), dashed line = TTFT p95 (right axis); fixed output length "
        "(ignore_eos) keeps results comparable across backends",
    "实线=聚合吞吐(左轴), 虚线=TTFT p95(右轴); 本次未固定输出长度":
        "Solid line = aggregate throughput (left axis), dashed line = TTFT p95 (right axis); output length was not "
        "fixed in this run",
    # ---- 单流解码
    "解码语言|中文": "Chinese",
    "解码语言|英文": "English",
    "章节|单流解码": "Single-stream decode",
    "表头|语言": "Language",
    "表头|输出 tokens": "Output tokens",
    "表头|吞吐 tok/s": "Throughput tok/s",
    "表头|最佳 tok/s": "Best tok/s",
    "表头|投机 burst tok/chunk": "Spec burst tok/chunk",
    "spec_burst > 1 提示投机采样生效(每 chunk 平均 token 数)":
        "spec_burst > 1 means speculative decoding is active (average tokens per chunk)",
    # ---- 场景
    "表头|上下文 tokens": "Context tokens",
    "表头|请求/秒": "Req/s",
    "表头|端到端 p95 s": "E2E p95 s",
    "表头|输出 tokens 均值": "Out tokens avg",
    "表头|最大在途": "Max in-flight",
    "表头|JSON 合法": "JSON valid",
    "章节|场景 · {label}": "Scenario · {label}",
    "任务模板: {label} · max_tokens {max_tokens} · 每并发 {rpw} 请求 · 不发送 ignore_eos, 测真实任务行为":
        "Task template: {label} · max_tokens {max_tokens} · requests per worker {rpw} · ignore_eos is not sent, so "
        "real task behavior is measured",
    "图片 {n} 张/请求": "images per request {n}",
    "任务集 {n} 条": "task set size {n}",
    "图片池 {n} 张(内置示例图片)": (
        "image pool: {n} image (built-in samples)",
        "image pool: {n} images (built-in samples)"),
    "图片池 {n} 张": ("image pool: {n} image", "image pool: {n} images"),
    "另有 {n} 张不能用已跳过": ("{n} more unusable image skipped", "{n} more unusable images skipped"),
    # ---- 真实请求回放: 闭环
    "章节|真实请求回放 · 闭环": "Real-request replay · closed-loop",
    "表头|入 tokens 均值": "In tokens avg",
    "表头|出 tokens 均值": "Out tokens avg",
    "表头|池回绕": "Pool wrapped",
    "回放池 {size} 条(跳过 {skipped}, 坏行 {bad}); cursor 跨格推进避免重复请求命中前缀缓存": (
        "Replay pool: {size} request (skipped {skipped}, bad lines {bad}); the cursor advances across cells so "
        "repeated requests do not hit the prefix cache",
        "Replay pool: {size} requests (skipped {skipped}, bad lines {bad}); the cursor advances across cells so "
        "repeated requests do not hit the prefix cache"),
    # ---- 真实请求回放: 开环
    "章节|真实请求回放 · 开环 (泊松到达)": "Real-request replay · open-loop (Poisson arrivals)",
    "表头|速率 req/s": "Rate req/s",
    "表头|发送": "Sent",
    "表头|丢弃": "Dropped",
    "表头|完成 req/s": "Completed req/s",
    "{done} / 目标 {rate:g}": "{done} / target {rate:g}",
    "在途请求时间线 · {rate:g} req/s": "In-flight request timeline · {rate:g} req/s",
    "(峰值 {peak}, 曲线持续抬升 = 排队堆积)": "(peak {peak}; a steadily rising curve means requests are piling up)",
    "泊松到达持续 {duration} 秒(固定种子, 两次运行到达时间轴相同); 在途上限 {cap}, 超限丢弃并计数":
        "Poisson arrivals for {duration}s (fixed seed, so both runs share the same arrival timeline); in-flight "
        "limit {cap}, requests over the limit are dropped and counted",
    # ---- 失败与重跑披露
    "章节|失败与重跑披露": "Failures and reruns",
    "表头|运行": "Run",
    "表头|阶段": "Phase",
    "表头|尝试": "Attempt",
    "表头|错误样本": "Error sample",
    "整格重跑: 有失败的格子等 30s 后重跑(最多 3 次), 这里列出每轮失败; 最终结果以最后一轮为准":
        "Rerun the whole cell: a cell with failures waits 30s and runs again (up to 3 times); every failed round is "
        "listed here, and the final result comes from the last round",
    # ---- 顶部信息: 徽章和运行表
    "徽章|套件": "Suite",
    "徽章|框架": "Framework",
    "徽章|框架版本": "Framework version",
    "徽章|标签": "Tag",
    "表头|模型": "Model",
    "表头|开始时间 (UTC)": "Start time (UTC)",
    # ---- 测量口径 (每条一个整句)
    "章节|测量口径": "Methodology",
    "TTFT = SSE 首个 content/reasoning 增量; 解码吞吐 = (completion_tokens−1)/流内解码跨度(usage 精确计数)":
        "TTFT = the first content/reasoning delta in the SSE stream; decode throughput = (completion_tokens-1) / "
        "the decode time span inside the stream (exact token count from usage).",
    "主流程默认固定输出长度(ignore_eos)保证不同后端吞吐可比; 业务/回放场景<b>不</b>发送 ignore_eos, 测真实任务行为":
        "The main flow fixes the output length by default (ignore_eos) so throughput is comparable across "
        "backends; scenario and replay runs do <b>not</b> send ignore_eos, so they measure real task behavior.",
    "每次测量带唯一批次号防前缀缓存命中虚高; 并发轮屏障同步起跑; 聚合吞吐 = 轮总 token ÷ 轮墙钟":
        "Every measurement carries a unique batch ID so prefix-cache hits do not inflate the results; concurrent "
        "rounds start together at a barrier; aggregate throughput = total tokens in the round ÷ wall-clock time "
        "of the round.",
    'TTFT/TPOT/端到端分位均"先逐请求计算、再排序取分位", 非聚合比值':
        "TTFT, TPOT and end-to-end percentiles are all computed per request first and then sorted to take the "
        "percentile, not ratios of aggregates.",
    "开环回放为泊松到达、绝对时间调度(无累计漂移), 到达时间轴按固定种子生成 — 两次运行的对比收到相同到达序列":
        "Open-loop replay uses Poisson arrivals scheduled in absolute time (no cumulative drift), with the arrival "
        "timeline generated from a fixed seed, so both runs in a comparison receive the same arrival sequence.",
    "失败请求计为失败并保留错误样本; 基础设施型失败的格子整格重跑(最多 3 次)并全量披露":
        "Failed requests are counted as failures and their error samples are kept; cells with infrastructure-type "
        "failures are rerun whole (up to 3 times) and fully disclosed.",
    # ---- 页面标题、错误、页脚
    "仅支持性能测试运行 (run_*) 的报告": "Reports are only available for speed test runs (run_*)",
    "{model} 压测报告": "{model} speed test report",
    "A/B 对比": "A/B comparison",
    "LLM Bench Pro v{app} · 报告生成 v{report} · 引擎 v{engine} · 生成于 {time} (UTC) · 数据与口径详见各节说明; 本文件自包含, 可离线打开与打印":
        "LLM Bench Pro v{app} · report generator v{report} · engine v{engine} · generated {time} (UTC) · see the "
        "notes in each section for data and methodology; this file is self-contained and can be opened and printed "
        "offline",
}
