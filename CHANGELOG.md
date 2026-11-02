# Changelog

## 0.5.0 — release candidate

- Replace native browser deletion prompts with an accessible in-app confirmation dialog for embedded desktop windows. Cancel/Escape keep files; Delete removes the item and updates the lists.
- Report filesystem deletion failures to the user.
- Add persistent Mint, Cyan, Violet, Rose and Amber GUI accents, preserving red inputs, blue outputs, white Salt canvases and black Pepper canvases.
- Replace the private PCB example with an original labelled copper bar and regeneration script.
- Add Windows x64 backend packaging, NSIS installer configuration, source setup launchers and native build workflow.
- Fix Windows parent-process monitoring and hide backend console windows.
- Add clean source release assembly, checksums, licence notices, setup documentation and GitHub wiki pages.

Mac and Windows native builds and automated tests passed in GitHub Actions. See [release validation](docs/Release-validation.md). Manual native-window GUI validation remains pending.
