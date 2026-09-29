"use strict";
/* LLM Bench Pro 前端逻辑 (零依赖经典脚本; 图表用本地内置的 ECharts) */
const UI_VERSION="3.7.0";  /* 与 llm_bench_pro/version.py 保持一致 */
/* ============================================================
   基础工具
   ============================================================ */
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const icon=(name,cls="")=>`<svg class="icon ${cls}"><use href="#i-${name}"/></svg>`;
function fmt(v,d=1){return v==null||!isFinite(v)?"—":Number(v).toFixed(d)}
function fmtInt(v){return v==null||!isFinite(v)?"—":Math.round(v).toLocaleString()}
function fmtAxis(v){
  const a=Math.abs(v);
  if(a>=1e6)return (v/1e6).toFixed(1).replace(/\.0$/,"")+"M";
  if(a>=1e4)return (v/1e3).toFixed(1).replace(/\.0$/,"")+"k";
  if(a>=100||v===0)return Math.round(v).toLocaleString();
  if(a>=10)return v.toFixed(0);
  return v.toFixed(a<1?2:1).replace(/\.?0+$/,"");
}
/* 秒: 小于 10 秒保留两位小数, 否则一位 */
function fmtSec(v){return v==null||!isFinite(v)?"—":Number(v).toFixed(Math.abs(v)<10?2:1)}
function median(xs){const v=xs.filter(x=>x!=null&&isFinite(x)).sort((p,q)=>p-q);if(!v.length)return null;const m=v.length>>1;return v.length%2?v[m]:(v[m-1]+v[m])/2}
/* 坐标轴上限: 整洁刻度步长(1/2/2.5/5×10^n), 4 格网格 */
function niceMax(v){
  if(!(v>0))return 1;
  const raw=v/4,p=10**Math.floor(Math.log10(raw)),n=raw/p;
  return (n<=1?1:n<=2?2:n<=2.5?2.5:n<=5?5:10)*p*4;
}
/* 时间统一按浏览器本地时区显示(后端存 UTC ISO) */
function toDate(iso){if(!iso)return null;let s=String(iso);if(!/[zZ]$|[+-]\d\d:?\d\d$/.test(s))s+="Z";const d=new Date(s);return isNaN(d.getTime())?null:d}
const pad2=n=>String(n).padStart(2,"0");
function timeText(iso){const d=toDate(iso);return d?`${d.getFullYear()}-${pad2(d.getMonth()+1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`:"—"}
function shortTime(iso){const d=toDate(iso);return d?`${pad2(d.getMonth()+1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`:""}
function durationText(s){s=Math.max(0,Math.round(s||0));if(s<3600)return Math.max(1,Math.round(s/60))+" 分钟";if(s<86400)return (s/3600).toFixed(1).replace(/\.0$/,"")+" 小时";return (s/86400).toFixed(1).replace(/\.0$/,"")+" 天"}
const STATUS_NAME={running:"进行中",done:"已完成",failed:"失败",interrupted:"已中断",cancelled:"已停止"};
/* 离线报告(「导出报告」生成的 HTML): window.LLMB_OFFLINE 里带着页面要用的数据, 页面照常渲染, 只是不连后端、不能改数据 */
const OFF=window.LLMB_OFFLINE||null;
async function getJSON(url){
  if(OFF)return offlineApi(OFF,url);
  const r=await fetch(url,{cache:"no-store"});if(!r.ok)throw new Error("HTTP "+r.status);return r.json();
}
async function postJSON(url,body){
  if(OFF)return{ok:false,error:"这是导出的离线报告，不能修改数据"};
  try{const r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    try{return await r.json()}catch(e){return{ok:false,error:"HTTP "+r.status}}}
  catch(e){return{ok:false,error:"无法连接后端服务（"+e.message+"）"}}
}
/* 本地偏好: 在线时存浏览器里; 离线报告用导出那一刻的偏好, 改了只在这次打开有效(不写进看报告的人的浏览器) */
const LS=(()=>{
  const off=window.LLMB_OFF_STATE;
  if(off){const m=new Map(Object.entries(off.ls||{}));return{get:k=>m.has(k)?m.get(k):null,set:(k,v)=>{m.set(k,String(v))}}}
  return{get:k=>{try{return localStorage.getItem(k)}catch(e){return null}},set:(k,v)=>{try{localStorage.setItem(k,String(v))}catch(e){}}};
})();
function lsGet(key){try{return JSON.parse(LS.get(key)||"{}")}catch(e){return{}}}
function lsSet(key,val){LS.set(key,JSON.stringify(val))}
/* 离线报告的「接口」: 按页面请求的路径从报告带的数据里取(返回副本, 页面改了也不影响下次取); 取不到就报错 */
function offlineApi(B,url){
  const u=new URL(url,"http://offline.local/"),p=decodeURIComponent(u.pathname),q=k=>u.searchParams.get(k)||"",A=(B&&B.api)||{};
  const copy=x=>x==null?null:JSON.parse(JSON.stringify(x));
  const none=()=>{throw new Error("离线报告里没有这部分数据")};
  const list=s=>s.split(",").filter(Boolean);
  switch(p){
    case "/api/version":return copy(A.version||{});
    case "/api/results":return copy(A.perfList||[]);
    case "/api/run":return A.perfRuns&&A.perfRuns[q("id")]?copy(A.perfRuns[q("id")]):none();
    case "/api/iq-results":return copy(A.iqList||[]);
    case "/api/iq-items":{
      const d=A.iqItems;if(!d||!d.runs||!d.runs[q("id")])return none();
      const out=copy(d);out.runs={};
      [q("id"),...list(q("cmp"))].forEach(id=>{if(d.runs[id])out.runs[id]=copy(d.runs[id])});
      return out;
    }
    case "/api/iq-compare":return copy((A.iqCompare||{})[q("a")+"|"+q("b")]);
    case "/api/iq-answer":{
      const e=(A.iqAnswers||{})[q("sid")+"|"+q("idx")];
      if(!e)return{ok:false,error:"离线报告里没有这道题的回答"};
      const answers={};list(q("ids")).forEach(id=>{if(e.answers&&e.answers[id])answers[id]=e.answers[id]});
      return copy({ok:true,sid:q("sid"),idx:+q("idx"),type:e.type,prompt:e.prompt,answers});
    }
    case "/api/gen-results":return copy(A.genList||[]);
    case "/api/banks":case "/api/endpoints":return[];
    case "/api/status":case "/api/iq-status":case "/api/gen-status":return{running:false};
  }
  if(p.startsWith("/works/")){const f=((B&&B.files)||{})[p.slice(1)];return f&&typeof f==="object"?copy(f):none()}
  return none();
}
/* 作品文件地址: 在线 = 服务端 /works/…; 离线报告 = 报告里带的内容(截图是 data: 地址, 网页和记录用 blob: 地址) */
const OFF_BLOBS=new Map();
function workUrl(path){
  if(!OFF)return "/"+path;
  const f=(OFF.files||{})[path];if(f==null)return "";
  if(typeof f==="string"&&f.startsWith("data:"))return f;
  if(!OFF_BLOBS.has(path))OFF_BLOBS.set(path,URL.createObjectURL(new Blob([typeof f==="string"?f:JSON.stringify(f,null,1)],
    {type:/\.html?$/i.test(path)?"text/html;charset=utf-8":"application/json"})));
  return OFF_BLOBS.get(path);
}
/* 预览 iframe 的内容来源: 离线报告用 srcdoc(配合 sandbox 属性是不同源的), 并在 doctype 后加上和服务端一样的资源限制 */
function workFrameSrc(path){
  if(!OFF)return `src="/${esc(path)}"`;
  const f=(OFF.files||{})[path];
  if(typeof f!=="string")return `srcdoc="${esc("<p style='font:14px sans-serif;padding:24px'>离线报告里没有这个作品</p>")}"`;
  const meta=`<meta http-equiv="Content-Security-Policy" content="${esc(OFF.worksCsp||"")}">`;
  return `srcdoc="${esc(f.replace(/^(\s*<!doctype[^>]*>)?/i,m=>m+meta))}"`;
}
/* 新标签页打开: 像普通网页一样运行(可以加载外部字体和脚本), 仍然隔离, 碰不到本系统的数据和接口 */
function workOpenUrl(path){return OFF?workUrl(path):"/"+path+"?open=1"}
function workOpenLink(it,{text=false,label=false}={}){
  if(!it||!it.file||it.error)return "";
  const tip="新标签页打开：像普通网页一样运行（可以加载外部字体和脚本），仍然隔离，碰不到本系统的数据";
  return `<a class="btn ${text?"btn-secondary btn-sm":"btn-ghost btn-icon btn-sm"} work-open" href="${esc(workOpenUrl(it.file))}" target="_blank" rel="noopener noreferrer" title="${tip}"${text?"":` aria-label="${esc("新标签页打开"+(label?"："+it.name:""))}"`}>${icon("external")}${text?"新标签页打开":""}</a>`;
}
/* 图表卡里的标签页(条形 / 能力形状、折线 / 散点)记住上次选的 */
const CTAB=Object.assign({subj:"bars",tok:"line"},lsGet("llm-bench-pro-ctab"));
function bindFormMemory(key,ids){
  const saved=lsGet(key);
  ids.forEach(id=>{const el=$(id);if(el&&saved[id]!=null&&saved[id]!=="")el.value=saved[id]});
  const save=()=>{const k={};ids.forEach(id=>{const el=$(id);if(el)k[id]=el.value});lsSet(key,k)};
  ids.forEach(id=>{const el=$(id);if(el){el.addEventListener("input",save);el.addEventListener("change",save)}});
  return save;
}
/* 行内提示: type = error | success | warning | info */
function msg(el,type,text){
  el=typeof el==="string"?$(el):el;if(!el)return;
  if(!text){el.innerHTML="";el.className="inline-msg";return}
  const ic={error:"x-circle",success:"check-circle",warning:"alert",info:"info"}[type]||"info";
  el.className="inline-msg"+(type&&type!=="info"?" is-"+type:"");
  el.innerHTML=icon(ic)+`<span>${esc(text).replace(/\n/g,"<br>")}</span>`;
}
function toast(text,type="info",ms=5000,action){
  const el=document.createElement("div");
  el.className="toast is-"+type;
  el.innerHTML=icon({error:"x-circle",success:"check-circle",warning:"alert"}[type]||"info")+`<span>${esc(text)}</span>`+
    (action?`<button class="btn btn-secondary btn-sm">${esc(action.label)}</button>`:"")+
    `<button class="btn btn-ghost btn-icon btn-sm" aria-label="关闭">${icon("x")}</button>`;
  const btns=el.querySelectorAll("button"),close=btns[btns.length-1];
  close.onclick=()=>el.remove();
  if(action&&btns.length>1)btns[0].onclick=()=>{el.remove();action.onClick()};
  $("toasts").appendChild(el);
  if(ms)setTimeout(()=>el.remove(),ms);
}
window.addEventListener("error",e=>toast(`页面脚本出错：${e.message}（第 ${e.lineno} 行），请刷新页面后重试`,"error",0));
function setBusy(btn,busy){
  btn=typeof btn==="string"?$(btn):btn;if(!btn)return;
  btn.disabled=busy;btn.classList.toggle("is-loading",busy);
  const use=btn.querySelector("use");if(!use)return;
  if(busy){if(!btn.dataset.icon)btn.dataset.icon=use.getAttribute("href");use.setAttribute("href","#i-loader")}
  else if(btn.dataset.icon){use.setAttribute("href",btn.dataset.icon)}
}
function setConn(ok,text){
  $("conn").className="conn "+(ok?"is-ok":"is-err");
  $("connText").textContent=text;
}
function emptyState(title,desc,{iconName="inbox",action="",inline=false}={}){
  return `<div class="empty${inline?" is-inline":""}">${icon(iconName)}<div class="empty-title">${esc(title)}</div>${desc?`<div class="empty-desc">${esc(desc)}</div>`:""}${action}</div>`;
}
function alertBox(tone,html,action=""){
  const ic={warn:"alert",bad:"x-circle",info:"info",good:"check-circle"}[tone]||"info";
  return `<div class="alert is-${tone}">${icon(ic)}<div>${html}</div>${action}</div>`;
}

/* ============================================================
   名词解释: 页面上用大白话, 悬停可看专业说法; 左侧「名词解释」列出全部
   ============================================================ */
const TERMS={
  token:{name:"token",tech:"token",desc:"模型读写文字的最小单位。中文里 1 个 token 大约是 1 个汉字，英文里大约是 3/4 个单词。"},
  decode:{name:"生成速度",tech:"解码速度（Decode），单位 token/秒",desc:"模型每秒能写出多少个 token。越高越好。"},
  agg:{name:"总生成速度",tech:"聚合吞吐（Throughput）",desc:"同时处理多个请求时，所有请求加起来每秒写出多少 token，反映服务器的总能力。越高越好。"},
  per:{name:"单个请求的速度",tech:"单流吞吐",desc:"同时处理多个请求时，每个请求分到的生成速度。同时请求越多，通常越慢。"},
  ttft:{name:"首字等待",tech:"TTFT（Time To First Token）",desc:"从发出请求到收到第一个字要等多久。输入越长、同时请求越多，通常要等越久。越短越好。"},
  itl:{name:"出字间隔",tech:"ITL（Inter-Token Latency）/ TPOT",desc:"相邻两次收到新内容隔了多久，决定看起来“打字”流不流畅。越短越好。"},
  prefill:{name:"读入速度",tech:"Prefill 吞吐",desc:"模型读取你发过去的内容（提示词、资料）的速度，决定长输入要等多久才开始回答。越高越好。"},
  pct:{name:"一般 / 较慢 / 最慢",tech:"p50 / p95 / p99 分位数",desc:"把所有请求从快到慢排好：“一般”是正中间那个（p50）；“较慢”表示 95% 的请求都比它快（p95）；“最慢”是 99%（p99）。"},
  conc:{name:"同时请求数",tech:"并发（Concurrency）",desc:"同一时刻有多少个请求在等模型回答。"},
  rps:{name:"每秒完成请求数",tech:"req/s（QPS）",desc:"每秒能完整回答多少个请求。越高越好。"},
  e2e:{name:"完整响应时间",tech:"端到端延迟（E2E）",desc:"从发出请求到收到最后一个字的总时间。越短越好。"},
  burst:{name:"每次返回的 token 数",tech:"Burst（投机解码）",desc:"服务每次推送几个 token。明显大于 1 通常说明开启了投机解码（一次猜好几个字）来加速。"},
  jitter:{name:"出字波动",tech:"ITL 抖动",desc:"出字间隔忽快忽慢的程度。越小越平稳。"},
  kv:{name:"显存缓存占用",tech:"KV Cache 使用率",desc:"服务端存放对话上下文的显存用了多少。接近 100% 时新请求要排队。"},
  prefix:{name:"重复内容复用率",tech:"前缀缓存命中率",desc:"请求开头与之前请求相同的部分可以直接复用、不用重读，复用得越多越快。"},
  open:{name:"按固定速率发送",tech:"开环（泊松到达）",desc:"不管前面的请求有没有回完，按设定速率随机间隔地发新请求，模拟真实用户陆续到来。处理中的请求越积越多，说明服务跟不上。"},
  closed:{name:"固定同时请求数",tech:"闭环",desc:"始终保持固定数量的请求在处理，一个回完马上发下一个。"},
  inflight:{name:"处理中的请求",tech:"在途请求",desc:"已经发出、还没回完的请求数量。"},
  fixed:{name:"生成满指定长度",tech:"ignore_eos",desc:"让模型每次都写满规定的长度，避免有的模型提前结束让速度看起来偏高。"},
  ci:{name:"误差范围",tech:"95% 置信区间（Wilson）",desc:"题目数量有限，分数会有随机波动。真实水平有 95% 的把握落在这个范围内。两个分数的范围重叠很多时，差距可能只是运气。"},
  sig:{name:"差异可信",tech:"McNemar 配对检验，p < 0.05",desc:"两次测试用同一套题，逐题比较谁对谁错。“差异可信”表示差距不太可能是随机波动；“差异不明显”表示可能只是运气。"},
  macro:{name:"各科平均",tech:"宏平均",desc:"每科先算正确率再求平均，题多的科目不会占更大比重。"},
  trunc:{name:"没答完",tech:"截断（finish_reason = length）",desc:"回答写到长度上限被强行停止，常见于思考太久或上限太小，这些题记为答错。"},
  run:{name:"实际运行检查",tech:"无头浏览器运行检测",desc:"在后台浏览器里真正打开模型写的网页，检查能否加载、有没有报错、是不是白屏，并按题目模拟操作看功能是否生效。"},
  static:{name:"只看了代码",tech:"源码检查（降级）",desc:"后台浏览器不可用时只检查代码里有没有相关关键词，不能代表作品真的能用。"},
  judge:{name:"AI 看图打分",tech:"视觉评审（VLM Judge）",desc:"让一个能看图的模型看截图和代码，按题目要求逐项打 0–10 分，汇总成百分制。"},
  repeat:{name:"陷入重复输出",tech:"退化重复（degenerate repetition）",desc:"模型不停地重复同一段内容直到长度上限，这是模型自身的问题。检测到后会立即停止并标记。"},
  cont:{name:"接着写",tech:"续写",desc:"作品太长一次写不完时，把已写好的部分交给模型让它接着写，再拼起来。每次拼接做了什么都记在「生成过程」里。"},
  control:{name:"对照运行",tech:"干净环境复现",desc:"作品报错时，在不加任何检测代码的干净页面里按同样步骤再运行一遍。同样报错，说明是作品本身的问题。"},
  sampling:{name:"随机性",tech:"采样参数 temperature / top_p / top_k",desc:"控制模型每次选词有多随机。太低时小模型容易反复写同一段；官方推荐值是模型厂商给出的最佳设置。"},
};
/* 页面上的名词: 大白话 + 悬停显示专业说法 */
function term(key,label){
  const t=TERMS[key];if(!t)return esc(label||key);
  return `<span class="term" data-term="${esc(key)}" title="${esc(t.tech+"：" +t.desc+"（点击查看名词解释）")}">${esc(label||t.name)}</span>`;
}
/* 名词解释: 左边词、右边解释; 顶部搜索; 从页面上的词点进来时定位并高亮 */
function showGlossary(focus){
  Modal.open("名词解释",`<div class="gl-top"><label class="qb-search">${icon("search")}<input class="input" id="glQ" type="search" placeholder="搜索名词、专业说法或解释"></label>
      <span class="faint">页面上带虚线下划线的词，点一下就能跳到这里</span></div>
    <div class="glossary" id="glList">${Object.entries(TERMS).map(([k,t])=>`<div class="glossary-item" id="gl-${esc(k)}" data-gl="${esc((t.name+" "+t.tech+" "+t.desc).toLowerCase())}"><div><div class="glossary-name">${esc(t.name)}</div>
      <div class="glossary-tech">${esc(t.tech)}</div></div><div class="glossary-desc">${esc(t.desc)}</div></div>`).join("")}</div>
    <div class="gl-empty" id="glEmpty" hidden>${emptyState("没有找到这个词","换个说法试试",{iconName:"search",inline:true})}</div>`,{wide:true});
  const q=$("glQ");
  q.addEventListener("input",()=>{const v=q.value.trim().toLowerCase();let n=0;
    document.querySelectorAll("#glList .glossary-item").forEach(x=>{const on=!v||x.dataset.gl.includes(v);x.hidden=!on;n+=on});$("glEmpty").hidden=!!n});
  if(focus&&TERMS[focus]){const it=$("gl-"+focus);if(it){it.classList.add("is-hit");setTimeout(()=>it.scrollIntoView({block:"center"}),30)}}
  else setTimeout(()=>q.focus(),30);
}

/* ============================================================
   主题
   ============================================================ */
let C={};
function readTheme(){
  const cs=getComputedStyle(document.documentElement),v=n=>cs.getPropertyValue(n).trim();
  C={a:v("--series-1"),b:v("--series-2"),t:v("--series-3"),series:[1,2,3,4,5,6].map(i=>v("--series-"+i)),
     grid:v("--chart-grid"),axis:v("--chart-axis"),text:v("--text-3"),text2:v("--text-2"),text1:v("--text-1"),text3:v("--text-3"),
     surface:v("--surface-1"),surface2:v("--surface-2"),border:v("--border"),borderStrong:v("--border-strong"),
     good:v("--good"),bad:v("--bad"),warn:v("--warn"),primary:v("--primary-fg"),
     goodMark:v("--good-mark"),warnMark:v("--warn-mark"),badMark:v("--bad-mark"),track:v("--chart-track"),
     heatHi:v("--heat-hi"),font:v("--font-sans"),mono:v("--font-mono")||v("--font-sans")};
}
function withAlpha(hex,a){const h=String(hex).replace("#","");return h.length===6?"#"+h+Math.round(a*255).toString(16).padStart(2,"0"):hex}
function applyTheme(t,persist){
  document.documentElement.dataset.theme=t;
  if(persist)LS.set("llm-bench-pro-theme",t);
  $("themeBtn").querySelector("use").setAttribute("href",t==="dark"?"#i-sun":"#i-moon");
  $("themeBtn").setAttribute("aria-label",t==="dark"?"切换为亮色":"切换为暗色");
  readTheme();
  return redrawVisible();
}
/* 亮色 / 暗色切换的过渡: 支持 View Transitions 的浏览器, 新主题从点击处圆形展开(整页截图过渡, 图表也一起);
   其他浏览器颜色渐变; 系统设置了「减少动画」时直接切换 */
function toggleTheme(ev){
  const next=document.documentElement.dataset.theme==="dark"?"light":"dark";
  if(matchMedia("(prefers-reduced-motion: reduce)").matches){applyTheme(next,true);return}
  if(typeof document.startViewTransition==="function"){
    const [x,y]=themeOrigin(ev),r=Math.ceil(Math.hypot(Math.max(x,innerWidth-x),Math.max(y,innerHeight-y)));
    const vt=document.startViewTransition(()=>applyTheme(next,true));
    vt.ready.then(()=>document.documentElement.animate(
      {clipPath:[`circle(0px at ${x}px ${y}px)`,`circle(${r}px at ${x}px ${y}px)`]},
      {duration:480,easing:"cubic-bezier(.4,0,.2,1)",pseudoElement:"::view-transition-new(root)"})).catch(()=>{});
    vt.updateCallbackDone.catch(e=>console.error("切换主题失败:",e));
    return;
  }
  const html=document.documentElement;
  html.classList.add("theme-fade");
  applyTheme(next,true);
  clearTimeout(toggleTheme.t);
  toggleTheme.t=setTimeout(()=>html.classList.remove("theme-fade"),420);
}
/* 圆形展开的圆心: 鼠标点在哪就从哪开始; 键盘触发(没有坐标)时用按钮中心; 都没有时从右上角 */
function themeOrigin(ev){
  if(ev&&ev.clientX>0&&ev.clientY>0)return[ev.clientX,ev.clientY];
  const el=ev&&ev.target&&ev.target.closest&&ev.target.closest("button,[data-theme-toggle]");
  if(el&&el.getClientRects().length){const r=el.getBoundingClientRect();return[r.left+r.width/2,r.top+r.height/2]}
  return[innerWidth-40,40];
}
$("themeBtn").onclick=toggleTheme;
/* 侧栏: 默认 64px 图标栏, 悬停展开; 「固定」后一直展开(记在本机) */
function applyRailPin(on,persist){
  document.querySelector(".app").classList.toggle("is-pinned",on);
  const b=$("railPin");b.setAttribute("aria-pressed",String(on));
  b.title=b.ariaLabel=on?"收起侧栏":"固定展开侧栏";
  if(persist)LS.set("llm-bench-pro-rail",on?"1":"0");
}
$("railPin").onclick=()=>applyRailPin(!document.querySelector(".app").classList.contains("is-pinned"),true);
/* 密度: 标准 / 紧凑(表格行高、面板内边距), 记在本机 */
function applyDensity(d,persist){
  document.documentElement.dataset.density=d;
  document.querySelectorAll("[data-density-toggle]").forEach(b=>b.setAttribute("aria-checked",String(d==="compact")));
  if(persist)LS.set("llm-bench-pro-density",d);
  for(const inst of CHARTS.values()){try{inst.resize()}catch(e){}}
}

/* ============================================================
   导航 / 抽屉 / 弹窗 / 通用点击
   ============================================================ */
let VIEW="dash";
const VIEWS={dash:"viewDash",cmp:"viewCmp",iq:"viewIq",gen:"viewGen",tasks:"viewTasks",models:"viewModels",styleguide:"viewSg"};
/* 地址 #页面, 看某一个任务集时是 #tasks/<任务集 id>, 看某一个模型时是 #models/<模型 id>: 拆成页面和后面的部分 */
function parseRoute(h){const s=String(h||"").replace(/^#/,""),i=s.indexOf("/");return i<0?{view:s,sub:""}:{view:s.slice(0,i),sub:s.slice(i+1)}}
function showView(v){
  let {view,sub}=parseRoute(v);
  if(!VIEWS[view]){view="dash";sub=""}
  if(OFF&&view!==OFF.page)view=OFF.page;
  VIEW=view;
  document.querySelectorAll(".nav-item").forEach(b=>{if(b.dataset.view===view)b.setAttribute("aria-current","page");else b.removeAttribute("aria-current")});
  Object.entries(VIEWS).forEach(([k,id])=>$(id).classList.toggle("is-active",k===view));
  closeDrawers();closeMenus();
  const tsId=view==="tasks"&&TS_ID_RE.test(sub)?sub:"",mdId=view==="models"&&MD_ID_RE.test(sub)?sub:"";
  try{history.replaceState(null,"","#"+view+(tsId?"/"+tsId:mdId?"/"+mdId:""))}catch(e){}
  if(view==="dash")render();
  if(view==="cmp")renderCmp();
  if(view==="iq"){loadBanks();loadIqResults();}
  if(view==="gen"){renderTaskChips();loadGenResults();}
  if(view==="tasks")tsShow(tsId);
  if(view==="models")mdShow(mdId);
  if(view==="styleguide")renderStyleguide();
  window.scrollTo(0,0);
}
function redrawVisible(){
  if(VIEW==="dash")return render();
  if(VIEW==="cmp")return renderCmp();
  if(VIEW==="iq")return renderIq();
  if(VIEW==="gen")return renderGen();
  if(VIEW==="tasks")return tsRedraw();
  if(VIEW==="styleguide")return renderStyleguide();
  /* 模型管理页没有图表, 换主题不用重画 */
}
/* 新建测试用右侧抽屉: 同一时间只开一个, 结果页保持可见 */
const DRAWERS=["launcher","iqLauncher","genLauncher"];
function closeDrawers(except){
  DRAWERS.forEach(id=>{if(id!==except&&$(id)&&!$(id).hidden)toggleLauncher(id,false)});
}
function toggleLauncher(id,force){
  if(OFF)return;  /* 离线报告不能新建测试 */
  const el=$(id);if(!el)return;
  const open=force==null?el.hidden:force;
  if(open){try{({launcher:launcherSummary,iqLauncher:iqLauncherSummary,genLauncher:genLauncherSummary}[id]||(()=>{}))()}catch(e){}}
  if(open)closeDrawers(id);
  el.hidden=!open;
  $("drawerBackdrop").hidden=!DRAWERS.some(d=>$(d)&&!$(d).hidden);
  document.querySelectorAll(`[data-toggle="${id}"][aria-expanded]`).forEach(b=>b.setAttribute("aria-expanded",String(open)));
  if(open&&force==null){const f=el.querySelector("input:not([type=checkbox]):not([type=file]),select");if(f)setTimeout(()=>f.focus(),60)}
}
$("drawerBackdrop").addEventListener("click",()=>closeDrawers());
/* 地址栏 #dash / #iq … 变化(前进/后退、手动修改、点页面里的链接)时切换页面;
   任务集页面里 #tasks ↔ #tasks/<id>、模型管理页面里 #models ↔ #models/<id> 切换列表和详情 */
function routeHash(){
  const {view,sub}=parseRoute(location.hash);
  if(!VIEWS[view])return;
  if(view!==VIEW){showView(location.hash);return}
  if(view==="tasks")tsRoute(sub);
  if(view==="models")mdRoute(sub);
}
window.addEventListener("hashchange",routeHash);
/* 运行中的任务: 侧栏圆点 + 页头"进行中"按钮, 抽屉关着也看得到 */
function setRunning(job,on){
  document.querySelectorAll(`[data-running="${job}"],[data-running-pill="${job}"]`).forEach(el=>el.hidden=!on);
}
function closeMenus(except){document.querySelectorAll("details.dropdown[open]").forEach(d=>{if(d!==except)d.open=false})}
document.addEventListener("click",e=>{
  const tm=e.target.closest(".term[data-term]");
  if(tm&&!e.target.closest("th,.cselect-panel,select")){e.preventDefault();showGlossary(tm.dataset.term);return}
  const nav=e.target.closest(".nav-item");if(nav&&nav.dataset.view){showView(nav.dataset.view);return}
  if(e.target.closest("[data-density-toggle]")){applyDensity(document.documentElement.dataset.density==="compact"?"normal":"compact",true);closeMenus();return}
  if(e.target.closest("[data-theme-toggle]")){toggleTheme(e);closeMenus();return}
  const rt=e.target.closest(".bar-runs-toggle");
  if(rt){const bar=rt.closest(".bar"),on=!bar.classList.contains("show-runs");bar.classList.toggle("show-runs",on);rt.setAttribute("aria-expanded",String(on));return}
  if(e.target.closest(".menu .menu-item"))setTimeout(()=>closeMenus(),0);
  const tg=e.target.closest("[data-toggle]");if(tg){toggleLauncher(tg.dataset.toggle);return}
  const jump=e.target.closest("[data-jumpto]");
  if(jump){e.preventDefault();const t=$(jump.dataset.jumpto);if(t)t.scrollIntoView({behavior:"smooth",block:"start"});return}
  const flip=e.target.closest("[data-flip]");
  if(flip){const card=flip.closest(".ccard");const on=!card.classList.contains("is-table");
    card.classList.toggle("is-table",on);flip.setAttribute("aria-pressed",String(on));
    flip.innerHTML=on?icon("gauge")+"图表":icon("table")+"数据";
    if(!on){const ch=card.querySelector(".chart");if(ch&&ch._ec)ch._ec.resize()}return}
  const row=e.target.closest("tr[data-expand]");
  if(row){const d=row.nextElementSibling;const open=d.hidden;d.hidden=!open;row.setAttribute("aria-expanded",String(open));return}
  const dd=e.target.closest("details.dropdown");
  closeMenus(dd);
});

const Modal={
  last:null,
  onClose:null,
  open(title,html,{badges="",flush=false,dialog=false,panel=false,wide=false}={}){
    if(!$("modal").hidden)this.close();
    this.last=document.activeElement;
    $("modalTitle").textContent=title;
    $("modalBadges").innerHTML=badges;
    const body=$("modalBody");body.className="modal-body"+(flush?" is-flush":"");body.innerHTML=html;body.onclick=null;
    $("modal").classList.toggle("is-dialog",!!dialog);
    $("modal").classList.toggle("is-panel",!!panel);
    $("modal").classList.toggle("is-wide",!!wide);
    $("modal").hidden=false;
    $("modalClose").focus();
  },
  close(){
    if($("modal").hidden)return;
    $("modal").hidden=true;$("modalBody").innerHTML="";  /* 清空 iframe, 停止作品音频/动画 */
    disposeDetached();
    const cb=this.onClose;this.onClose=null;
    if(this.last&&this.last.focus)this.last.focus();
    if(cb)cb();
  }
};
function confirmDialog({title,message,confirmText="确定",danger=false}){
  return new Promise(resolve=>{
    let settled=false;
    const finish=v=>{if(settled)return;settled=true;Modal.onClose=null;Modal.close();resolve(v)};
    Modal.open(title,`<p class="dialog-text">${esc(message)}</p><div class="dialog-actions">
      <button type="button" class="btn btn-secondary" data-dialog="no">取消</button>
      <button type="button" class="btn ${danger?"btn-danger-solid":"btn-primary"}" data-dialog="yes">${esc(confirmText)}</button></div>`,{dialog:true});
    Modal.onClose=()=>{if(!settled){settled=true;resolve(false)}};
    $("modalBody").onclick=e=>{const b=e.target.closest("[data-dialog]");if(b)finish(b.dataset.dialog==="yes")};
    $("modalBody").querySelector('[data-dialog="yes"]').focus();
  });
}
/* 启动类请求: 与速度测试共用端点时后端返回 endpoint_busy, 由用户确认是否仍要同时运行 */
async function postWithConflict(url,body){
  let d=await postJSON(url,body);
  if(!d.ok&&d.code==="endpoint_busy"){
    const go=await confirmDialog({title:"这个模型服务正在被使用",message:d.error+"\n\n同时测试会互相影响结果。仍要同时开始吗？",confirmText:"仍要开始"});
    if(!go)return null;
    d=await postJSON(url,{...body,force:true,conflict_with:d.conflict});
  }
  return d;
}
$("modalClose").onclick=()=>Modal.close();
$("modal").addEventListener("mousedown",e=>{if(e.target===$("modal"))Modal.close()});
/* 下拉菜单: ↑ ↓ 在菜单项之间移动(从按钮上按 ↓ 进到第一项) */
document.addEventListener("keydown",e=>{
  if((e.key!=="ArrowDown"&&e.key!=="ArrowUp")||!e.target.closest)return;
  const dd=e.target.closest("details.dropdown[open]");if(!dd)return;
  const items=[...dd.querySelectorAll(".menu .menu-item")].filter(x=>!x.disabled&&x.getClientRects().length);if(!items.length)return;
  e.preventDefault();
  const i=items.indexOf(document.activeElement),down=e.key==="ArrowDown";
  items[i<0?(down?0:items.length-1):(i+(down?1:items.length-1))%items.length].focus();
});
document.addEventListener("keydown",e=>{
  if($("modal").hidden){
    if(e.key==="Escape"){
      const open=document.querySelector("details.dropdown[open]");
      if(open){const inside=open.contains(document.activeElement);closeMenus();if(inside){const s=open.querySelector("summary");if(s)s.focus()}}  /* 焦点回到打开菜单的按钮 */
      else closeDrawers();
    }
    return;
  }
  if(e.key==="Escape"){Modal.close();return}
  if(e.key==="Tab"){  /* 焦点限制在弹窗内(只数能拿到焦点的: 图标里的 <use href> 不算, 藏起来的不算) */
    const f=[...$("modal").querySelectorAll("button,a[href],input,select,textarea,iframe,[tabindex]:not([tabindex='-1'])")].filter(x=>!x.disabled&&x.tabIndex>=0&&x.getClientRects().length);
    if(!f.length)return;
    if(e.shiftKey&&document.activeElement===f[0]){e.preventDefault();f[f.length-1].focus()}
    else if(!e.shiftKey&&document.activeElement===f[f.length-1]){e.preventDefault();f[0].focus()}
  }
});

/* ============================================================
   自定义下拉 (原生 <select> 与 datalist 的弹出列表由系统绘制, 无法跟随主题)
   - 原生 <select> 保留并隐藏, 继续承载 value / change, 现有逻辑零改动
   - 程序赋值 .value / .selectedIndex、重写 options 均自动同步显示
   - 选项多于 8 个时带搜索; 键盘 ↑↓ Home End Enter Esc
   ============================================================ */
const CSelect=(()=>{
  const panel=document.createElement("div");
  panel.className="cselect-panel";panel.hidden=true;panel.tabIndex=-1;
  panel.innerHTML=`<div class="cselect-search-wrap" hidden>${icon("search","icon-sm")}<input class="cselect-search" placeholder="搜索" aria-label="搜索选项" autocomplete="off"></div>
    <div class="cselect-list" role="listbox"></div>`;
  document.body.appendChild(panel);
  const searchWrap=panel.querySelector(".cselect-search-wrap"),search=panel.querySelector(".cselect-search"),listEl=panel.querySelector(".cselect-list");
  let cur=null;  /* {kind:"select"|"combo", el, anchor, items:[{value,text,disabled,selected}], view:[idx], active} */

  function splitText(t){const p=String(t).split(" · ");return p.length>2?[p[0],p.slice(1).join(" · ")]:[t,""]}
  function itemsOf(c){
    /* 选项可以用 data-sub 给第二行的小字(比如保存的模型: 名称一行, 模型名和地址一行) */
    if(c.kind==="select")return[...c.el.options].map((o,i)=>({value:o.value,text:o.textContent,sub:o.dataset.sub,disabled:o.disabled,selected:i===c.el.selectedIndex}));
    const dl=c.dl;const v=c.el.value;
    return dl?[...dl.options].map(o=>({value:o.value,text:o.value,sub:o.label||o.textContent,disabled:false,selected:o.value===v})):[];
  }
  function build(){
    const c=cur;c.items=itemsOf(c);
    const q=(c.kind==="combo"?(c.filter?c.el.value:""):search.value).trim().toLowerCase();
    c.view=c.items.map((x,i)=>i).filter(i=>!q||(c.items[i].text+" "+(c.items[i].sub||"")).toLowerCase().includes(q));
    if(!c.view.includes(c.active))c.active=c.view.find(i=>c.items[i].selected)??c.view.find(i=>!c.items[i].disabled)??-1;
    listEl.innerHTML=c.view.length?c.view.map(i=>{
      const it=c.items[i];const [main,sub]=it.sub!=null?[it.text,it.sub]:splitText(it.text);
      return `<div class="cselect-option${it.selected?" is-selected":""}${i===c.active?" is-active":""}${it.disabled?" is-disabled":""}" role="option" id="cso-${i}" data-i="${i}" aria-selected="${it.selected}">
        <span class="cselect-check">${it.selected?icon("check"):""}</span>
        <span class="cselect-text"><span class="cselect-main">${esc(main||"（空）")}</span>${sub?`<span class="cselect-sub">${esc(sub)}</span>`:""}</span></div>`;
    }).join(""):`<div class="cselect-empty">${c.items.length?"无匹配项":"暂无选项"}</div>`;
    if(c.kind==="select")c.anchor.setAttribute("aria-activedescendant",c.active>=0?"cso-"+c.active:"");
  }
  function position(){
    const r=cur.anchor.getBoundingClientRect();
    panel.style.minWidth=Math.max(r.width,200)+"px";
    panel.style.left="0px";panel.style.top="0px";
    const w=panel.offsetWidth,h=panel.offsetHeight;
    panel.style.left=Math.max(8,Math.min(r.left,innerWidth-w-8))+"px";
    const below=innerHeight-r.bottom-8,above=r.top-8;
    panel.style.top=(below<h&&above>below?Math.max(8,r.top-4-h):r.bottom+4)+"px";
  }
  function scrollActive(){const a=listEl.querySelector(".is-active");if(a)a.scrollIntoView({block:"nearest"})}
  function openFor(c){
    close(false);cur=c;
    const many=c.kind==="select"&&c.el.options.length>8;
    searchWrap.hidden=!many;search.value="";
    c.anchor.setAttribute("aria-expanded","true");
    build();panel.hidden=false;position();scrollActive();
    if(many)search.focus();
  }
  function close(refocus){
    if(!cur)return;
    const c=cur;cur=null;panel.hidden=true;
    c.anchor.setAttribute("aria-expanded","false");
    if(refocus)c.anchor.focus();
  }
  function choose(i){
    const c=cur;if(!c||i<0)return;const it=c.items[i];if(!it||it.disabled)return;
    if(c.kind==="select"){
      const changed=c.el.selectedIndex!==i;
      c.el.selectedIndex=i;close(true);
      if(changed)c.el.dispatchEvent(new Event("change",{bubbles:true}));
    }else{
      c.el.value=it.value;close(false);
      c.el.dispatchEvent(new Event("input",{bubbles:true}));c.el.dispatchEvent(new Event("change",{bubbles:true}));
    }
  }
  function move(step){
    const c=cur;if(!c||!c.view.length)return;
    const enabled=c.view.filter(i=>!c.items[i].disabled);if(!enabled.length)return;
    let pos=enabled.indexOf(c.active);
    pos=step==="home"?0:step==="end"?enabled.length-1:(pos<0?0:Math.max(0,Math.min(enabled.length-1,pos+step)));
    c.active=enabled[pos];
    listEl.querySelectorAll(".cselect-option").forEach(o=>o.classList.toggle("is-active",+o.dataset.i===c.active));
    if(c.kind==="select")c.anchor.setAttribute("aria-activedescendant","cso-"+c.active);
    scrollActive();
  }
  function onKey(e){
    if(!cur)return false;
    const k=e.key;
    if(k==="ArrowDown"){e.preventDefault();move(1)}
    else if(k==="ArrowUp"){e.preventDefault();move(-1)}
    else if(k==="Home"&&cur.kind==="select"){e.preventDefault();move("home")}
    else if(k==="End"&&cur.kind==="select"){e.preventDefault();move("end")}
    else if(k==="Enter"){e.preventDefault();choose(cur.active)}
    else if(k==="Escape"){e.preventDefault();e.stopPropagation();close(true)}
    else if(k==="Tab"){close(false)}
    else return false;
    return true;
  }
  panel.addEventListener("keydown",onKey);
  search.addEventListener("input",()=>{if(cur){cur.active=-1;build();position()}});
  listEl.addEventListener("mousemove",e=>{
    const o=e.target.closest(".cselect-option");if(!o||!cur||+o.dataset.i===cur.active)return;
    cur.active=+o.dataset.i;listEl.querySelectorAll(".cselect-option").forEach(x=>x.classList.toggle("is-active",x===o));
  });
  listEl.addEventListener("mousedown",e=>e.preventDefault());  /* 保持输入框焦点 */
  listEl.addEventListener("click",e=>{const o=e.target.closest(".cselect-option");if(o)choose(+o.dataset.i)});
  document.addEventListener("mousedown",e=>{if(cur&&!panel.contains(e.target)&&!cur.anchor.contains(e.target))close(false)},true);
  window.addEventListener("resize",()=>close(false));
  document.addEventListener("scroll",e=>{if(cur&&!panel.contains(e.target))position()},true);

  function renderLabel(sel){
    const cs=sel._cs;if(!cs)return;
    const o=sel.options[sel.selectedIndex],txt=o?o.textContent:"";
    cs.value.textContent=txt||"暂无选项";
    cs.value.classList.toggle("is-placeholder",!txt);
    cs.trigger.title=txt;
    cs.trigger.disabled=sel.disabled;
    if(cur&&cur.el===sel)build();
  }
  function enhance(sel){
    if(sel._cs)return;
    const wrap=document.createElement("span");wrap.className="cselect";
    sel.parentNode.insertBefore(wrap,sel);wrap.appendChild(sel);
    const trigger=document.createElement("button");
    trigger.type="button";trigger.className=sel.className+" cselect-trigger";
    trigger.setAttribute("aria-haspopup","listbox");trigger.setAttribute("aria-expanded","false");
    const lbl=sel.getAttribute("aria-label")||(sel.id&&document.querySelector(`label[for="${sel.id}"]`)||{}).textContent;
    if(lbl)trigger.setAttribute("aria-label",lbl.trim());
    trigger.innerHTML=`<span class="cselect-value"></span>`;
    wrap.appendChild(trigger);
    sel.className="cselect-native";sel.tabIndex=-1;sel.setAttribute("aria-hidden","true");
    sel._cs={trigger,value:trigger.firstChild};
    if(sel.id)document.querySelectorAll(`label[for="${sel.id}"]`).forEach(l=>l.addEventListener("click",e=>{e.preventDefault();trigger.focus()}));
    for(const prop of ["value","selectedIndex"]){  /* 程序赋值时同步显示 */
      const d=Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,prop);
      Object.defineProperty(sel,prop,{configurable:true,get(){return d.get.call(this)},set(v){d.set.call(this,v);renderLabel(this)}});
    }
    new MutationObserver(()=>renderLabel(sel)).observe(sel,{childList:true,subtree:true,attributes:true,characterData:true});
    sel.addEventListener("change",()=>renderLabel(sel));
    trigger.addEventListener("click",()=>{if(cur&&cur.el===sel)close(true);else openFor({kind:"select",el:sel,anchor:trigger,active:sel.selectedIndex})});
    trigger.addEventListener("keydown",e=>{
      if(cur&&cur.el===sel){onKey(e);return}
      if(["ArrowDown","ArrowUp","Enter"," "].includes(e.key)){e.preventDefault();openFor({kind:"select",el:sel,anchor:trigger,active:sel.selectedIndex})}
    });
    renderLabel(sel);
  }
  function combo(input){
    const dl=$(input.getAttribute("list"));if(!dl)return;
    input.removeAttribute("list");input.setAttribute("autocomplete","off");
    input.setAttribute("role","combobox");input.setAttribute("aria-expanded","false");
    const openCombo=filter=>{if(!dl.options.length)return;
      if(cur&&cur.el===input){cur.filter=filter;build();position();return}
      openFor({kind:"combo",el:input,anchor:input,dl,filter,active:-1})};
    input.addEventListener("focus",()=>openCombo(false));
    input.addEventListener("click",()=>openCombo(false));
    input.addEventListener("input",e=>{if(e.isTrusted)openCombo(true)});
    input.addEventListener("keydown",e=>{
      if(cur&&cur.el===input){if(e.key==="Enter"&&cur.active<0){close(false);return}onKey(e);return}
      if(e.key==="ArrowDown"){e.preventDefault();openCombo(false)}
    });
    input.addEventListener("blur",()=>setTimeout(()=>{if(cur&&cur.el===input&&!panel.contains(document.activeElement))close(false)},120));
  }
  return{enhance,combo,close};
})();


/* ============================================================
   运行日志 + 状态轮询
   ============================================================ */
function LogBox(id,job){
  const el=$(id);let t0=0,timer=null;
  el.innerHTML=`<div class="runlog-bar" hidden><i></i></div><div class="runlog-head"><span class="runlog-dot"></span><span class="runlog-title"></span><span class="runlog-time"></span>
    <button class="btn btn-ghost btn-sm runlog-stop" type="button" hidden>${icon("stop")}停止</button>
    <button class="btn btn-ghost btn-sm runlog-copy" type="button">${icon("copy")}复制日志</button></div><pre class="runlog-body"></pre>`;
  const title=el.querySelector(".runlog-title"),time=el.querySelector(".runlog-time"),body=el.querySelector(".runlog-body");
  const stop=el.querySelector(".runlog-stop");
  let stopping=false;
  stop.onclick=async()=>{
    const ok=await confirmDialog(job==="bank"?{title:"停止更新题集",confirmText:"停止",danger:true,message:"不再继续下载，已经下载好的题集数据会留在本地，下次不用重新下载。"}:
      {title:"停止测试",confirmText:"停止",danger:true,
      message:"不再发新的请求，已经完成的结果会保留。"+(job==="iq"?"\n停止后可以在能力测试页接着跑。":"")+"\n正在进行的请求会被放弃。"});
    if(!ok)return;
    const d=await postJSON("/api/cancel",{job});
    if(!d.ok){toast(d.error,"error");return}
    stopping=true;stop.disabled=true;title.textContent="正在停止…";
  };
  el.querySelector(".runlog-copy").onclick=()=>{
    if(!navigator.clipboard){toast("当前浏览器不支持复制","error");return}
    navigator.clipboard.writeText(body.textContent).then(()=>toast("日志已复制","success",2000),()=>toast("复制失败","error"));
  };
  const tick=()=>{const s=Math.max(0,Math.round((Date.now()-t0)/1000));time.textContent=(s>=60?Math.floor(s/60)+" 分 ":"")+(s%60)+" 秒"};
  return{
    start(text){el.hidden=false;el.className="runlog is-running";title.textContent=text;body.textContent="";stopping=false;el.querySelector(".runlog-bar").hidden=true;
      stop.hidden=!job;stop.disabled=false;t0=Date.now();clearInterval(timer);timer=setInterval(tick,1000);tick();if(job)setRunning(job,true)},
    lines(arr){const atBottom=body.scrollHeight-body.scrollTop-body.clientHeight<32;body.textContent=arr.join("\n");if(atBottom)body.scrollTop=body.scrollHeight;
      const m=[...arr].reverse().map(x=>/进度\s*(\d+)\s*\/\s*(\d+)/.exec(x)).find(Boolean),bar=el.querySelector(".runlog-bar");
      if(m&&+m[2]>0){bar.hidden=false;bar.firstChild.style.width=Math.min(100,100*m[1]/m[2]).toFixed(1)+"%";bar.title=`已完成 ${m[1]} / ${m[2]}`}},
    state(s){if(s.cancelling){stopping=true;stop.disabled=true;title.textContent="正在停止…"}},
    get stopping(){return stopping},
    finish(ok,text){clearInterval(timer);tick();stop.hidden=true;el.className="runlog "+(ok?"is-ok":"is-fail");title.textContent=text;if(job)setRunning(job,false)}
  };
}
function pollStatus(url,log,{interval=2000,onDone}={}){
  const h=setInterval(async()=>{
    try{
      const s=await getJSON(url);
      log.lines((s.log||[]).map(x=>x.msg).slice(-300));
      log.state(s);
      if(!s.running){clearInterval(h);log.finish(!s.error,s.error?"没有完成："+s.error:(log.stopping?"已停止，完成的部分已保存":"已完成"));if(onDone)onDone(s)}
    }catch(e){}
  },interval);
  return h;
}

/* ============================================================
   图表层 (ECharts)
   规范: 同一系列在所有图里颜色不变(A 紫 / B 青…); 线 2px、点 8px 带底色描边; 面积只用 10% 淡色;
   网格线用细实线; 不画双纵轴(两种单位拆成两张图); 浮层里数值在前、名称在后;
   每张图都能切到「数据」表格查看具体数字。
   ============================================================ */
const CHARTS=new Map();
let CHART_RO=null;
function disposeDetached(){
  for(const [id,inst] of CHARTS){
    const dom=inst.getDom&&inst.getDom();
    if(!dom||!document.body.contains(dom)){try{inst.dispose()}catch(e){}CHARTS.delete(id)}
  }
}
function chartInst(id){
  const el=$(id);
  if(!el||typeof window.echarts==="undefined")return null;
  let inst=CHARTS.get(id);
  if(inst&&inst.getDom()!==el){try{inst.dispose()}catch(e){}inst=null;CHARTS.delete(id)}
  if(!inst){
    inst=window.echarts.init(el,null,{renderer:"canvas"});
    CHARTS.set(id,inst);el._ec=inst;
    if(typeof ResizeObserver!=="undefined"){
      if(!CHART_RO)CHART_RO=new ResizeObserver(es=>es.forEach(x=>{if(x.target._ec&&x.target.clientWidth)x.target._ec.resize()}));
      CHART_RO.observe(el);
    }
  }
  return inst;
}
/* 面积淡色: 只用 10% 透明度, 非法颜色回落到主色(历史事故: 漏传颜色导致渐变色标 undefined) */
function areaFill(color){
  const base=/^#?[0-9a-fA-F]{6}$/.test(String(color))?color:"#6950E8";
  return{color:withAlpha(base,.10)};
}
/* 浮层 HTML: 数值在前(加粗), 名称在后, 色块是短线; 全部转义 */
function tt(title,rows,sub){
  return `<div class="tt-title">${esc(title)}</div>`+rows.map(([color,name,val])=>
    `<div class="tt-row">${color?`<span class="tt-key" style="background:${color}"></span>`:`<span class="tt-key"></span>`}<span class="tt-v">${esc(val)}</span><span class="tt-n">${esc(name)}</span></div>`).join("")+
    (sub?`<div class="tt-sub">${esc(sub)}</div>`:"");
}
function baseOption(extra){
  return Object.assign({
    animation:false,  // 与离线报告一致; 交互感由浮层/图例承担
    textStyle:{fontFamily:C.font,fontSize:12,color:C.text2},
    grid:{left:4,right:16,top:36,bottom:4,containLabel:true},
    tooltip:{trigger:"axis",confine:true,transitionDuration:0,backgroundColor:C.surface,borderColor:C.borderStrong,borderWidth:1,padding:[8,12],
      textStyle:{color:C.text1,fontFamily:C.font,fontSize:12},extraCssText:"border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.18)",
      axisPointer:{type:"line",lineStyle:{color:C.axis,width:1}}},
  },extra||{});
}
function axisValue(o={}){
  return{type:"value",name:o.name||"",nameGap:10,nameTextStyle:{color:C.text3,fontSize:11,align:o.alignName||"left"},
    min:o.min,max:o.max,axisLine:{show:false},axisTick:{show:false},splitLine:{lineStyle:{color:C.grid,width:1}},
    axisLabel:{color:C.text3,fontSize:11,formatter:o.fmt||fmtAxis}};
}
function axisCat(data,o={}){
  return{type:"category",data,boundaryGap:o.gap!==false,name:o.name||"",nameLocation:"middle",nameGap:o.nameGap||26,
    nameTextStyle:{color:C.text3,fontSize:11},inverse:!!o.inverse,
    axisTick:{show:false},axisLine:{lineStyle:{color:C.axis}},axisLabel:{color:o.labelColor||C.text3,fontSize:11,hideOverlap:true,
      width:o.labelWidth,overflow:o.labelWidth?"truncate":undefined,formatter:o.fmt}};
}
function legendOf(names,kind="line"){
  return{show:names.length>1,top:0,left:0,itemGap:16,textStyle:{color:C.text2,fontSize:12},data:names,
    icon:kind==="line"?"rect":"roundRect",itemWidth:kind==="line"?16:10,itemHeight:kind==="line"?3:10};
}
/* 折线: 2px; 数据点只在点数不多(<=12)时显示, 否则悬停时出现; 面积只用 10% 淡色 */
function sLine(name,color,data,o={}){
  const dots=o.dots===false?false:(o.dots===true||(Array.isArray(data)&&data.length<=12));
  return{name,type:"line",data,connectNulls:true,symbol:"circle",symbolSize:7,showSymbol:dots,
    lineStyle:{width:2,color},itemStyle:{color,borderColor:C.surface,borderWidth:2},
    areaStyle:o.area?areaFill(color):undefined,emphasis:{focus:"series"},z:o.z||2,
    endLabel:o.endLabel?{show:true,formatter:"{a}",color,fontSize:11,fontWeight:600,distance:6}:undefined};
}
/* 柱: 单系列最宽 28px, 分组时每根最宽 14px; 顶端 4px 圆角; 同组柱之间留 2px 左右的空隙 */
function sBar(name,color,data,o={}){
  return{name,type:"bar",data,barMaxWidth:o.maxWidth||(o.grouped?14:28),barGap:o.grouped?"18%":"12%",barCategoryGap:o.catGap||"38%",stack:o.stack,
    itemStyle:{color,borderRadius:o.flat?0:(o.horizontal?[0,4,4,0]:[4,4,0,0])},
    label:o.label?{show:true,position:o.horizontal?"right":"top",color:C.text2,fontSize:11,formatter:o.label}:undefined,
    emphasis:{focus:"series"}};
}
/* 同一条轴统一数字格式: 最大值过万时全部用 k, 否则用千分位 */
function axisFmtFor(series){
  const mx=Math.max(0,...series.flatMap(s=>s.data.map(v=>Math.abs(Array.isArray(v)?v[1]:v)||0)));
  return mx>=10000?(v=>v===0?"0":(v/1000).toFixed(v%1000?1:0)+"k"):(v=>Math.abs(v)>=1000?Math.round(v).toLocaleString():fmtAxis(v));
}
/* 两色按比例混合(得到不透明的中间色), 用于同一色相由浅到深的顺序色 */
function mix(c1,c2,t){
  const h=x=>{const m=String(x||"").replace("#","");return m.length===6?[0,2,4].map(i=>parseInt(m.slice(i,i+2),16)):null};
  const a=h(c1),b=h(c2);if(!a||!b)return c1;
  return "#"+a.map((v,i)=>Math.round(v*(1-t)+b[i]*t).toString(16).padStart(2,"0")).join("");
}
/* 进度条清单: 每行 = 名称 + 带底槽的横条 + 右侧对齐的数值文字; 没有坐标轴, 高度随行数变化, 只有一两行也不空。
   rows: [{name, values:[每个系列的值], colors?:[每个系列的颜色], right:"右侧文字"}]; series: [{name,color}] */
function meterChart(id,{rows,series,max,nameWidth=150,tip}){
  const el=$(id);if(!el)return;
  const S=series&&series.length?series:[{name:"",color:C.a}],multi=S.length>1,rowH=multi?40:30;
  el.style.height=Math.max(44,rows.length*rowH+(multi?34:6))+"px";
  if(!rows.length){chartEmpty(id);return}
  const mx=max||Math.max(1,...rows.flatMap(r=>r.values.map(v=>v||0)));
  setChart(id,{animation:false,textStyle:{fontFamily:C.font},
    legend:multi?legendOf(S.map(x=>x.name),"rect"):{show:false},
    grid:{left:0,right:0,top:multi?30:2,bottom:2,containLabel:true},
    xAxis:{type:"value",max:mx,show:false},
    yAxis:[{type:"category",inverse:true,data:rows.map(r=>r.name),axisLine:{show:false},axisTick:{show:false},
        axisLabel:{color:C.text1,fontSize:13,width:nameWidth,overflow:"truncate",margin:14}},
      {type:"category",inverse:true,position:"right",data:rows.map(r=>r.right||""),axisLine:{show:false},axisTick:{show:false},
        axisLabel:{color:C.text2,fontSize:12,fontWeight:600,margin:14}}],
    tooltip:Object.assign(baseOption().tooltip,{trigger:"item",formatter:q=>{const r=rows[q.dataIndex];
      return tip?tip(r,q.seriesIndex):tt(r.name,[[q.color,S[q.seriesIndex].name||"",r.right||String(q.value)]])}}),
    series:S.map((x,si)=>({name:x.name,type:"bar",yAxisIndex:0,barWidth:multi?9:12,barGap:"70%",
      showBackground:true,backgroundStyle:{color:C.track,borderRadius:6},
      itemStyle:{color:x.color,borderRadius:6},
      data:rows.map(r=>({value:r.values[si],itemStyle:{color:(r.colors&&r.colors[si])||x.color,borderRadius:6}}))}))});
}
function chartEmpty(id,text){
  const inst=chartInst(id);if(!inst)return;
  inst.setOption({graphic:{type:"text",left:"center",top:"middle",style:{text:text||"没有数据",fill:C.text3,fontSize:13,fontFamily:C.font}},
    xAxis:{show:false},yAxis:{show:false},series:[]},true);
}
function setChart(id,opt){
  const inst=chartInst(id);if(!inst)return null;
  inst.setOption(opt,true);inst.resize();
  return inst;
}
/* 常用: 类目横轴 + 多条折线, 单一数值轴(同一单位) */
function lineChart(id,{cats,series,unit,digits=1,yName,xName,area=false,tip}){
  if(!series.some(s=>s.data.some(v=>v!=null))){chartEmpty(id);return}
  setChart(id,baseOption({
    color:series.map(s=>s.color),
    legend:legendOf(series.map(s=>s.name)),
    grid:{left:4,right:series.length>1&&series.length<=4?30:16,top:series.length>1?44:30,bottom:xName?26:4,containLabel:true},
    xAxis:axisCat(cats,{gap:false,name:xName}),
    yAxis:axisValue({name:yName||unit,fmt:axisFmtFor(series)}),
    tooltip:Object.assign(baseOption().tooltip,{formatter:ps=>{
      const i=ps[0].dataIndex;
      return tt(tip&&tip.title?tip.title(i):String(ps[0].axisValue),
        ps.filter(p=>p.value!=null).map(p=>[p.color,p.seriesName,fmt(p.value,digits)+" "+(unit||"")]),tip&&tip.sub?tip.sub(i,ps):"");}}),
    series:series.map(s=>sLine(s.name,s.color,s.data,{area:area&&series.length===1,endLabel:series.length>1&&series.length<=4}))}));
}
/* 常用: 类目 + 分组柱, 单一数值轴 */
function barChart(id,{cats,series,unit,digits=1,yName,horizontal=false,labels=false,tip,height,catLabelWidth}){
  if(!series.some(s=>s.data.some(v=>v!=null))){chartEmpty(id);return}
  const cat=axisCat(cats,{inverse:horizontal,labelWidth:catLabelWidth});
  const af=axisFmtFor(series);
  const val=horizontal?axisValue({fmt:v=>af(v)+(unit==="%"?"%":"")}):axisValue({name:yName||unit,fmt:af});
  const lab=labels?(p=>p.value==null?"":fmt(p.value,digits)):null;
  setChart(id,baseOption({
    color:series.map(s=>s.color),
    legend:legendOf(series.map(s=>s.name),"rect"),
    grid:{left:4,right:labels&&horizontal?48:16,top:series.length>1?44:30,bottom:4,containLabel:true},
    xAxis:horizontal?val:cat,yAxis:horizontal?cat:val,
    tooltip:Object.assign(baseOption().tooltip,{trigger:"axis",axisPointer:{type:"shadow",shadowStyle:{color:withAlpha(C.primary&&C.primary.length===7?C.primary:"#6950E8",.06)}},
      formatter:ps=>{const i=ps[0].dataIndex;
        return tt(tip&&tip.title?tip.title(i):String(ps[0].axisValue),
          ps.filter(p=>p.value!=null).map(p=>[p.color,p.seriesName,fmt(p.value,digits)+" "+(unit||"")]),tip&&tip.sub?tip.sub(i,ps):"");}}),
    series:series.map(s=>sBar(s.name,s.color,s.data,{horizontal,label:lab,grouped:series.length>1}))}));
  const auto=horizontal?Math.max(160,cats.length*(series.length>1?series.length*16+14:30)+(series.length>1?64:40)):0;
  if(height||auto){$(id).style.height=(height||auto)+"px";const inst=CHARTS.get(id);if(inst)inst.resize()}
}

/* ============================================================
   页面积木: 章节 / 图表卡 / 指标块 / 结论卡 / 对比标记
   ============================================================ */
function sec(id,title,desc,body,jump){
  return `<section class="sec" id="${id}" data-jump="${esc(jump||title)}"><div class="sec-head"><div><h2 class="sec-title">${title}</h2>${desc?`<p class="sec-desc">${desc}</p>`:""}</div></div>${body}</section>`;
}
function stripTags(h){return String(h).replace(/<[^>]*>/g,"")}
/* 图表卡: 右上角「数据」切换到同内容的表格(不靠悬停也能读到每个数) */
function ccard(id,title,{desc="",h=280,table="",span=false}={}){
  return `<div class="ccard${span?" span-all":""}"><div class="ccard-head"><div><h3 class="ccard-title">${title}</h3>${desc?`<p class="ccard-desc">${desc}</p>`:""}</div>
    ${table?`<button type="button" class="btn btn-ghost btn-sm" data-flip aria-pressed="false" title="切换为数据表">${icon("table")}数据</button>`:""}</div>
    <div class="chart" id="${id}" style="height:${h}px" role="img" aria-label="${esc(stripTags(title))}"></div>
    ${table?`<div class="ccard-table">${table}</div>`:""}</div>`;
}
let SPY=null;
function buildJump(navId,root){
  const nav=$(navId);if(!nav)return;
  const secs=root?[...root.querySelectorAll("section.sec[data-jump]")]:[];
  nav.innerHTML=secs.length>1?secs.map(s=>`<a href="javascript:void 0" data-jumpto="${esc(s.id)}">${esc(s.dataset.jump)}</a>`).join(""):"";
  if(SPY){SPY.disconnect();SPY=null}
  if(secs.length<2||typeof IntersectionObserver==="undefined")return;
  const seen=new Map();
  SPY=new IntersectionObserver(es=>{
    es.forEach(x=>seen.set(x.target.id,x.isIntersecting));
    const cur=secs.find(s=>seen.get(s.id));
    nav.querySelectorAll("a").forEach(a=>{const on=!!cur&&a.dataset.jumpto===cur.id;a.setAttribute("aria-current",String(on));if(on)keepInNav(nav,a)});
  },{rootMargin:"-120px 0px -55% 0px"});
  secs.forEach(s=>SPY.observe(s));
}
/* 章节目录一行放不下(手机)时, 把当前章节滚到目录中间: 只滚目录本身, 不动页面。
   不能用 scrollIntoView: 它会连带滚动整页, 手指正在往下滑时会被打断, 页面还会被拉回吸顶页头的位置 */
function keepInNav(nav,a){
  if(nav.scrollWidth<=nav.clientWidth)return;
  const nr=nav.getBoundingClientRect(),ar=a.getBoundingClientRect();
  if(ar.left>=nr.left+8&&ar.right<=nr.right-8)return;
  nav.scrollTo({left:nav.scrollLeft+(ar.left+ar.width/2)-(nr.left+nr.width/2),behavior:"smooth"});
}
/* 概览带: 左边结论, 右边 3–5 个关键数字 */
function stat(label,value,unit,{sub="",delta="",tip="",hero=false,wide=false}={}){
  return `<div class="stat${hero?" is-hero":""}${wide?" is-wide":""}"${tip?` title="${esc(tip)}"`:""}><div class="stat-label"><span>${label}</span>${delta}</div>
    <div class="stat-value">${value}${unit&&value!=="—"?`<small>${unit}</small>`:""}</div>${sub?`<div class="stat-sub">${sub}</div>`:""}</div>`;
}
function overview(concl,stats,{title="结论",meta="",cols=2}={}){
  const ic={good:"check-circle",bad:"x-circle",warn:"alert",info:"bulb"};
  return `<div class="ov"><div class="ov-concl"><div class="ov-h">${esc(title)}</div>
    <ul class="summary-list">${concl.map(i=>`<li class="is-${i.tone||"info"}">${icon(ic[i.tone||"info"])}<span>${i.html}</span></li>`).join("")}</ul>
    ${meta?`<div class="ov-meta">${meta}</div>`:""}</div>
    ${stats?`<div class="ov-stats" style="--cols:${cols}">${stats}</div>`:""}</div>`;
}
/* 加载中: 与最终布局同形的骨架 */
function skeletonPage(){
  const line=w=>`<div class="skeleton" style="height:12px;width:${w}%;margin-top:14px"></div>`;
  return `<div class="ov"><div><div class="skeleton" style="height:12px;width:18%"></div>${line(88)}${line(76)}${line(82)}</div>
    <div class="ov-stats">${'<div class="stat"><div class="skeleton" style="height:10px;width:50%"></div><div class="skeleton" style="height:26px;width:66%;margin-top:12px"></div></div>'.repeat(4)}</div></div>
    <div class="sec"><div class="skeleton" style="height:14px;width:24%"></div><div class="grid-3" style="margin-top:20px">${'<div class="skeleton" style="height:200px"></div>'.repeat(3)}</div></div>`;
}
function kpi(label,value,unit,{sub="",delta="",hero=false,tip=""}={}){
  return `<div class="kpi${hero?" is-hero":""}"${tip?` title="${esc(tip)}"`:""}><div class="kpi-head"><span class="kpi-label">${label}</span>${delta}</div>
    <div class="kpi-value">${value}${unit&&value!=="—"?`<small>${unit}</small>`:""}</div>${sub?`<div class="kpi-sub">${sub}</div>`:""}</div>`;
}
function summaryCard(title,items,foot=""){
  const ic={good:"check-circle",bad:"x-circle",warn:"alert",info:"bulb"};
  if(!items.length)return "";
  return `<div class="summary"><div class="summary-head">${icon("bulb")}<span class="summary-title">${title}</span></div>
    <ul class="summary-list">${items.map(i=>`<li class="is-${i.tone||"info"}">${icon(ic[i.tone||"info"])}<span>${i.html}</span></li>`).join("")}</ul>
    ${foot?`<div class="summary-foot">${foot}</div>`:""}</div>`;
}
/* 变化标记: deltaPill(基准, 对象) = 对象相对基准; dir=1 越高越好, -1 越低越好; mode=pp 用百分点。
   页面上一律写成「A 比 B」: deltaPill(B 的值, A 的值, dir, {prefix:"比 B "}) */
function deltaPill(va,vb,dir,{mode="pct",prefix=""}={}){
  if(va==null||vb==null)return `<span class="delta flat">—</span>`;
  const d=mode==="pp"?vb-va:(va?(vb-va)/Math.abs(va)*100:0);
  const flat=Math.abs(d)<(mode==="pp"?.5:1);
  const unit=mode==="pp"?" 个百分点":"%";
  if(flat)return `<span class="delta flat" title="${dir<0?"越低越好":"越高越好"}，基本持平">${icon("minus")}${prefix}持平</span>`;
  const good=d*dir>0;
  return `<span class="delta ${good?"up":"down"}" title="${dir<0?"越低越好":"越高越好"}，${good?"更好":"更差"}">${icon(d>0?"arrow-up":"arrow-down")}${prefix}${d>=0?"+":""}${fmt(d,1)}${unit}</span>`;
}
/* pctChange(基准, 对象): 对象相对基准变化了百分之几; 页面上用 pctChange(B, A) 表示「A 比 B」 */
function pctChange(va,vb){return va==null||vb==null||!va?null:(vb-va)/Math.abs(va)*100}
/* 表格: head=[列名...], rows=[[单元格 HTML...]...] */
function table(head,rows,{maxH}={}){
  return `<div class="table-wrap"${maxH?` style="max-height:${maxH}px"`:""}><table class="table"><thead><tr>${head.map(h=>`<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map(c=>`<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
/* A/B 对照单元格: 主值 + 下方小字 B 值 */
function abCell(va,vb,f,hasB){return `${f(va)}${hasB?`<span class="sub">B ${f(vb)}</span>`:""}`}

/* ============================================================
   多表格系统
   - dataTable(spec): 统一的表格组件。排序(升/降/还原)、吸顶表头、固定首列、两层表头、
     格内细条 / 热力底色 / 变化 / 状态、搜索、列显隐、复制(TSV)、导出 CSV、行展开、分页、分组
   - 7 种形态都是同一个组件的不同配置: 明细 / 对比 / 矩阵热力 / 排行 / 分组 / 检查矩阵 / 统计摘要
   - panel(): 章节面板, 右上角「图表 | 表格」切换; 吸顶栏的页面级切换一次换整页
   列定义: {key,label,unit,type,digits,get,fmt,text,sortValue,sticky,group,hidden,tip,color,max,scale,dir,noSort,width}
     type: text | num | int | pct | sec | delta | status | bar | heat | tag | html
   ============================================================ */
const DT={specs:new Map(),state:new Map()};
const DT_PAGE=50;
const DT_LS="llm-bench-pro-dt";
function dtState(id,spec){
  let s=DT.state.get(id);
  if(!s){
    const saved=lsGet(DT_LS)[id]||{};
    spec=spec||DT.specs.get(id);
    /* 没有保存过选择时, 列定义里写了 hidden:true 的列默认不显示 */
    const hidden=saved.hidden||(spec?spec.columns.filter(c=>c.hidden).map(c=>c.key):[]);
    s={sort:saved.sort||null,hidden:new Set(hidden),size:saved.size||0,q:"",page:0,open:new Set(),closed:new Set()};
    DT.state.set(id,s);
  }
  return s;
}
function dtSave(id){const all=lsGet(DT_LS),s=dtState(id);all[id]={sort:s.sort,hidden:[...s.hidden],size:s.size||undefined};lsSet(DT_LS,all)}
/* 每页行数: 表格给了 pageSizes 时可以在表格底部选, 否则用 pageSize */
function dtPageSize(spec,st){return(spec.pageSizes&&spec.pageSizes.includes(st.size)?st.size:0)||spec.pageSize||DT_PAGE}
/* 翻页器: 页码(首页、末页、当前页前后各一页, 中间用 … 省略) + 跳到第几页 + 可选的每页条数。
   kind 是 data 属性前缀: data-{kind}-page / -jump / -jumpbtn / -size; compact = 只有 ‹ [当前页] / 总页数 › */
function pageList(p,n){
  if(n<=7)return [...Array(n).keys()];
  const s=new Set([0,n-1,p-1,p,p+1]);
  if(p<=3)[1,2,3,4].forEach(x=>s.add(x));
  if(p>=n-4)[n-5,n-4,n-3,n-2].forEach(x=>s.add(x));
  const a=[...s].filter(x=>x>=0&&x<n).sort((x,y)=>x-y),out=[];
  a.forEach((x,i)=>{if(i){const g=x-a[i-1];if(g===2)out.push(x-1);else if(g>2)out.push(null)}out.push(x)});
  return out;
}
function pagerHTML(kind,{page,pages,total,unit="",size,sizes,compact=false,keys=false}){
  const at=`data-${kind}-page`;
  const arrow=(to,dir,label,off)=>`<button type="button" class="pager-btn" ${at}="${to}" data-dir="${dir}" aria-label="${label}" title="${label}${keys?`（键盘 ${dir==="prev"?"←":"→"}）`:""}"${off?" disabled":""}>${icon(dir==="prev"?"chevron-left":"chevron-right","icon-sm")}</button>`;
  const prev=arrow(page-1,"prev","上一页",page<=0),next=arrow(page+1,"next","下一页",page>=pages-1);
  const input=extra=>`<input class="pager-input" type="number" inputmode="numeric" min="1" max="${pages}" data-${kind}-jump aria-label="跳到第几页（共 ${pages} 页）"${extra}>`;
  if(compact)return pages>1?`<div class="pager is-compact">${prev}<label class="pager-cur">${input(` value="${page+1}"`)}<span>/ ${fmtInt(pages)} 页</span></label>${next}</div>`:"";
  const nums=pageList(page,pages).map(x=>x==null?`<span class="pager-gap" aria-hidden="true">…</span>`:
    `<button type="button" class="pager-btn pager-num${x===page?" is-current":""}" ${at}="${x}"${x===page?' aria-current="page"':""}>${x+1}</button>`).join("");
  const info=[total!=null?`<span>共 ${fmtInt(total)} ${unit}</span>`:"",
    sizes?`<label class="pager-size">每页<select class="select" data-${kind}-size aria-label="每页显示多少${unit||"行"}">${sizes.map(n=>`<option value="${n}"${n===size?" selected":""}>${n}</option>`).join("")}</select>${unit}</label>`:""].join("");
  const ctrl=pages>1?`<nav class="pager-nav" aria-label="翻页">${prev}<span class="pager-nums">${nums}</span><span class="pager-of">${page+1} / ${fmtInt(pages)}</span>${next}</nav>
    <span class="pager-jump">跳到第${input(` placeholder="${page+1}"`)}页<button type="button" class="btn btn-secondary btn-sm" data-${kind}-jumpbtn>跳转</button></span>`:"";
  return info||ctrl?`<div class="pager">${info?`<div class="pager-info">${info}</div>`:""}${ctrl?`<div class="pager-ctrl">${ctrl}</div>`:""}</div>`:"";
}
/* 跳页输入框 → 0 起的页号(超出范围夹到首页/末页); 没填或不是数字返回 null */
function pagerTarget(input){
  if(!input)return null;
  const v=parseInt(String(input.value).trim(),10),max=parseInt(input.max,10)||1;
  return isFinite(v)?Math.min(Math.max(1,v),max)-1:null;
}
/* 翻页会重画翻页器: 记下焦点在哪个位置, 重画后放回同一个翻页器的对应位置(键盘连续翻页不丢焦点) */
function pagerFocusKey(){
  const a=document.activeElement,p=a&&a.closest&&a.closest(".pager");if(!p)return null;
  return{compact:p.classList.contains("is-compact"),what:a.dataset.dir||(a.matches(".pager-input,[data-qb-jumpbtn],[data-dt-jumpbtn],[data-gw-jumpbtn]")?"jump":"num")};
}
function pagerRefocus(root,k){
  if(!k||!root)return;
  const p=root.querySelector(k.compact?".pager.is-compact":".pager:not(.is-compact)");if(!p)return;
  const el=p.querySelector({prev:"[data-dir=prev]:not([disabled])",next:"[data-dir=next]:not([disabled])",jump:".pager-input",num:".pager-num.is-current"}[k.what])||
    p.querySelector(".pager-num.is-current")||p.querySelector(".pager-input");
  if(el)el.focus({preventScroll:true});
}
/* 翻页后内容顶部不在视野里(比如在底部翻页器翻页)时, 滚回内容顶部 */
function scrollTopIntoView(el){
  if(!el)return;
  const pad=parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop)||0,r=el.getBoundingClientRect();
  if(r.top<pad-4||r.top>innerHeight*.6)el.scrollIntoView({block:"start"});
}
/* 数字: 千分位 + 固定小数位; 空值 "—" */
function numText(v,d=1){return v==null||!isFinite(v)?"—":Number(v).toLocaleString("zh-CN",{minimumFractionDigits:d,maximumFractionDigits:d})}
function dtDigits(col){return col.digits??(col.type==="int"?0:col.type==="sec"?2:1)}
function dtVal(col,row){return col.get?col.get(row):row[col.key]}
const TONE_RANK={bad:3,warn:2,neutral:1,info:1,good:0};
/* 排序与导出用的原始值: 数字 / 文本; 状态取文字, 变化取百分比 */
function dtRaw(col,row){
  const v=dtVal(col,row);
  if(v==null)return null;
  if(col.type==="status")return v.text??"";
  if(col.type==="tag")return String(v);
  if(typeof v==="number")return isFinite(v)?v:null;
  if(col.type==="html")return col.text?col.text(v,row):stripTags(String(v)).trim();
  return col.text?col.text(v,row):v;
}
function dtSortKey(col,row){
  if(col.sortValue)return col.sortValue(row);
  const v=dtVal(col,row);
  if(col.type==="status")return v?TONE_RANK[v.tone]??1:null;
  if(col.type==="delta"){const dir=col.dir??row._dir??1;return v==null||!isFinite(v)?null:v*dir}
  return dtRaw(col,row);
}
/* 导出值: 数字按显示精度取整, 不带千分位 */
function dtExport(col,row){
  const raw=dtRaw(col,row);
  if(raw==null||raw==="")return"";
  if(typeof raw==="number"){const d=col.digitsOf?col.digitsOf(row):dtDigits(col);return col.type==="delta"?(raw>=0?"+":"")+raw.toFixed(1)+"%":String(Number(raw.toFixed(d)))}
  return String(raw);
}
function dtCompare(a,b){
  if(typeof a==="number"&&typeof b==="number")return a-b;
  return String(a).localeCompare(String(b),"zh-CN",{numeric:true});
}
/* 排序: 空值永远排最后; 相等时保持原顺序 */
function dtSortRows(spec,rows,sort){
  if(!sort)return rows;
  const col=spec.columns.find(c=>c.key===sort.key);if(!col)return rows;
  const key=r=>{const v=dtSortKey(col,r);return v==null||v===""||(typeof v==="number"&&!isFinite(v))?null:v};
  return rows.map((r,i)=>[r,key(r),i]).sort((x,y)=>{
    if(x[1]==null||y[1]==null)return x[1]==null&&y[1]==null?x[2]-y[2]:(x[1]==null?1:-1);
    const c=dtCompare(x[1],y[1]);
    return c?(sort.dir==="desc"?-c:c):x[2]-y[2];
  }).map(x=>x[0]);
}
function dtVisibleCols(spec){const st=dtState(spec.id);return spec.columns.filter(c=>c.sticky||!st.hidden.has(c.key))}
/* 过滤 + 排序后的全部行(不分页) */
function dtRows(spec){
  const st=dtState(spec.id),cols=dtVisibleCols(spec);
  let rows=spec.rows||[];
  const q=st.q.trim().toLowerCase();
  if(q)rows=rows.filter(r=>cols.some(c=>{const t=dtExport(c,r);return t&&t.toLowerCase().includes(q)})||(spec.searchText&&spec.searchText(r).toLowerCase().includes(q)));
  return dtSortRows(spec,rows,st.sort);
}
/* 导出矩阵: 可见列 + 过滤排序后的全部行 */
function dtMatrix(spec){
  const cols=dtVisibleCols(spec);
  return{head:cols.map(c=>[c.group,c.label&&stripTags(c.label),c.unit?`（${c.unit}）`:""].filter(Boolean).join(" ").replace(" （","（")),
    rows:dtRows(spec).map(r=>cols.map(c=>dtExport(c,r)))};
}
function csvCell(v){const s=v==null?"":String(v);return /[",\r\n]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s}
function toCSV(m,title){return "﻿"+(title?csvCell(title)+"\r\n":"")+[m.head,...m.rows].map(r=>r.map(csvCell).join(",")).join("\r\n")}
function toTSV(m){return [m.head,...m.rows].map(r=>r.map(v=>String(v??"").replace(/[\t\r\n]+/g," ")).join("\t")).join("\n")}
function downloadText(name,text,type="text/csv;charset=utf-8"){downloadBlob(name,new Blob([text],{type}))}
function downloadBlob(name,blob){
  const u=URL.createObjectURL(blob);
  const a=document.createElement("a");a.href=u;a.download=name;document.body.appendChild(a);a.click();a.remove();
  setTimeout(()=>URL.revokeObjectURL(u),4000);
}
function safeName(s){return String(s||"表格").replace(/[\\/:*?"<>|\s]+/g,"_").slice(0,60)}
/* 热力底色: seq = 同一色相由浅到深; div = 正(更好)绿 / 负(更差)红, 小于 1 视为持平 */
function heatBg(t){return mix(C.surface,C.heatHi||C.series[4],Math.max(0,Math.min(1,t))*.62)}
function divBg(g,lim){if(g==null||!isFinite(g)||Math.abs(g)<1)return"";const t=Math.min(1,Math.abs(g)/(lim||20));return mix(C.surface,g>0?C.goodMark:C.badMark,.12+t*.46)}
function deltaText(d,dir){
  if(d==null||!isFinite(d))return `<span class="dt-delta flat">—</span>`;
  if(Math.abs(d)<1)return `<span class="dt-delta flat">${icon("minus","icon-sm")}持平</span>`;
  const good=d*(dir||1)>0;
  return `<span class="dt-delta ${good?"up":"down"}">${icon(d>0?"arrow-up":"arrow-down","icon-sm")}${d>=0?"+":""}${fmt(d,1)}%</span>`;
}
function statusBadge(v){
  if(!v||(v.tone==="neutral"&&(!v.text||v.text==="—")))return `<span class="faint">—</span>`;
  const ic={good:"check",bad:"x",warn:"alert",info:"clock",neutral:"minus"}[v.tone]||"minus";
  return `<span class="badge is-${v.tone==="neutral"?"plain":v.tone}"${v.tip?` title="${esc(v.tip)}"`:""}>${icon(v.icon||ic)}${esc(v.text)}</span>`;
}
/* 单元格 HTML */
function dtCell(col,row,ctx){
  const v=dtVal(col,row);
  if(col.fmt)return col.fmt(v,row);
  const d=dtDigits(col);
  switch(col.type){
    case "html":return v==null?"—":String(v);
    case "tag":{const c=(row._color)||C.a;return v?`<span class="run-tag" style="background:${c}">${esc(v)}</span>`:""}
    case "status":return statusBadge(v);
    case "delta":return deltaText(v,col.dir??row._dir??1);
    case "sec":return v==null||!isFinite(v)?"—":fmtSec(v);
    case "bar":{
      if(v==null||!isFinite(v))return"—";
      const mx=col.max||ctx.max[col.key]||1,w=Math.max(0,Math.min(100,100*v/mx));
      return `<span class="dt-barcell"><span class="dt-meter"><i style="width:${w.toFixed(1)}%;background:${row._color&&col.runColor?row._color:(col.color||C.text3)}"></i></span><span class="dt-num">${numText(v,d)}</span></span>`;
    }
    case "num":case "int":case "pct":case "heat":return numText(v,d);
    default:return v==null||v===""?"—":esc(v);
  }
}
function dtAlign(col){return col.align||(["text","status","html","tag"].includes(col.type||"text")?"left":"right")}
function dtHeat(spec,cols,rows){
  /* 热力列的取值范围: spec.heatShared 时所有热力列共用一个范围(矩阵表) */
  const heatCols=cols.filter(c=>c.type==="heat");
  const range=list=>{const xs=list.filter(v=>v!=null&&isFinite(v));return xs.length?[Math.min(...xs),Math.max(...xs)]:null};
  const out={};
  if(spec.heatShared){const r=range(heatCols.flatMap(c=>rows.map(x=>dtVal(c,x))));heatCols.forEach(c=>out[c.key]=r)}
  else heatCols.forEach(c=>out[c.key]=range(rows.map(x=>dtVal(c,x))));
  return out;
}
function dtCellStyle(col,row,ctx){
  const v=dtVal(col,row);
  if(col.type==="heat"&&v!=null&&isFinite(v)){
    if(col.scale==="div"){const g=v*(col.dir??row._dir??1);const bg=divBg(g,col.lim||ctx.divLim);return bg?` style="background:${bg}"`:""}
    const r=ctx.heat[col.key];if(!r)return"";
    const t=r[1]>r[0]?(v-r[0])/(r[1]-r[0]):.5;
    return ` style="background:${heatBg(col.invert?1-t:t)}"`;
  }
  return"";
}
function dtInner(spec){
  const st=dtState(spec.id);
  const cols=dtVisibleCols(spec);
  const all=dtRows(spec);
  const size=dtPageSize(spec,st);
  const pages=Math.max(1,Math.ceil(all.length/size));
  st.page=Math.min(Math.max(0,st.page),pages-1);
  const view=all.length>size?all.slice(st.page*size,(st.page+1)*size):all;
  const ctx={max:{},heat:dtHeat(spec,cols,spec.rows||[]),divLim:spec.divLim||20};
  cols.filter(c=>c.type==="bar").forEach(c=>ctx.max[c.key]=Math.max(1e-9,...(spec.rows||[]).map(r=>{const v=dtVal(c,r);return v!=null&&isFinite(v)?v:0})));
  const hasGroups=cols.some(c=>c.group);
  let groupRow="";
  if(hasGroups){
    const spans=[];cols.forEach(c=>{const g=c.group||"";const last=spans[spans.length-1];if(last&&last.g===g)last.n++;else spans.push({g,n:1,sticky:c.sticky})});
    groupRow=`<tr class="dt-groups">${spans.map(x=>`<th colspan="${x.n}" class="${x.sticky?"dt-sticky":""}${x.g?" has-group":""}">${x.g?`<span>${x.g}</span>`:""}</th>`).join("")}</tr>`;
  }
  const th=c=>{
    const sorted=st.sort&&st.sort.key===c.key?st.sort.dir:"";
    const can=!c.noSort&&!spec.noSort;
    return `<th data-k="${esc(c.key)}" class="dt-${dtAlign(c)}${c.sticky?" dt-sticky":""}${can?" can-sort":""}"${can?` tabindex="0" aria-sort="${sorted==="asc"?"ascending":sorted==="desc"?"descending":"none"}"`:""}${c.tip?` title="${esc(c.tip)}"`:""}${c.width?` style="width:${c.width}"`:""}>`+
      `<span class="dt-th">${c.label}${c.unit?`<span class="dt-unit">${esc(c.unit)}</span>`:""}${can?`<span class="dt-sort">${sorted==="asc"?"▲":sorted==="desc"?"▼":""}</span>`:""}</span></th>`;
  };
  const rowKey=(r,i)=>spec.rowKey?String(spec.rowKey(r)):String((spec.rows||[]).indexOf(r));
  const tr=(r)=>{
    const key=rowKey(r),exp=spec.expand?spec.expand(r):null,open=exp&&st.open.has(key);
    const cls=[r._cls||"",exp?"is-expandable":"",open?"is-open":""].filter(Boolean).join(" ");
    return `<tr data-rk="${esc(key)}"${cls?` class="${cls}"`:""}${exp?` aria-expanded="${!!open}"`:""}>${cols.map((c,ci)=>`<td class="dt-${dtAlign(c)}${c.sticky?" dt-sticky":""}${c.wrap?" dt-wrap":""}${c.type==="num"||c.type==="int"||c.type==="pct"||c.type==="sec"||c.type==="heat"||c.type==="bar"?" dt-n":""}"${dtCellStyle(c,r,ctx)}>${ci===0&&exp?icon("chevron-right","icon-sm dt-caret"):""}${dtCell(c,r,ctx)}</td>`).join("")}</tr>`+
      (open?`<tr class="dt-detail"><td colspan="${cols.length}">${exp}</td></tr>`:"");
  };
  let body;
  if(spec.groupBy){
    const order=[];const by=new Map();
    view.forEach(r=>{const g=spec.groupBy(r);if(!by.has(g)){by.set(g,[]);order.push(g)}by.get(g).push(r)});
    body=order.map(g=>{
      const rs=by.get(g),closed=st.closed.has(String(g));
      return `<tr class="dt-grouprow" data-g="${esc(g)}"><td colspan="${cols.length}"><button type="button" class="dt-gbtn" aria-expanded="${!closed}">${icon("chevron-right","icon-sm dt-caret")}${spec.groupLabel?spec.groupLabel(g,rs):esc(g)}</button></td></tr>`+
        (closed?"":rs.map(tr).join(""));
    }).join("");
  }else body=view.map(tr).join("");
  const tfoot=spec.totals?`<tfoot><tr>${cols.map((c,ci)=>{const v=ci===0?(spec.totals.label||"合计"):spec.totals.values&&spec.totals.values[c.key];
    return `<td class="dt-${dtAlign(c)}${c.sticky?" dt-sticky":""}">${ci===0?esc(v):v==null?"":(typeof v==="number"?numText(v,dtDigits(c)):v)}</td>`}).join("")}</tr></tfoot>`:"";
  const n=(spec.rows||[]).length;
  const showSearch=spec.search??n>12;
  const hideable=spec.columns.filter(c=>!c.sticky);
  const tools=`<div class="dt-tools">
      ${showSearch?`<label class="dt-search">${icon("search","icon-sm")}<input type="search" data-dt-q placeholder="搜索" value="${esc(st.q)}" aria-label="在表格里搜索"></label>`:""}
      ${hideable.length>2?`<details class="dropdown dt-cols"><summary class="btn btn-ghost btn-sm" title="选择显示哪些列">${icon("columns","icon-sm")}列</summary>
        <div class="dropdown-panel menu is-right">${hideable.map(c=>`<label class="option-row"><input type="checkbox" data-dt-col="${esc(c.key)}" ${st.hidden.has(c.key)?"":"checked"}><span class="grow">${esc([c.group,stripTags(c.label)].filter(Boolean).join(" · "))}</span></label>`).join("")}</div></details>`:""}
      <button type="button" class="btn btn-ghost btn-sm" data-dt-copy title="复制整张表（可以直接粘进 Excel）">${icon("copy","icon-sm")}复制</button>
      <button type="button" class="btn btn-ghost btn-sm" data-dt-csv title="导出为 CSV 文件">${icon("download","icon-sm")}CSV</button>
    </div>`;
  const pager=pages>1||(spec.pageSizes&&all.length>Math.min(...spec.pageSizes))?pagerHTML("dt",{page:st.page,pages,size,sizes:spec.pageSizes}):"";
  const count=all.length!==n?`显示 ${fmtInt(all.length)} / ${fmtInt(n)} 行`:`${fmtInt(n)} 行`;
  return `<div class="dt-bar">${spec.title?`<div class="dt-title">${spec.title}${spec.sub?`<span class="dt-sub">${spec.sub}</span>`:""}</div>`:""}${tools}</div>
    <div class="dt-scroll"${spec.maxH?` style="max-height:${spec.maxH}px"`:""}><table class="dt-table${spec.cls?" "+spec.cls:""}"><thead>${groupRow}<tr>${cols.map(th).join("")}</tr></thead>
      <tbody>${body||`<tr class="dt-empty"><td colspan="${cols.length}">${esc(spec.empty||(st.q?"没有匹配的行":"没有数据"))}</td></tr>`}</tbody>${tfoot}</table></div>
    <div class="dt-foot"><span>${count}${spec.note?` · ${spec.note}`:""}</span>${pager}</div>`;
}
function dataTable(spec){
  DT.specs.set(spec.id,spec);
  dtState(spec.id,spec);
  return `<div class="dt" data-dt="${esc(spec.id)}">${dtInner(spec)}</div>`;
}
function dtRefresh(id,keepFocus){
  const spec=DT.specs.get(id);if(!spec)return;
  const html=dtInner(spec);
  document.querySelectorAll(`[data-dt="${CSS.escape(id)}"]`).forEach(el=>{
    const q=keepFocus&&el.contains(document.activeElement)&&document.activeElement.matches("[data-dt-q]");
    const pos=q?document.activeElement.selectionStart:0;
    el.innerHTML=html;
    if(q){const inp=el.querySelector("[data-dt-q]");if(inp){inp.focus();try{inp.setSelectionRange(pos,pos)}catch(e){}}}
  });
}
function dtSort(id,key){
  const st=dtState(id),s=st.sort;
  st.sort=!s||s.key!==key?{key,dir:"desc"}:s.dir==="desc"?{key,dir:"asc"}:null;
  st.page=0;dtSave(id);dtRefresh(id);
}
/* 多张表合成一个 CSV: 表名一行, 表与表之间空一行 */
function tablesCSV(ids){
  return "﻿"+ids.map(id=>{const s=DT.specs.get(id);if(!s)return"";const m=dtMatrix(s);
    return [csvCell(stripTags(s.title||s.exportName||id))].concat([m.head,...m.rows].map(r=>r.map(csvCell).join(","))).join("\r\n")}).filter(Boolean).join("\r\n\r\n");
}
function tableIdsIn(root){return root?[...new Set([...root.querySelectorAll("[data-dt]")].map(x=>x.dataset.dt))]:[]}
function exportPageTables(page){
  const root={dash:"dashBody",cmp:"cmpBody",iq:"iqResult",gen:"genResult",tasks:"tasksBody",models:"modelsBody"}[page];
  const ids=tableIdsIn($(root));
  if(!ids.length){toast("这一页没有可以导出的表格","warning");return}
  downloadText(`${{dash:"速度测试",cmp:"速度对比",iq:"能力测试",gen:"代码生成",tasks:"任务集",models:"模型管理"}[page]}_全部表格.csv`,tablesCSV(ids));
  toast(`已导出 ${ids.length} 张表`,"success",2500);
}
async function copyText(text,what){
  try{await navigator.clipboard.writeText(text);toast(`已复制${what||""}，可以直接粘进 Excel`,"success",2500)}
  catch(e){toast("浏览器没有允许复制，请改用导出 CSV","error")}
}
document.addEventListener("click",e=>{
  const box=e.target.closest("[data-dt]");if(!box)return;
  const id=box.dataset.dt,spec=DT.specs.get(id);if(!spec)return;
  const th=e.target.closest("th.can-sort");
  if(th){dtSort(id,th.dataset.k);return}
  const pg=e.target.closest("[data-dt-page]");
  if(pg){dtGo(id,+pg.dataset.dtPage,box);return}
  const jb=e.target.closest("[data-dt-jumpbtn]");
  if(jb){const t=pagerTarget(jb.parentElement.querySelector("[data-dt-jump]"));if(t!=null)dtGo(id,t,box);return}
  if(e.target.closest("[data-dt-copy]")){copyText(toTSV(dtMatrix(spec)),"表格");return}
  if(e.target.closest("[data-dt-csv]")){downloadText(safeName(stripTags(spec.exportName||spec.title||id))+".csv",toCSV(dtMatrix(spec),stripTags(spec.title||"")));return}
  const g=e.target.closest(".dt-gbtn");
  if(g){const st=dtState(id),k=g.closest("tr").dataset.g;st.closed.has(k)?st.closed.delete(k):st.closed.add(k);dtRefresh(id);return}
  const row=e.target.closest("tr.is-expandable");
  if(row&&!e.target.closest("button,a,input,summary,label,select")){
    const st=dtState(id),k=row.dataset.rk;st.open.has(k)?st.open.delete(k):st.open.add(k);dtRefresh(id);
  }
});
document.addEventListener("keydown",e=>{
  const th=e.target.closest&&e.target.closest("[data-dt] th.can-sort");
  if(th&&(e.key==="Enter"||e.key===" ")){e.preventDefault();const id=th.closest("[data-dt]").dataset.dt;dtSort(id,th.dataset.k);
    const again=document.querySelector(`[data-dt="${CSS.escape(id)}"] th[data-k="${CSS.escape(th.dataset.k)}"]`);if(again)again.focus()}
});
let dtQT=null;
document.addEventListener("input",e=>{
  const q=e.target.closest&&e.target.closest("[data-dt-q]");if(!q)return;
  const id=q.closest("[data-dt]").dataset.dt;
  clearTimeout(dtQT);dtQT=setTimeout(()=>{const st=dtState(id);st.q=q.value;st.page=0;dtRefresh(id,true)},160);
});
/* 表格翻页: 滚回表格顶部(内部滚动区和整页), 焦点放回翻页器 */
function dtGo(id,p,box){
  const k=pagerFocusKey();
  dtState(id).page=p;dtRefresh(id);
  box.querySelector(".dt-scroll")?.scrollTo?.(0,0);
  scrollTopIntoView(box);
  pagerRefocus(box,k);
}
document.addEventListener("keydown",e=>{
  if(e.key!=="Enter"||!e.target.closest)return;
  const inp=e.target.closest("[data-dt-jump]");if(!inp)return;
  e.preventDefault();
  const box=inp.closest("[data-dt]"),t=pagerTarget(inp);if(box&&t!=null)dtGo(box.dataset.dt,t,box);
});
document.addEventListener("change",e=>{
  const sz=e.target.closest&&e.target.closest("[data-dt-size]");
  if(sz){const box=sz.closest("[data-dt]"),id=box.dataset.dt,spec=DT.specs.get(id),st=dtState(id);if(!spec)return;
    const first=st.page*dtPageSize(spec,st);st.size=+sz.value;st.page=Math.floor(first/dtPageSize(spec,st));dtSave(id);dtRefresh(id);
    box.querySelector("[data-dt-size]")?.focus();return}
  const c=e.target.closest&&e.target.closest("[data-dt-col]");if(!c)return;
  const id=c.closest("[data-dt]").dataset.dt,st=dtState(id);
  c.checked?st.hidden.delete(c.dataset.dtCol):st.hidden.add(c.dataset.dtCol);
  dtSave(id);dtRefresh(id);
  const dd=document.querySelector(`[data-dt="${CSS.escape(id)}"] .dt-cols`);if(dd)dd.open=true;
});
/* 矩阵(透视)表: 记录 → 行 × 列 → 值 */
function pivotRows(records,{row,col,value}){
  const rows=[],cols=[],map=new Map();
  records.forEach(r=>{
    const rk=typeof row==="function"?row(r):r[row],ck=typeof col==="function"?col(r):r[col];
    if(!map.has(rk)){map.set(rk,{_row:rk});rows.push(rk)}
    if(!cols.includes(ck))cols.push(ck);
    map.get(rk)["c_"+ck]=typeof value==="function"?value(r):r[value];
  });
  return{rows:rows.map(k=>map.get(k)),cols};
}
/* 对比表: 同一个键的 A/B 两行 → 一行里 A | B | 变化 三列一组 */
function compareRows(keys,runs,getRow,metrics){
  return keys.map(k=>{
    const out={_key:k};
    metrics.forEach(m=>{
      const vals=runs.map(x=>{const r=getRow(x,k);return r?m.get(r):null});
      vals.forEach((v,i)=>out[m.key+"_"+i]=v);
      if(runs.length>1)out[m.key+"_d"]=pctChange(vals[1],vals[0]);  /* A 比 B */
    });
    return out;
  });
}
function compareCols(runs,metrics){
  return metrics.flatMap(m=>[
    ...runs.map((x,i)=>({key:m.key+"_"+i,label:x.tag,group:m.label+(m.unit?`（${m.unit}）`:""),type:m.type||"num",digits:m.digits,tip:m.tip})),
    ...(runs.length>1?[{key:m.key+"_d",label:"A 比 B",group:m.label+(m.unit?`（${m.unit}）`:""),type:"delta",dir:m.dir??1}]:[])]);
}
/* ---------- 面板: 图表 | 表格 ---------- */
const VIEWMODE=Object.assign({dash:"chart",cmp:"chart",iq:"chart",gen:"chart"},lsGet("llm-bench-pro-viewmode"));
const PANEL_OVR=new Map();
function panelMode(id){return PANEL_OVR.get(id)||VIEWMODE[VIEW]||"chart"}
function segHTML(attr,cur,items){
  return `<span class="seg" role="group">${items.map(([v,label,ic])=>`<button type="button" class="seg-btn" ${attr}="${v}" aria-pressed="${v===cur}">${ic?icon(ic):""}${label}</button>`).join("")}</span>`;
}
/* 面板: chart=图表区 HTML(可含主表), tables=[spec|HTML], 两者都有时右上角可切换 */
function panel({id,title,desc="",jump,chart="",tables=[],tcols=2,tools="",foot=""}){
  const both=!!chart&&tables.length>0,mode=panelMode(id);
  const tbl=tables.map(t=>typeof t==="string"?t:dataTable(t));
  const multi=tbl.length>1;
  return `<section class="sec" id="${id}" data-jump="${esc(jump||stripTags(title))}" data-pv="${both?mode:(chart?"chart":"table")}">
    <div class="sec-head"><div class="sec-head-text"><h2 class="sec-title">${title}</h2>${desc?`<p class="sec-desc">${desc}</p>`:""}</div>
      <div class="sec-tools">${tools}${both?segHTML("data-pv-set",mode,[["chart","图表","chart"],["table","表格","table"]]):""}
        ${tables.some(t=>typeof t!=="string")?`<button type="button" class="btn btn-ghost btn-icon btn-sm" data-pv-export title="导出本节全部表格（CSV）" aria-label="导出本节全部表格">${icon("download")}</button>`:""}</div></div>
    ${chart?`<div class="pv-chart">${chart}</div>`:""}
    ${tbl.length?`<div class="pv-table"><div class="dt-grid${multi?" is-multi":""}" style="--tcols:${multi?tcols:1}">${tbl.join("")}</div></div>`:""}${foot}
  </section>`;
}
function resizeChartsIn(root){root.querySelectorAll(".chart").forEach(ch=>{if(ch._ec)try{ch._ec.resize()}catch(e){}})}
function setPanelMode(sec,mode){
  if(!sec.querySelector(".pv-chart")||!sec.querySelector(".pv-table"))return;
  sec.dataset.pv=mode;
  sec.querySelectorAll("[data-pv-set]").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.pvSet===mode)));
  if(mode==="chart")requestAnimationFrame(()=>resizeChartsIn(sec));
}
function applyViewMode(page,mode,persist){
  VIEWMODE[page]=mode;
  if(persist)lsSet("llm-bench-pro-viewmode",VIEWMODE);
  const root=$({dash:"dashBody",cmp:"cmpBody",iq:"iqResult",gen:"genResult",tasks:"tasksBody"}[page]);
  document.querySelectorAll(`[data-vm-page="${page}"] [data-vm]`).forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.vm===mode)));
  if(!root)return;
  root.querySelectorAll("section.sec[data-pv]").forEach(sec=>{PANEL_OVR.delete(sec.id);setPanelMode(sec,mode)});
}
document.addEventListener("click",e=>{
  const ps=e.target.closest("[data-pv-set]");
  if(ps){const sec=ps.closest("section.sec");PANEL_OVR.set(sec.id,ps.dataset.pvSet);setPanelMode(sec,ps.dataset.pvSet);return}
  const pe=e.target.closest("[data-pv-export]");
  if(pe){const sec=pe.closest("section.sec"),ids=tableIdsIn(sec);
    if(ids.length)downloadText(safeName(sec.dataset.jump||sec.id)+".csv",tablesCSV(ids));return}
  const vm=e.target.closest("[data-vm]");
  if(vm){applyViewMode(vm.closest("[data-vm-page]").dataset.vmPage,vm.dataset.vm,true);return}
});

/* ============================================================
   速度测试: 新建 / 列表 / 指标
   ============================================================ */
let RUNS={},RUNS_LOADED=false,perfPoll=null;
const FULL={};  /* 测试完整记录缓存(列表接口只返回摘要) */
let renderSeq=0,cmpSeq=0;
async function ensureRuns(ids){
  await Promise.all(ids.filter(id=>id&&!FULL[id]).map(async id=>{FULL[id]=fixLenLabels(await getJSON("/api/run?id="+encodeURIComponent(id)))}));
}
/* 输入长度的标签: 1.5 之前的速度测试按「每句 77.5 token」估算着拼长输入, 在新一代分词器上实际只有标称的 45% 左右。
   标签和实际长度差 10% 以上的档位改按实际长度显示(原标签留在 label_nominal); 图表、表格、结论和 A/B 是否可比都跟着按实际长度 */
function lenK(t){const k=t/1000;return (k<100?Math.round(k*10)/10:Math.round(k))+"K"}
function fixLenLabels(r){
  if(!r||r._len)return r;
  const moved=[],rag=[];
  (r.phases||[]).forEach(ph=>{
    if(ph.id==="scn_rag")(ph.points||[]).forEach(q=>{   /* 看资料回答: 实际输入和资料长度差 15% 以上(段落粒度粗些) */
      if(!q.ctx_tokens||!q.prompt_tokens_avg||Math.abs(q.prompt_tokens_avg/q.ctx_tokens-1)<=0.15)return;
      q.ctx_actual=Math.round(q.prompt_tokens_avg);
      rag.push({from:kLabel(q.ctx_tokens),to:lenK(q.ctx_actual)});
    });
    if(ph.id!=="prefill"&&ph.id!=="prefill_conc")return;
    (ph.points||[]).forEach(q=>{
      const m=/^(\d+(?:\.\d+)?)K$/.exec(q.label||"");
      if(!m||!q.in_tokens)return;
      const ratio=q.in_tokens/(+m[1]*1000);
      if(Math.abs(ratio-1)<=0.1)return;
      moved.push({from:q.label,to:lenK(q.in_tokens),ratio});
      q.label_nominal=q.label;q.label=lenK(q.in_tokens);
    });
  });
  r._len={moved,rag};
  return r;
}
/* 看资料回答: 一档的实际输入长度; 两次测试同一档的实际长度差 15% 以上(新旧算法)就不配对比较 */
function ragActual(q){return q&&(q.ctx_actual||q.prompt_tokens_avg||q.ctx_tokens)}
function ragPair(qa,qb){return !!(qa&&qb)&&Math.abs(ragActual(qa)/ragActual(qb)-1)<=0.15}
const perfLog=LogBox("runLog","perf");
const SUITE_NAME={quick:"快速",standard:"标准",full:"完整",custom:"自定义"};
const saveForm=bindFormMemory("llm-bench-pro-form",["fBase","fModel","fTag","fSuite","fConc","fMConc","fLens","fFw","fFwVer",
  "fScnConc","fScnRpw","fScnMt","fImgDir","fImgN","fReplaySel","fRpConc","fRpRates","fRpDur"]);
function suitePlaceholders(){
  const s=$("fSuite").value;
  $("fConc").placeholder={quick:"默认 1,4,8",standard:"默认 1,2,4,8,16",full:"默认 1,2,4,8,16,32,48,64"}[s]||"";
  $("fLens").placeholder={quick:"默认 1K、4K、8K",standard:"默认 1K–8K 共 8 档",full:"默认 1K–16K 共 8 档"}[s]||"";
}
/* 原生 details 下拉: 打开时测量, 右侧放不下则右对齐 */
function fitDropdown(dt){
  const panel=dt.querySelector(".dropdown-panel");if(!panel)return;
  panel.style.left="";panel.style.right="";
  const r=dt.getBoundingClientRect(),p=panel.getBoundingClientRect(),vw=document.documentElement.clientWidth;
  if(r.left+p.width>vw-12){panel.style.right="0";panel.style.left="auto"}
}
document.querySelectorAll("details.dropdown").forEach(dt=>dt.addEventListener("toggle",()=>{if(dt.open)fitDropdown(dt)}));
window.addEventListener("resize",()=>document.querySelectorAll("details.dropdown[open]").forEach(fitDropdown));

/* ---------- 模拟真实业务: 类型 / 条件参数 / 素材(任务集、图片) ---------- */
const SCN_TPL=[
  ["chat","对话问答","短回答和长回答混合的日常问答"],
  ["code","写代码","实现函数、类、脚本或修 bug"],
  ["json","提取成 JSON","把商品描述整理成标准 JSON，统计格式是否合法"],
  ["rag","看资料回答","给一段长资料再提问，要求注明出处；可选资料长度"],
  ["vision","看图回答","看图说出形状和颜色、读柱状图和饼图；默认用内置示例图片，也可以上传自己的图片"],
  ["custom","自定义任务集","用你导入的任务集（JSONL，每行一个请求）；在左侧「任务集」页面导入、逐行查看、下载模板"],
];
const RAG_CTX_OPTS=[[1500,"1.5K"],[4000,"4K"],[16000,"16K"]];
function scnChip(val,label,tip,checked){
  return `<label class="chip-check" title="${esc(tip)}"><input type="checkbox" value="${esc(val)}" ${checked?"checked":""}>${esc(label)}</label>`;
}
function renderScnChips(){
  const sel=new Set(lsGet("llm-bench-pro-scn").tasks||[]);
  $("scnChips").innerHTML=SCN_TPL.map(([id,name,tip])=>scnChip(id,name,tip,sel.has(id))).join("");
  const ctxSel=new Set(lsGet("llm-bench-pro-scn").rag_ctx||[4000]);
  $("ragCtxChips").innerHTML=RAG_CTX_OPTS.map(([v,l])=>scnChip(v,l,"资料约 "+l+" token",ctxSel.has(v))).join("");
}
function scnSelected(){return [...document.querySelectorAll("#scnChips input:checked")].map(x=>x.value)}
function scnSyncVisibility(){
  const sel=new Set(scnSelected());
  $("scnCommon").hidden=!sel.size;
  $("scnRagRow").hidden=!sel.has("rag");
  $("scnVisionRow").hidden=!sel.has("vision");
  $("scnCustomRow").hidden=!sel.has("custom");
  const st=lsGet("llm-bench-pro-scn");
  st.tasks=scnSelected();
  st.rag_ctx=[...document.querySelectorAll("#ragCtxChips input:checked")].map(x=>+x.value);
  lsSet("llm-bench-pro-scn",st);
}
["scnChips","ragCtxChips"].forEach(id=>$(id).addEventListener("change",scnSyncVisibility));
renderScnChips();
scnSyncVisibility();

/* 自定义任务集模板: 每种写法一两行, 每行的 meta.note 是说明(不会发给模型)。
   这段是严格 JSON: 测试直接读出来, 用 bench.py 的解析器逐行检查, 所以不要在里面写注释。
   带图片那一行的示例图是 224×224 的 PNG(vision_assets.Canvas 画的): 左边红色圆形、右边蓝色正方形 */
const TASK_TEMPLATE=/*TASK-TEMPLATE-BEGIN*/[
{"messages":[{"role":"user","content":"用两三句话解释什么是 KV cache。"}],"meta":{"note":"最简单的写法：只有一条用户消息；不写 params 时最多生成 4096 token"}},
{"messages":[{"role":"system","content":"你是简洁的技术助手，回答不超过 100 字。"},{"role":"user","content":"推理服务的首字延迟主要受哪些因素影响？"}],"params":{"max_tokens":256,"temperature":0.3},"meta":{"note":"带 system 提示，并限定这一行最多生成 256 token、temperature 为 0.3"}},
{"messages":[{"role":"system","content":"你是客服助手，回答礼貌、简短。"},{"role":"user","content":"我的订单还没发货。"},{"role":"assistant","content":"抱歉让您久等了，请提供订单号，我帮您查询。"},{"role":"user","content":"订单号是 20260928001。"}],"params":{"max_tokens":300},"meta":{"note":"多轮对话：assistant 是模型之前的回答，按时间顺序排列，最后一条是这次要回答的问题"}},
{"messages":[{"role":"user","content":"把这个地址整理成 JSON，字段为 province、city、street：浙江省杭州市西湖区文三路 90 号"}],"params":{"max_tokens":200,"temperature":0,"response_format":{"type":"json_object"}},"meta":{"note":"要求输出 JSON 对象（提示词里也要写明 JSON），会统计 JSON 合法率"}},
{"messages":[{"role":"system","content":"从商品描述里提取信息，只输出 JSON。"},{"role":"user","content":"无线蓝牙耳机，续航 30 小时，售价 199 元，有黑色和白色两种。"}],"params":{"max_tokens":300,"temperature":0,"response_format":{"type":"json_schema","json_schema":{"name":"product","schema":{"type":"object","properties":{"name":{"type":"string"},"price":{"type":"number"},"colors":{"type":"array","items":{"type":"string"}}},"required":["name","price","colors"]}}}},"meta":{"note":"按指定的 JSON Schema 输出：name 是随便起的名字，schema 规定字段；会统计 JSON 合法率"}},
{"messages":[{"role":"user","content":[{"type":"text","text":"图里有哪些形状？分别是什么颜色？"},{"type":"image_url","image_url":{"url":"data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAOAAAADgCAIAAACVT/22AAAC5klEQVR42u3d0Q0CMQxEQZqBxmibDigCWkDJKdjredoKnPlEx+0jFe7mBAJUAlSASoBKgApQCVABKgEqASpAJUAFqASoBKgAlQAVoBKgEqACVAJUgEqASoAKUAlQCVABKgEqQCVAJUAFqASoAJUAlQAVoBKgAlQCVAJUgEqAClAJUAlQASoBKgEqQCVABagEqASoAJUAFaASoFI+0Nfj8eO8N6C1RPIKaDOUsALajCamgFZ3SSqgbWhiCmgDmpgC2kMno4CWponpdKBddDI6DmgvmpjOAtpXJ6P5QLvrZDQZaIZORjOBJulkNA1onk5Gc4Cm6mQ0AWi2TkZ7A52g8xKj9+e79VoCnaNz3yiggAIK6GCdm0YBPQp0ps4do4ACCiig43UuGwX0EFA614wCCiig44FyuWwUUEABnQ2UyB2jgAIKKKAGaE2gLG4aBRRQQKcCpXDfKKCAAgqoAQoooIDSedoooIACCqgBCiiggAIKaARQ8q4yCiiggAJqgAIKKKCAAgoooIACCiigBiiggAIKKKCAAgoooIACCiiggAIKKKN+bgeoAQoooIACCiiggAJ6JVBGfbgBUEABBRRQQAEF9A9AGfUBW0ABBZRRf6IAKKCAAgoooIxepxNQQAEFlNFVnYACCiigjK7qBPQo0OFG1y4GKKCAAjre6PK5AD0NdKDRnVsBCiiggA42unkoQP8DdIjRj/oCjTdKUnugwUYxCgEaaZShKKBhRgEKBBpjlJ5YoAFG0QkH2tooNyOAdmRKzDigjYziMhRofaagAFrXKCWAFmXKB6BFmZIBaEWpQABalCkKgJbD6vkBreXVewMqASpAJUAlQAWoBKgAlQCVABWgEqACVAJUAlSASoBKgApQCVABKgEqASpAJUAFqASoBKgAlQAVoBKgEqACVAJUgEqASoAKUAlQCVABKgEqQCVAJUAFqASoAJUAlQAVoBKgAlQCVAJUgEqAClAJUAlQASod7Avc2fHFfVzcpAAAAABJRU5ErkJggg=="}}]}],"params":{"max_tokens":300},"meta":{"note":"带图片（模型要能看图）：content 写成列表，图片用 base64 data URL，每张至少 28×28 像素；这张示例图 224×224，左边红色圆形、右边蓝色正方形"}},
{"messages":[{"role":"user","content":"用一句话说明大模型推理时为什么要做批处理。"}],"params":{"max_tokens":512,"enable_thinking":false},"meta":{"note":"关闭思考（Qwen3 等有思考开关的模型），会转成 chat_template_kwargs.enable_thinking；服务不认这个参数时删掉即可"}}
]/*TASK-TEMPLATE-END*/;
function downloadTaskTemplate(){
  downloadText("任务集模板.jsonl",TASK_TEMPLATE.map(x=>JSON.stringify(x)).join("\n")+"\n","application/x-ndjson;charset=utf-8");
}
$("btnTaskImport").addEventListener("click",()=>$("fTaskUpload").click());

/* 素材列表(任务集带可用行数; 图片包带张数、尺寸范围、有几张不能用)与上传后的检查结果 */
let SCN_ASSETS={tasks:[],images:[],builtin_images:null},IMG_REPORT=null,TASK_REPORT=null;
function fmtBytes(n){return n==null||!isFinite(n)?"—":n<1024?n+" B":n<1048576?Math.round(n/1024)+" KB":(n/1048576).toFixed(1)+" MB"}
function hintList(items){return items&&items.length?`<ul class="hint-list">${items.map(x=>`<li>${esc(x)}</li>`).join("")}</ul>`:""}
function imgPackText(p){
  return ["图片包 "+p.image_id.slice(4,12),p.count+" 张",p.dims||"尺寸读不出",fmtBytes(p.size),shortTime(p.mtime),
    p.too_small?`有 ${p.too_small} 张太小，会被模型拒绝`:"",p.broken?`有 ${p.broken} 张不能用`:""].filter(Boolean).join(" · ");
}
/* 新建面板里任务集的选项: 名称 · 可用条数(旧版本导入、还没有名称的显示 id) */
function taskSetText(p){
  return [p.name||p.file_id,`${fmtInt(p.lines)} 条可用${p.total>p.lines?`（共 ${fmtInt(p.total)} 行）`:""}`].join(" · ");
}
async function loadScenarioAssets(keepImg,keepTask){
  try{
    const d=await getJSON("/api/scenario-list");
    SCN_ASSETS=d;
    const st=lsGet("llm-bench-pro-scn"),b=d.builtin_images||{count:0,width:0,height:0};
    const img=$("fImgSel"),want1=keepImg||st.img||img.value;
    img.innerHTML=`<option value="builtin">内置示例图片（${b.count} 张） · ${b.width}×${b.height}</option>`+
      d.images.map(p=>`<option value="${esc(p.image_id)}">${esc(imgPackText(p))}</option>`).join("")+
      `<option value="dir">服务器上的文件夹…</option>`;
    img.value=[...img.options].some(o=>o.value===want1)?want1:"builtin";
    const tsk=$("fTaskSel"),want2=keepTask||st.task||tsk.value;
    tsk.innerHTML=`<option value="">未选择</option>`+d.tasks.map(p=>`<option value="${esc(p.file_id)}">${esc(taskSetText(p))}</option>`).join("");
    if(want2&&d.tasks.find(p=>p.file_id===want2))tsk.value=want2;
    scnAssetRemember();
    scnAssetSync();
  }catch(e){/* 服务不可达时保持空列表 */}
}
/* 记住选的图片来源和任务集(列表加载完、或用户改了选择时才记, 页面刚打开时不能用默认值覆盖) */
function scnAssetRemember(){
  const st=lsGet("llm-bench-pro-scn");
  st.img=$("fImgSel").value;st.task=$("fTaskSel").value;lsSet("llm-bench-pro-scn",st);
}
/* 选择变化: 图片来源的说明; 选中的图片包里有不能用的图时提前提示(刚上传的检查结果优先显示) */
function scnAssetSync(){
  const v=$("fImgSel").value,t=$("fTaskSel").value;
  $("fImgDirField").hidden=v!=="dir";
  const b=SCN_ASSETS.builtin_images,p=(SCN_ASSETS.images||[]).find(x=>x.image_id===v);
  $("fImgSrcHelp").textContent=v==="builtin"?(b?`内置 ${b.count} 张 ${b.width}×${b.height} 的图：${(b.names||[]).join("、")}。不用上传；每张图配的问题只问图里有的东西，比如哪根柱子最高`:"")
    :v==="dir"?"用运行本服务的机器上的图片文件夹，在下面填路径":p?`上传的图片包：${p.count} 张${p.dims?"，尺寸 "+p.dims:""}`:"";
  const ib=$("fImgCheck");
  if(IMG_REPORT&&IMG_REPORT.id===v){ib.innerHTML=IMG_REPORT.html;ib.hidden=false}
  else if(p&&p.usable<p.count){
    IMG_REPORT=null;ib.hidden=false;
    ib.innerHTML=alertBox(p.usable?"warn":"bad",`<b>${p.usable?`这个图片包里有 ${p.count-p.usable} 张不能用，测试时会跳过：`:"这个图片包里没有能用的图片，请重新上传，或改用内置示例图片："}</b>`+hintList(p.problems));
  }else{IMG_REPORT=null;ib.hidden=true;ib.innerHTML=""}
  const tb=$("fTaskCheck");
  if(TASK_REPORT&&TASK_REPORT.id===t){tb.innerHTML=TASK_REPORT.html;tb.hidden=false}
  else{TASK_REPORT=null;tb.hidden=true;tb.innerHTML=""}
}
["fImgSel","fTaskSel"].forEach(id=>$(id).addEventListener("change",()=>{scnAssetRemember();scnAssetSync()}));
scnAssetSync();
function readFileBase64(f){
  return new Promise((res,rej)=>{const r=new FileReader();r.onload=()=>res(String(r.result).split(",",2)[1]||"");r.onerror=()=>rej(new Error("读取失败"));r.readAsDataURL(f)});
}
/* 图片上传后的检查结果: 没收的逐张说原因; 收下但要注意的(偏小、扩展名不对)单独列出 */
function imgReportHtml(d){
  const files=d.files||[],bad=files.filter(f=>!f.ok),warn=files.filter(f=>f.ok&&f.level==="warn");
  const list=fs=>hintList(fs.slice(0,10).map(f=>`${f.name}：${f.msg}`).concat(fs.length>10?[`……还有 ${fs.length-10} 张`]:[]));
  const head=d.ok?`已收进图片包 ${d.count} 张（${[d.dims,fmtBytes(d.size)].filter(Boolean).join("，")}）`+(bad.length?`，${bad.length} 张没收：`:warn.length?"":"，全部可以用。")
    :files.length?"没有能用的图片，这次没有上传：":(d.error||"上传失败");
  return alertBox(!d.ok?"bad":bad.length||warn.length?"warn":"good",`<b>${esc(head)}</b>${list(bad)}`+
    (warn.length?`<div class="upcheck-h">收下了，但要注意：</div>${list(warn)}`:""));
}
const IMG_MAX_BYTES=20*1024*1024,IMG_UPLOAD_MAX=11*1024*1024;  /* 单张上限; 一次上传的总量(base64 后约大三分之一, 服务一次最多收 16 MB) */
$("fImgUpload").addEventListener("change",async e=>{
  const files=[...e.target.files];
  e.target.value="";
  if(!files.length)return;
  const send=files.filter(f=>f.size<=IMG_MAX_BYTES);
  const local=files.filter(f=>f.size>IMG_MAX_BYTES).map(f=>({name:f.name,ok:false,level:"bad",msg:`有 ${fmtBytes(f.size)}，超过单张 20 MB 的上限`}));
  const total=send.reduce((s,f)=>s+f.size,0);
  const show=d=>{IMG_REPORT={id:d.ok?d.image_id:$("fImgSel").value,html:imgReportHtml(d)};scnAssetSync()};
  if(total>IMG_UPLOAD_MAX){show({ok:false,files:[],error:`这次选的图片一共 ${fmtBytes(total)}，超过一次上传的上限 11 MB（上传时会编码变大约三分之一，服务一次最多收 16 MB）。请压缩图片、少选几张，或者把图片放到服务器上，选「服务器上的文件夹」`});return}
  if(!send.length){show({ok:false,files:local});return}
  msg("probeOut","info","正在上传并检查 "+send.length+" 张图片…");
  try{
    const payload=await Promise.all(send.map(async f=>({name:f.name,data:await readFileBase64(f)})));
    const d=await postJSON("/api/scenario-upload",{kind:"images",files:payload});
    d.files=local.concat(d.files||[]);
    if(d.ok)await loadScenarioAssets(d.image_id);
    show(d);
    const n=d.files.filter(f=>!f.ok).length;
    msg("probeOut",d.ok?"success":"error",d.ok?`已上传图片 ${d.count} 张${n?`，${n} 张没收（原因见图片来源下方）`:""}`:"上传失败："+(d.error||"没有能用的图片"));
  }catch(err){msg("probeOut","error",err.message)}
});
/* 任务集导入后的检查结果: 共几行、可用几行、带 response_format / 带图片的各几条, 有问题的行给出行号和原因;
   内容完全相同的已经导入过时说明它叫什么(不重复保存) */
function taskReportHtml(d,name){
  const c=d.check;
  if(!c)return alertBox("bad",`<b>${esc(d.error||"导入失败")}</b>`);
  const n=c.total-c.valid,who=d.ok&&d.name?`「${d.name}」`:` ${name}`;
  const rest=n?`共 ${c.total} 行，可用 ${c.valid} 行，${n} 行有问题（测试时会跳过）`:`共 ${c.total} 行，全部可用`;
  const head=!d.ok?`${name} 没有导入：共 ${c.total} 行，没有一行能用`
    :d.exists?`这个任务集已经导入过（名称：${d.name}），没有重复保存：${rest}`:`已导入${who}：${rest}`;
  const items=c.problems.map(x=>`第 ${x.line} 行：${x.reason}`).concat(n>c.problems.length?[`……另外还有 ${n-c.problems.length} 行有问题`]:[]);
  const warns=c.warnings.map(x=>`第 ${x.line} 行：${x.reason}`).concat(c.warning_count>c.warnings.length?[`……另外还有 ${c.warning_count-c.warnings.length} 条提醒`]:[]);
  return alertBox(!d.ok?"bad":n||warns.length?"warn":"good",`<b>${esc(head)}</b>`+
    (d.ok?`<div class="upcheck-sub">带 response_format ${c.json} 条（会统计 JSON 是否合法） · 带图片 ${c.image} 条</div>`:"")+
    (c.hint?`<div>${esc(c.hint)}</div>`:"")+
    (items.length?`<div class="upcheck-h">有问题的行${c.problems.length<n?`（只列前 ${c.problems.length} 条）`:""}：</div>${hintList(items)}`:"")+
    (warns.length?`<div class="upcheck-h">提醒（这些行照常发送）：</div>${hintList(warns)}`:""));
}
/* 服务一次最多收 16 MB 的请求(超出的部分会被截掉); 文件里的引号、换行转成上传格式后会变长, 所以按请求体算 */
const UPLOAD_BODY_MAX=16*1024*1024-64*1024;
$("fTaskUpload").addEventListener("change",async e=>{
  const f=e.target.files[0];
  e.target.value="";
  if(!f)return;
  const show=d=>{TASK_REPORT={id:d.ok?d.file_id:$("fTaskSel").value,html:taskReportHtml(d,f.name)};scnAssetSync()};
  try{
    const body={kind:"tasks",name:f.name,content:await f.text()};
    if(new Blob([JSON.stringify(body)]).size>UPLOAD_BODY_MAX){show({ok:false,error:`${f.name} 太大：上传时超过服务一次最多收的 16 MB，请拆成几个小文件，或放到服务器上用命令行 --custom-file 引用`});return}
    msg("probeOut","info","正在导入并检查任务集 "+f.name+"…");
    const d=await postJSON("/api/scenario-upload",body);
    if(d.ok){await loadScenarioAssets(null,d.file_id);tsInvalidate(d.file_id)}
    show(d);
    msg("probeOut",d.ok?"success":"error",!d.ok?"导入失败："+d.error:d.exists?`这个任务集已经导入过（名称：${d.name}），已选中它`
      :`已导入任务集「${d.name}」：${fmtInt(d.lines)} 条可用${d.bad_lines?`，${d.bad_lines} 行有问题（见任务集下方的检查结果）`:""}`);
  }catch(err){msg("probeOut","error","读取文件失败："+err.message)}
});
$("fSuite").addEventListener("change",suitePlaceholders);
suitePlaceholders();

async function probe(){
  if(!$("fBase").value.trim()){msg("probeOut","error","请先填写服务地址");$("fBase").focus();return}
  const btn=$("btnProbe");setBusy(btn,true);msg("probeOut","info","正在连接…");
  try{
    const d=await postJSON("/api/probe",{base:$("fBase").value,api_key:$("fKey").value});
    if(!d.ok){const f=mdFailText(d);msg("probeOut","error",d.code?`连不上：${f.short}。${f.long}`:"连不上："+d.error);return}
    $("modelList").innerHTML=d.models.map(m=>`<option value="${esc(m.id)}">${m.max_model_len?"最长上下文 "+Math.round(m.max_model_len/1024)+"K":""}</option>`).join("");
    if(d.models.length&&!$("fModel").value)$("fModel").value=d.models[0].id;
    if(!$("fFw").value&&d.framework)$("fFw").value=d.framework;
    if(!$("fFwVer").value&&d.fw_version)$("fFwVer").value=d.fw_version;
    msg("probeOut","success",`连接成功 · 响应 ${d.latency_ms} 毫秒 · 可用模型 ${d.count} 个${d.framework?" · "+d.framework+(d.fw_version?" "+d.fw_version:""):""}`);
    saveForm();
  }finally{setBusy(btn,false)}
}
async function start(){
  const model=$("fModel").value.trim();
  if(!model){msg("probeOut","error","请填写模型名称");$("fModel").focus();return}
  const scen={};
  const tasks=scnSelected();
  if(tasks.length){
    scen.tasks=tasks;
    if($("fScnConc").value.trim())scen.conc=$("fScnConc").value.trim();
    scen.requests_per_worker=parseInt($("fScnRpw").value)||3;
    if($("fScnMt").value)scen.max_tokens=parseInt($("fScnMt").value);
    const ragCtx=[...document.querySelectorAll("#ragCtxChips input:checked")].map(x=>+x.value);
    if(tasks.includes("rag")&&ragCtx.length)scen.rag_ctx=ragCtx;
    if(tasks.includes("vision")){
      const v=$("fImgSel").value,n=parseInt($("fImgN").value)||1,dir=$("fImgDir").value.trim();
      if(v==="dir"&&!dir){msg("probeOut","error","请填写服务器上的图片文件夹，或换成内置示例图片");$("fImgDir").focus();return}
      scen.vision_src=v==="dir"?{dir,images:n}:v&&v!=="builtin"?{image_id:v,images:n}:{builtin:true,images:n};
    }
    if(tasks.includes("custom")&&$("fTaskSel").value)scen.custom_file_id=$("fTaskSel").value;
  }
  const replay={};
  const rid=$("fReplaySel").value;
  if(rid){
    replay.file_id=rid;
    if($("fRpConc").value.trim())replay.closed={conc:$("fRpConc").value.trim()};
    if($("fRpRates").value.trim())replay.open={rates:$("fRpRates").value.trim(),duration_s:parseInt($("fRpDur").value)||60};
  }
  const body={base:$("fBase").value,api_key:$("fKey").value,model,suite:$("fSuite").value,tag:$("fTag").value,
    metrics:$("fMetrics").checked,conc_ladder:$("fConc").value,matrix_conc:$("fMConc").value,lens:$("fLens").value,
    framework:$("fFw").value,fw_version:$("fFwVer").value,fixed_output:$("fFixed").checked,
    scenarios:Object.keys(scen).length?{...scen,replay:Object.keys(replay).length?replay:undefined}:undefined};
  const d=await postWithConflict("/api/start",body);
  if(!d)return;
  if(!d.ok){msg("probeOut","error",d.error);return}
  msg("probeOut","",null);
  watchPerf("进行中 · "+model);
}
function watchPerf(title){
  $("btnStart").disabled=true;
  perfLog.start(title);
  clearInterval(perfPoll);
  perfPoll=pollStatus("/api/status",perfLog,{onDone:()=>{$("btnStart").disabled=false;refresh(true)}});
}

/* ---------- 回放文件: 列表 / 上传 ---------- */
async function loadReplayFiles(keep){
  try{
    const d=await getJSON("/api/replay-list");
    const sel=$("fReplaySel");
    sel.innerHTML=`<option value="">不回放</option>`+d.files.map(f=>
      `<option value="${esc(f.file_id)}">${esc(f.file_id.slice(7,15))} · ${(f.size/1048576).toFixed(1)} MB · ${shortTime(f.mtime)}</option>`).join("");
    if(keep&&d.files.find(f=>f.file_id===keep))sel.value=keep;
  }catch(e){/* 服务不可达时保持空列表 */}
}
$("fReplayFile").addEventListener("change",async e=>{
  const f=e.target.files[0];
  e.target.value="";
  if(!f)return;
  const tooBig=`${f.name} 太大：请放到运行服务的机器上，用命令行 --replay-file 引用`;
  if(f.size>15*1024*1024){msg("probeOut","error",tooBig+"（文件超过 15 MB）");return}
  try{
    const body={name:f.name,content:await f.text()};
    if(new Blob([JSON.stringify(body)]).size>UPLOAD_BODY_MAX){msg("probeOut","error",tooBig+"（上传时超过服务一次最多收的 16 MB）");return}
    msg("probeOut","info","正在上传并检查 "+f.name+"…");
    const d=await postJSON("/api/replay-upload",body);
    const p=d.check&&d.check.problems[0],first=p?`第 ${p.line} 行：${p.reason}`:"";
    if(!d.ok){msg("probeOut","error","上传失败："+d.error+(first?`（${first}）`:""));return}
    await loadReplayFiles(d.file_id);
    msg("probeOut","success",`已上传 ${f.name}：${fmtInt(d.lines)} 条可用请求${d.bad_lines?`（${d.bad_lines} 行有问题，回放时跳过${first?`，比如${first}`:""}）`:""}`);
  }catch(err){msg("probeOut","error","读取文件失败："+err.message)}
});

/* ---------- 新建面板底部的「这次要测什么」 ---------- */
function optText(id){const s=$(id);const o=s&&s.options[s.selectedIndex];return o?o.textContent:""}
function launcherSummary(){
  const box=$("launcherSum");if(!box)return;
  const scn=scnSelected().map(k=>SCN_LABEL[k]||k),rp=$("fReplaySel").value;
  box.innerHTML=`${icon("list-checks","icon-sm")}<span>这次将测：<b>${esc(optText("fSuite"))}</b>${scn.length?` · 模拟业务 ${scn.length} 类（${esc(scn.join("、"))}）`:""}${rp?" · 回放真实请求":""}${$("fFixed").checked?"":" · 输出长度不固定"}</span>`;
}
function iqLauncherSummary(){
  const box=$("iqLauncherSum");if(!box)return;
  const b=IQ_BANKS.find(x=>x.bank_id===$("iqBank").value),per=parseInt($("iqTier").value)||0;
  const n=b?(b.subjects||[]).reduce((t,s)=>t+(per?Math.min(per,s.n):s.n),0):null;
  box.innerHTML=`${icon("list-checks","icon-sm")}<span>这次将考：${n!=null?`<b>${fmtInt(n)}</b> 题（${b.subjects.length} 个科目）`:"先选择题集"} · ${esc(optText("iqTier").split("，")[0])} · ${$("iqThink").checked?"思考模式":"不思考"} · 同时答 ${esc($("iqConc").value||"8")} 题</span>`;
}
function genLauncherSummary(){
  const box=$("genLauncherSum");if(!box)return;
  const n=selectedTasks().length,judge=$("genJudgeBase").value.trim()&&$("genJudgeModel").value.trim();
  box.innerHTML=`${icon("list-checks","icon-sm")}<span>这次将写：<b>${n}</b> 道题 · 同时写 ${esc($("genConc").value||"4")} 题 · ${$("genThink").checked?"思考模式":"不思考"}${judge?" · AI 看图打分":""}</span>`;
}
[["launcher",launcherSummary],["iqLauncher",iqLauncherSummary],["genLauncher",genLauncherSummary]].forEach(([id,f])=>{
  const el=$(id);if(!el)return;el.addEventListener("input",f);el.addEventListener("change",f);
});

/* ---------- 导出离线报告 ---------- */
async function refresh(focusNew){
  status("加载中…");
  if(!RUNS_LOADED)$("dashEmpty").innerHTML=skeletonPage();
  try{
    const list=await getJSON("/api/results?summary=1");
    if(!SERVER.version)setConn(true,"服务已连接");
    const prev=new Set(Object.keys(RUNS));
    RUNS={};list.forEach(r=>RUNS[r.run_id]=r);
    Object.keys(FULL).forEach(id=>{const m=RUNS[id];  /* 已删除或状态变化的测试重新加载详情 */
      if(!m||m.status!==FULL[id].status||m.finished_utc!==FULL[id].finished_utc)delete FULL[id]});
    RUNS_LOADED=true;
    const names=Object.keys(RUNS).sort().reverse();
    const fresh=focusNew?names.find(n=>!prev.has(n)):null;
    const opts=(keep)=>names.map(n=>`<option value="${esc(n)}" ${n===keep?"selected":""}>${esc(label(RUNS[n]))}</option>`).join("");
    const keepA=fresh||(RUNS[$("runA").value]?$("runA").value:names[0]);
    const keepB=RUNS[$("runB").value]?$("runB").value:"";
    $("runA").innerHTML=opts(keepA);
    $("runB").innerHTML=`<option value="">不对比</option>`+opts(keepB);
    const cA=RUNS[$("cmpA").value]?$("cmpA").value:names[0],cB=RUNS[$("cmpB").value]?$("cmpB").value:(names[1]||"");
    $("cmpA").innerHTML=opts(cA);
    $("cmpB").innerHTML=`<option value="">选择测试 B</option>`+opts(cB);
    status(names.length?`共 ${names.length} 次测试`:"");
    if(!names.length&&VIEW==="dash")toggleLauncher("launcher",true);
    if(VIEW==="dash"||VIEW==="cmp")redrawVisible();
  }catch(e){
    setConn(false,"服务未连接");
    status("");
    $("dashEmpty").innerHTML=emptyState("连不上后端服务","请确认 python run.py 正在运行（"+e.message+"）",{iconName:"alert"});
    $("dashBody").hidden=true;
  }
}
function runFw(r){return r.framework&&r.framework.name?`${r.framework.name}${r.framework.version?" "+r.framework.version:""}`:""}
function label(r){
  return [r.model||"?",runFw(r),SUITE_NAME[r.suite]||r.suite,r.tag||"",r.status&&r.status!=="done"?STATUS_NAME[r.status]||r.status:"",shortTime(r.started_utc)].filter(Boolean).join(" · ");
}
function status(s){$("status").textContent=s}
function phase(run,id){return run&&(run.phases||[]).find(p=>p.id===id)}
function hostOf(url){return String(url||"").replace(/https?:\/\//,"").replace(/\/v1\/chat\/completions$/,"")}

/* 指标提取: 指标块 / 对比 / 差异表共用; dir=1 越高越好, -1 越低越好 */
function perfCtx(r){
  const dp=phase(r,"decode"),pp=phase(r,"prefill"),cp=phase(r,"concurrency"),pcp=phase(r,"prefill_conc");
  const rpp=phase(r,"replay"),olp=phase(r,"openloop");
  let ok=0,tot=0;(cp?cp.points:[]).forEach(p=>{ok+=p.ok;tot+=p.ok+p.fail});
  const scn=(r.phases||[]).filter(p=>(p.id||"").startsWith("scn_"));
  let jok=0,jtot=0,scnLast=null;
  scn.forEach(p=>(p.points||[]).forEach(pt=>{
    jok+=pt.json_ok||0;jtot+=pt.json_total||0;
    if(pt.ctx_tokens==null&&(!scnLast||(pt.conc||0)>(scnLast.conc||0)))scnLast=pt;  // 非资料问答场景的最高并发点
  }));
  const cpts=cp?[...cp.points].sort((x,y)=>x.conc-y.conc):[];
  return{
    zh:dp&&dp.cases.find(c=>c.lang==="zh"),en:dp&&dp.cases.find(c=>c.lang==="en"),
    peak:cpts.length?cpts.reduce((m,p)=>p.agg_tps>m.agg_tps?p:m):null,
    c1:cpts.find(p=>p.conc===1)||cpts[0]||null,
    pLast:pp&&pp.points.length?pp.points[pp.points.length-1]:null,
    cLast:cpts.length?cpts[cpts.length-1]:null,
    pcp,s:pcp&&pcp.summary,succ:tot?100*ok/tot:null,fails:tot-ok,
    scnLast,jsonRate:jtot?100*jok/jtot:null,
    rpLast:rpp&&rpp.points.length?rpp.points[rpp.points.length-1]:null,
    olLast:olp&&olp.points.length?olp.points[olp.points.length-1]:null,
    olMax:olp&&olp.points.length?Math.max(...olp.points.map(p=>p.max_inflight||0)):null};
}
/* 长输入并发这几项是整个长度阶梯的汇总: 阶梯的长度范围或同时请求数不同, 两次测试就不可比 */
function ladderRef(m){const p=m.pcp,q=p&&p.points;return q&&q.length?`${q[0].label}–${q[q.length-1].label}、同时 ${p.conc} 个请求`:null}
const PERF_METRICS=[
  {key:"zh",label:()=>"单个请求生成速度 · 中文",term:"decode",unit:"token/秒",dir:1,val:m=>m.zh&&m.zh.decode_tps_med,
    sub:m=>m.zh?`每次写 ${m.zh.out_tokens} token · 出字间隔 ${fmt(m.zh.itl_p50_ms_med)} 毫秒`:""},
  {key:"en",label:()=>"单个请求生成速度 · 英文",term:"decode",unit:"token/秒",dir:1,val:m=>m.en&&m.en.decode_tps_med,
    sub:m=>m.en?`每次写 ${m.en.out_tokens} token · 出字间隔 ${fmt(m.en.itl_p50_ms_med)} 毫秒`:""},
  {key:"peak",label:()=>"最高总生成速度",term:"agg",unit:"token/秒",dir:1,val:m=>m.peak&&m.peak.agg_tps,
    sub:m=>m.peak?`同时 ${m.peak.conc} 个请求时${m.c1&&m.c1.agg_tps&&m.peak.conc!==m.c1.conc?`，是 1 个请求时的 ${fmt(m.peak.agg_tps/m.c1.agg_tps,1)} 倍`:""}`:""},
  {key:"ttft",label:()=>"首字等待 · 请求最多时（较慢）",term:"ttft",unit:"秒",dir:-1,digits:2,val:m=>m.cLast&&m.cLast.ttft_p95_s,ref:m=>m.cLast&&m.cLast.conc,
    sub:m=>m.cLast?`同时 ${m.cLast.conc} 个请求 · 一般 ${fmtSec(m.cLast.ttft_p50_s)} 秒`:""},
  {key:"pmax",label:m=>`读入速度 · 输入 ${m.pLast?m.pLast.label:"最长"}`,term:"prefill",unit:"token/秒",dir:1,digits:0,val:m=>m.pLast&&m.pLast.prefill_tps_med,ref:m=>m.pLast&&m.pLast.label,
    sub:m=>m.pLast?`首字等待 ${fmtSec(m.pLast.ttft_med_s)} 秒`:""},
  {key:"mpre",label:m=>`长输入同时 ${m.pcp?m.pcp.conc:"多"} 个请求 · 平均读入速度`,term:"prefill",unit:"token/秒",dir:1,digits:0,val:m=>m.s&&m.s.prefill_avg,ref:ladderRef,
    sub:m=>m.s?`范围 ${fmtInt(m.s.prefill_min)}–${fmtInt(m.s.prefill_max)}`:""},
  {key:"mdec",label:m=>`长输入同时 ${m.pcp?m.pcp.conc:"多"} 个请求 · 平均总生成速度`,term:"agg",unit:"token/秒",dir:1,val:m=>m.s&&m.s.decode_avg,ref:ladderRef,
    sub:m=>m.s?`单个请求一般 ${fmt(m.s.per_stream_decode_p50)} · 较慢 ${fmt(m.s.per_stream_decode_p95)}`:""},
  {key:"succ",label:()=>"请求成功率",unit:"%",dir:1,val:m=>m.succ,sub:m=>m.fails?`失败 ${m.fails} 个`:"同时请求测试中全部成功"},
];
const CMP_EXTRA=[
  {key:"itl",label:()=>"出字间隔 · 英文（一般）",term:"itl",unit:"毫秒",dir:-1,val:m=>m.en&&m.en.itl_p50_ms_med},
  {key:"burst",label:()=>"每次返回的 token 数 · 中文",term:"burst",unit:"个",dir:1,digits:2,val:m=>m.zh&&m.zh.spec_burst_med},
  {key:"ttftmax",label:m=>`首字等待 · 输入 ${m.pLast?m.pLast.label:"最长"}`,term:"ttft",unit:"秒",dir:-1,digits:2,val:m=>m.pLast&&m.pLast.ttft_med_s,ref:m=>m.pLast&&m.pLast.label},
  {key:"p50",label:()=>"长输入时单个请求生成速度（一般）",term:"per",unit:"token/秒",dir:1,val:m=>m.s&&m.s.per_stream_decode_p50,ref:ladderRef},
  {key:"scnreq",label:()=>"模拟业务 · 每秒完成请求数",term:"rps",unit:"个/秒",dir:1,digits:2,val:m=>m.scnLast&&m.scnLast.req_s,ref:m=>m.scnLast&&m.scnLast.conc,
    sub:m=>m.scnLast?`同时 ${m.scnLast.conc} 个请求${m.jsonRate!=null?" · JSON 合格 "+fmt(m.jsonRate,0)+"%":""}`:""},
  {key:"rps",label:()=>"回放真实请求 · 每秒完成请求数",term:"rps",unit:"个/秒",dir:1,digits:2,val:m=>m.rpLast&&m.rpLast.req_s,ref:m=>m.rpLast&&m.rpLast.conc,
    sub:m=>m.rpLast?`同时 ${m.rpLast.conc} 个 · 最多积压 ${fmtInt(m.rpLast.max_inflight)} 个`:""},
  {key:"inf",label:m=>`按固定速率发送 · 最多积压${m.olLast?"（"+m.olLast.rate+" 个/秒）":""}`,term:"inflight",unit:"个",dir:-1,digits:0,val:m=>m.olMax,ref:m=>m.olLast&&m.olLast.rate,
    sub:m=>m.olLast?`实际完成 ${fmt(m.olLast.completed_rps,2)} / 目标 ${m.olLast.rate} 个/秒`:""},
];
/* 两次测试的参照档位是否一致(例如"请求最多时"一个是 64 个、一个是 16 个就不可比) */
/* 参照档位的大白话, 例如"同时 16 个请求"、"输入 16K" */
function refText(k,m){
  try{const r=k.ref(m);if(r==null)return "";
    return {ttft:`同时 ${r} 个请求`,pmax:`输入 ${r}`,ttftmax:`输入 ${r}`,mpre:`输入 ${r}`,mdec:`输入 ${r}`,p50:`输入 ${r}`,
      scnreq:`同时 ${r} 个请求`,rps:`同时 ${r} 个请求`,inf:`${r} 个/秒`}[k.key]||String(r)}
  catch(e){return ""}
}
function sameRef(k,ma,mb){if(!k.ref)return true;try{return k.ref(ma)===k.ref(mb)}catch(e){return false}}
function safeVal(f,m){try{const v=f(m);return v==null||!isFinite(v)?null:v}catch(e){return null}}
function safeSub(k,m){try{return k.sub?k.sub(m):""}catch(e){return""}}
function metricLabel(k,m){try{return k.label(m)}catch(e){return k.key}}
function metricVal(k,v){const d=k.digits??1;return v==null?"—":(k.unit==="%"?fmt(v,d):(d===0?fmtInt(v):fmt(v,d)))}

/* ============================================================
   速度测试: 结果页 (结论 → 指标 → 各章节图表, 每节可展开具体数字)
   ============================================================ */
/* 自动识别值得注意的数据现象(不代表测试出错, 提示人工确认) */
function perfAnomalies(r){
  const out=[...(r.notes||[])];
  const mv=(r._len&&r._len.moved)||[];
  if(mv.length){
    const rs=mv.map(x=>x.ratio).sort((x,y)=>x-y),ex=mv.reduce((a,x)=>parseFloat(x.from)>parseFloat(a.from)?x:a);
    out.unshift(`这次测试的长输入是用旧的估算方法拼的，在这个模型上实际只有标称长度的 ${fmt(100*rs[Math.floor(rs.length/2)],0)}% 左右。`+
      `下面已按实际长度显示（例如原来标 ${ex.from} 的显示为 ${ex.to}）；速度是按实际 token 数算的，本身没有问题`);
  }
  const rg=(r._len&&r._len.rag)||[];
  if(rg.length)out.splice(mv.length?1:0,0,`「看资料回答」的资料也是用旧方法估算长度的，例如标 ${rg[rg.length-1].from} 的实际约 ${rg[rg.length-1].to}；下面同样按实际长度显示`);
  const sk=r.length_skips||[];
  if(sk.length){
    const name={prefill:"输入长度",prefill_conc:"长输入并发",longctx:"超长输入"};
    const by=[...new Set(sk.map(x=>x.phase))].map(ph=>`${name[ph]||ph} ${[...new Set(sk.filter(x=>x.phase===ph).map(x=>x.label))].join("、")}`);
    out.push(`这些档位没有测：${by.join("；")}。原因：${sk[0].reason}`);
  }
  const cal=r.prompt_calibration;
  if(cal&&cal.method==="guess")out.push(`没能按这个模型的实际 token 数校准输入长度（${cal.error||"原因不明"}），各档长度按旧的估算拼，可能和标签差得多，以表格里的「实际 token 数」为准`);
  const ov=r.overrides||{},cp=phase(r,"concurrency");
  if(cp&&cp.points.length>1){
    const pts=[...cp.points].sort((x,y)=>x.conc-y.conc);
    for(let i=1;i<pts.length;i++){
      const p0=pts[i-1],p1=pts[i];
      if(p0.agg_tps>0&&p1.agg_tps<p0.agg_tps*0.95)
        out.push(`同时请求从 ${p0.conc} 个加到 ${p1.conc} 个时，总生成速度不升反降（${fmt(p0.agg_tps)} → ${fmt(p1.agg_tps)} token/秒），说明服务已到上限或在排队`);
    }
    const c1=pts.find(p=>p.conc===1),c2=pts.find(p=>p.conc>1);
    const dp=phase(r,"decode"),zh=dp&&dp.cases.find(c=>c.lang==="zh");
    if(c1&&c2&&c1.per_stream_tps_med&&c2.per_stream_tps_med&&c2.per_stream_tps_med<c1.per_stream_tps_med*0.5)
      out.push(`请求一多，每个请求的速度掉了一大半：从 1 个请求时的 ${fmt(c1.per_stream_tps_med)} 降到 ${c2.conc} 个时的 ${fmt(c2.per_stream_tps_med)} token/秒（下降 ${fmt(100-100*c2.per_stream_tps_med/c1.per_stream_tps_med,0)}%）`+
        (zh&&zh.spec_burst_med>1.3?`。1 个请求时每次返回 ${fmt(zh.spec_burst_med,2)} 个 token，投机解码加速可能只在请求很少时有效`:""));
    const fail=pts.reduce((s,p)=>s+(p.fail||0),0);
    if(fail)out.push(`同时请求测试中有 ${fail} 个请求失败`);
  }
  if(ov.fixed_output===false&&ov.fixed_output_note)out.push(ov.fixed_output_note+"：模型提前结束时速度会偏高，不同服务之间不能直接比较");
  if(r.status&&!["done","running"].includes(r.status))out.push(`这次测试${STATUS_NAME[r.status]||r.status}${r.error?"（"+r.error+"）":""}，部分项目可能缺失`);
  return out;
}
/* 结论: 单请求速度 / 最高总速度 / 从多少个请求开始明显变慢 / 长输入要等多久 (+ 失败、B 对比) */
const SLOW_TTFT=3;  /* 首字等待较慢时超过 3 秒, 用户会觉得慢 */
function perfConclusions(a,b){
  const m=perfCtx(a),out=[];
  if(m.zh||m.en){
    const parts=[m.zh&&`中文 <b>${fmt(m.zh.decode_tps_med)}</b>`,m.en&&`英文 <b>${fmt(m.en.decode_tps_med)}</b>`].filter(Boolean).join("、");
    out.push({tone:"info",html:`只有 1 个请求时，每秒能写 ${parts} 个 token。`});
  }
  if(m.peak&&m.c1){
    const x=m.c1.agg_tps?m.peak.agg_tps/m.c1.agg_tps:null;
    const drop=m.cLast&&m.cLast.conc>m.peak.conc&&m.cLast.agg_tps<m.peak.agg_tps*0.95;
    out.push({tone:drop?"warn":"info",html:`同时 <b>${m.peak.conc}</b> 个请求时${term("agg","总速度")}最高，每秒 <b>${fmtInt(m.peak.agg_tps)}</b> token${x&&m.peak.conc>1?`，是 1 个请求时的 <b>${fmt(x,1)}</b> 倍`:""}`+
      (drop?`；再加到 ${m.cLast.conc} 个反而降到 ${fmtInt(m.cLast.agg_tps)}，${m.peak.conc} 个左右就是上限。`:"。")});
  }
  const cps=concPoints(a);
  if(cps&&cps.length){
    const knee=cps.find(q=>q.ttft_p95_s!=null&&q.ttft_p95_s>SLOW_TTFT);
    if(knee)out.push({tone:knee.ttft_p95_s>10?"bad":"warn",html:`从同时 <b>${knee.conc}</b> 个请求开始明显变慢：${term("ttft")}较慢时 <b>${fmtSec(knee.ttft_p95_s)}</b> 秒${m.cLast&&m.cLast.conc!==knee.conc?`，${m.cLast.conc} 个时 ${fmtSec(m.cLast.ttft_p95_s)} 秒`:""}。`});
    else if(m.cLast&&m.cLast.ttft_p95_s!=null)out.push({tone:"good",html:`同时 ${m.cLast.conc} 个请求时，${term("ttft")}较慢也只要 <b>${fmtSec(m.cLast.ttft_p95_s)}</b> 秒，没有明显变慢。`});
  }
  if(m.pLast&&m.pLast.ttft_med_s!=null){
    const t=m.pLast.ttft_med_s;
    out.push({tone:t>10?"warn":"info",html:`输入 ${esc(m.pLast.label)}（约 ${fmtInt(m.pLast.in_tokens)} token${m.pLast.label_nominal?`，原来标的是 ${esc(m.pLast.label_nominal)}`:""}）时要等 <b>${fmtSec(t)}</b> 秒才开始回答，${term("prefill")} ${fmtInt(m.pLast.prefill_tps_med)} token/秒。`});
  }
  if(m.succ!=null&&m.succ<100)out.push({tone:"bad",html:`有 <b>${m.fails}</b> 个请求失败（成功率 ${fmt(m.succ,1)}%）。`});
  scnPhases(a).forEach(ph=>{const f=scnFails(ph),name=(ph.task&&ph.task.label)||SCN_LABEL[(ph.id||"").slice(4)]||ph.id;
    if(f.total&&!f.ok)out.push({tone:"bad",html:`「${esc(name)}」场景的 <b>${f.total}</b> 个请求全部失败${esc(f.why)}${esc(f.hint)}。`})});
  if(b){
    const mb=perfCtx(b);
    const rows=[...PERF_METRICS,...CMP_EXTRA].filter(k=>sameRef(k,m,mb)).map(k=>({k,va:safeVal(k.val,m),vb:safeVal(k.val,mb)})).filter(x=>x.va!=null&&x.vb!=null)
      .map(x=>({...x,d:pctChange(x.vb,x.va)})).filter(x=>x.d!=null);  /* A 比 B */
    const better=rows.filter(x=>x.d*x.k.dir>=1).sort((p,q)=>Math.abs(q.d)-Math.abs(p.d));
    const worse=rows.filter(x=>x.d*x.k.dir<=-1).sort((p,q)=>Math.abs(q.d)-Math.abs(p.d));
    const fmtD=x=>`${esc(metricLabel(x.k,m))} ${x.d>=0?"+":""}${fmt(x.d,1)}%`;
    if(!rows.length)out.push({tone:"info",html:`B 和 A 没有可以直接比较的指标（B 可能没有测完，或者两次测试的档位都不一样）。`});
    else out.push({tone:worse.length>better.length?"warn":"good",html:`A 比 B：<b>${better.length}</b> 项更好、<b>${worse.length}</b> 项更差、${rows.length-better.length-worse.length} 项基本持平。`+
      (better.length?`更好：${better.slice(0,2).map(fmtD).join("；")}。`:"")+(worse.length?`更差：${worse.slice(0,2).map(fmtD).join("；")}。`:"")});
  }
  return out;
}
function perfMetaLine(r){
  const ov=r.overrides||{};
  return [esc(r.model||"?"),runFw(r)&&esc(runFw(r)),`${esc(SUITE_NAME[r.suite]||r.suite||"")}规模`,esc(hostOf(r.url)),`开始于 ${esc(timeText(r.started_utc))}`,
    r.tag&&`标签 ${esc(r.tag)}`,ov.fixed_output!=null&&(ov.fixed_output?`${term("fixed","每次生成满指定长度")}`:"输出长度不固定")].filter(Boolean).join(" · ");
}
function metricTip(k){return k.term&&TERMS[k.term]?TERMS[k.term].name+"（"+TERMS[k.term].tech+"）："+TERMS[k.term].desc:""}
/* 概览带的 4 个关键数字; 其余指标在页面末尾的「全部指标」表里 */
const PERF_KEY_STATS=["zh","peak","ttftmax","succ"];
function perfStats(a,b){
  const ma=perfCtx(a),mb=b?perfCtx(b):null,all=[...PERF_METRICS,...CMP_EXTRA];
  return PERF_KEY_STATS.map(key=>{
    const k=all.find(x=>x.key===key);if(!k)return "";
    const va=safeVal(k.val,ma),vb=mb?safeVal(k.val,mb):null;
    const same=!mb||sameRef(k,ma,mb);
    const delta=!mb?"":same?deltaPill(vb,va,k.dir,{prefix:"比 B "}):`<span class="delta flat" title="A 是${esc(refText(k,ma))}，B 是${esc(refText(k,mb))}">档位不同</span>`;
    let sub=key==="zh"?(ma.en?`英文 ${fmt(ma.en.decode_tps_med)} token/秒 · 出字间隔 ${fmt(ma.zh&&ma.zh.itl_p50_ms_med)} 毫秒`:esc(safeSub(k,ma))):esc(safeSub(k,ma));
    if(key==="ttftmax"&&ma.pLast)sub=`${term("prefill")} ${fmtInt(ma.pLast.prefill_tps_med)} token/秒`;
    if(mb)sub+=`<br>B：${metricVal(k,vb)} ${esc(k.unit)}${same?"":`（${esc(refText(k,mb))}，不可比）`}`;
    return stat(esc(metricLabel(k,ma)),metricVal(k,va),esc(k.unit),{tip:metricTip(k),delta,sub});
  }).join("");
}
/* 两次测试的系列: 单次测试时只有 A */
function runSeries(a,b,get){return [["A",a,C.a],b?["B",b,C.b]:null].filter(Boolean).map(([t,r,c])=>({tag:t,run:r,color:c,ph:get(r)})).filter(x=>x.ph)}
/* 单次: 明细表; A/B: 对比表(A | B | 变化 三列一组) */
function perfTable(id,title,runs,keys,getRow,M,single){
  if(runs.length>1)return{id,title:title+" · A / B 对比",columns:[{key:"_key",label:single.keyLabel,type:single.keyType||"text",sticky:true,fmt:single.keyFmt},...compareCols(runs,M)],
    rows:compareRows(keys,runs,getRow,M)};
  return{id,title,columns:[{key:"_key",label:single.keyLabel,type:single.keyType||"text",sticky:true,fmt:single.keyFmt},...single.cols],
    rows:keys.map(k=>{const q=getRow(runs[0],k);return q?Object.assign({_key:k},single.row(q)):null}).filter(Boolean)};
}

/* ---------- 同时请求 ---------- */
function concPoints(r){const p=phase(r,"concurrency");return p&&p.points.length?[...p.points].sort((x,y)=>x.conc-y.conc):null}
function concSection(a,b,p){
  const runs=runSeries(a,b,concPoints);if(!runs.length)return "";
  const concs=[...new Set(runs.flatMap(x=>x.ph.map(q=>q.conc)))].sort((x,y)=>x-y);
  const M=[{key:"agg",label:"总生成速度",unit:"token/秒",dir:1,get:q=>q.agg_tps},{key:"per",label:"单个请求速度",unit:"token/秒",dir:1,get:q=>q.per_stream_tps_med},
    {key:"t50",label:"首字等待 一般",unit:"秒",dir:-1,type:"sec",get:q=>q.ttft_p50_s},{key:"t95",label:"首字等待 较慢",unit:"秒",dir:-1,type:"sec",get:q=>q.ttft_p95_s}];
  const spec=perfTable(p+"-conc-t","同时请求明细",runs,concs,(x,c)=>x.ph.find(z=>z.conc===c),M,{keyLabel:"同时请求数",keyType:"int",
    cols:[{key:"agg",label:"总生成速度",unit:"token/秒",type:"bar",color:C.a},{key:"per",label:"单个请求速度",unit:"token/秒",type:"num"},
      {key:"t50",label:"首字等待 一般",unit:"秒",type:"sec"},{key:"t95",label:"首字等待 较慢",unit:"秒",type:"heat",digits:2,tip:"颜色越深等得越久"},
      {key:"ok",label:"成功",type:"text"},{key:"rate",label:"成功率",unit:"%",type:"num"}],
    row:q=>({agg:q.agg_tps,per:q.per_stream_tps_med,t50:q.ttft_p50_s,t95:q.ttft_p95_s,ok:`${q.ok} / ${q.ok+q.fail}`,rate:q.ok+q.fail?100*q.ok/(q.ok+q.fail):null})});
  return panel({id:p+"-conc",title:"同时请求越多，会怎样",jump:"同时请求",
    desc:`横轴是${term("conc")}。总速度通常先涨后平；每个请求分到的速度和${term("ttft")}会随之变差。虚线是 ${SLOW_TTFT} 秒：超过它用户会觉得慢`,
    chart:`<div class="grid-3">${ccard(p+"ConcAgg",term("agg"),{desc:"所有请求加起来每秒写多少 token · 越高越好",h:240})}
      ${ccard(p+"ConcPer",term("per"),{desc:"每个请求分到的生成速度 · 越高越好",h:240})}
      ${ccard(p+"ConcTtft",term("ttft")+"（较慢的情况）",{desc:"95% 的请求比这更快拿到第一个字 · 越短越好",h:240})}</div>`,
    tables:[spec]});
}
function drawConc(a,b,p){
  const runs=runSeries(a,b,concPoints);if(!runs.length)return;
  const concs=[...new Set(runs.flatMap(x=>x.ph.map(q=>q.conc)))].sort((x,y)=>x-y);
  const get=(x,c,k)=>{const q=x.ph.find(z=>z.conc===c);return q&&q[k]!=null?q[k]:null};
  const ser=k=>runs.map(x=>({name:x.tag,color:x.color,data:concs.map(c=>get(x,c,k))}));
  const title=i=>`同时 ${concs[i]} 个请求`;
  lineChart(p+"ConcAgg",{cats:concs.map(String),xName:"同时请求数",unit:"token/秒",series:ser("agg_tps"),area:true,
    tip:{title,sub:i=>runs.map(x=>{const q=x.ph.find(z=>z.conc===concs[i]);return q?`${x.tag} 成功 ${q.ok}/${q.ok+q.fail}`:""}).filter(Boolean).join(" · ")}});
  lineChart(p+"ConcPer",{cats:concs.map(String),xName:"同时请求数",unit:"token/秒",series:ser("per_stream_tps_med"),tip:{title}});
  lineChart(p+"ConcTtft",{cats:concs.map(String),xName:"同时请求数",unit:"秒",digits:2,series:ser("ttft_p95_s"),
    tip:{title,sub:i=>runs.map(x=>`${x.tag} 一般 ${fmtSec(get(x,concs[i],"ttft_p50_s"))} 秒`).join(" · ")}});
  /* 标出最高总速度、3 秒线 */
  const agg=CHARTS.get(p+"ConcAgg");
  if(agg)agg.setOption({series:[{markPoint:{symbol:"circle",symbolSize:9,itemStyle:{color:C.a,borderColor:C.surface,borderWidth:2},
    label:{show:true,position:"top",distance:8,color:C.text1,fontSize:11,fontWeight:600,formatter:q=>"最高 "+fmtInt(q.value)},data:[{type:"max"}]}}]});
  const tt95=CHARTS.get(p+"ConcTtft");
  if(tt95)tt95.setOption({series:[{markLine:{silent:true,symbol:"none",lineStyle:{color:C.warnMark,type:"dashed",width:1},
    label:{show:true,position:"insideEndTop",color:C.text3,fontSize:11,formatter:SLOW_TTFT+" 秒"},data:[{yAxis:SLOW_TTFT}]}}]});
}

/* ---------- 输入长度(单个请求) ---------- */
function prefillPoints(r){const p=phase(r,"prefill");return p&&p.points.length?p.points:null}
function lenLabels(runs,key="label"){
  const m=new Map();runs.forEach(x=>x.ph.forEach(q=>{if(!m.has(q[key]))m.set(q[key],q.in_tokens||0)}));
  return [...m.entries()].sort((x,y)=>x[1]-y[1]).map(x=>x[0]);
}
function prefillSection(a,b,p){
  const runs=runSeries(a,b,prefillPoints);if(!runs.length)return "";
  const labels=lenLabels(runs);
  const M=[{key:"tps",label:"读入速度",unit:"token/秒",dir:1,digits:0,get:q=>q.prefill_tps_med},{key:"ttft",label:"首字等待",unit:"秒",dir:-1,type:"sec",get:q=>q.ttft_med_s}];
  const spec=perfTable(p+"-prefill-t","输入长度明细",runs,labels,(x,l)=>x.ph.find(z=>z.label===l),M,{keyLabel:"输入长度",
    cols:[{key:"tok",label:"实际 token 数",type:"int"},{key:"tps",label:"读入速度",unit:"token/秒",type:"bar",digits:0,color:C.a},{key:"ttft",label:"首字等待",unit:"秒",type:"heat",digits:2}],
    row:q=>({tok:q.in_tokens,tps:q.prefill_tps_med,ttft:q.ttft_med_s})});
  return panel({id:p+"-prefill",title:"输入越长，要等多久",jump:"输入长度",desc:`只有 1 个请求时，不同输入长度下的${term("prefill")}和${term("ttft")}`,
    chart:`<div class="grid-2">${ccard(p+"PreTps",term("prefill"),{desc:"每秒读入多少 token · 越高越好",h:240})}
      ${ccard(p+"PreTtft",term("ttft"),{desc:"输入越长通常要等越久 · 越短越好",h:240})}</div>`,tables:[spec]});
}
function drawPrefill(a,b,p){
  const runs=runSeries(a,b,prefillPoints);if(!runs.length)return;
  const labels=lenLabels(runs);
  const get=(x,l,k)=>{const q=x.ph.find(z=>z.label===l);return q&&q[k]!=null?q[k]:null};
  const ser=k=>runs.map(x=>({name:x.tag,color:x.color,data:labels.map(l=>get(x,l,k))}));
  const title=i=>{const q=runs.map(x=>x.ph.find(z=>z.label===labels[i])).find(Boolean);
    return `输入 ${labels[i]}${q?`（约 ${fmtInt(q.in_tokens)} token${q.label_nominal?`，原来标的是 ${q.label_nominal}`:""}）`:""}`};
  lineChart(p+"PreTps",{cats:labels,xName:"输入长度",unit:"token/秒",digits:0,series:ser("prefill_tps_med"),area:true,tip:{title}});
  lineChart(p+"PreTtft",{cats:labels,xName:"输入长度",unit:"秒",digits:2,series:ser("ttft_med_s"),tip:{title}});
}

/* ---------- 长输入 + 同时请求: 以热力表为主 ---------- */
function matrixPhase(r){const p=phase(r,"prefill_conc");return p&&p.points.length?p.points:null}
function matrixSection(a,b,p){
  const pa=phase(a,"prefill_conc"),pb=b?phase(b,"prefill_conc"):null;
  if(!pa||!pa.points.length)return "";
  const runs=runSeries(a,b,matrixPhase),labels=lenLabels(runs);
  const M=[{key:"ttft",label:"首字等待 平均",unit:"秒",dir:-1,digits:2,get:q=>q.ttft_avg_ms!=null?q.ttft_avg_ms/1000:null},
    {key:"itl",label:"出字间隔 平均",unit:"毫秒",dir:-1,get:q=>q.itl_avg_ms},
    {key:"pre",label:"总读入速度",unit:"token/秒",dir:1,digits:0,get:q=>q.prefill_tps_agg},{key:"dec",label:"总生成速度",unit:"token/秒",dir:1,get:q=>q.decode_tps_agg}];
  const det=(x,who)=>x?`<b>${who}</b> 每个请求的读入速度：${(x.stream_prefill_tps||[]).map(v=>fmtInt(v)).join(" / ")} token/秒；每个请求的生成速度：${(x.stream_decode_tps||[]).map(v=>fmt(v)).join(" / ")} token/秒`:"";
  let heat;
  if(runs.length>1){
    const rows=compareRows(labels,runs,(x,l)=>x.ph.find(z=>z.label===l),M);
    heat={id:p+"-matrix-h",title:"A 相对 B 的变化（绿色是 A 更好、红色是 A 更差，颜色越深差距越大）",columns:[{key:"_key",label:"输入长度",type:"text",sticky:true},
      ...M.map(m=>({key:m.key+"_d",label:m.label,unit:"变化",type:"heat",scale:"div",dir:m.dir,fmt:v=>deltaText(v,m.dir),sortValue:r=>r[m.key+"_d"]==null?null:r[m.key+"_d"]*m.dir}))],
      rows,note:"按好坏方向换算后比较"};
  }else{
    heat={id:p+"-matrix-h",title:`每种输入长度下同时 ${pa.conc||""} 个请求（颜色越深数值越大）`,columns:[{key:"_key",label:"输入长度",type:"text",sticky:true},
      {key:"tok",label:"实际 token 数",type:"int"},...M.map(m=>({key:m.key,label:m.label,unit:m.unit,type:"heat",digits:m.digits}))],
      rows:pa.points.map(q=>Object.assign({_key:q.label,tok:q.in_tokens},...M.map(m=>({[m.key]:m.get(q)})))),
      expand:r=>{const q=pa.points.find(z=>z.label===r._key);return det(q,"A")},note:"点行可以展开看每个请求"};
  }
  const detail=perfTable(p+"-matrix-t","长输入并发明细",runs,labels,(x,l)=>x.ph.find(z=>z.label===l),[...M,{key:"ok",label:"成功",unit:"个",dir:1,digits:0,get:q=>q.ok}],{keyLabel:"输入长度",
    cols:[{key:"tok",label:"实际 token 数",type:"int"},...M.map(m=>({key:m.key,label:m.label,unit:m.unit,type:"num",digits:m.digits})),{key:"ok",label:"成功",type:"text"}],
    row:q=>Object.assign({tok:q.in_tokens,ok:`${q.ok} / ${q.ok+q.fail}`},...M.map(m=>({[m.key]:m.get(q)})))});
  if(runs.length===1)detail.expand=r=>det(pa.points.find(z=>z.label===r._key),"A");
  const sums=[[pa.summary,"A",C.a],pb&&[pb.summary,"B",C.b]].filter(x=>x&&x[0]);
  const sum={id:p+"-matrix-s",title:"汇总",columns:[{key:"_tag",label:"测试",type:"tag"},
      {key:"pmin",label:"读入速度 最低",unit:"token/秒",type:"int"},{key:"pmax",label:"最高",unit:"token/秒",type:"int"},{key:"pavg",label:"平均",unit:"token/秒",type:"int"},
      {key:"dmin",label:"总生成速度 最低",unit:"token/秒",type:"num"},{key:"dmax",label:"最高",unit:"token/秒",type:"num"},{key:"davg",label:"平均",unit:"token/秒",type:"num"},
      {key:"s50",label:"单个请求生成 一般",unit:"token/秒",type:"num"},{key:"s90",label:"较慢",unit:"token/秒",type:"num"},{key:"s95",label:"最慢",unit:"token/秒",type:"num"}],
    rows:sums.map(([s,t,c])=>({_tag:t,_color:c,pmin:s.prefill_min,pmax:s.prefill_max,pavg:s.prefill_avg,dmin:s.decode_min,dmax:s.decode_max,davg:s.decode_avg,
      s50:s.per_stream_decode_p50,s90:s.per_stream_decode_p90,s95:s.per_stream_decode_p95}))};
  const s=pa.summary;
  return panel({id:p+"-matrix",title:`长输入时同时 ${pa.conc||""} 个请求`,jump:"长输入并发",
    desc:`每种输入长度下同时发 ${pa.conc||"多"} 个请求，看要等多久、总速度多少`+(s?`。平均${term("prefill")} <b>${fmtInt(s.prefill_avg)}</b>、平均${term("agg")} <b>${fmt(s.decode_avg)}</b> token/秒`:""),
    chart:`<div class="side-row">${dataTable(heat)}${ccard(p+"MxTtft",term("ttft")+"（平均）随输入长度变化",{desc:"越短越好",h:Math.max(240,labels.length*38+96)})}</div>`,
    tables:[detail,...(sums.length?[sum]:[])],tcols:1});
}
function drawMatrix(a,b,p){
  const runs=runSeries(a,b,matrixPhase);if(!runs.length)return;
  const labels=lenLabels(runs);
  const get=(x,l,k,f=v=>v)=>{const q=x.ph.find(z=>z.label===l);return q&&q[k]!=null?f(q[k]):null};
  const title=i=>`输入 ${labels[i]}`;
  lineChart(p+"MxTtft",{cats:labels,xName:"输入长度",unit:"秒",digits:2,series:runs.map(x=>({name:x.tag,color:x.color,data:labels.map(l=>get(x,l,"ttft_avg_ms",v=>v/1000))})),tip:{title}});
}

/* ---------- 单个请求的生成细节: 统计摘要表 + 区间点图 ---------- */
function decodeStats(c){
  if(!c)return null;
  const runs=c.runs||[];
  const m=k=>median(runs.map(r=>r[k]));
  return{out:c.out_tokens,tps:c.decode_tps_med,best:c.decode_tps_best,tpot:m("tpot_ms"),p50:c.itl_p50_ms_med,p95:m("itl_p95_ms"),p99:m("itl_p99_ms"),jit:m("itl_jitter_ms"),burst:c.spec_burst_med};
}
function decodeRows(a,b){
  const rows=[];
  [["zh","中文"],["en","英文"]].forEach(([lang,ln])=>[[a,"A",C.a],[b,"B",C.b]].forEach(([r,tag,color])=>{
    const d=r&&phase(r,"decode"),s=d&&decodeStats(d.cases.find(c=>c.lang===lang));
    if(s)rows.push(Object.assign({_key:b?`${ln} · ${tag}`:ln,_tag:tag,_color:color,lang:ln},s));
  }));
  return rows;
}
function decodeSection(a,b,p){
  const da=phase(a,"decode");if(!da)return "";
  const rows=decodeRows(a,b);if(!rows.length)return "";
  const spec={id:p+"-decode-t",title:`${term("itl")}与${term("decode")}`,columns:[{key:"_key",label:"内容",type:"text",sticky:true},
    {key:"tps",label:"生成速度",unit:"token/秒",type:"num"},{key:"best",label:"最快一次",unit:"token/秒",type:"num"},{key:"tpot",label:"平均每个 token",unit:"毫秒",type:"num",digits:2},
    {key:"p50",label:"出字间隔 一般",unit:"毫秒",type:"num",group:"出字间隔"},{key:"p95",label:"较慢",unit:"毫秒",type:"num",group:"出字间隔"},{key:"p99",label:"最慢",unit:"毫秒",type:"num",group:"出字间隔"},
    {key:"jit",label:"波动",unit:"毫秒",type:"num",tip:TERMS.jitter.desc},{key:"burst",label:"每次返回的 token",type:"num",digits:2,tip:TERMS.burst.desc},{key:"out",label:"每次写",unit:"token",type:"int"}],rows};
  const sp=["zh","en"].map(l=>{const s2=decodeStats(da.cases.find(c=>c.lang===l));return s2?`${l==="zh"?"中文":"英文"} <b>${fmt(s2.tps)}</b>`:""}).filter(Boolean).join("、");
  return panel({id:p+"-decode",title:"单个请求写得多快、稳不稳",jump:"单个请求",
    desc:`只有 1 个请求时每秒能写 ${sp} 个 token。${term("itl")}越短、越集中，看起来越流畅；${term("burst")}明显大于 1 通常表示开了投机解码`,
    chart:`<div class="side-row">${dataTable({id:p+"-decode-c",title:"关键数字",columns:[spec.columns[0],spec.columns[1],
        {key:"p50",label:"出字间隔 一般",unit:"毫秒",type:"num"},{key:"p95",label:"较慢",unit:"毫秒",type:"num"},{key:"p99",label:"最慢",unit:"毫秒",type:"num"},spec.columns[8]],rows})}
      ${ccard(p+"DecItl",term("itl")+"的分布（毫秒）",{desc:"● 一般　┃ 较慢　○ 最慢 · 越靠左越快、越短越稳",h:Math.max(150,rows.length*40+56)})}</div>`,
    tables:[spec]});
}
/* 区间点图: 每行一条细线从"一般"到"最慢", 实心点 = 一般, 竖线 = 较慢, 空心点 = 最慢 */
function rangeChart(id,rows,unit){
  const el=$(id);if(!el)return;
  if(!rows.length){chartEmpty(id);return}
  setChart(id,baseOption({
    grid:{left:4,right:30,top:26,bottom:4,containLabel:true},
    xAxis:axisValue({name:unit,min:0}),yAxis:axisCat(rows.map(r=>r._key),{inverse:true,labelColor:C.text2}),
    tooltip:Object.assign(baseOption().tooltip,{trigger:"item",formatter:q=>{const r=rows[q.dataIndex];
      return tt(r._key,[[r._color,"一般",fmt(r.p50)+" "+unit],[r._color,"较慢",fmt(r.p95)+" "+unit],[r._color,"最慢",fmt(r.p99)+" "+unit]])}}),
    series:[{type:"custom",data:rows.map((r,i)=>[i,r.p50,r.p95,r.p99]),encode:{x:[1,2,3],y:0},
      renderItem:(params,api)=>{
        const i=api.value(0),r=rows[i],c=r._color||C.a;
        const a1=api.coord([api.value(1),i]),a2=api.coord([api.value(2),i]),a3=api.coord([api.value(3),i]);
        return{type:"group",children:[
          {type:"line",shape:{x1:a1[0],y1:a1[1],x2:a3[0],y2:a3[1]},style:{stroke:c,lineWidth:2,opacity:.55}},
          {type:"line",shape:{x1:a2[0],y1:a2[1]-7,x2:a2[0],y2:a2[1]+7},style:{stroke:c,lineWidth:2}},
          {type:"circle",shape:{cx:a3[0],cy:a3[1],r:4.5},style:{fill:C.surface,stroke:c,lineWidth:2}},
          {type:"circle",shape:{cx:a1[0],cy:a1[1],r:5},style:{fill:c,stroke:C.surface,lineWidth:2}},
          {type:"text",style:{text:fmt(api.value(3)),x:a3[0]+9,y:a3[1],verticalAlign:"middle",fill:C.text3,font:"11px "+C.font}}]};
      }}]}));
}
function drawDecode(a,b,p){rangeChart(p+"DecItl",decodeRows(a,b),"毫秒")}

/* ---------- 旧版测试的长上下文阶段 ---------- */
function longctxSection(a,b,p){
  const pa=phase(a,"longctx");if(!pa||!pa.points||!pa.points.length)return "";
  const spec={id:p+"-longctx-t",title:"超长输入（旧版）",columns:[{key:"tok",label:"输入 token",type:"int",sticky:true},{key:"ttft",label:"首字等待",unit:"秒",type:"sec"},
    {key:"pre",label:"读入速度",unit:"token/秒",type:"int"},{key:"dec",label:"生成速度",unit:"token/秒",type:"num"},{key:"i50",label:"出字间隔 一般",unit:"毫秒",type:"num"},{key:"i95",label:"较慢",unit:"毫秒",type:"num"}],
    rows:pa.points.map(q=>({tok:q.in_tokens,ttft:q.ttft_s,pre:q.prefill_tps,dec:q.decode_tps,i50:q.itl_p50_ms,i95:q.itl_p95_ms}))};
  if(pa.points.length<3)return panel({id:p+"-longctx",title:"超长输入（旧版测试项）",jump:"超长输入",desc:"早期版本的长上下文测试结果，数据点太少，直接列出",tables:[spec]});
  return panel({id:p+"-longctx",title:"超长输入（旧版测试项）",jump:"超长输入",desc:"早期版本的长上下文测试结果",
    chart:`<div class="grid-2">${ccard(p+"LcTtft",term("ttft"),{desc:"越短越好",h:240})}${ccard(p+"LcDec",term("decode"),{desc:"读完长输入后的生成速度 · 越高越好",h:240})}</div>`,tables:[spec]});
}
function drawLongctx(a,b,p){
  const pa=phase(a,"longctx");if(!pa||!pa.points||pa.points.length<3)return;
  const cats=pa.points.map(q=>fmtAxis(q.in_tokens));
  lineChart(p+"LcTtft",{cats,xName:"输入 token",unit:"秒",digits:2,series:[{name:"A",color:C.a,data:pa.points.map(q=>q.ttft_s)}]});
  lineChart(p+"LcDec",{cats,xName:"输入 token",unit:"token/秒",series:[{name:"A",color:C.a,data:pa.points.map(q=>q.decode_tps)}]});
}

/* ---------- 模拟真实业务(scn_*): 每个场景一行的汇总表 + 各场景明细 ---------- */
const SCN_LABEL=Object.fromEntries(SCN_TPL.map(([id,name])=>[id,name]));
const kLabel=v=>(v/1000).toFixed(v%1000?1:0)+"K";
function retryTag(p){return (p.attempts||1)>1?` <span class="badge is-warn" title="这一档失败后整档重跑过，明细见导出的报告">重跑 ${p.attempts} 次</span>`:""}
function scnPhases(r){return (r.phases||[]).filter(ph=>(ph.id||"").startsWith("scn_"))}
/* 场景的失败情况: 总请求数 / 成功数 / 不重复的错误(带服务端返回的原因); 图片理解全部失败时给出具体建议 */
function scnFails(ph){
  const pts=ph.points||[],total=pts.reduce((s,q)=>s+(q.total||0),0),ok=pts.reduce((s,q)=>s+(q.ok||0),0);
  const errs=[...new Set(pts.flatMap(q=>q.errors||[]))];
  const hint=ph.id==="scn_vision"&&ok===0?visionFailHint(errs):"";
  return{total,ok,fail:total-ok,errs,hint,why:errs.length?`（${errs[0]}${errs.length>1?` 等 ${errs.length} 种错误`:""}）`:""};
}
/* 看图回答全部 HTTP 400: 服务端原因里能看出是模型不支持看图、还是图片太小, 就直说; 看不出时两样都先查 */
function visionFailHint(errs){
  if(!errs.some(e=>/\b400\b/.test(e)))return "";
  const all=errs.join(" ");
  if(/not a multimodal|at most 0 image|image input is not supported|does not support (image|vision)|image_url is only supported|not support(ed)? (image|vision)/i.test(all))
    return "，模型或服务不支持看图（图片输入），请换一个能看图的模型";
  if(/must be larger than factor|too small/i.test(all))return "，图片太小：每张至少 28×28 像素，推荐 224×224 以上";
  return "，请先检查图片尺寸（每张至少 28×28 像素，推荐 224×224 以上），再确认模型是否支持看图";
}
function scnLast(ph){const pts=ph.points||[];return pts.length?pts.reduce((m,q)=>((q.conc||0)>(m.conc||0)||(q.ctx_tokens||0)>(m.ctx_tokens||0)?q:m),pts[0]):null}
function scnSection(a,b,p){
  const phs=scnPhases(a);if(!phs.length)return "";
  const nameOf=ph=>(ph.task&&ph.task.label)||SCN_LABEL[(ph.id||"").slice(4)]||ph.id;
  const jsonRate=ph=>{const ok=(ph.points||[]).reduce((s,q)=>s+(q.json_ok||0),0),t=(ph.points||[]).reduce((s,q)=>s+(q.json_total||0),0);return t?100*ok/t:null};
  const M=[{key:"rps",label:"每秒完成请求数",unit:"个/秒",dir:1,digits:2,get:q=>q.req_s},{key:"t95",label:"首字等待 较慢",unit:"秒",dir:-1,type:"sec",get:q=>q.ttft_p95_s},
    {key:"e95",label:"完整响应 较慢",unit:"秒",dir:-1,type:"sec",get:q=>q.e2e_p95_s}];
  let summary;
  if(b){
    const runs=[{tag:"A",r:a},{tag:"B",r:b}];
    summary={id:p+"-scn-sum",title:"各场景汇总 · A / B（各自最高一档）",columns:[{key:"_key",label:"场景",type:"text",sticky:true},...compareCols(runs,M)],
      rows:compareRows(phs.map(ph=>ph.id),runs,(x,pid)=>{const ph=(x.r.phases||[]).find(z=>z.id===pid);return ph?scnLast(ph):null},M).map(r=>Object.assign(r,{_key:nameOf(phs.find(ph=>ph.id===r._key))}))};
  }else{
    summary={id:p+"-scn-sum",title:"各场景汇总（各自最高一档）",columns:[{key:"name",label:"场景",type:"text",sticky:true},{key:"at",label:"测到",type:"text"},
      {key:"rps",label:"每秒完成请求数",unit:"个/秒",type:"bar",digits:2,color:C.a},{key:"t95",label:"首字等待 较慢",unit:"秒",type:"sec"},{key:"e95",label:"完整响应 较慢",unit:"秒",type:"sec"},
      {key:"out",label:"平均输出",unit:"token",type:"int"},{key:"succ",label:"成功率",unit:"%",type:"num"},{key:"json",label:"JSON 合格率",unit:"%",type:"num",digits:0}],
      rows:phs.map(ph=>{const q=scnLast(ph)||{};const isRag=ph.id==="scn_rag";
        return{name:nameOf(ph),at:isRag?(q.ctx_actual?`资料约 ${fmtInt(q.ctx_actual)} token（原来标 ${kLabel(q.ctx_tokens)}）`:`资料 ${fmtInt(q.ctx_tokens)} token`):`同时 ${q.conc} 个`,rps:q.req_s,t95:q.ttft_p95_s,e95:q.e2e_p95_s,out:q.out_tokens_avg,
          succ:q.total?100*q.ok/q.total:null,json:jsonRate(ph)}})};
  }
  const charts=[],details=[];
  phs.forEach((ph,idx)=>{
    const isRag=ph.id==="scn_rag",key=isRag?"ctx_tokens":"conc",pb=b?(b.phases||[]).find(x=>x.id===ph.id):null;
    const hasJson=(ph.points||[]).some(x=>x.json_total);
    const t=ph.task||{};
    const ts=t.task_set&&t.task_set.id?t.task_set:null;  /* 3.6.0 起记下用的是哪个任务集 */
    const desc=[jsonRate(ph)!=null?`JSON 合格率 ${fmt(jsonRate(ph),0)}%`:"",t.max_tokens?"每次最多 "+t.max_tokens+" token":"",t.requests_per_worker?"每个并发发 "+t.requests_per_worker+" 次":"",
      t.images?(t.image_source==="builtin"?"内置示例图片 ":"图片 ")+t.images+" 张"+(t.images_per_request?"，每次带 "+t.images_per_request+" 张":"")+(t.images_skipped?"（另有 "+t.images_skipped+" 张不能用，已跳过）":""):"",
      ts?`任务集：${ts.name||ts.id}`:"",t.pool_size?(ts?t.pool_size+" 条请求":"任务集 "+t.pool_size+" 条"):"",
      Array.isArray(t.rag_ctx)?"资料长度 "+t.rag_ctx.map(x=>(x/1000)+"K").join(" / ")+ragActualNote(ph,t.rag_ctx):""].filter(Boolean).join(" · ");
    const tsLink=ts&&TS_ID_RE.test(ts.id)?` <a class="qb-link" href="#tasks/${esc(ts.id)}" data-online-only title="到任务集页面逐行查看这个任务集">查看任务集</a>`:"";
    const f=scnFails(ph);
    const failNote=!f.total||f.ok===f.total?"":f.ok===0?alertBox("bad",`<b>${f.total} 个请求全部失败</b>${esc(f.why)}${esc(f.hint)}，所以下面的图没有数据。`)
      :alertBox("warn",`${f.fail} / ${f.total} 个请求失败${esc(f.why)}，图里只算成功的请求。`);
    charts.push(`<div class="scn-block"><div class="sub-h">${esc(nameOf(ph))}${desc?`<span class="sub-h-note">${esc(desc)}${tsLink}</span>`:""}</div>${failNote}
      <div class="grid-2">${ccard(`${p}Scn${idx}Rps`,term("rps"),{desc:(isRag?"横轴是资料长度":"横轴是同时请求数")+" · 越高越好",h:220})}
        ${ccard(`${p}Scn${idx}E2e`,term("e2e")+"（较慢的情况）",{desc:"95% 的请求比这更快拿到完整回答 · 越短越好",h:220})}</div></div>`);
    details.push({id:`${p}-scn-${ph.id}`,title:esc(nameOf(ph)),sub:esc(desc),columns:[{key:"k",label:isRag?"资料长度":"同时请求数",unit:isRag?"token":"",type:"int",sticky:true},
      ...(isRag?[{key:"inTok",label:"实际输入",unit:"token",type:"int"}]:[]),{key:"ok",label:"成功",type:"text"},{key:"rps",label:"每秒完成请求数",unit:"个/秒",type:"num",digits:2},...(pb?[{key:"rpsB",label:"B",unit:"个/秒",type:"num",digits:2}]:[]),
      {key:"t95",label:"首字等待 较慢",unit:"秒",type:"sec"},{key:"e95",label:"完整响应 较慢",unit:"秒",type:"sec"},...(pb?[{key:"e95B",label:"B",unit:"秒",type:"sec"}]:[]),
      {key:"out",label:"平均输出",unit:"token",type:"int"},{key:"inf",label:"最多积压",type:"int"},...(hasJson?[{key:"json",label:"JSON 合格",type:"text"}]:[]),{key:"note",label:"备注",type:"html"}],
      rows:(ph.points||[]).map(q=>{let z=pb?(pb.points||[]).find(x=>x[key]===q[key]):null;
        if(isRag&&z&&!ragPair(q,z))z=null;   /* 新旧算法的资料实际长度不同, 不比 */
        return{k:q[key],inTok:isRag&&q.prompt_tokens_avg?Math.round(q.prompt_tokens_avg):null,ok:`${q.ok} / ${q.total}`,rps:q.req_s,rpsB:z&&z.req_s,t95:q.ttft_p95_s,e95:q.e2e_p95_s,e95B:z&&z.e2e_p95_s,out:q.out_tokens_avg,inf:q.max_inflight,
          json:q.json_total!=null?`${fmtInt(q.json_ok)} / ${fmtInt(q.json_total)}`:"—",note:(retryTag(q)+(q.pool_wrapped?` <span class="badge" title="任务集用完一轮后重复使用">已循环</span>`:"")+(q.fail?` <span class="badge is-bad">失败 ${q.fail}</span>`:"")).trim()||"—"}})});
  });
  return panel({id:p+"-scn",title:"模拟真实业务",jump:"真实业务",desc:"不同业务类型的请求按真实方式结束（不强制写满长度），看每秒能处理多少、用户要等多久",
    chart:dataTable(summary)+`<div class="scn-list">${charts.join("")}</div>`,tables:[summary,...details],tcols:1});
}
function ragActualNote(ph,ctxs){
  const act=ctxs.map(x=>{const q=(ph.points||[]).find(z=>z.ctx_tokens===x);return q&&q.ctx_actual?lenK(q.ctx_actual):null});
  return act.some(Boolean)?`（旧方法估算的，实际约 ${act.map(x=>x||"—").join(" / ")}）`:"";
}
function drawScn(a,b,p){
  scnPhases(a).forEach((ph,idx)=>{
    const isRag=ph.id==="scn_rag",key=isRag?"ctx_tokens":"conc";
    const pb=b?(b.phases||[]).find(x=>x.id===ph.id):null;
    const keys=[...new Set([...(ph.points||[]),...((pb&&pb.points)||[])].map(q=>q[key]))].sort((x,y)=>x-y);
    const runs=[{tag:"A",color:C.a,pts:ph.points||[]},pb?{tag:"B",color:C.b,pts:pb.points||[]}:null].filter(Boolean);
    const at=(x,k)=>x.pts.find(z=>z[key]===k);
    const get=(x,k,f)=>{const q=at(x,k);if(isRag&&x.tag==="B"&&q&&!ragPair(at(runs[0],k),q))return null;return q&&q[f]!=null?q[f]:null};
    const ref=k=>at(runs[0],k)||(runs[1]&&at(runs[1],k));
    const cats=keys.map(k=>{if(!isRag)return String(k);const q=ref(k);return q&&q.ctx_actual?lenK(q.ctx_actual):kLabel(k)}),xName=isRag?"资料长度（token）":"同时请求数";
    const title=i=>{if(!isRag)return `同时 ${keys[i]} 个请求`;const q=ref(keys[i]);
      return q&&q.ctx_actual?`资料约 ${fmtInt(q.ctx_actual)} token（原来标 ${kLabel(keys[i])}）`:`资料约 ${fmtInt(keys[i])} token`};
    lineChart(`${p}Scn${idx}Rps`,{cats,xName,unit:"个/秒",digits:2,series:runs.map(x=>({name:x.tag,color:x.color,data:keys.map(k=>get(x,k,"req_s"))})),area:true,tip:{title}});
    lineChart(`${p}Scn${idx}E2e`,{cats,xName,unit:"秒",digits:2,series:runs.map(x=>({name:x.tag,color:x.color,data:keys.map(k=>get(x,k,"e2e_p95_s"))})),
      tip:{title,sub:i=>runs.map(x=>`${x.tag} 首字等待较慢 ${fmtSec(get(x,keys[i],"ttft_p95_s"))} 秒`).join(" · ")}});
  });
}

/* ---------- 回放真实请求 ---------- */
function replaySection(a,b,p){
  const pa=phase(a,"replay"),pb=b?phase(b,"replay"):null,oa=phase(a,"openloop"),ob=b?phase(b,"openloop"):null;
  if(!pa&&!oa)return "";
  const charts=[],tables=[];
  if(pa){
    const pool=pa.pool||{};
    tables.push({id:p+"-replay-c",title:term("closed"),sub:`请求池 ${fmtInt(pool.size)} 条${pool.wrapped?"（已循环使用）":""}`,columns:[{key:"conc",label:"同时请求数",type:"int",sticky:true},
      {key:"rps",label:"每秒完成请求数",unit:"个/秒",type:"num",digits:2},...(pb?[{key:"rpsB",label:"B",unit:"个/秒",type:"num",digits:2}]:[]),
      {key:"t95",label:"首字等待 较慢",unit:"秒",type:"sec"},{key:"e95",label:"完整响应 较慢",unit:"秒",type:"sec"},...(pb?[{key:"e95B",label:"B",unit:"秒",type:"sec"}]:[]),
      {key:"io",label:"平均输入 / 输出",unit:"token",type:"text"},{key:"inf",label:"最多积压",type:"int"},{key:"ok",label:"成功",type:"text"},{key:"note",label:"备注",type:"html"}],
      rows:pa.points.map(q=>{const z=pb?pb.points.find(x=>x.conc===q.conc):null;
        return{conc:q.conc,rps:q.req_s,rpsB:z&&z.req_s,t95:q.ttft_p95_s,e95:q.e2e_p95_s,e95B:z&&z.e2e_p95_s,io:`${fmtInt(q.prompt_tokens_avg)} / ${fmtInt(q.out_tokens_avg)}`,
          inf:q.max_inflight,ok:`${q.ok} / ${q.total}`,note:(retryTag(q)+(q.fail?` <span class="badge is-bad">失败 ${q.fail}</span>`:"")).trim()||"—"}})});
    charts.push(`<div class="scn-block"><div class="sub-h">${term("closed")}<span class="sub-h-note">请求池 ${fmtInt(pool.size)} 条${pool.wrapped?"（已循环使用，后面的请求可能因为重复内容复用而偏快）":""}${a.replay&&a.replay.file?" · "+esc(a.replay.file):""}</span></div>
      <div class="grid-2">${ccard(p+"RpRps",term("rps"),{desc:"横轴是同时请求数 · 越高越好",h:220})}${ccard(p+"RpE2e",term("e2e")+"（较慢的情况）",{desc:"越短越好",h:220})}</div></div>`);
  }
  if(oa){
    tables.push({id:p+"-replay-o",title:term("open"),columns:[{key:"rate",label:"目标速率",unit:"个/秒",type:"num",sticky:true},{key:"sent",label:"发出",type:"int"},
      {key:"done",label:"实际完成",unit:"个/秒",type:"num",digits:2},...(ob?[{key:"doneB",label:"B",unit:"个/秒",type:"num",digits:2}]:[]),
      {key:"lag",label:"跟得上吗",type:"status"},{key:"t95",label:"首字等待 较慢",unit:"秒",type:"sec"},{key:"e95",label:"完整响应 较慢",unit:"秒",type:"sec"},
      {key:"inf",label:"最多积压",type:"int"},{key:"ok",label:"成功",type:"text"}],
      rows:oa.points.map(q=>{const z=ob?ob.points.find(x=>x.rate===q.rate):null,lag=q.completed_rps!=null&&q.rate&&q.completed_rps<q.rate*0.9;
        return{rate:q.rate,sent:q.sent,done:q.completed_rps,doneB:z&&z.completed_rps,lag:lag?{tone:"bad",text:"跟不上"}:{tone:"good",text:"跟得上"},
          t95:q.ttft_p95_s,e95:q.e2e_p95_s,inf:q.max_inflight,ok:`${q.ok} / ${q.total}`}})});
    charts.push(`<div class="scn-block"><div class="sub-h">${term("open")}<span class="sub-h-note">按设定速率随机间隔地发请求；两次测试的发送时间点完全相同。${term("inflight")}一直往上涨，说明服务跟不上</span></div>
      <div class="grid-2">${ccard(p+"OlInf",term("inflight")+"数量随时间变化",{desc:"横轴是开始后的秒数",h:240})}${ccard(p+"OlRate","目标速率 vs 实际完成速率",{desc:"实际明显低于目标说明处理不过来",h:240})}</div></div>`);
  }
  return panel({id:p+"-replay",title:"回放真实请求",jump:"真实回放",desc:"用线上导出的真实请求施压",chart:`<div class="scn-list">${charts.join("")}</div>`,tables,tcols:1});
}
function drawReplay(a,b,p){
  const pa=phase(a,"replay"),pb=b?phase(b,"replay"):null;
  if(pa){
    const runs=[{tag:"A",color:C.a,pts:pa.points},pb?{tag:"B",color:C.b,pts:pb.points}:null].filter(Boolean);
    const concs=[...new Set(runs.flatMap(x=>x.pts.map(q=>q.conc)))].sort((x,y)=>x-y);
    const get=(x,c,k)=>{const q=x.pts.find(z=>z.conc===c);return q&&q[k]!=null?q[k]:null};
    lineChart(p+"RpRps",{cats:concs.map(String),xName:"同时请求数",unit:"个/秒",digits:2,series:runs.map(x=>({name:x.tag,color:x.color,data:concs.map(c=>get(x,c,"req_s"))})),area:true});
    lineChart(p+"RpE2e",{cats:concs.map(String),xName:"同时请求数",unit:"秒",digits:2,series:runs.map(x=>({name:x.tag,color:x.color,data:concs.map(c=>get(x,c,"e2e_p95_s"))}))});
  }
  const oa=phase(a,"openloop"),ob=b?phase(b,"openloop"):null;
  if(oa){
    const runs=[["A",oa,C.a],["B",ob,C.b]].filter(x=>x[1]);
    const series=[];
    runs.forEach(([tag,ph,base])=>ph.points.forEach((pt,j)=>{
      const ts=pt.inflight_ts||[];if(ts.length<2)return;
      const color=runs.length>1?base:C.series[j%C.series.length];
      series.push({name:`${runs.length>1?tag+" ":""}${pt.rate} 个/秒`,color,data:ts.map(([t,v])=>[t,v])});
    }));
    if(series.length){
      setChart(p+"OlInf",baseOption({color:series.map(s=>s.color),legend:legendOf(series.map(s=>s.name)),
        grid:{left:4,right:16,top:series.length>1?44:30,bottom:26,containLabel:true},
        xAxis:Object.assign(axisValue({fmt:v=>v+"s"}),{name:"开始后的秒数",nameLocation:"middle",nameGap:26,axisLine:{show:true,lineStyle:{color:C.axis}},splitLine:{show:false}}),
        yAxis:axisValue({name:"个"}),
        tooltip:Object.assign(baseOption().tooltip,{formatter:ps=>tt(`开始后 ${Math.round(ps[0].value[0])} 秒`,ps.map(q=>[q.color,q.seriesName,fmtInt(q.value[1])+" 个处理中"]))}),
        series:series.map(s=>Object.assign(sLine(s.name,s.color,s.data,{dots:false,area:series.length===1}),{symbolSize:0}))}));
    }else chartEmpty(p+"OlInf","没有记录处理中的请求数");
    const rates=[...new Set(runs.flatMap(([,ph])=>ph.points.map(q=>q.rate)))].sort((x,y)=>x-y);
    const done=runs.map(([tag,ph,c])=>({name:tag+" 实际完成",color:c,data:rates.map(r=>{const q=ph.points.find(z=>z.rate===r);return q?q.completed_rps:null})}));
    barChart(p+"OlRate",{cats:rates.map(r=>r+" 个/秒"),unit:"个/秒",digits:2,labels:true,series:[{name:"目标速率",color:C.axis,data:rates},...done]});
  }
}

/* ---------- 服务端状态: 曲线 + 指标摘要表 ---------- */
function metricsUsable(r){return (r.metrics_samples||[]).filter(m=>m.gpu_cache_usage!=null||m.prefix_cache_hit!=null)}
function engineSummary(r){
  const s=metricsUsable(r);if(!s.length)return[];
  const pct=(k,v)=>v==null?null:(k==="gpu_cache_usage"&&v<=1.05?v*100:v);
  const stats=(k,f=v=>v)=>{const xs=s.map(m=>f(m[k])).filter(v=>v!=null&&isFinite(v));
    return xs.length?{avg:xs.reduce((p,q)=>p+q,0)/xs.length,min:Math.min(...xs),max:Math.max(...xs),n:xs.length}:null};
  return [["显存缓存占用","%",stats("gpu_cache_usage",v=>pct("gpu_cache_usage",v))],["重复内容复用率","%",stats("prefix_cache_hit")],
    ["处理中的请求","个",stats("requests_running")],["排队的请求","个",stats("requests_waiting")]].filter(x=>x[2]).map(([name,unit,v])=>({name,unit,...v}));
}
function engineSection(a,b,p){
  if(!metricsUsable(a).length)return "";
  const spec={id:p+"-engine-t",title:"服务端指标摘要（测试 A）",columns:[{key:"name",label:"指标",type:"text",sticky:true},{key:"unit",label:"单位",type:"text"},
    {key:"avg",label:"平均",type:"num"},{key:"min",label:"最低",type:"num"},{key:"max",label:"最高",type:"num"},{key:"n",label:"采样次数",type:"int"}],rows:engineSummary(a)};
  return panel({id:p+"-engine",title:"服务端状态",jump:"服务端",desc:`测试期间服务端的${term("kv")}和${term("prefix")}（来自 vLLM /metrics）`,
    chart:ccard(p+"Eng",term("kv")+" 与 "+term("prefix"),{desc:"显存缓存接近 100% 时新请求要排队；复用率越高越省时",h:220}),tables:[spec]});
}
function drawEngine(a,b,p){
  const s=a.metrics_samples||[];if(!metricsUsable(a).length)return;
  const t0=s[0].t;
  const norm=(k,v)=>v==null?null:(k==="gpu_cache_usage"&&v<=1.05?v*100:v);
  const mk=(k,name,color)=>Object.assign(sLine(name,color,s.filter(m=>norm(k,m[k])!=null).map(m=>[Math.round(m.t-t0),norm(k,m[k]),m]),{dots:false,area:k==="gpu_cache_usage"}),{symbolSize:0});
  setChart(p+"Eng",baseOption({color:[C.a,C.b],legend:legendOf(["显存缓存占用","重复内容复用率"]),
    grid:{left:4,right:16,top:44,bottom:26,containLabel:true},
    xAxis:Object.assign(axisValue({fmt:v=>(s[s.length-1].t-t0)>120?`${Math.floor(v/60)}:${pad2(Math.round(v%60))}`:v+" 秒"}),{name:(s[s.length-1].t-t0)>120?"测试开始后（分:秒）":"测试开始后",nameLocation:"middle",nameGap:26,axisLine:{show:true,lineStyle:{color:C.axis}},splitLine:{show:false}}),
    yAxis:axisValue({name:"%",max:100}),
    tooltip:Object.assign(baseOption().tooltip,{formatter:ps=>{const m=ps[0].data[2]||{};
      return tt(`开始后 ${Math.round(ps[0].value[0])} 秒`,ps.map(q=>[q.color,q.seriesName,fmt(q.value[1])+"%"]),`处理中 ${fmtInt(m.requests_running||0)} 个 · 排队 ${fmtInt(m.requests_waiting||0)} 个`)}}),
    series:[mk("gpu_cache_usage","显存缓存占用",C.a),mk("prefix_cache_hit","重复内容复用率",C.b)]}));
}

/* ---------- 全部指标: 概览带里没放下的都在这里 ---------- */
function allMetricsSection(a,b,p){
  const ma=perfCtx(a),mb=b?perfCtx(b):null;
  const rows=[...PERF_METRICS,...CMP_EXTRA].map(k=>{
    const va=safeVal(k.val,ma),vb=mb?safeVal(k.val,mb):null;
    if(va==null&&vb==null)return null;
    const same=!mb||sameRef(k,ma,mb);
    return{name:metricLabel(k,ma),va,vb,unit:k.unit,_dir:k.dir,dirText:k.dir<0?"越低越好":"越高越好",digits:k.digits??1,
      d:mb&&same?pctChange(vb,va):null,cmp:mb?(same?{tone:"good",text:"可比"}:{tone:"warn",text:"档位不同",tip:`B 是${refText(k,mb)}`}):null,sub:safeSub(k,ma),tip:metricTip(k)};
  }).filter(Boolean);
  const num=(key)=>({key,type:"num",digitsOf:r=>r.digits,fmt:(v,r)=>metricVal({digits:r.digits,unit:r.unit},v)});
  const spec={id:p+"-all-t",title:mb?"全部指标 · A / B":"全部指标",columns:[{key:"name",label:"指标",type:"text",sticky:true,wrap:true},
    Object.assign(num("va"),{label:mb?"A":"数值"}),...(mb?[Object.assign(num("vb"),{label:"B"}),{key:"d",label:"A 比 B",type:"delta"},{key:"cmp",label:"可比性",type:"status"}]:[]),
    {key:"unit",label:"单位",type:"text"},{key:"dirText",label:"方向",type:"text"},{key:"sub",label:"说明",type:"text",wrap:true}],rows,maxH:340};
  return panel({id:p+"-all",title:"全部指标",jump:"全部指标",desc:"上面图表里的关键数字汇总在一张表里，可以排序、复制到 Excel 或导出",tables:[spec]});
}

/* ---------- 组装 ---------- */
function perfSectionsHTML(a,b,p){
  return [concSection,prefillSection,matrixSection,decodeSection,scnSection,replaySection,engineSection,longctxSection].map(f=>f(a,b,p)).join("");
}
function drawPerfCharts(a,b,p){
  [drawConc,drawPrefill,drawMatrix,drawDecode,drawLongctx,drawScn,drawReplay,drawEngine].forEach(f=>{
    try{f(a,b,p)}catch(e){console.error(f.name,e)}
  });
}
async function render(){
  if(!RUNS_LOADED)return;
  const idA=$("runA").value,idB=$("runB").value;
  const body=$("dashBody");
  if(!RUNS[idA]){
    body.hidden=true;buildJump("dashJump",null);
    $("dashEmpty").innerHTML=emptyState("还没有速度测试","测模型生成有多快、同时处理很多请求时稳不稳、输入很长时要等多久。点右上角「新建速度测试」开始，结果会显示在这里",
      {action:`<button class="btn btn-primary" data-toggle="launcher" data-online-only>${icon("plus")}新建速度测试</button>`});
    return;
  }
  const seq=++renderSeq;
  try{await ensureRuns([idA,RUNS[idB]&&idB!==idA?idB:""])}
  catch(e){$("dashEmpty").innerHTML=emptyState("加载测试详情失败",e.message,{iconName:"alert",inline:true});return}
  if(seq!==renderSeq)return;  /* 期间切换了选择, 以最新一次为准 */
  const a=FULL[idA],b=RUNS[idB]&&idB!==idA?FULL[idB]:null;
  $("dashEmpty").innerHTML="";body.hidden=false;
  const hints=perfAnomalies(a);
  body.innerHTML=overview(perfConclusions(a,b),perfStats(a,b),{meta:perfMetaLine(a)+(b?`<br>B：${esc(label(b))}`:"")})+
    (hints.length?`<div class="notes">${alertBox("warn",`<b>需要注意</b><ul class="hint-list">${hints.map(h=>`<li>${esc(h)}</li>`).join("")}</ul>`)}</div>`:"")+
    perfSectionsHTML(a,b,"d")+allMetricsSection(a,b,"d");
  disposeDetached();
  drawPerfCharts(a,b,"d");
  buildJump("dashJump",body);
}

/* ============================================================
   速度对比
   ============================================================ */
function swapCmp(){const a=$("cmpA").value,b=$("cmpB").value;if(!b)return;$("cmpA").value=b;$("cmpB").value=a;renderCmp()}
function runLine(r,tag,color){
  return `<span class="run-line"><span class="run-tag" style="background:${color}">${tag}</span><b>${esc(r.model||"?")}</b> · ${esc([runFw(r)||"推理框架未填写",(SUITE_NAME[r.suite]||r.suite||"")+"规模",r.tag,hostOf(r.url),timeText(r.started_utc)].filter(Boolean).join(" · "))}</span>`;
}
function cmpRows(a,b){
  const ma=perfCtx(a),mb=perfCtx(b);
  return [...PERF_METRICS,...CMP_EXTRA].map(k=>{
    const va=safeVal(k.val,ma),vb=safeVal(k.val,mb),same=sameRef(k,ma,mb),d=same?pctChange(vb,va):null;  /* A 比 B */
    return{k,label:metricLabel(k,ma),va,vb,d,same,refB:same?"":refText(k,mb),gain:d==null?null:d*k.dir};  /* gain>0 表示 A 更好 */
  }).filter(x=>x.va!=null||x.vb!=null);
}
/* 对好坏的影响: 更差 → 更好 → 持平 → 不可比 */
function cmpImpactOrder(rows){
  const rank=x=>x.gain==null?(x.same?3:4):x.gain<=-1?0:x.gain>=1?1:2;
  return [...rows].sort((p,q)=>rank(p)-rank(q)||(rank(p)<2?Math.abs(q.gain)-Math.abs(p.gain):0));
}
function cmpTableRows(rows){
  return rows.map(x=>({label:x.label,va:x.va,vb:x.vb,d:x.same?x.d:null,_dir:x.k.dir,unit:x.k.unit,digits:x.k.digits??1,dirText:x.k.dir<0?"越低越好":"越高越好",
    cmp:x.va==null||x.vb==null?{tone:"neutral",text:"缺一边"}:x.same?{tone:"good",text:"可比"}:{tone:"warn",text:"档位不同",tip:"B 是"+x.refB},
    judge:x.gain==null?null:Math.abs(x.gain)<1?{tone:"neutral",text:"持平"}:x.gain>0?{tone:"good",text:"A 更好"}:{tone:"bad",text:"A 更差"}}));
}
async function renderCmp(){
  if(!RUNS_LOADED)return;
  const idA=$("cmpA").value,idB=$("cmpB").value;
  const el=$("cmpBody");
  if(!RUNS[idA]){el.innerHTML=emptyState("还没有速度测试","把两次速度测试放在一起看谁更快、快多少。先在「速度测试」页完成至少两次测试");buildJump("cmpJump",null);return}
  if(!RUNS[idB]||idA===idB){
    el.innerHTML=`<div class="ov is-single"><div class="ov-concl"><div class="ov-h">测试 A</div>${runLine(RUNS[idA],"A",C.a)}</div></div><div style="margin-top:16px">`+
      emptyState("再选一个测试 B","比如换了推理框架、量化方式或显卡之后再测一次，放在一起比",{iconName:"compare"})+`</div>`;
    buildJump("cmpJump",null);return;
  }
  const seq=++cmpSeq;
  try{await ensureRuns([idA,idB])}catch(e){el.innerHTML=emptyState("加载测试详情失败",e.message,{iconName:"alert"});return}
  if(seq!==cmpSeq)return;
  const a=FULL[idA],b=FULL[idB];
  const rows=cmpRows(a,b),both=rows.filter(x=>x.gain!=null);
  const better=both.filter(x=>x.gain>=1).sort((p,q)=>q.gain-p.gain),worse=both.filter(x=>x.gain<=-1).sort((p,q)=>p.gain-q.gain);
  const notSame=rows.filter(x=>!x.same&&x.va!=null&&x.vb!=null);
  const concl=[];
  concl.push({tone:worse.length>better.length?"warn":better.length?"good":"info",
    html:`${both.length} 项可比的指标里，A 比 B：<b>${better.length}</b> 项更好、<b>${worse.length}</b> 项更差、${both.length-better.length-worse.length} 项基本持平（差别小于 1%）${notSame.length?`，另有 ${notSame.length} 项档位不同不可比`:""}。`});
  if(better.length)concl.push({tone:"good",html:"A 更好的地方："+better.slice(0,3).map(x=>`${esc(x.label)} <b>${fmt(Math.abs(x.d),1)}%</b>`).join("；")+"。"});
  if(worse.length)concl.push({tone:"bad",html:"A 更差的地方："+worse.slice(0,3).map(x=>`${esc(x.label)} <b>${fmt(Math.abs(x.d),1)}%</b>`).join("；")+"。"});
  if(notSame.length)concl.push({tone:"info",html:`没有计入（两次测试的档位不同，例如最多同时请求数、最长输入不一样）：${notSame.map(x=>esc(x.label)).join("、")}。`});
  const ov=[a,b].map(r=>(r.overrides||{}).fixed_output);
  if(ov[0]!==ov[1])concl.push({tone:"warn",html:"两次测试的输出长度设置不同（一次固定、一次不固定），速度类指标不能直接比较。"});
  /* 右侧: 变化最大的项目(最好 2 项 + 最差 2 项) */
  const top=[...better.slice(0,2),...worse.slice(0,2)];
  const stats=top.map(x=>stat(esc(x.label),metricVal(x.k,x.va),esc(x.k.unit),{delta:deltaPill(x.vb,x.va,x.k.dir,{prefix:"比 B "}),tip:metricTip(x.k),
    sub:`A ${metricVal(x.k,x.va)} · B ${metricVal(x.k,x.vb)} · ${x.k.dir<0?"越低越好":"越高越好"}`})).join("")+
    (top.length<4?stat("可比指标",`${better.length}<small>更好</small> ${worse.length}<small>更差</small>`,"",{sub:`${both.length-better.length-worse.length} 项持平${notSame.length?` · ${notSame.length} 项不可比`:""}`,wide:top.length%2===0}):"");
  const ordered=cmpImpactOrder(rows),trows=cmpTableRows(ordered);
  const num=(key,label)=>({key,label,type:"num",digitsOf:r=>r.digits,fmt:(v,r)=>metricVal({digits:r.digits,unit:r.unit},v)});
  const sizeNote=a.suite!==b.suite?`两次测试规模不同（${esc(SUITE_NAME[a.suite]||a.suite)} / ${esc(SUITE_NAME[b.suite]||b.suite)}），只比较两边都有的项目`:"";
  const compact={id:"c-all-c",title:"对比总表",sub:sizeNote,columns:[{key:"label",label:"指标",type:"text",sticky:true,wrap:true},num("va","A"),num("vb","B"),
    {key:"d",label:"A 比 B",type:"delta"},{key:"cmp",label:"可比性",type:"status"}],rows:trows,note:"默认按对好坏的影响排序：先更差、再更好"};
  const full={id:"c-all-t",title:"对比总表",sub:sizeNote,columns:[{key:"label",label:"指标",type:"text",sticky:true,wrap:true},num("va","A"),num("vb","B"),
    {key:"d",label:"A 比 B",type:"delta"},{key:"judge",label:"结论",type:"status"},{key:"cmp",label:"可比性",type:"status"},{key:"unit",label:"单位",type:"text"},{key:"dirText",label:"方向",type:"text"}],rows:trows};
  const h=Math.max(220,both.length*30+60);
  el.innerHTML=overview(concl,stats,{title:"对比结论",meta:runLine(a,"A",C.a)+runLine(b,"B",C.b)})+
    panel({id:"c-diff",title:"变化一览",jump:"变化一览",desc:"A 比 B：往右是 A 更好，往左是 A 更差；延迟类指标（越短越好）已按“好坏”方向换算。灰色表示差别小于 1%，基本持平",
      chart:`<div class="side-row is-rev">${dataTable(compact)}${ccard("cDiff","各项指标的变化（%）",{desc:"按对好坏的影响排序",h})}</div>`,tables:[full]})+
    perfSectionsHTML(a,b,"c");
  disposeDetached();
  drawDiffChart("cDiff",cmpImpactOrder(both));
  drawPerfCharts(a,b,"c");
  buildJump("cmpJump",el);
}
function drawDiffChart(id,rows){
  if(!rows.length){chartEmpty(id,"两次测试没有共同的指标");return}
  const lim=niceMax(Math.max(8,...rows.map(x=>Math.abs(x.gain)))*1.45);  /* 两端留出放文字标签的空间 */
  const colorOf=g=>Math.abs(g)<1?C.axis:(g>0?C.goodMark:C.badMark);
  setChart(id,baseOption({
    grid:{left:4,right:24,top:8,bottom:4,containLabel:true},
    xAxis:Object.assign(axisValue({min:-lim,max:lim,fmt:v=>(v>0?"+":"")+Math.round(v)+"%"}),{splitNumber:4}),
    yAxis:axisCat(rows.map(x=>x.label),{inverse:true,labelWidth:220,labelColor:C.text2}),
    tooltip:Object.assign(baseOption().tooltip,{trigger:"item",formatter:p=>{const x=rows[p.dataIndex],dg=x.k.digits??1;
      return tt(x.label,[["","A",fmt(x.va,dg)+" "+x.k.unit],["","B",fmt(x.vb,dg)+" "+x.k.unit]],
        `A 比 B ${x.d>=0?"+":""}${fmt(x.d,1)}% · ${Math.abs(x.gain)<1?"基本持平":x.gain>0?"A 更好":"A 更差"}（${x.k.dir<0?"越低越好":"越高越好"}）`)}}),
    series:[{type:"bar",barMaxWidth:18,data:rows.map(x=>({value:Math.max(-lim,Math.min(lim,x.gain)),itemStyle:{color:colorOf(x.gain),borderRadius:x.gain>=0?[0,4,4,0]:[4,0,0,4]}})),
      label:{show:true,position:"right",color:C.text2,fontSize:11,formatter:p=>{const g=rows[p.dataIndex].gain;return Math.abs(g)<1?"持平":(g>0?"更好 ":"更差 ")+fmt(Math.abs(g),1)+"%"}},
      labelLayout:p=>{const g=rows[p.dataIndex]&&rows[p.dataIndex].gain;return g<0?{x:p.rect.x-4,align:"right"}:{}},
      markLine:{silent:true,symbol:"none",label:{show:false},lineStyle:{color:C.axis,width:1,type:"solid"},data:[{xAxis:0}]}}]}));
}

/* ============================================================
   能力测试
   ============================================================ */
let IQ_RUNS={},IQ_BANKS=[],IQ_LOADED=false,iqPoll=null;
const IQ_CMP=new Set();
const iqLog=LogBox("iqLog","iq");
const bankLog=LogBox("bankLog","bank");
bindFormMemory("llm-bench-pro-iq-form",["iqBase","iqModel","iqConc","iqTag","iqTier","iqProxy","iqBankSrc","iqSampling","iqTemp","iqTopP","iqTopK",
  "iqBudMcq","iqBudMath","iqBudMath500","iqBudInstruct"]);
function samplingFields(){document.querySelectorAll("[data-custom-sampling]").forEach(f=>f.hidden=$("iqSampling").value!=="custom")}
$("iqSampling").addEventListener("change",samplingFields);
samplingFields();
function samplingBody(){
  const v=$("iqSampling").value;
  return v==="custom"?{temperature:$("iqTemp").value,top_p:$("iqTopP").value,top_k:$("iqTopK").value}:v;
}
function samplingText(s){
  if(!s)return"";
  if(!s.temperature)return"每次取最可能的答案（temperature 0）";
  return [`temperature ${s.temperature}`,s.top_p!=null?`top_p ${s.top_p}`:"",s.top_k!=null?`top_k ${s.top_k}`:"",s.seed!=null?`随机种子 ${s.seed}`:""].filter(Boolean).join(" · ");
}
const IQ_CMP_CACHE={};
function iqCompare(a,b){
  const k=a+"|"+b;
  if(!IQ_CMP_CACHE[k])IQ_CMP_CACHE[k]=getJSON(`/api/iq-compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`).catch(()=>null);
  return IQ_CMP_CACHE[k];
}
const fmtP=p=>p==null?"—":(p<0.001?"<0.001":p.toFixed(3));
async function iqResume(runId){
  const r=IQ_RUNS[runId];
  const d=await postWithConflict("/api/iq-resume",{run_id:runId,api_key:$("iqKey").value});
  if(!d)return;
  if(!d.ok){toast("接着跑失败："+d.error,"error");return}
  toggleLauncher("iqLauncher",true);
  watchIq("接着跑 · "+(r?iqLabel(r):runId));
}
async function loadBanks(){
  try{
    IQ_BANKS=await getJSON("/api/banks");
    const sel=$("iqBank"),keep=sel.value;
    sel.innerHTML=IQ_BANKS.map(b=>`<option value="${esc(b.bank_id)}">${esc(b.bank_id)} · ${b.total} 题 · ${esc((b.created_utc||"").slice(0,10))}</option>`).join("");
    if(keep&&IQ_BANKS.find(b=>b.bank_id===keep))sel.value=keep;
    bankInfo();
    loadDataStatus();
  }catch(e){$("iqBankInfo").textContent="题集列表加载失败："+e.message}
}
function bankInfo(){
  const b=IQ_BANKS.find(x=>x.bank_id===$("iqBank").value);
  $("iqBankInfo").textContent=b?`共 ${b.total} 题：`+(b.subjects||[]).map(s=>`${s.name} ${s.n}`).join("、"):"还没有题集，请在「更多设置」里点「更新题集」";
}
/* 更新题集(后台任务): 缺少的题集数据先下载到本地, 再只用本地数据生成题库; 本地数据齐全时不联网 */
async function bankUpdate(){
  const d=await postJSON("/api/bank-update",{proxy:$("iqProxy").value||"",source:$("iqBankSrc").value});
  if(!d.ok){msg("iqMsg","error","题集更新没有开始："+d.error);return}
  watchBank("更新题集");
}
let bankPoll=null;
function watchBank(title){
  const btn=$("iqBtnBank");setBusy(btn,true);
  bankLog.start(title);clearInterval(bankPoll);
  bankPoll=pollStatus("/api/bank-status",bankLog,{interval:1000,onDone:async s=>{
    setBusy(btn,false);
    await loadBanks();
    if(s.run_id&&IQ_BANKS.find(b=>b.bank_id===s.run_id)){$("iqBank").value=s.run_id;bankInfo();iqLauncherSummary()}
  }});
}
/* 本地题集数据: 齐全时可以完全离线生成题库 */
async function loadDataStatus(){
  const el=$("iqDataInfo");if(!el||OFF)return;
  try{
    const s=await getJSON("/api/datasets");
    const miss=s.datasets.filter(x=>!x.ready).map(x=>x.name);
    el.textContent=!miss.length?"本地已有全部题集数据，更新题集不需要联网":
      miss.length===s.datasets.length?"本地还没有题集数据，第一次更新会先下载（约 23 MB）":`本地还缺 ${miss.join("、")} 的数据，更新时会先下载`;
    el.title="本地数据目录："+s.dir;
  }catch(e){el.textContent=""}
}
async function iqStart(){
  const model=$("iqModel").value.trim();
  if(!model){msg("iqMsg","error","请填写模型名称");$("iqModel").focus();return}
  if(!$("iqBank").value){msg("iqMsg","error","请先选择或更新题集");return}
  const bud={};[["mcq","iqBudMcq"],["math","iqBudMath"],["math500","iqBudMath500"],["instruct","iqBudInstruct"]]
    .forEach(([k,id])=>{const v=parseInt($(id).value);if(isFinite(v)&&v>=8)bud[k]=v});
  const d=await postWithConflict("/api/iq-start",{base:$("iqBase").value,api_key:$("iqKey").value,model,bank_id:$("iqBank").value,
    conc:$("iqConc").value,tag:$("iqTag").value,limit:$("iqTier").value||null,thinking:$("iqThink").checked,sampling:samplingBody(),
    budgets:Object.keys(bud).length?bud:undefined});
  if(!d)return;
  if(!d.ok){msg("iqMsg","error",d.error);return}
  msg("iqMsg","",null);
  watchIq("进行中 · "+model);
}
function watchIq(title){
  $("iqBtnStart").disabled=true;iqLog.start(title);
  clearInterval(iqPoll);
  iqPoll=pollStatus("/api/iq-status",iqLog,{onDone:()=>{$("iqBtnStart").disabled=false;loadIqResults(true)}});
}
function iqLabel(r){
  const acc=r.overall&&r.overall.acc!=null?r.overall.acc+"%":(STATUS_NAME[r.status]||"未完成");
  return [r.model||"?",runFw(r),r.thinking?"思考":"不思考",acc,r.tag||"",shortTime(r.started_utc)].filter(Boolean).join(" · ");
}
async function loadIqResults(focusNew){
  if(!IQ_LOADED)$("iqResult").innerHTML=skeletonPage();
  try{
    const list=await getJSON("/api/iq-results");
    Object.keys(IQ_CMP_CACHE).forEach(k=>delete IQ_CMP_CACHE[k]);
    const prev=new Set(Object.keys(IQ_RUNS));
    IQ_RUNS={};list.forEach(r=>IQ_RUNS[r.run_id]=r);IQ_LOADED=true;
    const names=Object.keys(IQ_RUNS).sort().reverse();
    const fresh=focusNew?names.find(n=>!prev.has(n)):null;
    const keep=fresh||(IQ_RUNS[$("iqMainSel").value]?$("iqMainSel").value:names[0]);
    $("iqMainSel").innerHTML=names.map(n=>`<option value="${esc(n)}" ${n===keep?"selected":""}>${esc(iqLabel(IQ_RUNS[n]))}</option>`).join("");
    [...IQ_CMP].forEach(id=>{if(!IQ_RUNS[id])IQ_CMP.delete(id)});
    if(!names.length&&VIEW==="iq")toggleLauncher("iqLauncher",true);
    renderIq();
  }catch(e){$("iqResult").innerHTML=emptyState("无法加载测试结果",e.message,{iconName:"alert"})}
}
function renderIqCmpList(mainId){
  const names=Object.keys(IQ_RUNS).sort().reverse().filter(n=>n!==mainId);
  IQ_CMP.delete(mainId);
  $("iqCmpList").innerHTML=names.length?names.map(n=>`<label class="option-row"><input type="checkbox" value="${esc(n)}" ${IQ_CMP.has(n)?"checked":""}>
    <span class="grow">${esc(iqLabel(IQ_RUNS[n]))}</span></label>`).join(""):`<div class="option-row faint">没有其他测试</div>`;
  $("iqCmpLabel").textContent=IQ_CMP.size?`对比中（${IQ_CMP.size}）`:"加入对比";
}
$("iqCmpList").addEventListener("change",e=>{
  if(e.target.type!=="checkbox")return;
  e.target.checked?IQ_CMP.add(e.target.value):IQ_CMP.delete(e.target.value);
  renderIq();
});
function budgetText(r){
  if(r.thinking)return "思考模式 · 每题最长 32K token";
  const b=(r.params&&r.params.budgets)||{mcq:16,math:2048,math500:4096,instruct:320};
  return `每题最长：选择题 ${b.mcq} · GSM8K ${b.math} · MATH-500 ${b.math500} · 按要求作答 ${b.instruct} token`;
}
function tokStat(r){
  const ss=r.subjects||[];
  const inT=ss.reduce((t,x)=>t+(x.in_tokens||0),0),outT=ss.reduce((t,x)=>t+(x.out_tokens||0),0),n=ss.reduce((t,x)=>t+(x.n||0),0);
  return{inT,outT,per:n?outT/n:null};
}
function verLt(v,target){const a=String(v||"0").split(".").map(Number),b=target.split(".").map(Number);for(let i=0;i<3;i++){if((a[i]||0)!==b[i])return (a[i]||0)<b[i]}return false}
function iqVersionWarning(r){
  if(verLt(r.iq_version,"1.1.0")&&r.thinking)return `这次测试用的是旧版评测程序（${r.iq_version}）：思考模式下选择题最多只能写 8 个 token，思考被截断后全部记错，MATH-500 判分也有问题，分数不可信，请重新测试`;
  if(verLt(r.iq_version,"1.1.0"))return `这次测试用的是旧版评测程序（${r.iq_version}）：MATH-500 判分有问题（全判错），总分偏低，请重新测试`;
  if(verLt(r.iq_version,"1.2.0")&&r.thinking)return `这次测试用的是 ${r.iq_version} 版评测程序：思考模式能写的长度偏短，想得久的题会被截断记错，建议重新测试`;
  if(verLt(r.iq_version,"1.3.0")&&!r.thinking)return `这次测试用的是 ${r.iq_version} 版评测程序：数学题能写的长度偏短（900 / 1280 token），部分题会被截断记错，数学分偏低`;
  if(verLt(r.iq_version,"1.3.0")&&r.thinking)return `这次测试用的是 ${r.iq_version} 版评测程序：思考模式没有加随机性，容易反复绕圈被截断，建议用新版重新测试`;
  if(verLt(r.iq_version,"1.4.0"))return `这次测试用的是 ${r.iq_version} 版评测程序：之后修正了答案识别、MATH-500 等价判断和部分按要求作答的规则，限题量时 MMLU 只覆盖少数学科，请求失败的题也记为答错。与 1.4.0 之后的分数不宜直接比较`;
  return "";
}
function iqIssues(r){
  const o=r.overall||{},out=[];
  if(o.truncated)out.push(`${o.truncated} 题没答完`);
  if(o.errors)out.push(`${o.errors} 题请求失败`);
  return out;
}
const shortSub=n=>String(n||"").replace(/（官方）|\(官方\)|\(中文\)|（中文）/g,"").trim();
/* 雷达图顶点名称: MMLU 保留分组(中学/大学…), 其他只留题集名 */
const radarName=n=>{const t=shortSub(n);return /^MMLU/.test(t)?t:t.split(/\s+/)[0]};
function renderIq(){  /* 渲染出错时明确显示错误, 不静默白屏 */
  try{_renderIq()}
  catch(e){
    console.error("renderIq failed:",e);
    const el=$("iqResult");
    if(el)el.innerHTML=emptyState("结果显示出错",String((e&&e.message)||e),{iconName:"alert",inline:true});
  }
}
function iqSeries(a){
  return [{r:a,color:C.series[0],tag:"A"},...[...IQ_CMP].filter(id=>IQ_RUNS[id]).slice(0,5).map((id,i)=>({r:IQ_RUNS[id],color:C.series[i+1],tag:String.fromCharCode(66+i)}))];
}
/* 百分点差值: 小于 0.5 个百分点视为持平 */
function ppText(v){
  if(v==null||!isFinite(v))return `<span class="dt-delta flat">—</span>`;
  if(Math.abs(v)<.5)return `<span class="dt-delta flat">${icon("minus","icon-sm")}持平</span>`;
  return `<span class="dt-delta ${v>0?"up":"down"}">${icon(v>0?"arrow-up":"arrow-down","icon-sm")}${v>0?"+":""}${fmt(v,1)}</span>`;
}
const IQ_SIG=new Map();  /* "A|B" -> iq-compare 结果, 用于排行表的「差异是否可信」列 */
function iqSubjRows(series){
  const a=series[0].r;
  const subs=[...(a.subjects||[])].filter(x=>x.n).sort((x,y)=>(y.acc||0)-(x.acc||0));
  return subs.map(sub=>{
    const row={sid:sub.id,name:shortSub(sub.name),full:sub.name,n:sub.n,correct:sub.correct,ci:`${fmt(sub.ci_lo,1)}–${fmt(sub.ci_hi,1)}`,
      trunc:sub.truncated,err:sub.errors,act:`<button type="button" class="btn btn-ghost btn-sm" data-qb-go="${esc(sub.id)}" data-qb-filter="${sub.correct<sub.n?"bad":"all"}">${sub.correct<sub.n?`看错题 ${sub.n-sub.correct}`:"看题目"}</button>`};
    series.forEach((s,i)=>{
      const x=(s.r.subjects||[]).find(y=>y.id===sub.id);
      row["acc_"+i]=x?x.acc:null;row["tok_"+i]=x&&x.n?x.out_tokens/x.n:null;
      if(i){
        row["d_"+i]=x&&sub.acc!=null?sub.acc-x.acc:null;  /* A 比它 */
        const sig=IQ_SIG.get(a.run_id+"|"+s.r.run_id),t=sig&&sig.ok&&sig.same_bank&&sig.subjects&&sig.subjects[sub.id];
        row["sig_"+i]=!sig?{tone:"neutral",text:"计算中"}:!t||!t.n?{tone:"neutral",text:"—"}:t.significant?{tone:"good",text:"可信",tip:"p = "+fmtP(t.p)}:{tone:"neutral",text:"不明显",tip:"p = "+fmtP(t.p)};
      }
    });
    return row;
  });
}
function iqSubjSpecs(series){
  const rows=iqSubjRows(series),multi=series.length>1;
  const accCol=(s,i)=>({key:"acc_"+i,label:multi?s.tag:"正确率",unit:multi?"":"%",group:multi?"正确率（%）":"",type:"bar",color:s.color,max:100});
  const compact={id:"iq-subj-c",title:"科目排行",columns:[{key:"name",label:"科目",type:"text",sticky:true},...series.map(accCol),
      ...(multi?series.slice(1).map((s,i)=>({key:"sig_"+(i+1),label:`A 与 ${s.tag}`,group:"差异是否可信",type:"status",tip:TERMS.sig.desc})):[{key:"ci",label:"误差范围",unit:"%",type:"text",align:"right",tip:TERMS.ci.desc}]),
      {key:"n",label:"题数",type:"int"},{key:"act",label:"",type:"html",noSort:true}],rows,search:false};
  const full={id:"iq-subj-t",title:"科目排行",columns:[{key:"name",label:"科目",type:"text",sticky:true},{key:"n",label:"题数",type:"int"},...series.map(accCol),
      ...(multi?series.slice(1).map((s,i)=>({key:"d_"+(i+1),label:`A 比 ${s.tag}`,group:"差距（百分点）",type:"num",fmt:ppText,sortValue:r=>r["d_"+(i+1)]})):[]),
      ...(multi?series.slice(1).map((s,i)=>({key:"sig_"+(i+1),label:`A 与 ${s.tag}`,group:"差异是否可信",type:"status"})):[{key:"ci",label:"误差范围",unit:"%",type:"text",align:"right"},{key:"correct",label:"答对",type:"int"}]),
      ...series.map((s,i)=>({key:"tok_"+i,label:multi?s.tag:"每题 token",group:multi?"平均每题输出 token":"",type:"int",tip:"平均每题输出多少 token，越少越省"})),
      {key:"trunc",label:"没答完",type:"int"},{key:"err",label:"请求失败",type:"int"},{key:"act",label:"",type:"html",noSort:true}],rows};
  return{compact,full};
}
function _renderIq(){
  if(!IQ_LOADED)return;
  const el=$("iqResult");
  const mainId=$("iqMainSel").value,a=IQ_RUNS[mainId];
  renderIqCmpList(mainId);
  if(!a){el.innerHTML=emptyState("还没有能力测试","用公开的标准考题（数学、常识、推理、中文、按要求作答）考模型，看答对多少。点右上角「新建能力测试」开始",
    {action:`<button class="btn btn-primary" data-toggle="iqLauncher" data-online-only>${icon("plus")}新建能力测试</button>`});buildJump("iqJump",null);return}
  const series=iqSeries(a);
  const base=a.overall||{};
  /* ---- 提示 ---- */
  let alerts="";
  series.forEach(s=>{const w=iqVersionWarning(s.r);if(w)alerts+=alertBox("warn",`<b>${s.tag}</b>：${esc(w)}`)});
  if(Array.isArray(a.warnings)&&a.warnings.length)alerts+=alertBox("warn",`<b>A 自检提示</b>：${a.warnings.map(esc).join("；")}`);
  const errN=(a.overall||{}).errors||0;
  if(a.status==="done"&&errN&&SERVER.iq_version&&a.iq_version===SERVER.iq_version)
    alerts+=alertBox("info",`A 有 ${errN} 题请求失败（已记为答错）。重试只会重新回答这些题，其他结果不变。`,
      `<button class="btn btn-secondary btn-sm" data-online-only onclick="iqResume('${esc(a.run_id)}')">${icon("play")}重试失败的题</button>`);
  if(["cancelled","interrupted","failed"].includes(a.status)){
    const canResume=SERVER.iq_version&&a.iq_version===SERVER.iq_version;
    const doneN=(a.subjects||[]).reduce((t,x)=>t+(x.n||0),0);
    alerts+=alertBox("info",`A ${esc(STATUS_NAME[a.status]||a.status)}${a.error?"（"+esc(a.error)+"）":""}：已完成 ${a.subjects?a.subjects.length:0} 个科目共 ${doneN} 题，没做完的科目里已答的题也保存了，请求失败的题接着跑时会重新回答。${canResume?"接着跑会沿用原来的服务地址、采样和题量，使用新建面板里填的 API Key。":"这次测试由其他版本的评测程序生成，不能接着跑。"}`,
      canResume?`<button class="btn btn-secondary btn-sm" data-online-only onclick="iqResume('${esc(a.run_id)}')">${icon("play")}接着跑</button>`:"");
  }
  const mismatch=series.slice(1).filter(s=>s.r.bank_id!==a.bank_id);
  const pkey=r=>JSON.stringify([r.params&&r.params.subject_ids||null,r.params&&r.params.limit_per_subject||null]);
  const pdiff=series.slice(1).filter(s=>s.r.bank_id===a.bank_id&&pkey(s.r)!==pkey(a));
  if(pdiff.length)alerts+=alertBox("warn",`题量设置不一样：${pdiff.map(s=>esc(s.tag)).join("、")} 和 A 选的科目或每科题数不同，总分覆盖的题不同，请以各科成绩和“差异是否可信”为准`);
  if(mismatch.length)alerts+=alertBox("warn",`题集版本不一样：${mismatch.map(s=>esc(s.tag+"（"+s.r.bank_id+"）")).join("、")} 和 A（${esc(a.bank_id)}）用的不是同一套题，分数不能直接比`);
  /* ---- 结论 ---- */
  const subs=[...(a.subjects||[])].filter(x=>x.n);
  const sorted=[...subs].sort((x,y)=>(y.acc||0)-(x.acc||0));
  const concl=[];
  if(base.n)concl.push({tone:"info",html:`A 一共答对 <b>${base.correct}</b> / ${base.n} 题，正确率 <b>${fmt(base.acc,1)}%</b>（${term("ci")} ${fmt(base.ci_lo,1)}–${fmt(base.ci_hi,1)}%）。`});
  if(sorted.length>=3){
    concl.push({tone:"good",html:"最擅长："+sorted.slice(0,2).map(x=>`${esc(shortSub(x.name))} <b>${fmt(x.acc,1)}%</b>`).join("、")+"。"});
    concl.push({tone:"warn",html:"最弱："+sorted.slice(-2).reverse().map(x=>`${esc(shortSub(x.name))} <b>${fmt(x.acc,1)}%</b>`).join("、")+"。"});
  }
  if(base.truncated)concl.push({tone:"warn",html:`有 <b>${base.truncated}</b> 题${term("trunc")}（写到长度上限被停下），记为答错。${a.thinking?"思考模式下想得太久会出现这种情况。":"可以在「更多设置」里调大这类题的最长长度。"}`});
  if(base.errors)concl.push({tone:"bad",html:`有 <b>${base.errors}</b> 题请求失败，记为答错，可以点「重试失败的题」。`});
  /* ---- 概览带右侧: A 的总正确率 + 每个对比对象一行成绩条 ---- */
  const tk=tokStat(a);
  let stats=stat(`<span class="run-line"><span class="run-tag" style="background:${C.a}">A</span><b>${esc(a.model||"?")}</b>${runFw(a)?" · "+esc(runFw(a)):""}</span>`,
    base.acc!=null?fmt(base.acc,1):"—","%",{hero:true,wide:true,
    sub:base.n?`${term("ci")} ${fmt(base.ci_lo,1)}–${fmt(base.ci_hi,1)}% · 答对 ${base.correct} / ${base.n} 题${base.macro_acc!=null?` · ${term("macro")} ${fmt(base.macro_acc,1)}%`:""}<br>${a.thinking?"思考模式":"不思考"} · ${esc(samplingText(a.sampling)||"采样未记录")}${tk.per!=null?` · 平均每题输出 ${fmt(tk.per,0)} token`:""}${iqIssues(a).length?`<br><span class="warn">${esc(iqIssues(a).join(" · "))}</span>`:""}`
      :`测试没有完成（${esc(STATUS_NAME[a.status]||a.status||"")}）`});
  series.slice(1).forEach(s=>{
    const o=s.r.overall||{};
    stats+=`<div class="stat is-wide cmp-line"><div class="cmp-line-head"><span class="run-tag" style="background:${s.color}">${s.tag}</span>
        <span class="cmp-line-name">${esc((s.r.model||"?")+(runFw(s.r)?" · "+runFw(s.r):""))} · ${s.r.thinking?"思考":"不思考"}</span>
        <span class="cmp-line-acc">${o.acc!=null?fmt(o.acc,1):"—"}<small>%</small></span>${deltaPill(o.acc,base.acc,1,{mode:"pp",prefix:"A 比它 "})}</div>
      <div class="cmp-line-sig" data-sig-card="${esc(s.r.run_id)}">正在计算差异是否可信…</div></div>`;
  });
  /* ---- 各科得分: 排行表为主, 旁边是条形图 / 能力形状 ---- */
  const {compact,full}=iqSubjSpecs(series);
  const barH=Math.max(260,subs.length*(series.length*16+14)+70);
  const subjTab=CTAB.subj==="radar"?"radar":"bars";
  const chartTabs=`<div class="ccard" data-ctab-card="subj"><div class="ccard-head"><div><h3 class="ccard-title">各科正确率</h3><p class="ccard-desc">越高越好 · 点柱子看这一科的题${series.length===1?" · 横线是"+term("ci"):""}</p></div>
      ${segHTML("data-ctab",subjTab,[["bars","条形"],["radar","能力形状"]])}</div>
    <div class="chart" id="iqBars" data-ctab-pane="bars" style="height:${barH}px" role="img" aria-label="各科正确率"${subjTab==="bars"?"":" hidden"}></div>
    <div class="chart" id="iqRadar" data-ctab-pane="radar" style="height:${Math.min(460,Math.max(340,barH))}px" role="img" aria-label="能力形状"${subjTab==="radar"?"":" hidden"}></div></div>`;
  /* 正确率和每题 token: 折线(默认) / 散点 */
  const tokTab=CTAB.tok==="scatter"?"scatter":"line";
  const tokDesc={line:`科目按${series.length>1?" A 的":""}每题 token 从少到多排：上面是正确率，下面是平均每题输出多少 token（对数刻度）`,
    scatter:"每个点是一个科目：越靠上答得越好，越靠左越省 token（横轴是对数刻度）"+(series.length>1?"；同一科目的 A、B 用细线连起来":"")};
  const tokCard=`<div class="ccard" data-ctab-card="tok"><div class="ccard-head"><div><h3 class="ccard-title">正确率和每题 token</h3><p class="ccard-desc" data-ctab-desc>${tokDesc[tokTab]}</p></div>
      ${segHTML("data-ctab",tokTab,[["line","折线"],["scatter","散点"]])}</div>
    <div class="chart" id="iqTok" data-ctab-pane="line" data-desc="${esc(tokDesc.line)}" style="height:430px" role="img" aria-label="各科正确率和每题 token（折线）"${tokTab==="line"?"":" hidden"}></div>
    <div class="chart" id="iqTokScatter" data-ctab-pane="scatter" data-desc="${esc(tokDesc.scatter)}" style="height:380px" role="img" aria-label="正确率 × 平均每题输出 token（散点）"${tokTab==="scatter"?"":" hidden"}></div></div>`;
  const hasMmlu=subs.some(x=>/^mmlu/.test(x.id));
  el.innerHTML=overview(concl,stats,{meta:`题集 ${esc(a.bank_id||"")} · ${esc(budgetText(a))} · 开始于 ${esc(timeText(a.started_utc))}`})+
    (alerts?`<div class="notes">${alerts}</div>`:"")+
    panel({id:"iq-subj",title:"各科得分",jump:"各科得分",desc:series.length>1?"按 A 的成绩从高到低排列；「差异是否可信」按同一批题逐题比较（McNemar 检验）":"按成绩从高到低排列；点「看错题」直接跳到下面这一科答错的题",
      chart:`<div class="side-row">${dataTable(compact)}${chartTabs}</div>`,tables:[full]})+
    (hasMmlu?panel({id:"iq-mmlu",title:"MMLU 各学科",jump:"MMLU 学科",desc:"只有 MMLU 在题库里记了每道题属于哪个学科，这里把它的四个分组展开到 53 个具体学科（每个学科题数不多，正确率仅供参考）。ARC、GSM8K、MATH-500、HellaSwag、C-Eval、指令遵循没有更细的分类，它们的正确率就是上面「科目排行」里的那一行",
      tables:[`<div id="iqMmlu"><div class="qb-loading faint">正在按学科统计…</div></div>`]}):"")+
    panel({id:"iq-cost",title:"正确率和 token 花费",jump:"token 花费",desc:"每个科目答对了多少、平均每道题输出多少 token；点某一科可以直接看这一科的题",
      chart:tokCard,
      tables:[{id:"iq-cost-t",title:"各科正确率与 token",columns:[{key:"name",label:"科目",type:"text",sticky:true},
        ...series.map((s,i)=>({key:"acc_"+i,label:series.length>1?s.tag:"正确率",group:series.length>1?"正确率（%）":"",unit:series.length>1?"":"%",type:"num"})),
        ...series.map((s,i)=>({key:"tok_"+i,label:series.length>1?s.tag:"每题 token",group:series.length>1?"平均每题输出 token":"",type:"int"}))],rows:iqSubjRows(series)}]})+
    qbSectionHTML(series);
  disposeDetached();
  drawIqCharts(series);
  buildJump("iqJump",el);
  qbInit(series);
  /* 差异是否可信: 同一批题逐题比较, 结果异步填入概览与排行表 */
  series.slice(1).forEach(s=>iqCompare(a.run_id,s.r.run_id).then(d=>{
    IQ_SIG.set(a.run_id+"|"+s.r.run_id,d||{ok:false});
    const card=document.querySelector(`[data-sig-card="${CSS.escape(s.r.run_id)}"]`);
    ["iq-subj-c","iq-subj-t"].forEach(id=>{const sp=DT.specs.get(id);if(sp&&$("iqResult").contains(document.querySelector(`[data-dt="${id}"]`))){sp.rows=iqSubjRows(series);dtRefresh(id)}});
    if(!card)return;
    if(!d||!d.ok){card.textContent="暂时无法判断差异是否可信";return}
    if(!d.same_bank){card.textContent="题集不同，无法逐题比较";return}
    if(!d.overall.n||d.overall.significant==null){card.textContent="没有双方都正常作答的共同题目，无法比较";return}
    const o=d.overall;
    const go=(f,txt)=>`<a href="javascript:void 0" class="qb-link" data-qb-go="" data-qb-filter="${f}" data-qb-vs="${esc(s.r.run_id)}" title="在「逐题查看」里列出这些题">${txt}</a>`;
    card.innerHTML=`<span class="sig ${o.significant?"yes":"no"}">${o.significant?"差异可信":"差异不明显，可能是随机波动"}</span> · ${go("vs-a",`只有 A 答对 ${o.a_only} 题`)} · ${go("vs-b",`只有 ${esc(s.tag)} 答对 ${o.b_only} 题`)}`;
    card.title=`${TERMS.sig.tech}：共同题目 ${o.n} 道，p = ${fmtP(o.p)}`;
  }));
}
function drawIqCharts(series){
  const a=series[0].r;
  const subs=[...(a.subjects||[])].filter(x=>x.n).sort((x,y)=>(y.acc||0)-(x.acc||0));
  if(!subs.length){["iqBars","iqRadar","iqTok","iqTokScatter"].forEach(id=>chartEmpty(id));return}
  const names=subs.map(x=>shortSub(x.name));
  const valOf=(s,sub,f)=>{const x=(s.r.subjects||[]).find(y=>y.id===sub.id);return x?f(x):null};
  /* 各科正确率: 横向柱; 只看 A 时加误差范围 */
  const barSeries=series.map(s=>sBar(s.tag,s.color,subs.map(sub=>valOf(s,sub,x=>x.acc)),{horizontal:true,grouped:series.length>1}));
  if(series.length===1)barSeries[0].label={show:true,position:"insideLeft",color:"#fff",fontSize:11,fontWeight:600,formatter:p=>p.value>=12?fmt(p.value,1)+"%":""};
  if(series.length===1)barSeries.push({type:"custom",name:"误差范围",z:10,silent:true,tooltip:{show:false},
    data:subs.map((x,i)=>[i,x.ci_lo,x.ci_hi]),encode:{x:[1,2],y:0},
    renderItem:(params,api)=>{
      const i=api.value(0),p1=api.coord([api.value(1),i]),p2=api.coord([api.value(2),i]),h=7,st={stroke:C.text2,lineWidth:1};
      return{type:"group",children:[{type:"line",shape:{x1:p1[0],y1:p1[1],x2:p2[0],y2:p2[1]},style:st},
        {type:"line",shape:{x1:p1[0],y1:p1[1]-h/2,x2:p1[0],y2:p1[1]+h/2},style:st},{type:"line",shape:{x1:p2[0],y1:p2[1]-h/2,x2:p2[0],y2:p2[1]+h/2},style:st}]};
    }});
  const barsInst=setChart("iqBars",baseOption({
    color:series.map(s=>s.color),legend:legendOf(series.map(s=>s.tag),"rect"),
    grid:{left:4,right:16,top:series.length>1?40:12,bottom:4,containLabel:true},
    xAxis:axisValue({min:0,max:100,fmt:v=>v+"%"}),yAxis:axisCat(names,{inverse:true,labelWidth:130,labelColor:C.text2}),
    tooltip:Object.assign(baseOption().tooltip,{axisPointer:{type:"shadow",shadowStyle:{color:"rgba(128,128,128,.08)"}},formatter:ps=>{
      const sub=subs[ps[0].dataIndex];
      return tt(sub.name,series.map(s=>{const x=(s.r.subjects||[]).find(y=>y.id===sub.id);
        return [s.color,s.tag,x?`${fmt(x.acc,1)}%（${x.correct}/${x.n}）`:"—"]}),series.length===1?`误差范围 ${fmt(sub.ci_lo,1)}–${fmt(sub.ci_hi,1)}%`:"")}}),
    series:barSeries}));
  if(barsInst){barsInst.off("click");barsInst.on("click",p=>{if(p.seriesType==="bar"&&subs[p.dataIndex])qbGo(subs[p.dataIndex].id,"all")})}
  /* 能力形状: 雷达(第二个标签) */
  setChart("iqRadar",baseOption({
    color:series.map(s=>s.color),legend:legendOf(series.map(s=>s.tag)),
    tooltip:Object.assign(baseOption().tooltip,{trigger:"item",formatter:p=>tt(series[p.dataIndex]?series[p.dataIndex].tag:"",subs.map((sub,i)=>["",names[i],p.value[i]!=null?fmt(p.value[i],1)+"%":"—"]))}),
    radar:{indicator:subs.map(sub=>({name:radarName(sub.name),max:100})),radius:"64%",center:["50%","56%"],splitNumber:4,
      axisName:{color:C.text2,fontSize:11},splitLine:{lineStyle:{color:C.grid}},splitArea:{show:false},axisLine:{lineStyle:{color:C.grid}}},
    series:[{type:"radar",symbolSize:6,data:series.map(s=>({name:s.tag,value:subs.map(sub=>valOf(s,sub,x=>x.acc)),
      lineStyle:{width:2,color:s.color},itemStyle:{color:s.color,borderColor:C.surface,borderWidth:1},areaStyle:{color:withAlpha(s.color,.10)}}))}]}));
  drawIqTokLine(series,subs);
  drawIqTokScatter(series,subs);
}
/* 面积: 由浓到淡的纵向渐变(上沿 top 透明度 → 底部 2%); 非法颜色回落到主色 */
function areaGrad(color,top){
  const c=/^#?[0-9a-fA-F]{6}$/.test(String(color))?color:"#6950E8";
  return new echarts.graphic.LinearGradient(0,0,0,1,[{offset:0,color:withAlpha(c,top)},{offset:1,color:withAlpha(c,.02)}]);
}
function tokText(v){return v==null||!isFinite(v)?"—":v>=10?fmtInt(v):fmt(v,1)}
function iqSubVal(s,sub){const x=(s.r.subjects||[]).find(y=>y.id===sub.id);return x&&x.n?{acc:x.acc,tok:x.out_tokens>0?x.out_tokens/x.n:null,n:x.n}:null}
/* 正确率和每题 token(折线 + 面积): 科目按 A 的每题 token 从少到多排, 上下两张图共用横轴、各有一条纵轴(不做双纵轴);
   悬停时两张图同一科目一起高亮, 点这一列看这一科的题 */
function drawIqTokLine(series,subs){
  const el=$("iqTok");if(!el)return;
  const bucket=v=>v?Math.round(Math.log10(v)*4):99;  /* 每题 token 差不多的算一档, 同一档里按正确率从高到低 */
  const order=subs.map(sub=>({sub,v:iqSubVal(series[0],sub)})).filter(o=>o.v)
    .sort((x,y)=>(bucket(x.v.tok)-bucket(y.v.tok))||((y.v.acc||0)-(x.v.acc||0))).map(o=>o.sub);
  if(!order.length){chartEmpty("iqTok");return}
  const multi=series.length>1,names=order.map(sub=>shortSub(sub.name));
  const vals=series.map(s=>order.map(sub=>iqSubVal(s,sub)));
  const accs=vals.map(v=>v.map(x=>x?x.acc:null)),toks=vals.map(v=>v.map(x=>x&&x.tok?x.tok:null));
  const W=el.clientWidth||el.parentElement.clientWidth||900,L=56,R=24,band=(W-L-R)/order.length;
  const rot=band<56,dense=band<44;  /* 一列太窄: 科目名改为斜排; 再窄就不在点上写数字(悬停看) */
  const T0=multi?54:34,H0=176,T1=T0+H0+48,H1=118,B=rot?78:46;
  el.style.height=(T1+H1+B)+"px";
  const lo=Math.min(...accs.flat().filter(v=>v!=null)),hiTok=Math.max(2,...toks.flat().filter(v=>v!=null));
  const overall=(series[0].r.overall||{}).acc;
  const mk=(s,i,data,ax,f)=>({name:s.tag,type:"line",xAxisIndex:ax,yAxisIndex:ax,data,connectNulls:true,
    symbol:"circle",symbolSize:8,showSymbol:true,z:3+i,lineStyle:{width:2,color:s.color},
    itemStyle:{color:s.color,borderColor:C.surface,borderWidth:2},areaStyle:{origin:"start",color:areaGrad(s.color,multi?.16:.30)},
    emphasis:{focus:"series"},labelLayout:{hideOverlap:true},
    label:multi||dense?undefined:{show:true,position:"top",distance:6,color:C.text2,fontSize:11,backgroundColor:C.surface,padding:[1,3],borderRadius:3,
      formatter:p=>p.value==null?"":f(p.value)}});
  const xa=g=>({type:"category",gridIndex:g,data:names,boundaryGap:true,axisTick:{show:false},axisLine:{lineStyle:{color:C.axis}},
    axisLabel:g===0?{show:false}:Object.assign({color:C.text2,fontSize:band<96?10.5:11,interval:0,lineHeight:14,margin:10},
      rot?{rotate:35,width:80,overflow:"truncate"}:{width:Math.floor(band)-4,overflow:"truncate",formatter:v=>String(v).replace(" ","\n")})});
  const accS=series.map((s,i)=>mk(s,i,accs[i],0,v=>fmt(v,1)+"%"));
  if(!multi&&overall!=null)accS[0].markLine={silent:true,symbol:"none",lineStyle:{color:C.text3,type:"dashed",width:1},
    label:{position:"insideStartTop",color:C.text3,fontSize:11,backgroundColor:C.surface,padding:[1,4],borderRadius:3,formatter:`总正确率 ${fmt(overall,1)}%`},data:[{yAxis:overall}]};
  const tokAxis={type:"log",logBase:10,gridIndex:1,min:1,max:Math.pow(10,Math.ceil(Math.log10(hiTok*1.6))),
    name:"平均每题输出 token（对数刻度）",nameGap:10,nameTextStyle:{color:C.text3,fontSize:11,align:"left"},
    axisLine:{show:false},axisTick:{show:false},splitLine:{lineStyle:{color:C.grid}},axisLabel:{color:C.text3,fontSize:11,formatter:fmtAxis}};
  const inst=setChart("iqTok",baseOption({
    color:series.map(s=>s.color),legend:legendOf(series.map(s=>s.tag)),
    axisPointer:{link:[{xAxisIndex:"all"}]},
    grid:[{left:L,right:R,top:T0,height:H0},{left:L,right:R,top:T1,height:H1}],
    xAxis:[xa(0),xa(1)],
    yAxis:[Object.assign(axisValue({name:"正确率",max:100,min:Math.max(0,Math.floor((lo-8)/10)*10),fmt:v=>v+"%"}),{gridIndex:0}),tokAxis],
    tooltip:Object.assign(baseOption().tooltip,{trigger:"axis",axisPointer:{type:"shadow",shadowStyle:{color:withAlpha(/^#[0-9a-f]{6}$/i.test(C.text3)?C.text3:"#888888",.10)}},
      formatter:ps=>{const i=ps[0].dataIndex,sub=order[i];if(!sub)return"";
        return tt(sub.name,series.map((s,k)=>{const v=vals[k][i];return[s.color,s.tag,v?`${fmt(v.acc,1)}% · 每题 ${tokText(v.tok)} token`:"—"]}),
          `${vals[0][i]?vals[0][i].n+" 题 · ":""}点一下看这一科的题`)}}),
    series:[...accS,...series.map((s,i)=>mk(s,i,toks[i],1,tokText))]}));
  if(!inst)return;
  /* 点这一列(两张图任一处)就看这一科的题 */
  const zr=inst.getZr(),hit=e=>{for(const g of [0,1])if(inst.containPixel({gridIndex:g},[e.offsetX,e.offsetY])){const i=Math.round(inst.convertFromPixel({xAxisIndex:g},e.offsetX));return order[i]||null}return null};
  zr.off("click");zr.off("mousemove");
  zr.on("click",e=>{const sub=hit(e);if(sub)qbGo(sub.id,"all")});
  zr.on("mousemove",e=>zr.setCursorStyle(hit(e)?"pointer":"default"));
}
/* 散点名字防重叠: 横向位置相近(对数刻度 0.25 格内)的点算一簇, 簇里的名字统一从最右边那个点的右侧开始写,
   按正确率从高到低排, 名字之间至少隔一行字高, 挤的往下错开。返回 Map(点 → [dx, dy]) */
function scatterLabelOffsets(pts,{plotW,plotH,yMin,yMax,lineH=15}){
  const list=pts.filter(Boolean).map(p=>({p,lx:Math.log10(p.value[0])}));
  if(!list.length)return new Map();
  const d0=Math.floor(Math.min(...list.map(x=>x.lx))),d1=Math.max(d0+1,Math.ceil(Math.max(...list.map(x=>x.lx))));
  const ux=plotW/(d1-d0),uy=plotH/Math.max(1,yMax-yMin),out=new Map();
  list.forEach(x=>x.y=(yMax-x.p.value[1])*uy);
  list.sort((a,b)=>a.lx-b.lx);
  const groups=[];list.forEach(x=>{const g=groups[groups.length-1];if(g&&x.lx-g[g.length-1].lx<.25)g.push(x);else groups.push([x])});
  groups.forEach(g=>{
    const right=Math.max(...g.map(x=>x.lx));g.sort((a,b)=>a.y-b.y);
    let last=-1e9;g.forEach(x=>{const y=Math.max(x.y,last+lineH);out.set(x.p,[(right-x.lx)*ux,y-x.y]);last=y});
  });
  return out;
}
/* 正确率 × 每题 token(散点): 横轴对数刻度; 对比时同一科目用细线连起来; 名字挤在一起时上下错开而不是藏掉 */
function drawIqTokScatter(series,subs){
  const pts=series.map(s=>subs.map(sub=>{const v=iqSubVal(s,sub);return v&&v.tok?{value:[v.tok,v.acc],name:shortSub(sub.name),n:v.n,id:sub.id}:null}));
  const el=$("iqTokScatter"),top=series.length>1?44:26;
  const lo=Math.min(...pts.flat().filter(Boolean).map(p=>p.value[1])),yMin=Math.max(0,Math.floor(lo/10)*10-10);
  const offs=scatterLabelOffsets(pts[0],{plotW:(el&&(el.clientWidth||el.parentElement.clientWidth)||900)-76,plotH:(el&&el.clientHeight||380)-top-58,yMin,yMax:100});
  pts[0].forEach(p=>{const o=p&&offs.get(p);if(o&&(o[0]>.5||o[1]>.5))p.label={offset:[Math.round(o[0]),Math.round(o[1])]}});
  const links=series.length>1?subs.map((sub,i)=>({type:"line",silent:true,symbol:"none",z:1,lineStyle:{color:C.axis,width:1},tooltip:{show:false},
    data:pts.map(p=>p[i]&&p[i].value).filter(Boolean)})).filter(x=>x.data.length>1):[];
  const inst=setChart("iqTokScatter",baseOption({
    color:series.map(s=>s.color),legend:legendOf(series.map(s=>s.tag),"rect"),
    grid:{left:4,right:28,top,bottom:30,containLabel:true},
    xAxis:{type:"log",logBase:10,name:"平均每题输出 token（越往左越省）",nameLocation:"middle",nameGap:28,nameTextStyle:{color:C.text3,fontSize:11},
      axisLine:{show:true,lineStyle:{color:C.axis}},axisTick:{show:false},splitLine:{lineStyle:{color:C.grid}},axisLabel:{color:C.text3,fontSize:11,formatter:fmtAxis}},
    yAxis:axisValue({name:"正确率 %",max:100,fmt:v=>v+"%",min:yMin}),
    tooltip:Object.assign(baseOption().tooltip,{trigger:"item",formatter:q=>q.seriesType!=="scatter"?"":tt(q.name,[[q.color,q.seriesName,`${fmt(q.value[1],1)}% · 每题 ${tokText(q.value[0])} token`]],"点一下看这一科的题")}),
    series:[...links,...series.map((s,i)=>({name:s.tag,type:"scatter",symbolSize:11,z:3,itemStyle:{color:s.color,borderColor:C.surface,borderWidth:1.5},
      data:pts[i].filter(Boolean),label:i===0?{show:true,position:"right",distance:6,color:C.text2,fontSize:11,formatter:q=>q.name}:undefined}))]}));
  if(inst){inst.off("click");inst.on("click",q=>{if(q.seriesType==="scatter"&&q.data&&q.data.id)qbGo(q.data.id,"all")})}
}
/* ---- MMLU 各学科: 分组表(逐题数据加载后统计) ---- */
function renderMmlu(){
  const box=$("iqMmlu"),d=QB.data;if(!box||!d)return;
  const groups=d.subjects.filter(s=>/^mmlu/.test(s.id));
  if(!groups.length){box.innerHTML=emptyState("这次测试没有 MMLU 题目","",{inline:true});return}
  const runs=QB.series.filter(s=>(d.runs[s.r.run_id]||{}).same_bank);
  const rows=[];
  groups.forEach(g=>{
    const bySub=new Map();
    d.questions.filter(q=>q.sid===g.id).forEach(q=>{const k=q.sub||"";if(!bySub.has(k))bySub.set(k,[]);bySub.get(k).push(q)});
    const part=[...bySub.entries()].map(([sub,list])=>{
      const row={g:shortSub(g.name),gid:g.id,sub,name:sub?subTopic(sub):"（未分学科）",n:list.length,
        act:`<button type="button" class="btn btn-ghost btn-sm" data-qb-go="${esc(g.id)}" data-qb-filter="all" data-qb-q="${esc(sub?subTopic(sub):"")}">看题目</button>`};
      runs.forEach((s,i)=>{const recs=d.runs[s.r.run_id].recs,ok=list.filter(q=>(recs[qbKey(q)]||{}).ok).length;row["ok_"+i]=ok;row["acc_"+i]=100*ok/list.length});
      return row;
    }).sort((x,y)=>(y.acc_0??-1)-(x.acc_0??-1));
    rows.push(...part);
  });
  const multi=runs.length>1;
  const spec={id:"iq-mmlu-t",title:"MMLU 各学科",maxH:640,pageSize:1000,
    groupBy:r=>r.g,groupLabel:(g,rs)=>{const n=rs.reduce((t,r)=>t+r.n,0),ok=rs.reduce((t,r)=>t+(r.ok_0||0),0);
      return `${esc(g)} <span class="faint">· ${rs.length} 个学科 · ${n} 题 · A 正确率 ${n?fmt(100*ok/n,1):"—"}%</span>`},
    columns:[{key:"name",label:"学科",type:"text",sticky:true},{key:"n",label:"题数",type:"int"},
      ...runs.map((s,i)=>({key:"acc_"+i,label:multi?s.tag:"正确率",unit:multi?"":"%",group:multi?"正确率（%）":"",type:"bar",color:s.color,max:100})),
      ...runs.map((s,i)=>({key:"ok_"+i,label:multi?s.tag:"答对",group:multi?"答对":"",type:"int"})),{key:"act",label:"",type:"html",noSort:true}],rows};
  box.innerHTML=dataTable(spec);
}
/* ---- 逐题查看: 卡片 | 表格 ---- */
function qbSectionHTML(series){
  const mode=panelMode("iq-items");
  return `<section class="sec" id="iq-items" data-jump="逐题查看" data-pv="${mode}">
    <div class="sec-head"><div class="sec-head-text"><h2 class="sec-title">逐题查看</h2><p class="sec-desc">${series.length>1?"每道题的题目、标准答案和各次测试的答案；可以只看两次结果不一样的题":"每道题的题目、标准答案和模型的答案；点「看回答」可以看模型的原话"}</p></div>
      <div class="sec-tools">${segHTML("data-pv-set",mode,[["chart","卡片","layers"],["table","表格","table"]])}</div></div>
    <div class="qb" id="qb"></div></section>`;
}
function qbTableSpec(rows){
  const d=QB.data,runs=QB.series.filter(s=>(d.runs[s.r.run_id]||{}).same_bank),multi=runs.length>1;
  const recOf=(s,q)=>((d.runs[s.r.run_id]||{}).recs||{})[qbKey(q)];
  const stOf=rec=>{const [label,tone]=QB_STATE[qbState(rec)];return{tone:tone||"neutral",text:label}};
  return{id:"iq-items-t",title:"逐题",search:false,pageSize:50,pageSizes:[20,50,100,200],rowKey:q=>qbKey(q),
    columns:[{key:"where",label:"题目",type:"text",sticky:true,get:q=>`${shortSub((d.subjMap[q.sid]||{}).name||q.sid)} · 第 ${q.idx+1} 题`,sortValue:q=>d.subjects.findIndex(s=>s.id===q.sid)*1e5+q.idx},
      {key:"topic",label:"学科",type:"text",get:q=>subTopic(q.sub)||"—"},
      {key:"q",label:"题目内容",type:"html",get:q=>`<span class="dt-ellipsis" title="${esc(q.q||"")}">${esc(q.q||"（找不到题目）")}</span>`,text:(v,q)=>q.q||""},
      {key:"gold",label:"标准答案",type:"text",get:q=>q.answer!=null?String(q.answer):(q.rules?"按规则检查":"—")},
      ...runs.map(s=>({key:"p_"+s.tag,label:multi?s.tag:"模型的答案",group:multi?"答案":"",type:"html",
        get:q=>{const r=recOf(s,q);return !r?"—":r.err?`<span class="bad">请求失败</span>`:`<span class="${r.ok?"good":"bad"}">${esc(r.pred??"没看出")}</span>`},
        text:(v,q)=>{const r=recOf(s,q);return !r?"":r.err?"请求失败":String(r.pred??"")}})),
      ...runs.map(s=>({key:"s_"+s.tag,label:multi?s.tag:"结果",group:multi?"结果":"",type:"status",get:q=>stOf(recOf(s,q))})),
      {key:"out",label:"输出",unit:"token",type:"int",get:q=>{const r=recOf(runs[0],q);return r&&r.out!=null?r.out:null}}],
    rows,expand:q=>qbCard(q,{full:true}),note:"点行展开看完整题目和回答"};
}
/* ---- 逐题查看: 题目 / 标准答案 / 各次测试的答案; 回答原文点开时才加载 ---- */
const MMLU_ZH={abstract_algebra:"抽象代数",anatomy:"解剖学",astronomy:"天文学",business_ethics:"商业伦理",clinical_knowledge:"临床知识",
  college_biology:"大学生物",college_chemistry:"大学化学",college_computer_science:"大学计算机",college_mathematics:"大学数学",
  college_medicine:"大学医学",college_physics:"大学物理",computer_security:"计算机安全",conceptual_physics:"概念物理",
  econometrics:"计量经济学",electrical_engineering:"电气工程",elementary_mathematics:"初等数学",formal_logic:"形式逻辑",
  global_facts:"全球常识",high_school_biology:"高中生物",high_school_chemistry:"高中化学",high_school_computer_science:"高中计算机",
  high_school_european_history:"高中欧洲史",high_school_geography:"高中地理",high_school_government_and_politics:"高中政治",
  high_school_macroeconomics:"高中宏观经济",high_school_mathematics:"高中数学",high_school_microeconomics:"高中微观经济",
  high_school_physics:"高中物理",high_school_psychology:"高中心理学",high_school_statistics:"高中统计",high_school_us_history:"高中美国史",
  high_school_world_history:"高中世界史",human_aging:"人类衰老",human_sexuality:"人类性学",international_law:"国际法",
  jurisprudence:"法理学",logical_fallacies:"逻辑谬误",machine_learning:"机器学习",management:"管理学",marketing:"市场营销",
  medical_genetics:"医学遗传学",miscellaneous:"综合常识",moral_disputes:"道德争议",moral_scenarios:"道德情境",nutrition:"营养学",
  philosophy:"哲学",prehistory:"史前史",professional_accounting:"专业会计",professional_law:"专业法律",professional_medicine:"专业医学",
  professional_psychology:"专业心理学",public_relations:"公共关系",security_studies:"安全研究",sociology:"社会学",
  us_foreign_policy:"美国外交政策",virology:"病毒学",world_religions:"世界宗教"};
const subTopic=s=>s?(MMLU_ZH[s]||String(s).replace(/_/g," ")):"";
const QB_STATE={ok:["答对","good","check"],wrong:["答错","bad","x"],trunc:["没答完","warn","clock"],err:["请求失败","bad","alert"],none:["没做这题","","minus"]};
const QB_SIZES=[6,12,24,48],QB_PREF=lsGet("llm-bench-pro-qb");
const QB={key:"",main:"",data:null,loading:null,err:"",series:[],subj:"",filter:"all",vs:"",q:"",page:0,size:QB_SIZES.includes(QB_PREF.size)?QB_PREF.size:6};
const qbKey=q=>q.sid+"|"+q.idx;
function qbState(rec){return !rec?"none":rec.ok?"ok":rec.err?"err":rec.trunc?"trunc":"wrong"}
/* 筛选: bad=没答对(含没答完、请求失败); vs-* 与对照测试逐题比较, 口径同「差异是否可信」(只看双方都正常作答的题) */
function qbPass(f,a,x){
  if(f==="all")return true;
  if(!a)return false;
  if(f==="ok")return a.ok;
  if(f==="bad")return !a.ok;
  if(f==="trunc")return !a.ok&&!!a.trunc&&!a.err;
  if(f==="err")return !!a.err;
  if(!x||a.err||x.err)return false;
  if(f==="vs-a")return a.ok&&!x.ok;
  if(f==="vs-b")return !a.ok&&x.ok;
  if(f==="vs-none")return !a.ok&&!x.ok;
  return true;
}
function qbInit(series){
  QB.series=series;
  const main=series[0].r.run_id,cmp=series.slice(1).map(s=>s.r.run_id),key=[main,...cmp].join("|");
  if(QB.key!==key){
    if(QB.main!==main)Object.assign(QB,{subj:"",filter:"all",q:""});
    if(!cmp.includes(QB.vs))QB.vs=cmp[0]||"";
    if(!cmp.length&&QB.filter.startsWith("vs-"))QB.filter="all";
    Object.assign(QB,{key,main,data:null,err:"",page:0});
    const p=QB.loading=getJSON(`/api/iq-items?id=${encodeURIComponent(main)}&cmp=${encodeURIComponent(cmp.join(","))}`)
      .then(d=>{
        if(QB.loading!==p)return;
        if(!d||!d.ok)throw new Error((d&&d.error)||"加载失败");
        d.questions.forEach(q=>q._hay=[q.q,...(q.choices||[]),q.choices?null:q.answer,q.sub,subTopic(q.sub)].filter(v=>v!=null).join("\n").toLowerCase());
        d.subjMap=Object.fromEntries(d.subjects.map(s=>[s.id,s]));
        QB.data=d;
      })
      .catch(e=>{if(QB.loading===p)QB.err=/HTTP 404/.test(e.message)?"服务端还是旧版本，重启服务后才能逐题查看":e.message})
      .finally(()=>{if(QB.loading===p){QB.loading=null;qbRender()}});
  }
  qbRender();
}
function qbRender(){
  const box=$("qb");if(!box)return;
  if(QB.err){box.innerHTML=emptyState("没能加载题目",QB.err,{iconName:"alert",inline:true});return}
  const d=QB.data;
  if(!d){box.innerHTML=`<div class="qb-loading faint">正在加载题目…</div>`;return}
  if(QB.subj&&!d.subjMap[QB.subj])QB.subj="";
  const recsA=d.runs[QB.main].recs,cmp=QB.series.slice(1);
  const other=cmp.filter(s=>!(d.runs[s.r.run_id]||{}).same_bank);
  const subjOpt=s=>{
    const qs=d.questions.filter(q=>q.sid===s.id),bad=qs.filter(q=>!(recsA[qbKey(q)]||{}).ok).length;
    return `<option value="${esc(s.id)}" ${s.id===QB.subj?"selected":""}>${esc(shortSub(s.name))}（${qs.length} 题，${bad?`没答对 ${bad}`:"全对"}）</option>`;
  };
  box.innerHTML=`${d.bank_found?"":alertBox("warn",`找不到题集文件（banks/${esc(d.bank_id)}.json），只能看到每题的对错和模型的答案，看不到题目内容`)}
    <div class="qb-bar">
      <select class="select" id="qbSubj" aria-label="科目"><option value="">全部科目（${d.questions.length} 题）</option>${d.subjects.map(subjOpt).join("")}</select>
      <label class="qb-search">${icon("search")}<input class="input" id="qbSearch" type="search" placeholder="搜索题目或选项里的文字" value="${esc(QB.q)}"></label>
      ${cmp.length>1?`<label class="qb-vs"><span>和谁对照</span><select class="select" id="qbVs">${cmp.map(s=>`<option value="${esc(s.r.run_id)}" ${s.r.run_id===QB.vs?"selected":""}>${esc(s.tag)} · ${esc(s.r.model||"")}</option>`).join("")}</select></label>`:""}
    </div>
    ${other.length?`<div class="qb-note">${esc(other.map(s=>s.tag).join("、"))} 用的题集和 A 不一样，不能逐题对照</div>`:""}
    <div class="qb-chiprow" id="qbChipRow"><div class="filter-chips" id="qbChips"></div><div class="qb-pager-top" id="qbPagerTop"></div></div>
    <div class="pv-chart"><div class="qb-list" id="qbList"></div><div class="qb-pager" id="qbPager"></div></div>
    <div class="pv-table" id="qbTable"></div>`;
  qbRenderList();
  renderMmlu();
}
function qbRenderList(){
  const d=QB.data,list=$("qbList");if(!d||!list)return;
  const recsA=d.runs[QB.main].recs,vs=d.runs[QB.vs],recsX=vs&&vs.same_bank?vs.recs:null;
  const needle=QB.q.trim().toLowerCase();
  const scope=d.questions.filter(q=>(!QB.subj||q.sid===QB.subj)&&(!needle||q._hay.includes(needle)));
  const pass=(f,q)=>qbPass(f,recsA[qbKey(q)],recsX&&recsX[qbKey(q)]);
  const vsTag=(QB.series.find(s=>s.r.run_id===QB.vs)||{}).tag||"B";
  const A=QB.series.length>1?"A ":"";  /* 对照模式下注明指 A 的结果 */
  const chips=[["all","全部"],["ok",A+"答对"],["bad",A+"没答对"],["trunc","其中没答完"],["err","其中请求失败"]]
    .concat(recsX?[["vs-a","只有 A 答对"],["vs-b",`只有 ${vsTag} 答对`],["vs-none","都没答对"]]:[]);
  if(!chips.some(c=>c[0]===QB.filter))QB.filter="all";
  const cnt={};chips.forEach(([f])=>cnt[f]=scope.filter(q=>pass(f,q)).length);
  $("qbChips").innerHTML=chips.filter(([f])=>!["trunc","err"].includes(f)||cnt[f]||f===QB.filter)
    .map(([f,label])=>`${f==="vs-a"?`<span class="qb-sep" aria-hidden="true"></span>`:""}<button type="button" class="filter-chip" data-qb-filter="${f}" aria-pressed="${f===QB.filter}">${esc(label)} <b>${cnt[f]}</b></button>`).join("");
  const rows=scope.filter(q=>pass(QB.filter,q));
  /* 表格形态: 同一份筛选结果; 筛选条件变了回到第一页 */
  const sig=[QB.filter,QB.subj,QB.q,QB.vs].join("|");
  if(QB.tsig!==sig){QB.tsig=sig;dtState("iq-items-t").page=0}
  if($("qbTable"))$("qbTable").innerHTML=dataTable(qbTableSpec(rows));
  const pages=Math.max(1,Math.ceil(rows.length/QB.size));
  QB.page=Math.min(Math.max(0,QB.page),pages-1);
  const view=rows.slice(QB.page*QB.size,(QB.page+1)*QB.size);
  list.innerHTML=view.length?view.map(q=>qbCard(q)).join(""):
    emptyState(needle?"没有找到相关的题":"这里没有题",needle?"换个关键词试试":"换一个筛选条件看看",{iconName:needle?"search":"inbox",inline:true});
  /* 实际没被截断的题目去掉「展开全文」 */
  list.querySelectorAll(".qcard-q.is-clamp").forEach(el=>{
    if(el.scrollHeight>el.clientHeight+2)return;
    el.classList.remove("is-clamp");
    const more=el.nextElementSibling;if(more&&more.hasAttribute("data-qb-more"))more.remove();
  });
  $("qbPagerTop").innerHTML=pagerHTML("qb",{page:QB.page,pages,compact:true,keys:true});
  $("qbPager").innerHTML=rows.length?pagerHTML("qb",{page:QB.page,pages,total:rows.length,unit:"题",size:QB.size,sizes:rows.length>QB_SIZES[0]?QB_SIZES:null,keys:true}):"";
}
/* 翻页: 在底部翻页时滚回卡片顶部; 键盘翻页焦点留在翻页器上 */
function qbSetPage(p){
  const k=pagerFocusKey();
  QB.page=p;qbRenderList();
  scrollTopIntoView($("qbChipRow"));
  pagerRefocus($("qb"),k);
}
/* 展开题目全文或回答时, 这张卡占满一整行, 读长文更方便 */
function qbWide(card){
  if(!card||!card.closest(".qb-list"))return;
  const open=!card.querySelector(".qresp").hidden,txt=!!card.querySelector(".qcard-q:not(.is-clamp)+[data-qb-more]");
  const was=card.classList.contains("is-wide");card.classList.toggle("is-wide",open||txt);
  if(was!==card.classList.contains("is-wide"))card.scrollIntoView({block:"nearest"});
}
function qbCard(q,opt={}){
  const d=QB.data,sub=d.subjMap[q.sid]||{},key=qbKey(q),multi=QB.series.length>1;
  const runs=QB.series.map(s=>{const R=d.runs[s.r.run_id]||{};return{s,same:!!R.same_bank,rec:R.same_bank?(R.recs||{})[key]:null}}).filter(r=>r.same);
  const tagOf=r=>multi?`<span class="run-tag" style="background:${r.s.color}">${esc(r.s.tag)}</span>`:"";
  const whose=(r,what)=>multi?esc(r.s.tag)+" "+what:"模型"+what;
  const predOf=r=>r.rec&&r.rec.pred!=null?String(r.rec.pred):null;
  const verdicts=runs.map(r=>{const [label,tone,ic]=QB_STATE[qbState(r.rec)];
    return `<span class="qv${tone?" is-"+tone:""}">${tagOf(r)}${icon(ic,"icon-sm")}${label}</span>`}).join("");
  const clamp=!opt.full&&q.q!=null;  /* 卡片网格里题目先显示几行; 渲染后实际没超出的去掉「展开全文」 */
  let body=q.q==null?`<div class="qcard-q faint">（题集文件里找不到这道题）</div>`:
    `<div class="qcard-q${clamp?" is-clamp":""}">${esc(q.q)}</div>${clamp?`<button type="button" class="qb-more" data-qb-more>展开全文</button>`:""}`;
  const answered=runs.filter(r=>r.rec&&!r.rec.err);
  if(Array.isArray(q.choices)){
    const gold=String(q.answer||"").toUpperCase();
    body+=`<ol class="qchoices">${q.choices.map((c,j)=>{
      const L="ABCD"[j],isAns=L===gold;
      const picked=answered.filter(r=>(predOf(r)||"").toUpperCase()===L);
      const marks=(isAns?`<span class="qmark is-good">${icon("check","icon-sm")}标准答案</span>`:"")+
        picked.map(r=>`<span class="qmark ${isAns?"is-good":"is-bad"}">${whose(r,"选了")}</span>`).join("");
      return `<li class="${isAns?"is-answer":picked.length?"is-wrong":""}"><span class="qchoice-key">${L}</span><span class="qchoice-text">${esc(c)}</span>${marks?`<span class="qchoice-marks">${marks}</span>`:""}</li>`;
    }).join("")}</ol>`;
    const odd=answered.filter(r=>!/^[A-D]$/i.test(predOf(r)||""));  /* 没按要求只答字母 */
    if(odd.length)body+=`<div class="qans">${odd.map(r=>`<div class="qans-row"><span class="qans-k">${whose(r,"的答案")}</span><span class="qans-v is-bad">${predOf(r)!=null?esc(predOf(r)):"没看出选了哪个"}</span></div>`).join("")}</div>`;
  }else if(q.rules||sub.type==="instruct"){
    body+=`<div class="qrules"><span class="qans-k">要求</span>${(q.rules||[]).map(r=>`<span class="qrule"${r.tech?` title="检查规则：${esc(r.tech)}"`:""}>${esc(r.text)}</span>`).join("")}</div>`;
  }else{
    body+=`<div class="qans"><div class="qans-row"><span class="qans-k">标准答案</span><span class="qans-v mono">${esc(q.answer??"—")}</span></div>`+
      answered.map(r=>`<div class="qans-row"><span class="qans-k">${whose(r,"的答案")}</span><span class="qans-v mono ${r.rec.ok?"is-good":"is-bad"}">${predOf(r)!=null?esc(predOf(r)):"没看出最终答案"}</span></div>`).join("")+`</div>`;
  }
  body+=runs.filter(r=>r.rec&&r.rec.err).map(r=>`<div class="qcard-err">${icon("alert","icon-sm")}<span>${multi?esc(r.s.tag)+" ":""}请求失败：${esc(r.rec.err)}</span></div>`).join("");
  const meta=answered.map(r=>{const x=r.rec,p=[];
    if(x.out!=null)p.push(`输出 ${fmtInt(x.out)} token`);
    if(x.rc)p.push(`思考 ${fmtInt(x.rc)} 字`);
    if(x.finish==="length")p.push("写到长度上限被停下");
    return p.length?(multi?r.s.tag+"：":"")+p.join(" · "):""}).filter(Boolean).join("　");
  const hasText=runs.some(r=>r.rec&&r.rec.has),canPrompt=!!d.bank_found&&d.iq_version===SERVER.iq_version;
  const btn=hasText||canPrompt?`<button type="button" class="btn btn-ghost btn-sm" data-qb-ans="${esc(key)}" aria-expanded="false">${icon("eye")}${hasText?"看回答":"看发给模型的原文"}</button>`:"";
  return `<article class="qcard"><header class="qcard-head"><span class="qcard-where">${esc(shortSub(sub.name||q.sid))} · 第 ${q.idx+1} 题</span>${q.sub?`<span class="qcard-topic">${esc(subTopic(q.sub))}</span>`:""}<span class="qcard-verdicts">${verdicts}</span></header>
    ${body}${btn||meta?`<footer class="qcard-foot">${btn}<span>${esc(meta)}</span></footer>`:""}<div class="qresp" hidden></div></article>`;
}
async function qbToggleAnswer(btn){
  const box=btn.closest(".qcard").querySelector(".qresp");
  const open=box.hidden;box.hidden=!open;btn.setAttribute("aria-expanded",String(open));
  qbWide(btn.closest(".qcard"));
  if(!open||box.dataset.loaded)return;
  box.innerHTML=`<div class="qresp-note">正在加载…</div>`;
  const key=btn.dataset.qbAns,i=key.lastIndexOf("|");
  const runs=QB.series.filter(s=>(QB.data.runs[s.r.run_id]||{}).same_bank);
  try{
    const d=await getJSON(`/api/iq-answer?ids=${encodeURIComponent(runs.map(s=>s.r.run_id).join(","))}&sid=${encodeURIComponent(key.slice(0,i))}&idx=${encodeURIComponent(key.slice(i+1))}`);
    if(!d.ok)throw new Error(d.error||"加载失败");
    box.innerHTML=qbAnswerHtml(d,runs);box.dataset.loaded="1";
  }catch(e){box.innerHTML=`<div class="qresp-note">加载失败：${esc(e.message)}</div>`}
}
function qbAnswerHtml(d,runs){
  const multi=QB.series.length>1;
  const kept=runs.filter(s=>{const a=d.answers[s.r.run_id];return a&&a.kept!==false});
  const prompt=open=>d.prompt?`<details class="qresp-more"${open?" open":""}><summary>发给模型的原文</summary><pre class="qresp-text">${esc(d.prompt)}</pre></details>`:"";
  /* 旧版测试没保存这题的回答: 一句话说明, 直接展开发给模型的原文 */
  if(!kept.length)return `<div class="qresp-note">这次测试没有保存这道题的回答（之前的版本只保存答错题回答的最后 240 字，新的测试会保存每道题的完整回答）</div>${prompt(true)}`;
  return runs.map(s=>{
    const a=d.answers[s.r.run_id];
    const head=`<div class="qresp-head">${multi?`<span class="run-tag" style="background:${s.color}">${esc(s.tag)}</span>${esc(s.r.model||"")} 的回答`:"模型的回答"}${a&&a.finish?`<span class="faint">· ${esc(a.finish==="stop"?"正常结束":a.finish==="length"?"写到长度上限被停下":a.finish)}</span>`:""}</div>`;
    if(!a)return `<div class="qresp-block">${head}<div class="qresp-note">这次测试没有做这道题</div></div>`;
    let body;
    if(a.err)body=`<div class="qcard-err">${icon("alert","icon-sm")}<span>请求失败：${esc(a.err)}</span></div>`;
    else if(a.kept===false)body=`<div class="qresp-note">这次测试没有保存这道题的回答</div>`;
    else if(!a.text)body=`<div class="qresp-note">没有给出正式回答：${a.finish==="length"?`思考了 ${fmtInt(a.rc)} 字还没想完，就写到了长度上限`:a.rc?`只输出了思考内容（${fmtInt(a.rc)} 字）`:"模型返回了空内容"}</div>`;
    else body=`<pre class="qresp-text">${a.full?"":"…"}${esc(a.text)}</pre>`+
      (a.full?"":`<div class="qresp-note">这次测试只保存了回答的最后 240 字；新的测试会保存完整回答</div>`);
    if(a.rules)body+=`<ul class="qrule-list">${a.rules.map(r=>`<li class="${r.pass?"is-good":"is-bad"}"${r.tech?` title="检查规则：${esc(r.tech)}"`:""}>${icon(r.pass?"check":"x","icon-sm")}${esc(r.text)}${r.actual?`<span class="faint">（${esc(r.actual)}）</span>`:""}</li>`).join("")}</ul>`;
    if(a.rtail)body+=`<details class="qresp-more"><summary>看思考过程的最后一段（一共思考了 ${fmtInt(a.rc)} 字）</summary><pre class="qresp-text">${a.rtail.length<(a.rc||0)?"…":""}${esc(a.rtail)}</pre></details>`;
    return `<div class="qresp-block">${head}${body}</div>`;
  }).join("")+prompt(false);
}
function qbGo(sid,filter,vs,q){
  if(vs)QB.vs=vs;
  Object.assign(QB,{subj:sid||"",filter:filter||"all",q:q||"",page:0});
  if(QB.data)qbRender();
  const t=$("iq-items");if(t)t.scrollIntoView({behavior:"smooth",block:"start"});
}
let qbTimer=null;
$("iqResult").addEventListener("click",e=>{
  const go=e.target.closest("[data-qb-go]");
  if(go){e.preventDefault();qbGo(go.dataset.qbGo,go.dataset.qbFilter,go.dataset.qbVs,go.dataset.qbQ);return}
  const ct=e.target.closest("[data-ctab]");
  if(ct){const card=ct.closest(".ccard"),k=ct.dataset.ctab;
    card.querySelectorAll("[data-ctab]").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.ctab===k)));
    let pane=null;card.querySelectorAll("[data-ctab-pane]").forEach(p=>{p.hidden=p.dataset.ctabPane!==k;if(!p.hidden)pane=p});
    const d=card.querySelector("[data-ctab-desc]");if(d&&pane&&pane.dataset.desc)d.textContent=pane.dataset.desc;
    if(card.dataset.ctabCard){CTAB[card.dataset.ctabCard]=k;lsSet("llm-bench-pro-ctab",CTAB)}
    requestAnimationFrame(()=>resizeChartsIn(card));
    return}
  const chip=e.target.closest("#qbChips [data-qb-filter]");
  if(chip){QB.filter=chip.dataset.qbFilter;QB.page=0;qbRenderList();return}
  const pg=e.target.closest("[data-qb-page]");
  if(pg){qbSetPage(+pg.dataset.qbPage);return}
  const jb=e.target.closest("[data-qb-jumpbtn]");
  if(jb){const t=pagerTarget(jb.parentElement.querySelector("[data-qb-jump]"));if(t!=null)qbSetPage(t);return}
  const ans=e.target.closest("[data-qb-ans]");if(ans){qbToggleAnswer(ans);return}
  const more=e.target.closest("[data-qb-more]");
  if(more){const on=more.previousElementSibling.classList.toggle("is-clamp");more.textContent=on?"展开全文":"收起";qbWide(more.closest(".qcard"))}
});
$("iqResult").addEventListener("change",e=>{
  if(e.target.id==="qbSubj"){QB.subj=e.target.value;QB.page=0;qbRenderList()}
  else if(e.target.id==="qbVs"){QB.vs=e.target.value;QB.page=0;qbRenderList()}
  else if(e.target.matches("[data-qb-size]")){
    const first=QB.page*QB.size;QB.size=+e.target.value;QB.page=Math.floor(first/QB.size);lsSet("llm-bench-pro-qb",{size:QB.size});
    qbRenderList();$("qbPager").querySelector("[data-qb-size]")?.focus()}
  else if(e.target.matches(".is-compact [data-qb-jump]")){const t=pagerTarget(e.target);if(t!=null&&t!==QB.page)qbSetPage(t);else e.target.value=QB.page+1}
});
$("iqResult").addEventListener("keydown",e=>{
  if(e.key!=="Enter"||!e.target.matches("[data-qb-jump]"))return;
  e.preventDefault();const t=pagerTarget(e.target);if(t!=null)qbSetPage(t);
});
/* 键盘 ← → 翻逐题卡片: 卡片在屏幕上、焦点不在输入框里、没有打开面板或弹窗时才生效 */
document.addEventListener("keydown",e=>{
  if((e.key!=="ArrowLeft"&&e.key!=="ArrowRight")||e.altKey||e.ctrlKey||e.metaKey||e.shiftKey||e.defaultPrevented)return;
  if(e.target.closest&&e.target.closest("input,select,textarea,[contenteditable=true],details[open]"))return;
  if(!$("modal").hidden||document.querySelector(".drawer:not([hidden])"))return;
  const sec=$("iq-items"),list=$("qbList");
  if(!sec||!list||sec.dataset.pv==="table"||!list.offsetParent)return;
  const r=list.getBoundingClientRect();if(r.bottom<80||r.top>innerHeight-80)return;
  const b=$("qbPagerTop")&&$("qbPagerTop").querySelector(`[data-dir=${e.key==="ArrowLeft"?"prev":"next"}]`);
  if(!b||b.disabled)return;
  e.preventDefault();qbSetPage(+b.dataset.qbPage);
});
$("iqResult").addEventListener("input",e=>{
  if(e.target.id!=="qbSearch")return;
  clearTimeout(qbTimer);
  qbTimer=setTimeout(()=>{QB.q=e.target.value;QB.page=0;qbRenderList()},200);
});

/* ============================================================
   代码生成
   ============================================================ */
let GEN_RUNS={},GEN_LOADED=false,genPoll=null,GEN_FILTER="all";
const genLog=LogBox("genLog","gen");
bindFormMemory("llm-bench-pro-gen-form",["genBase","genModel","genConc","genTag","genSampling","genTemp","genTopP","genTopK","genPresence"]);
bindFormMemory("llm-bench-pro-gen-judge",["genJudgeBase","genJudgeModel"]);
const TIER_NAME={普通:"基础",困难:"进阶",地狱:"高难",实战:"真实场景"};
const TIER_ORDER=["普通","困难","地狱","实战"];
const tagName=t=>TIER_NAME[t]||t;
const TASK_CATALOG=[
 {id:"pelican",name:"鹈鹕骑自行车",tier:"普通",cat:"anim"},{id:"earth",name:"可拖拽 3D 地球",tier:"普通",cat:"d3"},
 {id:"blackhole",name:"黑洞吸积盘",tier:"普通",cat:"anim"},{id:"matrix",name:"矩阵字符雨",tier:"普通",cat:"anim"},
 {id:"koi",name:"锦鲤池塘",tier:"普通",cat:"anim"},{id:"fireworks",name:"点击烟花",tier:"普通",cat:"anim"},
 {id:"solar",name:"太阳系模拟",tier:"普通",cat:"anim"},{id:"landing",name:"产品落地页",tier:"普通",cat:"page"},
 {id:"dashboard",name:"数据看板",tier:"普通",cat:"page"},
 {id:"flappy",name:"Flappy Bird",tier:"困难",cat:"game"},{id:"tetris",name:"俄罗斯方块",tier:"困难",cat:"game"},
 {id:"breakout",name:"打砖块",tier:"困难",cat:"game"},{id:"ninja",name:"切水果",tier:"困难",cat:"game"},
 {id:"platformer",name:"2D 平台跳跃",tier:"困难",cat:"game"},{id:"snake",name:"贪吃蛇",tier:"困难",cat:"game"},
 {id:"fps",name:"3D 第一人称迷宫",tier:"地狱",cat:"d3"},{id:"cube3d",name:"3D 魔方",tier:"地狱",cat:"d3"},
 {id:"pinball",name:"物理弹珠台",tier:"地狱",cat:"game"},{id:"fluid",name:"实时流体模拟",tier:"地狱",cat:"anim"},
 {id:"eco",name:"生态进化模拟",tier:"地狱",cat:"anim"},{id:"piano",name:"可弹奏钢琴",tier:"地狱",cat:"app"},
 {id:"sortviz",name:"排序算法可视化",tier:"地狱",cat:"anim"},{id:"win95",name:"Win95 桌面",tier:"地狱",cat:"app"},
 {id:"applecard",name:"Apple 风格产品页",tier:"实战",cat:"page"},{id:"stripe",name:"Stripe 风格首屏",tier:"实战",cat:"page"},
 {id:"iostodo",name:"iOS 待办应用",tier:"实战",cat:"app"},{id:"ecomdetail",name:"电商详情页",tier:"实战",cat:"page"},
 {id:"ioscalc",name:"iOS 计算器",tier:"实战",cat:"app"},{id:"dock",name:"macOS Dock",tier:"实战",cat:"app"},
 {id:"terminal",name:"macOS 终端",tier:"实战",cat:"app"},{id:"parallax",name:"3D 悬停卡片",tier:"实战",cat:"page"},
 {id:"glasslogin",name:"玻璃拟态登录页",tier:"实战",cat:"page"},{id:"feed",name:"社区信息流",tier:"实战",cat:"page"},
];
function renderTaskChips(){
  const box=$("genTasks");
  if(box.childElementCount)return;  /* 已渲染则保留勾选状态 */
  const groups={};TASK_CATALOG.forEach(t=>(groups[t.tier]=groups[t.tier]||[]).push(t));
  box.innerHTML=Object.entries(groups).map(([tier,list])=>`<div class="task-group" data-tier="${esc(tier)}">
    <div class="task-group-head"><span class="task-group-name">${esc(tagName(tier))}</span><span class="task-group-count"></span>
      <button type="button" class="btn btn-ghost btn-sm" data-group-toggle>全选</button></div>
    <div class="chips">${list.map(t=>`<label class="chip"><input type="checkbox" value="${esc(t.id)}" checked>${icon("check")}<span>${esc(t.name)}</span></label>`).join("")}</div></div>`).join("");
  chipChange();
}
$("genTasks").addEventListener("change",chipChange);
$("genTasks").addEventListener("click",e=>{
  const b=e.target.closest("[data-group-toggle]");if(!b)return;
  const boxes=[...b.closest(".task-group").querySelectorAll("input")];
  const all=boxes.every(x=>x.checked);boxes.forEach(x=>x.checked=!all);chipChange();
});
function selectedTasks(){return[...document.querySelectorAll("#genTasks input:checked")].map(x=>x.value)}
function chipChange(){
  document.querySelectorAll("#genTasks .task-group").forEach(gp=>{
    const boxes=[...gp.querySelectorAll("input")],n=boxes.filter(x=>x.checked).length;
    gp.querySelector(".task-group-count").textContent=`${n} / ${boxes.length}`;
    gp.querySelector("[data-group-toggle]").textContent=n===boxes.length?"清空":"全选";
  });
  $("genTaskCount").textContent=`已选 ${selectedTasks().length} / ${TASK_CATALOG.length}`;
}
function genSamplingUI(){
  const v=$("genSampling").value;
  document.querySelectorAll("[data-gen-custom]").forEach(f=>f.hidden=v!=="custom");
  $("genSamplingHelp").querySelector(".help").textContent={
    official:"官方推荐：思考时 temperature 0.6 / top_p 0.95，不思考时 0.7 / 0.8，top_k 20，固定随机种子 42。温度太低时小模型写长文件容易陷入无限重复",
    legacy:"旧版低温：temperature 0.3。只在需要和 2.2 之前的结果对比时使用，小模型更容易陷入重复输出",
    custom:"自定义：留空的项使用官方推荐值；presence_penalty 调高可以减少重复，但可能影响代码质量"}[v]||"";
}
$("genSampling").addEventListener("change",genSamplingUI);
genSamplingUI();
function genSamplingBody(){
  const v=$("genSampling").value;
  if(v!=="custom")return v;
  return{temperature:$("genTemp").value,top_p:$("genTopP").value,top_k:$("genTopK").value,presence_penalty:$("genPresence").value};
}
function judgeBody(){return{judge_base:$("genJudgeBase").value.trim(),judge_model:$("genJudgeModel").value.trim(),judge_key:$("genJudgeKey").value}}
function judgeValid(jb){if(!!jb.judge_base!==!!jb.judge_model){msg("genInfo","error","AI 看图打分需要同时填写服务地址和模型，或者都留空");return false}return true}
function evalMethodText(ev){
  if(!ev)return"";
  const m=ev.method==="browser"?"在后台浏览器里实际运行检查":"只看代码（没找到 Chrome / Edge，结果仅供参考）";
  return "检查方式："+m+(ev.judge_model?" + AI 看图打分（"+ev.judge_model+"）":"，没有配置 AI 看图打分");
}
async function genStart(){
  const model=$("genModel").value.trim();
  if(!model){msg("genInfo","error","请填写模型名称");$("genModel").focus();return}
  const tasks=selectedTasks();
  if(!tasks.length){msg("genInfo","error","请至少选 1 道题");return}
  const jb=judgeBody();if(!judgeValid(jb))return;
  const d=await postWithConflict("/api/gen-start",{base:$("genBase").value,api_key:$("genKey").value,model,conc:$("genConc").value,
    tag:$("genTag").value,tasks,thinking:$("genThink").checked,sampling:genSamplingBody(),...jb});
  if(!d)return;
  if(!d.ok){msg("genInfo","error",d.error);return}
  msg("genInfo","info",evalMethodText(d.eval));
  watchGen(`进行中 · ${model} · ${tasks.length} 题`);
}
async function genReeval(){
  const runId=$("genMainSel").value;
  if(!runId){toast("没有可以重新检查的任务","warning");return}
  const jb=judgeBody();
  if(!!jb.judge_base!==!!jb.judge_model){toggleLauncher("genLauncher",true);judgeValid(jb);return}
  const d=await postJSON("/api/gen-eval",{run_id:runId,...jb});
  if(!d.ok){toast(d.error,"error");return}
  toggleLauncher("genLauncher",true);
  msg("genInfo","info",evalMethodText(d.eval));
  watchGen("重新检查 · "+(GEN_RUNS[runId]?genLabel(GEN_RUNS[runId]):runId),runId);
}
function watchGen(title,keepRun){
  $("genBtnStart").disabled=true;$("genBtnEval").disabled=true;
  genLog.start(title);
  clearInterval(genPoll);
  genPoll=pollStatus("/api/gen-status",genLog,{interval:3000,onDone:()=>{
    $("genBtnStart").disabled=false;$("genBtnEval").disabled=false;
    loadGenResults(!keepRun,keepRun);
  }});
}
async function loadGenResults(focusNew,keepRun){
  if(!GEN_LOADED)$("genResult").innerHTML=genSkeleton();
  try{
    const list=await getJSON("/api/gen-results");
    const prev=new Set(Object.keys(GEN_RUNS));
    GEN_RUNS={};list.forEach(r=>GEN_RUNS[r.run_id]=r);GEN_LOADED=true;
    const names=Object.keys(GEN_RUNS).sort().reverse();
    const fresh=focusNew?names.find(n=>!prev.has(n)):null;
    const main=$("genMainSel"),cmp=$("genCmpSel");
    const keepMain=keepRun||fresh||(GEN_RUNS[main.value]?main.value:names[0]);
    const keepCmp=GEN_RUNS[cmp.value]?cmp.value:"";
    const opts=k=>names.map(n=>`<option value="${esc(n)}" ${n===k?"selected":""}>${esc(genLabel(GEN_RUNS[n]))}</option>`).join("");
    main.innerHTML=opts(keepMain);
    cmp.innerHTML=`<option value="">不对比</option>`+opts(keepCmp);
    if(!names.length&&VIEW==="gen")toggleLauncher("genLauncher",true);
    renderGen();
  }catch(e){$("genResult").innerHTML=emptyState("无法加载生成结果",e.message,{iconName:"alert"})}
}
function avgOf(xs){const v=xs.filter(x=>typeof x==="number"&&isFinite(x));return v.length?v.reduce((p,q)=>p+q,0)/v.length:null}
function genStats(r){
  const items=r.items||[];
  const ok=items.filter(x=>!x.error);
  const v2=!!((r.eval&&r.eval.eval_version)||ok.some(x=>x.eval));
  const browser=ok.filter(x=>x.eval&&x.eval.method==="browser");
  const stat=ok.filter(x=>x.eval&&x.eval.method==="static");
  const mode=browser.length&&stat.length?"mixed":stat.length?"static":browser.length?"browser":((r.eval||{}).method==="static"?"static":"browser");
  const execPool=mode==="static"?(stat.length?stat:ok):(browser.length?browser:ok);
  const judged=ok.filter(x=>typeof x.judge_score==="number");
  const judgeErr=ok.filter(x=>x.eval&&x.eval.judge&&x.eval.judge.error&&typeof x.judge_score!=="number");
  const starred=ok.filter(x=>typeof x.stars==="number"&&x.stars>0);
  return{ok,v2,mode,browserN:browser.length,staticN:stat.length,
    exec:v2?avgOf(execPool.map(x=>x.exec_score)):null,
    judge:avgOf(judged.map(x=>x.judge_score)),judgeN:judged.length,judgeErr:judgeErr.length,
    stars:avgOf(starred.map(x=>x.stars)),starN:starred.length,
    planned:r.planned||items.length};
}
function genLabel(r){
  const s=genStats(r);
  const parts=[r.model||"?",runFw(r),r.thinking?"思考":"不思考",`完成 ${s.ok.length}/${s.planned}`,r.status&&r.status!=="done"?STATUS_NAME[r.status]||r.status:""];
  if(s.exec!=null)parts.push(`${s.mode==="static"?"只看代码":"运行检查"} ${s.exec.toFixed(0)}%`);
  if(s.judge!=null)parts.push(`AI 打分 ${s.judge.toFixed(0)}`);
  if(s.stars!=null)parts.push(`人工 ${s.stars.toFixed(1)}（${s.starN}）`);
  if(!s.v2)parts.push("旧版检查");
  parts.push(shortTime(r.started_utc));
  return parts.filter(Boolean).join(" · ");
}
function scoreCls(p){return p==null?"":p>=80?"good":p>=50?"mid":"bad"}
/* 检查项的大白话名称(原名放在悬停提示里) */
const CHECK_PLAIN={load:"能正常打开，没有卡死",nonblank:"打开后有内容（不是白屏）",animated:"不操作时画面也在动",no_error:"运行时没有报错",
  responsive:"手机屏幕上显示正常",self_contained:"不依赖外部网络资源",complete:"代码写完整了",probe:"检查过程顺利完成",doctype:"是完整的网页代码"};
function plainCheck(c){
  if(CHECK_PLAIN[c.id])return CHECK_PLAIN[c.id];
  if(/^step/.test(c.id))return "操作：“"+String(c.label).replace(/^交互：/,"")+"”有反应";
  if(/^f\d/.test(c.id))return "代码里有相关实现（关键词 "+String(c.label).replace(/^源码特征 \//,"").replace(/\/$/,"")+"）";
  return c.label;
}
/* 没通过时直接说哪里不行 */
const CHECK_FAIL={load:"打不开或卡死",nonblank:"打开后是白屏",animated:"不操作时画面不动",no_error:"运行时报错",
  responsive:"手机屏幕上显示不正常",self_contained:"依赖外部网络资源（已被拦截）",complete:"代码没写完整",probe:"检查过程中断",doctype:"不是完整的网页代码"};
function failText(c){
  if(CHECK_FAIL[c.id])return CHECK_FAIL[c.id];
  if(/^step/.test(c.id))return "操作“"+String(c.label).replace(/^交互：/,"")+"”没反应";
  if(/^f\d/.test(c.id))return "代码里没找到相关实现（关键词 "+String(c.label).replace(/^源码特征 \//,"").replace(/\/$/,"")+"）";
  return c.label+" 没通过";
}
function repText(d){
  if(!d)return"";
  return d.kind==="loop"||d.period?`同一段内容每 ${d.period} 个字符循环一次，重复了 ${fmtInt(d.repeats)} 次`:"内容高度雷同（像是在机械地复制或计数）";
}
/* 作品的主要问题: 按优先级只取一个, 用于归因统计和卡片标题 */
const VERDICTS=[
  ["pass","全部检查通过","good","模型写得不错"],
  ["partial","部分功能没反应","warn","模型写的功能不完整"],
  ["error","运行报错","bad","作品本身的 bug"],
  ["blank","白屏或打不开","bad","作品本身的问题"],
  ["unfinished","代码没写完","bad","太长没写完"],
  ["repeat","陷入重复输出","bad","模型自身的问题"],
  ["fail","生成失败","bad","请求出错或没写出代码"],
  ["env","报错可能是检测引起","warn","需要人工确认"],
  ["static","没有实际运行","neutral","评测环境问题"],
];
const VERDICT_META=Object.fromEntries(VERDICTS.map(([k,n,tone,why])=>[k,{name:n,tone,why}]));
function genVerdict(it){
  if(it.error)return{key:"fail",text:(it.degenerate?"模型陷入重复输出，没写出有效代码":"生成失败："+it.error)};
  if(it.degenerate)return{key:"repeat",text:`模型陷入重复输出：${repText(it.degenerate)}，已提前停止`};
  const e=it.eval||{},by=Object.fromEntries((e.checks||[]).map(c=>[c.id,c]));
  if(it.unfinished||(by.complete&&!by.complete.pass))return{key:"unfinished",text:it.unfinished?"接着写了多轮仍没写完（写到长度上限）":"代码没写完整（缺少结尾或脚本没闭合）"};
  if(!it.eval)return{key:"static",text:"还没有检查"};
  if(e.method==="static")return{key:"static",text:"没有在浏览器里实际运行，只检查了代码里的关键词"};
  if(by.load&&!by.load.pass)return{key:"blank",text:"页面打不开或卡死"};
  if(by.nonblank&&!by.nonblank.pass)return{key:"blank",text:"打开后是白屏"};
  if(by.no_error&&!by.no_error.pass){
    const ctl=e.control;
    if(ctl&&ctl.reproduced===false)return{key:"env",text:"运行报错，但在干净环境里没有复现，可能是检测引起的"};
    return{key:"error",text:"运行时报错"+(ctl&&ctl.reproduced?"（干净环境里同样报错，是作品本身的问题）":"")};
  }
  const fails=(e.checks||[]).filter(c=>!c.pass);
  if(fails.length)return{key:"partial",text:fails.slice(0,2).map(failText).join("；")+(fails.length>2?`，还有 ${fails.length-2} 项`:"")};
  return{key:"pass",text:"全部检查通过"};
}
/* 框架对模型输出做过什么: 用于回答"作品是不是被框架弄坏了" */
function changeKind(it){
  if(!Array.isArray(it.changes))return"legacy";
  const c=it.changes.join("\n");
  if(/改为不思考/.test(c))return"rescued";
  if(/续写|重写/.test(c))return"stitched";
  if(/原样保存/.test(c))return"raw";
  return"trimmed";
}
const CHANGE_KINDS=[["raw","原样保存，一个字没改"],["trimmed","只去掉了代码前后的说明文字或代码块标记"],["stitched","把多轮接着写的内容拼接起来"],["rescued","思考失败，改为不思考重新生成"],["legacy","旧任务，没有保存原始输出"]];
function tone2color(t){return t==="good"?C.goodMark:t==="bad"?C.badMark:t==="warn"?C.warnMark:C.axis}

/* ============================================================
   作品列表: 卡片(缩略图 / 标题 / 自己的问题 / 检查 / 数据 / 操作) · 分页 · 筛选 · 搜索 · 排序 · A / B 并排 · 表格
   下面「纯逻辑」一节的函数不碰页面(缩略图选哪张、谁更好、卡片上写什么、筛选与分页), tests/js/checks.js 有断言。
   ============================================================ */
let GEN_SORT="default";
const GEN_SORTS=[["default","按题目顺序"],["pass","检查通过项（少的在前）"],["lines","代码行数（多的在前）"],["tokens","输出 token（多的在前）"],["rounds","接着写的轮数（多的在前）"],["stars","人工星级（高的在前）"]];
const GEN_LS="llm-bench-pro-gen-works";        /* 每页几件、上次看到第几页(同一个测试和筛选下刷新页面停在原处) */
const GEN_PREF=lsGet(GEN_LS);
const GW_SIZES=[12,24,48];
let GEN_TIER="all",GEN_Q="",GEN_PAGE=0,GEN_SIZE=GW_SIZES.includes(GEN_PREF.size)?GEN_PREF.size:12;
const GW={a:null,b:null,rows:[],ctx:null,ctxB:null,mainId:"",pairId:"",sigTable:""};   /* 当前这一节要用的数据, 筛选 / 翻页时只重画这一节 */

/* ---------- 纯逻辑 ---------- */
function genSortRows(rows,sort){
  const key={pass:x=>x.it.error?-1:(x.it.total?x.it.pass/x.it.total:0),lines:x=>-(x.it.lines||0),tokens:x=>-(x.it.out_tokens||0),rounds:x=>-(x.it.continuations||0),stars:x=>-(x.it.stars||0)}[sort];
  if(!key)return rows;
  return rows.map((x,i)=>[x,key(x),i]).sort((p,q)=>p[1]-q[1]||p[2]-q[2]).map(x=>x[0]);
}

/* 缩略图选哪张(规则):
   1. 只用桌面尺寸的截图(1280×800, 缩小后 768×480, 正好是 16:10); 手机尺寸(*_mobile, 390 宽的竖屏)不用;
   2. 首选「空闲后」那张(*_idle): 作品已经打开一会儿、动画在跑、还没有任何操作。比首屏晚一点, 启动 / 加载中的画面(例如 Win95 的黑色开机画面)
      已经过去; 游戏类是标题画面, 像封面; A / B 对比时两边拍的是同一个时刻, 看起来公平;
   3. 没有就用首屏(*_initial), 再没有就用第一张桌面截图;
   4. 不选操作之后的截图: 滚动 / 点击之后常常是黑屏或半截画面(实测好几件作品如此), 想看操作后的画面点「详情」。
   没有截图(只看了代码 / 浏览器没起来 / 旧版本)返回 null, 列表显示占位。 */
function genPickShot(it){
  const e=it&&it.eval;
  if(!e||!it.file||!e.shots_dir||!Array.isArray(e.shots))return null;
  const desk=e.shots.filter(s=>s&&s.file&&!/mobile/i.test(String(s.name||s.file)));
  const s=desk.find(x=>/idle$/.test(String(x.name||"")))||desk.find(x=>/initial$/.test(String(x.name||"")))||desk[0];
  if(!s)return null;
  return{file:s.file,name:s.name||"",caption:s.caption||"",path:it.file.replace(/[^/]+$/,"")+e.shots_dir+"/"+s.file};
}

/* 谁更好(A / B 对比, 一道题一个结论), 判断顺序:
   1. 有一边没生成出来: 另一边更好(两边都没生成出来: 不比);
   2. 两边都有人工星级: 比星级(相同就是差不多);
   3. 否则两边都有 AI 看图打分: 比 AI 分(差 5 分以内算差不多);
   4. 否则比检查通过的比例(6/6 比 4/6; 通过数一样就是差不多); 一边实际运行、一边只看了代码时检查方式不同, 不比。
   返回 {side: a | b | tie | none, basis: gen | stars | judge | checks, text: 一句话说明}; 有一边没有这道题返回 null。 */
const GEN_WIN_RULE="怎么判断谁更好：有一边没生成出来，另一边更好；两边都有人工星级，比星级；否则两边都有 AI 看图打分，比 AI 分（差 5 分以内算差不多）；再否则比检查通过的比例。一边实际运行、一边只看了代码时，检查方式不同，不比。";
const GEN_JUDGE_TIE=5;
function genWinner(ia,ib){
  if(!ia||!ib)return null;
  if(ia.error&&ib.error)return{side:"none",basis:"gen",text:"两边都没生成出来"};
  if(ia.error)return{side:"b",basis:"gen",text:"A 没生成出来"};
  if(ib.error)return{side:"a",basis:"gen",text:"B 没生成出来"};
  const star=x=>typeof x.stars==="number"&&x.stars>0?x.stars:0,sa=star(ia),sb=star(ib);
  if(sa&&sb)return{side:sa===sb?"tie":sa>sb?"a":"b",basis:"stars",text:`人工评分 A ${sa} 星，B ${sb} 星`};
  const ja=ia.judge_score,jb=ib.judge_score;
  if(typeof ja==="number"&&typeof jb==="number"){
    const d=ja-jb;
    return{side:Math.abs(d)<GEN_JUDGE_TIE?"tie":d>0?"a":"b",basis:"judge",text:`AI 打分 A ${fmt(ja,0)} 分，B ${fmt(jb,0)} 分`};
  }
  const ma=(ia.eval&&ia.eval.method)||"legacy",mb=(ib.eval&&ib.eval.method)||"legacy";
  if(ma!==mb)return{side:"none",basis:"checks",text:"检查方式不同（一边实际运行，一边只看了代码），不比较"};
  if(!ia.total||!ib.total)return{side:"none",basis:"checks",text:"还没有检查结果"};
  const ra=ia.pass/ia.total,rb=ib.pass/ib.total,label=ma==="browser"?"运行检查":"代码关键词";
  return{side:Math.abs(ra-rb)<1e-9?"tie":ra>rb?"a":"b",basis:"checks",text:`${label}通过 A ${ia.pass}/${ia.total}，B ${ib.pass}/${ib.total}`};
}
function genWinLabel(w){return !w?"":({a:"A 更好",b:"B 更好",tie:"差不多"}[w.side]||"没法比")}

/* 整次测试共同的情况(没在浏览器里运行、旧版检查)只在页面顶部说一次; 卡片上只写这件作品自己的问题 */
function genStaticWhy(ev,items){return ev.browser_error||(items.map(x=>x.eval&&x.eval.notes&&x.eval.notes[0]).find(Boolean))||"后台浏览器没有启动"}
function genRunCtx(s,ev,items){
  return{v2:!!s.v2,mode:s.mode,shared:s.v2&&(s.mode==="static"||s.mode==="mixed")?genStaticWhy(ev||{},items||[]):""};
}
const STRIP_CLOSED=new Set();
function genStrip(a,s,ev,items){
  if(!(s.v2&&(s.mode==="static"||s.mode==="mixed"))||STRIP_CLOSED.has(a.run_id))return "";
  const why=genStaticWhy(ev,items);
  return `<div class="strip is-bad" role="status">${icon("x-circle")}<span class="strip-text"><b>${s.mode==="static"?"这些作品没有在浏览器里实际运行":`有 ${s.staticN} 件作品没有在浏览器里实际运行`}</b>，只检查了代码里的关键词，通过率不能代表作品真的能用。
      <span class="faint" title="${esc(why)}">原因：${esc(why)}</span></span>
    <button class="btn btn-secondary btn-sm" data-online-only onclick="genReeval()">${icon("scan-check")}重新检查</button>
    <button class="btn btn-ghost btn-icon btn-sm" data-strip-close="${esc(a.run_id)}" aria-label="收起提示" title="收起提示">${icon("x")}</button></div>`;
}
function genFailList(it){return it.eval?(it.eval.checks||[]).filter(c=>!c.pass):[]}
function genFailNote(fails){return fails.slice(0,2).map(failText).join("；")+(fails.length>2?`，还有 ${fails.length-2} 项`:"")}
/* 卡片上的状态标签和「自己的问题」:
   - 整次测试都只看了代码 / 都是旧版检查: 状态标签不写(每张都一样, 顶部写过了), 有没找到的代码关键词才写;
   - 一部分只看了代码: 标「没有实际运行」, 原因和顶部警示带一样就不再写;
   - 其余(报错、白屏、没写完、陷入重复、生成失败、部分功能没反应)都是这件作品自己的问题, 原样写一句。 */
function genCardInfo(it,v,ctx){
  const meta=VERDICT_META[v.key]||{tone:"neutral",name:""};
  let badge={tone:meta.tone,text:meta.name},note="";
  if(v.key==="static"){
    const common=!ctx.v2||ctx.mode==="static";
    const fails=genFailList(it),why=(it.eval&&it.eval.notes&&it.eval.notes[0])||"";
    note=fails.length?genFailNote(fails):(!common&&why&&why!==ctx.shared?why:"");
    if(common)badge=null;
    else if(!it.eval)badge={tone:"neutral",text:"还没有检查"};
  }else if(v.key!=="pass")note=v.text;
  return{key:v.key,tone:meta.tone,name:meta.name,badge,note};
}
/* 检查结果: 「运行检查 5/6」「代码关键词 3/5」, 旧版本(没有 eval)也是关键词 */
function genScore(it){
  const e=it.eval;
  if(it.error||!(it.total>0))return null;
  const label=!e||e.method==="static"?"代码关键词":"运行检查";
  const pct=typeof it.exec_score==="number"?it.exec_score:100*it.pass/it.total;
  return{label,text:`${label} ${it.pass}/${it.total}`,cls:scoreCls(pct)};
}
function genCheckSegs(it){
  const e=it.eval;
  if(e&&Array.isArray(e.checks))return e.checks.map(c=>({pass:!!c.pass,tip:(c.pass?"通过："+plainCheck(c):"没通过："+failText(c))+(c.detail?"\n"+c.detail:"")}));
  if(Array.isArray(it.checks))return it.checks.map((p,i)=>{const f=(it.features||[])[i];return{pass:!!p,tip:(p?"通过":"没通过")+(f?"：代码里"+(p?"有":"没有")+"「"+f+"」":"")}});
  return[];
}
function genDataLine(it){
  return[it.lines?`${fmtInt(it.lines)} 行`:"",it.continuations?`接着写 ${it.continuations} 轮`:"",it.out_tokens?`${fmtInt(it.out_tokens)} token`:""].filter(Boolean).join(" · ");
}

/* 筛选: 状态标签 × 难度 × 名称搜索。row = {it, v, ib, vb, win} */
function genMatchStatus(f,row){
  if(f==="all")return true;
  if(f==="issues")return row.v.key!=="pass";
  if(f==="win-a"||f==="tie"||f==="win-b")return !!row.win&&row.win.side===({"win-a":"a","tie":"tie","win-b":"b"})[f];
  return row.v.key===f;
}
function genMatchTier(t,row){return t==="all"||(row.it.tags||[]).includes(t)}
function genMatchName(q,row){
  q=String(q||"").trim().toLowerCase();
  return !q||[row.it.name,row.it.id].some(x=>String(x||"").toLowerCase().includes(q));
}
function genFilterRows(rows,{status="all",tier="all",q=""}={}){
  return rows.filter(r=>genMatchStatus(status,r)&&genMatchTier(tier,r)&&genMatchName(q,r));
}
/* 标签上的数字: 状态标签按「难度 + 搜索」算, 难度标签按「状态 + 搜索」算, 和点下去看到的件数一样 */
function genCounts(rows,st,statuses,tiers){
  const by={},byTier={};
  statuses.forEach(k=>by[k]=genFilterRows(rows,{status:k,tier:st.tier,q:st.q}).length);
  tiers.forEach(t=>byTier[t]=genFilterRows(rows,{status:st.status,tier:t,q:st.q}).length);
  return{by,byTier};
}
/* 翻页: 页码夹在 [0, 最后一页] */
function pageWindow(total,size,page){
  const pages=Math.max(1,Math.ceil(total/size)),p=Math.min(Math.max(0,parseInt(page,10)||0),pages-1);
  return{pages,page:p,start:p*size,end:Math.min(total,(p+1)*size)};
}
/* 「同一个测试、同一组筛选」的签名: 变了就回到第 1 页; 一样(刷新页面)就停在记住的那一页 */
function genViewSig(){return[GW.mainId,GW.pairId,GEN_FILTER,GEN_TIER,GEN_Q,GEN_SORT].join("|")}
function genSavePos(){lsSet(GEN_LS,{size:GEN_SIZE,page:GEN_PAGE,sig:genViewSig()})}
function genRows(a,b){
  const itB=id=>b?(b.items||[]).find(x=>x.id===id)||null:null;
  return(a.items||[]).map(it=>{const ib=itB(it.id);
    return{it,v:genVerdict(it),ib,vb:ib?genVerdict(ib):null,win:ib?genWinner(it,ib):null}});
}
/* 换了测试: 回到第 1 页(A 换了连筛选、搜索一起清掉); B 换了只回到第 1 页 */
function genViewSync(a,b){
  const main=a.run_id,pair=b?b.run_id:"",first=!GW.mainId;
  if(GW.mainId&&GW.mainId!==main){GEN_FILTER="all";GEN_TIER="all";GEN_Q="";GEN_PAGE=0}
  else if(!first&&GW.pairId!==pair)GEN_PAGE=0;
  if(!b&&/^(win-a|tie|win-b)$/.test(GEN_FILTER))GEN_FILTER="all";
  GW.mainId=main;GW.pairId=pair;
  if(first&&GEN_PREF.sig===genViewSig()&&GEN_PREF.page>0)GEN_PAGE=GEN_PREF.page;
}

/* ---------- 缩略图与卡片 ---------- */
const GEN_CATS={anim:"clapperboard",game:"gamepad",d3:"box",page:"layout",app:"app-window"};
const TASK_BY_ID=Object.fromEntries(TASK_CATALOG.map(t=>[t.id,t]));
function genTierIdx(it){const i=TIER_ORDER.findIndex(t=>(it.tags||[]).includes(t));return i<0?0:i}
/* 没有截图时的占位: 按难度换淡色底(data-t 0–3), 图标按题目类别(动画 / 游戏 / 3D / 网页 / 应用) */
function genPhHTML(it,msg,ic,sub){
  const cat=(TASK_BY_ID[it.id]||{}).cat;
  return `<span class="work-ph" data-t="${genTierIdx(it)}">${icon(ic||GEN_CATS[cat]||GEN_CATS.page,"icon-lg")}<span>${esc(msg)}</span>${sub?`<span class="work-ph-sub">${esc(sub)}</span>`:""}</span>`;
}
function genThumbHTML(run,it,tag){
  const ref=`data-run="${esc(run.run_id)}" data-item="${esc(it.id)}"`;
  if(!it.file||it.error){
    const msg=it.error?"没有生成出来":"没有作品文件";
    return `<div class="work-thumb is-static" title="${esc(it.error?msg+"："+it.error:msg)}">${genPhHTML(it,msg,it.error?"x-circle":"ban")}</div>`;
  }
  const shot=genPickShot(it),src=shot?workUrl(shot.path):"";
  const inner=src?`<img class="work-shot" src="${esc(src)}" alt="" width="768" height="480" loading="lazy" decoding="async" data-shot="${esc(shot.path)}">`
    :genPhHTML(it,shot?"报告里没有这张截图 · 点击预览":"没有截图 · 点击预览");
  return `<button type="button" class="work-thumb${src?" skeleton":""}" data-gen="preview" ${ref} tabindex="-1" aria-label="预览：${esc(it.name)}${tag?"（"+tag+"）":""}" title="预览「${esc(it.name)}」">${inner}<span class="work-thumb-hint" aria-hidden="true"><span>${icon("play")}预览</span></span></button>`;
}
function genFlagHTML(info){
  if(!info.badge)return "";
  const ic={good:"check",bad:"x",warn:"alert",neutral:"ban"}[info.badge.tone]||"minus",tone=info.badge.tone==="neutral"?"plain":info.badge.tone;
  return `<span class="work-flag"><span class="badge is-${tone}">${icon(ic)}${esc(info.badge.text)}</span></span>`;
}
function genActionsHTML(run,it){
  const can=!!it.file&&!it.error,e=it.eval,hasTrace=!!it.trace||!!it.rounds;
  const ref=`data-run="${esc(run.run_id)}" data-item="${esc(it.id)}"`,nm=esc(it.name);
  const prev=can?`<button type="button" class="btn btn-secondary btn-sm act-preview" data-gen="preview" ${ref} aria-label="预览：${nm}" title="预览：在隔离的沙箱里运行这件作品">${icon("play")}<span>预览</span></button>`:"";
  const open=workOpenLink(it,{label:true});
  const detail=e?`<button type="button" class="btn btn-ghost btn-sm" data-gen="detail" ${ref} aria-label="详情：${nm}" title="看截图和每一项检查">${icon("image")}<span>详情</span></button>`:"";
  const trace=hasTrace?`<button type="button" class="btn btn-ghost btn-sm" data-gen="trace" ${ref} aria-label="生成过程：${nm}" title="看模型每一轮的原始输出">${icon("layers")}<span>过程</span></button>`:"";
  const menu=(open?`<a class="menu-item" role="menuitem" href="${esc(workOpenUrl(it.file))}" target="_blank" rel="noopener noreferrer">${icon("external")}新标签页打开</a>`:"")+
    (detail?`<button type="button" class="menu-item" role="menuitem" data-gen="detail" ${ref}>${icon("image")}详情（截图和每项检查）</button>`:"")+
    (trace?`<button type="button" class="menu-item" role="menuitem" data-gen="trace" ${ref}>${icon("layers")}生成过程</button>`:"");
  const more=menu?`<details class="dropdown act-more"><summary class="btn btn-ghost btn-icon btn-sm" aria-label="更多操作：${nm}" title="更多操作">${icon("more")}</summary><div class="dropdown-panel menu" role="menu">${menu}</div></details>`:"";
  if(!prev&&!menu&&it.error)return `<div class="work-acts"></div>`;   /* 什么操作都没有(没生成出来又没有过程记录): 留空位, 不画分隔线 */
  return `<div class="work-acts"><div class="work-acts-in">${prev}<span class="act-inline">${open}${detail}${trace}</span>${more}${it.error?"":starsHTML(run,it)}</div></div>`;
}
/* 作品卡: 六行固定位置 —— 缩略图 / 标题行 / 这件作品自己的问题(没有就是空的) / 检查结果 / 数据 / 操作(含打星); 一排卡片用 subgrid 逐行对齐 */
function genCard(run,it,v,ctx,{tag="",inPair=false}={}){
  const info=genCardInfo(it,v,ctx),e=it.eval,j=e&&e.judge,sc=genScore(it),segs=genCheckSegs(it);
  const ref=`data-run="${esc(run.run_id)}" data-item="${esc(it.id)}"`;
  const judge=j&&j.score!=null?`<span class="badge" title="AI 看图打分${j.stale?"（基于旧截图）":""}">${icon("sparkle")}<b class="score ${scoreCls(j.score)}">${fmt(j.score,0)}</b></span>`:(j&&j.error?`<span class="badge is-bad">打分失败</span>`:"");
  const head=inPair
    ?`<header class="work-head"><span class="run-tag" style="background:${tag==="A"?C.a:C.b}">${tag}</span><span class="work-name" title="${esc(genLabel(run))}">${esc([run.model||"?",runFw(run)].filter(Boolean).join(" · "))}</span>${judge}</header>`
    :`<header class="work-head"><h3 class="work-name" title="${esc(it.name)}">${esc(it.name)}</h3><span class="badge">${esc(tierOf(it)||"—")}</span>${judge}</header>`;
  const note=info.note?`<p class="work-note is-${info.tone==="bad"?"bad":"warn"}" title="${esc(info.note)}">${icon(info.tone==="bad"?"x-circle":"alert","icon-sm")}<span>${esc(info.note)}</span></p>`:`<p class="work-note"></p>`;
  const bar=segs.length?`<span class="checkbar">${segs.map(s=>`<i class="${s.pass?"":"fail"}" title="${esc(s.tip)}"></i>`).join("")}</span>`:"",score=sc?`<span class="work-score score ${sc.cls}">${esc(sc.text)}</span>`:"";
  const checks=!bar&&!score?`<div class="work-checks"></div>`
    :e?`<button type="button" class="work-checks" data-gen="detail" ${ref} tabindex="-1" title="点一下看每一项检查和截图" aria-label="${esc(sc?sc.text:"检查结果")}，点开看每一项检查">${bar}${score}</button>`
    :`<div class="work-checks">${bar}${score}</div>`;
  return `<article class="work" data-item="${esc(it.id)}"><div class="work-media">${genThumbHTML(run,it,tag)}${genFlagHTML(info)}</div>${head}${note}${checks}<p class="work-data">${esc(genDataLine(it))}</p>${genActionsHTML(run,it)}</article>`;
}
/* 一道题的 A / B 并排: 行首标出谁更好, 两半按行对齐(缩略图并排); 判断规则在悬停提示里 */
function genPairHead(a,b,it,ib,win){
  const cls=!ib?"flat":{a:"up",b:"down"}[win.side]||"flat",ic={up:"arrow-up",down:"arrow-down"}[cls]||"minus";
  const label=!ib?"B 没有这道题":genWinLabel(win);
  const tip=GEN_WIN_RULE+(win?"\n\n这道题："+genWinLabel(win)+"（"+win.text+"）":"");
  const side=ib&&!ib.error&&!it.error&&it.file&&ib.file?`<button type="button" class="btn btn-ghost btn-sm pair-side" data-gen="compare" data-run="${esc(a.run_id)}" data-item="${esc(it.id)}" aria-label="并排预览：${esc(it.name)}" title="A 和 B 两件作品并排运行">${icon("columns")}<span>并排预览</span></button>`:"";
  return `<div class="pair-head"><span class="delta ${cls} pair-win" title="${esc(tip)}">${icon(ic)}${esc(label)}</span><h3 class="pair-name" title="${esc(it.name)}">${esc(it.name)}</h3><span class="badge">${esc(tierOf(it)||"—")}</span><span class="pair-why">${esc(win?win.text:"")}</span>${side}</div>`;
}
function genPairHTML(a,b,row,ctx,ctxB){
  const{it,v,ib,vb,win}=row;
  return `<div class="work-pair" data-item="${esc(it.id)}">${genPairHead(a,b,it,ib,win)}${genCard(a,it,v,ctx,{tag:"A",inPair:true})}${ib?genCard(b,ib,vb,ctxB,{tag:"B",inPair:true}):`<div class="work is-empty">${emptyState("B 没有这道题","",{inline:true})}</div>`}</div>`;
}
/* 加载中: 与最终布局同形的骨架(概览 + 一屏卡片) */
function genSkeleton(){
  const line=(w,h=12,mt=0)=>`<div class="skeleton" style="height:${h}px;width:${w}%;margin-top:${mt}px"></div>`;
  const card=`<div class="work is-sk" aria-hidden="true"><div class="work-media"><div class="work-thumb skeleton"></div></div><div class="work-head">${line(55,14)}</div><p class="work-note"></p><div class="work-checks">${line(70,10)}</div><div class="work-data">${line(45,10)}</div><div class="work-acts">${line(100,28)}</div></div>`;
  return `<div class="ov"><div>${line(18)}${line(88,12,14)}${line(76,12,14)}${line(82,12,14)}</div>
    <div class="ov-stats">${'<div class="stat"><div class="skeleton" style="height:10px;width:50%"></div><div class="skeleton" style="height:26px;width:66%;margin-top:12px"></div></div>'.repeat(4)}</div></div>
    <div class="sec" aria-busy="true"><div class="skeleton" style="height:14px;width:12%"></div><div class="skeleton" style="height:36px;width:100%;margin-top:16px"></div><div class="work-grid" style="margin-top:16px">${card.repeat(6)}</div></div>`;
}

/* ---------- 这一节的渲染: 筛选标签 · 卡片(分页) · 翻页器 · 表格 ---------- */
function genChipHTML(attr,val,label,n,pressed,tip){
  return `<button type="button" class="filter-chip" ${attr}="${esc(val)}" aria-pressed="${pressed}"${tip?` title="${esc(tip)}"`:""}>${esc(label)} <b>${fmtInt(n)}</b></button>`;
}
function genRenderWorks(opt={}){
  const{a,b,rows,ctx,ctxB}=GW,list=$("gwList");
  if(!a||!list)return;
  const st={status:GEN_FILTER,tier:GEN_TIER,q:GEN_Q};
  /* 状态标签: 全部 / 有问题的 / 各类问题(整个测试里有的才列出, 选中的一直在) / 全部通过 / (对比时)A 更好 · 差不多 · B 更好 */
  const has=k=>genFilterRows(rows,{status:k}).length>0;
  const kinds=VERDICTS.map(([k])=>k).filter(k=>k!=="pass"&&(has(k)||k===GEN_FILTER));
  const statuses=[["all","全部"],["issues","有问题的"],...kinds.map(k=>[k,VERDICT_META[k].name]),["pass","全部通过"]];
  const wins=b?[["win-a","A 更好"],["tie","差不多"],["win-b","B 更好"]]:[];
  const tiers=TIER_ORDER.filter(t=>rows.some(r=>(r.it.tags||[]).includes(t)));
  const cnt=genCounts(rows,st,[...statuses,...wins].map(x=>x[0]),tiers);
  const act=document.activeElement,fo=act&&act.closest&&act.closest("#gwChips [data-gen-filter],#gwTiers [data-gen-tier]");
  const foSel=fo?(fo.dataset.genFilter!=null?`[data-gen-filter="${fo.dataset.genFilter}"]`:`[data-gen-tier="${fo.dataset.genTier}"]`):"";
  $("gwChips").innerHTML=statuses.map(([k,n])=>genChipHTML("data-gen-filter",k,n,cnt.by[k],k===GEN_FILTER)).join("")+
    (wins.length?`<span class="qb-sep" aria-hidden="true"></span>`+wins.map(([k,n])=>genChipHTML("data-gen-filter",k,n,cnt.by[k],k===GEN_FILTER,GEN_WIN_RULE)).join(""):"");
  $("gwTiers").innerHTML=[["all","全部"],...tiers.map(t=>[t,tagName(t)])].map(([t,n])=>genChipHTML("data-gen-tier",t,n,t==="all"?genFilterRows(rows,{status:st.status,q:st.q}).length:cnt.byTier[t],t===GEN_TIER)).join("");
  if(foSel){const c=document.querySelector("#gen-works "+foSel);if(c)c.focus({preventScroll:true})}
  /* 筛选 → 排序 → 分页 */
  const all=genSortRows(genFilterRows(rows,st),GEN_SORT),pw=pageWindow(all.length,GEN_SIZE,GEN_PAGE);
  GEN_PAGE=pw.page;
  list.removeAttribute("aria-busy");
  if(!all.length){
    const narrowed=GEN_FILTER!=="all"||GEN_TIER!=="all"||GEN_Q.trim();
    list.innerHTML=!rows.length?emptyState("这个测试里还没有作品","",{inline:true})
      :emptyState("没有符合条件的作品",GEN_Q.trim()?`没有找到「${GEN_Q.trim()}」，换个名字或筛选条件试试`:"换一个筛选条件看看",
        {iconName:GEN_Q.trim()?"search":"inbox",inline:true,action:narrowed?`<button type="button" class="btn btn-secondary" data-gw-clear>${icon("x")}清除筛选</button>`:""});
  }else list.innerHTML=all.slice(pw.start,pw.end).map(r=>b?genPairHTML(a,b,r,ctx,ctxB):genCard(a,r.it,r.v,ctx)).join("");
  const unit=b?"题":"件";
  $("gwPagerTop").innerHTML=pagerHTML("gw",{page:pw.page,pages:pw.pages,compact:true,keys:true});
  $("gwPager").innerHTML=all.length?pagerHTML("gw",{page:pw.page,pages:pw.pages,total:all.length,unit,size:GEN_SIZE,sizes:all.length>GW_SIZES[0]?GW_SIZES:null,keys:true}):"";
  $("gwLive").textContent=all.length?`第 ${pw.page+1} / ${pw.pages} 页，共 ${all.length} ${unit}`:"没有符合条件的作品";
  /* 表格: 同一份筛选结果, 筛选或排序变了回到表格第一页 */
  const sig=[GW.mainId,GW.pairId,GEN_FILTER,GEN_TIER,GEN_Q,GEN_SORT].join("|");
  if(GW.sigTable!==sig||opt.table){
    GW.sigTable=sig;
    const specs=[genWorksTable(a,b,all,ctx),genCheckMatrix(a,all)];
    specs.forEach(s=>{dtState(s.id,s).page=0});
    $("gwTable").innerHTML=specs.map(dataTable).join("");
  }
  if(opt.focus){const el=document.querySelector("#gen-works "+opt.focus);if(el)el.focus({preventScroll:true})}
}
function genSetFilter(f,{scroll=false}={}){
  GEN_FILTER=f;GEN_PAGE=0;genSavePos();genRenderWorks();
  if(scroll){const w=$("gen-works");if(w)w.scrollIntoView({block:"start"})}
}
function genSetTier(t){GEN_TIER=t;GEN_PAGE=0;genSavePos();genRenderWorks()}
function genSetPage(p){
  const k=pagerFocusKey();
  GEN_PAGE=p;genSavePos();genRenderWorks();
  scrollTopIntoView($("gwChipRow"));
  pagerRefocus($("gen-works"),k);
}
function genClearFilters(){
  GEN_FILTER="all";GEN_TIER="all";GEN_Q="";GEN_PAGE=0;
  const s=$("genSearch");if(s)s.value="";
  genSavePos();genRenderWorks();
  if(s)s.focus();
}
/* 缩略图打不开: 换成占位, 写明原因(先说「没能显示」, 再向服务端确认是文件不在还是文件坏了) */
function genThumbFail(img){
  const t=img.closest(".work-thumb");if(!t)return;
  const r=GEN_RUNS[t.dataset.run],it=r&&(r.items||[]).find(x=>x.id===t.dataset.item);
  if(!it)return;
  t.classList.remove("skeleton");
  const fill=why=>{
    t.innerHTML=genPhHTML(it,"截图没能显示 · 点击预览","image-off",why)+`<span class="work-thumb-hint" aria-hidden="true"><span>${icon("play")}预览</span></span>`;
    t.title=`预览「${it.name}」（截图没能显示：${why}）`;
  };
  fill(OFF?"报告里的这张截图读不出来":"正在确认原因…");
  if(OFF)return;
  fetch(img.getAttribute("src"),{cache:"no-store"}).then(x=>fill(x.status===404?"截图文件不存在，可能被删除或移走了":x.ok?"截图文件读不出来，可能已损坏":"加载失败（HTTP "+x.status+"）"))
    .catch(e=>fill("连不上后端服务（"+e.message+"）"));
}
function renderGen(){
  if(!GEN_LOADED)return;
  const el=$("genResult");
  const a=GEN_RUNS[$("genMainSel").value],b0=GEN_RUNS[$("genCmpSel").value];
  const b=b0&&a&&b0.run_id!==a.run_id?b0:null;
  if(!a){el.innerHTML=emptyState("还没有生成任务","让模型写网页小游戏和应用，在后台浏览器里真正运行、点击、按键，检查能不能用。点右上角「新建生成任务」开始",
    {action:`<button class="btn btn-primary" data-toggle="genLauncher" data-online-only>${icon("plus")}新建生成任务</button>`});buildJump("genJump",null);return}
  const s=genStats(a),ev=a.eval||{};
  const items=a.items||[];
  const verdicts=items.map(it=>({it,v:genVerdict(it)}));
  const count=k=>verdicts.filter(x=>x.v.key===k).length;
  /* ---- 提示(环境问题用一条警示带, 其他仍是提示框) ---- */
  let alerts="";
  if(a.status&&a.status!=="done")alerts+=alertBox("warn",`这个任务${esc(STATUS_NAME[a.status]||a.status)}${a.error?"："+esc(a.error):""}。下面只有已经完成的题，原计划 ${s.planned} 题。`);
  if(!s.v2)alerts+=alertBox("warn","这个任务用的是旧版检查（只在代码里找关键词），分数不可信。在「更多」里点「重新检查作品」按新方式在浏览器里实际运行，人工评分会保留。");
  if(s.v2&&s.mode==="browser"&&verLt(ev.eval_version,"1.1.0"))
    alerts+=alertBox("warn",`这个任务的运行检查用的是 ${esc(ev.eval_version||"1.0")} 版规则：会把自带动画、鼠标悬停效果误判为“操作有反应”，输入“.”会丢字符，手机适配检查不生效。建议重新检查，人工评分会保留。`);
  if(a.thinking_dropped)alerts+=alertBox("warn","模型服务不接受“开启思考”的参数，这个任务实际上可能没有思考。");
  /* ---- 关键数字: 没有数据的不占位 ---- */
  const passN=count("pass");
  const execLabel=s.mode==="static"?"只看代码的命中率":"实际运行检查通过率";
  let stats=stat("完成的作品",`${s.ok.length}<small>/ ${s.planned}</small>`,"",{sub:items.length-s.ok.length?`${items.length-s.ok.length} 题没生成出来`:"全部生成出来了"})+
    stat("全部检查通过",`${passN}<small>件</small>`,"",{sub:items.length?`占 ${fmt(100*passN/items.length,0)}%`:""})+
    stat(s.mode==="static"?execLabel:term("run",execLabel),s.exec==null?"—":fmt(s.exec,1),s.exec==null?"":"%",
      {sub:s.mode==="static"?`<span class="warn">${icon("alert","icon-sm")} 没有实际运行，仅供参考</span>`:s.mode==="mixed"?`只统计实际运行的 ${s.browserN} 件`:"打开、报错、白屏、动画和操作反应"});
  const missing=[];
  if(s.judge!=null)stats+=stat(term("judge"),fmt(s.judge,1),"/ 100",{sub:`${s.judgeN} 件有分${s.judgeErr?`，${s.judgeErr} 件打分失败`:""}${ev.judge_model?" · "+esc(ev.judge_model):""}`});
  else missing.push(ev.judge_model?`${TERMS.judge.name}：都没打出分`:`没有配置${TERMS.judge.name}`);
  if(s.stars!=null)stats+=stat("人工平均星级",fmt(s.stars,1),"/ 5",{sub:`已评 ${s.starN} 件`});
  else missing.push("还没有人工评分（在作品卡片或作品表里点星星）");
  const nStats=3+(s.judge!=null)+(s.stars!=null);
  /* ---- 结论: 模型问题 vs 环境/框架问题 ---- */
  const modelIssues=["repeat","unfinished","error","blank","partial"].map(k=>[k,count(k)]).filter(x=>x[1]);
  const envIssues=["static","env"].map(k=>[k,count(k)]).filter(x=>x[1]);
  const ck={};items.forEach(it=>{const k=changeKind(it);ck[k]=(ck[k]||0)+1});
  const concl=[];
  concl.push({tone:passN===items.length?"good":"info",html:`${items.length} 件作品里，<b>${passN}</b> 件全部检查通过。`});
  if(modelIssues.length)concl.push({tone:"warn",html:"<b>模型自身的问题</b>："+modelIssues.map(([k,n])=>`${VERDICT_META[k].name} ${n} 件`).join("、")+"。"});
  if(count("fail"))concl.push({tone:"bad",html:`<b>${count("fail")}</b> 件没有生成出来（请求出错或没写出有效代码）。`});
  if(envIssues.length)concl.push({tone:"bad",html:"<b>评测环境的问题</b>（不能算在模型头上）："+envIssues.map(([k,n])=>`${VERDICT_META[k].name} ${n} 件`).join("、")+"。"});
  if(ck.legacy===items.length)concl.push({tone:"info",html:"这个任务生成于 2.3 之前，没有保存模型的原始输出，无法逐字核对框架有没有改动。之后的新任务会自动保存。"});
  else concl.push({tone:"good",html:`框架有没有改动模型写的代码：<b>${ck.raw||0}</b> 件原样保存，<b>${ck.trimmed||0}</b> 件只去掉了代码前后的说明文字或代码块标记${ck.stitched?`，<b>${ck.stitched}</b> 件拼接了接着写的内容`:""}${ck.rescued?`，<b>${ck.rescued}</b> 件思考失败后改为不思考重新生成`:""}。除此之外保存的作品和模型输出逐字一致。`});
  if(s.mode==="browser"||s.mode==="mixed"){
    const ctlN=items.filter(it=>it.eval&&it.eval.control&&it.eval.control.reproduced).length;
    if(ctlN)concl.push({tone:"info",html:`报错的作品里有 <b>${ctlN}</b> 件在不加任何检测代码的干净环境里${term("control","重新运行")}也同样报错，确认是作品自身的 bug。`});
  }
  /* ---- 问题出在哪: 两个进度条清单 + 表格 ---- */
  const whyT={id:"gen-why-t",title:"作品情况（按最主要的问题归类）",columns:[{key:"name",label:"问题",type:"text",sticky:true},{key:"n",label:"件数",type:"int"},{key:"pct",label:"占比",unit:"%",type:"bar",color:C.text3,max:100,digits:0},
      {key:"who",label:"算在谁头上",type:"text"},{key:"list",label:"作品",type:"text",wrap:true}],
    rows:VERDICTS.filter(([k])=>count(k)).map(([k,n,tone,why])=>({name:n,n:count(k),pct:100*count(k)/Math.max(1,items.length),who:why,list:verdicts.filter(x=>x.v.key===k).map(x=>x.it.name).join("、")}))};
  const chgT={id:"gen-chg-t",title:"框架对模型输出做过什么",columns:[{key:"name",label:"处理方式",type:"text",sticky:true,wrap:true},{key:"n",label:"件数",type:"int"},{key:"pct",label:"占比",unit:"%",type:"num",digits:0}],
    rows:CHANGE_KINDS.filter(([k])=>ck[k]).map(([k,n])=>({name:n,n:ck[k],pct:100*ck[k]/Math.max(1,items.length)}))};
  /* ---- 各难度: 汇总表为主 + 每档一张逐题进度条小卡 ---- */
  const tiers=TIER_ORDER.filter(t=>[a,b].some(r=>r&&(r.items||[]).some(it=>(it.tags||[]).includes(t))));
  const tierRows=tiers.map(t=>{const A=tierInfo(a,t),B=b?tierInfo(b,t):null;
    const dist={};A.its.forEach(it=>{const k=genVerdict(it).key;if(k!=="pass")dist[k]=(dist[k]||0)+1});
    return{name:tagName(t),n:A.its.length,avg:A.avg,avgB:B&&B.avg,pass:A.pass,fail:A.fail,
      issues:Object.entries(dist).sort((p,q)=>q[1]-p[1]).map(([k,n])=>`${VERDICT_META[k].name} ${n}`).join(" · ")||"—"}});
  const tierT={id:"gen-tier-t",title:"难度汇总",columns:[{key:"name",label:"难度",type:"text",sticky:true},{key:"n",label:"件数",type:"int"},
      {key:"avg",label:b?"A 平均通过率":"平均通过率",unit:"%",type:"bar",color:C.a,max:100},...(b?[{key:"avgB",label:"B 平均通过率",unit:"%",type:"bar",color:C.b,max:100}]:[]),
      {key:"pass",label:"全部通过",type:"int"},{key:"fail",label:"没生成出来",type:"int"},{key:"issues",label:"主要问题分布",type:"text",wrap:true}],rows:tierRows};
  /* ---- 作品: 卡片(分页) | 表格(作品表 + 检查矩阵); 筛选、搜索、排序、翻页只重画这一节 ---- */
  GW.a=a;GW.b=b;GW.ctx=genRunCtx(s,ev,items);GW.ctxB=b?genRunCtx(genStats(b),b.eval||{},b.items||[]):null;
  genViewSync(a,b);
  GW.rows=genRows(a,b);
  if(!GEN_SORTS.some(x=>x[0]===GEN_SORT))GEN_SORT="default";
  const worksMode=panelMode("gen-works");
  const onlyB=b?(b.items||[]).filter(x=>!items.some(y=>y.id===x.id)).length:0;
  el.innerHTML=genStrip(a,s,ev,items)+overview(concl,stats,{cols:2,meta:`${esc(a.model||"")} · ${a.thinking?"思考模式":"不思考"} · ${esc(samplingTextGen(a))} · ${esc(evalMethodText(ev))} · 开始于 ${esc(timeText(a.started_utc))}`+
      (missing.length?`<br>${missing.map(esc).join("；")}`:"")})+(alerts?`<div class="notes">${alerts}</div>`:"")+
    panel({id:"gen-why",title:"问题出在哪",jump:"问题归因",desc:"每件作品只按最主要的一个问题归类；红色是作品/模型的问题，灰色是评测环境的问题。点一行可以筛选下面的作品",
      chart:`<div class="grid-2">
        <div class="ccard"><div class="ccard-head"><div><h3 class="ccard-title">作品情况</h3><p class="ccard-desc">共 ${items.length} 件，鼠标放上去能看到是哪几件</p></div></div><div class="chart" id="genWhy"></div></div>
        <div class="ccard"><div class="ccard-head"><div><h3 class="ccard-title">框架有没有改动模型写的代码</h3><p class="ccard-desc">除这些处理外，保存的作品和模型写的逐字一致</p></div></div><div class="chart" id="genChange"></div>
          ${ck.legacy?`<p class="ccard-note">${ck.legacy===items.length?"这个任务":"其中 "+ck.legacy+" 件"}生成于 2.3 之前，没有保存模型原始输出；之后的新任务会自动保存，可以在作品的「生成过程」里逐字核对。</p>`:""}</div>
      </div>`,tables:[whyT,chgT],tcols:1})+
    panel({id:"gen-tier",title:"各难度的表现",jump:"难度",desc:`${s.mode==="static"?"只看代码的命中率（没有实际运行，仅供参考）":"实际运行检查的通过率"}，每张卡里按分数从高到低排列${b?"；右侧数字是 A / B":""}`,
      chart:dataTable(tierT)+tierCards(a,b,s.mode),tables:[tierT,genTaskTable(a,b)],tcols:1})+
    `<section class="sec" id="gen-works" data-jump="作品" data-pv="${worksMode}">
      <div class="sec-head"><div class="sec-head-text"><h2 class="sec-title">作品</h2><p class="sec-desc">点缩略图或「预览」直接玩，点检查结果或「详情」看截图和每一项检查，「过程」看模型的原始输出${b?"；每道题 A 在左、B 在右，题名前写着谁更好（先比人工星级，再比 AI 打分，最后比检查通过的比例）":""}${onlyB?`。B 里还有 ${onlyB} 道 A 没做的题，这里不显示`:""}</p></div>
        <div class="sec-tools">${segHTML("data-pv-set",worksMode,[["chart","卡片","layers"],["table","表格","table"]])}
          <button type="button" class="btn btn-ghost btn-icon btn-sm" data-pv-export title="导出作品表与检查矩阵（CSV）" aria-label="导出作品表">${icon("download")}</button></div></div>
      <div class="work-tools">
        <div class="qb-bar"><label class="qb-search">${icon("search")}<input class="input" id="genSearch" type="search" placeholder="按名称搜索作品" value="${esc(GEN_Q)}" aria-label="按名称搜索作品" autocomplete="off"></label>
          <label class="work-sort"><span>排序</span><select class="select" id="genSort">${GEN_SORTS.map(([k,n])=>`<option value="${k}" ${k===GEN_SORT?"selected":""}>${esc(n)}</option>`).join("")}</select></label></div>
        <div class="qb-chiprow" id="gwChipRow"><div class="filter-chips gw-chips" id="gwChips" role="group" aria-label="按状态筛选"></div><div class="qb-pager-top" id="gwPagerTop"></div></div>
        <div class="work-tier-row"><span class="work-tier-label" id="gwTierLabel">难度</span><div class="filter-chips gw-chips" id="gwTiers" role="group" aria-labelledby="gwTierLabel"></div></div>
      </div>
      <div class="pv-chart"><div class="${b?"work-pairs":"work-grid"}" id="gwList"></div><div class="qb-pager" id="gwPager"></div></div>
      <div class="pv-table" id="gwTable"></div>
      <span class="sr-only" id="gwLive" role="status" aria-live="polite"></span>
    </section>`;
  disposeDetached();
  drawGenCharts(a,b,verdicts,ck);
  buildJump("genJump",el);
  const gs=$("genSort");if(gs)CSelect.enhance(gs);
  GW.sigTable="";
  genRenderWorks();
}
function samplingTextGen(r){
  const sm=r.sampling;
  if(!sm)return "随机性：旧版 T0.3";
  const first=r.thinking?sm.think:sm.plain;
  return (sm.mode==="official"?"官方推荐采样":sm.mode==="legacy"?"旧版低温 T0.3":"自定义采样")+(first&&first.temperature!=null?`（temperature ${first.temperature}）`:"");
}
function tierOf(it){const t=(it.tags||[]).find(x=>TIER_NAME[x]);return t?tagName(t):""}
function starsHTML(run,it){
  const off=OFF?` tabindex="-1" aria-disabled="true"`:"";   /* 离线报告里星级只读 */
  return `<span class="stars" role="group" aria-label="人工评分：${esc(it.name)}">${[1,2,3,4,5].map(i=>`<button type="button" class="star ${i<=(it.stars||0)?"on":""}" data-rate="${i}" data-run="${esc(run.run_id)}" data-item="${esc(it.id)}" aria-label="${i} 分" aria-pressed="${i===it.stars}"${off}>${icon("star")}</button>`).join("")}</span>`;
}
/* 作品表(与卡片共用筛选和排序; 信息与卡片一致, 多一个可选的缩略图列) */
function genMiniHTML(run,it){
  const shot=genPickShot(it),src=shot&&it.file&&!it.error?workUrl(shot.path):"";
  if(!src)return `<span class="work-mini is-ph" aria-hidden="true">${icon("image","icon-sm")}</span>`;
  return `<button type="button" class="work-mini" data-gen="preview" data-run="${esc(run.run_id)}" data-item="${esc(it.id)}" aria-label="预览：${esc(it.name)}"><img src="${esc(src)}" alt="" width="64" height="40" loading="lazy" decoding="async" data-shot="${esc(shot.path)}"></button>`;
}
function genTableActions(run,it){
  const can=!!it.file&&!it.error,hasTrace=!!it.trace||!!it.rounds,ref=`data-run="${esc(run.run_id)}" data-item="${esc(it.id)}"`,nm=esc(it.name);
  return `<span class="dt-actions">${can?`<button type="button" class="btn btn-secondary btn-sm" data-gen="preview" ${ref} aria-label="预览：${nm}">${icon("play")}预览</button>`:""}${workOpenLink(it,{label:true})}`+
    `${it.eval?`<button type="button" class="btn btn-ghost btn-sm" data-gen="detail" ${ref} aria-label="详情：${nm}">${icon("image")}详情</button>`:""}`+
    `${hasTrace?`<button type="button" class="btn btn-ghost btn-sm" data-gen="trace" ${ref} aria-label="生成过程：${nm}">${icon("layers")}过程</button>`:""}</span>`;
}
function genWorksTable(a,b,shown,ctx){
  ctx=ctx||GW.ctx||{v2:true,mode:"browser",shared:""};
  const vStatus=(it)=>{const v=genVerdict(it),m=VERDICT_META[v.key]||{tone:"neutral",name:""};return{tone:m.tone==="neutral"?"neutral":m.tone,text:m.name,tip:v.text}};
  const WIN_RANK={a:2,tie:1,none:0,b:-1};
  return{id:"gen-works-t",title:"作品表",pageSize:100,rowKey:x=>x.it.id,
    columns:[{key:"thumb",label:"截图",type:"html",noSort:true,hidden:true,get:x=>genMiniHTML(a,x.it),text:(v,x)=>genPickShot(x.it)?"有":"没有",tip:"列表里用的缩略图（在「列」里勾选显示）"},
      {key:"name",label:"作品",type:"text",sticky:true,get:x=>x.it.name},{key:"tier",label:"难度",type:"text",get:x=>tierOf(x.it)},
      {key:"status",label:b?"A 主要问题":"主要问题",type:"status",get:x=>vStatus(x.it)},
      {key:"note",label:b?"A 自己的问题":"这件作品自己的问题",type:"text",wrap:true,get:x=>genCardInfo(x.it,x.v,ctx).note||"—",tip:"整次测试共同的情况（比如没在浏览器里运行）在页面顶部说明，这里只写这件作品自己的问题"},
      {key:"pass",label:b?"A 检查通过":"检查通过",type:"html",get:x=>x.it.error||!x.it.total?"—":`<span class="dt-barcell"><span class="dt-meter"><i style="width:${x.it.total?100*x.it.pass/x.it.total:0}%;background:${x.it.pass===x.it.total?C.goodMark:C.a}"></i></span><span class="dt-num">${x.it.pass}/${x.it.total}</span></span>`,
        sortValue:x=>x.it.error||!x.it.total?null:x.it.pass/x.it.total,text:(v,x)=>x.it.total?`${x.it.pass}/${x.it.total}`:""},
      ...(b?[{key:"statusB",label:"B 主要问题",type:"status",get:x=>{const y=x.ib;return y?vStatus(y):{tone:"neutral",text:"没有这题"}}},
        {key:"passB",label:"B 检查通过",type:"text",align:"right",get:x=>{const y=x.ib;return y&&y.total?`${y.pass}/${y.total}`:"—"},sortValue:x=>{const y=x.ib;return y&&y.total?y.pass/y.total:null}},
        {key:"dpass",label:"A 比 B 多过",unit:"项",type:"int",get:x=>{const y=x.ib;return y&&!y.error&&!x.it.error&&y.total&&x.it.total?x.it.pass-y.pass:null}},
        {key:"win",label:"这道题谁更好",type:"text",get:x=>x.ib?genWinLabel(x.win):"B 没有这道题",sortValue:x=>x.win?WIN_RANK[x.win.side]:null,tip:GEN_WIN_RULE}]:[]),
      {key:"lines",label:"行数",type:"int",get:x=>x.it.lines||null},{key:"rounds",label:"接着写",unit:"轮",type:"int",get:x=>x.it.continuations||0},
      {key:"tok",label:"输出",unit:"token",type:"int",get:x=>x.it.out_tokens||null},
      {key:"judge",label:"AI 分",type:"num",digits:0,get:x=>typeof x.it.judge_score==="number"?x.it.judge_score:null},
      {key:"stars",label:"人工星级",type:"html",get:x=>x.it.error?"—":starsHTML(a,x.it),sortValue:x=>x.it.stars||0,text:(v,x)=>x.it.stars?String(x.it.stars):""},
      {key:"act",label:"",type:"html",noSort:true,get:x=>genTableActions(a,x.it),text:()=>""}],
    rows:shown,note:b?"B 列按同一道题对齐":""};
}
/* 检查矩阵: 作品 × 通用检查项(✓ / ✗ / —), 题目专属的交互与功能检查合成一列 */
const MATRIX_CHECKS=[["load","能打开"],["nonblank","不白屏"],["no_error","没报错"],["animated","有动画"],["responsive","手机适配"],["self_contained","不依赖外网"],["complete","代码完整"]];
function genCheckMatrix(a,shown){
  const st=(it,id)=>{const c=it.eval&&(it.eval.checks||[]).find(x=>x.id===id);return !c?{tone:"neutral",text:"—"}:c.pass?{tone:"good",text:"过",tip:plainCheck(c)}:{tone:"bad",text:"没过",tip:failText(c)}};
  const own=it=>{const cs=(it.eval&&it.eval.checks||[]).filter(c=>/^(step|f\d)/.test(c.id));return cs.length?{p:cs.filter(c=>c.pass).length,n:cs.length}:null};
  return{id:"gen-matrix-t",title:"检查矩阵（作品 × 检查项）",pageSize:100,rowKey:x=>x.it.id,
    columns:[{key:"name",label:"作品",type:"text",sticky:true,get:x=>x.it.name},
      ...MATRIX_CHECKS.map(([id,label])=>({key:"c_"+id,label,type:"status",align:"center",get:x=>x.it.error?{tone:"neutral",text:"—"}:st(x.it,id),tip:CHECK_PLAIN[id]})),
      {key:"own",label:"题目专属检查",type:"html",align:"right",get:x=>{const o=own(x.it);return o?`<span class="${o.p===o.n?"good":o.p?"":"bad"}">${o.p}/${o.n}</span>`:"—"},
        sortValue:x=>{const o=own(x.it);return o?o.p/o.n:null},text:(v,x)=>{const o=own(x.it);return o?`${o.p}/${o.n}`:""},tip:"按题目模拟的操作和功能检查"}],
    rows:shown,note:"✓ 过 / ✗ 没过 / — 这件作品没做这项检查"};
}
/* 各难度逐题得分(表格视图) */
function genTaskTable(a,b){
  const runs=[{tag:"A",r:a},b?{tag:"B",r:b}:null].filter(Boolean);
  const ids=[...new Set(runs.flatMap(x=>(x.r.items||[]).map(it=>it.id)))];
  const find=(r,id)=>(r.items||[]).find(z=>z.id===id);
  return{id:"gen-task-t",title:"逐题得分",columns:[{key:"name",label:"题目",type:"text",sticky:true},{key:"tier",label:"难度",type:"text"},
      ...runs.map((x,i)=>({key:"s_"+i,label:runs.length>1?x.tag:"得分",group:runs.length>1?"得分（%）":"",unit:runs.length>1?"":"%",type:"bar",color:i?C.b:C.a,max:100}))],
    rows:ids.map(id=>{const cat=TASK_CATALOG.find(z=>z.id===id),first=runs.map(x=>find(x.r,id)).find(Boolean);
      const row={name:cat?cat.name:(first&&first.name)||id,tier:first?tierOf(first):""};
      runs.forEach((x,i)=>{const it=find(x.r,id);row["s_"+i]=it&&!it.error?it.exec_score:null});return row})};
}
function tierInfo(r,t){
  const its=(r.items||[]).filter(it=>(it.tags||[]).includes(t));
  return{its,avg:avgOf(its.filter(x=>!x.error).map(x=>x.exec_score)),pass:its.filter(x=>genVerdict(x).key==="pass").length,fail:its.filter(x=>x.error).length};
}
function tierCards(a,b,mode){
  const tiers=TIER_ORDER.filter(t=>[a,b].some(r=>r&&(r.items||[]).some(it=>(it.tags||[]).includes(t))));
  const cards=tiers.map((t,i)=>{
    const A=tierInfo(a,t),B=b?tierInfo(b,t):null;
    const notes=[`${A.its.length} 题`,A.pass?`${A.pass} 题全部通过`:"",A.fail?`${A.fail} 题没生成出来`:""].filter(Boolean).join(" · ");
    return `<div class="ccard" style="order:${i}"><div class="tier-head"><div><h3 class="ccard-title">${esc(tagName(t))}</h3><p class="ccard-desc">${esc(notes)}</p></div>
      <div class="tier-score"><div class="tier-num">${A.avg==null?"—":fmt(A.avg,1)}<small>%</small></div>
        <div class="tier-sub">${B?`B ${B.avg==null?"—":fmt(B.avg,1)+"%"}`:(mode==="static"?"平均命中率":"平均通过率")}</div></div></div>
      <div class="chart" id="genTier${i}"></div></div>`;
  });
  /* 两列各自往下排(左: 第 1、3 张; 右: 第 2、4 张), 卡片高度不被同一行拉齐, 不留空白; 窄屏按原顺序排成一列 */
  return `<div class="tier-cols"><div class="tier-col">${cards.filter((c,i)=>i%2===0).join("")}</div><div class="tier-col">${cards.filter((c,i)=>i%2===1).join("")}</div></div>`;
}
function drawGenCharts(a,b,verdicts,ck){
  const total=Math.max(1,verdicts.length);
  /* 作品情况: 按主要问题 */
  const vk=VERDICTS.filter(([k])=>verdicts.some(x=>x.v.key===k));
  const vRows=vk.map(([k,n,tone])=>{const c=verdicts.filter(x=>x.v.key===k).length;
    return{k,name:n,values:[c],colors:[tone2color(tone)],right:`${c} 件 · ${Math.round(100*c/total)}%`}});
  meterChart("genWhy",{rows:vRows,max:total,nameWidth:140,tip:r=>{const names=verdicts.filter(x=>x.v.key===r.k).map(x=>x.it.name);
    return tt(r.name,[[r.colors[0],VERDICT_META[r.k].why,r.right]],names.slice(0,10).join("、")+(names.length>10?" …":"")+" · 点击筛选")}});
  const why=CHARTS.get("genWhy");
  if(why){why.off("click");why.on("click",q=>{const r=vRows[q.dataIndex];if(!r)return;GEN_TIER="all";GEN_Q="";const sb=$("genSearch");if(sb)sb.value="";genSetFilter(r.k,{scroll:true})})}
  /* 框架处理 */
  const kc={raw:C.goodMark,trimmed:C.series[0],stitched:C.series[4],rescued:C.warnMark,legacy:C.axis};
  const cRows=CHANGE_KINDS.filter(([k])=>ck[k]).map(([k,n])=>({name:n,values:[ck[k]],colors:[kc[k]],right:`${ck[k]} 件 · ${Math.round(100*ck[k]/total)}%`}));
  meterChart("genChange",{rows:cRows,max:total,nameWidth:250});
  /* 各难度: 每张小卡一张进度条清单, 按分数从高到低 */
  const runs=[{tag:"A",color:C.a,r:a},b?{tag:"B",color:C.b,r:b}:null].filter(Boolean);
  const tiers=TIER_ORDER.filter(t=>runs.some(x=>(x.r.items||[]).some(it=>(it.tags||[]).includes(t))));
  const scoreOf=(r,id)=>{const it=(r.items||[]).find(z=>z.id===id);return !it?undefined:(it.error?null:it.exec_score)};
  const pct=v=>v===undefined?"—":v==null?"没生成出来":Math.round(v)+"%";
  tiers.forEach((t,i)=>{
    const ids=[...new Set(runs.flatMap(x=>(x.r.items||[]).filter(it=>(it.tags||[]).includes(t)).map(it=>it.id)))];
    ids.sort((p,q)=>(scoreOf(a,q)??-1)-(scoreOf(a,p)??-1));
    const rows=ids.map(id=>{const cat=TASK_CATALOG.find(z=>z.id===id);
      const vals=runs.map(x=>scoreOf(x.r,id));
      return{id,name:cat?cat.name:id,values:vals.map(v=>v==null?null:v),right:runs.length>1?vals.map(pct).join(" / "):pct(vals[0])}});
    meterChart("genTier"+i,{rows,max:100,series:runs.map(x=>({name:x.tag,color:x.color})),nameWidth:130,
      tip:r=>{const lines=runs.map(x=>{const it=(x.r.items||[]).find(z=>z.id===r.id);
        return [x.color,x.tag,it?(it.error?"没生成出来":`${fmt(it.exec_score,0)}%（${it.pass}/${it.total} 项）`):"没有这道题"]});
        const it=(a.items||[]).find(z=>z.id===r.id);return tt(r.name,lines,it?(VERDICT_META[genVerdict(it).key]||{}).name:"")}});
  });
}
$("genResult").addEventListener("change",e=>{
  if(e.target.id==="genSort"){GEN_SORT=e.target.value;GEN_PAGE=0;genSavePos();genRenderWorks()}
  else if(e.target.matches("[data-gw-size]")){
    const first=GEN_PAGE*GEN_SIZE;GEN_SIZE=+e.target.value;GEN_PAGE=Math.floor(first/GEN_SIZE);genSavePos();
    genRenderWorks();const z=$("gwPager").querySelector("[data-gw-size]");if(z)z.focus()}
  else if(e.target.matches(".is-compact [data-gw-jump]")){const t=pagerTarget(e.target);if(t!=null&&t!==GEN_PAGE)genSetPage(t);else e.target.value=GEN_PAGE+1}
});
let genQT=null;
$("genResult").addEventListener("input",e=>{
  if(e.target.id!=="genSearch")return;
  clearTimeout(genQT);
  genQT=setTimeout(()=>{GEN_Q=e.target.value.trim().slice(0,80);GEN_PAGE=0;genSavePos();genRenderWorks()},200);
});
$("genResult").addEventListener("keydown",e=>{
  if(e.key==="Enter"&&e.target.matches("[data-gw-jump]")){e.preventDefault();const t=pagerTarget(e.target);if(t!=null)genSetPage(t)}
});
/* 缩略图: 加载完去掉骨架; 打不开换成占位并写明原因 */
$("genResult").addEventListener("load",e=>{
  const img=e.target;if(!img||!img.matches||!img.matches("img.work-shot"))return;
  const t=img.closest(".work-thumb");if(t)t.classList.remove("skeleton");
},true);
$("genResult").addEventListener("error",e=>{
  const img=e.target;if(!img||!img.matches||!img.matches("img.work-shot"))return;
  genThumbFail(img);
},true);
/* 键盘 ← → 翻作品卡片: 卡片在屏幕上、焦点不在输入框里、没有打开面板或弹窗时才生效 */
document.addEventListener("keydown",e=>{
  if(VIEW!=="gen"||(e.key!=="ArrowLeft"&&e.key!=="ArrowRight")||e.altKey||e.ctrlKey||e.metaKey||e.shiftKey||e.defaultPrevented)return;
  if(e.target.closest&&e.target.closest("input,select,textarea,[contenteditable=true],details[open]"))return;
  if(!$("modal").hidden||document.querySelector(".drawer:not([hidden])"))return;
  const sec=$("gen-works"),list=$("gwList");
  if(!sec||!list||sec.dataset.pv==="table"||!list.offsetParent)return;
  const r=list.getBoundingClientRect();if(r.bottom<80||r.top>innerHeight-80)return;
  const b=$("gwPagerTop")&&$("gwPagerTop").querySelector(`[data-dir=${e.key==="ArrowLeft"?"prev":"next"}]`);
  if(!b||b.disabled)return;
  e.preventDefault();genSetPage(+b.dataset.gwPage);
});
$("genResult").addEventListener("click",e=>{
  const sc=e.target.closest("[data-strip-close]");
  if(sc){STRIP_CLOSED.add(sc.dataset.stripClose);const st=sc.closest(".strip");if(st)st.remove();return}
  const f=e.target.closest("[data-gen-filter]");
  if(f){genSetFilter(f.dataset.genFilter);return}
  const tr=e.target.closest("[data-gen-tier]");
  if(tr){genSetTier(tr.dataset.genTier);return}
  const pg=e.target.closest("[data-gw-page]");
  if(pg){genSetPage(+pg.dataset.gwPage);return}
  const jb=e.target.closest("[data-gw-jumpbtn]");
  if(jb){const t=pagerTarget(jb.parentElement.querySelector("[data-gw-jump]"));if(t!=null)genSetPage(t);return}
  if(e.target.closest("[data-gw-clear]")){genClearFilters();return}
  const rate=!OFF&&e.target.closest("[data-rate]");  /* 离线报告里星级只读 */
  if(rate){rateStars(rate.dataset.run,rate.dataset.item,+rate.dataset.rate);return}
  const act=e.target.closest("[data-gen]");if(!act)return;
  const r=GEN_RUNS[act.dataset.run],it=r&&(r.items||[]).find(x=>x.id===act.dataset.item);if(!it)return;
  if(act.dataset.gen==="preview")previewWork(it);
  else if(act.dataset.gen==="detail")genDetail(r,it,"checks");
  else if(act.dataset.gen==="trace")genDetail(r,it,"trace");
  else if(act.dataset.gen==="compare")previewCompare(it);
});
let rateSeq=0;
function rateStars(runId,itemId,n){
  const r=GEN_RUNS[runId],it=r&&(r.items||[]).find(x=>x.id===itemId);
  if(!it||!n)return;
  const seq=++rateSeq,prev=it.stars;
  it._rateSeq=seq;
  it.stars=it.stars===n?null:n;
  document.querySelectorAll(`[data-rate][data-run="${CSS.escape(runId)}"][data-item="${CSS.escape(itemId)}"]`).forEach(s=>{
    const i=+s.dataset.rate;s.classList.toggle("on",i<=(it.stars||0));s.setAttribute("aria-pressed",String(i===it.stars))});
  postJSON("/api/gen-rate",{run_id:runId,item_id:itemId,stars:it.stars}).then(d=>{
    if(it._rateSeq!==seq)return;  /* 之后又点过, 以最后一次为准 */
    if(!d.ok){it.stars=prev;renderGen();toast("评分保存失败："+d.error,"error")}
  });
  if(GW.b&&$("gwList"))genRenderWorks({focus:`[data-rate="${n}"][data-run="${CSS.escape(runId)}"][data-item="${CSS.escape(itemId)}"]`});
}
const GEN_SANDBOX="allow-scripts allow-pointer-lock allow-forms allow-modals"; /* 无 same-origin/top-navigation/popups: 作品代码碰不到本页和接口; localStorage 由服务端 /works 垫片提供(否则游戏脚本一启动就崩) */
const SANDBOX_BADGE=`<span class="badge" title="作品在隔离的沙箱里运行，碰不到本页面和后端接口；本地存储用内存代替（刷新就清空）">${icon("ban")}隔离运行</span>`;
function focusPreviewFrame(){
  const f=document.querySelector("#modalBody iframe.frame");
  if(f){try{f.focus();f.contentWindow&&f.contentWindow.focus()}catch(e){}}
}
function previewWork(it){
  Modal.open(it.name,`<iframe class="frame" sandbox="${GEN_SANDBOX}" ${workFrameSrc(it.file)} title="${esc(it.name)}"></iframe>`,{badges:SANDBOX_BADGE+workOpenLink(it,{text:true}),flush:true});
  focusPreviewFrame();  /* 键盘类游戏不用先点一下 */
}
function previewCompare(it){
  const a=GEN_RUNS[$("genMainSel").value],b=GEN_RUNS[$("genCmpSel").value];
  const ib=b&&(b.items||[]).find(x=>x.id===it.id);
  const side=(r,x,tag)=>`<div><div class="split-head"><span class="run-tag ${tag.toLowerCase()}">${tag}</span>${esc(genLabel(r))}${workOpenLink(x)}</div>
    ${x&&!x.error?`<iframe class="frame" style="flex:1" sandbox="${GEN_SANDBOX}" ${workFrameSrc(x.file)} title="${tag}"></iframe>`
      :emptyState(x?"这题没生成出来":"这个任务没有这道题",x?x.error:"",{inline:true})}</div>`;
  Modal.open(it.name+" · 并排对比",`<div class="split">${side(a,it,"A")}${side(b,ib,"B")}</div>`,{badges:SANDBOX_BADGE,flush:true});
  focusPreviewFrame();
}
/* 检查详情 / AI 打分 / 生成过程 三个标签 */
function genDetail(r,it,tab){
  const e=it.eval;
  const tabs=[e&&["checks","运行检查"],e&&["judge","AI 看图打分"],(it.trace||it.rounds)&&["trace","生成过程"]].filter(Boolean);
  if(!tabs.length)return;
  if(!tabs.some(t=>t[0]===tab))tab=tabs[0][0];
  const v=genVerdict(it);
  Modal.open(it.name,`<div class="tabs" role="tablist">${tabs.map(([k,n])=>`<button class="tab" role="tab" data-tab="${k}" aria-selected="${k===tab}">${n}</button>`).join("")}</div>
    ${tabs.map(([k])=>`<div data-panel="${k}" ${k===tab?"":"hidden"}>${k==="checks"?checksPanel(it):k==="judge"?judgePanel(it):`<div class="faint">加载中…</div>`}</div>`).join("")}`,
    {badges:`<span class="badge is-${(VERDICT_META[v.key]||{}).tone==="good"?"good":(VERDICT_META[v.key]||{}).tone==="bad"?"bad":"warn"}">${esc((VERDICT_META[v.key]||{}).name||"")}</span>`+(e?`<span class="badge">${e.method==="static"?"代码关键词":"运行检查"} ${it.pass}/${it.total}</span>`:"")});
  let traceLoaded=false;
  const show=k=>{
    document.querySelectorAll("#modalBody [data-tab]").forEach(b=>b.setAttribute("aria-selected",String(b.dataset.tab===k)));
    document.querySelectorAll("#modalBody [data-panel]").forEach(p=>p.hidden=p.dataset.panel!==k);
    if(k==="trace"&&!traceLoaded){traceLoaded=true;loadTracePanel(it)}
  };
  $("modalBody").onclick=ev=>{const b=ev.target.closest("[data-tab]");if(b)show(b.dataset.tab);
    const rb=ev.target.closest("[data-round]");if(rb)showRound(+rb.dataset.round)};
  if(tab==="trace")show("trace");
}
function checksPanel(it){
  const e=it.eval;
  const dir=it.file.replace(/[^/]+$/,"")+e.shots_dir+"/";
  const rows=(e.checks||[]).map(c=>`<tr><td style="width:72px"><span class="badge ${c.pass?"is-good":"is-bad"}">${c.pass?"通过":"没通过"}</span></td>
    <td class="text-left"><span title="${esc(c.label)}">${esc(c.pass?plainCheck(c):failText(c))}</span>${c.detail?`<span class="sub">${esc(c.detail)}</span>`:""}</td></tr>`).join("");
  const ctl=e.control;
  const ctlHtml=ctl&&ctl.errors?alertBox(ctl.reproduced?"info":"warn",`<b>${term("control")}</b>：${ctl.reproduced?"在不加任何检测代码的干净页面里按同样步骤运行，同样报错，说明是作品本身的问题：":"在干净页面里运行没有报错，这些错误可能是检测环境引起的，请人工确认。"}${ctl.reproduced?`<ul class="hint-list">${ctl.errors.map(x=>`<li class="mono small">${esc(x)}</li>`).join("")}</ul>`:""}`):"";
  return `<div class="detail-layout">
    <div><div class="shot-grid">${(e.shots||[]).map(s=>`<figure class="shot"><img src="${esc(workUrl(dir+s.file))}" alt="${esc(s.caption)}" loading="lazy"><figcaption>${esc(s.caption)}</figcaption></figure>`).join("")||emptyState("没有截图","只看代码的检查不会截图",{inline:true})}</div></div>
    <div><section class="detail-section"><h4>检查项 ${it.pass} / ${it.total}<span class="faint" style="font-weight:400"> · ${e.method==="browser"?"在后台浏览器里实际运行":"只看了代码"}</span></h4>
      ${ctlHtml}<div class="table-wrap" style="max-height:none"><table class="table"><tbody>${rows}</tbody></table></div>
      ${(e.notes||[]).length?`<p class="faint small" style="margin-top:8px">${e.notes.map(esc).join("<br>")}</p>`:""}</section></div></div>`;
}
function judgePanel(it){
  const j=it.eval&&it.eval.judge;
  if(!j)return `<p class="faint">没有配置 AI 看图打分。在「新建生成任务」里填写打分模型，再点「重新检查」。</p>`;
  if(j.error)return alertBox("warn",esc(j.error));
  return `<div class="row" style="align-items:baseline"><span class="score-big score ${scoreCls(j.score)}">${fmt(j.score,1)}</span><span class="faint">/ 100 · ${esc(j.model||"")}</span></div>
    ${j.stale?alertBox("info",j.kept_because?esc("这次打分没有替换原来的分数："+j.kept_because):"重新检查时没有配置打分模型，这是之前基于旧截图的分数。"):""}
    ${j.summary?`<p class="muted" style="margin:8px 0 12px">${esc(j.summary)}</p>`:""}
    <div class="table-wrap" style="max-height:none"><table class="table"><tbody>${(j.items||[]).map(x=>`<tr>
      <td style="width:70px">${x.score==null?`<span class="badge">没打分</span>`:`<span class="score ${scoreCls(x.score*10)}">${x.score} / 10</span>`}</td>
      <td class="text-left">${esc(x.label)}<span class="sub">${esc(x.reason)}</span></td></tr>`).join("")}</tbody></table></div>`;
}
const FINISH_TEXT={stop:"正常写完",length:"写到长度上限",repetition:"陷入重复，已停止","":"—"};
const MODE_TEXT={first:"第一次生成",prefix:"接着写（从中断处继续）",instruct:"接着写（按提示继续）",restart:"不思考，重新生成"};
let TRACE=null;
async function loadTracePanel(it){
  const panel=document.querySelector('#modalBody [data-panel="trace"]');if(!panel)return;
  TRACE=null;
  if(!it.trace){
    panel.innerHTML=alertBox("info","这件作品生成于 2.3 之前，没有保存模型的原始输出，只能看到下面的简要记录。")+roundsTable(it.rounds||[]);
    return;
  }
  try{TRACE=await getJSON("/"+it.trace)}catch(e){panel.innerHTML=alertBox("bad","原始输出加载失败："+esc(e.message));return}
  const t=TRACE,rounds=t.rounds||[];
  const deg=t.degenerate,degR=t.degenerate_reasoning;
  panel.innerHTML=`<div class="stack">
    ${deg?alertBox("bad",`<b>模型${term("repeat")}</b>：第 ${deg.round} 轮写到后面开始${repText(deg)}。框架检测到后立即停止、没有再接着写。这是模型自身的问题（常见于温度太低或模型较小）。<br>重复的片段：<span class="mono small">${esc(String(deg.sample||"").slice(0,120))}</span>`):""}
    ${degR?alertBox("warn",`<b>思考过程陷入重复</b>：第 ${degR.round} 轮的思考${repText(degR)}，已停止思考。`):""}
    ${t.rescued?alertBox("warn",esc(t.rescued)):""}
    ${t.unfinished?alertBox("warn","接着写了多轮仍然没有写完，保存的是最后拼接出的内容。"):""}
    <div class="summary"><div class="summary-head">${icon("wrench")}<span class="summary-title">框架对模型输出做了什么</span></div>
      <ul class="change-list">${(t.changes||[]).map(c=>`<li>${icon("check")}<span>${esc(c)}</span></li>`).join("")}</ul>
      <div class="summary-foot">除上面列出的处理外，保存的作品与模型输出逐字一致。模型共输出 ${fmtInt(t.raw_chars)} 个字符，保存的网页 ${fmtInt(t.html_chars)} 个字符 · ${esc(t.thinking?"思考模式":"不思考")} · ${esc(samplingText(t.thinking?(t.sampling||{}).think:(t.sampling||{}).plain)||"采样未记录")}</div></div>
    ${ccard("traceChart","每一轮写了多少",{desc:"思考过程和正文分开统计（单位：字符）",h:Math.max(180,rounds.length*46+60)})}
    ${roundsTable(rounds)}
    <div><div class="row" style="margin-bottom:8px"><span class="eyebrow">模型原始输出</span>
      ${rounds.map((r,i)=>r.content!=null?`<button class="btn btn-ghost btn-sm" data-round="${i}">第 ${r.n} 轮</button>`:"").join("")}
      <a class="btn btn-ghost btn-sm" href="${esc(workUrl(it.trace))}" download="${esc(it.trace.split("/").pop())}" style="margin-left:auto">${icon("download")}下载完整记录（JSON）</a></div>
      <div id="rawBox"></div></div></div>`;
  const cats=rounds.map(r=>`第 ${r.n} 轮`);
  setChart("traceChart",baseOption({color:[C.series[2],C.a],legend:legendOf(["思考过程","正文"],"rect"),
    grid:{left:4,right:60,top:36,bottom:4,containLabel:true},xAxis:axisValue({}),yAxis:axisCat(cats,{inverse:true}),
    tooltip:Object.assign(baseOption().tooltip,{axisPointer:{type:"shadow",shadowStyle:{color:"rgba(128,128,128,.08)"}},formatter:ps=>{const r=rounds[ps[0].dataIndex];
      return tt(`第 ${r.n} 轮 · ${MODE_TEXT[r.mode]||r.mode}`,ps.map(p=>[p.color,p.seriesName,fmtInt(p.value)+" 字符"]),`结束：${FINISH_TEXT[r.finish]||r.finish||"—"} · 输出 ${fmtInt(r.completion_tokens)} token${r.tokens_estimated?"（估算）":""}`)}}),
    series:[sBar("思考过程",C.series[2],rounds.map(r=>r.reasoning_chars||0),{horizontal:true,stack:"x",flat:true}),
      sBar("正文",C.a,rounds.map(r=>r.content_chars||0),{horizontal:true,stack:"x"})]}));
  const firstWithContent=rounds.findIndex(r=>r.content!=null);
  if(firstWithContent>=0)showRound(firstWithContent);
}
function roundsTable(rounds){
  if(!rounds.length)return "";
  return table(["轮次","方式","思考","结束原因","输出 token","正文字符","思考字符","用时"],rounds.map(r=>[
    `第 ${r.n} 轮`,esc(MODE_TEXT[r.mode]||r.mode||"—"),r.thinking?"是":"否",
    r.error?`<span class="bad">出错：${esc(r.error)}</span>`:`<span class="${r.finish==="repetition"?"bad":r.finish==="length"?"warn":""}">${esc(FINISH_TEXT[r.finish]||r.finish||"—")}</span>`,
    r.completion_tokens!=null?fmtInt(r.completion_tokens)+(r.tokens_estimated?"（估算）":""):"—",fmtInt(r.content_chars),fmtInt(r.reasoning_chars),r.seconds!=null?fmt(r.seconds,1)+" 秒":"—"]));
}
function showRound(i){
  const box=$("rawBox");if(!box||!TRACE)return;
  const r=(TRACE.rounds||[])[i];if(!r)return;
  document.querySelectorAll("#modalBody [data-round]").forEach(b=>b.classList.toggle("btn-secondary",+b.dataset.round===i));
  const text=r.content||"",HEAD=6000,TAIL=4000;
  const rep=r.repetition&&r.repetition.where==="content"?r.repetition:null;
  let html;
  if(text.length<=HEAD+TAIL)html=markRepeat(text,0,rep);
  else html=markRepeat(text.slice(0,HEAD),0,rep)+`\n\n<span class="faint">……（中间省略 ${fmtInt(text.length-HEAD-TAIL)} 个字符，完整内容请下载 JSON）……</span>\n\n`+markRepeat(text.slice(-TAIL),text.length-TAIL,rep);
  const reason=r.reasoning_head?`<details class="advanced" style="margin-top:8px"><summary>${icon("chevron-down")}这一轮的思考过程（${fmtInt(r.reasoning_chars)} 字符，显示开头${r.reasoning_tail?"和结尾":""}）</summary>
    <div class="raw-box" style="margin-top:8px">${esc(r.reasoning_head)}${r.reasoning_tail?`\n\n<span class="faint">……</span>\n\n${esc(r.reasoning_tail)}`:""}</div></details>`:"";
  box.innerHTML=`<div class="raw-box">${html||'<span class="faint">（这一轮没有正文）</span>'}</div>${reason}`;
}
/* 把重复区(从 rep.start 起)标红, offset 是这段文本在整轮内容中的起点 */
function markRepeat(seg,offset,rep){
  if(!rep||rep.start==null||rep.start>=offset+seg.length)return esc(seg);
  const k=Math.max(0,rep.start-offset);
  return esc(seg.slice(0,k))+`<mark title="从这里开始重复">${esc(seg.slice(k))}</mark>`;
}

/* ============================================================
   任务集: 列表(导入 / 下载模板 / 改名 / 删除) · 详情(概况 / 输入长度分布 / 逐行查看) · 拖文件到页面上导入
   地址 #tasks 是列表, #tasks/<id> 是某一个; 浏览器后退回到列表, 刷新停在原处。
   逐行数据按页从服务端取(筛选、搜索也在服务端做), 图片只在看到时按行号取
   ============================================================ */
const TS_ID_RE=/^scn-[0-9a-f]{12}$/;
const TS_LS="llm-bench-pro-ts";          /* 每页几行、卡片 / 表格、每个任务集看到第几页和筛选条件 */
const TS_SIZES=[6,12,24,48];
const TS_NAME_MAX=80;
const TS_EXTS=[".jsonl",".json",".txt"];
const TS_PREF=lsGet(TS_LS);
const TS={list:null,listErr:"",listLoading:null,cur:"",data:null,dataErr:"",dataStatus:0,dataFor:"",lines:null,linesErr:"",
  seq:0,filter:"all",q:"",page:0,size:TS_SIZES.includes(TS_PREF.size)?TS_PREF.size:6,mem:{},full:new Map(),
  report:null,flash:"",importing:false,fromList:false,focusAfter:"",bins:[]};

/* ---------- 纯逻辑(tests/js/checks.js 有断言) ---------- */
/* 名称: 去掉控制字符、会打乱文字方向的不可见字符和首尾空白; 1–80 个字(按字数, 不按字节)。与服务端 tasksets.clean_name 同一套规则 */
function tsNameCheck(raw){
  const name=String(raw??"").replace(/[\u0000-\u001f\u007f-\u009f‪-‮⁦-⁩﻿]/g,"").trim();
  const n=[...name].length;
  if(!n)return{ok:false,name,n,error:"名称不能为空"};
  if(n>TS_NAME_MAX)return{ok:false,name,n,error:`名称最多 ${TS_NAME_MAX} 个字（现在 ${n} 个）`};
  return{ok:true,name,n,error:""};
}
/* 一行的状态: 文字 + 图标 + 颜色, 不只靠颜色区分 */
const TS_STATUS={ok:{text:"可用",tone:"good",icon:"check",tip:"测试时会发送这一行"},
  skip:{text:"会跳过",tone:"warn",icon:"ban",tip:"没有消息，或者输入太长，测试时跳过这一行"},
  bad:{text:"有问题",tone:"bad",icon:"x",tip:"格式不对，发出去服务端也会拒绝，测试时跳过这一行"}};
function tsStatusOf(st){return TS_STATUS[st]||TS_STATUS.bad}
/* 消息的角色: 大白话(原来的 role 在悬停提示里) */
const TS_ROLE={system:"系统提示",user:"用户",assistant:"模型之前的回答",tool:"工具结果",developer:"开发者提示",function:"函数结果"};
function tsRoleName(role){return TS_ROLE[role]||(role?`不认识的角色「${role}」`:"没写角色")}
/* 筛选标签: 全部 / 可用 / 有问题 / 带图片 / 要求 JSON, 数字是按搜索过滤之后的行数 */
const TS_FILTERS=[["all","全部",""],["ok","可用","测试时会发送的行"],["bad","有问题","格式不对、没有消息或输入太长的行，测试时会跳过"],
  ["image","带图片","消息里带图片的行，要用能看图的模型"],["json","要求 JSON","带 response_format 的行，测试时统计 JSON 是否合法"]];
function tsChipsHTML(counts,cur){
  return TS_FILTERS.map(([f,label,tip])=>`<button type="button" class="filter-chip" data-ts-filter="${f}" aria-pressed="${f===cur}"${tip?` title="${esc(tip)}"`:""}>${esc(label)} <b>${fmtInt((counts||{})[f]||0)}</b></button>`).join("");
}
/* 能导入的文件: .jsonl / .json / .txt(不分大小写); 不能导入时说明原因 */
function tsFileCheck(name){
  const n=String(name||""),m=/\.([^.\\/]+)$/.exec(n),ext=m?"."+m[1].toLowerCase():"";
  if(TS_EXTS.includes(ext))return{ok:true,reason:""};
  const kind=/^\.(png|jpe?g|gif|webp|bmp|svg|heic|avif)$/.test(ext)?"图片":/^\.(xlsx?|csv|tsv)$/.test(ext)?"表格":
    /^\.(docx?|pdf|md|pptx?)$/.test(ext)?"文档":/^\.(zip|rar|7z|gz|tgz|tar)$/.test(ext)?"压缩包":"";
  return{ok:false,reason:`${n||"这个文件"} ${kind?"是"+kind+"，":""}不能导入：任务集要是 .jsonl、.json 或 .txt 文件（每行一个 JSON 请求）`};
}
/* 输入长度分档: 最长比最短大很多(20 倍以上)时按 10–20–50 倍数分档(0、10、20、50、100、200、500、1K…), 否则等宽分成 10 档左右;
   每档含下限、不含上限。返回 [{lo, hi, n, label}], 从第一个有数的档到最后一个有数的档 */
function lenBins(values){
  const xs=(values||[]).filter(v=>typeof v==="number"&&isFinite(v)&&v>=0);
  if(!xs.length)return[];
  let mn=Infinity,mx=-Infinity;
  for(const v of xs){if(v<mn)mn=v;if(v>mx)mx=v}
  let edges;
  if(mx===mn)edges=[mn,mn+1];
  else if(mx>=Math.max(mn,1)*20){
    edges=[0];
    for(let b=10;edges[edges.length-1]<=mx;b*=10)for(const k of [1,2,5])if(k*b>edges[edges.length-1]&&edges[edges.length-1]<=mx)edges.push(k*b);
  }else{
    const raw=(mx-mn)/10,p=10**Math.floor(Math.log10(Math.max(raw,1))),r=raw/p;
    const step=Math.max(1,(r<=1?1:r<=2?2:r<=5?5:10)*p),start=Math.floor(mn/step)*step;
    edges=[start];while(edges[edges.length-1]<=mx)edges.push(edges[edges.length-1]+step);
  }
  const bins=edges.slice(0,-1).map((lo,i)=>({lo,hi:edges[i+1],n:0}));
  for(const v of xs){let i=bins.length-1;while(i>0&&v<bins[i].lo)i--;bins[i].n++}
  let a=0,b=bins.length-1;
  while(a<b&&!bins[a].n)a++;
  while(b>a&&!bins[b].n)b--;
  return bins.slice(a,b+1).map(x=>Object.assign(x,{label:x.hi-x.lo===1?lenShort(x.lo):`${lenShort(x.lo)}–${lenShort(x.hi)}`}));
}
function lenShort(v){return v>=1000&&v%100===0?(v/1000).toFixed(v%1000?1:0)+"K":String(v)}
function lenBinText(b){return b.hi-b.lo===1?fmtInt(b.lo):`${fmtInt(b.lo)}–${fmtInt(b.hi)}`}
/* params 的大白话: [{text, tip, tone}]; mt 是服务端算好的实际发送的 max_tokens */
function tsParamItems(p,mt){
  p=p&&typeof p==="object"&&!Array.isArray(p)?p:{};
  const out=[],has=k=>p[k]!=null&&p[k]!=="";
  const key=p.max_tokens?"max_tokens":p.max_completion_tokens?"max_completion_tokens":has("max_tokens")?"max_tokens":has("max_completion_tokens")?"max_completion_tokens":"";
  const eff=fmtInt(mt||4096),sent=mt!=null;  /* mt 为空: 这一行不会发送, 不说「按多少」 */
  if(!key){if(sent)out.push({text:`没写每次最多生成多少，按 ${eff} token`,tip:"params.max_tokens 没写时按默认 4096"})}
  else{
    const n=Math.trunc(Number(p[key]));
    if(!(n>0))out.push({text:`每次最多生成：写的「${tsShort(p[key])}」不是正整数${sent?`，按 ${eff} token`:""}`,tip:`params.${key}`,tone:"warn"});
    else if(sent&&n>mt)out.push({text:`每次最多生成：写的 ${fmtInt(n)} 超过上限，按 ${eff} token`,tip:`params.${key}，上限 8192`,tone:"warn"});
    else out.push({text:`每次最多生成 ${fmtInt(n)} token`,tip:`params.${key}`});
  }
  if(p.temperature!=null)out.push({text:`随机性 ${tsShort(p.temperature)}`,tip:"params.temperature：0 最稳定，越大越随机"});
  const rf=p.response_format;
  if(rf&&typeof rf==="object"){
    if(rf.type==="json_object")out.push({text:"要求输出 JSON 对象",tip:"params.response_format = json_object，测试时统计 JSON 是否合法"});
    else if(rf.type==="json_schema")out.push({text:`按 JSON Schema「${tsShort((rf.json_schema&&rf.json_schema.name)||"没写名字")}」输出`,tip:"params.response_format = json_schema，测试时统计 JSON 是否合法"});
    else if(rf.type==="text")out.push({text:"输出普通文字",tip:"params.response_format = text"});
  }
  if(p.enable_thinking!=null)out.push({text:p.enable_thinking?"开启思考":"关闭思考",tip:"params.enable_thinking：发送时转成 chat_template_kwargs.enable_thinking"});
  const unused=["model","stream","stream_options","n"].filter(k=>k in p);
  const known=new Set(["max_tokens","max_completion_tokens","temperature","response_format","enable_thinking",...unused]);
  const other=Object.keys(p).filter(k=>!known.has(k));
  if(other.length)out.push({text:"其他参数："+other.map(k=>`${k} = ${tsShort(p[k])}`).join("，"),tip:"原样发给模型服务"});
  if(unused.length)out.push({text:`测试时不用：${unused.join("、")}`,tip:"模型用新建面板里填的，请求一律按流式发送；这几项由测试程序决定",tone:"faint"});
  return out;
}
function tsShort(v){const s=typeof v==="string"?v:JSON.stringify(v);return s.length>60?s.slice(0,60)+"…":s}
/* 多久以前: 刚刚 / 5 分钟前 / 3 小时前 / 2 天前, 一个月以上写日期(放在窄的数字格里也不会挤出去) */
function tsAgo(iso,now){
  const d=toDate(iso);if(!d)return "—";
  const s=Math.max(0,((now||Date.now())-d.getTime())/1000);
  if(s<60)return "刚刚";if(s<3600)return Math.floor(s/60)+" 分钟前";if(s<86400)return Math.floor(s/3600)+" 小时前";
  if(s<30*86400)return Math.floor(s/86400)+" 天前";
  return `${d.getFullYear()}-${pad2(d.getMonth()+1)}-${pad2(d.getDate())}`;
}
/* 搜到的文字标出来: 先转义再标, 不分大小写 */
function tsHighlight(text,q){
  const s=String(text??"");q=String(q||"").trim();
  if(!q)return esc(s);
  const re=new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g,"\\$&"),"gi");
  let out="",last=0,m;
  while((m=re.exec(s))){out+=esc(s.slice(last,m.index))+`<mark class="ts-hl">${esc(m[0])}</mark>`;last=m.index+m[0].length;if(!m[0].length)re.lastIndex++}
  return out+esc(s.slice(last));
}
/* 每行最多生成的概况: 「所有行都是 512 token」/「多数是 512 token（8 行）」, 没写的按 4096 单独说 */
function tsMtSummary(dist,unset){
  const d=(dist||[]).filter(x=>Array.isArray(x)&&x[1]>0);
  if(!d.length)return{value:null,text:"没有可用的行"};
  const total=d.reduce((t,x)=>t+x[1],0),[v,n]=d[0];
  const tail=unset?`；其中 ${fmtInt(unset)} 行没写，按 4096`:"";
  if(d.length===1)return{value:v,text:`每行都是 ${fmtInt(v)} token${tail}`};
  return{value:v,text:`多数是 ${fmtInt(v)} token（${fmtInt(n)} / ${fmtInt(total)} 行），另外还有 ${d.slice(1,4).map(x=>`${fmtInt(x[0])}（${fmtInt(x[1])} 行）`).join("、")}${d.length>4?" 等":""}${tail}`};
}

/* ---------- 接口 ---------- */
/* 出错时带上服务端说的原因(getJSON 只给 HTTP 状态码) */
async function tsApi(url){
  if(OFF)throw new Error("离线报告里没有任务集");
  let r;
  try{r=await fetch(url,{cache:"no-store"})}catch(e){const err=new Error("连不上后端服务（"+e.message+"）");err.status=0;throw err}
  let d=null;try{d=await r.json()}catch(e){}
  if(!r.ok||!d||d.ok===false){const err=new Error((d&&d.error)||("HTTP "+r.status));err.status=r.status;throw err}
  return d;
}
function tsFind(id){return (TS.list||[]).find(x=>x.id===id)||(TS.data&&TS.data.set&&TS.data.set.id===id?TS.data.set:null)}
function tsLoadList(){
  const p=TS.listLoading=tsApi("/api/task-sets")
    .then(d=>{if(TS.listLoading===p){TS.list=d.sets||[];TS.listErr=""}})
    .catch(e=>{if(TS.listLoading===p){TS.listErr=e.message;if(TS.list)toast("刷新任务集失败："+e.message,"error")}})
    .finally(()=>{if(TS.listLoading===p){TS.listLoading=null;if(VIEW==="tasks"&&!TS.cur)tsRenderList()}});
  return p;
}
/* 新建面板里导入了任务集: 列表要重新取 */
function tsInvalidate(id){
  if(VIEW==="tasks"){tsLoadList();if(id)TS.flash=id}else TS.list=null;
}

/* ---------- 路由 ---------- */
function tsShow(id){  /* 切到任务集页面(showView 调用) */
  TS.cur=id||"";TS.fromList=false;
  if(!TS.list&&!TS.listLoading)tsLoadList();
  tsRender();
}
function tsRoute(sub){  /* 同一页面里 #tasks ↔ #tasks/<id>(点链接、后退、前进) */
  const id=TS_ID_RE.test(sub)?sub:"",prev=TS.cur;
  if(id===prev)return;
  TS.fromList=!prev&&!!id;  /* 从列表点进来的: 「← 全部任务集」用浏览器后退, 不多出一条历史 */
  TS.focusAfter=id?"detail":prev?"row:"+prev:"";
  TS.cur=id;closeMenus();
  if(!id&&!TS.list&&!TS.listLoading)tsLoadList();
  tsRender();
  window.scrollTo(0,0);
}
function tsOpen(id){location.hash="#tasks/"+id}
function tsBack(){
  if(TS.fromList){TS.fromList=false;history.back();return}
  const prev=TS.cur;
  try{history.replaceState(null,"","#tasks")}catch(e){}
  TS.cur="";TS.focusAfter="row:"+prev;
  if(!TS.list&&!TS.listLoading)tsLoadList();
  tsRender();window.scrollTo(0,0);
}
function tsRender(){if(VIEW==="tasks")TS.cur?tsRenderDetail():tsRenderList()}
function tsRedraw(){if(TS.cur&&TS.data&&TS.dataFor===TS.cur)tsDrawChart()}  /* 换了主题: 图表按新配色重画 */
function tsRefresh(){
  if(TS.cur){TS.dataFor="";TS.full.clear()}  /* 详情: 连概况一起重新取(保留筛选和页码) */
  tsLoadList();tsRender();
}

/* ---------- 公共小块 ---------- */
function tsReportHTML(forId){
  const r=TS.report;
  if(!r||(forId&&r.id&&r.id!==forId))return "";
  return `<div class="ts-report" role="status">${r.html}<button type="button" class="btn btn-ghost btn-icon btn-sm ts-report-x" data-ts-report-close aria-label="关闭检查结果" title="关闭">${icon("x")}</button></div>`;
}
function tsErrorHTML(title,message,what){
  return emptyState(title,message,{iconName:"alert",action:`<button type="button" class="btn btn-secondary" data-ts-retry="${what}">${icon("refresh")}重试</button>`});
}
function tsSkOv(){
  const line=w=>`<div class="skeleton" style="height:12px;width:${w}%;margin-top:14px"></div>`;
  return `<div class="ov"><div><div class="skeleton" style="height:12px;width:18%"></div>${line(86)}${line(72)}${line(80)}</div>
    <div class="ov-stats">${'<div class="stat"><div class="skeleton" style="height:10px;width:50%"></div><div class="skeleton" style="height:26px;width:62%;margin-top:12px"></div></div>'.repeat(4)}</div></div>`;
}
function tsSkCardItems(n){
  return `<div class="qcard ts-sk-card" aria-hidden="true"><div class="skeleton" style="height:14px;width:36%"></div>
    <div class="skeleton" style="height:56px"></div><div class="skeleton" style="height:12px;width:70%"></div><div class="skeleton" style="height:12px;width:45%"></div></div>`.repeat(n);
}
function tsSkCards(n){return `<div class="qb-list">${tsSkCardItems(n)}</div>`}
function tsLink(s){return `<a class="qb-link" href="#tasks/${esc(s.id)}">「${esc(s.name)}」</a>`}
function tsImportBusy(on){
  document.querySelectorAll("[data-ts-import]").forEach(b=>{
    setBusy(b,on);
    const sp=b.querySelector("span");if(sp)sp.textContent=on?"正在检查…":"导入任务集";
    if(b.id==="tsImportBtn")b.setAttribute("aria-label",on?"正在检查…":"导入任务集");
  });
}

/* ---------- 列表 ---------- */
function tsRenderList(){
  const el=$("tasksBody");if(!el)return;
  const rep=tsReportHTML("");
  if(!TS.list){
    el.innerHTML=rep+(TS.listErr?tsErrorHTML("没能加载任务集",TS.listErr,"list"):tsSkOv()+
      `<div class="sec"><div class="skeleton" style="height:14px;width:22%"></div><div class="ts-sk-rows">${'<div class="skeleton" style="height:14px"></div>'.repeat(6)}</div></div>`);
    buildJump("tasksJump",null);return;
  }
  if(!TS.list.length){el.innerHTML=rep+tsEmptyHTML()+tsFormatSec();buildJump("tasksJump",null);tsFocusAfter();return}
  el.innerHTML=rep+tsListOverview()+panel({id:"ts-list",title:"全部任务集",jump:"任务集列表",
    desc:"点一行查看每一行请求；新导入的排在最前面。「用过」只统计 3.6.0 之后的速度测试",tables:[tsListSpec()]})+tsFormatSec();
  buildJump("tasksJump",el);
  tsFlashRow();
  tsFocusAfter();
}
function tsEmptyHTML(){
  return `<div class="empty ts-empty">${icon("file-json")}<div class="empty-title">还没有任务集</div>
    <div class="empty-desc">任务集是你自己的一批请求（JSONL 文件，每行一个），速度测试时轮流发给模型，看你的业务跑得多快。</div>
    <ol class="ts-steps"><li><b>下载模板</b><span>每种写法都有示例</span></li><li><b>照着改</b><span>换成自己的请求</span></li><li><b>导入</b><span>也可以直接拖到这一页上</span></li></ol>
    <div class="ts-empty-acts"><button type="button" class="btn btn-primary" data-ts-import>${icon("upload")}<span>导入任务集</span></button>
      <button type="button" class="btn btn-secondary" data-ts-tpl>${icon("download")}下载模板</button></div></div>`;
}
function tsListOverview(){
  const L=TS.list,valid=L.reduce((t,s)=>t+s.valid,0),total=L.reduce((t,s)=>t+s.total,0);
  const badSets=L.filter(s=>s.total>s.valid),badLines=badSets.reduce((t,s)=>t+s.total-s.valid,0);
  const last=L.reduce((m,s)=>!m||(s.imported_utc||"")>(m.imported_utc||"")?s:m,null);
  const most=L.filter(s=>s.uses).sort((a,b)=>b.uses-a.uses)[0];
  const concl=[{tone:"info",html:`一共 <b>${fmtInt(L.length)}</b> 个任务集，能用的请求一共 <b>${fmtInt(valid)}</b> 条。`},
    badLines?{tone:"warn",html:`有 <b>${fmtInt(badSets.length)}</b> 个任务集带有问题的行（一共 ${fmtInt(badLines)} 行），测试时会跳过这些行：${badSets.slice(0,3).map(tsLink).join("、")}${badSets.length>3?" 等":""}。`}
      :{tone:"good",html:"每个任务集的每一行都能用。"},
    {tone:"info",html:`最近一次导入是 <b>${esc(timeText(last.imported_utc))}</b>：${tsLink(last)}。`},
    most?{tone:"info",html:`用得最多的是 ${tsLink(most)}，在速度测试里用过 <b>${most.uses}</b> 次。`}
      :{tone:"info",html:"还没有在速度测试里用过任务集：新建速度测试时勾选「自定义任务集」，再选一个；或者在这里点「在速度测试里使用」。"}];
  const stats=stat("任务集",fmtInt(L.length),"个",{sub:`文件一共 ${esc(fmtBytes(L.reduce((t,s)=>t+s.size,0)))}`})+
    stat("能用的请求",fmtInt(valid),"条",{sub:`总行数 ${fmtInt(total)}`})+
    stat("有问题的行",fmtInt(badLines),"行",{sub:badLines?`在 ${badSets.length} 个任务集里，测试时跳过`:"没有"})+
    stat("最近导入",esc(tsAgo(last.imported_utc)),"",{sub:`${esc(timeText(last.imported_utc))} · ${esc(last.name)}`});
  return overview(concl,stats,{title:"概况"});
}
function tsListSpec(){
  return{id:"ts-list-t",title:`任务集 <span class="dt-sub">${fmtInt(TS.list.length)} 个</span>`,exportName:"任务集列表",search:TS.list.length>8,pageSize:20,pageSizes:[10,20,50,100],rowKey:s=>s.id,
    rows:TS.list.map(s=>Object.assign({_cls:"is-link"},s)),empty:"没有任务集",
    columns:[
      {key:"name",label:"名称",type:"html",sticky:true,sortValue:s=>s.name,text:(v,s)=>s.name,
        get:s=>`<a class="ts-name-link" href="#tasks/${esc(s.id)}" title="${esc(s.name)}">${esc(s.name)}</a>${s.busy?` <span class="badge is-info" title="有速度测试正在用它">${icon("clock")}测试中</span>`:""}`},
      {key:"valid",label:"可用 / 总行数",type:"html",align:"right",sortValue:s=>s.valid,text:(v,s)=>`${s.valid} / ${s.total}`,tip:"测试时会发送的行 / 文件里的行（空行不算）",
        get:s=>`<span class="ts-count"><b>${fmtInt(s.valid)}</b> / ${fmtInt(s.total)}</span>`},
      {key:"bad",label:"有问题",type:"status",sortValue:s=>s.total-s.valid,tip:"格式不对、没有消息或输入太长的行，测试时跳过",
        get:s=>s.total>s.valid?{tone:"warn",text:`${fmtInt(s.total-s.valid)} 行`,tip:"测试时跳过这些行，点进去筛选「有问题」查看原因"}:{tone:"neutral",text:"—"}},
      {key:"json",label:"要求 JSON",unit:"条",type:"int",tip:"可用的行里带 response_format 的：测试时统计 JSON 是否合法"},
      {key:"image",label:"带图片",unit:"条",type:"int",tip:"可用的行里带图片的：要用能看图的模型"},
      {key:"chars_avg",label:"平均",unit:"字符",group:"输入长度",type:"int",tip:"每行发给模型的文字有多少个字符（中文 1 个字算 1 个），图片不算；只算可用的行"},
      {key:"chars_max",label:"最长",unit:"字符",group:"输入长度",type:"int",tip:"最长的一行有多少个字符"},
      {key:"size",label:"文件大小",type:"text",align:"right",get:s=>fmtBytes(s.size),sortValue:s=>s.size},
      {key:"imported_utc",label:"导入时间",type:"text",get:s=>timeText(s.imported_utc),sortValue:s=>s.imported_utc||""},
      {key:"uses",label:"用过",unit:"次",type:"int",tip:"在速度测试里用过几次（3.6.0 之后的测试才有记录）"},
      {key:"act",label:"操作",type:"html",noSort:true,get:tsActionsHTML,text:()=>""}]};
}
function tsActionsHTML(s){
  const b=(act,ic,label)=>`<button type="button" class="btn btn-ghost btn-icon btn-sm ts-act${act==="delete"?" ts-act-del":""}" data-ts-act="${act}" data-id="${esc(s.id)}" title="${esc(label)}" aria-label="${esc(label)}：${esc(s.name)}">${icon(ic)}</button>`;
  return `<span class="dt-actions">${b("view","eye","查看")}${b("use","play","在速度测试里使用")}${b("download","download","下载原文件")}${b("rename","pencil","改名")}${b("delete","trash","删除")}</span>`;
}
/* 刚导入(或重复导入)的那一行短暂高亮 */
function tsFlashRow(){
  const id=TS.flash;if(!id)return;
  const tr=document.querySelector(`[data-dt="ts-list-t"] tr[data-rk="${CSS.escape(id)}"]`);if(!tr)return;
  TS.flash="";
  tr.classList.add("is-flash");
  if(tr.getBoundingClientRect().bottom>innerHeight-8)tr.scrollIntoView({block:"nearest"});  /* 只滚到刚好看得到, 上面的检查结果尽量留在屏幕上 */
  setTimeout(()=>tr.classList.remove("is-flash"),1600);
}
/* 页面切换后焦点放到合适的地方: 进详情放到名称上, 回列表放回刚才那一行 */
function tsFocusAfter(){
  const f=TS.focusAfter;if(!f)return;
  const a=document.activeElement;
  if(a&&a!==document.body&&!$("tasksBody").contains(a)&&!a.closest(".nav"))return;  /* 焦点在别处(比如搜索框), 不去抢 */
  TS.focusAfter="";
  const el=f==="detail"?$("tsNameH"):f.startsWith("row:")?document.querySelector(`[data-dt="ts-list-t"] tr[data-rk="${CSS.escape(f.slice(4))}"] .ts-name-link`):null;
  if(el)el.focus({preventScroll:true});
}
/* 文件格式说明: 默认收起; 手机上每个字段排成一块 */
function tsFormatSec(){
  const row=(f,need,what,eg)=>`<tr><td>${f}</td><td>${need}</td><td>${what}</td><td>${eg}</td></tr>`;
  return `<section class="sec ts-format" id="ts-format" data-jump="文件格式说明"><details class="fmt-help">
    <summary>${icon("chevron-down")}文件格式说明：每行一个 JSON 请求</summary>
    <div class="fmt-body">
      <p>每行一个 JSON 对象，空行会被忽略，不能写注释。模型名用新建速度测试里填的，请求一律按流式发送，所以不用写 <code>model</code>、<code>stream</code>。
        测试时各行按固定顺序打乱后轮流发送，行数少于「同时请求数 × 每个并发发几次」时会重复使用（结果里标「已循环」，重复的请求可能因为命中缓存而偏快）。
        不知道怎么写时，先点「下载模板」，每种写法都有一两行示例。</p>
      <div class="table-wrap"><table class="table fmt-table">
        <thead><tr><th>字段</th><th>必填</th><th>含义</th><th>示例</th></tr></thead>
        <tbody>
          ${row("<code>messages</code>","是","按顺序发给模型的消息列表，每条有 role 和 content",'<code>[{"role":"user","content":"你好"}]</code>')}
          ${row("<code>role</code>","是","谁说的：system 系统提示、user 用户、assistant 模型之前的回答、tool 工具结果",'<code>"system"</code>')}
          ${row("<code>content</code>","是","一段文字；带图片时写成列表，里面放文字项和图片项",'<code>"用一句话介绍你自己"</code>')}
          ${row("content 里的文字","—","列表里的文字项",'<code>{"type":"text","text":"图里有什么？"}</code>')}
          ${row("content 里的图片","—","url 用 <code>data:image/png;base64,…</code>，或模型服务能访问到的图片网址；每张至少 28×28 像素",'<code>{"type":"image_url","image_url":{"url":"data:image/png;base64,iVBOR…"}}</code>')}
          ${row("<code>params</code>","否","这一行额外带的请求参数，原样发给模型服务（model、stream、stream_options、n 由测试程序决定，写了也不用）",'<code>{"max_tokens":512,"temperature":0.3}</code>')}
          ${row("<code>params.<wbr>max_tokens</code>","否","最多生成多少 token；不写按 4096，超过 8192 按 8192；也可以写 max_completion_tokens","<code>512</code>")}
          ${row("<code>params.<wbr>temperature</code>","否","随机性，0 最稳定，不小于 0","<code>0.3</code>")}
          ${row("<code>params.<wbr>response_format</code>","否","要求输出 JSON，带了它的行会统计 JSON 合法率；json_schema 要写 name 和 schema",'<code>{"type":"json_object"}</code>')}
          ${row("<code>params.<wbr>enable_thinking</code>","否","思考开关（Qwen3 等），会转成 chat_template_kwargs.enable_thinking","<code>false</code>")}
          ${row("<code>meta</code>","否","备注，不会发给模型；meta.prompt_tokens 超过 60000 的行会被跳过",'<code>{"note":"写给自己看的说明"}</code>')}
        </tbody></table></div>
    </div></details></section>`;
}

/* ---------- 详情 ---------- */
function tsViewState(id){return Object.assign({filter:"all",page:0,q:""},(TS_PREF.pos||{})[id]||{},TS.mem[id]||{})}
function tsSaveState(){
  const id=TS.cur;if(!id)return;
  TS.mem[id]={filter:TS.filter,page:TS.page,q:TS.q};
  const pos=Object.assign({},TS_PREF.pos||{});delete pos[id];pos[id]={filter:TS.filter,page:TS.page};
  const keys=Object.keys(pos);while(keys.length>30)delete pos[keys.shift()];  /* 只记最近看过的 30 个 */
  TS_PREF.pos=pos;TS_PREF.size=TS.size;lsSet(TS_LS,TS_PREF);
}
function tsUrl(head){
  return `/api/task-set?id=${encodeURIComponent(TS.cur)}&offset=${TS.page*TS.size}&limit=${TS.size}&status=${TS.filter}&q=${encodeURIComponent(TS.q)}${head?"":"&head=0"}`;
}
/* 取数据: head=true 连概况一起(打开一个任务集时); 翻页、筛选、搜索只取这一页。慢的时候(超过 150 毫秒)才换成骨架, 不闪 */
async function tsFetch(head){
  const id=TS.cur,seq=++TS.seq;
  const slow=!head&&TS.lines?setTimeout(()=>{const list=$("tsList");if(seq===TS.seq&&list){list.innerHTML=tsSkCardItems(Math.min(TS.size,6));list.setAttribute("aria-busy","true")}},150):null;
  try{
    const d=await tsApi(tsUrl(head));
    if(seq!==TS.seq||id!==TS.cur)return;
    const pages=Math.max(1,Math.ceil(d.total/TS.size));
    if(TS.page>pages-1){TS.page=pages-1;tsSaveState();clearTimeout(slow);return tsFetch(head)}  /* 记住的页码超出了(比如换了筛选) */
    if(head){TS.data=d;TS.dataErr=""}
    TS.lines=d;TS.linesErr="";
  }catch(e){
    if(seq!==TS.seq||id!==TS.cur)return;
    if(head){TS.dataErr=e.message;TS.dataStatus=e.status}else TS.linesErr=e.message;
  }finally{clearTimeout(slow)}
  if(head)tsRenderDetail();else tsRenderLines();
}
function tsRenderDetail(){
  const el=$("tasksBody"),id=TS.cur;if(!el)return;
  if(TS.dataFor!==id){  /* 换了一个任务集: 恢复它上次的筛选和页码, 重新取 */
    Object.assign(TS,tsViewState(id),{data:null,dataErr:"",dataStatus:0,dataFor:id,lines:null,linesErr:""});
    tsFetch(true);
  }
  const back=`<button type="button" class="btn btn-ghost btn-sm ts-back" data-ts-back>${icon("arrow-left")}全部任务集</button>`;
  if(TS.dataErr){
    el.innerHTML=tsReportHTML(id)+`<div class="ts-head">${back}</div>`+(TS.dataStatus===404
      ?emptyState("这个任务集不存在","可能已经被删除了。已经跑完的测试结果不受影响",{iconName:"inbox",action:`<button type="button" class="btn btn-secondary" data-ts-back>${icon("arrow-left")}回到全部任务集</button>`})
      :tsErrorHTML("没能加载这个任务集",TS.dataErr,"detail"));
    buildJump("tasksJump",null);return;
  }
  if(!TS.data){
    el.innerHTML=tsReportHTML(id)+`<div class="ts-head">${back}<div class="skeleton" style="height:24px;width:34%;margin-top:6px"></div>
      <div class="skeleton" style="height:12px;width:22%;margin-top:6px"></div></div>`+tsSkOv()+
      `<div class="sec"><div class="skeleton" style="height:14px;width:18%"></div><div style="margin-top:20px">${tsSkCards(3)}</div></div>`;
    buildJump("tasksJump",null);return;
  }
  const s=TS.data.set,uses=TS.data.uses||[];
  TS.bins=lenBins(s.chars);
  el.innerHTML=tsReportHTML(id)+tsDetailHead(s,back)+tsDetailOverview(s,uses)+tsLenPanel(s)+tsLinesSec();
  disposeDetached();
  tsDrawChart();
  tsRenderLines();
  buildJump("tasksJump",el);
  tsFocusAfter();
}
function tsDetailHead(s,back){
  return `<div class="ts-head">${back}
    <div class="ts-head-main">
      <div class="ts-title" id="tsTitle">${tsTitleHTML(s)}</div>
      <div class="ts-actions">
        <button type="button" class="btn btn-primary btn-sm" data-ts-act="use" data-id="${esc(s.id)}" title="打开新建速度测试，自动勾选「自定义任务集」并选中它">${icon("play")}<span>在速度测试里使用</span></button>
        <button type="button" class="btn btn-secondary btn-sm ts-dl" data-ts-act="download" data-id="${esc(s.id)}" title="下载原文件（文件名用任务集名称）" aria-label="下载原文件">${icon("download")}<span>下载</span></button>
        <details class="dropdown more ts-more"><summary class="btn btn-ghost btn-icon btn-sm" aria-label="更多操作" title="更多操作">${icon("more")}</summary>
          <div class="dropdown-panel menu is-right" role="menu">
            <button class="menu-item" type="button" data-ts-act="rename" data-id="${esc(s.id)}">${icon("pencil")}改名</button>
            <button class="menu-item is-danger" type="button" data-ts-act="delete" data-id="${esc(s.id)}">${icon("trash")}删除这个任务集</button>
          </div></details>
      </div>
    </div>
    <div class="ts-meta">${[`导入于 ${esc(timeText(s.imported_utc))}`,`文件 ${esc(fmtBytes(s.size))}`,
      `<span class="mono" title="任务集 id：按文件内容算出来的，内容一样的文件 id 也一样">${esc(s.id)}</span>`,
      s.busy?`<span class="badge is-info">${icon("clock")}有速度测试正在用它</span>`:""].filter(Boolean).join('<span class="ts-dot" aria-hidden="true">·</span>')}</div>
  </div>`;
}
function tsTitleHTML(s){
  return `<h2 class="ts-name" id="tsNameH" tabindex="-1" title="${esc(s.name)}">${esc(s.name)}</h2>
    <button type="button" class="btn btn-ghost btn-icon btn-sm ts-edit" data-ts-edit aria-label="改名：${esc(s.name)}" title="改名（回车保存，Esc 取消）">${icon("pencil")}</button>`;
}
function tsRunText(u){return [u.model||"?",[u.framework,u.fw_version].filter(Boolean).join(" "),u.tag,shortTime(u.started_utc),u.status&&u.status!=="done"?STATUS_NAME[u.status]||u.status:""].filter(Boolean).join(" · ")}
function tsRunLink(u){return `<a href="#dash" class="qb-link" data-ts-run="${esc(u.run_id)}" title="到速度测试页看这次测试">${esc(tsRunText(u))}</a>`}
function tsDetailOverview(s,uses){
  const bad=s.total-s.valid,mt=tsMtSummary(s.mt_dist,s.mt_unset);
  const concl=[
    {tone:"info",html:`共 <b>${fmtInt(s.total)}</b> 行，<b>${fmtInt(s.valid)}</b> 行能用。测试时各行按固定顺序打乱后轮流发送。`},
    bad?{tone:"warn",html:`有 <b>${fmtInt(bad)}</b> 行有问题（${[s.bad?`格式不对 ${fmtInt(s.bad)} 行`:"",s.skipped?`没有消息或输入太长 ${fmtInt(s.skipped)} 行`:""].filter(Boolean).join("，")}），测试时会跳过。
      <a href="javascript:void 0" class="qb-link" data-ts-goto="bad">看有问题的行</a>`}:{tone:"good",html:"每一行都能用。"},
    {tone:"info",html:`要求输出 JSON 的 <b>${fmtInt(s.json)}</b> 行（会统计 JSON 是否合法）；带图片的 <b>${fmtInt(s.image)}</b> 行${s.image?"（要用能看图的模型）":""}。`},
    s.valid?{tone:"info",html:`输入平均 <b>${fmtInt(s.chars_avg)}</b> 字符、最长 <b>${fmtInt(s.chars_max)}</b> 字符；每次最多生成：${esc(mt.text)}。`}:null,
    uses.length?{tone:"info",html:`在速度测试里用过 <b>${uses.length}</b> 次，最近一次：${tsRunLink(uses[0])}。`}
      :{tone:"info",html:"还没有在速度测试里用过。点「在速度测试里使用」就能用它测一次。"}].filter(Boolean);
  const stats=stat("能用的行",`${fmtInt(s.valid)}<small class="ts-of">/ ${fmtInt(s.total)}</small>`,"行",{sub:bad?`<span class="warn">有问题 ${fmtInt(bad)} 行</span>`:"全部能用"})+
    stat("要求 JSON 输出",fmtInt(s.json),"行",{sub:`带图片 ${fmtInt(s.image)} 行`})+
    stat("输入长度 · 平均",s.valid?fmtInt(s.chars_avg):"—","字符",{sub:s.valid?`最短 ${fmtInt(s.chars_min)} · 最长 ${fmtInt(s.chars_max)}`:"",tip:"每行发给模型的文字有多少个字符（中文 1 个字算 1 个），图片不算；只算能用的行"})+
    stat("每次最多生成",mt.value!=null?fmtInt(mt.value):"—","token",{sub:esc(mt.value!=null&&(s.mt_dist||[]).length>1?"各行不一样，这是最多的":s.mt_unset?"没写的按 4096":"每行都一样"),tip:mt.text})+
    stat("用过",fmtInt(uses.length),"次",{sub:uses.length?`最近 ${esc(shortTime(uses[0].started_utc))}`:"还没用过",tip:"在速度测试里用过几次（3.6.0 之后的测试才有记录）"})+
    stat("文件",esc(fmtBytes(s.size)),"",{sub:`导入于 ${esc(shortTime(s.imported_utc))}`});
  const renamed=u=>u.name&&u.name!==s.name?`<span class="faint">（当时叫「${esc(u.name)}」）</span>`:"";
  const meta=uses.length?`<div class="ts-uses-h">用过的测试（点一下到速度测试页看）：</div><ul class="ts-uses">${uses.slice(0,5).map(u=>`<li>${tsRunLink(u)}${renamed(u)}</li>`).join("")}</ul>${uses.length>5?`<div>……还有 ${uses.length-5} 次</div>`:""}`:"";
  return overview(concl,stats,{title:"概况",meta,cols:2});
}
function tsLenPanel(s){
  const bins=TS.bins,total=bins.reduce((t,b)=>t+b.n,0);
  const spec={id:"ts-len-t",title:"输入长度分布",exportName:"输入长度分布",columns:[{key:"label",label:"输入长度",unit:"字符",type:"text",sticky:true,tip:"每档含下限、不含上限"},
    {key:"n",label:"行数",type:"int"},{key:"pct",label:"占比",unit:"%",type:"num",digits:1}],
    rows:bins.map(b=>({label:lenBinText(b),n:b.n,pct:total?100*b.n/total:null})),empty:"没有能用的行"};
  return panel({id:"ts-len",title:"输入长度分布",jump:"输入长度",
    desc:`每行发给模型的文字有多少个字符（中文 1 个字算 1 个，图片不算），只算能用的 ${fmtInt(s.valid)} 行${s.valid?`：平均 ${fmtInt(s.chars_avg)}、最长 ${fmtInt(s.chars_max)}`:""}`,
    chart:ccard("tsLenChart","每档有几行",{desc:"横轴是输入长度（字符），每档含下限、不含上限",h:260}),tables:[spec]});
}
function tsDrawChart(){
  const bins=TS.bins||[];if(!$("tsLenChart"))return;
  if(!bins.length){chartEmpty("tsLenChart","没有能用的行");return}
  const total=bins.reduce((t,b)=>t+b.n,0);
  barChart("tsLenChart",{cats:bins.map(b=>b.label),series:[{name:"行数",color:C.series[4]||C.a,data:bins.map(b=>b.n)}],unit:"行",digits:0,labels:true,
    tip:{title:i=>`输入长度 ${lenBinText(bins[i])} 字符`,sub:i=>`占能用的行的 ${fmt(100*bins[i].n/total,1)}%`}});
  const inst=CHARTS.get("tsLenChart");if(inst)inst.setOption({yAxis:{minInterval:1}});  /* 行数只有整数刻度 */
}
function tsLinesSec(){
  const mode=PANEL_OVR.get("ts-lines")||(TS_PREF.mode==="table"?"table":"chart");
  return `<section class="sec" id="ts-lines" data-jump="逐行查看" data-pv="${mode}">
    <div class="sec-head"><div class="sec-head-text"><h2 class="sec-title">逐行查看</h2>
      <p class="sec-desc">每一行发给模型的消息、参数和备注；有问题的行写明原因（和测试时实际发送的判断一样）。键盘 ← → 翻页</p></div>
      <div class="sec-tools">${segHTML("data-pv-set",mode,[["chart","卡片","layers"],["table","表格","table"]])}</div></div>
    <div class="qb ts-lines">
      <div class="qb-bar"><label class="qb-search">${icon("search")}<input class="input" id="tsSearch" type="search" placeholder="搜索消息里的文字或备注" value="${esc(TS.q)}" aria-label="搜索消息里的文字或备注"></label></div>
      <div class="qb-chiprow" id="tsChipRow"><div class="filter-chips ts-chips" id="tsChips" role="group" aria-label="筛选"></div><div class="qb-pager-top" id="tsPagerTop"></div></div>
      <div id="tsEmpty"></div>
      <div class="pv-chart"><div class="qb-list" id="tsList"></div></div>
      <div class="pv-table" id="tsTable"></div>
      <div class="qb-pager" id="tsPager"></div>
    </div></section>`;
}
function tsRenderLines(){
  const L=TS.lines,list=$("tsList");if(!list)return;
  const chipFocus=document.activeElement&&document.activeElement.closest&&document.activeElement.closest("#tsChips [data-ts-filter]");
  $("tsChips").innerHTML=tsChipsHTML(L&&L.counts,TS.filter);
  if(chipFocus){const c=$("tsChips").querySelector(`[data-ts-filter="${TS.filter}"]`);if(c)c.focus({preventScroll:true})}
  list.removeAttribute("aria-busy");
  const clear=()=>{$("tsEmpty").innerHTML="";$("tsTable").innerHTML="";$("tsPagerTop").innerHTML="";$("tsPager").innerHTML=""};
  if(TS.linesErr){clear();list.innerHTML="";$("tsEmpty").innerHTML=tsErrorHTML("没能加载这一页",TS.linesErr,"lines");return}
  if(!L){clear();list.innerHTML=tsSkCardItems(3);return}
  const pages=Math.max(1,Math.ceil(L.total/TS.size));
  if(!L.lines.length){
    clear();list.innerHTML="";
    const narrowed=TS.filter!=="all"||TS.q;
    $("tsEmpty").innerHTML=narrowed?emptyState("没有符合条件的行",TS.q?`没有找到「${TS.q}」，换个关键词或筛选条件试试`:"换一个筛选条件看看",
      {iconName:TS.q?"search":"inbox",inline:true,action:`<button type="button" class="btn btn-secondary" data-ts-clear>${icon("x")}清除筛选</button>`})
      :emptyState("这里没有行","",{inline:true});
    return;
  }
  $("tsEmpty").innerHTML="";
  list.innerHTML=L.lines.map(l=>tsCard(l)).join("");
  $("tsTable").innerHTML=dataTable(tsLinesTableSpec(L.lines));
  $("tsPagerTop").innerHTML=pagerHTML("ts",{page:TS.page,pages,compact:true,keys:true});
  $("tsPager").innerHTML=pagerHTML("ts",{page:TS.page,pages,total:L.total,unit:"行",size:TS.size,sizes:TS_SIZES,keys:true});
  if(list.offsetParent)tsUnclamp(list);  /* 卡片藏着(表格视图)时量不出高度, 切回卡片时再量 */
}
/* 实际没有被截断的文字去掉「展开全文」 */
function tsUnclamp(root){
  if(!root)return;
  root.querySelectorAll(".ts-text.is-clamp").forEach(el=>{
    const more=el.nextElementSibling;
    if(el.scrollHeight>el.clientHeight+2||(more&&more.dataset.cut))return;
    el.classList.remove("is-clamp");
    if(more&&more.hasAttribute("data-ts-more"))more.remove();
  });
}
function tsFirstText(l){
  const t=(l.messages||[]).map(m=>(m.parts||[]).filter(p=>p.t==="text").map(p=>p.text).join(" ")).find(Boolean)||(l.raw&&l.raw.text)||"";
  return t.length>160?t.slice(0,160)+"…":t;
}
function tsLinesTableSpec(lines){
  return{id:"ts-lines-t",title:"逐行",exportName:"逐行查看",search:false,noSort:true,pageSize:1000,rowKey:l=>String(l.no),rows:lines,
    columns:[{key:"no",label:"行号",type:"int",sticky:true},
      {key:"st",label:"状态",type:"status",get:l=>{const s=tsStatusOf(l.status);return{tone:s.tone,text:s.text,icon:s.icon,tip:l.reason||s.tip}}},
      {key:"first",label:"消息",type:"html",get:l=>`<span class="dt-ellipsis ts-first" title="${esc(tsFirstText(l))}">${tsHighlight(tsFirstText(l),TS.q)}</span>`,text:(v,l)=>tsFirstText(l)},
      {key:"chars",label:"输入长度",unit:"字符",type:"int"},
      {key:"mt",label:"最多生成",unit:"token",type:"int"},
      {key:"tags",label:"标记",type:"text",tip:"要求 JSON 输出 / 带几张图 / 几条消息",
        get:l=>[l.json?"要求 JSON":"",l.images.length?`${l.images.length} 张图`:"",l.messages&&l.messages.length>1?`${l.messages.length} 条消息`:""].filter(Boolean).join(" · ")||"—"},
      {key:"why",label:"原因 / 提醒",type:"text",wrap:true,get:l=>[l.reason,...l.warns].filter(Boolean).join("；")||"—"},
      {key:"note",label:"备注",type:"html",get:l=>{const n=(l.meta&&typeof l.meta.note==="string"&&l.meta.note)||"";return n?`<span class="dt-ellipsis ts-note-cell" title="${esc(n)}">${tsHighlight(n,TS.q)}</span>`:"—"},
        text:(v,l)=>(l.meta&&typeof l.meta.note==="string"&&l.meta.note)||""}],
    expand:l=>tsCard(l,{inTable:true}),note:"点一行展开看完整内容"};
}
function tsCard(l,opt={}){
  const st=tsStatusOf(l.status),q=TS.q;
  const badges=[l.json?`<span class="badge is-info" title="带 response_format，测试时统计 JSON 是否合法">${icon("braces")}要求 JSON</span>`:"",
    l.images.length?`<span class="badge" title="消息里带图片，要用能看图的模型">${icon("image")}${l.images.length} 张图</span>`:"",
    l.warns.length?`<span class="badge is-warn" title="这些行照常发送">${icon("alert")}${l.warns.length} 条提醒</span>`:""].join("");
  const head=`<header class="qcard-head"><span class="qcard-where">第 ${fmtInt(l.no)} 行</span><span class="qv is-${st.tone}" title="${esc(st.tip)}">${icon(st.icon,"icon-sm")}${esc(st.text)}</span>${badges}
    ${l.chars!=null?`<span class="ts-card-len" title="发给模型的文字有多少个字符（图片不算）">${fmtInt(l.chars)} 字符</span>`:""}</header>`;
  const reason=l.status!=="ok"?`<div class="ts-reason is-${st.tone}">${icon(l.status==="skip"?"ban":"x-circle","icon-sm")}<span><b>原因：</b>${esc(l.reason||"—")}</span></div>`:"";
  const warns=l.warns.length?`<ul class="ts-warns" aria-label="提醒">${l.warns.map(w=>`<li>${icon("alert","icon-sm")}<span>${esc(w)}</span></li>`).join("")}</ul>`:"";
  const msgs=l.messages?`<div class="ts-msgs">${l.messages.map((m,i)=>tsMsgHTML(l,m,i,q)).join("")||`<div class="faint small">（messages 是空的）</div>`}</div>`
    :l.raw?`<div class="ts-msgs"><div class="ts-msg is-raw"><div class="ts-role">这一行的原文（不能按消息显示）</div>${tsTextHTML(l,l.raw,"raw",q)}</div></div>`:"";
  const items=l.status==="ok"||l.params?tsParamItems(l.params,l.mt):[];
  const params=items.length?`<div class="ts-params" aria-label="参数">${items.map(x=>`<span class="ts-param${x.tone?" is-"+x.tone:""}"${x.tip?` title="${esc(x.tip)}"`:""}>${esc(x.text)}</span>`).join("")}</div>`:"";
  const meta=l.meta&&typeof l.meta==="object"?l.meta:null;
  const noteText=meta&&typeof meta.note==="string"?meta.note:"";
  const metaExtra=meta?Object.keys(meta).filter(k=>k!=="note").map(k=>k==="prompt_tokens"?`约 ${fmtInt(meta[k])} token（meta.prompt_tokens）`:`${k} = ${tsShort(meta[k])}`):[];
  const note=noteText||metaExtra.length?`<div class="ts-note">${icon("info","icon-sm")}<span>${noteText?`<b>备注：</b>${tsHighlight(noteText,q)}`:""}${metaExtra.length?`<span class="faint">${noteText?" · ":""}${esc(metaExtra.join(" · "))}</span>`:""}</span></div>`:"";
  const foot=`<footer class="qcard-foot ts-card-foot">
    <button type="button" class="btn btn-ghost btn-sm" data-ts-copy="${l.no}" title="复制这一行的原始 JSON（和文件里一模一样）">${icon("copy")}复制这一行 JSON</button>
    <button type="button" class="btn btn-ghost btn-sm" data-ts-raw="${l.no}" title="格式化显示这一行的 JSON">${icon("braces")}看原始 JSON</button></footer>`;
  return `<article class="qcard ts-card${l.status!=="ok"?" is-"+st.tone:""}" data-no="${l.no}" aria-label="第 ${l.no} 行，${esc(st.text)}">${head}${reason}${warns}${msgs}${params}${note}${foot}</article>`;
}
function tsMsgHTML(l,m,i,q){
  const extra=[m.name?`名字 ${m.name}`:"",m.tool_call_id?`回应工具调用 ${m.tool_call_id}`:"",
    m.tool_calls?`调用工具：${m.tool_calls.join("、")}${m.tool_calls_n>m.tool_calls.length?` 等 ${m.tool_calls_n} 个`:""}`:""].filter(Boolean);
  let html="",imgs=[];
  const flush=()=>{if(imgs.length){html+=`<div class="ts-img-row">${imgs.join("")}</div>`;imgs=[]}};
  (m.parts||[]).forEach((p,j)=>{
    if(p.t==="img"){imgs.push(tsImgHTML(l,p.i));return}
    flush();
    html+=p.t==="text"?tsTextHTML(l,p,`${i}-${j}`,q):`<div class="faint small">（${esc(p.type)} 类型的内容，这里不显示）</div>`;
  });
  flush();
  const role=m.role||"";
  return `<div class="ts-msg ts-role-${esc(/^[a-z]+$/.test(role)?role:"other")}"><div class="ts-role" title="${esc(role?"role: "+role:"这条消息没写 role")}">${esc(tsRoleName(m.role))}${extra.length?`<span class="ts-role-extra">${esc(extra.join(" · "))}</span>`:""}</div>
    ${html||(m.tool_calls?"":`<div class="faint small">（没有内容）</div>`)}</div>`;
}
function tsTextHTML(l,p,key,q){
  const cut=!!p.cut;
  return `<div class="ts-text is-clamp" data-key="${esc(key)}">${tsHighlight(p.text,q)}${cut?`<span class="ts-cut">……</span>`:""}</div>`+
    `<button type="button" class="ts-more" data-ts-more="${l.no}" data-key="${esc(key)}"${cut?' data-cut="1"':""} aria-expanded="false">展开全文${cut?`（共 ${fmtInt(p.len)} 字）`:""}</button>`;
}
function tsImgSrc(no,i){return `/api/task-set-image?id=${encodeURIComponent(TS.cur)}&line=${no}&idx=${i}`}
function tsImgCap(im){return [im.width&&im.height?`${im.width}×${im.height}`:"",im.format||"",im.bytes?fmtBytes(im.bytes):""].filter(Boolean).join(" · ")}
function tsImgHTML(l,i){
  const im=l.images[i]||{};
  if(im.kind==="url")return `<div class="ts-img is-url" title="网址形式的图片：测试时由模型服务自己去下载，这里不加载">${icon("image")}<span class="ts-img-body"><span class="ts-img-cap">网址图片（这里不加载）</span><span class="ts-url mono">${esc(im.url)}${im.cut?"…":""}</span></span></div>`;
  if(im.kind!=="data")return `<div class="ts-img is-wrong">${icon("x-circle")}<span class="ts-img-body"><span class="ts-img-cap">第 ${i+1} 张图写得不对</span><span class="ts-img-msg">${esc(im.msg||"")}</span></span></div>`;
  /* 服务端已经知道这张图解不开(损坏、不是图片): 不去请求, 直接写原因 */
  if(!im.format)return `<div class="ts-img is-bad" title="${esc(im.msg||"")}"><span class="ts-thumb is-broken">${icon("image")}<span>显示不了</span></span>
    <span class="ts-img-cap">第 ${i+1} 张图 · ${esc(fmtBytes(im.bytes))}</span><span class="ts-img-msg">${icon("x-circle","icon-sm")}${esc(im.msg||"数据读不出来")}</span></div>`;
  const cap=tsImgCap(im)||"读不出尺寸";
  return `<button type="button" class="ts-img${im.ok===false?" is-bad":im.level==="warn"?" is-warn":""}" data-ts-img="${l.no}" data-idx="${i}" title="点一下看大图${im.msg?"："+esc(im.msg):""}" aria-label="第 ${i+1} 张图，${esc(cap)}，点一下看大图">
    <span class="ts-thumb"><img loading="lazy" decoding="async" alt="" src="${esc(tsImgSrc(l.no,i))}" data-ts-thumb="${esc(im.ok===false&&im.msg?im.msg:"")}"></span>
    <span class="ts-img-cap">${esc(cap)}</span>${im.msg?`<span class="ts-img-msg">${icon(im.ok===false?"x-circle":"alert","icon-sm")}${esc(im.msg)}</span>`:""}</button>`;
}

/* ---------- 操作 ---------- */
async function tsImport(file){
  if(!file)return;
  if(TS.importing){toast("正在导入上一个文件，请稍等","warning");return}
  const chk=tsFileCheck(file.name);
  const fail=text=>{TS.report={id:"",html:alertBox("bad",`<b>${esc(text)}</b>`)};tsRender();toast(text,"error")};
  if(!chk.ok){fail(chk.reason);return}
  if(file.size>15*1024*1024){fail(`${file.name} 有 ${fmtBytes(file.size)}，超过 15 MB 的上限：请拆成几个小文件，或放到服务器上用命令行 --custom-file 引用`);return}
  TS.importing=true;tsImportBusy(true);
  try{
    const body={kind:"tasks",name:file.name,content:await file.text()};
    if(new Blob([JSON.stringify(body)]).size>UPLOAD_BODY_MAX){fail(`${file.name} 太大：上传时超过服务一次最多收的 16 MB，请拆成几个小文件`);return}
    const d=await postJSON("/api/scenario-upload",body);
    TS.report={id:d.ok?d.file_id:"",html:taskReportHtml(d,file.name)};
    if(!d.ok){tsRender();toast("导入失败："+(d.error||"没有一行能用"),"error");return}
    await tsLoadList();
    loadScenarioAssets();  /* 新建面板的下拉也刷新 */
    TS.flash=d.file_id;
    if(d.exists){
      toast(`这个任务集已经导入过（名称：${d.name}），没有重复保存`,"info",8000,{label:"打开它",onClick:()=>tsOpen(d.file_id)});
      tsRender();
    }else{
      toast(`已导入「${d.name}」`,"success",3000);
      if(TS.cur===d.file_id)tsRender();else tsOpen(d.file_id);
    }
  }catch(e){fail("读取文件失败："+e.message)}
  finally{TS.importing=false;tsImportBusy(false)}
}
function tsDownload(id){
  const a=document.createElement("a");a.href="/api/task-set-download?id="+encodeURIComponent(id);a.download="";
  document.body.appendChild(a);a.click();a.remove();
}
/* 在速度测试里使用: 打开新建速度测试, 勾选「自定义任务集」、选中它, 抽屉滚到这一栏并短暂高亮 */
async function tsUse(id){
  const s=tsFind(id);
  const chip=document.querySelector('#scnChips input[value="custom"]');
  if(chip&&!chip.checked){chip.checked=true;scnSyncVisibility()}
  const sel=$("fTaskSel");
  if(![...sel.options].some(o=>o.value===id))await loadScenarioAssets(null,id);
  if(![...sel.options].some(o=>o.value===id)){toast("新建面板里找不到这个任务集，请刷新页面再试","error");return}
  sel.value=id;scnAssetRemember();scnAssetSync();
  toggleLauncher("launcher",true);
  launcherSummary();
  const row=$("scnCustomRow");
  requestAnimationFrame(()=>{
    row.scrollIntoView({block:"center",behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth"});
    row.classList.remove("is-flash");void row.offsetWidth;row.classList.add("is-flash");
    setTimeout(()=>row.classList.remove("is-flash"),1800);
    const trig=sel._cs&&sel._cs.trigger;(trig||sel).focus({preventScroll:true});
  });
  toast(`已在新建速度测试里选中「${s?s.name:id}」`,"success",2500);
}
/* 改名(列表和「更多」菜单): 弹窗里改, 自动全选; 回车保存, Esc 关闭; 没改动或不合规时保存按钮不能点 */
function tsRenameDialog(id){
  const s=tsFind(id);if(!s)return;
  Modal.open("改名",`<form class="ts-rename" id="tsRenameForm" novalidate>
      <label class="ts-rename-label" for="tsRenameInput">任务集名称</label>
      <input class="input" id="tsRenameInput" value="${esc(s.name)}" autocomplete="off" spellcheck="false" aria-describedby="tsRenameHelp">
      <div class="ts-name-help" id="tsRenameHelp" aria-live="polite">1–${TS_NAME_MAX} 个字；回车保存，Esc 取消</div>
      <div class="dialog-actions"><button type="button" class="btn btn-secondary" data-ts-dialog-cancel>取消</button>
        <button type="submit" class="btn btn-primary" id="tsRenameSave" disabled>保存</button></div></form>`,{dialog:true});
  const inp=$("tsRenameInput"),help=$("tsRenameHelp"),save=$("tsRenameSave");
  const check=()=>{const c=tsNameCheck(inp.value),same=c.ok&&c.name===s.name;
    save.disabled=!c.ok||same;inp.setAttribute("aria-invalid",String(!c.ok));
    help.classList.toggle("is-error",!c.ok);help.textContent=c.ok?(same?"名称没有改动":`${c.n} / ${TS_NAME_MAX} 个字；回车保存，Esc 取消`):c.error;return c};
  inp.addEventListener("input",check);
  $("tsRenameForm").addEventListener("submit",async e=>{
    e.preventDefault();const c=check();if(!c.ok||c.name===s.name)return;
    setBusy(save,true);
    const err=await tsDoRename(id,c.name);
    setBusy(save,false);
    if(err){help.textContent=err;help.classList.add("is-error");inp.focus();return}
    Modal.close();tsRefocusRename(id);
  });
  $("tsRenameForm").querySelector("[data-ts-dialog-cancel]").addEventListener("click",()=>Modal.close());
  setTimeout(()=>{inp.focus();inp.select()},0);
}
/* 保存新名称; 成功后就地更新列表和详情, 返回错误说明(成功时为空) */
async function tsDoRename(id,name){
  const d=await postJSON("/api/task-set-rename",{id,name});
  if(!d.ok)return d.error||"改名失败";
  (TS.list||[]).forEach(x=>{if(x.id===id)x.name=d.name});
  if(TS.data&&TS.data.set&&TS.data.set.id===id)TS.data.set.name=d.name;
  toast(`已改名为「${d.name}」`,"success",2500);
  tsRender();
  loadScenarioAssets();  /* 新建面板的下拉跟着改 */
  return "";
}
/* 改完名后焦点放回原处: 列表里是这一行的「改名」, 详情里是名称旁的笔 */
function tsRefocusRename(id){
  const el=TS.cur?document.querySelector("#tsTitle [data-ts-edit]"):document.querySelector(`[data-dt="ts-list-t"] [data-ts-act="rename"][data-id="${CSS.escape(id)}"]`);
  if(el)el.focus({preventScroll:true});
}
/* 详情页头: 点名称旁的笔原地改名; 回车保存, Esc 取消, 空名或超长当场提示 */
function tsInlineRename(){
  const s=TS.data&&TS.data.set,box=$("tsTitle");if(!s||!box)return;
  box.innerHTML=`<form class="ts-rename-inline" id="tsInline" novalidate>
    <input class="input ts-name-input" id="tsInlineInput" value="${esc(s.name)}" autocomplete="off" spellcheck="false" aria-label="任务集名称" aria-describedby="tsInlineHelp">
    <button type="submit" class="btn btn-primary btn-sm" id="tsInlineSave" disabled>保存</button>
    <button type="button" class="btn btn-ghost btn-sm" data-ts-inline-cancel>取消</button>
    <div class="ts-name-help" id="tsInlineHelp" aria-live="polite">回车保存，Esc 取消</div></form>`;
  const inp=$("tsInlineInput"),help=$("tsInlineHelp"),save=$("tsInlineSave");
  const cancel=()=>{box.innerHTML=tsTitleHTML(s);const b=box.querySelector("[data-ts-edit]");if(b)b.focus()};
  const check=()=>{const c=tsNameCheck(inp.value),same=c.ok&&c.name===s.name;
    save.disabled=!c.ok||same;inp.setAttribute("aria-invalid",String(!c.ok));
    help.classList.toggle("is-error",!c.ok);help.textContent=c.ok?(same?"名称没有改动；Esc 取消":`${c.n} / ${TS_NAME_MAX} 个字；回车保存，Esc 取消`):c.error;return c};
  inp.addEventListener("input",check);
  inp.addEventListener("keydown",e=>{if(e.key==="Escape"){e.preventDefault();e.stopPropagation();cancel()}});
  box.querySelector("[data-ts-inline-cancel]").addEventListener("click",cancel);
  $("tsInline").addEventListener("submit",async e=>{
    e.preventDefault();const c=check();
    if(!c.ok){inp.focus();return}
    if(c.name===s.name){cancel();return}
    setBusy(save,true);
    const err=await tsDoRename(s.id,c.name);
    if(err){setBusy(save,false);help.textContent=err;help.classList.add("is-error");inp.focus();return}
    tsRefocusRename(s.id);
  });
  inp.focus();inp.select();
}
async function tsDelete(id){
  const s=tsFind(id);if(!s)return;
  if(s.busy){toast("有速度测试正在用这个任务集，等测试结束（或停止它）之后再删除","warning");return}
  const ok=await confirmDialog({title:"删除任务集",confirmText:"删除",danger:true,
    message:`删除「${s.name}」？\n\n已经跑完的测试结果不受影响，只是以后新建速度测试时不能再选它。`+
      (s.uses?`\n这个任务集在速度测试里用过 ${s.uses} 次。`:"")+"\n删除后不能恢复，需要的话先下载原文件留一份。"});
  if(!ok)return;
  const d=await postJSON("/api/task-set-delete",{id});
  if(!d.ok){toast("删除失败："+d.error,"error");return}
  toast(`已删除「${s.name}」`,"success",3000);
  const i=(TS.list||[]).findIndex(x=>x.id===id),next=TS.list&&(TS.list[i+1]||TS.list[i-1]);
  if(TS.list)TS.list=TS.list.filter(x=>x.id!==id);
  if(TS.report&&TS.report.id===id)TS.report=null;
  if(TS.cur===id){TS.cur="";TS.dataFor="";TS.data=null;TS.fromList=false;try{history.replaceState(null,"","#tasks")}catch(e){}}
  TS.focusAfter=next?"row:"+next.id:"";
  tsRender();  /* 列表就地更新, 不整页刷新 */
  if(!next){const b=$("tsImportBtn");if(b)b.focus()}
  loadScenarioAssets();
}
/* 复制一行: 取文件里这一行的原文(图片的 base64 也原样带上) */
async function tsCopyLine(no){
  try{
    const d=await tsApi(`/api/task-set-line?id=${encodeURIComponent(TS.cur)}&line=${no}&raw=1`);
    await tsCopyText(d.text);
    toast(`已复制第 ${no} 行的 JSON`,"success",2000);
  }catch(e){toast("复制失败："+e.message+"。可以点「看原始 JSON」手动选中复制","error")}
}
function tsCopyText(text){
  if(navigator.clipboard&&window.isSecureContext)return navigator.clipboard.writeText(text);
  return new Promise((res,rej)=>{  /* 不是 https 或本机地址时浏览器不给剪贴板接口: 用老办法 */
    const prev=document.activeElement,t=document.createElement("textarea");
    t.value=text;t.setAttribute("readonly","");t.style.cssText="position:fixed;left:-9999px;top:0;opacity:0";
    document.body.appendChild(t);t.select();
    let ok=false;try{ok=document.execCommand("copy")}catch(e){}
    t.remove();if(prev&&prev.focus)prev.focus({preventScroll:true});
    ok?res():rej(new Error("浏览器没有允许复制"));
  });
}
/* 取某一行的全文(「展开全文」「看原始 JSON」共用, 按行缓存) */
function tsLine(no){
  const k=TS.cur+"|"+no;
  if(!TS.full.has(k))TS.full.set(k,tsApi(`/api/task-set-line?id=${encodeURIComponent(TS.cur)}&line=${no}`).catch(e=>{TS.full.delete(k);throw e}));
  return TS.full.get(k);
}
async function tsRawModal(no){
  Modal.open(`第 ${fmtInt(no)} 行的原始 JSON`,`<div class="qb-loading faint">正在加载…</div>`,{wide:true});
  const body=$("modalBody"),mark=body.dataset.tsRaw=String(no)+"|"+Date.now();
  let html;
  try{
    const d=await tsLine(no);
    html=d.pretty!=null?`<div class="ts-raw-bar"><span class="faint">图片的 base64 只显示开头；「复制这一行 JSON」得到的是文件里的原文</span>
        <button type="button" class="btn btn-secondary btn-sm" data-ts-copy="${no}">${icon("copy")}复制这一行 JSON</button></div><pre class="raw-box ts-raw" tabindex="0">${esc(d.pretty)}</pre>`
      :`${alertBox("bad",`这一行不是合法的 JSON：${esc(d.line.reason||"")}`)}<pre class="raw-box ts-raw" tabindex="0">${esc(d.line.raw?d.line.raw.text:"")}</pre>`;
  }catch(e){html=emptyState("没能加载这一行",e.message,{iconName:"alert",inline:true})}
  if(!$("modal").hidden&&body.dataset.tsRaw===mark)body.innerHTML=html;
}
function tsImgModal(no,i){
  const l=((TS.lines&&TS.lines.lines)||[]).find(x=>x.no===no);const im=l&&l.images[i];if(!im)return;
  const w=im.width||0,zoom=w&&w<96?Math.min(8,Math.floor(192/w)):1;  /* 很小的图放大几倍看清楚 */
  Modal.open(`第 ${fmtInt(no)} 行 · 第 ${i+1} 张图`,`<figure class="ts-big"><div class="ts-big-img"><img src="${esc(tsImgSrc(no,i))}" alt="第 ${no} 行的第 ${i+1} 张图"${zoom>1?` style="width:${w*zoom}px" class="is-pixel"`:""}></div>
    <figcaption>${esc(tsImgCap(im))}${zoom>1?`（放大 ${zoom} 倍显示）`:""}${im.msg?`<div class="${im.ok===false?"bad":"warn"}">${esc(im.msg)}</div>`:""}</figcaption></figure>`,{wide:true});
}
/* 展开 / 收起一段文字; 服务端截断过的先取全文 */
async function tsToggleMore(btn){
  const text=btn.previousElementSibling,card=btn.closest(".qcard");if(!text)return;
  if(btn.dataset.cut){
    btn.disabled=true;btn.textContent="正在加载全文…";
    try{
      const d=await tsLine(+btn.dataset.tsMore),k=btn.dataset.key;
      let full="";
      if(k==="raw")full=d.line.raw?d.line.raw.text:"";
      else{const [i,j]=k.split("-").map(Number),p=((d.line.messages||[])[i]||{}).parts;full=p&&p[j]?p[j].text:""}
      text.innerHTML=tsHighlight(full,TS.q);
      delete btn.dataset.cut;
    }catch(e){btn.disabled=false;btn.textContent="展开全文";toast("没能取到全文："+e.message,"error");return}
    btn.disabled=false;
  }
  const open=text.classList.contains("is-clamp");
  text.classList.toggle("is-clamp",!open);
  btn.textContent=open?"收起":"展开全文";btn.setAttribute("aria-expanded",String(open));
  if(card&&card.closest(".qb-list")){  /* 展开的卡片占满一行, 读长文更方便 */
    const wide=!!card.querySelector('.ts-more[aria-expanded="true"]'),was=card.classList.contains("is-wide");
    card.classList.toggle("is-wide",wide);if(was!==wide)card.scrollIntoView({block:"nearest"});
  }
  btn.focus({preventScroll:true});
}
function tsSetPage(p){
  const k=pagerFocusKey();
  TS.page=p;tsSaveState();
  return tsFetch(false).then(()=>{scrollTopIntoView($("tsChipRow"));pagerRefocus($("ts-lines"),k)});
}
function tsSetFilter(f){
  TS.filter=f;TS.page=0;tsSaveState();
  $("tsChips").querySelectorAll("[data-ts-filter]").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.tsFilter===f)));
  tsFetch(false);
}
/* 到速度测试页看某次测试(「用过的测试」里的链接) */
async function tsOpenRun(id){
  if(!RUNS[id])await refresh();
  if(!RUNS[id]){toast("这次测试已经不在了（可能被删除）","warning");return}
  $("runA").value=id;
  location.hash="#dash";  /* 切页面时画选中的这次测试; 浏览器后退回到任务集 */
}

/* ---------- 事件 ---------- */
$("tsImportBtn").addEventListener("click",()=>{if(!TS.importing)$("tsImportFile").click()});
$("tsImportFile").addEventListener("change",e=>{const f=e.target.files[0];e.target.value="";tsImport(f)});
document.addEventListener("click",e=>{
  if(!e.target.closest)return;
  if(e.target.closest("[data-ts-tpl]")){downloadTaskTemplate();toast("已下载模板：每种写法都有一两行示例，每行的 meta.note 是说明","success",4000);return}
  if(e.target.closest("[data-ts-refresh]")){tsRefresh();return}
  const go=e.target.closest("[data-goto-tasks]");
  if(go){e.preventDefault();closeDrawers();if(VIEW!=="tasks"||TS.cur)location.hash="#tasks";return}
  const cp=e.target.closest("[data-ts-copy]");if(cp){tsCopyLine(+cp.dataset.tsCopy);return}
});
$("tasksBody").addEventListener("click",e=>{
  const t=e.target;
  const imp=t.closest("[data-ts-import]");if(imp){if(!TS.importing)$("tsImportFile").click();return}
  const act=t.closest("[data-ts-act]");
  if(act){const id=act.dataset.id,a=act.dataset.tsAct;
    if(a==="view")tsOpen(id);else if(a==="use")tsUse(id);else if(a==="download")tsDownload(id);
    else if(a==="rename")tsRenameDialog(id);else if(a==="delete")tsDelete(id);return}
  if(t.closest("[data-ts-back]")){e.preventDefault();tsBack();return}
  if(t.closest("[data-ts-edit]")){tsInlineRename();return}
  if(t.closest("[data-ts-report-close]")){TS.report=null;const r=t.closest(".ts-report");if(r)r.remove();return}
  const rt=t.closest("[data-ts-retry]");
  if(rt){const w=rt.dataset.tsRetry;
    if(w==="list"){TS.listErr="";tsLoadList();tsRenderList()}
    else if(w==="detail"){TS.dataFor="";tsRenderDetail()}
    else{TS.linesErr="";TS.lines=null;tsRenderLines();tsFetch(false)}return}
  const run=t.closest("[data-ts-run]");if(run){e.preventDefault();tsOpenRun(run.dataset.tsRun);return}
  const gt=t.closest("[data-ts-goto]");
  if(gt){e.preventDefault();tsSetFilter(gt.dataset.tsGoto);const sec=$("ts-lines");if(sec)sec.scrollIntoView({behavior:"smooth",block:"start"});return}
  const ch=t.closest("#tsChips [data-ts-filter]");if(ch){tsSetFilter(ch.dataset.tsFilter);return}
  if(t.closest("[data-ts-clear]")){TS.filter="all";TS.q="";TS.page=0;const s=$("tsSearch");if(s)s.value="";tsSaveState();tsFetch(false);if(s)s.focus();return}
  const pg=t.closest("[data-ts-page]");if(pg){tsSetPage(+pg.dataset.tsPage);return}
  const jb=t.closest("[data-ts-jumpbtn]");if(jb){const n=pagerTarget(jb.parentElement.querySelector("[data-ts-jump]"));if(n!=null)tsSetPage(n);return}
  const more=t.closest("[data-ts-more]");if(more){tsToggleMore(more);return}
  const im=t.closest("[data-ts-img]");if(im){tsImgModal(+im.dataset.tsImg,+im.dataset.idx);return}
  if(t.closest('[data-dt="ts-lines-t"] tr.is-expandable'))setTimeout(()=>tsUnclamp($("tsTable")),0);  /* 表格里展开的一行 */
  const raw=t.closest("[data-ts-raw]");if(raw){tsRawModal(+raw.dataset.tsRaw);return}
  if(t.closest("a,button,input,select,label,summary,details"))return;
  const tr=t.closest('[data-dt="ts-list-t"] tr.is-link');if(tr&&tr.dataset.rk)tsOpen(tr.dataset.rk);  /* 点一行打开详情 */
});
$("tasksBody").addEventListener("change",e=>{
  const sz=e.target.closest("[data-ts-size]");
  if(sz){const first=TS.page*TS.size;TS.size=+sz.value;TS.page=Math.floor(first/TS.size);tsSaveState();
    tsFetch(false).then(()=>{const s=$("tsPager")&&$("tsPager").querySelector("[data-ts-size]");if(s)s.focus()});return}
  if(e.target.matches(".is-compact [data-ts-jump]")){const n=pagerTarget(e.target);if(n!=null&&n!==TS.page)tsSetPage(n);else e.target.value=TS.page+1}
});
$("tasksBody").addEventListener("keydown",e=>{
  if(e.key==="Enter"&&e.target.matches("[data-ts-jump]")){e.preventDefault();const n=pagerTarget(e.target);if(n!=null)tsSetPage(n)}
});
let tsQT=null;
$("tasksBody").addEventListener("input",e=>{
  if(e.target.id!=="tsSearch")return;
  clearTimeout(tsQT);
  tsQT=setTimeout(()=>{TS.q=e.target.value.trim().slice(0,200);TS.page=0;tsSaveState();tsFetch(false)},250);
});
/* 卡片 / 表格: 记住选的看法; 切回卡片时量一下哪些文字其实不用「展开全文」 */
$("tasksBody").addEventListener("click",e=>{const b=e.target.closest("#ts-lines [data-pv-set]");if(!b)return;
  TS_PREF.mode=b.dataset.pvSet;lsSet(TS_LS,TS_PREF);
  if(b.dataset.pvSet==="chart")requestAnimationFrame(()=>tsUnclamp($("tsList")))});
/* 缩略图加载失败: 换成占位, 写明原因 */
$("tasksBody").addEventListener("error",e=>{
  const img=e.target;if(!img||!img.matches||!img.matches("img[data-ts-thumb]"))return;
  const box=img.parentElement;box.classList.add("is-broken");
  box.innerHTML=`${icon("image")}<span>加载失败${img.dataset.tsThumb?"："+esc(img.dataset.tsThumb):"：图片数据读不出来"}</span>`;
},true);
/* 键盘 ← → 翻逐行卡片: 逐行区在屏幕上、焦点不在输入框里、没有打开面板或弹窗时才生效 */
document.addEventListener("keydown",e=>{
  if(VIEW!=="tasks"||!TS.cur||(e.key!=="ArrowLeft"&&e.key!=="ArrowRight")||e.altKey||e.ctrlKey||e.metaKey||e.shiftKey||e.defaultPrevented)return;
  if(e.target.closest&&e.target.closest("input,select,textarea,[contenteditable=true],details[open]"))return;
  if(!$("modal").hidden||document.querySelector(".drawer:not([hidden])"))return;
  const sec=$("ts-lines");if(!sec||!TS.lines||!TS.lines.total)return;
  const r=sec.getBoundingClientRect();if(r.bottom<80||r.top>innerHeight-80)return;
  const pages=Math.max(1,Math.ceil(TS.lines.total/TS.size)),p=TS.page+(e.key==="ArrowLeft"?-1:1);
  if(p<0||p>=pages)return;
  e.preventDefault();tsSetPage(p);
});
/* 把文件拖到任务集页面上导入: 整页虚线框遮罩「松开即可导入」, 拖走消失; 一看就不支持的文件(图片、多个文件)当场说明 */
let tsDragN=0,tsDragT=null;
function tsDragHasFiles(e){return !!(e.dataTransfer&&[...(e.dataTransfer.types||[])].includes("Files"))}
function tsDropState(e){
  const items=[...((e.dataTransfer&&e.dataTransfer.items)||[])].filter(x=>x.kind==="file");
  if(items.length>1)return `一次只能导入一个文件（现在拖了 ${items.length} 个）`;
  const type=items[0]&&items[0].type||"";
  if(type&&!/^text\/|^application\/(json|x-ndjson|jsonl|x-jsonlines|ndjson)/.test(type))return `不支持这种文件（${type}）：只能导入 .jsonl、.json 或 .txt`;
  return "";
}
function tsDropShow(e){
  clearTimeout(tsDragT);tsDragT=setTimeout(tsDropHide,800);  /* 拖出窗口时有的浏览器不发 dragleave */
  const bad=tsDropState(e),m=$("tsDrop");
  m.hidden=false;m.classList.toggle("is-bad",!!bad);
  $("tsDropTitle").textContent=bad?"不能导入":"松开即可导入任务集";
  $("tsDropSub").textContent=bad||".jsonl / .json / .txt，每行一个 JSON 请求";
  $("tsDropIcon").setAttribute("href",bad?"#i-ban":"#i-upload");
  if(e.dataTransfer)e.dataTransfer.dropEffect=bad?"none":"copy";
}
function tsDropHide(){clearTimeout(tsDragT);tsDragN=0;const m=$("tsDrop");if(m)m.hidden=true}
function tsDropOn(e){return VIEW==="tasks"&&!OFF&&tsDragHasFiles(e)}
document.addEventListener("dragenter",e=>{if(!tsDropOn(e))return;e.preventDefault();tsDragN++;if($("modal").hidden)tsDropShow(e)});
document.addEventListener("dragover",e=>{if(!tsDropOn(e))return;e.preventDefault();if($("modal").hidden)tsDropShow(e);else e.dataTransfer.dropEffect="none"});
document.addEventListener("dragleave",e=>{if(!tsDropOn(e))return;tsDragN=Math.max(0,tsDragN-1);if(!tsDragN)tsDropHide()});
document.addEventListener("drop",e=>{
  if(!tsDropOn(e))return;
  e.preventDefault();tsDropHide();  /* 不让浏览器直接打开这个文件 */
  if(!$("modal").hidden)return;
  const files=[...(e.dataTransfer.files||[])];
  if(files.length>1){toast(`一次只能导入一个文件，这次拖了 ${files.length} 个，没有导入`,"warning");return}
  tsImport(files[0]);
});

/* ============================================================
   删除
   ============================================================ */
async function deleteRun(kind){
  const sel={perf:"runA",iq:"iqMainSel",gen:"genMainSel"}[kind],id=$(sel).value;
  const meta={perf:RUNS,iq:IQ_RUNS,gen:GEN_RUNS}[kind][id];
  if(!meta){toast("没有可以删除的记录","warning");return}
  const name={perf:label,iq:iqLabel,gen:genLabel}[kind](meta);
  const ok=await confirmDialog({title:"删除这条记录",confirmText:"删除",danger:true,
    message:`删除后无法恢复${kind==="gen"?"，作品文件和检查截图也会一起删除":""}。\n\n${name}`});
  if(!ok)return;
  const d=await postJSON("/api/run-delete",{run_id:id});
  if(!d.ok){toast("删除失败："+d.error,"error");return}
  toast("已删除","success",2500);
  if(kind==="perf"){delete FULL[id];refresh()}
  else if(kind==="iq"){IQ_CMP.delete(id);loadIqResults()}
  else loadGenResults();
}

/* ============================================================
   模型管理: 列表(添加 / 测试连接 / 用它新建 / 编辑 / 删除) · 详情(连接信息 / 服务上的模型 / 用过的测试)
   地址 #models 是列表, #models/<id> 是某一个; 浏览器后退回到列表, 刷新停在原处。
   保存的模型存在服务端(含 API Key)。页面上 Key 只显示遮住的形式, 完整的 Key 只在编辑弹窗里点眼睛才看得到,
   不写进元素属性、表格导出和本地存储; 离线报告里没有这一页, 也不带模型列表。
   「连接状态」是这次打开页面后测试连接的结果: 只有点了「测试连接」才去连, 打开页面不会自动发请求
   ============================================================ */
let EPS=[];
const EPS_ST={loaded:false,err:"",loading:null};
const EP_FIELDS={perf:["fBase","fKey","fModel"],iq:["iqBase","iqKey","iqModel"],gen:["genBase","genKey","genModel"]};
const EP_SEL={perf:"fEpSel",iq:"iqEpSel",gen:"genEpSel"};
const EP_ADD="__add__";          /* 新建面板的下拉里「还没有保存的模型，去添加」 */
const MD_ID_RE=/^ep_[A-Za-z0-9_]{1,60}$/;
const MD_NAME_MAX=64,MD_MODEL_MAX=128,MD_URL_MAX=500,MD_KEY_MAX=8192;
const MD_PROBE_CONC=4;           /* 全部测试连接: 同时最多测几个 */
const MD_KIND={perf:{name:"速度测试",short:"速度",icon:"gauge",view:"dash",sel:"runA",launcher:"launcher",new:"新建速度测试"},
  iq:{name:"能力测试",short:"能力",icon:"list-checks",view:"iq",sel:"iqMainSel",launcher:"iqLauncher",new:"新建能力测试"},
  gen:{name:"代码生成",short:"代码生成",icon:"code",view:"gen",sel:"genMainSel",launcher:"genLauncher",new:"新建生成任务"}};
const MD_HELP={url:"OpenAI 兼容接口的地址，填到端口就行；末尾的 /v1 会自动去掉",key:"默认遮住，点右边的眼睛可以看；只存在本机的数据库里",
  model:"要和服务上的模型名称一模一样（区分大小写）",name:"列表和新建面板里显示的名字"};
/* cur: 正在看的模型 id(空 = 列表); probe: 这次打开页面后每个模型测试连接的结果; all: 全部测试连接的进度;
   runs: 详情里「用过的测试」按 id|类型 缓存; form: 添加 / 编辑弹窗的状态 */
const MD={cur:"",fromList:false,focusAfter:"",flash:"",q:"",probe:new Map(),all:null,runs:new Map(),kind:"all",form:null};

/* ---------- 纯逻辑(tests/js/checks.js 有断言) ---------- */
/* Key 的遮住形式: 16 个字以上露头尾各 4 个, 8–15 个露头尾各 2 个, 更短的全遮住; 与服务端 endpoints.mask_key 同一套 */
function maskKey(k){
  k=String(k||"");const n=k.length;
  if(!n)return "—";
  return n>=16?k.slice(0,4)+"…"+k.slice(-4):n>=8?k.slice(0,2)+"…"+k.slice(-2):"••••";
}
function epHost(url){const m=String(url||"").match(/^https?:\/\/([^/?#]+)/i);return m?m[1]:String(url||"")}
/* 名称、模型名称: 去掉控制字符、会打乱文字方向的不可见字符和首尾空白(与服务端同一套) */
function mdClean(s){return String(s??"").replace(/[\u0000-\u001f\u007f-\u009f‪-‮⁦-⁩﻿]/g,"").trim()}
function mdLen(s){return [...String(s??"")].length}
function mdDefaultName(model,url){return [...`${model} · ${epHost(url)}`].slice(0,MD_NAME_MAX).join("").trim()}
/* 地址: 去掉首尾空白, 再去掉末尾的 /、/v1、/v1/chat/completions(测试时会自动加上; 与服务端 bench.normalize_base 相同)。
   返回 {url, cut}: cut 是去掉的那一段(只去掉了末尾的 / 时为空, 不用提示) */
function mdUrlClean(raw){
  const s=String(raw??"").trim();let b=s.replace(/\/+$/,"");
  for(const suf of ["/chat/completions","/v1"])if(b.endsWith(suf))b=b.slice(0,-suf.length);
  const tail=s.slice(b.length);
  return{url:b,cut:/^\/*$/.test(tail)?"":tail};
}
/* 地址能不能用: http:// 或 https:// 开头、有主机、端口是数字、中间没有空白、不带用户名密码(与服务端 endpoints.url_ok 相同) */
function mdUrlOk(u){
  if(!/^https?:\/\/[^\s/?#@]+(?:[/?#]\S*)?$/i.test(String(u||"")))return false;
  try{return !!new URL(u).hostname}catch(e){return false}
}
/* 同一个服务的不同写法 → 同一个键(与服务端 endpoints.url_key 相同): 去掉末尾的 /v1 等, 协议和主机不分大小写,
   localhost 和 [::1] 当作 127.0.0.1, 没写端口时补上默认端口 */
function mdUrlKey(u){
  const b=mdUrlClean(u).url;
  try{
    const x=new URL(b);let h=x.hostname.toLowerCase();
    if(h==="localhost"||h==="[::1]")h="127.0.0.1";
    return `${x.protocol}//${h}:${x.port||(x.protocol==="https:"?443:80)}${x.pathname.replace(/\/+$/,"")}`;
  }catch(e){return b.toLowerCase()}
}
/* 添加 / 编辑时的检查(与服务端 endpoints.clean_fields 同一套): errors 是不能保存的问题, notes 是自动改过的地方 */
function mdFormCheck(raw){
  raw=raw||{};
  const errors={},notes={},{url,cut}=mdUrlClean(raw.url);
  if(!url)errors.url="请填写服务地址";
  else if(mdLen(url)>MD_URL_MAX)errors.url=`服务地址最多 ${MD_URL_MAX} 个字（现在 ${mdLen(url)} 个）`;
  else if(!mdUrlOk(url))errors.url="要以 http:// 或 https:// 开头，中间不能有空格，比如 http://127.0.0.1:8000";
  else if(cut)notes.url=`已去掉末尾的「${cut}」，测试时会自动加上`;
  const model=mdClean(raw.model);
  if(!model)errors.model="请填写模型名称";
  else if(mdLen(model)>MD_MODEL_MAX)errors.model=`模型名称最多 ${MD_MODEL_MAX} 个字（现在 ${mdLen(model)} 个）`;
  const name=mdClean(raw.name);
  if(mdLen(name)>MD_NAME_MAX)errors.name=`名称最多 ${MD_NAME_MAX} 个字（现在 ${mdLen(name)} 个）`;
  const k0=String(raw.key??""),key=k0.trim();
  if(/[\u0000-\u001f\u007f]/.test(key))errors.key="Key 中间不能有换行或其他控制字符";
  else if(key.length>MD_KEY_MAX)errors.key=`Key 最多 ${MD_KEY_MAX} 个字`;
  else if(key!==k0)notes.key="已去掉首尾的空格或换行";
  return{ok:!Object.keys(errors).length,errors,notes,nameDefault:!name,
    fields:{url,model,api_key:key,name:name||(url&&model?mdDefaultName(model,url):"")}};
}
/* 名称(详情页原地改名): 1–64 个字 */
function mdNameCheck(raw){
  const name=mdClean(raw),n=mdLen(name);
  if(!n)return{ok:false,name,n,error:"名称不能为空"};
  if(n>MD_NAME_MAX)return{ok:false,name,n,error:`名称最多 ${MD_NAME_MAX} 个字（现在 ${n} 个）`};
  return{ok:true,name,n,error:""};
}
/* 连不上的原因(服务端 endpoints.probe_fail 分的类): 短说法放进列表的状态格, 大白话解释放在悬停提示和详情里 */
const MD_FAIL={
  timeout:["超时","10 秒内没有响应：服务太忙、地址不通，或者被防火墙拦住了"],
  refused:["拒绝连接","这个地址上没有服务在运行：服务没开，或者端口写错了"],
  auth:["Key 不对","服务要求 API Key：填的 Key 不对、过期了，或者没填"],
  forbidden:["没有权限","服务认得这个 Key，但它没有访问这个服务的权限"],
  not_found:["地址不对","这个地址上找不到 /v1/models：检查一下端口和路径（地址填到端口就行）"],
  server:["服务出错","服务端内部出错了：稍后再试，或者看看服务的日志"],
  http:["请求被拒绝","服务拒绝了这次请求"],
  dns:["找不到主机","主机名写错了，或者这台电脑解析不了这个主机名"],
  unreachable:["网络不通","这台电脑连不到那个地址：不在同一个网络，或者中间的路不通"],
  reset:["连接被断开","服务中途断开了连接：可能不是 HTTP 服务，或者服务正在重启"],
  tls:["证书有问题","HTTPS 证书验证没通过：证书过期、是自签名的，或者其实该用 http://"],
  bad_json:["不是模型列表","返回的不是 OpenAI 兼容的模型列表：这个地址可能不是模型服务"],
  bad_url:["地址格式不对","要以 http:// 或 https:// 开头，比如 http://127.0.0.1:8000"],
  bad_key:["Key 格式不对","Key 中间不能有换行或其他控制字符"],
};
/* {short: 如「401 Key 不对」「拒绝连接」, long: 大白话解释, raw: 服务端给的原文(Key 已由服务端遮住)} */
function mdFailText(d){
  d=d||{};
  const st=d.status,code=d.code==="auth"&&st===403?"forbidden":d.code,f=MD_FAIL[code];
  if(!f)return{short:"连不上",long:d.error||"连不上这个服务",raw:d.error||""};
  const withSt=st&&["auth","forbidden","not_found","server","http"].includes(code);
  return{short:(withSt?st+" ":"")+f[0],long:f[1],raw:d.error||""};
}
function mdLatency(ms){return ms==null||!isFinite(ms)?"—":ms<1000?`${fmtInt(ms)} 毫秒`:`${fmt(ms/1000,1)} 秒`}
function mdCtxText(n){return n?`最大上下文 ${fmtInt(n)} token`:"服务没给最大上下文"}
/* 最近使用: 一键填入的时间和最近一次用它跑测试的时间, 取晚的那个; 都没有时为空 */
function mdLastUse(ep){
  const a=ep&&ep.last_used_utc,b=ep&&ep.uses&&ep.uses.last_utc,da=toDate(a),db=toDate(b);
  return da&&(!db||da>=db)?a:db?b:"";
}
function mdTime(iso){const d=toDate(iso);return d?d.getTime():null}
/* 默认顺序: 最近使用的在前; 都没用过的按添加时间, 新的在前 */
function mdOrder(list){
  const t=e=>mdTime(mdLastUse(e))??-Infinity,c=e=>mdTime(e.created_utc)??0;
  return [...(list||[])].sort((x,y)=>(t(y)-t(x))||(c(y)-c(x)));
}
/* 保存的模型在不在服务返回的模型列表里(区分大小写) */
function mdHasModel(d,model){return !!(d&&(d.models||[]).some(m=>m.id===model))}
function mdUses(ep){return Object.assign({perf:0,iq:0,gen:0,total:0,last_utc:null},ep&&ep.uses)}
/* 用过的测试: 一行结果摘要(速度: 最高总生成速度与单个请求速度; 能力: 正确率; 代码生成: 完成几题、检查通过率) */
function mdRunSummary(r){
  const s=(r&&r.summary)||{};
  if(r.kind==="perf"){
    const p=[];
    if(s.peak_tps!=null)p.push(`最高总生成速度 ${fmt(s.peak_tps,1)} token/秒${s.peak_conc?`（同时 ${s.peak_conc} 个请求）`:""}`);
    if(s.decode_tps!=null)p.push(`单个请求 ${fmt(s.decode_tps,1)} token/秒`);
    if(s.scn)p.push(`模拟业务 ${s.scn} 类`);
    return p.join(" · ")||"没有速度数据";
  }
  if(r.kind==="iq")return s.acc!=null?`正确率 ${fmt(s.acc,1)}%${s.n?`（答对 ${fmtInt(s.correct)} / ${fmtInt(s.n)} 题）`:""}`:"没有成绩";
  const p=[`完成 ${fmtInt(s.done||0)} / ${fmtInt(s.planned||0)} 题`];
  if(s.exec!=null)p.push(`${s.method==="static"?"只看了代码":"运行检查"}通过 ${fmt(s.exec,0)}%`);
  if(s.judge!=null)p.push(`AI 打分 ${fmt(s.judge,0)}`);
  return p.join(" · ");
}
function mdRunSetting(r){
  if(r.kind==="perf")return SUITE_NAME[r.suite]||r.suite||"—";
  return r.thinking==null?"—":r.thinking?"思考":"不思考";
}
function mdRunStatus(r){
  const tone={done:"good",running:"info",failed:"bad",interrupted:"warn",cancelled:"warn"}[r.status]||"neutral";
  return{tone,text:STATUS_NAME[r.status]||r.status||"—",tip:r.error||""};
}

/* ---------- 接口 ---------- */
function loadEndpoints(){
  if(OFF)return Promise.resolve();
  const before=EPS_ST.loaded?JSON.stringify(EPS):"";
  const p=EPS_ST.loading=tsApi("/api/endpoints")
    .then(l=>{if(EPS_ST.loading!==p)return;EPS=Array.isArray(l)?l:[];EPS_ST.loaded=true;EPS_ST.err="";renderEpSelects()})
    .catch(e=>{if(EPS_ST.loading!==p)return;EPS_ST.err=e.message;if(EPS_ST.loaded&&VIEW==="models")toast("刷新模型列表失败："+e.message,"error")})
    .finally(()=>{if(EPS_ST.loading!==p)return;EPS_ST.loading=null;
      if(VIEW==="models"&&(!before||EPS_ST.err||before!==JSON.stringify(EPS)))mdRender();mdPaintAllBtn()});
  return p;
}
/* 保存(新增或修改); 成功后 EPS 换成服务端返回的全部(带「用过几次」), 新建面板的下拉跟着更新 */
async function mdSave(fields,id){
  const d=await postJSON("/api/endpoints",Object.assign({},fields,id?{id}:{}));
  if(!d.ok)return{ok:false,error:d.error||"保存失败"};
  EPS=Array.isArray(d.endpoints)?d.endpoints:EPS;EPS_ST.loaded=true;renderEpSelects();
  return{ok:true,ep:d.endpoint};
}
/* 记下「一键填入」的时间(列表里的「最近使用」) */
function mdTouch(id){
  postJSON("/api/endpoint-use",{id}).then(d=>{
    if(!d.ok)return;
    const e=EPS.find(x=>x.id===id);if(e){e.last_used_utc=d.last_used_utc;renderEpSelects()}
  });
}

/* ---------- 新建面板: 「从已保存的模型填入」 ---------- */
/* 下拉里的一项: 名称一行, 模型名和主机一行(名称就是默认的「模型 · 主机」时不重复) */
function epOptionSub(e){
  const d=`${e.model} · ${epHost(e.url)}`;
  return e.name===d||e.name===mdDefaultName(e.model,e.url)?"":d;
}
function renderEpSelects(){
  Object.values(EP_SEL).forEach(id=>{
    const sel=$(id);if(!sel)return;
    sel.innerHTML='<option value="">选择后自动填入 地址 / Key / 模型</option>'+(EPS.length
      ?mdOrder(EPS).map(e=>{const sub=epOptionSub(e);return `<option value="${esc(e.id)}"${sub?` data-sub="${esc(sub)}"`:""}>${esc(e.name)}</option>`}).join("")
      :`<option value="${EP_ADD}">还没有保存的模型，去添加 →</option>`);
    sel.value="";
  });
}
function epFill(page,ep){
  const [b,k,m]=EP_FIELDS[page]||[];
  if(!b)return;
  if(ep.url){$(b).value=ep.url;$(b).dispatchEvent(new Event("input"))}
  $(k).value=ep.api_key||"";
  if(ep.model){$(m).value=ep.model;$(m).dispatchEvent(new Event("input"))}
}
function onEpSelect(page){
  const sel=$(EP_SEL[page]),v=sel.value;
  sel.value="";
  if(v===EP_ADD){  /* 还没有保存的模型: 到模型管理页面, 打开「添加模型」 */
    closeDrawers();
    if(VIEW!=="models"||MD.cur){try{history.pushState(null,"","#models")}catch(e){}showView("models")}
    mdFormDialog("",null);return;
  }
  const ep=EPS.find(x=>x.id===v);if(!ep)return;
  epFill(page,ep);mdTouch(ep.id);
  toast(`已填入「${ep.name}」`,"success");
}
Object.keys(EP_SEL).forEach(page=>{const sel=$(EP_SEL[page]);if(sel)sel.addEventListener("change",()=>onEpSelect(page))});

/* ---------- 路由 ---------- */
function mdShow(id){  /* 切到模型管理页面(showView 调用): 每次进来都重新取一次列表(「用过几次」会变) */
  MD.cur=id||"";MD.fromList=false;MD.focusAfter="";MD.runs.clear();MD.kind="all";
  loadEndpoints();
  mdRender();
}
function mdRoute(sub){  /* 同一页面里 #models ↔ #models/<id>(点链接、后退、前进) */
  const id=MD_ID_RE.test(sub)?sub:"",prev=MD.cur;
  if(id===prev)return;
  MD.fromList=!prev&&!!id;  /* 从列表点进来的: 「← 全部模型」用浏览器后退, 不多出一条历史 */
  MD.focusAfter=id?"detail":prev?"row:"+prev:"";
  MD.cur=id;closeMenus();
  if(id){MD.runs.clear();MD.kind="all"}
  mdRender();
  window.scrollTo(0,0);
}
function mdOpen(id){location.hash="#models/"+id}
function mdBack(){
  if(MD.fromList){MD.fromList=false;history.back();return}
  const prev=MD.cur;
  try{history.replaceState(null,"","#models")}catch(e){}
  MD.cur="";MD.focusAfter="row:"+prev;
  mdRender();window.scrollTo(0,0);
}
function mdRender(){if(VIEW==="models")MD.cur?mdRenderDetail():mdRenderList()}
function mdRefresh(){MD.runs.clear();loadEndpoints();if(MD.cur)mdPaintRuns(true)}

/* ---------- 公共小块 ---------- */
function mdLink(ep){return `<a class="qb-link" href="#models/${esc(ep.id)}">「${esc(ep.name)}」</a>`}
function mdErrorHTML(title,message,what,inline){
  return emptyState(title,message,{iconName:"alert",inline,action:`<button type="button" class="btn btn-secondary" data-md-retry="${what}">${icon("refresh")}重试</button>`});
}
function mdSkRows(n){return `<div class="ts-sk-rows">${'<div class="skeleton" style="height:14px"></div>'.repeat(n)}</div>`}
/* 用它新建: 速度测试 / 能力测试 / 代码生成 / 三个新建面板都填上。菜单在表格里也能完整显示(打开时按按钮位置固定定位) */
function mdUseMenu(ep,where){
  const head=where==="head";
  const item=(t,ic,label)=>`<button type="button" class="menu-item" role="menuitem" data-md-use="${t}" data-id="${esc(ep.id)}">${icon(ic)}${label}</button>`;
  return `<details class="dropdown md-use-dd" data-md-menu="use" data-id="${esc(ep.id)}">
    <summary class="btn ${head?"btn-primary btn-sm":"btn-ghost btn-sm md-act md-use-btn"}" aria-label="用它新建：${esc(ep.name)}" title="用它新建：把地址、Key、模型填进新建面板">${icon("play")}${head?"<span>用它新建</span>":""}${icon("chevron-down","icon-sm")}</summary>
    <div class="dropdown-panel menu" role="menu" aria-label="用它新建">
      ${item("perf","gauge","新建速度测试")}${item("iq","list-checks","新建能力测试")}${item("gen","code","新建生成任务")}
      <div class="menu-sep"></div>${item("all","layers","三个新建面板都填上")}</div></details>`;
}
/* 「测试连接」按钮进行中: 转圈 +「正在连接…」, 用 aria-disabled 禁用(焦点留在按钮上, 键盘用户不会丢位置) */
function mdProbeBtn(b,ep){
  const busy=(mdProbeOf(ep)||{}).st==="busy",use=b.querySelector("use"),sp=b.querySelector("span"),t=busy?"正在连接…":"测试连接";
  b.classList.toggle("is-loading",busy);b.setAttribute("aria-disabled",String(busy));
  if(use)use.setAttribute("href",busy?"#i-loader":"#i-plug");
  if(sp)sp.textContent=t;
  b.title=busy?"正在请求 /v1/models，最多等 10 秒":"测试连接：请求 /v1/models，看现在能不能连上";
  if(!sp)b.setAttribute("aria-label",`${t}：${ep.name}`);
}
function mdPaintAllBtn(){
  const a=MD.all,none=!EPS.length;  /* 还没取到列表、取失败或者一个都没有: 不能点 */
  document.querySelectorAll("[data-md-probe-all]").forEach(b=>{
    const use=b.querySelector("use"),sp=b.querySelector("span");
    b.classList.toggle("is-loading",!!a);b.setAttribute("aria-disabled",String(!!a||none));
    if(use)use.setAttribute("href",a?"#i-loader":"#i-plug");
    if(sp)sp.textContent=a?`正在测试 ${a.done} / ${a.total}…`:"全部测试连接";
    b.title=none?"还没有保存的模型":a?"正在逐个测试连接（同时最多 4 个）":"逐个测试保存的模型能不能连上（同时最多 4 个）";
  });
}

/* ---------- 连接状态(这次打开页面后) ---------- */
/* 这个模型的测试连接结果; 之后改过地址或 Key 的不算 */
function mdProbeOf(ep){const p=ep&&MD.probe.get(ep.id);return p&&p.url===ep.url&&p.key===(ep.api_key||"")?p:null}
function mdClock(ts){const d=new Date(ts);return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`}
function mdConnState(ep){
  const p=mdProbeOf(ep);
  if(!p)return{tone:"neutral",text:"还没检查",icon:"minus"};
  if(p.st==="busy")return{tone:"info",text:"正在连接…",icon:"loader"};
  if(p.st==="ok")return mdHasModel(p.d,ep.model)?{tone:"good",text:"正常 · "+mdLatency(p.d.latency_ms),icon:"check"}
    :{tone:"warn",text:"连得上，但没有这个模型",icon:"alert"};
  return{tone:"bad",text:"连不上 · "+mdFailText(p.d).short,icon:"x"};
}
function mdConnTip(ep){
  const p=mdProbeOf(ep);
  if(!p)return "这次打开页面后还没测试过连接";
  if(p.st==="busy")return "正在请求 /v1/models，最多等 10 秒";
  if(p.st==="ok"){const d=p.d;
    return [`响应 ${mdLatency(d.latency_ms)}`,d.framework?`${d.framework}${d.fw_version?" "+d.fw_version:""}`:"",`服务上有 ${d.count} 个模型`,
      mdHasModel(d,ep.model)?"":`没有「${ep.model}」`,mdClock(p.at)+" 检查"].filter(Boolean).join(" · ")}
  const f=mdFailText(p.d);
  return `${f.long}${f.raw?"\n服务返回："+f.raw:""}\n${mdClock(p.at)} 检查`;
}
function mdConnHTML(ep){
  const s=mdConnState(ep),tip=esc(mdConnTip(ep));
  if(s.tone==="neutral")return `<span class="md-conn" data-md-conn="${esc(ep.id)}" title="${tip}">${icon("minus","icon-sm")}${esc(s.text)}</span>`;
  return `<span class="badge is-${s.tone} md-conn" data-md-conn="${esc(ep.id)}" title="${tip}">${icon(s.icon,s.icon==="loader"?"md-spin":"")}${esc(s.text)}</span>`;
}
async function mdProbe(id,{quiet=false}={}){
  const ep=EPS.find(x=>x.id===id);if(!ep)return;
  const cur=MD.probe.get(id);
  if(cur&&cur.st==="busy"&&cur.url===ep.url&&cur.key===(ep.api_key||""))return cur.done;
  const st={st:"busy",url:ep.url,key:ep.api_key||"",at:Date.now(),d:null};
  MD.probe.set(id,st);mdPaintProbe(id);
  st.done=postJSON("/api/probe",{base:ep.url,api_key:ep.api_key||""}).then(d=>{
    if(MD.probe.get(id)!==st)return;  /* 这期间删掉了, 或者改了地址 / Key 又测了一次 */
    if(!d.ok&&!d.code){MD.probe.delete(id);mdPaintProbe(id);if(!quiet)toast("测试连接没有发出去："+(d.error||"原因不明"),"error");return}
    Object.assign(st,{st:d.ok?"ok":"fail",d,at:Date.now()});
    mdPaintProbe(id);
    if(quiet)return;
    const s=mdConnState(ep);
    toast(`「${ep.name}」`+(s.tone==="good"?`连接正常：响应 ${mdLatency(d.latency_ms)}`:s.tone==="warn"?`连得上，但服务上没有「${ep.model}」`:`连不上：${mdFailText(d).short}`),
      s.tone==="good"?"success":s.tone==="warn"?"warning":"error",3500);
  });
  return st.done;
}
/* 全部测试连接: 按列表顺序逐个测, 同时最多 4 个 */
async function mdProbeAll(){
  if(MD.all||!EPS.length)return;
  const ids=mdOrder(EPS).map(e=>e.id);
  MD.all={done:0,total:ids.length};mdPaintAllBtn();
  let i=0;
  const worker=async()=>{while(i<ids.length){const id=ids[i++];await mdProbe(id,{quiet:true});if(MD.all){MD.all.done++;mdPaintAllBtn()}}};
  await Promise.all(Array.from({length:Math.min(MD_PROBE_CONC,ids.length)},worker));
  const eps=ids.map(id=>EPS.find(x=>x.id===id)).filter(Boolean),st=eps.map(mdConnState);
  const ok=st.filter(s=>s.tone==="good").length,warn=st.filter(s=>s.tone==="warn").length,bad=st.filter(s=>s.tone==="bad").length;
  MD.all=null;mdPaintAllBtn();
  toast(`测完 ${eps.length} 个：${ok} 个正常`+(warn?`，${warn} 个连得上但没有保存的模型`:"")+(bad?`，${bad} 个连不上`:""),bad?"error":warn?"warning":"success",5000);
}
/* 测试连接的结果就地更新: 列表只换这一行的状态格和按钮(焦点不动), 详情换概况和连接信息 */
function mdPaintProbe(id){
  if(VIEW!=="models")return;
  const ep=EPS.find(x=>x.id===id);
  if(!MD.cur){
    const ov=$("mdOv");if(ov)ov.innerHTML=mdListOverview();
    if(!ep)return;
    document.querySelectorAll(`#mdTable [data-md-conn="${CSS.escape(id)}"]`).forEach(x=>{x.outerHTML=mdConnHTML(ep)});
    document.querySelectorAll(`#mdTable [data-md-act="probe"][data-id="${CSS.escape(id)}"]`).forEach(b=>mdProbeBtn(b,ep));
    return;
  }
  if(MD.cur!==id||!ep)return;
  const ov=$("mdDetOv");if(ov)ov.innerHTML=mdDetailOverview(ep);
  const body=$("mdConnBody");
  if(body){
    const had=body.contains(document.activeElement);
    body.innerHTML=mdConnBodyHTML(ep);
    if(had){const b=document.querySelector('#mdHeadActs [data-md-act="probe"]');if(b)b.focus({preventScroll:true})}
  }
  document.querySelectorAll('#mdHeadActs [data-md-act="probe"]').forEach(b=>mdProbeBtn(b,ep));
}

/* ---------- 列表 ---------- */
function mdRenderList(){
  const el=$("modelsBody");if(!el)return;
  mdPaintAllBtn();
  if(!EPS_ST.loaded){
    el.innerHTML=EPS_ST.err?mdErrorHTML("没能加载模型列表",EPS_ST.err,"list"):tsSkOv()+
      `<div class="sec"><div class="skeleton" style="height:14px;width:22%"></div>${mdSkRows(4)}</div>`;
    buildJump("modelsJump",null);return;
  }
  if(!EPS.length){el.innerHTML=mdEmptyHTML();buildJump("modelsJump",null);mdFocusAfter();return}
  if(MD.flash&&MD.q&&!mdRows().some(e=>e.id===MD.flash))MD.q="";  /* 刚保存的那一行被搜索条件挡住了: 清掉搜索 */
  const a=document.activeElement,typing=a&&a.id==="mdSearch"?a.selectionStart:null;  /* 列表刷新时正在搜索: 焦点和光标留在搜索框 */
  el.innerHTML=`<div id="mdOv">${mdListOverview()}</div>`+panel({id:"md-list",title:"全部模型",jump:"模型列表",
    desc:"点一行看详情。「连接状态」是这次打开页面后测试连接的结果；「在测试里用过」按服务地址和模型名称对上历史测试",
    tools:`<label class="qb-search md-search">${icon("search")}<input class="input" id="mdSearch" type="search" placeholder="搜索名称、模型名、服务地址" value="${esc(MD.q)}" aria-label="搜索名称、模型名、服务地址" autocomplete="off"></label>`,
    tables:[`<div id="mdTable">${mdTableHTML()}</div>`]});
  buildJump("modelsJump",el);
  if(typing!=null){const s=$("mdSearch");if(s){s.focus({preventScroll:true});try{s.setSelectionRange(typing,typing)}catch(e){}}}
  mdFlashRow();
  mdFocusAfter();
}
function mdEmptyHTML(){
  return `<div class="empty ts-empty md-empty">${icon("sliders")}<div class="empty-title">还没有保存的模型</div>
    <div class="empty-desc">把常用的模型服务（服务地址、API Key、模型名称）存在这里，新建速度测试、能力测试、代码生成时一键填入，不用每次复制粘贴。</div>
    <ol class="ts-steps"><li><b>添加模型</b><span>填服务地址和 Key</span></li><li><b>测试连接</b><span>从服务上的模型里点选</span></li><li><b>一键填入</b><span>在新建测试里选它</span></li></ol>
    <div class="ts-empty-acts"><button type="button" class="btn btn-primary" data-md-add>${icon("plus")}<span>添加模型</span></button></div></div>`;
}
function mdListOverview(){
  const L=EPS,n=L.length,withKey=L.filter(e=>e.api_key).length;
  const st=L.map(e=>[e,mdConnState(e)]),done=st.filter(([,s])=>s.tone!=="neutral"&&s.tone!=="info");
  const good=done.filter(([,s])=>s.tone==="good"),warn=done.filter(([,s])=>s.tone==="warn"),bad=done.filter(([,s])=>s.tone==="bad");
  const busy=st.filter(([,s])=>s.tone==="info").length;
  const last=mdOrder(L).find(e=>mdLastUse(e));
  const most=[...L].filter(e=>mdUses(e).total).sort((a,b)=>mdUses(b).total-mdUses(a).total)[0];
  const U=L.reduce((t,e)=>{const u=mdUses(e);t.perf+=u.perf;t.iq+=u.iq;t.gen+=u.gen;t.total+=u.total;return t},{perf:0,iq:0,gen:0,total:0});
  const uText=u=>`速度 ${fmtInt(u.perf)} · 能力 ${fmtInt(u.iq)} · 代码生成 ${fmtInt(u.gen)}`;
  const concl=[{tone:"info",html:`保存了 <b>${fmtInt(n)}</b> 个模型${withKey?`，其中 ${fmtInt(withKey)} 个带 API Key`:"，都没有 API Key"}。`},
    last?{tone:"info",html:`最近用的是 ${mdLink(last)}（${esc(tsAgo(mdLastUse(last)))}）。`}
      :{tone:"info",html:"还没有用过：在列表里点 ▶「用它新建」，或者在新建测试面板里选「从已保存的模型填入」。"},
    !done.length?{tone:"info",html:busy?`正在测试连接（${busy} 个）…`:"这次打开页面后还没测试过连接：点「全部测试连接」看看它们现在能不能连上（只请求模型列表，不会发起测试）。"}
      :{tone:bad.length?"bad":warn.length?"warn":"good",html:`这次打开页面后测过 <b>${fmtInt(done.length)}</b> 个：<b>${fmtInt(good.length)}</b> 个正常`+
        (warn.length?`，<b>${fmtInt(warn.length)}</b> 个连得上但服务上没有保存的模型（${warn.slice(0,3).map(([e])=>mdLink(e)).join("、")}）`:"")+
        (bad.length?`，<b>${fmtInt(bad.length)}</b> 个连不上：${bad.slice(0,3).map(([e,s])=>`${mdLink(e)}（${esc(s.text.replace(/^连不上 · /,""))}）`).join("、")}${bad.length>3?" 等":""}`:"")+
        (busy?`；还有 ${busy} 个正在测`:"")+"。"},
    most?{tone:"info",html:`用得最多的是 ${mdLink(most)}：在测试里用过 <b>${fmtInt(mdUses(most).total)}</b> 次（${uText(mdUses(most))}）。`}
      :{tone:"info",html:"保存的模型还没在测试里用过（按服务地址和模型名称对上历史测试）。"}];
  const stats=stat("保存的模型",fmtInt(n),"个",{sub:`带 API Key 的 ${fmtInt(withKey)} 个`})+
    stat("连接正常",done.length?fmtInt(good.length):"—","个",{sub:done.length?`这次测过 ${fmtInt(done.length)} 个`:"这次还没测过",tip:"这次打开页面后测试连接的结果"})+
    stat("连不上",done.length?fmtInt(bad.length):"—","个",{sub:bad.length?`<span class="bad">${esc(bad.slice(0,2).map(([e])=>e.name).join("、"))}${bad.length>2?" 等":""}</span>`:done.length?"没有":"这次还没测过"})+
    stat("在测试里用过",fmtInt(U.total),"次",{sub:uText(U),tip:"按服务地址和模型名称对上历史测试"});
  return overview(concl,stats,{title:"概况"});
}
function mdRows(){
  const q=MD.q.trim().toLowerCase(),rows=mdOrder(EPS);
  return q?rows.filter(e=>[e.name,e.model,e.url].some(s=>String(s||"").toLowerCase().includes(q))):rows;  /* 不搜 Key */
}
function mdListSpec(list){
  const rows=list.map(e=>Object.assign({_cls:"is-link"},e)),q=MD.q.trim();
  return{id:"md-list-t",title:`保存的模型 <span class="dt-sub">${q?`找到 ${fmtInt(rows.length)} / ${fmtInt(EPS.length)} 个`:`${fmtInt(EPS.length)} 个`}</span>`,
    exportName:"模型列表",search:false,pageSize:20,pageSizes:[10,20,50,100],rowKey:e=>e.id,rows,empty:"没有模型",
    note:"默认按最近使用排序",
    columns:[
      {key:"name",label:"名称",type:"html",sticky:true,sortValue:e=>e.name,text:(v,e)=>e.name,
        get:e=>`<a class="ts-name-link md-name-link" href="#models/${esc(e.id)}" title="${esc(e.name)}">${esc(e.name)}</a>`},
      {key:"model",label:"模型名",type:"html",sortValue:e=>e.model,text:(v,e)=>e.model,
        get:e=>`<span class="dt-ellipsis md-model" title="${esc(e.model)}">${esc(e.model)}</span>`},
      {key:"host",label:"服务地址",type:"html",sortValue:e=>epHost(e.url),text:(v,e)=>e.url,tip:"只显示主机和端口，鼠标放上去看完整地址",
        get:e=>`<span class="dt-ellipsis md-host" title="${esc(e.url)}">${esc(epHost(e.url))}</span>`},
      {key:"key",label:"API Key",type:"html",sortValue:e=>e.api_key?1:0,text:(v,e)=>e.api_key?maskKey(e.api_key):"没有",
        tip:"只显示遮住的形式；完整的 Key 在「编辑」里点眼睛才看得到",
        get:e=>e.api_key?`<span class="mono md-key">${esc(maskKey(e.api_key))}</span>`:`<span class="faint">没有</span>`},
      {key:"conn",label:"连接状态",type:"status",tip:"这次打开页面后测试连接的结果",get:e=>mdConnState(e),fmt:(v,e)=>mdConnHTML(e)},
      {key:"last",label:"最近使用",type:"html",tip:"最近一次一键填入、或者用它跑测试的时间",sortValue:e=>mdTime(mdLastUse(e)),
        text:(v,e)=>mdLastUse(e)?timeText(mdLastUse(e)):"还没用过",
        get:e=>{const t=mdLastUse(e);return t?`<span title="${esc(timeText(t))}">${esc(tsAgo(t))}</span>`:`<span class="faint">还没用过</span>`}},
      ...Object.entries(MD_KIND).map(([k,m])=>({key:"u_"+k,label:m.short,group:"在测试里用过（次）",type:"int",get:e=>mdUses(e)[k],
        tip:`用它跑过几次${m.name}（按服务地址和模型名称对上历史测试）`,fmt:v=>v?numText(v,0):`<span class="faint">0</span>`})),
      {key:"act",label:"操作",type:"html",noSort:true,get:mdActionsHTML,text:()=>""}]};
}
function mdActionsHTML(e){
  const b=(act,ic,label,cls="",tip=label,attrs="")=>`<button type="button" class="btn btn-ghost btn-icon btn-sm md-act${cls}" data-md-act="${act}" data-id="${esc(e.id)}" title="${esc(tip)}" aria-label="${esc(label)}：${esc(e.name)}"${attrs}>${icon(ic)}</button>`;
  /* 正在测试连接的这一行: 排序、翻页、搜索把表格重画时也保持「正在连接…」(与 mdProbeBtn 就地更新的结果一样) */
  const busy=(mdProbeOf(e)||{}).st==="busy";
  const probe=busy?b("probe","loader","正在连接…"," is-loading","正在请求 /v1/models，最多等 10 秒",' aria-disabled="true"'):b("probe","plug","测试连接");
  return `<span class="dt-actions">${probe}${mdUseMenu(e,"row")}${b("edit","pencil","编辑")}${b("delete","trash","删除"," md-act-del")}</span>`;
}
function mdTableHTML(){
  const rows=mdRows();
  if(!rows.length)return emptyState("没有符合条件的模型",`没有找到「${MD.q.trim()}」：搜索的是名称、模型名和服务地址`,
    {iconName:"search",inline:true,action:`<button type="button" class="btn btn-secondary" data-md-clear>${icon("x")}清除搜索</button>`});
  const spec=mdListSpec(rows);
  if(MD.flash){  /* 刚保存的那一行: 翻到它所在的那一页 */
    const i=dtRows(spec).findIndex(e=>e.id===MD.flash),st=dtState(spec.id);
    if(i>=0)st.page=Math.floor(i/dtPageSize(spec,st));
  }
  return dataTable(spec);
}
function mdPaintTable(){
  const box=$("mdTable");if(!box)return;
  box.innerHTML=mdTableHTML();
  EPS.forEach(ep=>{const b=box.querySelector(`[data-md-act="probe"][data-id="${CSS.escape(ep.id)}"]`);if(b)mdProbeBtn(b,ep)});
}
/* 刚添加或刚改过的那一行短暂高亮 */
function mdFlashRow(){
  const id=MD.flash;if(!id)return;
  MD.flash="";
  const tr=document.querySelector(`[data-dt="md-list-t"] tr[data-rk="${CSS.escape(id)}"]`);if(!tr)return;
  tr.classList.add("is-flash");
  const r=tr.getBoundingClientRect();
  if(r.bottom>innerHeight-8||r.top<120)tr.scrollIntoView({block:"nearest"});
  setTimeout(()=>tr.classList.remove("is-flash"),1600);
}
/* 页面切换后焦点放到合适的地方: 进详情放到名称上, 回列表放回刚才那一行, 删完最后一个放到「添加模型」 */
function mdFocusAfter(){
  const f=MD.focusAfter;if(!f)return;
  const a=document.activeElement;
  if(a&&a!==document.body&&!$("modelsBody").contains(a)&&!a.closest(".nav")&&!a.closest("#viewModels .pagehead"))return;  /* 焦点在别处, 不去抢 */
  MD.focusAfter="";
  const el=f==="detail"?$("mdNameH"):f==="add"?$("mdAddBtn"):f.startsWith("row:")?document.querySelector(`[data-dt="md-list-t"] tr[data-rk="${CSS.escape(f.slice(4))}"] .md-name-link`):null;
  if(el)el.focus({preventScroll:true});
}

/* ---------- 详情 ---------- */
function mdRenderDetail(){
  const el=$("modelsBody"),id=MD.cur;if(!el)return;
  mdPaintAllBtn();MD.flash="";
  const back=`<button type="button" class="btn btn-ghost btn-sm ts-back" data-md-back>${icon("arrow-left")}全部模型</button>`;
  if(!EPS_ST.loaded){
    el.innerHTML=`<div class="ts-head">${back}</div>`+(EPS_ST.err?mdErrorHTML("没能加载这个模型",EPS_ST.err,"list"):
      `<div class="skeleton" style="height:24px;width:34%"></div><div class="skeleton" style="height:12px;width:46%;margin:10px 0 20px"></div>`+tsSkOv()+
      `<div class="sec"><div class="skeleton" style="height:14px;width:18%"></div>${mdSkRows(3)}</div>`);
    buildJump("modelsJump",null);return;
  }
  const ep=EPS.find(x=>x.id===id);
  if(!ep){
    el.innerHTML=`<div class="ts-head">${back}</div>`+emptyState("这个模型不存在","可能已经被删除了。已经填到新建面板里的内容和过去的测试结果都不受影响",
      {iconName:"inbox",action:`<button type="button" class="btn btn-secondary" data-md-back>${icon("arrow-left")}回到全部模型</button>`});
    buildJump("modelsJump",null);return;
  }
  el.innerHTML=mdDetailHead(ep,back)+`<div id="mdDetOv">${mdDetailOverview(ep)}</div>`+mdConnSec(ep)+mdRunsSec(ep);
  document.querySelectorAll('#mdHeadActs [data-md-act="probe"]').forEach(b=>mdProbeBtn(b,ep));
  if(!MD.runs.has(mdRunsKey()))mdLoadRuns();
  buildJump("modelsJump",el);
  mdFocusAfter();
}
function mdDetailHead(ep,back){
  /* 每一段包在 span 里: 外面是 flex, 不包的话「模型」和后面的值之间的空格会被吃掉 */
  const meta=[`<span>模型 <span class="mono" title="${esc(ep.model)}">${esc(ep.model)}</span></span>`,`<span class="md-url">地址 <span class="mono">${esc(ep.url)}</span></span>`,
    ep.api_key?`<span>API Key <span class="mono" title="只显示遮住的形式；完整的 Key 在「编辑」里点眼睛才看得到">${esc(maskKey(ep.api_key))}</span></span>`:"<span>没有 API Key</span>",
    ep.created_utc?`<span>添加于 ${esc(timeText(ep.created_utc))}</span>`:""].filter(Boolean);
  return `<div class="ts-head">${back}
    <div class="ts-head-main">
      <div class="ts-title" id="mdTitle">${mdTitleHTML(ep)}</div>
      <div class="ts-actions" id="mdHeadActs">
        <button type="button" class="btn btn-secondary btn-sm" data-md-act="probe" data-id="${esc(ep.id)}">${icon("plug")}<span>测试连接</span></button>
        ${mdUseMenu(ep,"head")}
        <details class="dropdown more ts-more" data-md-menu="more" data-id="${esc(ep.id)}"><summary class="btn btn-ghost btn-icon btn-sm" aria-label="更多操作" title="更多操作">${icon("more")}</summary>
          <div class="dropdown-panel menu is-right" role="menu">
            <button class="menu-item" type="button" role="menuitem" data-md-act="edit" data-id="${esc(ep.id)}">${icon("pencil")}编辑地址、Key、模型</button>
            <button class="menu-item is-danger" type="button" role="menuitem" data-md-act="delete" data-id="${esc(ep.id)}">${icon("trash")}删除这个模型</button>
          </div></details>
      </div>
    </div>
    <div class="ts-meta">${meta.join('<span class="ts-dot" aria-hidden="true">·</span>')}</div>
  </div>`;
}
function mdTitleHTML(ep){
  return `<h2 class="ts-name" id="mdNameH" tabindex="-1" title="${esc(ep.name)}">${esc(ep.name)}</h2>
    <button type="button" class="btn btn-ghost btn-icon btn-sm ts-edit" data-md-rename aria-label="改名：${esc(ep.name)}" title="改名（回车保存，Esc 取消）">${icon("pencil")}</button>`;
}
function mdDetailOverview(ep){
  const p=mdProbeOf(ep),s=mdConnState(ep),u=mdUses(ep),d=p&&p.d;
  const fwText=d&&d.framework?`${d.framework}${d.fw_version?" "+d.fw_version:""}`:"";
  let conn;
  if(!p)conn={tone:"info",html:"这次打开页面后还没测试过连接：点「测试连接」看看现在能不能连上（只请求模型列表，不会发起测试）。"};
  else if(p.st==="busy")conn={tone:"info",html:"正在测试连接…"};
  else if(p.st==="ok"){
    const mine=(d.models||[]).find(m=>m.id===ep.model);
    conn=mine?{tone:"good",html:`连接正常：响应 <b>${esc(mdLatency(d.latency_ms))}</b>${fwText?`，${esc(fwText)}`:""}；服务上有 ${fmtInt(d.count)} 个模型，保存的「${esc(ep.model)}」在里面（${esc(mdCtxText(mine.max_model_len))}）。`}
      :{tone:"warn",html:`连得上（响应 ${esc(mdLatency(d.latency_ms))}），但服务上没有「${esc(ep.model)}」这个模型：可能写错了（区分大小写），或者服务换了模型。服务上现在是 ${(d.models||[]).slice(0,4).map(m=>`「${esc(m.id)}」`).join("、")||"空的"}${d.count>4?" 等":""}。`};
  }else{const f=mdFailText(d);conn={tone:"bad",html:`连不上：<b>${esc(f.short)}</b>——${esc(f.long)}。`}}
  const concl=[conn,
    u.total?{tone:"info",html:`在测试里用过 <b>${fmtInt(u.total)}</b> 次：速度测试 ${fmtInt(u.perf)} 次、能力测试 ${fmtInt(u.iq)} 次、代码生成 ${fmtInt(u.gen)} 次；最近一次是 ${esc(timeText(u.last_utc))}。`}
      :{tone:"info",html:"还没有用它跑过测试（按服务地址和模型名称对上历史测试）。点「用它新建」就能把地址、Key、模型填进新建面板。"},
    ep.last_used_utc?{tone:"info",html:`最近一次一键填入是 ${esc(tsAgo(ep.last_used_utc))}（${esc(timeText(ep.last_used_utc))}）。`}
      :{tone:"info",html:"还没有一键填入过。"}];
  const stats=stat("连接",p&&p.st==="ok"?(s.tone==="good"?"正常":"缺模型"):p&&p.st==="fail"?"连不上":p?"测试中":"—","",
      {sub:p&&p.st==="ok"?`响应 ${esc(mdLatency(d.latency_ms))} · ${esc(mdClock(p.at))} 检查`:p&&p.st==="fail"?esc(mdFailText(d).short):"这次还没测过",tip:"这次打开页面后测试连接的结果"})+
    stat("框架与版本",fwText?esc(fwText):"—","",{sub:p&&p.st==="ok"?(fwText?"从 /version 或 /metrics 认出来的":"认不出框架（不是 vLLM，或服务没开放）"):"测试连接后显示"})+
    stat("服务上的模型",p&&p.st==="ok"?fmtInt(d.count):"—","个",{sub:p&&p.st==="ok"?(mdHasModel(d,ep.model)?"包含保存的模型":`<span class="warn">没有「${esc(ep.model)}」</span>`):"测试连接后显示"})+
    stat("在测试里用过",fmtInt(u.total),"次",{sub:`速度 ${fmtInt(u.perf)} · 能力 ${fmtInt(u.iq)} · 代码生成 ${fmtInt(u.gen)}`});
  return overview(concl,stats,{title:"概况"});
}
function mdConnSec(ep){
  return `<section class="sec" id="md-conn" data-jump="连接信息"><div class="sec-head"><div class="sec-head-text"><h2 class="sec-title">连接信息</h2>
    <p class="sec-desc">这次打开页面后测试连接的结果：请求服务的 /v1/models（最多等 10 秒），再从 /version、/metrics 认框架和版本，都带上保存的 Key；不会发起测试</p></div></div>
    <div id="mdConnBody">${mdConnBodyHTML(ep)}</div></section>`;
}
function mdConnBodyHTML(ep){
  const p=mdProbeOf(ep),btn=(label,ic)=>`<button type="button" class="btn btn-secondary btn-sm" data-md-act="probe" data-id="${esc(ep.id)}">${icon(ic)}<span>${label}</span></button>`;
  if(!p)return emptyState("还没测试连接","点「测试连接」看看现在能不能连上，顺便列出服务上有哪些模型、每个的最大上下文",
    {iconName:"plug",inline:true,action:btn("测试连接","plug")});
  if(p.st==="busy")return `<div class="md-conn-meta" role="status"><span class="badge is-info">${icon("loader","md-spin")}正在连接…</span><span class="faint">最多等 10 秒</span></div>${mdSkRows(3)}`;
  if(p.st==="fail"){
    const f=mdFailText(p.d);
    return alertBox("bad",`<b>连不上：${esc(f.short)}</b><div>${esc(f.long)}</div>${f.raw?`<div class="md-raw">服务返回：<span class="mono">${esc(f.raw)}</span></div>`:""}<div class="md-raw">${esc(mdClock(p.at))} 检查</div>`,btn("再试一次","refresh"));
  }
  const d=p.d,has=mdHasModel(d,ep.model);
  const warn=has?"":alertBox("warn",`服务上没有「${esc(ep.model)}」这个模型：可能写错了（区分大小写），或者服务换了模型。${d.models&&d.models.length?"可以在下面的列表里点「改用这个」。":""}`);
  const meta=`<div class="md-conn-meta">${[`<span class="badge is-good">${icon("check")}连接正常</span>`,`<span>响应 <b>${esc(mdLatency(d.latency_ms))}</b></span>`,
    `<span>${d.framework?`框架 <b>${esc(d.framework)}${d.fw_version?" "+esc(d.fw_version):""}</b>`:"认不出框架"}</span>`,`<span>服务上有 <b>${fmtInt(d.count)}</b> 个模型</span>`,`<span>${esc(mdClock(p.at))} 检查</span>`]
    .join('<span class="ts-dot" aria-hidden="true">·</span>')}${btn("再测一次","refresh")}</div>`;
  return warn+meta+(d.models&&d.models.length?dataTable(mdModelsSpec(ep,d)):emptyState("服务上没有模型","/v1/models 返回的是空列表",{inline:true}));
}
function mdModelsSpec(ep,d){
  const rows=(d.models||[]).map(m=>({id:m.id,max_model_len:m.max_model_len,_cls:m.id===ep.model?"md-cur":""}));
  return{id:"md-models-t",title:`服务上的模型 <span class="dt-sub">${fmtInt(rows.length)} 个</span>`,exportName:"服务上的模型",search:rows.length>12,pageSize:50,rowKey:m=>m.id,rows,
    columns:[
      {key:"id",label:"模型名称",type:"html",sticky:true,sortValue:m=>m.id,text:(v,m)=>m.id,
        get:m=>`<span class="mono">${esc(m.id)}</span>${m.id===ep.model?` <span class="badge is-good" title="保存的就是这个模型">${icon("check")}当前保存的</span>`:""}`},
      {key:"max_model_len",label:"最大上下文",unit:"token",type:"int",tip:"服务允许的最长输入加输出（max_model_len）；服务没给时为空"},
      {key:"act",label:"操作",type:"html",noSort:true,text:()=>"",
        get:m=>m.id===ep.model?`<span class="faint">正在用</span>`:`<button type="button" class="btn btn-ghost btn-sm" data-md-switch="${esc(m.id)}" title="把保存的模型名称改成「${esc(m.id)}」">改用这个</button>`}]};
}
function mdRunsKey(){return MD.cur+"|"+MD.kind}
function mdRunsSec(ep){
  return `<section class="sec" id="md-runs" data-jump="用过的测试"><div class="sec-head"><div class="sec-head-text"><h2 class="sec-title">最近用它跑过的测试</h2>
    <p class="sec-desc">按服务地址和模型名称对上历史测试（地址写法不同但指向同一个服务的也算），新的在前，最多列 50 次；点一行到结果页看那次测试</p></div>
    <div class="sec-tools" id="mdRunsSeg">${mdRunsSegHTML(ep)}</div></div>
    <div id="mdRunsBody">${mdRunsBodyHTML()}</div></section>`;
}
function mdRunsSegHTML(ep){
  const ent=MD.runs.get(MD.cur+"|all"),c=(ent&&ent.d&&ent.d.counts)||mdUses(ep),total=(c.perf||0)+(c.iq||0)+(c.gen||0);
  return `<span class="seg" role="group" aria-label="按类型筛选">${[["all","全部",total],["perf","速度",c.perf],["iq","能力",c.iq],["gen","代码生成",c.gen]]
    .map(([k,label,n])=>`<button type="button" class="seg-btn" data-md-kind="${k}" aria-pressed="${k===MD.kind}">${label} <b class="md-seg-n">${fmtInt(n||0)}</b></button>`).join("")}</span>`;
}
function mdLoadRuns(){
  const id=MD.cur,kind=MD.kind,k=id+"|"+kind;if(!id)return;
  const ent={loading:true,d:null,err:""};MD.runs.set(k,ent);
  tsApi(`/api/endpoint-runs?id=${encodeURIComponent(id)}&kind=${encodeURIComponent(kind)}`)
    .then(d=>{ent.d=d}).catch(e=>{ent.err=e.message})
    .finally(()=>{ent.loading=false;if(VIEW==="models"&&MD.cur===id&&MD.kind===kind)mdPaintRuns()});
}
function mdPaintRuns(reload){
  if(reload&&MD.cur&&!MD.runs.has(mdRunsKey()))mdLoadRuns();
  const body=$("mdRunsBody"),seg=$("mdRunsSeg"),ep=EPS.find(x=>x.id===MD.cur);if(!body)return;
  const k=document.activeElement&&document.activeElement.closest&&document.activeElement.closest("#mdRunsSeg [data-md-kind]");
  if(seg&&ep){seg.innerHTML=mdRunsSegHTML(ep);if(k){const b=seg.querySelector(`[data-md-kind="${MD.kind}"]`);if(b)b.focus({preventScroll:true})}}
  body.innerHTML=mdRunsBodyHTML();
}
function mdRunsBodyHTML(){
  const ent=MD.runs.get(mdRunsKey()),ep=EPS.find(x=>x.id===MD.cur);
  if(!ent||ent.loading)return `<div aria-busy="true">${mdSkRows(4)}</div>`;
  if(ent.err)return mdErrorHTML("没能加载用过的测试",ent.err,"runs",true);
  const d=ent.d,kindName=MD.kind==="all"?"测试":MD_KIND[MD.kind].name;
  if(!d.runs.length)return emptyState(`还没有用它跑过${kindName}`,"按服务地址和模型名称对上历史测试：速度测试、能力测试、代码生成都算",
    {iconName:"inbox",inline:true,action:ep?`<button type="button" class="btn btn-secondary" data-md-use="${MD.kind==="all"?"perf":MD.kind}" data-id="${esc(ep.id)}">${icon("play")}用它${MD.kind==="all"?"新建速度测试":MD_KIND[MD.kind].new}</button>`:""});
  return dataTable(mdRunsSpec(d));
}
function mdRunsSpec(d){
  const rows=d.runs.map(r=>Object.assign({_cls:"is-link"},r));
  return{id:"md-runs-t",title:`用过的测试 <span class="dt-sub">${d.matched>rows.length?`最近 ${fmtInt(rows.length)} 次（一共 ${fmtInt(d.matched)} 次）`:`${fmtInt(rows.length)} 次`}</span>`,
    exportName:"用过的测试",search:false,pageSize:20,pageSizes:[10,20,50],rowKey:r=>r.run_id,rows,
    columns:[
      {key:"kind",label:"类型",type:"html",sticky:true,sortValue:r=>r.kind,text:(v,r)=>MD_KIND[r.kind].name,
        get:r=>`<a class="md-run-link" href="#${MD_KIND[r.kind].view}" data-md-run="${esc(r.run_id)}" data-kind="${esc(r.kind)}" title="到${MD_KIND[r.kind].name}页看这次测试">${icon(MD_KIND[r.kind].icon,"icon-sm")}${MD_KIND[r.kind].name}</a>`},
      {key:"started_utc",label:"开始时间",type:"text",get:r=>timeText(r.started_utc),sortValue:r=>mdTime(r.started_utc)},
      {key:"sum",label:"结果",type:"text",wrap:true,get:r=>mdRunSummary(r)},
      {key:"setting",label:"设置",type:"text",get:r=>mdRunSetting(r),tip:"速度测试的规模；能力测试和代码生成是否让模型先思考"},
      {key:"status",label:"状态",type:"status",get:r=>mdRunStatus(r)},
      {key:"fw",label:"框架",type:"text",get:r=>[r.framework,r.fw_version].filter(Boolean).join(" ")||"—"},
      {key:"tag",label:"备注标签",type:"text",get:r=>r.tag||"—"}]};
}
function mdSetKind(kind){
  if(!["all","perf","iq","gen"].includes(kind)||kind===MD.kind)return;
  MD.kind=kind;
  document.querySelectorAll("#mdRunsSeg [data-md-kind]").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.mdKind===kind)));
  const ent=MD.runs.get(mdRunsKey());
  if(ent&&!ent.err){mdPaintRuns();return}
  mdLoadRuns();
  const k=kind;setTimeout(()=>{const e=MD.runs.get(MD.cur+"|"+k);if(MD.kind===k&&e&&e.loading)mdPaintRuns()},150);  /* 慢的时候才换成骨架, 不闪 */
}
/* 到结果页看某次测试(「用过的测试」里的一行): 选中它, 浏览器后退回到这里 */
async function mdOpenRun(kind,id){
  const k=MD_KIND[kind];if(!k)return;
  if(kind==="perf"){
    if(!RUNS[id])await refresh();
    if(!RUNS[id]){toast("这次测试已经不在了（可能被删除）","warning");return}
    $("runA").value=id;
  }else{  /* 能力测试 / 代码生成的列表切页面时才取: 先放一个选项进去, 取回列表后会保留这个选择 */
    const sel=$(k.sel);
    if(![...sel.options].some(o=>o.value===id)){const o=document.createElement("option");o.value=id;o.textContent=id;sel.appendChild(o)}
    sel.value=id;
  }
  location.hash="#"+k.view;
}

/* ---------- 操作 ---------- */
/* 用它新建: 切到对应页面、打开新建面板、填好地址 / Key / 模型, 这几栏短暂高亮; 「三个新建面板都填上」只填不跳 */
function mdUse(id,target){
  const ep=EPS.find(x=>x.id===id);if(!ep)return;
  mdTouch(id);
  if(target==="all"){
    Object.keys(EP_FIELDS).forEach(p=>epFill(p,ep));
    toast(`已把「${ep.name}」填进速度测试、能力测试、代码生成三个新建面板`,"success",3500);return;
  }
  const k=MD_KIND[target];if(!k)return;
  if(VIEW!==k.view){try{history.pushState(null,"","#"+k.view)}catch(e){}showView(k.view)}  /* 浏览器后退回到模型管理 */
  epFill(target,ep);
  toggleLauncher(k.launcher,true);  /* 打开时会重算面板底部的「这次将测」 */
  const grid=$(EP_FIELDS[target][0]).closest(".form-grid");
  requestAnimationFrame(()=>{
    if(!grid)return;
    grid.scrollIntoView({block:"nearest",behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth"});
    grid.classList.remove("is-flash");void grid.offsetWidth;grid.classList.add("is-flash");
    setTimeout(()=>grid.classList.remove("is-flash"),1800);
    $(EP_FIELDS[target][0]).focus({preventScroll:true});
  });
  toast(`已在「${k.new}」里填好「${ep.name}」的服务地址、Key 和模型`,"success",3500);
}
async function mdDelete(id){
  const ep=EPS.find(x=>x.id===id);if(!ep)return;
  const u=mdUses(ep);
  const ok=await confirmDialog({title:"删除模型",confirmText:"删除",danger:true,
    message:`删除「${ep.name}」？\n\n已经填到新建面板里的内容和过去的测试结果都不受影响，只是以后不能再一键填入它。`+
      (u.total?`\n用它跑过的 ${u.total} 次测试会留着。`:"")+"\n删除后不能恢复。"});
  if(!ok)return;
  const d=await postJSON("/api/endpoint-delete",{id});
  if(!d.ok&&!/不存在/.test(d.error||"")){toast("删除失败："+(d.error||"原因不明"),"error");return}
  toast(`已删除「${ep.name}」`,"success",3000);
  const L=mdOrder(EPS),i=L.findIndex(x=>x.id===id),next=L[i+1]||L[i-1];
  EPS=EPS.filter(x=>x.id!==id);MD.probe.delete(id);renderEpSelects();
  if(MD.cur===id){MD.cur="";MD.fromList=false;try{history.replaceState(null,"","#models")}catch(e){}}
  MD.focusAfter=next?"row:"+next.id:"add";
  mdRender();  /* 列表就地更新, 不整页刷新 */
}
/* 「服务上的模型」里点「改用这个」: 把保存的模型名称改成这一个 */
async function mdSwitchModel(model){
  const ep=EPS.find(x=>x.id===MD.cur);if(!ep||!model||model===ep.model)return;
  const r=await mdSave({name:ep.name===mdDefaultName(ep.model,ep.url)?"":ep.name,url:ep.url,api_key:ep.api_key||"",model},ep.id);
  if(!r.ok){toast("没有改成："+r.error,"error");return}
  toast(`已改用「${model}」`,"success",2500);
  mdRender();
}
/* 详情页头: 点名称旁的笔原地改名; 回车保存, Esc 取消, 空名或超长当场提示 */
function mdInlineRename(){
  const ep=EPS.find(x=>x.id===MD.cur),box=$("mdTitle");if(!ep||!box)return;
  box.innerHTML=`<form class="ts-rename-inline" id="mdInline" novalidate>
    <input class="input ts-name-input" id="mdInlineInput" autocomplete="off" spellcheck="false" aria-label="名称" aria-describedby="mdInlineHelp">
    <button type="submit" class="btn btn-primary btn-sm" id="mdInlineSave" disabled>保存</button>
    <button type="button" class="btn btn-ghost btn-sm" data-md-inline-cancel>取消</button>
    <div class="ts-name-help" id="mdInlineHelp" aria-live="polite">回车保存，Esc 取消</div></form>`;
  const inp=$("mdInlineInput"),help=$("mdInlineHelp"),save=$("mdInlineSave");
  inp.value=ep.name;
  const cancel=()=>{box.innerHTML=mdTitleHTML(ep);const b=box.querySelector("[data-md-rename]");if(b)b.focus()};
  const check=()=>{const c=mdNameCheck(inp.value),same=c.ok&&c.name===ep.name;
    save.disabled=!c.ok||same;inp.setAttribute("aria-invalid",String(!c.ok));
    help.classList.toggle("is-error",!c.ok);help.textContent=c.ok?(same?"名称没有改动；Esc 取消":`${c.n} / ${MD_NAME_MAX} 个字；回车保存，Esc 取消`):c.error;return c};
  inp.addEventListener("input",check);
  inp.addEventListener("keydown",e=>{if(e.key==="Escape"){e.preventDefault();e.stopPropagation();cancel()}});
  box.querySelector("[data-md-inline-cancel]").addEventListener("click",cancel);
  $("mdInline").addEventListener("submit",async e=>{
    e.preventDefault();const c=check();
    if(!c.ok){inp.focus();return}
    if(c.name===ep.name){cancel();return}
    setBusy(save,true);
    const r=await mdSave({name:c.name,url:ep.url,api_key:ep.api_key||"",model:ep.model},ep.id);
    if(!r.ok){setBusy(save,false);help.textContent=r.error;help.classList.add("is-error");inp.focus();return}
    toast(`已改名为「${r.ep.name}」`,"success",2500);
    mdRender();
    const b=document.querySelector("#mdTitle [data-md-rename]");if(b)b.focus({preventScroll:true});
  });
  inp.focus();inp.select();
}
/* 打开弹窗的按钮: 关弹窗时焦点回到它; 它在列表或页头里被重新画过时, 按同样的位置找新的 */
function mdOpenerSel(el){
  if(!el||!el.closest)return "";
  if(el.id)return "#"+CSS.escape(el.id);
  const dd=el.closest("details[data-md-menu]");
  if(dd)return `details[data-md-menu="${dd.dataset.mdMenu}"][data-id="${CSS.escape(dd.dataset.id)}"]>summary`;
  if(el.dataset.mdAct&&el.dataset.id)return `[data-md-act="${el.dataset.mdAct}"][data-id="${CSS.escape(el.dataset.id)}"]`;
  return "";
}
/* 添加 / 编辑: 弹窗。自动聚焦第一个要填的框; 地址粘贴或离开输入框时去掉首尾空格和末尾的 /v1…并提示;
   Key 默认遮住; 「测试连接」列出服务上的模型, 点一下填进「模型名称」; 回车保存, Esc 关闭; 编辑时没改动保存按钮不能点 */
function mdFormDialog(id,opener){
  const ep=id?EPS.find(x=>x.id===id):null;if(id&&!ep)return;
  const back=mdOpenerSel(opener);
  Modal.open(ep?"编辑模型":"添加模型",mdFormHTML(!!ep),{dialog:true});
  Modal.last={focus:()=>{const el=(back&&document.querySelector(back))||$("mdAddBtn");if(el&&el.getClientRects().length)el.focus({preventScroll:true})}};
  const F=MD.form={id:ep?ep.id:"",orig:ep?{url:ep.url,model:ep.model,api_key:ep.api_key||"",name:ep.name}:null,touched:{},tried:false,probe:null,urlCut:"",keyNote:""};
  const ids={url:"mdUrl",key:"mdKey",model:"mdModel",name:"mdName"},el=k=>$(ids[k]);
  if(ep){el("url").value=ep.url;el("key").value=ep.api_key||"";el("model").value=ep.model;el("name").value=ep.name}  /* 用属性赋值, Key 不进元素属性 */
  const save=$("mdFormSave"),formEl=$("mdForm"),alive=()=>$("mdForm")===formEl;   /* 弹窗关掉又打开后, 上一个弹窗里还没回来的请求不能去改新弹窗 */
  const raw=()=>({url:el("url").value,key:el("key").value,model:el("model").value,name:el("name").value});
  const paint=()=>{
    if(!alive())return null;
    const c=mdFormCheck(raw()),pr=F.probe&&F.probe.d&&F.probe.d.ok?F.probe.d:null;
    const dup=c.fields.url&&c.fields.model?EPS.find(x=>x.id!==F.id&&x.model===c.fields.model&&mdUrlKey(x.url)===mdUrlKey(c.fields.url)):null;
    Object.keys(ids).forEach(k=>{
      const h=$(ids[k]+"Help"),err=(F.tried||F.touched[k])&&c.errors[k];
      let text=MD_HELP[k],cls="";
      if(err){text=err;cls="is-error"}
      else if(k==="url"&&(c.notes.url||F.urlCut)){text=c.notes.url||`已去掉末尾的「${F.urlCut}」，测试时会自动加上`;cls="is-note"}
      else if(k==="key"&&(c.notes.key||F.keyNote)){text=c.notes.key||F.keyNote;cls="is-note"}
      else if(k==="name"&&c.nameDefault&&c.fields.name)text=`不填就用「${c.fields.name}」`;
      else if(k==="model"&&c.fields.model&&pr&&!mdHasModel(pr,c.fields.model)){text=`服务上没有「${c.fields.model}」：服务上有 ${pr.models.slice(0,3).map(m=>m.id).join("、")||"（空）"}${pr.models.length>3?" 等":""}`;cls="is-warn"}
      else if(k==="model"&&dup){text=`已经保存过同样的地址和模型：「${dup.name}」（再存一个也可以）`;cls="is-note"}
      h.textContent=text;h.className="help md-help"+(cls?" "+cls:"");
      el(k).setAttribute("aria-invalid",String(!!err));
    });
    const same=!!F.orig&&c.ok&&["url","model","api_key","name"].every(k=>c.fields[k]===F.orig[k]);
    save.disabled=same;
    msg("mdFormMsg",same?"info":"",same?"没有改动":"");
    document.querySelectorAll("#mdFormProbeOut [data-md-pick]").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.mdPick===c.fields.model)));
    return c;
  };
  const tidyUrl=()=>{const i=el("url"),r=mdUrlClean(i.value);if(r.url!==i.value){i.value=r.url;if(r.cut)F.urlCut=r.cut}};
  const tidyKey=()=>{const i=el("key"),v=i.value.trim();if(v!==i.value){i.value=v;if(v)F.keyNote="已去掉首尾的空格或换行"}};
  Object.keys(ids).forEach(k=>{
    el(k).addEventListener("input",()=>{if(k==="url")F.urlCut="";if(k==="key")F.keyNote="";paint()});
    el(k).addEventListener("blur",()=>{if(!alive())return;if(k==="url")tidyUrl();if(k==="key")tidyKey();F.touched[k]=true;paint()});
  });
  el("url").addEventListener("paste",()=>setTimeout(()=>{if(alive()){tidyUrl();paint()}},0));
  el("key").addEventListener("paste",()=>setTimeout(()=>{if(alive()){tidyKey();paint()}},0));
  $("mdKeyEye").addEventListener("click",()=>{
    const i=el("key"),show=i.type==="password",b=$("mdKeyEye");
    i.type=show?"text":"password";
    b.setAttribute("aria-pressed",String(show));b.title=show?"隐藏 Key":"显示 Key";b.setAttribute("aria-label",b.title);
    b.querySelector("use").setAttribute("href",show?"#i-eye-off":"#i-eye");
  });
  $("mdFormProbe").addEventListener("click",async()=>{
    const btn=$("mdFormProbe");if(btn.getAttribute("aria-disabled")==="true")return;
    tidyUrl();tidyKey();
    const c=mdFormCheck(raw());
    if(c.errors.url||c.errors.key){F.touched.url=F.touched.key=true;paint();el(c.errors.url?"url":"key").focus();return}
    btn.classList.add("is-loading");btn.setAttribute("aria-disabled","true");btn.querySelector("use").setAttribute("href","#i-loader");btn.querySelector("span").textContent="正在连接…";
    const out=$("mdFormProbeOut");
    out.innerHTML=`<div class="md-conn-meta" role="status"><span class="badge is-info">${icon("loader","md-spin")}正在连接…</span><span class="faint">最多等 10 秒</span></div>`;
    const url=c.fields.url,key=c.fields.api_key,at=Date.now();
    const d=await postJSON("/api/probe",{base:url,api_key:key});
    if(!alive())return;  /* 弹窗已经关了 */
    btn.classList.remove("is-loading");btn.setAttribute("aria-disabled","false");btn.querySelector("use").setAttribute("href","#i-plug");btn.querySelector("span").textContent="测试连接";
    F.probe={d,url,key,at};
    out.innerHTML=mdFormProbeHTML(d,c.fields.model);
    if(d.ok&&d.models.length===1&&!el("model").value.trim()){el("model").value=d.models[0].id;F.touched.model=true}  /* 只有一个模型: 直接填上 */
    paint();
  });
  $("mdFormProbeOut").addEventListener("click",e=>{
    const b=e.target.closest("[data-md-pick]");if(!b)return;
    el("model").value=b.dataset.mdPick;F.touched.model=true;paint();
  });
  $("mdForm").querySelector("[data-md-form-cancel]").addEventListener("click",()=>Modal.close());
  $("mdForm").addEventListener("submit",async e=>{
    e.preventDefault();
    if(save.disabled&&save.classList.contains("is-loading"))return;
    tidyUrl();tidyKey();F.tried=true;
    const c=paint();if(!c)return;
    if(!c.ok){const k=Object.keys(ids).find(x=>c.errors[x]);if(k)el(k).focus();return}
    if(save.disabled)return;
    setBusy(save,true);
    const r=await mdSave(c.fields,F.id);
    if(!alive())return;
    setBusy(save,false);
    if(!r.ok){msg("mdFormMsg","error","保存失败："+r.error);return}
    const sv=r.ep,pk=F.probe;
    if(pk&&pk.url===sv.url&&pk.key===(sv.api_key||"")&&(pk.d.ok||pk.d.code))  /* 弹窗里测过、地址和 Key 没再改: 结果记到这个模型上 */
      MD.probe.set(sv.id,{st:pk.d.ok?"ok":"fail",d:pk.d,url:sv.url,key:sv.api_key||"",at:pk.at});
    MD.flash=sv.id;
    if(!F.id&&MD.cur){try{history.pushState(null,"","#models")}catch(e){}MD.cur="";MD.fromList=false}  /* 在详情里添加的: 回到列表看新的这一行 */
    toast(F.id?`已保存「${sv.name}」`:`已添加「${sv.name}」`,"success",2500);
    mdRender();   /* 列表就地更新并高亮这一行; 详情就地更新 */
    Modal.close();
  });
  const first=Object.keys(ids).find(k=>(k==="url"||k==="model")&&!el(k).value.trim())||"url";
  setTimeout(()=>{const i=el(first);if(i){i.focus();if(ep)i.setSelectionRange(i.value.length,i.value.length)}},0);
  paint();
}
function mdFormHTML(edit){
  const f=(id,label,req,input)=>`<div class="field"><label for="${id}">${label}<span class="md-req${req?"":" is-opt"}">${req?"必填":"可不填"}</span></label>${input}
    <span class="help md-help" id="${id}Help"></span></div>`;
  return `<form class="md-form" id="mdForm" novalidate autocomplete="off">
    ${f("mdUrl","服务地址",true,`<input class="input" id="mdUrl" placeholder="http://127.0.0.1:8000" spellcheck="false" autocomplete="off" inputmode="url" aria-describedby="mdUrlHelp" aria-required="true">`)}
    ${f("mdKey","API Key",false,`<div class="md-keywrap"><input class="input" id="mdKey" type="password" placeholder="没有可不填" spellcheck="false" autocomplete="new-password" aria-describedby="mdKeyHelp">
      <button type="button" class="btn btn-ghost btn-icon btn-sm" id="mdKeyEye" aria-label="显示 Key" title="显示 Key" aria-pressed="false">${icon("eye")}</button></div>`)}
    <div class="md-probe"><button type="button" class="btn btn-secondary btn-sm" id="mdFormProbe">${icon("plug")}<span>测试连接</span></button>
      <span class="help">用上面的地址和 Key 取服务上的模型列表，点一个就填进「模型名称」</span></div>
    <div id="mdFormProbeOut" aria-live="polite"></div>
    ${f("mdModel","模型名称",true,`<input class="input" id="mdModel" placeholder="比如 Qwen3-8B；先点「测试连接」可以直接选" spellcheck="false" autocomplete="off" aria-describedby="mdModelHelp" aria-required="true">`)}
    ${f("mdName","名称",false,`<input class="input" id="mdName" placeholder="不填就用「模型 · 主机」" autocomplete="off" aria-describedby="mdNameHelp">`)}
    <div class="dialog-actions"><span class="inline-msg" id="mdFormMsg" aria-live="polite"></span>
      <button type="button" class="btn btn-secondary" data-md-form-cancel>取消</button>
      <button type="submit" class="btn btn-primary" id="mdFormSave">${icon("check")}<span>${edit?"保存修改":"保存"}</span></button></div>
  </form>`;
}
function mdFormProbeHTML(d,model){
  if(!d.ok&&!d.code)return alertBox("bad",`<b>测试连接没有发出去</b><div>${esc(d.error||"原因不明")}</div>`);
  if(!d.ok){const f=mdFailText(d);return alertBox("bad",`<b>连不上：${esc(f.short)}</b><div>${esc(f.long)}</div>${f.raw?`<div class="md-raw">服务返回：<span class="mono">${esc(f.raw)}</span></div>`:""}`)}
  const fw=d.framework?` · ${esc(d.framework)}${d.fw_version?" "+esc(d.fw_version):""}`:"";
  if(!d.models.length)return alertBox("warn",`<b>连接正常</b> · 响应 ${esc(mdLatency(d.latency_ms))}${fw}<div>但服务上没有模型（/v1/models 返回的是空列表）</div>`);
  return alertBox("good",`<b>连接正常</b> · 响应 ${esc(mdLatency(d.latency_ms))}${fw}<div>服务上有 ${fmtInt(d.count)} 个模型，点一个填进「模型名称」：</div>`)+
    `<div class="md-pick" role="group" aria-label="服务上的模型">${d.models.map(m=>`<button type="button" class="md-pick-item" data-md-pick="${esc(m.id)}" aria-pressed="${m.id===model}">
      <span class="md-pick-id">${esc(m.id)}</span><span class="md-pick-sub">${esc(mdCtxText(m.max_model_len))}</span></button>`).join("")}</div>`;
}

/* ---------- 事件 ---------- */
$("mdAddBtn").addEventListener("click",e=>mdFormDialog("",e.currentTarget));
document.addEventListener("click",e=>{
  if(!e.target.closest)return;
  const go=e.target.closest("[data-goto-models]");
  if(go){e.preventDefault();closeDrawers();if(VIEW!=="models"||MD.cur)location.hash="#models";return}
  const pa=e.target.closest("[data-md-probe-all]");if(pa){if(pa.getAttribute("aria-disabled")!=="true")mdProbeAll();return}
  if(e.target.closest("[data-md-refresh]")){mdRefresh();return}
});
$("modelsBody").addEventListener("click",e=>{
  const t=e.target;
  const add=t.closest("[data-md-add]");if(add){mdFormDialog("",add);return}
  const use=t.closest("[data-md-use]");if(use){mdUse(use.dataset.id||MD.cur,use.dataset.mdUse);return}
  const act=t.closest("[data-md-act]");
  if(act){
    if(act.getAttribute("aria-disabled")==="true")return;
    const id=act.dataset.id,a=act.dataset.mdAct;
    if(a==="probe")mdProbe(id);else if(a==="edit")mdFormDialog(id,act);else if(a==="delete")mdDelete(id);
    return;
  }
  if(t.closest("[data-md-back]")){e.preventDefault();mdBack();return}
  if(t.closest("[data-md-rename]")){mdInlineRename();return}
  const rt=t.closest("[data-md-retry]");
  if(rt){if(rt.dataset.mdRetry==="list"){EPS_ST.err="";loadEndpoints();mdRender()}else{MD.runs.delete(mdRunsKey());mdLoadRuns();mdPaintRuns()}return}
  if(t.closest("[data-md-clear]")){MD.q="";const s=$("mdSearch");if(s)s.value="";dtState("md-list-t").page=0;mdPaintTable();if(s)s.focus();return}
  const sw=t.closest("[data-md-switch]");if(sw){mdSwitchModel(sw.dataset.mdSwitch);return}
  const kd=t.closest("[data-md-kind]");if(kd){mdSetKind(kd.dataset.mdKind);return}
  const run=t.closest("[data-md-run]");if(run){e.preventDefault();mdOpenRun(run.dataset.kind,run.dataset.mdRun);return}
  if(t.closest("a,button,input,select,label,summary,details"))return;
  const tr=t.closest('[data-dt="md-list-t"] tr.is-link');if(tr&&tr.dataset.rk){mdOpen(tr.dataset.rk);return}  /* 点一行打开详情 */
  const rr=t.closest('[data-dt="md-runs-t"] tr.is-link');
  if(rr&&rr.dataset.rk){const ent=MD.runs.get(mdRunsKey()),r=ent&&ent.d&&ent.d.runs.find(x=>x.run_id===rr.dataset.rk);if(r)mdOpenRun(r.kind,r.run_id)}
});
let mdQT=null;
$("modelsBody").addEventListener("input",e=>{
  if(e.target.id!=="mdSearch")return;
  clearTimeout(mdQT);
  mdQT=setTimeout(()=>{MD.q=e.target.value.slice(0,200);dtState("md-list-t").page=0;mdPaintTable()},160);
});
/* 「用它新建」菜单在表格里(外面是可以左右滑的滚动区): 打开时按按钮位置固定定位; 滚动时跟着按钮走,
   按钮滚出看得见的范围或者改了窗口大小时收起 */
function mdPlaceMenu(d){
  const s=d.querySelector("summary"),p=d.querySelector(".dropdown-panel");if(!s||!p)return;
  const r=s.getBoundingClientRect(),vw=document.documentElement.clientWidth;
  p.style.left="0px";p.style.top="0px";
  const w=p.offsetWidth,h=p.offsetHeight;
  p.style.left=Math.max(8,Math.min(r.right-w,vw-w-8))+"px";
  p.style.top=(innerHeight-r.bottom-8<h&&r.top-8>h?r.top-4-h:r.bottom+4)+"px";
}
document.addEventListener("toggle",e=>{const d=e.target;if(d&&d.matches&&d.matches("details.md-use-dd")&&d.open)mdPlaceMenu(d)},true);
document.addEventListener("scroll",()=>{
  const d=document.querySelector("details.md-use-dd[open]");if(!d)return;
  const s=d.querySelector("summary").getBoundingClientRect(),box=d.closest(".dt-scroll");
  const c=box?box.getBoundingClientRect():{left:0,top:0,right:innerWidth,bottom:innerHeight};
  if(s.bottom<Math.max(0,c.top)||s.top>Math.min(innerHeight,c.bottom)||s.right<c.left||s.left>c.right)d.open=false;
  else mdPlaceMenu(d);
},true);
window.addEventListener("resize",()=>document.querySelectorAll("details.md-use-dd[open]").forEach(d=>{d.open=false}));

/* ============================================================
   样式自检: 令牌色块 / 字号 / 基础组件(地址 #styleguide)
   ============================================================ */
/* 样式自检用的 7 种表格示例(演示数据) */
function sgTables(){
  const concs=[1,2,4,8,16,32,48,64],agg=[130.8,258,476,812,1352,1511,1775,1745],ttft=[.08,.1,.12,.15,.5,7.2,7.6,13.5];
  const detail={id:"sg-detail",title:"① 明细表 · 同时请求",columns:[
    {key:"conc",label:"同时请求数",type:"int",sticky:true},{key:"agg",label:"总生成速度",unit:"token/秒",type:"bar",color:C.a},
    {key:"per",label:"单个请求速度",unit:"token/秒",type:"num"},{key:"ttft",label:"首字等待 较慢",unit:"秒",type:"sec"},{key:"ok",label:"成功",type:"text"}],
    rows:concs.map((c,i)=>({conc:c,agg:agg[i],per:agg[i]/c,ttft:ttft[i],ok:`${c*10} / ${c*10}`}))};
  const runs=[{tag:"A"},{tag:"B"}],bAgg=agg.map((v,i)=>v*(i%3?0.94:1.03)),bT=ttft.map(v=>v*1.2);
  const cmpMetrics=[{key:"agg",label:"总生成速度",unit:"token/秒",dir:1,get:r=>r.agg},{key:"t95",label:"首字等待 较慢",unit:"秒",dir:-1,type:"sec",get:r=>r.t}];
  const compare={id:"sg-compare",title:"② 对比表 · A / B 与变化",columns:[{key:"_key",label:"同时请求数",type:"int",sticky:true},...compareCols(runs,cmpMetrics)],
    rows:compareRows(concs,[{a:agg,t:ttft},{a:bAgg,t:bT}],(x,k)=>{const i=concs.indexOf(k);return{agg:x.a[i],t:x.t[i]}},cmpMetrics)};
  const lens=["1K","2K","4K","8K","16K"];
  const pv=pivotRows(lens.flatMap((l,i)=>[1,4,16].map(c=>({l,c,v:(i+1)*c*0.07}))),{row:"l",col:"c",value:"v"});
  const matrix={id:"sg-matrix",title:"③ 矩阵热力表 · 首字等待（秒）",heatShared:true,columns:[{key:"_row",label:"输入长度",type:"text",sticky:true},
    ...pv.cols.map(c=>({key:"c_"+c,label:`同时 ${c} 个`,type:"heat",digits:2}))],rows:pv.rows};
  const subs=[["指令遵循",100],["ARC 科学推理",92.5],["GSM8K 数学",88.7],["MMLU 中学",85.6],["MMLU 通识",77.5],["MATH-500",76.2],["HellaSwag",73.8]];
  const rank={id:"sg-rank",title:"④ 排行表 · 各科正确率",columns:[{key:"name",label:"科目",type:"text",sticky:true},{key:"acc",label:"正确率",unit:"%",type:"bar",color:C.a,max:100},{key:"n",label:"题数",type:"int"}],
    rows:subs.map(([name,acc],i)=>({name,acc,n:[30,80,150,104,240,80,80][i]}))};
  const grp={id:"sg-group",title:"⑤ 分组表 · MMLU 学科",groupBy:r=>r.g,groupLabel:(g,rs)=>`${esc(g)} <span class="faint">· ${rs.length} 个学科</span>`,
    columns:[{key:"sub",label:"学科",type:"text",sticky:true},{key:"acc",label:"正确率",unit:"%",type:"bar",color:C.a,max:100},{key:"n",label:"题数",type:"int"}],
    rows:[["MMLU 中学","高中物理",75,8],["MMLU 中学","高中生物",100,8],["MMLU 大学","大学数学",50,8],["MMLU 大学","大学医学",87.5,8],["MMLU 专业","专业法律",62.5,8]].map(([g,sub,acc,n])=>({g,sub,acc,n}))};
  const ck=["能打开","不白屏","有动画","没报错","手机适配"],st=(p)=>p==null?{tone:"neutral",text:"—"}:p?{tone:"good",text:"通过"}:{tone:"bad",text:"没过"};
  const checks={id:"sg-checks",title:"⑥ 检查矩阵表 · 作品 × 检查项",columns:[{key:"name",label:"作品",type:"text",sticky:true},...ck.map((c,i)=>({key:"k"+i,label:c,type:"status",align:"center"}))],
    rows:[["贪吃蛇",[1,1,1,1,1]],["俄罗斯方块",[1,1,1,0,1]],["3D 魔方",[1,0,null,0,1]],["钢琴",[1,1,0,1,0]]].map(([name,v])=>Object.assign({name},...v.map((p,i)=>({["k"+i]:st(p==null?null:!!p)}))))};
  const summ={id:"sg-summary",title:"⑦ 统计摘要表 · 出字间隔（毫秒）",columns:[{key:"lang",label:"内容",type:"text",sticky:true},
    ...[["mean","平均"],["p50","一般"],["p95","较慢"],["p99","最慢"],["max","最大"]].map(([k,l])=>({key:k,label:l,type:"num",digits:1})),{key:"n",label:"样本数",type:"int"}],
    rows:[{lang:"中文",mean:7.8,p50:7.6,p95:9.9,p99:12.4,max:18.2,n:1536},{lang:"英文",mean:7.7,p50:7.6,p95:9.6,p99:11.8,max:16.9,n:1536}]};
  return [detail,compare,matrix,rank,grp,checks,summ].map(dataTable).join("");
}
function renderStyleguide(){
  const cs=getComputedStyle(document.documentElement),v=n=>cs.getPropertyValue(n).trim();
  const sw=(name,label)=>`<div class="sg-sw"><i style="background:var(${name})"></i><span class="sg-sw-name">${esc(label||name)}</span><span class="sg-sw-val">${esc(v(name))}</span></div>`;
  const group=(title,names)=>`<div class="sg-group"><h3 class="sg-h">${esc(title)}</h3><div class="sg-sws">${names.map(n=>Array.isArray(n)?sw(n[0],n[1]):sw(n)).join("")}</div></div>`;
  const heat=[0,.2,.4,.6,.8,1].map(t=>`<i style="background:${mix(C.surface,C.heatHi||C.series[4],t)}"></i>`).join("");
  $("sgBody").innerHTML=`<div class="stack">
    ${group("中性灰阶",["--n-0","--n-1","--n-2","--n-3","--n-4","--n-5","--n-6","--n-7","--n-8","--n-9"])}
    ${group("界面语义",[["--bg","背景"],["--surface-1","面板"],["--surface-2","表头 / 悬停"],["--surface-3","按下"],["--border","描边"],["--border-strong","强描边"],["--text-1","正文"],["--text-2","次要文字"],["--text-3","说明文字"],["--text-4","占位 / 禁用"],["--accent","交互色"],["--accent-ink","交互色上的文字"]])}
    ${group("数据系列（A B C D E F）",["--series-1","--series-2","--series-3","--series-4","--series-5","--series-6"])}
    ${group("状态",[["--good","好 · 文字"],["--good-soft","好 · 底色"],["--good-mark","好 · 图形"],["--warn","警告 · 文字"],["--warn-soft","警告 · 底色"],["--warn-mark","警告 · 图形"],["--bad","差 · 文字"],["--bad-soft","差 · 底色"],["--bad-mark","差 · 图形"],["--info","进行中 · 文字"],["--info-soft","进行中 · 底色"]])}
    <div class="sg-group"><h3 class="sg-h">热力表顺序色阶</h3><div class="sg-heat">${heat}</div></div>
    <div class="sg-group"><h3 class="sg-h">字号阶梯</h3><div class="sg-type">
      ${[["40","首屏主数字",40,650],["28","关键数字",28,650],["20","页面标题",20,650],["16","面板标题",16,600],["14","正文",14,400],["13","次要文字",13,400],["12","说明 / 表头",12,500]]
        .map(([k,t,px,w])=>`<div><span class="sg-sw-val">${k}px</span><span style="font-size:${px}px;font-weight:${w};line-height:1.2">${t} 1,774.6</span></div>`).join("")}</div></div>
    <div class="sg-group"><h3 class="sg-h">按钮</h3><div class="row">
      <button class="btn btn-primary">${icon("plus")}新建速度测试</button><button class="btn btn-secondary">${icon("file-down")}导出报告</button>
      <button class="btn btn-ghost">${icon("refresh")}刷新</button><button class="btn btn-danger">${icon("trash")}删除</button>
      <button class="btn btn-primary is-loading" disabled>${icon("loader")}开始中</button><button class="btn btn-secondary btn-sm">小按钮</button>
      <button class="btn btn-ghost btn-icon" aria-label="更多">${icon("sliders")}</button></div></div>
    <div class="sg-group"><h3 class="sg-h">分段切换 / 筛选片 / 选择片</h3><div class="row">
      <span class="seg" role="group"><button class="seg-btn" aria-pressed="true">${icon("gauge")}图表</button><button class="seg-btn" aria-pressed="false">${icon("table")}表格</button></span>
      <span class="seg" role="group"><button class="seg-btn" aria-pressed="false">标准</button><button class="seg-btn" aria-pressed="true">紧凑</button></span>
      <span class="filter-chips"><button class="filter-chip" aria-pressed="true">全部 <b>924</b></button><button class="filter-chip" aria-pressed="false">没答对 <b>177</b></button></span>
      <label class="chip"><input type="checkbox" checked>${icon("check")}<span>贪吃蛇</span></label><label class="chip-check"><input type="checkbox">看图回答</label></div></div>
    <div class="sg-group"><h3 class="sg-h">徽标 / 变化 / 测试标签</h3><div class="row">
      <span class="badge">默认</span><span class="badge is-good">${icon("check")}通过</span><span class="badge is-warn">${icon("alert")}没答完</span><span class="badge is-bad">${icon("x")}失败</span><span class="badge is-info">进行中</span>
      ${deltaPill(100,112,1,{prefix:"比 B "})}${deltaPill(100,90,1,{prefix:"比 B "})}${deltaPill(100,100.4,1,{prefix:"比 B "})}
      <span class="run-tag" style="background:var(--series-1)">A</span><span class="run-tag" style="background:var(--series-2)">B</span><span class="run-tag" style="background:var(--series-3)">C</span></div></div>
    <div class="sg-group"><h3 class="sg-h">提示框</h3>
      ${alertBox("info","这次测试由旧版评测程序生成，分数口径不同。")}${alertBox("warn","有 17 题没答完（写到长度上限被停下）。")}
      ${alertBox("bad","后台浏览器没有启动，只检查了代码。",`<button class="btn btn-secondary btn-sm">${icon("scan-check")}重新检查</button>`)}${alertBox("good","全部检查通过。")}</div>
    <div class="sg-group"><h3 class="sg-h">表单</h3><div class="form-grid" style="max-width:640px">
      <div class="field"><label for="sgIn">服务地址</label><input class="input" id="sgIn" placeholder="http://127.0.0.1:8000"><span class="help">OpenAI 兼容接口的地址</span></div>
      <div class="field"><label for="sgSel">测试规模</label><select class="select" id="sgSel"><option>标准：约 12 分钟（推荐）</option><option>完整：约 35 分钟</option></select></div>
      <div class="field"><span class="label">思考模式</span><label class="check"><input type="checkbox" checked>让模型先思考再回答</label></div></div></div>
    <div class="sg-group"><h3 class="sg-h">表格形态（同一个组件的 7 种配置）</h3><div class="dt-grid is-multi" style="--tcols:2">${sgTables()}</div></div>
    <div class="sg-group"><h3 class="sg-h">空状态 / 骨架</h3><div class="grid-2">${emptyState("还没有速度测试","点右上角「新建速度测试」，测完的结果会显示在这里",{inline:true})}
      <div class="kpi"><div class="skeleton" style="height:12px;width:50%"></div><div class="skeleton" style="height:30px;width:70%;margin-top:12px"></div></div></div></div>
  </div>`;
  const sel=$("sgSel");if(sel)CSelect.enhance(sel);
}

/* ============================================================
   导出报告(离线 HTML) / 打开离线报告
   ============================================================ */
/* 导出: 当前页面(同一套界面)连同数据打包成一个 HTML 文件, 双击就能打开, 和这里看到的一样 */
const EXPORT_LS=["llm-bench-pro-viewmode","llm-bench-pro-dt","llm-bench-pro-ctab","llm-bench-pro-qb","llm-bench-pro-gen-works","llm-bench-pro-density","llm-bench-pro-rail"];
const PAGE_NAME={dash:"速度测试",cmp:"速度对比",iq:"能力测试",gen:"代码生成"};
function exportSel(page){
  if(page==="dash")return[$("runA").value,[$("runB").value]];
  if(page==="cmp")return[$("cmpA").value,[$("cmpB").value]];
  if(page==="iq")return[$("iqMainSel").value,[...IQ_CMP]];
  return[$("genMainSel").value,[$("genCmpSel").value]];
}
function exportTitle(page,id,cmp){
  const src=page==="iq"?IQ_RUNS:page==="gen"?GEN_RUNS:RUNS,r=src[id];
  const models=[id,...cmp].map(x=>(src[x]&&src[x].model)||x);
  return `${PAGE_NAME[page]} · ${models.join(" vs ")}${r&&r.started_utc?" · "+shortTime(r.started_utc):""}`;
}
async function exportHtml(page){
  const [id,raw]=exportSel(page),cmp=raw.filter(x=>x&&x!==id);
  if(!id){toast("请先选择要导出的测试","warning");return}
  const btn=document.querySelector(`[data-export="${page}"]`);
  const ls={};EXPORT_LS.forEach(k=>{const v=LS.get(k);if(v!=null)ls[k]=v});
  const ui={panels:[...PANEL_OVR],qb:{subj:QB.subj,filter:QB.filter,q:QB.q,vs:QB.vs},genFilter:GEN_FILTER,genSort:GEN_SORT,genView:{tier:GEN_TIER,q:GEN_Q,page:GEN_PAGE,size:GEN_SIZE}};
  const title=exportTitle(page,id,cmp);
  setBusy(btn,true);
  try{
    const r=await fetch("/api/export-html",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({page,id,cmp,title,state:{theme:document.documentElement.dataset.theme,ls},ui})});
    if(!r.ok){let m="HTTP "+r.status;try{m=(await r.json()).error||m}catch(e){}throw new Error(m)}
    const blob=await r.blob();
    downloadBlob(safeName(title.replace(/ · /g,"_"))+".html",blob);
    toast(`已导出「${title}」（${(blob.size/1048576).toFixed(1)} MB）：一个网页文件，双击就能打开，和这里看到的一样`,"success",5000);
  }catch(e){toast("导出失败："+e.message,"error")}
  finally{setBusy(btn,false)}
}
/* 打开离线报告: 只显示导出的那一页, 选中导出时的测试和筛选, 隐藏需要后端的操作 */
function offlineInit(){
  document.documentElement.classList.add("is-offline");
  SERVER=Object.assign({},(OFF.api||{}).version||{});
  $("conn").className="conn is-offline";
  $("connText").textContent="离线报告";
  $("conn").title=`从 LLM Bench Pro v${SERVER.version||"?"} 导出的离线报告（${timeText(OFF.exported_at)}）：数据是导出那一刻的样子，不会更新，也不能修改`;
  const page=VIEWS[OFF.page]&&OFF.page!=="styleguide"?OFF.page:"dash";
  document.querySelectorAll(".nav-item[data-view]").forEach(b=>{if(b.dataset.view!==page)b.hidden=true});
  const S=OFF.sel||{},cmp=S.cmp||[],opt=x=>x?`<option value="${esc(x)}" selected></option>`:"";
  if(page==="dash"){$("runA").innerHTML=opt(S.a);$("runB").innerHTML=`<option value="">不对比</option>`+opt(cmp[0])}
  if(page==="cmp"){$("cmpA").innerHTML=opt(S.a);$("cmpB").innerHTML=opt(cmp[0])}
  if(page==="iq"){$("iqMainSel").innerHTML=opt(S.a);cmp.forEach(x=>IQ_CMP.add(x))}
  if(page==="gen"){$("genMainSel").innerHTML=opt(S.a);$("genCmpSel").innerHTML=`<option value="">不对比</option>`+opt(cmp[0])}
  const U=OFF.ui||{};
  (U.panels||[]).forEach(([k,v])=>PANEL_OVR.set(k,v));
  if(U.qb){Object.assign(QB,{subj:U.qb.subj||"",filter:U.qb.filter||"all",q:U.qb.q||"",vs:U.qb.vs||""});QB.main=S.a||""}
  if(U.genFilter)GEN_FILTER=U.genFilter;
  if(U.genSort)GEN_SORT=U.genSort;
  if(U.genView){
    if(typeof U.genView.tier==="string")GEN_TIER=U.genView.tier;
    if(typeof U.genView.q==="string")GEN_Q=U.genView.q;
    if(Number.isInteger(U.genView.page))GEN_PAGE=U.genView.page;
    if(GW_SIZES.includes(U.genView.size))GEN_SIZE=U.genView.size;
  }
  showView(page);
  if(page==="dash"||page==="cmp")refresh();
}
/* ============================================================
   启动
   ============================================================ */
let SERVER={};
const VERSION_WARNED={};
async function checkVersion(){
  try{
    const v=await getJSON("/api/version");
    SERVER=v;
    setConn(true,`服务正常 · 已运行 ${durationText(v.uptime_s)}`);
    $("conn").title=`后端 v${v.version} · 进程 ${v.pid} · 启动于 ${timeText(v.started_at)}${v.commit?" · 提交 "+v.commit:""}\n数据库 ${v.db}\n评测程序：速度 ${v.bench_version} · 能力 ${v.iq_version} · 代码生成 ${v.gen_version}`;
    if(v.version!==UI_VERSION&&!VERSION_WARNED.ver){
      VERSION_WARNED.ver=1;
      toast(`页面（v${UI_VERSION}）和后端服务（v${v.version}）版本不一致：页面可能还是旧的，功能可能不正常。`,"warning",0,
        {label:"刷新页面",onClick:()=>location.reload()});
    }
    if(v.code_changed&&!VERSION_WARNED.code){
      VERSION_WARNED.code=1;
      toast("后端代码已经更新，但服务还在运行旧代码。请重启 python run.py 让修改生效。","warning",0);
    }
  }catch(e){setConn(false,"服务未连接")}
}
async function resumeRunning(){
  const jobs=[
    ["/api/status","perf",()=>watchPerf("进行中（刷新页面后继续跟踪）")],
    ["/api/iq-status","iq",()=>watchIq("进行中（刷新页面后继续跟踪）")],
    ["/api/gen-status","gen",()=>watchGen("进行中（刷新页面后继续跟踪）")],
    ["/api/bank-status","bank",()=>watchBank("更新题集（刷新页面后继续跟踪）")],
  ];
  for(const [url,,watch] of jobs){
    try{const s=await getJSON(url);if(s.running)watch()}catch(e){}
  }
}
let rzT;
window.addEventListener("resize",()=>{clearTimeout(rzT);rzT=setTimeout(()=>{for(const inst of CHARTS.values()){try{inst.resize()}catch(e){}}},120)});
matchMedia("(prefers-color-scheme: light)").addEventListener("change",e=>{
  if(LS.get("llm-bench-pro-theme"))return;
  applyTheme(e.matches?"light":"dark",false);
});
document.querySelectorAll("select.select").forEach(CSelect.enhance);
CSelect.combo($("fModel"));
readTheme();
applyTheme(document.documentElement.dataset.theme||"dark",false);
applyRailPin(LS.get("llm-bench-pro-rail")==="1",false);
document.querySelectorAll("[data-vm-page]").forEach(g=>g.querySelectorAll("[data-vm]").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.vm===(VIEWMODE[g.dataset.vmPage]||"chart")))));
applyDensity(LS.get("llm-bench-pro-density")==="compact"?"compact":"normal",false);
if(OFF)offlineInit();
else{
  showView((location.hash||"#dash").slice(1));
  checkVersion().then(()=>{if(VIEW==="iq")renderIq()});
  setInterval(checkVersion,60000);
  refresh();
  loadReplayFiles();
  loadScenarioAssets();
  loadEndpoints();
  resumeRunning();
}
