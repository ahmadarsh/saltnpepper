#!/usr/bin/env python3
"""Bundle an official KiCad 10.0.0 Windows x64 install for PCB export.

Accepts an installed directory or the tree extracted from the official installer
with 7-Zip. Set KICAD_INSTALL_ROOT or pass --source. Native DLLs and the two
required kifaces retain their original paths; editor EXEs, Python packages,
3D models, footprint/symbol libraries and documentation are excluded. Native
SVG/XAO export of the public two-layer example must pass before build succeeds.
This script does not download or modify the original KiCad installation.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT=ROOT/'desktop'/'kicad-runtime'
EXCLUDED_PARTS={'lib','libs','site-packages','__pycache__','python','python3','scripting'}


def installation_root(source=None):
    if source:
        root=Path(source).expanduser().resolve()
        if (root/'kicad-cli.exe').is_file():return root.parent
        if (root/'bin'/'kicad-cli.exe').is_file():return root
        matches=sorted(p.parent.parent for p in root.glob('**/bin/kicad-cli.exe'))
        if len(matches)==1:return matches[0]
        raise ValueError('Expected one KiCad install tree containing bin/kicad-cli.exe.')
    configured=os.environ.get('KICAD_INSTALL_ROOT')
    if configured:return installation_root(configured)
    for variable in ['ProgramFiles','ProgramW6432']:
        if os.environ.get(variable):
            candidate=Path(os.environ[variable])/'KiCad'/'10.0'
            if (candidate/'bin'/'kicad-cli.exe').is_file():return candidate.resolve()
    raise ValueError('Install official KiCad 10.0.0 x64 or set KICAD_INSTALL_ROOT to its extracted install directory.')


def native_command(cli,args,env,cwd):
    started=time.monotonic()
    result=subprocess.run([str(cli),*map(str,args)],cwd=cwd,env=env,capture_output=True,text=True,
                          encoding='utf-8',errors='replace',timeout=180,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    if result.returncode:
        raise RuntimeError(f'Bundled KiCad command failed ({result.returncode}): {args[:3]}\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}')
    return result.stdout.strip(),round(time.monotonic()-started,3)


def bundle_msvc_runtime(output,binary_files,records):
    """Do not silently rely on Visual Studio runtimes installed on CI runners."""
    if sys.platform!='win32':return
    import pefile  # PyInstaller's Windows build dependency.
    required=set()
    for binary in binary_files:
        if binary.suffix.lower()=='.manifest':continue
        image=pefile.PE(str(binary),fast_load=True)
        try:
            image.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT'],pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT']])
            for entry in getattr(image,'DIRECTORY_ENTRY_IMPORT',[])+getattr(image,'DIRECTORY_ENTRY_DELAY_IMPORT',[]):
                name=entry.dll.decode('ascii').lower()
                if re.match(r'^(?:msvcp|vcruntime|concrt|vcomp)140.*\.dll$',name):required.add(name)
        finally:image.close()
    missing={name for name in required if not (output/'bin'/name).is_file()}
    if not missing:return
    roots=[Path(os.environ[name]) for name in ['KICAD_MSVC_REDIST_ROOT','VCToolsRedistDir'] if os.environ.get(name)]
    for name in ['ProgramFiles','ProgramFiles(x86)']:
        if os.environ.get(name):
            vs=Path(os.environ[name])/'Microsoft Visual Studio'
            if vs.exists():roots.extend(vs.glob('*/*/VC/Redist/MSVC'))
    candidates=[]
    for root in roots:
        if (root/'msvcp140.dll').is_file():candidates.append(root)
        candidates.extend(root.glob('**/x64/Microsoft.VC*.CRT'))
        candidates.extend(root.glob('**/x64/Microsoft.VC*.OpenMP'))
    candidates.sort(key=lambda p:tuple(map(int,re.findall(r'\d+',str(p)))),reverse=True)
    chosen=[]
    for family in [{n for n in missing if not n.startswith('vcomp')},{n for n in missing if n.startswith('vcomp')}]:
        if not family:continue
        redist=next((p for p in candidates if all((p/name).is_file() for name in family)),None)
        if redist is None:raise RuntimeError('KiCad requires app-local Microsoft VC++ DLLs: '+', '.join(sorted(missing))+'. Set KICAD_MSVC_REDIST_ROOT to the official Visual Studio x64 redistributable directory.')
        chosen.append(redist)
    # Copy one complete matching CRT set; mixed runtime versions are avoided.
    for path in (path for redist in chosen for path in redist.glob('*.dll')):
        destination=output/'bin'/path.name;shutil.copy2(path,destination)
        relative=destination.relative_to(output).as_posix()
        records[:]=[row for row in records if row['file'].lower()!=relative.lower()]
        records.append(dict(file=relative,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bytes=path.stat().st_size,redistributable='Microsoft Visual C++ x64 CRT'))


def self_test(output,sample):
    if sys.platform!='win32':raise RuntimeError('Native Windows runtime validation must run on Windows.')
    # Missing DLLs should fail the CI command rather than open a modal OS dialog.
    import ctypes
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    cli=output/'bin'/'kicad-cli.exe'
    with tempfile.TemporaryDirectory(prefix='salt-pepper-kicad-runtime-') as temporary:
        folder=Path(temporary);home=folder/'home';home.mkdir()
        env={key:value for key,value in os.environ.items() if not key.upper().startswith('KICAD')}
        systemroot=Path(env.get('SystemRoot',r'C:\Windows'))
        env.update(PATH=os.pathsep.join(map(str,[cli.parent,systemroot/'System32',systemroot])),
                   HOME=str(home),USERPROFILE=str(home),APPDATA=str(home/'AppData'/'Roaming'),
                   LOCALAPPDATA=str(home/'AppData'/'Local'),TEMP=str(folder),TMP=str(folder),
                   KICAD_CONFIG_HOME=str(folder/'config'))
        env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
        version,version_seconds=native_command(cli,['--version'],env,folder)
        if not re.match(r'^10\.0\.0(?:$|\s|[-+])',version):raise RuntimeError(f'Expected official KiCad 10.0.0, found {version!r}.')
        _,svg_seconds=native_command(cli,['pcb','export','svg','--layers','F.Cu,B.Cu','--common-layers','Edge.Cuts','--mode-multi','--page-size-mode','1','--exclude-drawing-sheet','--output',folder/'svg',sample],env,folder)
        files=sorted((folder/'svg').glob('*.svg'))
        if len(files)!=2:raise RuntimeError('Bundled KiCad did not export both top and bottom copper SVGs.')
        for path in files:
            if ET.parse(path).getroot().tag.rsplit('}',1)[-1]!='svg':raise RuntimeError('Invalid native copper SVG.')
        _,xao_seconds=native_command(cli,['pcb','export','xao','--force','--no-board-body','--no-components','--include-pads','--include-tracks','--include-zones','--include-inner-copper','--output',folder/'copper.xao',sample],env,folder)
        xao=ET.parse(folder/'copper.xao').getroot()
        if xao.tag!='XAO' or xao.find('geometry/shape') is None:raise RuntimeError('Bundled KiCad did not produce valid copper XAO.')
        return dict(status='PASS',version=version,sample=sample.name,isolated_path=True,
                    checks=['version','native top and bottom SVG','native copper XAO'],
                    seconds=dict(version=version_seconds,svg=svg_seconds,xao=xao_seconds),
                    xao_bytes=(folder/'copper.xao').stat().st_size)


def build(source=None,output=DEFAULT_OUTPUT,sample=None):
    source=installation_root(source);output=Path(output).expanduser().resolve()
    sample=Path(sample or ROOT/'examples'/'two-layer-demo.kicad_pcb').resolve()
    if not sample.is_file():raise ValueError('The public KiCad smoke-test board is missing.')
    if output==source or output in source.parents or source in output.parents:raise ValueError('Output must be separate from the source KiCad installation.')
    with (source/'bin'/'kicad-cli.exe').open('rb') as executable:
        header=executable.read(64)
        if len(header)!=64 or header[:2]!=b'MZ':raise ValueError('The KiCad CLI is not a Windows PE executable.')
        executable.seek(struct.unpack_from('<I',header,60)[0]);pe_header=executable.read(6)
        if len(pe_header)!=6 or pe_header[:4]!=b'PE\0\0' or struct.unpack_from('<H',pe_header,4)[0]!=0x8664:
            raise ValueError('This release requires the Windows x64 KiCad CLI.')
    # Resolve and validate the two kifaces before replacing any previous output.
    kifaces=[]
    for name in ['_pcbnew.kiface','_eeschema.kiface']:
        matches=list((source/'bin').rglob(name))
        if len(matches)!=1:raise ValueError(f'Expected exactly one {name} in the KiCad bin directory.')
        kifaces.extend(matches)
    if output.exists():shutil.rmtree(output)
    output.mkdir(parents=True)
    binary_files=[source/'bin'/'kicad-cli.exe',*kifaces]
    for path in (source/'bin').rglob('*'):
        relative=path.relative_to(source/'bin')
        if any(part.lower() in EXCLUDED_PARTS or part.lower().startswith('python3.') for part in relative.parts[:-1]):continue
        if path.is_file() and path.suffix.lower() in ['.dll','.manifest']:
            binary_files.append(path)
    records=[]
    for path in sorted(set(binary_files)):
        relative=path.relative_to(source);destination=output/relative
        destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,destination)
        records.append(dict(file=relative.as_posix(),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bytes=path.stat().st_size))
    bundle_msvc_runtime(output,binary_files,records)
    for relative in ['share/kicad/resources','share/kicad/schemas','share/kicad/fonts','share/licenses','licenses','LICENSES']:
        path=source/relative
        if path.is_dir() and not (output/relative).exists():shutil.copytree(path,output/relative)
    # Preserve standalone upstream license notices without copying large docs.
    for directory,dirs,files in os.walk(source):
        dirs[:]=[name for name in dirs if name.lower() not in {'3dmodels','symbols','footprints','site-packages','internat','help','__pycache__'}]
        for name in files:
            if not re.match(r'^(licen[cs]e|copying|copyright|notice)([._-].*)?$',name,re.I):continue
            path=Path(directory)/name
            if path.stat().st_size>2*1024*1024:continue
            relative=path.relative_to(source);destination=output/relative;destination.parent.mkdir(parents=True,exist_ok=True)
            if not destination.exists():shutil.copy2(path,destination)
    license_dir=output/'licenses';license_dir.mkdir(exist_ok=True)
    shutil.copy2(ROOT/'licenses'/'GPL-3.0.txt',license_dir/'KiCad-GPL-3.0.txt')
    validation=self_test(output,sample)
    manifest=dict(component='KiCad PCB export runtime',version=validation['version'],architecture='x86_64',
                  source='Official KiCad 10.0.0 Windows x64 distribution',
                  included=['kicad-cli.exe','PCB and schematic kifaces','native DLLs','small resources, schemas and fonts','upstream license notices'],
                  excluded=['GUI editor EXEs','Python packages','3D model library','footprint and symbol libraries','help and translations'],
                  binaries=records,validation=validation)
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    summary=dict(output=str(output),version=validation['version'],native_files=len(records),bytes=sum(p.stat().st_size for p in output.rglob('*') if p.is_file()),validation=validation)
    print(json.dumps(summary,indent=2),flush=True)
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,help='Installed or 7-Zip-extracted KiCad root (default: KICAD_INSTALL_ROOT or Program Files/KiCad/10.0)')
    parser.add_argument('--output',type=Path,default=DEFAULT_OUTPUT)
    parser.add_argument('--sample',type=Path,default=ROOT/'examples'/'two-layer-demo.kicad_pcb')
    args=parser.parse_args();build(args.source,args.output,args.sample)
