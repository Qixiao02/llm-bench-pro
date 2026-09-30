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
  /* ---- 评分标准: 以「能不能用」为准 (只有 能打开 / 不白屏 / 不报错 / 核心操作有反应 算分, 其余只作提示) ---- */
  "能用（代码结尾不完整，但页面能正常运行）": "Usable (the code ends abruptly, but the page runs fine)",
  "两边都没有实际运行，看不出哪个能用，不比较": "Neither side was actually run, so we can't tell which one works; not compared",
  "没有实际运行，只在代码里找了关键词，不算分，仅供参考": "Not actually run; only keywords were searched for in the code. Not scored, for reference only",
  "这个任务生成于新的评分标准之前：页面上已经按新标准重新算了分——只算「能打开、不白屏、不报错、核心操作有反应」，动画、手机适配、外网依赖、代码写没写完整只作提示。存下来的检查记录没有改动。":
    "This task was generated before the new scoring standard. The page has recalculated its scores under the new standard: only \"opens, isn't blank, no errors, core actions respond\" count, while animation, mobile layout, external network dependencies and whether the code was written out in full are hints only. The saved check records are unchanged.",
  "（它依赖外部网络资源，检查时没联网，可能因此没加载出来）": " (it depends on external network resources and the check ran offline, so it may not have loaded because of that)",
  "（干净环境里同样报错）": " (it errors the same way in a clean environment)",
  "没有实际运行，看不出能不能用": "Not actually run, so we can't tell whether it works",
  "（不含没有实际运行的 {n} 件）": " (not counting the {n} that were not actually run)",
  "{n} 件作品都没有实际运行，看不出能不能用，所以没有打分。": "None of the {n} works were actually run, so we can't tell whether they work and nothing is scored.",
  "实际运行的 {n} 件作品里，": "Of the {n} works that were actually run, ",
  "{n} 件作品里，": "Of the {n} works, ",
  "（算分）": " (scored)",
  "（没有操作步骤的纯动画题里算分，其余只作提示）": " (scored for pure-animation tasks with no actions to try; a hint otherwise)",
  "没有实际运行，不打分": "Not actually run; not scored",
  "能打开、不白屏、不报错、核心操作有反应": "Opens, isn't blank, no errors, core actions respond",
  "没有打分": "Not scored",
  "没打分": "Not scored",
  "没有实际运行": "Not actually run",
  "（在干净页面里没有复现，可能是检测引起的，没算分）": " (not reproduced on a clean page; possibly caused by the checker; not scored)",
  "（只作提示，不算分）": " (hint only; not scored)",
  "按题目模拟的核心操作，算分": "The core actions simulated for this task; scored",
  "只在没有实际运行时才有，只作参考，不算分": "Only present when the work was not actually run; for reference, not scored",
  "能打开、不白屏、没报错、核心操作有反应算分（没过是红色）；其余只作提示（没过是黄色「提示」）；没有实际运行的只有代码关键词；「—」是这件作品没做这项检查":
    "Opens, isn't blank, no errors and core actions responding are scored (a fail is red); the rest are hints only (a fail is a yellow \"Hint\"); works that were not actually run only have code keywords; \"—\" means the work was not checked for this item",
  "检查项|提示": "Hint",
  "运行时报错，但在干净页面里没有复现，可能是检测引起的（没算分）": "Errors while running, but not reproduced on a clean page; possibly caused by the checker (not scored)",
  "能不能用 {pass} / {total}": "Usable: {pass} / {total}",
  "在后台浏览器里实际运行": "run in a background browser",
  "只算：能打开、不白屏、不报错、题目要求的核心操作有反应。": "Only these count: it opens, isn't blank, has no errors, and the core actions the task asks for respond.",
  "只在代码里找了关键词，看不出能不能用，所以不打分；下面的结果只作参考。": "Only keywords were searched for in the code, so we can't tell whether it works and it isn't scored; the results below are for reference only.",
  "只作提示（不算分）": "Hints only (not scored)",
  "动画、手机适配、外网依赖、代码是否写完整不影响「能不能用」，页面没坏就只提示一句。": "Animation, mobile layout, external network dependencies and whether the code was written out in full don't affect \"usable or not\"; if the page isn't broken they are only mentioned.",
});
