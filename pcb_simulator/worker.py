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
        from pcb_simulator.engine import inspect_model,run_simulation
        if request['operation']=='inspect':
            result=inspect_model(Path(request['source']),output,emit)
        elif request['operation']=='simulate':
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
