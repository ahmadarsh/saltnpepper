"""One CAD/simulation job per process, controlled by the local server."""
import json
from pathlib import Path
import sys
import time
import traceback

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))

def write(path,value):
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value,indent=2,default=str),encoding='utf-8');temporary.replace(path)

def main():
    request=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    job=Path(request['job_dir']);output=Path(request['output_dir'])
    def emit(stage,message,**extra):
        write(job/'progress.json',dict(stage=stage,message=message,time=time.time(),**extra))
        print(f'[{stage}] {message}',flush=True)
    try:
        if request['operation'].startswith('kicad_'):
            from pcb_simulator import kicad_preview
            op=request['operation']
            if op=='kicad_inspect':result=kicad_preview.inspect_board(request['source'],output,emit)
            elif op=='kicad_net':result=kicad_preview.select_net(request['source'],output,request['net'],emit)
            elif op=='kicad_prepare':
                result=kicad_preview.prepare(request['source'],output,request['net'],request['input_ids'],request['output_ids'],emit)
                if request.get('workbench_dir'):
                    from pcb_simulator.kicad_workbench import promote_to_workbench
                    board=json.loads(Path(request['board_file']).read_text(encoding='utf-8'))
                    promote_to_workbench(output/'copper.xao',Path(request['workbench_dir']),board,request['net'],result['terminals'],emit)
                    result['solver_connected']=True
                    result['message']='Selected copper is ready in the Geometry workbench.'
                    write(output/'handoff.json',result)
            else:raise ValueError('Unknown KiCad job.')
        elif request['operation']=='inspect':
            from pcb_simulator.engine import inspect_model
            result=inspect_model(Path(request['source']),output,emit)
        elif request['operation']=='simulate':
            from pcb_simulator.engine import run_simulation
            inventory=json.loads(Path(request['inventory']).read_text(encoding='utf-8'))
            report=run_simulation(Path(request['source']),inventory,output,request['input_tags'],request['output_tags'],request['parameters'],emit)
            emit('postprocessing','Building the interactive result viewer and downloads.')
            from pcb_simulator.results import build_results
            build_results(output,report,emit)
            result=dict(report_file='report.json',viewer_file='viewer.html')
        else:raise ValueError('Unknown job operation.')
        write(job/'result.json',dict(status='succeeded',result=result))
        emit('complete','Ready.')
    except Exception as exc:
        traceback.print_exc()
        write(job/'result.json',dict(status='failed',error=str(exc)))
        emit('failed',str(exc));return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
