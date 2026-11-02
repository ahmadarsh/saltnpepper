"""Collect versioned copyleft dependency sources beside release assets."""
import hashlib
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
SOURCES = {
    'gmsh-4.15.2-source.tgz': 'https://gmsh.info/src/gmsh-4.15.2-source.tgz',
    'opencascade-7.8.1.tar.gz': 'https://github.com/Open-Cascade-SAS/OCCT/archive/refs/tags/V7_8_1.tar.gz',
}

def main():
    target = ROOT / 'release' / 'dependency-sources'
    target.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, url in SOURCES.items():
        path = target / name
        if not path.exists():
            temporary = path.with_suffix('.download')
            with urllib.request.urlopen(url, timeout=90) as response, temporary.open('wb') as out:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk: break
                    out.write(chunk)
            temporary.replace(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(f'{digest}  {name}')
        print(name, path.stat().st_size, flush=True)
    (target / 'SHA256SUMS.txt').write_text('\n'.join(rows) + '\n')
    (target / 'README.md').write_text('# Dependency sources\n\nVersioned upstream source archives for Gmsh 4.15.2 and OpenCASCADE 7.8.1 used by the tested Mac Gmsh SDK. Keep their licence notices. The platform build manifest records Gmsh BuildInfo; verify dependency versions for each platform. Other third-party source links and licences are in THIRD_PARTY_NOTICES.md and desktop/licenses.\n')

if __name__ == '__main__': main()
