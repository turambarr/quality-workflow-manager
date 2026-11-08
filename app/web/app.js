'use strict';

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const uid = () => crypto.randomUUID();
const clone = value => JSON.parse(JSON.stringify(value));
const statuses = ['未开始','进行中','待检查','需修改','已完成','不涉及'];
const icons = {
  star:'<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-2.9-5.6 2.9 1.1-6.2L3 9.6l6.2-.9Z"/>',
  down:'<path d="m5 9 7 7 7-7"/>',
  up:'<path d="m5 15 7-7 7 7"/>',
  grid:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  flow:'<rect x="8" y="2" width="8" height="6" rx="1.5"/><rect x="2" y="16" width="7" height="6" rx="1.5"/><rect x="15" y="16" width="7" height="6" rx="1.5"/><path d="M12 8v4M5.5 16v-4h13v4"/>',
  folder:'<path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"/><path d="M3 9h18"/>',
  file:'<path d="M14 2H5a1 1 0 0 0-1 1v18a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V8Z"/><path d="M14 2v6h6M8 13h8M8 17h6"/>',
  plus:'<path d="M12 5v14M5 12h14"/>', minus:'<path d="M5 12h14"/>',
  search:'<circle cx="10.5" cy="10.5" r="7"/><path d="m16 16 5 5"/>',
  arrow:'<path d="M4 12h16m-6-6 6 6-6 6"/>',
  back:'<path d="M20 12H4m6-6-6 6 6 6"/>',
  close:'<path d="m6 6 12 12M18 6 6 18"/>',
  edit:'<path d="m14 4 6 6M4 20l5-1L21 7a2 2 0 0 0-4-4L5 15l-1 5Z"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  save:'<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h12l4 4v12a2 2 0 0 1-2 2Z"/><path d="M7 3v6h10V3M7 21v-8h10v8"/>',
  download:'<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  upload:'<path d="M12 16V4m-5 5 5-5 5 5M4 16v5h16v-5"/>',
  settings:'<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3" fill="currentColor" stroke="none"/><circle cx="15" cy="17" r="3" fill="currentColor" stroke="none"/>',
  check:'<path d="m5 12 4 4L19 6"/>',
  fit:'<path d="M3 9V3h6m6 0h6v6M3 15v6h6m6 0h6v-6"/><rect x="8" y="8" width="8" height="8" rx="1"/>',
  link:'<path d="m10 13 4-4m-5 7-2 2a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0m2 0 2-2a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0" transform="translate(1 0)"/>',
  archive:'<rect x="3" y="3" width="18" height="4" rx="1"/><path d="M5 7v14h14V7M9 12h6"/>',
  info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7v.2"/>',
  copy:'<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
  home:'<path d="m3 10 9-7 9 7v11h-6v-7H9v7H3Z"/>',
  chevron:'<path d="m9 5 7 7-7 7"/>',
  book:'<path d="M12 4C8 2 5 2 2 4v16c3-2 6-2 10 0 4-2 7-2 10 0V4c-3-2-6-2-10 0Zm0 0v16"/>'
};
const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.file}</svg>`;
const statusPill = value => `<span class="pill status-${esc(value)}">${esc(value)}</span>`;
const button = (action, label, glyph, cls='', attrs='') => `<button type="button" class="btn ${cls}" data-action="${action}" ${attrs}>${glyph ? icon(glyph) : ''}${label}</button>`;
const iconButton = (action, label, glyph, attrs='') => `<button type="button" class="icon-btn" data-action="${action}" aria-label="${esc(label)}" title="${esc(label)}" ${attrs}>${icon(glyph)}</button>`;
let state = {groups:[],templates:[]};
let ui = {view:'groups',groupId:null,templateId:null,nodeId:null,tab:'overview',version:null,edit:false,search:'',mode:'work',scope:null,expanded:[],nodeSearch:'',zoom:1,panX:45,panY:45,dirty:false};
let busy = false, toastTimer, dragState = null, suppressClick = false, modalOrigin = null;
let actor = '';
try { actor = localStorage.getItem('quality-author') || ''; } catch (_) {}
const group = () => state.groups.find(g => g.id === ui.groupId);
const isTemplate = () => ui.view === 'template';
const flow = () => isTemplate() ? state.templates.find(t => t.id === ui.templateId) : group();
const selectedNode = () => flow()?.nodes.find(n => n.id === ui.nodeId);
const activeNodes = f => (f?.nodes || []).filter(n => !n.archived);
const latest = n => n?.records?.at(-1);
const nodeStatus = n => latest(n)?.status || '未开始';
const stats = f => {const ns=activeNodes(f).filter(n=>!childrenOf(f,n.id).length||n.templates?.length||n.records?.length);return {total:ns.length,done:ns.filter(n=>nodeStatus(n)==='已完成').length,records:ns.reduce((a,n)=>a+(n.records?.length||0),0)};};
const formatDate = (value, full=false) => {
  if (!value) return '暂无记录';
  const d=new Date(value); if(Number.isNaN(d.getTime()))return '';
  return new Intl.DateTimeFormat('zh-CN',{year:full?'numeric':undefined,month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}).format(d);
};
function toast(message){clearTimeout(toastTimer);$('#toast').textContent=message;$('#toast').classList.add('show');toastTimer=setTimeout(()=>$('#toast').classList.remove('show'),3600);}
async function fetchState(){const response=await fetch('/api/state',{cache:'no-store'});if(!response.ok)throw new Error('无法读取本地记录，请重新打开程序。');state=await response.json();}
async function mutate(path, body={}, method='POST'){
  if(busy)throw new Error('正在保存，请稍候。');
  busy=true;
  try {
    const response=await fetch(`/api${path}`,{method,headers:{'Content-Type':'application/json','X-App-Token':state.csrf_token},body:JSON.stringify(body)});
    const data=await response.json();
    if(!response.ok)throw new Error(typeof data.error==='string'?data.error:(data.message||'保存未完成，请重试。'));
    state=data.state || data;
    return state;
  } catch(error){if(error instanceof TypeError)throw new Error('无法连接本地程序。请保持当前页面，重新启动程序后再保存。');throw error;}
  finally {busy=false;}
}
function mayLeave(){if(!ui.dirty)return true;if(!window.confirm('本次填写尚未保存。是否放弃这些内容？'))return false;delete recordDrafts[ui.nodeId];ui.dirty=false;return true;}
function navigate(view, id){if(!mayLeave())return;ui={...ui,view,groupId:view==='group'?id:null,templateId:view==='template'?id:null,nodeId:null,tab:'overview',version:null,edit:false,search:'',dirty:false,mode:view==='template'?'graph':'work',scope:null,expanded:[],nodeSearch:'',zoom:1,panX:35,panY:50};if(view==='group')ui.nodeId=orderedNodes(group())[0]?.id||null;render();}
function render(){
  const current=flow();
  $('#app').innerHTML=`<div class="shell">
    <aside class="sidebar" aria-label="主导航">
      <div class="brand"><div class="brand-mark"><svg viewBox="0 0 32 38" fill="none" aria-hidden="true"><path d="M8 3h13l6 6v26H8z" stroke="currentColor" stroke-width="1.5"/><path d="M21 3v7h6M3 9v26h18M13 17h9M13 23h9M13 29h5" stroke="currentColor" stroke-width="1.5"/></svg></div><div><div class="brand-name">项目材料管理</div><div class="brand-sub">流程 · 材料 · 记录</div></div></div>
      <nav><div class="nav-label">工作空间</div><button class="nav-item ${['groups','group'].includes(ui.view)?'active':''}" data-action="groups">${icon('grid')}项目组<span class="nav-count">${state.groups.length}</span></button><button class="nav-item ${['templates','template'].includes(ui.view)?'active':''}" data-action="templates">${icon('flow')}流程模板<span class="nav-count">${state.templates.length}</span></button><button class="nav-item ${ui.view==='library'?'active':''}" data-action="library">${icon('book')}过程库</button><button class="nav-item ${ui.view==='favorites'?'active':''}" data-action="favorites">${icon('star')}收藏夹</button></nav>
      ${state.groups.length?`<div><div class="nav-label">项目组快捷入口</div><div class="recent-list">${state.groups.slice(0,6).map(g=>`<button class="recent-group ${g.id===ui.groupId?'active':''}" data-action="open-group" data-id="${esc(g.id)}"><span>${esc(g.name)}</span></button>`).join('')}</div></div>`:''}
      <div class="sidebar-bottom"><button class="nav-item ${ui.view==='backup'?'active':''}" data-action="backup">${icon('save')}数据与备份</button><div class="local-note"><span class="dot"></span>记录保存在本机</div></div>
    </aside>
    <main id="main" class="main ${['group','template'].includes(ui.view)?'project-main':''}" tabindex="-1"><div class="topbar"><div class="breadcrumbs"><button data-action="groups">工作空间</button>${icon('chevron')}<span class="current">${esc(ui.view==='groups'?'项目组':ui.view==='templates'?'流程模板':ui.view==='backup'?'数据与备份':ui.view==='favorites'?'收藏夹':ui.view==='library'?'过程库':current?.name||'流程图')}</span></div><div class="topbar-right">本机工作空间</div><nav class="mobile-nav" aria-label="主导航">${iconButton('groups','项目组','grid')}${iconButton('templates','流程模板','flow')}${iconButton('favorites','收藏夹','star')}${iconButton('backup','数据与备份','save')}</nav></div>
    ${ui.view==='groups'?renderGroups():ui.view==='templates'?renderTemplates():ui.view==='backup'?renderBackup():ui.view==='favorites'?renderFavorites():ui.view==='library'?renderLibrary():renderWorkspace()}
    </main></div>`;
  if(['group','template'].includes(ui.view)){applyTransform();wireCanvas();}
}
function groupCards(){
  const q=ui.search.trim().toLocaleLowerCase();
  const groups=state.groups.filter(g=>(g.name+' '+g.teacher).toLocaleLowerCase().includes(q));
  return `${groups.map(g=>{const s=stats(g);return `<button class="group-card" data-action="open-group" data-id="${esc(g.id)}"><div class="card-top"><span class="folder-symbol">${icon('folder')}</span>${g.is_demo?'<span class="tag">示例</span>':icon('arrow')}</div><h3>${esc(g.name)}</h3><div class="description">${esc(g.teacher||'负责老师待填写')}</div><div class="card-progress"><div class="progress-meta"><span>节点完成情况</span><span class="mono">${s.done} / ${s.total}</span></div><div class="progress-track"><span style="width:${s.total?s.done/s.total*100:0}%"></span></div></div><div class="card-footer"><span>${s.records} 次情况记录</span><span>${formatDate(g.updated_at)}</span></div></button>`;}).join('')}${!q?`<button class="group-card add-card" data-action="new-group">${icon('plus')}<span>新建项目组</span><span class="small muted">从空白流程或已有模板开始</span></button>`:''}${!groups.length&&q?'<div class="empty"><h3>没有找到项目组</h3><p>试试其他名称或老师姓名。</p></div>':''}`;
}
function renderGroups(){const total=state.groups.reduce((a,g)=>a+stats(g).total,0),records=state.groups.reduce((a,g)=>a+stats(g).records,0);return `<div class="page-scroll"><div class="page"><div class="page-header"><div><div class="eyebrow">工作空间 / 项目组</div><h1>项目组</h1><p class="page-description">打开一份流程，继续记录新的进展。</p></div>${button('new-group','新建项目组','plus','primary')}</div><div class="summary-line"><span><strong>${state.groups.length}</strong>个项目组</span><span><strong>${total}</strong>个流程节点</span><span><strong>${records}</strong>次情况记录</span></div><div class="search-row"><label class="search">${icon('search')}<input id="group-search" type="search" placeholder="搜索项目组或负责老师" aria-label="搜索项目组或负责老师" value="${esc(ui.search)}"></label><span class="result-count">每个项目组独立记录</span></div><div class="group-grid" id="group-grid">${groupCards()}</div><p class="page-footnote">${icon('info')}示例项目组用于体验操作，可另外创建自己的项目组。</p></div></div>`;}
function renderTemplates(){return `<div class="page-scroll"><div class="page"><div class="page-header"><div><div class="eyebrow">工作空间 / 流程模板</div><h1>流程模板</h1><p class="page-description">整理常用节点，创建项目组时直接使用。</p></div>${button('new-template','新建模板','plus','primary')}</div><div class="group-grid">${state.templates.map(t=>`<button class="group-card template-card" data-action="open-template" data-id="${esc(t.id)}"><div class="card-top"><span class="folder-symbol">${icon('flow')}</span>${icon('arrow')}</div><h3>${esc(t.name)}</h3><p class="description">${esc(t.description||'点击设置节点说明、文档模板与连接关系。')}</p><div class="template-count"><span>${activeNodes(t).length} 个节点</span><span>${t.edges?.length||0} 条连接</span></div></button>`).join('')}</div><p class="page-footnote">${icon('info')}模板用于创建新的项目组，现有项目组的流程独立保存。</p></div></div>`;}
function renderBackup(){return `<div class="page-scroll"><div class="page"><div class="page-header"><div><div class="eyebrow">工作空间 / 数据与备份</div><h1>妥善保存每一次记录</h1><p class="page-description">项目组、流程模板和历次记录一同备份。</p></div></div><div class="backup-panel"><section class="backup-section"><h3>导出数据备份</h3><p>将当前数据保存为备份文件。换电脑或重新安装程序时，可以导入这份文件继续使用。</p>${button('download-backup','导出备份','download','primary')}</section><section class="backup-section"><h3>从备份恢复</h3><p>恢复后将使用备份中的项目组与记录。恢复之前，程序会另外保存一份当前数据。</p><label class="btn file-label">${icon('upload')}选择备份文件<input type="file" id="restore-file" accept=".sqlite,.sqlite3,.db" aria-label="选择备份文件"></label></section><section class="backup-section"><h3>本机数据位置</h3><p>记录与程序分开保存，更新程序时可以继续使用原有数据。</p><div class="path">${esc(state.storage?.database_path||state.storage?.db_path||state.storage?.path||'数据保存在本机应用数据目录')}</div></section></div></div></div>`;}
function renderNode(n){const count=n.records?.length||0;const descendants=orderedNodes(flow(),n.id).filter(x=>!childrenOf(flow(),x.id).length||x.templates?.length||x.records?.length);const progress=descendants.length&&!count?`<span class="small muted">子项 ${descendants.filter(x=>nodeStatus(x)==='已完成').length} / ${descendants.length} 完成</span>`:statusPill(nodeStatus(n));return `<button class="node ${n.id===ui.nodeId?'selected':''}" data-node="${esc(n.id)}" data-action="select-node" data-id="${esc(n.id)}" style="left:${Number(n.x)||0}px;top:${Number(n.y)||0}px" title="${esc(n.title)}" aria-label="${esc(n.title)}，${esc(nodeStatus(n))}，${n.templates?.length||0}份文档模板"><span class="node-category">${esc(n.category||'流程节点')}</span><span class="node-title">${esc(n.title)}</span><span class="node-bottom">${isTemplate()?`<span class="small muted">${n.templates?.length||0} 份模板</span>`:progress}<span class="node-meta">${icon('file')}${n.templates?.length||0}${count?` · ${icon('clock')}${count}`:''}</span></span></button>`;}
function edgePath(source,target){let sx=source.x+240,sy=source.y+66,tx=target.x,ty=target.y+66;if(tx>=sx-20){const bend=Math.max(45,Math.abs(tx-sx)*.48);return `M ${sx} ${sy} C ${sx+bend} ${sy}, ${tx-bend} ${ty}, ${tx} ${ty}`;}if(Math.abs(ty-sy)>90){sx=source.x+120;sy=source.y+(ty>sy?132:0);tx=target.x+120;ty=target.y+(ty>sy?0:132);const bend=Math.max(45,Math.abs(ty-sy)*.5);return `M ${sx} ${sy} C ${sx} ${sy+(ty>sy?bend:-bend)}, ${tx} ${ty-(ty>sy?bend:-bend)}, ${tx} ${ty}`;}return `M ${sx} ${sy} C ${sx+75} ${sy}, ${sx+75} ${sy-110}, ${sx-30} ${sy-110} L ${tx-40} ${ty-110} Q ${tx-75} ${ty-110}, ${tx-75} ${ty-60} Q ${tx-75} ${ty}, ${tx} ${ty}`;}
function renderEdges(f){const ns=activeNodes(f);return `<svg class="edge-layer" id="edge-layer" width="1" height="1" aria-hidden="true"><defs><marker id="arrowhead" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M1 1 7 4 1 7" fill="none" stroke="#b7ae9d" stroke-width="1.3"/></marker></defs>${(f.edges||[]).map(edge=>{const a=ns.find(n=>n.id===edge.source),b=ns.find(n=>n.id===edge.target);return a&&b?`<path class="edge-path" data-edge="${esc(edge.id)}" d="${edgePath(a,b)}" marker-end="url(#arrowhead)"/>`:'';}).join('')}</svg>`;}
function renderTemplateNames(templates){return templates?.length?`<div class="document-list">${templates.map(t=>`<div class="document-row">${icon('file')}<div class="document-info"><div class="document-title">${esc(t.name)}</div></div></div>`).join('')}</div>`:'<div class="placeholder">对应文档模板名称待补充。</div>';}
function renderDocuments(docs){return docs?.length?`<div class="document-list">${docs.map(d=>`<div class="document-row">${icon('file')}<div class="document-info"><div class="document-title">${esc(d.name)}</div>${d.note?`<div class="document-note">${esc(d.note)}</div>`:''}</div>${statusPill(d.status||'未开始')}</div>`).join('')}</div>`:'';}
function renderHistory(n){return n.records?.length?`<p class="history-intro">每次保存的完整情况，按时间依次留存。</p><div class="timeline">${[...n.records].reverse().map((r,i)=>`<button class="history-item" data-action="view-version" data-id="${esc(r.id)}"><span class="history-title"><span>第 ${r.version} 次记录 ${i===0?'<span class="tag">最新</span>':''}</span>${statusPill(r.status)}</span><div class="history-date">${formatDate(r.created_at,true)} · ${esc(r.author)}</div><p class="history-note">${esc(r.note||'查看本次各份材料的完整情况')}</p></button>`).join('')}</div>`:`<div class="empty">${icon('clock')}<h3>还没有历史记录</h3><p>保存第一次情况后，就会出现在这里。</p></div>`;}
function renderVersion(n){const r=n.records.find(r=>r.id===ui.version);if(!r)return '<p>未找到这份记录。</p>';return `${button('tab-history','返回历次记录','back','quiet small-btn')}<div class="history-banner" style="margin-top:15px"><strong>第 ${r.version} 次记录 · 历史内容</strong>${formatDate(r.created_at,true)} · ${esc(r.author)}</div><section class="detail-section"><div class="section-label"><span>当次完成情况</span>${statusPill(r.status)}</div><p class="prose">${esc(r.note||'未填写补充说明。')}</p></section><section class="detail-section"><div class="section-label">当次文档情况</div>${renderDocuments(r.documents)||'<div class="placeholder">当次未设置文档模板。</div>'}</section><section class="detail-section"><div class="section-label">当时的节点名称与说明</div><p class="document-title">${esc(r.node_title||n.title)}</p><p class="prose">${esc(r.node_description||'当时未填写节点说明。')}</p></section>${button('tab-overview','返回当前情况','back','quiet small-btn')}`;}
const options = value => statuses.map(s=>`<option ${s===value?'selected':''}>${s}</option>`).join('');
function refreshDetail(){render();}
function applyTransform(){const w=$('#world');if(w)w.style.transform=`translate(${ui.panX}px,${ui.panY}px) scale(${ui.zoom})`;if($('#zoom-label'))$('#zoom-label').textContent=`${Math.round(ui.zoom*100)}%`;}
function fitGraph(){const viewport=$('#flow-viewport');if(!viewport)return;const ns=graphModel.nodes;if(!ns.length){ui.zoom=1;ui.panX=35;ui.panY=45;return applyTransform();}const minX=Math.min(...ns.map(n=>n.x)),minY=Math.min(...ns.map(n=>n.y)),maxX=Math.max(...ns.map(n=>n.x+240)),maxY=Math.max(...ns.map(n=>n.y+165));const pad=45;ui.zoom=Math.max(.25,Math.min(1,(viewport.clientWidth-pad*2)/(maxX-minX),(viewport.clientHeight-pad*2)/(maxY-minY)));ui.panX=(viewport.clientWidth-(maxX-minX)*ui.zoom)/2-minX*ui.zoom;ui.panY=35-minY*ui.zoom;applyTransform();}
function zoomBy(factor,cx,cy){const v=$('#flow-viewport');if(!v)return;cx=cx??v.clientWidth/2;cy=cy??v.clientHeight/2;const before=ui.zoom;ui.zoom=Math.max(.15,Math.min(2,ui.zoom*factor));ui.panX=cx-(cx-ui.panX)*ui.zoom/before;ui.panY=cy-(cy-ui.panY)*ui.zoom/before;applyTransform();}
function wireCanvas(){const viewport=$('#flow-viewport');if(!viewport)return;viewport.addEventListener('wheel',event=>{event.preventDefault();if(Math.abs(event.deltaX)>Math.abs(event.deltaY)){ui.panX-=event.deltaX;applyTransform();return;}const rect=viewport.getBoundingClientRect();zoomBy(event.deltaY>0?.92:1.08,event.clientX-rect.left,event.clientY-rect.top);},{passive:false});viewport.addEventListener('pointerdown',event=>{if(event.button!==0||event.target.closest('button'))return;dragState={pointer:event.pointerId,sx:event.clientX,sy:event.clientY,px:ui.panX,py:ui.panY,moved:false};viewport.setPointerCapture(event.pointerId);});viewport.addEventListener('pointermove',event=>{if(!dragState||event.pointerId!==dragState.pointer)return;const dx=event.clientX-dragState.sx,dy=event.clientY-dragState.sy;if(Math.abs(dx)+Math.abs(dy)>4)dragState.moved=true;if(dragState.moved){ui.panX=dragState.px+dx;ui.panY=dragState.py+dy;applyTransform();}});const finish=()=>{dragState=null;};viewport.addEventListener('pointerup',finish);viewport.addEventListener('pointercancel',finish);}
async function updateNode(id,patch){if(isTemplate()){const t=clone(flow());t.nodes=t.nodes.map(n=>n.id===id?{...n,...patch}:n);return mutate(`/templates/${encodeURIComponent(t.id)}`,{name:t.name,description:t.description,nodes:t.nodes,edges:t.edges},'PUT');}return mutate(`/groups/${encodeURIComponent(ui.groupId)}/nodes/${encodeURIComponent(id)}`,patch,'PUT');}
function showModal(title,body,footer='',wide=false){modalOrigin=document.activeElement;$('#modal-root').innerHTML=`<div class="modal-backdrop"><section class="modal ${wide?'wide':''}" role="dialog" aria-modal="true" aria-labelledby="modal-title"><div class="modal-head"><h2 id="modal-title">${title}</h2>${iconButton('close-modal','关闭窗口','close')}</div>${body}${footer?`<div class="modal-footer">${footer}</div>`:''}</section></div>`;const first=$('.modal input:not([type=hidden]),.modal textarea,.modal select,.modal button');first?.focus();}
function closeModal(){if($('#modal-root form')&&$('#modal-root').dataset.dirty==='true'&&!window.confirm('尚未保存，是否放弃这次修改？'))return;$('#modal-root').innerHTML='';$('#modal-root').dataset.dirty='false';pendingNode=null;modalOrigin?.focus?.();}
function forceCloseModal(){$('#modal-root').dataset.dirty='false';closeModal();}
const formFooter = (label='保存') => `${button('close-modal','取消',null)}<button type="submit" form="modal-form" class="btn primary">${esc(label)}</button>`;
const basicFields=['项目名称关键词（非密处理）','校内项目编号','金额（万元）','方向','项目类型（横向／纵向）','来源单位','项目起始时间','项目截止时间','项目状态','研究内容与成果形式','是否有采购','是否有更改','是否涉及关键／重要／特殊过程','是否有售后要求','是否使用测量设备','是否延期交付','是否有倒签情况','结题项目技术文档是否完整','项目负责人','负责人电话','联系人','联系人电话','所属学院','学院联系人'];
function groupModal(edit=false){const g=edit?group():null;showModal(edit?'项目资料':'新建项目组',`<form id="modal-form" data-kind="${edit?'edit-group':'new-group'}" class="modal-body"><div class="error-box" id="modal-error" role="alert"></div><div class="field-row"><div><label class="form-label" for="group-name">项目组名称</label><input class="input" id="group-name" name="name" value="${esc(g?.name||'')}" placeholder="例如：先进通信项目组" required maxlength="150"></div><div><label class="form-label" for="group-teacher">负责老师</label><input class="input" id="group-teacher" name="teacher" value="${esc(g?.teacher||'')}" placeholder="填写负责老师姓名" maxlength="100"></div></div>${!edit?`<div><label class="form-label" for="group-template">使用流程模板</label><select class="input" id="group-template" name="template_id"><option value="">空白流程 · 自行添加节点</option>${state.templates.map(t=>`<option value="${esc(t.id)}">${esc(t.name)} · ${activeNodes(t).length} 个节点</option>`).join('')}</select><p class="form-help">创建后可以按项目组的实际情况调整。</p></div>`:''}<div><label class="form-label" for="group-description">项目组说明</label><textarea class="input" id="group-description" name="description" placeholder="简单记录项目组的情况">${esc(g?.description||'')}</textarea></div><details class="collapse"><summary>更多项目基本信息</summary><div class="basic-fields">${basicFields.map((key,i)=>`<label><span class="field-label">${esc(key)}</span><input class="input" data-basic-key="${esc(key)}" value="${esc(g?.basic_info?.[key]||'')}" maxlength="1000"></label>`).join('')}</div></details></form>`,formFooter(edit?'保存资料':'创建项目组'),true);}
function templateMetaModal(create=false,fromGroup=false){const t=fromGroup?group():flow();showModal(fromGroup?'保存为流程模板':create?'新建流程模板':'模板信息',`<form id="modal-form" data-kind="${fromGroup?'save-template':create?'new-template':'edit-template-meta'}" class="modal-body"><div id="modal-error" class="error-box" role="alert"></div><div><label class="form-label" for="template-name">模板名称</label><input class="input" id="template-name" name="name" value="${esc(create?'':fromGroup?(t.name+'的流程'):t.name)}" required maxlength="150" placeholder="例如：硬件研制流程"></div><div><label class="form-label" for="template-description">模板说明</label><textarea class="input" id="template-description" name="description">${esc(create||fromGroup?'':t.description||'')}</textarea></div>${fromGroup?'<p class="form-help">保存节点说明、对应模板名称和连线，办理记录继续留在当前项目组。</p>':''}</form>`,formFooter(create?'创建模板':'保存模板'));}
function nodeModal(edit=false){if(!flow())return;const n=edit?selectedNode():null;showModal(edit?'编辑节点':'添加流程节点',`<form id="modal-form" data-kind="${edit?'edit-node':'new-node'}" class="modal-body"><div id="modal-error" class="error-box" role="alert"></div><div class="field-row"><div><label class="form-label" for="node-title">节点名称</label><input class="input" id="node-title" name="title" value="${esc(n?.title||'')}" required maxlength="200" placeholder="例如：第1次采购"></div><div><label class="form-label" for="node-category">分类（可选）</label><input class="input" id="node-category" name="category" value="${esc(n?.category||'')}" placeholder="例如：采购与外包" list="category-list"><datalist id="category-list">${[...new Set(activeNodes(flow()).map(n=>n.category).filter(Boolean))].map(c=>`<option value="${esc(c)}">`).join('')}</datalist></div></div><div class="field-row"><div><label class="form-label" for="node-parent">所属流程</label><select class="input" id="node-parent" name="parent_id"><option value="">主流程</option>${orderedNodes(flow()).filter(x=>x.id!==n?.id&&!isDescendant(flow(),x.id,n?.id)).map(x=>`<option value="${esc(x.id)}" ${(n?.parent_id||(edit?null:ui.scope))===x.id?'selected':''}>${esc(nodePath(flow(),x))}</option>`).join('')}</select></div><div><label class="form-label" for="node-date">计划日期（可选）</label><input class="input" type="date" id="node-date" name="planned_date" value="${esc(n?.planned_date||'')}"></div></div><div><label class="form-label" for="node-description">节点说明</label><textarea class="input" id="node-description" name="description" rows="5" placeholder="填写这个节点的含义、工作要求和注意事项。也可以稍后补充。">${esc(n?.description||'')}</textarea></div><div><label class="form-label">对应文档模板</label><div id="template-names">${(n?.templates?.length?n.templates:[{id:uid(),name:''}]).map(templateInputRow).join('')}</div>${button('add-template-name','添加模板名称','plus','quiet small-btn')}<p class="form-help">一个节点可以对应多份模板；此处记录模板名称。</p></div>${edit?`<div class="button-row">${button('duplicate-node','复制为另一个节点','copy','quiet small-btn')}${button('archive-node',isTemplate()?'删除节点':'归档节点','archive','quiet small-btn danger')}</div>`:''}</form>`,formFooter(edit?'保存节点':'添加节点'),true);}
function templateInputRow(t){return `<div class="template-edit-row" data-template-id="${esc(t.id)}"><input class="input template-name-input" aria-label="文档模板名称" value="${esc(t.name)}" placeholder="例如：8.4-1《供方评价单》" maxlength="300">${iconButton('remove-template-name','移除这份模板名称','close')}</div>`;}
function edgeModal(){const ns=childrenOf(flow(),ui.scope);showModal('设置节点连接',`<div class="modal-body"><p class="muted small">连接用于提示先后关系，各节点仍可独立记录进展。</p><form id="edge-form"><div class="field-row"><div><label class="form-label" for="edge-source">从节点</label><select class="input" id="edge-source" name="source" required>${ns.map(n=>`<option value="${esc(n.id)}">${esc(n.title)}</option>`).join('')}</select></div><div><label class="form-label" for="edge-target">连接到</label><select class="input" id="edge-target" name="target" required>${ns.map((n,i)=>`<option value="${esc(n.id)}" ${i===1?'selected':''}>${esc(n.title)}</option>`).join('')}</select></div></div><div class="error-box" id="edge-error" role="alert" style="margin-top:12px"></div><div class="form-actions"><button class="btn primary" type="submit" ${ns.length<2?'disabled':''}>${icon('link')}添加连接</button></div></form><div>${(flow().edges||[]).filter(e=>ns.some(n=>n.id===e.source)&&ns.some(n=>n.id===e.target)).map(edge=>`<div class="edge-row"><span>${esc(ns.find(n=>n.id===edge.source)?.title||'已归档节点')}</span>${icon('arrow')}<span>${esc(ns.find(n=>n.id===edge.target)?.title||'已归档节点')}</span>${iconButton('delete-edge','移除连接','close',`data-id="${esc(edge.id)}"`)}</div>`).join('')||'<p class="muted small">还没有连接。可以根据实际工作安排添加。</p>'}</div></div>`,button('close-modal','完成',null),true);}
function archivesModal(){const ns=flow().nodes.filter(n=>n.archived);showModal('已归档的节点',`<div class="modal-body"><p class="small muted">节点的历次记录继续保留，恢复后可以再次查看和填写。</p>${ns.map(n=>`<div class="archive-row"><div><p>${esc(n.title)}</p><small>${n.records?.length||0} 次记录</small></div>${button('restore-node','恢复',null,'small-btn',`data-id="${esc(n.id)}"`)}</div>`).join('')||'<p class="muted">暂无已归档节点。</p>'}</div>`,button('close-modal','关闭',null));}

