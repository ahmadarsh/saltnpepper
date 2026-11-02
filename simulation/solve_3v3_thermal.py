"""3D copper DC + steady conduction/convection with temperature feedback.

Approximate thermal model: copper only, convection on exposed outward top/bottom
faces; buried interfaces, radiation and terminal/FR4 heat paths are not modeled.
"""
import argparse
import json
import time
from pathlib import Path
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import splu

SIGMA20=58e6
ALPHA=.00393
K_COPPER=400.
AMBIENT=30.
CURRENT=2.
VINPUT=3.3

def save(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')

def factor(matrix):
    return splu(matrix.tocsc(),permc_spec='MMD_AT_PLUS_A',diag_pivot_thresh=0,
                options={'SymmetricMode':True})

class Operators:
    def __init__(self,xyz,tets):
        self.xyz=xyz;self.tets=tets;self.n=len(xyz)
        edges=xyz[tets[:,1:]]-xyz[tets[:,0],None,:]
        det=np.linalg.det(edges)
        if np.any(np.abs(det)<1e-32):raise ValueError('Zero-volume tetrahedra')
        self.volume=np.abs(det)/6
        self.grad=np.zeros((len(tets),4,3))
        self.grad[:,1:,:]=np.linalg.inv(edges).transpose(0,2,1)
        self.grad[:,0,:]=-self.grad[:,1:,:].sum(axis=1)
        self.local=self.volume[:,None,None]*np.einsum('eik,ejk->eij',self.grad,self.grad)
        t=tets.astype(np.int32)
        self.rows=np.repeat(t,4,axis=1).ravel();self.cols=np.tile(t,(1,4)).ravel()
    def matrix(self,coefficient):
        coef=np.asarray(coefficient)
        values=self.local*coef if coef.ndim==0 else self.local*coef[:,None,None]
        return coo_matrix((values.ravel(),(self.rows,self.cols)),shape=(self.n,self.n)).tocsr()
    def heat_load(self,q):
        return np.bincount(self.tets.ravel(),weights=np.repeat(q*self.volume/4,4),minlength=self.n)

def convection_matrix(xyz,triangles):
    p=xyz[triangles]
    area=np.linalg.norm(np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]),axis=1)/2
    values=area[:,None,None]/12*(np.ones((3,3))+np.eye(3))
    matrix=coo_matrix((values.ravel(),(np.repeat(triangles.astype(np.int32),3,axis=1).ravel(),
        np.tile(triangles.astype(np.int32),(1,3)).ravel())),shape=(len(xyz),len(xyz))).tocsr()
    return matrix,area

def electrical(ops,source,sink,temperature,parameters=None):
    p=parameters or {}
    current=float(p.get('current_A',CURRENT)); voltage=float(p.get('voltage_V',VINPUT))
    denominator=1+float(p.get('alpha_per_K',ALPHA))*(temperature[ops.tets].mean(axis=1)-20)
    if np.any(denominator<=0):raise ValueError('Temperature produces nonpositive copper resistivity')
    sigma=float(p.get('conductivity_20_S_m',SIGMA20))/denominator
    matrix=ops.matrix(sigma)
    fixed=np.unique(np.r_[source,sink]);free=np.setdiff1d(np.arange(ops.n),fixed)
    u=np.zeros(ops.n);u[source]=1
    if len(free):
        lu=factor(matrix[free][:,free])
        u[free]=lu.solve(-matrix[free][:,fixed]@u[fixed]);del lu
    reaction=matrix@u
    g=float(reaction[source].sum())
    if not np.isfinite(g) or g<=0:raise ValueError('Invalid terminal conductance')
    drop=current/g
    electric=-drop*np.einsum('ei,eik->ek',u[ops.tets],ops.grad)
    j=sigma[:,None]*electric;q=np.einsum('ei,ei->e',j,j)/sigma
    power=float(np.sum(q*ops.volume))
    checks=dict(relative_current_imbalance=float(abs(reaction[source].sum()+reaction[sink].sum())/g),
        relative_linear_residual=float(np.linalg.norm(reaction[free])/g),
        relative_electrical_power_error=abs(power-current*drop)/max(power,1e-30))
    if max(checks.values())>2e-5:raise ValueError(f'Electrical conservation checks failed: {checks}')
    return dict(resistance_ohm=1/g,terminal_drop_V=drop,total_joule_power_W=power,checks=checks),dict(
        voltage_V=voltage-drop*(1-u),ir_drop_mV=drop*(1-u)*1000,
        current_density_A_m2=j,joule_W_m3=q,node_current_A=reaction*drop,conductivity_S_m=sigma)

