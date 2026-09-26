"use strict";
/* LLM Bench Pro 前端逻辑 (零依赖, 经典脚本) */
const UI_VERSION="2.7.0";  /* 与 llm_bench_pro/version.py 保持一致 */
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
function median(xs){const v=xs.filter(x=>x!=null&&isFinite(x)).sort((p,q)=>p-q);if(!v.length)return null;const m=v.length>>1;return v.length%2?v[m]:(v[m-1]+v[m])/2}
/* 时间统一按浏览器本地时区显示(后端存 UTC ISO) */
function toDate(iso){if(!iso)return null;let s=String(iso);if(!/[zZ]$|[+-]\d\d:?\d\d$/.test(s))s+="Z";const d=new Date(s);return isNaN(d.getTime())?null:d}
const pad2=n=>String(n).padStart(2,"0");
function timeText(iso){const d=toDate(iso);return d?`${d.getFullYear()}-${pad2(d.getMonth()+1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`:"—"}
function shortTime(iso){const d=toDate(iso);return d?`${pad2(d.getMonth()+1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`:""}
function durationText(s){s=Math.max(0,Math.round(s||0));if(s<3600)return Math.max(1,Math.round(s/60))+" 分钟";if(s<86400)return (s/3600).toFixed(1).replace(/\.0$/,"")+" 小时";return (s/86400).toFixed(1).replace(/\.0$/,"")+" 天"}
const STATUS_NAME={running:"运行中",done:"已完成",failed:"失败",interrupted:"已中断",cancelled:"已停止"};
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
  const save=()=>{const k={};ids.forEach(id=>k[id]=$(id).value);lsSet(key,k)};
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

/* ============================================================
   主题
   ============================================================ */
let C={};
function readTheme(){
  const cs=getComputedStyle(document.documentElement),v=n=>cs.getPropertyValue(n).trim();
  C={a:v("--series-1"),b:v("--series-2"),t:v("--series-3"),series:[1,2,3,4,5,6].map(i=>v("--series-"+i)),
     grid:v("--chart-grid"),axis:v("--chart-axis"),text:v("--text-3"),text2:v("--text-2"),text1:v("--text-1"),
     surface:v("--surface-1"),borderStrong:v("--border-strong"),font:v("--font-sans"),mono:v("--font-mono")||v("--font-sans")};
}
function withAlpha(hex,a){const h=String(hex).replace("#","");return h.length===6?"#"+h+Math.round(a*255).toString(16).padStart(2,"0"):hex}
function applyTheme(t,persist){
  document.documentElement.dataset.theme=t;
  if(persist)try{localStorage.setItem("llm-bench-pro-theme",t)}catch(e){}
  $("themeBtn").querySelector("use").setAttribute("href",t==="dark"?"#i-sun":"#i-moon");
  $("themeBtn").setAttribute("aria-label",t==="dark"?"切换为亮色主题":"切换为暗色主题");
  readTheme();
  redrawVisible();
}
$("themeBtn").onclick=()=>applyTheme(document.documentElement.dataset.theme==="dark"?"light":"dark",true);

/* ============================================================
   导航 / 折叠 / 展开 / 弹窗
   ============================================================ */
let VIEW="dash";
const VIEWS={dash:"viewDash",cmp:"viewCmp",iq:"viewIq",gen:"viewGen"};
function showView(v){
  if(!VIEWS[v])v="dash";
  VIEW=v;
  document.querySelectorAll(".nav-item").forEach(b=>{if(b.dataset.view===v)b.setAttribute("aria-current","page");else b.removeAttribute("aria-current")});
  Object.entries(VIEWS).forEach(([k,id])=>$(id).classList.toggle("is-active",k===v));
  try{history.replaceState(null,"","#"+v)}catch(e){}
  if(v==="dash")render();
  if(v==="cmp")renderCmp();
  if(v==="iq"){loadBanks();loadIqResults();}
  if(v==="gen"){renderTaskChips();loadGenResults();}
}
function redrawVisible(){
  if(VIEW==="dash")render();
  else if(VIEW==="cmp")renderCmp();
  else if(VIEW==="iq")renderIq();
}
function toggleLauncher(id,force){
  const el=$(id);const open=force==null?el.hidden:force;
  el.hidden=!open;
  document.querySelectorAll(`[data-toggle="${id}"][aria-expanded]`).forEach(b=>b.setAttribute("aria-expanded",String(open)));
  if(open&&force==null){const f=el.querySelector("input:not([type=checkbox]),select");if(f)f.focus()}
}
document.addEventListener("click",e=>{
  const nav=e.target.closest(".nav-item");if(nav&&nav.dataset.view){showView(nav.dataset.view);return}
  const tg=e.target.closest("[data-toggle]");if(tg){toggleLauncher(tg.dataset.toggle);return}
  const col=e.target.closest("[data-collapse]");
  if(col){const p=col.closest(".panel");p.classList.toggle("is-collapsed");col.setAttribute("aria-expanded",String(!p.classList.contains("is-collapsed")));
    if(!p.classList.contains("is-collapsed"))redrawVisible();return}
  const vis=e.target.closest("[data-vis]");
  if(vis){const [g,k]=vis.dataset.vis.split(".");VIS[g][k]^=1;redrawVisible();return}
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
    else{EP_EDIT=null;manageEndpoints()}  /* 取消编辑 → 回到新增态 */
    return
  }
  const row=e.target.closest("tr[data-expand]");
  if(row){const d=row.nextElementSibling;const open=d.hidden;d.hidden=!open;row.setAttribute("aria-expanded",String(open));return}
  const dd=document.querySelector("details.dropdown[open]");
  if(dd&&!dd.contains(e.target))dd.open=false;
});

