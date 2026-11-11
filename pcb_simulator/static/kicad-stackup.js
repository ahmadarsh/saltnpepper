'use strict';

// A schematic cross-section, with the file's dimensions kept separate from the
// enlarged drawing thickness of thin copper, masks and unmeasured surface films.
function kcStackupCrossSection(details) {
  const layers=details.stackup||[];
  if(!layers.length)return '<p class="muted">No physical stackup is saved in this board.</p>';
  const fmt=value=>value==null?'Unspecified':Number(value).toLocaleString('en-US',{maximumFractionDigits:4});
  const geometry=layers.map(layer=>{
    const kind=String(layer.type||'').toLowerCase(),name=String(layer.name||'');
    const material=kind==='copper'||name.endsWith('.Cu')?'copper':
      kind.includes('mask')||name.endsWith('.Mask')?'mask':
      kind.includes('paste')||name.endsWith('.Paste')?'paste':
      kind.includes('silk')||name.endsWith('.SilkS')?'silk':
      ['core','prepreg','dielectric'].includes(kind)||name.startsWith('dielectric')?'dielectric':'other';
    const physical=layer.thickness_mm!=null;
    return {layer,material,physical,height:physical?Math.min(76,Math.max(20,Math.sqrt(layer.thickness_mm)*60)):20};
  });
  const startY=40,gap=3,totalHeight=geometry.reduce((n,row)=>n+row.height+gap,0)-gap;
  const height=Math.max(340,startY+totalHeight+72),x=58,width=160,labelX=250;
  let y=startY;
  const drawings=geometry.map(({layer,material,physical,height:h})=>{
    const middle=y+h/2,fill={copper:'url(#kcStackupCopper)',dielectric:'url(#kcStackupFibre)',mask:'#1e8b5d',paste:'url(#kcStackupPaste)',silk:'#eff4f2',other:'#6e8396'}[material];
    const border=physical?'#263b37':'var(--muted)';
    const dash=physical?'':' stroke-dasharray="4 3"';
    const description=layer.thickness_mm==null?'Thickness unspecified':`${fmt(layer.thickness_mm)} mm / ${fmt(layer.thickness_mils)} mils`;
    const name=String(layer.display_name||layer.name||'Unnamed layer');
    const output=`<g><title>${esc(name+' · '+(layer.type||'Unspecified type')+' · '+description)}</title>
      <rect x="${x}" y="${y}" width="${width}" height="${h}" rx="1" fill="${fill}" fill-opacity="${physical?1:.5}" stroke="${border}" stroke-width="1"${dash}/>
      ${material==='dielectric'?`<path d="M ${x+4} ${y+3} H ${x+width-4}" stroke="#ffe3a7" stroke-opacity=".6"/>`:''}
      <path d="M ${x+width+3} ${middle} H ${labelX-9}" stroke="var(--muted)" stroke-opacity=".65" fill="none"/>
      <circle cx="${x+width+3}" cy="${middle}" r="1.7" fill="var(--muted)"/>
      <text x="${labelX}" y="${middle-3}" fill="currentColor" font-size="11" font-weight="700">${esc(name)}</text>
      <text x="${labelX}" y="${middle+10}" fill="var(--muted)" font-size="9">${esc(description)}</text>
    </g>`;
    y+=h+gap;return output;
  }).join('');
  const dimension=details.board_thickness_mm==null?'Board thickness unspecified':
    `Board ${fmt(details.board_thickness_mm)} mm / ${fmt(details.board_thickness_mils)} mils`;
  const dimensionLine=details.board_thickness_mm==null?'':`<path d="M 41 ${startY} H 23 V ${startY+totalHeight} H 41 M 18 ${startY+5} L 23 ${startY} L 28 ${startY+5} M 18 ${startY+totalHeight-5} L 23 ${startY+totalHeight} L 28 ${startY+totalHeight-5}" fill="none" stroke="var(--muted)" stroke-width="1"/>`;
  return `<svg class="kc-stackup-cross-section" viewBox="0 0 500 ${height}" role="img" aria-label="Board stackup cross-section, top to bottom" style="display:block;width:100%;max-height:450px;font-family:inherit">
    <title>KiCad board cross-section. Copper is orange, dielectric amber, solder mask green, paste silver and silkscreen white. Thin layers are enlarged; dashed bands have unspecified thickness.</title>
    <defs>
      <linearGradient id="kcStackupCopper" x1="0" y1="0" x2="0" y2="1" gradientUnits="objectBoundingBox"><stop stop-color="#f8bd7a"/><stop offset=".35" stop-color="#c77f3e"/><stop offset=".72" stop-color="#a96227"/><stop offset="1" stop-color="#e8a35f"/></linearGradient>
      <linearGradient id="kcStackupPaste" x1="0" y1="0" x2="0" y2="1" gradientUnits="objectBoundingBox"><stop stop-color="#e2e9ed"/><stop offset="1" stop-color="#83949e"/></linearGradient>
      <pattern id="kcStackupFibre" width="12" height="12" patternUnits="userSpaceOnUse"><rect width="12" height="12" fill="#caa04c"/><path d="M 0 0 L 12 12 M 12 0 L 0 12" stroke="#f6d58d" stroke-width="1" stroke-opacity=".55"/><path d="M 0 6 H 12 M 6 0 V 12" stroke="#947035" stroke-width=".7" stroke-opacity=".45"/></pattern>
    </defs>
    <text x="58" y="20" fill="var(--muted)" font-size="10" font-weight="700">TOP</text>
    ${dimensionLine}${drawings}
    <text x="58" y="${startY+totalHeight+19}" fill="var(--muted)" font-size="10" font-weight="700">BOTTOM</text>
    <text x="58" y="${startY+totalHeight+40}" fill="currentColor" font-size="10">${esc(dimension)}</text>
    <text x="58" y="${startY+totalHeight+57}" fill="var(--muted)" font-size="9">Thin layers enlarged · dashed = thickness unspecified</text>
  </svg>`;
}
