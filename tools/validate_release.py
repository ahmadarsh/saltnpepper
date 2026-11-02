"""Check local release archives, expected public content and source syntax."""
import ast
import hashlib
from pathlib import Path
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT/'release'

def main():
    source = RELEASE/'source'/'Salt-and-Pepper-0.5.0'
    assert source.is_dir()
    private_design = '3V3' + '_NET.step'
    for path in source.rglob('*'):
        if not path.is_file(): continue
        relative=path.relative_to(source)
        assert not {'backups', 'data', '.venv', '.python_deps', 'node_modules', 'target', '__pycache__'} & set(relative.parts), relative
        assert path.name != private_design
        if path.suffix == '.py': ast.parse(path.read_text(encoding='utf-8'),filename=str(relative))
        if path.suffix in ('.py','.md','.txt','.json','.toml','.html','.js','.css','.command','.ps1','.yml'):
            assert '/Users/'+'arshahmad/' not in path.read_text(encoding='utf-8'), relative
    assert sorted(p.relative_to(source).as_posix() for p in source.rglob('*.step')) == ['examples/copper-bar.step']
    for archive in [*RELEASE.glob('*.zip'),*(RELEASE/'macos').glob('*.zip')]:
        with zipfile.ZipFile(archive) as z: assert z.testzip() is None, archive
    for path in (RELEASE/'dependency-sources').glob('*'):
        if path.name.endswith(('.tgz','.tar.gz')):
            with tarfile.open(path) as archive: assert len(archive.getmembers()) > 10, path
    for row in (RELEASE/'SHA256SUMS.txt').read_text().splitlines():
        digest,name=row.split('  ',1)
        assert hashlib.sha256((RELEASE/name).read_bytes()).hexdigest()==digest, name
    print('PASS: clean public source, Python syntax, single public STEP model, archive integrity and SHA256 checksums')

if __name__=='__main__': main()
