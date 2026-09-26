/* 前端单测 harness (拼接在 app.js 之前执行):
   用最小 DOM/浏览器桩让 1900 行经典脚本在 Node 里完整加载——
   boot 路径上的异步链(fetch)被冻结为永挂起的 Promise, 不触发真实渲染;
   定时器被替换为 no-op 保证 Node 进程能退出。 */
"use strict";

function __mkEl(tag) {
  const el = {
    tagName: String(tag || "div").toUpperCase(),
    id: "", style: {}, dataset: {}, hidden: false,
    innerHTML: "", textContent: "", value: "", className: "",
    tabIndex: 0, children: [], options: [], selectedIndex: -1,
    clientWidth: 640, clientHeight: 300, offsetWidth: 640, offsetHeight: 300,
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    setAttribute() {}, getAttribute() { return null; }, removeAttribute() {},
    appendChild(c) { return c; }, removeChild() {}, remove() {}, replaceWith() {},
    insertBefore(n) { return n; }, insertAdjacentElement(w, n) { return n; }, insertAdjacentHTML() {},
    after() {}, before() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; },
    querySelector() { return __mkEl("div"); }, querySelectorAll() { return []; },
    closest() { return null; }, contains() { return false; },
    getBoundingClientRect() { return { left: 0, top: 0, right: 640, bottom: 300, width: 640, height: 300 }; },
    focus() {}, blur() {}, click() {}, scrollIntoView() {},
    parentNode: null, firstChild: null,
  };
  return el;
}

const __byId = new Map();
globalThis.document = {
  getElementById(id) { if (!__byId.has(id)) __byId.set(id, __mkEl("div")); return __byId.get(id); },
  querySelector() { return __mkEl("div"); },
  querySelectorAll() { return []; },
  createElement(t) { return __mkEl(t); },
  createTextNode(t) { return { textContent: t }; },
  addEventListener() {}, removeEventListener() {},
  documentElement: __mkEl("html"),
  body: __mkEl("body"),
  activeElement: null,
};

globalThis.window = globalThis;
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};
globalThis.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
globalThis.localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
globalThis.history = { replaceState() {}, pushState() {} };
globalThis.location = { hash: "", pathname: "/", search: "", host: "", hostname: "",
                        origin: "http://x", href: "http://x/", protocol: "http:" };
try {  /* Node 21+ 自带只读 navigator, 覆盖失败则保留原生(boot 路径不触它) */
  Object.defineProperty(globalThis, "navigator", {
    value: { userAgent: "node-harness", clipboard: { writeText() { return Promise.resolve(); } } },
    configurable: true,
  });
} catch (e) { /* keep native */ }
globalThis.innerWidth = 1440;
globalThis.innerHeight = 900;
globalThis.getComputedStyle = () => ({ getPropertyValue() { return ""; } });
/* fetch 永挂起: boot 的 refresh()/checkVersion() 等异步链静默冻结, 不会产生未处理拒绝 */
globalThis.fetch = () => new Promise(() => {});
globalThis.setInterval = () => 0;   /* 防 Node 事件循环被 checkVersion 轮询挂住 */
globalThis.setTimeout = () => 0;
globalThis.clearTimeout = () => {};
globalThis.clearInterval = () => {};
globalThis.requestAnimationFrame = () => 0;

class __Evt { constructor(type, opts) { this.type = type; Object.assign(this, opts || {}); } }
globalThis.Event = __Evt;
globalThis.CustomEvent = class extends __Evt { constructor(type, opts) { super(type, opts); this.detail = (opts || {}).detail; } };
globalThis.MutationObserver = class { observe() {} disconnect() {} };
globalThis.HTMLSelectElement = class {};
globalThis.HTMLElement = class {};

/* echarts 桩: 纯逻辑测试不渲染图表; LinearGradient 记录参数供 ecArea 断言 */
globalThis.echarts = {
  init() { return { setOption() {}, resize() {}, dispose() {}, on() {},
                    getDom() { return __mkEl("div"); }, getOption() { return { series: [] }; } }; },
  graphic: {
    LinearGradient: class {
      constructor(x, y, x2, y2, colorStops) {
        this.type = "linear"; this.x = x; this.y = y; this.x2 = x2; this.y2 = y2;
        this.colorStops = colorStops;
      }
    },
  },
};
