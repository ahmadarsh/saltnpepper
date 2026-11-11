'use strict';
// Isolated KiCad copper review: the STEP workbench keeps its own camera and buffers.
let kcGeometryViewer = null;

function kcGeometryCreate() {
  const canvas = document.getElementById('kcGeometryCanvas');
  const gl = canvas.getContext('webgl2', { antialias: true, alpha: true });
  if (!gl) throw Error('WebGL 2 is unavailable. Download the XAO to inspect this geometry in CAD.');
  function shader(type, source) {
    const value = gl.createShader(type);
    gl.shaderSource(value, source); gl.compileShader(value);
    if (!gl.getShaderParameter(value, gl.COMPILE_STATUS)) {
      const message = gl.getShaderInfoLog(value); gl.deleteShader(value); throw Error(message);
    }
    return value;
  }
  const program = gl.createProgram();
  const vertex = shader(gl.VERTEX_SHADER, `#version 300 es
    in vec3 pos;
    uniform float scale, aspect, yaw, pitch, depthScale;
    uniform vec2 pan;
    out vec3 viewPos;
    void main() {
      float cy=cos(yaw), sy=sin(yaw), cx=cos(pitch), sx=sin(pitch);
      vec3 p=vec3(cy*pos.x-sy*pos.y, sy*pos.x+cy*pos.y, pos.z);
      p=vec3(p.x, cx*p.y-sx*p.z, sx*p.y+cx*p.z);
      viewPos=p;
      gl_Position=vec4(p.x*scale/aspect+pan.x, p.y*scale+pan.y, -p.z*depthScale, 1.0);
    }`);
  const fragment = shader(gl.FRAGMENT_SHADER, `#version 300 es
    precision highp float;
    in vec3 viewPos;
    uniform vec3 colour;
    uniform bool electrode;
    out vec4 outColour;
    void main() {
      vec3 normal=normalize(cross(dFdx(viewPos),dFdy(viewPos)));
      float diffuse=abs(dot(normal,normalize(vec3(.35,-.45,.82))));
      float light=electrode ? 1.0 : (.55+.45*diffuse);
      outColour=vec4(colour*light,1.0);
    }`);
  gl.attachShader(program, vertex); gl.attachShader(program, fragment); gl.linkProgram(program);
  gl.deleteShader(vertex); gl.deleteShader(fragment);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw Error(gl.getProgramInfoLog(program));
  const uniforms = {};
  for (const name of ['scale','aspect','yaw','pitch','depthScale','pan','colour','electrode']) uniforms[name]=gl.getUniformLocation(program,name);
  const v = { canvas, gl, program, uniforms, bodies:[], yaw:-.35, pitch:.65, zoom:1, pan:[0,0], extent:1, bounds:[-1,-1,-1,1,1,1], drag:null };
  function rotated(x,y,z) {
    const rx=Math.cos(v.yaw)*x-Math.sin(v.yaw)*y;
    const ry=Math.sin(v.yaw)*x+Math.cos(v.yaw)*y;
    return [rx,Math.cos(v.pitch)*ry-Math.sin(v.pitch)*z];
  }
  v.draw = () => {
    const width=Math.max(1,Math.round(canvas.clientWidth*devicePixelRatio));
    const height=Math.max(1,Math.round(canvas.clientHeight*devicePixelRatio));
    if (canvas.width!==width || canvas.height!==height) { canvas.width=width; canvas.height=height; }
    const aspect=width/height;
    let maxX=0,maxY=0;
    for (const x of [v.bounds[0],v.bounds[3]]) for (const y of [v.bounds[1],v.bounds[4]]) for (const z of [v.bounds[2],v.bounds[5]]) {
      const [rx,ry]=rotated(x,y,z); maxX=Math.max(maxX,Math.abs(rx));maxY=Math.max(maxY,Math.abs(ry));
    }
    const scale=.88/Math.max(maxY,maxX/aspect,.0001)*v.zoom;
    gl.viewport(0,0,width,height); gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
    gl.useProgram(program);gl.enable(gl.DEPTH_TEST);gl.depthFunc(gl.LEQUAL);gl.disable(gl.CULL_FACE);
    gl.uniform1f(uniforms.scale,scale);gl.uniform1f(uniforms.aspect,aspect);
    gl.uniform1f(uniforms.yaw,v.yaw);gl.uniform1f(uniforms.pitch,v.pitch);
    gl.uniform1f(uniforms.depthScale,.8/v.extent);gl.uniform2fv(uniforms.pan,v.pan);
    for (const body of v.bodies) {
      const electrode=body.kind==='electrode';
      const colour=electrode ? (body.role==='input'?[1,.045,.12]:[.06,.3,1]) : [.84,.57,.3];
      if (electrode) {gl.enable(gl.POLYGON_OFFSET_FILL);gl.polygonOffset(-2,-2);} else gl.disable(gl.POLYGON_OFFSET_FILL);
      gl.uniform3fv(uniforms.colour,colour);gl.uniform1i(uniforms.electrode,electrode?1:0);
      gl.bindVertexArray(body.vao);gl.drawElements(gl.TRIANGLES,body.count,gl.UNSIGNED_INT,0);
    }
    gl.disable(gl.POLYGON_OFFSET_FILL);gl.bindVertexArray(null);
  };
  canvas.onpointerdown = e => {
    if (![0,1,2].includes(e.button))return;
    e.preventDefault();canvas.setPointerCapture(e.pointerId);
    v.drag={x:e.clientX,y:e.clientY,pan:e.shiftKey||e.button!==0};
  };
  canvas.onpointermove = e => {
    if (!v.drag)return;
    const dx=e.clientX-v.drag.x,dy=e.clientY-v.drag.y;
    if(v.drag.pan){v.pan[0]+=2*dx/Math.max(1,canvas.clientWidth);v.pan[1]-=2*dy/Math.max(1,canvas.clientHeight);}
    else {v.yaw+=dx*.008;v.pitch=Math.max(-Math.PI,Math.min(Math.PI,v.pitch+dy*.008));}
    v.drag.x=e.clientX;v.drag.y=e.clientY;v.draw();
  };
  canvas.onpointerup=canvas.onpointercancel=canvas.onlostpointercapture=()=>{v.drag=null;};
  canvas.oncontextmenu=e=>e.preventDefault();
  canvas.addEventListener('wheel',e=>{e.preventDefault();v.zoom=Math.min(40,Math.max(.1,v.zoom*Math.exp(-e.deltaY*.0015)));v.draw();},{passive:false});
  const observer=new ResizeObserver(()=>requestAnimationFrame(v.draw));observer.observe(canvas);
  const view=(yaw,pitch)=>{v.yaw=yaw;v.pitch=pitch;v.pan=[0,0];v.zoom=1;v.draw();};
  document.getElementById('kcGeometryTop').onclick=()=>view(0,0);
  document.getElementById('kcGeometryBottom').onclick=()=>view(0,Math.PI);
  document.getElementById('kcGeometryIso').onclick=()=>view(-.35,.65);
  document.getElementById('kcGeometryFit').onclick=()=>{v.pan=[0,0];v.zoom=1;v.draw();};
  document.getElementById('kcGeometryClose').onclick=()=>document.getElementById('kcGeometryDialog').close();
  return v;
}

