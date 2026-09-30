/* 英文词条: 任务集 —— app.js 里「任务集」区域 (页面 #tasks) 和新建速度测试面板里「自定义任务集」的文字。
   键是代码里 t("…") / tn("…") / tk("…") 的第一个参数 (中文原文); 带语境的键写成 "语境|原文"; tn 的值是 [单数, 复数];
   占位符 {名字} 和 HTML 标签必须和中文一致; 英文里不能有汉字。
   本文件只能写 I18N.add("en", {…}); 和 I18N.add("enData", {…}); (tests/i18n_lint.py 按这个格式读取)。 */

I18N.add("en", {
  /* ---- 多久以前 (tsAgo) ---- */
  "刚刚": "Just now",
  "{n} 分钟前": ["{n} minute ago", "{n} minutes ago"],
  "{n} 小时前": ["{n} hour ago", "{n} hours ago"],
  "{n} 天前": ["{n} day ago", "{n} days ago"],
});
