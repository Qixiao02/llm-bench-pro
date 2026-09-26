"use strict";
/* LLM Bench Pro 前端逻辑 (零依赖经典脚本; 图表用本地内置的 ECharts) */
const UI_VERSION="2.9.0";  /* 与 llm_bench_pro/version.py 保持一致 */
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
async function getJSON(url){const r=await fetch(url,{cache:"no-store"});if(!r.ok)throw new Error("HTTP "+r.status);return r.json()}
async function postJSON(url,body){
  try{const r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    try{return await r.json()}catch(e){return{ok:false,error:"HTTP "+r.status}}}
  catch(e){return{ok:false,error:"无法连接后端服务（"+e.message+"）"}}
}
function lsGet(key){try{return JSON.parse(localStorage.getItem(key)||"{}")}catch(e){return{}}}
function lsSet(key,val){try{localStorage.setItem(key,JSON.stringify(val))}catch(e){}}
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
  return `<span class="term" title="${esc(t.tech+"：" +t.desc)}">${esc(label||t.name)}</span>`;
}
function showGlossary(){
  Modal.open("名词解释",`<p class="muted" style="margin-bottom:12px">页面上尽量用大白话；把鼠标放在带虚线下划线的词上，也能看到这里的解释。</p>
    <div class="glossary">${Object.values(TERMS).map(t=>`<div class="glossary-item"><div><div class="glossary-name">${esc(t.name)}</div>
      <div class="glossary-tech">${esc(t.tech)}</div></div><div class="glossary-desc">${esc(t.desc)}</div></div>`).join("")}</div>`,{wide:true});
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
  if(persist)try{localStorage.setItem("llm-bench-pro-theme",t)}catch(e){}
  $("themeBtn").querySelector("use").setAttribute("href",t==="dark"?"#i-sun":"#i-moon");
  $("themeBtn").setAttribute("aria-label",t==="dark"?"切换为亮色":"切换为暗色");
  readTheme();
  redrawVisible();
}
function toggleTheme(){applyTheme(document.documentElement.dataset.theme==="dark"?"light":"dark",true)}
$("themeBtn").onclick=toggleTheme;
/* 侧栏: 默认 64px 图标栏, 悬停展开; 「固定」后一直展开(记在本机) */
function applyRailPin(on,persist){
  document.querySelector(".app").classList.toggle("is-pinned",on);
  const b=$("railPin");b.setAttribute("aria-pressed",String(on));
  b.title=b.ariaLabel=on?"收起侧栏":"固定展开侧栏";
  if(persist)try{localStorage.setItem("llm-bench-pro-rail",on?"1":"0")}catch(e){}
}
$("railPin").onclick=()=>applyRailPin(!document.querySelector(".app").classList.contains("is-pinned"),true);
/* 密度: 标准 / 紧凑(表格行高、面板内边距), 记在本机 */
function applyDensity(d,persist){
  document.documentElement.dataset.density=d;
  document.querySelectorAll("[data-density-toggle]").forEach(b=>b.setAttribute("aria-checked",String(d==="compact")));
  if(persist)try{localStorage.setItem("llm-bench-pro-density",d)}catch(e){}
  for(const inst of CHARTS.values()){try{inst.resize()}catch(e){}}
}

/* ============================================================
   导航 / 抽屉 / 弹窗 / 通用点击
   ============================================================ */
