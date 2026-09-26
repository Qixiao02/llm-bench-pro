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
T("withAlpha(undefined) 原样返回 undefined — 调用方必须传有效色 (mkConc 事故锚点)", () => {
  /* 2026-09 addColorStop('undefined') 根因: ecConc 漏传颜色参数。
     本用例固定该语义: 上游一旦再漏传, ecArea 守卫用例会立即红。 */
  assert.equal(withAlpha(undefined, .26), undefined);
});
T("ecArea: 主题全色板都能产出合法渐变 colorStops", () => {
  const palette = ["#6950E8", "#0E9AB0", "#D97F06", "#D6408E", "#2F7FE0", "#5E9E12"];
  for (const color of palette) {
    const g = ecArea(color).color;
    assert.equal(g.type, "linear");
    assert.equal(g.colorStops.length, 2);
    for (const s of g.colorStops) {
      assert.ok(typeof s.color === "string" && /^#[0-9a-fA-F]{8}$/.test(s.color),
        "非法渐变色: " + String(s.color) + " (来自 " + color + ")");
    }
    assert.match(g.colorStops[0].color, /^#.{6}42$/);
    assert.match(g.colorStops[1].color, /^#.{6}05$/);
  }
});
T("ecArea 在 C 为空对象时被守卫拦截(而非产出 undefined 色标)", () => {
  const saved = C;
  C = {};                                        /* 模拟 readTheme 前的初始状态 */
  try {
    const g = ecArea(C.a).color;                 /* C.a === undefined */
    for (const s of g.colorStops) {
      assert.ok(typeof s.color === "string", "colorStops 出现非字符串: " + String(s.color));
    }
  } finally {
    C = saved;
  }
});

/* ---------- tooltip / 图标 ---------- */
T("tt: 标题与行内容全转义", () => {
  const h = tt("<x> · 并发 4", [["#fff", "<b>名</b>", "1<2"], ["", "ok", "3/4"]]);
  assert.ok(!h.includes("<b>名</b>") && !h.includes("1<2"));
  assert.ok(h.includes("&lt;b&gt;名&lt;/b&gt;") && h.includes("1&lt;2"));
});
T("icon: 引用符号 id 且带基类", () => {
  assert.equal(icon("play"), '<svg class="icon "><use href="#i-play"/></svg>');
  assert.equal(icon("stop", "icon-sm"), '<svg class="icon icon-sm"><use href="#i-stop"/></svg>');
});

/* ---------- 启动路径未被破坏 ---------- */
T("app.js 在桩环境下完整加载(执行到了文件尾)", () => {
  assert.ok(typeof render === "function" && typeof drawPrefill === "function" && typeof ecCtx === "function");
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
T("maskKey: API Key 掩码显示", () => {
  assert.equal(maskKey("sk-1234567890abcdef"), "sk-1…cdef");
  assert.equal(maskKey(""), "—");
  assert.equal(maskKey(null), "—");
});

console.log("FRONTEND-OK " + __n);
