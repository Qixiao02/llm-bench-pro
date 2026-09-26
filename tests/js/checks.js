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
  assert.equal(Math.round(rows[0].m_d), 10);
  const cols = compareCols([{tag: "A"}, {tag: "B"}], [{key: "m", label: "速度", unit: "token/秒", dir: 1}]);
  assert.deepEqual(cols.map(c => c.label), ["A", "B", "变化"]);
  assert.equal(cols[0].group, "速度（token/秒）");
});
T("maskKey: API Key 掩码显示", () => {
  assert.equal(maskKey("sk-1234567890abcdef"), "sk-1…cdef");
  assert.equal(maskKey(""), "—");
  assert.equal(maskKey(null), "—");
});

console.log("FRONTEND-OK " + __n);
