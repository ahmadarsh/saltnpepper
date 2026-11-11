'use strict';
function kcDetailsTab(details) {
  $('kcSelectionPanel').hidden=details;$('kcDetailsPanel').hidden=!details;
  $('kcSelectionTab').setAttribute('aria-selected',String(!details));$('kcDetailsTab').setAttribute('aria-selected',String(details));
  if(details)kcRenderDetails();
}
function kcRenderDetails() {
  if(!KC.board)return;
  const b=KC.board,d=b.details||{},num=x=>x==null?'Unspecified':Number(x).toLocaleString('en-US',{maximumFractionDigits:4});
  const table=(heads,rows)=>`<div class="kc-details-table-wrap"><table class="kc-details-table"><thead><tr>${heads.map(h=>`<th scope="col">${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map(c=>`<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  const netLabel=name=>{const n=b.nets.find(n=>n.name===name);return n?`<span class="kc-detail-net" style="--net-colour:${n.colour};color:var(--net-colour)"><span class="kc-net-dot"></span>${esc(name)}</span>`:'<span class="muted">No net</span>';};
  const stack=d.stackup||[];
  const rows=stack.flatMap(l=>{
    const base=[esc(l.display_name&&l.display_name!==l.name?l.display_name+' ('+l.name+')':l.name),esc(l.type||'—'),esc(l.material||'—'),num(l.thickness_mm),num(l.thickness_mils),num(l.epsilon_r),num(l.loss_tangent)];
    if((l.sublayers||[]).length<=1)return [base];
    return [base,...l.sublayers.map((s,i)=>[esc('↳ Ply '+(i+1)),esc(l.type||'—'),esc(s.material||'—'),num(s.thickness_mm),num(s.thickness_mils),num(s.epsilon_r),num(s.loss_tangent)])];
  });
  $('kcDetails').innerHTML=`<div class="kc-details-header"><div><h2>${esc(KC.filename||b.filename)}</h2><p>Imported board data · 1 mil = 0.0254 mm · Missing values are marked unspecified.</p></div><span class="prototype-pill">READ FROM KICAD</span></div><div class="kc-details-stats"><div><strong>${b.pads.length}</strong><span>Copper pad entries</span></div><div><strong>${b.nets.length}</strong><span>Nets</span></div><div><strong>${d.copper_layer_count??'—'}</strong><span>Copper layers</span></div><div><strong>${num(d.board_thickness_mm)} mm</strong><span>Board · ${num(d.board_thickness_mils)} mils</span></div></div><section class="kc-details-section"><h3>Complete stackup · top to bottom</h3><p>Finish: ${esc(d.copper_finish||'Unspecified')} · Specified layer total: ${num(d.specified_stackup_thickness_mm)} mm / ${num(d.specified_stackup_thickness_mils)} mils. Cross-section is schematic; thin layers are enlarged for readability.</p>${stack.length?`<div class="kc-stackup-layout">${kcStackupCrossSection(d)}${table(['Layer','Type','Material','Thickness mm','Thickness mils','εr','Loss tangent'],rows)}</div>`:'<p>No explicit stackup is saved in this board. No layer thicknesses were inferred.</p>'}</section><section class="kc-details-section"><h3>Nets · ${b.nets.length}</h3>${table(['Net','Pads','Track segments','Vias','Zones','Colour source'],b.nets.map(n=>[netLabel(n.name),n.pads,n.tracks,n.vias,n.zones,esc(n.colour_source||'Automatic')]))}</section><section class="kc-details-section"><h3>Pads · ${b.pads.length}</h3>${table(['Component','Pad','Net','Layers','Type / shape','X mm','Y mm','Size mm','Size mils'],b.pads.map(p=>[esc(p.reference),esc(p.number),netLabel(p.net),esc(p.layers.join(', ')),esc(p.type+' / '+p.shape),num(p.x_mm),num(p.y_mm),p.size_mm.map(num).join(' × '),p.size_mm.map(v=>num(v/.0254)).join(' × ')]))}</section>`;
}
$('kcSelectionTab').onclick=()=>kcDetailsTab(false);$('kcDetailsTab').onclick=()=>kcDetailsTab(true);
for(const id of ['kcSelectionTab','kcDetailsTab'])$(id).onkeydown=e=>{if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();const details=id==='kcSelectionTab';kcDetailsTab(details);$(details?'kcDetailsTab':'kcSelectionTab').focus();}};
