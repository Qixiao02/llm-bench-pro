/* 前端逻辑断言 (拼接在 app.js 之后执行, 同一文件作用域, 直接引用其顶层函数)。
   输出 "FRONTEND-OK <n>" 表示全部通过; 任一断言失败抛异常, Node 以非零退出。 */
const assert = require("node:assert");
let __n = 0;
function T(name, fn) { fn(); __n++; console.log("  ok - " + name); }

/* ---------- 版本与基础工具 ---------- */
T("UI_VERSION 为语义化版本", () => {
  assert.match(UI_VERSION, /^\d+\.\d+\.\d+$/);
});
T("esc: HTML 注入全量转义", () => {
  assert.equal(esc('<img src=x onerror=alert(1)>'), "&lt;img src=x onerror=alert(1)&gt;");
  assert.equal(esc("a\"b'c&d"), "a&quot;b&#39;c&amp;d");
  assert.equal(esc(null), "");
  assert.equal(esc(undefined), "");
  assert.equal(esc(0), "0");           /* 0 不是空值 */
});
T("fmt: 空值与非有限数出占位符", () => {
  assert.equal(fmt(null), "—");
  assert.equal(fmt(NaN), "—");
  assert.equal(fmt(Infinity), "—");
  assert.equal(fmt(12.34, 1), "12.3");
  assert.equal(fmt(7, 2), "7.00");
});
T("fmtInt: 千位分隔且不丢精度语义", () => {
  assert.equal(fmtInt(null), "—");
  const s = fmtInt(1234567);
  assert.match(s, /^[\d.,\s\u00A0’']+$/);   /* 兼容不同 locale 分隔符 */
  assert.equal(s.replace(/[\D]/g, ""), "1234567");
});
T("fmtAxis: 数量级缩写", () => {
  assert.equal(fmtAxis(1500000), "1.5M");
  assert.equal(fmtAxis(12000), "12k");
  assert.equal(fmtAxis(12345), "12.3k");
  assert.equal(fmtAxis(150), "150");
  assert.equal(fmtAxis(0), "0");
  assert.equal(fmtAxis(0.5), "0.5");
  assert.equal(fmtAxis(12.3), "12");
});
T("median: 奇偶样本与脏值过滤", () => {
  assert.equal(median([3, 1, 2]), 2);
  assert.equal(median([4, 1, 3, 2]), 2.5);
  assert.equal(median([null, 1, NaN]), 1);
  assert.equal(median([]), null);
});
T("niceMax: 整洁刻度上限", () => {
  assert.equal(niceMax(0), 1);
  assert.equal(niceMax(-5), 1);
  assert.equal(niceMax(400), 400);
  assert.equal(niceMax(300), 400);
  assert.equal(niceMax(101), 200);
  assert.equal(niceMax(1010), 2000);
});

/* ---------- 时间 ---------- */
T("toDate: 补 Z/拒绝垃圾", () => {
  assert.notEqual(toDate("2026-01-01T00:00:00Z"), null);
  assert.notEqual(toDate("2026-01-01T00:00:00"), null);   /* 无时区按 UTC 补 */
  assert.equal(toDate(""), null);
  assert.equal(toDate("garbage"), null);
});
T("durationText: 分钟/小时/天", () => {
  assert.equal(durationText(59), "1 分钟");
  assert.equal(durationText(3600), "1 小时");
  assert.equal(durationText(5400), "1.5 小时");
  assert.equal(durationText(90000), "1 天");
});

/* ---------- 主题色 → 渐变 (echarts 集成的回归守卫) ---------- */
T("withAlpha: 6位hex → 8位hex; 非hex 原样返回", () => {
  assert.equal(withAlpha("#6950E8", .26), "#6950E842");
  assert.equal(withAlpha("#6950E8", .02), "#6950E805");
  assert.equal(withAlpha("rgb(1,2,3)", .5), "rgb(1,2,3)");   /* passthrough */
  assert.equal(withAlpha("#ABC", .5), "#ABC");
});
T("withAlpha(undefined) 原样返回 undefined — 调用方必须传有效色", () => {
  assert.equal(withAlpha(undefined, .26), undefined);
});
T("areaFill: 主题全色板都产出 10% 透明度的淡色; 非法颜色回落到主色(漏传颜色事故锚点)", () => {
  const palette = ["#6950E8", "#0E9AB0", "#D97F06", "#D6408E", "#2F7FE0", "#5E9E12", "#8a70ef", "#1a9eb2"];
  for (const color of palette) {
    const f = areaFill(color).color;
    assert.ok(/^#[0-9a-fA-F]{8}$/.test(f), "非法淡色: " + f);
    assert.match(f, /1a$/i);                       /* 0.10 → 0x1a */
  }
  const saved = C;
  C = {};
  try {
    assert.match(areaFill(C.a).color, /^#6950E81a$/i);   /* C.a === undefined 时不产出 undefined */
    assert.match(areaFill("rgb(1,2,3)").color, /^#6950E81a$/i);
  } finally {
    C = saved;
  }
});

/* ---------- tooltip / 图标 ---------- */
T("tt: 标题/行/脚注全转义, 数值在名称前", () => {
  const h = tt("<x> · 并发 4", [["#fff", "<b>名</b>", "1<2"], ["", "ok", "3/4"]], "<i>注</i>");
  assert.ok(!h.includes("<b>名</b>") && !h.includes("1<2") && !h.includes("<i>注</i>"));
  assert.ok(h.includes("&lt;b&gt;名&lt;/b&gt;") && h.includes("1&lt;2") && h.includes("&lt;i&gt;注&lt;/i&gt;"));
  assert.ok(h.indexOf("1&lt;2") < h.indexOf("&lt;b&gt;名"));   /* 值在前, 名在后 */
});
/* ---------- 术语: 大白话 / 专业 两种写法 ---------- */
/* 临时切到某个模式跑一段, 跑完还原 */
const withMode = (mode, fn) => { const saved = TERM_MODE; TERM_MODE = mode; try { return fn(); } finally { TERM_MODE = saved; } };
const shown = h => (/>([^<]*)<\/span>/.exec(h) || [])[1];
const isLatinWord = s => /[A-Za-z]/.test(s);
T("术语词表: 每个词有大白话 / 完整说法 / 解释, 除 token 外都有专业写法, 专业词能在完整说法里找到(悬停和名词解释两处一致)", () => {
  for (const [k, t] of Object.entries(TERMS)) {
    assert.ok(t.name && t.tech && t.desc, "名词缺字段: " + k);
    if (k === "token") { assert.equal(t.pro, undefined); continue; }   /* 本来就是专业词 */
    assert.ok(t.pro && t.pro === t.pro.trim(), "缺专业写法: " + k);
    assert.notEqual(t.pro, t.name, k);
    const lead = isLatinWord(t.pro) ? t.pro.split(/\s+/)[0] : t.pro;    /* 英文的对第一个词, 纯中文的整个对 */
    assert.ok(t.tech.toLowerCase().includes(lead.toLowerCase()), `${k}: 完整说法「${t.tech}」里没有专业词「${t.pro}」`);
    assert.equal(termField(t, "pro"), t.pro);                           /* 取字段的唯一入口 */
  }
  for (const [k, w] of Object.entries(WORDS)) assert.ok(w.name && w.pro && (!w.of || TERMS[w.of]), "标签词缺字段: " + k);   /* 只做标签的词: 分位词等, of 指向名词解释里的词条 */
  assert.deepEqual([WORDS.p50.pro, WORDS.p95.pro, WORDS.p99.pro], ["P50", "P95", "P99"]);
  assert.deepEqual([WORDS.p50.name, WORDS.p95.name, WORDS.p99.name], ["一般", "较慢", "最慢"]);
  assert.equal(Object.keys(WORDS).filter(k => TERMS[k]).length, 0);                                /* 两张表的 key 不重复 */
});
T("term(): 大白话模式显示大白话、悬停给专业说法; 专业模式显示专业词、悬停给对应的大白话; 自定义文字在专业模式下也换成专业词; 未知名词原样转义", () => {
  withMode("plain", () => {
    const h = term("ttft");
    assert.ok(h.includes('class="term"') && h.includes('data-term="ttft"') && shown(h) === "首字等待");
    assert.ok(h.includes("TTFT（Time To First Token）：从发出请求") && h.includes("（点击查看名词解释）"));
    assert.equal(shown(term("agg", "总速度")), "总速度");
  });
  withMode("pro", () => {
    const h = term("ttft");
    assert.ok(h.includes('data-term="ttft"') && shown(h) === "TTFT");
    assert.ok(h.includes("大白话：首字等待。从发出请求到收到第一个字") && !h.includes("Time To First Token") && h.includes("（点击查看名词解释）"));
    assert.equal(shown(term("agg", "总速度")), "Throughput");           /* 自定义文字: 专业模式也换 */
    assert.equal(shown(term("prefill")), "Prefill");
    assert.equal(shown(term("token")), "token");                         /* 没有专业写法的词两种模式一样 */
  });
  for (const mode of ["plain", "pro"]) withMode(mode, () => {
    assert.equal(term("no-such", "<a>"), "&lt;a&gt;");
    assert.equal(term("no-such"), "no-such");
    for (const k of Object.keys(TERMS)) {
      const h = term(k);
      assert.equal(shown(h), termWord(k), `${mode}/${k}`);
      assert.ok(/^<span class="term" data-term="[a-z0-9]+" title="[^"<]+">[^<]+<\/span>$/.test(h), `${mode}/${k}: ${h}`);   /* 属性没被破坏 */
    }
  });
  assert.equal(TERM_MODE, "plain");                                       /* 默认大白话 */
});
T("termText / termHtml: {key} 按当前模式换词; {!key} 不带下划线; {key|文字} 自定义; {key|文字|专业文字} 专业模式另写; 不认识的 {…} 原样保留", () => {
  withMode("plain", () => {              /* 大白话模式: 模板怎么写就怎么显示, 不改空格 */
    assert.equal(termText("{ttft} {p95}"), "首字等待 较慢");
    assert.equal(termText("最高{agg}"), "最高总生成速度");
    assert.equal(termText("{agg|总速度}最高"), "总速度最高");
    assert.equal(termText("{ttft}{p95}时"), "首字等待较慢时");
    assert.equal(termText("单个请求{decode|生成} {p50}"), "单个请求生成 一般");
    assert.equal(termText("{v90}/{v95}"), "较慢/最慢");
    assert.equal(termText("{rerun}"), "重新运行");
    assert.equal(termText("{preagg} {sigtest}"), "总读入速度 McNemar 检验");
    assert.equal(termText("{nope} {x|y} {} {ttft"), "{nope} {x|y} {} {ttft");
    const h = termHtml("横轴是{conc}，{!agg|总速度}<b>{p95}</b>");
    assert.ok(h.startsWith('横轴是<span class="term" data-term="conc"') && h.includes(">同时请求数</span>，总速度<b>较慢</b>"));
    assert.ok(!h.includes('data-term="agg"'));                           /* {!key} 不带下划线和悬停 */
    const r = termHtml("里{rerun}也");                                    /* 换个说法的词(rerun)点开还是「对照运行」那一条 */
    assert.ok(r.includes('data-term="control"') && r.includes(">重新运行</span>") && !r.includes('data-term="rerun"'));
    assert.ok(!termHtml("{p95} {!rerun}").includes("<span"));            /* 分位词、{!key} 都不带下划线 */
  });
  withMode("pro", () => {                /* 专业模式: 英文专业词和汉字之间补空格, 全角标点旁不补 */
    assert.equal(termText("{ttft} {p95}"), "TTFT P95");
    assert.equal(termText("最高{agg}"), "最高 Throughput");
    assert.equal(termText("{agg|总速度}最高"), "Throughput 最高");
    assert.equal(termText("{ttft}{p95}时"), "TTFT P95 时");
    assert.equal(termText("{conc}{ttft}"), "并发 TTFT");
    assert.equal(termText("（{ttft}）"), "（TTFT）");
    assert.equal(termText("，{prefill} 10 token/秒"), "，Prefill 10 token/秒");
    assert.equal(termText("单个请求{decode|生成} {p50}"), "单个请求 Decode P50");
    assert.equal(termText("{v90}/{v95}"), "P90/P95");                    /* 速度的分位如实写 P90 / P95 */
    assert.equal(termText("有 3 题{trunc}（写到长度上限）"), "有 3 题截断（写到长度上限）");   /* 中文专业词不加空格 */
    assert.equal(termText("{preagg}"), "Prefill 总吞吐");
    assert.equal(termText("{rerun}"), "复现");
    assert.equal(termText("（{!sigtest}）"), "（配对检验）");
    assert.equal(termText("{nope} {x|y}"), "{nope} {x|y}");
    assert.equal(termText("{token}"), "token");
    assert.ok(termHtml("里{rerun}也").includes(">复现</span>") && termHtml("里{rerun}也").includes('data-term="control"'));
    const h = termHtml("时{agg}最高，{!kv|显存缓存}满");
    assert.ok(/时 <span class="term" data-term="agg"[^>]*>Throughput<\/span> 最高，KV Cache 使用率满$/.test(h), h);   /* 空格在下划线外面 */
  });
});
T("术语: 词只按 key 换一次(结果里没有模板了, 再处理一遍不变); 纯文本版本没有 HTML; HTML 版本去掉标签后和纯文本一致", () => {
  for (const mode of ["plain", "pro"]) withMode(mode, () => {
    for (const k of [...Object.keys(TERMS), ...Object.keys(WORDS)]) {
      const t = termText(`前{${k}}后`), h = termHtml(`前{${k}}后`);
      assert.ok(!/[<>{}]/.test(t), `${mode}/${k}: 纯文本里有标签或模板: ${t}`);
      assert.ok(!/[{}]/.test(h), `${mode}/${k}: ${h}`);
      assert.equal(termText(t), t);
      assert.equal(termHtml(h), h);
      assert.equal(stripTags(h), t);
    }
    assert.equal(termText(""), "");
    assert.equal(termText(null), "");
  });
});
T("指标卡 / 对比表的标签: 两种模式都没有残留的模板; 大白话模式不出现专业词, 专业模式下带上专业词", () => {
  const m = {pLast: {label: "16K"}, pcp: {conc: 4}, olLast: {rate: 5}};
  const full = {...m, zh: {out_tokens: 512, itl_p50_ms_med: 10}, en: {out_tokens: 512, itl_p50_ms_med: 10}, cLast: {conc: 8, ttft_p50_s: 1}, s: {per_stream_decode_p50: 50, per_stream_decode_p95: 60}};
  const proWords = ["Prefill", "TTFT", "ITL", "Decode", "Throughput", "req/s", "E2E", "Open-loop", "Burst", "P50", "P95", "P99"];
  for (const k of [...PERF_METRICS, ...CMP_EXTRA]) {
    const plain = withMode("plain", () => [metricLabel(k, m), safeSub(k, full)]);
    const pro = withMode("pro", () => [metricLabel(k, m), safeSub(k, full)]);
    for (const s of [...plain, ...pro]) assert.ok(!/[{}<>]/.test(s), `${k.key}: 有残留模板: ${s}`);
    for (const w of proWords) assert.ok(!plain[0].includes(w) && !plain[1].includes(w), `${k.key}: 大白话模式出现专业词 ${w}: ${plain.join(" | ")}`);
    if (k.key !== "succ") assert.ok(proWords.some(w => pro[0].includes(w)), `${k.key}: 专业模式的标签里没有专业词: ${pro[0]}`);
  }
  const zh = PERF_METRICS.find(x => x.key === "zh"), peak = PERF_METRICS.find(x => x.key === "peak"), ttft = PERF_METRICS.find(x => x.key === "ttft");
  assert.deepEqual(withMode("plain", () => [zh, peak, ttft].map(x => metricLabel(x, m))), ["单个请求生成速度 · 中文", "最高总生成速度", "首字等待 · 请求最多时（较慢）"]);
  assert.deepEqual(withMode("pro", () => [zh, peak, ttft].map(x => metricLabel(x, m))), ["单个请求 Decode · 中文", "最高 Throughput", "TTFT · 请求最多时（P95）"]);
  /* 指标卡悬停: 大白话模式 = 大白话（专业说法）：解释; 专业模式 = 专业词（大白话：…）：解释 */
  assert.equal(withMode("plain", () => metricTip(ttft)), "首字等待（TTFT（Time To First Token））：" + TERMS.ttft.desc);
  assert.equal(withMode("pro", () => metricTip(ttft)), "TTFT（大白话：首字等待）：" + TERMS.ttft.desc);
  assert.equal(metricTip(PERF_METRICS.find(x => x.key === "succ")), "");
});
/* 合成一份各章节都有数据的速度测试: 两种模式下整页的表头 / 图表标题 / 坐标轴 / 图例都走统一函数 */
const synthPerfRun = () => ({run_id: "r1", model: "m", suite: "full", status: "done", url: "http://h", started_utc: "2026-01-01T00:00:00Z", phases: [
  {id: "concurrency", points: [{conc: 1, agg_tps: 100, per_stream_tps_med: 100, ttft_p50_s: .1, ttft_p95_s: .2, ok: 2, fail: 0}, {conc: 4, agg_tps: 300, per_stream_tps_med: 75, ttft_p50_s: .2, ttft_p95_s: .5, ok: 8, fail: 0}]},
  {id: "prefill", points: [{label: "1K", in_tokens: 1000, prefill_tps_med: 5000, ttft_med_s: .2}, {label: "4K", in_tokens: 4000, prefill_tps_med: 6000, ttft_med_s: .7}]},
  {id: "prefill_conc", conc: 4, summary: {prefill_min: 1, prefill_max: 2, prefill_avg: 1.5, decode_min: 1, decode_max: 2, decode_avg: 1.5, per_stream_decode_p50: 50, per_stream_decode_p90: 60, per_stream_decode_p95: 65},
    points: [{label: "1K", in_tokens: 1000, ttft_avg_ms: 300, itl_avg_ms: 12, prefill_tps_agg: 8000, decode_tps_agg: 200, ok: 4, fail: 0, stream_prefill_tps: [2000], stream_decode_tps: [50]}]},
  {id: "decode", cases: [{lang: "zh", out_tokens: 256, decode_tps_med: 100, decode_tps_best: 110, itl_p50_ms_med: 10, spec_burst_med: 1, runs: [{tpot_ms: 10, itl_p95_ms: 12, itl_p99_ms: 15, itl_jitter_ms: 1}]}]},
  {id: "scn_chat", task: {label: "对话问答"}, points: [{conc: 4, req_s: 1.2, ttft_p95_s: .5, e2e_p95_s: 5, ok: 4, total: 4, out_tokens_avg: 100, max_inflight: 4}]},
  {id: "replay", pool: {size: 10, wrapped: false}, points: [{conc: 4, req_s: 2, ttft_p95_s: 1, e2e_p95_s: 5, prompt_tokens_avg: 100, out_tokens_avg: 50, max_inflight: 4, ok: 8, total: 8}]},
  {id: "openloop", points: [{rate: 2, sent: 10, completed_rps: 1.9, ttft_p95_s: 1, e2e_p95_s: 5, max_inflight: 3, ok: 10, total: 10, inflight_ts: [[0, 1], [3, 2]]}]},
  {id: "longctx", points: [{in_tokens: 1000, ttft_s: .5, prefill_tps: 2000, decode_tps: 50, itl_p50_ms: 10, itl_p95_ms: 12}, {in_tokens: 2000, ttft_s: .9, prefill_tps: 2100, decode_tps: 49, itl_p50_ms: 10, itl_p95_ms: 12}, {in_tokens: 4000, ttft_s: 1.9, prefill_tps: 2100, decode_tps: 48, itl_p50_ms: 10, itl_p95_ms: 12}]}],
  metrics_samples: [{t: 0, gpu_cache_usage: .1, prefix_cache_hit: 20, requests_running: 1, requests_waiting: 0}, {t: 5, gpu_cache_usage: .2, prefix_cache_hit: 30, requests_running: 2, requests_waiting: 0}]});
/* 收集页面里「当标签用」的文字: 表头 / 图表标题 / 章节标题 / 表格标题, 和图表的坐标轴名、图例、系列名 */
function labelTexts(html) {
  const out = [];
  for (const re of [/<th[^>]*>([\s\S]*?)<\/th>/g, /<h[23] class="(?:ccard|sec)-title">([\s\S]*?)<\/h[23]>/g, /<div class="dt-title">([\s\S]*?)(?:<span|<\/div>)/g]) {
    let m; while ((m = re.exec(html))) out.push(stripTags(m[1]).trim());
  }
  return out.filter(Boolean);
}
function recordCharts() {   /* 每张图 setOption 的所有调用都记下来(先画整图、后面可能再补标记) */
  const opts = new Map();
  globalThis.echarts.init = el => ({setOption(o) { (opts.get(el) || opts.set(el, []).get(el)).push(o); }, resize() {}, dispose() {}, on() {}, off() {}, getDom() { return el; }, getZr() { return {on() {}, off() {}}; }});
  return opts;
}
function chartTexts(opts) {
  const out = [], arr = x => (Array.isArray(x) ? x : x ? [x] : []);
  for (const o of [...opts.values()].flat()) {
    arr(o.xAxis).concat(arr(o.yAxis)).forEach(a => a.name && out.push(a.name));
    arr(o.legend).forEach(l => (l.data || []).forEach(d => out.push(typeof d === "string" ? d : d.name)));
    arr(o.series).forEach(s => s.name && out.push(s.name));
  }
  return out;
}
T("速度测试整页: 两种模式下表头、图表标题、坐标轴、图例都走统一函数(大白话模式没有专业词, 专业模式没有这些词的大白话)", () => {
  const plainNames = ["读入速度", "首字等待", "出字间隔", "生成速度", "总生成速度", "每秒完成请求数", "完整响应", "同时请求数", "显存缓存占用", "重复内容复用率", "固定同时请求数", "按固定速率发送", "一般", "较慢", "最慢"];
  const proWords = ["Prefill", "TTFT", "ITL", "Decode", "Throughput", "req/s", "E2E", "Open-loop", "Closed-loop", "KV Cache", "Prefix Cache", "P50", "P95", "P99"];
  const savedInit = globalThis.echarts.init;
  try {
    for (const mode of ["plain", "pro"]) withMode(mode, () => {
      CHARTS.clear();                    /* 图表实例按 id 缓存, 换模式要重新建 */
      const opts = recordCharts();
      const a = synthPerfRun(), b = synthPerfRun();
      const html = perfSectionsHTML(a, b, "t") + allMetricsSection(a, b, "t") + perfSectionsHTML(a, null, "s") + allMetricsSection(a, null, "s");   /* A/B 对比和单个测试的表头写法不同, 都要查 */
      drawPerfCharts(a, b, "t");
      drawPerfCharts(a, null, "s");
      const labels = [...labelTexts(html), ...chartTexts(opts)];
      assert.ok(labels.length > 60 && opts.size >= 15, `${mode}: 只收集到 ${labels.length} 个标签、${opts.size} 张图`);
      for (const s of labels) assert.ok(!/[{}]/.test(s), `${mode}: 标签里有残留模板: ${s}`);
      const bad = mode === "plain" ? proWords : plainNames;
      for (const s of labels) for (const w of bad) assert.ok(!s.includes(w), `${mode}: 标签「${s}」里出现了不该出现的「${w}」`);
      const all = labels.join("\n");
      const want = mode === "plain" ? ["首字等待 较慢", "总生成速度", "同时请求数", "读入速度", "出字间隔 一般", "显存缓存占用", "每秒完成请求数", "完整响应 较慢"]
        : ["TTFT P95", "Throughput", "并发", "Prefill", "ITL P50", "KV Cache 使用率", "req/s", "E2E P95", "Per-stream TPS", "Prefill 总吞吐"];
      for (const w of want) assert.ok(all.includes(w), `${mode}: 没有找到「${w}」`);
      /* 复制 / 导出 CSV 用的表头也是同一套写法(A/B 对比表是「指标（单位） A / B / A 比 B」, 单个测试是「指标（单位）」) */
      const csvAB = tablesCSV(["t-conc-t"]), csvOne = tablesCSV(["s-conc-t"]);
      const head = mode === "plain" ? "首字等待 较慢（秒）" : "TTFT P95（秒）";
      const line1 = t => t.split("\n")[1];   /* 第 0 行是表名, 第 1 行是表头 */
      assert.ok(csvAB.includes(`${head} A,${head} B,${head} A 比 B`), `${mode}: ${line1(csvAB)}`);
      assert.ok(line1(csvOne).includes(head), `${mode}: ${line1(csvOne)}`);
    });
  } finally {
    globalThis.echarts.init = savedInit;
    CHARTS.clear();
  }
});
T("速度测试的结论句和章节说明: 词的位置按 key 换, 大白话模式一字不差, 专业模式补空格; 指标卡的补充说明也一样", () => {
  const run = synthPerfRun();
  run.phases[0].points.push({conc: 8, agg_tps: 280, per_stream_tps_med: 30, ttft_p50_s: 2, ttft_p95_s: 4.5, ok: 16, fail: 0});
  const sentences = () => perfConclusions(run, null).map(i => stripTags(i.html));
  const descs = () => [...perfSectionsHTML(run, null, "s").matchAll(/<p class="(?:sec|ccard)-desc">([\s\S]*?)<\/p>/g)].map(m => stripTags(m[1]));
  withMode("plain", () => {
    assert.ok(sentences().includes("同时 4 个请求时总速度最高，每秒 300 token，是 1 个请求时的 3.0 倍；再加到 8 个反而降到 280，4 个左右就是上限。"));
    assert.ok(sentences().includes("从同时 8 个请求开始明显变慢：首字等待较慢时 4.50 秒。"));
    assert.ok(sentences().includes("输入 4K（约 4,000 token）时要等 0.70 秒才开始回答，读入速度 6,000 token/秒。"));
    assert.ok(descs().includes("横轴是同时请求数。总速度通常先涨后平；每个请求分到的速度和首字等待会随之变差。虚线是 3 秒：超过它用户会觉得慢"));
    assert.ok(descs().includes("● 一般　┃ 较慢　○ 最慢 · 越靠左越快、越短越稳"));
    assert.ok(descs().includes("显存缓存接近 100% 时新请求要排队；复用率越高越省时"));
    assert.ok(descs().includes("测试期间服务端的显存缓存占用和重复内容复用率（来自 vLLM /metrics）"));
    assert.equal(stripTags(perfMetaLine(Object.assign({}, run, {overrides: {fixed_output: true}}))).split(" · ").pop(), "每次生成满指定长度");
    assert.ok(perfAnomalies({phases: [{id: "concurrency", points: [{conc: 1, agg_tps: 100}, {conc: 2, agg_tps: 50}]}]}).some(t => t.includes("时，总生成速度不升反降（")));
  });
  withMode("pro", () => {
    assert.ok(sentences().includes("同时 4 个请求时 Throughput 最高，每秒 300 token，是 1 个请求时的 3.0 倍；再加到 8 个反而降到 280，4 个左右就是上限。"));
    assert.ok(sentences().includes("从同时 8 个请求开始明显变慢：TTFT P95 时 4.50 秒。"));
    assert.ok(sentences().includes("输入 4K（约 4,000 token）时要等 0.70 秒才开始回答，Prefill 6,000 token/秒。"));
    assert.ok(descs().includes("横轴是并发。Throughput 通常先涨后平；每个请求分到的速度和 TTFT 会随之变差。虚线是 3 秒：超过它用户会觉得慢"));
    assert.ok(descs().includes("● P50　┃ P95　○ P99 · 越靠左越快、越短越稳"));
    assert.ok(descs().includes("KV Cache 使用率接近 100% 时新请求要排队；Prefix Cache 命中率越高越省时"));
    assert.ok(descs().includes("测试期间服务端的 KV Cache 使用率和 Prefix Cache 命中率（来自 vLLM /metrics）"));
    assert.equal(stripTags(perfMetaLine(Object.assign({}, run, {overrides: {fixed_output: true}}))).split(" · ").pop(), "ignore_eos");
    assert.ok(perfAnomalies({phases: [{id: "concurrency", points: [{conc: 1, agg_tps: 100}, {conc: 2, agg_tps: 50}]}]}).some(t => t.includes("时，Throughput 不升反降（")));
    const stats = stripTags(perfStats(run, null));
    assert.ok(stats.includes("单个请求 Decode · 中文") && stats.includes("每次写 256 token · ITL 10.0 毫秒") && stats.includes("最高 Throughput") && stats.includes("TTFT · 输入 4K") && stats.includes("Prefill 6,000 token/秒"), stats);
  });
});
T("能力测试的表头和柱状图: 误差范围 / 差异是否可信 / 没答完 在两种模式下的写法", () => {
  const sub = (id, n, c) => ({id, name: "科" + id, n, correct: c, acc: 100 * c / n, ci_lo: 50, ci_hi: 90, truncated: 1, errors: 0, out_tokens: 100});
  const one = [{r: {run_id: "a", subjects: [sub("s", 10, 8)]}, color: "#000", tag: "A"}];
  const two = one.concat([{r: {run_id: "b", subjects: [sub("s", 10, 7)]}, color: "#111", tag: "B"}]);
  const cols = specs => [specs.compact, specs.full].flatMap(s => s.columns.flatMap(c => [c.label, c.group || ""]));
  withMode("plain", () => {
    assert.ok(cols(iqSubjSpecs(one)).includes("误差范围") && cols(iqSubjSpecs(one)).includes("没答完"));
    assert.ok(cols(iqSubjSpecs(two)).includes("差异是否可信"));
    assert.equal(iqIssues({overall: {truncated: 2, errors: 1}}).join("|"), "2 题没答完|1 题请求失败");
  });
  withMode("pro", () => {
    assert.ok(cols(iqSubjSpecs(one)).includes("95% CI") && cols(iqSubjSpecs(one)).includes("截断"));
    assert.ok(cols(iqSubjSpecs(two)).includes("McNemar"));
    assert.ok(!cols(iqSubjSpecs(two)).concat(cols(iqSubjSpecs(one))).some(s => /误差范围|没答完|差异是否可信/.test(s)));
    assert.equal(iqIssues({overall: {truncated: 2, errors: 1}}).join("|"), "2 题截断|1 题请求失败");
    assert.equal(QB_STATE.trunc[0], "截断");
  });
  assert.equal(QB_STATE.trunc[0], "没答完");
  assert.deepEqual(QB_STATE.ok, ["答对", "good", "check"]);
});
T("代码生成页的名词(对照运行 / 陷入重复输出 / AI 看图打分 / 实际运行检查): 两种模式下的写法, 大白话模式和原来一字不差", () => {
  const it = {file: "works/r/t.html", pass: 0, total: 0, eval: {method: "browser", checks: [], shots: [], shots_dir: "s", control: {errors: ["x"], reproduced: true}}};
  const plain = h => stripTags(h);
  withMode("plain", () => {
    assert.ok(plain(checksPanel(it)).includes("对照运行："));
    assert.equal(plain(termHtml("{run|实际运行检查}通过率")), "实际运行检查通过率");
    assert.equal(plain(termHtml("报错的作品里有 3 件在不加任何检测代码的干净环境里{rerun}也同样报错")), "报错的作品里有 3 件在不加任何检测代码的干净环境里重新运行也同样报错");
    assert.equal(plain(termHtml("模型{repeat}")), "模型陷入重复输出");
    assert.equal(termText("{judge}：都没打出分"), "AI 看图打分：都没打出分");
    assert.equal(termText("没有配置{judge}"), "没有配置AI 看图打分");
  });
  withMode("pro", () => {
    assert.ok(plain(checksPanel(it)).includes("干净环境复现："));
    assert.equal(plain(termHtml("{run|实际运行检查}通过率")), "Headless 运行检测通过率");
    assert.equal(plain(termHtml("报错的作品里有 3 件在不加任何检测代码的干净环境里{rerun}也同样报错")), "报错的作品里有 3 件在不加任何检测代码的干净环境里复现也同样报错");
    assert.equal(plain(termHtml("模型{repeat}")), "模型退化重复");
    assert.equal(termText("{judge}：都没打出分"), "VLM Judge：都没打出分");
    assert.equal(termText("没有配置{judge}"), "没有配置 VLM Judge");
    assert.equal(termText("{static}"), "源码检查");
  });
  /* 作品卡、排序、检查方式这些「标签」里的词也跟着走 */
  const card = h => stripTags(h);
  const work = {id: "snake", name: "贪吃蛇", tags: ["普通"], continuations: 4, lines: 10, out_tokens: 100, pass: 3, total: 4, eval: {method: "browser", checks: [], judge: {score: 88, model: "j"}}};
  const verdict = {key: "pass", text: "全部检查通过"}, gctx = {v2: true, mode: "browser", shared: ""};
  withMode("plain", () => {
    assert.ok(card(genCard({run_id: "r"}, work, verdict, gctx)).includes("10 行 · 接着写 4 轮 · 100 token"));
    assert.ok(genCard({run_id: "r"}, work, verdict, gctx).includes('title="AI 看图打分"'));
    assert.equal(genSorts().find(x => x[0] === "rounds")[1], "接着写的轮数（多的在前）");
    assert.equal(evalMethodText({method: "browser", judge_model: "m"}), "检查方式：在后台浏览器里实际运行检查 + AI 看图打分（m）");
    assert.equal(evalMethodText({method: "browser"}), "检查方式：在后台浏览器里实际运行检查，没有配置 AI 看图打分");
    assert.equal(samplingTextGen({}), "随机性：旧版 T0.3");
    assert.ok(judgePanel({eval: {}}).includes("没有配置 AI 看图打分。在「新建生成任务」里"));
  });
  withMode("pro", () => {
    assert.ok(card(genCard({run_id: "r"}, work, verdict, gctx)).includes("10 行 · 续写 4 轮 · 100 token"));
    assert.ok(genCard({run_id: "r"}, work, verdict, gctx).includes('title="VLM Judge"'));
    assert.equal(genSorts().find(x => x[0] === "rounds")[1], "续写的轮数（多的在前）");
    assert.equal(evalMethodText({method: "browser", judge_model: "m"}), "检查方式：在后台浏览器里实际运行检查 + VLM Judge（m）");
    assert.equal(evalMethodText({method: "browser"}), "检查方式：在后台浏览器里实际运行检查，没有配置 VLM Judge");
    assert.equal(samplingTextGen({}), "采样参数：旧版 T0.3");
    assert.ok(judgePanel({eval: {}}).includes("没有配置 VLM Judge。在「新建生成任务」里"));
  });
});
T("名词解释: 每个词一行, 左边大白话 + 完整说法, 右边解释; 搜索能搜到专业词(两种模式内容一样)", () => {
  const list = glossaryItems();
  for (const k of Object.keys(TERMS)) assert.ok(list.includes(`id="gl-${k}"`), k);
  assert.ok(list.includes('class="glossary-name">首字等待<') && list.includes('class="glossary-tech">TTFT（Time To First Token）<'));
  const gl = k => new RegExp(`id="gl-${k}" data-gl="([^"]*)"`).exec(list)[1];
  assert.ok(gl("prefill").includes("prefill") && gl("pct").includes("p95") && gl("agg").includes("throughput") && gl("prefix").includes("prefix cache"));
  assert.equal(withMode("pro", () => glossaryItems()), list);
});
T("术语模式: 切换后写入本地偏好、能读回来; 只认 plain / pro; 导出离线报告会带上", () => {
  const store = new Map(), saved = globalThis.localStorage, mode0 = TERM_MODE;
  globalThis.localStorage = {getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k)};
  try {
    assert.equal(TERM_LS, "llm-bench-pro-terms");
    setTermMode("pro", true);
    assert.equal(TERM_MODE, "pro");
    assert.equal(store.get(TERM_LS), "pro");
    assert.equal(termModeOf(LS.get(TERM_LS)), "pro");                    /* 刷新后读回来 */
    assert.equal(termWord("prefill"), "Prefill");
    setTermMode("plain", true);
    assert.equal(store.get(TERM_LS), "plain");
    assert.equal(termModeOf(LS.get(TERM_LS)), "plain");
    assert.equal(termWord("prefill"), "读入速度");
    store.clear();
    setTermMode("pro", false);                                           /* 启动时按已有偏好应用, 不重复写 */
    assert.equal(TERM_MODE, "pro");
    assert.equal(store.has(TERM_LS), false);
    setTermMode("bogus", true);                                          /* 不认识的值按大白话处理 */
    assert.deepEqual([TERM_MODE, store.get(TERM_LS)], ["plain", "plain"]);
    assert.deepEqual(["pro", "plain", null, undefined, "", "PRO", "x"].map(termModeOf), ["pro", "plain", "plain", "plain", "plain", "plain", "plain"]);
    assert.ok(EXPORT_LS.includes(TERM_LS));                              /* 「导出报告」带上当前模式 */
  } finally {
    globalThis.localStorage = saved;
    TERM_MODE = mode0;
  }
  assert.equal(TERM_MODE, "plain");
});
T("模型管理「用过的测试」摘要里的指标名也跟着术语模式走; 单个请求这样的普通说明文字不变", () => {
  const r = {kind: "perf", summary: {peak_tps: 1280.84, peak_conc: 4, decode_tps: 410}};
  assert.equal(withMode("plain", () => mdRunSummary(r)), "最高总生成速度 1280.8 token/秒（同时 4 个请求） · 单个请求 410.0 token/秒");
  assert.equal(withMode("pro", () => mdRunSummary(r)), "最高 Throughput 1280.8 token/秒（同时 4 个请求） · 单个请求 410.0 token/秒");
});
T("页面结构: 侧栏底部有术语切换按钮(aria-pressed), 每个「更多」菜单里都有切换项, 图标存在", () => {
  const fs = require("node:fs"), path = require("node:path");
  const html = fs.readFileSync(path.join(process.env.LLMB_ROOT || process.cwd(), "web", "index.html"), "utf8");
  assert.ok(/<button[^>]*id="termsBtn"[^>]*aria-pressed="false"/.test(html) && html.includes('title="术语：大白话 / 专业"'));
  assert.ok(html.indexOf('id="themeBtn"') < html.indexOf('id="termsBtn"') && html.indexOf('id="termsBtn"') < html.indexOf('id="railPin"'));   /* 在主题切换旁边 */
  const themes = html.match(/data-theme-toggle/g).length, terms = html.match(/data-terms-toggle/g).length;
  assert.ok(themes >= 4 && terms === themes, `切换亮色的菜单项 ${themes} 个, 切换术语的 ${terms} 个`);
  assert.equal(html.match(/data-terms-toggle[^>]*><svg[^>]*><use href="#i-terms"\/><\/svg>切换术语：大白话 \/ 专业</g).length, terms);
  assert.ok(html.includes('<symbol id="i-terms"'));
});
T("deltaPill: 越低越好的指标变小算更好; 小于 1% 算持平", () => {
  assert.ok(deltaPill(10, 8, -1).includes("delta up"));
  assert.ok(deltaPill(10, 12, -1).includes("delta down"));
  assert.ok(deltaPill(100, 100.5, 1).includes("持平"));
  assert.ok(deltaPill(null, 1, 1).includes("—"));
  assert.ok(deltaPill(80, 82, 1, {mode: "pp"}).includes("+2.0 个百分点"));
});
T("genVerdict: 按优先级只取一个主要问题", () => {
  assert.equal(genVerdict({error: "x"}).key, "fail");
  assert.equal(genVerdict({degenerate: {kind: "loop", period: 1, repeats: 9000}, eval: {checks: []}}).key, "repeat");
  assert.equal(genVerdict({eval: {method: "static", checks: [{id: "doctype", pass: true}]}}).key, "static");
  assert.equal(genVerdict({eval: {method: "browser", checks: [{id: "nonblank", pass: false}]}}).key, "blank");
  assert.equal(genVerdict({eval: {method: "browser", checks: [{id: "no_error", pass: false}], control: {reproduced: false}}}).key, "env");
  assert.equal(genVerdict({eval: {method: "browser", checks: [{id: "no_error", pass: false}], control: {reproduced: true}}}).key, "error");
  assert.equal(genVerdict({eval: {method: "browser", checks: [{id: "step1", label: "交互：跳", pass: false}]}}).key, "partial");
  assert.equal(genVerdict({eval: {method: "browser", checks: [{id: "load", pass: true}]}}).key, "pass");
});
T("changeKind: 区分原样保存 / 只去掉说明 / 拼接续写 / 旧任务", () => {
  assert.equal(changeKind({}), "legacy");
  assert.equal(changeKind({changes: ["原样保存了模型输出，没有做任何修改"]}), "raw");
  assert.equal(changeKind({changes: ["去掉了代码后面的 Markdown 代码块标记"]}), "trimmed");
  assert.equal(changeKind({changes: ["接上第 2 轮续写（直接拼接）"]}), "stitched");
});
T("markRepeat: 重复区从 start 起标记, 其余转义", () => {
  assert.equal(markRepeat("ab<c", 0, null), "ab&lt;c");
  assert.equal(markRepeat("abcdef", 0, {start: 3}), 'abc<mark title="从这里开始重复">def</mark>');
  assert.equal(markRepeat("xyz", 100, {start: 50}), '<mark title="从这里开始重复">xyz</mark>');
  assert.equal(markRepeat("xyz", 0, {start: 50}), "xyz");
});
T("icon: 引用符号 id 且带基类", () => {
  assert.equal(icon("play"), '<svg class="icon "><use href="#i-play"/></svg>');
  assert.equal(icon("stop", "icon-sm"), '<svg class="icon icon-sm"><use href="#i-stop"/></svg>');
});

/* ---------- 启动路径未被破坏 ---------- */
T("app.js 在桩环境下完整加载(执行到了文件尾)", () => {
  assert.ok(typeof render === "function" && typeof renderCmp === "function" && typeof renderGen === "function" && typeof chartInst === "function");
});

/* ---------- 生成物预览沙箱策略 (游戏"点开始无反应"事故锚点) ---------- */
T("GEN_SANDBOX: 放行脚本/弹窗, 始终不放行 same-origin", () => {
  /* localStorage 由服务端 /works 垫片兜底, 这里守住"不给作品同源权限"的安全底线 */
  const flags = GEN_SANDBOX.split(/\s+/);
  assert.ok(flags.includes("allow-scripts"));
  assert.ok(flags.includes("allow-modals"));        /* alert/confirm 不再被静默吞掉 */
  assert.ok(!flags.includes("allow-same-origin"));  /* 作品不得触达父页面与后端接口 */
  assert.ok(!flags.includes("allow-top-navigation"));
  assert.ok(!flags.includes("allow-popups"));
});

T("renderIq 有异常兜底包装(渲染错误不会静默白屏)", () => {
  assert.ok(typeof renderIq === "function" && typeof _renderIq === "function" && renderIq !== _renderIq);
});
T("逐题查看: 作答状态与筛选口径(对照只看双方都正常作答的题)", () => {
  assert.equal(qbState(null), "none");
  assert.equal(qbState({ok: true}), "ok");
  assert.equal(qbState({ok: false, err: "timeout"}), "err");
  assert.equal(qbState({ok: false, trunc: true}), "trunc");
  assert.equal(qbState({ok: false}), "wrong");
  const ok = {ok: true}, bad = {ok: false}, cut = {ok: false, trunc: true}, err = {ok: false, err: "x"};
  assert.ok(qbPass("all", ok) && qbPass("ok", ok) && !qbPass("ok", bad));
  assert.ok(qbPass("bad", bad) && qbPass("bad", cut) && qbPass("bad", err));   /* 没答对 = 答错 + 没答完 + 请求失败 */
  assert.ok(qbPass("trunc", cut) && !qbPass("trunc", bad) && qbPass("err", err) && !qbPass("err", bad));
  assert.ok(qbPass("vs-a", ok, bad) && !qbPass("vs-a", ok, ok) && !qbPass("vs-a", ok, err) && !qbPass("vs-a", ok, null));
  assert.ok(qbPass("vs-b", bad, ok) && !qbPass("vs-b", err, ok));
  assert.ok(qbPass("vs-none", bad, cut) && !qbPass("vs-none", bad, err));
});
T("逐题查看: MMLU 学科名换成中文, 未知的去下划线", () => {
  assert.equal(subTopic("high_school_physics"), "高中物理");
  assert.equal(subTopic("brand_new_subject"), "brand new subject");
  assert.equal(subTopic(""), "");
});
T("表格排序: 数字升降、空值永远排最后、相等保持原顺序", () => {
  const spec = {id: "t-sort", columns: [{key: "v", type: "num"}, {key: "s", type: "status"}]};
  const rows = [{v: 3, i: 0}, {v: null, i: 1}, {v: 10, i: 2}, {v: 3, i: 3}, {v: NaN, i: 4}];
  assert.deepEqual(dtSortRows(spec, rows, {key: "v", dir: "asc"}).map(r => r.i), [0, 3, 2, 1, 4]);
  assert.deepEqual(dtSortRows(spec, rows, {key: "v", dir: "desc"}).map(r => r.i), [2, 0, 3, 1, 4]);
  assert.deepEqual(dtSortRows(spec, rows, null).map(r => r.i), [0, 1, 2, 3, 4]);
  const st = [{s: {tone: "good"}}, {s: {tone: "bad"}}, {s: {tone: "warn"}}];
  assert.deepEqual(dtSortRows(spec, st, {key: "s", dir: "desc"}).map(r => r.s.tone), ["bad", "warn", "good"]);  /* 按严重程度 */
});
T("表格数字: 千分位 + 固定小数, 空值占位; 导出不带千分位", () => {
  assert.equal(numText(1774.63, 1), "1,774.6");
  assert.equal(numText(7, 2), "7.00");
  assert.equal(numText(null), "—");
  assert.equal(dtExport({key: "v", type: "num", digits: 1}, {v: 1774.63}), "1774.6");
  assert.equal(dtExport({key: "v", type: "delta"}, {v: -5.04}), "-5.0%");
  assert.equal(dtExport({key: "v", type: "status"}, {v: {tone: "bad", text: "没过"}}), "没过");
});
T("CSV / TSV: 逗号、引号、换行正确转义, CSV 带 BOM", () => {
  assert.equal(csvCell("a,b"), '"a,b"');
  assert.equal(csvCell('说 "好"'), '"说 ""好"""');
  assert.equal(csvCell("x\ny"), '"x\ny"');
  assert.equal(csvCell(12.5), "12.5");
  const m = {head: ["指标", "值"], rows: [["速度, 中文", "130.8"], ["说明\t含制表符", "1"]]};
  const csv = toCSV(m);
  assert.ok(csv.startsWith("﻿"));
  assert.ok(csv.includes('"速度, 中文",130.8'));
  assert.equal(toTSV(m).split("\n")[2], "说明 含制表符\t1");
});
T("变化判定: 按方向判断好坏, 差别小于 1% 为持平", () => {
  assert.ok(deltaText(0.6, 1).includes("持平"));
  assert.ok(deltaText(5, 1).includes("up"));
  assert.ok(deltaText(5, -1).includes("down"));   /* 越低越好的指标变大 = 更差 */
  assert.ok(deltaText(-5, -1).includes("up"));
  assert.ok(deltaText(null, 1).includes("—"));
});
T("矩阵整形与对比整形", () => {
  const p = pivotRows([{l: "1K", c: 1, v: 0.1}, {l: "1K", c: 4, v: 0.3}, {l: "2K", c: 1, v: 0.2}], {row: "l", col: "c", value: "v"});
  assert.deepEqual(p.cols, [1, 4]);
  assert.deepEqual(p.rows.map(r => r._row), ["1K", "2K"]);
  assert.equal(p.rows[0].c_4, 0.3);
  assert.equal(p.rows[1].c_4, undefined);
  const rows = compareRows([1], [{v: 100}, {v: 110}], (x, k) => x, [{key: "m", get: r => r.v}]);
  assert.equal(rows[0].m_0, 100);
  assert.equal(rows[0].m_1, 110);
  assert.equal(Math.round(rows[0].m_d), -9);   /* 变化 = A 比 B: 100 比 110 少 9.1% */
  const cols = compareCols([{tag: "A"}, {tag: "B"}], [{key: "m", label: "速度", unit: "token/秒", dir: 1}]);
  assert.deepEqual(cols.map(c => c.label), ["A", "B", "A 比 B"]);   /* 变化列写明方向 */
  assert.equal(cols[0].group, "速度（token/秒）");
});
T("翻页: 页码列表(首尾 + 当前页前后, 只隔一页时直接显示那一页, 隔得多才用 …)", () => {
  assert.deepEqual(pageList(0, 1), [0]);
  assert.deepEqual(pageList(2, 5), [0, 1, 2, 3, 4]);
  assert.deepEqual(pageList(0, 154), [0, 1, 2, 3, 4, null, 153]);
  assert.deepEqual(pageList(3, 154), [0, 1, 2, 3, 4, null, 153]);
  assert.deepEqual(pageList(4, 154), [0, null, 3, 4, 5, null, 153]);
  assert.deepEqual(pageList(49, 154), [0, null, 48, 49, 50, null, 153]);
  assert.deepEqual(pageList(153, 154), [0, null, 149, 150, 151, 152, 153]);
  assert.deepEqual(pageList(4, 8), [0, null, 3, 4, 5, 6, 7]);
  for (let n = 1; n <= 40; n++) for (let p = 0; p < n; p++) {
    const l = pageList(p, n), nums = l.filter(x => x != null);
    assert.ok(nums.includes(0) && nums.includes(n - 1) && nums.includes(p), `n=${n} p=${p}`);
    assert.ok(nums.every((x, i) => !i || x > nums[i - 1]), "递增");
    assert.ok(l.every((x, i) => x != null || (l[i + 1] - l[i - 1] > 2)), "… 至少省略两页");
    assert.ok(n <= 7 ? l.length === n : l.length <= 7, "页数多时最多 7 格");
  }
});
T("翻页: 跳页输入框解析(夹到首末页, 非数字不跳)", () => {
  const box = (value, max) => ({value, max: String(max)});
  assert.equal(pagerTarget(box("50", 154)), 49);
  assert.equal(pagerTarget(box(" 7 ", 154)), 6);
  assert.equal(pagerTarget(box("999", 154)), 153);
  assert.equal(pagerTarget(box("0", 154)), 0);
  assert.equal(pagerTarget(box("-3", 154)), 0);
  assert.equal(pagerTarget(box("", 154)), null);
  assert.equal(pagerTarget(box("abc", 154)), null);
  assert.equal(pagerTarget(null), null);
});
T("翻页器 HTML: 只有一页时不出翻页按钮; 当前页标 aria-current; 首页的 ‹ 不可点", () => {
  assert.equal(pagerHTML("qb", {page: 0, pages: 1, compact: true}), "");
  assert.ok(!pagerHTML("qb", {page: 0, pages: 1, total: 3, unit: "题"}).includes("data-qb-page"));
  const h = pagerHTML("dt", {page: 0, pages: 19, size: 50, sizes: [20, 50]});
  assert.ok(/data-dt-page="-1" data-dir="prev"[^>]*disabled/.test(h));
  assert.ok(h.includes('aria-current="page">1<'));
  assert.ok(h.includes('<option value="50" selected>'));
  assert.ok(h.includes("data-dt-jump") && h.includes("data-dt-jumpbtn"));
});
T("散点名字防重叠: 挨着的点名字错开一行、统一从这一簇最右边的点右侧开始", () => {
  const p = (tok, acc) => ({value: [tok, acc]});
  const a = p(2.0, 73.8), b = p(2.2, 73.8), c = p(2.0, 72.9), far = p(1200, 76.2);
  const o = scatterLabelOffsets([a, b, null, c, far], {plotW: 1200, plotH: 300, yMin: 50, yMax: 100});
  const y = q => (100 - q.value[1]) * 6 + o.get(q)[1];   /* 6 px / 每 1% */
  const ys = [a, b, c].map(y).sort((m, n) => m - n);
  assert.ok(ys[1] - ys[0] >= 15 && ys[2] - ys[1] >= 15, ys.join(","));
  assert.ok(o.get(a)[0] > 0 && Math.abs(o.get(b)[0]) < 1e-9, "簇里左边的点名字往右挪到最右那个点之后");
  assert.deepEqual(o.get(far), [0, 0]);   /* 单独的点不动 */
});
T("离线报告: 接口从报告数据里取(逐题只留请求的测试、回答按题取、返回副本、取不到报错)", () => {
  const B = {api: {version: {version: "9"}, perfList: [{run_id: "r1"}], perfRuns: {r1: {run_id: "r1"}},
    iqItems: {questions: [1], runs: {a: {recs: {}}, b: {recs: {}}, c: {recs: {}}}}, iqCompare: {"a|b": {ok: true}},
    iqAnswers: {"s|0": {type: "mcq", prompt: "p", answers: {a: {ok: true}, b: {ok: false}}}}, genList: [{run_id: "g"}]},
    files: {"works/x/t.gen.json": {rounds: []}, "works/x/t.html": "<p>hi</p>"}};
  assert.equal(offlineApi(B, "/api/version").version, "9");
  assert.equal(offlineApi(B, "/api/run?id=r1").run_id, "r1");
  assert.throws(() => offlineApi(B, "/api/run?id=zz"), /没有这部分数据/);
  assert.deepEqual(Object.keys(offlineApi(B, "/api/iq-items?id=a&cmp=b").runs), ["a", "b"]);
  assert.deepEqual(Object.keys(offlineApi(B, "/api/iq-items?id=b&cmp=").runs), ["b"]);   /* 报告里换主测试 */
  assert.throws(() => offlineApi(B, "/api/iq-items?id=zz"));
  assert.deepEqual(offlineApi(B, "/api/iq-compare?a=a&b=b"), {ok: true});
  assert.equal(offlineApi(B, "/api/iq-compare?a=c&b=a"), null);
  const ans = offlineApi(B, "/api/iq-answer?ids=a&sid=s&idx=0");
  assert.deepEqual([Object.keys(ans.answers), ans.prompt, ans.idx], [["a"], "p", 0]);
  assert.equal(offlineApi(B, "/api/iq-answer?ids=a&sid=s&idx=9").ok, false);
  assert.deepEqual(offlineApi(B, "/works/x/t.gen.json"), {rounds: []});
  assert.throws(() => offlineApi(B, "/works/x/t.html"));      /* 作品网页不走接口, 用 workUrl / workFrameSrc */
  assert.deepEqual(offlineApi(B, "/api/banks"), []);
  assert.equal(offlineApi(B, "/api/gen-status").running, false);
  const r = offlineApi(B, "/api/results"); r.push(2);
  assert.equal(offlineApi(B, "/api/results").length, 1);       /* 返回副本: 页面改了不影响下次取 */
  assert.equal(OFF, null);                                      /* 正常页面不是离线模式 */
  assert.equal(workUrl("works/x/t.html"), "/works/x/t.html");
  assert.equal(workOpenUrl("works/x/t.html"), "/works/x/t.html?open=1");
  assert.equal(workFrameSrc("works/x/t.html"), 'src="/works/x/t.html"');
});
T("场景失败: 统计失败数与错误; 图片理解全部 HTTP 400 时先查图片尺寸再查模型是否支持看图", () => {
  const f = scnFails({id: "scn_vision", points: [{total: 12, ok: 0, errors: ["HTTP Error 400: Bad Request"]},
    {total: 24, ok: 0, errors: ["HTTP Error 400: Bad Request"]}]});
  assert.deepEqual([f.total, f.ok, f.fail, f.errs.length], [36, 0, 36, 1]);
  assert.ok(f.hint.includes("28×28") && f.hint.includes("224×224") && f.hint.includes("是否支持看图"));
  const g = scnFails({id: "scn_chat", points: [{total: 10, ok: 9, errors: ["timeout", "reset"]}]});
  assert.deepEqual([g.fail, g.hint], [1, ""]);
  assert.ok(g.why.includes("等 2 种错误"));
  assert.equal(scnFails({id: "scn_vision", points: [{total: 5, ok: 0, errors: ["timeout"]}]}).hint, "");   /* 不是 400 不乱猜 */
  assert.equal(scnFails({id: "scn_json", points: []}).total, 0);
});
T("看图回答失败: 服务端原因看得出是图片太小 / 模型不支持看图时直说, 原因原样显示", () => {
  const small = 'HTTP 400: {"error": {"message": "height:1 or width:1 must be larger than factor:28"}}';
  const f = scnFails({id: "scn_vision", points: [{total: 4, ok: 0, errors: [small]}]});
  assert.ok(f.hint.includes("图片太小") && f.why.includes("must be larger than factor"));
  assert.ok(visionFailHint(['HTTP 400: {"message": "Qwen3 is not a multimodal model"}']).includes("不支持看图"));
  assert.ok(visionFailHint(["HTTP 400: At most 0 image(s) may be provided in one request."]).includes("不支持看图"));
  assert.equal(visionFailHint(["HTTP 500: boom"]), "");
  assert.equal(scnFails({id: "scn_vision", points: [{total: 4, ok: 1, errors: [small]}]}).hint, "");  /* 有成功的不下结论 */
});
T("场景素材: 大小显示、图片包说明(标出太小的张数)、任务集检查报告", () => {
  assert.deepEqual([fmtBytes(70), fmtBytes(2048), fmtBytes(3 * 1048576), fmtBytes(null)], ["70 B", "2 KB", "3.0 MB", "—"]);
  const t = imgPackText({image_id: "img-c414cd0e204d", count: 1, dims: "1×1", size: 70, mtime: "2026-09-24T21:01:00", too_small: 1, broken: 0});
  assert.ok(t.startsWith("图片包 c414cd0e · 1 张 · 1×1 · 70 B") && t.includes("有 1 张太小，会被模型拒绝"));
  const ok = taskReportHtml({ok: true, check: {total: 3, valid: 2, json: 1, image: 1, hint: "",
    problems: [{line: 2, reason: "不是合法的 JSON（第 5 个字符附近：缺少逗号）"}], warnings: [], warning_count: 0}}, "t.jsonl");
  assert.ok(ok.includes("is-warn") && ok.includes("可用 2 行") && ok.includes("第 2 行：") && ok.includes("带 response_format 1 条") && ok.includes("带图片 1 条"));
  const none = taskReportHtml({ok: false, error: "没有一行能用", check: {total: 1, valid: 0, json: 0, image: 0, hint: "",
    problems: [{line: 1, reason: "<b>x</b>"}], warnings: [], warning_count: 0}}, "t.jsonl");
  assert.ok(none.includes("is-bad") && none.includes("&lt;b&gt;x&lt;/b&gt;") && !none.includes("<b>x</b>"));  /* 原因转义 */
  const img = imgReportHtml({ok: true, count: 1, size: 2000, dims: "448×448", files: [{name: "a.png", ok: true, level: "ok", msg: ""},
    {name: "b.png", ok: false, level: "bad", msg: "只有 1×1 像素，太小"}]});
  assert.ok(img.includes("已收进图片包 1 张") && img.includes("1 张没收") && img.includes("b.png：只有 1×1 像素"));
  const warn = imgReportHtml({ok: true, count: 1, size: 2000, dims: "300×300", files: [{name: "p.jpg", ok: true, level: "warn", msg: "扩展名是 .jpg，实际是 PNG 图片"}]});
  assert.ok(warn.includes("is-warn") && !warn.includes("没收") && warn.indexOf("收下了，但要注意") < warn.indexOf("p.jpg"));  /* 收下的不混进「没收」里 */
});
T("任务集模板: 每行都是带 messages 的对象, 覆盖 system / 多轮 / JSON 输出 / 图片 / max_tokens / temperature", () => {
  const lines = TASK_TEMPLATE.map(x => JSON.stringify(x));
  assert.ok(lines.every(l => !l.includes("\n") && Array.isArray(JSON.parse(l).messages)));
  const has = f => TASK_TEMPLATE.some(f);
  assert.ok(has(x => x.messages.some(m => m.role === "system")));
  assert.ok(has(x => x.messages.some(m => m.role === "assistant")));
  assert.ok(has(x => x.params && x.params.response_format && x.params.response_format.type === "json_object"));
  assert.ok(has(x => x.params && x.params.response_format && x.params.response_format.type === "json_schema"));
  assert.ok(has(x => x.messages.some(m => Array.isArray(m.content) && m.content.some(p => p.type === "image_url"))));
  assert.ok(has(x => x.params && x.params.max_tokens) && has(x => x.params && x.params.temperature != null));
  assert.ok(TASK_TEMPLATE.every(x => x.meta && x.meta.note));  /* 每行都有说明 */
});
/* ---------- 任务集页面 ---------- */
T("任务集: 地址 #tasks/<id> 拆成页面和任务集 id; id 只认 scn- 加 12 位十六进制", () => {
  assert.deepEqual(parseRoute("#tasks/scn-0123456789ab"), {view: "tasks", sub: "scn-0123456789ab"});
  assert.deepEqual(parseRoute("#tasks"), {view: "tasks", sub: ""});
  assert.deepEqual(parseRoute("dash"), {view: "dash", sub: ""});
  assert.ok(TS_ID_RE.test("scn-0123456789ab"));
  for (const bad of ["scn-0123456789AB", "scn-0123456789abc", "../x", "scn-", ""]) assert.ok(!TS_ID_RE.test(bad), bad);
  assert.ok(VIEWS.tasks === "viewTasks");
});
T("任务集名称: 去掉控制字符和首尾空白, 1–80 个字(按字数不按字节), 与服务端同一套规则", () => {
  assert.deepEqual(tsNameCheck("  客服\u0000问答‮ \n"), {ok: true, name: "客服问答", n: 4, error: ""});
  assert.equal(tsNameCheck("").error, "名称不能为空");
  assert.equal(tsNameCheck(" \t﻿ ").error, "名称不能为空");
  assert.ok(tsNameCheck(null).error.includes("不能为空"));
  assert.ok(tsNameCheck("字".repeat(80)).ok);
  const long = tsNameCheck("字".repeat(81));
  assert.ok(!long.ok && long.error.includes("80") && long.error.includes("81"));
  assert.ok(tsNameCheck("😀".repeat(80)).ok);          /* 表情算 1 个字 */
  assert.equal(tsNameCheck("😀".repeat(81)).n, 81);
});
T("任务集逐行状态: 文字 + 图标 + 颜色, 不只靠颜色区分; 不认识的按有问题处理", () => {
  assert.deepEqual([tsStatusOf("ok").text, tsStatusOf("ok").tone, tsStatusOf("ok").icon], ["可用", "good", "check"]);
  assert.deepEqual([tsStatusOf("skip").text, tsStatusOf("skip").tone], ["会跳过", "warn"]);
  assert.deepEqual([tsStatusOf("bad").text, tsStatusOf("bad").tone, tsStatusOf("bad").icon], ["有问题", "bad", "x"]);
  assert.equal(tsStatusOf("???").text, "有问题");
  for (const k of ["ok", "skip", "bad"]) assert.ok(tsStatusOf(k).tip);
  assert.equal(tsRoleName("assistant"), "模型之前的回答");
  assert.equal(tsRoleName("system"), "系统提示");
  assert.ok(tsRoleName("usr").includes("usr") && tsRoleName(null).includes("没写"));
});
T("任务集筛选标签: 全部 / 可用 / 有问题 / 带图片 / 要求 JSON 都带数字, 当前的标 aria-pressed", () => {
  const h = tsChipsHTML({all: 14, ok: 12, bad: 2, image: 1, json: 3}, "bad");
  assert.deepEqual([...h.matchAll(/data-ts-filter="(\w+)"/g)].map(m => m[1]), ["all", "ok", "bad", "image", "json"]);
  assert.ok(/data-ts-filter="bad" aria-pressed="true"/.test(h) && /data-ts-filter="all" aria-pressed="false"/.test(h));
  assert.ok(h.includes("全部 <b>14</b>") && h.includes("有问题 <b>2</b>") && h.includes("要求 JSON <b>3</b>"));
  assert.ok(tsChipsHTML(null, "all").includes("带图片 <b>0</b>"));   /* 还没取到数据时显示 0 */
});
T("任务集输入长度分档: 等宽 / 按 10–20–50 倍数; 每档含下限不含上限, 行数加起来不变", () => {
  assert.deepEqual(lenBins([]), []);
  assert.deepEqual(lenBins([null, NaN, -1]), []);
  assert.deepEqual(lenBins([7, 7, 7]).map(b => [b.lo, b.hi, b.n, b.label]), [[7, 8, 3, "7"]]);
  const lin = lenBins([10, 20, 30, 40]);                    /* 最长不到最短的 20 倍: 等宽 */
  assert.deepEqual([lin[0].lo, lin[0].hi - lin[0].lo, lin.reduce((t, b) => t + b.n, 0)], [10, 5, 4]);
  assert.ok(lin.every((b, i) => !i || b.lo === lin[i - 1].hi), "档位首尾相接");
  assert.equal(lin[lin.length - 1].n, 1);                    /* 最后一档有数 */
  const wide = lenBins([5, 12, 180, 1200, 3000, 3000]);       /* 差得多: 0 10 20 50 100 200 500 1K 2K 5K */
  assert.deepEqual(wide.map(b => b.label), ["0–10", "10–20", "20–50", "50–100", "100–200", "200–500", "500–1K", "1K–2K", "2K–5K"]);
  assert.deepEqual(wide.map(b => b.n), [1, 1, 0, 0, 1, 0, 0, 1, 2]);
  const edge = lenBins([1000, 1999, 2000]), binOf = v => edge.find(b => v >= b.lo && v < b.hi);
  assert.ok(binOf(1999) && binOf(2000) && binOf(1999) !== binOf(2000));   /* 含下限、不含上限 */
  const trim = lenBins([150, 160, 5000]);                    /* 前后没数的档去掉 */
  assert.equal(trim[0].n > 0 && trim[trim.length - 1].n > 0, true);
  assert.equal(lenBinText({lo: 1000, hi: 2000}), "1,000–2,000");
  for (let i = 0; i < 30; i++) {                             /* 随机数据: 每个值都落在自己的档里 */
    const xs = Array.from({length: 40}, () => Math.floor(Math.random() * (i % 2 ? 60000 : 900)) + (i % 3) * 7);
    const bins = lenBins(xs);
    assert.equal(bins.reduce((t, b) => t + b.n, 0), xs.length);
    for (const v of xs) assert.equal(bins.filter(b => v >= b.lo && v < b.hi).length, 1, `${v} 不止落在一档`);
  }
});
T("任务集参数说明: max_tokens 没写 / 写错 / 超上限, JSON 输出, 思考开关, 测试时不用的参数", () => {
  const txt = (p, mt) => tsParamItems(p, mt).map(x => x.text);
  assert.ok(txt({}, 4096)[0].includes("没写") && /4\D?096/.test(txt({}, 4096)[0]));   /* 千分位随系统语言 */
  assert.deepEqual(txt({max_tokens: 256}, 256), ["每次最多生成 256 token"]);
  assert.ok(txt({max_completion_tokens: 300}, 300)[0].includes("300"));
  const bad = tsParamItems({max_tokens: "很多"}, 4096)[0];
  assert.ok(bad.text.includes("不是正整数") && bad.tone === "warn");
  assert.ok(tsParamItems({max_tokens: 99999}, 8192)[0].text.includes("超过上限"));
  assert.ok(txt({response_format: {type: "json_object"}}, 4096).includes("要求输出 JSON 对象"));
  assert.ok(txt({response_format: {type: "json_schema", json_schema: {name: "product"}}}, 4096).some(t => t.includes("「product」")));
  assert.ok(txt({enable_thinking: false}, 4096).includes("关闭思考"));
  assert.ok(txt({temperature: 0}, 4096).includes("随机性 0"));
  const all = txt({model: "x", stream: true, top_p: 0.9}, 4096);
  assert.ok(all.some(t => t.includes("top_p = 0.9")) && all.some(t => t.includes("测试时不用：model、stream")));
  assert.ok(tsParamItems({temperature: 0.3}, 4096).every(x => x.tip));   /* 专业说法都在悬停提示里 */
});
T("任务集导入: 只收 .jsonl / .json / .txt(不分大小写), 其他文件说明原因", () => {
  for (const ok of ["a.jsonl", "B.JSON", "c.v2.txt", "路径\\客服.JSONL"]) assert.ok(tsFileCheck(ok).ok, ok);
  const img = tsFileCheck("shot.PNG");
  assert.ok(!img.ok && img.reason.includes("是图片") && img.reason.includes(".jsonl"));
  assert.ok(tsFileCheck("data.xlsx").reason.includes("是表格"));
  assert.ok(!tsFileCheck("README").ok && !tsFileCheck("").ok && !tsFileCheck("a.jsonl.zip").ok);
});
T("任务集搜索: 搜到的文字标出来, 先转义再标, 不分大小写, 特殊字符照字面找", () => {
  assert.equal(tsHighlight("Apple <b>pie</b> apple", "APPLE"), '<mark class="ts-hl">Apple</mark> &lt;b&gt;pie&lt;/b&gt; <mark class="ts-hl">apple</mark>');
  assert.equal(tsHighlight("a.b*c", ".b*"), 'a<mark class="ts-hl">.b*</mark>c');
  assert.equal(tsHighlight("<x>", ""), "&lt;x&gt;");
  assert.equal(tsHighlight("abc", "zz"), "abc");
  assert.equal(tsHighlight("一二三", "二"), '一<mark class="ts-hl">二</mark>三');
});
T("任务集 max_tokens 概况: 都一样 / 多数是某个值 / 没写的单独说", () => {
  assert.equal(tsMtSummary([[512, 8]], 0).text, "每行都是 512 token");
  const m = tsMtSummary([[512, 8], [256, 2], [4096, 1]], 1);
  assert.equal(m.value, 512);
  assert.ok(m.text.includes("多数是 512 token（8 / 11 行）") && m.text.includes("256（2 行）") && m.text.includes("1 行没写，按 4096"));
  assert.equal(tsMtSummary([], 0).value, null);
});
T("任务集: 多久以前(放进窄的数字格)", () => {
  const now = Date.parse("2026-09-28T12:00:00Z");
  assert.equal(tsAgo("2026-09-28T11:59:30", now), "刚刚");
  assert.equal(tsAgo("2026-09-28T11:55:00", now), "5 分钟前");
  assert.equal(tsAgo("2026-09-28T09:00:00", now), "3 小时前");
  assert.equal(tsAgo("2026-09-26T12:00:00", now), "2 天前");
  assert.match(tsAgo("2026-07-01T00:00:00", now), /^2026-0[67]-\d\d$/);
  assert.equal(tsAgo("", now), "—");
});
T("任务集: 新建面板的选项是「名称 · 可用条数」; 重复导入的检查报告说明它叫什么", () => {
  assert.equal(taskSetText({file_id: "scn-0123456789ab", name: "客服问答", lines: 12, total: 12}), "客服问答 · 12 条可用");
  assert.equal(taskSetText({file_id: "scn-0123456789ab", lines: 12, total: 14}), "scn-0123456789ab · 12 条可用（共 14 行）");
  const c = {total: 3, valid: 3, json: 0, image: 0, hint: "", problems: [], warnings: [], warning_count: 0};
  const dup = taskReportHtml({ok: true, exists: true, name: "旧的<名字>", check: c}, "a.jsonl");
  assert.ok(dup.includes("已经导入过（名称：旧的&lt;名字&gt;）") && dup.includes("没有重复保存"));
  const fresh = taskReportHtml({ok: true, name: "新任务集", check: c}, "新任务集.jsonl");
  assert.ok(fresh.includes("已导入「新任务集」：共 3 行，全部可用") && fresh.includes("is-good"));
});

T("主题切换过渡: 圆心取鼠标点击处", () => {
  assert.deepEqual(themeOrigin({clientX: 120, clientY: 48}), [120, 48]);
  assert.equal(themeOrigin(null).length, 2);   /* 没有事件时也给出圆心(右上角), 不报错 */
});
T("maskKey: API Key 只显示遮住的形式(16 个字以上露头尾各 4 个, 8–15 个露各 2 个, 更短的全遮住), 与服务端同一套", () => {
  assert.equal(maskKey("sk-1234567890abcdef"), "sk-1…cdef");
  assert.equal(maskKey("sk-demo-1234"), "sk…34");
  assert.equal(maskKey("abc"), "••••");
  assert.equal(maskKey(""), "—");
  assert.equal(maskKey(null), "—");
  for (let n = 1; n <= 40; n++) {              /* 任何长度都不会露出完整的 Key, 最多露一半 */
    const k = "k".repeat(n), m = maskKey(k);
    assert.notEqual(m, k);
    assert.ok([...m].filter(c => c === "k").length <= Math.floor(n / 2), `${n} 个字露多了: ${m}`);
  }
});
/* ---------- 模型管理页面 ---------- */
T("模型管理: 地址 #models/<id> 拆成页面和模型 id; id 只认 ep_ 加字母数字下划线", () => {
  assert.deepEqual(parseRoute("#models/ep_1790652162_f0295b25"), {view: "models", sub: "ep_1790652162_f0295b25"});
  assert.ok(VIEWS.models === "viewModels");
  assert.ok(MD_ID_RE.test("ep_1790652162_f0295b25"));
  for (const bad of ["", "ep_", "ep_../x", "scn-0123456789ab", "ep_" + "a".repeat(61), "ep_a b"]) assert.ok(!MD_ID_RE.test(bad), bad);
  assert.ok(!DRAWERS.includes("epDrawer"));      /* 旧的右侧面板没有了 */
});
T("模型管理: 地址规整(去掉首尾空白和末尾的 /v1、/v1/chat/completions, 告诉用户去掉了什么), 与服务端 normalize_base 相同", () => {
  assert.deepEqual(mdUrlClean(" http://127.0.0.1:8000/v1/chat/completions \n"), {url: "http://127.0.0.1:8000", cut: "/v1/chat/completions"});
  assert.deepEqual(mdUrlClean("http://h:8000/v1/"), {url: "http://h:8000", cut: "/v1/"});
  assert.deepEqual(mdUrlClean("http://h:8000/"), {url: "http://h:8000", cut: ""});   /* 只去掉了末尾的 /: 不用提示 */
  assert.deepEqual(mdUrlClean("http://h/gateway/chat/completions"), {url: "http://h/gateway", cut: "/chat/completions"});
  assert.deepEqual(mdUrlClean("http://h:8000"), {url: "http://h:8000", cut: ""});
  for (const ok of ["http://127.0.0.1:8000", "https://api.example.com", "http://[::1]:8000", "http://h:8000/gateway"]) assert.ok(mdUrlOk(ok), ok);
  for (const bad of ["", "ftp://h", "http://", "http://a b", "http://h:abc", "http://h:99999", "http://user:pw@h", "127.0.0.1:8000", "javascript:alert(1)"]) assert.ok(!mdUrlOk(bad), bad);
});
T("模型管理: 同一个服务的不同写法算同一个(去掉 /v1、主机不分大小写、localhost 当 127.0.0.1、补默认端口), 与服务端 url_key 相同", () => {
  const same = ["http://127.0.0.1:18199/v1/chat/completions", "http://127.0.0.1:18199", "HTTP://LOCALHOST:18199/v1", " http://[::1]:18199 "];
  assert.equal(new Set(same.map(mdUrlKey)).size, 1, same.map(mdUrlKey).join(" | "));
  assert.equal(mdUrlKey("http://127.0.0.1:18199/v1"), "http://127.0.0.1:18199");
  assert.equal(mdUrlKey("http://h"), mdUrlKey("http://h:80/v1"));
  assert.equal(mdUrlKey("https://h"), mdUrlKey("https://H:443"));
  assert.notEqual(mdUrlKey("http://h:8000"), mdUrlKey("http://h:8001"));
  assert.notEqual(mdUrlKey("http://h:8000"), mdUrlKey("http://h:8000/gateway"));
});
T("模型管理: 添加 / 编辑时的检查(必填、http(s)、长度、Key 去首尾空白、名称默认「模型 · 主机」), 与服务端 clean_fields 同一套", () => {
  const ok = mdFormCheck({url: " http://127.0.0.1:18199/v1 ", key: "  sk-demo-1234\n", model: " Qwen3-8B ", name: ""});
  assert.ok(ok.ok);
  assert.deepEqual(ok.fields, {url: "http://127.0.0.1:18199", model: "Qwen3-8B", api_key: "sk-demo-1234", name: "Qwen3-8B · 127.0.0.1:18199"});
  assert.ok(ok.nameDefault && ok.notes.url.includes("「/v1」") && ok.notes.key.includes("去掉首尾"));
  const empty = mdFormCheck({});
  assert.deepEqual([empty.ok, empty.errors.url, empty.errors.model], [false, "请填写服务地址", "请填写模型名称"]);
  assert.ok(mdFormCheck({url: "ftp://h", model: "m"}).errors.url.includes("http://"));
  assert.ok(mdFormCheck({url: "http://h", model: "m", key: "sk-a\nb"}).errors.key.includes("换行"));
  assert.ok(mdFormCheck({url: "http://h", model: "m", name: "名".repeat(65)}).errors.name.includes("64"));
  assert.ok(mdFormCheck({url: "http://h", model: "m", name: "名".repeat(64)}).ok);   /* 按字数不按字节 */
  assert.ok(mdFormCheck({url: "http://h", model: "m".repeat(129)}).errors.model.includes("128"));
  assert.equal(mdFormCheck({url: "http://h", model: "m", name: " 甲‮乙 "}).fields.name, "甲乙");
  assert.equal(mdDefaultName("m".repeat(100), "http://h:1").length, 64);
  assert.deepEqual([mdNameCheck("").error, mdNameCheck("名".repeat(65)).ok, mdNameCheck(" 新名字 ").name], ["名称不能为空", false, "新名字"]);
});
T("模型管理: 连不上的原因写成大白话(超时 / 拒绝连接 / 401 Key 不对 / 404 地址不对…), 服务端原文另外给", () => {
  const f = (code, status, error) => mdFailText({ok: false, code, status, error});
  assert.equal(f("timeout").short, "超时");
  assert.equal(f("refused").short, "拒绝连接");
  assert.equal(f("auth", 401).short, "401 Key 不对");
  assert.equal(f("auth", 403).short, "403 没有权限");
  assert.equal(f("not_found", 404).short, "404 地址不对");
  assert.equal(f("server", 502).short, "502 服务出错");
  assert.equal(f("dns").short, "找不到主机");
  assert.equal(f("bad_json").short, "不是模型列表");
  assert.ok(f("refused").long.includes("端口") && f("timeout").long.includes("10 秒") && f("auth", 401).long.includes("Key"));
  assert.equal(f("auth", 401, "HTTP 401: bad key").raw, "HTTP 401: bad key");
  assert.deepEqual(mdFailText({ok: false, error: "奇怪的错误"}), {short: "连不上", long: "奇怪的错误", raw: "奇怪的错误"});
  for (const k of Object.keys(MD_FAIL)) assert.ok(MD_FAIL[k][0] && MD_FAIL[k][1], k);
});
T("模型管理: 连接状态是文字 + 图标 + 颜色(正常带延迟 / 连得上但没有这个模型 / 连不上带原因 / 还没检查), 改过地址或 Key 的旧结果不算", () => {
  const ep = {id: "ep_1_a", url: "http://h:1", api_key: "k", model: "m"};
  const saved = new Map(MD.probe);
  try {
    MD.probe.clear();
    assert.equal(mdConnState(ep).text, "还没检查");
    MD.probe.set(ep.id, {st: "busy", url: ep.url, key: "k"});
    assert.deepEqual([mdConnState(ep).text, mdConnState(ep).icon], ["正在连接…", "loader"]);
    MD.probe.set(ep.id, {st: "ok", url: ep.url, key: "k", at: 0, d: {ok: true, latency_ms: 23, count: 1, models: [{id: "m"}]}});
    assert.deepEqual([mdConnState(ep).tone, mdConnState(ep).text], ["good", "正常 · 23 毫秒"]);
    MD.probe.get(ep.id).d.models = [{id: "M"}];               /* 区分大小写 */
    assert.equal(mdConnState(ep).tone, "warn");
    MD.probe.set(ep.id, {st: "fail", url: ep.url, key: "k", at: 0, d: {ok: false, code: "auth", status: 401, error: "x"}});
    assert.deepEqual([mdConnState(ep).tone, mdConnState(ep).text], ["bad", "连不上 · 401 Key 不对"]);
    assert.equal(mdConnState(Object.assign({}, ep, {api_key: "k2"})).text, "还没检查");   /* 改了 Key: 之前的结果不算 */
    assert.ok(!mdConnHTML(Object.assign({}, ep, {api_key: "sk-secret-0123456789"})).includes("sk-secret"));
  } finally {
    MD.probe.clear();
    saved.forEach((v, k) => MD.probe.set(k, v));
  }
  assert.equal(mdLatency(23), "23 毫秒");
  assert.equal(mdLatency(6004), "6.0 秒");
  assert.equal(mdLatency(null), "—");
  assert.ok(mdCtxText(131072).includes("最大上下文") && mdCtxText(131072).replace(/\D/g, "") === "131072");
});
T("模型管理: 正在测试连接的这一行, 排序 / 翻页 / 搜索把表格重画后按钮仍是「正在连接…」(转圈、禁用、有提示)", () => {
  const ep = {id: "ep_1_a", name: "甲", url: "http://h:1", api_key: "k", model: "m"};
  const saved = new Map(MD.probe);
  try {
    MD.probe.clear();
    const idle = mdActionsHTML(ep);
    assert.ok(idle.includes("测试连接：甲") && !idle.includes("aria-disabled") && idle.includes("#i-plug"));
    MD.probe.set(ep.id, {st: "busy", url: ep.url, key: "k"});
    const busy = mdActionsHTML(ep);
    assert.ok(busy.includes("正在连接…：甲") && busy.includes('aria-disabled="true"') && busy.includes("is-loading") && busy.includes("#i-loader") && busy.includes("最多等 10 秒"));
    assert.ok(busy.includes("用它新建：甲") && busy.includes("编辑：甲") && busy.includes("删除：甲"));   /* 每个图标按钮都有 aria-label */
  } finally {
    MD.probe.clear();
    saved.forEach((v, k) => MD.probe.set(k, v));
  }
});
T("模型管理: 默认按最近使用排序(一键填入和最近一次测试取晚的); 都没用过的按添加时间, 新的在前", () => {
  const eps = [{id: "a", created_utc: "2026-01-01T00:00:00Z"},
    {id: "b", created_utc: "2026-01-02T00:00:00Z", last_used_utc: "2026-03-01T00:00:00Z"},
    {id: "c", created_utc: "2026-01-03T00:00:00Z", uses: {last_utc: "2026-03-05T00:00:00+00:00"}},
    {id: "d", created_utc: "2026-01-04T00:00:00Z"},
    {id: "e", created_utc: "2026-01-05T00:00:00Z", last_used_utc: "2026-03-09T00:00:00Z", uses: {last_utc: "2026-03-02T00:00:00+00:00"}}];
  assert.deepEqual(mdOrder(eps).map(e => e.id), ["e", "c", "b", "d", "a"]);
  assert.equal(mdLastUse(eps[4]), "2026-03-09T00:00:00Z");
  assert.equal(mdLastUse(eps[2]), "2026-03-05T00:00:00+00:00");
  assert.equal(mdLastUse(eps[0]), "");
  assert.deepEqual(eps.map(e => e.id), ["a", "b", "c", "d", "e"]);   /* 不改原数组 */
});
T("模型管理: 列表里任何地方都没有完整的 Key(单元格、悬停提示、复制和导出 CSV 用的文字、概况), 搜索也不搜 Key", () => {
  const key = "sk-list-secret-0123456789";
  const saved = EPS;
  try {
    EPS = [{id: "ep_1_a", name: "甲", url: "http://h:1", model: "m", api_key: key, uses: {perf: 1, iq: 0, gen: 2, total: 3, last_utc: null}}];
    const spec = mdListSpec(mdRows());
    const cells = spec.rows.map(r => spec.columns.map(c => dtCell(c, r, {max: {}, heat: {}}) + "|" + dtExport(c, r)).join("|")).join("");
    assert.ok(!cells.includes(key) && cells.includes(maskKey(key)));
    assert.ok(!JSON.stringify(dtMatrix(spec)).includes(key));
    assert.ok(!mdActionsHTML(EPS[0]).includes(key) && !mdListOverview().includes(key));
    MD.q = "0123456789";
    assert.equal(mdRows().length, 0);
    MD.q = "";
    assert.deepEqual(spec.columns.map(c => c.key), ["name", "model", "host", "key", "conn", "last", "u_perf", "u_iq", "u_gen", "act"]);
    assert.equal(spec.columns.find(c => c.key === "u_gen").group, "在测试里用过（次）");
  } finally {
    EPS = saved;
    MD.q = "";
  }
});
T("模型管理: 用过的测试一行摘要(速度 / 能力 / 代码生成)与设置、状态", () => {
  assert.equal(mdRunSummary({kind: "perf", summary: {peak_tps: 1280.84, peak_conc: 4, decode_tps: 410}}), "最高总生成速度 1280.8 token/秒（同时 4 个请求） · 单个请求 410.0 token/秒");
  assert.equal(mdRunSummary({kind: "perf", summary: {scn: 2}}), "模拟业务 2 类");
  assert.ok(mdRunSummary({kind: "iq", summary: {acc: 79.2, correct: 19, n: 24}}).startsWith("正确率 79.2%（答对 19 / 24 题）"));
  assert.equal(mdRunSummary({kind: "iq", summary: {acc: null}}), "没有成绩");
  assert.equal(mdRunSummary({kind: "gen", summary: {done: 30, planned: 33, exec: 78.4, method: "browser", judge: 71}}), "完成 30 / 33 题 · 运行检查通过 78% · AI 打分 71");
  assert.ok(mdRunSummary({kind: "gen", summary: {done: 1, planned: 1, exec: 60, method: "static"}}).includes("只看了代码"));
  assert.deepEqual([mdRunSetting({kind: "perf", suite: "quick"}), mdRunSetting({kind: "iq", thinking: true}), mdRunSetting({kind: "gen", thinking: null})], ["快速", "思考", "—"]);
  assert.deepEqual([mdRunStatus({status: "done"}).tone, mdRunStatus({status: "failed", error: "x"}).tip, mdRunStatus({status: "interrupted"}).text], ["good", "x", "已中断"]);
});
T("模型管理: 新建面板的下拉 — 名称一行、模型和主机一行(默认名称时不重复); 一个都没有时给「去添加」", () => {
  assert.equal(epOptionSub({name: "m · h:1", model: "m", url: "http://h:1"}), "");
  assert.equal(epOptionSub({name: "我的模型", model: "m", url: "http://h:1/v1"}), "m · h:1");
  assert.equal(EP_ADD, "__add__");
});

T("输入长度: 旧算法拼的档位按实际长度显示, 新测试不动; 长度范围不同的两次测试不可比", () => {
  const old = fixLenLabels({phases: [
    {id: "prefill", points: [{label: "1K", in_tokens: 490}, {label: "32K", in_tokens: 14490}, {label: "128K", in_tokens: 57855}]},
    {id: "prefill_conc", conc: 4, points: [{label: "1K", in_tokens: 488}, {label: "16K", in_tokens: 7245}]}]});
  assert.deepEqual(old.phases[0].points.map(q => [q.label, q.label_nominal]), [["0.5K", "1K"], ["14.5K", "32K"], ["57.9K", "128K"]]);
  assert.deepEqual(old.phases[1].points.map(q => q.label), ["0.5K", "7.2K"]);
  assert.equal(fixLenLabels(old), old);                                   /* 同一份结果只处理一次 */
  const neu = fixLenLabels({phases: [{id: "prefill_conc", conc: 4, points: [{label: "1K", in_tokens: 1012}, {label: "16K", in_tokens: 15990}]}]});
  assert.deepEqual(neu.phases[0].points.map(q => [q.label, q.label_nominal]), [["1K", undefined], ["16K", undefined]]);
  assert.equal(lenK(250000), "250K");
  const note = perfAnomalies(old)[0];
  assert.ok(note.includes("旧的估算方法") && note.includes("原来标 128K 的显示为 57.9K") && note.includes("45%"), note);
  assert.ok(perfAnomalies({phases: [], prompt_calibration: {method: "guess", error: "没返回用量"}}).some(t => t.includes("没能按这个模型的实际 token 数校准")));
  assert.equal(perfAnomalies(neu).length, 0);                              /* 新测试没有额外提示 */
  const k = PERF_METRICS.find(x => x.key === "mpre");
  assert.equal(ladderRef(perfCtx(neu)), "1K–16K、同时 4 个请求");
  assert.equal(sameRef(k, perfCtx(old), perfCtx(neu)), false);             /* 旧 0.5K–7.2K 与新 1K–16K 不比 */
  assert.equal(sameRef(k, perfCtx(neu), perfCtx(neu)), true);
});

T("看资料回答: 旧结果的资料长度按实际显示, 新旧测试实际长度差得多时不配对比较", () => {
  const old = fixLenLabels({phases: [{id: "scn_rag", points: [{ctx_tokens: 4000, prompt_tokens_avg: 2136, conc: 4}]}]});
  assert.equal(old.phases[0].points[0].ctx_actual, 2136);
  assert.ok(perfAnomalies(old).some(t => t.includes("看资料回答") && t.includes("标 4K 的实际约 2.1K")));
  const neu = fixLenLabels({phases: [{id: "scn_rag", points: [{ctx_tokens: 4000, prompt_tokens_avg: 3980, conc: 4}]}]});
  assert.equal(neu.phases[0].points[0].ctx_actual, undefined);
  assert.equal(ragPair(old.phases[0].points[0], neu.phases[0].points[0]), false);            /* 旧 2.1K 与新 4K 不比 */
  assert.equal(ragPair(old.phases[0].points[0], {ctx_tokens: 4000, prompt_tokens_avg: 2125}), true);  /* 两次旧测试照常比 */
  assert.equal(ragActualNote(old.phases[0], [1500, 4000]), "（旧方法估算的，实际约 — / 2.1K）");
  assert.equal(ragActualNote(neu.phases[0], [4000]), "");
});

T("超过模型最大上下文而没测的档位: 「需要注意」里按阶段写明哪几档、为什么", () => {
  const why = "超过模型的最大上下文（32768 token）";
  const r = {phases: [], length_skips: [{phase: "prefill", label: "64K", reason: why}, {phase: "prefill", label: "128K", reason: why},
    {phase: "longctx", label: "64K", reason: why}]};
  const t = perfAnomalies(r).find(x => x.includes("没有测"));
  assert.ok(t && t.includes("输入长度 64K、128K") && t.includes("超长输入 64K") && t.includes("32768"), t);
});

/* ---------- 代码生成: 作品列表 ---------- */
const shotIt = (names, extra) => ({id: "snake", name: "贪吃蛇", file: "works/run1/snake.html", tags: ["困难", "游戏"], pass: 5, total: 6,
  eval: Object.assign({method: "browser", shots_dir: "snake.shots", checks: [{id: "load", pass: true}, {id: "step1", label: "交互：按键", pass: true}],
    shots: names.map(n => ({name: n, file: n + ".jpg", caption: "图 " + n}))}, extra || {})});
T("作品缩略图: 优先「空闲后」的桌面截图, 其次首屏, 手机截图不用, 没有截图返回 null", () => {
  assert.equal(genPickShot(shotIt(["01_initial", "02_idle", "03_step1", "09_mobile"])).path, "works/run1/snake.shots/02_idle.jpg");
  assert.equal(genPickShot(shotIt(["09_mobile", "03_step1", "02_idle", "01_initial"])).file, "02_idle.jpg");   /* 顺序不影响 */
  assert.equal(genPickShot(shotIt(["01_initial", "03_step1"])).file, "01_initial.jpg");                       /* 没有空闲后: 首屏 */
  assert.equal(genPickShot(shotIt(["03_step1", "04_step2"])).file, "03_step1.jpg");                           /* 都没有: 第一张桌面截图 */
  assert.equal(genPickShot(shotIt(["09_mobile"])), null);                                                     /* 只有手机截图: 不用 */
  assert.equal(genPickShot(shotIt([])), null);
  assert.equal(genPickShot({id: "x", file: "works/r/x.html", eval: {method: "static", checks: [], shots: []}}), null);   /* 只看代码: 没有截图 */
  assert.equal(genPickShot({id: "x"}), null);                                                                 /* 旧版本: 没有 eval */
  assert.equal(genPickShot({id: "x", eval: {shots_dir: "x.shots", shots: [{name: "02_idle", file: "a.jpg"}]}}), null);   /* 没有作品文件 */
  assert.equal(genPickShot(shotIt(["02_idle"])).caption, "图 02_idle");
});

T("A / B 谁更好: 没生成 > 人工星级 > AI 分(差 5 分以内算差不多) > 检查通过比例; 检查方式不同不比", () => {
  const ok = (pass, total, x) => Object.assign({id: "t", file: "f", pass, total, eval: {method: "browser", checks: []}}, x || {});
  assert.equal(genWinner(null, ok(1, 2)), null);                                        /* B 没有这道题 */
  assert.equal(genWinner(ok(1, 2), undefined), null);
  assert.equal(genWinner({error: "x"}, ok(1, 2)).side, "b");
  assert.equal(genWinner(ok(0, 5), {error: "x"}).side, "a");
  assert.equal(genWinner({error: "x"}, {error: "y"}).side, "none");
  /* 人工星级压过 AI 分和检查 */
  let w = genWinner(ok(6, 6, {stars: 3, judge_score: 90}), ok(2, 6, {stars: 4, judge_score: 10}));
  assert.deepEqual([w.side, w.basis], ["b", "stars"]);
  assert.equal(genWinner(ok(6, 6, {stars: 3}), ok(2, 6, {stars: 3})).side, "tie");
  w = genWinner(ok(2, 6, {stars: 5}), ok(6, 6));                                        /* 只有一边有星级: 不比星级 */
  assert.deepEqual([w.side, w.basis], ["b", "checks"]);
  /* AI 分压过检查; 差 5 分以内算差不多, 刚好差 5 分算有差别 */
  w = genWinner(ok(2, 6, {judge_score: 82}), ok(6, 6, {judge_score: 60}));
  assert.deepEqual([w.side, w.basis], ["a", "judge"]);
  assert.equal(genWinner(ok(2, 6, {judge_score: 82}), ok(6, 6, {judge_score: 79})).side, "tie");
  assert.equal(genWinner(ok(2, 6, {judge_score: 82}), ok(6, 6, {judge_score: 77})).side, "a");
  assert.equal(genWinner(ok(6, 6, {judge_score: 70}), ok(2, 6, {judge_score: 75.1})).side, "b");
  /* 检查通过比例: 通过数一样是差不多; 总数不同时比比例 */
  assert.equal(genWinner(ok(6, 6), ok(4, 6)).side, "a");
  assert.equal(genWinner(ok(4, 6), ok(6, 6)).side, "b");
  assert.equal(genWinner(ok(5, 6), ok(5, 6)).side, "tie");
  assert.equal(genWinner(ok(6, 7), ok(6, 6)).side, "b");
  assert.ok(genWinner(ok(6, 6), ok(4, 6)).text.includes("A 6/6") && genWinner(ok(6, 6), ok(4, 6)).text.includes("B 4/6"));
  /* 一边实际运行、一边只看代码: 不比; 都只看代码 / 都是旧版本可以比, 写「代码关键词」 */
  const st = (pass, total) => ok(pass, total, {eval: {method: "static", checks: []}});
  assert.equal(genWinner(st(5, 6), ok(3, 6)).side, "none");
  w = genWinner(st(5, 6), st(3, 6));
  assert.ok(w.side === "a" && w.text.includes("代码关键词"), w.text);
  assert.equal(genWinner({file: "f", pass: 3, total: 4}, {file: "f", pass: 2, total: 4}).side, "a");
  assert.equal(genWinner({file: "f", pass: 3, total: 4}, ok(2, 4)).side, "none");
  assert.equal(genWinner(ok(0, 0), ok(0, 0)).side, "none");                             /* 没有检查结果 */
  assert.deepEqual(["a", "b", "tie", "none"].map(s => genWinLabel({side: s})), ["A 更好", "B 更好", "差不多", "没法比"]);
  assert.equal(genWinLabel(null), "");
  assert.ok(["人工星级", "AI", "检查", "5 分", "没生成"].every(k => genWinRule().includes(k)));   /* 悬停提示写全了判断规则 */
});

T("卡片上的说明: 整次测试共同的情况不重复, 只写这件作品自己的问题", () => {
  const stat = (fails, notes) => ({pass: 1, total: 3, eval: {method: "static", notes: notes || [],
    checks: [{id: "doctype", pass: true}, ...fails.map((f, i) => ({id: "f" + (i + 1), label: "源码特征 /" + f + "/", pass: false}))]}});
  const all = {v2: true, mode: "static", shared: "没找到浏览器"}, mix = {v2: true, mode: "mixed", shared: "没找到浏览器"};
  const info = (it, ctx) => genCardInfo(it, genVerdict(it), ctx);
  let i = info(stat([]), all);
  assert.deepEqual([i.badge, i.note], [null, ""]);                                       /* 整次都只看代码: 无标签、无说明 */
  i = info(stat(["click"]), all);
  assert.ok(i.badge === null && i.note.includes("click"));                              /* 只写这件作品自己没找到的关键词 */
  assert.ok(!i.note.includes("没有在浏览器里实际运行"));
  i = info(stat([]), mix);
  assert.deepEqual([i.badge.text, i.note], ["没有实际运行", ""]);                       /* 混合: 标出是哪几件, 原因同顶部就不再写 */
  i = info(stat([], ["浏览器崩了一次"]), mix);
  assert.equal(i.note, "浏览器崩了一次");                                               /* 这件自己的原因才写 */
  i = info(stat([], ["没找到浏览器"]), mix);
  assert.equal(i.note, "");
  i = genCardInfo({pass: 0, total: 0}, genVerdict({pass: 0, total: 0}), {v2: false, mode: "browser", shared: ""});   /* 旧版本: 每张都一样, 不写 */
  assert.deepEqual([i.badge, i.note], [null, ""]);
  i = genCardInfo({pass: 0, total: 0}, genVerdict({pass: 0, total: 0}), {v2: true, mode: "browser", shared: ""});   /* 新版测试里个别没检查: 写「还没有检查」 */
  assert.equal(i.badge.text, "还没有检查");
  /* 其余都是这件作品自己的问题: 原样写一句; 全部通过没有说明 */
  const fail = {error: "timed out"};
  i = info(fail, all);
  assert.ok(i.badge.text === "生成失败" && i.note.includes("timed out"));
  const pass = {pass: 2, total: 2, eval: {method: "browser", checks: [{id: "load", pass: true}, {id: "step1", label: "交互：按键", pass: true}]}};
  i = info(pass, {v2: true, mode: "browser", shared: ""});
  assert.deepEqual([i.badge.text, i.note], ["全部检查通过", ""]);
  const part = {pass: 1, total: 2, eval: {method: "browser", checks: [{id: "load", pass: true}, {id: "step1", label: "交互：按键", pass: false}]}};
  i = info(part, {v2: true, mode: "browser", shared: ""});
  assert.ok(i.badge.text === "部分功能没反应" && i.note.includes("按键"));
  assert.equal(genStaticWhy({browser_error: "启动失败"}, []), "启动失败");
  assert.equal(genStaticWhy({}, [{eval: {notes: ["降级"]}}]), "降级");
  assert.equal(genStaticWhy({}, []), "后台浏览器没有启动");
});

T("作品筛选: 状态 × 难度 × 名称搜索; 标签数字和点下去看到的件数一致", () => {
  const R = (id, name, tier, key, win) => ({it: {id, name, tags: [tier, "x"]}, v: {key}, ib: null, vb: null, win: win ? {side: win} : null});
  const rows = [R("snake", "贪吃蛇", "困难", "pass", "a"), R("tetris", "俄罗斯方块", "困难", "error", "b"), R("pelican", "鹈鹕骑自行车", "普通", "static", "tie"),
    R("landing", "产品落地页", "普通", "pass", "a"), R("terminal", "macOS 终端", "实战", "partial", null)];
  const ids = f => genFilterRows(rows, f).map(r => r.it.id);
  assert.deepEqual(ids({}), ["snake", "tetris", "pelican", "landing", "terminal"]);
  assert.deepEqual(ids({status: "issues"}), ["tetris", "pelican", "terminal"]);
  assert.deepEqual(ids({status: "pass"}), ["snake", "landing"]);
  assert.deepEqual(ids({status: "error"}), ["tetris"]);
  assert.deepEqual(ids({tier: "困难"}), ["snake", "tetris"]);
  assert.deepEqual(ids({status: "issues", tier: "困难"}), ["tetris"]);
  assert.deepEqual(ids({q: "贪吃"}), ["snake"]);
  assert.deepEqual(ids({q: "  MACOS "}), ["terminal"]);                                  /* 不分大小写, 去首尾空白 */
  assert.deepEqual(ids({q: "landing"}), ["landing"]);                                    /* 名字和题目 id 都能搜 */
  assert.deepEqual(ids({q: "不存在"}), []);
  assert.deepEqual(ids({status: "pass", tier: "普通", q: "产品"}), ["landing"]);
  assert.deepEqual(ids({status: "win-a"}), ["snake", "landing"]);                        /* 对比: A 更好 / 差不多 / B 更好 */
  assert.deepEqual([ids({status: "tie"}), ids({status: "win-b"})], [["pelican"], ["tetris"]]);
  const c = genCounts(rows, {status: "issues", tier: "all", q: ""}, ["all", "issues", "pass", "static", "win-a"], ["普通", "困难", "实战"]);
  assert.deepEqual(c.by, {all: 5, issues: 3, pass: 2, static: 1, "win-a": 2});           /* 状态标签的数字不受「状态」本身影响 */
  assert.deepEqual(c.byTier, {普通: 1, 困难: 1, 实战: 1});                                /* 难度标签的数字按当前状态算 */
  const c2 = genCounts(rows, {status: "all", tier: "困难", q: "蛇"}, ["all", "issues", "pass"], ["普通", "困难"]);
  assert.deepEqual(c2.by, {all: 1, issues: 0, pass: 1});                                 /* 状态数字按难度和搜索算 */
  assert.deepEqual(c2.byTier, {普通: 0, 困难: 1});
  /* 排序: 稳定, 空值排后面 */
  const s = [{it: {id: "a", pass: 1, total: 4, lines: 10}}, {it: {id: "b", error: "x"}}, {it: {id: "c", pass: 4, total: 4, lines: 99}}, {it: {id: "d", pass: 1, total: 4, lines: 10}}];
  assert.deepEqual(genSortRows(s, "pass").map(r => r.it.id), ["b", "a", "d", "c"]);
  assert.deepEqual(genSortRows(s, "lines").map(r => r.it.id), ["c", "a", "d", "b"]);
  assert.deepEqual(genSortRows(s, "default").map(r => r.it.id), ["a", "b", "c", "d"]);
});

T("作品分页: 每页 12 / 24 / 48, 页码夹在首页和末页之间", () => {
  assert.deepEqual(GW_SIZES, [12, 24, 48]);
  assert.deepEqual(pageWindow(33, 12, 0), {pages: 3, page: 0, start: 0, end: 12});
  assert.deepEqual(pageWindow(33, 12, 2), {pages: 3, page: 2, start: 24, end: 33});
  assert.deepEqual(pageWindow(33, 12, 9), {pages: 3, page: 2, start: 24, end: 33});      /* 筛选后页数变少: 回到末页 */
  assert.deepEqual(pageWindow(33, 12, -4), {pages: 3, page: 0, start: 0, end: 12});
  assert.deepEqual(pageWindow(33, 48, 1), {pages: 1, page: 0, start: 0, end: 33});
  assert.deepEqual(pageWindow(0, 12, 0), {pages: 1, page: 0, start: 0, end: 0});
  assert.equal(pageWindow(24, 12, "1").start, 12);
  assert.equal(pageWindow(25, 12, 2).end, 25);
  /* 换每页条数时看的还是原来那一条: 第 3 页第一条(下标 24)在每页 48 里是第 1 页 */
  assert.equal(Math.floor(24 / 48), 0);
});

T("作品列表: 换测试回到第 1 页并清掉筛选, 只换对照只回第 1 页, 都没换保留页码", () => {
  const keep = [GEN_FILTER, GEN_TIER, GEN_Q, GEN_PAGE, GW.mainId, GW.pairId];
  try {
    GW.mainId = "gen_a"; GW.pairId = ""; GEN_FILTER = "static"; GEN_TIER = "困难"; GEN_Q = "蛇"; GEN_PAGE = 2;
    genViewSync({run_id: "gen_a"}, null);
    assert.deepEqual([GEN_FILTER, GEN_TIER, GEN_Q, GEN_PAGE], ["static", "困难", "蛇", 2]);
    genViewSync({run_id: "gen_a"}, {run_id: "gen_b"});                                   /* 只换了对照 */
    assert.deepEqual([GEN_FILTER, GEN_TIER, GEN_Q, GEN_PAGE], ["static", "困难", "蛇", 0]);
    GEN_PAGE = 3; genViewSync({run_id: "gen_a"}, {run_id: "gen_b"});                     /* 什么都没换(比如切了主题重画) */
    assert.equal(GEN_PAGE, 3);
    GEN_FILTER = "win-a"; genViewSync({run_id: "gen_a"}, null);                          /* 取消对照: 对照专用的筛选回到「全部」 */
    assert.equal(GEN_FILTER, "all");
    GEN_FILTER = "pass"; GEN_TIER = "实战"; GEN_Q = "x"; GEN_PAGE = 2; genViewSync({run_id: "gen_c"}, null);   /* 换了测试 */
    assert.deepEqual([GEN_FILTER, GEN_TIER, GEN_Q, GEN_PAGE], ["all", "all", "", 0]);
    assert.equal(genViewSig(), "gen_c||all|all||" + GEN_SORT);
  } finally { [GEN_FILTER, GEN_TIER, GEN_Q, GEN_PAGE, GW.mainId, GW.pairId] = keep; }
});

T("作品卡: 六行固定位置(空的也留着位置), 图标按钮有名字, 缩略图懒加载, 没有截图是占位", () => {
  const run = {run_id: "gen_1", model: "m", items: []};
  const it = {id: "snake", name: "贪吃蛇", file: "works/gen_1/snake.html", tags: ["困难", "游戏"], lines: 293, continuations: 4, out_tokens: 80000, pass: 3, total: 5,
    eval: {method: "static", checks: [{id: "doctype", pass: true}, {id: "f1", label: "源码特征 /click/", pass: false}], notes: ["没找到浏览器"], shots: []}};
  const ctx = {v2: true, mode: "static", shared: "没找到浏览器"};
  let h = genCard(run, it, genVerdict(it), ctx);
  assert.ok(!h.includes("没有在浏览器里实际运行"), "整次测试共同的话只在页面顶部说一次");
  const pos = ["work-media", "work-head", "work-note", "work-checks", "work-data", "work-acts"].map(c => h.indexOf(`class="${c}`));
  assert.ok(pos.every((p, i) => p > 0 && (!i || p > pos[i - 1])), "六行按固定顺序: " + pos);
  assert.ok(h.includes("work-ph") && h.includes("没有截图 · 点击预览"));
  assert.equal((h.match(/<img /g) || []).length, 0);
  assert.match(h, /293 行 · 接着写 4 轮 · 80\D?000 token/);                              /* 行数 · 接着写几轮 · token 在同一行 */
  assert.ok(h.includes("接着写 4 轮") && h.includes("代码关键词 3/5") && h.includes("click"));
  ["预览：贪吃蛇", "新标签页打开：贪吃蛇", "更多操作：贪吃蛇", "详情：贪吃蛇", "1 分", "5 分"].forEach(l => assert.ok(h.includes(`aria-label="${l}"`), l));
  assert.ok(h.includes('data-gen="preview"') && h.includes('data-gen="detail"') && !h.includes('data-gen="trace"'));
  /* 有截图: 用空闲后那张, 懒加载, 16:10 的宽高; 有生成过程才有「过程」 */
  const it2 = shotIt(["01_initial", "02_idle", "09_mobile"]);
  it2.file = "works/gen_1/snake.html"; it2.trace = "works/gen_1/snake.gen.json"; it2.stars = 4;
  h = genCard(run, it2, genVerdict(it2), {v2: true, mode: "browser", shared: ""});
  assert.ok(h.includes('src="/works/gen_1/snake.shots/02_idle.jpg"') && h.includes('loading="lazy"') && h.includes('width="768" height="480"'));
  assert.ok(h.includes('data-gen="trace"') && h.includes("work-thumb skeleton"));
  assert.equal((h.match(/class="star on"/g) || []).length, 4);
  /* 没有「自己的问题」时那一行是空的(不是没有): 一排卡片才能对齐 */
  assert.ok(h.includes('<p class="work-note"></p>'));
  /* 没生成出来: 缩略图不能点、没有星星和预览 */
  const bad = {id: "snake", name: "贪吃蛇", error: "timed out", tags: ["困难"]};
  h = genCard(run, bad, genVerdict(bad), ctx);
  assert.ok(h.includes("work-thumb is-static") && h.includes("没有生成出来") && !h.includes('data-rate="1"') && !h.includes('data-gen="preview"'));
  assert.ok(h.includes('<div class="work-checks"></div>') && h.includes('<p class="work-data"></p>'));
  assert.ok(h.includes("timed out"));
  /* 名称里的特殊字符要转义 */
  const evil = Object.assign({}, it, {name: '<img src=x onerror=alert(1)>"'});
  h = genCard(run, evil, genVerdict(evil), ctx);
  assert.ok(!h.includes("<img src=x") && h.includes("&lt;img src=x"));
});

T("A / B 并排: 行首写谁更好, 两半各有缩略图; B 没有这道题时留出位置", () => {
  const a = {run_id: "gen_a", model: "ma", items: []}, b = {run_id: "gen_b", model: "mb", items: []};
  const ia = shotIt(["01_initial", "02_idle"]), ib = shotIt(["01_initial"]);
  ia.file = "works/gen_a/snake.html"; ib.file = "works/gen_b/snake.html";
  ib.pass = 3;
  const row = {it: ia, v: genVerdict(ia), ib, vb: genVerdict(ib), win: genWinner(ia, ib)};
  const ctx = {v2: true, mode: "browser", shared: ""};
  let h = genPairHTML(a, b, row, ctx, ctx);
  assert.ok(h.indexOf("A 更好") < h.indexOf("贪吃蛇") && h.indexOf("A 更好") < h.indexOf("work-media"), "谁更好写在行首");
  assert.ok(h.includes("delta up") && h.includes("怎么判断谁更好") && h.includes("并排预览：贪吃蛇"));
  assert.equal((h.match(/<article class="work"/g) || []).length, 2);
  assert.ok(h.includes("02_idle.jpg") && h.includes("01_initial.jpg"));
  assert.ok(h.includes(">A<") && h.includes(">B<"));
  h = genPairHTML(a, b, {it: ia, v: genVerdict(ia), ib: null, vb: null, win: null}, ctx, ctx);
  assert.ok(h.includes("B 没有这道题") && h.includes("work is-empty") && !h.includes("并排预览"));
  const worse = Object.assign({}, ib, {pass: 6});
  h = genPairHTML(a, b, {it: ia, v: genVerdict(ia), ib: worse, vb: genVerdict(worse), win: genWinner(ia, worse)}, ctx, ctx);
  assert.ok(h.includes("delta down") && h.includes("B 更好"));
});

T("作品表: 缩略图列默认隐藏, 可选; 有「自己的问题」和(对比时)「谁更好」列", () => {
  const spec = {id: "t-hid", columns: [{key: "a", label: "a"}, {key: "b", label: "b", hidden: true}], rows: []};
  dataTable(spec);
  assert.ok(dtState("t-hid").hidden.has("b") && !dtState("t-hid").hidden.has("a"));
  const run = {run_id: "gen_1", items: []}, it = shotIt(["02_idle"]);
  it.file = "works/gen_1/snake.html";
  const rows = [{it, v: genVerdict(it), ib: null, vb: null, win: null}];
  const t = genWorksTable(run, null, rows, {v2: true, mode: "browser", shared: ""});
  const keys = t.columns.map(c => c.key);
  assert.ok(["thumb", "name", "tier", "status", "note", "pass", "lines", "tok", "stars", "act"].every(k => keys.includes(k)) && !keys.includes("win"));
  assert.equal(t.columns.find(c => c.key === "thumb").hidden, true);
  assert.equal(dtExport(t.columns.find(c => c.key === "thumb"), rows[0]), "有");
  const ib = shotIt(["01_initial"]);
  const t2 = genWorksTable(run, {run_id: "gen_2"}, [{it, v: genVerdict(it), ib, vb: genVerdict(ib), win: genWinner(it, ib)}], {v2: true, mode: "browser", shared: ""});
  const win = t2.columns.find(c => c.key === "win");
  assert.ok(win && win.tip.includes("怎么判断"));
  assert.equal(dtExport(win, {ib, win: {side: "a"}}), "A 更好");
  assert.equal(dtExport(win, {ib: null, win: null}), "B 没有这道题");
});

T("作品列表的加载骨架: 和最终布局同形(六张卡, 每张六行)", () => {
  const h = genSkeleton();
  assert.equal((h.match(/class="work is-sk"/g) || []).length, 6);
  ["work-media", "work-head", "work-note", "work-checks", "work-data", "work-acts"].forEach(c => assert.equal((h.match(new RegExp(`class="${c}"`, "g")) || []).length, 6, c));
  assert.ok(h.includes('aria-hidden="true"') && h.includes("skeleton"));
  assert.ok(!/<p[^>]*>(?:(?!<\/p>)[\s\S])*<div/.test(h), "p 里不能放 div: 解析器会把 p 提前关掉, 卡片的行就错位了");
  /* 每张卡恰好六个直接孩子(顺序: 缩略图 / 标题 / 问题 / 检查 / 数据 / 操作), subgrid 才能逐行对齐 */
  const i0 = h.indexOf('class="work is-sk"'), card = h.slice(i0, h.indexOf('class="work is-sk"', i0 + 1));
  assert.equal((card.match(/class="work-(media|head|note|checks|data|acts)"/g) || []).length, 6);
});

T("作品占位图: 按难度(0–3)换底色、按题目类别换图标, 每道题都有类别", () => {
  assert.ok(TASK_CATALOG.every(t => GEN_CATS[t.cat]), "33 道题都有类别");
  assert.equal(TASK_CATALOG.length, 33);
  assert.equal(genTierIdx({tags: ["普通"]}), 0);
  assert.equal(genTierIdx({tags: ["实战", "网页"]}), 3);
  assert.equal(genTierIdx({tags: []}), 0);
  const h = genPhHTML({id: "snake", tags: ["困难"]}, "没有截图 · 点击预览");
  assert.ok(h.includes('data-t="1"') && h.includes("#i-gamepad") && h.includes("没有截图 · 点击预览"));
  assert.ok(genPhHTML({id: "earth", tags: ["普通"]}, "x").includes("#i-box"));
  assert.ok(genPhHTML({id: "no-such", tags: ["普通"]}, "x").includes("#i-layout"));
  assert.ok(genPhHTML({id: "snake", tags: ["困难"]}, "截图没能显示", "image-off", "文件不存在").includes("文件不存在"));
});

/* ---------- 界面语言 (i18n.js: t / tn / td / tm / tk、静态 HTML 翻译、语言状态、X-Lang 请求头) ---------- */
/* 测试用的词条都带「测试专用」, 不会和真实词典重复; 每个用到英文的测试结束后切回中文 */
["modal", "launcher", "iqLauncher", "genLauncher"].forEach(id => { document.getElementById(id).hidden = true; });  /* 换语言的通用重画不去碰抽屉和弹窗 */
function __inEn(fn) { I18N.set("en"); try { fn(); } finally { I18N.set("zh"); } }
function __txt(s) { return { nodeType: 3, nodeValue: s }; }
function __el(tag, attrs, kids) {   /* 最小的假 DOM: 元素 / 文本节点 / 属性 / innerHTML, 够 applyStaticI18n 用 */
  const a = Object.assign({}, attrs || {});
  return {
    nodeType: 1, tagName: tag, childNodes: kids || [], _html: null,
    getAttribute(k) { return k in a ? a[k] : null; }, setAttribute(k, v) { a[k] = String(v); }, hasAttribute(k) { return k in a; },
    get innerHTML() {
      return this._html !== null ? this._html
        : this.childNodes.map(c => c.nodeType === 3 ? c.nodeValue : "<" + c.tagName.toLowerCase() + ">" + c.innerHTML + "</" + c.tagName.toLowerCase() + ">").join("");
    },
    set innerHTML(v) { this._html = v; this.childNodes = []; },
  };
}

T("界面语言: 测试环境默认是中文, I18N.lang / 语言标记 / 数字格式跟着走", () => {
  assert.equal(I18N.lang, "zh");
  assert.equal(I18N.locale(), "zh-CN");
  __inEn(() => {
    assert.equal(I18N.lang, "en");
    assert.equal(document.documentElement.lang, "en");
    assert.equal(I18N.locale(), "en-US");
  });
  assert.equal(document.documentElement.lang, "zh-CN");
});

T("t / tn / td / tm / tk (中文模式): 原样返回, 占位符替换, {{ }} 是字面花括号", () => {
  assert.equal(t("你好"), "你好");
  assert.equal(t("共 {n} 行 {名字}", { n: 3, 名字: "甲" }), "共 3 行 甲");
  assert.equal(t("缺 {x} 保留", { n: 1 }), "缺 {x} 保留");                     /* 没传的名字原样留着, 一眼看得出写错了 */
  assert.equal(t("{a}|{b}", { a: null, b: undefined }), "|");                   /* null / undefined 当空串 */
  assert.equal(t("{{n}} 是字面的, {n} 是 5", { n: 5 }), "{n} 是字面的, 5 是 5");
  assert.equal(t("没有参数时 {n} 和 {{ 都不动"), "没有参数时 {n} 和 {{ 都不动");
  assert.equal(t("更好", null, "对比"), "更好");                                /* 语境只影响英文词典的键 */
  assert.equal(t(null), "");
  assert.equal(tn("{n} 行", 1), "1 行");
  assert.equal(tn("{n} 行", 2), "2 行");
  assert.equal(tn("{n} 行 {m}", 3, { m: "x" }), "3 行 x");
  assert.equal(tn("{n} 行", 1234, { n: "1,234" }), "1,234 行");                 /* {n} 可以换成已经格式化的文字, 单复数仍按数值 */
  assert.equal(td("鹈鹕骑自行车"), "鹈鹕骑自行车");
  assert.equal(td(null), null);
  assert.equal(tm("任务集不存在: x"), "任务集不存在: x");
  assert.equal(tk("可用"), "可用");
});

T("t / tn (英文模式): 查词典、语境、单复数、缺词回退成中文并每个键只记一次、控制台只警告一次", () => {
  I18N.add("en", { "测试专用 你好 {名字}": "Hello {名字}", "测试专用更好": "good", "对比|测试专用更好": "better",
    "测试专用 {n} 个": ["{n} thing", "{n} things"], "测试专用 <b>{n}</b>": "<b>{n}</b> bold", "测试专用 单个": "single" });
  const warns = [], warn = console.warn;
  console.warn = (...a) => warns.push(a.join(" "));
  try {
    __inEn(() => {
      assert.equal(t("测试专用 你好 {名字}", { 名字: "Ann" }), "Hello Ann");
      assert.equal(t("测试专用更好"), "good");
      assert.equal(t("测试专用更好", null, "对比"), "better");
      assert.equal(tn("测试专用 {n} 个", 1), "1 thing");
      assert.equal(tn("测试专用 {n} 个", 0), "0 things");
      assert.equal(tn("测试专用 {n} 个", 2), "2 things");
      assert.equal(tn("测试专用 {n} 个", 1000, { n: "1,000" }), "1,000 things");
      assert.equal(tn("测试专用 单个", 5), "single");                           /* 词条写成字符串: 不分单复数 */
      assert.equal(t("测试专用 <b>{n}</b>", { n: 3 }), "<b>3</b> bold");
      const before = I18N.missing.length;
      assert.equal(t("没有英文的句子 {x}", { x: 1 }), "没有英文的句子 1");     /* 回退成中文 (占位符照样替换) */
      assert.equal(t("没有英文的句子 {x}", { x: 2 }), "没有英文的句子 2");
      assert.equal(tn("没有英文的 {n} 个", 3), "没有英文的 3 个");
      assert.equal(t("测试专用更好", null, "没有这个语境"), "测试专用更好");
      assert.equal(I18N.missing.length, before + 3);                            /* 每个键只记一次 */
      assert.ok(I18N.missing.includes("没有英文的句子 {x}") && I18N.missing.includes("没有这个语境|测试专用更好"));
    });
  } finally { console.warn = warn; }
  assert.ok(warns.length <= 1, warns.join("\n"));                               /* 只警告一次, 不刷屏 */
});

T("td: 数据里的中文名, 英文模式查 enData, 查不到回退原文并记下", () => {
  I18N.add("enData", { "测试专用作品": "Test work" });
  assert.equal(td("测试专用作品"), "测试专用作品");
  __inEn(() => {
    assert.equal(td("测试专用作品"), "Test work");
    assert.equal(td("测试专用没有的作品"), "测试专用没有的作品");
    assert.equal(td("Already English"), "Already English");
    assert.equal(td(42), 42);
    assert.ok(I18N.missingData.includes("测试专用没有的作品") && !I18N.missingData.includes("Already English"));
  });
});

T("tm: 服务端提示 —— 先查完整原文, 再试正则模式 ($1 / 函数, 函数里可以再 tm), 都不行回退原文并记进 missingServer", () => {
  I18N.add("en", { "测试专用服务端: 完整": "Server: exact", "测试专用任务": "job" });
  I18N.addPattern([/^测试专用不存在: (\S+)$/, "Not found: $1"],
    [/^测试专用 (.+) 在跑$/, (m, name) => "A " + tm(name) + " is running"],
    [/^测试专用全局(\d+)$/g, "Global $1"]);
  assert.equal(tm("测试专用不存在: x1"), "测试专用不存在: x1");                   /* 中文模式不动 */
  __inEn(() => {
    assert.equal(tm("测试专用服务端: 完整"), "Server: exact");
    assert.equal(tm("测试专用不存在: abc"), "Not found: abc");
    assert.equal(tm("测试专用 测试专用任务 在跑"), "A job is running");
    assert.equal(tm("测试专用全局7"), "Global 7");
    assert.equal(tm("测试专用全局8"), "Global 8");                             /* 带 g 标志的正则连续用也不出错 */
    assert.equal(tm("测试专用没人认识的提示"), "测试专用没人认识的提示");
    assert.equal(tm("HTTP 500"), "HTTP 500");                                   /* 没有汉字的原样, 不记录 */
    assert.equal(tm(null), null);
    assert.ok(I18N.missingServer.includes("测试专用没人认识的提示") && !I18N.missingServer.includes("HTTP 500"));
  });
});

T("I18N.detect: 网址 ?lang= → 离线报告带的偏好 → 本地存储 → 浏览器语言 (仅 AUTO_DETECT 打开时; zh 开头用中文, 否则英文; 拿不到用中文)", () => {
  const off = l => ({ ls: { "llm-bench-pro-lang": l } });
  assert.equal(I18N.AUTO_DETECT, false, "翻译全部完成前不自动识别");
  const saved = I18N.AUTO_DETECT;
  try {
    for (const auto of [false, true]) {
      I18N.AUTO_DETECT = auto;
      assert.equal(I18N.detect(off("en"), "zh", "zh-CN"), "en");
      assert.equal(I18N.detect(off("zh"), "en", "en-US"), "zh");
      assert.equal(I18N.detect(off("xx"), "en", "zh-CN"), "en");                     /* 报告里的值不认识: 往下走 */
      assert.equal(I18N.detect({ ls: {} }, "en", "zh-CN"), "en");
      assert.equal(I18N.detect(null, "zh", "en-US"), "zh");
      assert.equal(I18N.detect(null, "xx", "en-US"), auto ? "en" : "zh");
      assert.equal(I18N.detect(off("zh"), "zh", "zh-CN", "en"), "en");               /* 网址最优先 */
      assert.equal(I18N.detect(off("en"), "en", "en-US", "zh"), "zh");
      assert.equal(I18N.detect(null, null, "en-US", "xx"), auto ? "en" : "zh");      /* 网址里的值不认识: 往下走 */
      for (const n of ["zh-CN", "zh", "ZH-tw", "zh-Hant-HK"]) assert.equal(I18N.detect(null, null, n), "zh", n);
      for (const n of ["en-US", "en", "de", "ja"]) assert.equal(I18N.detect(null, null, n), auto ? "en" : "zh", n);
      assert.equal(I18N.detect(null, null, ""), "zh");
      assert.equal(I18N.detect(null, null, undefined), "zh");
    }
  } finally { I18N.AUTO_DETECT = saved; }
});
T("I18N.showSwitch: 翻译完成前隐藏语言按钮, 已经在英文模式时照常显示 (好切回来)", () => {
  const lang = I18N.lang, ready = I18N.READY;
  try {
    I18N.READY = false;
    I18N.lang = "zh"; assert.equal(I18N.showSwitch(), false);
    I18N.lang = "en"; assert.equal(I18N.showSwitch(), true);
    I18N.READY = true;
    I18N.lang = "zh"; assert.equal(I18N.showSwitch(), true);
  } finally { I18N.lang = lang; I18N.READY = ready; }
  assert.equal(I18N.READY, false, "翻译全部完成前保持关闭");
});

T("applyStaticI18n: 文本节点和 title / aria-label 按词典翻译, 首尾空白保留, 空白合并后查词典, 切回中文还原", () => {
  I18N.add("en", { "测试专用静态": "Static", "测试专用标题": "Title tip", "测试专用 空格 合并": "Merged", "测试专用读屏": "Screen reader" });
  const t1 = __txt("\n   测试专用静态  \n"), t2 = __txt("测试专用 空格\n   合并"), t3 = __txt("没词条的中文"), t4 = __txt("English only");
  const btn = __el("BUTTON", { title: "测试专用标题", "aria-label": "测试专用读屏", "data-x": "测试专用标题", placeholder: "没词条" }, [t1]);
  const skip = [__el("SVG", {}, [__txt("测试专用静态")]), __el("SCRIPT", {}, [__txt("测试专用静态")]),
    __el("SPAN", { translate: "no" }, [__txt("测试专用静态")]), __el("TEXTAREA", { placeholder: "测试专用标题" }, [__txt("测试专用静态")])];
  const root = __el("DIV", {}, [btn, t2, t3, t4].concat(skip));
  applyStaticI18n(root);                                                       /* 中文模式: 什么都不变 */
  assert.equal(t1.nodeValue, "\n   测试专用静态  \n");
  I18N.lang = "en";
  applyStaticI18n(root);
  assert.equal(t1.nodeValue, "\n   Static  \n");                                /* 首尾空白原样保留 */
  assert.equal(t2.nodeValue, "Merged");
  assert.equal(t3.nodeValue, "没词条的中文");                                    /* 没词条: 不动 */
  assert.equal(t4.nodeValue, "English only");
  assert.equal(btn.getAttribute("title"), "Title tip");
  assert.equal(btn.getAttribute("aria-label"), "Screen reader");
  assert.equal(btn.getAttribute("data-x"), "测试专用标题");                       /* 只翻译 title / placeholder / aria-label / alt */
  assert.equal(btn.getAttribute("placeholder"), "没词条");
  assert.equal(skip[0].childNodes[0].nodeValue, "测试专用静态");                   /* svg / script / translate="no" / textarea 里的不翻译 */
  assert.equal(skip[1].childNodes[0].nodeValue, "测试专用静态");
  assert.equal(skip[2].childNodes[0].nodeValue, "测试专用静态");
  assert.equal(skip[3].childNodes[0].nodeValue, "测试专用静态");
  assert.equal(skip[3].getAttribute("placeholder"), "Title tip");                 /* 文本框里的内容不翻译, 它的 placeholder 要翻译 */
  applyStaticI18n(root);                                                       /* 再翻一次: 不会翻成乱码 */
  assert.equal(t1.nodeValue, "\n   Static  \n");
  I18N.lang = "zh";
  applyStaticI18n(root);                                                       /* 切回中文: 原文还原 */
  assert.equal(t1.nodeValue, "\n   测试专用静态  \n");
  assert.equal(t2.nodeValue, "测试专用 空格\n   合并");
  assert.equal(btn.getAttribute("title"), "测试专用标题");
  assert.equal(btn.getAttribute("aria-label"), "测试专用读屏");
});

T("静态翻译只管「页面刚打开时就有的」节点和明确传进来的节点; 被别处改过的值以新的为准, 不会被还原覆盖", () => {
  I18N.add("en", { "测试专用甲": "A-en", "测试专用乙": "B-en" });
  const a = __txt("测试专用甲"), b = __txt("测试专用乙"), label = __el("B", { "aria-label": "测试专用甲" }, []);
  const root = __el("DIV", {}, [a, label]);
  const body = document.body;
  document.body = root;
  try {
    I18N.lang = "zh"; applyStaticI18n(root);                                   /* 登记为「静态节点」 (页面刚打开时 boot 做的事) */
    const late = __txt("测试专用乙");
    root.childNodes.push(late);                                                /* 之后动态插入的节点: 不认识 */
    I18N.set("en");
    assert.equal(a.nodeValue, "A-en");
    assert.equal(late.nodeValue, "测试专用乙");                                   /* 动态节点靠 t() 自己翻译, 静态那遍不碰 */
    label.setAttribute("aria-label", "运行时写的中文");                             /* 应用代码换了属性: 记录作废 */
    I18N.set("zh");
    assert.equal(a.nodeValue, "测试专用甲");
    assert.equal(label.getAttribute("aria-label"), "运行时写的中文");                 /* 不覆盖成旧的原文 */
    applyStaticI18n(root);                                                     /* 明确传进来的 (含动态插入的) 才会处理 */
    I18N.lang = "en"; applyStaticI18n(root);
    assert.equal(late.nodeValue, "B-en");
  } finally { document.body = body; I18N.set("zh"); }
});

T("data-i18n-html: 句子中间夹着标签的元素, 整段 innerHTML 一起翻译, 切回中文还原", () => {
  const zh = "测试专用先看 <code>x</code> 再做";
  I18N.add("en", { [zh]: "See <code>x</code> first" });
  const p = __el("P", { "data-i18n-html": "" }, [__txt("测试专用先看 "), __el("CODE", {}, [__txt("x")]), __txt(" 再做")]);
  assert.equal(p.innerHTML, zh);
  I18N.lang = "en"; applyStaticI18n(p);
  assert.equal(p.innerHTML, "See <code>x</code> first");
  applyStaticI18n(p);
  assert.equal(p.innerHTML, "See <code>x</code> first");
  I18N.lang = "zh"; applyStaticI18n(p);
  assert.equal(p.innerHTML, zh);
});

T("文档标题: 有词条就翻译, 切回中文还原; 被改成别的标题就以新的为准", () => {
  I18N.add("en", { "测试专用标题页": "Test title" });
  document.title = "测试专用标题页";
  I18N.set("en");
  assert.equal(document.title, "Test title");
  I18N.set("zh");
  assert.equal(document.title, "测试专用标题页");
  I18N.set("en");
  document.title = "别处设置的标题";
  I18N.set("zh");
  assert.equal(document.title, "别处设置的标题");
  document.title = "";
});

T("I18N.set: 通知 onChange 监听者 (某个出错不影响其他的); setLang 写本地偏好", () => {
  const seen = [];
  let on = true;   /* 监听者没法取消, 用开关让它们在这个测试之后什么都不做 */
  I18N.onChange(l => { if (on) seen.push("a:" + l); });
  I18N.onChange(() => { if (on) throw new Error("监听者出错 (测试故意的)"); });
  I18N.onChange(l => { if (on) seen.push("c:" + l); });
  const err = console.error;
  console.error = () => {};
  const store = new Map(), oldLS = globalThis.localStorage;
  globalThis.localStorage = { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => { store.set(k, String(v)); }, removeItem: k => { store.delete(k); } };
  try {
    setLang("en");
    assert.equal(I18N.lang, "en");
    assert.equal(store.get("llm-bench-pro-lang"), "en");                       /* 在线: 存进浏览器 */
    assert.equal(document.getElementById("langAbbr").textContent, "EN");        /* 语言按钮显示当前语言的缩写 */
    setLang("zh");
    assert.equal(store.get("llm-bench-pro-lang"), "zh");
    assert.equal(document.getElementById("langAbbr").textContent, "中");
    setLang("nonsense");                                                        /* 不认识的值当中文 */
    assert.equal(I18N.lang, "zh");
  } finally { I18N.set("zh"); on = false; globalThis.localStorage = oldLS; console.error = err; }
  assert.deepEqual(seen.slice(0, 6), ["a:en", "c:en", "a:zh", "c:zh", "a:zh", "c:zh"]);
});

T("发往后端的请求都带 X-Lang 请求头 (getJSON / postJSON / tsApi / 导出报告), 换语言后马上生效", () => {
  const calls = [], old = globalThis.fetch;
  globalThis.fetch = (url, init) => { calls.push({ url, init: init || {} }); return new Promise(() => {}); };
  const runA = document.getElementById("runA");
  const keep = runA.value;
  runA.value = "run_20260101_000000_x";
  try {
    for (const lang of ["zh", "en", "zh"]) {
      I18N.set(lang);
      calls.length = 0;
      getJSON("/api/results"); postJSON("/api/cancel", { job: "perf" }); tsApi("/api/task-sets"); exportHtml("dash");
      assert.deepEqual(calls.map(c => c.url), ["/api/results", "/api/cancel", "/api/task-sets", "/api/export-html"]);
      for (const c of calls) assert.equal(c.init.headers["X-Lang"], lang, c.url + " 的请求头没有带当前语言 " + lang);
      assert.equal(calls[1].init.headers["Content-Type"], "application/json");   /* 原来的请求头还在 */
      assert.equal(calls[3].init.headers["Content-Type"], "application/json");
    }
  } finally { globalThis.fetch = old; runA.value = keep; I18N.set("zh"); }
});

T("被试点转换的基础函数: 英文模式的时长 / 多久以前 / 状态名 / 页面名 / 数字格式", () => {
  __inEn(() => {
    assert.equal(durationText(59), "1 minute");
    assert.equal(durationText(120), "2 minutes");
    assert.equal(durationText(3600), "1 hour");
    assert.equal(durationText(5400), "1.5 hours");
    assert.equal(durationText(90000), "1 day");
    const now = Date.parse("2026-09-30T12:00:00Z"), ago = s => tsAgo(new Date(now - s * 1000).toISOString(), now);
    assert.equal(ago(10), "Just now");
    assert.equal(ago(60), "1 minute ago");
    assert.equal(ago(3 * 3600), "3 hours ago");
    assert.equal(ago(86400), "1 day ago");
    assert.equal(ago(3 * 86400), "3 days ago");
    assert.deepEqual(["running", "done", "failed", "interrupted", "cancelled"].map(k => STATUS_NAME[k]), ["Running", "Completed", "Failed", "Interrupted", "Stopped"]);
    assert.deepEqual(["dash", "cmp", "iq", "gen"].map(k => PAGE_NAME[k]), ["Speed test", "Speed comparison", "Capability test", "Code generation"]);
    assert.equal(fmtInt(1234567), "1,234,567");
    assert.equal(numText(1234.5, 2), "1,234.50");
    assert.equal(emptyState("标题", "").includes("标题"), true);                  /* 没翻译的数据 / 标题照原样 */
  });
  assert.equal(durationText(59), "1 分钟");
  assert.equal(STATUS_NAME.done, "已完成");
});

T("侧栏连接状态: 用最近一次取到的 SERVER 重新生成, 换语言后跟着变", () => {
  const conn = document.getElementById("connText"), box = document.getElementById("conn");
  CONN_OK = true;
  SERVER = { version: "3.7.0", uptime_s: 90, pid: 42, started_at: "2026-09-30T00:00:00Z", commit: "abc123", db: "/x/y.db", bench_version: "1.5.0", iq_version: "1.4.0", gen_version: "2.3.0" };
  paintConn();
  assert.equal(conn.textContent, "服务正常 · 已运行 2 分钟");
  assert.match(box.title, /^后端 v3\.7\.0 · 进程 42 · 启动于 .+ · 提交 abc123\n数据库 \/x\/y\.db\n评测程序：速度 1\.5\.0 · 能力 1\.4\.0 · 代码生成 2\.3\.0$/);
  __inEn(() => {
    paintConn();
    assert.equal(conn.textContent, "Service OK · up 2 minutes");
    assert.match(box.title, /^Backend v3\.7\.0 · PID 42 · started .+ · commit abc123\nDatabase \/x\/y\.db\nBenchmark programs: speed 1\.5\.0 · ability 1\.4\.0 · code generation 2\.3\.0$/);
    CONN_OK = false; paintConn();
    assert.equal(conn.textContent, "Service not connected");
  });
  CONN_OK = null; SERVER = {};
});

T("页头的测试下拉: 「不对比」等选项文字按当前语言生成 (换语言时用缓存的 RUNS 重新生成)", () => {
  const keep = RUNS;
  RUNS = { run_20260101_000000_a: { run_id: "run_20260101_000000_a", model: "m-a", suite: "quick", status: "done", started_utc: "2026-01-01T00:00:00Z" } };
  try {
    fillRunSelects();
    assert.ok(document.getElementById("runB").innerHTML.includes(">不对比</option>"));
    assert.ok(document.getElementById("cmpB").innerHTML.includes(">选择测试 B</option>"));
    __inEn(() => {
      fillRunSelects();
      assert.ok(document.getElementById("runB").innerHTML.includes(">No comparison</option>"));
      assert.ok(document.getElementById("cmpB").innerHTML.includes(">Choose test B</option>"));
    });
  } finally { RUNS = keep; }
});

console.log("FRONTEND-OK " + __n);
