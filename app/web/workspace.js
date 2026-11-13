'use strict';

const recordDrafts = {};
let pendingNode = null;
let graphModel = {nodes:[],edges:[],branches:[],sections:[]};
let orderDraft = [];
const childrenOf = (f,parent=null) => activeNodes(f).filter(n=>(n.parent_id||null)===(parent||null)).sort((a,b)=>(a.order_index||0)-(b.order_index||0));
function orderedNodes(f,parent=null,depth=0){if(depth>10)return [];return childrenOf(f,parent).flatMap(n=>[n,...orderedNodes(f,n.id,depth+1)]);}
function isDescendant(f,id,ancestor){if(!ancestor)return false;let n=f?.nodes.find(x=>x.id===id),seen=new Set();while(n?.parent_id&&!seen.has(n.id)){seen.add(n.id);if(n.parent_id===ancestor)return true;n=f.nodes.find(x=>x.id===n.parent_id);}return false;}
function nodePath(f,n){const path=[n.title];let parent=n.parent_id,seen=new Set();while(parent&&!seen.has(parent)){seen.add(parent);const p=f.nodes.find(x=>x.id===parent);if(!p)break;path.unshift(p.title);parent=p.parent_id;}return path.join(' / ');}
function nodeDepth(f,n){let depth=0,parent=n.parent_id,seen=new Set();while(parent&&!seen.has(parent)){seen.add(parent);depth++;parent=f.nodes.find(x=>x.id===parent)?.parent_id;}return depth;}
function recordFormValues(){const form=$('#record-form');if(!form)return null;return {author:$('#record-author').value,status:$('#record-status').value,note:$('#record-note').value,documents:$$('.record-doc',form).map(row=>({template_id:row.dataset.template,status:$('.doc-status',row).value,note:$('.doc-note',row).value}))};}
function sameRecordValues(a,b){if(!a||!b)return false;if(a.author!==b.author||a.status!==b.status||a.note!==b.note)return false;const map=list=>Object.fromEntries((list||[]).map(d=>[d.template_id,`${d.status}\u0000${d.note}`]));const left=map(a.documents),right=map(b.documents);const keys=new Set([...Object.keys(left),...Object.keys(right)]);return [...keys].every(k=>left[k]===right[k]);}
function syncSaveState(){const form=$('#record-form');if(!form)return;const r=latest(selectedNode()),changed=!r||!sameRecordValues(recordFormValues(),r);const repeated=!!r&&recordDay(r)===todayKey();ui.dirty=changed;const button=document.querySelector('[form="record-form"]');if(button)button.disabled=repeated&&!changed;const label=$('#save-state');if(label)label.textContent=!r?'开始第一次检查':repeated?(changed?'今天已有记录，保存后更新这一天':'今天已经记录过，没有改动'):(changed?'本次修改尚未保存':'保存后记为今天的新一次检查');}
function captureDraft(){const form=$('#record-form');if(!form||!ui.nodeId)return;recordDrafts[ui.nodeId]={expected_version:Number(form.dataset.version||0),author:$('#record-author').value,status:$('#record-status').value,note:$('#record-note').value,documents:$$('.record-doc',form).map(row=>({template_id:row.dataset.template,status:$('.doc-status',row).value,note:$('.doc-note',row).value}))};syncSaveState();}
function openWorkNode(id){
  if(id===ui.nodeId&&ui.mode==='work')return;
  if(ui.dirty){pendingNode=id;showModal('保存后继续检查',`<div class="modal-body"><p>当前节点有尚未保存的内容。可以保存本次检查后继续，也可以放弃这次修改。</p></div>`,button('close-modal','继续编辑',null)+button('discard-and-go','放弃修改',null)+button('save-and-go','保存并继续','save','primary'));return;}
  ui.nodeId=id;ui.mode='work';ui.tab='overview';ui.version=null;ui.dirty=false;render();
}
function renderWorkspace(){
  const f=flow();if(!f)return '<div class="empty"><h3>未找到该流程</h3></div>';
  if(ui.mode==='work'&&!selectedNode())ui.nodeId=orderedNodes(f)[0]?.id||null;
  const workCount=orderedNodes(f).filter(n=>!childrenOf(f,n.id).length||n.templates?.length||n.records?.length).length;
  return `<div class="workspace-titlebar"><div class="workspace-name"><h1>${esc(f.name)}</h1>${f.is_demo?'<span class="tag">示例</span>':''}<span class="workspace-meta">${isTemplate()?'分级模板':`${workCount} 项工作`}</span></div><div class="button-row">${isTemplate()?button('edit-template-meta','模板信息','settings','small-btn quiet'):button('edit-group','项目资料','info','small-btn quiet')}${!isTemplate()?button('export-progress','导出完成情况','download','small-btn'):''}${button('workspace-more','更多','settings','small-btn quiet')}</div></div>
  <div class="modebar"><div class="mode-tabs" role="tablist" aria-label="工作方式"><button class="mode-tab ${ui.mode==='work'?'active':''}" data-action="mode-work" role="tab" aria-selected="${ui.mode==='work'}">${icon('file')}逐项检查</button><button class="mode-tab ${ui.mode==='overview'?'active':''}" data-action="mode-overview" role="tab" aria-selected="${ui.mode==='overview'}">${icon('grid')}全流程</button>${isTemplate()?'':`<button class="mode-tab ${ui.mode==='stats'?'active':''}" data-action="mode-stats" role="tab" aria-selected="${ui.mode==='stats'}">${icon('chart')}完成度统计</button>`}</div><div class="button-row">${button('new-node','添加节点','plus','quiet small-btn')}</div></div>
  ${ui.mode==='stats'?renderStatsView(f):ui.mode==='graph'?renderGraphView(f):ui.mode==='overview'?renderOverviewView(f):renderWorkbench(f)}`;
}
function docRowsOf(n){return (n.templates||[]).map(t=>({t,status:docStatus(n,t)}));}
function nodeHasStatus(f,n,status){if(docRowsOf(n).some(d=>d.status===status))return true;return orderedNodes(f,n.id).some(k=>docRowsOf(k).some(d=>d.status===status));}
function statusCounts(f){const counts={};DOC_STATUSES.concat(['不涉及']).forEach(s=>counts[s]=0);let all=0;activeNodes(f).forEach(n=>docRowsOf(n).forEach(d=>{counts[d.status]=(counts[d.status]||0)+1;all+=1;}));return {counts,all};}
function nodesMaterialStats(nodes){let done=0,total=0;nodes.forEach(n=>docRowsOf(n).forEach(d=>{if(d.status==='不涉及')return;total+=1;if(d.status==='已完成')done+=1;}));return {done,total,pct:total?Math.round(done/total*100):0};}
function ovDots(n){const docs=docRowsOf(n);return docs.slice(0,7).map(d=>`<span class="ov-dot s-${esc(d.status)}" title="${esc(d.t.name)}：${esc(d.status)}"></span>`).join('')+(docs.length>7?`<span class="ov-dot-more">+${docs.length-7}</span>`:'');}
function ovRow(n,index){const docs=docRowsOf(n),done=docs.filter(d=>d.status==='已完成').length,status=nodeStatus(n);return `<li><button class="ov-row" data-action="overview-node" data-id="${esc(n.id)}"><span class="ov-index">${String(index).padStart(2,'0')}</span><span class="ov-row-main"><span class="ov-name">${esc(n.title)}</span><span class="ov-sub">${docs.length?`${done}/${docs.length} 份材料`:'无需材料'}</span></span><span class="ov-dots">${ovDots(n)}</span><span class="ov-pill status-${esc(status)}">${esc(status)}</span></button></li>`;}
function ovTile(n,index){const docs=docRowsOf(n),done=docs.filter(d=>d.status==='已完成').length,status=nodeStatus(n);return `<button class="ov-tile" data-action="overview-node" data-id="${esc(n.id)}"><span class="ov-tile-top"><span class="ov-index">${String(index).padStart(2,'0')}</span><span class="ov-name">${esc(n.title)}</span><span class="ov-pill status-${esc(status)}">${esc(status)}</span></span><span class="ov-tile-meta">${docs.length?`${done}/${docs.length} 份材料`:'无需材料'}</span><span class="ov-dots">${ovDots(n)}</span></button>`;}
function ovStage(f,group,index){
  const st=nodesMaterialStats(group.nodes),title=group.top?group.top.title:'其它',no=group.top?String(index).padStart(2,'0'):'—';
  return `<section class="ov-stage"><header class="ov-stage-head"><div class="ov-stage-title"><span class="ov-stage-no">${no}</span><h3>${esc(title)}</h3><span class="ov-stage-sub">${group.nodes.length} 个过程</span></div><div class="ov-stage-meter"><span class="meter"><i style="width:${st.pct}%"></i></span><b>${st.done}/${st.total}</b></div></header><ul class="ov-rows">${group.nodes.map((n,i)=>ovRow(n,i+1)).join('')}</ul></section>`;
}
function renderOverviewView(f){
  const stats=documentStats(f),all=stats.total+(stats.excluded||0),pct=stats.total?Math.round(stats.counts['已完成']/stats.total*100):0;
  const isWork=n=>docRowsOf(n).length||!childrenOf(f,n.id).length;
  const tops=childrenOf(f,null),stageTops=tops.filter(t=>childrenOf(f,t.id).length);
  const works=activeNodes(f).filter(isWork);
  const head=`<div class="ov-head"><div class="ov-title"><h2>全流程</h2><p>${stageTops.length?`${stageTops.length} 个阶段 · `:''}${works.length} 个过程 · ${all} 份材料</p></div><div class="ov-meter"><span>材料完成 ${stats.counts['已完成']} / ${stats.total}</span><span class="meter"><i style="width:${pct}%"></i></span><b>${pct}%</b></div><div class="button-row">${button('mode-graph','流程图视图','flow','quiet small-btn')}</div></div>`;
  if(!works.length)return `<div class="overview-view">${head}<div class="empty">${icon('grid')}<h3>还没有流程节点</h3><p>点击“添加节点”，建立第一项工作。</p>${button('new-node','添加节点','plus','primary')}</div></div>`;
  if(!stageTops.length)return `<div class="overview-view">${head}<div class="ov-tiles">${works.map((n,i)=>ovTile(n,i+1)).join('')}</div></div>`;
  const groups=stageTops.map(top=>({top,nodes:orderedNodes(f,top.id).filter(isWork)})).filter(g=>g.nodes.length);
  const loose=tops.filter(t=>!childrenOf(f,t.id).length).filter(isWork);
  if(loose.length)groups.push({top:null,nodes:loose});
  return `<div class="overview-view">${head}<div class="ov-grid">${groups.map((g,i)=>ovStage(f,g,i+1)).join('')}</div></div>`;
}
function renderWorkbench(f){const n=selectedNode();return `<div class="workbench"><aside class="process-directory" aria-label="过程目录"><div class="directory-header"><span>过程目录</span><span>${orderedNodes(f).length}</span></div><label class="search directory-search">${icon('search')}<input id="node-search" type="search" placeholder="搜索过程或模板名称" aria-label="搜索过程或模板名称" value="${esc(ui.nodeSearch)}"></label>${directoryFilterHtml(f)}<div class="directory-items" id="directory-items">${renderDirectory(f)}</div></aside><section class="process-page" aria-label="节点办理页面">${n?renderProcessPage(f,n):`<div class="empty">${icon('flow')}<h3>添加第一个流程节点</h3><p>点击“添加节点”，建立项目组自己的流程。</p>${button('new-node','添加节点','plus','primary')}</div>`}</section></div>`;}
const DOC_STATUSES=['已完成','待检查','需修改','进行中','未开始'];
function documentStats(f){
  const counts={};DOC_STATUSES.forEach(status=>counts[status]=0);
  let total=0,excluded=0,nodeCount=0;
  activeNodes(f).forEach(n=>{
    const docs=n.templates||[];
    if(!docs.length)return;
    nodeCount+=1;
    const saved=latest(n)?.documents||[];
    docs.forEach(t=>{
      const status=saved.find(d=>d.template_id===t.id)?.status||'未开始';
      if(status==='不涉及'){excluded+=1;return;}
      counts[status]=(counts[status]||0)+1;total+=1;
    });
  });
  return {counts,total,excluded,nodeCount};
}
function sectionStats(f){
  const rows=[];
  activeNodes(f).forEach(sec=>{
    if(sec.parent_id||!childrenOf(f,sec.id).length)return;
    const nodes=activeNodes(f).filter(n=>n.id===sec.id||isDescendant(f,n.id,sec.id));
    let done=0,total=0;
    nodes.forEach(n=>{
      const saved=latest(n)?.documents||[];
      (n.templates||[]).forEach(t=>{
        const status=saved.find(d=>d.template_id===t.id)?.status||'未开始';
        if(status==='不涉及')return;
        total+=1; if(status==='已完成')done+=1;
      });
    });
    if(total)rows.push({name:sec.title,done,total});
  });
  return rows;
}
function renderStatsView(f){
  const {counts,total,excluded,nodeCount}=documentStats(f);
  const percent=total?Math.round(counts['已完成']/total*100):0;
  if(!total)return `<div class="stats-view"><div class="empty">${icon('chart')}<h3>还没有可以统计的材料</h3><p>先给过程配置文档模板，再记录完成情况，这里会显示材料完成度。</p></div></div>`;
  let offset=0;
  const segments=DOC_STATUSES.filter(status=>counts[status]).map(status=>{
    const value=counts[status]/total*100;
    const circle=`<circle class="donut-seg donut-${status}" cx="21" cy="21" r="15.9155" fill="none" stroke-width="5.4" stroke-dasharray="${value.toFixed(3)} ${(100-value).toFixed(3)}" stroke-dashoffset="${(-offset).toFixed(3)}"/>`;
    offset+=value;
    return circle;
  }).join('');
  const legend=DOC_STATUSES.map(status=>`<div class="stats-row"><span class="stats-dot donut-${status}"></span><span class="stats-label">${status}</span><span class="stats-count">${counts[status]}</span><span class="stats-percent">${total?(counts[status]/total*100).toFixed(0):0}%</span></div>`).join('');
  return `<div class="stats-view">
    <div class="stats-card">
      <div class="stats-chart">
        <svg viewBox="0 0 42 42" role="img" aria-label="材料完成情况饼图">
          <circle class="donut-track" cx="21" cy="21" r="15.9155" fill="none" stroke-width="5.4"/>
          <g transform="rotate(-90 21 21)">${segments}</g>
          <text class="donut-value" x="21" y="20.4">${percent}%</text>
          <text class="donut-caption" x="21" y="26">已完成</text>
        </svg>
      </div>
      <div class="stats-legend">
        <div class="stats-heading"><h3>材料完成情况</h3><p>共 ${total} 份材料，分布在 ${nodeCount} 个过程；${excluded?`${excluded} 份“不涉及”未计入分母。`:'统计的是各份材料的最新状态。'}</p></div>
        <div class="stats-rows">${legend}</div>
        <div class="stats-foot">已完成 ${counts['已完成']} 份 · 待检查 ${counts['待检查']} 份 · 需修改 ${counts['需修改']} 份</div>
      </div>
    </div>
    ${(()=>{const rows=sectionStats(f);if(!rows.length)return '';return `<div class="stats-card stats-stages"><div class="stats-heading"><h3>各阶段完成度</h3><p>按阶段汇总材料完成情况；“不涉及”不计入。</p></div><div class="stage-rows">${rows.map(r=>{const pct=Math.round(r.done/r.total*100);return `<div class="stage-row"><span class="stage-name">${esc(r.name)}</span><span class="stage-bar"><i style="width:${pct}%"></i></span><span class="stage-value">${r.done} / ${r.total}</span><span class="stage-pct">${pct}%</span></div>`;}).join('')}</div></div>`;})()}
  </div>`;
}
function docStatus(n,t){return latest(n)?.documents?.find(d=>d.template_id===t.id)?.status||'未开始';}
function directoryFilterHtml(f){
  const {counts,all}=statusCounts(f),active=ui.statusFilter||'';
  const opts=[['','全部',all],...DOC_STATUSES.map(s=>[s,s,counts[s]||0])];
  if(counts['不涉及'])opts.push(['不涉及','不涉及',counts['不涉及']]);
  return `<div class="directory-filter"><label class="filter-select" title="按完成情况筛选"><select id="status-filter" aria-label="按完成情况筛选">${opts.map(([value,label,count])=>`<option value="${esc(value)}" ${active===value?'selected':''}>${label}（${count} 份）</option>`).join('')}</select></label></div>`;
}
function renderDirectory(f){
  const q=(ui.nodeSearch||'').trim().toLowerCase(),filter=ui.statusFilter||'';
  const nodes=orderedNodes(f).filter(n=>(nodePath(f,n)+' '+(n.templates||[]).map(t=>t.name).join(' ')).toLowerCase().includes(q)&&(!filter||nodeHasStatus(f,n,filter)));
  if(!nodes.length)return `<div class="directory-empty">${filter?'没有符合这个状态的过程':'没有找到对应过程'}</div>`;
  const expanded=new Set(ui.dirExpanded||[]);
  return nodes.map(n=>{
    const kids=childrenOf(f,n.id),status=nodeStatus(n),allDocs=n.templates||[],docs=filter?allDocs.filter(t=>docStatus(n,t)===filter):allDocs,open=expanded.has(n.id);
    const canExpand=docs.length>1,isWork=!kids.length||docs.length||n.records?.length;
    const bits=[];
    if(isWork)bits.push(`<span class="directory-status status-${esc(status)}">${esc(status)}</span>`);
    if(docs.length>1)bits.push(`<span>${docs.length} 份材料</span>`);
    if(!isWork&&kids.length)bits.push(`<span>${kids.length} 个下级节点</span>`);
    const metaBits=[];
    if(n.favorite)metaBits.push('<span class="directory-star" title="已收藏">★</span>');
    if(bits.length)metaBits.push(bits.join('<span class="directory-meta-dot">·</span>'));
    const meta=metaBits.length?`<span class="directory-meta">${metaBits.join('')}</span>`:'';
    const row=`<div class="directory-row ${open?'expanded':''} ${n.id===ui.nodeId?'selected':''}" style="--depth:${q||filter?0:Math.min(nodeDepth(f,n),4)}"><button class="directory-item ${n.id===ui.nodeId?'selected':''} ${kids.length?'directory-parent':''}" data-action="select-node" data-id="${esc(n.id)}" title="${esc(n.title)}"><span class="directory-state status-${esc(status)}">${kids.length?icon('folder'):icon(status==='已完成'?'check':'file')}</span><span class="directory-name">${esc(n.title)}</span>${meta}</button>${canExpand?`<button class="directory-toggle" data-action="toggle-directory" data-id="${esc(n.id)}" aria-expanded="${open}" aria-label="${open?'收起':'展开'}${esc(n.title)}的文档" title="${open?'收起文档':'展开文档'}">${icon('chevron')}</button>`:''}</div>`;
    const docsList=canExpand&&open?`<div class="directory-docs" style="--depth:${Math.min(nodeDepth(f,n),4)}">${docs.map((t,i)=>`<button class="directory-doc" data-action="open-doc" data-id="${esc(n.id)}" data-doc="${esc(t.id)}" title="${esc(t.name)}"><span class="directory-doc-index">${String(i+1).padStart(2,'0')}</span><span class="directory-doc-name">${esc(t.name)}</span><span class="directory-status status-${esc(docStatus(n,t))}">${esc(docStatus(n,t))}</span></button>`).join('')}</div>`:'';
    return row+docsList;
  }).join('');
}
function renderProcessPage(f,n){const all=orderedNodes(f),index=all.findIndex(x=>x.id===n.id),r=latest(n),children=childrenOf(f,n.id);return `<div class="process-heading"><div class="process-heading-text"><div class="process-path">${esc(nodePath(f,n))}</div><div class="process-title-line"><h2>${esc(n.title)}</h2>${!isTemplate()?statusPill(nodeStatus(n)):''}</div><div class="process-dates"><span>${n.planned_date?`计划日期 ${esc(n.planned_date)}`:'计划日期待设置'}</span><span>${r?`最近检查 ${esc(recordDay(r))}`:'尚未记录完成情况'}</span></div>${n.description?`<div class="process-description" title="${esc(n.description)}"><span class="process-description-label">节点说明</span><p>${esc(n.description)}</p></div>`:''}</div><div class="button-row">${!isTemplate()?`<button class="icon-btn star-toggle ${n.favorite?'is-starred':''}" data-action="toggle-favorite" aria-label="${n.favorite?'取消收藏':'收藏此过程'}" aria-pressed="${Boolean(n.favorite)}" title="${n.favorite?'取消收藏':'收藏此过程'}">${icon('star')}</button>`:''}${iconButton('locate-in-graph','在流程图中定位','flow')}${iconButton('edit-node','编辑节点说明与模板','settings')}</div></div>
  <div class="process-tabs"><button class="${ui.tab==='overview'?'active':''}" data-action="tab-overview">${isTemplate()?'节点配置':'办理与记录'}</button>${!isTemplate()?`<button class="${['history','version'].includes(ui.tab)?'active':''}" data-action="tab-history">历次检查 <span>${n.records?.length||0}</span></button>`:''}</div>
  <div class="process-scroll"><div class="process-columns"><div class="process-primary">${children.length?`<section class="subprocess-summary"><div class="section-label"><span>下级流程 · ${children.length} 个节点</span>${button('enter-subflow','查看流程图','flow','quiet small-btn',`data-id="${esc(n.id)}"`)}</div><div class="child-links">${children.map(c=>`<button data-action="select-node" data-id="${esc(c.id)}"><span>${esc(c.title)}</span>${statusPill(nodeStatus(c))}${icon('chevron')}</button>`).join('')}</div></section>`:''}${ui.tab==='history'?renderHistory(n):ui.tab==='version'?renderVersion(n):isTemplate()?`<section><div class="section-label">节点说明与文档模板</div><p class="prose">${esc(n.description||'节点说明待补充。')}</p>${renderTemplateNames(n.templates)}<div style="margin-top:22px">${button('edit-node','编辑节点','edit','primary')}</div></section>`:renderRecordForm(n)}</div><aside class="process-reference"><div class="reference-title">填写参考 ${icon('book')}</div><section><div class="section-label"><span>节点说明</span>${iconButton('edit-node','编辑节点说明','edit')}</div><div class="prose">${esc(n.description||'节点说明待补充。可以填写工作要求、适用情况和注意事项。')}</div></section><section><div class="section-label"><span>对应文档模板</span><span class="muted small">${n.templates?.length||0} 份</span></div>${renderTemplateNames(n.templates)}</section>${n.parent_id?`<section><div class="section-label">所属流程</div>${button('select-node',esc(f.nodes.find(x=>x.id===n.parent_id)?.title||'上级流程'),'folder','quiet small-btn',`data-id="${esc(n.parent_id)}"`)}</section>`:''}${!isTemplate()&&children.length?'<div class="small muted">需要时可将本流程记录为“不涉及”，并填写原因。</div>':''}</aside></div></div>
  <div class="process-footer"><div class="step-buttons">${button('previous-node','上一个','back','',index<=0?'disabled':'')}<span>${index+1} / ${all.length}</span>${button('next-node','下一个','arrow','',index>=all.length-1?'disabled':'')}</div>${!isTemplate()&&ui.tab==='overview'?`<div class="footer-save"><span id="save-state">${!r?'开始第一次检查':ui.dirty?'本次修改尚未保存':(recordDay(r)===todayKey()?'今天已经记录过，没有改动':'保存后记为今天的新一次检查')}</span><button type="submit" form="record-form" class="btn primary"${r&&recordDay(r)===todayKey()&&!ui.dirty?' disabled':''}>${icon('save')}保存本次检查</button></div>`:''}</div>`;}
