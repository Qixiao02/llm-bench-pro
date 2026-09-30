"use strict";
/* ============================================================
   界面语言 (中文 / English) 的翻译框架
   约定见 CONTRIBUTING.md「界面文字与翻译」。要点:
   - 以中文原文为键 (gettext 风格): 中文原文继续留在代码里, 英文放在词典 web/static/i18n.en.<区域>.js 里;
   - t("中文 {名字}", {名字: 值}) 普通句子 · tn("{n} 行", n) 带数量 · td("数据里的中文名") ·
     tm(服务端返回的提示) · tk("常量里的中文") 只做标记, 用的时候再 t(x);
   - 中文模式原样返回 (替换占位符); 英文模式查词典, 查不到就回退成中文并记进 I18N.missing;
   - 加载顺序: i18n.js → i18n.en.*.js (词典) → app.js。本文件不依赖 app.js。
   ============================================================ */
const I18N=(()=>{
  const KEY="llm-bench-pro-lang";  /* 本地偏好里记语言的键 (值 zh / en); 离线报告里也用它 */
  /* 汉字和中文标点: 与 tests/i18n_lint.py 的 CJK_RE 一致 */
  const CJK=/[\u3400-\u4dbf\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]/;
  /* 占位符 {名字} (名字可以是中文); {{ 和 }} 表示字面的花括号。与 tests/i18n_lint.py 的 PH_RE 一致 */
  const PH=/\{\{|\}\}|\{([A-Za-z_\u4e00-\u9fff][\w\u4e00-\u9fff]*)\}/g;
  const ATTRS=["title","placeholder","aria-label","alt"];  /* 静态 HTML 里翻译这几个属性 */
  const SKIP={SCRIPT:1,STYLE:1,SVG:1,TEXTAREA:1,NOSCRIPT:1,TEMPLATE:1};
  const norm=s=>String(s).replace(/\s+/g," ").trim();      /* 静态文字的键: 去首尾空白, 中间的空白合成一个空格 */
  const S={
    KEY,
    lang:"zh",
    /* 两个开关: 英文翻译全部完成之前保持 false, 免得用户看到半中半英; 全部翻完后一起改成 true (页头脚本 index.html 里也要跟着改):
       AUTO_DETECT — 没有明确选过语言时, 按浏览器语言自动选 (false = 一律中文);
       READY — 显示语言切换按钮 (false = 隐藏, 但已经在英文模式时照常显示, 好切回来)。
       任何时候都可以用网址 ?lang=en 直接试英文 (并记住)。 */
    AUTO_DETECT:false,
    READY:false,
    en:Object.create(null),      /* 界面文字: 中文原文 → 英文; tn 的值是 [单数, 复数] */
    enData:Object.create(null),  /* 数据里的中文名 (作品名、题库科目名、场景名 ...) → 英文 */
    patterns:[],                 /* 服务端提示的正则模式 [{re, to}] */
    missing:[],                  /* 英文模式下 t() / tn() 查不到的键 (每个只记一次) */
    missingData:[],              /* td() 查不到的数据名 */
    missingServer:[],            /* tm() 没有词条也匹配不上任何模式的服务端提示 */
    dups:[],                     /* 不同文件给同一个键写了不同的英文 (测试会检查) */
  };
  const seen=new Set(),listeners=[];
  let warned=false,title=null,booted=false;

  /* ---------- 记录缺词: 每个键只记一次; 控制台只警告一次, 不刷屏 ---------- */
  S._note=(list,key,warn)=>{
    const id=list+"\u0000"+key;
    if(seen.has(id))return;
    seen.add(id);S[list].push(key);
    if(warn&&!warned&&typeof console!=="undefined"){
      warned=true;
      console.warn("[i18n] English dictionary entry missing, showing the Chinese text instead. First one: "+JSON.stringify(key)+
        ". Full list: I18N.missing (also I18N.missingServer / I18N.missingData)");
    }
  };
  /* 替换占位符: params 里没有的名字原样留着 (一眼能看出写错了); 值是 null / undefined 当空串 */
  S._fill=(s,params)=>{
    if(params==null||typeof params!=="object")return s;
    return s.replace(PH,(m,k)=>m==="{{"?"{":m==="}}"?"}":(k in params?(params[k]==null?"":String(params[k])):m));
  };
  S.CJK=CJK;
  S.locale=()=>S.lang==="en"?"en-US":"zh-CN";  /* toLocaleString 等用 */

  /* ---------- 词典 ---------- */
  S.add=(lang,dict)=>{
    const table=lang==="en"?S.en:lang==="enData"?S.enData:null;
    if(!table)throw new Error("I18N.add: unknown table "+lang);
    for(const k of Object.keys(dict)){
      const v=dict[k];
      if(k in table&&JSON.stringify(table[k])!==JSON.stringify(v))S.dups.push(k);
      table[k]=v;
    }
  };
  /* I18N.addPattern([/^任务集不存在: (.+)$/, "Task set not found: $1"], ...): 服务端提示里带变化部分的, 用正则模式;
     第二项是替换文字 ($1 是第一个括号匹配到的) 或函数 (m, a, b)=>…, 函数里可以再调用 tm() 翻译匹配到的部分 */
  S.addPattern=(...items)=>{for(const [re,to] of items)S.patterns.push({re,to})};
  S.has=(zh,ctx)=>typeof S.en[ctx?ctx+"|"+zh:zh]!=="undefined";

  /* ---------- 语言 ---------- */
  /* 来源优先级: 网址 ?lang= → 离线报告带来的偏好 → 本地存储 → 浏览器语言 (仅 AUTO_DETECT 打开时; zh 开头用中文, 否则英文; 拿不到就用中文) */
  S.detect=(off,stored,nav,url)=>{
    const ok=v=>v==="zh"||v==="en"?v:"";
    const u=ok(url);if(u)return u;
    const o=ok(off&&off.ls&&off.ls[KEY]);if(o)return o;
    const s=ok(stored);if(s)return s;
    return S.AUTO_DETECT&&nav&&!/^zh/i.test(String(nav))?"en":"zh";
  };
  /* 语言切换按钮 (带 data-lang-toggle 的元素) 要不要显示 */
  S.showSwitch=()=>S.READY||S.lang==="en";
  function syncSwitch(){
    if(typeof document==="undefined"||!document.querySelectorAll)return;
    const show=S.showSwitch();
    document.querySelectorAll("[data-lang-toggle]").forEach(el=>{if(el.style)el.style.display=show?"":"none"});
  }
  S.onChange=fn=>{listeners.push(fn)};  /* 语言切换后 (静态文字翻完之后) 依次调用: 动态生成的文字在这里重画 */

  /* ---------- 静态 HTML: 遍历文本节点和 title / placeholder / aria-label / alt, 用词典翻译 ---------- */
  /* 只处理「页面刚打开时就有的」节点 (boot 时记下) 和明确传给 applyStaticI18n 的节点; 之后 JS 动态插入的节点走 t() */
  const KNOWN=typeof WeakSet==="function"?new WeakSet():{has(){return true},add(){}};
  const TXT=new WeakMap(),ATT=new WeakMap(),HTM=new WeakMap();  /* 记着原文, 切回中文时还原 */
  const tx=zh=>{const v=S.en[norm(zh)];return typeof v==="string"?v:undefined};
  function doText(n){
    const cur=n.nodeValue,rec=TXT.get(n);
    if(S.lang==="en"){
      if(rec&&cur===rec.out)return;
      const zh=rec&&cur===rec.zh?rec.zh:cur;  /* 记录里的翻译被别处改掉了: 把现在的值当新的原文 */
      if(!CJK.test(zh))return;
      const v=tx(zh);if(v===undefined)return;
      const m=/^(\s*)[\s\S]*?(\s*)$/.exec(zh),out=m[1]+v+m[2];  /* 保留原来首尾的空白 */
      TXT.set(n,{zh,out});n.nodeValue=out;
    }else if(rec&&cur===rec.out){n.nodeValue=rec.zh;TXT.delete(n)}
  }
  function doAttrs(el){
    if(!el.getAttribute)return;
    let recs=ATT.get(el);
    for(const a of ATTRS){
      const cur=el.getAttribute(a);if(cur==null)continue;
      const rec=recs&&recs[a];
      if(S.lang==="en"){
        if(rec&&cur===rec.out)continue;
        if(!CJK.test(cur))continue;
        const v=tx(cur);if(v===undefined)continue;
        if(!recs){recs={};ATT.set(el,recs)}
        recs[a]={zh:cur,out:v};el.setAttribute(a,v);
      }else if(rec&&cur===rec.out){el.setAttribute(a,rec.zh);delete recs[a]}
    }
  }
  /* 带 data-i18n-html 的元素 (句子中间夹着 <code> <b> <a> 等标签, 拆成文本节点没法翻): 整段 innerHTML 一起翻译, 键是 innerHTML (空白合并) */
  function doHtml(el){
    const cur=el.innerHTML,rec=HTM.get(el);
    if(S.lang==="en"){
      if(rec&&cur===rec.out)return;
      const zh=rec&&cur===rec.zh?rec.zh:cur;
      const v=tx(zh);if(v===undefined)return;
      el.innerHTML=v;
      HTM.set(el,{zh,out:el.innerHTML});  /* 读回来的值 (浏览器序列化后) 才是之后比较用的 */
    }else if(rec&&cur===rec.out){el.innerHTML=rec.zh;HTM.delete(el)}
  }
  /* 文档标题 (<title>): 和文本节点一样记着原文, 切回中文时还原; 标题被别处改成了别的 (比如离线报告按语言重新生成) 就以新的为准 */
  function doTitle(){
    if(typeof document==="undefined"||typeof document.title!=="string")return;
    const cur=document.title;
    if(S.lang==="en"){
      if(title&&cur===title.out)return;
      const zh=title&&cur===title.zh?title.zh:cur;
      const v=CJK.test(zh)?tx(zh):undefined;if(v===undefined)return;
      title={zh,out:v};document.title=v;
    }else if(title&&cur===title.out){document.title=title.zh;title=null}
  }
  function walk(root,only){
    if(!root)return;
    const visit=n=>{
      const ty=n.nodeType;
      if(ty===3){if(!only||KNOWN.has(n)){KNOWN.add(n);doText(n)}return}
      if(ty===1){
        const tag=String(n.tagName||"").toUpperCase();
        if(n.getAttribute&&n.getAttribute("translate")==="no")return;
        const known=!only||KNOWN.has(n);
        if(SKIP[tag]){if(tag==="TEXTAREA"&&known){KNOWN.add(n);doAttrs(n)}return}  /* 里面的内容不翻译; 文本框的 placeholder 要翻译 */
        if(known){KNOWN.add(n);doAttrs(n)}
        if(n.hasAttribute&&n.hasAttribute("data-i18n-html")){if(known)doHtml(n);return}
      }else if(ty!==9&&ty!==11)return;
      const kids=n.childNodes;
      if(kids)for(let i=0;i<kids.length;i++)visit(kids[i]);
    };
    visit(root);
  }
  S._walk=walk;

  /* 换语言: 只改状态和静态 HTML, 然后通知 onChange 的监听者去重画动态内容。app.js 的 setLang(x) 会先写本地偏好再调用它 */
  S.set=lang=>{
    S.lang=lang==="en"?"en":"zh";
    if(typeof document!=="undefined"&&document.documentElement){
      document.documentElement.lang=S.lang==="en"?"en":"zh-CN";
      if(document.documentElement.classList)document.documentElement.classList.remove("i18n-pending");
      doTitle();
      if(document.body)walk(document.body,true);
      syncSwitch();
    }
    for(const fn of listeners.slice()){try{fn(S.lang)}catch(e){if(typeof console!=="undefined")console.error(e)}}
  };
  /* 页面加载时调用一次 (app.js 最前面): 记下静态节点, 英文模式下先翻译, 去掉首屏隐藏 */
  S.boot=()=>{
    if(booted)return;
    booted=true;
    if(typeof document==="undefined"||!document.documentElement)return;
    document.documentElement.lang=S.lang==="en"?"en":"zh-CN";
    if(document.body)walk(document.body,false);
    doTitle();
    syncSwitch();
    if(document.documentElement.classList)document.documentElement.classList.remove("i18n-pending");
  };

  /* 初始语言 */
  try{
    let stored=null,url=null;
    try{stored=localStorage.getItem(KEY)}catch(e){}
    try{url=new URLSearchParams(location.search).get("lang")}catch(e){}   /* ?lang=en */
    S.lang=S.detect(typeof window!=="undefined"?window.LLMB_OFF_STATE:null,stored,typeof navigator!=="undefined"?navigator.language:"",url);
    if(url&&(url==="zh"||url==="en")){try{localStorage.setItem(KEY,url)}catch(e){}}   /* 用网址选了语言就记住, 以后不带 ?lang= 也保持 */
  }catch(e){S.lang="zh"}
  return S;
})();

