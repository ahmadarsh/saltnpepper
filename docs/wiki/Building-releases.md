# Building releases

## Mac arm64

Install Xcode command line tools, Rust stable, Node 22 and Python 3.11. Create the source virtual environment, then:

```sh
.venv/bin/python -m pip install -r requirements.txt -r desktop/requirements-build.txt
zsh "desktop/Build Mac App.command"
.venv/bin/python desktop/smoke_test.py desktop/backend-dist/salt-pepper-backend
.venv/bin/python tools/prepare_release.py
```

Output: dist/Salt and Pepper.app, dist/Salt and Pepper Mac.zip, a DMG in dist/, and release/ source archive and checksums. The current Mac target requires macOS 14+ and builds for the host architecture; the CI Mac target is arm64. Intel Mac is not an advertised release target.

## Windows x64

Use a Windows x64 computer or GitHub Windows runner, Python 3.11 x64, Node 22, Rust stable MSVC and Visual Studio 2022 Build Tools with Desktop development with C++. WebView2 must be available. See <https://v2.tauri.app/start/prerequisites/>.

```powershell
& "desktop/Build Windows App.ps1"
```

This installs native Python dependencies, freezes the backend, runs its end-to-end simulation test, and builds an NSIS installer in dist/windows. No cross-compilation of the Mac Python binary is attempted. See <https://v2.tauri.app/distribute/windows-installer/>.

## GitHub preparation

The repository is <https://github.com/ahmadarsh/saltnpepper>. Clone it to build from source; the source ZIP also contains the clean repository content. Run **Build release candidates** in Actions or push a `v0.5.0` tag. The workflow uploads Mac and Windows artifacts; it does not publish a public release automatically. The attachment workflows can copy the verified Windows installer and create a Mac DMG from a successful build run into an existing draft release. Download artifacts, complete GUI validation on both operating systems, then attach installers/ZIPs, matching source, dependency sources and checksums to the GitHub release.

Run `python tools/fetch_dependency_sources.py` before redistribution to collect copyleft dependency sources. Keep licence notices with binaries. Do not upload the original workspace, backups, data, old designs or environment directories.

The `docs/wiki` folder is ready for review. The GitHub wiki is <https://github.com/ahmadarsh/saltnpepper/wiki>. It uses the separate `https://github.com/ahmadarsh/saltnpepper.wiki.git` repository. Enable and initialise the wiki in GitHub before pushing pages; `release/wiki` contains the prepared wiki pages. The pages in `docs/wiki` remain available in the main repository too.

The initial V0.5 native Mac and Windows builds passed: [build run](https://github.com/ahmadarsh/saltnpepper/actions/runs/41480370531). This verifies native packaging and backend tests; manual installation and native-window GUI checks remain separate.