def thermal_benchmark():
    # Symmetry of a regular tetrahedron makes all nodal temperatures equal.
    # The integrated balance then gives theta = Q/(h*A) exactly for this FE case.
    xyz=np.array([[0,0,0],[1,0,0],[.5,np.sqrt(3)/2,0],[.5,np.sqrt(3)/6,np.sqrt(2/3)]])*.01
    tets=np.array([[0,1,2,3]])
    faces=np.array([[0,1,2],[0,1,3],[0,2,3],[1,2,3]])
    ops=Operators(xyz,tets);H,area=convection_matrix(xyz,faces)
    h=5.;q=np.array([1e4]);load=ops.heat_load(q)
    theta=factor(ops.matrix(K_COPPER)+h*H).solve(load)
    exact=float(q[0]*ops.volume.sum()/(h*area.sum()))
    assert np.allclose(theta,exact,rtol=2e-8)
    assert np.isclose(float(np.sum(h*(H@theta))),float(load.sum()),rtol=2e-8)
    print(json.dumps(dict(status='PASS',benchmark='Symmetric regular tetrahedron, nodal FE theta=Q/(h*A)',
        expected_rise_C=exact,computed_rise_C=theta.tolist()),indent=2))

def solve_folder(folder, parameters, emit=None):
    """Solve a generic, conformal linear-tetrahedron mesh. Units in NPZ are mm."""
    folder=Path(folder);started=time.monotonic();p=parameters
    ambient=float(p.get('ambient_C',30));current=float(p.get('current_A',2))
    voltage=float(p.get('voltage_V',3.3));allowable=float(p.get('allowable_rise_C',45))
    thermal=p.get('analysis_mode','electrothermal')=='electrothermal'
    h=float(p.get('convection_h_W_m2K',5));k=float(p.get('thermal_k_W_mK',400))
    with np.load(folder/'solver_mesh.npz') as archive:
        data={name:archive[name] for name in archive.files}
    xyz=data['nodes_mm']*.001;tets=data['tetrahedra']
    source=data['input_nodes'];sink=data['output_nodes'];active=np.unique(tets)
    if not len(source) or not len(sink):raise ValueError('Both electrodes require meshed nodes')
    if np.intersect1d(source,sink).size:raise ValueError('Input and output electrodes share mesh nodes; select disjoint pads/faces')
    rows=np.repeat(tets[:,0],3);cols=tets[:,1:].ravel()
    graph=coo_matrix((np.ones(len(rows),dtype=np.int8),(rows,cols)),shape=(len(xyz),len(xyz))).tocsr()
    _,labels=connected_components(graph,directed=False)
    src_labels=np.unique(labels[source]);sink_labels=np.unique(labels[sink])
    connectivity=dict(source_component_labels=src_labels.tolist(),output_component_labels=sink_labels.tolist(),
        volume_components=len(np.unique(labels[active])),all_port_nodes_in_volume_mesh=bool(np.isin(np.r_[source,sink],active).all()))
    save(folder/'connectivity.json',connectivity)
    if not connectivity['all_port_nodes_in_volume_mesh'] or len(src_labels)!=1 or len(sink_labels)!=1 or src_labels[0]!=sink_labels[0]:
        raise ValueError('Selected electrodes are disconnected in the 3D copper mesh. Check STEP contact/gaps or choose pads on one connected conductor; no gaps are bridged.')
    old=np.flatnonzero(labels==src_labels[0]);mapping=np.full(len(xyz),-1,dtype=np.int64);mapping[old]=np.arange(len(old))
    selected=np.all(labels[tets]==src_labels[0],axis=1);tt=mapping[tets[selected]]
    boundary=data['convection_triangles'];boundary=mapping[boundary[np.all(mapping[boundary]>=0,axis=1)]]
    source=mapping[source];sink=mapping[sink];ops=Operators(xyz[old],tt)
    temperature=np.full(len(old),ambient);history=[]
    baseline,_=electrical(ops,source,sink,temperature,p)
    if thermal:
        if not len(boundary):raise ValueError('No convection boundary on the selected connected conductor. Choose all exterior cooling or check model Z orientation.')
        H,area=convection_matrix(xyz[old],boundary)
        thermal_factor=factor(ops.matrix(k)+h*H)
        for iteration in range(1,61):
            report,a=electrical(ops,source,sink,temperature,p)
            target=ambient+thermal_factor.solve(ops.heat_load(a['joule_W_m3']))
            delta=float(np.max(np.abs(target-temperature)))
            history.append(dict(iteration=iteration,max_temperature_C=float(target.max()),max_temperature_change_C=delta,
                resistance_ohm=report['resistance_ohm'],power_W=report['total_joule_power_W']))
            if emit:emit('solving',f'Electrothermal iteration {iteration}: peak {target.max():.3f} °C',iteration=iteration)
            if not np.isfinite(target).all() or target.max()>500:raise ValueError('Copper-only electrothermal model exceeds 500 °C or diverges; reduce load or provide more cooling')
            if delta<.0001:
                temperature=target;break
            temperature=.8*target+.2*temperature
        else:raise ValueError('Electrothermal feedback did not converge in 60 iterations')
        # Recompute electrical fields at the reported temperature.
        report,a=electrical(ops,source,sink,temperature,p)
        loss=float(np.sum(h*(H@(temperature-ambient))))
        error=abs(loss-report['total_joule_power_W'])/max(report['total_joule_power_W'],1e-30)
        if error>1e-4:raise ValueError(f'Thermal power imbalance exceeds tolerance: {error:g}')
        report.update(convection_heat_loss_W=loss,relative_thermal_power_error=error,convection_area_mm2=float(area.sum()*1e6))
    else:report,a=electrical(ops,source,sink,temperature,p)
    ports=json.loads((folder/'ports.json').read_text(encoding='utf-8'))['ports'];per_pad=[]
    memberships=np.zeros(len(old),dtype=np.int32)
    for port in ports:
        memberships[mapping[np.asarray(port['node_indices'],dtype=np.int64)]]+=1
    for port in ports:
        ids=mapping[np.asarray(port['node_indices'],dtype=np.int64)]
        per_pad.append(dict(name=port['name'],role=port['role'],tag=port['original_solid'],current_A=float((a['node_current_A'][ids]/memberships[ids]).sum()),
            mean_voltage_V=float(a['voltage_V'][ids].mean()),max_temperature_C=float(temperature[ids].max()) if thermal else None))
    jmag=np.linalg.norm(a['current_density_A_m2'],axis=1)/1e6
    report.update(status='SOLVED_3D_APPROXIMATE_ELECTROTHERMAL' if thermal else 'SOLVED_3D_ELECTRICAL',thermal_solved=thermal,
        input_voltage_V=voltage,output_voltage_V=voltage-report['terminal_drop_V'],total_current_A=current,
        room_temperature_C=ambient,allowable_rise_C=allowable,limit_temperature_C=ambient+allowable,
        maximum_temperature_C=float(temperature.max()) if thermal else None,
        temperature_rise_C=float(temperature.max()-ambient) if thermal else None,
        within_rise_limit_in_this_model=bool(temperature.max()<=ambient+allowable) if thermal else None,
        convection_coefficient_W_m2K=h if thermal else None,baseline_at_ambient=baseline,
        peak_element_current_density_A_mm2=float(jmag.max()),peak_element_joule_density_W_mm3=float(a['joule_W_m3'].max()/1e9),
        local_potential_overshoot_V=float(max(a['voltage_V'].max()-voltage,voltage-report['terminal_drop_V']-a['voltage_V'].min(),0)),
        solved_nodes=len(old),tetrahedra=len(tt),excluded_disconnected_tetrahedra=int((~selected).sum()),
        connectivity=connectivity,per_pad=per_pad,iterations=history,elapsed_seconds=round(time.monotonic()-started,2),
        assumptions=dict(copper_conductivity_at_20C_S_m=p.get('conductivity_20_S_m',SIGMA20),
            resistivity_temperature_coefficient_per_K=p.get('alpha_per_K',ALPHA),copper_thermal_conductivity_W_mK=k,
            thermal_model=('Copper-only conduction with assumed convection on '+p.get('cooling_mode','outer_faces')+'. No FR4, radiation, solder mask or terminal heat sinking.') if thermal else 'Temperature is not solved. Conductivity is evaluated at the specified ambient temperature.',
            electrical_ports='Common equipotential input and output electrodes; specified current is TOTAL. Current sign is positive into copper. Reactions at shared same-role pad nodes are split equally for per-pad accounting.',
            peak_note='Sharp-corner current/heating maxima may be mesh-dependent.',
            disconnected_copper='Only the connected component containing every selected electrode is solved. Other components are excluded.'))
    fields=dict(node_tags=data['node_tags'][old],nodes_mm=data['nodes_mm'][old],tetrahedra=tt,
        tetrahedron_tags=data['tetrahedron_tags'][selected],voltage_V=a['voltage_V'],ir_drop_mV=a['ir_drop_mV'],
        current_density_A_m2=a['current_density_A_m2'],current_density_A_mm2=jmag,joule_W_mm3=a['joule_W_m3']/1e9,
        node_current_A=a['node_current_A'],external_triangles=mapping[data['external_triangles'][np.all(mapping[data['external_triangles']]>=0,axis=1)]],
        input_nodes=source,output_nodes=sink)
    if thermal:fields['temperature_C']=temperature
    np.savez_compressed(folder/'fields.npz',**fields)
    save(folder/'report.json',report)
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--directory',type=Path);parser.add_argument('--h',type=float,default=5.)
    parser.add_argument('--summary-only',action='store_true');parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args()
    if args.self_test:thermal_benchmark();return
    if args.directory is None:parser.error('--directory is required')
    folder=args.directory;started=time.monotonic();data=np.load(folder/'solver_mesh.npz')
    tags=data['node_tags'];xyz=data['nodes_mm']*.001;tets=data['tetrahedra'];source=data['input_nodes'];sink=data['output_nodes']
    active_nodes=np.unique(tets)
    rows=np.repeat(tets[:,0],3);cols=tets[:,1:].ravel()
    graph=coo_matrix((np.ones(len(rows),dtype=np.int8),(rows,cols)),shape=(len(xyz),len(xyz))).tocsr()
    _,labels=connected_components(graph,directed=False)
    src_labels=np.unique(labels[source]);sink_labels=np.unique(labels[sink]);active_labels=np.unique(labels[active_nodes])
    connectivity=dict(source_component_labels=src_labels.tolist(),output_component_labels=sink_labels.tolist(),
        volume_components=len(active_labels),all_port_nodes_in_volume_mesh=bool(np.isin(np.r_[source,sink],active_nodes).all()))
    save(folder/'connectivity.json',connectivity)
    if len(src_labels)!=1 or len(sink_labels)!=1 or src_labels[0]!=sink_labels[0]:
        raise ValueError('Selected input/output ports are not in one connected conductive component')
    old=np.flatnonzero(labels==src_labels[0]);mapping=np.full(len(xyz),-1);mapping[old]=np.arange(len(old))
    selected=np.all(labels[tets]==src_labels[0],axis=1);tt=mapping[tets[selected]]
    boundary=data['convection_triangles'];boundary=boundary[np.all(mapping[boundary]>=0,axis=1)]
    boundary=mapping[boundary];source=mapping[source];sink=mapping[sink]
    ops=Operators(xyz[old],tt)
    print(f'Assembling {len(old)} unknowns / {len(tt)} tetrahedra...',flush=True)
    H,area=convection_matrix(xyz[old],boundary)
    thermal_matrix=ops.matrix(K_COPPER)+args.h*H
    thermal_factor=factor(thermal_matrix)
    temperature=np.full(len(old),AMBIENT)
    baseline,baseline_a=electrical(ops,source,sink,temperature)
    history=[];last_r=None
    for iteration in range(1,41):
        report,a=electrical(ops,source,sink,temperature)
        heat=ops.heat_load(a['joule_W_m3'])
        new_temperature=AMBIENT+thermal_factor.solve(heat)
        delta=float(np.max(np.abs(new_temperature-temperature)))
        history.append(dict(iteration=iteration,max_temperature_C=float(new_temperature.max()),
            max_temperature_change_C=delta,resistance_ohm=report['resistance_ohm'],power_W=report['total_joule_power_W']))
        print(json.dumps(history[-1]),flush=True)
        if new_temperature.max()>500:raise ValueError('Approximate copper-only thermal model exceeds its valid temperature range')
        if delta<.0005:
            temperature=new_temperature;break
        temperature=.8*new_temperature+.2*temperature
        last_r=report['resistance_ohm']
    else:raise ValueError('Electrothermal feedback did not converge in 40 iterations')
    convection_loss=float(np.sum(args.h*(H@(temperature-AMBIENT))))
    thermal_error=abs(convection_loss-report['total_joule_power_W'])/report['total_joule_power_W']
    if thermal_error>1e-4:raise ValueError(f'Thermal power imbalance: {thermal_error}')
    ports=json.loads((folder/'ports.json').read_text(encoding='utf-8'))['ports']
    per_pad=[]
    for p in ports:
        ids=mapping[np.asarray(p['node_indices'],dtype=np.int64)]
        per_pad.append(dict(name=p['name'],role=p['role'],current_A=float(a['node_current_A'][ids].sum()),
            mean_voltage_V=float(a['voltage_V'][ids].mean()),max_temperature_C=float(temperature[ids].max())))
    jmag=np.linalg.norm(a['current_density_A_m2'],axis=1)/1e6
    report.update(status='SOLVED_3D_APPROXIMATE_ELECTROTHERMAL',source='volume.msh',
        local_potential_overshoot_V=float(max(a['voltage_V'].max()-VINPUT,VINPUT-report['terminal_drop_V']-a['voltage_V'].min(),0)),
        input_voltage_V=VINPUT,output_voltage_V=VINPUT-report['terminal_drop_V'],total_current_A=CURRENT,
        room_temperature_C=AMBIENT,maximum_temperature_C=float(temperature.max()),
        temperature_rise_C=float(temperature.max()-AMBIENT),allowable_rise_C=45.,limit_temperature_C=75.,
        within_rise_limit_in_this_model=bool(temperature.max()<=75),
        convection_coefficient_W_m2K=args.h,convection_area_mm2=float(area.sum()*1e6),
        convection_heat_loss_W=convection_loss,relative_thermal_power_error=thermal_error,
        baseline_at_30C=baseline,peak_element_current_density_A_mm2=float(jmag.max()),
        peak_element_joule_density_W_mm3=float(a['joule_W_m3'].max()/1e9),
        solved_nodes=len(old),tetrahedra=len(tt),per_pad=per_pad,iterations=history,
        elapsed_seconds=round(time.monotonic()-started,2),
        assumptions=dict(copper_conductivity_at_20C_S_m=SIGMA20,resistivity_temperature_coefficient_per_K=ALPHA,
            copper_thermal_conductivity_W_mK=K_COPPER,thermal_model='Copper-only, convection on exposed outward top/bottom copper surfaces. Buried interfaces adiabatic. No FR4 spreading, radiation, solder mask or terminal heat sinking. Still-air h is an assumed constant, not a CFD prediction.',
            electrical_ports='Selected source pads share a potential and selected output pads are equipotential. Current is TOTAL, not per pad.',
            peak_note='Sharp-corner current/heating maxima may be mesh-dependent.'))
    output=folder/f'h_{args.h:g}';output.mkdir(exist_ok=True)
    save(output/'electrothermal_report.json',report)
    if not args.summary_only:
        np.savez_compressed(output/'fields.npz',node_tags=tags[old],nodes_mm=data['nodes_mm'][old],
            tetrahedra=tt,tetrahedron_tags=data['tetrahedron_tags'][selected],
            voltage_V=a['voltage_V'],ir_drop_mV=a['ir_drop_mV'],temperature_C=temperature,
            current_density_A_m2=a['current_density_A_m2'],joule_W_mm3=a['joule_W_m3']/1e9,
            current_density_A_mm2=jmag,node_current_A=a['node_current_A'],
            external_triangles=mapping[data['external_triangles'][np.all(mapping[data['external_triangles']]>=0,axis=1)]],
            input_nodes=source,output_nodes=sink)
    print(json.dumps({k:report[k] for k in ['status','resistance_ohm','terminal_drop_V','total_joule_power_W',
        'maximum_temperature_C','temperature_rise_C','within_rise_limit_in_this_model','elapsed_seconds']}),flush=True)

if __name__=='__main__':main()
