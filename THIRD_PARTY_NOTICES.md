# Third-party notices

The application bundles native dependencies; the project licence does not replace their licences. Retain this file and desktop/licenses when redistributing binaries.

| Component | Licence / source |
| --- | --- |
| KiCad 10.0.0 PCB export runtime (Mac V0.9) | GPL-3.0-or-later; [matching source](https://gitlab.com/kicad/code/kicad/-/tree/10.0.0), bundled upstream notices under `Contents/Resources/kicad/Contents/Resources/Licenses`; dependency manifest in `kicad/manifest.json` |
| Gmsh 4.15.2 | GPL-2.0-or-later with library-linking exception; [source archive](https://gmsh.info/src/gmsh-4.15.2-source.tgz), desktop/licenses/Gmsh-LICENSE.txt |
| OpenCASCADE, used by Gmsh | LGPL-2.1 with additional exception; [upstream](https://dev.opencascade.org/resources/licensing), release-specific source/build information in Gmsh |
| NumPy | BSD; [source](https://github.com/numpy/numpy), included package notices |
| SciPy, bundled BLAS/LAPACK/SuperLU | BSD and included component notices; [source](https://github.com/scipy/scipy) |
| CPython | PSF licence; [source](https://www.python.org/downloads/source/) |
| PyInstaller | GPL with bootloader exception; [source](https://github.com/pyinstaller/pyinstaller) |
| Tauri / Wry / Tao | MIT or Apache-2.0; [source](https://github.com/tauri-apps/tauri) |
| Rust dependencies | See Cargo.lock and upstream package metadata; [registry](https://crates.io/) |

The native binary's exact installed Python versions are captured in `desktop/licenses/python-packages.txt` during each build. Rust versions are pinned by Cargo.lock, JavaScript tooling by package-lock.json. For redistribution, accompany the app with this project source and the corresponding upstream source and notices for copyleft components. Build scripts are provided. `tools/fetch_dependency_sources.py` collects the Gmsh and OpenCASCADE source archives for the release folder; these archives are separate from user geometry.
