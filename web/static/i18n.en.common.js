/* 英文词条: 通用区域 —— 基础工具 / 主题 / 界面语言 / 导航 / 自定义下拉 / 运行日志 / 图表层 / 页面积木 / 多表格系统 / 删除 /
   样式自检 / 导出报告 / 启动, 以及导航、按钮、通用提示; 中文和英文两边 (index.html 静态文字 + JS 里的 t()) 都用到的句子也放这里。
   键是代码里 t("…") / tn("…") / tk("…") 的第一个参数 (中文原文); 带语境的键写成 "语境|原文"; tn 的值是 [单数, 复数];
   占位符 {名字} 和 HTML 标签必须和中文一致; 英文里不能有汉字。
   本文件只能写 I18N.add("en", {…}); (tests/i18n_lint.py 按这个格式读取)。 */

I18N.add("en", {
  /* ---- 页面名字 (页头标题、导航、导出的文件名和报告标题) ---- */
  "速度测试": "Speed test",
  "速度对比": "Speed comparison",
  "能力测试": "Capability test",
  "代码生成": "Code generation",

  /* ---- 基础工具: 时间、状态 ---- */
  "{n} 分钟": ["{n} minute", "{n} minutes"],
  "{n} 小时": ["{n} hour", "{n} hours"],
  "{n} 天": ["{n} day", "{n} days"],
  "进行中": "Running",
  "已完成": "Completed",
  "失败": "Failed",
  "已中断": "Interrupted",
  "已停止": "Stopped",

  /* ---- 基础工具: 接口和离线报告的提示 ---- */
  "这是导出的离线报告，不能修改数据": "This is an exported offline report, so data can't be changed",
  "无法连接后端服务（{msg}）": "Can't reach the backend service ({msg})",
  "离线报告里没有这部分数据": "This part of the data isn't in the offline report",
  "离线报告里没有这道题的回答": "The answer to this question isn't in the offline report",
  "离线报告里没有这个作品": "This work isn't in the offline report",
  "新标签页打开：像普通网页一样运行（可以加载外部字体和脚本），仍然隔离，碰不到本系统的数据": "Open in a new tab: runs like a normal web page (it can load external fonts and scripts) but stays isolated and can't reach this system's data",
  "新标签页打开": "Open in new tab",
  "新标签页打开：{name}": "Open in new tab: {name}",
  "关闭": "Close",
  "页面脚本出错：{msg}（第 {line} 行），请刷新页面后重试": "Page script error: {msg} (line {line}). Please reload the page and try again",

  /* ---- 主题、侧栏 ---- */
  "切换为亮色": "Switch to light theme",
  "切换为暗色": "Switch to dark theme",
  "切换主题失败:": "Failed to switch theme:",
  "收起侧栏": "Collapse the sidebar",
  "固定展开侧栏": "Keep the sidebar expanded",

  /* ---- 导航 / 抽屉 / 弹窗 / 通用点击 ---- */
  "切换按钮|图表": "Chart",  /* 图表卡上「切回图表」的按钮; 页头的「图表 | 表格」切换是 "图表": "Charts", 所以用语境区分 */
  "数据": "Data",
  "确定": "OK",
  "取消": "Cancel",
  "这个模型服务正在被使用": "This model service is in use",
  "同时测试会互相影响结果。仍要同时开始吗？": "Testing at the same time will skew the results. Start anyway?",
  "仍要开始": "Start anyway",

  /* ---- 自定义下拉 ---- */
  "搜索": "Search",
  "搜索选项": "Search options",
  "（空）": "(empty)",
  "无匹配项": "No matches",
  "暂无选项": "No options",

  /* ---- 图表层 / 页面积木 ---- */
  "没有数据": "No data",
  "切换为数据表": "Switch to data table",
  "不对比": "No comparison",

  /* ---- 启动: 侧栏的连接状态和版本提示 ---- */
  "离线报告": "Offline report",
  "从 LLM Bench Pro v{version} 导出的离线报告（{time}）：数据是导出那一刻的样子，不会更新，也不能修改": "Offline report exported from LLM Bench Pro v{version} ({time}): the data is a snapshot from the moment of export; it won't update and can't be changed",
  "服务未连接": "Service not connected",
  "服务已连接": "Service connected",
  "服务正常 · 已运行 {time}": "Service OK · up {time}",
  "后端 v{version} · 进程 {pid} · 启动于 {time}": "Backend v{version} · PID {pid} · started {time}",
  " · 提交 {commit}": " · commit {commit}",
  "数据库 {db}": "Database {db}",
  "评测程序：速度 {bench} · 能力 {iq} · 代码生成 {gen}": "Benchmark programs: speed {bench} · ability {iq} · code generation {gen}",
  "页面（v{ui}）和后端服务（v{server}）版本不一致：页面可能还是旧的，功能可能不正常。": "The page (v{ui}) and the backend service (v{server}) versions differ: the page may be outdated and some features may not work.",
  "刷新页面": "Reload page",
  "后端代码已经更新，但服务还在运行旧代码。请重启 python run.py 让修改生效。": "The backend code has been updated but the service is still running the old code. Please restart python run.py to apply the changes.",
  "进行中（刷新页面后继续跟踪）": "Running (tracking continues after reload)",
  "更新题集（刷新页面后继续跟踪）": "Updating question banks (tracking continues after reload)",

  /* ---- 运行日志 + 状态轮询 —— 第二阶段: 在这一节里加 ---- */

  /* ---- 页面积木 (页面积木区域里还没转的) —— 第二阶段: 在这一节里加 ---- */

  /* ---- 多表格系统 —— 第二阶段: 在这一节里加 ---- */

  /* ---- 删除 —— 第二阶段: 在这一节里加 ---- */

  /* ---- 样式自检 (开发用的页面, 可以不翻) —— 第二阶段: 在这一节里加 ---- */

  /* ---- 导出报告 ---- */
  "请先选择要导出的测试": "Pick a test to export first",
  "已导出「{title}」（{size} MB）：一个网页文件，双击就能打开，和这里看到的一样": "Exported “{title}” ({size} MB): one web page file; double-click to open it, and it looks the same as here",
  "导出失败：{msg}": "Export failed: {msg}",
});
