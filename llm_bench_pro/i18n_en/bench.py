# -*- coding: utf-8 -*-
"""bench.py 的英文词条: 中文原文 → English。规则见 CONTRIBUTING.md「服务端消息与翻译」。
带数量的 (tn) 词条写成 (单数, 复数); 占位符 {名字} 中英文必须一致; 字面的花括号写成 {{ }}; 英文里不能有汉字。"""
ENTRIES = {
    # ---- 校准长度 / 上下文超长: 有的会存进结果里 (calibration.error、length_skips 的 reason、overrides 的说明)
    "校准请求失败：{error}": "Calibration request failed: {error}",
    "服务返回的输入 token 数不随长度变化（可能没有返回真实用量）":
        "The input token count returned by the service does not change with length (it may not be returning real usage)",
    "服务返回的输入 token 数不随资料长度变化（可能没有返回真实用量）":
        "The input token count returned by the service does not change with the amount of material (it may not be "
        "returning real usage)",
    "超过模型的最大上下文（服务返回：{detail}）": "Exceeds the model's maximum context (service replied: {detail})",
    "超过模型的最大上下文（{n} token）": "Exceeds the model's maximum context ({n} tokens)",
    "每句 {unit:.1f} token，说明文字和对话模板 {overhead} token（实测）":
        "{unit:.1f} tokens per sentence, {overhead} tokens for the instructions and chat template (measured)",
    "没能校准，按旧估算每句 {unit:.1f} token（{reason}）":
        "Calibration failed; using the old estimate of {unit:.1f} tokens per sentence ({reason})",
    "  资料长度校准: 每段 {unit:.1f} token，问题和说明 {overhead} token（实测）":
        "  Material length calibration: {unit:.1f} tokens per passage, {overhead} tokens for the question and "
        "instructions (measured)",
    "  资料长度校准: 没能校准，按旧估算每段 {unit} token（{reason}）":
        "  Material length calibration: failed; using the old estimate of {unit} tokens per passage ({reason})",
    "端点不支持 ignore_eos, 输出长度未固定":
        "The endpoint does not support ignore_eos, so the output length was not fixed",
    # ---- 日志
    "  端点不支持 ignore_eos, 已关闭固定输出长度":
        "  The endpoint does not support ignore_eos; fixed output length turned off",
    "  长度校准: {text}": "  Length calibration: {text}",
    "  {label} 及更长的档位跳过: {reason}": "  {label} and longer tiers skipped: {reason}",
    "  超长输入 {label} 跳过: {reason}": "  Very long input {label} skipped: {reason}",
    "  {label} 跳过: {reason}": "  {label} skipped: {reason}",
    "矩阵 {label}": "matrix {label}",
    "  {label}: {fail}/{total} 失败, {pause:.0f}s 后重跑 (尝试 {attempt}/{max_attempts})":
        "  {label}: {fail}/{total} failed, rerunning in {pause:.0f}s (attempt {attempt}/{max_attempts})",
    "  warmup shape: 输入x{n}句 × 并发{conc}": (
        "  warmup shape: input x{n} sentence × concurrency {conc}",
        "  warmup shape: input x{n} sentences × concurrency {conc}"),
    "[phase] replay 闭环": "[phase] replay closed-loop",
    "[phase] replay 开环 (泊松到达)": "[phase] replay open-loop (Poisson arrivals)",
    "已取消: 已完成的阶段已保存": "Cancelled: completed phases have been saved",
    # ---- 场景: 图片和任务集
    "  跳过图片 {name}: {reason}": "  Skipping image {name}: {reason}",
    "  另外还跳过 {n} 张不能用的图片": ("  Also skipped {n} more unusable image", "  Also skipped {n} more unusable images"),
    "  图片池 {n} 张(内置示例图片), 每请求 {per} 张": (
        "  Image pool: {n} image (built-in samples), {per} per request",
        "  Image pool: {n} images (built-in samples), {per} per request"),
    "  图片池 {n} 张, 每请求 {per} 张": (
        "  Image pool: {n} image, {per} per request",
        "  Image pool: {n} images, {per} per request"),
    "  任务集 {n} 条": ("  Task set: {n} request", "  Task set: {n} requests"),
    "图片目录不存在: {path} (图片理解场景需要已上传的图片包或服务器图片目录)":
        "Image folder not found: {path} (the image scenario needs an uploaded image pack or a folder on the server)",
    "图片目录中没有图片(jpg/png/webp/gif): {path}": "No images (jpg/png/webp/gif) in the image folder: {path}",
    "图片目录里没有能用的图片: {path} ({reasons})": "No usable images in the image folder: {path} ({reasons})",
    # ---- 启动前的检查
    "未知任务类型: {name} (可选: {options})": "Unknown task type: {name} (choose from: {options})",
    "回放文件不存在: {path}": "Replay file not found: {path}",
    # ---- 阶段名和场景名: 存进结果的显示名 (中文模式和以前一样); 带语境, 免得和报告 / 前端里同名的标题撞键
    "阶段名|Prefill 阶梯": "Prefill ladder",
    "阶段名|单流解码": "Single-stream decode",
    "阶段名|并发阶梯": "Concurrency ladder",
    "阶段名|提示词阶梯×并发": "Prompt ladder × concurrency",
    "阶段名|长上下文驻留": "Long-context decode",
    "阶段名|场景 · {label}": "Scenario · {label}",
    "阶段名|回放·闭环": "Replay · closed-loop",
    "阶段名|回放·开环 (泊松到达)": "Replay · open-loop (Poisson arrivals)",
    "场景名|对话问答": "Chat Q&A",
    "场景名|代码生成": "Code generation",
    "场景名|结构化抽取": "Structured extraction",
    "场景名|RAG 问答": "RAG Q&A",
    "场景名|图片理解": "Image understanding",
    "场景名|自定义任务集": "Custom task set",
    # ---- 日志: 回放开环每档一行 (键里的对齐格式和以前的 %-6g / %6.2f 一样)
    "  rate={rate:<6g} sent={sent} shed={shed} ok={ok}/{total}  完成={rps:6.2f} rps  ttft_p95={ttft:6.2f}s  "
    "in-flight_max={inflight}":
        "  rate={rate:<6g} sent={sent} shed={shed} ok={ok}/{total}  completed={rps:6.2f} rps  ttft_p95={ttft:6.2f}s  "
        "in-flight_max={inflight}",
    # ---- 任务集 / 回放文件的逐行检查: 显示在上传检查报告和任务集页面里 (reason / warns / hint)
    # JSON 语法错误的说明 (接在 "near character N: " 后面, 所以是小写开头的片段)
    "第 {pos} 个字符附近：{why}": "near character {pos}: {why}",
    "第 {pos} 个字符附近": "near character {pos}",
    "缺少逗号，或者括号没有配对": "a comma is missing, or the brackets are unbalanced",
    "缺少冒号": "a colon is missing",
    "键名要用英文双引号括起来，最后一项后面不能有逗号":
        "keys must be in double quotes, and the last item cannot be followed by a comma",
    "最后一项后面不能有逗号": "the last item cannot be followed by a comma",
    "字符串没有结束（缺少英文双引号）": "the string is not closed (a closing double quote is missing)",
    "字符串里不能直接换行（要写成 \\n）": "a string cannot contain a raw line break (write it as \\n)",
    "一行里只能放一个 JSON 对象": "only one JSON object is allowed per line",
    "这里缺少值（可能多了逗号，或用了中文引号、单引号）":
        "a value is missing here (there may be an extra comma, or curly or single quotes were used)",
    "文件开头有 BOM，请存为不带 BOM 的 UTF-8": "the file starts with a BOM; save it as UTF-8 without a BOM",
    # 一行的问题 (存进 reason)
    "不是合法的 JSON（{detail}）": "Invalid JSON ({detail})",
    '每行应是一个 JSON 对象，形如 {{"messages": [...]}}': 'Each line must be a JSON object, like {{"messages": [...]}}',
    "缺少 messages（消息列表）": "Missing messages (the message list)",
    "messages 是空的": "messages is empty",
    'messages 第 {k} 条不是对象，应为 {{"role": ..., "content": ...}}':
        'Message {k} is not an object; expected {{"role": ..., "content": ...}}',
    "messages 第 {k} 条缺少 role": "Message {k} is missing role",
    "messages 第 {k} 条的 role「{role}」不认识（应为 system / user / assistant / tool）":
        'Message {k} has an unknown role "{role}" (expected system / user / assistant / tool)',
    "messages 第 {k} 条缺少 content": "Message {k} is missing content",
    'messages 第 {k} 条的 content 第 {j} 项应为 {{"type": ...}}': 'Message {k}: content item {j} must be {{"type": ...}}',
    "messages 第 {k} 条的 content 第 {j} 项缺少 text": "Message {k}: content item {j} is missing text",
    'messages 第 {k} 条的图片应写成 {{"type": "image_url", "image_url": {{"url": "..."}}}}':
        'Message {k}: an image must be written as {{"type": "image_url", "image_url": {{"url": "..."}}}}',
    "messages 第 {k} 条的 content 应为文字，或文字和图片组成的列表":
        "Message {k}: content must be text, or a list of text and images",
    # 图片的序号 i 是整行按消息顺序数的第几张 (不是这条消息里的第几张), k 是它所在的消息
    "messages 第 {k} 条的第 {i} 张图不是 base64 格式的 data URL（应为 data:image/png;base64,…）":
        "Image {i} (message {k}): not a base64 data URL (expected data:image/png;base64,…)",
    "messages 第 {k} 条的第 {i} 张图的 base64 数据已损坏": "Image {i} (message {k}): the base64 data is corrupted",
    "messages 第 {k} 条的第 {i} 张图{msg}": "Image {i} (message {k}): {msg}",
    "messages 第 {k} 条的第 {i} 张图的地址应为 data:image/…;base64,… 或 http(s) 网址":
        "Image {i} (message {k}): the address must be data:image/…;base64,… or an http(s) URL",
    'params 应为对象，如 {{"max_tokens": 512}}': 'params must be an object, like {{"max_tokens": 512}}',
    'response_format 应为 {{"type": "json_object"}} 或 {{"type": "json_schema", "json_schema": {{...}}}}':
        'response_format must be {{"type": "json_object"}} or {{"type": "json_schema", "json_schema": {{...}}}}',
    'json_schema 应写成 {{"name": "名字", "schema": {{JSON Schema}}}}':
        'json_schema must be written as {{"name": "my_schema", "schema": {{JSON Schema}}}}',
    "temperature 应为不小于 0 的数字": "temperature must be a number not less than 0",
    "输入约 {tokens} token，超过 {limit} 的上限，跳过": "Input is about {tokens} tokens, over the limit of {limit}; skipped",
    # 提醒 (存进 warns; 这些行照常发送)
    "第 {i} 张图是网址，模型服务需要能访问到它": "Image {i} is a URL; the model service must be able to reach it",
    "第 {i} 张图{msg}": "Image {i}: {msg}",
    "{key} 不是正整数，会按默认 {default}": "{key} is not a positive integer; the default of {default} will be used",
    "{key} 是 {n}，超过上限，会按 {cap}": "{key} is {n}, which is over the limit; {cap} will be used",
    # 整个文件的提示 (hint)
    "整个文件是一个 JSON 数组；任务集要求每行一个 JSON 对象（JSONL），可以参考「下载模板」":
        'The whole file is a single JSON array, but a task set needs one JSON object per line (JSONL). '
        'See "Download template" for an example.',
    "一个请求被排版成了多行；任务集要求每个请求写在一行里（JSONL），可以参考「下载模板」":
        'A request is spread over several lines, but a task set needs each request on a single line (JSONL). '
        'See "Download template" for an example.',
    "文件里没有可用请求: {path} (没有消息或超长跳过 {skipped} 行, 格式不对 {bad} 行)":
        "No usable requests in the file: {path} ({skipped} skipped for having no messages or being too long, "
        "{bad} with a bad format)",
    # ---- 命令行: 选项说明 (--help) 和参数格式错误
    "llm-bench-pro 推理基准引擎": "llm-bench-pro inference benchmark engine",
    "完整 chat completions URL (或 base URL, 自动规整)":
        "Full chat completions URL (or a base URL; it is normalized automatically)",
    "vLLM /metrics 地址 (框架指标抓取)": "vLLM /metrics URL (for scraping framework metrics)",
    "运行标签, 如 '1.6.5 vs 1.6.3'": "Run tag, e.g. '1.6.5 vs 1.6.3'",
    "结果目录 (默认 data/results/, 页面服务启动时自动导入)":
        "Results directory (default: data/results/; imported automatically when the web service starts)",
    "自定义套件 JSON 文件 (suite=custom 时)": "Custom suite JSON file (used when suite=custom)",
    "自定义并发阶梯, 逗号分隔, 如 1,2,4,8": "Custom concurrency ladder, comma-separated, e.g. 1,2,4,8",
    "提示词阶梯x并发的并发路数 (默认 4)": "Concurrency for the prompt ladder x concurrency matrix (default: 4)",
    "自定义长度阶梯(K), 逗号分隔, 如 1,2,4,8,16": "Custom input-length ladder (in K), comma-separated, e.g. 1,2,4,8,16",
    "后端框架名称, 如 1Cat-vLLM / vLLM / SGLang": "Backend framework name, e.g. 1Cat-vLLM / vLLM / SGLang",
    "框架版本号, 如 1.6.5-sm70main": "Framework version, e.g. 1.6.5-sm70main",
    "不发送 ignore_eos(允许模型提前结束输出)": "Do not send ignore_eos (let the model end its output early)",
    "任务场景, 逗号分隔: chat/code/json/rag/vision/custom (默认不启用任何场景)":
        "Scenarios to run, comma-separated: chat/code/json/rag/vision/custom (none by default)",
    "任务场景并发列表, 逗号分隔, 如 4,8 (默认 4,8)": "Scenario concurrency list, comma-separated, e.g. 4,8 (default: 4,8)",
    "任务场景每并发请求数 (默认 3)": "Requests per worker in each scenario (default: 3)",
    "RAG 场景上下文档位(token), 逗号分隔, 如 1500,4000,16000":
        "Context tiers for the RAG scenario (in tokens), comma-separated, e.g. 1500,4000,16000",
    "图片理解场景的图片目录(服务器路径); 不填用内置示例图片":
        "Image folder for the image scenario (a server path); built-in sample images are used if omitted",
    "图片理解每请求图片数 1-4 (默认 1)": "Images per request in the image scenario, 1-4 (default: 1)",
    "自定义任务集 JSONL (每行 {{messages, params}})": "Custom task set JSONL (one {{messages, params}} per line)",
    "真实请求回放 JSONL 文件 (每行 {{messages, params}})":
        "Real-request replay JSONL file (one {{messages, params}} per line)",
    "回放闭环并发列表, 逗号分隔, 如 8,16": "Closed-loop replay concurrency list, comma-separated, e.g. 8,16",
    "回放开环速率列表(req/s), 逗号分隔, 如 2,5; 传了才跑开环":
        "Open-loop replay rate list (req/s), comma-separated, e.g. 2,5; open-loop runs only if given",
    "开环每档速率持续秒数 (默认 60)": "Duration in seconds of each open-loop rate (default: 60)",
    "关闭按 batch shape 的预热": "Turn off warmup by batch shape",
    "结果落地: json=outdir 文件(默认) / db=SQLite 库 / both":
        "Where to save results: json = files in outdir (default) / db = SQLite database / both",
    "SQLite 库路径 (默认 data/llm_bench.db 或 $LLM_BENCH_DB)":
        "SQLite database path (default: data/llm_bench.db or $LLM_BENCH_DB)",
    "--conc-ladder 格式错误, 应为逗号分隔整数": "Invalid --conc-ladder: expected comma-separated integers",
    "--lens 格式错误: 应为 1-256 的逗号分隔整数(K)": "Invalid --lens: expected comma-separated integers from 1 to 256 (in K)",
    "{flag} 格式错误, 应为逗号分隔整数": "Invalid {flag}: expected comma-separated integers",
    "--replay-rates 格式错误, 应为逗号分隔数字": "Invalid --replay-rates: expected comma-separated numbers",
}
