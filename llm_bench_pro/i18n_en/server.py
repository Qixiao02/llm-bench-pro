# -*- coding: utf-8 -*-
"""server.py 的英文词条: 中文原文 → English。规则见 CONTRIBUTING.md「服务端消息与翻译」。
带数量的 (tn) 词条写成 (单数, 复数); 占位符 {名字} 中英文必须一致; 字面的花括号写成 {{ }}; 英文里不能有汉字。"""
ENTRIES = {
    # ---- 任务名 (job_name): 放进「Another …」「The …」这样的句子里, 所以用小写、不带冠词
    "任务名|性能测试": "speed test",
    "任务名|能力评测": "capability test",
    "任务名|代码生成": "code generation run",
    "任务名|题集更新": "question set update",
    "已有{name}在运行": "Another {name} is already running",
    "没有运行中的{name}": "No {name} is running",
    "{name}正在使用同一模型端点。同时运行会使性能测试的吞吐和延迟数据失真。":
        "The {name} is using the same model endpoint. Running both at the same time would distort the "
        "throughput and latency data of the speed test.",
    "job 应为 perf / iq / gen / bank": "job must be one of perf / iq / gen / bank",
    "收到停止请求：不再开始新的请求，已完成的结果会保留":
        "Stop requested: no new requests will be started, and results already completed are kept",
    # ---- 启动速度测试: 存进结果里的说明
    "其他测试": "other test",
    "启动时{name}正在使用同一端点，数据可能受干扰":
        "The {name} was using the same endpoint when this run started, so the data may be affected",
    # ---- 请求的基本检查 / 访问令牌
    "需要访问令牌": "Access token required",
    "该服务启用了访问令牌，请使用 <code>http://主机:端口/?token=令牌</code> 打开。":
        "This service requires an access token. Open it with <code>http://HOST:PORT/?token=TOKEN</code>.",
    "拒绝跨源请求": "Cross-origin requests are not allowed",
    "Content-Type 必须为 application/json": "Content-Type must be application/json",
    # ---- 测试连接
    "base / api_key 应为文字": "base and api_key must be strings",
    # ---- 任务集页面
    "任务集 id 不对（应为 scn- 加 12 位十六进制数字）": "Invalid task set id (expected scn- followed by 12 hex digits)",
    "任务集不存在（可能已被删除）": "The task set does not exist (it may have been deleted)",
    "offset / limit 应为整数": "offset and limit must be integers",
    "offset 不能小于 0，limit 应为 1–{max}": "offset must be at least 0 and limit must be between 1 and {max}",
    "status 应为 {options} 之一": "status must be one of {options}",
    "line 应为行号": "line must be a line number",
    "没有第 {no} 行（或者这一行是空行）": "There is no line {no} (or that line is blank)",
    "line / idx 应为整数": "line and idx must be integers",
    "name 应为文字": "name must be a string",
    "有速度测试正在用这个任务集，等测试结束（或停止它）之后再删除":
        "A speed test is using this task set. Delete it after the test finishes (or stop the test).",
    # ---- 模型管理页面
    "模型 id 不对（应为 ep_ 开头的字母、数字、下划线）": "Invalid model id (expected ep_ followed by letters, digits or underscores)",
    "这个模型不存在（可能已被删除）": "This model does not exist (it may have been deleted)",
    "kind 应为 all / perf / iq / gen 之一": "kind must be one of all / perf / iq / gen",
    "limit 应为整数": "limit must be an integer",
    "limit 应为 1–{max}": "limit must be between 1 and {max}",
    # ---- 查看 / 删除 / 评分: run_id 和测试是否存在
    "非法 run_id": "Invalid run_id",
    "run 不存在": "The run does not exist",
    "非法对比 run_id": "Invalid comparison run_id",
    "非法题号": "Invalid question number",
    "非法 cmp run_id": "Invalid cmp run_id",
    "cmp run 不存在": "The cmp run does not exist",
    "cmp 格式错误": "Invalid cmp format",
    "该运行尚未结束，请先停止": "This run is still in progress. Stop it first.",
    "run 或作品不存在": "The run or generated page does not exist",
    "stars 应为 0-5 整数或 null": "stars must be an integer from 0 to 5, or null",
    # ---- 导出离线报告
    "不支持导出这个页面": "This page cannot be exported",
    "一次最多导出 7 次测试": "You can export at most 7 tests at a time",
    "非法 run_id: {id}": "Invalid run_id: {id}",
    "测试不存在: {ids}": ("The test does not exist: {ids}", "These tests do not exist: {ids}"),
    # ---- 启动测试: 参数检查
    "缺少 base/model": "base and model are required",
    "缺少 base/model/bank_id": "base, model and bank_id are required",
    "未知测试套件": "Unknown test suite",
    "并发梯度格式错误：应为 1-128 的逗号分隔整数，如 1,2,4,8":
        "Invalid concurrency ladder: expected comma-separated integers from 1 to 128, e.g. 1,2,4,8",
    "矩阵并发数应为 1-32 的整数": "The matrix concurrency must be an integer from 1 to 32",
    "输入长度梯度格式错误：应为 1-256 的逗号分隔整数（K），如 1,2,4,8,16":
        "Invalid input length ladder: expected comma-separated integers from 1 to 256 (in K tokens), e.g. 1,2,4,8,16",
    "场景配置错误：{error}": "Invalid scenario settings: {error}",
    "参数错误：{error}": "Invalid parameters: {error}",
    "并发应为整数": "Concurrency must be an integer",
    "subjects 应为科目 id 列表": "subjects must be a list of subject ids",
    "sampling 格式错误": "Invalid sampling format",
    "{name} 超出范围 {lo}–{hi}": "{name} must be between {lo} and {hi}",
    "{name} 应为逗号分隔整数列表": "{name} must be a comma-separated list of integers",
    "{name} 应为整数列表": "{name} must be a list of integers",
    "{name} 超出范围 {lo}-{hi}": "{name} must be between {lo} and {hi}",
    # ---- 启动测试: 任务场景 (scenarios) 和真实请求回放 (replay) 的检查
    "scenarios 应为对象": "scenarios must be an object",
    "tasks 应为任务类型列表": "tasks must be a list of task types",
    "未知任务类型 {name} (可选: {options})": "Unknown task type {name} (choose from: {options})",
    "tasks 里有重复的任务类型": "tasks contains duplicate task types",
    "requests_per_worker / max_tokens 应为整数": "requests_per_worker and max_tokens must be integers",
    "vision_src 应为对象": "vision_src must be an object",
    "非法 image_id": "Invalid image_id",
    "图片包 {name} 不存在（可能已被删除），请重新上传或改用内置示例图片":
        "Image pack {name} does not exist (it may have been deleted). Upload it again or use the built-in sample images.",
    "服务器上没有这个图片文件夹: {dir}": "There is no such image folder on the server: {dir}",
    "图片包 {name} 里没有图片（支持 jpg / png / webp / gif）":
        "Image pack {name} contains no images (supported: jpg / png / webp / gif)",
    "图片文件夹 {name} 里没有图片（支持 jpg / png / webp / gif）":
        "Image folder {name} contains no images (supported: jpg / png / webp / gif)",
    "图片包 {name} 里没有能用的图片：{detail}。请重新上传，或改用内置示例图片":
        "Image pack {name} has no usable images: {detail}. Upload it again or use the built-in sample images.",
    "图片文件夹 {name} 里没有能用的图片：{detail}。请重新上传，或改用内置示例图片":
        "Image folder {name} has no usable images: {detail}. Upload them again or use the built-in sample images.",
    "vision_src.images 应为 1-4 的整数": "vision_src.images must be an integer from 1 to 4",
    "非法 custom_file_id": "Invalid custom_file_id",
    "任务集不存在: {id} (可能已被删除, 请重新导入)":
        "The task set does not exist: {id} (it may have been deleted; import it again)",
    "任务集文件不存在: {path}": "The task set file does not exist: {path}",
    "自定义任务集需要选择已上传的任务集或填写服务器文件路径":
        "A custom task set needs an imported task set or a file path on the server",
    "replay 应为对象": "replay must be an object",
    "非法 file_id": "Invalid file_id",
    "回放文件不存在: {id} (可能已被删除, 请重新上传)":
        "The replay file does not exist: {id} (it may have been deleted; upload it again)",
    "replay 需要 file_id(上传的文件)或 file(服务器路径)":
        "replay needs either file_id (an uploaded file) or file (a path on the server)",
    "replay.closed 应为对象": "replay.closed must be an object",
    "replay.closed.requests_per_worker 应为整数": "replay.closed.requests_per_worker must be an integer",
    "replay.open 应为对象": "replay.open must be an object",
    "replay.open.rates 应为数字列表": "replay.open.rates must be a list of numbers",
    "replay.open.rates 需要至少一个 0.05-1000 的速率": "replay.open.rates needs at least one rate between 0.05 and 1000",
    # ---- 上传任务集 / 图片包 / 回放文件
    "缺少文件内容 (content 应为 JSONL 文本)": "Missing file content (content must be JSONL text)",
    "文件超过 15MB 上限; 大文件请放到服务器后用路径引用":
        "The file exceeds the 15MB limit. For large files, put them on the server and reference them by path.",
    "第 {line} 行：{reason}": "Line {line}: {reason}",
    "没有一行能用（{first}）": "No usable lines ({first})",
    "没有一行能用": "No usable lines",
    '没有可用行: 每行应为 {{"messages": [...], "params": {{...}}}}':
        'No usable lines: each line must be {{"messages": [...], "params": {{...}}}}',
    "缺少 files: [{{name, data(base64)}}]": "Missing files: [{{name, data(base64)}}]",
    "第 {n} 张": "Image {n}",
    "一次最多上传 {max} 张，这张没有收": "At most {max} images can be uploaded at a time; this one was not accepted",
    "不是支持的图片类型（只收 jpg / png / webp / gif）": "Unsupported image type (only jpg / png / webp / gif are accepted)",
    "上传的数据不是合法的 base64": "The uploaded data is not valid base64",
    "没有能用的图片：{detail}": "No usable images: {detail}",
    "kind 应为 tasks 或 images": "kind must be tasks or images",
    # ---- 代码生成的重新评测 / 题集更新 (任务的标题、日志) / 能力评测续跑
    "已有代码生成任务或重新评测在运行": "Another code generation run or re-evaluation is already running",
    "重新评测": "Re-evaluation",
    "更新题集": "Question set update",
    "题集正在更新中": "A question set update is already in progress",
    "已停止：已经下载好的题集数据留在本地，下次不用重新下载":
        "Stopped: the question set data already downloaded stays on this machine, so it will not be downloaded again next time",
    "提示：可以换一个「题集下载源」或填「下载用的代理」再试；没有网的机器，把能联网机器上的 data/datasets/ 拷贝过来即可离线生成":
        'Tip: try a different "Question set download source" or set a "Download proxy", then retry. On a machine without '
        'internet access, copy data/datasets/ from a machine that is online to build the question sets offline',
    "只有已停止、中断、失败或含请求失败题目的运行可以续跑":
        "Only runs that were stopped, interrupted or failed, or that contain questions with failed requests, can be resumed",
    "该运行由评测程序 {old} 生成，当前为 {new}，判分口径不同，不能续跑，请重新运行":
        "This run was made with capability test version {old}; the current version is {new}. Scoring differs between "
        "versions, so it cannot be resumed. Run the test again instead.",
    # ---- 命令行: --help 和启动输出
    "LLM Bench Pro 服务": "LLM Bench Pro server",
    "监听端口 (默认 18080)": "Port to listen on (default 18080)",
    "监听地址 (默认 127.0.0.1 仅本机; 局域网访问用 0.0.0.0, 建议同时设置 --token)":
        "Address to listen on (default 127.0.0.1, this machine only; use 0.0.0.0 for LAN access and set --token as well)",
    "访问令牌; 设置后需用 http://主机:端口/?token=令牌 打开页面":
        "Access token; when set, open the page with http://HOST:PORT/?token=TOKEN",
    "{name}/ 已搬到 data/{name}/": "{name}/ was moved to data/{name}/",
    "{name}/ 里有 {n} 项和 data/{name}/ 重名，没有搬动，请手动核对后删除旧目录": (
        "{name}/ has {n} item with the same name in data/{name}/. It was not moved; please check it and delete "
        "the old directory manually",
        "{name}/ has {n} items with the same name in data/{name}/. They were not moved; please check them and "
        "delete the old directory manually"),
    "{name}/ 已并入 data/{name}/": "{name}/ was merged into data/{name}/",
    "{name}/ 搬到 data/ 失败（{error}）。请关掉占用这些文件的程序后重启服务，或手动搬到 data/{name}/":
        "Moving {name}/ to data/ failed ({error}). Close any program that is using these files and restart the "
        "service, or move it to data/{name}/ manually",
    "✗ 无法监听 {host}:{port}（{error}）\n  端口可能已被占用，常见原因是已有 LLM Bench Pro 在运行。\n  请先关闭旧进程，或换一个端口：python run.py {next_port}":
        "✗ Cannot listen on {host}:{port} ({error})\n  The port may already be in use, most often because LLM Bench Pro is "
        "already running.\n  Close the old process first, or use another port: python run.py {next_port}",
    "  {mark} 目录调整：{text}": "  {mark} Directory change: {text}",
    "  ⚠ 正在监听 {host} 且未设置访问令牌：局域网内任何人都可以发起测试、查看结果。建议加 --token":
        "  ⚠ Listening on {host} without an access token: anyone on the network can start tests and view results. "
        "Consider adding --token",
    "  导入旧 JSON {inserted} 个, 失败 {failed} 个, 标记中断 {stale} 个":
        "  Old JSON import: {inserted} imported, {failed} failed, {stale} marked as interrupted",
}