function renderRecordForm(n){const r=latest(n),draft=recordDrafts[n.id],values=draft||r||{};return `<form id="record-form" data-version="${draft?.expected_version??r?.version??0}" class="record-form work-record-form"><div class="record-section-title"><h3>本次检查</h3><span>${r&&recordDay(r)===todayKey()?'今天已有记录，保存会更新这一天':`保存后成为第 ${(r?.version||0)+1} 次检查`}</span></div><div id="record-error" class="error-box" role="alert"></div><div class="field-row"><div><label class="form-label" for="record-author">记录人</label><input class="input" id="record-author" name="author" value="${esc(values.author||actor||group()?.name||'')}" maxlength="100" required></div><div><label class="form-label" for="record-status">节点完成情况</label><select class="input" id="record-status" name="status">${options(values.status||'未开始')}</select></div></div><div><label class="form-label" for="record-note">本次情况与修改意见</label><textarea class="input" id="record-note" name="note" rows="4" placeholder="记录检查结果、需要补充的内容，以及下一次需要注意的问题…">${esc(values.note||'')}</textarea></div>${n.templates?.length?'<div class="record-section-title materials-title"><h3>逐份材料检查</h3><span>分别填写每份材料的情况</span></div>':''}${(n.templates||[]).map((t,i)=>{const d=values.documents?.find(d=>d.template_id===t.id);return `<div class="record-doc" data-template="${esc(t.id)}"><div class="document-form-heading"><span class="document-number">${String(i+1).padStart(2,'0')}</span><label class="form-label" for="status-${esc(t.id)}">${esc(t.name)}</label><select class="input doc-status" id="status-${esc(t.id)}" aria-label="${esc(t.name)}的完成情况">${options(d?.status||'未开始')}</select></div><textarea class="input doc-note" aria-label="${esc(t.name)}的情况说明" placeholder="填写这份材料的修改意见或完成说明">${esc(d?.note||'')}</textarea></div>`;}).join('')}</form>`;}
function buildGraph(f){const nodes=[],edges=[],branches=[],sections=[],seen=new Set();const expanded=new Set(ui.expanded||[]);function width(n,depth=0){if(depth>10||!expanded.has(n.id))return 240;const kids=childrenOf(f,n.id);return Math.max(240,kids.reduce((sum,c)=>sum+width(c,depth+1)+60,0)-60);}
  function place(parent,x,y,depth=0){if(depth>10)return;const ns=childrenOf(f,parent);let cursor=x;for(const n of ns){if(seen.has(n.id))continue;seen.add(n.id);const w=width(n);nodes.push({...n,x:cursor,y});if(expanded.has(n.id)&&childrenOf(f,n.id).length){const children=childrenOf(f,n.id);sections.push({id:n.id,title:n.title,x:cursor-15,y:y+184,width:w+30});branches.push({source:n.id,target:children[0].id});place(n.id,cursor,y+235,depth+1);}cursor+=w+60;}const actual=(f.edges||[]).filter(e=>ns.some(n=>n.id===e.source)&&ns.some(n=>n.id===e.target));edges.push(...actual);}
  place(ui.scope||null,20,35);graphModel={nodes,edges,branches,sections};return graphModel;}
