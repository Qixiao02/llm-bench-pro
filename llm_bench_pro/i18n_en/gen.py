# -*- coding: utf-8 -*-
"""gen.py 的英文词条: 中文原文 → English。规则见 CONTRIBUTING.md「服务端消息与翻译」。
带数量的 (tn) 词条写成 (单数, 复数); 占位符 {名字} 中英文必须一致; 字面的花括号写成 {{ }}; 英文里不能有汉字。

存进结果里的说明 (作品条目和 data/works/<run>/<题>.gen.json 里的 changes / rescued, 作品的 error) 按任务语言生成。
前端 (web/static/app.js 的 changeKind) 靠这几段文字里的关键词给 changes 分类, 改英文时要保留:
  改为不思考 → "regenerated without thinking"; 续写 / 重写 → "continuation"; 原样保存 → "as is"。"""
ENTRIES = {
    # ---- 采样参数的错误提示 (接口返回给页面)
    "采样参数 {key} 无效: {value!r}": "Invalid sampling parameter {key}: {value!r}",
    "采样参数 {key} 应在 {lo} 到 {hi} 之间: {value}": "Sampling parameter {key} must be between {lo} and {hi} (got {value})",
    "未知的采样方式: {sampling!r}": "Unknown sampling mode: {sampling!r}",
    "tasks 应为题目 id 数组": "tasks must be an array of question IDs",
    "请至少选择 1 道题目": "Select at least 1 question",
    "未知题目：{ids}": ("Unknown question ID: {ids}", "Unknown question IDs: {ids}"),
    "生成运行不存在: {run_id}": "Code generation run not found: {run_id}",

    # ---- 重复输出的描述 (放进日志句子里)
    "每 {period} 个字符循环一次，已重复 {repeats} 次": "a {period}-character cycle repeated {repeats} times",
    "最近几千字内容高度雷同（压缩率 {ratio:.2f}，正常代码约 0.2 以上）":
        "the last few thousand characters are highly repetitive: compression ratio {ratio:.2f}, normal code is "
        "around 0.2 or higher",

    # ---- 生成和续写的日志
    "    ⚠ 续写失败, 保留已生成部分: {error}": "    ⚠ Continuation failed; keeping the part generated so far: {error}",
    "    ↻ 续写从头重新输出了整个文件, 改用新内容":
        "    ↻ The continuation re-output the whole file from the start; using the new content",
    "    ⚠ 模型陷入重复输出({detail}), 停止生成、不再续写":
        "    ⚠ Model stuck in repetition ({detail}); stopped generating, no continuation",
    "    ⚠ 思考过程陷入重复输出, 停止思考": "    ⚠ Thinking stuck in repetition; stopped thinking",
    "    ⚠ 续写 {n} 轮仍未闭合": (
        "    ⚠ Still unfinished after {n} continuation round",
        "    ⚠ Still unfinished after {n} continuation rounds"),
    "    ↻ 截断, 续写第 {n} 轮(关闭思考直出代码)":
        "    ↻ Truncated; continuation round {n} (thinking off, output code directly)",

    # ---- 存进作品条目 / 生成过程文件的说明 (trace["rescued"] 和 changes 列表)
    "思考过程陷入重复，没写出代码；改为不思考、直接重新生成":
        "Thinking got stuck in repetition and no code was written; regenerated without thinking",
    "思考过程用完了输出长度，没写出代码；改为不思考、直接重新生成":
        "Thinking used up the output limit and no code was written; regenerated without thinking",
    "第 {n} 轮续写时模型从头重写了整个文件，采用了重写后的版本":
        "In continuation round {n}, the model rewrote the whole file from the start; the rewritten version was used",
    # 下面四条只出现在「接上第 N 轮续写（……）」的括号里, 是小写开头的片段, 用 ", " 连起来
    "模型从被截断的那一行重新写，去掉了重复的半行（{n} 个字符）": (
        "the model restarted from the truncated line; removed {n} duplicated character",
        "the model restarted from the truncated line; removed {n} duplicated characters"),
    "去掉了与上文重复的 {n} 个字符": (
        "removed {n} character duplicated from the text above",
        "removed {n} characters duplicated from the text above"),
    "去掉了开头的代码块标记": "removed the code fence at the start",
    "补了 1 个换行": "added 1 line break",
    "接上第 {n} 轮续写（{detail}）": "Joined continuation round {n} ({detail})",
    "接上第 {n} 轮续写（直接拼接）": "Joined continuation round {n} (appended directly)",
    "去掉了混在正文里的思考过程（{n} 个字符）": (
        "Removed thinking text mixed into the answer ({n} character)",
        "Removed thinking text mixed into the answer ({n} characters)"),
    "去掉了代码前面的说明文字（{n} 个字符）和代码块标记：「{snippet}」": (
        'Removed explanatory text before the code ({n} character) and code fence markers: "{snippet}"',
        'Removed explanatory text before the code ({n} characters) and code fence markers: "{snippet}"'),
    "去掉了代码前面的说明文字（{n} 个字符）：「{snippet}」": (
        'Removed explanatory text before the code ({n} character): "{snippet}"',
        'Removed explanatory text before the code ({n} characters): "{snippet}"'),
    "去掉了代码后面的说明文字（{n} 个字符）和代码块标记：「{snippet}」": (
        'Removed explanatory text after the code ({n} character) and code fence markers: "{snippet}"',
        'Removed explanatory text after the code ({n} characters) and code fence markers: "{snippet}"'),
    "去掉了代码后面的说明文字（{n} 个字符）：「{snippet}」": (
        'Removed explanatory text after the code ({n} character): "{snippet}"',
        'Removed explanatory text after the code ({n} characters): "{snippet}"'),
    "去掉了代码前面的 Markdown 代码块标记": "Removed the Markdown code fence before the code",
    "去掉了代码后面的 Markdown 代码块标记": "Removed the Markdown code fence after the code",
    "删除了续写接缝处多余的代码块标记": "Removed a stray code fence at the continuation seam",
    "原样保存了模型输出，没有做任何修改": "Saved the model output as is, with no changes",

    # ---- 开始和结束
    "== gen v{version} | {model} | {n} 题 | conc={conc} | 采样 {sampling} | 评测: {method}{judge} ==": (
        "== gen v{version} | {model} | {n} question | conc={conc} | sampling {sampling} | evaluation: {method}{judge} ==",
        "== gen v{version} | {model} | {n} questions | conc={conc} | sampling {sampling} | evaluation: {method}{judge} =="),
    "无头浏览器运行检测": "headless browser runtime check",
    "源码检查(未找到浏览器)": "code-only check (browser not found)",
    " + 视觉评审 {model}": " + visual review {model}",
    "已取消: 保留已完成的 {n} 件作品": (
        "Cancelled: kept {n} completed generated page",
        "Cancelled: kept {n} completed generated pages"),
    "完成 => {location}": "done => {location}",

    # ---- 每题的进度 (作品名和标签是题目表里的数据, 不翻)
    "▶ 开始: {name} ({tags})": "▶ Started: {name} ({tags})",
    "  ✗ [{name}] 失败: {error} · 进度 {done}/{total}": "  ✗ [{name}] Failed: {error} · progress {done}/{total}",
    "思考耗尽未产出正文(思考{n}字)": (
        "Thinking used up the output limit without producing an answer ({n} character of thinking)",
        "Thinking used up the output limit without producing an answer ({n} characters of thinking)"),
    "输出中没有有效的 HTML(提取到 {n} 字)": (
        "No valid HTML in the output ({n} character extracted)",
        "No valid HTML in the output ({n} characters extracted)"),
    "模型陷入重复输出，没有写出有效的 HTML": "The model got stuck in repetition and did not produce valid HTML",
    "  ✗ [{name}] {reason} · 进度 {done}/{total}": "  ✗ [{name}] {reason} · progress {done}/{total}",
    "  · [{name}] 已生成，取消于评测前": "  · [{name}] Generated; cancelled before evaluation",
    "  ✓ [{name}] {summary} · 进度 {done}/{total}": "  ✓ [{name}] {summary} · progress {done}/{total}",
    "已生成、未评测": "generated, not evaluated",
    "  ⚠ [{name}] 原始输出留档失败: {error}": "  ⚠ [{name}] Failed to save the raw output: {error}",

    # ---- 一件作品的检查摘要 (用 " · " 连成一行)
    "运行检测 {passed}/{total}": "runtime check {passed}/{total}",
    "（未通过：{names}）": " (failed: {names})",
    " · 评审 {score:.0f} 分": " · review score {score:.0f}",
    " · 评审失败": " · review failed",
    " · {n} 行": (" · {n} line", " · {n} lines"),

    # ---- 重新评测
    "== 重新评测 {run_id} | {n} 件作品 | {method}{judge} ==": (
        "== re-evaluation {run_id} | {n} generated page | {method}{judge} ==",
        "== re-evaluation {run_id} | {n} generated pages | {method}{judge} =="),
    "  ✗ [{name}] 作品文件缺失: {file}": "  ✗ [{name}] Generated page file is missing: {file}",
    "  · [{name}] 浏览器检测失败，保留上次的运行检测和评审":
        "  · [{name}] Browser check failed; keeping the previous runtime check and review",
    "重新评测已取消": "Re-evaluation cancelled",
    "重新评测完成": "Re-evaluation done",
}