const Modal={
  last:null,
  onClose:null,
  open(title,html,{badges="",flush=false,dialog=false,panel=false}={}){
    if(!$("modal").hidden)this.close();
    this.last=document.activeElement;
    $("modalTitle").textContent=title;
    $("modalBadges").innerHTML=badges;
    const body=$("modalBody");body.className="modal-body"+(flush?" is-flush":"");body.innerHTML=html;body.onclick=null;
    $("modal").classList.toggle("is-dialog",!!dialog);
    $("modal").classList.toggle("is-panel",!!panel);
    $("modal").hidden=false;
    $("modalClose").focus();
  },
  close(){
    if($("modal").hidden)return;
    $("modal").hidden=true;$("modalBody").innerHTML="";  /* 清空 iframe, 停止作品音频/动画 */
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
/* 启动类请求: 与性能测试共用端点时后端返回 endpoint_busy, 由用户确认是否仍要同时运行 */
async function postWithConflict(url,body){
  let d=await postJSON(url,body);
  if(!d.ok&&d.code==="endpoint_busy"){
    const go=await confirmDialog({title:"模型端点正在被使用",message:d.error+"\n\n仍要同时启动吗？",confirmText:"仍要启动"});
    if(!go)return null;
    d=await postJSON(url,{...body,force:true,conflict_with:d.conflict});
  }
  return d;
}
$("modalClose").onclick=()=>Modal.close();
$("modal").addEventListener("mousedown",e=>{if(e.target===$("modal"))Modal.close()});
document.addEventListener("keydown",e=>{
  if($("modal").hidden)return;
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
    const ok=await confirmDialog({title:"停止运行",confirmText:"停止",danger:true,
      message:"不再开始新的请求，已完成的结果会保留。"+(job==="iq"?"\n停止后可以在能力评测页续跑。":"")+"\n正在进行中的请求会被放弃。"});
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
      stop.hidden=!job;stop.disabled=false;t0=Date.now();clearInterval(timer);timer=setInterval(tick,1000);tick()},
    lines(arr){const atBottom=body.scrollHeight-body.scrollTop-body.clientHeight<32;body.textContent=arr.join("\n");if(atBottom)body.scrollTop=body.scrollHeight},
    state(s){if(s.cancelling){stopping=true;stop.disabled=true;title.textContent="正在停止…"}},
    get stopping(){return stopping},
    finish(ok,text){clearInterval(timer);tick();stop.hidden=true;el.className="runlog "+(ok?"is-ok":"is-fail");title.textContent=text}
  };
}
function pollStatus(url,log,{interval=2000,onDone}={}){
  const h=setInterval(async()=>{
    try{
      const s=await getJSON(url);
      log.lines((s.log||[]).map(x=>x.msg).slice(-300));
      log.state(s);
      if(!s.running){clearInterval(h);log.finish(!s.error,s.error?"运行失败："+s.error:(log.stopping?"已停止，已完成的结果已保存":"运行完成"));if(onDone)onDone(s)}
    }catch(e){}
  },interval);
  return h;
}

/* ============================================================
   图表
   ============================================================ */
const TIP=$("tip");
const VIS={pre:{a:1,b:1},conc:{a:1,b:1,t:1}};
function setupCanvas(cv,ratio=.42,minH=220,maxH=420){
  const dpr=window.devicePixelRatio||1;
  const w=Math.max(cv.clientWidth,60);
  const h=Math.round(Math.min(maxH,Math.max(minH,w*ratio)));
  cv.width=Math.round(w*dpr);cv.height=Math.round(h*dpr);cv.style.height=h+"px";
  const g=cv.getContext("2d");g.setTransform(dpr,0,0,dpr,0,0);g.clearRect(0,0,w,h);
  g.font=`10.5px ${C.mono||C.font}`;g.textBaseline="middle";g.lineJoin="round";g.lineCap="round";
  cv._hit=[];
  return{g,w,h};
}
function noData(g,w,h,text="无数据"){g.fillStyle=C.text;g.textAlign="center";g.font=`12px ${C.font}`;g.fillText(text,w/2,h/2);g.textAlign="left"}
/* 坐标轴上限: 先取整洁的刻度步长(1/2/2.5/5×10^n), 4 格网格刻度均为整洁数值 */
function niceMax(v){
  if(!(v>0))return 1;
  const raw=v/4,p=10**Math.floor(Math.log10(raw)),n=raw/p;
  return (n<=1?1:n<=2?2:n<=2.5?2.5:n<=5?5:10)*p*4;
}
function tt(title,rows){
  return `<div class="tt-title">${esc(title)}</div>`+rows.map(([color,name,val])=>
    `<div class="tt-row">${color?`<span class="swatch" style="background:${color}"></span>`:""}<span>${esc(name)}</span><span class="tt-v">${esc(val)}</span></div>`).join("");
}
function bindTips(cv){
  const show=e=>{
    const r=cv.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
    let best=null,bd=600;
    (cv._hit||[]).forEach(p=>{const d=(p.x-mx)**2+(p.y-my)**2;if(d<bd){bd=d;best=p}});
    if(!best){TIP.style.display="none";return}
    TIP.innerHTML=best.html;TIP.style.display="block";
    const tw=TIP.offsetWidth,th=TIP.offsetHeight,px=r.left+best.x,py=r.top+best.y;
    let x=px+14,y=py-th-10;
    if(x+tw>innerWidth-8)x=px-tw-14;
    if(y<8)y=py+14;
    TIP.style.left=x+"px";TIP.style.top=y+"px";
  };
  cv.onmousemove=show;cv.onclick=show;cv.onmouseleave=()=>TIP.style.display="none";
}
function legendBtn(key,color,text,{dash=false,on=true}={}){
  const mark=dash?`<span class="legend-dash" style="color:${color}"></span>`:`<span class="swatch" style="background:${color}"></span>`;
  return key?`<button type="button" class="legend-item" data-vis="${key}" aria-pressed="${on?"true":"false"}">${mark}${esc(text)}</button>`
            :`<span class="legend-item static">${mark}${esc(text)}</span>`;
}
function drawGrid(g,{pad,w,h,ymax,fmtY=fmtAxis,right=null}){
  g.lineWidth=1;
  for(let i=0;i<=4;i++){
    const y=Math.round(pad.t+(h-pad.t-pad.b)*i/4)+.5;
    g.strokeStyle=i===4?C.axis:C.grid;
    g.beginPath();g.moveTo(pad.l,y);g.lineTo(w-pad.r,y);g.stroke();
    g.fillStyle=C.text;g.textAlign="right";g.fillText(fmtY(ymax*(1-i/4)),pad.l-8,y);
    if(right){g.textAlign="left";g.fillText(right.fmt(right.max*(1-i/4)),w-pad.r+8,y)}
  }
  g.textAlign="left";
}
function catX(pad,w,n){return i=>n>1?pad.l+(w-pad.l-pad.r)*i/(n-1):(pad.l+w-pad.r)/2}
function drawXLabels(g,labels,X,h,pad){
  g.fillStyle=C.text;
  const step=Math.max(1,Math.ceil(labels.length/12));
  labels.forEach((lab,i)=>{if(i%step&&i!==labels.length-1)return;
    g.textAlign=labels.length===1?"center":(i===0?"left":(i===labels.length-1?"right":"center"));
    g.fillText(String(lab),X(i),h-pad.b+14)});
  g.textAlign="left";
}
function axisTitles(g,pad,w,left,right){
  g.font=`10.5px ${C.mono||C.font}`;g.fillStyle=C.text2;
  if(left){g.textAlign="left";g.fillText(left,4,8)}
  if(right){g.textAlign="right";g.fillText(right,w-4,8)}
  g.textAlign="left";
}
function strokeSeries(g,pts,color,{width=1.75,dash=null}={}){
  const v=pts.filter(p=>p.y!=null&&isFinite(p.y));if(!v.length)return;
  g.strokeStyle=color;g.lineWidth=width;g.setLineDash(dash||[]);
  g.beginPath();v.forEach((p,i)=>i?g.lineTo(p.x,p.y):g.moveTo(p.x,p.y));g.stroke();g.setLineDash([]);
}
function dots(g,pts,color,r=2.5){
  pts.forEach(p=>{if(p.y==null||!isFinite(p.y))return;g.beginPath();g.arc(p.x,p.y,r+1.5,0,7);g.fillStyle=C.surface;g.fill();
    g.beginPath();g.arc(p.x,p.y,r,0,7);g.fillStyle=color;g.fill()});
}

function prefillSeries(r){const p=phase(r,"prefill");return p&&p.points.length?p.points:null}

/* ============================================================
   ECharts 增强层: 内置 vendor/echarts.min.js 存在时用交互图表
   (悬浮十字线/渐变面积/可点图例/入场动画), 缺失时自动回落原生 canvas
   ============================================================ */
const EC_INSTANCES=new Map();
const ecReady=()=>typeof window.echarts!=="undefined";
function ecCtx(cvId){
  let el=$(cvId);
  if(!el)return null;
  if(el.tagName==="CANVAS"){  // 首次把 canvas 换成 echarts 容器(同 id)
    const div=document.createElement("div");
    div.id=el.id;div.className="chart-ec";
    el.replaceWith(div);el=div;
  }
  let inst=EC_INSTANCES.get(cvId);
  if(inst&&!document.body.contains(inst.getDom())){  // renderCmp 重建了 DOM
    try{inst.dispose()}catch(e){}
    inst=null;EC_INSTANCES.delete(cvId);
  }
  if(!inst){inst=window.echarts.init(el);EC_INSTANCES.set(cvId,inst)}
  return inst;
}
function ecBase(){
  const font=C.mono||C.font;
  // animation:false 与 bench 报告同款: 入场动画在渐变面积上有偶发的
  // zrender addColorStop(undefined) 竞态, 交互感由 tooltip/图例承担
  return{animation:false,
    textStyle:{fontFamily:font,color:C.text2},
    grid:{left:56,right:20,top:36,bottom:30},
    tooltip:{trigger:"axis",backgroundColor:C.surface,borderColor:C.borderStrong,padding:[8,12],
      textStyle:{color:C.text1,fontFamily:font,fontSize:12},
      axisPointer:{type:"line",lineStyle:{color:C.axis,width:1}}},
  };
}
function ecAxis(cat,name){
  return{
    xAxis:{type:cat?"category":"value",name:name?"":""+name,boundaryGap:false,
      axisTick:{show:false},axisLine:{lineStyle:{color:C.axis}},
      axisLabel:{color:C.text,fontFamily:C.mono||C.font,fontSize:10.5}},
    yAxis:{type:"value",splitLine:{lineStyle:{color:C.grid}},
      axisLabel:{color:C.text,fontFamily:C.mono||C.font,fontSize:10.5},
      nameTextStyle:{color:C.text,fontFamily:C.mono||C.font,fontSize:10.5,align:"left"}},
  };
}
function ecLegend(extra){
  return Object.assign({show:true,top:2,right:0,icon:"roundRect",itemWidth:14,itemHeight:4,itemGap:14,
    textStyle:{color:C.text2,fontFamily:C.mono||C.font,fontSize:11}},extra||{});
}
function ecArea(color){  // 纵向渐变面积: 上浓下淡; 必须用 LinearGradient 类实例
  const base=/^#?[0-9a-fA-F]{6}$/.test(String(color))?color:"#6950E8";  // 非法色兜底: 历史上漏传颜色曾致 addColorStop(undefined)
  const stops=[{offset:0,color:withAlpha(base,.26)},{offset:1,color:withAlpha(base,.02)}];
  return{color:new window.echarts.graphic.LinearGradient(0,0,0,1,stops)};
}
function ecEmpty(inst,text){
  inst.setOption(Object.assign(ecBase(),{title:{text:text||"无数据",left:"center",top:"middle",
    textStyle:{color:C.text,fontSize:12,fontFamily:C.mono||C.font}}}),true);
}

function ecPrefill(a,b,cvId,lgId){
  const inst=ecCtx(cvId);
  if(!inst)return;
  $(lgId).innerHTML="";
  const pa=prefillSeries(a),pb=b?prefillSeries(b):null;
  if(!pa){ecEmpty(inst,"该运行不包含 Prefill 阶段数据");return}
  const labels=[];[pa,pb].forEach(ps=>(ps||[]).forEach(p=>{if(!labels.includes(p.label))labels.push(p.label)}));
  const mk=(pts,tag,color)=>({name:tag+" · Prefill 吞吐",type:"line",smooth:.3,symbolSize:7,
    lineStyle:{width:2,color},itemStyle:{color},areaStyle:ecArea(color),
    data:pts.map(p=>({value:[p.label,p.prefill_tps_med||0],ttft:p.ttft_med_s,inTok:p.in_tokens}))});
  const series=[mk(pa,"A",C.a)];
  if(pb)series.push(mk(pb,"B",C.b));
  inst.setOption(Object.assign(ecBase(),ecAxis(true),{
    color:[C.a,C.b],legend:ecLegend(),
    xAxis:{type:"category",data:labels,boundaryGap:false,axisTick:{show:false},
      axisLine:{lineStyle:{color:C.axis}},axisLabel:{color:C.text,fontFamily:C.mono||C.font,fontSize:10.5}},
    yAxis:Object.assign(ecAxis().yAxis,{name:"tok/s"}),
    tooltip:Object.assign(ecBase().tooltip,{formatter:ps=>{
      const rows=ps.map(p=>`${p.marker}${esc(p.seriesName)} <b>${fmtInt(p.value[1])}</b> tok/s`+
        `<span style="color:${C.text};opacity:.75"> · TTFT ${fmt(p.data.ttft,2)}s · 输入 ${fmtInt(p.data.inTok)}</span>`);
      return `<b>${esc(ps[0].axisValue)}</b><br>`+rows.join("<br>");}}),
    series}),true);
  inst.resize();
}

function ecConc(a,b,cvId,lgId){
  const inst=ecCtx(cvId);
  if(!inst)return;
  $(lgId).innerHTML="";
  const pa=phase(a,"concurrency"),pb=b?phase(b,"concurrency"):null;
  if(!pa||!pa.points.length){ecEmpty(inst,"该运行不包含并发阶段数据");return}
  const concs=[...new Set([...pa.points,...(pb?pb.points:[])].map(p=>p.conc))].sort((x,y)=>x-y);
  const mkConc=(p,tag,color)=>[
    {name:tag+" · 聚合吞吐",type:"line",smooth:.3,symbolSize:7,lineStyle:{width:2,color},
     itemStyle:{color},areaStyle:ecArea(color),yAxisIndex:0,
     data:concs.map(c=>{const q=p.points.find(x=>x.conc===c);return q?{value:[c,q.agg_tps||0],q}:null}).filter(Boolean)},
    {name:tag+" · 单流吞吐",type:"line",smooth:.3,symbol:"none",yAxisIndex:0,
     lineStyle:{width:1.5,color:withAlpha(color,.55),type:"dashed"},
     data:concs.map(c=>{const q=p.points.find(x=>x.conc===c);return q&&q.per_stream_tps_med!=null?[c,q.per_stream_tps_med]:null})},
    {name:tag+" · TTFT p95",type:"line",smooth:.3,symbolSize:5,yAxisIndex:1,
     lineStyle:{width:1.5,color:C.t,type:"dashed"},itemStyle:{color:C.t},
     data:concs.map(c=>{const q=p.points.find(x=>x.conc===c);return q&&q.ttft_p95_s!=null?[c,q.ttft_p95_s]:null})}];
  const series=mkConc(pa,"A",C.a);
  if(pb)series.push(...mkConc(pb,"B",C.b));
  inst.setOption(Object.assign(ecBase(),{
    color:[C.a,C.b],
    legend:ecLegend(),  // 不用 scroll: 双运行 6 项图例自动换行, 避免截断箭头
    grid:{left:56,right:52,top:50,bottom:30},
    tooltip:Object.assign(ecBase().tooltip,{formatter:ps=>{
      const c=ps[0].axisValue;
      const agg=ps.find(p=>p.seriesName.endsWith("聚合吞吐"));
      const extra=agg&&agg.data.q?`<span style="color:${C.text};opacity:.75">TTFT p50 ${fmt(agg.data.q.ttft_p50_s,2)}s · 成功 ${agg.data.q.ok}/${agg.data.q.ok+agg.data.q.fail}</span>`:"";
      return `<b>并发 ${c}</b><br>`+ps.map(p=>`${p.marker}${esc(p.seriesName)} <b>${fmt(p.value[1],p.seriesName.includes("TTFT")?2:1)}</b>${p.seriesName.includes("TTFT")?" s":" tok/s"}`).join("<br>")+(extra?`<br>`+extra:"");}}),
    xAxis:{type:"value",name:"",axisTick:{show:false},axisLine:{lineStyle:{color:C.axis}},
      axisLabel:{color:C.text,fontFamily:C.mono||C.font,fontSize:10.5,formatter:v=>fmtAxis(v)}},
    yAxis:[{type:"value",name:"tok/s",splitLine:{lineStyle:{color:C.grid}},
       axisLabel:{color:C.text,fontFamily:C.mono||C.font,fontSize:10.5,formatter:fmtAxis},
       nameTextStyle:{color:C.text,fontFamily:C.mono||C.font,fontSize:10.5,align:"left"}},
      {type:"value",name:"TTFT s",splitLine:{show:false},
       axisLabel:{color:C.text,fontFamily:C.mono||C.font,fontSize:10.5},
       nameTextStyle:{color:C.text,fontFamily:C.mono||C.font,fontSize:10.5,align:"right"}}],
    series}),true);
  inst.resize();
}

function ecMetrics(a){
  const inst=ecCtx("cMetrics");
  if(!inst)return;
  const s=a.metrics_samples||[];
  const usable=s.filter(m=>m.gpu_cache_usage!=null||m.prefix_cache_hit!=null);
  $("metricsPanel").hidden=!usable.length;
  if(!usable.length||$("metricsPanel").classList.contains("is-collapsed"))return;
  $("lMetrics").innerHTML="";
  const t0=s[0].t;
  const norm=(k,v)=>v==null?null:(k==="gpu_cache_usage"&&v<=1.05?v*100:v);
  const mk=(k,name,color)=>({name,type:"line",smooth:.25,symbol:"none",step:false,
    lineStyle:{width:1.75,color},areaStyle:k==="gpu_cache_usage"?ecArea(color):undefined,
    data:s.filter(m=>norm(k,m[k])!=null).map(m=>[Math.round(m.t-t0),norm(k,m[k]),m])});
  inst.setOption(Object.assign(ecBase(),ecAxis(false),{
    color:[C.a,C.b],legend:ecLegend(),
    yAxis:Object.assign(ecAxis().yAxis,{name:"%",max:100}),
    xAxis:{type:"value",axisTick:{show:false},axisLine:{lineStyle:{color:C.axis}},
      axisLabel:{color:C.text,fontFamily:C.mono||C.font,fontSize:10.5,
        formatter:v=>v>=120?Math.round(v/60)+"min":v+"s"}},
    tooltip:Object.assign(ecBase().tooltip,{formatter:ps=>{
      const m=ps[0].data[2];
      return `<b>t + ${Math.round(ps[0].axisValue)} s</b><br>`+
        ps.map(p=>`${p.marker}${esc(p.seriesName)} <b>${fmt(p.value[1])}</b>%`).join("<br>")+
        `<br><span style="color:${C.text};opacity:.75">运行 / 排队 ${fmtInt(m.requests_running||0)} / ${fmtInt(m.requests_waiting||0)}</span>`;}}),
    series:[mk("gpu_cache_usage","KV Cache 使用率",C.a),mk("prefix_cache_hit","前缀缓存命中率",C.b)]}),true);
  inst.resize();
}

function ecOpenloop(pa,pb,ids){
  const inst=ecCtx(ids.cv);
  if(!inst)return;
  $(ids.lg).innerHTML="";
  const runs=[["A",pa,C.a],["B",pb,C.b]].filter(([_,p])=>p);
  const series=[];
  runs.forEach(([tag,p,base])=>p.points.forEach((pt,j)=>{
    const ts=pt.inflight_ts||[];
    if(ts.length<2)return;
    const color=runs.length>1?base:C.series[j%C.series.length];
    series.push({name:`${tag} ${pt.rate} rps`,type:"line",smooth:.25,symbol:"none",
      lineStyle:{width:1.75,color},areaStyle:ecArea(color),
      data:ts.map(([t,v])=>[t,v,pt.rate])});
  }));
  if(!series.length){ecEmpty(inst,"无在途采样数据");return}
  inst.setOption(Object.assign(ecBase(),ecAxis(false),{
    legend:ecLegend({type:"scroll"}),
    yAxis:Object.assign(ecAxis().yAxis,{name:"在途"}),
    xAxis:{type:"value",axisTick:{show:false},axisLine:{lineStyle:{color:C.axis}},
      axisLabel:{color:C.text,fontFamily:C.mono||C.font,fontSize:10.5,formatter:v=>v+"s"}},
    tooltip:Object.assign(ecBase().tooltip,{valueFormatter:v=>fmtInt(v)+" 个"}),
    series}),true);
  inst.resize();
}
/* ECharts 层结束 */

function drawPrefill(a,b,cvId,lgId){
  if(ecReady())return ecPrefill(a,b,cvId,lgId);
  const cv=$(cvId);if(!cv||!cv.clientWidth)return;
  const {g,w,h}=setupCanvas(cv);
  const pa=prefillSeries(a),pb=b?prefillSeries(b):null;
  const sets=[pa&&VIS.pre.a&&{pts:pa,color:C.a,tag:"A"},pb&&VIS.pre.b&&{pts:pb,color:C.b,tag:"B"}].filter(Boolean);
  $(lgId).innerHTML=(pa?legendBtn("pre.a",C.a,"A · Prefill 吞吐",{on:VIS.pre.a}):"")+(pb?legendBtn("pre.b",C.b,"B · Prefill 吞吐",{on:VIS.pre.b}):"");
  if(!pa){noData(g,w,h,"该运行不包含 Prefill 阶段数据");return}
  const labels=[];[pa,pb].forEach(ps=>(ps||[]).forEach(p=>{if(!labels.includes(p.label))labels.push(p.label)}));
  const all=sets.flatMap(s=>s.pts.map(p=>p.prefill_tps_med||0));
  const ymax=niceMax(Math.max(...all,1)*1.08);
  const pad={l:Math.ceil(g.measureText(fmtAxis(ymax)).width)+18,r:16,t:24,b:28};
  drawGrid(g,{pad,w,h,ymax});
  const X=catX(pad,w,labels.length),Y=v=>pad.t+(h-pad.t-pad.b)*(1-v/ymax);
  drawXLabels(g,labels,X,h,pad);
  axisTitles(g,pad,w,"Prefill (tok/s)");
  sets.forEach(s=>{
    const pts=s.pts.map(p=>({x:X(labels.indexOf(p.label)),y:Y(p.prefill_tps_med||0),p}));
    strokeSeries(g,pts,s.color);dots(g,pts,s.color);
    pts.forEach(q=>cv._hit.push({x:q.x,y:q.y,html:tt(`${s.tag} · ${q.p.label}`,[
      [s.color,"Prefill",fmtInt(q.p.prefill_tps_med)+" tok/s"],["","TTFT",fmt(q.p.ttft_med_s,2)+" s"],["","输入",fmtInt(q.p.in_tokens)+" tokens"]])}));
  });
  bindTips(cv);
}
function concChart(a,b,cvId,lgId){
  if(ecReady())return ecConc(a,b,cvId,lgId);
  const cv=$(cvId);if(!cv||!cv.clientWidth)return;
  const {g,w,h}=setupCanvas(cv);
  const pa=phase(a,"concurrency"),pb=b?phase(b,"concurrency"):null;
  let lg="";
  if(pa){lg+=legendBtn("conc.a",C.a,"A · 聚合",{on:VIS.conc.a})+legendBtn("conc.a",C.a,"A · 单流",{dash:true,on:VIS.conc.a})}
  if(pb){lg+=legendBtn("conc.b",C.b,"B · 聚合",{on:VIS.conc.b})+legendBtn("conc.b",C.b,"B · 单流",{dash:true,on:VIS.conc.b})}
  if(pa)lg+=legendBtn("conc.t",C.t,"TTFT p95",{dash:true,on:VIS.conc.t});
  $(lgId).innerHTML=lg;
  if(!pa||!pa.points.length){noData(g,w,h,"该运行不包含并发阶段数据");return}
  const concs=[...new Set([...pa.points,...(pb?pb.points:[])].map(p=>p.conc))].sort((x,y)=>x-y);
  const sets=[VIS.conc.a&&{p:pa,color:C.a,tag:"A"},pb&&VIS.conc.b&&{p:pb,color:C.b,tag:"B"}].filter(Boolean);
  const ymax=niceMax(Math.max(1,...sets.flatMap(s=>s.p.points.map(q=>Math.max(q.agg_tps||0,q.per_stream_tps_med||0))))*1.08);
  const tmax=niceMax(Math.max(.01,...[pa,pb].filter(Boolean).flatMap(p=>p.points.map(q=>q.ttft_p95_s||0)))*1.08);
  const fmtT=v=>fmt(v,tmax<1?2:1);
  const pad={l:Math.ceil(g.measureText(fmtAxis(ymax)).width)+18,r:VIS.conc.t?Math.ceil(g.measureText(fmtT(tmax)).width)+18:16,t:24,b:28};
  drawGrid(g,{pad,w,h,ymax,right:VIS.conc.t?{max:tmax,fmt:fmtT}:null});
  const X=catX(pad,w,concs.length),Xc=c=>X(concs.indexOf(c));
  const Y=v=>pad.t+(h-pad.t-pad.b)*(1-v/ymax),Y2=v=>pad.t+(h-pad.t-pad.b)*(1-v/tmax);
  drawXLabels(g,concs,X,h,pad);
  axisTitles(g,pad,w,"吞吐 (tok/s) · 横轴为并发数",VIS.conc.t?"TTFT p95 (s)":"");
  sets.forEach(s=>{
    const agg=s.p.points.map(q=>({x:Xc(q.conc),y:Y(q.agg_tps||0),q}));
    const per=s.p.points.map(q=>({x:Xc(q.conc),y:q.per_stream_tps_med==null?null:Y(q.per_stream_tps_med)}));
    strokeSeries(g,per,withAlpha(s.color,.6),{width:1.5,dash:[5,4]});
    strokeSeries(g,agg,s.color);dots(g,agg,s.color);
    agg.forEach(o=>cv._hit.push({x:o.x,y:o.y,html:tt(`${s.tag} · 并发 ${o.q.conc}`,[
      [s.color,"聚合吞吐",fmtInt(o.q.agg_tps)+" tok/s"],["","单流吞吐",fmt(o.q.per_stream_tps_med)+" tok/s"],
      ["","TTFT p50 / p95",`${fmt(o.q.ttft_p50_s,2)} / ${fmt(o.q.ttft_p95_s,2)} s`],["","成功",`${o.q.ok} / ${o.q.ok+o.q.fail}`]])}));
  });
  if(VIS.conc.t){
    [[pa,"A",[2,4]],[pb,"B",[6,4]]].forEach(([p,tag,dash])=>{
      if(!p)return;
      const pts=p.points.map(q=>({x:Xc(q.conc),y:q.ttft_p95_s==null?null:Y2(q.ttft_p95_s),q}));
      strokeSeries(g,pts,C.t,{width:1.5,dash});
      pts.forEach(o=>{if(o.y!=null)cv._hit.push({x:o.x,y:o.y,html:tt(`${tag} · 并发 ${o.q.conc}`,[[C.t,"TTFT p95",fmt(o.q.ttft_p95_s,2)+" s"]])})});
    });
  }
  bindTips(cv);
}
function metricsChart(a){
  if(ecReady())return ecMetrics(a);
  const s=a.metrics_samples||[];
  const panel=$("metricsPanel");
  const usable=s.filter(m=>m.gpu_cache_usage!=null||m.prefix_cache_hit!=null);
  panel.hidden=!usable.length;
  if(!usable.length||panel.classList.contains("is-collapsed"))return;
  const cv=$("cMetrics");if(!cv.clientWidth)return;
  const {g,w,h}=setupCanvas(cv,.22,180,260);
  const t0=s[0].t,tspan=Math.max(1,s[s.length-1].t-t0);
  const pad={l:Math.ceil(g.measureText("100%").width)+18,r:16,t:24,b:28};
  drawGrid(g,{pad,w,h,ymax:100,fmtY:v=>Math.round(v)+"%"});
  axisTitles(g,pad,w,"占比 (%) · 横轴为测试时间");
  g.fillStyle=C.text;
  for(let i=0;i<=4;i++){const t=tspan*i/4;g.textAlign=i===0?"left":(i===4?"right":"center");
    g.fillText(t>=120?Math.round(t/60)+" min":Math.round(t)+" s",pad.l+(w-pad.l-pad.r)*i/4,h-pad.b+14)}
  g.textAlign="left";
  const norm=(k,v)=>v==null?null:(k==="gpu_cache_usage"&&v<=1.05?v*100:v);
  const series=[["gpu_cache_usage",C.a,"KV Cache 使用率"],["prefix_cache_hit",C.b,"前缀缓存命中率"]];
  const X=t=>pad.l+(w-pad.l-pad.r)*(t-t0)/tspan,Y=v=>pad.t+(h-pad.t-pad.b)*(1-v/100);
  series.forEach(([k,col,name])=>{
    const pts=s.map(m=>({x:X(m.t),y:norm(k,m[k])==null?null:Y(norm(k,m[k])),m,v:norm(k,m[k])})).filter(p=>p.y!=null);
    strokeSeries(g,pts,col,{width:1.75});
    pts.forEach((p,i)=>{if(i%2)return;cv._hit.push({x:p.x,y:p.y,html:tt(`t + ${Math.round(p.m.t-t0)} s`,[
      [col,name,fmt(p.v)+"%"],["","运行 / 排队",`${fmt(p.m.requests_running,0)} / ${fmt(p.m.requests_waiting,0)}`]])})});
  });
  $("lMetrics").innerHTML=series.map(([k,c,n])=>legendBtn("",c,n)).join("");
  bindTips(cv);
}

/* ============================================================
   性能基准
   ============================================================ */
let RUNS={},RUNS_LOADED=false,perfPoll=null;
const FULL={};  /* 运行完整文档缓存(列表接口只返回摘要) */
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

/* 原生 details 下拉: 打开时测量, 右溢出则右对齐锚点, 避免中窄宽度下面板被切/漂移 */
function fitDropdown(dt){
  const panel=dt.querySelector(".dropdown-panel");if(!panel)return;
  panel.style.left="";panel.style.right="";
  const r=dt.getBoundingClientRect(),p=panel.getBoundingClientRect(),vw=document.documentElement.clientWidth;
  if(r.left+p.width>vw-12){panel.style.right="0";panel.style.left="auto"}
}
document.querySelectorAll("details.dropdown").forEach(dt=>dt.addEventListener("toggle",()=>{if(dt.open)fitDropdown(dt)}));
window.addEventListener("resize",()=>document.querySelectorAll("details.dropdown[open]").forEach(fitDropdown));

/* ============================================================
   模型端点配置: 地址/Key/模型 命名存服务端, 三个页面一键填入
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
    sel.innerHTML='<option value="">选择后一键填入 地址 / Key / 模型</option>'+
      EPS.map(e=>`<option value="${esc(e.id)}">${esc(e.name)}</option>`).join("");
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
  const body={id:EP_EDIT||null,name:$("epName").value.trim(),url:$("epUrl").value.trim(),
              api_key:$("epKey").value,model:$("epModel").value.trim()};
  if(!body.url||!body.model){msg("epOut","warning","API 地址与模型名称必填");return}
  const d=await postJSON("/api/endpoints",body);
  if(!d.ok){msg("epOut","error","保存失败："+d.error);return}
  EPS=d.endpoints||EPS;EP_EDIT=null;renderEpSelects();
  toast(editing?"配置已更新":"已添加「"+d.endpoint.name+"」","success");
  manageEndpoints();
}
function epEdit(id){EP_EDIT=id;manageEndpoints()}
function maskKey(k){k=String(k||"");return k?k.slice(0,4)+"…"+k.slice(-4):"—"}
function epHost(url){const m=String(url||"").match(/^https?:\/\/([^/?#]+)/i);return m?m[1]:String(url||"")}
let EP_EDIT=null;  /* 编辑中的配置 id; null = 新增模式 */
function manageEndpoints(){
  let editing=EP_EDIT?EPS.find(x=>x.id===EP_EDIT):null;
  if(EP_EDIT&&!editing)EP_EDIT=null;
  const val=v=>esc(editing?(v||""):"");
  const cards=EPS.map(e=>{
    const on=editing&&editing.id===e.id;
    return `<article class="ep-card${on?" is-on":""}">
      <div class="ep-card-main">
        <div class="ep-name">${esc(e.name)}</div>
        <div class="ep-sub" title="${esc(e.url)}">
          <span class="ep-model">${esc(e.model||"—")}</span><span class="ep-dot">·</span>
          <span class="ep-host">${esc(epHost(e.url))}</span><span class="ep-dot">·</span>
          <span class="ep-keymask">${esc(maskKey(e.api_key))}</span>
        </div>
      </div>
      <div class="ep-card-actions">
        <button type="button" class="btn btn-secondary btn-sm" data-ep-use="${esc(e.id)}" title="填入性能、能力、代码生成三个表单">填入</button>
        <button type="button" class="btn btn-ghost btn-icon btn-sm" data-ep-edit="${esc(e.id)}" title="编辑" aria-label="编辑">${icon("sliders")}</button>
        <button type="button" class="btn btn-ghost btn-icon btn-sm ep-del" data-ep-del="${esc(e.id)}" title="删除" aria-label="删除">${icon("trash")}</button>
      </div>
    </article>`;
  }).join("");
  const form=`<form class="ep-form" autocomplete="off" onsubmit="epSave();return false">
      <div class="eyebrow">${editing?"正在编辑":"新建"}</div>
      <div class="ep-fields">
        <div class="field span-2"><label for="epName">名称</label><input class="input" id="epName" placeholder="留空则用「模型 · 主机」" value="${editing?esc(editing.name):""}"></div>
        <div class="field span-2"><label for="epUrl">API 地址</label><input class="input" id="epUrl" placeholder="http://127.0.0.1:8000" value="${val(editing&&editing.url)}"></div>
        <div class="field"><label for="epModel">模型</label><input class="input" id="epModel" placeholder="模型名称" value="${val(editing&&editing.model)}"></div>
        <div class="field"><label for="epKey">API Key</label>
          <div class="ep-keywrap"><input class="input" id="epKey" type="password" autocomplete="off" placeholder="可选" value="${val(editing&&editing.api_key)}">
          <button type="button" class="btn btn-ghost btn-icon btn-sm" data-ep-reveal title="显示 Key" aria-label="显示 Key">${icon("eye")}</button></div></div>
      </div>
      <div class="ep-actions">
        <span class="inline-msg" id="epOut"></span>
        ${editing?'<button type="button" class="btn btn-ghost btn-sm" data-ep-cancel>取消</button>':""}
        <button type="submit" class="btn btn-primary btn-sm">${editing?"保存":"添加"}</button>
      </div>
    </form>`;
  Modal.open("模型管理",`
    <div class="ep-shell">
      <div class="ep-list-head"><span class="eyebrow">已保存</span><span class="ep-count">${EPS.length}</span></div>
      <div class="ep-list">${cards||'<p class="ep-empty">还没有配置</p>'}</div>
      ${form}
      <p class="ep-note">存在本机数据库。填入会同步到性能、能力、代码生成三个页面。</p>
    </div>`,{panel:true});
}
async function epApply(id){
  const ep=EPS.find(x=>x.id===id);if(!ep)return;
  Object.keys(EP_FIELDS).forEach(page=>epFill(page,ep));
  Modal.close();
  postJSON("/api/endpoint-use",{id}).catch(()=>{});
  toast(`已填入「${ep.name}」· 性能 / 能力 / 代码生成三个表单`,"success");
}
async function epRemove(id){
  const ep=EPS.find(x=>x.id===id);if(!ep)return;
  const ok=await confirmDialog({title:"删除模型配置",message:"确定删除「"+ep.name+"」吗？已填入表单的内容不受影响。",confirmText:"删除",danger:true});
  if(!ok){manageEndpoints();return}
  await postJSON("/api/endpoint-delete",{id});
  await loadEndpoints();
  manageEndpoints();
}
Object.keys(EP_SEL).forEach(page=>{const sel=$(EP_SEL[page]);if(sel)sel.addEventListener("change",()=>onEpSelect(page))});

/* ---------- 任务场景: 模板 chips / 条件参数 / 资产(任务集/图片包) ---------- */
const SCN_TPL=[
  ["chat","对话问答","短答与长文混合的通用问答"],
  ["code","代码生成","实现函数/类/脚本/修 bug"],
  ["json","结构化抽取","商品信息→标准 JSON(合法率)"],
  ["rag","RAG 问答","长上下文+引用式回答, 可选档位"],
  ["vision","图片理解","图片描述/图表解读/文字提取"],
  ["custom","自定义任务集","上传你自己的请求 JSONL"],
];
const RAG_CTX_OPTS=[[1500,"1.5K"],[4000,"4K"],[16000,"16K"]];
function scnChip(val,label,tip,checked){
  return `<label class="chip-check" title="${esc(tip)}"><input type="checkbox" value="${esc(val)}" ${checked?"checked":""}>${esc(label)}</label>`;
}
function renderScnChips(){
  const sel=new Set(lsGet("llm-bench-pro-scn").tasks||[]);
  $("scnChips").innerHTML=SCN_TPL.map(([id,name,tip])=>scnChip(id,name,tip,sel.has(id))).join("");
  const ctxSel=new Set(lsGet("llm-bench-pro-scn").rag_ctx||[4000]);
  $("ragCtxChips").innerHTML=RAG_CTX_OPTS.map(([v,l])=>scnChip(v,l,"上下文约 "+l+" tokens",ctxSel.has(v))).join("");
}
function scnSelected(){
  return [...document.querySelectorAll("#scnChips input:checked")].map(x=>x.value);
}
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
  if(files.reduce((s,f)=>s+f.size,0)>15*1024*1024){msg("probeOut","error","图片总量超过 15MB：请分批上传或放服务器目录后填路径");return}
  msg("probeOut","info","正在上传 "+files.length+" 张图片…");
  try{
    const payload=await Promise.all(files.map(async f=>({name:f.name,data:await readFileBase64(f)})));
    const d=await postJSON("/api/scenario-upload",{kind:"images",files:payload});
    if(!d.ok){msg("probeOut","error","上传失败："+d.error);return}
    await loadScenarioAssets(d.image_id);
    msg("probeOut","success",`已上传图片包：${d.count} 张（${(d.size/1048576).toFixed(1)} MB）`);
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
    msg("probeOut","success",`已上传任务集：${fmtInt(d.lines)} 条可用请求${d.bad_lines?`（${d.bad_lines} 行无效已忽略）`:""}`);
  }catch(err){msg("probeOut","error",err.message)}
});
$("fSuite").addEventListener("change",suitePlaceholders);
suitePlaceholders();

