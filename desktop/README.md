# Desktop packaging

Salt and Pepper 0.5.0 uses a Rust/Tauri window with a bundled native Python CAD/FEM backend. HTML/CSS/WebGL provides the existing interface. The backend is local-only, starts on a free port and stops with the main window. It runs workers in isolated processes.

See [build instructions](../docs/wiki/Building-releases.md), [setup](../docs/wiki/Setup.md) and [licences](../THIRD_PARTY_NOTICES.md). Mac arm64 and Windows x64 require native builds on their respective operating systems. `Build Mac App.command` creates the .app and ZIP. `Build Windows App.ps1` creates the NSIS installer and tests its frozen backend.

The app bundles no user runs or private models. It contains only the original sample copper bar. Packaged data is stored in the platform application-data directory. Back up data while the app is stopped.

The backend smoke test performs a real STEP import and electrothermal FEM solve with an analytical resistance check. Rust lifecycle tests verify start/stop. GUI deletion checks are in `tools/check_workbench.py`. macOS builds are ad hoc signed; Windows candidates are unsigned. Public notarization and code signing require publisher credentials.
