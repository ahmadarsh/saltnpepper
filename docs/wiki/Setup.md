# Setup

## Packaged application

**Mac:** Apple Silicon, macOS 14+. Download the Mac DMG from the [V0.5 release](https://github.com/ahmadarsh/saltnpepper/releases/tag/v0.5.0), open it, and drag Salt and Pepper.app onto the Applications shortcut. Open the app from Applications. A ZIP is also available. This candidate is ad hoc signed and not notarized. If macOS blocks a downloaded build you trust, use System Settings → Privacy & Security → Open Anyway. No global Python installation is needed.

**Windows:** Windows 10/11 x64. Run the NSIS `-setup.exe`. WebView2 is required and the installer downloads its bootstrapper if needed, so first installation can need internet. The unsigned candidate may show SmartScreen publisher warnings; check the release checksum and source before choosing to run it. Windows binary availability and validation are recorded on each release.

## Source setup (Mac)

Install Python 3.11 (64-bit recommended). From the project root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python pcb_simulator/server.py
```

Or use Setup Salt and Pepper.command, then Start Salt and Pepper.command in pcb_simulator. Open the printed local URL. Stop with the matching Stop launcher or Ctrl+C in the server terminal.

## Source setup (Windows PowerShell)

Install Python 3.11 x64 from python.org. Open PowerShell in the project root:

```powershell
py -3 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe pcb_simulator/server.py
```

Alternatively use Setup Salt and Pepper.cmd, then Start Salt and Pepper.cmd. Stop using Stop Salt and Pepper.cmd or Ctrl+C. Do not copy a Mac virtual environment to Windows: native Gmsh, NumPy and SciPy must be installed on the target OS.

## Storage

Source: `pcb_simulator/data`. Mac app: `~/Library/Application Support/com.arshahmad.salt-and-pepper/data`. Windows app: `%APPDATA%\com.arshahmad.salt-and-pepper\data`. Logs sit beside the packaged data directory. Closing the main desktop window stops its backend; a browser-based source server stays running until stopped.

Saved data is not included in public source releases. Back it up while the app is closed. Use the delete buttons to remove old geometry or results; deleting geometry retains completed result files.
