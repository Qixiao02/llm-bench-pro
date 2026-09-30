# -*- coding: utf-8 -*-
"""bankman.py 的英文词条: 中文原文 → English。规则见 CONTRIBUTING.md「服务端消息与翻译」。
带数量的 (tn) 词条写成 (单数, 复数); 占位符 {名字} 中英文必须一致; 字面的花括号写成 {{ }}; 英文里不能有汉字。
科目名 (GSM8K 数学、MMLU 中学 ……) 会进题库文件的内容哈希, 不随语言变, 不在这里 (登记在 tests/i18n_py_allow.txt)。"""
ENTRIES = {
    # ---- 下载源偏好和下载途径的名称 (日志和错误说明里用; 本地数据的 source 字段存的一直是中文名, 显示时才换成当前语言,
    #      见 bankman.route_key / source_text。GitHub / HuggingFace / hf-mirror 是专有名称, 不翻)
    "魔搭（国内）": "ModelScope (China)",
    "GitHub / HuggingFace（海外）": "GitHub / HuggingFace (overseas)",
    "魔搭 OSS": "ModelScope OSS",
    "魔搭": "ModelScope",
    "魔搭 OSS（杭州）": "ModelScope OSS (Hangzhou)",
    # 题集名之间的分隔 (中文用顿号, 英文用逗号); 用语境单独成词条, 免得和别的模块的「、」撞键
    "题集名列表|、": ", ",
    # ---- 停止 / 下载途径的错误 (会出现在任务日志和「更新题集」的失败原因里)
    "更新题集|已停止": "Stopped",
    "服务器不支持分段下载": "The server does not support partial downloads (HTTP Range requests)",
    "GitHub 和它的镜像都连不上": "Can't connect to GitHub or any of its mirrors",
    "      用的是 {host}": "      Using {host}",
    "GitHub 镜像下载失败：{error}": "Download from the GitHub mirrors failed: {error}",
    "压缩包里缺少科目: {names}": "Subjects missing from the archive: {names}",
    "压缩包里没有 ARC-Challenge-Test.jsonl": "ARC-Challenge-Test.jsonl not found in the archive",
    # ---- 逐个途径尝试 (first_ok)
    "      {name}：从{label}下载完成，{mb:.1f} MB，{secs:.1f} 秒": "      {name}: downloaded from {label}, {mb:.1f} MB, {secs:.1f} s",
    "{label}（{msg}）": "{label} ({msg})",
    "      {name}：{label}不可用（{msg}），换下一个": "      {name}: {label} unavailable ({msg}), trying the next one",
    "{name} 所有下载途径都失败：{errors}": "All download routes for {name} failed: {errors}",
    # ---- 下载 (download)
    "进度 {done} / {total} · {name}": "Progress {done} / {total} · {name}",
    "  [{i}/{total}] {name}：本地已有，跳过下载": "  [{i}/{total}] {name}: already available locally, skipping download",
    "  [{i}/{total}] {name}：开始下载（{mode}优先）": "  [{i}/{total}] {name}: starting download, trying {mode} first",
    "进度 {done} / {total} · 数据已在本地": "Progress {done} / {total} · data is local",
    # ---- 抽样
    "MMLU 科目 {subject} 有效题目不足 {n} 道": (
        "MMLU subject {subject} has fewer than {n} valid question",
        "MMLU subject {subject} has fewer than {n} valid questions"),
    "C-Eval 科目 {subject} 有效题目不足 {n} 道": (
        "C-Eval subject {subject} has fewer than {n} valid question",
        "C-Eval subject {subject} has fewer than {n} valid questions"),
    # ---- 生成题库 (build)
    "离线模式下本地缺少这些题集的数据：{names}。请在能联网的机器上先更新一次题集，再把 {path} 拷贝过来":
        "Offline mode is on, but local data is missing for {names}. Update the question sets once on a machine with "
        "internet access, then copy {path} over.",
    "下载源：{mode}；本地缺少 {n} 个题集的数据，先下载到 {path}": (
        "Download source: {mode}; {n} question set has no local data yet, downloading it to {path} first",
        "Download source: {mode}; {n} question sets have no local data yet, downloading them to {path} first"),
    "全部题集的数据都已在本地（{path}），不需要联网": "All question set data is already local ({path}); no network needed",
    "从本地数据生成题库…": "Building the question bank from local data...",
    "题集 {id} 为空，题库未生成": "Question set {id} is empty; the question bank was not generated",
    "题库和已有的 {bank_id} 完全相同（内容一样，id 一样），不用新增":
        "The question bank is identical to the existing {bank_id} (same content, same id); nothing new to add",
    "已生成新题库 {bank_id}": "Generated a new question bank: {bank_id}",
    "完成：{bank_id}，共 {n} 题；本次下载 {mb:.1f} MB，用时 {secs:.0f} 秒": (
        "Done: {bank_id}, {n} question; downloaded {mb:.1f} MB this time, took {secs:.0f} s",
        "Done: {bank_id}, {n} questions; downloaded {mb:.1f} MB this time, took {secs:.0f} s"),
    "题库不存在: {bank_id}": "Question bank not found: {bank_id}",
    # ---- 命令行
    "能力评测题库: 下载数据到本地 / 从本地数据生成题库":
        "Question bank for capability tests: download data locally / build the bank from local data",
    "build=缺什么下载什么再生成(默认); download=只下载数据; status=看本地数据":
        "build = download whatever is missing, then build the bank (default); download = only download the data; "
        "status = show the local data",
    "下载源偏好(默认魔搭, 国内)": "Preferred download source (default: ModelScope, in China)",
    "下载用的 HTTP 代理, 如 http://127.0.0.1:7890": "HTTP proxy for downloads, e.g. http://127.0.0.1:7890",
    "不联网, 只用本地数据生成": "Do not use the network; build only from local data",
    "download 时重新下载全部数据": "With download, re-download all data",
    "{name:<14} 已下载  {rows:>6} 行  {source}": "{name:<14} downloaded  {rows:>6} rows  {source}",
    "{name:<14} 缺少    {rows:>6} 行  {source}": "{name:<14} missing     {rows:>6} rows  {source}",
    "本地数据目录: {path} | 可以离线生成: 是": "Local data directory: {path} | Can build offline: yes",
    "本地数据目录: {path} | 可以离线生成: 否": "Local data directory: {path} | Can build offline: no",
    "失败：{error}": "Failed: {error}",
    "已停止：已经下载好的数据留在本地": "Stopped: the data already downloaded is kept locally",
}
