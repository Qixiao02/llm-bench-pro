# -*- coding: utf-8 -*-
"""cdp.py 的英文词条: 中文原文 → English。规则见 CONTRIBUTING.md「服务端消息与翻译」。
带数量的 (tn) 词条写成 (单数, 复数); 占位符 {名字} 中英文必须一致; 字面的花括号写成 {{ }}; 英文里不能有汉字。"""
ENTRIES = {
    # ---- 启动后台浏览器失败的原因 (抛出的异常文字; 会显示在页面上 / 存进作品的检查结果里)
    "未找到 Chrome/Edge/Chromium (可设 LLM_BENCH_BROWSER 指定路径)":
        "Chrome/Edge/Chromium not found (set LLM_BENCH_BROWSER to specify the path)",
    "无法启动浏览器 {path}: {error}": "Cannot start the browser {path}: {error}",
    "浏览器已启动但无法连接调试端口 {port}: {error}":
        "The browser started but the debugging port {port} is not reachable: {error}",
    "浏览器启动后立即退出（退出码 {code}）：{path}": "The browser exited right after starting (exit code {code}): {path}",
    "浏览器启动后立即退出（退出码 {code}）：{path}。浏览器输出：{output}":
        "The browser exited right after starting (exit code {code}): {path}. Browser output: {output}",
    "浏览器 {waited} 秒内没有准备好：{path}": "The browser was not ready within {waited} s: {path}",
    "浏览器 {waited} 秒内没有准备好：{path}。浏览器输出：{output}":
        "The browser was not ready within {waited} s: {path}. Browser output: {output}",
    # ---- WebSocket / CDP 会话 / PNG 解码的错误
    "WebSocket 握手失败": "WebSocket handshake failed",
    "WebSocket 握手被拒: {head}": "WebSocket handshake rejected: {head}",
    "WebSocket 连接关闭": "WebSocket connection closed",
    "WebSocket 被对端关闭": "WebSocket closed by the peer",
    "{method} 超时或连接断开(页面可能卡死)": "{method} timed out or the connection dropped (the page may be frozen)",
    "evaluate 异常: {text}": "evaluate raised an exception: {text}",
    "非 PNG": "Not a PNG",
    "不支持的 PNG 格式": "Unsupported PNG format",
    # ---- 回收遗留的后台浏览器 (页面启动测试时 / --reap / --reap-all)
    "  已关闭遗留的后台浏览器(所属进程 {pid} 已退出): {name}":
        "  Closed a leftover headless browser (its owner process {pid} has exited): {name}",
    "{name}  浏览器{browser}  目录{folder}": "{name}  browser {browser}  directory {folder}",
    "回收浏览器|已关闭": "closed",
    "回收浏览器|未在运行": "not running",
    "回收浏览器|已删除": "deleted",
    "回收浏览器|删除失败(可能仍被占用)": "deletion failed (may still be in use)",
    "共处理 {n} 个": ("Processed {n} browser", "Processed {n} browsers"),
    # ---- 命令行 (--help)
    "后台浏览器维护": "Headless browser maintenance",
    "回收所属进程已退出的后台浏览器": "Clean up leftover headless browsers whose owner process has exited",
    "关闭全部 llmbench 后台浏览器(含旧版本遗留), 确认没有评测在运行时使用":
        "Close all llmbench headless browsers (including leftovers from older versions); use only when no test is running",
}
