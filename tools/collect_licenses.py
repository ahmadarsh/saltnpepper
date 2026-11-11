"""Capture dependency notices and exact native Python versions before freezing."""
from importlib import metadata
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent.parent

def main():
    target = ROOT / 'desktop' / 'licenses'
    target.mkdir(parents=True,exist_ok=True)
    for name in ['LICENSE', 'THIRD_PARTY_NOTICES.md', 'licenses/GPL-3.0.txt', 'licenses/CC-BY-4.0.txt']:
        shutil.copy2(ROOT / name, target / Path(name).name)
    lines = [f'Python {sys.version}']
    for name in ['numpy', 'scipy', 'gmsh', 'pyinstaller', 'pyinstaller-hooks-contrib', 'altgraph', 'macholib']:
        try: dist = metadata.distribution(name)
        except metadata.PackageNotFoundError: continue
        lines.append(f'{dist.metadata["Name"]}=={dist.version}')
        for entry in dist.files or []:
            if any(word in entry.name.upper() for word in ('LICENSE', 'COPYING', 'NOTICE')):
                source = Path(dist.locate_file(entry))
                if source.is_file():
                    destination = target / 'python' / name / Path(str(entry).replace('..', '_'))
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
    (target / 'python-packages.txt').write_text('\n'.join(lines) + '\n')
    import gmsh
    gmsh.initialize()
    try: (target / 'gmsh-build-info.txt').write_text(gmsh.option.getString('General.BuildInfo') + '\n')
    finally: gmsh.finalize()
    # Registry package notices, including Wry/Tao and transitive Rust crates.
    import os
    cargo = Path(os.environ.get('CARGO_HOME', Path.home() / '.cargo'))
    if not cargo.exists(): cargo = ROOT / '.build-tools' / 'cargo'
    for registry in (cargo / 'registry' / 'src').glob('*'):
        for package in registry.iterdir():
            for source in package.glob('*'):
                if source.is_file() and source.name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE')):
                    destination = target / 'rust' / package.name / source.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)

if __name__ == '__main__': main()
