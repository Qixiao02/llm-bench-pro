/* 英文词条: 速度测试 —— app.js 里「速度测试: 新建 / 列表 / 指标」和「速度测试: 结果页」两个区域, 以及新建面板。
   键是代码里 t("…") / tn("…") / tk("…") 的第一个参数 (中文原文); 带语境的键写成 "语境|原文"; tn 的值是 [单数, 复数];
   占位符 {名字} 和 HTML 标签必须和中文一致; 英文里不能有汉字。
   本文件只能写 I18N.add("en", {…}); 和 I18N.add("enData", {…}); (tests/i18n_lint.py 按这个格式读取)。
   数据里的中文名 (场景名等, 见 td()) 写在 I18N.add("enData", {…}) 里。 */

I18N.add("en", {
  /* ---- 新建 / 列表 / 指标 ---- */
  "选择测试 B": "Choose test B",
  "共 {n} 次测试": ["{n} test in total", "{n} tests in total"],
  "加载中…": "Loading…",
  "连不上后端服务": "Can't reach the backend service",
  "请确认 python run.py 正在运行（{msg}）": "Make sure python run.py is running ({msg})",

  /* ---- 结果页: 结论 ---- */
  "有 <b>{n}</b> 个请求失败（成功率 {rate}%）。": ["<b>{n}</b> request failed ({rate}% success rate).", "<b>{n}</b> requests failed ({rate}% success rate)."],
  "A 比 B：<b>{better}</b> 项更好、<b>{worse}</b> 项更差、{same} 项基本持平。": "A vs B: <b>{better}</b> better, <b>{worse}</b> worse, {same} about the same.",
  /* 这两句拼在上一句后面, 中文的句号后面不用空格, 英文要空一格: 值开头的空格是故意的 */
  "更好：{list}。": " Better: {list}.",
  "更差：{list}。": " Worse: {list}.",
  "；": "; ",
});
