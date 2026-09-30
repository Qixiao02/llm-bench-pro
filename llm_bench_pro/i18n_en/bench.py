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
}
