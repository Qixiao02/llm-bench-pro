/* 英文词条: 代码生成 —— app.js 里「代码生成」区域 (页面 #gen)、新建生成任务面板、作品卡和检查项。
   键是代码里 t("…") / tn("…") / tk("…") 的第一个参数 (中文原文); 带语境的键写成 "语境|原文"; tn 的值是 [单数, 复数];
   占位符 {名字} 和 HTML 标签必须和中文一致; 英文里不能有汉字。
   本文件只能写 I18N.add("en", {…}); 和 I18N.add("enData", {…}); (tests/i18n_lint.py 按这个格式读取)。
   数据里的中文名 (题目名、作品名、检查项名等, 见 td()) 写在 I18N.add("enData", {…}) 里。 */

I18N.add("en", {
  /* "中文原文": "English", */
  /* ---- 作品列表 (一件作品一行) ---- */
  "没有生成出来": "Not generated",
  "没有作品文件": "No work file",
  "报告里没有这张截图": "This screenshot isn't in the report",
  "没有截图": "No screenshot",
});
