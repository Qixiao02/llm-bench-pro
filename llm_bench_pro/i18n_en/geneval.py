# -*- coding: utf-8 -*-
"""geneval.py 的英文词条: 中文原文 → English。规则见 CONTRIBUTING.md「服务端消息与翻译」。
带数量的 (tn) 词条写成 (单数, 复数); 占位符 {名字} 中英文必须一致; 字面的花括号写成 {{ }}; 英文里不能有汉字。
检查项的名称 (geneval.CHECK_LABELS) 和交互步骤的名字 (gen_specs) 是测试内容, 不在这里; 这里只有检查之后产生的说明文字。"""
ENTRIES = {
    # ---- 运行检测: 每项检查的说明 (checks[].detail)、notes、截图说明 (shots[].caption); 存进作品的评测结果, 显示在作品详情里
    "未找到元素 {target}": "Element not found: {target}",
    "命中「{text}」": 'Matched "{text}"',
    "加载超时": "Load timed out",
    "主线程无响应(疑似死循环)": "Main thread not responding (possible infinite loop)",
    "页面卡死, 无法继续检测": "Page hung; cannot continue the runtime check",
    "页面卡死，未检测": "Page hung; not checked",
    "首屏（加载后约 1.2 秒）": "First screen (about 1.2 s after load)",
    "主色占比 {ratio:.1f}%，颜色数 {colors}": "Dominant color covers {ratio:.1f}% of the screen, color count {colors}",
    "空闲 {idle:.1f} 秒后": "After {idle:.1f} s idle",
    "预热动作失败: {error}": "Warm-up action failed: {error}",
    "首屏白屏，无法确认脚本正常运行": "Blank first screen; cannot confirm the script ran normally",
    "{n} 条：{errors}": ("{n} error: {errors}", "{n} errors: {errors}"),
    "画面变化 {diff:.2f}%，rAF {raf} 次，绘制调用 {draws} 次":
        "Screen change {diff:.2f}%, rAF calls {raf}, draw calls {draws}",
    "交互触发异常：{error}": "Interaction raised an exception: {error}",
    "画面变化 {diff:.2f}%（等长空闲基线 {base_diff:.2f}%），DOM 变更 {mut}（基线 {base_mut:.0f}），事件处理 {handled} 次":
        "Screen change {diff:.2f}% (equal-length idle baseline {base_diff:.2f}%), DOM mutations {mut} "
        "(baseline {base_mut:.0f}), event handler calls {handled}",
    "{why}；作品没有处理该输入，变化来自自身动画或样式":
        "{why}; the generated page did not handle this input, so the change comes from its own animation or styling",
    "交互「{label}」之后": 'After interaction "{label}"',
    "页面无响应：{error}": "Page not responding: {error}",
    "功能断言通过（计数 {before} → {now}，需增加 {gain}）":
        "Functional assertion passed (count {before} → {now}, must increase by {gain})",
    "功能断言未通过（计数 {before} → {now}，需增加 {gain}）":
        "Functional assertion failed (count {before} → {now}, must increase by {gain})",
    "功能断言在操作前已成立，无法确认由本次操作产生":
        "Functional assertion already held before the action; cannot confirm this action caused it",
    "功能断言通过": "Functional assertion passed",
    "功能断言未通过": "Functional assertion failed",
    "桌面首屏白屏，不检查移动端": "Blank first screen on desktop; mobile not checked",
    "移动端 390px 视口": "Mobile 390px viewport",
    "缺少 viewport meta": "Missing viewport meta tag",
    "布局宽 {width}px 超出设备宽 {device}px": "Layout width {width}px exceeds device width {device}px",
    "移动端白屏": "Blank screen on mobile",
    "移动端加载异常：{error}": "Exception while loading on mobile: {error}",
    "内容宽 {width}px / 设备宽 {device}px": "Content width {width}px / device width {device}px",
    "检测中断: {error}": "Runtime check interrupted: {error}",
    "检测中断（页面无响应或超时）：{error}": "Runtime check interrupted (page not responding or timed out): {error}",
    "检测中断，未执行": "Runtime check interrupted; not run",
    # ---- 对照运行的结论 (接在 no_error 的说明后面)
    "{detail}。对照：不注入任何检测脚本单独运行同样报错，是作品自身的问题":
        "{detail}. Control run: the same errors occur with no check scripts injected, so the problem is in the "
        "generated page itself",
    "{detail}。对照：不注入检测脚本单独运行时没有报错，可能是检测环境引起的，请人工确认":
        "{detail}. Control run: no errors when run without the check scripts, so the errors may be caused by the "
        "checking environment; please verify manually",
    # ---- 单文件自包含
    "外部依赖被拦截：{urls}": "External dependencies blocked: {urls}",
    "仅网络字体/图片等外链 {n} 个（已拦截，不影响功能）": (
        "Only 1 external link, such as a web font or image (blocked; no effect on functionality)",
        "Only {n} external links, such as web fonts or images (blocked; no effect on functionality)"),
    # ---- 源码检查 (没有浏览器时的降级)
    "已去除注释后匹配": "Matched after stripping comments",
    "未找到无头浏览器，降级为源码检查": "Headless browser not found; falling back to a code-only check",
    # ---- 视觉评审: 评审输出无法解析的说明 (存进评审结果的 error)
    "评审输出中没有包含 items 的 JSON": "The judge output contains no JSON object with an items list",
    "评审缺少清单项 {items}": "The judge output is missing checklist items: {items}",
    # ---- 浏览器池和编排
    "本机没有找到 Chrome / Edge 浏览器": "No Chrome / Edge browser found on this machine",
    "评测已结束": "The evaluation has ended",
    "  ⚠ 后台浏览器无法启动，本次作品只能做源码检查：{error}":
        "  ⚠ Cannot start the headless browser; pages in this run can only get a code-only check: {error}",
    "后台浏览器不可用，作品没有实际运行，只检查了源代码：{reason}":
        "Headless browser unavailable; the generated page was not actually run, only its source code was checked: "
        "{reason}",
    "未知原因": "unknown reason",
    "后台浏览器出错，作品没有实际运行，只检查了源代码：{error}":
        "Headless browser error; the generated page was not actually run, only its source code was checked: {error}",
    "    评审中: {name}": "    Reviewing: {name}",
    "无截图（未进行浏览器运行检测），跳过视觉评审":
        "No screenshots (no browser runtime check was performed); visual review skipped",
    # ---- 命令行
    "生成作品评测: 运行检测 + 视觉评审": "Evaluate generated pages: runtime check + visual review",
    "gen 运行 ID": "Code generation run ID",
    "只评测这些题, 逗号分隔": "Only evaluate these questions, comma-separated",
}