document.addEventListener('click',async event=>{
  const target=event.target.closest('[data-action]');if(!target||target.disabled)return;const action=target.dataset.action;
  if(['new-group','edit-group','new-template','edit-template-meta','save-as-template','new-node','edit-node','edges','archives'].includes(action)&&!mayLeave())return;
  if(action==='select-node'&&suppressClick)return;
  try {
    if(action==='groups')return navigate('groups');
    if(action==='templates')return navigate('templates');
    if(action==='backup')return navigate('backup');
    if(action==='open-group')return navigate('group',target.dataset.id);
    if(action==='open-template')return navigate('template',target.dataset.id);
    if(action==='new-group')return groupModal();
    if(action==='edit-group')return groupModal(true);
    if(action==='new-template')return templateMetaModal(true);
    if(action==='edit-template-meta')return templateMetaModal();
    if(action==='save-as-template')return templateMetaModal(false,true);
    if(action==='close-modal')return closeModal();
    if(action==='select-node'){return openWorkNode(target.dataset.id);}
    if(action==='close-node'){if(!mayLeave())return;ui.mode='graph';ui.dirty=false;render();return;}
    if(action==='toggle-edit'){if(!mayLeave())return;ui.edit=!ui.edit;ui.mode='graph';ui.dirty=false;render();return;}
    if(action==='new-node')return nodeModal();
    if(action==='edit-node')return nodeModal(true);
    if(action==='edges')return edgeModal();
    if(action==='archives')return archivesModal();
    if(action==='fit')return fitGraph();
    if(action==='zoom-in')return zoomBy(1.2);
    if(action==='zoom-out')return zoomBy(1/1.2);
    if(action==='tab-overview'||action==='tab-history'||action==='cancel-record'){if(!mayLeave())return;ui.tab=action==='tab-history'?'history':'overview';ui.dirty=false;refreshDetail();return;}
    if(action==='new-record'){if(ui.tab==='record')return;ui.tab='record';ui.dirty=false;refreshDetail();$('#record-author')?.focus();return;}
    if(action==='view-version'){ui.tab='version';ui.version=target.dataset.id;refreshDetail();return;}
    if(action==='add-template-name'){$('#template-names').insertAdjacentHTML('beforeend',templateInputRow({id:uid(),name:''}));$('#modal-root').dataset.dirty='true';$$('.template-name-input').at(-1)?.focus();return;}
    if(action==='remove-template-name'){target.closest('.template-edit-row').remove();$('#modal-root').dataset.dirty='true';return;}
    if(action==='duplicate-node'){const n=selectedNode(),data={title:n.title+'（副本）',description:n.description,category:n.category,x:n.x+35,y:n.y+165,templates:(n.templates||[]).map(t=>({id:uid(),name:t.name}))};await addNode({...data,parent_id:n.parent_id||null,order_index:(n.order_index||0)+1,planned_date:n.planned_date||''});forceCloseModal();render();toast('已复制节点，办理记录从空白开始');return;}
    if(action==='archive-node'){const n=selectedNode();if(!window.confirm(isTemplate()?'确定从这个流程模板中删除该节点？':'归档后节点将从流程图隐藏，已有记录继续保留。是否归档？'))return;if(isTemplate()){const t=clone(flow());const removed=new Set(t.nodes.filter(x=>x.id===n.id||isDescendant(t,x.id,n.id)).map(x=>x.id));t.nodes=t.nodes.filter(x=>!removed.has(x.id));t.edges=t.edges.filter(e=>!removed.has(e.source)&&!removed.has(e.target));await mutate(`/templates/${encodeURIComponent(t.id)}`,t,'PUT');}else{await mutate(`/groups/${encodeURIComponent(ui.groupId)}/nodes/${encodeURIComponent(n.id)}`,{},'DELETE');}forceCloseModal();ui.nodeId=orderedNodes(flow())[0]?.id||null;render();toast(isTemplate()?'节点已删除':'节点已归档');return;}
    if(action==='restore-node'){await updateNode(target.dataset.id,{archived:false});render();archivesModal();toast('节点已恢复');return;}
    if(action==='delete-edge'){if(isTemplate()){const t=clone(flow());t.edges=t.edges.filter(e=>e.id!==target.dataset.id);await mutate(`/templates/${encodeURIComponent(t.id)}`,t,'PUT');}else await mutate(`/groups/${encodeURIComponent(ui.groupId)}/edges/${encodeURIComponent(target.dataset.id)}`,{},'DELETE');render();edgeModal();toast('连接已移除');return;}
    if(action==='download-backup'){target.disabled=true;try{const response=await fetch('/api/backup');if(!response.ok)throw new Error('备份未完成，请重试。');const blob=await response.blob();const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download=`项目材料备份-${new Date().toISOString().slice(0,10)}.sqlite3`;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);toast('已导出备份文件');}finally{target.disabled=false;}return;}
  }catch(error){toast(error.message);}
});
async function addNode(data){if(isTemplate()){const t=clone(flow());const id=uid();t.nodes.push({id,...data,records:[],archived:false});await mutate(`/templates/${encodeURIComponent(t.id)}`,t,'PUT');ui.nodeId=id;}else{const before=new Set(flow().nodes.map(n=>n.id));await mutate(`/groups/${encodeURIComponent(ui.groupId)}/nodes`,data);ui.nodeId=flow().nodes.find(n=>!before.has(n.id))?.id;}ui.tab='overview';}
document.addEventListener('input',event=>{if(event.target.id==='group-search'){ui.search=event.target.value;$('#group-grid').innerHTML=groupCards();}if(event.target.closest('#record-form')){ui.dirty=true;captureDraft();}if(event.target.closest('#modal-form'))$('#modal-root').dataset.dirty='true';});
document.addEventListener('change',event=>{if(event.target.closest('#record-form')){ui.dirty=true;captureDraft();}if(event.target.closest('#modal-form'))$('#modal-root').dataset.dirty='true';});
document.addEventListener('submit',async event=>{
  const form=event.target;if(!['record-form','modal-form','edge-form'].includes(form.id))return;event.preventDefault();const submit=form.querySelector('[type=submit]')||document.querySelector(`[form="${form.id}"]`);if(submit)submit.disabled=true;
  const values=Object.fromEntries(new FormData(form));
  const errorEl=$(form.id==='record-form'?'#record-error':form.id==='edge-form'?'#edge-error':'#modal-error');if(errorEl)errorEl.textContent='';
  try {
    if(form.id==='record-form'){
      const n=selectedNode();const documents=$$('.record-doc',form).map(row=>({template_id:row.dataset.template,status:$('.doc-status',row).value,note:$('.doc-note',row).value}));
      await mutate(`/groups/${encodeURIComponent(ui.groupId)}/nodes/${encodeURIComponent(n.id)}/records`,{...values,documents,expected_version:Number(form.dataset.version||0)});actor=values.author;try{localStorage.setItem('quality-author',actor);}catch(_){}delete recordDrafts[n.id];ui.dirty=false;ui.tab='overview';if(pendingNode){ui.nodeId=pendingNode;pendingNode=null;}forceCloseModal();render();toast('本次情况已保存，之前的记录继续保留');return;
    }
    if(form.id==='edge-form'){
      if(values.source===values.target)throw new Error('请选择两个不同的节点。');if((flow().edges||[]).some(e=>e.source===values.source&&e.target===values.target))throw new Error('这两个节点已经连接。');
      if(isTemplate()){const t=clone(flow());t.edges.push({id:uid(),...values});await mutate(`/templates/${encodeURIComponent(t.id)}`,t,'PUT');}else await mutate(`/groups/${encodeURIComponent(ui.groupId)}/edges`,values);
      render();edgeModal();toast('连接已添加');return;
    }
    const kind=form.dataset.kind;
    if(kind==='new-group'||kind==='edit-group'){
      const basic_info={...(kind==='edit-group'?group().basic_info:{})};$$('[data-basic-key]',form).forEach(el=>{basic_info[el.dataset.basicKey]=el.value;});
      if(kind==='new-group'){const before=new Set(state.groups.map(g=>g.id));await mutate('/groups',{...values,template_id:values.template_id||null,basic_info});const id=state.groups.find(g=>!before.has(g.id))?.id;forceCloseModal();navigate('group',id);toast('项目组已创建');}
      else{await mutate(`/groups/${encodeURIComponent(ui.groupId)}`,{...values,basic_info},'PUT');forceCloseModal();render();toast('项目资料已保存');}return;
    }
    if(['new-template','save-template','edit-template-meta'].includes(kind)){
      if(kind==='edit-template-meta'){await mutate(`/templates/${encodeURIComponent(ui.templateId)}`,values,'PUT');forceCloseModal();render();}
      else{const before=new Set(state.templates.map(t=>t.id));await mutate('/templates',{...values,...(kind==='save-template'?{group_id:ui.groupId}:{nodes:[],edges:[]})});const id=state.templates.find(t=>!before.has(t.id))?.id;forceCloseModal();if(kind==='new-template')navigate('template',id);else render();}toast('流程模板已保存');return;
    }
    if(kind==='new-node'||kind==='edit-node'){
      const templates=$$('.template-edit-row',form).map(row=>({id:row.dataset.templateId,name:$('.template-name-input',row).value.trim()})).filter(t=>t.name);
      const patch={...values,templates,parent_id:values.parent_id||null};
      if(kind==='edit-node')await updateNode(ui.nodeId,patch);
      else{const ns=childrenOf(flow(),patch.parent_id);await addNode({...patch,x:60+ns.length*300,y:70,order_index:ns.length});}
      forceCloseModal();render();toast('节点已保存');return;
    }
  }catch(error){if(errorEl){errorEl.textContent=error.message;errorEl.scrollIntoView({block:'nearest'});}toast(error.message);}
  finally{if(submit)submit.disabled=false;}
});
document.addEventListener('change',async event=>{
  if(event.target.id!=='restore-file')return;const file=event.target.files?.[0];if(!file)return;
  if(!window.confirm('将使用所选备份替换当前工作数据。程序会先保存一份当前数据。是否继续恢复？')){event.target.value='';return;}
  try{if(busy)throw new Error('正在保存，请稍后恢复。');busy=true;const response=await fetch('/api/restore',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-App-Token':state.csrf_token},body:file});const data=await response.json();if(!response.ok)throw new Error(data.error||'恢复未完成，请确认备份文件有效。');state=data.state||data;ui.nodeId=null;ui.groupId=null;ui.templateId=null;render();toast('数据已恢复');}catch(error){toast(error.message);}finally{busy=false;event.target.value='';}
});
document.addEventListener('keydown',event=>{
  const modal=$('.modal');if(event.key==='Escape'){if(modal)closeModal();else if(ui.mode==='work'&&mayLeave()){ui.mode='graph';ui.dirty=false;render();}}
  if(event.key==='Tab'&&modal){const focusable=$$('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]',modal).filter(el=>el.getClientRects().length);const first=focusable[0],last=focusable.at(-1);if(!modal.contains(document.activeElement)){event.preventDefault();first?.focus();}else if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}}
});
window.addEventListener('beforeunload',event=>{if(ui.dirty||$('#modal-root').dataset.dirty==='true'){event.preventDefault();event.returnValue='';}});
async function boot(){try{await fetchState();render();}catch(error){$('#app').innerHTML=`<div class="boot"><div><h2>暂时无法打开工作空间</h2><p class="muted" style="margin:12px 0 20px">${esc(error.message)}</p><button class="btn primary" id="retry">重新连接</button></div></div>`;$('#retry').onclick=boot;}}
boot();
