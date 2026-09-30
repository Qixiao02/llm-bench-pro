/* 英文词条: index.html 的静态文字 (文本节点和 title / placeholder / aria-label / alt 属性)。
   键 = 去掉首尾空白、中间的空白合成一个空格的中文原文 (与页面上看到的一致); 翻译在页面打开和切换语言时由 applyStaticI18n 完成。
   JS 里动态生成的文字不放这里 (放对应区域的词典, 键写在 t("…") 里); 同一句中文两边都用到的, 放 i18n.en.common.js。
   句子中间夹着 <code> <b> <a> 的元素, 在 index.html 里给元素加 data-i18n-html, 键就是它的 innerHTML (空白合并), 值里的标签要和中文一致。
   本文件只能写 I18N.add("en", {…}); (tests/i18n_lint.py 按这个格式读取)。 */

I18N.add("en", {
  /* ---- 侧栏 ---- */
  "侧栏": "Sidebar",
  "大模型测试平台": "LLM testing platform",
  "主导航": "Main navigation",
  "测试": "Tests",
  "速度": "Speed",
  "对比": "Compare",
  "能力": "Capability",
  "生成": "Code",
  "设置": "Settings",
  "任务集：速度测试「自定义任务集」用的请求文件，在这里导入、逐行查看、下载模板": "Task sets: the request files used by the speed test's “custom task set”. Import them, view them row by row, and download a template here",
  "任务集": "Task sets",
  "模型管理：保存常用的服务地址、Key 和模型，测试连接，新建测试时一键填入": "Model manager: save the service URLs, keys and models you use often, test the connection, and fill them in with one click when creating a test",
  "模型管理": "Model manager",
  "模型": "Models",
  "名词解释：页面上出现的名词都是什么意思": "Glossary: what every term on these pages means",
  "名词解释": "Glossary",
  "名词": "Glossary",
  "后端服务连接状态": "Backend connection status",
  "连接中…": "Connecting…",
  "切换亮色/暗色": "Switch light/dark theme",
  "固定展开侧栏": "Keep the sidebar expanded",

  /* ---- 各页面页头 (标题、A / B 选择、查看方式、导出、更多菜单、新建按钮) ---- */
  "模型生成有多快、同时处理很多请求时还稳不稳、输入很长时要等多久": "How fast the model generates, how stable it stays under many simultaneous requests, and how long you wait with very long inputs",
  "当前测试": "Current tests",
  "查看的测试 A": "Test A being viewed",
  "对比的测试 B": "Test B to compare with",
  "查看方式": "View mode",
  "图表视图": "Chart view",
  "图表": "Charts",
  "表格视图：每个章节都换成表格": "Table view: every section becomes a table",
  "表格": "Tables",
  "把现在看到的速度测试（A 和 B）导出成一个网页文件：双击就能打开，和这里看到的一样，可以直接发给别人": "Export the speed test you are viewing (A and B) as one web page file: double-click to open it, it looks the same as here, and you can send it to others as is",
  "导出报告": "Export report",
  "更多操作": "More actions",
  "刷新结果": "Refresh results",
  "导出本页全部表格（CSV）": "Export all tables on this page (CSV)",
  "删除测试 A": "Delete test A",
  "紧凑显示": "Compact display",
  "切换亮色 / 暗色": "Switch light / dark theme",
  "术语：大白话 / 专业": "Terms: plain / technical",
  "切换术语：大白话 / 专业": "Switch terms: plain / technical",
  "测试进行中": "Test running",
  "新建速度测试": "New speed test",
  "跳转到": "Jump to",

  "两次速度测试放在一起看：谁更快、快多少，比如换了推理框架、量化方式或显卡之后": "Put two speed tests side by side: which is faster and by how much, for example after switching the inference framework, quantization or GPU",
  "测试 A": "Test A",
  "交换 A / B": "Swap A / B",
  "交换 A 与 B": "Swap A and B",
  "测试 B": "Test B",
  "把现在看到的 A / B 对比导出成一个网页文件：双击就能打开，和这里看到的一样，可以直接发给别人": "Export the A / B comparison you are viewing as one web page file: double-click to open it, it looks the same as here, and you can send it to others as is",

  "用公开的标准考题（数学、常识、推理、中文、按要求作答）考模型，看答对多少": "Quiz the model with public standard exam questions (math, common sense, reasoning, Chinese, instruction following) and see how many it gets right",
  "查看的测试": "Test being viewed",
  "加入对比": "Add to comparison",
  "把现在看到的能力测试（含对比、逐题和模型的回答原文）导出成一个网页文件：双击就能打开，和这里看到的一样": "Export the ability test you are viewing (with comparisons, per-question results and the model's raw answers) as one web page file: double-click to open it, it looks the same as here",
  "新建能力测试": "New ability test",

  "让模型写网页小游戏和应用，在后台浏览器里真正运行、点击、按键，检查能不能用": "Have the model write small web games and apps, then really run them, click and press keys in a background browser to check that they work",
  "查看的任务": "Task being viewed",
  "对比的任务": "Task to compare with",
  "把现在看到的代码生成结果（含作品网页、检查截图和生成过程）导出成一个网页文件：双击就能打开，作品也能预览": "Export the code generation results you are viewing (with the web pages, check screenshots and generation process) as one web page file: double-click to open it, and the works can be previewed too",
  "对 A 的作品重新运行检查（可同时配置 AI 看图打分），保留人工评分": "Re-run the checks on A's works (you can also set up AI image scoring); manual ratings are kept",
  "重新检查作品": "Re-check works",
  "删除任务 A（连同作品）": "Delete task A (with its works)",
  "任务进行中": "Task running",
  "新建生成任务": "New generation task",

  "速度测试「自定义任务集」用的请求文件：每行一个请求（JSONL）": "Request files used by the speed test's “custom task set”: one request per line (JSONL)",
  "速度测试里「自定义任务集」用的请求，每行一个；导入后可以逐行查看": "The requests used by the speed test's “custom task set”, one per line; after importing you can view them row by row",
  "下载 JSONL 模板：每种写法都有一两行示例，每行的 meta.note 是说明": "Download a JSONL template: one or two example lines for each format; the meta.note on each line explains it",
  "下载模板": "Download template",
  "刷新": "Refresh",
  "导入任务集：选一个 .jsonl / .json / .txt 文件，也可以直接把文件拖到这一页上": "Import a task set: pick a .jsonl / .json / .txt file, or just drag the file onto this page",
  "导入任务集": "Import task set",

  "常用的模型服务：服务地址、API Key、模型名称，新建测试时一键填入": "Frequently used model services: service URL, API key and model name, filled in with one click when creating a test",
  "保存常用的服务地址、Key 和模型，测一测能不能连上，新建测试时一键填入": "Save the service URLs, keys and models you use often, check whether they connect, and fill them in with one click when creating a test",
  "逐个测试保存的模型能不能连上（同时最多 4 个）": "Test each saved model's connection one by one (up to 4 at a time)",
  "全部测试连接": "Test all connections",
  "添加模型：服务地址、API Key、模型名称": "Add a model: service URL, API key, model name",
  "添加模型": "Add model",

  "样式自检": "Style check",
  "全部设计令牌、字号和基础组件，用来截图核对亮暗两套主题": "All design tokens, type sizes and base components, for checking the light and dark themes in screenshots",

  /* ---- 新建: 速度测试 (右侧抽屉) —— 第二阶段: 在这一节里加 ---- */

  /* ---- 新建: 能力测试 (右侧抽屉) —— 第二阶段: 在这一节里加 ---- */

  /* ---- 新建: 代码生成 (右侧抽屉) —— 第二阶段: 在这一节里加 ---- */

  /* ---- 全局: 提示 / 拖入导入 / 弹窗 —— 第二阶段: 在这一节里加 ---- */
});
