# Salt and Pepper — V0.9.2

A local PCB power-integrity workbench. Import KiCad boards or STEP copper geometry, assign input/output pads, and explore steady-state voltage drop, current density, Joule generation and optional temperature in a 3D results viewer.

This branch contains software source, build/test files and required license notices. It excludes private boards, workspaces, simulation history, recordings, wiki pages, screenshots, installers, bundled third-party runtimes and build caches. The public release assets may describe an older version; this branch does not publish a release.

## Features

- Native KiCad import with real net names and pad identities, colour-matched net lists and top/bottom copper selection. Companion `.kicad_pro` files can provide custom net colours.
- Click pads to assign red inputs and blue outputs; inspect copper/dielectric stackup thickness in mm and mils.
- Prepare selected-net 3D copper, including inner layers and vias, into the existing Setup workbench. Through-hole pad pieces retain one terminal identity.
- Custom copper-layer names are mapped using exported layer types and physical stack order.
- Electrical-only or approximate copper electrothermal FEM, optional finer-mesh comparison, per-pad current reporting and offline interactive results.
- Portable `.pepper` workspaces retain boards, geometry, completed simulations, settings and view state. Startup is always clean: choose New or Open.
- Mac desktop native Open/Save/Save As: opening remembers the exact file; Save updates it atomically. Save As switches subsequent saves to the new destination. Browser sessions download snapshots. Windows implementation is prepared but native Windows verification remains pending.

## Requirements and source setup

Use 64-bit Python 3.11 for a new development environment. A supported native Gmsh wheel and KiCad 10 CLI are needed for CAD/board import. The Mac candidate bundles KiCad 10.0.0; failure reported on one KiCad 10.0.6 board remains uninvestigated, so compatibility with that board is not claimed.

On macOS (Apple Silicon, macOS 14+):

```sh
python3 -m venv .venv
.venv/bin/python3 -m pip install -r requirements.txt
.venv/bin/python3 pcb_simulator/server.py
```

On Windows 10/11 x64:

```powershell
py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe pcb_simulator\server.py
```

Open the localhost URL printed by the server. The native desktop shell starts the backend automatically; ordinary browser sessions use the browser workspace-download fallback. Runtime data is local and ignored by Git. Stop a source server with `server.py --stop` using the same `--data-dir` if you supplied one.

For source KiCad import, install the official KiCad distribution. The app checks an explicit `SALT_PEPPER_KICAD_CLI`, PATH, then standard platform locations. Do not point to an unrelated or untrusted executable. No external KiCad/Python/Rust installation is required for users of a correctly bundled desktop package.

## First simulation

1. Choose **New workspace**, then **Load example model** for the generic copper bar. Click **Use example ports**.
2. Choose **Electrical only**, current **0.1 A**, ambient **20 °C**, mesh **0.8 mm** and turn **Compare finer mesh** off under Advanced.
3. Run and inspect the result. The 1 × 1 × 10 mm bar at conductivity 58 MS/m should measure approximately **0.172414 mΩ**.
4. For a PCB, choose **KiCad import**, import your `.kicad_pcb` and optional `.kicad_pro`, select a net, assign input/output pads on the top/bottom views, and choose **Prepare selected copper**.
5. Inspect geometry and operating conditions before solving. Save a `.pepper` workspace to retain completed runs and continue later.

The small original `examples/two-layer-demo.kicad_pcb` is a redistributable import fixture: net `DEMO_POWER`, input `J1.1`, output `J2.1`. Personal USB-UART projects are not included in this source branch. The optional build argument for a private example ZIP is intended only for local packaging.

Start a mesh sensitivity study around 0.5 → 0.3 → 0.18 mm, scaled to the geometry. The setting is a maximum size, not a uniform tetrahedron dimension. Check through-thickness/local-feature resolution and compare relevant results; a 35 µm copper layer does not automatically require a global 0.035 mm mesh. Two meshes alone do not prove convergence, and sharp-corner maxima can remain mesh-dependent.

## How the solver works

KiCad CLI exports copper/connectivity; Gmsh and OpenCASCADE prepare exact 3D copper and conformal first-order tetrahedra. Custom FEM assembles steady conduction equations; SciPy SuperLU solves sparse systems on the CPU. A unit electrode difference determines conductance, and fields scale to the requested **total current**. All inputs share one potential and all outputs another; independent per-pad loads are not implemented. Geometry and conductivity determine current sharing.

Optional electrothermal analysis calculates Joule generation and copper heat conduction with approximate convection, updating temperature-dependent conductivity until convergence. It excludes FR4, solder mask, components, radiation and realistic terminal heat sinking. The displayed stackup does not mean those materials are thermally solved. Numerical checks include current balance, residuals and power balance; these do not certify physical accuracy. GPU acceleration, transient heating, signal-integrity and full EM analysis are not implemented.

