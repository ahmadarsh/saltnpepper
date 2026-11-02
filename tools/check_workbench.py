"""End-to-end GUI checks and README captures against a disposable app data directory.

Requires Chrome and the optional websockets and Pillow packages. Never uses user data.
Usage: python tools/check_workbench.py [path/to/frozen/backend]
"""
import asyncio
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pcb_simulator.viewer import check_browser
import websockets

async def check(port, urls):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list') as r:
        tab = next(t for t in json.load(r) if t['type'] == 'page')
    async with websockets.connect(tab['webSocketDebuggerUrl'], max_size=30_000_000) as ws:
        number = 0
        errors = []
        async def call(method, params=None):
            nonlocal number
            number += 1
            await ws.send(json.dumps(dict(id=number, method=method, params=params or {})))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get('method') == 'Runtime.exceptionThrown': errors.append(msg['params'])
                if msg.get('id') == number:
                    if 'error' in msg: raise RuntimeError(msg['error'])
                    return msg.get('result', {})
        async def js(source):
            r = await call('Runtime.evaluate', dict(expression=source, returnByValue=True, awaitPromise=True))
            if 'exceptionDetails' in r: raise RuntimeError(r['exceptionDetails'])
            return r.get('result', {}).get('value')
        async def until(source):
            for _ in range(600):
                if await js(source): return
                await asyncio.sleep(.2)
            raise AssertionError(source)
        async def capture(name):
            await asyncio.sleep(.2)
            r = await call('Page.captureScreenshot', {'format':'png'})
            images = ROOT / 'docs' / 'images'; images.mkdir(exist_ok=True)
            (images / name).write_bytes(base64.b64decode(r['data']))
        await call('Runtime.enable')
        await call('Page.enable')
        await call('Emulation.setDeviceMetricsOverride', dict(width=1600, height=1000, deviceScaleFactor=1, mobile=False))
        await call('Page.navigate', {'url':urls[0]})
        await until("typeof state!=='undefined' && $('example') && $('accentColour')")
        await js("$('skipWelcome').click();window.confirm=()=>{throw Error('Native confirm must not be used')};$('example').click()")
        await until("state.model?.status==='ready' && state.inventory.length===3")
        await js("$('examplePorts').click()")
        assert await js('state.input.size===1 && state.output.size===1')
        for colour in ['mint','cyan','violet','rose','amber']:
            await js("$('accentColour').value="+json.dumps(colour)+";$('accentColour').dispatchEvent(new Event('change'))")
            assert await js("document.documentElement.dataset.accent==="+json.dumps(colour))
        await js("$('accentColour').value='violet';$('accentColour').dispatchEvent(new Event('change'));document.querySelector('[data-theme-choice=pepper]').click()")
        await js("$('runForm').elements.analysis_mode.value='electrical';$('runForm').elements.current_A.value=.1;$('runForm').elements.ambient_C.value=20;$('runForm').elements.mesh_size_mm.value=.8;$('runForm').elements.refine.checked=false")
        await capture('pepper-workbench.png')
        # Cancel and Escape preserve geometry. The test has disabled native confirm.
        await js("document.querySelector('[data-delete-model]').click()")
        assert await js("$('deleteDialog').open && document.activeElement.id==='cancelDelete'")
        await js("$('cancelDelete').click()")
        await asyncio.sleep(.1)
        assert await js('state.models.length===1')
        await js("document.querySelector('[data-delete-model]').click()")
        await call('Input.dispatchKeyEvent', {'type':'keyDown','key':'Escape','code':'Escape','windowsVirtualKeyCode':27})
        await call('Input.dispatchKeyEvent', {'type':'keyUp','key':'Escape','code':'Escape','windowsVirtualKeyCode':27})
        await until("!$('deleteDialog').open")
        assert await js('state.models.length===1')
        await js("$('runForm').elements.analysis_mode.value='electrical';$('runForm').elements.current_A.value=.1;$('runForm').elements.ambient_C.value=20;$('runForm').elements.mesh_size_mm.value=.8;$('runForm').elements.refine.checked=false;$('runForm').requestSubmit()")
        await until("state.runs.some(r=>r.status==='succeeded')")
        run = await js("state.runs.find(r=>r.status==='succeeded').id")
        await js("location.hash='#setup';document.querySelector('[data-delete-model]').click();$('confirmDelete').click()")
        await until('state.models.length===0')
        assert await js('state.runs.length===1')
        result = await js("fetch('/api/runs/"+run+"').then(r=>r.json())")
        assert abs(result['report']['resistance_ohm'] - .01/(58e6*1e-6)) < 1e-9
        # Results remain readable after removing their source model.
        await call('Page.navigate', {'url': urls[0]+'artifacts/'+run+'/viewer.html'})
        await until("document.body?.dataset.viewerStatus==='ready'")
        await js("if(PCB3D.theme!=='salt')$('themeToggle').click()")
        await capture('salt-results.png')
        if await js("!!$('palette')"):
            await js("$('palette').value='neon';$('palette').dispatchEvent(new Event('change'))")
        # Capture real rendered field frames; only encode them into GIF, without altering content.
        from PIL import Image
        frames = []
        for i in range(18):
            await call('Input.dispatchMouseEvent', {'type':'mouseMoved','x':850,'y':500})
            await call('Input.dispatchMouseEvent', {'type':'mousePressed','x':850,'y':500,'button':'left','clickCount':1})
            await call('Input.dispatchMouseEvent', {'type':'mouseMoved','x':875,'y':504,'button':'left','buttons':1})
            await call('Input.dispatchMouseEvent', {'type':'mouseReleased','x':875,'y':504,'button':'left','clickCount':1})
            await asyncio.sleep(.06)
            data = await call('Page.captureScreenshot', {'format':'png'})
            frames.append(Image.open(io.BytesIO(base64.b64decode(data['data']))).convert('RGB'))
        frames[0].save(ROOT/'docs/images/simulation.gif',save_all=True,append_images=frames[1:],duration=130,loop=0,optimize=True)
        await call('Page.navigate', {'url':urls[0]+'#runs'})
        await until("typeof state!=='undefined' && state.runs.length===1")
        await js("window.confirm=()=>{throw Error('Native confirm must not be used')};document.querySelector('[data-delete-run]').click();$('cancelDelete').click()")
        assert await js('state.runs.length===1')
        await js("document.querySelector('[data-delete-run]').click();$('confirmDelete').click()")
        await until('state.runs.length===0')
        assert not errors, errors
        return {'status':'PASS','checks':['example import and ports','all five accents','cancel and Escape preserve files','delete model through GUI','completed results survive model removal','real field animation','cancel run deletion','delete run through GUI'],'captures':'docs/images'}

def main():
    with tempfile.TemporaryDirectory(prefix='sp-ui-test-') as d:
        data=Path(d)/'data'
        command=[sys.argv[1]] if len(sys.argv)>1 else [sys.executable,str(ROOT/'pcb_simulator/server.py')]
        with (Path(d)/'server.log').open('wb') as log:
            process=subprocess.Popen(command+['--no-browser','--port','0','--data-dir',str(data)],stdout=log,stderr=log)
            try:
                for _ in range(900):
                    if (data/'server.json').exists(): break
                    if process.poll() is not None: raise RuntimeError('Server exited')
                    time.sleep(.1)
                control=json.loads((data/'server.json').read_text())
                base=f'http://127.0.0.1:{control["port"]}/'
                print(json.dumps(check_browser.main([base], runner=check),indent=2))
            finally:
                if process.poll() is None:
                    try:
                        req=urllib.request.Request(base+'api/shutdown',data=json.dumps({'token':control['token']}).encode())
                        urllib.request.urlopen(req,timeout=10).close()
                        process.wait(timeout=15)
                    except Exception: process.terminate();process.wait(timeout=10)

if __name__=='__main__':main()
