# Troubleshooting

**Delete does nothing:** use version 0.5.0 and confirm using the in-app Delete dialog. Old desktop bundles include the old frontend: updating source files does not update an installed .app. Replace the installed app and restart it. Active imports/runs cannot be deleted; wait or cancel first. A file permission/lock error is shown in the toast. Close external programs holding saved artifacts open on Windows.

**Two solves:** finer mesh comparison is enabled. Disable it for one mesh solve per run.

**Import or solver error:** inspect Jobs and the saved worker log. Check STEP units, touching geometry and terminal assignments. Start with the sample bar before a complex PCB.

**Slow run or out of memory:** use a coarser mesh and disable finer comparison, then refine deliberately. Large tetrahedral models can use significant RAM.

**Port busy:** source server defaults to 8765. Stop the existing server or launch `server.py --port 8766`. Packaged apps choose a free port automatically. They store data separately from the source server.

**Windows missing Gmsh DLL:** recreate the virtual environment on Windows using x64 Python. Do not use the legacy .python_deps folder or a Mac frozen backend.

**Desktop startup fails:** inspect the logs beside the application data directory described in Setup. Report OS version, app version, error text and a small shareable geometry; keep private design files out of public issues.
