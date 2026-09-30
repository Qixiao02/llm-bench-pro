# -*- coding: utf-8 -*-
"""store.py 的英文词条: 中文原文 → English。规则见 CONTRIBUTING.md「服务端消息与翻译」。
带数量的 (tn) 词条写成 (单数, 复数); 占位符 {名字} 中英文必须一致; 字面的花括号写成 {{ }}; 英文里不能有汉字。"""
ENTRIES = {
    # ---- 抛出的错误: 接口把 str(e) 放进 error 显示在页面上, 命令行直接打印
    "无法识别运行类型: {run_id}": "Cannot determine the run type: {run_id}",
    "运行尚未结束，请先停止后再删除": "The run has not finished yet. Stop it first, then delete it.",
    "API 地址必须以 http:// 或 https:// 开头": "The service URL must start with http:// or https://",
    # 和 endpoints.py 的「模型名称不能为空」同一句; 用语境单独成词条, 不动 endpoints.py 的词典
    "保存模型|模型名称不能为空": "The model name cannot be empty",
    "配置不存在或已被删除": "The configuration does not exist or has been deleted",
    "run 不存在: {run_id}": "Run not found: {run_id}",
    # ---- import_json_file 返回的原因: 前缀 skipped: / error: 是协议不翻, 只翻后面的原因 (小写开头, 接在前缀后面)
    "导入|非对象 JSON": "not a JSON object",
    "导入|无法识别类型": "unknown run type",
    "导入|已删除": "previously deleted",
    "导入|库内原生运行": "run already in the database (not imported from a file)",
    "导入|未变化": "unchanged",
    "导入|内容不同(加 --force 覆盖)": "content differs (use --force to overwrite)",
    # ---- 校验往返
    "{fn} (缺失)": "{fn} (missing)",
    # ---- 命令行
    "llm-bench-pro SQLite 结果库": "llm-bench-pro SQLite results database",
    "库路径 (默认 data/llm_bench.db 或 $LLM_BENCH_DB)": "Database path (default: data/llm_bench.db or $LLM_BENCH_DB)",
    "建库建表": "Create the database and tables",
    "导入 data/results/*.json (幂等)": "Import data/results/*.json (idempotent)",
    "内容变化的已导入运行删除后重导": "Delete already-imported runs whose content has changed and import them again",
    "导出为 JSON": "Export as JSON",
    "把心跳超时的 running 运行标记为 interrupted": "Mark running runs whose heartbeat has timed out as interrupted",
    "校验库与 data/results/*.json 往返等价": "Verify that the database round-trips to data/results/*.json",
    "导入完成: {summary}": "Import complete: {summary}",
    "导出 {n} 个 => {out}": ("Exported {n} run => {out}", "Exported {n} runs => {out}"),
    "标记中断: {n}": "Marked as interrupted: {n}",
    "往返一致": "Round trip consistent",
    "不一致: {bad}": "Round trip inconsistent: {bad}",
}