function renderGraphView(f){const model=buildGraph(f),scope=f.nodes.find(n=>n.id===ui.scope);return `<div class="flow-workspace"><section class="flow-stage" aria-label="项目流程图"><div class="flow-toolbar"><div class="scope-path"><button data-action="scope-root">主流程</button>${scope?`${icon('chevron')}<button data-action="scope-up">${esc(nodePath(f,scope))}</button>`:''}</div><div class="button-row">${button('mode-overview','全流程','grid','quiet small-btn')}${button('order-nodes','调整顺序','settings','quiet small-btn')}${button('group-nodes','归入下级流程','folder','quiet small-btn')}${button('edges','设置连线','link','quiet small-btn')}</div></div><div id="flow-viewport" class="flow-viewport" aria-label="可平移和缩放的流程图"><div id="world" class="world">${model.sections.map(s=>`<div class="subflow-band" style="left:${s.x}px;top:${s.y}px;width:${s.width}px"><span>${esc(s.title)} · 下级流程</span></div>`).join('')}${renderEdges(model)}<svg class="edge-layer" width="1" height="1" aria-hidden="true">${model.branches.map(e=>{const a=model.nodes.find(n=>n.id===e.source),b=model.nodes.find(n=>n.id===e.target);return a&&b?`<path class="branch-path" d="M ${a.x+120} ${a.y+132} V ${b.y-18} H ${b.x+120} V ${b.y}"/>`:'';}).join('')}</svg>${model.nodes.map(n=>renderNode(n)+`${childrenOf(f,n.id).length?`<button class="node-expand" data-action="expand-node" data-id="${esc(n.id)}" aria-expanded="${ui.expanded.includes(n.id)}" style="left:${n.x}px;top:${n.y+137}px">${icon(ui.expanded.includes(n.id)?'up':'down')}${ui.expanded.includes(n.id)?'收起':'展开'} ${childrenOf(f,n.id).length} 个下级节点</button>`:`<div class="node-date" style="left:${n.x}px;top:${n.y+139}px">${n.planned_date?esc(n.planned_date):''}</div>`}`).join('')}</div>${!model.nodes.length?`<div class="canvas-empty"><h3>添加这个流程的第一个节点</h3>${button('new-node','添加节点','plus','primary')}</div>`:''}</div><div class="canvas-controls">${iconButton('zoom-out','缩小流程图','minus')}<span class="zoom-label" id="zoom-label">${Math.round(ui.zoom*100)}%</span>${iconButton('zoom-in','放大流程图','plus')}<span class="separator"></span>${iconButton('fit','完整显示流程图','fit')}${iconButton('graph-start','回到流程起点','back')}${iconButton('graph-right','向右查看流程','arrow')}</div><div class="canvas-legend">点击节点进入办理页 · 展开查看下级流程</div></section></div>`;}
function favoriteGroups(list){return list.map(g=>({g,nodes:orderedNodes(g).filter(n=>n.favorite)})).filter(x=>x.nodes.length);}
function favoriteRows(list){return list.map(({g,nodes})=>`<section class="favorite-group"><div class="favorite-group-head"><button class="favorite-group-name" data-action="open-group" data-id="${esc(g.id)}" title="打开 ${esc(g.name)}">${icon('flow')}<span>${esc(g.name)}</span>${g.archived?'<span class="tag tag-muted">已归档</span>':''}</button><span class="favorite-group-meta">${nodes.length} 个过程</span></div><div class="favorite-rows">${nodes.map(n=>`<button class="favorite-row" data-action="open-favorite" data-group="${esc(g.id)}" data-id="${esc(n.id)}"><span class="favorite-star">${icon('star')}</span><span class="favorite-main"><strong>${esc(n.title)}</strong>${nodePath(g,n)!==n.title?`<small>${esc(nodePath(g,n))}</small>`:''}</span>${statusPill(nodeStatus(n))}${icon('arrow')}</button>`).join('')}</div></section>`).join('');}
function favoriteSection(name,list,iconName='folder'){if(!list.length)return '';const total=list.reduce((sum,x)=>sum+x.nodes.length,0);return `<section class="folder-section"><div class="folder-heading"><span class="folder-heading-name">${icon(iconName)}<h2>${esc(name)}</h2></span><span class="folder-count">${list.length} 个项目组 · ${total} 个过程</span></div>${favoriteRows(list)}</section>`;}
function renderFavorites(){const live=state.groups.filter(g=>!g.archived),archived=state.groups.filter(g=>g.archived);const folders=(typeof folderList==='function'?folderList():[]);const liveSections=folders.map(f=>favoriteSection(f.name,favoriteGroups(live.filter(g=>(g.folder_id||null)===f.id)))).join('');const unfiled=favoriteSection('未分类',favoriteGroups(live.filter(g=>!g.folder_id)),'grid');const archList=favoriteGroups(archived);const archSection=archList.length?`<section class="folder-section archived-section"><div class="folder-heading"><span class="folder-heading-name">${icon('folder')}<h2>已归档</h2></span><span class="folder-count">${archList.length} 个项目组</span></div>${favoriteRows(archList)}</section>`:'';const count=live.reduce((sum,g)=>sum+orderedNodes(g).filter(n=>n.favorite).length,0)+archList.reduce((sum,x)=>sum+x.nodes.length,0);const body=liveSections+unfiled+archSection;return `<div class="page-scroll"><div class="page"><div class="page-header"><div class="eyebrow">工作空间 / 收藏夹</div></div><h1>收藏的过程</h1><p class="page-description">按文件夹和项目组归类，共 ${count} 个过程。</p>${body?`<div class="favorite-list">${body}</div>`:`<div class="empty">${icon('star')}<h3>把关注的过程留在这里</h3><p>在节点办理页点击星号，即可收藏这个项目的这个过程。</p></div>`}</div></div>`;}
function orderModal(){orderDraft=childrenOf(flow(),ui.scope).map(n=>n.id);showModal('调整办理顺序',`<div class="modal-body"><p class="small muted">此顺序同时用于逐项检查和从左到右的流程图。保存时连接相邻节点。</p><div id="order-list">${orderRows()}</div><div id="order-error" class="error-box" role="alert"></div></div>`,button('close-modal','取消',null)+button('save-order','保存顺序并连接','check','primary'),true);}
function orderRows(){return orderDraft.map((id,i)=>`<div class="order-row"><span class="order-number">${String(i+1).padStart(2,'0')}</span><span>${esc(flow().nodes.find(n=>n.id===id)?.title)}</span>${iconButton('order-up','向前移动','up',`data-id="${esc(id)}" ${i===0?'disabled':''}`)}${iconButton('order-down','向后移动','down',`data-id="${esc(id)}" ${i===orderDraft.length-1?'disabled':''}`)}</div>`).join('')||'<p class="muted small">当前层级还没有节点。</p>';}
async function saveOrder(ids=orderDraft,parent=ui.scope){if(isTemplate()){const t=clone(flow()),set=new Set(ids);t.nodes=t.nodes.map(n=>set.has(n.id)?{...n,order_index:ids.indexOf(n.id),x:60+ids.indexOf(n.id)*300,y:70}:n);t.edges=t.edges.filter(e=>!set.has(e.source)||!set.has(e.target));ids.slice(1).forEach((id,i)=>t.edges.push({id:uid(),source:ids[i],target:id}));await mutate(`/templates/${encodeURIComponent(t.id)}`,t,'PUT');}else await mutate(`/groups/${encodeURIComponent(ui.groupId)}/organize`,{parent_id:parent||null,node_ids:ids});}
function groupNodesModal(){const nodes=childrenOf(flow(),ui.scope);showModal('归入下级流程',`<form id="group-nodes-form" class="modal-body"><p class="small muted">选择属于同一事项的节点，用一个上级节点收纳。例如，将供方评价、采购检查和外包评审收纳到“采购与外包”。</p><div><label class="form-label" for="parent-title">上级流程名称</label><input class="input" id="parent-title" name="title" required placeholder="例如：采购与外包" maxlength="200"></div><div class="node-choice-list">${nodes.map(n=>`<label><input type="checkbox" name="node_id" value="${esc(n.id)}"><span>${esc(n.title)}</span></label>`).join('')}</div><div id="grouping-error" class="error-box" role="alert"></div></form>`,button('close-modal','取消',null)+'<button class="btn primary" type="submit" form="group-nodes-form">创建下级流程</button>',true);}
async function downloadProgress(){if(ui.dirty)throw new Error('请先保存当前节点的修改，再导出完成情况。');const response=await fetch(`/api/groups/${encodeURIComponent(ui.groupId)}/export`);if(!response.ok){let data=await response.json();throw new Error(data.error||'导出未完成，请重试。');}const blob=await response.blob(),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`${group().name}-完成情况-${new Date().toISOString().slice(0,10)}.xlsx`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),10000);toast('已导出所有节点的最新情况');}
document.addEventListener('click',async event=>{const target=event.target.closest('[data-action]');if(!target||target.disabled)return;const action=target.dataset.action;try{
  if(action==='favorites')return navigate('favorites');
  if(action==='open-favorite'){if(!mayLeave())return;ui.groupId=target.dataset.group;ui.templateId=null;ui.view='group';ui.nodeId=target.dataset.id;ui.mode='work';ui.tab='overview';ui.dirty=false;render();return;}
  if(action==='mode-work'){if(!mayLeave())return;ui.mode='work';ui.tab='overview';ui.nodeId=ui.nodeId||orderedNodes(flow())[0]?.id;render();return;}
  if(action==='mode-graph'){if(!mayLeave())return;ui.mode='graph';render();return;}
  if(action==='mode-stats'){if(!mayLeave())return;ui.mode='stats';render();return;}
  if(action==='mode-overview'){if(!mayLeave())return;ui.mode='overview';render();return;}
  if(action==='overview-node'){openWorkNode(target.dataset.id);return;}
  if(action==='filter-status'){ui.statusFilter=target.dataset.status||'';render();return;}
  if(action==='toggle-favorite'){const id=ui.nodeId;await updateNode(id,{favorite:!selectedNode().favorite});const n=selectedNode();target.classList.toggle('is-starred',n.favorite);target.setAttribute('aria-pressed',String(n.favorite));target.setAttribute('aria-label',n.favorite?'取消收藏':'收藏此过程');target.title=n.favorite?'取消收藏':'收藏此过程';toast(n.favorite?'已加入收藏夹':'已取消收藏');return;}
  if(action==='previous-node'||action==='next-node'){const ns=orderedNodes(flow()),i=ns.findIndex(n=>n.id===ui.nodeId),n=ns[i+(action==='next-node'?1:-1)];if(n)openWorkNode(n.id);return;}
  if(action==='save-and-go'){const form=$('#record-form'),destination=pendingNode;forceCloseModal();if(!form||!form.reportValidity())return;pendingNode=destination;form.requestSubmit();return;}
  if(action==='discard-and-go'){delete recordDrafts[ui.nodeId];ui.dirty=false;const id=pendingNode;pendingNode=null;forceCloseModal();openWorkNode(id);return;}
  if(action==='locate-in-graph'){if(!mayLeave())return;ui.mode='overview';render();const row=document.querySelector(`.ov-row[data-id="${CSS.escape(ui.nodeId||'')}"]`);if(row){row.scrollIntoView({block:'center'});row.classList.add('is-flash');setTimeout(()=>row.classList.remove('is-flash'),1400);}return;}
  if(action==='toggle-directory'){const id=target.dataset.id;ui.dirExpanded=(ui.dirExpanded||[]).includes(id)?ui.dirExpanded.filter(x=>x!==id):[...(ui.dirExpanded||[]),id];render();return;}
  if(action==='open-doc'){const id=target.dataset.id,doc=target.dataset.doc;if(id!==ui.nodeId||ui.mode!=='work'){openWorkNode(id);if($('.modal'))return;}const row=document.querySelector(`.record-doc[data-template="${CSS.escape(doc)}"]`);if(!row)return;row.scrollIntoView({block:'start'});row.querySelector('.doc-status')?.focus({preventScroll:true});return;}
  if(action==='expand-node'){const id=target.dataset.id;ui.expanded=ui.expanded.includes(id)?ui.expanded.filter(x=>x!==id):[...ui.expanded,id];render();return;}
  if(action==='enter-subflow'){if(!mayLeave())return;ui.scope=target.dataset.id;ui.mode='graph';ui.expanded=[];ui.panX=35;ui.panY=35;ui.zoom=1;render();return;}
  if(action==='scope-root'||action==='scope-up'){ui.scope=action==='scope-root'?null:flow().nodes.find(n=>n.id===ui.scope)?.parent_id||null;ui.expanded=[];ui.panX=35;ui.panY=35;render();return;}
  if(action==='graph-start'){ui.panX=35;ui.panY=35;ui.zoom=1;applyTransform();return;}
  if(action==='graph-right'){ui.panX-=300*ui.zoom;applyTransform();return;}
  if(action==='order-nodes'){if(!mayLeave())return;return orderModal();}
  if(action==='order-up'||action==='order-down'){const i=orderDraft.indexOf(target.dataset.id),j=i+(action==='order-up'?-1:1);if(j>=0&&j<orderDraft.length){[orderDraft[i],orderDraft[j]]=[orderDraft[j],orderDraft[i]];$('#order-list').innerHTML=orderRows();$('#modal-root').dataset.dirty='true';}return;}
  if(action==='save-order'){await saveOrder();forceCloseModal();render();toast('顺序和相邻连接已保存');return;}
  if(action==='group-nodes'){if(!mayLeave())return;return groupNodesModal();}
  if(action==='export-progress')return await downloadProgress();
  if(action==='workspace-more'){if(!mayLeave())return;showModal('流程操作',`<div class="modal-body workspace-menu">${!isTemplate()?button('save-as-template','保存为分级模板','copy'):button('edit-template-meta','编辑模板信息','settings')}${button('mode-graph','流程图视图（调整顺序与连线）','flow')}${button('archives','查看已归档节点','archive')}${button('new-node','添加流程节点','plus')}${button('order-nodes','调整当前层级顺序','settings')}</div>`,button('close-modal','关闭',null));return;}
}catch(error){const el=$('#order-error');if(el)el.textContent=error.message;else toast(error.message);}});
document.addEventListener('input',event=>{if(event.target.id==='node-search'){ui.nodeSearch=event.target.value;$('#directory-items').innerHTML=renderDirectory(flow());}});
document.addEventListener('submit',async event=>{const form=event.target;if(form.id!=='group-nodes-form')return;event.preventDefault();const submit=document.querySelector(`[form="${form.id}"]`);if(submit)submit.disabled=true;try{
  const data=new FormData(form),ids=data.getAll('node_id');if(!ids.length)throw new Error('请选择至少一个需要归入的节点。');const title=String(data.get('title')).trim();if(!title)throw new Error('请填写上级流程名称。');
  if(isTemplate()){const t=clone(flow()),id=uid(),selected=t.nodes.filter(n=>ids.includes(n.id)),set=new Set(ids),position=Math.min(...selected.map(n=>n.order_index||0));t.nodes.push({id,title,description:'',category:'',templates:[],parent_id:ui.scope||null,order_index:position,x:60+position*300,y:70,planned_date:'',records:[]});let childIndex=0;t.nodes=t.nodes.map(n=>set.has(n.id)?{...n,parent_id:id,order_index:childIndex++}:n);t.edges=t.edges.filter(e=>set.has(e.source)===set.has(e.target));await mutate(`/templates/${encodeURIComponent(t.id)}`,t,'PUT');await saveOrder(childrenOf(flow(),ui.scope).map(n=>n.id));}
  else{await mutate(`/groups/${encodeURIComponent(ui.groupId)}/group-nodes`,{title,parent_id:ui.scope||null,node_ids:ids});}
  forceCloseModal();render();toast('下级流程已创建，原有记录继续保留');
}catch(error){const el=$('#grouping-error');if(el)el.textContent=error.message;else toast(error.message);}finally{if(submit)submit.disabled=false;}});
