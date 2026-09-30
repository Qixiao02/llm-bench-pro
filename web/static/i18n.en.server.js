/* 英文词条: 服务端返回给界面的提示 (接口的 error 字段、后台任务的状态说明等)。页面上用 tm(消息) 翻译: 先查下面的完整原文,
   再依次试 I18N.addPattern 登记的正则模式 (整句匹配, 写成 ^…$; $1 是第一个括号匹配到的); 都不行就照原文显示, 并记进 I18N.missingServer。
   带变化部分的提示 (任务集编号、测试名等) 用正则模式; 模式的第二项也可以是函数 (m, a, b) => …, 里面可以再调用 tm() 翻译匹配到的一段。
   服务端 Python 代码里的消息本身不改 (它们是中文): 这里只管前端显示。
   本文件只能写 I18N.add("en", {…}); 和 I18N.addPattern([/正则/, "英文或函数"], …); (tests/i18n_lint.py 按这个格式读取)。
   下面是几条真实的提示 (来自 llm_bench_pro/server.py), 作为写法示范; 其余的第二阶段补全。 */

I18N.add("en", {
  /* 任务名 (server.py 的 JOB_NAMES), 下面的模式里用 tm() 翻译 */
  "性能测试": "Speed test",
  "能力评测": "Capability test",
  "题集更新": "Question bank update",

  /* 完整的原文 */
  "需要访问令牌": "An access token is required",
  "缺少 base/model": "Missing base/model",
  "缺少 base/model/bank_id": "Missing base/model/bank_id",
  "任务集不存在（可能已被删除）": "Task set not found (it may have been deleted)",
});

I18N.addPattern(
  [/^任务集不存在: (\S+) \(可能已被删除, 请重新导入\)$/, "Task set not found: $1 (it may have been deleted; please import it again)"],
  [/^测试不存在: (.+)$/, "Test not found: $1"],
  [/^已有(.+)在运行$/, (m, name) => "A " + tm(name).toLowerCase() + " task is already running"],
  [/^(.+)正在使用同一模型端点。同时运行会使性能测试的吞吐和延迟数据失真。$/,
    (m, name) => "The " + tm(name).toLowerCase() + " task is using the same model endpoint. Running both at once would skew the speed test's throughput and latency numbers."]
);
