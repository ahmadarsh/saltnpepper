#!/usr/bin/env python3
"""Build an arm64-only, relocatable KiCad PCB-export runtime on macOS.

Reads an installed official KiCad application without modifying it. The output
keeps KiCad's Contents/{MacOS,Frameworks,PlugIns,SharedSupport} layout, but omits
GUI editors, model/symbol/footprint libraries, documentation and Python packages.
Only the CLI, required kiface plugins, linked libraries and small resources are
included. A manifest records every source binary and its SHA-256. This runtime
supports native board SVG and XAO export, not the full KiCad application.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent.parent
DEFAULT_SOURCE=Path('/Applications/KiCad/KiCad.app')
DEFAULT_OUTPUT=ROOT/'desktop'/'kicad-runtime'
SYSTEM_PREFIXES=('/System/Library/','/usr/lib/')


def command(args,**kwargs):
    return subprocess.run([str(a) for a in args],check=True,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**kwargs).stdout


def dependencies(binary):
    lines=command(['/usr/bin/otool','-arch','arm64','-L',binary]).splitlines()[1:]
    return [line.strip().split(' (compatibility version',1)[0] for line in lines if line.startswith('\t')]


def build(source=DEFAULT_SOURCE,output=DEFAULT_OUTPUT):
    if sys.platform!='darwin':raise RuntimeError('Build this runtime on macOS with Apple developer tools installed.')
    source=Path(source).resolve();contents=source/'Contents';output=Path(output).resolve()
    if not (contents/'MacOS'/'kicad-cli').is_file():raise ValueError('Source must be an installed KiCad.app containing kicad-cli.')
    if output==source or output in source.parents or source in output.parents:raise ValueError('Output must be separate from the installed KiCad application.')
    if output.exists():shutil.rmtree(output)
    target=output/'Contents';target.mkdir(parents=True)
    frameworks=contents/'Frameworks'
    # KiCad CLI initializes both PCB and schematic kifaces even for PCB-only
    # exports. The schematic plugin is therefore a required runtime component.
    queue=[contents/'MacOS'/'kicad-cli',contents/'PlugIns'/'_pcbnew.kiface',contents/'PlugIns'/'_eeschema.kiface']
    queued=set(queue);copied={};manifest=[]
    def resolve(dep,loader):
        if dep.startswith(SYSTEM_PREFIXES):return None
        if dep.startswith('@rpath/'):
            tail=dep[len('@rpath/'):]
            candidates=[frameworks/tail,frameworks/'Python.framework'/tail]
        elif dep.startswith('@loader_path/'):
            candidates=[loader.parent/dep[len('@loader_path/'):]]
        elif dep.startswith('@executable_path/'):
            candidates=[contents/'MacOS'/dep[len('@executable_path/'):]]
        else:candidates=[Path(dep)]
        result=next((p for p in candidates if p.is_file()),None)
        if result is None:raise RuntimeError(f'Cannot resolve dependency {dep} from {loader}')
        if not result.resolve().is_relative_to(contents):raise RuntimeError(f'External non-system dependency: {dep}')
        return result
    while queue:
        original=queue.pop(0);relative=original.relative_to(contents)
        destination=target/relative;destination.parent.mkdir(parents=True,exist_ok=True)
        canonical=original.resolve()
        if canonical in copied:
            destination.symlink_to(os.path.relpath(copied[canonical],destination.parent))
            continue
        arches=command(['/usr/bin/lipo','-archs',original]).strip().split()
        if 'arm64' not in arches:raise RuntimeError(f'No arm64 architecture in {original}')
        if len(arches)>1:command(['/usr/bin/lipo',original,'-thin','arm64','-output',destination])
        else:shutil.copy2(original,destination)
        destination.chmod(original.stat().st_mode & 0o777)
        copied[canonical]=destination
        binary_deps=[]
        for dep in dependencies(original):
            resolved=resolve(dep,original)
            if resolved is None:continue
            # dylibs' install IDs appear in otool -L too. Do not follow self IDs.
            if resolved.resolve()==canonical:continue
            binary_deps.append(dep)
            if resolved not in queued:queued.add(resolved);queue.append(resolved)
        # Modified universal binaries need a fresh local signature. The parent
        # application is signed again by the app packaging workflow.
        command(['/usr/bin/codesign','--force','--sign','-',destination])
        manifest.append(dict(file=str(relative),source=str(original),source_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),dependencies=binary_deps))
    # Small resources are sufficient for PCB parsing, stroke text and exports.
    for name in ['resources','schemas']:
        src=contents/'SharedSupport'/name
        if src.exists():shutil.copytree(src,target/'SharedSupport'/name,symlinks=True)
    license_source=contents/'Resources'/'Licenses'
    if license_source.exists():shutil.copytree(license_source,target/'Resources'/'Licenses',symlinks=False)
    for name in ['LICENSE','COPYING','COPYING.txt']:
        path=contents/name
        if path.is_file():shutil.copy2(path,target/'Resources'/'Licenses'/name)
    (target/'Resources'/'Licenses').mkdir(parents=True,exist_ok=True)
    if (ROOT/'licenses'/'GPL-3.0.txt').exists():shutil.copy2(ROOT/'licenses'/'GPL-3.0.txt',target/'Resources'/'Licenses'/'KiCad-GPL-3.0.txt')
    info=plistlib.loads((contents/'Info.plist').read_bytes())
    info.update(CFBundleExecutable='kicad-cli',CFBundleName='KiCad CLI',CFBundleIdentifier='org.kicad.kicad-cli.runtime')
    (target/'Info.plist').write_bytes(plistlib.dumps(info))
    env=dict(os.environ,PATH='/usr/bin:/bin');env.pop('DYLD_LIBRARY_PATH',None);env.pop('DYLD_FRAMEWORK_PATH',None)
    # macOS may audit newly signed dylibs on their first execution. Normal warm
    # CLI calls are fast, but a clean build needs a larger validation deadline.
    version=command([target/'MacOS'/'kicad-cli','--version'],env=env,timeout=180).strip()
    result=dict(component='KiCad PCB export runtime',version=version,architecture='arm64',source=str(source),
                included=['kicad-cli','PCB and schematic plugins (CLI initializes both)','transitive native linked libraries','small resources and schemas','upstream license texts'],
                excluded=['3D model library','footprint and symbol libraries','GUI editor applications','help and translations','Python site-packages'],binaries=manifest)
    (output/'manifest.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(output=str(output),version=version,binaries=len(manifest),bytes=sum(p.stat().st_size for p in output.rglob('*') if p.is_file() and not p.is_symlink())),indent=2),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=DEFAULT_SOURCE)
    parser.add_argument('--output',type=Path,default=DEFAULT_OUTPUT)
    args=parser.parse_args();build(args.source,args.output)