One worker runs at a time. Runtime includes queue wait, worker startup, CAD, meshing, numerical solving and viewer generation. Compare those stages before attributing a delay to the solver. The smooth CAD preview is separate from the FEM mesh.

## Build the Mac app

Install Rust stable, Node/npm, Xcode Command Line Tools, Python build dependencies and the official KiCad app at `/Applications/KiCad/KiCad.app`. Match the existing arm64/macOS 14+ target. Then:

```sh
.venv/bin/python3 -m pip install -r desktop/requirements-build.txt
zsh 'desktop/Build Mac App.command'
```

Outputs: `dist/Salt and Pepper.app`, the Mac app ZIP and `dist/Salt-and-Pepper-0.9.2-macOS-arm64.dmg`. The build collects dependency licenses, bundles the KiCad CLI/runtime, compiles an AppKit file-panel helper and packages the backend and Tauri window. It is ad hoc signed; notarization and distribution signing are not configured.

Optional private example packaging: pass `--example-project /path/to/USB-UART.zip`. Never commit that board or generated package automatically.

## Build the Windows installer

Run natively on Windows x64 with Python 3.11 x64, Node/npm, Rust stable MSVC, Visual Studio 2022 C++ Build Tools/Windows SDK and WebView2. Install official **KiCad 10.0.0 x64** on the build machine: the Windows runtime bundler currently validates that exact version.

```powershell
& '.\desktop\Build Windows App.ps1' -KiCadRoot 'C:\Program Files\KiCad\10.0'
```

The default build uses the generic demo; a private board ZIP is optional via `-ExampleProject`. Output is `dist/windows/*-setup.exe` plus SHA-256. No Windows binary or native-dialog verification is claimed from a Mac build. Installers are unsigned; WebView2 bootstrap may require internet.

## Verification before distributing

```sh
.venv/bin/python3 -m unittest discover -s pcb_simulator -p 'test_*.py'
.venv/bin/python3 simulation/test_generic_engine.py
node tools/check_windows_workspace_ui.cjs
```

On Windows, substitute `.venv\Scripts\python.exe`. These cover solver correctness, units, connectivity, plated-pad grouping, import metadata, custom layers, archives, atomic writes and controller routing. Native chooser tests are mocked in unit tests; test actual desktop panels separately. Mac helper protocol tests are portable, but the AppKit executable requires a Mac build.

On each actual installed platform verify:

- Clean New/Open startup, KiCad/STEP import and unchanged operating settings after geometry handoff.
- Input/output names and colours, stackup, electrical/thermal fields and multiple completed runs on one board.
- First Save chooses a folder/name. Open → change → Save updates the exact opened file with no duplicate snapshot.
- Save As to another folder/Unicode filename preserves the original; later Save updates the new file only.
- Cancel/declined overwrite/write failure preserve the previous file and unsaved state; New/Clear forgets the association.
- Reopen retains settings and all completed runs. A corrupt archive fails without destroying the current workspace.
- Bundled KiCad works without developer PATH dependencies; Quit leaves no backend/worker process. Validate installer hashes and retain required notices.

`desktop/verify_macos_workspace_dialogs.py` and `desktop/verify_windows_workspace_dialogs.py` are optional interactive checks using disposable archives. They are not a substitute for the installed-app workflow.

## Source layout

```text
pcb_simulator/  Local server, CAD/import pipeline, GUI, viewers and regression tests
simulation/     FEM solver and analytical tests
examples/       Small generic demo geometry and generator
 desktop/       Tauri shell, native dialogs and platform packaging
licenses/       Project license texts
tools/          Build/license and test helpers
```

## Roadmap

| Version | Scope | Status |
| --- | --- | --- |
| V0.5 | STEP copper simulation | Previously released |
| V0.9.2 | KiCad import, real identities, workspaces and GUI refinements | Mac testing candidate |
| V1 | Expanded multi-input/multi-output PI workflow | In update |
| V1.2 | GPU acceleration | Yet to start |
| V1.5 | Basic SI | Yet to start |
| V2 | EM simulation | Yet to start |

Multiple selected pads already share common input/output potentials; V1 expands that workflow. Roadmap items are plans, not availability promises.

## License

Copyright 2026 Arsh Ahmad and contributors. Software: **GPL-3.0-or-later**. Original documentation/artwork/sample geometry: **CC BY 4.0**; generator code remains GPL. See `LICENSE`, `licenses/` and `THIRD_PARTY_NOTICES.md`. Third-party components retain their own licenses. Required notices are retained even though other documentation and media are excluded from this branch.
