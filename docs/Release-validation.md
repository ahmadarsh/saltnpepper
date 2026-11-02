# V0.5 release validation

Both native GitHub build jobs passed: [Mac arm64 and Windows x64 workflow](https://github.com/ahmadarsh/saltnpepper/actions/runs/41480370531).

| Platform / check | Result |
| --- | --- |
| Mac arm64 native packaging | Passed; macOS 14 minimum |
| Mac DMG | Created from the passing CI build; app signature and disk-image integrity verified |
| Mac frozen backend | Real STEP import, electrothermal solve, analytical resistance and shutdown passed |
| Mac regression suite | 17 tests passed |
| Windows x64 native packaging | NSIS installer built successfully on Windows Server 2022 |
| Windows frozen backend | Real STEP import, electrothermal solve, analytical resistance and shutdown passed |
| Windows Rust backend lifecycle | Startup, health check and graceful shutdown passed |
| Windows regression suite | 17 tests passed |
| Local browser GUI | Confirm/cancel/Escape deletion, retained results after model deletion, all five accents and sample pad assignment passed |
| Public example | Copper bar resistance and thermal benchmarks passed; private designs excluded |

The release is a V0.5 prerelease. The Mac app is ad hoc signed and not notarized; the Windows installer has no publisher signature configured. Manual installation and visual checks inside the Mac Tauri window and Windows WebView2 window remain separate from the automated backend/browser checks. No such manual native GUI checks are claimed here.

The source tag is `v0.5.0`. Documentation can receive later updates on main and in the wiki; the documentation ZIP accompanies the release. Keep the project/dependency sources and licence notices when redistributing.
