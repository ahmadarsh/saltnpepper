#!/usr/bin/env python3
"""Create and verify a standard drag-to-Applications DMG without mounting it."""
import argparse
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tempfile


def create(app, output, version=None):
    if sys.platform != 'darwin':
        raise ValueError('Create the Mac disk image on macOS.')
    app = Path(app).expanduser().resolve()
    output = Path(output).expanduser().resolve()
    info = app / 'Contents' / 'Info.plist'
    if app.suffix != '.app' or not info.is_file():
        raise ValueError('--app must point to a built, signed .app bundle.')
    if output.suffix.lower() != '.dmg' or app in output.parents:
        raise ValueError('--output must be a .dmg path outside the app bundle.')
    if version is None:
        with info.open('rb') as stream:
            version = plistlib.load(stream).get('CFBundleShortVersionString')
    if not isinstance(version, str) or not re.fullmatch(r'[0-9A-Za-z][0-9A-Za-z._+-]{0,47}', version):
        raise ValueError('Specify a valid --version or provide CFBundleShortVersionString in Info.plist.')
    # Copy the signed bundle unchanged. No Finder session or temporary mounted
    # interstitial disk is needed to produce a standard Applications shortcut.
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='salt-pepper-dmg-', dir=output.parent) as temporary:
        root = Path(temporary)
        staging = root / 'contents'
        staging.mkdir()
        subprocess.run(['/usr/bin/ditto', str(app), str(staging / app.name)], check=True)
        (staging / 'Applications').symlink_to('/Applications', target_is_directory=True)
        image = root / 'candidate.dmg'
        subprocess.run([
            '/usr/bin/hdiutil', 'create', '-volname', 'Salt and Pepper ' + version,
            '-srcfolder', str(staging), '-fs', 'HFS+', '-format', 'UDZO', '-ov', str(image)
        ], check=True)
        subprocess.run(['/usr/bin/hdiutil', 'verify', str(image)], check=True)
        os.replace(image, output)
    print('Verified DMG: ' + str(output), flush=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True, help='Built signed .app bundle')
    parser.add_argument('--output', type=Path, required=True, help='Destination .dmg file')
    parser.add_argument('--version', help='Volume version; defaults to the app Info.plist version')
    args = parser.parse_args()
    try:
        create(args.app, args.output, args.version)
    except (OSError, ValueError, plistlib.InvalidFileException, subprocess.CalledProcessError) as exc:
        parser.exit(1, 'Could not create DMG: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