/* t("中文 {名字}", {名字: 值}, 语境): 中文模式返回原文 (替换占位符); 英文模式查 I18N.en[原文],
   带语境时键是 "语境|原文"。查不到回退成中文并记进 I18N.missing。t 不转义值: 往 HTML 里插值时调用处自己 esc() */
function t(zh,params,ctx){
  if(typeof zh!=="string")zh=zh==null?"":String(zh);
  let s=zh;
  if(I18N.lang==="en"){
    const key=ctx?ctx+"|"+zh:zh,v=I18N.en[key];
    if(typeof v==="string")s=v;else I18N._note("missing",key,true);
  }
  return params?I18N._fill(s,params):s;
}
/* tn("{n} 行", n): 带数量。中文只有一种写法; 英文词条是 [单数, 复数], n === 1 用单数。{n} 默认就是 n, 要千分位等格式传 {n: fmtInt(n)} */
function tn(zh,n,params){
  let s=zh;
  if(I18N.lang==="en"){
    const v=I18N.en[zh];
    if(Array.isArray(v)&&v.length>=2)s=Number(n)===1?v[0]:v[1];
    else if(typeof v==="string")s=v;
    else I18N._note("missing",zh,true);
  }
  return I18N._fill(s,Object.assign({n:String(n)},params));
}
/* td("鹈鹕骑自行车动画"): 数据里的中文名 (作品名、题库科目名、场景名等) 的翻译; 词典是 I18N.enData, 查不到回退原文 */
function td(name){
  if(I18N.lang!=="en"||typeof name!=="string")return name;
  const v=I18N.enData[name];
  if(typeof v==="string")return v;
  if(I18N.CJK.test(name))I18N._note("missingData",name,false);
  return name;
}
/* tm(服务端返回的提示): 先查完整原文, 再依次试 I18N.addPattern 登记的正则模式; 都不行回退原文 (并记进 I18N.missingServer) */
function tm(msg){
  if(I18N.lang!=="en"||typeof msg!=="string"||!I18N.CJK.test(msg))return msg;
  const v=I18N.en[msg];
  if(typeof v==="string")return v;
  for(const p of I18N.patterns){
    p.re.lastIndex=0;
    if(p.re.test(msg)){p.re.lastIndex=0;return msg.replace(p.re,p.to)}
  }
  I18N._note("missingServer",msg,false);
  return msg;
}
/* tk("可用"): 只做标记, 原样返回中文。常量表里的中文 (不能在定义时翻译, 那会固定成加载时的语言) 用它标出来,
   让检查工具认得这是词典的键; 用的时候再 t(常量) 翻译 */
function tk(zh){return zh}
/* 翻译静态 HTML (文本节点和 title / placeholder / aria-label / alt 属性); 原文记着, 切回中文时还原。
   给动态插入的、写死了中文的一整块 HTML 用: applyStaticI18n(容器) */
function applyStaticI18n(root){
  I18N._walk(root||(typeof document!=="undefined"?document.body:null),false);
}
