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
T("term: 名词带悬停解释且转义; 未知名词原样转义", () => {
  const h = term("ttft");
  assert.ok(h.includes('class="term"') && h.includes("首字等待") && h.includes("TTFT"));
  assert.equal(term("no-such", "<a>"), "&lt;a&gt;");
  for (const k of Object.keys(TERMS)) {
    assert.ok(TERMS[k].name && TERMS[k].tech && TERMS[k].desc, "名词缺字段: " + k);
  }
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
T("主题切换过渡: 圆心取鼠标点击处", () => {
  assert.deepEqual(themeOrigin({clientX: 120, clientY: 48}), [120, 48]);
  assert.equal(themeOrigin(null).length, 2);   /* 没有事件时也给出圆心(右上角), 不报错 */
});
T("maskKey: API Key 掩码显示", () => {
  assert.equal(maskKey("sk-1234567890abcdef"), "sk-1…cdef");
  assert.equal(maskKey(""), "—");
  assert.equal(maskKey(null), "—");
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

console.log("FRONTEND-OK " + __n);
