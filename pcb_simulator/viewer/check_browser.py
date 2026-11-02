"""Validate standalone result pages with isolated, hidden local Chrome.

Usage: python -m pcb_simulator.viewer.check_browser path/to/viewer.html [...]
Requires websockets only for this optional browser QA command.
"""
import asyncio
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

import websockets


async def check(port, paths):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list") as response:
        tab = next(tab for tab in json.load(response) if tab["type"] == "page")
    async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=20_000_000) as ws:
        number = 0
        errors = []

        async def call(method, params=None):
            nonlocal number
            number += 1
            await ws.send(json.dumps(dict(id=number, method=method, params=params or {})))
            while True:
                message = json.loads(await ws.recv())
                if message.get("method") == "Runtime.exceptionThrown":
                    errors.append(message["params"]["exceptionDetails"])
                if message.get("id") == number:
                    if "error" in message:
                        raise RuntimeError(message["error"])
                    return message.get("result", {})

        async def evaluate(source):
            result = await call("Runtime.evaluate", dict(expression=source, returnByValue=True, awaitPromise=True))
            if "exceptionDetails" in result:
                raise RuntimeError(result["exceptionDetails"])
            return result.get("result", {}).get("value")

        await call("Runtime.enable")
        await call("Page.enable")
        reports = []
        for path in paths:
            await call("Emulation.setDeviceMetricsOverride", dict(width=1400, height=950, deviceScaleFactor=1, mobile=False))
            await call("Page.navigate", dict(url=path.resolve().as_uri()))
            for _ in range(100):
                await asyncio.sleep(.1)
                if await evaluate("document.body && document.body.dataset.viewerStatus==='ready'"):
                    break
            assert await evaluate("document.body.dataset.viewerStatus==='ready'"), errors
            initial = await evaluate("({field:PCB3D.field,bodies:PCB3D.bodies.length,min:+$('minimum').value,max:+$('maximum').value,expected:PACK.ranges.ir_drop_mV,thermal:PACK.report.thermal_solved,fields:[...$('field').options].map(o=>o.value),padRows:$('padTable').children.length,expectedPads:(PACK.report.per_pad||[]).length})")
            assert initial["field"] == "ir_drop_mV" and initial["bodies"] > 0, initial
            assert [initial["min"], initial["max"]] == initial["expected"], initial
            assert initial["padRows"] == initial["expectedPads"], initial
            assert ("temperature_C" in initial["fields"]) == initial["thermal"], initial
            assert await evaluate("PCB3D.theme==='salt'&&$('themeToggle').getAttribute('aria-pressed')==='false'")
            original_scale = await evaluate("[$('field').value,$('minimum').value,$('maximum').value]")
            await evaluate("$('themeToggle').click();new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
            assert await evaluate("PCB3D.theme==='pepper'&&localStorage.getItem('salt-pepper-theme')==='pepper'&&$('themeToggle').getAttribute('aria-pressed')==='true'")
            assert await evaluate("[$('field').value,$('minimum').value,$('maximum').value]") == original_scale
            clear = await evaluate("Array.from(gl.getParameter(gl.COLOR_CLEAR_VALUE))")
            assert abs(clear[0]) < .001, clear
            # A message from an unverified window must not change the theme.
            await evaluate("window.dispatchEvent(new MessageEvent('message',{data:{type:'salt-pepper-theme',theme:'salt'},origin:'https://untrusted.example'}))")
            assert await evaluate("PCB3D.theme==='pepper'")
            await evaluate("$('themeToggle').click();new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
            assert await evaluate("PCB3D.theme==='salt'&&localStorage.getItem('salt-pepper-theme')==='salt'")
            clear = await evaluate("Array.from(gl.getParameter(gl.COLOR_CLEAR_VALUE))")
            assert abs(clear[0] - 1) < .001, clear
            before = await evaluate("$('scene').toDataURL()")
            await evaluate("$('palette').value='neon';$('palette').dispatchEvent(new Event('change'));new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
            assert await evaluate("$('scene').toDataURL()") != before
            assert await evaluate("localStorage.getItem('salt-pepper-palette')==='neon'")
            for colourmap in ['heat', 'coolwarm', 'mono', 'rainbow']:
                await evaluate("$('palette').value="+json.dumps(colourmap)+";$('palette').dispatchEvent(new Event('change'));new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
                assert await evaluate("gl.getError()===0")
            await evaluate("$('field').value='copper';$('field').dispatchEvent(new Event('change'));new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
            before = await evaluate("$('scene').toDataURL()")
            await evaluate("$('copperColor').value='#00ffcc';$('copperColor').dispatchEvent(new Event('input'));new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
            assert await evaluate("$('scene').toDataURL()") != before
            await evaluate("$('copperColor').value='#d18a4b';$('copperColor').dispatchEvent(new Event('input'))")
            for field in initial["fields"]:
                await evaluate("$('field').value=" + json.dumps(field) + ";$('field').dispatchEvent(new Event('change'))")
                if field != "copper":
                    assert await evaluate("+$('maximum').value>+$('minimum').value")
                if field == "temperature_C":
                    assert await evaluate("+$('minimum').value===PACK.report.room_temperature_C&&+$('maximum').value===PACK.report.limit_temperature_C")
            await evaluate("$('top').click();$('body').value=1;$('body').dispatchEvent(new Event('input'));$('explode').value=2;$('explode').dispatchEvent(new Event('input'));$('reset').click()")
            await call("Emulation.setDeviceMetricsOverride", dict(width=390, height=844, deviceScaleFactor=1, mobile=True))
            await asyncio.sleep(.1)
            assert await evaluate("$('scene').width>0&&$('scene').height>0&&gl.getError()===0")
            reports.append(dict(path=str(path), status="PASS", themes="Salt/Pepper, persisted, accessible, field scale preserved", **initial))
        assert not errors, errors
        return reports


def main(paths, runner=check):
    candidates = [os.environ.get("CHROME_PATH"),
                  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                  shutil.which("google-chrome"), shutil.which("chromium")]
    chrome = next((Path(p) for p in candidates if p and Path(p).is_file()), None)
    if chrome is None:
        raise RuntimeError("Chrome is not installed. Set CHROME_PATH to its executable.")
    with tempfile.TemporaryDirectory(prefix="pcb-viewer-qa-") as temporary:
        profile = Path(temporary)
        log = (profile / "chrome.log").open("wb")
        process = subprocess.Popen([str(chrome), "--headless", "--no-first-run", "--no-default-browser-check",
                                    "--disable-extensions", "--disable-background-networking", "--use-angle=swiftshader",
                                    "--enable-unsafe-swiftshader", "--remote-debugging-port=0",
                                    f"--user-data-dir={profile}", "about:blank"],
                                   stdout=log, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            marker = profile / "DevToolsActivePort"
            for _ in range(100):
                if marker.exists():
                    break
                if process.poll() is not None:
                    raise RuntimeError(f"Chrome exited {process.returncode}")
                time.sleep(.1)
            return asyncio.run(runner(int(marker.read_text().splitlines()[0]), paths))
        except Exception:
            log.flush()
            print((profile / "chrome.log").read_text(encoding="utf-8", errors="replace"), file=sys.stderr)
            raise
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            log.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python -m pcb_simulator.viewer.check_browser path/to/viewer.html [...]")
    print(json.dumps(main([Path(arg) for arg in sys.argv[1:]]), indent=2))
