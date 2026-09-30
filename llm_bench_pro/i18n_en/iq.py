# -*- coding: utf-8 -*-
"""iq.py 的英文词条: 中文原文 → English。规则见 CONTRIBUTING.md「服务端消息与翻译」。
带数量的 (tn) 词条写成 (单数, 复数); 占位符 {名字} 中英文必须一致; 字面的花括号写成 {{ }}; 英文里不能有汉字。

存进结果里的说明 (max_tokens_policy、warnings、error、每题回答里插入的省略标记) 按任务语言生成; 逐题查看里的规则说明
(rule_text / instruct_detail) 按请求的语言现算。warnings 在页面上是并列显示的, 所以单句的不加句号。"""
ENTRIES = {
    # ---- 输出预算说明 (存进结果的 max_tokens_policy)
    "思考模式: 统一上限 {n}(思考与正文共享, 超上下文自动收缩)":
        "Thinking mode: a shared limit of {n} tokens for thinking and the answer (reduced automatically if it "
        "exceeds the context)",
    "输出预算: 选择题 {mcq} · GSM8K {math} · MATH-500 {math500} · 指令 {instruct}":
        "Output budget (tokens): multiple choice {mcq} · GSM8K {math} · MATH-500 {math500} · "
        "instruction following {instruct}",

    # ---- 每题回答留档时, 过长的回答中间插入的标记
    "\n…（中间省略 {n} 字）…\n": (
        "\n… ({n} character omitted from the middle) …\n",
        "\n… ({n} characters omitted from the middle) …\n"),

    # ---- 按要求作答题: 每条检查规则的说明 (逐题查看)
    "不超过 {n} 个字": ("At most {n} character", "At most {n} characters"),
    "至少 {n} 个字": ("At least {n} character", "At least {n} characters"),
    "不超过 {n} 个英文单词": ("At most {n} English word", "At most {n} English words"),
    "必须包含“{v}”": 'Must contain "{v}"',
    "不能出现“{v}”": 'Must not contain "{v}"',
    "以“{v}”开头": 'Starts with "{v}"',
    "以“{v}”结尾": 'Ends with "{v}"',
    "正好 {n} 行": ("Exactly {n} line", "Exactly {n} lines"),
    "格式符合题目要求": "Matches the format required by the question",
    "是合法的 JSON，且包含 {keys}": "Is valid JSON and contains the keys {keys}",
    "JSON 内容等于 {value}": "JSON content equals {value}",
    "实际 {n} 字": ("Actual: {n} character", "Actual: {n} characters"),
    "实际 {n} 个单词": ("Actual: {n} word", "Actual: {n} words"),
    "实际 {n} 行": ("Actual: {n} line", "Actual: {n} lines"),

    # ---- 运行后自检 (存进结果的 warnings)
    "思考模式可能未生效：仅 {pct:.0f}% 的回答包含思考内容。端点可能不支持 enable_thinking，或模型模板的开关名称不同":
        "Thinking mode may not be in effect: only {pct:.0f}% of the answers contain thinking content; the endpoint may "
        "not support enable_thinking, or the model template may use a different switch name",
    "非思考模式下仍有 {pct:.0f}% 的回答包含思考内容，思考开关可能未生效，选择题等短输出题可能因输出上限被截断":
        "In non-thinking mode, {pct:.0f}% of the answers still contain thinking content, so the thinking switch may "
        "not be working and short-output questions such as multiple choice may be cut off by the output limit",
    "端点不支持以下参数，已自动去掉：{params}":
        "The endpoint does not support these parameters, so they were removed automatically: {params}",
    "{n} 题请求失败（计为答错），可续跑重试这些题": (
        "{n} question request failed (counted as incorrect); resume the run to retry it",
        "{n} question requests failed (counted as incorrect); resume the run to retry them"),

    # ---- 开始、续跑、取消、结束
    "== iq v{version} | {model} | bank={bank} | {n} 题 | conc={conc} | {mode} | 采样 {sampling}{resume} ==": (
        "== iq v{version} | {model} | bank={bank} | {n} question | conc={conc} | {mode} | sampling {sampling}{resume} ==",
        "== iq v{version} | {model} | bank={bank} | {n} questions | conc={conc} | {mode} | sampling {sampling}{resume} =="),
    "思考模式(max_tokens≤{n})": "thinking mode (max_tokens≤{n})",
    "非思考": "non-thinking",
    " | 续跑, 已有 {n} 题": (" | resuming, {n} question already done", " | resuming, {n} questions already done"),
    "已取消: 已完成 {n} 题, 可在页面上续跑": (
        "Cancelled: {n} question completed; you can resume it on the page",
        "Cancelled: {n} questions completed; you can resume it on the page"),
    "总体: {correct}/{n} = {acc:.1f}% (CI {lo:.1f}-{hi:.1f}, 科目宏平均 {macro:.1f}%) => {location}":
        "Overall: {correct}/{n} = {acc:.1f}% (CI {lo:.1f}-{hi:.1f}, subject average {macro:.1f}%) => {location}",

    # ---- 逐科目的进度和中止
    "  进度 {done}/{total}": "  progress {done}/{total}",
    "连续 {n} 题请求失败，已中止（最近错误：{error}）。修复端点后可续跑": (
        "Stopped after {n} consecutive failed request (latest error: {error}). Fix the endpoint and resume the run.",
        "Stopped after {n} consecutive failed requests (latest error: {error}). Fix the endpoint and resume the run."),
    "  截断{n}": "  truncated {n}",
    "  请求失败{n}": "  failed requests {n}",
}
