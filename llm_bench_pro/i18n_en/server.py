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