let VIEW="dash";
const VIEWS={dash:"viewDash",cmp:"viewCmp",iq:"viewIq",gen:"viewGen",styleguide:"viewSg"};
function showView(v){
  if(!VIEWS[v])v="dash";
  VIEW=v;
  document.querySelectorAll(".nav-item").forEach(b=>{if(b.dataset.view===v)b.setAttribute("aria-current","page");else b.removeAttribute("aria-current")});
  Object.entries(VIEWS).forEach(([k,id])=>$(id).classList.toggle("is-active",k===v));
  closeDrawers();closeMenus();
  try{history.replaceState(null,"","#"+v)}catch(e){}
  if(v==="dash")render();
  if(v==="cmp")renderCmp();
  if(v==="iq"){loadBanks();loadIqResults();}
  if(v==="gen"){renderTaskChips();loadGenResults();}
  if(v==="styleguide")renderStyleguide();
  window.scrollTo(0,0);
}
function redrawVisible(){
  if(VIEW==="dash")render();
  else if(VIEW==="cmp")renderCmp();
  else if(VIEW==="iq")renderIq();
  else if(VIEW==="gen")renderGen();
  else if(VIEW==="styleguide")renderStyleguide();
}
/* 新建测试用右侧抽屉: 同一时间只开一个, 结果页保持可见 */
const DRAWERS=["launcher","iqLauncher","genLauncher"];
function closeDrawers(except){
  DRAWERS.forEach(id=>{if(id!==except&&$(id)&&!$(id).hidden)toggleLauncher(id,false)});
}
function toggleLauncher(id,force){
  const el=$(id);if(!el)return;
  const open=force==null?el.hidden:force;
  if(open)closeDrawers(id);
  el.hidden=!open;
  $("drawerBackdrop").hidden=!DRAWERS.some(d=>$(d)&&!$(d).hidden);
  document.querySelectorAll(`[data-toggle="${id}"][aria-expanded]`).forEach(b=>b.setAttribute("aria-expanded",String(open)));
  if(open&&force==null){const f=el.querySelector("input:not([type=checkbox]):not([type=file]),select");if(f)setTimeout(()=>f.focus(),60)}
}
$("drawerBackdrop").addEventListener("click",()=>closeDrawers());
/* 地址栏 #dash / #iq … 变化(前进/后退、手动修改)时切换页面 */
window.addEventListener("hashchange",()=>{const v=(location.hash||"").slice(1);if(VIEWS[v]&&v!==VIEW)showView(v)});
/* 运行中的任务: 侧栏圆点 + 页头"进行中"按钮, 抽屉关着也看得到 */
function setRunning(job,on){
  document.querySelectorAll(`[data-running="${job}"],[data-running-pill="${job}"]`).forEach(el=>el.hidden=!on);
}
function closeMenus(except){document.querySelectorAll("details.dropdown[open]").forEach(d=>{if(d!==except)d.open=false})}
document.addEventListener("click",e=>{
  const nav=e.target.closest(".nav-item");if(nav&&nav.dataset.view){showView(nav.dataset.view);return}
  if(e.target.closest("[data-density-toggle]")){applyDensity(document.documentElement.dataset.density==="compact"?"normal":"compact",true);closeMenus();return}
  if(e.target.closest("[data-theme-toggle]")){toggleTheme();closeMenus();return}
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
  const epBtn=e.target.closest("[data-ep-use],[data-ep-del],[data-ep-edit],[data-ep-save],[data-ep-cancel],[data-ep-reveal]");
  if(epBtn){
    if(epBtn.dataset.epUse)epApply(epBtn.dataset.epUse);
    else if(epBtn.dataset.epDel)epRemove(epBtn.dataset.epDel);
    else if(epBtn.dataset.epEdit)epEdit(epBtn.dataset.epEdit);
    else if("epReveal" in epBtn.dataset){
      const inp=$("epKey");if(!inp)return;
      const show=inp.type==="password";inp.type=show?"text":"password";
      epBtn.title=show?"隐藏 Key":"显示 Key";
    }
    else if("epSave" in epBtn.dataset)epSave();
    else{EP_EDIT=null;manageEndpoints()}  /* 取消编辑 → 回到新增 */
    return
  }
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
document.addEventListener("keydown",e=>{
  if($("modal").hidden){if(e.key==="Escape"){if(document.querySelector("details.dropdown[open]"))closeMenus();else closeDrawers()}return}
  if(e.key==="Escape"){Modal.close();return}
  if(e.key==="Tab"){  /* 焦点限制在弹窗内 */
    const f=[...$("modal").querySelectorAll("button,[href],input,select,textarea,iframe,[tabindex]:not([tabindex='-1'])")].filter(x=>!x.disabled);
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
    if(c.kind==="select")return[...c.el.options].map((o,i)=>({value:o.value,text:o.textContent,disabled:o.disabled,selected:i===c.el.selectedIndex}));
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
  el.innerHTML=`<div class="runlog-head"><span class="runlog-dot"></span><span class="runlog-title"></span><span class="runlog-time"></span>
    <button class="btn btn-ghost btn-sm runlog-stop" type="button" hidden>${icon("stop")}停止</button>
    <button class="btn btn-ghost btn-sm runlog-copy" type="button">${icon("copy")}复制日志</button></div><pre class="runlog-body"></pre>`;
  const title=el.querySelector(".runlog-title"),time=el.querySelector(".runlog-time"),body=el.querySelector(".runlog-body");
  const stop=el.querySelector(".runlog-stop");
  let stopping=false;
  stop.onclick=async()=>{
    const ok=await confirmDialog({title:"停止测试",confirmText:"停止",danger:true,
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
    start(text){el.hidden=false;el.className="runlog is-running";title.textContent=text;body.textContent="";stopping=false;
      stop.hidden=!job;stop.disabled=false;t0=Date.now();clearInterval(timer);timer=setInterval(tick,1000);tick();if(job)setRunning(job,true)},
    lines(arr){const atBottom=body.scrollHeight-body.scrollTop-body.clientHeight<32;body.textContent=arr.join("\n");if(atBottom)body.scrollTop=body.scrollHeight},
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
function sLine(name,color,data,o={}){
  return{name,type:"line",data,connectNulls:true,symbol:"circle",symbolSize:8,showSymbol:o.dots!==false,
    lineStyle:{width:2,color},itemStyle:{color,borderColor:C.surface,borderWidth:2},
    areaStyle:o.area?areaFill(color):undefined,emphasis:{focus:"series"},z:o.z||2};
}
function sBar(name,color,data,o={}){
  return{name,type:"bar",data,barMaxWidth:o.maxWidth||24,barGap:"12%",barCategoryGap:o.catGap||"36%",stack:o.stack,
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
    grid:{left:4,right:16,top:series.length>1?44:30,bottom:xName?26:4,containLabel:true},
    xAxis:axisCat(cats,{gap:false,name:xName}),
    yAxis:axisValue({name:yName||unit,fmt:axisFmtFor(series)}),
    tooltip:Object.assign(baseOption().tooltip,{formatter:ps=>{
      const i=ps[0].dataIndex;
      return tt(tip&&tip.title?tip.title(i):String(ps[0].axisValue),
        ps.filter(p=>p.value!=null).map(p=>[p.color,p.seriesName,fmt(p.value,digits)+" "+(unit||"")]),tip&&tip.sub?tip.sub(i,ps):"");}}),
    series:series.map(s=>sLine(s.name,s.color,s.data,{area:area&&series.length===1}))}));
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
    series:series.map(s=>sBar(s.name,s.color,s.data,{horizontal,label:lab}))}));
  if(height)$(id).style.height=height+"px";
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
    nav.querySelectorAll("a").forEach(a=>{const on=!!cur&&a.dataset.jumpto===cur.id;a.setAttribute("aria-current",String(on));if(on&&a.scrollIntoView&&nav.scrollWidth>nav.clientWidth)a.scrollIntoView({block:"nearest",inline:"nearest"})});
  },{rootMargin:"-120px 0px -55% 0px"});
  secs.forEach(s=>SPY.observe(s));
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
/* 变化标记: dir=1 越高越好, -1 越低越好; mode=pp 用百分点 */
function deltaPill(va,vb,dir,{mode="pct",prefix=""}={}){
  if(va==null||vb==null)return `<span class="delta flat">—</span>`;
  const d=mode==="pp"?vb-va:(va?(vb-va)/Math.abs(va)*100:0);
  const flat=Math.abs(d)<(mode==="pp"?.5:1);
  const unit=mode==="pp"?" 个百分点":"%";
  if(flat)return `<span class="delta flat" title="${dir<0?"越低越好":"越高越好"}，基本持平">${icon("minus")}${prefix}持平</span>`;
  const good=d*dir>0;
  return `<span class="delta ${good?"up":"down"}" title="${dir<0?"越低越好":"越高越好"}，${good?"更好":"更差"}">${icon(d>0?"arrow-up":"arrow-down")}${prefix}${d>=0?"+":""}${fmt(d,1)}${unit}</span>`;
}
function pctChange(va,vb){return va==null||vb==null||!va?null:(vb-va)/Math.abs(va)*100}
/* 表格: head=[列名...], rows=[[单元格 HTML...]...] */
function table(head,rows,{maxH}={}){
  return `<div class="table-wrap"${maxH?` style="max-height:${maxH}px"`:""}><table class="table"><thead><tr>${head.map(h=>`<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map(c=>`<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
/* A/B 对照单元格: 主值 + 下方小字 B 值 */
function abCell(va,vb,f,hasB){return `${f(va)}${hasB?`<span class="sub">B ${f(vb)}</span>`:""}`}

/* ============================================================
   速度测试: 新建 / 列表 / 指标
   ============================================================ */
let RUNS={},RUNS_LOADED=false,perfPoll=null;
const FULL={};  /* 测试完整记录缓存(列表接口只返回摘要) */
let renderSeq=0,cmpSeq=0;
async function ensureRuns(ids){
  await Promise.all(ids.filter(id=>id&&!FULL[id]).map(async id=>{FULL[id]=await getJSON("/api/run?id="+encodeURIComponent(id))}));
}
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
  ["vision","看图回答","描述图片、解读图表、识别文字"],
  ["custom","自定义任务集","上传你自己的请求（JSONL）"],
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

async function loadScenarioAssets(keepImg,keepTask){
  try{
    const d=await getJSON("/api/scenario-list");
    const img=$("fImgSel"),keep1=keepImg||img.value;
    img.innerHTML=`<option value="">未选择</option>`+d.images.map(p=>
      `<option value="${esc(p.image_id)}">${esc(p.image_id.slice(4,12))} · ${p.count} 张 · ${(p.size/1048576).toFixed(1)} MB</option>`).join("");
    if(keep1&&d.images.find(p=>p.image_id===keep1))img.value=keep1;
    const tsk=$("fTaskSel"),keep2=keepTask||tsk.value;
    tsk.innerHTML=`<option value="">未选择</option>`+d.tasks.map(p=>
      `<option value="${esc(p.file_id)}">${esc(p.file_id.slice(4,12))} · ${(p.size/1024).toFixed(0)} KB · ${shortTime(p.mtime)}</option>`).join("");
    if(keep2&&d.tasks.find(p=>p.file_id===keep2))tsk.value=keep2;
  }catch(e){/* 服务不可达时保持空列表 */}
}
function readFileBase64(f){
  return new Promise((res,rej)=>{const r=new FileReader();r.onload=()=>res(String(r.result).split(",",2)[1]||"");r.onerror=()=>rej(new Error("读取失败"));r.readAsDataURL(f)});
}
$("fImgUpload").addEventListener("change",async e=>{
  const files=[...e.target.files];
  e.target.value="";
  if(!files.length)return;
  if(files.reduce((s,f)=>s+f.size,0)>15*1024*1024){msg("probeOut","error","图片总共超过 15MB：请分批上传，或放到服务器文件夹后填路径");return}
  msg("probeOut","info","正在上传 "+files.length+" 张图片…");
  try{
    const payload=await Promise.all(files.map(async f=>({name:f.name,data:await readFileBase64(f)})));
    const d=await postJSON("/api/scenario-upload",{kind:"images",files:payload});
    if(!d.ok){msg("probeOut","error","上传失败："+d.error);return}
    await loadScenarioAssets(d.image_id);
    msg("probeOut","success",`已上传图片：${d.count} 张（${(d.size/1048576).toFixed(1)} MB）`);
  }catch(err){msg("probeOut","error",err.message)}
});
$("fTaskUpload").addEventListener("change",async e=>{
  const f=e.target.files[0];
  e.target.value="";
  if(!f)return;
  msg("probeOut","info","正在上传任务集 "+f.name+"…");
  try{
    const d=await postJSON("/api/scenario-upload",{kind:"tasks",name:f.name,content:await f.text()});
    if(!d.ok){msg("probeOut","error","上传失败："+d.error);return}
    await loadScenarioAssets(null,d.file_id);
    msg("probeOut","success",`已上传任务集：${fmtInt(d.lines)} 条可用请求${d.bad_lines?`（${d.bad_lines} 行格式不对，已忽略）`:""}`);
  }catch(err){msg("probeOut","error",err.message)}
});
$("fSuite").addEventListener("change",suitePlaceholders);
suitePlaceholders();

async function probe(){
  const btn=$("btnProbe");setBusy(btn,true);msg("probeOut","info","正在连接…");
  try{
    const d=await postJSON("/api/probe",{base:$("fBase").value,api_key:$("fKey").value});
    if(!d.ok){msg("probeOut","error","连不上："+d.error);return}
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
      scen.vision_src={image_id:$("fImgSel").value||undefined,dir:$("fImgDir").value.trim()||undefined,images:parseInt($("fImgN").value)||1};
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
  if(f.size>15*1024*1024){msg("probeOut","error","文件超过 15MB：请放到运行服务的机器上，用命令行 --replay-file 引用");return}
  msg("probeOut","info","正在上传 "+f.name+"…");
  try{
    const d=await postJSON("/api/replay-upload",{name:f.name,content:await f.text()});
    if(!d.ok){msg("probeOut","error","上传失败："+d.error);return}
    await loadReplayFiles(d.file_id);
    msg("probeOut","success",`已上传 ${f.name}：${fmtInt(d.lines)} 条可用请求${d.bad_lines?`（${d.bad_lines} 行格式不对，已忽略）`:""}`);
  }catch(err){msg("probeOut","error","读取文件失败："+err.message)}
});

/* ---------- 导出离线报告 ---------- */
function exportReport(view){
  const idA=view==="cmp"?$("cmpA").value:$("runA").value;
  if(!idA){toast("请先选择要导出的测试","warning");return}
  const idB=view==="cmp"?$("cmpB").value:$("runB").value;
  const url="/api/report?id="+encodeURIComponent(idA)+(idB?"&cmp="+encodeURIComponent(idB):"");
  const a=document.createElement("a");
  a.href=url;a.rel="noopener";
  document.body.appendChild(a);a.click();a.remove();
  toast("已开始下载报告（一个网页文件，可以直接发给别人打开）","success",3500);
}

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
  {key:"mpre",label:m=>`长输入同时 ${m.pcp?m.pcp.conc:"多"} 个请求 · 平均读入速度`,term:"prefill",unit:"token/秒",dir:1,digits:0,val:m=>m.s&&m.s.prefill_avg,
    sub:m=>m.s?`范围 ${fmtInt(m.s.prefill_min)}–${fmtInt(m.s.prefill_max)}`:""},
  {key:"mdec",label:m=>`长输入同时 ${m.pcp?m.pcp.conc:"多"} 个请求 · 平均总生成速度`,term:"agg",unit:"token/秒",dir:1,val:m=>m.s&&m.s.decode_avg,
    sub:m=>m.s?`单个请求一般 ${fmt(m.s.per_stream_decode_p50)} · 较慢 ${fmt(m.s.per_stream_decode_p95)}`:""},
  {key:"succ",label:()=>"请求成功率",unit:"%",dir:1,val:m=>m.succ,sub:m=>m.fails?`失败 ${m.fails} 个`:"同时请求测试中全部成功"},
];
const CMP_EXTRA=[
  {key:"itl",label:()=>"出字间隔 · 英文（一般）",term:"itl",unit:"毫秒",dir:-1,val:m=>m.en&&m.en.itl_p50_ms_med},
  {key:"burst",label:()=>"每次返回的 token 数 · 中文",term:"burst",unit:"个",dir:1,digits:2,val:m=>m.zh&&m.zh.spec_burst_med},
  {key:"ttftmax",label:m=>`首字等待 · 输入 ${m.pLast?m.pLast.label:"最长"}`,term:"ttft",unit:"秒",dir:-1,digits:2,val:m=>m.pLast&&m.pLast.ttft_med_s,ref:m=>m.pLast&&m.pLast.label},
  {key:"p50",label:()=>"长输入时单个请求生成速度（一般）",term:"per",unit:"token/秒",dir:1,val:m=>m.s&&m.s.per_stream_decode_p50},
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
    return {ttft:`同时 ${r} 个请求`,pmax:`输入 ${r}`,ttftmax:`输入 ${r}`,scnreq:`同时 ${r} 个请求`,rps:`同时 ${r} 个请求`,inf:`${r} 个/秒`}[k.key]||String(r)}
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
function perfConclusions(a,b){
  const m=perfCtx(a),out=[];
  if(m.zh||m.en){
    const parts=[m.zh&&`中文 <b>${fmt(m.zh.decode_tps_med)}</b>`,m.en&&`英文 <b>${fmt(m.en.decode_tps_med)}</b>`].filter(Boolean).join("、");
    out.push({tone:"info",html:`只有 1 个请求时，每秒能写 ${parts} 个 token。`});
  }
  if(m.peak&&m.c1){
    const x=m.c1.agg_tps?m.peak.agg_tps/m.c1.agg_tps:null;
    out.push({tone:"info",html:`同时 <b>${m.peak.conc}</b> 个请求时${term("agg","总速度")}最高，每秒 <b>${fmtInt(m.peak.agg_tps)}</b> token${x&&m.peak.conc>1?`，是 1 个请求时的 <b>${fmt(x,1)}</b> 倍`:""}。`});
    if(m.cLast&&m.cLast.conc>m.peak.conc&&m.cLast.agg_tps<m.peak.agg_tps*0.95)
      out.push({tone:"warn",html:`再加到 ${m.cLast.conc} 个请求时总速度反而降到 ${fmtInt(m.cLast.agg_tps)}，${m.peak.conc} 个左右已经是这台服务的上限。`});
  }
  if(m.cLast&&m.cLast.ttft_p95_s!=null){
    const t=m.cLast.ttft_p95_s;
    out.push({tone:t>10?"bad":t>3?"warn":"good",html:`同时 ${m.cLast.conc} 个请求时，${term("ttft")}一般 <b>${fmtSec(m.cLast.ttft_p50_s)}</b> 秒，较慢时 <b>${fmtSec(t)}</b> 秒${t>10?"，用户会明显感到卡":t>3?"，高峰时用户会觉得慢":""}。`});
  }
  if(m.pLast&&m.pLast.ttft_med_s!=null){
    const t=m.pLast.ttft_med_s;
    out.push({tone:t>10?"warn":"info",html:`输入 ${esc(m.pLast.label)}（约 ${fmtInt(m.pLast.in_tokens)} token）时，要等 <b>${fmtSec(t)}</b> 秒才开始回答（${term("prefill")} ${fmtInt(m.pLast.prefill_tps_med)} token/秒）。`});
  }
  if(m.s)out.push({tone:"info",html:`长输入同时 ${m.pcp.conc} 个请求：平均${term("prefill")} <b>${fmtInt(m.s.prefill_avg)}</b>、平均${term("agg")} <b>${fmt(m.s.decode_avg)}</b> token/秒。`});
  if(m.succ!=null&&m.succ<100)out.push({tone:"bad",html:`有 <b>${m.fails}</b> 个请求失败（成功率 ${fmt(m.succ,1)}%）。`});
  if(b){
    const mb=perfCtx(b);
    const rows=[...PERF_METRICS,...CMP_EXTRA].filter(k=>sameRef(k,m,mb)).map(k=>({k,va:safeVal(k.val,m),vb:safeVal(k.val,mb)})).filter(x=>x.va!=null&&x.vb!=null)
      .map(x=>({...x,d:pctChange(x.va,x.vb)})).filter(x=>x.d!=null);
    const better=rows.filter(x=>x.d*x.k.dir>=1).sort((p,q)=>Math.abs(q.d)-Math.abs(p.d));
    const worse=rows.filter(x=>x.d*x.k.dir<=-1).sort((p,q)=>Math.abs(q.d)-Math.abs(p.d));
    const fmtD=x=>`${esc(metricLabel(x.k,m))} ${x.d>=0?"+":""}${fmt(x.d,1)}%`;
    out.push({tone:worse.length>better.length?"warn":"good",html:`B 相比 A：<b>${better.length}</b> 项更好、<b>${worse.length}</b> 项更差、${rows.length-better.length-worse.length} 项基本持平。`+
      (better.length?`更好：${better.slice(0,2).map(fmtD).join("；")}。`:"")+(worse.length?`更差：${worse.slice(0,2).map(fmtD).join("；")}。`:"")});
  }
  return out;
}
function perfMetaLine(r){
  const ov=r.overrides||{};
  return [esc(r.model||"?"),runFw(r)&&esc(runFw(r)),`${esc(SUITE_NAME[r.suite]||r.suite||"")}规模`,esc(hostOf(r.url)),`开始于 ${esc(timeText(r.started_utc))}`,
    r.tag&&`标签 ${esc(r.tag)}`,ov.fixed_output!=null&&(ov.fixed_output?`${term("fixed","每次生成满指定长度")}`:"输出长度不固定")].filter(Boolean).join(" · ");
}
function perfKpis(a,b){
  const ma=perfCtx(a),mb=b?perfCtx(b):null;
  return PERF_METRICS.map(k=>{
    const va=safeVal(k.val,ma),vb=mb?safeVal(k.val,mb):null;
    if(va==null&&vb==null)return "";
    const tip=k.term&&TERMS[k.term]?TERMS[k.term].name+"（"+TERMS[k.term].tech+"）："+TERMS[k.term].desc:"";
    const same=!mb||sameRef(k,ma,mb);
    const delta=!mb?"":same?deltaPill(va,vb,k.dir,{prefix:"B "}):`<span class="delta flat" title="A 是${esc(refText(k,ma))}，B 是${esc(refText(k,mb))}">档位不同</span>`;
    return kpi(esc(metricLabel(k,ma)),metricVal(k,va),k.unit,{tip,delta,
      sub:esc(safeSub(k,ma))+(mb?`<br>B：${metricVal(k,vb)} ${esc(k.unit)}${same?"":`（B 是${esc(refText(k,mb))}，不可比）`}`:"")});
  }).join("");
}
function dataDetails(html,title="查看具体数字"){
  return `<details class="advanced"><summary>${icon("chevron-down")}${title}</summary><div style="margin-top:12px">${html}</div></details>`;
}
/* 两次测试的系列: 单次测试时只有 A */
function runSeries(a,b,get){return [["A",a,C.a],b?["B",b,C.b]:null].filter(Boolean).map(([t,r,c])=>({tag:t,run:r,color:c,ph:get(r)})).filter(x=>x.ph)}

/* ---------- 同时请求 ---------- */
function concPoints(r){const p=phase(r,"concurrency");return p&&p.points.length?[...p.points].sort((x,y)=>x.conc-y.conc):null}
function concSection(a,b,p){
  const runs=runSeries(a,b,concPoints);if(!runs.length)return "";
  const concs=[...new Set(runs.flatMap(x=>x.ph.map(q=>q.conc)))].sort((x,y)=>x-y);
  const rows=[];
  concs.forEach(c=>runs.forEach(x=>{const q=x.ph.find(z=>z.conc===c);if(!q)return;
    rows.push([String(c)+(runs.length>1?` <span class="run-tag ${x.tag.toLowerCase()}">${x.tag}</span>`:""),fmtInt(q.agg_tps),fmt(q.per_stream_tps_med),fmtSec(q.ttft_p50_s),fmtSec(q.ttft_p95_s),`${q.ok} / ${q.ok+q.fail}`])}));
  const tbl=table(["同时请求数","总生成速度（token/秒）","单个请求速度（token/秒）","首字等待 一般（秒）","首字等待 较慢（秒）","成功"],rows);
  return sec(p+"-conc","同时请求越多，会怎样",`横轴是${term("conc")}。总速度通常先涨后平；每个请求分到的速度和${term("ttft")}会随之变差`,
    `<div class="grid-3">${ccard(p+"ConcAgg",term("agg"),{desc:"所有请求加起来每秒写多少 token · 越高越好"})}
      ${ccard(p+"ConcPer",term("per"),{desc:"每个请求分到的生成速度 · 越高越好"})}
      ${ccard(p+"ConcTtft",term("ttft")+"（较慢的情况）",{desc:"95% 的请求比这更快拿到第一个字 · 越短越好"})}</div>`+dataDetails(tbl),"同时请求");
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
  const rows=[];
  labels.forEach(l=>runs.forEach(x=>{const q=x.ph.find(z=>z.label===l);if(!q)return;
    rows.push([esc(l)+(runs.length>1?` <span class="run-tag ${x.tag.toLowerCase()}">${x.tag}</span>`:""),fmtInt(q.in_tokens),fmtInt(q.prefill_tps_med),fmtSec(q.ttft_med_s)])}));
  const tbl=table(["输入长度","实际 token 数","读入速度（token/秒）","首字等待（秒）"],rows);
  return sec(p+"-prefill","输入越长，要等多久",`只有 1 个请求时，不同输入长度下的${term("prefill")}和${term("ttft")}`,
    `<div class="grid-2">${ccard(p+"PreTps",term("prefill"),{desc:"每秒读入多少 token · 越高越好"})}
      ${ccard(p+"PreTtft",term("ttft"),{desc:"输入越长通常要等越久 · 越短越好"})}</div>`+dataDetails(tbl),"输入长度");
}
function drawPrefill(a,b,p){
  const runs=runSeries(a,b,prefillPoints);if(!runs.length)return;
  const labels=lenLabels(runs);
  const get=(x,l,k)=>{const q=x.ph.find(z=>z.label===l);return q&&q[k]!=null?q[k]:null};
  const ser=k=>runs.map(x=>({name:x.tag,color:x.color,data:labels.map(l=>get(x,l,k))}));
  const title=i=>{const q=runs.map(x=>x.ph.find(z=>z.label===labels[i])).find(Boolean);return `输入 ${labels[i]}${q?`（约 ${fmtInt(q.in_tokens)} token）`:""}`};
  lineChart(p+"PreTps",{cats:labels,xName:"输入长度",unit:"token/秒",digits:0,series:ser("prefill_tps_med"),area:true,tip:{title}});
  lineChart(p+"PreTtft",{cats:labels,xName:"输入长度",unit:"秒",digits:2,series:ser("ttft_med_s"),tip:{title}});
}

/* ---------- 长输入 + 同时请求(矩阵) ---------- */
function matrixPhase(r){const p=phase(r,"prefill_conc");return p&&p.points.length?p.points:null}
function matrixSection(a,b,p){
  const pa=phase(a,"prefill_conc"),pb=b?phase(b,"prefill_conc"):null;
  if(!pa||!pa.points.length)return "";
  const two=!!pb;
  let t=`<div class="table-wrap"><table class="table"><thead><tr><th>输入长度</th><th>首字等待 平均（毫秒）</th><th>出字间隔 平均（毫秒）</th><th>总读入速度（token/秒）</th><th>总生成速度（token/秒）</th><th>成功</th></tr></thead><tbody>`;
  pa.points.forEach(q=>{
    const z=two?pb.points.find(x=>x.label===q.label)||null:null;
    const det=(x,who)=>x?`<b>${who}</b> 每个请求的读入速度：${(x.stream_prefill_tps||[]).map(v=>fmtInt(v)).join(" / ")} token/秒；每个请求的生成速度：${(x.stream_decode_tps||[]).map(v=>fmt(v)).join(" / ")} token/秒`:"";
    t+=`<tr class="expandable" data-expand aria-expanded="false"><td>${icon("chevron-right","icon-sm")}${esc(q.label)}<span class="sub">${fmtInt(q.in_tokens)} token</span></td>
      <td>${abCell(q.ttft_avg_ms,z&&z.ttft_avg_ms,v=>fmtInt(v),two)}</td><td>${abCell(q.itl_avg_ms,z&&z.itl_avg_ms,v=>fmt(v),two)}</td>
      <td>${abCell(q.prefill_tps_agg,z&&z.prefill_tps_agg,v=>fmtInt(v),two)}</td><td>${abCell(q.decode_tps_agg,z&&z.decode_tps_agg,v=>fmt(v),two)}</td>
      <td>${q.ok} / ${q.ok+q.fail}${two?`<span class="sub">B ${z?z.ok+" / "+(z.ok+z.fail):"—"}</span>`:""}</td></tr>
      <tr class="detail" hidden><td colspan="6">${det(q,"A")}${z?"<br>"+det(z,"B"):""}</td></tr>`;
  });
  t+=`</tbody></table></div>`;
  const sums=[[pa.summary,"A"],two&&[pb.summary,"B"]].filter(x=>x&&x[0]);
  if(sums.length)t+=`<div class="table-caption">汇总（点上表的行可展开看每个请求）</div>`+table(["测试","读入速度 最低–最高 / 平均","总生成速度 最低–最高 / 平均","单个请求读入 一般 / 较慢 / 最慢","单个请求生成 一般 / 较慢 / 最慢"],
    sums.map(([s,who])=>[`<span class="run-tag ${who.toLowerCase()}">${who}</span>`,`${fmtInt(s.prefill_min)}–${fmtInt(s.prefill_max)} / <b>${fmtInt(s.prefill_avg)}</b>`,
      `${fmt(s.decode_min)}–${fmt(s.decode_max)} / <b>${fmt(s.decode_avg)}</b>`,`${fmtInt(s.per_stream_prefill_p50)} / ${fmtInt(s.per_stream_prefill_p90)} / ${fmtInt(s.per_stream_prefill_p95)}`,
      `${fmt(s.per_stream_decode_p50)} / ${fmt(s.per_stream_decode_p90)} / ${fmt(s.per_stream_decode_p95)}`]));
  return sec(p+"-matrix",`长输入时同时 ${pa.conc||""} 个请求`,`每种输入长度下同时发 ${pa.conc||"多"} 个请求，看要等多久、总速度多少`,
    `<div class="grid-3">${ccard(p+"MxTtft",term("ttft")+"（平均）",{desc:"越短越好"})}
      ${ccard(p+"MxPre","总"+term("prefill"),{desc:"所有请求合计 · 越高越好"})}
      ${ccard(p+"MxDec",term("agg"),{desc:"所有请求合计 · 越高越好"})}</div>`+dataDetails(t),"长输入并发");
}
function drawMatrix(a,b,p){
  const runs=runSeries(a,b,matrixPhase);if(!runs.length)return;
  const labels=lenLabels(runs);
  const get=(x,l,k,f=v=>v)=>{const q=x.ph.find(z=>z.label===l);return q&&q[k]!=null?f(q[k]):null};
  const title=i=>`输入 ${labels[i]}`;
  barChart(p+"MxTtft",{cats:labels,unit:"秒",digits:2,series:runs.map(x=>({name:x.tag,color:x.color,data:labels.map(l=>get(x,l,"ttft_avg_ms",v=>v/1000))})),tip:{title}});
  barChart(p+"MxPre",{cats:labels,unit:"token/秒",digits:0,series:runs.map(x=>({name:x.tag,color:x.color,data:labels.map(l=>get(x,l,"prefill_tps_agg"))})),tip:{title}});
  barChart(p+"MxDec",{cats:labels,unit:"token/秒",series:runs.map(x=>({name:x.tag,color:x.color,data:labels.map(l=>get(x,l,"decode_tps_agg"))})),tip:{title}});
}

/* ---------- 单个请求的生成细节 ---------- */
function decodeStats(c){
  if(!c)return null;
  const runs=c.runs||[];
  const m=k=>median(runs.map(r=>r[k]));
  return{out:c.out_tokens,tps:c.decode_tps_med,best:c.decode_tps_best,tpot:m("tpot_ms"),p50:c.itl_p50_ms_med,p95:m("itl_p95_ms"),p99:m("itl_p99_ms"),jit:m("itl_jitter_ms"),burst:c.spec_burst_med};
}
function decodeSection(a,b,p){
  const da=phase(a,"decode"),db=b?phase(b,"decode"):null;if(!da)return "";
  const rows=[];
  for(const lang of ["zh","en"]){
    [[da,"A"],[db,"B"]].forEach(([d,tag])=>{if(!d)return;const s=decodeStats(d.cases.find(c=>c.lang===lang));if(!s)return;
      rows.push([(lang==="zh"?"中文":"英文")+(db?` <span class="run-tag ${tag.toLowerCase()}">${tag}</span>`:"")+`<span class="sub">每次写 ${s.out} token</span>`,
        fmt(s.tps),fmt(s.best),fmt(s.tpot,2),fmt(s.p50),fmt(s.p95),fmt(s.p99),fmt(s.jit),fmt(s.burst,2)])});
  }
  const tbl=table(["内容",`${term("decode")}（token/秒）`,"最快一次","平均每个 token（毫秒）",`${term("itl")} 一般`,"较慢","最慢",term("jitter","波动")+"（毫秒）",term("burst")],rows);
  const sp=["zh","en"].map(l=>{const s2=decodeStats(da.cases.find(c=>c.lang===l));return s2?`${l==="zh"?"中文":"英文"} <b>${fmt(s2.tps)}</b>`:""}).filter(Boolean).join("、");
  return sec(p+"-decode","单个请求写得多快、稳不稳",`只有 1 个请求时每秒能写 ${sp} 个 token；下面是${term("itl")}，越短看起来越流畅。${term("burst")}明显大于 1 通常表示开了投机解码`,
    ccard(p+"DecItl",term("itl")+"（毫秒）",{desc:`${term("pct","一般 / 较慢 / 最慢")}三种情况，颜色越深越慢 · 越短越好`,h:300})+dataDetails(tbl),"单个请求");
}
function drawDecode(a,b,p){
  const runs=runSeries(a,b,r=>phase(r,"decode"));if(!runs.length)return;
  const st=(x,lang)=>decodeStats(x.ph.cases.find(c=>c.lang===lang));
  const cats=[],v={p50:[],p95:[],p99:[]};
  [["zh","中文"],["en","英文"]].forEach(([l,ln])=>runs.forEach(x=>{const s2=st(x,l);if(!s2)return;
    cats.push(runs.length>1?`${ln} · ${x.tag}`:ln);v.p50.push(s2.p50);v.p95.push(s2.p95);v.p99.push(s2.p99)}));
  barChart(p+"DecItl",{cats,unit:"毫秒",labels:true,series:[{name:"一般",color:mix(C.a,C.surface,.58),data:v.p50},
    {name:"较慢",color:mix(C.a,C.surface,.28),data:v.p95},{name:"最慢",color:C.a,data:v.p99}]});
}

/* ---------- 旧版测试的长上下文阶段 ---------- */
function longctxSection(a,b,p){
  const pa=phase(a,"longctx");if(!pa||!pa.points||!pa.points.length)return "";
  const tbl=table(["输入 token","首字等待（秒）","读入速度（token/秒）","生成速度（token/秒）","出字间隔 一般 / 较慢（毫秒）"],
    pa.points.map(q=>[fmtInt(q.in_tokens),fmtSec(q.ttft_s),fmtInt(q.prefill_tps),fmt(q.decode_tps),`${fmt(q.itl_p50_ms)} / ${fmt(q.itl_p95_ms)}`]));
  if(pa.points.length<3)return sec(p+"-longctx","超长输入（旧版测试项）","早期版本的长上下文测试结果，数据点太少，直接列出",tbl,"超长输入");
  return sec(p+"-longctx","超长输入（旧版测试项）","早期版本的长上下文测试结果",
    `<div class="grid-2">${ccard(p+"LcTtft",term("ttft"),{desc:"越短越好"})}${ccard(p+"LcDec",term("decode"),{desc:"读完长输入后的生成速度 · 越高越好"})}</div>`+dataDetails(tbl),"超长输入");
}
function drawLongctx(a,b,p){
  const pa=phase(a,"longctx");if(!pa||!pa.points||pa.points.length<3)return;
  const cats=pa.points.map(q=>fmtAxis(q.in_tokens));
  lineChart(p+"LcTtft",{cats,xName:"输入 token",unit:"秒",digits:2,series:[{name:"A",color:C.a,data:pa.points.map(q=>q.ttft_s)}]});
  lineChart(p+"LcDec",{cats,xName:"输入 token",unit:"token/秒",series:[{name:"A",color:C.a,data:pa.points.map(q=>q.decode_tps)}]});
}

/* ---------- 模拟真实业务(scn_*) ---------- */
const SCN_LABEL=Object.fromEntries(SCN_TPL.map(([id,name])=>[id,name]));
const kLabel=v=>(v/1000).toFixed(v%1000?1:0)+"K";
function retryTag(p){return (p.attempts||1)>1?` <span class="badge is-warn" title="这一档失败后整档重跑过，明细见导出的报告">重跑 ${p.attempts} 次</span>`:""}
function scnSection(a,b,p){
  const blocks=[];
  (a.phases||[]).forEach((ph,idx)=>{
    const pid=ph.id||"";if(!pid.startsWith("scn_"))return;
    const tpl=pid.slice(4),isRag=tpl==="rag",key=isRag?"ctx_tokens":"conc";
    const pb=b?(b.phases||[]).find(x=>x.id===pid):null,two=!!pb;
    const labelName=(ph.task&&ph.task.label)||SCN_LABEL[tpl]||tpl;
    const hasJson=(ph.points||[]).some(x=>x.json_total);
    const head=[isRag?"资料长度（token）":"同时请求数","成功",`${term("rps")}`,`${term("ttft")} 较慢（秒）`,`${term("e2e")} 较慢（秒）`,"平均输出 token","最多积压"];
    if(hasJson)head.push("JSON 合格");
    const rows=(ph.points||[]).map(q=>{
      const z=two?(pb.points||[]).find(x=>x[key]===q[key]):null;
      const r=[fmtInt(q[key])+retryTag(q)+(q.pool_wrapped?` <span class="badge" title="任务集用完一轮后重复使用">已循环</span>`:""),
        `${q.ok} / ${q.total}${q.fail?`<span class="sub">失败 ${q.fail}</span>`:""}`,abCell(q.req_s,z&&z.req_s,v=>fmt(v,2),two),
        abCell(q.ttft_p95_s,z&&z.ttft_p95_s,fmtSec,two),abCell(q.e2e_p95_s,z&&z.e2e_p95_s,fmtSec,two),
        `${fmt(q.out_tokens_avg,0)}${q.out_tokens_p90!=null?`<span class="sub">多的时候 ${fmt(q.out_tokens_p90,0)}</span>`:""}`,q.max_inflight!=null?fmtInt(q.max_inflight):"—"];
      if(hasJson)r.push(q.json_total!=null?`${fmtInt(q.json_ok)} / ${fmtInt(q.json_total)}<span class="sub">${q.json_rate!=null?fmt(100*q.json_rate,0)+"%":""}</span>`:"—");
      return r;
    });
    const t=ph.task||{};
    const jOk=(ph.points||[]).reduce((s2,q)=>s2+(q.json_ok||0),0),jTot=(ph.points||[]).reduce((s2,q)=>s2+(q.json_total||0),0);
    const desc=[jTot?`JSON 合格率 ${fmt(100*jOk/jTot,0)}%`:"",t.max_tokens?"每次最多 "+t.max_tokens+" token":"",t.requests_per_worker?"每个并发发 "+t.requests_per_worker+" 次":"",
      t.images?"图片 "+t.images+" 张"+(t.images_per_request?"，每次带 "+t.images_per_request+" 张":""):"",t.pool_size?"任务集 "+t.pool_size+" 条":"",
      Array.isArray(t.rag_ctx)?"资料长度 "+t.rag_ctx.map(x=>(x/1000)+"K").join(" / "):""].filter(Boolean).join(" · ");
    blocks.push(`<div class="stack" style="margin-bottom:20px"><div><h3 class="ccard-title" style="font-size:15px">${esc(labelName)}</h3>
      <p class="ccard-desc">按真实方式结束（不强制写满长度）${desc?" · "+esc(desc):""}</p></div>
      <div class="grid-2">${ccard(`${p}Scn${idx}Rps`,term("rps"),{desc:(isRag?"横轴是资料长度":"横轴是同时请求数")+" · 越高越好",h:240})}
        ${ccard(`${p}Scn${idx}E2e`,term("e2e")+"（较慢的情况）",{desc:"95% 的请求比这更快拿到完整回答 · 越短越好",h:240})}</div>${dataDetails(table(head,rows))}</div>`);
  });
  if(!blocks.length)return "";
  return sec(p+"-scn","模拟真实业务","不同业务类型的请求按真实方式结束，看每秒能处理多少、用户要等多久",blocks.join(""),"真实业务");
}
function drawScn(a,b,p){
  (a.phases||[]).forEach((ph,idx)=>{
    const pid=ph.id||"";if(!pid.startsWith("scn_"))return;
    const isRag=pid==="scn_rag",key=isRag?"ctx_tokens":"conc";
    const pb=b?(b.phases||[]).find(x=>x.id===pid):null;
    const keys=[...new Set([...(ph.points||[]),...((pb&&pb.points)||[])].map(q=>q[key]))].sort((x,y)=>x-y);
    const runs=[{tag:"A",color:C.a,pts:ph.points||[]},pb?{tag:"B",color:C.b,pts:pb.points||[]}:null].filter(Boolean);
    const get=(x,k,f)=>{const q=x.pts.find(z=>z[key]===k);return q&&q[f]!=null?q[f]:null};
    const cats=keys.map(k=>isRag?kLabel(k):String(k)),xName=isRag?"资料长度（token）":"同时请求数";
    const title=i=>isRag?`资料约 ${fmtInt(keys[i])} token`:`同时 ${keys[i]} 个请求`;
    lineChart(`${p}Scn${idx}Rps`,{cats,xName,unit:"个/秒",digits:2,series:runs.map(x=>({name:x.tag,color:x.color,data:keys.map(k=>get(x,k,"req_s"))})),area:true,tip:{title}});
    lineChart(`${p}Scn${idx}E2e`,{cats,xName,unit:"秒",digits:2,series:runs.map(x=>({name:x.tag,color:x.color,data:keys.map(k=>get(x,k,"e2e_p95_s"))})),
      tip:{title,sub:i=>runs.map(x=>`${x.tag} 首字等待较慢 ${fmtSec(get(x,keys[i],"ttft_p95_s"))} 秒`).join(" · ")}});
  });
}

/* ---------- 回放真实请求 ---------- */
function replaySection(a,b,p){
  const pa=phase(a,"replay"),pb=b?phase(b,"replay"):null,oa=phase(a,"openloop"),ob=b?phase(b,"openloop"):null;
  if(!pa&&!oa)return "";
  let body="";
  if(pa){
    const two=!!pb,pool=pa.pool||{};
    const rows=pa.points.map(q=>{const z=two?pb.points.find(x=>x.conc===q.conc):null;
      return [fmtInt(q.conc)+retryTag(q),abCell(q.req_s,z&&z.req_s,v=>fmt(v,2),two),abCell(q.ttft_p95_s,z&&z.ttft_p95_s,fmtSec,two),abCell(q.e2e_p95_s,z&&z.e2e_p95_s,fmtSec,two),
        `${fmtInt(q.prompt_tokens_avg)} / ${fmtInt(q.out_tokens_avg)}`,fmtInt(q.max_inflight),`${q.ok} / ${q.total}${q.fail?`<span class="sub">失败 ${q.fail}</span>`:""}`]});
    body+=`<div class="stack" style="margin-bottom:20px"><div><h3 class="ccard-title" style="font-size:15px">${term("closed")}</h3>
      <p class="ccard-desc">请求池 ${fmtInt(pool.size)} 条${pool.wrapped?"（已循环使用，后面的请求可能因为重复内容复用而偏快）":""}${a.replay&&a.replay.file?" · "+esc(a.replay.file):""}</p></div>
      <div class="grid-2">${ccard(p+"RpRps",term("rps"),{desc:"横轴是同时请求数 · 越高越好",h:240})}${ccard(p+"RpE2e",term("e2e")+"（较慢的情况）",{desc:"越短越好",h:240})}</div>
      ${dataDetails(table(["同时请求数",term("rps"),"首字等待 较慢（秒）","完整响应 较慢（秒）","平均输入 / 输出 token","最多积压","成功"],rows))}</div>`;
  }
  if(oa){
    const two=!!ob;
    const rows=oa.points.map(q=>{const z=two?ob.points.find(x=>x.rate===q.rate):null;
      const lag=q.completed_rps!=null&&q.rate&&q.completed_rps<q.rate*0.9;
      return [fmt(q.rate,q.rate<10?1:0)+retryTag(q),`${fmtInt(q.sent)}${q.shed?`<span class="sub">丢弃 ${q.shed}</span>`:""}`,
        abCell(q.completed_rps,z&&z.completed_rps,v=>fmt(v,2),two)+(lag?`<span class="sub warn">跟不上目标速率</span>`:""),
        abCell(q.ttft_p95_s,z&&z.ttft_p95_s,fmtSec,two),abCell(q.e2e_p95_s,z&&z.e2e_p95_s,fmtSec,two),fmtInt(q.max_inflight),`${q.ok} / ${q.total}${q.fail?`<span class="sub">失败 ${q.fail}</span>`:""}`]});
    body+=`<div class="stack"><div><h3 class="ccard-title" style="font-size:15px">${term("open")}</h3>
      <p class="ccard-desc">按设定速率随机间隔地发请求；两次测试的发送时间点完全相同。${term("inflight")}一直往上涨，说明服务跟不上</p></div>
      <div class="grid-2">${ccard(p+"OlInf",term("inflight")+"数量随时间变化",{desc:"横轴是开始后的秒数",h:260})}${ccard(p+"OlRate","目标速率 vs 实际完成速率",{desc:"实际明显低于目标说明处理不过来",h:260})}</div>
      ${dataDetails(table(["目标速率（个/秒）","发出","实际完成（个/秒）","首字等待 较慢（秒）","完整响应 较慢（秒）","最多积压","成功"],rows))}</div>`;
  }
  return sec(p+"-replay","回放真实请求","用线上导出的真实请求施压",body,"真实回放");
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
    runs.forEach(([tag,ph,base],ri)=>ph.points.forEach((pt,j)=>{
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
    barChart(p+"OlRate",{cats:rates.map(r=>r+" 个/秒"),unit:"个/秒",digits:2,labels:true,series:[{name:"目标速率",color:C.grid&&C.axis?C.axis:"#999",data:rates},...done]});
  }
}

/* ---------- 服务端状态 ---------- */
function metricsUsable(r){return (r.metrics_samples||[]).filter(m=>m.gpu_cache_usage!=null||m.prefix_cache_hit!=null)}
function engineSection(a,b,p){
  if(!metricsUsable(a).length)return "";
  return sec(p+"-engine","服务端状态",`测试期间服务端的${term("kv")}和${term("prefix")}（来自 vLLM /metrics）`,
    ccard(p+"Eng",term("kv")+" 与 "+term("prefix"),{desc:"显存缓存接近 100% 时新请求要排队；复用率越高越省时",h:260}),"服务端");
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

/* ---------- 组装 ---------- */
function perfSectionsHTML(a,b,p){
  return [concSection,prefillSection,matrixSection,decodeSection,longctxSection,scnSection,replaySection,engineSection].map(f=>f(a,b,p)).join("");
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
      {action:`<button class="btn btn-primary" data-toggle="launcher">${icon("plus")}新建速度测试</button>`});
    return;
  }
  const seq=++renderSeq;
  try{await ensureRuns([idA,RUNS[idB]&&idB!==idA?idB:""])}
  catch(e){$("dashEmpty").innerHTML=emptyState("加载测试详情失败",e.message,{iconName:"alert",inline:true});return}
  if(seq!==renderSeq)return;  /* 期间切换了选择, 以最新一次为准 */
  const a=FULL[idA],b=RUNS[idB]&&idB!==idA?FULL[idB]:null;
  $("dashEmpty").innerHTML="";body.hidden=false;
  const hints=perfAnomalies(a);
  body.innerHTML=`<div class="stack">
      ${summaryCard("结论",perfConclusions(a,b),perfMetaLine(a)+(b?`<br>B：${esc(label(b))}`:""))}
      ${hints.length?alertBox("warn",`<b>需要注意</b><ul class="hint-list">${hints.map(h=>`<li>${esc(h)}</li>`).join("")}</ul>`):""}
      <div class="kpi-grid">${perfKpis(a,b)}</div></div>`+perfSectionsHTML(a,b,"d");
  disposeDetached();
  drawPerfCharts(a,b,"d");
  buildJump("dashJump",body);
}

/* ============================================================
   速度对比
   ============================================================ */
function swapCmp(){const a=$("cmpA").value,b=$("cmpB").value;if(!b)return;$("cmpA").value=b;$("cmpB").value=a;renderCmp()}
function runCard(r,tag){
  return `<div class="card cmp-run"><span class="run-tag ${tag.toLowerCase()}">${tag}</span><div style="min-width:0">
    <div class="cmp-run-name">${esc(r.model||"?")}</div>
    <div class="cmp-run-meta">${esc([runFw(r)||"推理框架未填写",(SUITE_NAME[r.suite]||r.suite||"")+"规模",r.tag,hostOf(r.url),timeText(r.started_utc)].filter(Boolean).join(" · "))}</div></div></div>`;
}
function cmpRows(a,b){
  const ma=perfCtx(a),mb=perfCtx(b);
  return [...PERF_METRICS,...CMP_EXTRA].map(k=>{
    const va=safeVal(k.val,ma),vb=safeVal(k.val,mb),same=sameRef(k,ma,mb),d=same?pctChange(va,vb):null;
    return{k,label:metricLabel(k,ma),va,vb,d,same,refB:same?"":refText(k,mb),gain:d==null?null:d*k.dir};  /* gain>0 表示 B 更好 */
  }).filter(x=>x.va!=null||x.vb!=null);
}
async function renderCmp(){
  if(!RUNS_LOADED)return;
  const idA=$("cmpA").value,idB=$("cmpB").value;
  const el=$("cmpBody");
  if(!RUNS[idA]){el.innerHTML=emptyState("还没有速度测试","把两次速度测试放在一起看谁更快、快多少。先在「速度测试」页完成至少两次测试");buildJump("cmpJump",null);return}
  if(!RUNS[idB]||idA===idB){
    el.innerHTML=`<div class="cmp-runs">${runCard(RUNS[idA],"A")}</div><div style="margin-top:16px">`+
      emptyState("再选一个测试 B","比如换了推理框架、量化方式或显卡之后再测一次，放在一起比",{iconName:"compare"})+`</div>`;
    buildJump("cmpJump",null);return;
  }
  const seq=++cmpSeq;
  try{await ensureRuns([idA,idB])}catch(e){el.innerHTML=emptyState("加载测试详情失败",e.message,{iconName:"alert"});return}
  if(seq!==cmpSeq)return;
  const a=FULL[idA],b=FULL[idB];
  const rows=cmpRows(a,b),both=rows.filter(x=>x.gain!=null);
  const better=both.filter(x=>x.gain>=1).sort((p,q)=>q.gain-p.gain),worse=both.filter(x=>x.gain<=-1).sort((p,q)=>p.gain-q.gain);
  const concl=[];
  concl.push({tone:worse.length>better.length?"warn":better.length?"good":"info",
    html:`${both.length} 项指标里，B 有 <b>${better.length}</b> 项更好、<b>${worse.length}</b> 项更差、${both.length-better.length-worse.length} 项基本持平（差别小于 1%）。`});
  if(better.length)concl.push({tone:"good",html:"B 更好的地方："+better.slice(0,3).map(x=>`${esc(x.label)} <b>${fmt(Math.abs(x.d),1)}%</b>`).join("；")+"。"});
  if(worse.length)concl.push({tone:"bad",html:"B 更差的地方："+worse.slice(0,3).map(x=>`${esc(x.label)} <b>${fmt(Math.abs(x.d),1)}%</b>`).join("；")+"。"});
  const notSame=rows.filter(x=>!x.same&&x.va!=null&&x.vb!=null);
  if(notSame.length)concl.push({tone:"info",html:`${notSame.length} 项因为两次测试的档位不同（例如最多同时请求数、最长输入不一样）没有计入：${notSame.map(x=>esc(x.label)).join("、")}。`});
  const ov=[a,b].map(r=>(r.overrides||{}).fixed_output);
  if(ov[0]!==ov[1])concl.push({tone:"warn",html:"两次测试的输出长度设置不同（一次固定、一次不固定），速度类指标不能直接比较。"});
  if(a.suite!==b.suite)concl.push({tone:"info",html:`两次测试规模不同（${esc(SUITE_NAME[a.suite]||a.suite)} / ${esc(SUITE_NAME[b.suite]||b.suite)}），只比较两边都有的项目。`});
  const kpis=rows.map(x=>{
    const dg=x.k.digits??1,f=v=>v==null?"—":(dg===0?fmtInt(v):fmt(v,dg));
    const tip=x.k.term&&TERMS[x.k.term]?TERMS[x.k.term].name+"（"+TERMS[x.k.term].tech+"）："+TERMS[x.k.term].desc:"";
    return `<div class="kpi"${tip?` title="${esc(tip)}"`:""}><div class="kpi-head"><span class="kpi-label">${esc(x.label)}</span>${x.same?deltaPill(x.va,x.vb,x.k.dir):`<span class="delta flat" title="B 是${esc(x.refB)}">档位不同</span>`}</div>
      <div class="kpi-value" style="font-size:22px">${f(x.va)}<span class="faint" style="font-size:14px;font-weight:400"> → </span>${f(x.vb)}<small>${esc(x.k.unit)}</small></div>
      <div class="kpi-sub">A → B · ${x.k.dir<0?"越低越好":"越高越好"}${x.same?"":` · B 是${esc(x.refB)}，不可比`}</div></div>`;
  }).join("");
  const diff=table(["指标","方向","A","B","差值","变化"],rows.map(x=>{
    const dg=x.k.digits??1,dd=x.va!=null&&x.vb!=null&&x.same?x.vb-x.va:null;
    const cls=dd==null||Math.abs(dd)<1e-9?"na":(dd*x.k.dir>0?"up":"down");
    return [`${esc(x.label)}<span class="sub">${esc(x.k.unit)}</span>`,`<span class="faint">${x.k.dir<0?"越低越好":"越高越好"}</span>`,fmt(x.va,dg),fmt(x.vb,dg),
      `<span class="${cls}">${dd==null||!x.same?"—":(dd>=0?"+":"")+fmt(dd,dg)}</span>`,x.same?deltaPill(x.va,x.vb,x.k.dir):`<span class="delta flat">档位不同</span>`];
  }));
  const h=Math.max(220,both.length*30+60);
  el.innerHTML=`<div class="stack"><div class="cmp-runs">${runCard(a,"A")}${runCard(b,"B")}</div>
      ${summaryCard("对比结论",concl)}</div>`+
    sec("c-diff","B 相对 A 的变化","往右是 B 更好，往左是 B 更差；延迟类指标（越短越好）已按“好坏”方向换算",
      ccard("cDiff","各项指标的变化（%）",{desc:"灰色表示差别小于 1%，基本持平",h,table:diff})+
      `<div class="kpi-grid" style="margin-top:16px">${kpis}</div>`,"变化一览")+
    perfSectionsHTML(a,b,"c");
  disposeDetached();
  drawDiffChart("cDiff",both);
  drawPerfCharts(a,b,"c");
  buildJump("cmpJump",el);
}
function drawDiffChart(id,rows){
  if(!rows.length){chartEmpty(id,"两次测试没有共同的指标");return}
  const lim=niceMax(Math.max(8,...rows.map(x=>Math.abs(x.gain)))*1.12);
  const colorOf=g=>Math.abs(g)<1?C.axis:(g>0?C.goodMark:C.badMark);
  setChart(id,baseOption({
    grid:{left:4,right:24,top:8,bottom:4,containLabel:true},
    xAxis:Object.assign(axisValue({min:-lim,max:lim,fmt:v=>(v>0?"+":"")+Math.round(v)+"%"}),{splitNumber:4}),
    yAxis:axisCat(rows.map(x=>x.label),{inverse:true,labelWidth:220,labelColor:C.text2}),
    tooltip:Object.assign(baseOption().tooltip,{trigger:"item",formatter:p=>{const x=rows[p.dataIndex],dg=x.k.digits??1;
      return tt(x.label,[["","A",fmt(x.va,dg)+" "+x.k.unit],["","B",fmt(x.vb,dg)+" "+x.k.unit]],
        `数值变化 ${x.d>=0?"+":""}${fmt(x.d,1)}% · ${Math.abs(x.gain)<1?"基本持平":x.gain>0?"B 更好":"B 更差"}（${x.k.dir<0?"越低越好":"越高越好"}）`)}}),
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
bindFormMemory("llm-bench-pro-iq-form",["iqBase","iqModel","iqConc","iqTag","iqTier","iqProxy","iqSampling","iqTemp","iqTopP","iqTopK",
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
  }catch(e){$("iqBankInfo").textContent="题集列表加载失败："+e.message}
}
function bankInfo(){
  const b=IQ_BANKS.find(x=>x.bank_id===$("iqBank").value);
  $("iqBankInfo").textContent=b?`共 ${b.total} 题：`+(b.subjects||[]).map(s=>`${s.name} ${s.n}`).join("、"):"还没有题集，请在「更多设置」里点「更新题集」";
}
async function bankUpdate(){
  const btn=$("iqBtnBank");setBusy(btn,true);
  msg("iqMsg","info","正在下载题集（MMLU、GSM8K、MATH-500、ARC、HellaSwag、C-Eval、指令遵循），大约 3–5 分钟，请不要关闭页面");
  try{
    const d=await postJSON("/api/bank-update",{proxy:$("iqProxy").value||""});
    if(!d.ok){msg("iqMsg","error","题集更新失败："+d.error+(d.hint?"\n"+d.hint:""));return}
    msg("iqMsg","success",`题集已更新：${d.bank_id} · ${d.total} 题`);
    await loadBanks();$("iqBank").value=d.bank_id;bankInfo();
  }finally{setBusy(btn,false)}
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
function _renderIq(){
  if(!IQ_LOADED)return;
  const el=$("iqResult");
  const mainId=$("iqMainSel").value,a=IQ_RUNS[mainId];
  renderIqCmpList(mainId);
  if(!a){el.innerHTML=emptyState("还没有能力测试","用公开的标准考题（数学、常识、推理、中文、按要求作答）考模型，看答对多少。点右上角「新建能力测试」开始",
    {action:`<button class="btn btn-primary" data-toggle="iqLauncher">${icon("plus")}新建能力测试</button>`});buildJump("iqJump",null);return}
  const series=[{r:a,color:C.series[0],tag:"A"},...[...IQ_CMP].filter(id=>IQ_RUNS[id]).slice(0,5).map((id,i)=>({r:IQ_RUNS[id],color:C.series[i+1],tag:String.fromCharCode(66+i)}))];
  const base=a.overall||{};
  /* ---- 成绩块: A 用大号数字, 对比项显示与 A 的差距和是否可信 ---- */
  const tiles=series.map(s=>{
    const o=s.r.overall||{},tk=tokStat(s.r);
    const who=`<span class="run-tag" style="background:${s.color}">${s.tag}</span> ${esc((s.r.model||"?")+(runFw(s.r)?" · "+runFw(s.r):""))}`;
    const sub=o.n?`${term("ci")} ${fmt(o.ci_lo,1)}–${fmt(o.ci_hi,1)}% · 答对 ${o.correct}/${o.n} 题${o.macro_acc!=null?` · ${term("macro")} ${fmt(o.macro_acc,1)}%`:""}`+
      `<br>${s.r.thinking?"思考模式":"不思考"} · ${esc(samplingText(s.r.sampling)||"采样未记录")}${tk.per!=null?` · 平均每题输出 ${fmt(tk.per,0)} token`:""}`:
      `测试没有完成（${esc(STATUS_NAME[s.r.status]||s.r.status||"")}）`;
    const issues=iqIssues(s.r);
    return `<div class="kpi${s.tag==="A"?" is-hero":""}"><div class="kpi-head"><span class="kpi-label" style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">${who}</span>
        ${s.tag!=="A"?deltaPill(base.acc,o.acc,1,{mode:"pp",prefix:"比 A "}):""}</div>
      <div class="kpi-value">${o.acc!=null?fmt(o.acc,1):"—"}<small>%</small></div>
      <div class="kpi-sub">${sub}</div>
      ${s.tag!=="A"?`<div class="kpi-sub" data-sig-card="${esc(s.r.run_id)}">正在计算差异是否可信…</div>`:""}
      ${issues.length?`<div class="kpi-sub warn">${esc(issues.join(" · "))}</div>`:""}</div>`;
  }).join("");
  /* ---- 提示 ---- */
  let alerts="";
  series.forEach(s=>{const w=iqVersionWarning(s.r);if(w)alerts+=alertBox("warn",`<b>${s.tag}</b>：${esc(w)}`)});
  if(Array.isArray(a.warnings)&&a.warnings.length)alerts+=alertBox("warn",`<b>A 自检提示</b>：${a.warnings.map(esc).join("；")}`);
  const errN=(a.overall||{}).errors||0;
  if(a.status==="done"&&errN&&SERVER.iq_version&&a.iq_version===SERVER.iq_version)
    alerts+=alertBox("info",`A 有 ${errN} 题请求失败（已记为答错）。重试只会重新回答这些题，其他结果不变。`,
      `<button class="btn btn-secondary btn-sm" onclick="iqResume('${esc(a.run_id)}')">${icon("play")}重试失败的题</button>`);
  if(["cancelled","interrupted","failed"].includes(a.status)){
    const canResume=SERVER.iq_version&&a.iq_version===SERVER.iq_version;
    const doneN=(a.subjects||[]).reduce((t,x)=>t+(x.n||0),0);
    alerts+=alertBox("info",`A ${esc(STATUS_NAME[a.status]||a.status)}${a.error?"（"+esc(a.error)+"）":""}：已完成 ${a.subjects?a.subjects.length:0} 个科目共 ${doneN} 题，没做完的科目里已答的题也保存了，请求失败的题接着跑时会重新回答。${canResume?"接着跑会沿用原来的服务地址、采样和题量，使用新建面板里填的 API Key。":"这次测试由其他版本的评测程序生成，不能接着跑。"}`,
      canResume?`<button class="btn btn-secondary btn-sm" onclick="iqResume('${esc(a.run_id)}')">${icon("play")}接着跑</button>`:"");
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
  /* ---- 各科明细表(带错题按钮) ---- */
  let t=`<div class="table-wrap" style="max-height:640px"><table class="table"><thead><tr><th>科目</th><th>题数</th>${series.map(s=>`<th><span class="run-tag" style="background:${s.color}">${s.tag}</span> 正确率</th><th title="平均每题输出多少 token，越少越省">${s.tag} 每题 token</th>`).join("")}<th>A 没答完 / 请求失败</th><th></th></tr></thead><tbody>`;
  const tokCell=(v,v0,self)=>{
    if(!v||!v.n)return `<td class="na">—</td>`;
    const per=v.out_tokens/v.n;
    const d=(!self&&v0&&v0.n&&series.length>1)?`<span class="sub">比 A ${per>=v0.out_tokens/v0.n?"+":""}${fmt((per-v0.out_tokens/v0.n)/(v0.out_tokens/v0.n)*100,0)}%</span>`:"";
    return `<td class="faint">${fmt(per,0)}${d}</td>`;
  };
  (a.subjects||[]).forEach(sub=>{
    const vals=series.map(s=>(s.r.subjects||[]).find(y=>y.id===sub.id)||null);
    const accs=vals.map(v=>v&&v.acc).filter(v=>v!=null);
    const best=accs.length>1?Math.max(...accs):null;
    t+=`<tr><td>${esc(sub.name)}</td><td class="faint">${sub.n}</td>`+vals.map((v,i)=>
      (v==null?`<td class="na">—</td>`:`<td class="${best!=null&&v.acc===best?"best":""}" ${i?`data-sig-cell="${esc(series[i].r.run_id)}|${esc(sub.id)}"`:""}>${fmt(v.acc,1)}%${series.length===1?`<span class="sub">误差范围 ${fmt(v.ci_lo,1)}–${fmt(v.ci_hi,1)}</span>`:""}</td>`)+
      tokCell(v,vals[0],i===0)).join("")+
      `<td class="${(sub.truncated||sub.errors)?"down":"faint"}">${sub.truncated==null?"—":`${sub.truncated} / ${sub.errors||0}`}</td>
      <td><button class="btn btn-ghost btn-sm" data-qb-go="${esc(sub.id)}" data-qb-filter="${sub.correct<sub.n?"bad":"all"}">${sub.correct<sub.n?`看错题（${sub.n-sub.correct}）`:"看题目"}</button></td></tr>`;
  });
  const overall=series.map(s=>s.r.overall&&s.r.overall.acc);
  const bestAll=series.length>1?Math.max(...overall.filter(v=>v!=null)):null;
  const subjAll=series.map(s=>({n:(s.r.subjects||[]).reduce((t2,x)=>t2+(x.n||0),0),out_tokens:(s.r.subjects||[]).reduce((t2,x)=>t2+(x.out_tokens||0),0)}));
  t+=`<tr class="total"><td>总计</td><td class="faint">${base.n??"—"}</td>`+overall.map((v,i)=>
    `<td class="${bestAll!=null&&v===bestAll?"best":""}">${v!=null?fmt(v,1)+"%":"—"}</td>`+tokCell(subjAll[i],subjAll[0],i===0)).join("")+
    `<td class="${(base.truncated||base.errors)?"down":"faint"}">${base.truncated==null?"—":`${base.truncated} / ${base.errors||0}`}</td><td></td></tr></tbody></table></div>`;
  const nSub=(a.subjects||[]).length;
  const barH=Math.max(260,nSub*(series.length*16+14)+70);
  const summ=summaryCard("结论",concl,`题集 ${esc(a.bank_id||"")} · ${esc(budgetText(a))} · 开始于 ${esc(timeText(a.started_utc))}`);
  el.innerHTML=`<div class="stack">${series.length===1?`<div class="hero-row">${tiles}${summ}</div>${alerts}`:`<div class="score-row">${tiles}</div>${alerts}${summ}`}</div>`+
    sec("iq-subj","各科得分","按 A 的成绩从高到低排列；只看一次测试时，横线表示"+term("ci"),
      `<div class="grid-2" style="grid-template-columns:minmax(0,1.4fr) minmax(0,1fr)">${ccard("iqBars","各科正确率",{desc:"越高越好 · 点柱子可以看这一科的题",h:barH})}
        ${ccard("iqRadar","能力分布",{desc:"越往外越好",h:Math.min(460,Math.max(340,barH))})}</div>`,"各科得分")+
    sec("iq-cost","花了多少 token","同样的正确率，用的 token 越少越省时省钱",ccard("iqTok","平均每题输出多少 token",{desc:"越少越省",h:barH}),"token 花费")+
    sec("iq-detail","逐科明细",series.length>1?"加粗的是这一科最高分；比 A 的“差异是否可信”显示在每个格子下方":"点「看错题」直接跳到下面这一科答错的题",t,"逐科明细")+
    sec("iq-items","逐题查看",series.length>1?"每道题的题目、标准答案和各次测试的答案；可以只看两次结果不一样的题":"每道题的题目、标准答案和模型的答案；点「看回答」可以看模型的原话",
      `<div class="qb" id="qb"></div>`,"逐题查看");
  disposeDetached();
  drawIqCharts(series);
  buildJump("iqJump",el);
  qbInit(series);
  /* 差异是否可信: 同一批题逐题比较, 结果异步填入 */
  series.slice(1).forEach(s=>iqCompare(a.run_id,s.r.run_id).then(d=>{
    const card=document.querySelector(`[data-sig-card="${CSS.escape(s.r.run_id)}"]`);
    if(!card)return;
    if(!d||!d.ok){card.textContent="暂时无法判断差异是否可信";return}
    if(!d.same_bank){card.textContent="题集不同，无法逐题比较";return}
    if(!d.overall.n||d.overall.significant==null){card.textContent="没有双方都正常作答的共同题目，无法比较";return}
    const o=d.overall;
    const go=(f,txt)=>`<a href="javascript:void 0" class="qb-link" data-qb-go="" data-qb-filter="${f}" data-qb-vs="${esc(s.r.run_id)}" title="在「逐题查看」里列出这些题">${txt}</a>`;
    card.innerHTML=`<span class="sig ${o.significant?"yes":"no"}">${o.significant?"差异可信":"差异不明显，可能是随机波动"}</span> · ${go("vs-a",`只有 A 答对 ${o.a_only} 题`)}，${go("vs-b",`只有 ${esc(s.tag)} 答对 ${o.b_only} 题`)}`;
    card.title=`${TERMS.sig.tech}：共同题目 ${o.n} 道，p = ${fmtP(o.p)}`;
    Object.entries(d.subjects).forEach(([sid,x])=>{
      const cell=document.querySelector(`[data-sig-cell="${CSS.escape(s.r.run_id+"|"+sid)}"]`);
      if(cell&&x.n)cell.insertAdjacentHTML("beforeend",`<span class="sub sig ${x.significant?"yes":"no"}" title="p = ${fmtP(x.p)}">${x.significant?"差异可信":"差异不明显"}</span>`);
    });
  }));
}
function drawIqCharts(series){
  const a=series[0].r;
  const subs=[...(a.subjects||[])].filter(x=>x.n).sort((x,y)=>(y.acc||0)-(x.acc||0));
  if(!subs.length){chartEmpty("iqBars");chartEmpty("iqRadar");chartEmpty("iqTok");return}
  const names=subs.map(x=>shortSub(x.name));
  const valOf=(s,sub,f)=>{const x=(s.r.subjects||[]).find(y=>y.id===sub.id);return x?f(x):null};
  /* 各科正确率: 横向柱; 只看 A 时加误差范围 */
  const barSeries=series.map(s=>sBar(s.tag,s.color,subs.map(sub=>valOf(s,sub,x=>x.acc)),{horizontal:true}));
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
    xAxis:axisValue({min:0,max:100,fmt:v=>v+"%"}),yAxis:axisCat(names,{inverse:true,labelWidth:150,labelColor:C.text2}),
    tooltip:Object.assign(baseOption().tooltip,{axisPointer:{type:"shadow",shadowStyle:{color:"rgba(128,128,128,.08)"}},formatter:ps=>{
      const sub=subs[ps[0].dataIndex];
      return tt(sub.name,series.map(s=>{const x=(s.r.subjects||[]).find(y=>y.id===sub.id);
        return [s.color,s.tag,x?`${fmt(x.acc,1)}%（${x.correct}/${x.n}）`:"—"]}),series.length===1?`误差范围 ${fmt(sub.ci_lo,1)}–${fmt(sub.ci_hi,1)}%`:"")}}),
    series:barSeries}));
  if(barsInst){barsInst.off("click");barsInst.on("click",p=>{if(p.seriesType==="bar"&&subs[p.dataIndex])qbGo(subs[p.dataIndex].id,"all")})}
  /* 能力分布: 雷达 */
  setChart("iqRadar",baseOption({
    color:series.map(s=>s.color),legend:legendOf(series.map(s=>s.tag)),
    tooltip:Object.assign(baseOption().tooltip,{trigger:"item",formatter:p=>tt(series[p.dataIndex]?series[p.dataIndex].tag:"",subs.map((sub,i)=>["",names[i],p.value[i]!=null?fmt(p.value[i],1)+"%":"—"]))}),
    radar:{indicator:subs.map(sub=>({name:radarName(sub.name),max:100})),radius:"64%",center:["50%","56%"],splitNumber:4,
      axisName:{color:C.text2,fontSize:11},splitLine:{lineStyle:{color:C.grid}},splitArea:{show:false},axisLine:{lineStyle:{color:C.grid}}},
    series:[{type:"radar",symbolSize:6,data:series.map(s=>({name:s.tag,value:subs.map(sub=>valOf(s,sub,x=>x.acc)),
      lineStyle:{width:2,color:s.color},itemStyle:{color:s.color,borderColor:C.surface,borderWidth:1},areaStyle:{color:withAlpha(s.color,.10)}}))}]}));
  /* 平均每题 token */
  barChart("iqTok",{cats:names,horizontal:true,unit:"token",digits:0,catLabelWidth:150,labels:series.length===1,
    series:series.map(s=>({name:s.tag,color:s.color,data:subs.map(sub=>valOf(s,sub,x=>x.n?x.out_tokens/x.n:null))}))});
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
const QB_PAGE=20;
const QB={key:"",main:"",data:null,loading:null,err:"",series:[],subj:"",filter:"all",vs:"",q:"",page:0};
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
    <div class="filter-chips" id="qbChips"></div>
    <div class="qb-list" id="qbList"></div>
    <div class="qb-pager" id="qbPager"></div>`;
  qbRenderList();
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
  const pages=Math.max(1,Math.ceil(rows.length/QB_PAGE));
  QB.page=Math.min(Math.max(0,QB.page),pages-1);
  const view=rows.slice(QB.page*QB_PAGE,(QB.page+1)*QB_PAGE);
  list.innerHTML=view.length?view.map(qbCard).join(""):
    emptyState(needle?"没有找到相关的题":"这里没有题",needle?"换个关键词试试":"换一个筛选条件看看",{iconName:needle?"search":"inbox",inline:true});
  /* 实际没被截断的题目去掉「展开全文」 */
  list.querySelectorAll(".qcard-q.is-clamp").forEach(el=>{
    if(el.scrollHeight>el.clientHeight+2)return;
    el.classList.remove("is-clamp");
    const more=el.nextElementSibling;if(more&&more.hasAttribute("data-qb-more"))more.remove();
  });
  $("qbPager").innerHTML=pages>1?`<button type="button" class="btn btn-secondary btn-sm" data-qb-page="${QB.page-1}" ${QB.page?"":"disabled"}>上一页</button>
    <span>第 ${QB.page+1} / ${pages} 页 · 共 ${rows.length} 题</span>
    <button type="button" class="btn btn-secondary btn-sm" data-qb-page="${QB.page+1}" ${QB.page<pages-1?"":"disabled"}>下一页</button>`:
    (rows.length?`<span>共 ${rows.length} 题</span>`:"");
}
function qbCard(q){
  const d=QB.data,sub=d.subjMap[q.sid]||{},key=qbKey(q),multi=QB.series.length>1;
  const runs=QB.series.map(s=>{const R=d.runs[s.r.run_id]||{};return{s,same:!!R.same_bank,rec:R.same_bank?(R.recs||{})[key]:null}}).filter(r=>r.same);
  const tagOf=r=>multi?`<span class="run-tag" style="background:${r.s.color}">${esc(r.s.tag)}</span>`:"";
  const whose=(r,what)=>multi?esc(r.s.tag)+" "+what:"模型"+what;
  const predOf=r=>r.rec&&r.rec.pred!=null?String(r.rec.pred):null;
  const verdicts=runs.map(r=>{const [label,tone,ic]=QB_STATE[qbState(r.rec)];
    return `<span class="qv${tone?" is-"+tone:""}">${tagOf(r)}${icon(ic,"icon-sm")}${label}</span>`}).join("");
  const long=q.q!=null&&(q.q.length>420||q.q.split("\n").length>7);
  let body=q.q==null?`<div class="qcard-q faint">（题集文件里找不到这道题）</div>`:
    `<div class="qcard-q${long?" is-clamp":""}">${esc(q.q)}</div>${long?`<button type="button" class="qb-more" data-qb-more>展开全文</button>`:""}`;
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
function qbGo(sid,filter,vs){
  if(vs)QB.vs=vs;
  Object.assign(QB,{subj:sid||"",filter:filter||"all",q:"",page:0});
  if(QB.data)qbRender();
  const t=$("iq-items");if(t)t.scrollIntoView({behavior:"smooth",block:"start"});
}
let qbTimer=null;
$("iqResult").addEventListener("click",e=>{
  const go=e.target.closest("[data-qb-go]");
  if(go){e.preventDefault();qbGo(go.dataset.qbGo,go.dataset.qbFilter,go.dataset.qbVs);return}
  const chip=e.target.closest("#qbChips [data-qb-filter]");
  if(chip){QB.filter=chip.dataset.qbFilter;QB.page=0;qbRenderList();return}
  const pg=e.target.closest("[data-qb-page]");
  if(pg){QB.page=+pg.dataset.qbPage;qbRenderList();const t=$("qbChips");if(t)t.scrollIntoView({block:"start"});return}
  const ans=e.target.closest("[data-qb-ans]");if(ans){qbToggleAnswer(ans);return}
  const more=e.target.closest("[data-qb-more]");
  if(more){const on=more.previousElementSibling.classList.toggle("is-clamp");more.textContent=on?"展开全文":"收起";}
});
$("iqResult").addEventListener("change",e=>{
  if(e.target.id==="qbSubj"){QB.subj=e.target.value;QB.page=0;qbRenderList()}
  else if(e.target.id==="qbVs"){QB.vs=e.target.value;QB.page=0;qbRenderList()}
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
 {id:"pelican",name:"鹈鹕骑自行车",tier:"普通"},{id:"earth",name:"可拖拽 3D 地球",tier:"普通"},
 {id:"blackhole",name:"黑洞吸积盘",tier:"普通"},{id:"matrix",name:"矩阵字符雨",tier:"普通"},
 {id:"koi",name:"锦鲤池塘",tier:"普通"},{id:"fireworks",name:"点击烟花",tier:"普通"},
 {id:"solar",name:"太阳系模拟",tier:"普通"},{id:"landing",name:"产品落地页",tier:"普通"},
 {id:"dashboard",name:"数据看板",tier:"普通"},
 {id:"flappy",name:"Flappy Bird",tier:"困难"},{id:"tetris",name:"俄罗斯方块",tier:"困难"},
 {id:"breakout",name:"打砖块",tier:"困难"},{id:"ninja",name:"切水果",tier:"困难"},
 {id:"platformer",name:"2D 平台跳跃",tier:"困难"},{id:"snake",name:"贪吃蛇",tier:"困难"},
 {id:"fps",name:"3D 第一人称迷宫",tier:"地狱"},{id:"cube3d",name:"3D 魔方",tier:"地狱"},
 {id:"pinball",name:"物理弹珠台",tier:"地狱"},{id:"fluid",name:"实时流体模拟",tier:"地狱"},
 {id:"eco",name:"生态进化模拟",tier:"地狱"},{id:"piano",name:"可弹奏钢琴",tier:"地狱"},
 {id:"sortviz",name:"排序算法可视化",tier:"地狱"},{id:"win95",name:"Win95 桌面",tier:"地狱"},
 {id:"applecard",name:"Apple 风格产品页",tier:"实战"},{id:"stripe",name:"Stripe 风格首屏",tier:"实战"},
 {id:"iostodo",name:"iOS 待办应用",tier:"实战"},{id:"ecomdetail",name:"电商详情页",tier:"实战"},
 {id:"ioscalc",name:"iOS 计算器",tier:"实战"},{id:"dock",name:"macOS Dock",tier:"实战"},
 {id:"terminal",name:"macOS 终端",tier:"实战"},{id:"parallax",name:"3D 悬停卡片",tier:"实战"},
 {id:"glasslogin",name:"玻璃拟态登录页",tier:"实战"},{id:"feed",name:"社区信息流",tier:"实战"},
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

function renderGen(){
  if(!GEN_LOADED)return;
  const el=$("genResult");
  const a=GEN_RUNS[$("genMainSel").value],b0=GEN_RUNS[$("genCmpSel").value];
  const b=b0&&a&&b0.run_id!==a.run_id?b0:null;
  if(!a){el.innerHTML=emptyState("还没有生成任务","让模型写网页小游戏和应用，在后台浏览器里真正运行、点击、按键，检查能不能用。点右上角「新建生成任务」开始",
    {action:`<button class="btn btn-primary" data-toggle="genLauncher">${icon("plus")}新建生成任务</button>`});buildJump("genJump",null);return}
  const s=genStats(a),ev=a.eval||{};
  const items=a.items||[];
  const verdicts=items.map(it=>({it,v:genVerdict(it)}));
  const count=k=>verdicts.filter(x=>x.v.key===k).length;
  /* ---- 提示 ---- */
  let alerts="";
  if(a.status&&a.status!=="done")alerts+=alertBox("warn",`这个任务${esc(STATUS_NAME[a.status]||a.status)}${a.error?"："+esc(a.error):""}。下面只有已经完成的题，原计划 ${s.planned} 题。`);
  if(!s.v2)alerts+=alertBox("warn","这个任务用的是旧版检查（只在代码里找关键词），分数不可信。点右上方「重新检查」按新方式在浏览器里实际运行，人工评分会保留。");
  else if(s.mode==="static"||s.mode==="mixed"){
    const why=ev.browser_error||(items.map(x=>x.eval&&x.eval.notes&&x.eval.notes[0]).find(Boolean))||"后台浏览器没有启动";
    alerts+=alertBox("bad",`<b>${s.mode==="static"?"这些作品没有在浏览器里实际运行":`有 ${s.staticN} 件作品没有在浏览器里实际运行`}</b>，只检查了代码里有没有相关关键词，${s.mode==="static"?"下面的通过率":"这部分作品的通过率"}不能代表作品真的能用。<br>
      原因：${esc(why)}<br>修复后（例如以普通权限重新启动服务）点「重新检查」即可，人工评分会保留。`,
      `<button class="btn btn-secondary btn-sm" onclick="genReeval()">${icon("scan-check")}重新检查</button>`);
  }
  if(s.v2&&s.mode==="browser"&&verLt(ev.eval_version,"1.1.0"))
    alerts+=alertBox("warn",`这个任务的运行检查用的是 ${esc(ev.eval_version||"1.0")} 版规则：会把自带动画、鼠标悬停效果误判为“操作有反应”，输入“.”会丢字符，手机适配检查不生效。建议「重新检查」，人工评分会保留。`);
  if(a.thinking_dropped)alerts+=alertBox("warn","模型服务不接受“开启思考”的参数，这个任务实际上可能没有思考。");
  /* ---- 指标 ---- */
  const execLabel=s.mode==="static"?"只看代码的命中率":"实际运行检查通过率";
  const kpis=`<div class="kpi-grid">
    ${kpi("完成的作品",`${s.ok.length}<small> / ${s.planned}</small>`,"",{sub:items.length-s.ok.length?`${items.length-s.ok.length} 题没生成出来`:"全部生成出来了"})}
    ${kpi(s.mode==="static"?execLabel:term("run",execLabel),s.exec==null?"—":fmt(s.exec,1),s.exec==null?"":"%",{sub:s.mode==="static"?"没有实际运行，仅供参考":s.mode==="mixed"?`只统计实际运行的 ${s.browserN} 件`:"打开、报错、白屏、动画和操作反应"})}
    ${kpi(term("judge"),s.judge==null?"—":fmt(s.judge,1),s.judge==null?"":"/ 100",{sub:!ev.judge_model&&s.judge==null?"没有配置打分模型":`${s.judgeN} 件有分${s.judgeErr?`，${s.judgeErr} 件打分失败`:""}${ev.judge_model?" · "+esc(ev.judge_model):""}`})}
    ${kpi("人工评分",s.stars==null?"—":fmt(s.stars,1),s.stars==null?"":"/ 5",{sub:s.starN?`已评 ${s.starN} 件`:"在下面的作品卡片上点星星"})}
  </div>`;
  /* ---- 结论: 模型问题 vs 环境/框架问题 ---- */
  const modelIssues=["repeat","unfinished","error","blank","partial"].map(k=>[k,count(k)]).filter(x=>x[1]);
  const envIssues=["static","env"].map(k=>[k,count(k)]).filter(x=>x[1]);
  const ck={};items.forEach(it=>{const k=changeKind(it);ck[k]=(ck[k]||0)+1});
  const concl=[];
  concl.push({tone:count("pass")===items.length?"good":"info",html:`${items.length} 件作品里，<b>${count("pass")}</b> 件全部检查通过。`});
  if(modelIssues.length)concl.push({tone:"warn",html:"<b>模型自身的问题</b>："+modelIssues.map(([k,n])=>`${VERDICT_META[k].name} ${n} 件`).join("、")+"。"});
  if(count("fail"))concl.push({tone:"bad",html:`<b>${count("fail")}</b> 件没有生成出来（请求出错或没写出有效代码）。`});
  if(envIssues.length)concl.push({tone:"bad",html:"<b>评测环境的问题</b>（不能算在模型头上）："+envIssues.map(([k,n])=>`${VERDICT_META[k].name} ${n} 件`).join("、")+"。"});
  if(ck.legacy===items.length)concl.push({tone:"info",html:"这个任务生成于 2.3 之前，没有保存模型的原始输出，无法逐字核对框架有没有改动。之后的新任务会自动保存。"});
  else concl.push({tone:"good",html:`框架有没有改动模型写的代码：<b>${ck.raw||0}</b> 件原样保存，<b>${ck.trimmed||0}</b> 件只去掉了代码前后的说明文字或代码块标记${ck.stitched?`，<b>${ck.stitched}</b> 件拼接了接着写的内容`:""}${ck.rescued?`，<b>${ck.rescued}</b> 件思考失败后改为不思考重新生成`:""}。除此之外保存的作品和模型输出逐字一致，每件作品的「生成过程」里可以看原始输出。`});
  if(s.mode==="browser"||s.mode==="mixed"){
    const ctlN=items.filter(it=>it.eval&&it.eval.control&&it.eval.control.reproduced).length;
    if(ctlN)concl.push({tone:"info",html:`报错的作品里有 <b>${ctlN}</b> 件在不加任何检测代码的干净环境里${term("control","重新运行")}也同样报错，确认是作品自身的 bug。`});
  }
  /* ---- 作品卡片 ---- */
  const cardHTML=({it,v})=>genCard(a,b,it,v);
  const filters=[["all","全部",items.length],["issues","有问题的",items.length-count("pass")],...VERDICTS.map(([k,n])=>[k,n,count(k)]).filter(x=>x[2]&&x[0]!=="pass"),["pass","全部通过",count("pass")]];
  if(!filters.some(f=>f[0]===GEN_FILTER&&f[2]))GEN_FILTER="all";
  const shown=verdicts.filter(x=>GEN_FILTER==="all"||(GEN_FILTER==="issues"?x.v.key!=="pass":x.v.key===GEN_FILTER));
  el.innerHTML=`<div class="stack">${alerts}${summaryCard("结论",concl,`${esc(a.model||"")} · ${a.thinking?"思考模式":"不思考"} · ${esc(samplingTextGen(a))} · ${esc(evalMethodText(ev))} · 开始于 ${esc(timeText(a.started_utc))}`)}${kpis}</div>`+
    sec("gen-why","问题出在哪","每件作品只按最主要的一个问题归类；红色是作品/模型的问题，灰色是评测环境的问题",
      `<div class="grid-2">
        <div class="ccard"><div class="ccard-head"><div><h3 class="ccard-title">作品情况</h3><p class="ccard-desc">共 ${items.length} 件，鼠标放上去能看到是哪几件</p></div></div><div class="chart" id="genWhy"></div></div>
        <div class="ccard"><div class="ccard-head"><div><h3 class="ccard-title">框架有没有改动模型写的代码</h3><p class="ccard-desc">除这些处理外，保存的作品和模型写的逐字一致</p></div></div><div class="chart" id="genChange"></div>
          ${ck.legacy?`<p class="ccard-note">${ck.legacy===items.length?"这个任务":"其中 "+ck.legacy+" 件"}生成于 2.3 之前，没有保存模型原始输出；之后的新任务会自动保存，可以在作品的「生成过程」里逐字核对。</p>`:""}</div>
      </div>`,"问题归因")+
    sec("gen-tier","各难度的表现",`${s.mode==="static"?"只看代码的命中率（没有实际运行，仅供参考）":"实际运行检查的通过率"}，每张卡里按分数从高到低排列${b?"；右侧数字是 A / B":""}`,
      tierCards(a,b,s.mode),"难度")+
    sec("gen-works","作品",`点「预览」直接玩，「检查详情」看截图和每项检查，「生成过程」看模型的原始输出`,
      `<div class="work-toolbar"><div class="filter-chips">${filters.map(([k,n,c])=>`<button type="button" class="filter-chip" data-gen-filter="${k}" aria-pressed="${k===GEN_FILTER}">${esc(n)} <b>${c}</b></button>`).join("")}</div></div>
      <div class="work-grid">${shown.map(cardHTML).join("")||emptyState("没有符合条件的作品","",{inline:true})}</div>`,"作品");
  disposeDetached();
  drawGenCharts(a,b,verdicts,ck);
  buildJump("genJump",el);
}
function samplingTextGen(r){
  const sm=r.sampling;
  if(!sm)return "随机性：旧版 T0.3";
  const first=r.thinking?sm.think:sm.plain;
  return (sm.mode==="official"?"官方推荐采样":sm.mode==="legacy"?"旧版低温 T0.3":"自定义采样")+(first&&first.temperature!=null?`（temperature ${first.temperature}）`:"");
}
function genCard(a,b,it,v){
  const tags=esc((it.tags||[]).map(tagName).join(" · "));
  const meta=VERDICT_META[v.key]||{tone:"neutral"};
  const tone=meta.tone==="neutral"?"":` is-${meta.tone}`;
  const ic={good:"check-circle",bad:"x-circle",warn:"alert",neutral:"ban"}[meta.tone]||"info";
  const e=it.eval,checks=e?e.checks||[]:[],fails=checks.filter(c=>!c.pass),j=e&&e.judge;
  const judgeBadge=j&&j.score!=null?`<span class="badge" title="AI 看图打分${j.stale?"（基于旧截图）":""}">${icon("sparkle")}<b class="score ${scoreCls(j.score)}">${fmt(j.score,0)}</b>${j.stale?" 旧":""}</span>`:(j&&j.error?`<span class="badge is-bad">打分失败</span>`:"");
  const metaLine=[tags,it.lines?`${fmtInt(it.lines)} 行`:"",it.continuations?`接着写 ${it.continuations} 轮`:"",it.out_tokens?`输出 ${fmtInt(it.out_tokens)} token`:""].filter(Boolean).join(" · ");
  const body=it.error?"":(e?`<div class="row" style="gap:10px"><span class="checkbar">${checks.map(c=>`<i class="${c.pass?"":"fail"}" title="${esc((c.pass?"通过："+plainCheck(c):"没通过："+failText(c))+(c.detail?"\n"+c.detail:""))}"></i>`).join("")}</span>
      <span class="score ${scoreCls(it.exec_score)}">${e.method==="static"?"代码关键词":"运行检查"} ${it.pass}/${it.total}</span></div>
      ${fails.length&&v.key!=="partial"?`<div class="work-fails">${fails.slice(0,3).map(c=>`<div>${icon("x-circle","icon-sm")} ${esc(failText(c))}</div>`).join("")}${fails.length>3?`<div class="faint">还有 ${fails.length-3} 项没通过</div>`:""}</div>`:""}`:"");
  const hasTrace=!!it.trace;
  return `<div class="work"><div class="work-head"><div style="min-width:0"><div class="work-name">${esc(it.name)}</div><div class="work-meta">${metaLine}</div></div>${judgeBadge}</div>
    <div class="work-verdict${tone}">${icon(ic)}<span>${esc(v.text)}</span></div>${body}
    <div class="work-actions">
      ${it.file&&!it.error?`<button class="btn btn-secondary btn-sm" data-gen="preview" data-run="${esc(a.run_id)}" data-item="${esc(it.id)}">${icon("play")}预览</button>`:""}
      ${e?`<button class="btn btn-ghost btn-sm" data-gen="detail" data-run="${esc(a.run_id)}" data-item="${esc(it.id)}">${icon("image")}检查详情</button>`:""}
      ${hasTrace||it.rounds?`<button class="btn btn-ghost btn-sm" data-gen="trace" data-run="${esc(a.run_id)}" data-item="${esc(it.id)}">${icon("layers")}生成过程</button>`:""}
      ${b&&!it.error?`<button class="btn btn-ghost btn-sm" data-gen="compare" data-run="${esc(a.run_id)}" data-item="${esc(it.id)}">${icon("columns")}并排对比</button>`:""}
      ${it.error?"":`<span class="stars" role="group" aria-label="人工评分">${[1,2,3,4,5].map(i=>`<button type="button" class="star ${i<=(it.stars||0)?"on":""}" data-rate="${i}" data-run="${esc(a.run_id)}" data-item="${esc(it.id)}" aria-label="${i} 分" aria-pressed="${i===it.stars}">${icon("star")}</button>`).join("")}</span>`}
    </div></div>`;
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
    return tt(r.name,[[r.colors[0],VERDICT_META[r.k].why,r.right]],names.slice(0,10).join("、")+(names.length>10?" …":""))}});
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
$("genResult").addEventListener("click",e=>{
  const f=e.target.closest("[data-gen-filter]");
  if(f){GEN_FILTER=f.dataset.genFilter;renderGen();const w=$("gen-works");if(w)w.scrollIntoView({block:"start"});return}
  const rate=e.target.closest("[data-rate]");
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
}
const GEN_SANDBOX="allow-scripts allow-pointer-lock allow-forms allow-modals"; /* 无 same-origin/top-navigation/popups: 作品代码碰不到本页和接口; localStorage 由服务端 /works 垫片提供(否则游戏脚本一启动就崩) */
const SANDBOX_BADGE=`<span class="badge" title="作品在隔离的沙箱里运行，碰不到本页面和后端接口；本地存储用内存代替（刷新就清空）">${icon("ban")}隔离运行</span>`;
function focusPreviewFrame(){
  const f=document.querySelector("#modalBody iframe.frame");
  if(f){try{f.focus();f.contentWindow&&f.contentWindow.focus()}catch(e){}}
}
function previewWork(it){
  Modal.open(it.name,`<iframe class="frame" sandbox="${GEN_SANDBOX}" src="/${esc(it.file)}" title="${esc(it.name)}"></iframe>`,{badges:SANDBOX_BADGE,flush:true});
  focusPreviewFrame();  /* 键盘类游戏不用先点一下 */
}
function previewCompare(it){
  const a=GEN_RUNS[$("genMainSel").value],b=GEN_RUNS[$("genCmpSel").value];
  const ib=b&&(b.items||[]).find(x=>x.id===it.id);
  const side=(r,x,tag)=>`<div><div class="split-head"><span class="run-tag ${tag.toLowerCase()}">${tag}</span>${esc(genLabel(r))}</div>
    ${x&&!x.error?`<iframe class="frame" style="flex:1" sandbox="${GEN_SANDBOX}" src="/${esc(x.file)}" title="${tag}"></iframe>`
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
    <div><div class="shot-grid">${(e.shots||[]).map(s=>`<figure class="shot"><img src="/${esc(dir+s.file)}" alt="${esc(s.caption)}" loading="lazy"><figcaption>${esc(s.caption)}</figcaption></figure>`).join("")||emptyState("没有截图","只看代码的检查不会截图",{inline:true})}</div></div>
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
      <a class="btn btn-ghost btn-sm" href="/${esc(it.trace)}" download style="margin-left:auto">${icon("download")}下载完整记录（JSON）</a></div>
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
   模型管理: 地址 / Key / 模型 命名保存在服务端, 三个测试页一键填入
   ============================================================ */
let EPS=[];
const EP_FIELDS={perf:["fBase","fKey","fModel"],iq:["iqBase","iqKey","iqModel"],gen:["genBase","genKey","genModel"]};
const EP_SEL={perf:"fEpSel",iq:"iqEpSel",gen:"genEpSel"};
function loadEndpoints(){
  return getJSON("/api/endpoints").then(l=>{EPS=Array.isArray(l)?l:[];renderEpSelects()}).catch(()=>{});
}
function renderEpSelects(){
  Object.values(EP_SEL).forEach(id=>{
    const sel=$(id);if(!sel)return;
    const cur=sel.value;
    sel.innerHTML='<option value="">选择后自动填入 地址 / Key / 模型</option>'+EPS.map(e=>`<option value="${esc(e.id)}">${esc(e.name)}</option>`).join("");
    if([...sel.options].some(o=>o.value===cur))sel.value=cur;
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
  const sel=$(EP_SEL[page]),ep=EPS.find(x=>x.id===sel.value);
  sel.value="";
  if(!ep)return;
  epFill(page,ep);
  postJSON("/api/endpoint-use",{id:ep.id}).catch(()=>{});
  toast(`已填入「${ep.name}」`,"success");
}
async function epSave(){
  const editing=EP_EDIT?EPS.find(x=>x.id===EP_EDIT):null;
  const body={id:EP_EDIT||null,name:$("epName").value.trim(),url:$("epUrl").value.trim(),api_key:$("epKey").value,model:$("epModel").value.trim()};
  if(!body.url||!body.model){msg("epOut","warning","服务地址和模型名称必须填写");return}
  const d=await postJSON("/api/endpoints",body);
  if(!d.ok){msg("epOut","error","保存失败："+d.error);return}
  EPS=d.endpoints||EPS;EP_EDIT=null;renderEpSelects();
  toast(editing?"已更新":"已添加「"+d.endpoint.name+"」","success");
  manageEndpoints();
}
function epEdit(id){EP_EDIT=id;manageEndpoints()}
function maskKey(k){k=String(k||"");return k?k.slice(0,4)+"…"+k.slice(-4):"—"}
function epHost(url){const m=String(url||"").match(/^https?:\/\/([^/?#]+)/i);return m?m[1]:String(url||"")}
let EP_EDIT=null;  /* 正在编辑的配置 id; null = 新增 */
function manageEndpoints(){
  let editing=EP_EDIT?EPS.find(x=>x.id===EP_EDIT):null;
  if(EP_EDIT&&!editing)EP_EDIT=null;
  const val=v=>esc(editing?(v||""):"");
  const cards=EPS.map(e=>{
    const on=editing&&editing.id===e.id;
    return `<article class="ep-card${on?" is-on":""}">
      <div class="ep-card-main"><div class="ep-name">${esc(e.name)}</div>
        <div class="ep-sub" title="${esc(e.url)}"><span class="ep-model">${esc(e.model||"—")}</span><span class="ep-dot">·</span>
          <span class="ep-host">${esc(epHost(e.url))}</span><span class="ep-dot">·</span><span class="ep-keymask">${esc(maskKey(e.api_key))}</span></div></div>
      <div class="ep-card-actions">
        <button type="button" class="btn btn-secondary btn-sm" data-ep-use="${esc(e.id)}" title="填入速度、能力、代码生成三个新建面板">填入</button>
        <button type="button" class="btn btn-ghost btn-icon btn-sm" data-ep-edit="${esc(e.id)}" title="编辑" aria-label="编辑">${icon("sliders")}</button>
        <button type="button" class="btn btn-ghost btn-icon btn-sm ep-del" data-ep-del="${esc(e.id)}" title="删除" aria-label="删除">${icon("trash")}</button>
      </div></article>`;
  }).join("");
  const form=`<form class="ep-form" autocomplete="off" onsubmit="epSave();return false">
      <div class="eyebrow">${editing?"正在编辑":"新增"}</div>
      <div class="ep-fields">
        <div class="field span-2"><label for="epName">名称</label><input class="input" id="epName" placeholder="留空则用「模型 · 地址」" value="${editing?esc(editing.name):""}"></div>
        <div class="field span-2"><label for="epUrl">服务地址</label><input class="input" id="epUrl" placeholder="http://127.0.0.1:8000" value="${val(editing&&editing.url)}"></div>
        <div class="field"><label for="epModel">模型名称</label><input class="input" id="epModel" placeholder="模型名称" value="${val(editing&&editing.model)}"></div>
        <div class="field"><label for="epKey">API Key</label>
          <div class="ep-keywrap"><input class="input" id="epKey" type="password" autocomplete="off" placeholder="没有可不填" value="${val(editing&&editing.api_key)}">
          <button type="button" class="btn btn-ghost btn-icon btn-sm" data-ep-reveal title="显示 Key" aria-label="显示 Key">${icon("eye")}</button></div></div>
      </div>
      <div class="ep-actions"><span class="inline-msg" id="epOut"></span>
        ${editing?'<button type="button" class="btn btn-ghost btn-sm" data-ep-cancel>取消</button>':""}
        <button type="submit" class="btn btn-primary btn-sm">${editing?"保存":"添加"}</button></div>
    </form>`;
  Modal.open("模型管理",`<div class="ep-shell">
      <div class="ep-list-head">已保存的模型 <span class="ep-count">${EPS.length} 个</span></div>
      <div class="ep-list">${cards||'<p class="ep-empty">还没有保存的模型</p>'}</div>
      ${form}
      <p class="ep-note">保存在本机数据库里。点「填入」会同时填到速度、能力、代码生成三个新建面板。</p></div>`,{panel:true});
}
async function epApply(id){
  const ep=EPS.find(x=>x.id===id);if(!ep)return;
  Object.keys(EP_FIELDS).forEach(page=>epFill(page,ep));
  Modal.close();
  postJSON("/api/endpoint-use",{id}).catch(()=>{});
  toast(`已填入「${ep.name}」到三个新建面板`,"success");
}
async function epRemove(id){
  const ep=EPS.find(x=>x.id===id);if(!ep)return;
  const ok=await confirmDialog({title:"删除保存的模型",message:"确定删除「"+ep.name+"」吗？已经填到面板里的内容不受影响。",confirmText:"删除",danger:true});
  if(!ok){manageEndpoints();return}
  await postJSON("/api/endpoint-delete",{id});
  await loadEndpoints();
  manageEndpoints();
}
Object.keys(EP_SEL).forEach(page=>{const sel=$(EP_SEL[page]);if(sel)sel.addEventListener("change",()=>onEpSelect(page))});

/* ============================================================
   样式自检: 令牌色块 / 字号 / 基础组件(地址 #styleguide)
   ============================================================ */
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
      ${deltaPill(100,112,1,{prefix:"B "})}${deltaPill(100,90,1,{prefix:"B "})}${deltaPill(100,100.4,1,{prefix:"B "})}
      <span class="run-tag" style="background:var(--series-1)">A</span><span class="run-tag" style="background:var(--series-2)">B</span><span class="run-tag" style="background:var(--series-3)">C</span></div></div>
    <div class="sg-group"><h3 class="sg-h">提示框</h3>
      ${alertBox("info","这次测试由旧版评测程序生成，分数口径不同。")}${alertBox("warn","有 17 题没答完（写到长度上限被停下）。")}
      ${alertBox("bad","后台浏览器没有启动，只检查了代码。",`<button class="btn btn-secondary btn-sm">${icon("scan-check")}重新检查</button>`)}${alertBox("good","全部检查通过。")}</div>
    <div class="sg-group"><h3 class="sg-h">表单</h3><div class="form-grid" style="max-width:640px">
      <div class="field"><label for="sgIn">服务地址</label><input class="input" id="sgIn" placeholder="http://127.0.0.1:8000"><span class="help">OpenAI 兼容接口的地址</span></div>
      <div class="field"><label for="sgSel">测试规模</label><select class="select" id="sgSel"><option>标准：约 12 分钟（推荐）</option><option>完整：约 35 分钟</option></select></div>
      <div class="field"><span class="label">思考模式</span><label class="check"><input type="checkbox" checked>让模型先思考再回答</label></div></div></div>
    <div class="sg-group"><h3 class="sg-h">空状态 / 骨架</h3><div class="grid-2">${emptyState("还没有速度测试","点右上角「新建速度测试」，测完的结果会显示在这里",{inline:true})}
      <div class="kpi"><div class="skeleton" style="height:12px;width:50%"></div><div class="skeleton" style="height:30px;width:70%;margin-top:12px"></div></div></div></div>
  </div>`;
  const sel=$("sgSel");if(sel)CSelect.enhance(sel);
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
  ];
  for(const [url,,watch] of jobs){
    try{const s=await getJSON(url);if(s.running)watch()}catch(e){}
  }
}
let rzT;
window.addEventListener("resize",()=>{clearTimeout(rzT);rzT=setTimeout(()=>{for(const inst of CHARTS.values()){try{inst.resize()}catch(e){}}},120)});
matchMedia("(prefers-color-scheme: light)").addEventListener("change",e=>{
  try{if(localStorage.getItem("llm-bench-pro-theme"))return}catch(err){}
  applyTheme(e.matches?"light":"dark",false);
});
document.querySelectorAll("select.select").forEach(CSelect.enhance);
CSelect.combo($("fModel"));
readTheme();
applyTheme(document.documentElement.dataset.theme||"dark",false);
try{applyRailPin(localStorage.getItem("llm-bench-pro-rail")==="1",false)}catch(e){applyRailPin(false,false)}
try{applyDensity(localStorage.getItem("llm-bench-pro-density")==="compact"?"compact":"normal",false)}catch(e){applyDensity("normal",false)}
showView((location.hash||"#dash").slice(1));
checkVersion().then(()=>{if(VIEW==="iq")renderIq()});
setInterval(checkVersion,60000);
refresh();
loadReplayFiles();
loadScenarioAssets();
loadEndpoints();
resumeRunning();