async function probe(){
  const btn=$("btnProbe");setBusy(btn,true);msg("probeOut","info","正在连接…");
  try{
    const d=await postJSON("/api/probe",{base:$("fBase").value,api_key:$("fKey").value});
    if(!d.ok){msg("probeOut","error","连接失败："+d.error);return}
    $("modelList").innerHTML=d.models.map(m=>`<option value="${esc(m.id)}">${m.max_model_len?"上下文 "+Math.round(m.max_model_len/1024)+"K":""}</option>`).join("");
    if(d.models.length&&!$("fModel").value)$("fModel").value=d.models[0].id;
    if(!$("fFw").value&&d.framework)$("fFw").value=d.framework;
    if(!$("fFwVer").value&&d.fw_version)$("fFwVer").value=d.fw_version;
    msg("probeOut","success",`连接成功 · 延迟 ${d.latency_ms} ms · 可用模型 ${d.count} 个${d.framework?" · "+d.framework+(d.fw_version?" "+d.fw_version:""):""}`);
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
      scen.vision_src={image_id:$("fImgSel").value||undefined,dir:$("fImgDir").value.trim()||undefined,
        images:parseInt($("fImgN").value)||1};
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
  watchPerf("运行中 · "+model);
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
  if(f.size>15*1024*1024){msg("probeOut","error","文件超过 15MB：请放到运行服务的机器上，用 CLI --replay-file 引用");return}
  msg("probeOut","info","正在上传 "+f.name+"…");
  try{
    const d=await postJSON("/api/replay-upload",{name:f.name,content:await f.text()});
    if(!d.ok){msg("probeOut","error","上传失败："+d.error);return}
    await loadReplayFiles(d.file_id);
    msg("probeOut","success",`已上传 ${f.name}：${fmtInt(d.lines)} 条可用请求${d.bad_lines?`（${d.bad_lines} 行无效已忽略）`:""}`);
  }catch(err){msg("probeOut","error","读取文件失败："+err.message)}
});

/* ---------- 离线报告导出 ---------- */
function exportReport(view){
  const idA=view==="cmp"?$("cmpA").value:$("runA").value;
  if(!idA){toast("请先选择运行","warning");return}
  const idB=view==="cmp"?$("cmpB").value:$("runB").value;
  const url="/api/report?id="+encodeURIComponent(idA)+(idB?"&cmp="+encodeURIComponent(idB):"");
  const a=document.createElement("a");
  a.href=url;a.rel="noopener";
  document.body.appendChild(a);a.click();a.remove();
  toast("已开始下载离线报告（自包含 HTML，可直接发送他人打开）","success",3500);
}

