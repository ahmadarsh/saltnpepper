"""Assemble an allowlisted public source tree, app assets, wiki and checksums.

Private workspace data and backups are never traversed. Does not publish anything.
"""
import hashlib
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parent.parent
VERSION = '0.5.0'
RELEASE = ROOT / 'release'
FILES = ['README.md','LICENSE','THIRD_PARTY_NOTICES.md','CONTRIBUTING.md','CHANGELOG.md','START_HERE.txt','requirements.txt','.gitignore',
         'simulation/solve_3v3_thermal.py','simulation/test_generic_engine.py',
         'desktop/package.json','desktop/package-lock.json','desktop/backend_entry.py','desktop/build_backend.py',
         'desktop/smoke_test.py','desktop/requirements-build.txt','desktop/requirements-macos-py39.lock.txt',
         'desktop/Build Mac App.command','desktop/Build Windows App.ps1','desktop/README.md','desktop/icon.svg',
         'desktop/src-tauri/Cargo.toml','desktop/src-tauri/Cargo.lock','desktop/src-tauri/build.rs',
         'desktop/src-tauri/tauri.conf.json','desktop/src-tauri/tauri.windows.conf.json',
         'pcb_simulator/server.py','pcb_simulator/engine.py','pcb_simulator/worker.py','pcb_simulator/results.py',
         'pcb_simulator/test_server.py','pcb_simulator/test_backend.py','pcb_simulator/README.md',
         'pcb_simulator/Setup Salt and Pepper.command','pcb_simulator/Start Salt and Pepper.command','pcb_simulator/Stop Salt and Pepper.command',
         'pcb_simulator/Setup Salt and Pepper.cmd','pcb_simulator/Start Salt and Pepper.cmd','pcb_simulator/Stop Salt and Pepper.cmd',
         'pcb_simulator/viewer/viewer.template.html','pcb_simulator/viewer/test_results.py','pcb_simulator/viewer/check_browser.py']
FOLDERS = ['examples','docs','licenses','tools','.github','pcb_simulator/static','desktop/src-tauri/src','desktop/src-tauri/icons','desktop/shell','desktop/licenses']

def main():
    RELEASE.mkdir(exist_ok=True)
    source = RELEASE / 'source' / f'Salt-and-Pepper-{VERSION}'
    if source.exists(): shutil.rmtree(source)
    source.mkdir(parents=True)
    paths = set(ROOT / name for name in FILES)
    for folder in FOLDERS:
        paths.update(p for p in (ROOT / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name != '.DS_Store')
    for path in sorted(paths):
        destination = source / path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    archive = RELEASE / f'Salt-and-Pepper-{VERSION}-source.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, strict_timestamps=False) as z:
        for path in sorted(source.rglob('*')):
            if path.is_file(): z.write(path, path.relative_to(source.parent))
    mac = RELEASE / 'macos'; mac.mkdir(exist_ok=True)
    built = ROOT / 'dist' / 'Salt and Pepper Mac.zip'
    if built.exists(): shutil.copy2(built, mac / f'Salt-and-Pepper-{VERSION}-macOS-arm64.zip')
    for dmg in (ROOT / 'dist').glob('*.dmg'): shutil.copy2(dmg, mac / dmg.name)
    windows = RELEASE / 'windows'; windows.mkdir(exist_ok=True)
    shutil.copy2(archive, windows / f'Salt-and-Pepper-{VERSION}-Windows-source.zip')
    installers = list((ROOT / 'dist' / 'windows').glob('*-setup.exe'))
    for installer in installers: shutil.copy2(installer, windows / installer.name)
    if not installers:
        (windows/'BUILD-PENDING.md').write_text('# Windows x64\n\nNative build scripts and GitHub Actions are prepared. A Windows installer has not been built or tested on this Mac. Run the Windows workflow or desktop/Build Windows App.ps1 on Windows, then perform GUI validation. The Windows-source ZIP includes the Setup/Start .cmd launchers and native build scripts; no Windows binary is claimed in this candidate.\n')
    wiki = RELEASE / 'wiki'
    shutil.copytree(ROOT/'docs/wiki', wiki, dirs_exist_ok=True)
    for page in wiki.glob('*.md'):
        page.write_text(page.read_text().replace('.md)', ')'))
    (RELEASE/'RELEASE_NOTES.md').write_text((ROOT/'CHANGELOG.md').read_text())
    rows=[]
    assets=[archive]+list(mac.glob('*.zip'))+list(mac.glob('*.dmg'))+list(windows.glob('*.exe'))+list(windows.glob('*.zip'))+list((RELEASE/'dependency-sources').glob('*.tgz'))+list((RELEASE/'dependency-sources').glob('*.tar.gz'))
    for path in sorted(assets):
        rows.append(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+path.relative_to(RELEASE).as_posix())
    (RELEASE/'SHA256SUMS.txt').write_text('\n'.join(rows)+'\n')
    (RELEASE/'README.md').write_text('''# Salt and Pepper V0.5 release candidate

- `source/` and `Salt-and-Pepper-0.5.0-source.zip`: clean public repository content.
- `macos/`: Apple Silicon app ZIP, macOS 14+; ad hoc signed, not notarized.
- `windows/`: Windows x64 installer when built on Windows, otherwise an explicit build-pending notice.
- `wiki/`: setup and usage pages for the separate GitHub wiki repository.
- `dependency-sources/`: versioned Gmsh/OpenCASCADE sources collected separately.
- `SHA256SUMS.txt`: hashes for the release archives.
- `VALIDATION.md`: measured checks and remaining platform validation.

Nothing has been published to GitHub. Private models, saved runs, backups and environments are excluded from the source archive. Software is GPL-3.0-or-later; documentation, original artwork and sample geometry are CC BY 4.0. Keep third-party notices and corresponding dependency sources with public releases.
''')
    (RELEASE/'SOURCE_FILES.txt').write_text('\n'.join(p.relative_to(ROOT).as_posix() for p in sorted(paths))+'\n')
    print(f'Prepared {len(paths)} source files; {archive.stat().st_size:,} byte source ZIP')

if __name__ == '__main__': main()