function kcShowGeometry(preview, manifest) {
  const dialog=document.getElementById('kcGeometryDialog');
  const summary=document.getElementById('kcGeometrySummary');
  const decode=(value,Type)=>{
    const raw=atob(value),bytes=new Uint8Array(raw.length);
    for(let i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);
    return new Type(bytes.buffer);
  };
  if (!kcGeometryViewer)kcGeometryViewer=kcGeometryCreate();
  const v=kcGeometryViewer,{gl}=v;
  for(const body of v.bodies){gl.deleteVertexArray(body.vao);gl.deleteBuffer(body.vbo);gl.deleteBuffer(body.ibo);}
  v.bodies=[];
  const bounds=[Infinity,Infinity,Infinity,-Infinity,-Infinity,-Infinity];
  try {
    // Draw copper first, then slightly offset electrodes while retaining occlusion.
    const bodies=[...(preview.bodies||[])].sort((a,b)=>(a.kind==='electrode')-(b.kind==='electrode'));
    for(const body of bodies){
      const vertices=decode(body.vertices_b64,Float32Array),indices=decode(body.triangles_b64,Uint32Array);
      if(!vertices.length||!indices.length)continue;
      if(vertices.length%3||indices.length%3)throw Error('The geometry preview has incomplete triangles.');
      for(let i=0;i<vertices.length;i++){
        if(!Number.isFinite(vertices[i]))throw Error('The geometry preview has invalid coordinates.');
        const axis=i%3;bounds[axis]=Math.min(bounds[axis],vertices[i]);bounds[axis+3]=Math.max(bounds[axis+3],vertices[i]);
      }
      const vao=gl.createVertexArray(),vbo=gl.createBuffer(),ibo=gl.createBuffer();
      gl.bindVertexArray(vao);gl.bindBuffer(gl.ARRAY_BUFFER,vbo);gl.bufferData(gl.ARRAY_BUFFER,vertices,gl.STATIC_DRAW);
      const pos=gl.getAttribLocation(v.program,'pos');gl.enableVertexAttribArray(pos);gl.vertexAttribPointer(pos,3,gl.FLOAT,false,0,0);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,ibo);gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,indices,gl.STATIC_DRAW);
      v.bodies.push({vao,vbo,ibo,count:indices.length,kind:body.kind,role:body.role,name:body.name});
    }
    if(!v.bodies.length)throw Error('No surface triangles were generated for the selected copper.');
    v.bounds=bounds;v.extent=Math.max(.001,Math.hypot(...[0,1,2].map(i=>Math.max(Math.abs(bounds[i]),Math.abs(bounds[i+3])))));
    v.yaw=-.35;v.pitch=.65;v.zoom=1;v.pan=[0,0];
    const terminals=(manifest.terminals||[]).map(t=>`${String(t.role).toUpperCase()}: ${t.label}`).join(' · ');
    summary.textContent=`${manifest.net} · ${manifest.volumes} copper solids · ${terminals}`;
    if(!dialog.open)dialog.showModal();
    requestAnimationFrame(v.draw);
  } catch(error) {
    for(const body of v.bodies){gl.deleteVertexArray(body.vao);gl.deleteBuffer(body.vbo);gl.deleteBuffer(body.ibo);}
    v.bodies=[];throw error;
  }
}