async function refresh(focusNew){
  status("加载中…");
  if(!RUNS_LOADED)$("dashEmpty").innerHTML=`<div class="kpi-grid">${'<div class="kpi"><div class="skeleton" style="height:12px;width:50%"></div><div class="skeleton" style="height:28px;width:70%;margin-top:12px"></div></div>'.repeat(4)}</div>`;
  try{
    const list=await getJSON("/api/results?summary=1");
    if(!SERVER.version)setConn(true,"服务已连接");
    const prev=new Set(Object.keys(RUNS));
    RUNS={};list.forEach(r=>RUNS[r.run_id]=r);
    Object.keys(FULL).forEach(id=>{const m=RUNS[id];  /* 已删除或状态/完成时间变化的运行重新加载详情 */
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
    $("cmpB").innerHTML=`<option value="">选择运行 B</option>`+opts(cB);
    status(names.length?`共 ${names.length} 次运行`:"");
    if(!names.length)toggleLauncher("launcher",true);
    redrawVisible();
  }catch(e){
    setConn(false,"服务未连接");
    status("");
    $("dashEmpty").innerHTML=emptyState("无法连接后端服务","请确认 python run.py 正在运行（"+e.message+"）",{iconName:"alert"});
    $("dashBody").hidden=true;
  }
}
function label(r){
  const fw=r.framework&&r.framework.name?`${r.framework.name}${r.framework.version?" "+r.framework.version:""}`:null;
  return [r.model||"?",fw,SUITE_NAME[r.suite]||r.suite,r.tag||"",r.status&&r.status!=="done"?STATUS_NAME[r.status]||r.status:"",shortTime(r.started_utc)].filter(Boolean).join(" · ");
}
function status(s){$("status").textContent=s}
function phase(run,id){return run&&(run.phases||[]).find(p=>p.id===id)}

/* 指标提取: KPI / 对比卡 / 差异表共用; dir=1 越高越好, -1 越低越好 */
function perfCtx(r){
  const dp=phase(r,"decode"),pp=phase(r,"prefill"),cp=phase(r,"concurrency"),pcp=phase(r,"prefill_conc");
  const rpp=phase(r,"replay"),olp=phase(r,"openloop");
  let ok=0,tot=0;(cp?cp.points:[]).forEach(p=>{ok+=p.ok;tot+=p.ok+p.fail});
  const scn=(r.phases||[]).filter(p=>(p.id||"").startsWith("scn_"));
  let jok=0,jtot=0,scnLast=null;
  scn.forEach(p=>(p.points||[]).forEach(pt=>{
    jok+=pt.json_ok||0;jtot+=pt.json_total||0;
    if(pt.ctx_tokens==null&&(!scnLast||(pt.conc||0)>(scnLast.conc||0)))scnLast=pt;  // 非RAG场景的最高并发点
  }));
  return{
    zh:dp&&dp.cases.find(c=>c.lang==="zh"),en:dp&&dp.cases.find(c=>c.lang==="en"),
    peak:cp&&cp.points.length?cp.points.reduce((m,p)=>p.agg_tps>m.agg_tps?p:m):null,
    pLast:pp&&pp.points.length?pp.points[pp.points.length-1]:null,
    cLast:cp&&cp.points.length?cp.points[cp.points.length-1]:null,
    pcp,s:pcp&&pcp.summary,succ:tot?100*ok/tot:null,
    scnLast,jsonRate:jtot?100*jok/jtot:null,
    rpLast:rpp&&rpp.points.length?rpp.points[rpp.points.length-1]:null,
    olLast:olp&&olp.points.length?olp.points[olp.points.length-1]:null,
    olMax:olp&&olp.points.length?Math.max(...olp.points.map(p=>p.max_inflight||0)):null};
}
const PERF_METRICS=[
  {key:"zh",label:()=>"单流解码 · 中文",unit:"tok/s",dir:1,val:m=>m.zh&&m.zh.decode_tps_med,sub:m=>m.zh?`${m.zh.out_tokens} tokens · Burst ${fmt(m.zh.spec_burst_med,2)}`:""},
  {key:"en",label:()=>"单流解码 · 英文",unit:"tok/s",dir:1,val:m=>m.en&&m.en.decode_tps_med,sub:m=>m.en?`ITL p50 ${fmt(m.en.itl_p50_ms_med)} ms`:""},
  {key:"peak",label:()=>"峰值聚合吞吐",unit:"tok/s",dir:1,val:m=>m.peak&&m.peak.agg_tps,sub:m=>m.peak?`并发 ${m.peak.conc}`:""},
  {key:"mpre",label:m=>`矩阵 Prefill 均值${m.pcp?"（"+m.pcp.conc+" 并发）":""}`,unit:"tok/s",dir:1,digits:0,val:m=>m.s&&m.s.prefill_avg,sub:m=>m.s?`范围 ${fmtInt(m.s.prefill_min)}–${fmtInt(m.s.prefill_max)}`:""},
  {key:"mdec",label:m=>`矩阵输出均值${m.pcp?"（"+m.pcp.conc+" 并发）":""}`,unit:"tok/s",dir:1,val:m=>m.s&&m.s.decode_avg,sub:m=>m.s?`单流 P50 ${fmt(m.s.per_stream_decode_p50)} · P95 ${fmt(m.s.per_stream_decode_p95)}`:""},
  {key:"pmax",label:m=>`Prefill @${m.pLast?m.pLast.label:"最大长度"}`,unit:"tok/s",dir:1,digits:0,val:m=>m.pLast&&m.pLast.prefill_tps_med,sub:m=>m.pLast?`TTFT ${fmt(m.pLast.ttft_med_s,2)} s`:""},
  {key:"ttft",label:()=>"TTFT p95（最大并发）",unit:"s",dir:-1,digits:2,val:m=>m.cLast&&m.cLast.ttft_p95_s,sub:m=>m.cLast?`并发 ${m.cLast.conc}`:""},
  {key:"succ",label:()=>"请求成功率",unit:"%",dir:1,val:m=>m.succ,sub:()=>"并发测试阶段"},
];
const CMP_EXTRA=[
  {key:"itl",label:()=>"ITL p50 · 英文",unit:"ms",dir:-1,val:m=>m.en&&m.en.itl_p50_ms_med},
  {key:"burst",label:()=>"Burst · 中文",unit:"tok/chunk",dir:1,digits:2,val:m=>m.zh&&m.zh.spec_burst_med},
  {key:"ttftmax",label:m=>`TTFT @${m.pLast?m.pLast.label:"最大长度"}`,unit:"s",dir:-1,digits:2,val:m=>m.pLast&&m.pLast.ttft_med_s},
  {key:"p50",label:()=>"矩阵单流输出 P50",unit:"tok/s",dir:1,val:m=>m.s&&m.s.per_stream_decode_p50},
  {key:"scnreq",label:()=>"任务场景 请求/秒",unit:"req/s",dir:1,digits:2,val:m=>m.scnLast&&m.scnLast.req_s,
    sub:m=>m.scnLast?`并发 ${m.scnLast.conc}${m.jsonRate!=null?" · JSON 合法 "+fmt(m.jsonRate,0)+"%":""}`:""},
  {key:"rps",label:()=>"回放闭环 请求/秒",unit:"req/s",dir:1,digits:2,val:m=>m.rpLast&&m.rpLast.req_s,
    sub:m=>m.rpLast?`并发 ${m.rpLast.conc} · 最大在途 ${fmtInt(m.rpLast.max_inflight)}`:""},
  {key:"inf",label:m=>`开环最大在途${m.olLast?" @"+m.olLast.rate+" rps":""}`,unit:"个",dir:-1,digits:0,val:m=>m.olMax,
    sub:m=>m.olLast?`完成 ${fmt(m.olLast.completed_rps,2)} / 目标 ${m.olLast.rate} req/s`:""},
];
function safeVal(f,m){try{const v=f(m);return v==null||!isFinite(v)?null:v}catch(e){return null}}
function deltaPill(va,vb,dir,{mode="pct",prefix=""}={}){
  if(va==null||vb==null)return `<span class="delta flat">—</span>`;
  const d=mode==="pp"?vb-va:(va?(vb-va)/Math.abs(va)*100:0);
  const flat=Math.abs(d)<(mode==="pp"?.5:1);
  if(flat)return `<span class="delta flat" title="${dir<0?"越低越好":"越高越好"}">${icon("minus")}${prefix}±${fmt(Math.abs(d),1)}${mode==="pp"?" pp":"%"}</span>`;
  const good=d*dir>0;
  const cls=good?"up":"down";
  const ic=d>0?"arrow-up":"arrow-down";
  return `<span class="delta ${cls}" title="${dir<0?"越低越好":"越高越好"}">${icon(ic)}${prefix}${d>=0?"+":""}${fmt(d,1)}${mode==="pp"?" pp":"%"}</span>`;
}

async function render(){
  if(!RUNS_LOADED)return;
  const idA=$("runA").value,idB=$("runB").value;
  if(!RUNS[idA]){
    $("dashBody").hidden=true;
    $("dashEmpty").innerHTML=emptyState("暂无运行记录","新建一次性能测试后，结果会显示在这里",
      {action:`<button class="btn btn-primary" data-toggle="launcher">${icon("plus")}新建测试</button>`});
    return;
  }
  const seq=++renderSeq;
  try{await ensureRuns([idA,RUNS[idB]?idB:""])}
  catch(e){$("dashEmpty").innerHTML=emptyState("加载运行详情失败",e.message,{iconName:"alert",inline:true});return}
  if(seq!==renderSeq)return;  /* 期间切换了选择, 以最新一次为准 */
  const a=FULL[idA],b=RUNS[idB]?FULL[idB]:null;
  $("dashEmpty").innerHTML="";$("dashBody").hidden=false;
  const ov=a.overrides||{};
  $("meta").innerHTML=[
    ["模型",a.model],["套件",SUITE_NAME[a.suite]||a.suite],["端点",(a.url||"").replace(/https?:\/\//,"").replace(/\/v1\/chat\/completions$/,"")],
    ov.conc_ladder&&["并发梯度",ov.conc_ladder.join(", ")],ov.matrix_conc&&["矩阵并发",ov.matrix_conc],
    ov.lens&&["输入长度",ov.lens.map(k=>k+"K").join(", ")],
    a.framework&&a.framework.name&&["框架",a.framework.name+(a.framework.version?" "+a.framework.version:"")],
    a.tag&&["标签",a.tag],["开始",timeText(a.started_utc)],
    ov.fixed_output!=null&&["输出长度",ov.fixed_output?"固定（ignore_eos）":(ov.fixed_output_note?"未固定（端点不支持）":"未固定")],
    a.status&&a.status!=="done"&&["状态",STATUS_NAME[a.status]||a.status],
  ].filter(Boolean).map(([k,v])=>`<span class="badge${k==="状态"?" is-warning":""}">${esc(k)} <b>${esc(v)}</b></span>`).join("");
  const hints=perfAnomalies(a);
  $("anomalies").innerHTML=hints.length?`<div class="alert is-info">${icon("info")}<div><b>数据提示</b><ul class="hint-list">${hints.map(h=>`<li>${esc(h)}</li>`).join("")}</ul></div></div>`:"";
  renderKPIs(a,b);
  pcTable(a,b);
  drawPrefill(a,b,"cPrefill","lPre");
  concChart(a,b,"cConc","lConc");
  decodeTable(a,b);
  metricsChart(a);
  scnPanels(a,b,"dashGrid","replayPanel");
  replayTable(a,b);
  olPanel(a,b);
}
/* 自动识别值得关注的数据现象(不代表测试出错, 提示人工确认) */
function perfAnomalies(r){
  const out=[...(r.notes||[])];
  const ov=r.overrides||{},cp=phase(r,"concurrency");
  if(cp&&cp.points.length>1){
    const pts=cp.points;
    for(let i=1;i<pts.length;i++){
      const p0=pts[i-1],p1=pts[i];
      if(p0.agg_tps>0&&p1.agg_tps<p0.agg_tps*0.95)
        out.push(`并发 ${p0.conc} → ${p1.conc} 时聚合吞吐不升反降（${fmt(p0.agg_tps)} → ${fmt(p1.agg_tps)} tok/s），扩展性异常`);
    }
    const c1=pts.find(p=>p.conc===1),c2=pts.find(p=>p.conc>1);
    const dp=phase(r,"decode"),zh=dp&&dp.cases.find(c=>c.lang==="zh");
    if(c1&&c2&&c1.per_stream_tps_med&&c2.per_stream_tps_med&&c2.per_stream_tps_med<c1.per_stream_tps_med*0.5)
      out.push(`单流速度从并发 1 的 ${fmt(c1.per_stream_tps_med)} 降到并发 ${c2.conc} 的 ${fmt(c2.per_stream_tps_med)} tok/s（下降 ${fmt(100-100*c2.per_stream_tps_med/c1.per_stream_tps_med,0)}%）`+
        (zh&&zh.spec_burst_med>1.3?`；单并发时 Burst 为 ${fmt(zh.spec_burst_med,2)}，投机解码可能只在单并发时生效`:""));
    const fail=pts.reduce((s,p)=>s+(p.fail||0),0);
    if(fail)out.push(`并发阶段有 ${fail} 个请求失败`);
  }
  if(ov.fixed_output===false&&ov.fixed_output_note)out.push(ov.fixed_output_note+"：模型提前结束时吞吐会偏高，不同后端之间不可直接比较");
  if(r.status&&!["done","running"].includes(r.status))out.push(`该运行${STATUS_NAME[r.status]||r.status}${r.error?"（"+r.error+"）":""}，部分阶段可能缺失`);
  return out;
}
function renderKPIs(a,b){
  const ma=perfCtx(a),mb=b?perfCtx(b):null;
  $("kpis").innerHTML=PERF_METRICS.map(k=>{
    const va=safeVal(k.val,ma),vb=mb?safeVal(k.val,mb):null;
    const value=va==null?"—":(k.unit==="%"?fmt(va,k.digits??1):(k.digits===0?fmtInt(va):fmt(va,k.digits??1)));
    return `<div class="kpi"><div class="kpi-head"><span class="kpi-label" title="${esc(k.label(ma))}">${esc(k.label(ma))}</span>${mb?deltaPill(va,vb,k.dir,{prefix:"B "}):""}</div>
      <div class="kpi-value num">${value}${va!=null?`<small>${k.unit}</small>`:""}</div>
      <div class="kpi-sub">${esc(safeSub(k,ma))}</div></div>`;
  }).join("");
}
function safeSub(k,m){try{return k.sub?k.sub(m):""}catch(e){return""}}
function abCell(va,vb,f,hasB){
  return `${f(va)}${hasB?`<span class="sub">B ${f(vb)}</span>`:""}`;
}
function pcTable(a,b){
  const pa=phase(a,"prefill_conc"),pb=b?phase(b,"prefill_conc"):null;
  const el=$("pcTbl");
  if(!pa){el.innerHTML=emptyState("该运行不包含此阶段数据","旧版本生成的结果，重新运行即可获得",{inline:true});return}
  const two=!!pb;
  let html=`<div class="table-wrap"><table class="table"><thead><tr><th>输入长度</th><th>TTFT 均值 (ms)</th><th>ITL 均值 (ms)</th><th>聚合 Prefill (tok/s)</th><th>聚合输出 (tok/s)</th><th>成功</th></tr></thead><tbody>`;
  pa.points.forEach(p=>{
    const q=two?pb.points.find(x=>x.label===p.label)||null:null;
    const has=two;
    const det=(x,who)=>x?`<b>${who}</b> 单流 Prefill：${x.stream_prefill_tps.map(v=>fmtInt(v)).join(" / ")} tok/s　单流输出：${x.stream_decode_tps.map(v=>fmt(v)).join(" / ")} tok/s`:"";
    html+=`<tr class="expandable" data-expand aria-expanded="false"><td>${icon("chevron-right","icon-sm")}${esc(p.label)}<span class="sub">${fmtInt(p.in_tokens)} tokens</span></td>
      <td>${abCell(p.ttft_avg_ms,q&&q.ttft_avg_ms,v=>fmtInt(v),has)}</td>
      <td>${abCell(p.itl_avg_ms,q&&q.itl_avg_ms,v=>fmt(v),has)}</td>
      <td>${abCell(p.prefill_tps_agg,q&&q.prefill_tps_agg,v=>fmtInt(v),has)}</td>
      <td>${abCell(p.decode_tps_agg,q&&q.decode_tps_agg,v=>fmt(v),has)}</td>
      <td>${p.ok} / ${p.ok+p.fail}${has?`<span class="sub">B ${q?q.ok+" / "+(q.ok+q.fail):"—"}</span>`:""}</td></tr>
      <tr class="detail" hidden><td colspan="6">${det(p,"A")}${q?"<br>"+det(q,"B"):""}</td></tr>`;
  });
  html+=`</tbody></table></div>`;
  const rows=[[pa.summary,"A"],two&&[pb.summary,"B"]].filter(x=>x&&x[0]);
  if(rows.length){
    html+=`<div class="table-caption">汇总</div><div class="table-wrap"><table class="table"><thead><tr><th>运行</th><th>Prefill 范围 / 均值 (tok/s)</th><th>输出范围 / 均值 (tok/s)</th><th>单流 Prefill P50 / P90 / P95</th><th>单流输出 P50 / P90 / P95</th></tr></thead><tbody>`+
      rows.map(([s,who])=>`<tr><td><span class="run-tag ${who.toLowerCase()}">${who}</span></td>
        <td>${fmtInt(s.prefill_min)} – ${fmtInt(s.prefill_max)} / <b>${fmtInt(s.prefill_avg)}</b></td>
        <td>${fmt(s.decode_min)} – ${fmt(s.decode_max)} / <b>${fmt(s.decode_avg)}</b></td>
        <td>${fmtInt(s.per_stream_prefill_p50)} / ${fmtInt(s.per_stream_prefill_p90)} / ${fmtInt(s.per_stream_prefill_p95)}</td>
        <td>${fmt(s.per_stream_decode_p50)} / ${fmt(s.per_stream_decode_p90)} / ${fmt(s.per_stream_decode_p95)}</td></tr>`).join("")+
      `</tbody></table></div>`;
  }
  el.innerHTML=html;
}
function decodeStats(c){
  if(!c)return null;
  const runs=c.runs||[];
  const m=k=>median(runs.map(r=>r[k]));
  return{out:c.out_tokens,tps:c.decode_tps_med,best:c.decode_tps_best,tpot:m("tpot_ms"),p50:c.itl_p50_ms_med,p95:m("itl_p95_ms"),p99:m("itl_p99_ms"),jit:m("itl_jitter_ms"),burst:c.spec_burst_med};
}
function decodeTable(a,b){
  const da=phase(a,"decode"),db=b?phase(b,"decode"):null;
  if(!da){$("decodeTbl").innerHTML=emptyState("该运行不包含此阶段数据","",{inline:true});return}
  const cols=[["tps","解码速度 (tok/s)",1],["best","最佳 (tok/s)",1],["tpot","TPOT (ms)",2],["p50","ITL p50 (ms)",1],["p95","ITL p95 (ms)",1],["p99","ITL p99 (ms)",1],["jit","抖动 (ms)",1],["burst","Burst",2]];
  let html=`<div class="table-wrap"><table class="table"><thead><tr><th>场景</th>${cols.map(c=>`<th>${c[1]}</th>`).join("")}</tr></thead><tbody>`;
  for(const lang of ["zh","en"]){
    const sa=decodeStats(da.cases.find(c=>c.lang===lang)),sb=db?decodeStats(db.cases.find(c=>c.lang===lang)):null;
    if(!sa)continue;
    html+=`<tr><td>${lang==="zh"?"中文":"英文"}<span class="sub">${sa.out} tokens / 次</span></td>`+
      cols.map(([k,,d])=>`<td>${abCell(sa[k],sb&&sb[k],v=>fmt(v,d),!!db)}</td>`).join("")+`</tr>`;
  }
  $("decodeTbl").innerHTML=html+`</tbody></table></div>`;
}

/* ============================================================
   任务场景: 按 scn_* phase 动态生成面板(模板任意组合)
   ============================================================ */
const SCN_LABEL=Object.fromEntries(SCN_TPL.map(([id,name])=>[id,name]));
function retryTag(p){return (p.attempts||1)>1?` <span class="sub" title="失败后整格重跑，明细见离线报告">重跑×${p.attempts}</span>`:""}
function scnPanels(a,b,gridId,beforeId){
  const grid=$(gridId),before=$(beforeId);
  if(!grid)return;
  grid.querySelectorAll("[data-scn-panel]").forEach(x=>x.remove());
  const frag=[];
  for(const p of (a.phases||[])){
    const pid=p.id||"";
    if(!pid.startsWith("scn_"))continue;
    const tpl=pid.slice(4);
    const label=(p.task&&p.task.label)||SCN_LABEL[tpl]||tpl;
    const pb=b?(b.phases||[]).find(x=>x.id===pid):null;
    const isRag=tpl==="rag",key=isRag?"ctx_tokens":"conc";
    const hasJson=(p.points||[]).some(x=>x.json_total);
    const two=!!pb;
    const cols=[isRag?"上下文 tokens":"并发","ok/total","请求/秒","TTFT p95 (s)","端到端 p95 (s)","出 tokens 均值","最大在途"];
    if(hasJson)cols.push("JSON 合法");
    let rows="";
    for(const pt of (p.points||[])){
      const q=two?(pb.points||[]).find(x=>x[key]===pt[key]):null;
      const jr=pt.json_total!=null?`${fmtInt(pt.json_ok)}/${fmtInt(pt.json_total)}<span class="sub">${pt.json_rate!=null?fmt(100*pt.json_rate,0)+"%":""}</span>`:"—";
      const meta=[(pt.attempts||1)>1?`重跑×${pt.attempts}`:"",pt.pool_wrapped?"池已回绕":""].filter(Boolean).map(x=>`<span class="sub">${esc(x)}</span>`).join(" ");
      rows+=`<tr><td>${isRag?fmtInt(pt[key]):fmtInt(pt[key])}${retryTag(pt)}</td>
        <td>${pt.ok}/${pt.total}${pt.fail?`<span class="sub">失败 ${pt.fail}</span>`:""}</td>
        <td>${abCell(pt.req_s,q&&q.req_s,v=>fmt(v,2),two)}</td>
        <td>${abCell(pt.ttft_p95_s,q&&q.ttft_p95_s,v=>fmt(v,2),two)}</td>
        <td>${abCell(pt.e2e_p95_s,q&&q.e2e_p95_s,v=>fmt(v,2),two)}</td>
        <td>${fmt(pt.prompt_tokens_avg?pt.out_tokens_avg:null)}${pt.out_tokens_p90!=null?`<span class="sub">p90 ${fmt(pt.out_tokens_p90,0)}</span>`:""}</td>
        <td>${pt.max_inflight!=null?fmtInt(pt.max_inflight):"—"}</td>
        ${hasJson?`<td>${jr}</td>`:""}${meta?`</tr><tr><td colspan="${cols.length}" class="sub">${meta}</td>`:""}</tr>`;
    }
    const t=p.task||{};
    const desc=[t.max_tokens?("max_tokens "+t.max_tokens):"",t.requests_per_worker?("每并发 "+t.requests_per_worker+" 请求"):"",
      t.images?("图片池 "+t.images+" 张"+(t.images_per_request?("/请求 "+t.images_per_request+" 张"):"")):"",
      t.pool_size?("任务集 "+t.pool_size+" 条"):"",Array.isArray(t.rag_ctx)?("档位 "+t.rag_ctx.map(x=>(x/1000)+"K").join("/")):""]
      .filter(Boolean).join(" · ");
    frag.push(`<div class="panel span-all" data-scn-panel><div class="panel-head"><div><h3 class="panel-title">场景 · ${esc(label)}</h3>
      <p class="panel-desc">真实任务行为（不发送 ignore_eos）${desc?" · "+esc(desc):""}</p></div></div>
      <div class="panel-body"><div class="table-wrap"><table class="table"><thead><tr>${cols.map(c=>`<th>${c}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div></div></div>`);
  }
  if(frag.length)before.insertAdjacentHTML("beforebegin",frag.join(""));
}
function replayTable(a,b,ids){
  ids=ids||{panel:"replayPanel",tbl:"replayTbl"};
  const pa=phase(a,"replay"),pb=b?phase(b,"replay"):null;
  const panel=$(ids.panel);
  if(!pa){panel.hidden=true;return}
  panel.hidden=false;
  const two=!!pb,pool=pa.pool||{};
  let html=`<div class="table-caption">回放池 ${fmtInt(pool.size)} 条${pool.wrapped?` · <span class="sub">已回绕（部分请求重复发送，前缀缓存可能使后段偏快）</span>`:""}${a.replay&&a.replay.file?` · ${esc(a.replay.file)}`:""}</div>
    <div class="table-wrap"><table class="table"><thead><tr><th>并发</th><th>请求/秒</th><th>TTFT p95 (s)</th><th>端到端 p95 (s)</th><th>入/出 tokens 均值</th><th>最大在途</th><th>成功</th></tr></thead><tbody>`;
  pa.points.forEach(p=>{
    const q=two?pb.points.find(x=>x.conc===p.conc):null;
    html+=`<tr><td>${fmtInt(p.conc)}${retryTag(p)}</td>
      <td>${abCell(p.req_s,q&&q.req_s,v=>fmt(v,2),two)}</td>
      <td>${abCell(p.ttft_p95_s,q&&q.ttft_p95_s,v=>fmt(v,2),two)}</td>
      <td>${abCell(p.e2e_p95_s,q&&q.e2e_p95_s,v=>fmt(v,2),two)}</td>
      <td>${fmtInt(p.prompt_tokens_avg)} / ${fmtInt(p.out_tokens_avg)}</td>
      <td>${fmtInt(p.max_inflight)}</td>
      <td>${p.ok}/${p.total}${p.fail?`<span class="sub">失败 ${p.fail}</span>`:""}</td></tr>`;
  });
  $(ids.tbl).innerHTML=html+`</tbody></table></div>`;
}
function olPanel(a,b,ids){
  ids=ids||{panel:"olPanel",tbl:"olTbl",cv:"cOpenloop",lg:"lOpenloop"};
  const pa=phase(a,"openloop"),pb=b?phase(b,"openloop"):null;
  const panel=$(ids.panel);
  if(!pa){panel.hidden=true;return}
  panel.hidden=false;
  const two=!!pb;
  let html=`<div class="table-wrap"><table class="table"><thead><tr><th>速率 (req/s)</th><th>发送/丢弃</th><th>完成 (req/s)</th><th>TTFT p95 (s)</th><th>端到端 p95 (s)</th><th>最大在途</th><th>成功</th></tr></thead><tbody>`;
  pa.points.forEach(p=>{
    const q=two?pb.points.find(x=>x.rate===p.rate):null;
    const lag=p.completed_rps!=null&&p.rate&&p.completed_rps<p.rate*0.9;
    html+=`<tr><td>${fmt(p.rate,p.rate<10?1:0)}${retryTag(p)}</td>
      <td>${fmtInt(p.sent)}${p.shed?`<span class="sub">丢弃 ${p.shed}</span>`:""}</td>
      <td>${abCell(p.completed_rps,q&&q.completed_rps,v=>fmt(v,2),two)}${lag?`<span class="sub" style="color:var(--warning)">目标 ${fmt(p.rate,p.rate<10?1:0)}</span>`:""}</td>
      <td>${abCell(p.ttft_p95_s,q&&q.ttft_p95_s,v=>fmt(v,2),two)}</td>
      <td>${abCell(p.e2e_p95_s,q&&q.e2e_p95_s,v=>fmt(v,2),two)}</td>
      <td>${fmtInt(p.max_inflight)}</td>
      <td>${p.ok}/${p.total}${p.fail?`<span class="sub">失败 ${p.fail}</span>`:""}</td></tr>`;
  });
  $(ids.tbl).innerHTML=html+`</tbody></table></div>`;
  drawOpenloop(pa,pb,ids);
}
function drawOpenloop(pa,pb,ids){
  if(ecReady())return ecOpenloop(pa,pb,ids);
  const cv=$(ids.cv);
  if(!cv||!cv.clientWidth)return;
  const {g,w,h}=setupCanvas(cv);
  const runs=[["A",pa,C.a],["B",pb,C.b]].filter(([_,p])=>p);
  const series=[];
  runs.forEach(([tag,p,base])=>p.points.forEach((pt,j)=>{
    if((pt.inflight_ts||[]).length>1)series.push({pt,color:runs.length>1?base:C.series[j%C.series.length],
      name:(runs.length>1?tag+" ":"")+pt.rate+" rps"});
  }));
  if(!series.length){noData(g,w,h,"无在途采样数据");$(ids.lg).innerHTML="";return}
  const maxT=Math.max(...series.map(s=>s.pt.inflight_ts[s.pt.inflight_ts.length-1][0]),1);
  const ym=niceMax(Math.max(...series.map(s=>Math.max(...s.pt.inflight_ts.map(x=>x[1]||0))),1));
  const pad={l:44,r:14,t:12,b:24};
  drawGrid(g,{pad,w,h,ymax:ym,fmtY:fmtAxis});
  const X=t=>pad.l+(w-pad.l-pad.r)*t/maxT,Y=v=>pad.t+(h-pad.t-pad.b)*(1-v/ym);
  series.forEach(s=>{
    const pts=s.pt.inflight_ts.map(([t,v])=>({x:X(t),y:Y(v),t,v})).filter(p=>p.y!=null);
    strokeSeries(g,pts,s.color,{width:1.75});
    pts.forEach((p,i)=>{if(i%3)return;cv._hit.push({x:p.x,y:p.y,
      html:tt(`${s.name} · t+${Math.round(p.t)}s`,[[s.color,"在途请求",fmtInt(p.v)]])})});
  });
  g.fillStyle=C.text;g.textAlign="center";
  for(let i=0;i<=4;i++){const t=maxT*i/4;g.fillText(Math.round(t)+"s",X(t),h-pad.b+14)}
  g.textAlign="left";
  axisTitles(g,pad,w,"在途请求","","");
  $(ids.lg).innerHTML=series.map(s=>legendBtn("",s.color,s.name)).join("");
  bindTips(cv);
}

async function deleteRun(kind){
  const sel={perf:"runA",iq:"iqMainSel",gen:"genMainSel"}[kind],id=$(sel).value;
  const meta={perf:RUNS,iq:IQ_RUNS,gen:GEN_RUNS}[kind][id];
  if(!meta){toast("没有可删除的运行","warning");return}
  const name={perf:label,iq:iqLabel,gen:genLabel}[kind](meta);
  const ok=await confirmDialog({title:"删除运行",confirmText:"删除",danger:true,
    message:`删除后不可恢复${kind==="gen"?"，作品文件与检测截图也会一并删除":""}。\n\n${name}`});
  if(!ok)return;
  const d=await postJSON("/api/run-delete",{run_id:id});
  if(!d.ok){toast("删除失败："+d.error,"error");return}
  toast("已删除运行","success",2500);
  if(kind==="perf"){delete FULL[id];refresh()}
  else if(kind==="iq"){IQ_CMP.delete(id);loadIqResults()}
  else loadGenResults();
}

/* ============================================================
   运行对比
   ============================================================ */
function swapCmp(){const a=$("cmpA").value,b=$("cmpB").value;if(!b)return;$("cmpA").value=b;$("cmpB").value=a;renderCmp()}
function runCard(r,tag){
  const fw=r.framework&&r.framework.name?`${r.framework.name}${r.framework.version?" "+r.framework.version:""}`:"框架未标注";
  return `<div class="card cmp-run"><span class="run-tag ${tag.toLowerCase()}">${tag}</span><div style="min-width:0">
    <div class="cmp-run-name">${esc(r.model||"?")}</div>
    <div class="cmp-run-meta">${esc([fw,SUITE_NAME[r.suite]||r.suite,r.tag,timeText(r.started_utc)].filter(Boolean).join(" · "))}</div></div></div>`;
}
async function renderCmp(){
  if(!RUNS_LOADED)return;
  const idA=$("cmpA").value,idB=$("cmpB").value;
  const el=$("cmpBody");
  if(!RUNS[idA]){el.innerHTML=emptyState("暂无运行记录","先在性能基准页完成至少两次运行");return}
  if(!RUNS[idB]){el.innerHTML=runCardsOnly(RUNS[idA])+emptyState("选择运行 B 以查看对比","例如不同框架版本、不同量化方案或不同推理引擎",{iconName:"compare"});return}
  const seq=++cmpSeq;
  try{await ensureRuns([idA,idB])}catch(e){el.innerHTML=emptyState("加载运行详情失败",e.message,{iconName:"alert"});return}
  if(seq!==cmpSeq)return;
  const a=FULL[idA],b=FULL[idB];
  const ma=perfCtx(a),mb=perfCtx(b);
  const cards=[...PERF_METRICS,...CMP_EXTRA].map(k=>{
    const va=safeVal(k.val,ma),vb=safeVal(k.val,mb),d=k.digits??1;
    const f=v=>v==null?"—":(d===0?fmtInt(v):fmt(v,d));
    return `<div class="kpi"><div class="kpi-head"><span class="kpi-label" title="${esc(k.label(ma))}">${esc(k.label(ma))}</span>${deltaPill(va,vb,k.dir)}</div>
      <div class="cmp-values num"><span>${f(va)}</span><span class="arrow">→</span><span>${f(vb)}</span><small class="faint" style="font-size:12px;font-weight:400">${k.unit}</small></div></div>`;
  }).join("");
  el.innerHTML=`<div class="cmp-runs">${runCard(a,"A")}${runCard(b,"B")}</div>
    <div class="kpi-grid">${cards}</div>
    <div class="grid-2" id="cmpGrid">
      <div class="panel"><div class="panel-head"><div><h3 class="panel-title">Prefill 吞吐对比</h3><p class="panel-desc">单流 Prefill 速度随输入长度的变化</p></div></div>
        <div class="panel-body"><canvas class="chart" id="cCmpPrefill"></canvas><div class="legend" id="lCmpPre"></div></div></div>
      <div class="panel"><div class="panel-head"><div><h3 class="panel-title">并发扩展性对比</h3><p class="panel-desc">聚合吞吐、单流吞吐与 TTFT p95</p></div></div>
        <div class="panel-body"><canvas class="chart" id="cCmpConc"></canvas><div class="legend" id="lCmpConc"></div></div></div>
      <div class="panel span-all"><div class="panel-head"><div><h3 class="panel-title">按输入长度对比</h3><p class="panel-desc">输入长度 × 并发矩阵中同档位的聚合吞吐</p></div></div>
        <div class="panel-body" id="cmpMatrix"></div></div>
      <div class="panel span-all"><div class="panel-head"><div><h3 class="panel-title">指标差异</h3><p class="panel-desc">颜色按指标优劣标注，延迟类指标越低越好</p></div></div>
        <div class="panel-body" id="diffTbl"></div></div>
      <div class="panel span-all" id="replayPanelC" hidden><div class="panel-head"><div><h3 class="panel-title">真实请求回放 · 闭环对比</h3><p class="panel-desc">同一回放池、同一请求顺序</p></div></div>
        <div class="panel-body" id="replayTblC"></div></div>
      <div class="panel span-all" id="olPanelC" hidden><div class="panel-head"><div><h3 class="panel-title">真实请求回放 · 开环对比</h3><p class="panel-desc">泊松到达时间轴相同（固定种子），A/B 差异全部来自服务端</p></div></div>
        <div class="panel-body"><canvas class="chart" id="cOpenloopC"></canvas><div class="legend" id="lOpenloopC"></div><div id="olTblC"></div></div></div>
    </div>`;
  drawPrefill(a,b,"cCmpPrefill","lCmpPre");
  concChart(a,b,"cCmpConc","lCmpConc");
  cmpMatrix(a,b);
  diffTable(a,b);
  scnPanels(a,b,"cmpGrid","replayPanelC");
  replayTable(a,b,{panel:"replayPanelC",tbl:"replayTblC"});
  olPanel(a,b,{panel:"olPanelC",tbl:"olTblC",cv:"cOpenloopC",lg:"lOpenloopC"});
}
function runCardsOnly(a){return `<div class="cmp-runs">${runCard(a,"A")}</div>`}
function cmpMatrix(a,b){
  const pA=phase(a,"prefill_conc"),pB=phase(b,"prefill_conc");
  if(!pA||!pB){$("cmpMatrix").innerHTML=emptyState("两次运行需都包含输入长度 × 并发矩阵阶段","",{inline:true});return}
  let t=`<div class="table-wrap"><table class="table"><thead><tr><th>输入长度</th><th>A Prefill</th><th>B Prefill</th><th>变化</th><th>A 输出</th><th>B 输出</th><th>变化</th></tr></thead><tbody>`;
  pA.points.forEach(p=>{
    const q=pB.points.reduce((best,x)=>Math.abs(x.in_tokens-p.in_tokens)<Math.abs(best.in_tokens-p.in_tokens)?x:best,pB.points[0]);
    const far=q&&Math.abs(q.in_tokens-p.in_tokens)/p.in_tokens>.3;
    const dl=(x,y)=>far?`<td class="na" title="B 最接近的档位为 ${esc(q.label)}">档位不匹配</td>`:`<td>${deltaPill(x,y,1)}</td>`;
    t+=`<tr><td>${esc(p.label)}<span class="sub">${fmtInt(p.in_tokens)} tokens</span></td>
      <td>${fmtInt(p.prefill_tps_agg)}</td><td>${far?"—":fmtInt(q.prefill_tps_agg)}</td>${dl(p.prefill_tps_agg,q.prefill_tps_agg)}
      <td>${fmt(p.decode_tps_agg)}</td><td>${far?"—":fmt(q.decode_tps_agg)}</td>${dl(p.decode_tps_agg,q.decode_tps_agg)}</tr>`;
  });
  $("cmpMatrix").innerHTML=t+`</tbody></table></div>`;
}
function diffTable(a,b){
  const ma=perfCtx(a),mb=perfCtx(b);
  let t=`<div class="table-wrap"><table class="table"><thead><tr><th>指标</th><th>方向</th><th><span class="run-tag a">A</span></th><th><span class="run-tag b">B</span></th><th>差值</th><th>变化</th></tr></thead><tbody>`;
  [...PERF_METRICS,...CMP_EXTRA].forEach(k=>{
    const va=safeVal(k.val,ma),vb=safeVal(k.val,mb),dg=k.digits??1;
    if(va==null&&vb==null)return;
    const d=va!=null&&vb!=null?vb-va:null;
    const cls=d==null||Math.abs(d)<1e-9?"na":(d*k.dir>0?"up":"down");
    t+=`<tr><td>${esc(k.label(ma))}<span class="sub">${esc(k.unit)}</span></td><td class="faint">${k.dir<0?"越低越好":"越高越好"}</td>
      <td>${fmt(va,dg)}</td><td>${fmt(vb,dg)}</td><td class="${cls}">${d==null?"—":(d>=0?"+":"")+fmt(d,dg)}</td><td>${deltaPill(va,vb,k.dir)}</td></tr>`;
  });
  $("diffTbl").innerHTML=t+`</tbody></table></div>`;
}

/* ============================================================
   能力评测
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
  if(!s.temperature)return"贪心解码";
  return [`T ${s.temperature}`,s.top_p!=null?`top_p ${s.top_p}`:"",s.top_k!=null?`top_k ${s.top_k}`:""].filter(Boolean).join(" · ");
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
  if(!d.ok){toast("续跑失败："+d.error,"error");return}
  toggleLauncher("iqLauncher",true);
  watchIq("续跑 · "+(r?iqLabel(r):runId));
  $("iqLog").scrollIntoView({behavior:"smooth",block:"nearest"});
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
  $("iqBankInfo").textContent=b?`${b.total} 题：`+(b.subjects||[]).map(s=>`${s.name} ${s.n}`).join("、"):"暂无题集，请在“题集管理”中更新";
}
async function bankUpdate(){
  const btn=$("iqBtnBank");setBusy(btn,true);
  msg("iqMsg","info","正在下载题集（MMLU、GSM8K、MATH-500、ARC、HellaSwag、C-Eval、IFEval），预计 3–5 分钟，请保持页面打开");
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
  watchIq("运行中 · "+model);
}
function watchIq(title){
  $("iqBtnStart").disabled=true;iqLog.start(title);
  clearInterval(iqPoll);
  iqPoll=pollStatus("/api/iq-status",iqLog,{onDone:()=>{$("iqBtnStart").disabled=false;loadIqResults(true)}});
}
function runFw(r){return r.framework&&r.framework.name?`${r.framework.name}${r.framework.version?" "+r.framework.version:""}`:""}
function iqLabel(r){
  const acc=r.overall&&r.overall.acc!=null?r.overall.acc+"%":(STATUS_NAME[r.status]||"未完成");
  return [r.model||"?",runFw(r),r.thinking?"思考":"非思考",acc,r.tag||"",shortTime(r.started_utc)].filter(Boolean).join(" · ");
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
    if(!names.length)toggleLauncher("iqLauncher",true);
    renderIq();
  }catch(e){$("iqResult").innerHTML=emptyState("无法加载评测结果",e.message,{iconName:"alert"})}
}
function renderIqCmpList(mainId){
  const names=Object.keys(IQ_RUNS).sort().reverse().filter(n=>n!==mainId);
  IQ_CMP.delete(mainId);
  $("iqCmpList").innerHTML=names.length?names.map(n=>`<label class="option-row"><input type="checkbox" value="${esc(n)}" ${IQ_CMP.has(n)?"checked":""}>
    <span class="grow">${esc(iqLabel(IQ_RUNS[n]))}</span></label>`).join(""):`<div class="option-row faint">没有其他运行</div>`;
  $("iqCmpLabel").textContent=IQ_CMP.size?`对比运行（${IQ_CMP.size}）`:"对比运行";
}
$("iqCmpList").addEventListener("change",e=>{
  if(e.target.type!=="checkbox")return;
  e.target.checked?IQ_CMP.add(e.target.value):IQ_CMP.delete(e.target.value);
  renderIq();
});
/* Token 花销维度: 输出预算明示 + 入/出总量 + 每题输出均值(对比时较 A 增减) */
function budgetText(r){
  if(r.thinking)return "思考模式 · 输出上限 32K";
  const b=(r.params&&r.params.budgets)||{mcq:16,math:2048,math500:4096,instruct:320};
  return `输出预算 选择题 ${b.mcq} · GSM8K ${b.math} · MATH-500 ${b.math500} · 指令 ${b.instruct}`;
}
function tokStat(r){
  const ss=r.subjects||[];
  const inT=ss.reduce((t,x)=>t+(x.in_tokens||0),0),outT=ss.reduce((t,x)=>t+(x.out_tokens||0),0),n=ss.reduce((t,x)=>t+(x.n||0),0);
  return {inT,outT,per:n?outT/n:null};
}
function iqCostLine(s,baseS){
  const t=tokStat(s.r),b0=baseS?tokStat(baseS.r):null;
  const d=(s.tag!=="A"&&b0&&b0.per&&t.per)?` <span class="sub" title="每题输出 token 相对 A">较A ${t.per>=b0.per?"+":""}${fmt((t.per-b0.per)/b0.per*100,0)}%</span>`:"";
  if(!t.inT&&!t.outT)return "";
  return `<div class="kpi-sub" title="Token 花销（能力维度之一：同等正确率下花得更少更高效）">`+
    `入 ${fmtInt(Math.round(t.inT))} · 出 ${fmtInt(Math.round(t.outT))} tok${t.per!=null?` · ${fmt(t.per,0)} tok/题${d}`:""}</div>`+
    `<div class="kpi-sub">${esc(budgetText(s.r))}</div>`;
}
function renderIq(){  /* 渲染异常不再静默白屏: 明确展示错误便于定位, 也避免"面板空白+点击无反应"的无提示状态 */
  try{_renderIq()}
  catch(e){
    console.error("renderIq failed:",e);
    const el=$("iqResult");
    if(el)el.innerHTML=emptyState("结果渲染出错",String((e&&e.message)||e),{iconName:"alert",inline:true});
  }
}
function _renderIq(){
  if(!IQ_LOADED)return;
  const el=$("iqResult");
  const mainId=$("iqMainSel").value,a=IQ_RUNS[mainId];
  renderIqCmpList(mainId);
  if(!a){el.innerHTML=emptyState("暂无评测结果","新建一次能力评测后，成绩会显示在这里",
    {action:`<button class="btn btn-primary" data-toggle="iqLauncher">${icon("plus")}新建评测</button>`});return}
  const series=[{r:a,color:C.series[0],tag:"A"},...[...IQ_CMP].filter(id=>IQ_RUNS[id]).slice(0,5).map((id,i)=>({r:IQ_RUNS[id],color:C.series[i+1],tag:String.fromCharCode(66+i)}))];
  const base=a.overall||{};
  let html=`<div class="score-cards">`+series.map(s=>{
    const o=s.r.overall||{};
    return `<div class="kpi"><div class="kpi-head"><span class="kpi-label" style="display:flex;align-items:center;gap:6px">
        <span class="run-tag" style="background:${s.color}">${s.tag}</span>${esc((s.r.model||"?")+(runFw(s.r)?" · "+runFw(s.r):""))}</span>
        ${s.tag!=="A"?deltaPill(base.acc,o.acc,1,{mode:"pp"}):""}</div>
      <div class="kpi-value num">${o.acc!=null?fmt(o.acc,1):"—"}<small>%</small></div>
      <div class="kpi-sub" title="${esc("采样："+(samplingText(s.r.sampling)||"未记录"))}">${o.n?`95% CI ${fmt(o.ci_lo,1)}–${fmt(o.ci_hi,1)}% · ${o.correct}/${o.n}${o.macro_acc!=null?` · 宏平均 ${fmt(o.macro_acc,1)}%`:""} · ${s.r.thinking?"思考":"非思考"}`:"运行未完成"}</div>
      ${iqCostLine(s,series[0])}
      ${s.tag!=="A"?`<div class="kpi-sub" data-sig-card="${esc(s.r.run_id)}">配对检验计算中…</div>`:""}
      ${iqIssues(s.r).length?`<div class="kpi-sub" style="color:var(--warning)">${esc(iqIssues(s.r).join(" · "))}</div>`:""}</div>`;
  }).join("")+`</div>`;
  series.forEach(s=>{const w=iqVersionWarning(s.r);if(w)html+=`<div class="alert is-warning">${icon("alert")}<span><b>${s.tag}</b>：${esc(w)}</span></div>`});
  if(Array.isArray(a.warnings)&&a.warnings.length)
    html+=`<div class="alert is-warning">${icon("alert")}<span><b>A 运行自检</b>：${a.warnings.map(esc).join("；")}</span></div>`;
  const errN=(a.overall||{}).errors||0;
  if(a.status==="done"&&errN&&SERVER.iq_version&&a.iq_version===SERVER.iq_version){
    html+=`<div class="alert is-info">${icon("info")}<span>A 有 ${errN} 题请求失败（已计为答错）。重试只会重新作答这些题，其余结果保持不变。</span>
      <button class="btn btn-secondary btn-sm" onclick="iqResume('${esc(a.run_id)}')">${icon("play")}重试失败的题</button></div>`;
  }
  if(["cancelled","interrupted","failed"].includes(a.status)){
    const canResume=SERVER.iq_version&&a.iq_version===SERVER.iq_version;
    const doneN=(a.subjects||[]).reduce((t,x)=>t+(x.n||0),0);
    html+=`<div class="alert is-info">${icon("info")}<span>A ${STATUS_NAME[a.status]||a.status}${a.error?"（"+esc(a.error)+"）":""}：已完成 ${a.subjects?a.subjects.length:0} 个科目共 ${doneN} 题，未完成科目中已作答的题目也已保存，请求失败的题续跑时会重新作答。${canResume?"续跑会沿用原来的模型端点、采样与题量设置，并使用上方表单中的 API Key。":"该运行由其他版本的评测程序生成，无法续跑。"}</span>
      ${canResume?`<button class="btn btn-secondary btn-sm" onclick="iqResume('${esc(a.run_id)}')">${icon("play")}续跑</button>`:""}</div>`;
  }
  const mismatch=series.slice(1).filter(s=>s.r.bank_id!==a.bank_id);
  const pkey=r=>JSON.stringify([r.params&&r.params.subject_ids||null,r.params&&r.params.limit_per_subject||null]);
  const pdiff=series.slice(1).filter(s=>s.r.bank_id===a.bank_id&&pkey(s.r)!==pkey(a));
  if(pdiff.length)html+=`<div class="alert is-warning">${icon("alert")}<span>题量设置不一致：${pdiff.map(s=>esc(s.tag)).join("、")} 与 A 选择的科目或每科题数不同，总分覆盖的题目不同，请以分科成绩和配对检验为准</span></div>`;
  if(mismatch.length)html+=`<div class="alert is-warning">${icon("alert")}<span>题集版本不一致：${mismatch.map(s=>esc(s.tag+"（"+s.r.bank_id+"）")).join("、")} 与 A（${esc(a.bank_id)}）使用了不同题集，分数不具可比性</span></div>`;
  html+=`<div class="iq-layout">
    <div class="panel"><div class="panel-head"><div><h3 class="panel-title">能力分布</h3><p class="panel-desc">各科目准确率</p></div></div>
      <div class="panel-body"><canvas class="chart" id="iqRadar"></canvas><div class="legend" id="iqRadarLg"></div></div></div>
    <div class="panel"><div class="panel-head"><div><h3 class="panel-title">分科准确率</h3><p class="panel-desc">${series.length>1?"加粗为各科最高分":"括号内为 95% 置信区间"}</p></div></div>
      <div class="panel-body" id="iqSubjTbl"></div></div></div>`;
  el.innerHTML=html;
  let t=`<div class="table-wrap" style="max-height:560px"><table class="table"><thead><tr><th>科目</th><th>题数</th>${series.map(s=>`<th><span class="run-tag" style="background:${s.color}">${s.tag}</span></th><th title="每题输出 token 均值（Token 花销）"><span class="run-tag" style="background:${s.color}">${s.tag}</span> tok/题</th>`).join("")}<th>A 截断 / 失败</th><th></th></tr></thead><tbody>`;
  const tokCell=(v,v0,self)=>{
    if(!v||!v.n)return `<td class="na">—</td>`;
    const per=v.out_tokens/v.n;
    const d=(!self&&v0&&v0.n&&series.length>1)?`<span class="sub">较A ${per>=v0.out_tokens/v0.n?"+":""}${fmt((per-v0.out_tokens/v0.n)/(v0.out_tokens/v0.n)*100,0)}%</span>`:"";
    return `<td class="num faint">${fmt(per,0)}${d}</td>`;
  };
  (a.subjects||[]).forEach(sub=>{
    const vals=series.map(s=>{const x=(s.r.subjects||[]).find(y=>y.id===sub.id);return x||null});
    const accs=vals.map(v=>v&&v.acc).filter(v=>v!=null);
    const best=accs.length>1?Math.max(...accs):null;
    t+=`<tr><td>${esc(sub.name)}</td><td class="faint">${sub.n}</td>`+vals.map((v,i)=>
      (v==null?`<td class="na">—</td>`:
      `<td class="${best!=null&&v.acc===best?"best":""}" ${i?`data-sig-cell="${esc(series[i].r.run_id)}|${esc(sub.id)}"`:""}>${fmt(v.acc,1)}%${series.length===1?`<span class="sub">${fmt(v.ci_lo,1)}–${fmt(v.ci_hi,1)}</span>`:""}</td>`)+
      tokCell(v,vals[0],i===0)).join("")+
      `<td class="${(sub.truncated||sub.errors)?"down":"faint"}">${sub.truncated==null?"—":`${sub.truncated} / ${sub.errors||0}`}</td>
      <td>${sub.correct<sub.n?`<button class="btn btn-ghost btn-sm" data-iq-wrong="${esc(sub.id)}" data-run="${esc(a.run_id)}">错题 ${sub.n-sub.correct}</button>`:""}</td></tr>`;
  });
  const overall=series.map(s=>s.r.overall&&s.r.overall.acc);
  const bestAll=series.length>1?Math.max(...overall.filter(v=>v!=null)):null;
  const subjAll=series.map(s=>({n:(s.r.subjects||[]).reduce((t2,x)=>t2+(x.n||0),0),out_tokens:(s.r.subjects||[]).reduce((t2,x)=>t2+(x.out_tokens||0),0)}));
  t+=`<tr class="total"><td>总体</td><td class="faint">${base.n??"—"}</td>`+overall.map((v,i)=>
    `<td class="${bestAll!=null&&v===bestAll?"best":""}">${v!=null?fmt(v,1)+"%":"—"}</td>`+tokCell(subjAll[i],subjAll[0],i===0)).join("")+
    `<td class="${(base.truncated||base.errors)?"down":"faint"}">${base.truncated==null?"—":`${base.truncated} / ${base.errors||0}`}</td><td></td></tr></tbody></table></div>`;
  $("iqSubjTbl").innerHTML=t;
  drawRadar(series);
  /* 配对显著性: 同一批题逐题比较(McNemar), 结果异步填入 */
  series.slice(1).forEach(s=>iqCompare(a.run_id,s.r.run_id).then(d=>{
    const card=document.querySelector(`[data-sig-card="${CSS.escape(s.r.run_id)}"]`);
    if(!card)return;
    if(!d||!d.ok){card.textContent="配对检验不可用";return}
    if(!d.same_bank){card.textContent="题集不同，无法逐题配对检验";return}
    if(!d.overall.n||d.overall.significant==null){card.textContent="没有双方都有效作答的共同题目，无法配对检验";return}
    const o=d.overall;
    card.innerHTML=`<span class="sig ${o.significant?"yes":"no"}">${o.significant?"差异显著":"差异不显著"}</span> · p=${fmtP(o.p)} · A 独对 ${o.a_only} / B 独对 ${o.b_only}`;
    card.title=`McNemar 配对检验：${o.n} 道共同题目中，仅 A 答对 ${o.a_only} 题，仅 B 答对 ${o.b_only} 题。p<0.05 视为差异显著。`;
    Object.entries(d.subjects).forEach(([sid,x])=>{
      const cell=document.querySelector(`[data-sig-cell="${CSS.escape(s.r.run_id+"|"+sid)}"]`);
      if(cell&&x.n)cell.insertAdjacentHTML("beforeend",`<span class="sub sig ${x.significant?"yes":"no"}" title="McNemar p=${fmtP(x.p)}">${x.significant?"显著":"不显著"} p=${fmtP(x.p)}</span>`);
    });
  }));
}
function verLt(v,target){const a=String(v||"0").split(".").map(Number),b=target.split(".").map(Number);for(let i=0;i<3;i++){if((a[i]||0)!==b[i])return (a[i]||0)<b[i]}return false}
function iqVersionWarning(r){
  if(verLt(r.iq_version,"1.1.0")&&r.thinking)return `该运行使用旧版评测程序（${r.iq_version}）：思考模式下选择题输出上限仅 8 token，思考被截断后全部计错，MATH-500 判分也有缺陷，分数不可信，请重新运行`;
  if(verLt(r.iq_version,"1.1.0"))return `该运行使用旧版评测程序（${r.iq_version}）：MATH-500 判分有缺陷（恒判错），总分偏低，请重新运行`;
  if(verLt(r.iq_version,"1.2.0")&&r.thinking)return `该运行使用 ${r.iq_version} 评测程序：思考模式输出上限较低，长思考题目可能被截断计错且未单独标记，建议重新运行`;
  if(verLt(r.iq_version,"1.3.0")&&!r.thinking)return `该运行使用 ${r.iq_version} 评测程序：MATH-500 / GSM8K 输出上限较低（900 / 1280 token），部分题目会被截断计错，数学科目分数偏低`;
  if(verLt(r.iq_version,"1.3.0")&&r.thinking)return `该运行使用 ${r.iq_version} 评测程序：思考模式为贪心解码，容易陷入重复而被截断，建议用新版重新运行`;
  if(verLt(r.iq_version,"1.4.0"))return `该运行使用 ${r.iq_version} 评测程序：之后修正了答案提取（首行字母、小写选项）、MATH-500 等价判定和部分指令遵循规则；限制题量时 MMLU 只覆盖少数学科，请求失败的题也计为答错。与 1.4.0 及之后的分数不宜直接比较`;
  return "";
}
function iqIssues(r){
  const o=r.overall||{},out=[];
  if(o.truncated)out.push(`${o.truncated} 题达到输出上限被截断`);
  if(o.errors)out.push(`${o.errors} 题请求失败`);
  return out;
}
$("iqResult").addEventListener("click",async e=>{
  const b=e.target.closest("[data-iq-wrong]");if(!b)return;
  const sid=b.dataset.iqWrong,r=IQ_RUNS[b.dataset.run],sub=(r.subjects||[]).find(x=>x.id===sid);
  setBusy(b,false);b.disabled=true;
  try{
    const d=await getJSON(`/api/iq-wrong?id=${encodeURIComponent(b.dataset.run)}&sid=${encodeURIComponent(sid)}`);
    if(!d.ok){toast(d.error,"error");return}
    const status=x=>x.err?`<span class="badge is-danger">请求失败</span>`:x.trunc?`<span class="badge is-warning">输出截断</span>`:`<span class="badge">答错</span>`;
    const rows=d.rows.map(x=>`<tr>
      <td>${x.idx+1}</td>
      <td class="text-left" style="min-width:320px;max-width:560px;white-space:normal">${esc(x.q||"（题集文件缺失，无法显示题干）")}
        ${x.choices?`<span class="sub">${x.choices.map((c,i)=>esc("ABCD"[i]+". "+String(c).slice(0,80))).join("　")}</span>`:""}</td>
      <td class="text-left">${esc(x.answer!=null?String(x.answer):(x.checks?"规则校验":"—"))}</td>
      <td class="text-left">${x.pred!=null?esc(x.pred):'<span class="faint">未提取到</span>'}</td>
      <td class="text-left">${status(x)}${x.out!=null?`<span class="sub">输出 ${x.out} tokens${x.finish?" · "+esc(x.finish):""}</span>`:""}</td>
      <td class="text-left mono" style="min-width:240px;max-width:420px;white-space:pre-wrap;font-size:12px">${esc(x.err||x.tail||"")}</td></tr>`).join("");
    const legacy=verLt(d.iq_version,"1.2.0")?`<div class="alert is-info">${icon("info")}<span>该运行由 ${esc(d.iq_version)} 版评测程序生成，未记录模型答案与输出尾部，仅能看到题目与请求失败信息。</span></div>`:"";
    Modal.open(`${sub?sub.name:sid} · 未答对 ${d.rows.length} 题`,legacy+(rows?`<div class="table-wrap" style="max-height:none"><table class="table"><thead><tr><th>#</th><th class="text-left">题目</th><th class="text-left">标准答案</th><th class="text-left">模型答案</th><th class="text-left">状态</th><th class="text-left">模型输出（末尾）</th></tr></thead><tbody>${rows}</tbody></table></div>`:emptyState("没有未答对的题目","",{inline:true})),
      {badges:`<span class="badge">${esc(iqLabel(r))}</span>`});
  }catch(err){toast("加载错题失败："+err.message,"error")}
  finally{b.disabled=false}
});
function drawRadar(series){
  const cv=$("iqRadar");if(!cv||!cv.clientWidth)return;
  const {g,w,h}=setupCanvas(cv,.9,260,380);
  const subs=series[0].r.subjects||[],n=subs.length;
  $("iqRadarLg").innerHTML=series.map(s=>legendBtn("",s.color,`${s.tag} · ${s.r.overall&&s.r.overall.acc!=null?s.r.overall.acc+"%":"—"}`)).join("");
  if(n<3){noData(g,w,h,"科目不足 3 个，无法绘制");return}
  const cx=w/2,cy=h/2,R=Math.min(w/2-70,h/2-30),ang=i=>-Math.PI/2+2*Math.PI*i/n;
  const pt=(i,r)=>[cx+r*Math.cos(ang(i)),cy+r*Math.sin(ang(i))];
  g.lineWidth=1;
  for(let ring=1;ring<=4;ring++){
    g.strokeStyle=ring===4?C.axis:C.grid;g.beginPath();
    for(let i=0;i<=n;i++){const [x,y]=pt(i%n,R*ring/4);i?g.lineTo(x,y):g.moveTo(x,y)}
    g.stroke();
    g.fillStyle=C.text;g.textAlign="left";g.fillText(String(ring*25),cx+3,cy-R*ring/4+7);
  }
  g.strokeStyle=C.grid;
  for(let i=0;i<n;i++){const [x,y]=pt(i,R);g.beginPath();g.moveTo(cx,cy);g.lineTo(x,y);g.stroke()}
  g.fillStyle=C.text2;
  subs.forEach((s,i)=>{const [x,y]=pt(i,R+14);const c=Math.cos(ang(i));
    g.textAlign=Math.abs(c)<.3?"center":(c>0?"left":"right");
    let name=String(s.name||s.id).replace(/（官方）|\(官方\)|\(中文\)|（中文）/g,"").trim();
    const maxW=Math.abs(c)<.3?w-8:(c>0?w-x-4:x-4);  /* 按可用宽度截断, 避免超出画布 */
    while(name.length>2&&g.measureText(name).width>maxW)name=name.slice(0,-2)+"…";
    g.fillText(name,x,y)});
  g.textAlign="left";
  series.forEach(s=>{
    const ss=s.r.subjects||[];
    const pts=subs.map((sub,i)=>{const m=ss.find(x=>x.id===sub.id);const v=m?Math.max(0,Math.min(100,m.acc||0)):0;const [x,y]=pt(i,R*v/100);return{x,y,v,name:sub.name}});
    g.beginPath();pts.forEach((p,i)=>i?g.lineTo(p.x,p.y):g.moveTo(p.x,p.y));g.closePath();
    g.fillStyle=withAlpha(s.color,.12);g.fill();g.strokeStyle=s.color;g.lineWidth=2;g.stroke();
    dots(g,pts,s.color,2.5);
    pts.forEach(p=>cv._hit.push({x:p.x,y:p.y,html:tt(p.name,[[s.color,s.tag,fmt(p.v,1)+"%"]])}));
  });
  bindTips(cv);
}

/* ============================================================
   代码生成
   ============================================================ */
let GEN_RUNS={},GEN_LOADED=false,genPoll=null;
const genLog=LogBox("genLog","gen");
bindFormMemory("llm-bench-pro-gen-form",["genBase","genModel","genConc","genTag"]);
bindFormMemory("llm-bench-pro-gen-judge",["genJudgeBase","genJudgeModel"]);
const TIER_NAME={普通:"基础",困难:"进阶",地狱:"高难",实战:"真实场景"};
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
function judgeBody(){return{judge_base:$("genJudgeBase").value.trim(),judge_model:$("genJudgeModel").value.trim(),judge_key:$("genJudgeKey").value}}
function judgeValid(jb){if(!!jb.judge_base!==!!jb.judge_model){msg("genInfo","error","视觉评审需要同时填写评审模型地址和评审模型，或都留空");return false}return true}
function evalMethodText(ev){
  if(!ev)return"";
  const m=ev.method==="browser"?"无头浏览器运行检测":"源码检查（未找到 Chrome/Edge，结果仅供参考）";
  return "评测方式："+m+(ev.judge_model?" + 视觉评审（"+ev.judge_model+"）":"，未配置视觉评审");
}
async function genStart(){
  const model=$("genModel").value.trim();
  if(!model){msg("genInfo","error","请填写模型名称");$("genModel").focus();return}
  const tasks=selectedTasks();
  if(!tasks.length){msg("genInfo","error","请至少选择 1 道题目");return}
  const jb=judgeBody();if(!judgeValid(jb))return;
  const d=await postWithConflict("/api/gen-start",{base:$("genBase").value,api_key:$("genKey").value,model,conc:$("genConc").value,
    tag:$("genTag").value,tasks,thinking:$("genThink").checked,...jb});
  if(!d)return;
  if(!d.ok){msg("genInfo","error",d.error);return}
  msg("genInfo","info",evalMethodText(d.eval));
  watchGen(`运行中 · ${model} · ${tasks.length} 题`);
}
async function genReeval(){
  const runId=$("genMainSel").value;
  if(!runId){toast("没有可重新评测的运行","warning");return}
  const jb=judgeBody();
  if(!!jb.judge_base!==!!jb.judge_model){toggleLauncher("genLauncher",true);judgeValid(jb);return}
  const d=await postJSON("/api/gen-eval",{run_id:runId,...jb});
  if(!d.ok){toast(d.error,"error");return}
  toggleLauncher("genLauncher",true);
  msg("genInfo","info",evalMethodText(d.eval));
  watchGen("重新评测 · "+(GEN_RUNS[runId]?genLabel(GEN_RUNS[runId]):runId),runId);
  $("genLog").scrollIntoView({behavior:"smooth",block:"nearest"});
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
    if(!names.length)toggleLauncher("genLauncher",true);
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
  const parts=[r.model||"?",runFw(r),r.thinking?"思考":"非思考",`完成 ${s.ok.length}/${s.planned}`,r.status&&r.status!=="done"?STATUS_NAME[r.status]||r.status:""];
  if(s.exec!=null)parts.push(`${s.mode==="static"?"源码":"检测"} ${s.exec.toFixed(0)}%`);
  if(s.judge!=null)parts.push(`评审 ${s.judge.toFixed(0)}`);
  if(s.stars!=null)parts.push(`人工 ${s.stars.toFixed(1)}（${s.starN}）`);
  if(!s.v2)parts.push("旧版评测");
  parts.push(shortTime(r.started_utc));
  return parts.filter(Boolean).join(" · ");
}
function scoreCls(p){return p==null?"":p>=80?"good":p>=50?"mid":"bad"}
function kpiBox(labelText,value,unit,sub){
  return `<div class="kpi"><div class="kpi-head"><span class="kpi-label">${esc(labelText)}</span></div>
    <div class="kpi-value num">${value}${unit?`<small>${unit}</small>`:""}</div><div class="kpi-sub">${esc(sub||"")}</div></div>`;
}
function renderGen(){
  if(!GEN_LOADED)return;
  const el=$("genResult");
  const a=GEN_RUNS[$("genMainSel").value],b=GEN_RUNS[$("genCmpSel").value];
  if(!a){el.innerHTML=emptyState("暂无生成结果","新建一次生成任务后，作品与检测结果会显示在这里",
    {action:`<button class="btn btn-primary" data-toggle="genLauncher">${icon("plus")}新建任务</button>`});return}
  const s=genStats(a),ev=a.eval||{};
  const modeText=s.mode==="static"?"源码检查":s.mode==="mixed"?"浏览器检测，部分题目降级":"无头浏览器运行检测";
  const execSub=s.mode==="static"?"关键词匹配，这些题没有在浏览器里跑过":
    s.mode==="mixed"?`只平均 ${s.browserN} 道浏览器检测，${s.staticN} 道源码降级未计入`:"加载、报错、白屏、动画与交互";
  const judgeSub=!ev.judge_model&&s.judge==null?"未配置评审模型":
    `有分 ${s.judgeN} 题${s.judgeErr?`，${s.judgeErr} 题失败未计入`:""}${ev.judge_model?" · "+ev.judge_model:""}`;
  let html="";
  if(a.status&&a.status!=="done")
    html+=`<div class="alert is-warning">${icon("alert")}<span>${esc(STATUS_NAME[a.status]||a.status)}${a.error?"："+esc(a.error):""}。列表里只有已经入库的题，计划 ${s.planned} 题。</span></div>`;
  html+=s.v2?`<div class="meta-list"><span class="badge">评测方式 <b>${modeText}</b></span>
      ${ev.browser&&s.mode!=="static"?`<span class="badge">浏览器 <b>${esc(ev.browser)}</b></span>`:""}
      <span class="badge">视觉评审 <b>${ev.judge_model?esc(ev.judge_model):"未配置"}</b></span>
      ${a.thinking_dropped?`<span class="badge is-warning">思考参数被端点拒绝</span>`:""}
      ${a.tag?`<span class="badge">标签 <b>${esc(a.tag)}</b></span>`:""}<span class="badge">开始 <b>${esc(timeText(a.started_utc))}</b></span></div>`
    :`<div class="alert is-warning">${icon("alert")}<span>该运行使用旧版评测（源码关键词匹配），分数不可信。点击右上方“重新评测”即可按新口径检测，人工评分会保留。</span></div>`;
  if(s.v2&&s.mode==="static")
    html+=`<div class="alert is-warning">${icon("alert")}<span>这些题没有在无头浏览器里跑起来，下面的命中率是源码关键词。打开单题详情可以看到原因（常见是 Chrome 启动失败）。</span></div>`;
  if(s.v2&&s.mode==="browser"&&verLt(ev.eval_version,"1.1.0"))
    html+=`<div class="alert is-warning">${icon("alert")}<span>该运行的运行检测使用 ${esc(ev.eval_version||"1.0")} 版口径：交互检查会把自带动画、CSS 悬停样式和每帧重写的计时文字误判为“交互生效”，输入“.”会丢字符，移动端溢出检查不生效。建议点击“重新评测”，人工评分会保留。</span></div>`;
  html+=`<div class="kpi-grid">
    ${kpiBox("已完成作品",`${s.ok.length}<small> / ${s.planned}</small>`,"",a.status&&a.status!=="done"?"含未跑完的计划题数":"生成失败的题目不计入通过率")}
    ${kpiBox(s.mode==="static"?"源码检查命中率":"运行检测通过率",s.exec==null?"—":fmt(s.exec,1),s.exec==null?"":"%",execSub)}
    ${kpiBox("视觉评审均分",s.judge==null?"—":fmt(s.judge,1),s.judge==null?"":"/ 100",judgeSub)}
    ${kpiBox("人工评分均值",s.stars==null?"—":fmt(s.stars,1),s.stars==null?"":"/ 5",s.starN?`已评 ${s.starN} 题`:"在作品卡片上评分")}
  </div><div class="work-grid">`;
  (a.items||[]).forEach(it=>{
    const tags=esc((it.tags||[]).map(tagName).join(" · "));
    if(it.error){
      html+=`<div class="work"><div class="work-head"><span class="work-name">${esc(it.name)}</span><span class="badge is-danger">生成失败</span></div>
        <div class="work-meta">${tags}</div><div class="work-fails">${esc(it.error)}</div></div>`;
      return;
    }
    const e=it.eval,checks=e?e.checks:[],fails=checks.filter(c=>!c.pass),j=e&&e.judge;
    const judgeBadge=j&&j.score!=null?`<span class="score ${scoreCls(j.score)}">评审 ${fmt(j.score,0)}${j.stale?" 旧":""}</span>`:(j&&j.error?`<span class="badge is-danger">评审失败</span>`:"");
    const staticBadge=e&&e.method==="static"&&s.mode!=="static"?`<span class="badge is-warning">源码检查</span>`:"";
    html+=`<div class="work">
      <div class="work-head"><span class="work-name">${esc(it.name)}</span><span class="row" style="gap:6px">${staticBadge}${judgeBadge}</span></div>
      <div class="work-meta">${tags} · ${it.lines} 行${it.continuations?` · 续写 ${it.continuations} 轮`:""}</div>
      ${e?`<div class="row" style="gap:10px"><span class="checkbar">${checks.map(c=>`<i class="${c.pass?"":"fail"}" title="${esc((c.pass?"通过：":"未通过：")+c.label+(c.detail?"\n"+c.detail:""))}"></i>`).join("")}</span>
          <span class="score ${scoreCls(it.exec_score)}">运行检测 ${it.pass}/${it.total}</span></div>
        ${fails.length?`<div class="work-fails">${fails.slice(0,3).map(c=>`<div>${icon("x-circle","icon-sm")} ${esc(c.label)}</div>`).join("")}${fails.length>3?`<div class="faint">另有 ${fails.length-3} 项未通过</div>`:""}</div>`:""}`
        :`<div class="work-fails faint">未评测</div>`}
      <div class="work-actions">
        <button class="btn btn-secondary btn-sm" data-gen="preview" data-run="${esc(a.run_id)}" data-item="${esc(it.id)}">${icon("eye")}预览</button>
        ${e?`<button class="btn btn-ghost btn-sm" data-gen="detail" data-run="${esc(a.run_id)}" data-item="${esc(it.id)}">${icon("image")}检测详情</button>`:""}
        ${b?`<button class="btn btn-ghost btn-sm" data-gen="compare" data-run="${esc(a.run_id)}" data-item="${esc(it.id)}">${icon("columns")}并排对比</button>`:""}
        <span class="stars" role="group" aria-label="人工评分">${[1,2,3,4,5].map(i=>`<button type="button" class="star ${i<=(it.stars||0)?"on":""}" data-rate="${i}" data-run="${esc(a.run_id)}" data-item="${esc(it.id)}" aria-label="${i} 分" aria-pressed="${i===it.stars}">${icon("star")}</button>`).join("")}</span>
      </div></div>`;
  });
  el.innerHTML=html+`</div>`;
}
$("genResult").addEventListener("click",e=>{
  const rate=e.target.closest("[data-rate]");
  if(rate){rateStars(rate.dataset.run,rate.dataset.item,+rate.dataset.rate);return}
  const act=e.target.closest("[data-gen]");if(!act)return;
  const r=GEN_RUNS[act.dataset.run],it=r&&(r.items||[]).find(x=>x.id===act.dataset.item);if(!it)return;
  if(act.dataset.gen==="preview")previewWork(it);
  else if(act.dataset.gen==="detail")genDetail(it);
  else if(act.dataset.gen==="compare")previewCompare(it);
});
let rateSeq=0;
function rateStars(runId,itemId,n){
  const r=GEN_RUNS[runId],it=r&&(r.items||[]).find(x=>x.id===itemId);
  if(!it||!n)return;
  const seq=++rateSeq,prev=it.stars;
  it._rateSeq=seq;
  it.stars=it.stars===n?null:n;
  renderGen();
  postJSON("/api/gen-rate",{run_id:runId,item_id:itemId,stars:it.stars}).then(d=>{
    if(it._rateSeq!==seq)return;  /* 后面又点过, 以最后一次为准 */
    if(!d.ok){it.stars=prev;renderGen();toast("评分保存失败："+d.error,"error")}
  });
}
const GEN_SANDBOX="allow-scripts allow-pointer-lock allow-forms allow-modals"; /* 无 same-origin/top-navigation/popups: 作品代码无法访问本页与接口; localStorage 由服务端 /works 垫片提供(否则游戏脚本启动即崩) */
const SANDBOX_BADGE=`<span class="badge" title="作品运行在无同源权限的沙箱 iframe 中，无法访问本页面与后端接口；localStorage 以内存垫片提供（刷新即清）">沙箱隔离</span>`;
function focusPreviewFrame(){
  const f=document.querySelector("#modalBody iframe.frame");
  if(f){try{f.focus();f.contentWindow&&f.contentWindow.focus()}catch(e){}}
}
function previewWork(it){
  Modal.open(it.name,`<iframe class="frame" sandbox="${GEN_SANDBOX}" src="/${esc(it.file)}" title="${esc(it.name)}"></iframe>`,{badges:SANDBOX_BADGE,flush:true});
  focusPreviewFrame();  /* 键盘类游戏无需先点一下 iframe */
}
function previewCompare(it){
  const a=GEN_RUNS[$("genMainSel").value],b=GEN_RUNS[$("genCmpSel").value];
  const ib=b&&(b.items||[]).find(x=>x.id===it.id);
  const side=(r,x,tag)=>`<div><div class="split-head"><span class="run-tag ${tag.toLowerCase()}">${tag}</span>${esc(genLabel(r))}</div>
    ${x&&!x.error?`<iframe class="frame" style="flex:1" sandbox="${GEN_SANDBOX}" src="/${esc(x.file)}" title="${tag}"></iframe>`
      :emptyState(x?"该题生成失败":"该运行没有此题的作品",x?x.error:"",{inline:true})}</div>`;
  Modal.open(it.name+" · 并排对比",`<div class="split">${side(a,it,"A")}${side(b,ib,"B")}</div>`,{badges:SANDBOX_BADGE,flush:true});
  focusPreviewFrame();
}
function genDetail(it){
  const e=it.eval;if(!e)return;
  const dir=it.file.replace(/[^/]+$/,"")+e.shots_dir+"/";
  const j=e.judge;
  const checkRows=e.checks.map(c=>`<tr><td style="width:64px"><span class="badge ${c.pass?"is-success":"is-danger"}">${c.pass?"通过":"未通过"}</span></td>
    <td class="text-left">${esc(c.label)}${c.detail?`<span class="sub">${esc(c.detail)}</span>`:""}</td></tr>`).join("");
  let judgeHtml;
  if(!j)judgeHtml=`<p class="faint">未配置评审模型。在“新建任务”中填写评审模型后点击“重新评测”。</p>`;
  else if(j.error)judgeHtml=`<div class="alert is-warning">${icon("alert")}<span>${esc(j.error)}</span></div>`;
  else judgeHtml=`<div class="row" style="align-items:baseline"><span class="score-big num ${"score "+scoreCls(j.score)}">${fmt(j.score,1)}</span><span class="faint">/ 100 · ${esc(j.model||"")}</span></div>
    ${j.stale?`<div class="alert is-info">${icon("info")}<span>${j.kept_because?esc("本次评审没有替换原分数："+j.kept_because):"重新评测时未配置评审模型，这是之前基于旧截图的评审结果。"}</span></div>`:""}
    ${j.summary?`<p class="muted" style="margin:6px 0 10px">${esc(j.summary)}</p>`:""}
    <div class="table-wrap" style="max-height:none"><table class="table"><tbody>${j.items.map(x=>`<tr>
      <td style="width:56px">${x.score==null?`<span class="badge">未评分</span>`:`<span class="score ${scoreCls(x.score*10)}">${x.score} / 10</span>`}</td>
      <td class="text-left">${esc(x.label)}<span class="sub">${esc(x.reason)}</span></td></tr>`).join("")}</tbody></table></div>`;
  Modal.open(it.name+" · 检测详情",`<div class="detail-layout">
    <div><div class="shot-grid">${(e.shots||[]).map(s=>`<figure class="shot"><img src="/${esc(dir+s.file)}" alt="${esc(s.caption)}" loading="lazy"><figcaption>${esc(s.caption)}</figcaption></figure>`).join("")||emptyState("无截图","源码检查模式不产生截图",{inline:true})}</div></div>
    <div>
      <section class="detail-section"><h4>运行检测 ${it.pass} / ${it.total}<span class="faint" style="font-weight:400"> · ${e.method==="browser"?"无头浏览器":"源码检查"}</span></h4>
        <div class="table-wrap" style="max-height:none"><table class="table"><tbody>${checkRows}</tbody></table></div>
        ${(e.notes||[]).length?`<p class="faint small" style="margin-top:6px">${e.notes.map(esc).join("<br>")}</p>`:""}</section>
      <section class="detail-section"><h4>视觉评审</h4>${judgeHtml}</section>
    </div></div>`,{badges:`<span class="badge">运行检测 ${it.pass}/${it.total}</span>`});
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
    setConn(true,`v${v.version} · 已运行 ${durationText(v.uptime_s)}`);
    $("conn").title=`后端 v${v.version} · PID ${v.pid} · 启动于 ${timeText(v.started_at)}${v.commit?" · 提交 "+v.commit:""}\n数据库 ${v.db}\n评测程序：性能 ${v.bench_version} · 能力 ${v.iq_version} · 代码生成 ${v.gen_version}`;
    if(v.version!==UI_VERSION&&!VERSION_WARNED.ver){
      VERSION_WARNED.ver=1;
      toast(`页面（v${UI_VERSION}）与后端服务（v${v.version}）版本不一致：页面仍在运行旧代码，功能可能异常。`,"warning",0,
        {label:"立即刷新页面",onClick:()=>location.reload()});
    }
    if(v.code_changed&&!VERSION_WARNED.code){
      VERSION_WARNED.code=1;
      toast("后端代码已更新，但服务仍在运行启动时的旧代码。请重启 python run.py 使修改生效。","warning",0);
    }
  }catch(e){setConn(false,"服务未连接")}
}
async function resumeRunning(){
  const jobs=[
    ["/api/status","launcher",()=>watchPerf("运行中（页面刷新后继续跟踪）")],
    ["/api/iq-status","iqLauncher",()=>watchIq("运行中（页面刷新后继续跟踪）")],
    ["/api/gen-status","genLauncher",()=>watchGen("运行中（页面刷新后继续跟踪）")],
  ];
  for(const [url,launcher,watch] of jobs){
    try{const s=await getJSON(url);if(s.running){toggleLauncher(launcher,true);watch()}}catch(e){}
  }
}
let rzT;
window.addEventListener("resize",()=>{clearTimeout(rzT);rzT=setTimeout(redrawVisible,150)});
matchMedia("(prefers-color-scheme: light)").addEventListener("change",e=>{
  try{if(localStorage.getItem("llm-bench-pro-theme"))return}catch(err){}
  applyTheme(e.matches?"light":"dark",false);
});
document.querySelectorAll("select.select").forEach(CSelect.enhance);
CSelect.combo($("fModel"));
applyTheme(document.documentElement.dataset.theme||"dark",false);
showView((location.hash||"#dash").slice(1));
checkVersion().then(()=>{if(VIEW==="iq")renderIq()});
setInterval(checkVersion,60000);
refresh();
loadReplayFiles();
loadScenarioAssets();
loadEndpoints();
resumeRunning();
